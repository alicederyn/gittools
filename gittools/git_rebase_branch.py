"""Usage:
    git-rebase-branch [--start] [options] [<branch>]
    git-rebase-branch --create <branch>
    git-rebase-branch --commit
    git-rebase-branch --reset <branch>
    git-rebase-branch --edit-script <editor> <template> <script>
    git-rebase-branch --merge <branch> ...

Options:
    --exec=<cmd>     Append "exec <cmd>" after each line creating a commit in the final
                     history.
    --onto=<branch>  Starting point at which to create the new commits; defaults to the
                     upstream branch. The upstream branch will be updated to match the
                     new value when the rebase completes.
    -n, --dry-run    Don't execute anything; just dump the intermediate commands
"""

import os
import tempfile

import sh
from docopt import docopt

from .git import Branch, getUpstreamBranch, revparse

rebase_branch = "git rebase-branch"


def route(to, tree):
    stack = [to]
    while tree[stack[-1]] in tree:
        stack.append(tree[stack[-1]])
    stack.reverse()
    return stack


def getRebaseDir():
    gitdir = revparse("--git-dir")
    rebaseDir = os.path.join(gitdir, "rebase-merge")
    return rebaseDir


def getBranchesFile():
    rebaseDir = getRebaseDir()
    rebasing = os.path.isdir(rebaseDir)
    assert rebasing
    branchesFile = os.path.join(rebaseDir, "branch-snapshots")
    return branchesFile


def allChildren(branch):
    children = set()
    todo = [branch]
    while todo:
        b = todo.pop(0)
        if b not in children:
            children.add(b)
            todo.extend(b.children)
    return children


def getRebaseArgs(root, execCmd, onto):
    args = ("git", "rebase", "-i", root.name, root.name)

    scriptLines = []
    todo = [root]
    blocked = allChildren(
        root
    )  # Initially, all children will require root to be completed
    last = None
    done = set()
    resetNextCommit = False
    while todo:
        branch = todo.pop()
        if branch not in done:
            blocked.remove(branch)
            done.add(branch)
            for child in branch.children:
                if child in blocked and not any(c in blocked for c in child.parents):
                    todo.append(child)
            scriptLines.append(f"# Branch {branch.name}")
            if onto is not None:
                scriptLines.append(f"exec {rebase_branch} --reset {onto}")
                onto = None
            elif branch.upstream is None:
                resetNextCommit = True
            elif branch.upstream is not last:
                scriptLines.append(
                    f"exec {rebase_branch} --reset {branch.upstream.name}"
                )
            for commit in reversed(branch.commits):
                if commit.merges:
                    merges = []
                    for m in commit.merges:
                        try:
                            merges.append(m.name)
                        except AttributeError:
                            merges.append(revparse("--short", m))
                    scriptLines.append(
                        f"exec {rebase_branch} --merge {' '.join(merges)}"
                    )
                else:
                    shortHash = revparse("--short", commit.hash)
                    command = "git reset --hard" if resetNextCommit else "pick"
                    scriptLines.append(f"{command} {shortHash} # {commit.subject}")
                resetNextCommit = False
                if execCmd is not None:
                    scriptLines.append("exec " + execCmd)
            scriptLines.append(f"exec {rebase_branch} --create {branch.name}")
            scriptLines.append("")
            last = branch
    scriptLines.append(f"exec {rebase_branch} --commit")

    return (args, "\n".join(scriptLines) + "\n")


def executeRebase(gitargs, script):
    """Executes git rebase; does not return unless there is an error starting git."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(script)
    gitEditor = str(sh.git.var("GIT_EDITOR", _tty_out=False)).strip()
    env = dict(os.environ)
    env["GIT_EDITOR"] = f"{rebase_branch} --edit-script {gitEditor} {f.name}"
    os.execvpe("git", gitargs, env)


def getUncommittedBranches():
    commits = {}
    branchesFile = getBranchesFile()
    if os.path.exists(branchesFile):
        with open(branchesFile) as f:
            for line in f:
                commit, b = line.strip().split(" ", 1)
                if commit != "/":
                    commits[b] = commit
    return commits


def startAction(arguments):
    rebaseDir = getRebaseDir()
    rebasing = os.path.isdir(rebaseDir)
    assert not rebasing
    try:
        branchName = arguments["<branch>"][0]
    except IndexError:
        branchName = revparse("--abbrev-ref", "HEAD")
    branch = Branch(branchName)
    onto = arguments["--onto"]
    execCmd = arguments["--exec"]
    gitargs, script = getRebaseArgs(branch, execCmd, onto)
    if arguments["--dry-run"]:
        print(" ".join(gitargs))
        print()
        print(script)
    else:
        executeRebase(gitargs, script)


def createAction(arguments):
    branchesFile = getBranchesFile()
    branch = arguments["<branch>"][0]
    currentCommit = revparse("HEAD")
    with open(branchesFile, "a") as f:
        f.write(f"{currentCommit} {branch}\n")


def commitAction(arguments):
    branchesFile = getBranchesFile()
    with open(os.path.join(getRebaseDir(), "head-name")) as f:
        endBranch = revparse("--abbrev-ref", f.readline().strip())
    upstream = getUpstreamBranch(endBranch)
    endCommit = None
    with open(branchesFile) as f:
        for line in f:
            commit, branch = line.strip().split(" ", 1)
            if branch != "/" and commit != "/":
                if branch == endBranch:
                    endCommit = commit
                else:
                    sh.git.branch(branch, commit, f=True)
                if upstream:
                    if upstream == "/":
                        sh.git.branch("--unset-upstream", branch)
                    else:
                        sh.git.branch("-u", upstream, branch)
                if branch != endBranch:
                    print(f"Updated refs/heads/{branch}")
            upstream = branch
    if endCommit:
        sh.git.reset("--hard", endCommit)


def resetAction(arguments):
    branch = arguments["<branch>"][0]
    commits = getUncommittedBranches()
    branchesFile = getBranchesFile()
    with open(branchesFile, "a") as f:
        f.write("/ %s\n" % (branch or "/"))
    assert branch is not None  # Buggy
    if branch is None:
        sh.git("update-ref", "-d", "HEAD")
        sh.git.reset("--hard")
        from time import sleep

        sleep(2)
    elif branch in commits:
        sh.git.checkout(commits[branch])
    else:
        sh.git.reset("--hard", branch)


def mergeAction(arguments):
    branches = arguments["<branch>"]
    committedBranches = frozenset(b.name for b in Branch.ALL)
    commits = getUncommittedBranches()
    mergeArgs = []
    for branch in branches:
        assert branch in committedBranches or branch in commits
        if branch in commits:
            mergeArgs.append(commits[branch])
        else:
            mergeArgs.append(branch)
    if len(branches) == 1:
        message = f"Merge branch {branch!r}"
    else:
        message = (
            f"Merge branches {', '.join(f'{b!r}' for b in branches[:-1])}"
            f" and {branch!r}"
        )
    sh.git.merge("--no-edit", "-m", message, *mergeArgs)


def editScriptAction(arguments):
    gitEditor = arguments["<editor>"]
    template = arguments["<template>"]
    script = arguments["<script>"]
    if os.path.exists(template):
        with open(template) as fin:
            with open(script, "w") as fout:
                for line in fin:
                    fout.write(line)
        os.unlink(template)
    os.execlp(gitEditor, gitEditor, script)


def main():
    import locale

    assert (
        locale.getpreferredencoding() == "UTF-8"
    )  # Fails if we us /usr/grte/v3/bin/python2.7
    arguments = docopt(__doc__)
    if arguments["--create"]:
        createAction(arguments)
    elif arguments["--commit"]:
        commitAction(arguments)
    elif arguments["--edit-script"]:
        editScriptAction(arguments)
    elif arguments["--reset"]:
        resetAction(arguments)
    elif arguments["--merge"]:
        mergeAction(arguments)
    else:
        startAction(arguments)
