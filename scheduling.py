import concurrent.futures.thread, threading
from datetime import datetime, timedelta
from functools import update_wrapper
from heapq import heappush, heappop
from utils import fractionalSeconds

class Scheduler(threading.Thread):
  """A half-baked ConcurrentThreadPoolExecutor implementation."""
  def __init__(self):
    threading.Thread.__init__(self)
    self._executor = concurrent.futures.thread.ThreadPoolExecutor(3)
    self._pq = []
    self._sleepingTasks = threading.Condition()
    self.daemon = True
    self.active = False
    self.refcount = 1

  def submit(self, task, *args, **kwargs):
    assert self.refcount > 0
    return self._executor.submit(task, *args, **kwargs)

  def submit_at(self, time, task, *args, **kwargs):
    assert self.refcount > 0
    with self._sleepingTasks:
      currentWakeUpTime = self._pq[0][0] if self._pq else None
      heappush(self._pq, (time, task, args, kwargs))
      if currentWakeUpTime is None or time < currentWakeUpTime:
        self._sleepingTasks.notify()
      if not self.active:
        self.active = True
        self.start()

  def run(self):
    with self._sleepingTasks:
      while self.active:
        while not self._pq:
          self._sleepingTasks.wait(99999)
        sleep_time = self._pq[0][0] - datetime.utcnow()
        if sleep_time > timedelta(0):
          self._sleepingTasks.wait(fractionalSeconds(sleep_time))
        else:
          (time, task, args, kwargs) = heappop(self._pq)
          callback = kwargs.pop('callback', None)
          future = self.submit(task, *args, **kwargs)
          if callback:
            future.add_done_callback(callback)

  def retain(self):
    assert self.refcount > 0
    self.refcount += 1

  def release(self):
    assert self.refcount > 0
    self.refcount -= 1
    if self.refcount == 0:
      if self.active:
        self.active = False
        with self._sleepingTasks:
          self._sleepingTasks.notify()
        self.join()
      self._executor.shutdown()

class CompletedFuture(object):
  def __init__(self, value):
    self.value = value

  def result(self):
    return value

  def done(self):
    return True

  def add_done_callback(self, callback):
    callback(self)

class NotDoneException(Exception): pass

class Poller(object):
  """A lazy-compatible function that refreshes a computation periodically."""
  def __init__(self, scheduler, task, *args, **kwargs):
    self.scheduler = scheduler
    self.repeat_every = kwargs.pop('repeat_every', timedelta(minutes = 2))
    self.task = task
    self.args = args
    self.kwargs = kwargs
    self._future = self.scheduler.submit(self.task, *args, **kwargs)
    self._asynchronous = False
    update_wrapper(self, task)

  def __call__(self):
    if not self._asynchronous or self._future.done():
      return self._future.result()
    raise NotDoneException()

  def watch(self, callback):
    self.scheduler.retain()
    self._asynchronous = True
    self._callback = callback
    self._future.add_done_callback(self.update)

  def reschedule(self):
    self.scheduler.submit_at(datetime.utcnow() + self.repeat_every,
                             self.task,
                             *self.args,
                             callback = self.update,
                             **self.kwargs)

  def update(self, new_future):
    old_future = self._future
    self._future = new_future
    old_future.cancel()
    if self._asynchronous:
      self.reschedule()
      try:
        if old_future is not new_future and new_future.result() == old_future.result():
          return  # Don't trigger invalidation if the value hasn't changed
      except BaseException:
        pass
      self._callback()

  def unwatch(self):
    self.scheduler.release()
    self._asynchronous = False
    self._callback = lambda : None

