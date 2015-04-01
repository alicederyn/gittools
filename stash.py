import getpass, requests, json, keyring, posixpath, urlparse, warnings
from collections import Counter, defaultdict
from itertools import count
from utils import Branch, Sh, ShError, lazy

class Stash(object):

  PARAMS = {
    'verify' : False,
  }
  STATUS_MAP = {
    'successful' : 'green',
    'inProgress' : 'orange',
    'failed' : 'red',
  }

  @lazy
  def _servers(self):
    """Remote Stash servers, keyed by remote name."""
    try:
      raw = Sh('git', 'config', '--get-regexp', 'remote\..*\.url')
      remotes = {}
      for l in raw:
        key, server = l.split(' ', 1)
        name = key.split('.', 1)[-1].rsplit('.', 1)[0]
        url = urlparse.urlparse(server)
        if url.hostname and url.hostname.startswith('stash.'):
          remotes[name] = 'https://%s' % url.hostname
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

  @lazy
  def _auth(self):
    user = getpass.getuser()
    auth = {}
    for server in set(self._servers.values()):
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

  def _getCommitStats(self, server, commits):
    try:
      with warnings.catch_warnings():
        warnings.simplefilter(
            'ignore', requests.packages.urllib3.exceptions.InsecureRequestWarning)
        r = requests.post(posixpath.join(server, 'rest/build-status/1.0/commits/stats'),
                          data = json.dumps(list(commits)),
                          auth = self._auth[server],
                          headers = { 'content-type': 'application/json' },
                          **Stash.PARAMS)
      if r.status_code >= 400:
        raise RuntimeError('Got %d fetching %s as %s' % (r.status_code, url, auth[0]))
      return r.json()
    except IOError:
      return {}

  @lazy
  def _ciStatuses(self):
    branchesByCommit = defaultdict(set)
    commitsByServer = defaultdict(set)
    for remoteBranch in Branch.REMOTES:
      remote, branchName = remoteBranch.name.split('/', 1)
      if remote in self._servers:
        server = self._servers[remote]
        commit = remoteBranch.latestCommit.hash
        commitsByServer[server].add(commit)
        branchesByCommit[commit].add(branchName)
    statsByBranch = defaultdict(Counter)
    for server, commits in commitsByServer.iteritems():
      for commit, stats in self._getCommitStats(server, commits).iteritems():
        colorCodedStats = { Stash.STATUS_MAP[k] : v for k, v in stats.iteritems()
                            if k in Stash.STATUS_MAP }
        for branch in branchesByCommit[commit]:
          statsByBranch[branch].update(colorCodedStats)
    return statsByBranch

  def ciStatus(self, branch):
    return dict(zip(count(0), self._ciStatuses[branch.name].elements()))

