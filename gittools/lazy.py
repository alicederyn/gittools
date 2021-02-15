import threading, weakref
from collections import deque
from functools import update_wrapper
from inspect import getcallargs
from weakref import WeakKeyDictionary, WeakSet

__all__ = ['lazy', 'lazy_invalidation']

def lazy(object = None, listener = None):
  if object is None:
    assert listener is not None
    return lambda object : lazy(object, listener)
  if isinstance(object, type) or str(type(object)) == "<type 'classobj'>":
    return update_wrapper(LazyFunction(object(), listener), object)
  elif hasattr(object, '__call__'):
    return update_wrapper(LazyFunction(object, listener), object)
  elif hasattr(object, '__get__'):
    lazy_property = LazyProperty(object)
    if hasattr(object, 'fget'):
      update_wrapper(lazy_property, object.fget)
    return lazy_property
  else:
    raise ValueError()

def lazy_invalidation():
  return LazyInvalidation()

class LazyConstants(object):
  def __init__(self):
    self._watchable_objects = WeakSet()

  def _watch_object(self, object):
    if object.watcher is not None:
      self._watchable_objects.add(object)

  def _add_dependency(self, object):
    pass

  def _unwatch_object(self, object):
    pass

  def _invalidate_all(self):
    for watchable_object in self._watchable_objects:
      watchable_object.invalidate()
      watchable_object.inited = False
    self._watchable_objects.clear()

class WeakWatchIntermediary(object):
  def __init__(self, result, watcher):
    self.watcher = watcher
    self.result = weakref.ref(result, self.release)
    watcher.watch(self)

  def __call__(self):
    try:
      self.result().invalidate()
    except TypeError:
      pass

  def release(self, weakref = None):
    watcher = self.__dict__.pop('watcher', None)  # Atomic
    try:
      watcher.unwatch()
    except (AttributeError, TypeError):
      pass
    try:
      result = self.result()
      result.invalidate()
      result.inited = False
    except (AttributeError, TypeError):
      pass
    self.result = None

class LazyInvalidation(object):
  def __enter__(self):
    assert threading.current_thread() == MAIN_THREAD
    assert not evaluation_stack
    self._watchMap = WeakKeyDictionary()
    self._watchable_objects = WeakSet()
    global invalidation_strategy
    invalidation_strategy._invalidate_all()
    invalidation_strategy = self

  def _watch_object(self, object):
    if object.watcher is not None and object.watcher not in self._watchMap:
      self._watchMap[object.watcher] = WeakWatchIntermediary(object, object.watcher)

  def _add_dependency(self, object):
    if evaluation_stack:
      evaluation_stack[-1].deps.append(object)

  def _unwatch_object(self, object):
    object.invalidate()
    self._watchable_objects.discard(object)

  def __exit__(self, type, value, traceback):
    global invalidation_strategy
    invalidation_strategy = LazyConstants()
    for intermediary in self._watchMap.values():
      intermediary.release()
    self._watchMap.clear()

  def _invalidate_all(self):
    raise TypeError('Cannot nest lazy_invalidation contexts')

class LazyEvaluationContext(object):
  def __init__(self, lazyObject):
    self.lazyObject = lazyObject

  def __enter__(self):
    assert threading.current_thread() == MAIN_THREAD
    invalidation_strategy._add_dependency(self)
    evaluation_stack.append(self.lazyObject)
    self.lazyObject.deps = []
    return self

  def __exit__(self, type, value, traceback):
    evaluation_stack.pop()
    self.lazyObject.deps = frozenset(self.lazyObject.deps)
    if not evaluation_stack:
      while invalidation_queue:
        invalidation_queue.pop().invalidate()

class LazyResult(object):
  inited = False
  deps = None  # Stores hard references to upstream dependencies for invalidation purposes

  def __init__(self, watcher = None):
    self.watcher = watcher

  def invalidate(self):
    if not hasattr(self, '_value'):
      return
    if threading.current_thread() != MAIN_THREAD or evaluation_stack:
      invalidation_queue.append(self)
      invalidation_event.set()
      return
    del self._value
    self.deps = None
    try:
      refs = tuple(self._refs)
    except AttributeError:
      return
    self._refs.clear()
    for ref in refs:
      ref.invalidate()

  def set(self, value):
    assert not hasattr(self, '_value')
    self._value = (value, None)

  def get(self, f, *args):
    assert threading.current_thread() == MAIN_THREAD
    if not self.inited:
      invalidation_strategy._watch_object(self)
      self.inited = True
    if evaluation_stack:
      if not hasattr(self, '_refs'):
        self._refs = WeakSet()
      self._refs.add(evaluation_stack[-1])
    try:
      value, e = self._value
    except AttributeError:
      with LazyEvaluationContext(self):
        try:
          value = f(*args)
          self._value = (value, None)
          return value
        except Exception as e:
          self._value = (None, e)
          raise
    if e:
      raise e
    return value

class LazyFunction(object):
  def __init__(self, func, listener = None):
    self.__func__ = func
    if listener is not None:
      self._value = LazyResult(listener)
    elif hasattr(func, 'watch'):
      self._value = LazyResult(func)
    else:
      self._value = LazyResult()

  def __call__(self):
    return self._value.get(self.__func__)

  def __get__(self, obj, objtype):
    if not isinstance(objtype, type):
      raise ValueError('@lazy attributes not supported on old-style classes')
    if obj is not None:
      return obj.__dict__.setdefault(
          self.__func__.__name__, LazyInstanceMethod(self.__func__, obj, objtype))
    return LazyInstanceMethod(self.__func__, obj, objtype)

  def invalidate(self):
    self._value.invalidate()

  def continually(self):
    while True:
      invalidation_event.clear()
      while invalidation_queue:
        invalidation_queue.pop().invalidate()
      with LazyEvaluationContext(invalidation_event):
        self()
      while not invalidation_event.is_set():
        invalidation_event.wait(99999)

class LazyInstanceMethod(object):
  def __new__(cls, func, obj, objtype):
    if obj is not None:
      try:
        return obj.__dict__[func.__name__]
      except KeyError:
        pass
    result = super(LazyInstanceMethod, cls).__new__(cls)
    if obj is not None:
      return obj.__dict__.setdefault(func.__name__, result)
    else:
      return result

  def __init__(self, func, obj, objtype):
    update_wrapper(self, func)
    self.__func__ = func
    self.__self__ = obj
    self.im_class = objtype
    self.im_func = func
    self.im_self = obj
    self.__dict__.setdefault('_results', {})

  def __call__(self, *args, **kwargs):
    if self.__self__ is None:
      obj = args[0]
      bound_method = getattr(obj, self.__name__)
      if bound_method.im_class != self.im_class:
        raise TypeError('@lazy does not support inheritance: ' + repr(self))
      return bound_method(*args[1:], **kwargs)
    else:
      args = (self.__self__,) + args
      allargs = tuple(getcallargs(self.__func__, *args, **kwargs).items())[1:]
      result = self._results.setdefault(allargs, LazyResult())
      return result.get(self.__func__, *args, **kwargs)

  def __repr__(self):
    if self.__self__ is not None:
      return '<bound lazy method %s.%s of %s>' % (
          self.im_class.__name__, self.__func__.__name__, repr(self.__self__))
    else:
      return '<unbound lazy method %s.%s>' % (
          self.im_class.__name__, self.__func__.__name__)

class Storage(object): pass

class PropertyWatchWrapper(object):
  def __init__(self, func, obj):
    self.func = func
    self.obj = obj
    self.storage = Storage()

  def watch(self, callback):
    self.func.watch(self.obj, self.storage, callback)
  
  def unwatch(self):
    self.func.unwatch(self.storage)

class LazyProperty(object):
  """Lazily-calculated property."""
  def __init__(self, delegate):
    self.delegate = delegate

  def __get__(self, obj, objtype=None):
    if obj is None:
      return self
    try:
      lazy_result = obj.__dict__[self.__name__]
    except KeyError:
      if hasattr(self.delegate, 'watch'):
        lazy_result = LazyResult(PropertyWatchWrapper(self.delegate, obj))
      else:
        lazy_result = LazyResult()
      obj.__dict__[self.__name__] = lazy_result
    return lazy_result.get(self.delegate.__get__, obj, objtype)

  def __set__(self, obj, value):
    raise AttributeError()

MAIN_THREAD = threading.current_thread()
evaluation_stack = []
invalidation_queue = deque()
invalidation_strategy = LazyConstants()
invalidation_event = threading.Event()

invalidation_event.invalidate = invalidation_event.set

