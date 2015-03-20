import re, sh
from collections import defaultdict, namedtuple
from datetime import datetime
from itertools import chain

__all__ = ['revparse', 'getUpstreamBranch', 'Branch', 'Commit']

def first(collection, default=None):
  return next(iter(collection), default)

def revparse(*args, **kwargs):
  try:
    return str(sh.git("rev-parse", *args, **kwargs)).strip()
  except sh.ErrorReturnCode, e:
    raise ValueError(e)

def getUpstreamBranch(branch):
  try:
    return revparse("--abbrev-ref", branch + "@{upstream}")
  except ValueError:
    return None

class lazy(object):
  """Lazily-calculated class and object properties."""
  def __init__(self, func):
    self._func = func
    self.__name__ = func.__name__
    self.__doc__ = func.__doc__

  def __get__(self, obj, klass=None):
    if self.__name__ == self.__name__.upper():
      if obj is not None:
        raise AttributeError("'%s' object has no attribute '%s'"
                             % (klass.__name__, self.__name__))
      if 'result' not in vars(self):
        self.result = self._func(klass)
      return self.result
    else:
      if obj is None:
        raise AttributeError("type object '%s' has no attribute '%s'"
                             % (klass.__name__, self.__name__))
      result = self._func(obj)
      setattr(obj, self.__name__, result)
      return result

  def clear(self):
    if 'result' in vars(self):
      del vars(self)['result']

RefLog = namedtuple('RefLine', 'timestamp hash')
Commit = namedtuple("Commit", "hash subject merges")

class Branch(object):
  _BRANCHES_BY_ID = { }

  @classmethod
  def clear_cache(cls):
    for k, p in vars(cls).iteritems():
      if k == k.upper():
        p.clear()
  
  @lazy
  def HEAD(cls):
    try:
      return cls(revparse("--abbrev-ref", "HEAD"))
    except ValueError:
      return None

  @lazy
  def ALL(cls):
    names = revparse("--abbrev-ref", "--branches").splitlines()
    return frozenset(cls(name) for name in names)

  @lazy
  def REMOTES(cls):
    names = revparse("--abbrev-ref", "--remotes").splitlines()
    locals = frozenset(b.name for b in cls.ALL)
    return frozenset(cls(name) for name in names if name.split('/', 1)[-1] in locals)

  @lazy
  def _REF_LOGS(cls):
    raw = {}
    for b in cls.ALL:
      try:
        raw[b] = sh.git.log("-g", "%s@{now}" % b.name, "--date=raw", "--format=%gd %H",
                            _tty_out=False, _iter=True)
      except sh.ErrorReturnCode:
        raw[b] = ()

    ref_logs = {}
    rx = re.compile("@[{](\\d+) .*[}] (\\w+)")
    for b in raw:
      ref_logs[b] = branch_logs = []
      for l in raw[b]:
        m = rx.search(l)
        if m:
          branch_logs.append(RefLog(int(m.group(1)), m.group(2)))
    return ref_logs

  @lazy
  def _COMMITS(cls):
    raw = {}
    for b in chain(cls.ALL, cls.REMOTES):
      raw[b] = sh.git.log("--first-parent", "--format=%H:%P:%s", b.name,
                          _iter=True, _tty_out=False)
    commits = {}
    for b in raw:
      commits[b] = [Commit(h, s.strip(), m.split(" ")[1:]) for h, m, s in
                    (l.split(":", 2) for l in raw[b])]
    return commits

  @lazy
  def REV_MAP(cls):
    # We want the last branch that pointed to a particular reference,
    # unless two or more branches currently point to it, in which case
    # we want the one that has pointed to it the longest.
    rev_map = defaultdict(list)
    for b in cls.ALL:
      last_timestamp = None
      first_rev = None
      for ref in cls._REF_LOGS[b]:
        if last_timestamp is None:
          first_rev = ref.hash
        else:
          if first_rev is not None:
            rev_map[first_rev].append((ref.timestamp, b))
            first_rev = None
          rev_map[ref.hash].append((-last_timestamp, b))
        last_timestamp = ref.timestamp
      if first_rev is not None:
        rev_map[first_rev].append((ref.timestamp, b))
    return { k : max(v)[1] for k, v in rev_map.iteritems() }

  def __new__(cls, name):
    if name not in cls._BRANCHES_BY_ID:
      cls._BRANCHES_BY_ID[name] = object.__new__(cls, name)
    return cls._BRANCHES_BY_ID[name]

  def __init__(self, name):
    self.name = name

  def __repr__(self):
    return "Branch('%s')" % self.name

  def __hash__(self):
    return hash(self.name)

  @lazy
  def _refLog(self):
    """
    Returns a map of commit hash to reference weight for this branch. If several
    branches have referenced a commit, the one with the highest weight has
    the best claim to "owning" it.

    """
    rev_map = {}
    last_timestamp = None
    first_rev = None
    for ref in type(self)._REF_LOGS.get(self, ()):
      if last_timestamp is None:
        first_rev = ref.hash
      else:
        if first_rev is not None:
          rev_map[first_rev] = ref.timestamp
          first_rev = None
        rev_map[ref.hash] = -last_timestamp
      last_timestamp = ref.timestamp
    if first_rev is not None:
      rev_map[first_rev] = ref.timestamp
    return rev_map

  @lazy
  def allCommits(self):
    """All commits made to this branch, in reverse chronological order.

    Merges will only list commit hashes, not branches.

    """
    return type(self)._COMMITS[self]

  @lazy
  def upstream(self):
    """The branch set as this branch's 'upstream', or None if none is set."""
    upstreamName = getUpstreamBranch(self.name)
    return None if upstreamName is None else Branch(upstreamName)

  @lazy
  def upstreamCommit(self):
    """The most recent commit this branch shares with its upstream.

    `git log` and `git reflog` are used to detect rebases on the upstream
    branch, in similar fashion to `git pull`.

    """
    if self.upstream is None:
      return None
    commitHashes = set(c.hash for c in self.allCommits)
    firstUpstreamReference = first(h for h in self.upstream._refLog if h in commitHashes)
    upstreamCommitHashes = set(c.hash for c in self.upstream.allCommits)
    return first(c for c in self.allCommits
                 if c.hash in upstreamCommitHashes or c == firstUpstreamReference)

  @lazy
  def commits(self):
    """All commits made to this branch since it left upstream, including merges."""
    commits = []
    for c in self.allCommits:
      if c == self.upstreamCommit:
        break
      if c.merges:
        mergedBranches = tuple(type(self).REV_MAP.get(rev, rev) for rev in c.merges)
        commits.append(Commit(c.hash, c.subject, mergedBranches))
      else:
        commits.append(c)
    return commits

  @lazy
  def parents(self):
    """All parents of this branch, whether upstream or merged."""
    parents = [p for c in self.commits for p in c.merges if type(p) == Branch]
    if self.upstream is not None:
      parents.append(self.upstream)
    return frozenset(parents)

  @lazy
  def children(self):
    """All branches which have this branch as upstream or merged."""
    return frozenset(b for b in type(self).ALL if self in b.parents)

  @lazy
  def modtime(self):
    """The timestamp of the latest commit to this branch."""
    log = tuple(sh.git.log("-n5", "--format=%at", self.name, "--",
                           _tty_out=False, _iter=True))
    for line in log:
      modtime = int(line.strip())
      if modtime != 1:
        return datetime.utcfromtimestamp(modtime)
    return None

  @lazy
  def unmerged(self):
    """The number of parent commits that have not been pulled to this branch."""
    unmerged = 0
    for parent in self.parents:
      log = sh.git.log("--format=tformat:.", "%s..%s" % (self.name, parent.name),
                       _tty_out=False, _iter=True)
      unmerged += sum(1 for l in log)
    return unmerged

