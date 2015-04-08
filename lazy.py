import threading, weakref

__all__ = ['lazy']

def lazy(object):
  if isinstance(object, classmethod):
    return LazyClassProperty(object.__func__)
  elif isinstance(object, staticmethod):
    return LazyStaticProperty(object.__func__)
  elif isinstance(object, property):
    return LazyProperty(object.fget)
  elif hasattr(object, '__call__'):
    return LazyFunction(object)
  else:
    return LazyAttribute(object)

class LocallyEvaluating(threading.local):
  evaluating = None
  _after_evaluation = []

  def invalidate_after_evaluation(self, lazyObject):
    if not self.evaluating:
      raise ValueError()
    self._after_evaluation.append(lazyObject)

_locally = LocallyEvaluating()

class LazyEvaluationContext(object):
  def __init__(self, lazyObject):
    self.lazyObject = lazyObject

  def __enter__(self):
    self._wasEvaluating = _locally.evaluating
    _locally.evaluating = self.lazyObject
    return self

  def __exit__(self, type, value, traceback):
    _locally.evaluating = self._wasEvaluating
    if _locally.evaluating is None:
      while _locally._after_evaluation:
        _locally._after_evaluation.pop().invalidate()

class LazyComputation(object):
  def invalidate(self):
    try:
      _locally.invalidate_after_evaluation(self)
      return
    except ValueError:
      pass
    try:
      del self._value
    except AttributeError:
      pass
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
    if _locally.evaluating is not None:
      if not hasattr(self, '_refs'):
        self._refs = weakref.WeakSet()
      self._refs.add(_locally.evaluating)
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

class InvalidationEvent():
  def __init__(self):
    self.event = threading.Event()

  def clear(self):
    self.event.clear()

  def invalidate(self):
    self.event.set()

  def wait(self):
    while not self.event.is_set():
      self.event.wait(99999)

class LazyFunction(object):
  def __init__(self, func):
    self.__func__ = func
    self.__name__ = func.__name__
    self.__doc__ = func.__doc__
    self._value = LazyComputation()

  def __call__(self):
    return self._value.get(self.__func__)

  def invalidate(self):
    self._value.invalidate()

  def continually(self):
    event = InvalidationEvent()
    while True:
      with LazyEvaluationContext(event):
        self()
      event.wait()
      event.clear()

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
    self.__name__ = func.__name__
    self.__doc__ = func.__doc__

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
    self.__name__ = func.__name__
    self.__doc__ = func.__doc__
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
    self.__name__ = func.__name__
    self.__doc__ = func.__doc__
    self._value = LazyComputation()

  def __get__(self, obj, objtype=None):
    if obj is not None:
      raise AttributeError("'%s' object has no attribute '%s'"
                           % (objtype.__name__, self.__name__))
    return self._value.get(self._func)

  def __set__(self, obj, value):
    raise AttributeError()

