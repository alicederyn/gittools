import re, travispy, warnings
from collections import defaultdict
from git import Branch
from lazy import lazy
from multiprocessing.pool import ThreadPool
from travispy import TravisPy
from utils import Sh, ShError

class TravisClient(object):

  SLUG_REGEX = re.compile('^git[@]github[.]com:(.*)[.]git$')

  @lazy
  @property
  def _githubToken(self):
    return Sh('git', 'config', 'github.token').next()

  @lazy
  @property
  def _remoteSlugs(self):
    """Remote 'slug' of any GitHub repos, keyed by remote name."""
    try:
      raw = Sh('git', 'config', '--get-regexp', 'remote\..*\.url')
      remotes = {}
      for l in raw:
        key, url = l.split(' ', 1)
        name = key.split('.', 1)[-1].rsplit('.', 1)[0]
        slug_match = TravisClient.SLUG_REGEX.match(url)
        if slug_match:
          remotes[name] = slug_match.group(1)
      return remotes
    except ShError, e:
      if e.returncode == 1:
        return {}
      raise

  @lazy
  @property
  def _remotesByBranchName(self):
    remotes = defaultdict(set)
    for remoteBranch in Branch.REMOTES:
      remote, branchName = remoteBranch.name.split('/', 1)
      if remote in self._remoteSlugs:
        remotes[branchName].add(remote)
    return remotes

  def _travis(self):
    with warnings.catch_warnings():
      warnings.filterwarnings('ignore', message='.*InsecurePlatformWarning.*')
      return TravisPy.github_auth(self._githubToken)

  @lazy
  @property
  def _ciStatuses(self):
    if not self._remotesByBranchName:
      return defaultdict(dict)
    pool = ThreadPool(20)
    try:
      with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='.*InsecurePlatformWarning.*')
        status = defaultdict(dict)
        todos = [(branch, remote) 
                 for branch, remotes in self._remotesByBranchName.iteritems()
                 for remote in remotes]
        if todos:
          travis = self._travis()
          remoteSlugs = self._remoteSlugs
          def fetchStatus(todo):
            branch, remote = todo
            slug = remoteSlugs[remote]
            try:
              b = travis.branch(branch, slug)
              status[branch][remote] = b.color
            except travispy.errors.TravisError, e:
              pass
          pool.map(fetchStatus, todos)
        return status
    except IOError:
      return defaultdict(dict)
    finally:
      pool.close()

  def ciStatus(self, branch):
    return self._ciStatuses[branch.name]

