"""CLI envelope, exit codes and subcommand behaviour (SPEC section E)."""

import importlib.machinery
import importlib.util
import json
import os
import platform

import pytest

from conftest import CLI_PATH, FIXTURE_DB, SCRIPTS

# These assert Linux-only behaviour (transport 'open' unavailable, doctor.platform == 'Linux').
# On macOS the same code correctly reports Darwin and offers 'open', so the tests must not run there.
# The Darwin paths are covered platform-independently by test_phase3_fixes.py and
# test_spec_token_transport.py, which monkeypatch platform.system() to "Darwin".
linux_only = pytest.mark.skipif(platform.system() != "Linux", reason="asserts Linux-only CLI behaviour")

ENVELOPE_KEYS = ["ok", "command", "data", "urls", "sent", "verified", "verify_reason", "ids", "links", "warnings", "error"]
NOW = ["--now", "2026-09-09T10:00"]
REPEATING_WARNING = ("Repeating to-dos may be missing: things.py only sees instances Things has already generated. "
                     "Open Things once to refresh.")


def load_cli_module():
    loader = importlib.machinery.SourceFileLoader("things_cli", CLI_PATH)
    spec = importlib.util.spec_from_loader("things_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def assert_envelope(payload):
    assert list(payload.keys()) == ENVELOPE_KEYS
    assert isinstance(payload["urls"], list) and isinstance(payload["warnings"], list)


def test_cli_file_shape():
    with open(CLI_PATH, "rb") as handle:
        assert handle.readline() == b"#!/usr/bin/env python3\n"
    # git stores only the executable bit, so a clone made under umask 002 is 0775: assert the x bits, not 0755
    mode = os.stat(CLI_PATH).st_mode
    assert mode & 0o111 == 0o111
    assert not mode & 0o002, "CLI must not be world writable"   # group-writable 0775 (umask 002) stays legal
    assert not CLI_PATH.endswith(".py")


def test_main_is_importable(capsys):
    module = load_cli_module()
    code = module.main(["--dry-run", "add", "Hello"])
    out = capsys.readouterr()
    assert code == 0
    payload = json.loads(out.out)
    assert_envelope(payload)
    assert payload["urls"] == ["things:///add?title=Hello"]
    assert out.out.count("\n") == 1


@pytest.mark.parametrize("args", [["inbox"], ["today"], ["doctor"], ["parse-date", "明天"], ["--dry-run", "add", "x"]])
def test_envelope_keys_always_present(run_cli, args):
    code, payload, _ = run_cli(*args)
    assert code == 0
    assert_envelope(payload)
    assert payload["ok"] is True and payload["error"] is None


def test_exit_0_reads(run_cli):
    code, payload, _ = run_cli(*NOW, "inbox")
    assert code == 0 and len(payload["data"]) == 2
    assert payload["urls"] == [] and payload["verified"] is None


def test_exit_1_usage_and_invalid_when(run_cli):
    code, payload, stderr = run_cli("--dry-run", "add", "买牛奶", "--when", "明天")
    assert code == 1 and payload["ok"] is False
    assert payload["error"] == "invalid --when value '明天'; run: things parse-date '明天'"
    assert stderr.startswith("error: invalid --when value")
    code, payload, _ = run_cli("bogus")
    assert code == 1 and payload["ok"] is False
    code, payload, _ = run_cli("get", "nope")
    assert code == 1 and payload["error"] == "no item with id nope"
    code, payload, _ = run_cli("--dry-run", "add", "x", "--deadline", "someday")
    assert code == 1


def test_exit_1_token_missing_exact_text(run_cli):
    # record transport (the Linux default): a real send needs the token -> exit 1 with the exact text
    code, payload, stderr = run_cli("complete", "ABC123", "DEF456")
    assert code == 1
    assert payload["error"] == ("Things auth token not found: ~/.config/things-skills/auth-token is missing. "
                                "Create it from Things → Settings → General → Enable Things URLs → Manage.")
    assert stderr.strip() == "error: " + payload["error"]


def test_dry_run_is_token_free(run_cli):
    # SPEC E.3: --dry-run sends nothing, so a missing token becomes a masked placeholder plus a warning
    # real fixture ids (unknown ids are skipped when the database is readable, E.8)
    code, payload, _ = run_cli("--dry-run", "complete", "5pUx6PESj3ctFYbgth1PXY", "DfYoiXcNLQssk9DkSoJV3Y")
    assert code == 0 and payload["ok"] is True
    assert payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&completed=true&auth-token=***",
                               "things:///update?id=DfYoiXcNLQssk9DkSoJV3Y&completed=true&auth-token=***"]
    assert "auth token not found; dry-run continues with a placeholder" in payload["warnings"]
    assert "DRY-RUN-PLACEHOLDER" not in json.dumps(payload)


@linux_only
def test_exit_2_open_transport_on_linux(run_cli, token_file):
    code, payload, _ = run_cli("--transport", "open", "add", "x")
    assert code == 2 and payload["error"] == "transport 'open' is only available on macOS"
    code, payload, _ = run_cli("ping", env={"THINGS_SKILLS_TRANSPORT": "open"})
    assert code == 2


def test_exit_3_bad_database(run_cli):
    code, payload, _ = run_cli("inbox", env={"THINGSDB": "/nonexistent/main.sqlite"})
    assert code == 3 and payload["ok"] is False and "unable to open database file" in payload["error"]


def test_exit_4_repeating(run_cli, token_file):
    code, payload, _ = run_cli("complete", "K9bx7h1xCJdevvyWardZDq")
    assert code == 4
    assert payload["error"] == "all 1 items are repeating to-dos"
    assert payload["data"]["done"] == [] and payload["data"]["skipped"][0]["id"] == "K9bx7h1xCJdevvyWardZDq"
    assert payload["data"]["skipped"][0]["title"] == "Repeating To-Do"
    assert payload["data"]["skipped"][0]["reason"].startswith("repeating to-do: Things URL scheme cannot change")
    assert payload["urls"] == []


def test_partial_repeating_skip_exit_0(run_cli, token_file):
    code, payload, _ = run_cli("complete", "5pUx6PESj3ctFYbgth1PXY", "K9bx7h1xCJdevvyWardZDq")
    assert code == 0 and payload["ok"] is True
    assert payload["data"]["done"] == ["5pUx6PESj3ctFYbgth1PXY"]
    assert [s["id"] for s in payload["data"]["skipped"]] == ["K9bx7h1xCJdevvyWardZDq"]
    assert payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&completed=true&auth-token=***"]
    assert any("K9bx7h1xCJdevvyWardZDq" in w for w in payload["warnings"])
    assert payload["verified"] is False and payload["verify_reason"] == "transport record: nothing was sent to Things"
    assert payload["ids"] == ["5pUx6PESj3ctFYbgth1PXY"] and payload["links"] == ["things:///show?id=5pUx6PESj3ctFYbgth1PXY"]


def test_yes_threshold(run_cli, token_file):
    ids = [f"ID{i}" for i in range(11)]
    code, payload, _ = run_cli("--dry-run", "complete", *ids, env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 4 and payload["error"] == "refusing to modify 11 items without --yes"
    code, payload, _ = run_cli("--dry-run", "--yes", "complete", *ids, env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 0 and len(payload["urls"]) == 11
    code, payload, _ = run_cli("--dry-run", "complete", *ids[:10], env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 0


def test_dry_run_add_cjk_and_english(run_cli):
    code, payload, _ = run_cli("--dry-run", "add", "买牛奶 a/b & c", "--when", "tomorrow", "--tags", "Errand",
                               "--checklist", "买菜", "--checklist", "做饭")
    assert code == 0 and payload["sent"] is False and payload["verified"] is None
    assert payload["urls"] == ["things:///add?title=%E4%B9%B0%E7%89%9B%E5%A5%B6%20a%2Fb%20%26%20c&when=tomorrow"
                               "&tags=Errand&checklist-items=%E4%B9%B0%E8%8F%9C%0A%E5%81%9A%E9%A5%AD"]
    code, payload, _ = run_cli("--dry-run", "add", "Review a/b test & ship #1", "--notes", "line1\nline2", "--list", "Work")
    assert payload["urls"] == ["things:///add?title=Review%20a%2Fb%20test%20%26%20ship%20%231&notes=line1%0Aline2&list=Work"]
    code, payload, _ = run_cli("add", "x", "--dry-run", "--checklist", "a\nb")
    assert payload["urls"] == ["things:///add?title=x&checklist-items=a%0Ab"]


def test_dry_run_complete_masks_token(run_cli, token_file):
    code, payload, stderr = run_cli("--dry-run", "complete", "ABC123", "DEF456", env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 0
    assert payload["urls"] == ["things:///update?id=ABC123&completed=true&auth-token=***",
                               "things:///update?id=DEF456&completed=true&auth-token=***"]
    assert "SECRET" not in json.dumps(payload) + stderr
    assert payload["warnings"] == ["repeating check unavailable for ABC123", "repeating check unavailable for DEF456"]
    assert payload["ids"] == ["ABC123", "DEF456"]


def test_dry_run_add_json(run_cli, tmp_path):
    path = tmp_path / "payload.json"
    path.write_text('[{"type":"to-do","attributes":{"title":"Buy milk"}}]', encoding="utf-8")
    code, payload, _ = run_cli("--dry-run", "add-json", str(path))
    assert code == 0
    assert payload["urls"] == ["things:///json?data=%5B%7B%22type%22%3A%22to-do%22%2C%22attributes%22%3A%7B%22title%22%3A%22Buy%20milk%22%7D%7D%5D"]
    assert payload["data"] == {"objects": 1, "items": 1, "top_level_titles": ["Buy milk"]}
    code, payload, _ = run_cli("--dry-run", "add-json", "-", stdin='[{"type":"project","attributes":{"title":"P","items":[{"type":"heading","attributes":{"title":"H"}},{"type":"to-do","attributes":{"title":"T"}}]}}]')
    assert code == 0 and payload["data"]["items"] == 3
    assert payload["urls"][0].startswith("things:///json?data=") and "add-json" not in payload["urls"][0]


def test_add_json_errors(run_cli, tmp_path, token_file):
    code, payload, _ = run_cli("--dry-run", "add-json", "-", stdin="{not json")
    assert code == 1 and payload["error"].startswith("invalid JSON: ")
    code, payload, _ = run_cli("--dry-run", "add-json", "-", stdin='[{"type":"heading","attributes":{}}]')
    assert code == 1 and payload["error"] == "[0].type: 'heading' is not allowed here"
    code, payload, _ = run_cli("--dry-run", "add-json", "-", stdin='[{"type":"to-do","attributes":{"when":"next week"}}]')
    assert code == 1 and payload["error"].startswith("[0].attributes.when: ")
    code, payload, _ = run_cli("--dry-run", "add-json", "-", stdin='[{"type":"to-do","attributes":{"tags":"a"}}]')
    assert code == 1 and payload["error"] == "[0].attributes.tags: must be an array of strings"
    many = json.dumps([{"type": "to-do", "attributes": {"title": str(i)}} for i in range(251)])
    code, payload, _ = run_cli("--dry-run", "add-json", "-", stdin=many)
    assert code == 1 and payload["error"] == "payload has 251 items; split into batches of 250"
    code, payload, _ = run_cli("--dry-run", "add-json", str(tmp_path / "missing.json"))
    assert code == 1
    update = '[{"type":"to-do","operation":"update","id":"5pUx6PESj3ctFYbgth1PXY","attributes":{"title":"x"}}]'
    code, payload, _ = run_cli("--dry-run", "add-json", "-", stdin=update)
    assert code == 0 and payload["urls"][0].endswith("&auth-token=***")


def test_add_json_needs_token_only_for_updates(run_cli):
    update = '[{"type":"to-do","operation":"update","id":"X","attributes":{"title":"x"}}]'
    code, payload, _ = run_cli("add-json", "-", stdin=update, env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 1 and payload["error"].startswith("Things auth token not found")
    code, payload, _ = run_cli("--dry-run", "add-json", "-", stdin=update, env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 0 and payload["urls"][0].endswith("&auth-token=***")
    assert "auth token not found; dry-run continues with a placeholder" in payload["warnings"]


def test_record_transport_writes_outbox(run_cli, tmp_path):
    code, payload, _ = run_cli("add", "买牛奶")
    assert code == 0 and payload["sent"] is False
    assert payload["verified"] is False and payload["verify_reason"] == "transport record: nothing was sent to Things"
    assert payload["ids"] == [] and payload["links"] == []
    lines = (tmp_path / ".things-skills" / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert list(entry) == ["ts", "command", "url"] and entry["command"] == "add"
    assert entry["url"] == "things:///add?title=%E4%B9%B0%E7%89%9B%E5%A5%B6"


def test_dry_run_flag_overrides_env_transport(run_cli, tmp_path):
    code, payload, _ = run_cli("--dry-run", "add", "x", env={"THINGS_SKILLS_TRANSPORT": "record"})
    assert code == 0 and not (tmp_path / ".things-skills").exists()


def test_verify_timeout_zero(run_cli):
    code, payload, _ = run_cli("--verify-timeout", "0", "add", "x")
    assert code == 0 and payload["verified"] is False and payload["verify_reason"] == "verification disabled"


@linux_only
def test_doctor_on_linux(run_cli):
    code, payload, _ = run_cli("doctor")
    assert code == 0
    data = payload["data"]
    assert data["platform"] == "Linux" and data["transport"] == "record"
    assert data["database"] == {"path": FIXTURE_DB, "status": "fixture", "error": None}
    assert data["token"] == {"path": "~/.config/things-skills/auth-token", "present": False, "empty": False,
                             "mode_ok": None, "mode": None}
    # The CLI resolves its own location with realpath; the checkout may be reached through a symlink.
    assert os.path.realpath(data["things_py"].pop("path")) == os.path.realpath(os.path.join(SCRIPTS, "vendor", "things"))
    assert data["things_py"] == {"installed": True, "version": "1.0.1", "source": "bundled"}
    assert data["config"]["present"] is False and data["config"]["valid"] is True and data["config"]["missing_tags"] == []
    assert data["cli_version"] == "0.2.0"
    assert set(data) == {"platform", "python", "transport", "database", "token", "things_py", "config", "cli_version"}


def test_doctor_reports_token_config_and_missing_tags(run_cli, token_file, config_file):
    os.chmod(token_file, 0o644)
    config_file({"tags": ["Errand", "@nope"]})
    code, payload, _ = run_cli("doctor")
    assert code == 0
    data = payload["data"]
    assert data["token"] == {"path": "~/.config/things-skills/auth-token", "present": True, "empty": False,
                             "mode_ok": False, "mode": "0644"}
    assert data["config"]["present"] is True and data["config"]["missing_tags"] == ["@nope"]
    assert "SECRET" not in json.dumps(payload)


def test_doctor_never_fails(run_cli, tmp_path):
    bad = tmp_path / ".config" / "things-skills"
    bad.mkdir(parents=True)
    (bad / "config.json").write_text("{oops", encoding="utf-8")
    code, payload, _ = run_cli("doctor", env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 0 and payload["ok"] is True
    assert payload["data"]["config"]["valid"] is False and payload["data"]["config"]["missing_tags"] is None
    assert payload["data"]["database"]["status"] == "unavailable"


def test_doctor_survives_a_token_file_that_is_not_text(run_cli, tmp_path):
    """A binary token file must not turn into an 'unexpected error' envelope; doctor reports it as unusable."""
    directory = tmp_path / ".config" / "things-skills"
    directory.mkdir(parents=True)
    token = directory / "auth-token"
    token.write_bytes(b"\xff\xfe\x00bad")
    os.chmod(token, 0o600)
    code, payload, _ = run_cli("doctor")
    assert code == 0 and payload["ok"] is True and payload["error"] is None
    assert payload["data"]["token"]["present"] is True and payload["data"]["token"]["empty"] is True


def test_parse_date(run_cli):
    code, payload, _ = run_cli(*NOW, "parse-date", "下周五晚上8点前交周报")
    assert code == 0
    assert payload["data"] == {"when": None, "deadline": "2026-09-18", "reminder": "20:00", "remaining": "交周报", "language": "zh"}
    code, payload, _ = run_cli(*NOW, "parse-date", "Friday", "--kind", "deadline")
    assert payload["data"]["deadline"] == "2026-09-11" and payload["data"]["when"] is None
    code, payload, _ = run_cli(*NOW, "parse-date", "by Friday", "--kind", "when")
    assert payload["data"]["when"] == "2026-09-11" and payload["data"]["deadline"] is None
    code, payload, _ = run_cli("parse-date", "x", "--now", "garbage")
    assert code == 1


def test_unknown_tag_dropped_with_warning(run_cli):
    code, payload, _ = run_cli("--dry-run", "add", "x", "--tags", "Errand,Bogus", "--tags", "home")
    assert code == 0
    assert payload["urls"] == ["things:///add?title=x&tags=Errand%2CHome"]
    assert payload["warnings"] == ["tag not found in Things, dropped: Bogus"]
    code, payload, _ = run_cli("--dry-run", "add", "x", "--tags", "Bogus", env={"THINGSDB": "/nonexistent.sqlite"})
    assert payload["urls"] == ["things:///add?title=x&tags=Bogus"]
    assert payload["warnings"] == ["database unavailable: tags not verified"]


def test_today_envelope(run_cli):
    code, payload, _ = run_cli(*NOW, "today")
    assert code == 0
    assert [item["title"] for item in payload["data"]["items"]][3] == "Repeating To-Do"
    assert payload["data"]["repeating_hint"] == {"due": [], "templates": 1, "warning": None}
    assert REPEATING_WARNING in payload["warnings"]
    assert all("evening" in item for item in payload["data"]["items"])


def test_search_and_read_flags(run_cli):
    code, payload, _ = run_cli("search", "with notes", "--type", "to-do")
    assert code == 0 and len(payload["data"]) == 8 and all(i["match"] == "notes" for i in payload["data"])
    code, payload, _ = run_cli("search", "heading", "--status", "all", "--limit", "2")
    assert len(payload["data"]) == 2
    code, payload, _ = run_cli(*NOW, "stale", "--days", "30")
    assert len(payload["data"]) == 8
    code, payload, _ = run_cli(*NOW, "overdue")
    assert [i["uuid"] for i in payload["data"]][0] == "K9bx7h1xCJdevvyWardZDq"
    code, payload, _ = run_cli(*NOW, "deadlines", "--within", "0")
    assert len(payload["data"]) == 3
    code, payload, _ = run_cli("anytime")
    assert all(i["type"] == "to-do" for i in payload["data"])
    code, payload, _ = run_cli("anytime", "--all-types")
    assert len(payload["data"]) == 14
    code, payload, _ = run_cli(*NOW, "logbook", "--days", "7")
    assert payload["data"] == []
    code, payload, _ = run_cli("projects", "--area", "Area 1")
    assert [p["title"] for p in payload["data"]] == ["Project in Area 1"]
    code, payload, _ = run_cli("get", "3Eva4XFof6zWb9iSfYy4ej")
    assert len(payload["data"]["checklist"]) == 3 and payload["links"] == ["things:///show?id=3Eva4XFof6zWb9iSfYy4ej"]


def test_update_family_dry_run(run_cli, token_file):
    code, payload, _ = run_cli("--dry-run", "update", "5pUx6PESj3ctFYbgth1PXY", "--title", "完成 Q3 复盘",
                               "--deadline", "2026-09-30", "--clear", "when")
    assert code == 0
    assert payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&title=%E5%AE%8C%E6%88%90%20Q3%20%E5%A4%8D%E7%9B%98"
                               "&when=&deadline=2026-09-30&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "update", "3x1QqJqfvZyhtw8NSdnZqG", "--title", "P2")
    assert payload["urls"] == ["things:///update-project?id=3x1QqJqfvZyhtw8NSdnZqG&title=P2&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "schedule", "5pUx6PESj3ctFYbgth1PXY", "--when", "anytime")
    assert code == 0 and "when=anytime is undocumented for update; check the result in Things" in payload["warnings"]
    code, payload, _ = run_cli("--dry-run", "schedule", "5pUx6PESj3ctFYbgth1PXY", "--when", "next week")
    assert code == 1
    code, payload, _ = run_cli("--dry-run", "deadline", "KisAmSsnzCcRRumjY4TkVV", "--push", "+3d")
    assert payload["urls"] == ["things:///update?id=KisAmSsnzCcRRumjY4TkVV&deadline=2021-05-24&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "deadline", "KisAmSsnzCcRRumjY4TkVV", "--clear")
    assert payload["urls"] == ["things:///update?id=KisAmSsnzCcRRumjY4TkVV&deadline=&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "deadline", "X", "--push", "+3d", env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 3
    code, payload, _ = run_cli("--dry-run", "tag", "5pUx6PESj3ctFYbgth1PXY", "--add", "Errand,Bogus")
    assert payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&add-tags=Errand&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "tag", "5pUx6PESj3ctFYbgth1PXY", "--set", "Home")
    assert payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&tags=Home&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "move", "5pUx6PESj3ctFYbgth1PXY", "--area", "Area 1")
    assert payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&list=Area%201&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "move", "5pUx6PESj3ctFYbgth1PXY", "--list-id", "P", "--heading", "H")
    assert payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&list-id=P&heading=H&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "move", "3x1QqJqfvZyhtw8NSdnZqG", "--area-id", "A")
    assert payload["urls"] == ["things:///update-project?id=3x1QqJqfvZyhtw8NSdnZqG&area-id=A&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "move", "3x1QqJqfvZyhtw8NSdnZqG", "--list", "L")
    assert code == 1
    code, payload, _ = run_cli("--dry-run", "move", "5pUx6PESj3ctFYbgth1PXY", "--list", "L", "--area", "A")
    assert code == 1
    code, payload, _ = run_cli("--dry-run", "cancel", "5pUx6PESj3ctFYbgth1PXY")
    assert payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&canceled=true&auth-token=***"]
    code, payload, _ = run_cli("--dry-run", "show", "ABC")
    assert code == 0 and payload["urls"] == ["things:///show?id=ABC"] and payload["verified"] is None
    code, payload, _ = run_cli("--dry-run", "add-project", "Ship 🚀 v2", "--area", "Work", "--todo", "Plan", "--todo", "Build")
    assert payload["urls"] == ["things:///add-project?title=Ship%20%F0%9F%9A%80%20v2&area=Work&to-dos=Plan%0ABuild"]


def test_unknown_ids_skipped_when_database_can_tell(run_cli, token_file):
    code, payload, _ = run_cli("--dry-run", "complete", "nope1", "5pUx6PESj3ctFYbgth1PXY")
    assert code == 0 and payload["urls"] == ["things:///update?id=5pUx6PESj3ctFYbgth1PXY&completed=true&auth-token=***"]
    assert "unknown id: nope1" in payload["warnings"]
    code, payload, _ = run_cli("--dry-run", "complete", "nope1")
    assert code == 1 and payload["error"] == "no item with id nope1"


UNKNOWN_AREA = "unknown area: Work; no area has that title, Things will ignore it (run: things areas)"
UNKNOWN_LIST = "unknown list: Work; no project or area has that title, Things will ignore it (run: things areas / things projects)"


def test_unknown_list_or_area_name_warns_when_database_can_tell(run_cli, token_file):
    """Finding 2016: `move --area Work` / `update --list Work` sent a name Things ignores without a word."""
    todo, project = "DfYoiXcNLQssk9DkSoJV3Y", "3x1QqJqfvZyhtw8NSdnZqG"
    code, payload, _ = run_cli(*NOW, "--dry-run", "move", todo, "--area", "Work")
    assert code == 0 and payload["ok"] is True and UNKNOWN_AREA in payload["warnings"]
    assert payload["urls"] == ["things:///update?id=%s&list=Work&auth-token=***" % todo]
    code, payload, _ = run_cli(*NOW, "--dry-run", "move", project, "--area", "Nope")
    assert code == 0 and "unknown area: Nope; no area has that title" in " ".join(payload["warnings"])
    code, payload, _ = run_cli(*NOW, "--dry-run", "update", todo, "--list", "Work")
    assert code == 0 and UNKNOWN_LIST in payload["warnings"]
    code, payload, _ = run_cli(*NOW, "--dry-run", "add", "x", "--list", "Work")
    assert code == 0 and payload["warnings"] == [UNKNOWN_LIST]
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-project", "x", "--area", "Work")
    assert code == 0 and payload["warnings"] == [UNKNOWN_AREA]
    # a project or area title Things knows passes, matched case-insensitively; a `--list` may name a project
    code, payload, _ = run_cli(*NOW, "--dry-run", "move", todo, "--area", "area 1")
    assert code == 0 and not any(w.startswith("unknown") for w in payload["warnings"])
    assert payload["urls"] == ["things:///update?id=%s&list=area%%201&auth-token=***" % todo]
    code, payload, _ = run_cli(*NOW, "--dry-run", "update", todo, "--list", "Project in Today")
    assert code == 0 and not any(w.startswith("unknown") for w in payload["warnings"])
    # ids and headings are not resolved
    code, payload, _ = run_cli(*NOW, "--dry-run", "move", todo, "--list-id", "P", "--heading", "H")
    assert code == 0 and not any(w.startswith("unknown") for w in payload["warnings"])


def test_unknown_list_name_passes_silently_without_a_database(monkeypatch, capsys):
    """Without a readable database nothing can be resolved: the name goes through, no warning, no error."""
    from things_lib import read
    module = load_cli_module()
    monkeypatch.setattr(read, "database_status", lambda: "unavailable")
    code = module.main([*NOW, "--dry-run", "move", "DfYoiXcNLQssk9DkSoJV3Y", "--area", "Work"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"] is True
    assert not any(w.startswith("unknown area") for w in payload["warnings"]), payload["warnings"]
    assert payload["urls"] == ["things:///update?id=DfYoiXcNLQssk9DkSoJV3Y&list=Work&auth-token=***"]


def test_global_flags_after_subcommand(run_cli):
    code, payload, _ = run_cli("add", "x", "--dry-run", "--now", "2026-09-09 10:00:00")
    assert code == 0 and payload["urls"] == ["things:///add?title=x"]


def test_stdout_is_single_json_line(run_cli, token_file):
    import subprocess, sys
    proc = subprocess.run([sys.executable, CLI_PATH, "complete", "K9bx7h1xCJdevvyWardZDq"], capture_output=True, text=True)
    assert proc.stdout.count("\n") == 1 and proc.stdout.endswith("\n")
    json.loads(proc.stdout)
    assert proc.stderr.startswith("error: ")


def test_duplicate_ids_collapse_to_one_write(run_cli, token_file):
    """Finding 1: `complete X X` must build one URL and verify one id, not two."""
    uid = "DfYoiXcNLQssk9DkSoJV3Y"
    code, payload, _ = run_cli("--dry-run", "complete", uid, uid, "5pUx6PESj3ctFYbgth1PXY", uid)
    assert code == 0
    assert payload["urls"] == ["things:///update?id=%s&completed=true&auth-token=***" % uid,
                               "things:///update?id=5pUx6PESj3ctFYbgth1PXY&completed=true&auth-token=***"]
    assert payload["data"]["done"] == [uid, "5pUx6PESj3ctFYbgth1PXY"]
    assert payload["ids"] == [uid, "5pUx6PESj3ctFYbgth1PXY"]
    # the --yes threshold counts unique ids
    code, payload, _ = run_cli("--dry-run", "complete", *([uid] * 11))
    assert code == 0 and len(payload["urls"]) == 1
    code, payload, _ = run_cli("--dry-run", "move", uid, uid, "--area", "Area 1")
    assert code == 0 and len(payload["urls"]) == 1 and payload["data"]["done"] == [uid]
