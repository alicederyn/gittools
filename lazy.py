import threading, weakref
from collections import deque
from functools import update_wrapper

__all__ = ['lazy']

MAIN_THREAD = threading.current_thread()
evaluation_stack = []
invalidation_queue = deque()
invalidation_event = threading.Event()

invalidation_event.invalidate = invalidation_event.set

def lazy(object):
  if isinstance(object, classmethod):
    return update_wrapper(LazyClassProperty(object.__func__), object.__func__)
  elif isinstance(object, staticmethod):
    return update_wrapper(LazyStaticProperty(object.__func__), object.__func__)
  elif isinstance(object, property):
    return update_wrapper(LazyProperty(object.fget), object.fget)
  elif isinstance(object, type) or str(type(object)) == "<type 'classobj'>":
    return update_wrapper(LazyFunctionType(object), object)
  elif hasattr(object, '__call__'):
    return update_wrapper(LazyFunction(object), object)
  else:
    return LazyAttribute(object)

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

class LazyComputation(object):
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
    self._value = LazyComputation()

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

class LazyFunctionType(LazyFunction):
  def __init__(self, ftype):
    LazyFunction.__init__(self, ftype())
    self._inited = False

  def __call__(self):
    if not self._inited:
      self.__func__.watch(self.invalidate)
      self._inited = True
    return LazyFunction.__call__(self)

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
    return obj.__dict__.setdefault(self.__name__, LazyComputation())

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

class LazyProperty(object):
  """Lazily-calculated property."""
  def __init__(self, func):
    self._func = func

  def __get__(self, obj, objtype=None):
    if obj is None:
      return self
    return obj.__dict__.setdefault(self.__name__, LazyComputation()).get(self._func, obj)

  def __set__(self, obj, value):
    raise AttributeError()

class LazyClassProperty(object):
  """Lazily-calculated class property."""
  def __init__(self, func):
    self._func = func
    self._value = LazyComputation()

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
    self._value = LazyComputation()

  def __get__(self, obj, objtype=None):
    if obj is not None:
      raise AttributeError("'%s' object has no attribute '%s'"
                           % (objtype.__name__, self.__name__))
    return self._value.get(self._func)

  def __set__(self, obj, value):
    raise AttributeError()

