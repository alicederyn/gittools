# coding=utf-8
"""Usage: git-mirror <source> <destination>

Sets up destination as a mirror of source. All git configuration will be symlinked to source, except for current branch and staging information. This means you can work on the same repository, sharing all local commits to branches. Typically, this is most useful when you need to work on a different branch, but you have something long-running in your clone, so cannot simply change branch.
"""

import os, sys
from docopt import docopt
from shutil import rmtree
from utils import Sh, ShError

def main():
  arguments = docopt(__doc__)
  src = os.path.abspath(arguments['<source>'])
  dst = os.path.abspath(arguments['<destination>'])

  if os.path.exists(dst):
    print >> sys.stderr, 'git-mirror: %s: File exists' % (arguments['<destination>'],)
    sys.exit(100)

  os.makedirs(os.path.join(dst, '.git', 'logs'))
  # ref: refs/heads/master
  with open(os.path.join(dst, '.git', 'HEAD'), 'w') as head:
    print >> head, 'ref: refs/heads/empty'
  str(Sh('touch', os.path.join(dst, '.git', 'HEAD')))
for file in ('FETCH_HEAD', 'config', 'description', 'hooks', 'info', 'logs/refs', 'objects', 'packed-refs', 'refs', 'rr-cache'):
  try:
    os.symlink(os.path.join(src, '.git', file), os.path.join(dst, '.git', file))
  except OSError, e:
    raise OSError('%s: %s' % (e, os.path.join(dst, '.git', file)))

