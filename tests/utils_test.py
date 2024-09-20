import pytest

from gittools.utils import Sh, ShError


def test_iteration_no_newline_no_error():
    x = Sh("printf", "hello")

    assert next(x) == "hello"
    with pytest.raises(StopIteration):
        next(x)


def test_iteration_newline_no_error():
    x = Sh("echo", "hello")

    assert next(x) == "hello"
    with pytest.raises(StopIteration):
        next(x)


def test_iteration_many_lines_no_error():
    x = Sh("bash", "-c", "for i in {1..1000}; do echo hello; done")

    for _ in range(1000):
        assert next(x) == "hello"
    with pytest.raises(StopIteration):
        next(x)


def test_iteration_error_no_stderr():
    p = Sh("false")

    with pytest.raises(ShError) as err:
        next(p)

    assert err.value.returncode == 1
    assert err.value.cmd == ("false",)
    assert err.value.stderr == ""


def test_iteration_error_stderr():
    p = Sh("cat", "DOES-NOT-EXIST")

    with pytest.raises(ShError) as err:
        next(p)
    assert err.value.stderr == "cat: DOES-NOT-EXIST: No such file or directory\n"


def test_iteration_error_stdout_no_stderr():
    p = Sh("bash", "-c", "echo hello ; false")

    assert next(p) == "hello"
    with pytest.raises(ShError):
        next(p)


def test_str_no_error_no_newline():
    output = str(Sh("printf", "hello"))
    assert output == "hello"


def test_str_no_error_newline():
    output = str(Sh("echo", "hello"))
    assert output == "hello\n"


def test_str_error_no_stderr():
    p = Sh("false")

    with pytest.raises(ShError) as err:
        str(p)
    assert err.value.returncode == 1
    assert err.value.cmd == ("false",)
    assert err.value.stderr == ""


def test_str_error_stderr():
    p = Sh("cat", "DOES-NOT-EXIST")

    with pytest.raises(ShError) as err:
        str(p)
    assert err.value.stderr == "cat: DOES-NOT-EXIST: No such file or directory\n"


def test_repr():
    p = Sh("false")
    assert repr(p) == "Sh('false')"


def test_context_management():
    with Sh("echo", "hello") as p:
        assert p._process.returncode is None
    assert p._process.returncode is not None
    assert p._process.returncode != 0
