# coding=utf-8
from collections import namedtuple
from utils import first

class Row(object):
  u"""Representation of a single row of a DAG.

  self.at: the column containing the row's node
  self.up: columns with up edges this row's node is connected to other nodes on up the DAG
  self.down: columns with down edges this row's node is connected to
  self.through: columns with edges this row's node is not connected to

  repr(self): Pythonic representation of this row, e.g. Row(at = 1, up={0,1}, down={0})
  unicode(self): Unicode-art representation of this row, e.g. ├▶┘
  """

  BOX_CHARS = [ u" ", u"╵", u"╶", u"└", u"╷", u"│", u"┌", u"├",
                u"╴", u"┘", u"─", u"┴", u"┐", u"┤", u"┬", u"┼" ]

  def __init__(self, at, up = (), down = (), through = ()):
    self.at = at
    self.up = frozenset(up)
    self.down = frozenset(down)
    self.through = frozenset(through)
    self._min = min({self.at} | self.up | self.down)
    self._max = max({self.at} | self.up | self.down)
    self._cols = max({self._max} | self.through) + 1
    assert 0 <= self.at
    assert all(idx >= 0 for idx in self.up)
    assert all(idx >= 0 for idx in self.down)
    assert all(idx >= 0 for idx in self.through)
    assert not any(idx in self.up or idx in self.down for idx in self.through)

  def __eq__(self, other):
    if not isinstance(other, Row):
      return False
    return (self.at == other.at and self.up == other.up
            and self.down == other.down and self.through == other.through)

  def __repr__(self):
    r = "%s(at = %d" % (type(self).__name__, self.at)
    if self.up:
      r += ", up = {%s}" % ','.join(map(str, sorted(self.up)))
    if self.down:
      r += ", down = {%s}" % ','.join(map(str, sorted(self.down)))
    if self.through:
      r += ", through = {%s}" % ','.join(map(str, sorted(self.through)))
    r += ")"
    return r

  def _first_codepoint(self, column):
    if column in self.through:
      up = down = True
      left = right = False
    else:
      up = column in self.up
      down = column in self.down
      if self._min == column == self._max:
        left = right = True
      else:
        left = self._min < column <= self._max
        right = self._min <= column < self._max
    return Row.BOX_CHARS[(1 if up else 0) + (2 if right else 0)
                         + (4 if down else 0) + (8 if left else 0)]

  def _second_codepoint(self, column):
    if column < self._cols - 1:
      if self._min <= column < self._max:
        if column + 1 == self.at:
          return u'▶'
        elif column == self.at:
          return u'◀'
        elif column in self.through or column + 1 in self.through:
          return u'┄'
        else:
          return u'─'
      else:
        return u' '
    else:
      return u''

  def __unicode__(self):
    return u''.join(self._first_codepoint(i) + self._second_codepoint(i)
                    for i in xrange(self._cols))

def layout(branches):
  # Sanitize data
  branchesSet = frozenset(branches)
  children = { b : frozenset(c for c in b.children if c in branchesSet) for b in branches }
  parents = { b : frozenset(p for p in b.parents if p in branchesSet) for b in branches }

  columns = {}
  active = []
  reached = set()
  grid = []
  for b in reversed(branches):
    reached.add(b)

    if not parents[b]:
      at = len(active)
    else:
      at = max(columns[p] for p in parents[b])
      if not children[active[at]] <= reached:
        at = len(active)
    columns[b] = at
    down = { columns[p] for p in parents[b]}
    for p in parents[b]:
      if all(c in columns for c in children[p]):
        active[columns[p]] = None
    through = { idx for idx, p in enumerate(active) if p and idx != at and idx not in down }
    if children[b]:
      while len(active) <= at:
        active.append(None)
      active[at] = b
    up = { idx for idx, p in enumerate(active) if p and idx not in through }
    while active and active[-1] is None:
      active.pop()
    grid.append(Row(at, up = up, down = down, through = through))
  grid.reverse()
  return grid

def layout_to(file, branches, label = lambda b : b.name):
  grid = layout(branches)
  for b, row in zip(branches, grid):
    file.write(unicode(row))
    file.write('  ')
    file.write(label(b))
    file.write('\n')

