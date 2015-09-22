import getpass, json, keyring, logging, posixpath, re, requests, urlparse, warnings
from collections import Counter, defaultdict
from git import Branch, lazy_git_property
from itertools import count
from scheduling import NotDoneException, Poller, Scheduler
from lazy import lazy
from utils import Sh, ShError

class Stash(object):

  STASH_REGEX = re.compile('^git[@](stash[^:]*):.*$')

  PARAMS = {
    'verify' : False,
  }
  STATUS_MAP = {
    'successful' : 'green',
    'inProgress' : 'yellow',
    'failed' : 'red',
  }

  def __init__(self):
    self._pollers = {}

  @staticmethod
  def hostname(url):
    stash_match = Stash.STASH_REGEX.match(url)
    if stash_match:
      match = stash_match.group(1)
      if match == 'stash' or match.startswith('stash.'):
        return match
    url = urlparse.urlparse(url)
    if url.hostname:
      if url.hostname == 'stash' or url.hostname.startswith('stash.'):
        return url.hostname
    return None

  @lazy_git_property(watching = 'config')
  def _serversByRemote(self):
    """Remote Stash servers, keyed by remote name."""
    try:
      raw = Sh('git', 'config', '--get-regexp', 'remote\..*\.url')
      remotes = {}
      for l in raw:
        key, server = l.split(' ', 1)
        name = key.split('.', 1)[-1].rsplit('.', 1)[0]
        hostname = Stash.hostname(server)
        if hostname:
          remotes[name] = 'https://%s' % hostname
      return remotes
    except ShError, e:
      if e.returncode == 1:
        return {}
      raise

  def _getWithAuth(self, url, auth):
    with warnings.catch_warnings():
      warnings.simplefilter(
          'ignore', requests.packages.urllib3.exceptions.InsecureRequestWarning)
      r = requests.get(url, auth = auth, **Stash.PARAMS)
      if r.status_code >= 400:
        raise RuntimeError('Got %d fetching %s as %s' % (r.status_code, url, auth[0]))
      return r.json()

  def _getAuth(self, servers):
    user = getpass.getuser()
    auth = {}
    for server in servers:
      password = keyring.get_password(server, user)
      if password is None:
        password = getpass.getpass('Password for %s? ' % server)
        # Verify the password
        self._getWithAuth(
            posixpath.join(server, 'rest/api/1.0/application-properties'),
            (user, password))
        keyring.set_password(server, user, password)
      auth[server] = (user, password)
    return auth

  def _getRawServerStats(self, server, commits, auth):
    try:
      with warnings.catch_warnings():
        warnings.simplefilter(
            'ignore', requests.packages.urllib3.exceptions.InsecureRequestWarning)
        url = posixpath.join(server, 'rest/build-status/1.0/commits/stats')
        data = json.dumps(list(commits))
        r = requests.post(url,
                          data = data,
                          auth = auth,
                          headers = { 'content-type': 'application/json' },
                          **Stash.PARAMS)
      if r.status_code >= 400:
        raise RuntimeError('Got %d fetching %s as %s' % (r.status_code, url, auth[0]))
      return r.json()
    except requests.ConnectionError:
      return {}
    except IOError:
      logging.exception("Failed to get stats for Stash server %s" % server)
      return {}

  def _getServerStatsByBranch(self, server, commitsByServer, branchesByCommit, auth):
    statsByBranch = defaultdict(Counter)
    commits = commitsByServer[server]
    rawStats = self._getRawServerStats(server, commits, auth)
    for commit, stats in rawStats.iteritems():
      colorCodedStats = { Stash.STATUS_MAP[k] : v for k, v in stats.iteritems()
                          if k in Stash.STATUS_MAP }
      for branch in branchesByCommit[commit]:
        statsByBranch[branch].update(colorCodedStats)
    return statsByBranch

  @lazy
  @property
  def _futuresByServer(self):
    if not self._serversByRemote:
      return {}

    servers = frozenset(self._serversByRemote.values())
    authByServer = self._getAuth(servers)
    branchesByCommit = defaultdict(set)
    commitsByServer = defaultdict(set)
    for remoteBranch in Branch.REMOTES:
      remote, branchName = remoteBranch.name.split('/', 1)
      if remote in self._serversByRemote:
        server = self._serversByRemote[remote]
        commit = remoteBranch.latestCommit.hash
        commitsByServer[server].add(commit)
        branchesByCommit[commit].add(branchName)

    _oldPollers = self._pollers
    try:
      with Scheduler() as scheduler:
        return { server : lazy(Poller(scheduler, self._getServerStatsByBranch, server,
                                 commitsByServer, branchesByCommit, authByServer[server]))
                for server in servers }
    finally:
      pass

  @lazy
  @property
  def _statsByBranch(self):
    statsByBranch = defaultdict(Counter)
    for serverStatsByBranch in self._futuresByServer.itervalues():
      try:
        for b, stats in serverStatsByBranch().iteritems():
          statsByBranch[b].update(stats)
      except NotDoneException:
        pass
    return statsByBranch

  def ciStatus(self, branch):
    return dict(zip(count(0), self._statsByBranch[branch.name].elements()))

