import traceback
from datetime import timedelta
from .git import GitLockWatcher
from time import sleep
from .utils import Sh, ShError

def continuous_fetch(remote = '--all',
                     every = timedelta(minutes = 2),
                     unused_for = timedelta(seconds = 10)):
  with GitLockWatcher(latency = unused_for) as lock:
    while True:
      lock.await_unlocked()
      try:
        Sh('/usr/local/bin/git', 'fetch', '--prune', remote).execute()
        Sh('/usr/local/bin/git', 'fetch', '--tags', '--prune', remote).execute()
      except ShError as e:
        traceback.print_exc()
      sleep(every.total_seconds())

def main():
  try:
    continuous_fetch()
  except KeyboardInterrupt:
    pass
