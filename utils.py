import re, sh
from collections import defaultdict, namedtuple
from datetime import datetime

def revparse(*args, **kwargs):
  try:
    return str(sh.git("rev-parse", *args, **kwargs)).strip()
  except sh.ErrorReturnCode, e:
    raise ValueError(e)

Commit = namedtuple("Commit", "hash subject")
def commitlog(branch):
  if not branch:
    return []
  log = sh.git.log("--format=%H %s", branch, _iter=True, _tty_out=False)
  return [Commit(h, s) for h, s in
          (l.split(" ", 1) for l in log.splitlines())]

def getUpstreamBranch(branch):
  try:
    return revparse("--abbrev-ref", branch + "@{upstream}")
  except ValueError:
    return None

def getBranches():
  return revparse("--abbrev-ref", "--branches").splitlines()

def hierarchy(top=None, branches=None):
  """Returns the 'upstream' hierarchy of all branches, plus the reverse
  'downstream' structure, excluding anything not downstream of 'top' if
  given. Does not currently handle merges.
  
  """
  branches = getBranches() if branches is None else branches
  parents = { branch : getUpstreamBranch(branch) for branch in branches }
  children = defaultdict(list)
  for branch in branches:
    children[parents[branch]].append(branch)
  assert top in children
  if top:
    tokeep = set()
    todo = [top]
    while todo:
      branch = todo.pop()
      if branch not in tokeep:
        tokeep.add(branch)
        todo.extend(children[branch])
  else:
    tokeep = children
  parents = { k : v for k, v in parents.iteritems() if k in tokeep }
  children = { k : tuple(children[k]) for k in tokeep }
  return parents, children

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
  def parents(self):
    u = getUpstreamBranch(self.name)
    if u:
      parents = [Branch(u)]
      spec = "%s..%s" % (u, self.name)
      mergeLog = sh.git.log("--merges", "--first-parent", "--format=%P", spec,
                            _tty_out=False, _iter=True)
      for l in mergeLog:
        for rev in l.strip().split()[1:]:
          try:
            parents.append(type(self).REV_MAP[rev])
          except KeyError:
            # Awkward... carry on regardless
            pass
      return frozenset(parents)
    else:
      return frozenset()

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
  def commits(self):
    """
    All commits made to this branch, in reverse chronological order.

    Uses `git log`.
    """
    return commitlog(self.name)

  @lazy
  def unpushedCommits(self):
    """
    All commits made to this branch that have not yet been pushed to a parant,
    in reverse chronological order.

    `git log` and `git reflog` are used to detect unmerged commits in parents, in
    similar fashion to `git pull`.

    """
    myLog = self.commits
    myRefLog = self._refLog
    parent = Branch(getUpstreamBranch(self.name))
    parentsLog = set(c.hash for c in parent.commits)
    parentsRefLog = parent._refLog
    unpushed = []
    for c in myLog:
      if c.hash in parentsLog:
        break
      if c.hash in parentsRefLog:
        if c.hash not in myRefLog or parentsRefLog[c.hash] > myRefLog[c.hash]:
          break
      unpushed.append(c)
    return tuple(unpushed)

  @lazy
  def children(self):
    return frozenset(b for b in type(self).ALL if self in b.parents)

  @lazy
  def modtime(self):
    log = tuple(sh.git.log("-n5", "--format=%at", self.name, "--",
                           _tty_out=False, _iter=True))
    for line in log:
      modtime = int(line.strip())
      if modtime != 1:
        return datetime.utcfromtimestamp(modtime)
    return None

  @lazy
  def unmerged(self):
    unmerged = 0
    for parent in self.parents:
      log = sh.git.log("--format=tformat:.", "%s..%s" % (self.name, parent.name),
                       _tty_out=False, _iter=True)
      unmerged += sum(1 for l in log)
    return unmerged

