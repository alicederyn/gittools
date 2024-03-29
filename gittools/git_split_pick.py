# coding=utf-8
"""Usage: git-split-pick [options] <commit>

Interactively cherry-picks the given commit in several parts.
Equivalent to repeatedly running `git add --patch <commit>; git commit`
until all parts of the commit have landed (or no more parts are accepted
during the patch).

Options:
    -h --help               Show this screen.
"""
import sh, subprocess, sys, time
from . import git
from docopt import docopt
from subprocess import PIPE

def anyUnstagedChanges():  # Includes untracked
  tracked = subprocess.call(['git', 'diff-files', '--quiet', '--ignore-submodules', '--'])
  untracked = subprocess.Popen(['git', 'ls-files', '--others', '--exclude-standard'],
                              stdout=PIPE, stderr=PIPE)
  (stdout, stderr) = untracked.communicate()
  return (tracked != 0) or bool(stdout.strip())

def anyStagedChanges():
  args = ['git', 'diff-index', '--cached', '--quiet', 'HEAD', '--ignore-submodules', '--']
  return (subprocess.call(args) != 0)

def emptyFiles():
  idx = sh.git('diff-index', '--cached', '--numstat', 'HEAD', '--', _iter=True, _tty_out=False)
  return [file for a, b, file in
          (l.split(None, 2) for l in idx.splitlines())
          if a == '0' and b == '0']

def gitAddInteractive():
  # Add all untracked files, as otherwise git add -i behaves unpleasantly
  # Cannot use git add -A -N as it also (surprisingly) adds deletions to the index
  (stdout, stderr) = (subprocess
      .Popen(['git', 'ls-files', '--others', '--exclude-standard'], stdout=PIPE, stderr=PIPE)
      .communicate())
  untracked = stdout.splitlines()
  if untracked:
    sh.git.add(N=True, *untracked).wait()
  subprocess.call(['git', 'add', '--interactive'])
  # Reset any empty files, as they're probably the untracked ones we just added
  f = emptyFiles()
  if f:
    sh.git.reset('--', *emptyFiles())

def splitPick(commit):
  if anyUnstagedChanges() or anyStagedChanges():
    print("You have uncommitted changes that would be overwritten by a split pick", file=sys.stderr)
    sys.exit(1)
  sh.git('cherry-pick', commit, n=True).wait()
  sh.git.reset().wait()
  while anyUnstagedChanges() or anyStagedChanges():
    gitAddInteractive()
    if not anyStagedChanges():  # User is done
      sh.git.reset(hard=True)
      sh.git.clean(d=True, f=True)
      break
    subprocess.call(['git', 'commit', '--reedit-message=' + commit, '--reset-author'])

def main():
  arguments = docopt(__doc__)
  splitPick(git.revparse(arguments['<commit>']))
