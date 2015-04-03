import re
from collections import defaultdict, namedtuple
from datetime import datetime
from utils import first, lazy, LazyList, Sh, ShError

__all__ = ['revparse', 'getUpstreamBranch', 'Branch']

def revparse(*args):
  """Returns the result of `git rev-parse *args`."""
  try:
    return str(Sh("git", "rev-parse", *args)).strip()
  except ShError, e:
    raise ValueError(e)

def getUpstreamBranch(branch):
  """Returns the upstream of branch, or None if none is set."""
  try:
    return revparse("--abbrev-ref", branch + "@{upstream}")
  except ValueError:
    return None

RefLine = namedtuple('RefLine', 'timestamp hash')
Commit = namedtuple("Commit", "hash subject merges")

class Branch(object):
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

  @classmethod
  def clear_cache(cls):
    for k, p in vars(cls).iteritems():
      if k == k.upper():
        try:
          p.clear()
        except AttributeError:
          pass

  @lazy
  def HEAD(cls):
    """The current HEAD branch, or None if head is detached."""
    try:
      return cls(revparse("--abbrev-ref", "HEAD"))
    except ValueError:
      return None

  @lazy
  def ALL(cls):
    """The set of all (local) branches."""
    names = revparse("--abbrev-ref", "--branches").splitlines()
    return frozenset(cls(name) for name in names)

  @lazy
  def REMOTES(cls):
    """The set of all remote branches that have a local branch of the same name."""
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

