import signal

class SignalListener(object):
  def __init__(self, signum):
    self.signum = signum

  def watch(self, callback):
    self._callback = callback
    self._next_signal = signal.signal(self.signum, self.resize_event)

  def resize_event(self, signal_num, stack):
    try:
      self._next_signal()
    except TypeError:
      pass
    finally:
      self._callback()

  def unwatch(self):
    signal.signal(self.signum, self._next_signal)

