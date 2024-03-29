# coding=utf-8
"""Usage: git-graph-branch [options]

Symbols:
    🔷   This branch is in sync with a remote of the same name
    🔶   This branch is out of sync with a remote of the same name
    ⌛   A CI build is in progress for this branch
    💚   A CI build has succeeded for this branch
    🔥   A CI build has failed for this branch

Options:
    -h --help               Show this screen.
    -w, --watch             Continue to watch for git repo changes after printing the graph.
    --profile               Profiles the app.
    -l, --local             Only display information available from the local git repo.
                            Continuous integration results will not be fetched.
"""
import logging, re, sys, traceback
from collections import Counter, defaultdict
from datetime import datetime
from docopt import docopt
from .git import Branch, revparse
from .layout import layout
from .lazy import lazy, lazy_invalidation
from .travis import TravisClient
from .utils import window_size

STATUS_ICONS = {
  'yellow': '⌛',
  'green': '💚',
  'red': '🔥',
}

def allChildren(branch):
  allChildren = set()
  todo = [branch]
  while todo:
    b = todo.pop()
    for child in b.children:
      if child not in allChildren:
        todo.append(child)
        allChildren.add(child)
  return allChildren

class BranchBlockers(object):
  def __init__(self, branches):
    self._branches = set(branches)
    self._blockers = {}

  def keys(self):
    return self._branches

  def __len__(self):
    return len(self._branches)

  def __contains__(self, branch):
    return branch in self._branches

  def __getitem__(self, branch):
    if not branch in self._branches:
      raise KeyError(branch)
    if not branch.children:
      return branch
    children = self._blockers.get(branch)
    if children is None:
      self._blockers[branch] = children = list(allChildren(branch))
      children.sort(key = lambda b : b.modtime)
    while children and children[-1] not in self._branches:
      children.pop()
    return self[children[-1]] if children else branch

  def __delitem__(self, branch):
    self._branches.remove(branch)
    if branch in self._blockers:
      del self._blockers[branch]

class PriorityBranchIterator(object):
  def __init__(self, blockers):
    self._blockers = blockers
    self._queue = list(blockers.keys())
    self._queue.sort(key = lambda b: b.modtime)
    self._priorities = []

  def __iter__(self):
    return self

  def __next__(self):
    blocker = None
    while self._priorities and self._priorities[-1] not in self._blockers:
      self._priorities.pop()
    while self._queue and self._queue[-1] not in self._blockers:
      self._queue.pop()
    if self._priorities:
      blocker = self._blockers[self._priorities[-1]]
    elif self._queue:
      blocker = self._blockers[self._queue[-1]]
    else:
      raise StopIteration()
    assert blocker in self._blockers
    self._priorities.extend(p for p in blocker.parents
                            if p in self._blockers and p not in self._priorities)
    del self._blockers[blocker]
    return blocker

@lazy
def layoutAllBranches():
  localBranches = Branch.ALL
  relevantBranches = set(localBranches)
  # Merge in any remote branches that are upstream of a local branch of a different name
  for branch in localBranches:
    if branch.upstream is not None and branch.upstream not in localBranches:
      if branch.upstream.name.split('/', 1)[-1] != branch.name:
        relevantBranches.add(branch.upstream)
  branches = sorted(relevantBranches, key = lambda b : b.modtime or datetime.fromtimestamp(1))
  branches = tuple(PriorityBranchIterator(BranchBlockers(branches)))
  return list(zip(branches, layout(branches)))

ESCAPE = re.compile(r'\x1b[\[][^@-~]*[@-~]')
def stripEscapeCodes(s):
  return ESCAPE.sub('', s)

SURROGATE_PAIR = re.compile('[\ud800-\udbff][\udc00-\udfff]', re.UNICODE)
# \U0001f538 - Small orange diamond
# \U0001f539 - Small blue diamond
DOUBLE_WIDTH = re.compile('[\u1b00-\u1bff\U0001f538\U0001f539]|[\u3dd8][\udc00-\udfff]', re.UNICODE)
def displayLen(s):
  return len(SURROGATE_PAIR.sub('.', DOUBLE_WIDTH.sub('..', s)))

def printGraph(clearScreen = False, ciTools = ()):
  remotes = frozenset(b.name for b in Branch.REMOTES)
  remoteHashes = dict(list(zip(remotes, revparse(*remotes).splitlines())))
  localsWithRemotes = defaultdict(set)
  for r in remotes:
    localsWithRemotes[r.split('/', 1)[-1]].add(r)

  done = set()
  awaitingParents = []
  firstChilds = []

  if clearScreen:
    sys.stdout.write('\x1b[0;0H')

  if sys.stdout.isatty():
    def control(chars):
      sys.stdout.write(chars)
  else:
    def control(chars):
      pass

  if sys.stdout.isatty():
    rows, columns = window_size()

  for b, row in layoutAllBranches():
    graph = str(row) + '  '
    name = b.name
    remotes = ''
    if b.name in localsWithRemotes:
      version = b.allCommits[0].hash
      if any(remoteHashes[r] != version for r in localsWithRemotes[b.name]):
        remotes = ' 🔶'
      else:
        remotes = ' 🔷'
    ciStatus = ''
    ciStatuses = [ status for tool in ciTools for status in list(tool.ciStatus(b).values()) if status ]
    if ciStatuses:
      ciStatus = ' ' + ''.join(STATUS_ICONS[status] for status in ciStatuses)
    unmerged = ''
    if b.unmerged > 0:
      unmerged = ' \x1b[1;31m'
      if b.unmerged <= 20:
        unmerged += '%s unmerged' % chr(0x245F + b.unmerged)
      else:
        unmerged += ' [%d unmerged]' % b.unmerged
      unmerged += '\x1b[0m'

    if sys.stdout.isatty():
      line = graph + name + remotes + ciStatus + unmerged

      # Shorten the CI statuses if the line is too long
      if displayLen(stripEscapeCodes(line)) > columns and ciStatuses:
        altCiStatus = ' '
        for status, count in Counter(ciStatuses).items():
          altCiStatus += STATUS_ICONS[status]
          if count > 1:
            altCiStatus += '×%d' % count
        if displayLen(altCiStatus) < displayLen(ciStatus):
          ciStatus = altCiStatus
        line = graph + name + remotes + ciStatus + unmerged

      # Remove the "unmerged" text if the line is too long
      if displayLen(stripEscapeCodes(line)) > columns and b.unmerged > 0:
        unmerged = ' \x1b[1;31m'
        if b.unmerged <= 20:
          unmerged += '%s ' % chr(0x245F + b.unmerged)
        else:
          unmerged += '[%d]' % b.unmerged
        unmerged += '\x1b[0m'
        line = graph + name + remotes + ciStatus + unmerged

      # Remove the space at the start of the CI statuses if the line is too long
      if displayLen(stripEscapeCodes(line)) > columns:
        ciStatus = ciStatus[1:]
        line = graph + name + remotes + ciStatus + unmerged

      # Reduce the branch name down to 10 characters if the line is too long
      if displayLen(stripEscapeCodes(line)) > columns and len(name) > 10:
        space = max(10, columns + len(name) - displayLen(stripEscapeCodes(line)))
        name = b.name
        if '/' in name:
          dir, name = name.rsplit('/', 1)
          name = dir[:max(0,space - 2 - len(name))] + '…/' + name
        if len(name) > space:
          name = name[:space - 1] + '…'
        line = graph + name + remotes + ciStatus + unmerged

    if b == Branch.HEAD:
      name = '\x1b[1;35m' + name + '\x1b[0m'
    line = graph + name + remotes + ciStatus + unmerged

    if not sys.stdout.isatty():
      line = stripEscapeCodes(line)
    sys.stdout.write(line)

    if clearScreen:
      control('\x1b[K')
    sys.stdout.write('\n')

  if clearScreen:
    control('\x1b[J')
    sys.stdout.flush()

def getPrintGraphArgs(options):
  def select(name, **algorithms):
    try:
      return algorithms[options[name]]
    except KeyError:
      sys.stderr.write('%s not a valid choice for %s (must be one of: %s)'
                       % (options[name], name, ", ".join(list(algorithms.keys()))))
  return {
    'ciTools' : () if options['--local'] else (TravisClient(),)
  }

def main():
  logging.basicConfig()
  options = docopt(__doc__)
  if options['--watch']:
    assert sys.stdout.isatty()
  printGraphArgs = getPrintGraphArgs(options)
  if options['--watch']:
    try:
      @lazy
      def action():
        try:
          printGraph(clearScreen = True, **printGraphArgs)
        except Exception:
          sys.stdout.write('\n')
          sys.stdout.flush()
          traceback.print_exc(3)
          sys.stdout.write('\x1b[J')
          sys.stdout.flush()
      with lazy_invalidation():
        action.continually()
    except KeyboardInterrupt:
      pass
  elif options['--profile']:
    import cProfile
    cProfile.run('printGraph(**printGraphArgs)')
  else:
    printGraph(**printGraphArgs)

