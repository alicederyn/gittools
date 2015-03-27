# coding=utf-8
from collections import namedtuple
from utils import first

Node = namedtuple("Node", "parents children data")

class Layout(object):
  BOX_CHARS = [ u" ", u"╵", u"╶", u"└", u"╷", u"│", u"┌", u"├",
                u"╴", u"┘", u"─", u"┴", u"┐", u"┤", u"┬", u"┼" ]
  FADING = u"┄"

  def __init__(self, branches):
    branchesSet = frozenset(branches)
    self._branches = tuple(Node(parents  = frozenset(b.parents) & branchesSet,
                                children = frozenset(b.children) & branchesSet,
                                data = b) for b in branches)

  def _grid(self):
    columns = {}
    active = []
    reached = set()
    grid = [()]
    for b in reversed(self._branches):
      reached.add(b.data)
      if not b.parents:
        idx = len(active)
      else:
        for p in b.parents:
          assert p in set(x.data for x in self._branches)
        idx = max(columns[p] for p in b.parents)
        if not set(active[idx].children) <= reached:
          idx = len(active)
      columns[b.data] = idx
      for p in b.parents:
        if all(c in columns for c in p.children):
          active[columns[p]] = None
      if b.children:
        while len(active) <= idx:
          active.append(None)
        active[idx] = b.data
      while active and active[-1] is None:
        active.pop()
      grid.append(tuple(active))
    grid.reverse()
    return grid

  def write_to(self, file, label = lambda b : b.name):
    grid = self._grid()
    active = []
    for lineUp, b, lineDown in zip(grid[:-1], self._branches, grid[1:]):
      if not lineUp and not lineDown:
        file.write(u" ╴  ")
        file.write(label(b.data))
        file.write("\n")
        continue
      indices = [i for i, u in enumerate(lineUp) if u == b.data]
      parentIndices = [i for i, d in enumerate(lineDown) if d in b.parents]
      if lineUp and not indices:
        indices = [ max(parentIndices) + 1 ]
      assert not b.parents or all(p in lineDown for p in b.parents)
      firstIdx = min(indices + parentIndices)
      lastIdx = max(indices + parentIndices)
      fading = False
      for i in xrange(max(len(lineUp), len(lineDown), lastIdx + 1)):
        up = lineUp[i] if i < len(lineUp) else None
        down = lineDown[i] if i < len(lineDown) else None
        through = (up not in (None, b.data)) and (down is not None and down not in b.parents)
        left = (not through and firstIdx < i <= lastIdx) or (up and not down)
        if firstIdx <= i < lastIdx:
          right = not through
        elif i == lastIdx:
          right = firstIdx == lastIdx and len(b.parents) == 1
        else:
          right = False
        char = Layout.BOX_CHARS[(1 if up else 0) + (2 if right else 0)
                              + (4 if down else 0) + (8 if left else 0)]
        if firstIdx < i < lastIdx:
          if fading or through:
            file.write(Layout.FADING)
          else:
            file.write(Layout.BOX_CHARS[10])
          fading = through
        elif firstIdx < i == lastIdx:
          file.write(u'▶')
        elif i == lastIdx + 1:
          if firstIdx == lastIdx and len(b.parents) == 1:
            file.write(u'◇')
        else:
          file.write(' ')
        file.write(char)
      if lastIdx + 1 >= max(len(lineUp), len(lineDown)):
        if firstIdx == lastIdx and len(b.parents) == 1:
          file.write(u'◇')
      file.write('  ')
      file.write(str(label(b.data)))
      file.write('\n')

