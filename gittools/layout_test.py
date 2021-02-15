# coding=utf-8
import sys
from .layout import Row, layout
from io import StringIO
from textwrap import dedent

class Node(object):
  def __init__(self, name, *parents):
    self.name = name
    self.parents = tuple(parents)
    self.children = []
    for parent in parents:
      parent.children.append(self)

  def __repr__(self):
    return "Node(%s, parents=%s, children=%s)" % (
        self.name, [p.name for p in self.parents], [c.name for c in self.children])

def test_row_repr():
  assert repr(Row(2)) == "Row(at = 2)"
  assert repr(Row(2, up = range(3))) == "Row(at = 2, up = {0,1,2})"
  assert (repr(Row(0, down = (1,), through = (2, 4)))
          == "Row(at = 0, down = {1}, through = {2,4})")

def test_row_unicode():
  assert str(Row(2)) == '    ─'
  assert str(Row(0, up={0}, down={0})) == '┼'
  assert str(Row(0, down={0})) == '┬'
  assert str(Row(0, up={0})) == '┴'
  assert str(Row(1, up={0}, down={0})) == '├▶╴'
  assert str(Row(4, up={4}, down={1,2,3,4})) == '  ┌─┬─┬▶┼'
  assert str(Row(4, up={4}, down={0,4}, through={1,2,3})) == '┌┄│┄│┄│▶┼'
  assert str(Row(0, up={0}, down={0}, through={1,2,3,4})) == '┼ │ │ │ │'
  assert str(Row(4, up={4}, down={1,3,4}, through={2,5})) == '  ┌┄│┄┬▶┼ │'
  assert str(Row(2, up={0,1,2,3,4}, down={0,1,2,3,4})) == '├─┼▶┼◀┼─┤'
  assert str(Row(0, down={0,1})) == '┬◀┐'

def test_row_equality():
  assert Row(2) == Row(2)
  assert Row(2) != Row(2, up = {4})

def test_row_max_min_cols():
  assert Row(2)._min == 2
  assert Row(2)._max == 2
  assert Row(2)._cols == 3
  assert Row(2, up={3,4}, down={0,1})._min == 0
  assert Row(2, up={3,4}, down={0,1})._max == 4
  assert Row(2, up={3,4}, down={0,1})._cols == 5
  assert Row(2, through={1,5})._min == 2
  assert Row(2, through={1,5})._max == 2
  assert Row(2, through={1,5})._cols == 6

def test_layout_multi_branch_merge():
  gh_pages = Node("gh-pages")
  master = Node("master")
  footnotes = Node("footnotes", master, Node("origin/footnotes"))
  issue4 = Node("issue4.idiomatic.java7", master)
  test_logs = Node("cleaner.test.logs", master)
  issue29 = Node("issue29-wildcards-in-optional-types", master)
  cleanup = Node("cleanup", master)
  issue2 = Node("issue2.nulls", master)
  issue27 = Node("issue27.dogfood", cleanup, issue2)
  develop = Node("develop", issue4, test_logs, issue29, issue27)
  refactor = Node("code.generator.refactor", develop)
  issue24 = Node("issue24.nested.classes.last", refactor)
  excerpt = Node("excerpt", issue24)
  qualified_name = Node("qualified.name", excerpt)
  no_warnings = Node("assert.no.warnings", qualified_name)
  issue1 = Node("issue1.generics", no_warnings)

  branches = [ issue1, no_warnings, qualified_name, excerpt, issue24, refactor, develop,
               issue27, issue2, cleanup, issue29, test_logs, issue4, footnotes, master,
               gh_pages ]
  assert layout(branches) == [
      Row(at = 0, down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0,1,2,3]),
      Row(at = 0, up = [0], down = [0,4], through = [1,2,3]),
      Row(at = 0, up = [0], down = [0], through = [1,2,3,4]),
      Row(at = 4, up = [0,4], down = [0], through = [1,2,3]),
      Row(at = 3, up = [0,3], down = [0], through = [1,2]),
      Row(at = 2, up = [0,2], down = [0], through = [1]),
      Row(at = 1, up = [0,1], down = [0]),
      Row(at = 1, up = [0], down = [0]),
      Row(at = 0, up = [0]),
      Row(at = 0),
  ]

def test_layout_simple_merge_with_crossover():
  develop = Node("develop")
  autovalue = Node("feature/auto.value", develop)
  deadlock = Node("feature/deadlock.transfercontroller", develop)
  workshop = Node("workshop", autovalue, deadlock)
  freebuilder = Node("feature/freebuilder", autovalue)

  branches = [ freebuilder, workshop, deadlock, autovalue, develop ]
  assert layout(branches) == [
      Row(at = 1, down = [1]),
      Row(at = 0, up = [1], down = [0,1]),
      Row(at = 0, up = [0], down = [0], through = [1]),
      Row(at = 1, up = [0,1], down = [0]),
      Row(at = 0, up = [0]),
  ]

def test_layout_simple_merge_no_crossover():
  develop = Node("develop")
  autovalue = Node("feature/auto.value", develop)
  deadlock = Node("feature/deadlock.transfercontroller", develop)
  freebuilder = Node("feature/freebuilder", autovalue)
  workshop = Node("workshop", autovalue, deadlock)

  branches = [ workshop, freebuilder, autovalue, deadlock, develop ]
  assert layout(branches) == [
      Row(at = 0, down = [0,1]),
      Row(at = 2, up = [0], down = [0], through = [1]),
      Row(at = 0, up = [0], down = [0], through = [1]),
      Row(at = 1, up = [0,1], down = [0]),
      Row(at = 0, up = [0]),
  ]

def test_row_unicode_branch_merge_to_head():
  grid = [
      Row(at = 0, down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0]),
      Row(at = 0, up = [0], down = [0,1,2,3]),
      Row(at = 0, up = [0], down = [0,4], through = [1,2,3]),
      Row(at = 0, up = [0], down = [0], through = [1,2,3,4]),
      Row(at = 4, up = [0,4], down = [0], through = [1,2,3]),
      Row(at = 3, up = [0,3], down = [0], through = [1,2]),
      Row(at = 2, up = [0,2], down = [0], through = [1]),
      Row(at = 1, up = [0,1], down = [0]),
      Row(at = 1, up = [0], down = [0]),
      Row(at = 0, up = [0]),
      Row(at = 0),
  ]
  output = ''.join(str(row) + '\n' for row in grid)
  assert output == dedent("""\
      ┬
      ┼
      ┼
      ┼
      ┼
      ┼
      ┼◀┬─┬─┐
      ┼◀│┄│┄│┄┐
      ┼ │ │ │ │
      ├┄│┄│┄│▶┘
      ├┄│┄│▶┘
      ├┄│▶┘
      ├▶┘
      ├▶╴
      ┴
      ─
  """)

def test_row_unicode_remerge_to_head():
  grid = [
      Row(at = 1, down = [1]),
      Row(at = 0, up = [1], down = [0,1]),
      Row(at = 0, up = [0], down = [0], through=[1]),
      Row(at = 1, up = [0,1], down = [0]),
      Row(at = 0, up = [0]),
  ]
  output = ''.join(str(row) + '\n' for row in grid)
  assert output == dedent("""\
        ┬
      ┬◀┤
      ┼ │
      ├▶┘
      ┴
  """)

def test_row_unicode_simple_merge_to_head_with_crossunder():
  grid = [
      Row(at = 0, down = [0,1]),
      Row(at = 2, up = [0], down = [0], through=[1]),
      Row(at = 0, up = [0], down = [0], through=[1]),
      Row(at = 1, up = [0,1], down = [0]),
      Row(at = 0, up = [0]),
  ]
  output = ''.join(str(row) + '\n' for row in grid)
  assert output == dedent("""\
      ┬◀┐
      ├┄│▶╴
      ┼ │
      ├▶┘
      ┴
  """)

def test_row_unicode_remerge_head_into_branch():
  grid = [
      Row(at = 0, down = [0]),
      Row(at = 1, down = [1], through=[0]),
      Row(at = 1, up = [0,1], down = [0,1]),
      Row(at = 0, up = [0], down = [0], through=[1]),
      Row(at = 1, up = [0,1], down = [0]),
      Row(at = 0, up = [0]),
  ]
  output = ''.join(str(row) + '\n' for row in grid)
  assert output == dedent("""\
      ┬
      │ ┬
      ├▶┼
      ┼ │
      ├▶┘
      ┴
  """)
