import os, re, select, subprocess, threading
from collections import defaultdict, namedtuple
from datetime import datetime
from itertools import chain

__all__ = ['first', 'lazy', 'revparse', 'getUpstreamBranch', 'Branch', 'Commit']

class ShError(Exception):
  def __init__(self, returncode, cmd, stderr):
    self.returncode = returncode
    self.cmd = cmd
    self.stderr = stderr

  def __str__(self):
    message = '%s exited with return code %s' % (self.cmd[0], self.returncode)
    stderr_lines = ['    ' + l for l in self.stderr.splitlines()]
    if stderr_lines:
      message += '\n' + '\n'.join(stderr_lines)
    return message

  def __repr__(self):
    return 'ShError(%s, %s, %s)' % (repr(self.returncode), repr(self.cmd), repr(self.stderr))

class Sh(object):
  def __init__(self, *cmd):
    self.cmd = cmd
    self._process = subprocess.Popen(cmd, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
    self._out = []
    self._err = []

  def __iter__(self):
    return self

  def next(self):
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
      except select.error, e:
        if e.args[0] == errno.EINTR:
          continue
        raise
      if self._process.stderr in rlist:
        data = os.read(self._process.stderr.fileno(), 1024)
        if data == "":
          self._process.stderr.close()
          read_set.remove(self._process.stderr)
          self._process.stderr = None
        else:
          self._err.append(data)
      if self._process.stdout in rlist:
        data = os.read(self._process.stdout.fileno(), 1024)
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
    out, err = self._process.communicate()
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

def revparse(*args, **kwargs):
  try:
    return str(Sh("git", "rev-parse", *args)).strip()
  except ShError, e:
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
      for l in raw[b]:
        m = rx.search(l)
        if m:
          branch_logs.append(RefLine(int(m.group(1)), m.group(2)))
    return ref_logs

  @lazy
  def _COMMITS(cls):
    raw = {}
    for b in chain(cls.ALL, cls.REMOTES):
      raw[b] = Sh("git", "log", "--first-parent", "--format=%H:%P:%s", b.name)
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
    return type(self)._REF_LOGS.get(self, ())

  @lazy
  def allCommits(self):
    """All commits made to this branch, in reverse chronological order.

    Merges will only list commit hashes, not branches.

    """
    return type(self)._COMMITS[self]

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
    with Sh("git", "log", "-n5", "--format=%at", self.name, "--") as log:
      for line in log:
        modtime = int(line)
        if modtime != 1:
          return datetime.utcfromtimestamp(modtime)
    return None

  @lazy
  def unmerged(self):
    """The number of parent commits that have not been pulled to this branch."""
    allCommits = set(c.hash for c in self.allCommits)
    parentCommits = set()
    for p in self.parents:
      for c in p.allCommits:
        if c.hash in allCommits:
          break
        parentCommits.add(c.hash)
    return len(parentCommits)

