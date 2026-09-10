"""Shared fixtures (SPEC section J). Every test runs against the committed fixture database."""

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "plugins", "things", "scripts")
CLI_PATH = os.path.join(SCRIPTS, "things")
FIXTURE_DB = os.path.join(ROOT, "tests", "fixtures", "main.sqlite")
EXAMPLE_CONFIG = os.path.join(ROOT, "plugins", "things", "config.example.json")

# Fail-closed guard against the real open(1) (see _refuse_real_open). The exit code is deliberately odd so a
# CLI error of "open exited 97: ..." is unmistakably the shim, never macOS.
OPEN_SHIM_EXIT = 97
OPEN_REFUSED = "things-skills tests: refused to launch the real open(1)"
REAL_SUBPROCESS_RUN = subprocess.run   # captured before any guard; only tests/test_live.py may restore it

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def pytest_collection_modifyitems(config, items):
    """Live tests need three explicit opt-ins: macOS, THINGS_SKILLS_LIVE=1 AND `-m live` on the command line.

    The env var alone is not enough: a shell that once exported it must not turn a plain `pytest` into a run
    that writes to the user's Things.
    """
    env_ok = os.environ.get("THINGS_SKILLS_LIVE") == "1" and platform.system() == "Darwin"
    selected = bool(re.search(r"\blive\b", config.getoption("markexpr") or ""))
    skip = pytest.mark.skip(reason="live test: needs macOS, Things 3, THINGS_SKILLS_LIVE=1 and `-m live`")
    for item in items:
        if "live" in item.keywords and not (env_ok and selected):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def open_shim_dir(tmp_path_factory):
    """A directory holding an `open` that refuses with OPEN_SHIM_EXIT; sits outside every test's tmp_path."""
    shim_dir = tmp_path_factory.mktemp("open-shim")
    shim = shim_dir / "open"
    shim.write_text('#!/bin/sh\necho "%s: $*" >&2\nexit %d\n' % (OPEN_REFUSED, OPEN_SHIM_EXIT), encoding="utf-8")
    shim.chmod(0o755)
    return shim_dir


def _refuse_real_open(shim_dir, monkeypatch):
    """Fail CLOSED: no unit test may reach the real open(1), in-process or in a child process.

    The transport picks `open` whenever `--transport open` is passed or the env default is overridden, and
    spawns it via PATH lookup. Two independent layers stop that from touching the user's Things:
    1. a PATH shim named `open` that refuses with OPEN_SHIM_EXIT (covers run_cli children, sh wrappers and
       helper scripts, which all inherit os.environ);
    2. a guard on subprocess.run inside this process (covers in-process `send`). Tests that fake Darwin
       already replace transport.subprocess.run themselves; their monkeypatch stacks on top of this one.
    tests/test_live.py restores the real PATH on purpose; nothing else may.
    """
    monkeypatch.setenv("PATH", str(shim_dir) + os.pathsep + os.environ.get("PATH", ""))

    from things_lib import transport as transport_mod

    def guarded_run(argv, *args, **kwargs):
        head = argv.split(None, 1)[0] if isinstance(argv, str) and argv.strip() else (
            argv[0] if isinstance(argv, (list, tuple)) and argv else "")
        if os.path.basename(str(head)) == "open":
            raise AssertionError(OPEN_REFUSED + "; monkeypatch transport.subprocess.run or use --dry-run")
        return REAL_SUBPROCESS_RUN(argv, *args, **kwargs)

    monkeypatch.setattr(transport_mod.subprocess, "run", guarded_run)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch, open_shim_dir):
    monkeypatch.setenv("THINGSDB", FIXTURE_DB)
    monkeypatch.setenv("THINGS_SKILLS_TRANSPORT", "record")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("THINGS_SKILLS_CONFIG", raising=False)
    monkeypatch.delenv("THINGS_SKILLS_LIVE", raising=False)
    monkeypatch.chdir(tmp_path)
    _refuse_real_open(open_shim_dir, monkeypatch)
    from things_lib import token as token_mod
    token_mod.reset_warnings()
    yield


@pytest.fixture
def now():
    return datetime(2026, 9, 9, 10, 0)


@pytest.fixture
def token_file(tmp_path):
    directory = tmp_path / ".config" / "things-skills"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "auth-token"
    path.write_text("SECRET\n", encoding="utf-8")
    path.chmod(0o600)
    return str(path)


@pytest.fixture
def config_file(tmp_path):
    """Factory: config_file(dict) writes ~/.config/things-skills/config.json and returns its path."""
    def write(data, name="config.json"):
        directory = tmp_path / ".config" / "things-skills"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path)
    return write


@pytest.fixture
def run_cli():
    """run_cli(*args, env=None, stdin=None) -> (exit code, parsed stdout JSON or None, stderr)."""
    def run(*args, env=None, stdin=None):
        merged = dict(os.environ)
        merged.update(env or {})
        proc = subprocess.run([sys.executable, CLI_PATH, *args], capture_output=True, text=True,
                              env=merged, input=stdin, timeout=60)
        try:
            payload = json.loads(proc.stdout) if proc.stdout.strip() else None
        except ValueError:
            payload = None
        return proc.returncode, payload, proc.stderr
    return run


class FakeClock:
    """Injected monotonic clock and sleep for the rate limiter: no real waiting."""

    def __init__(self):
        self.t = 0.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def fake_clock():
    return FakeClock()
