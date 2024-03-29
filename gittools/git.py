import os.path, re, threading, watchdog.events
from collections import defaultdict, namedtuple
from datetime import datetime, timedelta
from fnmatch import fnmatch
from functools import update_wrapper
from .lazy import lazy
from .multiobserver import OBSERVER
from .utils import first, fractionalSeconds, staticproperty, LazyList, Sh, ShError

__all__ = [ 'getUpstreamBranch', 'git_dir', 'lazy_git_property', 'revparse',
            'Branch', 'GitListener', 'GitLockWatcher' ]

# wait(None) blocks signals like KeyboardInterrupt
# Use wait(99999) instead
INDEFINITELY = 99999

@lazy
def git_dir():
  return revparse("--git-dir")

class GitLockWatcher(watchdog.events.FileSystemEventHandler):
  def __init__(self, latency = timedelta(seconds = 0.5)):
    self.lockfile = os.path.join(git_dir(), 'index.lock')
    self.latency = latency
    self._unlock_timestamp = datetime.utcfromtimestamp(0)
    self._unlocked = threading.Condition()

  @property
  def is_locked(self):
    return self._unlock_timestamp is not None and self._unlock_timestamp <= datetime.utcnow()

  def await_unlocked(self):
    while True:
      timeout = (fractionalSeconds(self._unlock_timestamp - datetime.utcnow())
                 if self._unlock_timestamp else INDEFINITELY)
      if timeout is not None and timeout <= 0:
        return
      with self._unlocked:
        self._unlocked.wait(timeout)

  def _lock(self):
    self._unlock_timestamp = None

  def _unlock(self):
    with self._unlocked:
      self._unlock_timestamp = datetime.utcnow() + self.latency
      self._unlocked.notify_all()

  def __enter__(self):
    OBSERVER.schedule(self, '.git')
    if os.path.exists(self.lockfile):
      self._lock()
    return self

  def __exit__(self, type, value, traceback):
    OBSERVER.unschedule(self, '.git')

  def on_created(self, event):
    if event.src_path == self.lockfile:
      self._lock()

  def on_deleted(self, event):
    if event.src_path == self.lockfile:
      self._unlock()

  def on_moved(self, event):
    if event.src_path == self.lockfile:
      self._unlock()
    if event.dest_path == self.lockfile:
      self._lock()

def revparse(*args):
  """Returns the result of `git rev-parse *args`."""
  try:
    return str(Sh("/usr/local/bin/git", "rev-parse", *args)).strip()
  except ShError as e:
    raise ValueError(e)

def getUpstreamBranch(branch):
  """Returns the upstream of branch, or None if none is set."""
  try:
    return revparse("--abbrev-ref", branch + "@{upstream}")
  except ValueError:
    return None

RefLine = namedtuple('RefLine', 'timestamp hash')
Commit = namedtuple("Commit", "hash subject merges")

class GitListener(watchdog.events.FileSystemEventHandler):
  """
  Listens for git filesystem events.

  Monitors root_dir (the current .git dir by default) and its subdirectories for
      file-system events.
  Events that match *any* include_glob will trigger an invalidation.
  If any exclude_globs are provided, events that *do not* match any of them will trigger an
      invalidation.
  If no globs are provided, *all* events trigger an invalidation.
  All globs are relative to root_dir.
  """
  def __init__(self,
               root_dir = None,
               exclude_globs = (),
               include_globs = ()):
    self.root_dir = root_dir
    self.exclude_globs = frozenset(exclude_globs)
    self.include_globs = frozenset(include_globs)
    self._recursive = bool(self.exclude_globs
                           or not self.include_globs
                           or any('*' in g for g in self.include_globs))

  def watch(self, callback):
    self._callback = callback
    root_dir = self.root_dir or git_dir()
    try:
      self._abs_root_dir = os.path.abspath(self.root_dir or git_dir())
    except AttributeError:
      raise ValueError('root_dir inappropriate: %s' % repr(root_dir))
    OBSERVER.schedule(self, self._abs_root_dir)

  def unwatch(self):
    OBSERVER.unschedule(self, self._abs_root_dir).stop()

  def path_matches(self, rel_path):
    if not self.exclude_globs and not self.include_globs:
      return True
    any_included = any(fnmatch(rel_path, g) for g in self.include_globs)
    if any_included:
      return True
    any_excluded = any(fnmatch(rel_path, g) for g in self.exclude_globs)
    if self.exclude_globs and not any_excluded:
      return True
    return False

  def on_any_event(self, event):
    if event.is_directory:
      pass
    elif self.path_matches(os.path.relpath(event.src_path, self._abs_root_dir)):
      self._callback()
    else:
      try:
        if self.path_matches(os.path.relpath(event.dest_path, self._abs_root_dir)):
          self._callback()
      except AttributeError:
        pass

def lazy_git_function(watching):
  return lazy(listener = GitListener(include_globs = watching))

class LazyGitProperty(watchdog.events.FileSystemEventHandler, property):
  """
  Base class for properties that provide information about a git repository.

  Monitors root_dir (the current .git dir by default) and its subdirectories for
      file-system events.
  Events that match *any* include_glob will trigger an invalidation.
  If any exclude_globs are provided, events that *do not* match any of them will trigger an
      invalidation.
  If no globs are provided, *all* events trigger an invalidation.
  All globs are relative to root_dir.
  Globs may include object properties, e.g. refs/heads/%name%
  """
  PROPERTY_RE = re.compile(r"%(\w+)%")

  def __init__(self, func, watching):
    property.__init__(self, fget = func)
    self.__func__ = func
    self._root_dir = os.path.abspath(git_dir())
    self._watching = frozenset([watching] if isinstance(watching, str)
                               else watching)
    update_wrapper(self, func)

  def substitute(self, obj, globs):
    return tuple(LazyGitProperty.PROPERTY_RE.sub(lambda m: getattr(obj, m.group(1)), g)
                 for g in globs)

  def watch(self, obj, storage, callback):
    root_dir = self._root_dir
    watching = self.substitute(obj, self._watching)
    class handler(watchdog.events.FileSystemEventHandler):
      def path_matches(self, rel_path):
        return any(fnmatch(rel_path, g) for g in watching)

      def on_any_event(self, event):
        if event.is_directory:
          pass
        elif self.path_matches(os.path.relpath(event.src_path, root_dir)):
          callback()
        else:
          try:
            if self.path_matches(os.path.relpath(event.dest_path, root_dir)):
              callback()
          except AttributeError:
            pass
    storage.handler = handler()
    OBSERVER.schedule(storage.handler, '.git')

  def unwatch(self, storage):
    OBSERVER.unschedule(storage.handler, '.git')

def lazy_git_property(watching):
  return lambda func : lazy(LazyGitProperty(func, watching))

class Branch:
  _BRANCHES_BY_ID = { }
  _MERGE_PATTERN = re.compile(
      "Merge branch(?: '([^']+)'|es ('[^']+'(?:, '[^']+')*) and '([^']+)')")

  @staticmethod
  def _mergedBranches(comment):
    """If comment is a merge commit comment, returns the branches named in it."""
    branches = []
    m = Branch._MERGE_PATTERN.match(comment)
    if m:
      branches.extend(m.group(i) for i in (1,3) if m.group(i))
      if m.group(2):
        branches.extend(t[1:-1] for t in m.group(2).split(', '))
    return frozenset(branches)

  @staticproperty
  @lazy_git_function(watching = ['HEAD'])
  def HEAD():
    """The current HEAD branch, or None if head is detached."""
    try:
      return Branch(revparse("--abbrev-ref", "HEAD"))
    except ValueError:
      return None

  @staticproperty
  @lazy_git_function(watching = ['refs/heads/*'])
  def ALL():
    """The set of all (local) branches."""
    names = revparse("--abbrev-ref", "--branches").splitlines()
    return frozenset(Branch(name) for name in names)

  @staticproperty
  @lazy_git_function(watching = ['refs/remotes/*'])
  def REMOTES():
    """The set of all remote branches that have a local branch of the same name."""
    names = revparse("--abbrev-ref", "--remotes").splitlines()
    locals = frozenset(b.name for b in Branch.ALL)
    return frozenset(Branch(name) for name in names if name.split('/', 1)[-1] in locals)

  def __new__(cls, name):
    if name == 'HEAD':
      raise ValueError('HEAD is not a valid Branch name')
    if name not in cls._BRANCHES_BY_ID:
      cls._BRANCHES_BY_ID[name] = super(Branch, cls).__new__(cls)
    return cls._BRANCHES_BY_ID[name]

  def __init__(self, name):
    self.name = name

  def __repr__(self):
    return "Branch('%s')" % self.name

  def __hash__(self):
    return hash(self.name)

  _REFLOG_RE = re.compile("@[{](\\d+) .*[}] (\\w+)")

  @lazy
  @property
  def fullName(self):
    return revparse('--symbolic-full-name', self.name)

  @lazy_git_property(watching = 'logs/%fullName%')
  def _refLog(self):
    try:
      rawlog = Sh("/usr/local/bin/git", "log", "-g", "%s@{now}" % self.name,
                  "--date=raw", "--format=%gd %H")
      matches = (Branch._REFLOG_RE.search(l) for l in rawlog)
      return tuple(RefLine(int(m.group(1)), m.group(2)) for m in matches if m)
    except ShError:
      return ()

  @lazy_git_property(watching = '%fullName%')
  def allCommits(self):
    """All commits made to this branch, in reverse chronological order.

    Merges will only list commit hashes, not branches.

    """
    raw = Sh("/usr/local/bin/git", "log", "--first-parent", "--format=%H:%P:%s", self.name, "--")
    commits = (Commit(h, s.strip(), m.split(" ")[1:]) for h, m, s in
               (l.split(":", 2) for l in raw))
    return LazyList(commits)

  @lazy
  @property
  def latestCommit(self):
    """The latest commit made to this branch."""
    return self.allCommits[0]

  @lazy_git_property(watching = 'config')
  def upstream(self):
    """The branch set as this branch's 'upstream', or None if none is set."""
    upstreamName = getUpstreamBranch(self.name)
    return None if upstreamName is None else Branch(upstreamName)

  @lazy
  @property
  def upstreamCommit(self):
    """The most recent commit this branch shares with its upstream.

    `git log` and `git reflog` are used to detect rebases on the upstream
    branch, in similar fashion to `git pull`.

    """
    if self.upstream is None:
      return None
    commitHashes = set(c.hash for c in self.allCommits)
    firstUpstreamReference = first(h.hash for h in self.upstream._refLog if h.hash in commitHashes)
    upstreamCommitHashes = set(c.hash for c in self.upstream.allCommits)
    return first(c for c in self.allCommits
                 if c.hash in upstreamCommitHashes or c.hash == firstUpstreamReference)

  @lazy
  @property
  def commits(self):
    """All commits made to this branch since it left upstream, including merges."""
    def impl():
      for c in self.allCommits:
        if c == self.upstreamCommit:
          return
        mergedBranches = [Branch(name) for name in Branch._mergedBranches(c.subject)]
        if mergedBranches:
          yield Commit(c.hash, c.subject, mergedBranches)
        else:
          yield c
    return LazyList(impl())

  @lazy
  @property
  def parents(self):
    """All parents of this branch, whether upstream or merged."""
    if self.upstream is None:
      return frozenset()
    parents = [p for c in self.commits for p in c.merges if type(p) == Branch]
    parents.append(self.upstream)
    return frozenset(parents)

  @lazy
  @property
  def children(self):
    """All branches which have this branch as upstream or merged."""
    return frozenset(b for b in type(self).ALL if self in b.parents)

  @lazy_git_property(watching = 'refs/heads/%name%')
  def modtime(self):
    """The timestamp of the latest commit to this branch."""
    with Sh("/usr/local/bin/git", "log", "-n5", "--format=%at", self.name, "--") as log:
      for line in log:
        modtime = int(line)
        if modtime != 1:
          return datetime.utcfromtimestamp(modtime)
    return None

  @lazy_git_property(watching = 'refs/heads/%name%')
  def unmerged(self):
    """The number of parent commits that have not been pulled to this branch."""
    if self.upstream is None:
      return 0
    allCommits = set(c.hash for c in self.allCommits)
    if len(self.parents) > 1:
      for c in self.allCommits:
        if c == self.upstreamCommit:
          break
        for rev in c.merges:
          allCommits.update(Sh("/usr/local/bin/git", "log", "--first-parent", "--format=%H", rev))
    parentCommits = set()
    for p in self.parents:
      for c in p.allCommits:
        if c.hash in allCommits:
          break
        parentCommits.add(c.hash)
    return len(parentCommits)

