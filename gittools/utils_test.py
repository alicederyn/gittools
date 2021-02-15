# coding=utf-8
from .utils import Sh, ShError

def test_iteration_no_newline_no_error():
  x = Sh('printf', 'hello')
  assert 'hello' == next(x)
  try:
    next(x)
    assert False and 'Expected StopIteration'
  except StopIteration:
    pass

def test_iteration_newline_no_error():
  x = Sh('echo', 'hello')
  assert 'hello' == next(x)
  try:
    next(x)
    assert False and 'Expected StopIteration'
  except StopIteration:
    pass

def test_iteration_many_lines_no_error():
  x = Sh('bash', '-c', 'for i in {1..1000}; do echo hello; done')
  for i in range(1000):
    assert 'hello' == next(x)
  try:
    next(x)
    assert False and 'Expected StopIteration'
  except StopIteration:
    pass

def test_iteration_error_no_stderr():
  p = Sh('false')
  try:
    next(p)
    assert False and 'Expected ShError'
  except ShError as e:
    assert 1 == e.returncode
    assert ('false',) == e.cmd
    assert '' == e.stderr

def test_iteration_error_stderr():
  p = Sh('cat', 'DOES-NOT-EXIST')
  try:
    next(p)
    assert False and 'Expected ShError'
  except ShError as e:
    assert 'cat: DOES-NOT-EXIST: No such file or directory\n' == e.stderr

def test_iteration_error_stdout_no_stderr():
  p = Sh('bash', '-c', 'echo hello ; false')
  assert 'hello' == next(p)
  try:
    next(p)
    assert False and 'Expected ShError'
  except ShError as e:
    pass

def test_str_no_error_no_newline():
  output = str(Sh('printf', 'hello'))
  assert 'hello' == output

def test_str_no_error_newline():
  output = str(Sh('echo', 'hello'))
  assert 'hello\n' == output

def test_str_error_no_stderr():
  p = Sh('false')
  try:
    str(p)
    assert False and 'Expected ShError'
  except ShError as e:
    assert 1 == e.returncode
    assert ('false',) == e.cmd
    assert '' == e.stderr

def test_str_error_stderr():
  p = Sh('cat', 'DOES-NOT-EXIST')
  try:
    str(p)
    assert False and 'Expected ShError'
  except ShError as e:
    assert 'cat: DOES-NOT-EXIST: No such file or directory\n' == e.stderr

def test_repr():
  p = Sh('false')
  assert "Sh('false')" == repr(p)

def test_context_management():
  with Sh('echo', 'hello') as p:
    assert p._process.returncode is None
  assert p._process.returncode is not None
  assert p._process.returncode != 0

