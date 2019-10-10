Alice's git tools
=================

This project contains a set of git CLI tools maintained by alice.purcell@oaknorth.ai. The most stable is `git graph-branch`, which displays a clean tree of your local git repository's branches, including forks and merges, whether the branch is in sync with origin (GitHub only), and whether tests are currently passing in CI.

To use the tools, add this checkout to your PATH.

git graph-branch
----------------

    Usage: git graph-branch [options]

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

To get the best out of git graph-branch, I recommend a few configuration changes to your git checkout (`/path/to/repo/.git/config`, or `~/.gitconfig` if you would like to make these changes to every checkout); these will also give you better defaults for several git commands.

    [branch]
      autosetupmerge = always  # sets upstream information when you run git checkout -b <branch>
    [remote]
      pushdefault = origin  # plain git push will continue to work as expected
    [gc]
      auto = 100000  # keeps branch history for longer
    [pull]
      rebase = true  # git graph-branch assumes you always rebase remote changes
    [push]
      default = simple  # plain git push will continue to work as expected

If you have not used these defaults before, you may want to set up upstream information for your existing branches as a one-off. For instance, if `feature/foo` is going to be applied to `develop`, run `git branch feature/foo --set-upstream-to=develop`. Once you have made the config changes above, `git branch -b feature/foo` will set this upstream information for you when you create the branch.

git graph-branch will then use this upstream information to determine a tree structure for your branches. For instance, you might see something like:

    ─  cleanup/immutables 🔷 🔥
    ┬  feature/java.8
    ┼  feature/herc.strategy.api.plugin 🔷 💚 
    ┼  feature/no.more.internal.cluster.dispatch.connection 🔷 💚 
    ├▶╴  feature/distTar-unbreakable 🔷 💚
    ┴  develop 🔶 💚 ② unmerged
    ─  workspace

In this case, `feature/java.8` is branched off `feature/herc.strategy.api.plugin`, which is branched off `feature/no.more.internal.cluster.dispatch.connection`, which itself is branched off of `develop` (and all four are passing CI tests!).
