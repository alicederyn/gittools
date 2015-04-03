import re
from collections import defaultdict, namedtuple
from datetime import datetime

__all__ = ['revparse', 'getUpstreamBranch', 'Branch']

def revparse(*args):
  try:
    return str(Sh("git", "rev-parse", *args)).strip()
  except ShError, e:
    raise ValueError(e)

def getUpstreamBranch(branch):
  try:
    return revparse("--abbrev-ref", branch + "@{upstream}")
  except ValueError:
    return None

RefLine = namedtuple('RefLine', 'timestamp hash')
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
        raw[b] = Sh("git", "log", "-g", "%s@{now}" % b.name, "--date=raw", "--format=%gd %H")
      except ShError:
        raw[b] = ()

    ref_logs = {}
    rx = re.compile("@[{](\\d+) .*[}] (\\w+)")
    for b in raw:
      ref_logs[b] = branch_logs = []
      try:
        for l in raw[b]:
          m = rx.search(l)
          if m:
            branch_logs.append(RefLine(int(m.group(1)), m.group(2)))
      except ShError:
        pass
    return ref_logs

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
    return type(self)._REF_LOGS.get(self, ())

  @lazy
  def allCommits(self):
    """All commits made to this branch, in reverse chronological order.

    Merges will only list commit hashes, not branches.

    """
    raw = Sh("git", "log", "--first-parent", "--format=%H:%P:%s", self.name)
    commits = (Commit(h, s.strip(), m.split(" ")[1:]) for h, m, s in
               (l.split(":", 2) for l in raw))
    return LazyList(commits)

  @lazy
  def latestCommit(self):
    """The latest commit made to this branch."""
    return self.allCommits[0]

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
    firstUpstreamReference = first(h.hash for h in self.upstream._refLog if h.hash in commitHashes)
    upstreamCommitHashes = set(c.hash for c in self.upstream.allCommits)
    return first(c for c in self.allCommits
                 if c.hash in upstreamCommitHashes or c.hash == firstUpstreamReference)

  @lazy
  def commits(self):
    """All commits made to this branch since it left upstream, including merges."""
    commits = []
    for c in self.allCommits:
      if c == self.upstreamCommit:
        break
      if c.merges:
        mergedBranches = tuple(type(self).REV_MAP.get(rev, rev) for rev in c.merges)
        # WORKAROUND: Filter out branches that aren't in the subject
        # TODO: Drop REV_MAP and only consider branches that are in the subject, so we don't
        #       'hide' valid merges with invalid ones.
        mergedBranches = tuple(b for b in mergedBranches
                                if type(b) != Branch or "'%s'" % b.name in c.subject)
        commits.append(Commit(c.hash, c.subject, mergedBranches))
      else:
        commits.append(c)
    return tuple(commits)

  @lazy
  def parents(self):
    """All parents of this branch, whether upstream or merged."""
    if self.upstream is None:
      return frozenset()
    parents = [p for c in self.commits for p in c.merges if type(p) == Branch]
    parents.append(self.upstream)
    return frozenset(parents)

  @lazy
  def children(self):
    """All branches which have this branch as upstream or merged."""
    return frozenset(b for b in type(self).ALL if self in b.parents)

  @lazy
  def modtime(self):
    """The timestamp of the latest commit to this branch."""
    with Sh("git", "log", "-n5", "--format=%at", self.name, "--") as log:
      for line in log:
        modtime = int(line)
        if modtime != 1:
          return datetime.utcfromtimestamp(modtime)
    return None

  @lazy
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
          allCommits.update(Sh("git", "log", "--first-parent", "--format=%H", rev))
    parentCommits = set()
    for p in self.parents:
      for c in p.allCommits:
        if c.hash in allCommits:
          break
        parentCommits.add(c.hash)
    return len(parentCommits)

