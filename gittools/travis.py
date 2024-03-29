import re, travispy, warnings
from collections import defaultdict
from .git import Branch, lazy_git_property
from .lazy import lazy
from multiprocessing.pool import ThreadPool
from .scheduling import NotDoneException, Poller, Scheduler
from travispy import TravisPy
from .utils import Sh, ShError
from weakref import WeakValueDictionary

class TravisClient(object):

  SLUG_REGEX = re.compile('^git[@]github[.]com:(.*)[.]git$')

  def __init__(self):
    self._pollers = WeakValueDictionary()
    self._scheduler = Scheduler(1) # TravisPy.github_auth is not thread-safe

  @lazy_git_property(watching = 'config')
  def _githubToken(self):
    return next(Sh('git', 'config', 'github.token'))

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
    except ShError as e:
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

  def _auth(self, token):
    if hasattr(self, '_cachedAuth'):
      return self._cachedAuth
    with warnings.catch_warnings():
      warnings.filterwarnings('ignore', message='.*InsecurePlatformWarning.*')
      self._cachedAuth = TravisPy.github_auth(token)
      return self._cachedAuth

  def _getRemoteStatus(self, token, slug, branch, hash):
    auth = self._auth(token)
    return TravisClient.fetchStatus(auth, slug, branch, hash)

  @staticmethod
  def fetchStatus(travis, slug, branch, hash):
    branchInfo = travis.branch(branch, slug)
    if branchInfo.commit.sha == hash:
      return travis.branch(branch, slug).color
    else:
      return None

  @lazy
  @property
  def _futuresByBranchAndRemote(self):
    if not self._remotesByBranchName:
      return defaultdict(dict)
    with warnings.catch_warnings():
      warnings.filterwarnings('ignore', message='.*InsecurePlatformWarning.*')
      try:
        token = self._githubToken
      except ShError:
        return defaultdict(dict)
      remoteSlugs = self._remoteSlugs
    futures = defaultdict(dict)
    for branch, remotes in self._remotesByBranchName.items():
      for remote in remotes:
        slug = remoteSlugs[remote]
        hash = Branch("%s/%s" % (remote, branch)).latestCommit.hash
        if (slug, branch, hash) in self._pollers:
          poller = self._pollers[(slug, branch, hash)]
        else:
          poller = Poller(self._scheduler, self._getRemoteStatus, token, slug, branch, hash)
          self._pollers[(slug, branch, hash)] = poller
        futures[branch][remote] = lazy(poller)
    self._futures = futures # Ensure pollers are not garbage-collected too soon
    return futures

  @lazy
  def ciStatus(self, branch):
    stats = defaultdict(dict)
    for remote, future in self._futuresByBranchAndRemote[branch.name].items():
      try:
        stats[remote] = future()
      except (IOError, NotDoneException, travispy.errors.TravisError):
        pass
    return stats
