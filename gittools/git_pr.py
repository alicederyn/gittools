import re

from .utils import Sh

GIT_URI_RE = re.compile(r"^\w+@([^:]+):(.*)\.git$")


def origin_url():
    url = str(Sh("git", "config", "--get", "remote.origin.url")).strip()
    if m := GIT_URI_RE.match(url):
        url = f"https://{m.group(1)}/{m.group(2)}"
    return url


def upstream_branch():
    branch = str(Sh("git", "rev-parse", "--abbrev-ref", "@{u}")).strip()
    if branch.startswith("origin/"):
        branch = branch[7:]
    return branch


def head_branch():
    return str(Sh("git", "rev-parse", "--abbrev-ref", "HEAD")).strip()


def main():
    repo_url = origin_url()
    upstream = upstream_branch()
    head = head_branch()

    if upstream != head:
        pr_url = f"{repo_url}/pull/new/{upstream}...{head}"
    else:
        pr_url = f"{repo_url}/pull/new/{head}"

    Sh("open", pr_url).execute()
