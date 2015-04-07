from lazy import lazy

def test_attribute_name():
  class Foo(object):
    bar = lazy(1)
  assert 'bar' == Foo.bar.__name__

def test_attribute_access():
  class Foo(object):
    bar = lazy(1)
  foo = Foo()
  assert 1 == foo.bar
  assert 1 == foo.bar

def test_attribute_overwrite():
  class Foo(object):
    bar = lazy(1)
  foo = Foo()
  assert 1 == foo.bar
  foo.bar = 3
  assert 3 == foo.bar

def test_attribute_immediate_overwrite():
  class Foo(object):
    bar = lazy(1)
  foo = Foo()
  foo.bar = 3
  assert 3 == foo.bar

def test_independent_attributes():
  class Foo(object):
    bar = lazy(1)
  foo1 = Foo()
  foo2 = Foo()
  assert 1 == foo1.bar
  assert 1 == foo2.bar
  foo1.bar = 3
  assert 3 == foo1.bar
  assert 1 == foo2.bar
  foo2.bar = 2
  assert 3 == foo1.bar
  assert 2 == foo2.bar

def test_property_cached():
  i = [0]
  class Foo(object):
    @lazy
    @property
    def bar(self):
      i[0] += 1
      return i[0]
  f = Foo()
  assert 1 == f.bar
  assert 1 == f.bar

def test_derived_property():
  i = [0]
  class Foo(object):
    baz = lazy('A')

    @lazy
    @property
    def bar(self):
      i[0] += 1
      return (self.baz, i[0])
  f = Foo()
  assert ('A', 1) == f.bar
  assert ('A', 1) == f.bar
  f.baz = 'B'
  assert ('B', 2) == f.bar
  assert ('B', 2) == f.bar
  f.baz = 'C'
  assert ('C', 3) == f.bar
  assert ('C', 3) == f.bar

def test_classmethod_cached():
  i = [0]
  class Foo(object):
    @lazy
    @classmethod
    def bar(cls):
      i[0] += 1
      return i[0]
  assert 1 == Foo.bar
  assert 1 == Foo.bar

def test_staticmethod_cached():
  i = [0]
  class Foo(object):
    @lazy
    @staticmethod
    def BAR():
      i[0] += 1
      return i[0]
  assert 1 == Foo.BAR
  assert 1 == Foo.BAR

