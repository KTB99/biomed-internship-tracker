import os
import stat

import pytest

from tracker.catalog import write_all

pytestmark = pytest.mark.skipif(os.name != "posix", reason="needs POSIX file modes")


@pytest.fixture
def set_umask():
    """Set the process umask for one test, then put the old one back."""
    previous = os.umask(0o022)
    try:
        yield os.umask
    finally:
        os.umask(previous)


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_rewriting_a_file_keeps_its_mode(tmp_path, set_umask):
    set_umask(0o077)
    target = tmp_path / "CLOSED.md"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o644)

    write_all({target: "new\n"})

    assert target.read_text(encoding="utf-8") == "new\n"
    assert mode(target) == 0o644


@pytest.mark.parametrize("mask, expected", [(0o022, 0o644), (0o002, 0o664)])
def test_a_new_file_gets_normal_permissions_under_the_umask(tmp_path, set_umask, mask, expected):
    set_umask(mask)
    target = tmp_path / "logs" / "screening.json"

    write_all({target: "{}\n"})

    assert target.read_text(encoding="utf-8") == "{}\n"
    assert mode(target) == expected
