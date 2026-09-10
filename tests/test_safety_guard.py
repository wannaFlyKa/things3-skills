"""conftest fails CLOSED: no unit test may reach the real open(1) or run the live suite by accident.

A real Things 3 with real data lives on the developer's Mac. These tests prove the two guard layers in
tests/conftest.py (_refuse_real_open) and the three-way opt-in for live tests, on every platform.
"""

import os
import platform
import shutil
import subprocess

import pytest

import conftest
from conftest import OPEN_REFUSED, OPEN_SHIM_EXIT
from things_lib import transport
from things_lib.transport import TransportError, send

# Imported at module level ON PURPOSE (finding 2023): test_live captures REAL_HOME / REAL_PATH when it is first
# imported. Collection imports this file before any fixture runs, so the capture predates conftest's HOME swap and
# open(1) shim even when tests/test_live.py itself is not part of the collected set (e.g. this file run alone).
# A lazy `import test_live` inside a test body would capture the shimmed PATH and fail the two guard tests below.
import test_live  # noqa: E402


def test_path_shim_shadows_open(tmp_path, open_shim_dir):
    found = shutil.which("open")
    assert found == str(open_shim_dir / "open"), found
    assert list(tmp_path.iterdir()) == [], "the shim must not live inside the per-test tmp_path (HOME)"
    # Run the shim through sh so the in-process guard (which also refuses argv[0] == 'open') is not what fires.
    proc = subprocess.run(["/bin/sh", found, "-g", "things:///version"], capture_output=True, text=True)
    assert proc.returncode == OPEN_SHIM_EXIT
    assert proc.stderr.strip() == "%s: -g things:///version" % OPEN_REFUSED


def test_in_process_send_open_is_refused(monkeypatch):
    monkeypatch.setattr(transport.platform, "system", lambda: "Darwin")
    with pytest.raises(AssertionError, match="refused to launch the real open"):
        send("things:///version", "open", "ping")


def test_guard_covers_string_and_absolute_argv():
    with pytest.raises(AssertionError, match="refused to launch the real open"):
        subprocess.run("open -g things:///version", shell=True)
    with pytest.raises(AssertionError, match="refused to launch the real open"):
        subprocess.run(["/usr/bin/open", "-g", "things:///version"])


def test_guard_lets_other_commands_through():
    proc = subprocess.run(["true"], capture_output=True)
    assert proc.returncode == 0


def test_cli_open_transport_fails_closed_on_every_platform(run_cli):
    # No linux_only skip on purpose: this is the incident guard. On macOS the child CLI must hit the shim.
    code, payload, err = run_cli("--transport", "open", "ping")
    assert code == 2, (code, payload, err)
    assert payload["ok"] is False and payload["sent"] is False
    if platform.system() == "Darwin":
        assert payload["error"] == "open exited %d: %s: -g things:///version" % (OPEN_SHIM_EXIT, OPEN_REFUSED)
    else:
        assert payload["error"] == "transport 'open' is only available on macOS"


def test_cli_env_override_to_open_fails_closed(run_cli):
    code, payload, err = run_cli("ping", env={"THINGS_SKILLS_TRANSPORT": "open"})
    assert code == 2 and payload["sent"] is False, (code, payload, err)
    if platform.system() == "Darwin":
        assert payload["error"].startswith("open exited %d: %s" % (OPEN_SHIM_EXIT, OPEN_REFUSED))


def test_live_env_restores_real_path_and_home(open_shim_dir, tmp_path):
    assert str(open_shim_dir) not in test_live.REAL_PATH, "REAL_PATH must be captured before conftest prepends the shim"
    assert test_live.REAL_HOME != str(tmp_path), "REAL_HOME must be captured before conftest swaps HOME"
    assert str(open_shim_dir) in os.environ["PATH"]
    env = test_live.live_env()
    assert env["PATH"] == test_live.REAL_PATH and str(open_shim_dir) not in env["PATH"]
    assert env["HOME"] == test_live.REAL_HOME and env["HOME"] != str(tmp_path)
    assert "THINGSDB" not in env and "THINGS_SKILLS_TRANSPORT" not in env


def test_live_undo_isolation_restores_home_path_and_subprocess_run(monkeypatch, open_shim_dir, tmp_path):
    assert subprocess.run is not conftest.REAL_SUBPROCESS_RUN, "the guard must be active before undo"
    test_live.undo_isolation(monkeypatch)
    assert subprocess.run is conftest.REAL_SUBPROCESS_RUN
    assert os.environ["PATH"] == test_live.REAL_PATH and str(open_shim_dir) not in os.environ["PATH"]
    assert os.environ["HOME"] == test_live.REAL_HOME and os.environ["HOME"] != str(tmp_path)


def test_live_links_are_reported_immediately_and_at_teardown(monkeypatch, capsys):
    monkeypatch.setattr(test_live, "STATE", {"links": [], "answers": []})
    test_live.created({"links": ["things:///show?id=ProjectA"], "ids": ["ProjectA"]})
    err = capsys.readouterr().err
    assert "[live] created things:///show?id=ProjectA" in err
    assert test_live.STATE["links"] == ["things:///show?id=ProjectA"]
    test_live.report_links()
    assert "trash these by hand" in capsys.readouterr().err and "things:///show?id=ProjectA" in err
    monkeypatch.setattr(test_live, "STATE", {"links": [], "answers": []})
    test_live.report_links()
    assert capsys.readouterr().err == ""


class _Item:
    def __init__(self, keywords):
        self.keywords = keywords
        self.markers = []

    def add_marker(self, marker):
        self.markers.append(marker)


class _Config:
    def __init__(self, markexpr):
        self.markexpr = markexpr

    def getoption(self, name):
        assert name == "markexpr"
        return self.markexpr


@pytest.mark.parametrize("env, system, markexpr, expect_skip", [
    ("1", "Darwin", "live", False),
    ("1", "Darwin", "", True),               # env alone never arms the live suite
    ("1", "Darwin", None, True),
    ("1", "Darwin", "not live", False),      # `-m` itself deselects the live items here; no skip needed
    ("1", "Linux", "live", True),
    (None, "Darwin", "live", True),
    ("1", "Darwin", "live and not slow", False),
    ("1", "Darwin", "lively", True),
])
def test_live_tests_need_env_darwin_and_m_live(monkeypatch, env, system, markexpr, expect_skip):
    if env is None:
        monkeypatch.delenv("THINGS_SKILLS_LIVE", raising=False)
    else:
        monkeypatch.setenv("THINGS_SKILLS_LIVE", env)
    monkeypatch.setattr(conftest.platform, "system", lambda: system)
    live, plain = _Item({"live": True}), _Item({})
    conftest.pytest_collection_modifyitems(_Config(markexpr), [live, plain])
    assert plain.markers == []
    assert bool(live.markers) is expect_skip
    if expect_skip:
        assert "`-m live`" in live.markers[0].kwargs["reason"]
