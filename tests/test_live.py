"""Live tests against a real Things 3 (SPEC J, section 10 of the build brief, open questions K.1/K.2/K.3/K.8).

Skipped unless THINGS_SKILLS_LIVE=1 and platform.system() == "Darwin". Runs the shared CLI as a subprocess
with the REAL home directory, the REAL database and the REAL PATH (conftest's fixture isolation, including
its open(1) shim, is undone per call), through the `open` transport. Every run creates fresh projects named
"Things Skills Test <timestamp>"; nothing is ever deleted. Each project link is printed to stderr the moment
it exists and the full list again at module teardown (also after -x or Ctrl-C), so the user can trash them.

    THINGS_SKILLS_LIVE=1 python3 -m pytest tests/test_live.py -m live -s
`-m live` is required: without it the live tests are skipped even with the env var set.
Optional: THINGS_SKILLS_LIVE_REPEATING_ID=<uuid of an existing repeating to-do> enables probes K.3 and K.8.
Use one you do not mind being touched: the probe sends completed=true straight to Things, then attempts
completed=false (a new instance may have been generated; check by hand).
"""

import json
import os
import platform
import subprocess
import sys
import time
from datetime import date, timedelta

import pytest

from conftest import CLI_PATH, REAL_SUBPROCESS_RUN

pytestmark = pytest.mark.live

LIVE = os.environ.get("THINGS_SKILLS_LIVE") == "1" and platform.system() == "Darwin"
REAL_HOME = os.environ.get("HOME", "")            # captured at import, before conftest swaps HOME
REAL_PATH = os.environ.get("PATH", "")            # captured at import, before conftest prepends its open(1) shim
REPEATING_ID = os.environ.get("THINGS_SKILLS_LIVE_REPEATING_ID", "")
STAMP = time.strftime("%Y%m%d-%H%M%S")
PROJECT_TITLE = "Things Skills Test %s" % STAMP
JSON_PROJECT_TITLE = "Things Skills Test %s (json)" % STAMP
STATE = {"links": [], "answers": []}

if not LIVE:
    pytestmark = [pytest.mark.live, pytest.mark.skip(reason="live test: needs macOS, Things 3 and THINGS_SKILLS_LIVE=1")]


def live_env():
    env = dict(os.environ)
    env.pop("THINGSDB", None)
    env.pop("THINGS_SKILLS_TRANSPORT", None)
    env.pop("THINGS_SKILLS_CONFIG", None)
    env["HOME"] = REAL_HOME
    env["PATH"] = REAL_PATH                        # child processes: the conftest open(1) shim is undone here
    return env


def undo_isolation(monkeypatch):
    """In-process raw sends (K.3) need the real HOME (token file), the real PATH and the real subprocess.run.

    This is the only place besides live_env() that undoes conftest's fail-closed guard; it stays inside the
    live module on purpose.
    """
    monkeypatch.setenv("HOME", REAL_HOME)
    monkeypatch.setenv("PATH", REAL_PATH)
    monkeypatch.setattr(subprocess, "run", REAL_SUBPROCESS_RUN)


def report_links():
    if STATE["links"]:
        sys.stderr.write("\n[live] trash these by hand (the URL scheme cannot delete): %s\n" % " ".join(STATE["links"]))
        sys.stderr.flush()


@pytest.fixture(scope="module", autouse=True)
def _print_links_on_exit():
    """Runs even after -x, a failure or Ctrl-C: the user must always get the list of what was written."""
    yield
    report_links()


def created(payload):
    link = payload["links"][0]
    STATE["links"].append(link)
    say("created %s (trash by hand when done)" % link)


def cli(*args, timeout=90):
    proc = subprocess.run([sys.executable, CLI_PATH, "--transport", "open", *args], capture_output=True, text=True,
                          env=live_env(), timeout=timeout)
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        payload = None
    return proc.returncode, payload, proc.stderr


def say(message):
    STATE["answers"].append(message)
    sys.stderr.write("\n[live] %s\n" % message)
    sys.stderr.flush()


def need(key):
    if key not in STATE:
        pytest.skip("earlier live step did not produce %s" % key)
    return STATE[key]


def assert_written(code, payload, stderr):
    assert code == 0, (code, payload, stderr)
    assert payload["ok"] is True, payload
    assert payload["sent"] is True, payload
    assert payload["verified"] is True, (payload["verify_reason"], payload["warnings"])
    assert payload["links"] and all(link.startswith("things:///show?id=") for link in payload["links"])
    return payload


def get(item_id):
    code, payload, stderr = cli("get", item_id)
    assert code == 0, (code, payload, stderr)
    return payload["data"]


# ---- setup sanity -------------------------------------------------------------------------------------

def test_00_doctor_and_ping():
    code, payload, stderr = cli("doctor")
    assert code == 0 and payload["ok"], stderr
    data = payload["data"]
    assert data["platform"] == "Darwin" and data["transport"] == "open"
    assert data["database"]["status"] == "readable", "Full Disk Access needed: %r" % data["database"]
    assert data["token"]["present"] and not data["token"]["empty"], "create ~/.config/things-skills/auth-token first"
    assert data["things_py"]["installed"]
    code, payload, stderr = cli("ping")
    assert code == 0 and payload["sent"] is True, "no handler for things:// (is Things installed and opened once?)"
    STATE["ready"] = True


# ---- create -------------------------------------------------------------------------------------------

def test_01_add_project_verified():
    need("ready")
    code, payload, stderr = cli("add-project", PROJECT_TITLE, "--notes", "created by tests/test_live.py; safe to trash",
                                "--todo", "Live child A %s" % STAMP)
    payload = assert_written(code, payload, stderr)
    project = payload["ids"][0]
    item = get(project)
    assert item["type"] == "project" and item["title"] == PROJECT_TITLE
    children = [i for i in item.get("items", []) if i.get("type") == "to-do"]
    assert [c["title"] for c in children] == ["Live child A %s" % STAMP]
    STATE["project"] = project
    STATE["child_a"] = children[0]["uuid"]
    created(payload)


def test_02_add_json_project_with_heading_and_checklist(tmp_path):
    need("ready")
    payload_file = tmp_path / "live.json"
    payload_file.write_text(json.dumps([{"type": "project", "attributes": {
        "title": JSON_PROJECT_TITLE, "notes": "created by tests/test_live.py; safe to trash", "items": [
            {"type": "heading", "attributes": {"title": "Phase 1 %s" % STAMP}},
            {"type": "to-do", "attributes": {"title": "Live JSON child %s" % STAMP, "checklist-items": [
                {"type": "checklist-item", "attributes": {"title": "step one"}},
                {"type": "checklist-item", "attributes": {"title": "step two"}}]}}]}}], ensure_ascii=False), encoding="utf-8")
    code, payload, stderr = cli("add-json", str(payload_file))
    payload = assert_written(code, payload, stderr)
    assert payload["urls"][0].startswith("things:///json?data=")
    assert payload["data"]["objects"] == 1 and payload["data"]["items"] == 3
    project = payload["ids"][0]
    item = get(project)
    headings = [i for i in item.get("items", []) if i.get("type") == "heading"]
    assert [h["title"] for h in headings] == ["Phase 1 %s" % STAMP]
    nested = headings[0].get("items", [])
    assert [t["title"] for t in nested] == ["Live JSON child %s" % STAMP]
    child = get(nested[0]["uuid"])
    assert [c["title"] for c in child["checklist"]] == ["step one", "step two"]
    STATE["json_project"] = project
    STATE["json_child"] = nested[0]["uuid"]
    created(payload)


def test_03_add_todo_into_project_with_checklist():
    project = need("project")
    code, payload, stderr = cli("add", "Live child B %s" % STAMP, "--list-id", project, "--when", "today",
                                "--checklist", "one", "--checklist", "two\nthree", "--notes", "line1\nline2 & more?")
    payload = assert_written(code, payload, stderr)
    child = payload["ids"][0]
    item = get(child)
    assert item["project"] == project and item["start_date"] == date.today().isoformat()
    assert [c["title"] for c in item["checklist"]] == ["one", "two", "three"]
    assert item["notes"] == "line1\nline2 & more?"
    STATE["child_b"] = child


def test_04_update_title():
    child = need("child_b")
    new_title = "Live child B renamed %s 买牛奶" % STAMP
    code, payload, stderr = cli("update", child, "--title", new_title)
    assert_written(code, payload, stderr)
    assert get(child)["title"] == new_title


# ---- modify ------------------------------------------------------------------------------------------

def test_05_schedule():
    child = need("child_b")
    target = (date.today() + timedelta(days=1)).isoformat()
    code, payload, stderr = cli("schedule", child, "--when", target)
    assert_written(code, payload, stderr)
    assert payload["data"]["done"] == [child] and payload["data"]["skipped"] == []
    assert get(child)["start_date"] == target
    code, payload, stderr = cli("schedule", child, "--when", "%s@18:30" % target)
    assert_written(code, payload, stderr)
    assert get(child)["reminder_time"] == "18:30"


def test_06_deadline_set_push_clear():
    child = need("child_b")
    base = date.today() + timedelta(days=7)
    code, payload, stderr = cli("deadline", child, "--date", base.isoformat())
    assert_written(code, payload, stderr)
    assert get(child)["deadline"] == base.isoformat()
    code, payload, stderr = cli("deadline", child, "--push", "+3d")
    assert_written(code, payload, stderr)
    assert get(child)["deadline"] == (base + timedelta(days=3)).isoformat()
    code, payload, stderr = cli("deadline", child, "--clear")
    assert code == 0 and payload["ok"], (payload, stderr)
    assert payload["urls"][0].endswith("&deadline=&auth-token=***")
    time.sleep(1.0)
    assert get(child)["deadline"] is None
    say("K.extra: update?deadline= clears a deadline: %s" % ("yes" if payload["verified"] else "unverified by CLI, DB says cleared"))


def test_07_tag_with_existing_tag():
    child = need("child_b")
    code, payload, stderr = cli("tags")
    assert code == 0
    existing = [t["title"] for t in payload["data"]]
    if not existing:
        pytest.skip("no tags exist in this Things database; tag step skipped")
    tag = existing[0]
    code, payload, stderr = cli("tag", child, "--add", tag)
    assert_written(code, payload, stderr)
    assert tag in get(child).get("tags", [])
    assert "tag not found in Things, dropped" not in " ".join(payload["warnings"])
    # A tag that does not exist is dropped with a warning. When it was the ONLY tag asked for, the
    # write would be a no-op, so the CLI refuses it (exit 1, "no valid tags to apply") rather than
    # sending an empty add-tags. The warning is still reported. See SPEC E.8.
    code, payload, stderr = cli("tag", child, "--add", "NoSuchTag-%s" % STAMP)
    assert code == 1 and payload["ok"] is False and payload["error"] == "no valid tags to apply"
    assert "tag not found in Things, dropped: NoSuchTag-%s" % STAMP in payload["warnings"]
    assert payload["urls"] == [] and payload["sent"] is False
    # A mix keeps the surviving tags and still warns about the dropped one.
    code, payload, stderr = cli("tag", child, "--add", "%s,NoSuchTag-%s" % (tag, STAMP))
    assert_written(code, payload, stderr)
    assert "tag not found in Things, dropped: NoSuchTag-%s" % STAMP in payload["warnings"]


def test_08_complete_children_then_projects():
    project = need("project")
    children = [need("child_a"), need("child_b")]
    code, payload, stderr = cli("complete", *children)
    assert_written(code, payload, stderr)
    assert payload["data"]["done"] == children
    for child in children:
        assert get(child)["status"] == "completed"
    code, payload, stderr = cli("complete", project)
    assert_written(code, payload, stderr)
    assert payload["urls"][0].startswith("things:///update-project?"), "projects go through update-project"
    assert get(project)["status"] == "completed"
    if "json_project" in STATE:
        code, payload, stderr = cli("complete", STATE["json_child"])
        assert_written(code, payload, stderr)
        code, payload, stderr = cli("complete", STATE["json_project"])
        assert_written(code, payload, stderr)
        assert get(STATE["json_project"])["status"] == "completed"


# ---- SPEC K open questions ------------------------------------------------------------------------------

def test_09_probe_k1_update_when_anytime():
    project = need("project")
    code, payload, stderr = cli("add", "Live probe K1 %s" % STAMP, "--list-id", project, "--when", "today")
    payload = assert_written(code, payload, stderr)
    probe = payload["ids"][0]
    code, payload, stderr = cli("update", probe, "--when", "anytime")
    assert code in (0, 2), (payload, stderr)
    assert "when=anytime is undocumented for update; check the result in Things" in payload["warnings"]
    time.sleep(1.5)
    item = get(probe)
    works = item["start"] == "Anytime" and item["start_date"] is None
    say("K.1 update?when=anytime on an existing to-do: %s (start=%r start_date=%r verified=%r)"
        % ("WORKS" if works else "DOES NOT WORK", item["start"], item["start_date"], payload["verified"]))
    if not works:
        code, payload, stderr = cli("update", probe, "--clear", "when")
        time.sleep(1.5)
        item = get(probe)
        say("K.1b update?when= (clear) moves to Anytime: %s (start=%r start_date=%r)"
            % (item["start"] == "Anytime" and item["start_date"] is None, item["start"], item["start_date"]))
    cli("complete", probe)


def test_10_probe_k2_evening_start_bucket():
    project = need("project")
    code, payload, stderr = cli("add", "Live probe K2 evening %s" % STAMP, "--list-id", project, "--when", "evening")
    payload = assert_written(code, payload, stderr)
    probe = payload["ids"][0]
    time.sleep(1.0)
    code, payload, stderr = cli("today")
    assert code == 0, stderr
    rows = [i for i in payload["data"]["items"] if i["uuid"] == probe]
    assert rows, "the evening to-do must appear in today()"
    evening_flag = rows[0]["evening"]
    say("K.2 TMTask.startBucket = 1 means This Evening: %s (evening flag on a when=evening to-do = %r; warnings=%r)"
        % ("CONFIRMED" if evening_flag else "NOT CONFIRMED", evening_flag, payload["warnings"]))
    assert "evening detection unavailable" not in payload["warnings"]
    cli("complete", probe)


def test_11_probe_k3_and_k8_repeating(monkeypatch):
    if not REPEATING_ID:
        pytest.skip("set THINGS_SKILLS_LIVE_REPEATING_ID=<uuid of an existing repeating to-do> to probe K.3/K.8")
    code, payload, stderr = cli("get", REPEATING_ID)
    assert code == 0 and payload["data"]["repeating"] is True, "the id must be a repeating to-do (template or instance)"
    before = payload["data"]
    code, payload, stderr = cli("complete", REPEATING_ID)
    assert code == 4 and payload["error"] == "all 1 items are repeating to-dos"
    say("K.3 our CLI refuses complete on repeating id %s: exit 4 as specified" % REPEATING_ID)
    # What Things itself does: send the raw update through the transport (bypassing the CLI refusal).
    sys.path.insert(0, os.path.join(os.path.dirname(CLI_PATH)))
    from things_lib import token as token_mod, transport, url as url_mod
    undo_isolation(monkeypatch)
    tok = token_mod.resolve_token()
    transport.send(url_mod.build("update", {"id": REPEATING_ID, "completed": True}, token=tok), "open", "update")
    time.sleep(2.0)
    after = get(REPEATING_ID)
    say("K.3 Things on update?completed=true for a repeating %s: status %r -> %r (%s)"
        % ("instance" if before.get("start_date") else "template", before["status"], after["status"],
           "REFUSED, E.9 stays" if after["status"] == before["status"] else "ACCEPTED: relax E.9 for instances"))
    if after["status"] != before["status"]:
        # Best-effort restore; never a hard assert, the K.3 answer above must survive a failed restore.
        transport.send(url_mod.build("update", {"id": REPEATING_ID, "completed": False}, token=tok), "open", "update")
        time.sleep(2.0)
        restored = get(REPEATING_ID)["status"]
        say("K.3 restore completed=false: %s -> %r; check %s by hand (a new instance may have been generated)"
            % (after["status"], restored, before.get("link")))
    # K.8: move on a repeating item, then move it back where it was.
    origin = {"list-id": before.get("project") or before.get("area")}
    if not origin["list-id"]:
        say("K.8 skipped: repeating item has no project/area to move back to")
        return
    project = need("project")
    code, payload, stderr = cli("move", REPEATING_ID, "--list-id", project)
    time.sleep(1.5)
    moved = get(REPEATING_ID)
    say("K.8 update?list-id on a repeating to-do: %s (project now %r, exit %d, verified %r)"
        % ("WORKS" if moved.get("project") == project else "DOES NOT WORK", moved.get("project"), code, payload["verified"]))
    if moved.get("project") == project:
        code, payload, stderr = cli("move", REPEATING_ID, "--list-id", origin["list-id"])
        assert code == 0, "moving the repeating item back failed; restore it by hand: %s" % before.get("link")


def test_99_print_links_for_manual_trashing(capsys):
    lines = ["", "=" * 78, "things-skills live run %s: trash these by hand (the URL scheme cannot delete):" % STAMP]
    lines += ["  " + link for link in STATE["links"]] or ["  (no project was created)"]
    lines += ["", "Open-question answers:"] + ["  " + a for a in STATE["answers"]] + ["=" * 78, ""]
    with capsys.disabled():
        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()
    assert STATE["links"], "no project link to print; earlier steps failed"
