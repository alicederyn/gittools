import watchdog.observers

__all__ = ['OBSERVER']

class DispatchingHandler(object):
  def __init__(self):
    self.handlers = frozenset()  # Copy-on-write

  def add_handler(self, handler):
    self.handlers = self.handlers | frozenset([handler])

  def remove_handler(self, handler):
    self.handlers = self.handlers - frozenset([handler])

  def has_handlers(self):
    return self.handlers

  def dispatch(self, event):
    for handler in self.handlers:
      handler.dispatch(event)

class MultiObserver(object):
  def __init__(self):
    self._handlers = {}
    self._observers = {}

  def schedule(self, handler, directory):
    try:
      multi_handler = self._handlers[directory]
    except KeyError:
      self._observers[directory] = observer = watchdog.observers.Observer()
      self._handlers[directory] = multi_handler = DispatchingHandler()
      observer.schedule(self._handlers[directory], directory, recursive = True)
      observer.start()
    multi_handler.add_handler(handler)

  def unschedule(self, handler, directory):
    try:
      self._handlers[directory].remove_handler(handler)
      if not self._handlers[directory].has_handlers():
        try:
          self._observers[directory].stop()
        except Exception:
          pass
        del self._observers[directory]
        del self._handlers[directory]
    except KeyError:
      pass

OBSERVER = MultiObserver()
