import getpass, keyring, posixpath, requests, sh, warnings
from collections import defaultdict
from multiprocessing.pool import ThreadPool
from utils import Branch, lazy

class Bamboo(object):

  PARAMS = {
    'verify' : False,
    'headers' : {'accept' : 'application/json'}
  }
  STATUS_MAP = {
    'Successful' : 'green',
    'Failed' : 'red',
  }

  @lazy
  def _githubToken(self):
    return str(sh.git.config('github.token', _tty_out=False)).strip()

  @lazy
  def _servers(self):
    """Remote Bamboo servers, keyed by remote name."""
    try:
      raw = sh.git.config('--get-regexp', 'bamboo\..*\.url', _tty_out=False, _iter=True)
      remotes = {}
      for l in raw:
        key, server = l.strip().split(' ', 1)
        name = key.split('.', 1)[-1].rsplit('.', 1)[0]
        remotes[name] = server
      return remotes
    except sh.ErrorReturnCode_1:
      return {}

  def _getWithAuth(self, url, auth):
    with warnings.catch_warnings():
      warnings.simplefilter(
          'ignore', requests.packages.urllib3.exceptions.InsecureRequestWarning)
      r = requests.get(url, auth = auth, **Bamboo.PARAMS)
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
            posixpath.join(server, 'rest/api/latest/currentUser'),
            (user, password))
        keyring.set_password(server, user, password)
      auth[server] = (user, password)
    return auth

  def _get(self, server, path):
    return self._getWithAuth(posixpath.join(server, 'rest/api/latest', path), self._auth[server])

  @lazy
  def _ciStatuses(self):
    status = defaultdict(dict)
    def fetchStatus(todo):
      branchName, remote, server, commit = todo
      r = self._get(server, 'result/byChangeset/%s?max-result=1' % (commit.hash,))
      try:
        statusText = r['results']['result'][0]['state']
        status[branchName][remote] = Bamboo.STATUS_MAP[statusText]
      except LookupError:
        pass

    pool = ThreadPool(20)
    try:
      todos = []
      for remoteBranch in Branch.REMOTES:
        remote, branchName = remoteBranch.name.split('/', 1)
        if remote in self._servers:
          server = self._servers[remote]
          commit = remoteBranch.latestCommit
          todos.append((branchName, remote, server, commit))
      pool.map(fetchStatus, todos)
    finally:
      pool.close()
    return status

  def ciStatus(self, branch):
    return self._ciStatuses[branch.name]

