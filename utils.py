import re, sh
from collections import defaultdict, namedtuple
from datetime import datetime

__all__ = ['revparse', 'getUpstreamBranch', 'getBranches', 'Branch', 'Commit']

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

def getBranches():
  return revparse("--abbrev-ref", "--branches").splitlines()

class lazy(object):
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
    return frozenset(cls(b) for b in getBranches())

  @lazy
  def REV_MAP(cls):
    # We want the last branch that pointed to a particular reference,
    # unless two or more branches currently point to it, in which case
    # we want the one that has pointed to it the longest.
    rx = re.compile("@[{](\\d+) .*[}] (\\w+)")
    rev_map = defaultdict(list)
    for b in cls.ALL:
      try:
        ref_log = tuple(sh.git.log("-g", "%s@{now}" % b.name, "--date=raw", "--format=%gd %H",
                                   _tty_out=False, _iter=True))
      except sh.ErrorReturnCode:
        ref_log = []
      last_timestamp = None
      first_rev = None
      for l in ref_log:
        m = rx.search(l)
        if m:
          ts = int(m.group(1))
          rev = m.group(2)
          if last_timestamp is None:
            first_rev = rev
          else:
            if first_rev is not None:
              rev_map[first_rev].append((ts, b))
              first_rev = None
            rev_map[rev].append((-last_timestamp, b))
          last_timestamp = ts
      if first_rev is not None:
        rev_map[first_rev].append((ts, b))
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
    rx = re.compile("@[{](\\d+) .*[}] (\\w+)")
    try:
      ref_log = tuple(sh.git.log("-g", "%s@{now}" % self.name, "--date=raw", "--format=%gd %H",
                                 _tty_out=False, _iter=True))
    except sh.ErrorReturnCode:
      return {}
    rev_map = {}
    last_timestamp = None
    first_rev = None
    for l in ref_log:
      m = rx.search(l)
      if m:
        ts = int(m.group(1))
        rev = m.group(2)
        if last_timestamp is None:
          first_rev = rev
        else:
          if first_rev is not None:
            rev_map[first_rev] = ts
            first_rev = None
          rev_map[rev] = -last_timestamp
        last_timestamp = ts
    if first_rev is not None:
      rev_map[first_rev] = ts
    return rev_map

  @lazy
  def allCommits(self):
    """All commits made to this branch, in reverse chronological order.

    Merges will only list commit hashes, not branches.

    """
    log = sh.git.log("--first-parent", "--format=%H:%P:%s", self.name,
                     _iter=True, _tty_out=False)
    return [Commit(h, s.strip(), m.split(" ")[1:]) for h, m, s in
            (l.split(":", 2) for l in log)]

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

