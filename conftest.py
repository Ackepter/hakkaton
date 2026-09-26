"""Test isolation: layouts are stored in a throw-away directory, never in the real config/layouts."""
import os
import shutil
import tempfile

import pytest

_LAYOUT_DIR = tempfile.mkdtemp(prefix="si-layouts-")
os.environ["SI_LAYOUT_DIR"] = _LAYOUT_DIR          # also inherited by the subprocesses of the live/e2e tests


@pytest.fixture(autouse=True)
def clean_layout_dir():
    def wipe():
        for entry in os.listdir(_LAYOUT_DIR):
            path = os.path.join(_LAYOUT_DIR, entry)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    wipe()
    yield
    wipe()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_LAYOUT_DIR, ignore_errors=True)
