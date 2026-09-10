"""Bundled things.py: vendor directory, import resolution, doctor fields and the setup row (no pip anywhere)."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types

import pytest

from conftest import FIXTURE_DB, ROOT, SCRIPTS
from things_lib import read

VENDOR = os.path.join(SCRIPTS, "vendor")
VENDOR_PKG = os.path.join(VENDOR, "things")
SETUP_CHECK = os.path.join(ROOT, "plugins", "things", "skills", "things-setup", "scripts", "setup_check.py")
SETUP_SKILL = os.path.join(ROOT, "plugins", "things", "skills", "things-setup", "SKILL.md")
NOW = "2026-09-09T10:00"


def load_setup_check():
    spec = importlib.util.spec_from_file_location("setup_check_under_test", SETUP_CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NULL_INFO = {"installed": False, "version": None, "source": None, "path": None}


def isolated_python(*args, pythonpath=None, cwd=None):
    """Run the interpreter with -S (no site-packages, no user site), so only what we put on the path is importable."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(THINGSDB=FIXTURE_DB, THINGS_SKILLS_TRANSPORT="record")
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    return subprocess.run([sys.executable, "-S", *args], capture_output=True, text=True, env=env, timeout=120, cwd=cwd)


def copy_scripts(tmp_path, with_vendor=True):
    """A private copy of plugins/things/scripts (CLI file, things_lib, optionally vendor) under tmp_path."""
    ignored = ["__pycache__"] + ([] if with_vendor else ["vendor"])
    dest = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, dest, ignore=shutil.ignore_patterns(*ignored))
    assert os.path.isdir(dest / "vendor" / "things") is with_vendor
    return dest


def cli_json(proc):
    assert proc.stdout.strip(), proc.stderr
    return json.loads(proc.stdout)


# ---- vendor directory --------------------------------------------------------------------------------

def test_vendor_layout():
    assert read.VENDOR_DIR == VENDOR
    for name in ("__init__.py", "api.py", "database.py"):
        assert os.path.isfile(os.path.join(VENDOR_PKG, name)), name
    assert not os.path.exists(os.path.join(VENDOR_PKG, "conftest.py")), "upstream conftest.py is not shipped"
    assert os.path.isfile(os.path.join(VENDOR, "README.md"))
    with open(os.path.join(VENDOR, "README.md"), encoding="utf-8") as handle:
        readme = handle.read()
    assert "1.0.1" in readme and "thingsapi/things.py" in readme and "Apache" in readme


def test_vendor_license_is_apache_2():
    path = os.path.join(VENDOR, "LICENSE-things.py")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert text.lstrip().startswith("Apache License")
    assert "Version 2.0" in text


def test_vendored_package_declares_version_1_0_1():
    with open(os.path.join(VENDOR_PKG, "__init__.py"), encoding="utf-8") as handle:
        assert re.search(r'^__version__ = "1\.0\.1"$', handle.read(), re.MULTILINE)


def test_vendor_contains_no_tests_for_pytest_to_collect():
    for base, _dirs, files in os.walk(VENDOR):
        for name in files:
            assert name != "conftest.py" and not name.startswith("test_"), os.path.join(base, name)


def test_no_requirements_file():
    assert not os.path.exists(os.path.join(ROOT, "requirements.txt")), "things.py is bundled; nothing to pip install"


# ---- import resolution -------------------------------------------------------------------------------

def test_things_py_info_reports_bundled_copy():
    info = read.things_py_info()
    assert info == {"installed": True, "version": "1.0.1", "source": "bundled", "path": VENDOR_PKG}
    assert set(info) == {"installed", "version", "source", "path"}
    assert read.things_version() == "1.0.1"
    module = sys.modules["things"]
    assert os.path.dirname(os.path.abspath(module.__file__)) == VENDOR_PKG
    assert os.path.dirname(os.path.abspath(module.api.__file__)) == VENDOR_PKG
    assert os.path.dirname(os.path.abspath(module.database.__file__)) == VENDOR_PKG


def test_vendor_dir_is_on_sys_path_exactly_once_after_import():
    read.things_version()
    assert sys.path.count(VENDOR) == 1


def test_bundled_copy_wins_over_system_copy_in_a_fresh_interpreter(tmp_path):
    """A different `things` earlier on sys.path (a stand-in for a system install) loses to the bundled copy."""
    other = tmp_path / "site" / "things"
    other.mkdir(parents=True)
    (other / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    code = ("import sys; sys.path.insert(0, %r); from things_lib import read; import json; "
            "info = read.things_py_info(); info['sys_path0'] = sys.path[0]; print(json.dumps(info))" % str(tmp_path / "site"))
    env = dict(os.environ, PYTHONPATH=SCRIPTS, THINGSDB=FIXTURE_DB)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"installed": True, "version": "1.0.1", "source": "bundled", "path": VENDOR_PKG,
                                      "sys_path0": VENDOR}


def test_already_imported_system_module_is_reported_as_system(monkeypatch):
    fake = types.ModuleType("things")
    fake.__file__ = "/usr/lib/python3/site-packages/things/__init__.py"
    fake.__version__ = "1.0.0"
    monkeypatch.setitem(sys.modules, "things", fake)
    assert read.things_py_info() == {"installed": True, "version": "1.0.0", "source": "system",
                                     "path": "/usr/lib/python3/site-packages/things"}
    assert read.things_version() == "1.0.0"


def test_already_imported_module_under_vendor_is_reported_as_bundled(monkeypatch):
    fake = types.ModuleType("things")
    fake.__file__ = os.path.join(VENDOR_PKG, "__init__.py")
    fake.__version__ = "1.0.1"
    monkeypatch.setitem(sys.modules, "things", fake)
    assert read.things_py_info()["source"] == "bundled"


def test_missing_vendor_dir_and_no_system_copy_fails_cleanly(tmp_path):
    """Contract: vendor dir missing and nothing installed -> null shape from things_py_info(), no exception."""
    code = ("import sys, json; from things_lib import read; read.VENDOR_DIR = %r; info = read.things_py_info(); "
            "print(json.dumps({'info': info, 'path_has_vendor': read.VENDOR_DIR in sys.path, "
            "'version': read.things_version(), 'status': read.database_status(), 'error': read.database_error()}))"
            % str(tmp_path / "no-vendor"))
    proc = isolated_python("-c", code, pythonpath=SCRIPTS)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"info": NULL_INFO, "path_has_vendor": False, "version": None,
                                       "status": "unavailable", "error": "things.py not installed"}


def test_cli_without_vendor_dir_and_no_system_copy(tmp_path):
    """doctor stays exit 0 with the null things_py shape; read commands exit 3 with the things.py message."""
    cli = str(copy_scripts(tmp_path, with_vendor=False) / "things")
    doctor = cli_json(isolated_python(cli, "doctor"))
    assert doctor["ok"] is True and doctor["error"] is None
    assert doctor["data"]["things_py"] == NULL_INFO
    assert doctor["data"]["database"]["status"] == "unavailable"
    assert doctor["data"]["database"]["error"] == "things.py not installed"
    inbox = isolated_python(cli, "inbox")
    assert inbox.returncode == 3, inbox.stdout + inbox.stderr
    payload = json.loads(inbox.stdout)
    assert payload["ok"] is False and payload["data"] is None
    assert payload["error"].startswith("things.py not installed")


def test_missing_vendor_dir_falls_back_to_system_copy(tmp_path):
    """Contract: vendor dir missing -> plain `import things`, reported as source "system" with its own version."""
    site = tmp_path / "site"
    stub = site / "things"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    code = ("import sys, json; from things_lib import read; read.VENDOR_DIR = %r; "
            "print(json.dumps(read.things_py_info()))" % str(tmp_path / "no-vendor"))
    proc = isolated_python("-c", code, pythonpath=os.pathsep.join([SCRIPTS, str(site)]))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"installed": True, "version": "9.9.9", "source": "system", "path": str(stub)}


def test_damaged_bundled_copy_is_reported_as_not_installed(tmp_path):
    """A syntactically broken vendor file surfaces as ImportError: doctor exit 0 with nulls, reads exit 3."""
    scripts = copy_scripts(tmp_path, with_vendor=True)
    (scripts / "vendor" / "things" / "api.py").write_text("def (\n", encoding="utf-8")
    cli = str(scripts / "things")
    proc = isolated_python(cli, "doctor")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doctor = cli_json(proc)
    assert doctor["ok"] is True and doctor["error"] is None
    assert doctor["data"]["things_py"] == NULL_INFO
    assert doctor["data"]["database"]["status"] == "unavailable"
    assert doctor["data"]["database"]["error"].startswith("things.py is damaged: SyntaxError")
    inbox = isolated_python(cli, "inbox")
    assert inbox.returncode == 3, inbox.stdout + inbox.stderr
    error = json.loads(inbox.stdout)["error"]
    assert error.startswith("things.py not installed: things.py is damaged: SyntaxError")


def test_damaged_bundled_copy_raises_import_error_in_process(monkeypatch, tmp_path):
    vendor = tmp_path / "vendor"
    (vendor / "things").mkdir(parents=True)
    (vendor / "things" / "__init__.py").write_text("def (\n", encoding="utf-8")
    for name in [m for m in sys.modules if m == "things" or m.startswith("things.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != VENDOR])
    monkeypatch.setattr(read, "VENDOR_DIR", str(vendor))
    with pytest.raises(ImportError) as excinfo:
        read._import_things()
    assert "things.py is damaged: SyntaxError" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, SyntaxError)
    assert read.things_py_info() == NULL_INFO
    assert read.things_version() is None
    # doctor's database.error names the damaged copy so the user is not told to install things.py
    assert read.database_status() == "unavailable"
    assert read.database_error().startswith("things.py is damaged: SyntaxError")


def test_database_path_without_thingsdb_uses_bundled_default(monkeypatch):
    monkeypatch.delenv("THINGSDB")
    things_database = read._import_things().database  # through the helper, so test order cannot matter
    assert os.path.dirname(os.path.abspath(things_database.__file__)) == VENDOR_PKG
    assert read.database_path() == things_database.DEFAULT_FILEPATH


# ---- doctor ------------------------------------------------------------------------------------------

def test_doctor_things_py_has_source_and_path(run_cli):
    code, payload, _ = run_cli("doctor")
    assert code == 0
    tpy = payload["data"]["things_py"]
    assert list(tpy) == ["installed", "version", "source", "path"]
    assert tpy["installed"] is True and tpy["version"] == "1.0.1"
    assert tpy["source"] == "bundled"
    # The CLI resolves its own location with realpath; the checkout may be reached through a symlink.
    assert os.path.realpath(tpy["path"]) == os.path.realpath(VENDOR_PKG)


# ---- setup row 3 -------------------------------------------------------------------------------------

def doctor_env(tpy):
    return {"ok": True, "warnings": [], "error": None, "data": {
        "platform": "Linux", "things_py": tpy,
        "database": {"path": FIXTURE_DB, "status": "fixture", "error": None},
        "token": {"present": False, "empty": False, "mode_ok": None, "mode": None},
        "config": {"path": "/tmp/config.json", "present": True, "valid": True, "missing_tags": []}}}


def row(steps, step_id):
    return next(s for s in steps if s["id"] == step_id)


@pytest.mark.parametrize("lang,bundled,system", [("en", "bundled 1.0.1", "system 1.0.1"), ("zh", "内置 1.0.1", "系统 1.0.1")])
def test_setup_row3_pass_text(lang, bundled, system):
    sc = load_setup_check()
    ping = {"ok": True, "sent": True, "data": {"transport": "record"}}
    for source, expected in (("bundled", bundled), ("system", system)):
        tpy = {"installed": True, "version": "1.0.1", "source": source, "path": VENDOR_PKG}
        steps = sc.build_steps(lang, doctor_env(tpy), ping, 0, "present", "/tmp/config.json", {"tags": []}, None)
        r = row(steps, "things_py")
        assert r["ok"] is True and r["detail"] == expected and r["fix"] is None
        assert row(steps, "database")["ok"] is True


@pytest.mark.parametrize("lang,detail,fix_must_have", [
    ("en", "cannot import things.py (bundled copy missing or damaged)", ("plugin update things@things3-skills", "re-clone")),
    ("zh", "无法导入 things.py（内置副本缺失或损坏）", ("plugin update things@things3-skills", "重新克隆")),
])
def test_setup_row3_fail_text_has_no_pip(lang, detail, fix_must_have):
    sc = load_setup_check()
    ping = {"ok": True, "sent": True, "data": {"transport": "record"}}
    tpy = {"installed": False, "version": None, "source": None, "path": None}
    steps = sc.build_steps(lang, doctor_env(tpy), ping, 0, "present", "/tmp/config.json", {"tags": []}, None)
    r = row(steps, "things_py")
    assert r["ok"] is False and r["detail"] == detail
    for needle in fix_must_have:
        assert needle in r["fix"], r["fix"]
    assert "pip" not in r["fix"].lower() and "requirements" not in r["fix"].lower()
    db = row(steps, "database")
    assert db["ok"] is False and "things.py" in db["detail"] and "pip" not in (db["fix"] or "").lower()


def test_setup_sources_mention_no_pip_or_requirements():
    for path in (SETUP_CHECK, SETUP_SKILL):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        assert not re.search(r"\bpip3?\b", text), path
        assert "requirements.txt" not in text, path
    with open(SETUP_SKILL, encoding="utf-8") as handle:
        skill = handle.read()
    assert "/plugin update things@things3-skills" in skill and "bundled" in skill


@pytest.mark.parametrize("lang,expected", [("en", "bundled 1.0.1"), ("zh", "内置 1.0.1")])
def test_setup_check_end_to_end_row3(lang, expected, tmp_path):
    env = dict(os.environ, THINGSDB=FIXTURE_DB, HOME=str(tmp_path), THINGS_SKILLS_TRANSPORT="record")
    env.pop("THINGS_SKILLS_CONFIG", None)
    proc = subprocess.run([sys.executable, SETUP_CHECK, "--no-create-config", "--now", NOW, "--lang", lang],
                          capture_output=True, text=True, env=env, timeout=120, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert "requirements" not in report
    r = row(report["steps"], "things_py")
    assert r["ok"] is True and r["detail"] == expected and r["fix"] is None
    assert report["doctor"]["things_py"]["source"] == "bundled"
    assert "pip" not in proc.stdout.lower()
