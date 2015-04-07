import threading, weakref

__all__ = ['lazy']

def lazy(object):
  if isinstance(object, classmethod):
    return LazyClassProperty(object.__func__)
  elif isinstance(object, staticmethod):
    return LazyStaticProperty(object.__func__)
  elif isinstance(object, property):
    return LazyProperty(object.fget)
  else:
    return LazyAttribute(object)

class LocallyEvaluating(threading.local):
  evaluating = None

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

class InvalidationBeforeCalculationCompletedException(Exception):
  pass

class LazyValue(object):
  def invalidate(self):
    assert not _locally.evaluating
    try:
      del self._value
    except AttributeError:
      raise InvalidationBeforeCalculationCompletedException()
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
    return obj.__dict__.setdefault(self.__name__, LazyValue())

  def __get__(self, obj, objtype):
    self._find_name(obj, objtype)
    if obj is None:
      return self
    return self._get_lazy_value(obj).get(lambda : self._default)

  def __set__(self, obj, value):
    self._find_name(obj)
    lazy_value = self._get_lazy_value(obj)
    try:
      lazy_value.invalidate()
    except InvalidationBeforeCalculationCompletedException:
      pass
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
    return obj.__dict__.setdefault(self.__name__, LazyValue()).get(self._func, obj)

  def __set__(self, obj, value):
    raise AttributeError()

class LazyClassProperty(object):
  """Lazily-calculated class property."""
  def __init__(self, func):
    self._func = func
    self.__name__ = func.__name__
    self.__doc__ = func.__doc__
    self._value = LazyValue()

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
    self._value = LazyValue()

  def __get__(self, obj, objtype=None):
    if obj is not None:
      raise AttributeError("'%s' object has no attribute '%s'"
                           % (objtype.__name__, self.__name__))
    return self._value.get(self._func)

  def __set__(self, obj, value):
    raise AttributeError()

