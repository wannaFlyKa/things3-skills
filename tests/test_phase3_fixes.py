"""Phase 3 decision tests: regressions for the fixes applied after the tester's pass.

Letters refer to the Phase 3 decision list: A token masking in transport errors, B unexpected-error
envelope and add-json read errors, C token file decoding, J private temp files, K `--push=-Nd`,
L add-json update verification, O plan.py --candidates-json, P record timestamps, Q deadline --push.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from conftest import CLI_PATH, FIXTURE_DB, ROOT
from things_lib import read
from things_lib import transport as transport_mod
from things_lib.token import EMPTY_TEXT, TokenError, read_token
from things_lib.transport import TransportError, send

NOW = ["--now", "2026-09-09T10:00"]
OVERDUE_TODAY = "KisAmSsnzCcRRumjY4TkVV"   # deadline 2021-05-21
TODO_INBOX = "DfYoiXcNLQssk9DkSoJV3Y"      # no deadline
SKILLS = os.path.join(ROOT, "plugins", "things", "skills")


class FakeCompleted:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def load_cli():
    loader = importlib.machinery.SourceFileLoader("things_cli_p3", CLI_PATH)
    spec = importlib.util.spec_from_loader("things_cli_p3", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def run_main(capsys, argv):
    code = load_cli().main(argv)
    out = capsys.readouterr()
    assert out.out.count("\n") == 1, out.out
    return code, json.loads(out.out), out.err


def write_token(tmp_path, content, mode=0o600):
    directory = tmp_path / ".config" / "things-skills"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "auth-token"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return str(path)


def fake_darwin(monkeypatch, run):
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(transport_mod.subprocess, "run", run)


# ---- A: `open` stderr and TimeoutExpired can echo the URL; the token must never come through ----------

URL = "things:///update?id=%s&completed=true&auth-token=SECRET" % TODO_INBOX


def test_open_failure_stderr_echoing_the_url_is_masked(monkeypatch):
    fake_darwin(monkeypatch, lambda argv, **kw: FakeCompleted(
        1, "LSOpenURLsWithRole() failed with error -10814 for the URL %s." % argv[-1]))
    with pytest.raises(TransportError) as info:
        send(URL, "open", "update")
    assert "SECRET" not in str(info.value)
    assert "auth-token=***" in str(info.value) and str(info.value).startswith("open exited 1: ")


def test_open_timeout_text_repeating_argv_is_masked(monkeypatch):
    def timeout(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 15)
    fake_darwin(monkeypatch, timeout)
    with pytest.raises(TransportError) as info:
        send(URL, "open", "update")
    assert "SECRET" not in str(info.value) and "auth-token=***" in str(info.value)


def test_open_success_stderr_is_masked_in_send_result(monkeypatch):
    fake_darwin(monkeypatch, lambda argv, **kw: FakeCompleted(0, "opened %s" % argv[-1]))
    result = send(URL, "open", "update")
    assert result.sent is True and "SECRET" not in result.stderr and "SECRET" not in result.masked_url


def test_cli_envelope_error_masks_token_when_open_fails(monkeypatch, capsys, tmp_path):
    write_token(tmp_path, "SECRET\n")
    fake_darwin(monkeypatch, lambda argv, **kw: FakeCompleted(1, "LSOpenURLsWithRole() failed for the URL %s" % argv[-1]))
    code, payload, err = run_main(capsys, NOW + ["--transport", "open", "complete", TODO_INBOX])
    assert code == 2 and payload["ok"] is False
    assert "SECRET" not in json.dumps(payload) and "SECRET" not in err
    assert "auth-token=***" in payload["error"]


# ---- B: no traceback ever; add-json read errors; warnings survive error paths -------------------------

def test_add_json_latin1_file_is_a_cannot_read_envelope(run_cli, tmp_path):
    path = tmp_path / "latin1.json"
    path.write_bytes('[{"type":"to-do","attributes":{"title":"caf\xe9"}}]'.encode("latin-1"))
    code, payload, err = run_cli(*NOW, "add-json", str(path), "--dry-run")
    assert code == 1 and payload["ok"] is False
    assert payload["error"].startswith("cannot read %s: " % path)
    assert "Traceback" not in err


def test_unexpected_exception_becomes_an_exit_1_envelope(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise KeyError("uuid")
    monkeypatch.setattr(read, "inbox", boom)
    code, payload, err = run_main(capsys, NOW + ["inbox"])
    assert code == 1 and payload["ok"] is False
    assert payload["error"].startswith("unexpected error: KeyError: ")
    assert "Traceback" not in err and err.startswith("error: unexpected error")


def test_unexpected_exception_text_is_token_masked(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("bad url things:///update?id=X&auth-token=SECRET")
    monkeypatch.setattr(read, "inbox", boom)
    code, payload, _ = run_main(capsys, NOW + ["inbox"])
    assert code == 1 and "SECRET" not in payload["error"] and "auth-token=***" in payload["error"]


def test_read_warnings_are_kept_when_the_command_fails(monkeypatch, capsys):
    def warn_then_fail(*args, **kwargs):
        read._warn("fixture warning")
        raise read.ReadError("boom")
    monkeypatch.setattr(read, "inbox", warn_then_fail)
    code, payload, _ = run_main(capsys, NOW + ["inbox"])
    assert code == 3 and payload["error"] == "boom"
    assert "fixture warning" in payload["warnings"]


# ---- C: the token is the first non-blank line, stripped; a BOM is ignored ------------------------------

def test_token_skips_leading_blank_lines(tmp_path):
    write_token(tmp_path, "\n   \n\t\nSECRET\nsecond line\n")
    assert read_token() == "SECRET"


def test_token_bom_crlf_and_padding(tmp_path):
    write_token(tmp_path, b"\xef\xbb\xbf\r\n  SECRET  \r\nmore\r\n")
    assert read_token() == "SECRET"


def test_token_file_of_only_blank_lines_is_empty(tmp_path):
    write_token(tmp_path, "\n \n\t\n")
    with pytest.raises(TokenError) as info:
        read_token()
    assert str(info.value) == EMPTY_TEXT


# ---- K + Q: deadline --push ------------------------------------------------------------------------------

def test_deadline_push_negative_offset_in_equals_form(run_cli):
    code, payload, _ = run_cli(*NOW, "deadline", OVERDUE_TODAY, "--push=-1d", "--dry-run")
    assert code == 0 and payload["ok"] is True, payload
    assert payload["urls"] == ["things:///update?id=%s&deadline=2021-05-20&auth-token=***" % OVERDUE_TODAY]


def test_deadline_push_strips_whitespace_and_rejects_bad_specs(run_cli):
    code, payload, _ = run_cli(*NOW, "deadline", OVERDUE_TODAY, "--push", " +1d ", "--dry-run")
    assert code == 0 and "deadline=2021-05-22" in payload["urls"][0]
    code, payload, _ = run_cli(*NOW, "deadline", OVERDUE_TODAY, "--push", "+1x", "--dry-run")
    assert code == 1 and payload["ok"] is False and payload["urls"] == []


def test_deadline_push_when_no_target_has_a_deadline(run_cli):
    code, payload, _ = run_cli(*NOW, "deadline", TODO_INBOX, "--push", "+3d", "--dry-run")
    assert code == 1 and payload["error"] == "no target has a deadline to push"
    assert payload["data"] == {"done": [], "skipped": [{"id": TODO_INBOX, "title": "To-Do in Inbox",
                                                         "reason": "no deadline to push"}]}
    assert "%s has no deadline to push; skipped" % TODO_INBOX in payload["warnings"]


def test_deadline_push_mixed_targets_pushes_the_one_with_a_deadline(run_cli):
    code, payload, _ = run_cli(*NOW, "deadline", TODO_INBOX, OVERDUE_TODAY, "--push", "+1w", "--dry-run")
    assert code == 0 and payload["data"]["done"] == [OVERDUE_TODAY]
    assert [s["id"] for s in payload["data"]["skipped"]] == [TODO_INBOX]
    assert "deadline=2021-05-28" in payload["urls"][0]


# ---- P: record timestamps: naive now is local time, the Z suffix is true UTC ----------------------------

def test_record_treats_naive_now_as_local_time(tmp_path):
    naive = datetime(2026, 9, 9, 10, 30, 5)
    send("things:///add?title=x", "record", "add", now=lambda: naive)
    with open(os.path.join(str(tmp_path), ".things-skills", "outbox.jsonl"), encoding="utf-8") as handle:
        line = json.loads(handle.read().splitlines()[-1])
    assert line["ts"] == naive.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    aware = datetime(2026, 9, 9, 2, 0, 0, tzinfo=timezone.utc)
    send("things:///add?title=y", "record", "add", now=lambda: aware)
    with open(os.path.join(str(tmp_path), ".things-skills", "outbox.jsonl"), encoding="utf-8") as handle:
        line = json.loads(handle.read().splitlines()[-1])
    assert line["ts"] == "2026-09-09T02:00:00Z"


# ---- L: add-json update-only verification checks the update object's own attributes -------------------

def update_payload(tmp_path, attributes):
    path = tmp_path / "update.json"
    path.write_text(json.dumps([{"type": "to-do", "operation": "update", "id": TODO_INBOX,
                                 "attributes": attributes}]), encoding="utf-8")
    return str(path)


def test_add_json_update_predicate_fails_until_every_attribute_is_visible(monkeypatch, capsys, tmp_path):
    write_token(tmp_path, "SECRET\n")
    fake_darwin(monkeypatch, lambda argv, **kw: FakeCompleted(0))
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    path = update_payload(tmp_path, {"title": "Renamed", "completed": True})
    monkeypatch.setattr(read, "get", lambda item_id, *a, **k: {"uuid": item_id, "title": "Renamed",
                                                              "status": "incomplete", "type": "to-do"})
    code, payload, _ = run_main(capsys, NOW + ["--transport", "open", "--verify-timeout", "0.6", "add-json", path])
    assert code == 2 and payload["verified"] is False and payload["verify_reason"].startswith("timeout")
    monkeypatch.setattr(read, "get", lambda item_id, *a, **k: {"uuid": item_id, "title": "Renamed",
                                                              "status": "completed", "type": "to-do"})
    code, payload, _ = run_main(capsys, NOW + ["--transport", "open", "--verify-timeout", "0.6", "add-json", path])
    assert code == 0 and payload["verified"] is True and payload["ids"] == [TODO_INBOX]
    assert payload["links"] == ["things:///show?id=" + TODO_INBOX]


def test_add_json_update_tags_are_checked_as_a_subset(monkeypatch, capsys, tmp_path):
    write_token(tmp_path, "SECRET\n")
    fake_darwin(monkeypatch, lambda argv, **kw: FakeCompleted(0))
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    monkeypatch.setattr(read, "tag_titles", lambda: ["Errand", "Home"])
    path = update_payload(tmp_path, {"tags": ["Errand"], "deadline": "2026-10-01"})
    monkeypatch.setattr(read, "get", lambda item_id, *a, **k: {"uuid": item_id, "title": "x", "status": "incomplete",
                                                              "type": "to-do", "tags": ["Home", "Errand"],
                                                              "deadline": "2026-10-01"})
    code, payload, _ = run_main(capsys, NOW + ["--transport", "open", "--verify-timeout", "0.6", "add-json", path])
    assert code == 0 and payload["verified"] is True, payload


def test_add_json_update_without_checkable_attribute_is_not_verifiable(monkeypatch, capsys, tmp_path):
    write_token(tmp_path, "SECRET\n")
    fake_darwin(monkeypatch, lambda argv, **kw: FakeCompleted(0))
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    path = update_payload(tmp_path, {"append-notes": "more"})
    code, payload, _ = run_main(capsys, NOW + ["--transport", "open", "add-json", path])
    assert code == 0 and payload["sent"] is True
    assert payload["verified"] is False and payload["verify_reason"] == "update payload not verifiable"
    assert payload["ids"] == [TODO_INBOX] and payload["links"] == ["things:///show?id=" + TODO_INBOX]


# ---- J + O: helper temp files are private; plan.py takes the candidates inline ---------------------------

def helper(skill, name):
    return os.path.join(SKILLS, skill, "scripts", name)


def wrapper_ref(skill):
    """Helpers print the ABSOLUTE path of the sibling wrapper: ${CLAUDE_SKILL_DIR} is substituted only in SKILL.md text."""
    return os.path.join(SKILLS, skill, "scripts", "things")


def run_helper(tmp_path, skill, name, *args, stdin=None):
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update({"THINGSDB": FIXTURE_DB, "HOME": str(tmp_path), "TMPDIR": str(tmpdir),
                "THINGS_SKILLS_TRANSPORT": "record"})
    env.pop("THINGS_SKILLS_CONFIG", None)
    proc = subprocess.run([sys.executable, helper(skill, name), *args], capture_output=True, text=True,
                          env=env, input=stdin, timeout=120, cwd=str(tmp_path))
    assert "Traceback" not in proc.stderr, proc.stderr
    return proc.returncode, proc.stdout, proc.stderr


def test_review_saved_file_is_private_and_apply_trusts_only_own_files(tmp_path, monkeypatch, capsys):
    code, out, err = run_helper(tmp_path, "things-organize", "review.py", "--scope", "inbox", *NOW, "--lang", "en")
    assert code == 0, err
    saved = json.loads(out)["saved"]
    assert os.path.basename(saved).startswith("things-organize-") and saved.endswith(".json")
    assert os.stat(saved).st_mode & 0o777 == 0o600
    assert all(c["command"].startswith(wrapper_ref("things-organize") + " ") for c in json.loads(out)["proposals"])
    assert "${CLAUDE_SKILL_DIR}" not in out
    # --apply without --from uses the newest file only when this user owns it
    loader = importlib.machinery.SourceFileLoader("review_p3", helper("things-organize", "review.py"))
    spec = importlib.util.spec_from_loader("review_p3", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: os.path.dirname(saved))
    assert module.main(["--apply", "1"]) == 0
    capsys.readouterr()
    real_uid = os.getuid()
    monkeypatch.setattr(module.os, "getuid", lambda: real_uid + 1)
    assert module.main(["--apply", "1"]) == 1
    assert "belongs to another user" in json.loads(capsys.readouterr().out)["error"]
    assert module.main(["--apply", "1", "--from", saved]) == 0, "an explicit --from is always honoured"


def load_helper(skill, name, module_name):
    loader = importlib.machinery.SourceFileLoader(module_name, helper(skill, name))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# ---- Second audit round (findings 2017, 2013, 2014, 2015, 2005) ------------------------------------------

def test_review_evening_keeps_scheduled_items_reported_as_someday():
    """Finding 2017: things.py reports Upcoming and scheduled-Today items with start == 'Someday' plus a start_date;
    only UNDATED Someday items (and Inbox) belong to another check."""
    review = load_helper("things-organize", "review.py", "review_p3_evening")
    now = datetime(2026, 9, 9, 10, 0)
    ctx = {"lang": "en", "now": now, "today": now.date(), "today_ids": {"k5"}, "evening_ids": set(),
           "universe": [{"uuid": "k1", "type": "to-do", "title": "健身", "start": "Someday"},
                        {"uuid": "k2", "type": "to-do", "title": "买菜", "start": "Inbox"},
                        {"uuid": "k3", "type": "to-do", "title": "gym", "start": "Anytime"},
                        {"uuid": "k4", "type": "to-do", "title": "gym", "start": "Someday", "start_date": "2026-09-17"},
                        {"uuid": "k5", "type": "to-do", "title": "gym", "start": "Someday", "start_date": "2026-09-01"}]}
    props, summary = review.check_evening(ctx, None)
    flags = {p["id"]: p["options"][0]["flags"] for p in props}
    assert [p["id"] for p in props] == ["k3", "k4", "k5"]
    assert flags["k4"] == ["--when", "2026-09-17@18:00"], "Upcoming item: its own start date at 18:00"
    assert flags["k5"] == ["--when", "evening"], "scheduled item sitting in Today: This Evening"
    assert summary == "3 proposals"


def test_review_summary_has_a_singular_form():
    """Finding 2013: '1 proposals'."""
    review = load_helper("things-organize", "review.py", "review_p3_count")
    assert review.count_words("en", 0) == "nothing to do"
    assert review.count_words("en", 1) == "1 proposal"
    assert review.count_words("en", 2) == "2 proposals"
    assert review.count_words("zh", 1) == "1 条建议" and review.count_words("zh", 3) == "3 条建议"
    now = datetime(2026, 9, 9, 10, 0)
    ctx = {"lang": "en", "now": now, "today": now.date(), "today_ids": set(), "evening_ids": set(), "warnings": [],
           "config": {"someday_resurface_days": 90},
           "someday": [{"uuid": "s1", "type": "to-do", "title": "old", "modified": "2026-01-01 00:00:00"}]}
    props, summary = review.check_someday(ctx, None)
    assert len(props) == 1 and summary == "1 proposal"


def test_review_routing_without_areas_names_the_projects():
    """Finding 2014: Things with no areas produced 'pick an area (-)', a list the user cannot pick from."""
    review = load_helper("things-organize", "review.py", "review_p3_route")
    ctx = {"lang": "en", "project_titles": ["Home Renovation", "Q4"], "area_titles": [],
           "config": {"routing_hints": [{"pattern": "报销", "area": "Work", "project": None, "regex": False}]}}
    words, target, kind, needs_input = review.resolve_route(ctx, {"title": "nothing", "notes": ""})
    assert words == ("no routing hint matched and Things has no areas yet: create one, or for a to-do name a project "
                     "(Home Renovation, Q4)")
    assert (target, kind, needs_input) == ("<AREA>", "area", True)
    words = review.resolve_route(ctx, {"title": "报销 8 月发票", "notes": ""})[0]
    assert words == ("routing hint matched area “Work” but Things has no such area and no areas yet: create it, or for a "
                     "to-do name a project (Home Renovation, Q4)")
    assert "(-)" not in words
    ctx["project_titles"] = []
    assert review.resolve_route(ctx, {"title": "nothing", "notes": ""})[0].endswith("name a project (-)")
    ctx["lang"] = "zh"
    assert review.resolve_route(ctx, {"title": "nothing", "notes": ""})[0] == \
        "没有匹配的路由规则，且 Things 里还没有领域：先创建一个，或（待办）填一个项目（-）"
    # with areas present the wording is unchanged
    ctx.update({"lang": "en", "area_titles": ["Home"]})
    assert review.resolve_route(ctx, {"title": "nothing", "notes": ""})[0] == "no routing hint matched, pick an area (Home)"


def test_review_repeating_warning_names_the_check_that_skipped(tmp_path):
    """Finding 2015: 'skipped repeating to-do X' sat under a tag-hygiene proposal that moves X, which is valid."""
    code, out, err = run_helper(tmp_path, "things-organize", "review.py", "--scope", "all", *NOW, "--lang", "en")
    assert code == 0, err
    result = json.loads(out)
    warnings = [w for w in result["warnings"] if "repeating to-do “Repeating To-Do”" in w]
    assert warnings == ["deadline check skipped repeating to-do “Repeating To-Do”: when/deadline can only be changed in "
                        "Things (moving it to an area or project still works)"]
    moves = [p for p in result["proposals"] if p["title"] == "Repeating To-Do" and p["check"] == "tags"]
    assert moves and " move " in moves[0]["command"], "the container move for a repeating to-do is still proposed"
    code, out, err = run_helper(tmp_path, "things-organize", "review.py", "--scope", "all", *NOW, "--lang", "zh")
    assert any(w.startswith("截止日期检查跳过了重复任务「Repeating To-Do」") for w in json.loads(out)["warnings"])


def test_plan_blocked_candidate_has_no_command_anywhere(tmp_path):
    """Finding 2005: JSON mode leaked the unconfirmed command in candidates[].command, wrote the add-json payload of a
    blocked project and printed 'Create these 0 item(s)?'."""
    only = json.dumps([{"text": "finish the expense report Friday"}])
    code, out, err = run_helper(tmp_path, "things-capture", "plan.py", *NOW, "--candidates-json", only)
    assert code == 0, err
    plan = json.loads(out)
    assert plan["commands"] == [] and [b["index"] for b in plan["blocked"]] == [1]
    assert plan["candidates"][0]["command"] is None
    assert plan["confirm_prompt"] is None, "no prompt when nothing is runnable"
    assert "expense" not in json.dumps(plan["commands"])
    mixed = json.dumps([{"text": "finish the expense report Friday"},
                        {"text": "launch website Friday", "phases": [{"title": "Draft", "todos": ["write outline"]}]},
                        {"text": "call mom Friday"}], ensure_ascii=False)
    code, out, err = run_helper(tmp_path, "things-capture", "plan.py", *NOW, "--candidates-json", mixed)
    assert code == 0, err
    plan = json.loads(out)
    assert [c["index"] for c in plan["commands"]] == [3] and [b["index"] for b in plan["blocked"]] == [1, 2]
    assert plan["candidates"][0]["command"] is None and plan["candidates"][1]["command"] is None
    assert "payload_file" not in plan["candidates"][1] and plan["payload_files"] == {}
    assert list((tmp_path / "tmpdir").glob("things-capture-*.json")) == [], "no payload file for a blocked project"
    assert len(plan["questions"]) == 2 and plan["confirm_prompt"] is None, "questions replace the prompt, as in Markdown"
    assert "add-json" not in plan["preview_markdown"]
    # nothing blocked: the prompt counts the runnable commands as before
    code, out, err = run_helper(tmp_path, "things-capture", "plan.py", *NOW, "--candidates-json",
                                json.dumps([{"text": "call mom Friday"}, {"text": "buy milk"}]))
    plan = json.loads(out)
    assert plan["confirm_prompt"] == "Create these 2 item(s)? (y / numbers like 1,3 / all)"


def test_plan_candidates_json_matches_stdin_and_payload_file_is_private(tmp_path):
    candidates = [{"text": "launch the newsletter", "title": "Launch newsletter",
                   "phases": [{"title": "Draft", "todos": [{"text": "write outline", "title": "write outline"}]}]},
                  {"text": "明天下午3点给妈妈打电话", "title": "给妈妈打电话"}]
    raw = json.dumps(candidates, ensure_ascii=False)
    code, inline, err = run_helper(tmp_path, "things-capture", "plan.py", *NOW, "--candidates-json", raw)
    assert code == 0, err
    code, piped, err = run_helper(tmp_path, "things-capture", "plan.py", *NOW, stdin=raw)
    assert code == 0, err
    inline, piped = json.loads(inline), json.loads(piped)
    assert [c["title"] for c in inline["candidates"]] == [c["title"] for c in piped["candidates"]]
    assert inline["commands"][1]["command"] == piped["commands"][1]["command"]
    for path in inline["payload_files"].values():
        assert os.path.basename(path).startswith("things-capture-") and os.stat(path).st_mode & 0o777 == 0o600
    assert len(inline["payload_files"]) == 1 and inline["commands"][0]["command"].startswith(
        wrapper_ref("things-capture") + " add-json ")
    assert "${CLAUDE_SKILL_DIR}" not in json.dumps(inline)
