import re
import sys

from .utils import Sh

GIT_URI_RE = re.compile(r"^\w+@([^:]+):(.*)\.git$")


def origin_url():
    url = str(Sh("git", "config", "--get", "remote.origin.url")).strip()
    if m := GIT_URI_RE.match(url):
        url = f"https://{m.group(1)}/{m.group(2)}"
    return url


def upstream_branch(branch):
    branch = str(Sh("git", "rev-parse", "--abbrev-ref", branch + "@{u}")).strip()
    if branch.startswith("origin/"):
        branch = branch[7:]
    return branch


def head_branch():
    return str(Sh("git", "rev-parse", "--abbrev-ref", "HEAD")).strip()


def pr_url(repo_url, branch):
    upstream = upstream_branch(branch)

    if upstream != branch:
        pr_url = f"{repo_url}/pull/new/{upstream}...{branch}"
    else:
        pr_url = f"{repo_url}/pull/new/{branch}"

    return pr_url


def main():
    repo_url = origin_url()
    for branch in sys.argv[1:] or [head_branch()]:
        Sh("open", pr_url(repo_url, branch)).execute()

