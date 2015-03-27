# coding=utf-8
import sys
from layout import Layout
from StringIO import StringIO
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

class TestBranchMerge(object):

  def setUp(self):
    self.expected = dedent(u"""\
                 ┌◇  issue1.generics
                 ├◇  assert.no.warnings
                 ├◇  qualified.name
                 ├◇  excerpt
                 ├◇  issue24.nested.classes.last
                 ├◇  code.generator.refactor
           ┌─┬─┬▶┤  develop
         ┌┄│┄│┄│▶┤  issue27.dogfood
         ├◇│ │ │ │  issue2.nulls
         ├┄│┄│┄│▶┘  cleanup
         ├┄│┄│▶┘  issue29-wildcards-in-optional-types
         ├┄│▶┘  cleaner.test.logs
         ├▶┘  issue4.idiomatic.java7
         ├▶╴  footnotes
         ┘  master
         ╴  gh-pages
        """)

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

    self.branches = [ issue1, no_warnings, qualified_name, excerpt, issue24, refactor, develop,
                      issue27, issue2, cleanup, issue29, test_logs, issue4, footnotes, master,
                      gh_pages ]
    self.grid = [
        ( ),
        ( None,   None,   None,      None,    no_warnings    ),
        ( None,   None,   None,      None,    qualified_name ),
        ( None,   None,   None,      None,    excerpt        ),
        ( None,   None,   None,      None,    issue24        ),
        ( None,   None,   None,      None,    refactor       ),
        ( None,   None,   None,      None,    develop        ),
        ( None,   issue4, test_logs, issue29, issue27        ),
        ( issue2, issue4, test_logs, issue29, cleanup ),
        ( master, issue4, test_logs, issue29, cleanup ),
        ( master, issue4, test_logs, issue29 ),
        ( master, issue4, test_logs ),
        ( master, issue4 ),
        ( master, ),
        ( master, ),
        ( ),
        ( ),
    ]

  def test_grid(self):
    self.setUp()
    layout = Layout(self.branches)
    grid = layout._grid()
    assert grid == self.grid

  def test_output(self):
    self.setUp()
    layout = Layout(self.branches)
    file = StringIO()
    layout.write_to(file)
    output = dedent(file.getvalue())
    assert output == self.expected

class TestSimpleMerge(object):

  def setUp(self):
    self.expected = dedent(u"""\
           ┌◇  feature/freebuilder
         ┌─┼▶╴  workshop
         ├◇│  feature/deadlock.transfercontroller
         ├▶┘  feature/auto.value
         ┘  develop
        """)

    develop = Node("develop")
    autovalue = Node("feature/auto.value", develop)
    deadlock = Node("feature/deadlock.transfercontroller", develop)
    workshop = Node("workshop", autovalue, deadlock)
    freebuilder = Node("feature/freebuilder", autovalue)

    self.branches = [ freebuilder, workshop, deadlock, autovalue, develop ]
    self.grid = [
        ( ),
        ( None,     autovalue),
        ( deadlock, autovalue ),
        ( develop,  autovalue ),
        ( develop, ),
        ( ),
    ]

  def test_grid(self):
    self.setUp()
    layout = Layout(self.branches)
    grid = layout._grid()
    assert ([[b.name if b else "-" for b in r] for r in grid]
            == [[b.name if b else "-" for b in r] for r in self.grid])

  def test_output(self):
    self.setUp()
    layout = Layout(self.branches)
    file = StringIO()
    layout.write_to(file)
    output = dedent(file.getvalue())
    assert output == self.expected


