import errno, os, select, signal, subprocess
from collections import namedtuple
from functools import update_wrapper
from .lazy import lazy
from .listener import SignalListener

__all__ = ['first', 'fractionalSeconds', 'staticproperty', 'window_size', 'LazyList', 'Sh', 'ShError']

def fractionalSeconds(delta):
  return delta.total_seconds() + delta.microseconds / 10000000.0

class staticproperty(object):
  def __init__(self, func):
    self._func = func
    update_wrapper(self, func)

  def __get__(self, obj, objtype):
    return self._func()

WindowSize = namedtuple('Size', 'rows columns')
@lazy(listener = SignalListener(signal.SIGWINCH))
def window_size():
  return WindowSize(*[int(v) for v in str(Sh('stty', 'size')).split()])

class ShError(Exception):
  def __init__(self, returncode, cmd, stderr):
    self.returncode = returncode
    self.cmd = cmd
    self.stderr = stderr

  def __str__(self):
    message = '%s exited with return code %s [%s]' % (
        self.cmd[0],
        self.returncode,
        ('arguments: %s' % ' '.join(self.cmd[1:])) if len(self.cmd) > 1 else 'no arguments')
    stderr_lines = ['    ' + l for l in self.stderr.splitlines()]
    if stderr_lines:
      message += '\n' + '\n'.join(stderr_lines)
    return message

  def __repr__(self):
    return 'ShError(%s, %s, %s)' % (repr(self.returncode), repr(self.cmd), repr(self.stderr))

class Sh:
  def __init__(self, *cmd):
    self.cmd = cmd
    self._process = subprocess.Popen(cmd, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
    self._out = []
    self._err = []

  def execute(self):
    with self as lines:
      for line in lines:
        pass

  def __iter__(self):
    return self

  def __next__(self):
    # Note: no universal newline support
    if len(self._out) == 1:
      lf = self._out[0].find('\n')
      if lf != -1:
        line = self._out[0][:lf]
        self._out[0] = self._out[0][lf+1:]
        return line
    read_set = [ v for v in (self._process.stdout, self._process.stderr) if v ]
    while read_set:
      try:
        rlist, _, _ = select.select(read_set, [], [])
      except select.error as e:
        if e.args[0] == errno.EINTR:
          continue
        raise
      if self._process.stderr in rlist:
        data = os.read(self._process.stderr.fileno(), 1024).decode('utf-8')
        if data == "":
          self._process.stderr.close()
          read_set.remove(self._process.stderr)
          self._process.stderr = None
        else:
          self._err.append(data)
      if self._process.stdout in rlist:
        data = os.read(self._process.stdout.fileno(), 1024).decode('utf-8')
        if data == "":
          self._process.stdout.close()
          read_set.remove(self._process.stdout)
          self._process.stdout = None
        else:
          lf = data.find('\n')
          if lf != -1:
            line = ''.join(self._out) + data[:lf]
            self._out = [data[lf+1:]]
            return line
          self._out.append(data)
    if self._out:
      line = ''.join(self._out)
      self._out = []
      if line:
        return line
    self._process.wait()
    if self._process.returncode:
      raise ShError(self._process.returncode, self.cmd, ''.join(self._err))
    else:
      raise StopIteration()

  def _communicate(self):
    bout, berr = self._process.communicate()
    out = bout.decode('utf-8')
    err = berr.decode('utf-8')

    self._process.stdout = self._process.stderr = None
    self._out.append(out)
    out = ''.join(self._out)
    self._out = []
    if err:
      self._err.append(err)
    return out

  def __str__(self):
    out = self._communicate()
    if self._process.returncode:
      raise ShError(self._process.returncode, self.cmd, ''.join(self._err))
    return out

  def __repr__(self):
    return '%s(%s)' % (type(self).__name__, ', '.join(repr(v) for v in self.cmd))

  def __enter__(self):
    return self

  def __exit__(self, type, value, traceback):
    if self._process.stdout:
      self._process.stdout.close()
      self._process.stdout = None
    if self._process.stderr:
      self._process.stderr.close()
      self._process.stderr = None
    try:
      self._process.kill()
      self._process.wait()
    except OSError:
      pass

def first(collection, default=None):
  return next(iter(collection), default)

class LazyListIterator(object):
  def __init__(self, iterator, values):
    self._iterator = iterator
    self._values = values
    self.pos = 0

  def __iter__(self):
    return self

  def __next__(self):
    try:
      v = self._values[self.pos]
    except IndexError:
      v = next(self._iterator)
      self._values.append(v)
    self.pos += 1
    return v

class LazyList(object):
  def __init__(self, iterator):
    self._iterator = iterator
    self._values = []

  def __iter__(self):
    return LazyListIterator(self._iterator, self._values)

  def __getitem__(self, y):
    try:
      while len(self._values) <= y:
        self._values.append(next(self._iterator))
    except StopIteration:
      raise IndexError("list index out of range")
    return self._values[y]

  def __len__(self):
    try:
      while True:
        self._values.append(next(self._iterator))
    except StopIteration:
      pass
    return len(self._values)

