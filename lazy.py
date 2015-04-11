import threading, weakref
from collections import deque
from functools import update_wrapper

__all__ = ['lazy', 'lazy_invalidation']

def lazy(object):
  if isinstance(object, classmethod):
    return update_wrapper(LazyClassProperty(object.__func__), object.__func__)
  elif isinstance(object, staticmethod):
    return update_wrapper(LazyStaticProperty(object.__func__), object.__func__)
  elif isinstance(object, type) or str(type(object)) == "<type 'classobj'>":
    return update_wrapper(LazyFunction(object()), object)
  elif hasattr(object, '__call__'):
    return update_wrapper(LazyFunction(object), object)
  elif hasattr(object, '__get__'):
    lazy_property = LazyProperty(object)
    if hasattr(object, 'fget'):
      update_wrapper(lazy_property, object.fget)
    return lazy_property
  else:
    return LazyAttribute(object)

def lazy_invalidation():
  return LazyInvalidation()

class LazyConstants(object):
  def __init__(self):
    self._watchable_objects = set()

  def _watch_object(self, object):
    if object.watcher is not None:
      self._watchable_objects.add(object)

  def _invalidate_all(self):
    for watchable_object in self._watchable_objects:
      watchable_object.invalidate()
      watchable_object.inited = False
    self._watchable_objects.clear()

class LazyInvalidation(object):
  def __enter__(self):
    assert threading.current_thread() == MAIN_THREAD
    assert not evaluation_stack
    self._watchable_objects = set()
    global invalidation_strategy
    invalidation_strategy._invalidate_all()
    invalidation_strategy = self

  def _watch_object(self, object):
    if object.watcher is not None:
      self._watchable_objects.add(object)
      object.watcher.watch(object.invalidate)

  def __exit__(self, type, value, traceback):
    global invalidation_strategy
    invalidation_strategy = LazyConstants()
    for watchable_object in self._watchable_objects:
      try:
        watchable_object.watcher.unwatch()
      except AttributeError:
        pass
      watchable_object.invalidate()
      watchable_object.inited = False
    self._watchable_objects.clear()

  def _invalidate_all(self):
    raise TypeError('Cannot nest lazy_invalidation contexts')

class LazyEvaluationContext(object):
  def __init__(self, lazyObject):
    self.lazyObject = lazyObject

  def __enter__(self):
    assert threading.current_thread() == MAIN_THREAD
    evaluation_stack.append(self.lazyObject)
    return self

  def __exit__(self, type, value, traceback):
    evaluation_stack.pop()
    if not evaluation_stack:
      while invalidation_queue:
        invalidation_queue.pop().invalidate()

class LazyResult(object):
  def __init__(self, watcher = None):
    self.watcher = watcher
    self.inited = False

  def invalidate(self):
    if not hasattr(self, '_value'):
      return
    if threading.current_thread() != MAIN_THREAD or evaluation_stack:
      invalidation_queue.append(self)
      invalidation_event.set()
      return
    del self._value
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
        self._refs = weakref.WeakSet()
      self._refs.add(evaluation_stack[-1])
    try:
      value, e = self._value
    except AttributeError:
      with LazyEvaluationContext(self):
        try:
          value = f(*args)
          self._value = (value, None)
          return value
        except Exception, e:
          self._value = (None, e)
          raise
    if e:
      raise e
    return value

class LazyFunction(object):
  def __init__(self, func):
    self.__func__ = func
    if hasattr(func, 'watch'):
      self._value = LazyResult(func)
    else:
      self._value = LazyResult()

  def __call__(self):
    return self._value.get(self.__func__)

  def __get__(self, obj, objtype):
    return self()

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

class LazyAttribute(object):
  """Attribute with lazy propagation on updates."""
  def __init__(self, default):
    self._default = default

  def _find_name(self, obj, objtype = None):
    if not hasattr(self, '__name__'):
      if objtype is None:
        objtype = type(obj)
      for k, v in objtype.__dict__.iteritems():
        if v is self:
          self.__name__ = k
          break
      else:
        raise Exception('%s not found on %s', self, objtype)

  def _get_lazy_value(self, obj):
    return obj.__dict__.setdefault(self.__name__, LazyResult())

  def __get__(self, obj, objtype):
    self._find_name(obj, objtype)
    if obj is None:
      return self
    return self._get_lazy_value(obj).get(lambda : self._default)

  def __set__(self, obj, value):
    self._find_name(obj)
    lazy_value = self._get_lazy_value(obj)
    lazy_value.invalidate()
    lazy_value.set(value)

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

class LazyClassProperty(object):
  """Lazily-calculated class property."""
  def __init__(self, func):
    self._func = func
    self._value = LazyResult()

  def __get__(self, obj, objtype=None):
    if obj is not None:
      raise AttributeError("'%s' object has no attribute '%s'"
                           % (objtype.__name__, self.__name__))
    return self._value.get(self._func, objtype)

  def __set__(self, obj, value):
    raise AttributeError()

class LazyStaticProperty(object):
  """Lazily-calculated static property."""
  def __init__(self, func):
    self._func = func
    self._value = LazyResult()

  def __get__(self, obj, objtype=None):
    if obj is not None:
      raise AttributeError("'%s' object has no attribute '%s'"
                           % (objtype.__name__, self.__name__))
    return self._value.get(self._func)

  def __set__(self, obj, value):
    raise AttributeError()

MAIN_THREAD = threading.current_thread()
evaluation_stack = []
invalidation_queue = deque()
invalidation_strategy = LazyConstants()
invalidation_event = threading.Event()

invalidation_event.invalidate = invalidation_event.set

