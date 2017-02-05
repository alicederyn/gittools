import re, travispy, warnings
from collections import defaultdict
from git import Branch, lazy_git_property
from lazy import lazy
from multiprocessing.pool import ThreadPool
from scheduling import NotDoneException, Poller, Scheduler
from travispy import TravisPy
from utils import Sh, ShError
from weakref import WeakValueDictionary

class TravisClient(object):

  SLUG_REGEX = re.compile('^git[@]github[.]com:(.*)[.]git$')

  def __init__(self):
    # Kick off asynchronous requests
    self._pollers = WeakValueDictionary()
    self._scheduler = Scheduler(1) # TravisPy.github_auth is not thread-safe
    self._futuresByBranchAndRemote

  @lazy_git_property(watching = 'config')
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

  def _auth(self, token):
    with warnings.catch_warnings():
      warnings.filterwarnings('ignore', message='.*InsecurePlatformWarning.*')
      # TODO: Run this on a single worker thread and have the others wait
      return TravisPy.github_auth(token)

  def _getRemoteStatus(self, token, slug, branch):
    auth = self._auth(token)
    return TravisClient.fetchStatus(auth, slug, branch)

  @staticmethod
  def fetchStatus(travis, slug, branch):
    return travis.branch(branch, slug).color

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
    for branch, remotes in self._remotesByBranchName.iteritems():
      for remote in remotes:
        slug = remoteSlugs[remote]
        if (slug, branch) in self._pollers:
          poller = self._pollers[(slug, branch)]
        else:
          poller = Poller(self._scheduler, self._getRemoteStatus, token, slug, branch)
          self._pollers[(slug, branch)] = poller
        futures[branch][remote] = lazy(poller)
    self._futures = futures # Ensure pollers are not garbage-collected too soon
    return futures

  @lazy
  def ciStatus(self, branch):
    stats = defaultdict(dict)
    for remote, future in self._futuresByBranchAndRemote[branch.name].iteritems():
      try:
        stats[remote] = future()
      except (IOError, NotDoneException, travispy.errors.TravisError):
        pass
    return stats
