Alice's git tools
=================

This project contains a set of git CLI tools maintained by [alicederyn].

[alicederyn]: https://github.com/alicederyn

Install the tools using [uv][]:

[uv]: https://docs.astral.sh/uv/

```bash
$ uv tool install git+https://github.com/alicederyn/gittools.git
```

Where did git graph-branch go?
------------------------------

git graph-branch has had a ground-up rewrite, and moved to its own repository:
https://github.com/alicederyn/git-graph-branch/


git pr
------

(Mac only)

Opens the browser to a GitHub page for creating a new PR for this branch, using upstream as the target branch.
