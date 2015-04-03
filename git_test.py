import git

def test_mergedBranches_single_branch():
  assert frozenset(['Foo']) == git.Branch._mergedBranches("Merge branch 'Foo' into master")

def test_mergedBranches_five_branches():
  assert frozenset("ABCDE") == git.Branch._mergedBranches(
      "Merge branches 'A', 'B', 'C', 'D' and 'E' into master")

