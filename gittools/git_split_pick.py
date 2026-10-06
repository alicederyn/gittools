"""Usage: git-split-pick [options] <commit>

Interactively cherry-picks the given commit in several parts.
Equivalent to repeatedly running `git add --patch <commit>; git commit`
until all parts of the commit have landed (or no more parts are accepted
during the patch).

Options:
    -h --help               Show this screen.
"""

import subprocess
import sys
from subprocess import DEVNULL, PIPE

from docopt import docopt

from . import git


def anyUnstagedChanges():  # Includes untracked
    tracked = subprocess.call(
        ["git", "diff-files", "--quiet", "--ignore-submodules", "--"]
    )
    untracked = subprocess.Popen(
        ["git", "ls-files", "--others", "--exclude-standard"], stdout=PIPE, stderr=PIPE
    )
    (stdout, stderr) = untracked.communicate()
    return (tracked != 0) or bool(stdout.strip())


def anyStagedChanges():
    args = [
        "git",
        "diff-index",
        "--cached",
        "--quiet",
        "HEAD",
        "--ignore-submodules",
        "--",
    ]
    return subprocess.call(args) != 0


def emptyFiles():
    idx = subprocess.run(
        ["git", "diff-index", "--cached", "--numstat", "HEAD", "--"],
        check=True,
        stdout=PIPE,
        text=True,
    ).stdout
    return [
        file
        for a, b, file in (line.split(None, 2) for line in idx.splitlines())
        if a == "0" and b == "0"
    ]


def gitAddInteractive():
    # Add all untracked files, as otherwise git add -i behaves unpleasantly
    # Cannot use git add -A -N as it also (surprisingly) adds deletions to the index
    (stdout, stderr) = subprocess.Popen(
        ["git", "ls-files", "--others", "--exclude-standard"], stdout=PIPE, stderr=PIPE
    ).communicate()
    untracked = stdout.splitlines()
    if untracked:
        subprocess.run(["git", "add", "-N", *untracked], check=True, stdout=DEVNULL)
    subprocess.call(["git", "add", "--interactive"])
    # Reset any empty files, as they're probably the untracked ones we just added
    f = emptyFiles()
    if f:
        subprocess.run(
            ["git", "reset", "--quiet", "--", *emptyFiles()], check=True, stdout=DEVNULL
        )


def splitPick(commit):
    if anyUnstagedChanges() or anyStagedChanges():
        print(
            "You have uncommitted changes that would be overwritten by a split pick",
            file=sys.stderr,
        )
        sys.exit(1)
    subprocess.run(["git", "cherry-pick", "-n", commit], check=True, stdout=DEVNULL)
    subprocess.run(["git", "reset", "--quiet"], check=True, stdout=DEVNULL)
    while anyUnstagedChanges() or anyStagedChanges():
        gitAddInteractive()
        if not anyStagedChanges():  # User is done
            subprocess.run(["git", "reset", "--hard"], check=True, stdout=DEVNULL)
            subprocess.run(["git", "clean", "-d", "-f"], check=True, stdout=DEVNULL)
            break
        subprocess.call(
            ["git", "commit", "--reedit-message=" + commit, "--reset-author"]
        )


def main():
    arguments = docopt(__doc__)
    splitPick(git.revparse(arguments["<commit>"]))
