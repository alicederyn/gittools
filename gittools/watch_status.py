import os.path, sys, watchdog.events, watchdog.observers
from .git import git_dir, Branch, GitListener, GitLockWatcher
from itertools import islice
from .lazy import lazy, lazy_invalidation
from .utils import window_size, Sh

@lazy
class git_status(object):
  def __call__(self):
    self._git_lock.await_unlocked()
    return list(Sh('git', 'status', '--porcelain', '--untracked-files=all'))

  def watch(self, callback):
    self._listener = GitListener(root_dir = os.path.join(git_dir(), '..'),
                                 exclude_globs = ['.git/*'],
                                 include_globs = ['.git/index',
                                                  '.git/info/exclude',
                                                  '.git/refs/heads/*'])
    self._listener.watch(callback)
    self._git_lock = GitLockWatcher()
    self._git_lock.__enter__()

  def unwatch(self):
    self._listener.unwatch()
    self._git_lock.__exit__(None, None, None)
    self._git_lock = None

@lazy
def show_status():
  rows, columns = window_size()
  sys.stdout.write('\x1b[0;0H\x1b[2J')
  sys.stdout.write('\x1b[1;33m')
  if Branch.HEAD is None:
    sys.stdout.write('HEAD detached')
  else:
    sys.stdout.write('On %s' % Branch.HEAD.name)
  sys.stdout.write('\x1b[0m')
  for line in islice(git_status(), rows - 1):
    sys.stdout.write('\n')
    if len(line) > columns:
      line = line[0:4] + '...' + line[-(columns - 8):]
    sys.stdout.write(line)
  sys.stdout.flush()

def main():
  assert sys.stdout.isatty()
  try:
    with lazy_invalidation():
      show_status.continually()
  except KeyboardInterrupt:
    print()

