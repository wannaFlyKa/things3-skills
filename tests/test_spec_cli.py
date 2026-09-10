"""CLI contract tests written from SPEC.md section E (E.1-E.10), plus B.6 and C.7 as seen through the CLI.

Fixture facts (SPEC J) drive the expectations; uuids below are the fixture's real rows.
"""

import importlib.machinery
import importlib.util
import json
import os
import platform
import re
import sys
from urllib.parse import unquote

import pytest

from conftest import CLI_PATH, FIXTURE_DB, ROOT

# See the note in test_cli.py: these assert Linux-only behaviour and would fail on macOS precisely
# because the CLI is behaving correctly there. Darwin paths are covered with a monkeypatched
# platform.system() in test_phase3_fixes.py and test_spec_token_transport.py.
linux_only = pytest.mark.skipif(platform.system() != "Linux", reason="asserts Linux-only CLI behaviour")

NOW = ["--now", "2026-09-09T10:00"]
ENVELOPE_KEYS = ["ok", "command", "data", "urls", "sent", "verified", "verify_reason", "ids", "links", "warnings", "error"]
B6 = "Repeating to-dos may be missing: things.py only sees instances Things has already generated. Open Things once to refresh."
SKIP_REASON = "repeating to-do: Things URL scheme cannot change when/deadline/completed/canceled; do it in Things"
NOT_FOUND = ("Things auth token not found: ~/.config/things-skills/auth-token is missing. "
             "Create it from Things → Settings → General → Enable Things URLs → Manage.")
EMPTY_TOKEN = "Things auth token file is empty: ~/.config/things-skills/auth-token"
PLACEHOLDER_WARNING = "auth token not found; dry-run continues with a placeholder"
ANYTIME_WARNING = "when=anytime is undocumented for update; check the result in Things"
FIXTURE_TOKEN = "vKkylosuSuGwxrz7qcklOw"

TODO_INBOX = "DfYoiXcNLQssk9DkSoJV3Y"              # To-Do in Inbox
TODO_CHECKLIST = "3Eva4XFof6zWb9iSfYy4ej"          # To-Do in Inbox with Checklist Items (3 rows)
TODO_ANYTIME = "QqhVksfbsAVaNnwB1x3CuD"            # To-Do in Anytime
TODO_AREA1 = "W5JYfjY2xtLdmedQKU6caM"              # Todo in Area 1, tags Errand, Home
REPEATING_INSTANCE = "K9bx7h1xCJdevvyWardZDq"      # Repeating To-Do (instance, visible)
REPEATING_TEMPLATE = "N1PJHsbjct4mb1bhcs7aHa"      # hidden template
OVERDUE_TODAY = "KisAmSsnzCcRRumjY4TkVV"           # deadline 2021-05-21
OVERDUE_HIDDEN = "Cc73oaq1C2mDMpZZUJaBxe"          # deadline 2021-05-21
PROJECT = "3x1QqJqfvZyhtw8NSdnZqG"                 # Project in Area 1
HEADING = "6QpDLSHZMRAUSAeZ9mNvgt"                 # Heading (in PROJECT)
AREA1 = "DciSFacytdrNG1nRaMJPgY"
ELEVEN_OPEN_TODOS = ["6Hf2qWBjWhq7B1xszwdo34", "3Eva4XFof6zWb9iSfYy4ej", "W5JYfjY2xtLdmedQKU6caM", "5pUx6PESj3ctFYbgth1PXY",
                     "KisAmSsnzCcRRumjY4TkVV", "DfYoiXcNLQssk9DkSoJV3Y", "7F4vqUNiTvGKaCUfv5pqYG", "HbKGAeZKFDkWH5osSBNHvz",
                     "E18tg5qepzrQk9J6jQtb5C", "QqhVksfbsAVaNnwB1x3CuD", "JLYSEPFkLfBC5rhGJRa5S1"]
STALE_TITLES = ["Overdue Todo automatically shown in Today", "Overdue Todo not shown in Today", "To-Do in Anytime",
                "To-Do in Area 1", "To-Do in Heading", "To-Do in Project", "Todo in Area 1", "Todo in Area 3"]
TODAY_ORDER = ["Upcoming To-Do in Today (yellow)", "Project in Today", "To-Do in Today", "Repeating To-Do",
               "Overdue Todo automatically shown in Today"]


def load_cli():
    loader = importlib.machinery.SourceFileLoader("things_cli_spec", CLI_PATH)
    spec = importlib.util.spec_from_loader("things_cli_spec", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def assert_envelope(payload, command=None):
    assert list(payload.keys()) == ENVELOPE_KEYS, list(payload.keys())
    assert isinstance(payload["ok"], bool) and isinstance(payload["sent"], bool)
    for key in ("urls", "ids", "links", "warnings"):
        assert isinstance(payload[key], list), key
        assert all(isinstance(v, str) for v in payload[key]), key
    assert payload["verified"] in (True, False, None)
    assert payload["verify_reason"] is None or isinstance(payload["verify_reason"], str)
    assert payload["error"] is None or isinstance(payload["error"], str)
    assert (payload["error"] is None) == payload["ok"], "error is set exactly when ok is false"
    assert isinstance(payload["command"], str)
    if command is not None:
        assert payload["command"] == command
    for link in payload["links"]:
        assert link.startswith("things:///show?id=")
    for url in payload["urls"]:
        assert url.startswith("things:///") and not url.startswith("things:///add-json")
        assert "auth-token=" not in url or url.endswith("auth-token=***")


def query_names(url):
    return [part.split("=", 1)[0] for part in url.split("?", 1)[1].split("&")] if "?" in url else []


def query(url):
    return dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))


# ---- E.1: every subcommand prints exactly one envelope with all 11 keys ------------------------------

WRITE_JSON = '[{"type":"to-do","attributes":{"title":"Buy milk"}}]'
EVERY_SUBCOMMAND = [
    ["inbox"], ["today"], ["upcoming"], ["anytime"], ["anytime", "--all-types"], ["someday"], ["logbook", "--days", "3000"],
    ["deadlines"], ["deadlines", "--within", "7"], ["projects"], ["projects", "--area", "Area 1"], ["areas"], ["tags"],
    ["get", TODO_CHECKLIST], ["get", "NOPE"], ["search", "inbox"], ["stale", "--days", "30"], ["overdue"],
    ["parse-date", "明天下午3点"], ["doctor"], ["ping"],
    ["--dry-run", "add", "买牛奶"], ["--dry-run", "add-project", "P", "--todo", "a"], ["--dry-run", "add-json", "-"],
    ["--dry-run", "update", TODO_INBOX, "--title", "x"], ["--dry-run", "complete", TODO_INBOX], ["--dry-run", "cancel", TODO_INBOX],
    ["--dry-run", "move", TODO_INBOX, "--list", "Project in Area 1"], ["--dry-run", "schedule", TODO_INBOX, "--when", "today"],
    ["--dry-run", "deadline", TODO_INBOX, "--date", "2026-10-01"], ["--dry-run", "tag", TODO_INBOX, "--add", "Errand"],
    ["--dry-run", "show", TODO_INBOX], ["complete", REPEATING_INSTANCE], ["complete"], ["frobnicate"], [],
    ["add", "x", "--when", "next week"], ["inbox", "--transport", "bogus"],
]


@pytest.mark.parametrize("args", EVERY_SUBCOMMAND, ids=[" ".join(a) or "<none>" for a in EVERY_SUBCOMMAND])
def test_envelope_for_every_subcommand_and_error_path(run_cli, token_file, args):
    code, payload, stderr = run_cli(*NOW, *args, stdin=WRITE_JSON)
    assert payload is not None, "stdout must be one JSON object; got %r / %r" % (code, stderr)
    assert_envelope(payload)
    assert code in (0, 1, 2, 3, 4)
    assert (code == 0) == payload["ok"]
    if not payload["ok"]:
        assert stderr.startswith("error: ") or "\nerror: " in stderr, stderr
        assert payload["error"] in stderr
    assert "Traceback" not in stderr
    if args and args[0] not in ("--dry-run",) and args[0] in ("inbox", "today", "upcoming", "anytime", "someday", "logbook",
                                                              "deadlines", "projects", "areas", "tags", "get", "search", "stale",
                                                              "overdue", "parse-date", "doctor"):
        assert payload["urls"] == [] and payload["verified"] is None and payload["sent"] is False
        assert payload["command"] == args[0]


def test_stdout_is_exactly_one_line_ensure_ascii_false_indent_none(run_cli):
    code, payload, stderr = run_cli("--dry-run", "add", "买牛奶 🎉", "--notes", "第一行\n第二行")
    assert code == 0
    proc_out = __import__("subprocess").run([sys.executable, CLI_PATH, "--dry-run", "add", "买牛奶 🎉"], capture_output=True, text=True)
    assert proc_out.stdout.count("\n") == 1 and proc_out.stdout.endswith("\n")
    assert "买牛奶 🎉" in proc_out.stdout and "\\u" not in proc_out.stdout
    assert not proc_out.stdout.startswith("{\n"), "indent=None"
    json.loads(proc_out.stdout)


# ---- E.2: exit codes each reachable --------------------------------------------------------------------

def test_exit_0_read(run_cli):
    code, payload, _ = run_cli(*NOW, "inbox")
    assert code == 0 and payload["ok"] is True and len(payload["data"]) == 2


@pytest.mark.parametrize("args,error_fragment", [
    (["add", "x", "--when", "next week"], "invalid --when value 'next week'; run: things parse-date 'next week'"),
    (["schedule", TODO_INBOX, "--when", "Friday"], "invalid --when value 'Friday'; run: things parse-date 'Friday'"),
    (["add", "x", "--deadline", "evening"], None),
    (["add", "x" * 4001], None),
    (["get", "NOPE"], "no item with id NOPE"),
    (["complete", TODO_INBOX], NOT_FOUND),                 # no token file, not dry-run
    (["add-json", "-"], "invalid JSON"),
    (["frobnicate"], None), ([], None), (["--now", "yesterday", "inbox"], None),
    (["deadline", TODO_INBOX, "--push", "+3x"], None),
    (["move", TODO_INBOX], None), (["move", TODO_INBOX, "--list", "A", "--area", "B"], None),
    (["move", PROJECT, "--list", "Project in Area 1"], None),
    (["deadline", TODO_INBOX], None),
    (["tag", TODO_INBOX], None),
])
def test_exit_1_usage_config_limit_token_and_unknown_id(run_cli, args, error_fragment):
    code, payload, stderr = run_cli(*NOW, *args, stdin="{not json")
    assert code == 1, (payload, stderr)
    assert payload["ok"] is False and isinstance(payload["error"], str) and payload["error"]
    if error_fragment:
        assert error_fragment in payload["error"], payload["error"]
    assert payload["urls"] == [] and payload["sent"] is False


@pytest.mark.parametrize("args", [["search", "x"], ["stale"], ["parse-date", "x"]])
def test_exit_1_malformed_config_on_config_consuming_commands(run_cli, tmp_path, args):
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    code, payload, _ = run_cli(*NOW, "--config", str(path), *args)
    assert code == 1 and payload["ok"] is False and "invalid JSON" in payload["error"]


def test_exit_1_malformed_explicit_config_even_for_reads_that_do_not_use_it(run_cli, tmp_path):
    """G: 'a malformed file is a ConfigError (exit 1)'; E.3: --config PATH. Stricter reading: any subcommand."""
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    code, payload, _ = run_cli(*NOW, "--config", str(path), "inbox")
    assert code == 1 and payload["ok"] is False and "invalid JSON" in payload["error"]


@linux_only
def test_exit_2_open_transport_unavailable_on_linux(run_cli, token_file):
    code, payload, _ = run_cli(*NOW, "--transport", "open", "complete", TODO_INBOX)
    assert code == 2 and payload["error"] == "transport 'open' is only available on macOS"
    code, payload, _ = run_cli(*NOW, "--transport", "open", "ping")
    assert code == 2 and payload["ok"] is False


@pytest.mark.parametrize("args", [["inbox"], ["today"], ["get", TODO_INBOX], ["search", "x"], ["stale"], ["overdue"], ["deadlines"],
                                  ["projects"], ["areas"], ["tags"], ["logbook"], ["deadline", TODO_INBOX, "--push", "+3d", "--dry-run"]])
def test_exit_3_when_database_unavailable(run_cli, token_file, tmp_path, args):
    code, payload, stderr = run_cli(*NOW, *args, env={"THINGSDB": str(tmp_path / "missing.sqlite")})
    assert code == 3, (payload, stderr)
    assert payload["ok"] is False and payload["data"] is None and payload["error"]
    assert "Traceback" not in stderr


def test_exit_4_all_repeating_and_yes_threshold(run_cli, token_file):
    code, payload, _ = run_cli(*NOW, "complete", REPEATING_INSTANCE)
    assert code == 4 and payload["error"] == "all 1 items are repeating to-dos"
    code, payload, _ = run_cli(*NOW, "--dry-run", "complete", *ELEVEN_OPEN_TODOS)
    assert code == 4 and payload["error"] == "refusing to modify 11 items without --yes"
    assert payload["urls"] == []


# ---- E.3: --dry-run token-free placeholder, --yes threshold, --verify-timeout, --now -----------------

def test_dry_run_without_token_uses_placeholder_with_exact_warning(run_cli, tmp_path):
    code, payload, stderr = run_cli(*NOW, "--dry-run", "complete", TODO_INBOX)
    assert code == 0 and payload["ok"] is True
    assert payload["urls"] == ["things:///update?id=%s&completed=true&auth-token=***" % TODO_INBOX]
    assert PLACEHOLDER_WARNING in payload["warnings"]
    assert payload["sent"] is False and payload["verified"] is None and payload["verify_reason"] is None
    assert not (tmp_path / ".things-skills").exists(), "dry-run writes nothing"
    assert FIXTURE_TOKEN not in json.dumps(payload) and FIXTURE_TOKEN not in stderr, "fixture is not 'readable', no DB fallback"


def test_dry_run_with_empty_token_file_uses_placeholder_but_real_run_is_exit_1(run_cli, tmp_path):
    directory = tmp_path / ".config" / "things-skills"
    directory.mkdir(parents=True)
    (directory / "auth-token").write_text("\n", encoding="utf-8")
    code, payload, _ = run_cli(*NOW, "--dry-run", "complete", TODO_INBOX)
    assert code == 0 and PLACEHOLDER_WARNING in payload["warnings"]
    code, payload, _ = run_cli(*NOW, "complete", TODO_INBOX)
    assert code == 1 and payload["error"] == EMPTY_TOKEN


def test_dry_run_with_token_has_no_placeholder_warning_and_masks(run_cli, token_file):
    code, payload, stderr = run_cli(*NOW, "--dry-run", "complete", TODO_INBOX)
    assert code == 0 and PLACEHOLDER_WARNING not in payload["warnings"]
    assert payload["urls"][0].endswith("&auth-token=***")
    assert "SECRET" not in json.dumps(payload) and "SECRET" not in stderr


def test_no_db_fallback_when_database_is_fixture_not_readable(run_cli):
    """C.3: the things.token() fallback is gated on database_status() == 'readable'; the fixture is 'fixture'."""
    code, payload, stderr = run_cli(*NOW, "complete", TODO_INBOX)
    assert code == 1 and payload["error"] == NOT_FOUND
    assert FIXTURE_TOKEN not in stderr and FIXTURE_TOKEN not in json.dumps(payload)


def test_yes_threshold_is_exactly_ten_ids(run_cli, token_file):
    code, payload, _ = run_cli(*NOW, "--dry-run", "complete", *ELEVEN_OPEN_TODOS[:10])
    assert code == 0 and len(payload["urls"]) == 10
    code, payload, _ = run_cli(*NOW, "--dry-run", "complete", *ELEVEN_OPEN_TODOS)
    assert code == 4 and payload["error"] == "refusing to modify 11 items without --yes" and payload["urls"] == []
    code, payload, _ = run_cli(*NOW, "--dry-run", "--yes", "complete", *ELEVEN_OPEN_TODOS)
    assert code == 0 and len(payload["urls"]) == 11
    assert [query(u)["id"] for u in payload["urls"]] == ELEVEN_OPEN_TODOS, "one URL per id, in argument order"
    code, payload, _ = run_cli(*NOW, "--dry-run", "cancel", *ELEVEN_OPEN_TODOS)
    assert code == 4
    code, payload, _ = run_cli(*NOW, "--dry-run", "schedule", *ELEVEN_OPEN_TODOS, "--when", "today")
    assert code == 4
    code, payload, _ = run_cli(*NOW, "--dry-run", "tag", *ELEVEN_OPEN_TODOS, "--add", "Errand")
    assert code == 4


def test_verify_timeout_zero_disables_verification(run_cli, token_file):
    code, payload, _ = run_cli(*NOW, "--verify-timeout", "0", "complete", TODO_INBOX)
    assert code == 0 and payload["verified"] is False and payload["verify_reason"] == "verification disabled"


def test_record_transport_reports_unverified_with_exact_reason(run_cli, token_file, tmp_path):
    code, payload, _ = run_cli(*NOW, "complete", TODO_INBOX)
    assert code == 0 and payload["ok"] is True and payload["sent"] is False
    assert payload["verified"] is False and payload["verify_reason"] == "transport record: nothing was sent to Things"
    assert payload["ids"] == [TODO_INBOX] and payload["links"] == ["things:///show?id=" + TODO_INBOX]
    lines = (tmp_path / ".things-skills" / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert list(entry) == ["ts", "command", "url"] and entry["command"] == "update"
    assert entry["url"] == payload["urls"][0] and entry["url"].endswith("auth-token=***")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["ts"])


@pytest.mark.parametrize("now", ["2026-09-09T10:00", "2026-09-09 10:00", "2026-09-09 10:00:30"])
def test_now_formats_accepted(run_cli, now):
    code, payload, _ = run_cli("--now", now, "parse-date", "明天")
    assert code == 0 and payload["data"]["when"] == "tomorrow"
    code, payload, _ = run_cli("--now", now, "overdue")
    assert code == 0 and len(payload["data"]) == 3


def test_global_flags_accepted_after_the_subcommand(run_cli, token_file):
    code, payload, _ = run_cli("complete", TODO_INBOX, "--dry-run", "--now", "2026-09-09T10:00")
    assert code == 0 and payload["urls"] and payload["verified"] is None
    code, payload, _ = run_cli("inbox", "--transport", "dry")
    assert code == 0


# ---- E.6 search --------------------------------------------------------------------------------------

def titles(payload):
    return [item["title"] for item in payload["data"]]


def test_search_fixture_expectations(run_cli):
    code, payload = run_cli(*NOW, "search", "inbox")[:2]
    assert code == 0 and sorted(titles(payload)) == ["To-Do in Inbox", "To-Do in Inbox with Checklist Items"]
    assert sorted(titles(run_cli(*NOW, "search", "INBOX")[1])) == ["To-Do in Inbox", "To-Do in Inbox with Checklist Items"]
    payload = run_cli(*NOW, "search", "with notes", "--type", "to-do")[1]
    assert len(payload["data"]) == 8 and all(item["match"] == "notes" for item in payload["data"])
    assert all(item["type"] == "to-do" for item in payload["data"])
    payload = run_cli(*NOW, "search", "heading", "--status", "all")[1]
    assert sorted(titles(payload)) == ["Cancelled To-Do in Heading", "Completed To-Do in Heading", "To-Do in Heading"]
    assert all(item["type"] != "heading" for item in payload["data"])
    for item in payload["data"]:
        assert set(item) >= {"match", "matched_terms", "link", "repeating", "days_until_deadline"}
        assert item["match"] in ("title", "notes") and isinstance(item["matched_terms"], list)
    assert titles(run_cli(*NOW, "search", "inbox", "--limit", "1")[1]).__len__() == 1
    assert titles(run_cli(*NOW, "search", "heading")[1]) == ["To-Do in Heading"], "default status open"
    assert titles(run_cli(*NOW, "search", "heading", "--status", "completed")[1]) == ["Completed To-Do in Heading"]
    assert titles(run_cli(*NOW, "search", "heading", "--status", "canceled")[1]) == ["Cancelled To-Do in Heading"]
    assert titles(run_cli(*NOW, "search", "zzzznotthere")[1]) == []
    assert titles(run_cli(*NOW, "search", "inbox checklist")[1]) == ["To-Do in Inbox with Checklist Items"], "every token must match"


def test_search_area_and_project_filters_by_uuid_or_title(run_cli):
    by_title = titles(run_cli(*NOW, "search", "in", "--project", "Project in Area 1")[1])
    by_uuid = titles(run_cli(*NOW, "search", "in", "--project", PROJECT)[1])
    assert by_title == by_uuid
    assert "Todo in Area 1" in by_title, "direct child of the project"
    assert "To-Do in Heading" in by_title, "a to-do under a heading of the project belongs to the project"
    assert "To-Do in Project" not in by_title, "that one lives in 'Project without Area'"
    by_area = titles(run_cli(*NOW, "search", "area 1", "--area", "Area 1")[1])
    assert by_area == titles(run_cli(*NOW, "search", "area 1", "--area", AREA1)[1])
    assert {"To-Do in Area 1", "Project in Area 1"} <= set(by_area)
    assert "Todo in Area 3" not in by_area
    assert titles(run_cli(*NOW, "search", "to-do", "--type", "project")[1]) == []
    assert titles(run_cli(*NOW, "search", "in", "--project", "No Such Project")[1]) == []


def test_search_area_filter_includes_todos_of_projects_in_that_area(run_cli):
    """Stricter reading of E.6 step 1: an item in a project that lives in Area 1 is in Area 1 (as Things shows it)."""
    by_area = titles(run_cli(*NOW, "search", "area 1", "--area", "Area 1")[1])
    assert "Todo in Area 1" in by_area, by_area


def cjk_items():
    def item(uuid, title, notes, modified):
        return {"uuid": uuid, "type": "to-do", "status": "incomplete", "title": title, "notes": notes, "start": "Anytime",
                "start_date": None, "deadline": None, "stop_date": None, "created": modified, "modified": modified,
                "index": 0, "today_index": 0}
    return [
        item("A1", "买牛奶", "", "2026-09-01 10:00:00"),
        item("A2", "去超市买牛奶和鸡蛋", "", "2026-09-05 10:00:00"),
        item("A3", "Groceries", "记得买牛奶", "2026-09-08 10:00:00"),
        item("A4", "Submit Expense report", "", "2026-09-02 10:00:00"),
        item("A5", "报销差旅费", "", "2026-09-03 10:00:00"),
        item("A6", "Weekly report", "写周报", "2026-09-04 10:00:00"),
        {"uuid": "H1", "type": "heading", "status": "incomplete", "title": "买牛奶 heading", "notes": "", "start": "Anytime",
         "start_date": None, "deadline": None, "stop_date": None, "created": "2026-09-01 10:00:00", "modified": "2026-09-01 10:00:00",
         "index": 0, "today_index": 0},
        dict(item("T1", "买牛奶 trashed", "", "2026-09-09 09:00:00"), trashed=True),
    ]


def run_main(monkeypatch, capsys, argv, items=None):
    from things_lib import read
    monkeypatch.setattr(read, "tasks_raw", lambda **filters: [dict(i) for i in (items or cjk_items())])
    module = load_cli()
    code = module.main(argv)
    out = capsys.readouterr()
    assert out.out.count("\n") == 1
    return code, json.loads(out.out), out.err


def test_search_cjk_substring_in_process(monkeypatch, capsys):
    code, payload, _ = run_main(monkeypatch, capsys, NOW + ["search", "牛奶", "--no-synonyms"])
    assert code == 0
    assert [i["uuid"] for i in payload["data"]] == ["A2", "A1", "A3"], "title hits first (modified desc), then notes"
    assert [i["match"] for i in payload["data"]] == ["title", "title", "notes"]
    assert all(i["matched_terms"] == ["牛奶"] for i in payload["data"])
    assert "H1" not in json.dumps(payload) and "T1" not in json.dumps(payload), "headings and trashed items excluded"
    code, payload, _ = run_main(monkeypatch, capsys, NOW + ["search", "牛奶 鸡蛋", "--no-synonyms"])
    assert [i["uuid"] for i in payload["data"]] == ["A2"], "every token must match"
    code, payload, _ = run_main(monkeypatch, capsys, NOW + ["search", "奶", "--no-synonyms"])
    assert {i["uuid"] for i in payload["data"]} == {"A1", "A2", "A3"}, "single CJK character substring"
    code, payload, _ = run_main(monkeypatch, capsys, NOW + ["search", "EXPENSE", "--no-synonyms"])
    assert [i["uuid"] for i in payload["data"]] == ["A4"], "ASCII case-insensitive"


def test_search_synonyms_from_config_in_process(monkeypatch, capsys, config_file):
    config_file({"synonyms": [["报销", "expense", "reimbursement"], ["周报", "weekly report"]]})
    code, payload, _ = run_main(monkeypatch, capsys, NOW + ["search", "报销"])
    assert {i["uuid"] for i in payload["data"]} == {"A4", "A5"}
    hit = next(i for i in payload["data"] if i["uuid"] == "A4")
    assert "expense" in hit["matched_terms"]
    code, payload, _ = run_main(monkeypatch, capsys, NOW + ["search", "报销", "--no-synonyms"])
    assert {i["uuid"] for i in payload["data"]} == {"A5"}
    code, payload, _ = run_main(monkeypatch, capsys, NOW + ["search", "周报"])
    assert {i["uuid"] for i in payload["data"]} == {"A6"}, "多词 synonym member is reachable from the single token"
    code, payload, _ = run_main(monkeypatch, capsys, NOW + ["search", "Reimbursement"])
    assert {i["uuid"] for i in payload["data"]} == {"A4", "A5"}, "synonym lookup is casefolded"


# ---- E.7 stale and overdue ---------------------------------------------------------------------------

def test_stale_fixture_expectations(run_cli, config_file):
    code, payload, _ = run_cli(*NOW, "stale", "--days", "30")
    assert code == 0 and sorted(titles(payload)) == STALE_TITLES
    ages = [item["age_days"] for item in payload["data"]]
    assert all(isinstance(a, int) and a > 30 for a in ages)
    assert ages == sorted(ages, reverse=True), "oldest first"
    for item in payload["data"]:
        assert item["type"] == "to-do" and item["start"] == "Anytime" and item["start_date"] is None
        assert item["repeating"] is False and item["status"] == "incomplete" and not item.get("trashed")
    config_file({"stale_days": 30})
    assert sorted(titles(run_cli(*NOW, "stale")[1])) == STALE_TITLES, "default --days comes from config.stale_days"
    assert titles(run_cli(*NOW, "stale", "--days", "100000")[1]) == []


def test_overdue_fixture_expectations(run_cli):
    code, payload, _ = run_cli(*NOW, "overdue")
    assert code == 0
    ids = [item["uuid"] for item in payload["data"]]
    assert ids[0] == REPEATING_INSTANCE and sorted(ids) == sorted([REPEATING_INSTANCE, OVERDUE_TODAY, OVERDUE_HIDDEN])
    deadlines = [item["deadline"] for item in payload["data"]]
    assert deadlines == sorted(deadlines) and all(d < "2026-09-09" for d in deadlines)
    assert payload["data"][0]["repeating"] is True
    assert all(item["days_until_deadline"] < 0 for item in payload["data"])
    assert all(item["type"] in ("to-do", "project") for item in payload["data"])


# ---- E.9 repeating refusal ---------------------------------------------------------------------------

@pytest.mark.parametrize("args", [["complete"], ["cancel"], ["schedule", "--when", "today"], ["deadline", "--date", "2026-10-01"],
                                  ["deadline", "--clear"], ["update", "--when", "today"], ["update", "--deadline", "2026-10-01"],
                                  ["update", "--completed"], ["update", "--canceled"], ["update", "--clear", "deadline"]])
@pytest.mark.parametrize("rid", [REPEATING_INSTANCE, REPEATING_TEMPLATE])
def test_repeating_refused_exit_4_with_skip_shape(run_cli, token_file, args, rid):
    argv = [args[0], rid] + args[1:]
    code, payload, stderr = run_cli(*NOW, *argv)
    assert code == 4, (payload, stderr)
    assert payload["ok"] is False and payload["error"] == "all 1 items are repeating to-dos"
    assert payload["urls"] == [] and payload["sent"] is False
    assert payload["data"]["done"] == []
    assert payload["data"]["skipped"] == [{"id": rid, "title": "Repeating To-Do", "reason": SKIP_REASON}]
    assert any(rid in w for w in payload["warnings"]), "each skip also appears in warnings"


def test_repeating_mixed_ids_partial(run_cli, token_file):
    code, payload, _ = run_cli(*NOW, "complete", REPEATING_INSTANCE, TODO_INBOX, TODO_ANYTIME)
    assert code == 0 and payload["ok"] is True
    assert payload["data"]["done"] == [TODO_INBOX, TODO_ANYTIME]
    assert [s["id"] for s in payload["data"]["skipped"]] == [REPEATING_INSTANCE]
    assert [query(u)["id"] for u in payload["urls"]] == [TODO_INBOX, TODO_ANYTIME]
    assert any(REPEATING_INSTANCE in w and "repeating" in w for w in payload["warnings"])
    assert REPEATING_INSTANCE not in payload["ids"]


def test_repeating_allowed_for_title_move_and_tag(run_cli, token_file):
    code, payload, _ = run_cli(*NOW, "--dry-run", "update", REPEATING_INSTANCE, "--title", "renamed")
    assert code == 0 and payload["urls"] == ["things:///update?id=%s&title=renamed&auth-token=***" % REPEATING_INSTANCE]
    code, payload, _ = run_cli(*NOW, "--dry-run", "move", REPEATING_INSTANCE, "--list", "Project in Area 1")
    assert code == 0 and payload["urls"] == ["things:///update?id=%s&list=Project%%20in%%20Area%%201&auth-token=***" % REPEATING_INSTANCE]
    code, payload, _ = run_cli(*NOW, "--dry-run", "tag", REPEATING_INSTANCE, "--add", "Errand")
    assert code == 0 and payload["urls"] == ["things:///update?id=%s&add-tags=Errand&auth-token=***" % REPEATING_INSTANCE]


def test_data_shape_null_on_usage_token_and_read_errors(run_cli, tmp_path):
    code, payload, _ = run_cli(*NOW, "complete", TODO_INBOX)                       # token missing -> exit 1
    assert code == 1 and payload["data"] is None
    code, payload, _ = run_cli(*NOW, "complete", TODO_INBOX, env={"THINGSDB": str(tmp_path / "x.sqlite")})
    assert code == 1 and payload["data"] is None


# ---- E.10 add-json -------------------------------------------------------------------------------------

def write_json(tmp_path, objects, name="payload.json"):
    path = tmp_path / name
    path.write_text(objects if isinstance(objects, str) else json.dumps(objects, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("objects,pattern", [
    ("{not json", r"^invalid JSON: .+"),
    ("", r"^invalid JSON: .+"),
    ([{"type": "heading", "attributes": {"title": "H"}}], r"^\[0\]\.type: .+"),
    ([{"type": "to-do", "attributes": {"title": "t", "tags": "a,b"}}], r"^\[0\]\.attributes\.tags: .+"),
    ([{"type": "to-do", "attributes": {"title": "t", "checklist-items": [{"type": "checklist-item", "attributes": {"title": "c"}}] * 101}}],
     r"^\[0\]\.attributes\.checklist-items: .+"),
    ([{"type": "to-do", "operation": "update", "attributes": {"title": "t"}}], r"^\[0\]\.id: .+"),
    ([{"type": "to-do", "attributes": {"title": "t", "foo": 1}}], r"^\[0\]\.attributes\.foo: .+"),
    ([{"type": "project", "attributes": {"items": [{"type": "checklist-item", "attributes": {"title": "c"}}]}}],
     r"^\[0\]\.attributes\.items\[0\]\.type: .+"),
    ([{"type": "to-do", "attributes": {"title": "t", "when": "next week"}}], r"next week"),
    ([{"type": "to-do", "attributes": {"title": "t", "deadline": "evening"}}], r"evening"),
    ([{"type": "project", "attributes": {"items": [{"type": "to-do", "attributes": {"title": "t", "when": "Friday"}}]}}], r"Friday"),
    ([{"type": "to-do", "attributes": {"title": "t", "notes": "n" * 10001}}], r"^\[0\]\.attributes\.notes: .+"),
    ({"type": "to-do", "attributes": {"title": "t"}}, r".+"),
])
def test_add_json_validation_errors(run_cli, tmp_path, objects, pattern):
    code, payload, stderr = run_cli(*NOW, "--dry-run", "add-json", write_json(tmp_path, objects))
    assert code == 1, (payload, stderr)
    assert payload["ok"] is False and re.search(pattern, payload["error"]), payload["error"]
    assert payload["urls"] == []


def test_add_json_over_250_items_exact_error(run_cli, tmp_path):
    objects = [{"type": "to-do", "attributes": {"title": "t%d" % i}} for i in range(251)]
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-json", write_json(tmp_path, objects))
    assert code == 1 and payload["error"] == "payload has 251 items; split into batches of 250"
    objects = [{"type": "project", "attributes": {"title": "p", "items": [{"type": "heading", "attributes": {"title": "h"}}] +
                                                  [{"type": "to-do", "attributes": {"title": "t%d" % i}} for i in range(249)]}}]
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-json", write_json(tmp_path, objects))
    assert code == 1 and payload["error"] == "payload has 251 items; split into batches of 250"
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-json", write_json(tmp_path, [{"type": "to-do", "attributes": {"title": "t%d" % i}} for i in range(250)]))
    assert code == 0 and payload["data"]["items"] == 250


def test_add_json_success_shape_stdin_and_tags_at_depth(run_cli, tmp_path):
    objects = [{"type": "project", "attributes": {"title": "发布 v2", "tags": ["Errand", "Nope"], "items": [
        {"type": "heading", "attributes": {"title": "准备"}},
        {"type": "to-do", "attributes": {"title": "写文档", "tags": ["Home", "Ghost"], "checklist-items": [
            {"type": "checklist-item", "attributes": {"title": "大纲"}}]}}]}},
        {"type": "to-do", "attributes": {"title": "Buy milk"}}]
    code, payload, stderr = run_cli(*NOW, "--dry-run", "add-json", "-", stdin=json.dumps(objects, ensure_ascii=False))
    assert code == 0, (payload, stderr)
    assert payload["data"] == {"objects": 2, "items": 4, "top_level_titles": ["发布 v2", "Buy milk"]}
    assert len(payload["urls"]) == 1 and payload["urls"][0].startswith("things:///json?data=")
    assert "auth-token" not in payload["urls"][0], "create-only payload needs no token"
    sent = json.loads(unquote(payload["urls"][0][len("things:///json?data="):]))
    assert sent[0]["attributes"]["tags"] == ["Errand"] and sent[0]["attributes"]["items"][1]["attributes"]["tags"] == ["Home"]
    assert "tag not found in Things, dropped: Nope" in payload["warnings"]
    assert "tag not found in Things, dropped: Ghost" in payload["warnings"]
    assert payload["verified"] is None


def test_tag_refuses_when_every_tag_was_dropped(run_cli, token_file):
    """E.8: dropping every requested tag would leave an empty add-tags/tags, so the write is refused."""
    code, payload, _ = run_cli(*NOW, "tag", TODO_INBOX, "--add", "Nope")
    assert code == 1 and payload["ok"] is False and payload["error"] == "no valid tags to apply"
    assert "tag not found in Things, dropped: Nope" in payload["warnings"]
    assert payload["urls"] == [] and payload["sent"] is False and payload["data"] is None
    # --set behaves the same way, and a surviving tag still lets the write through.
    code, payload, _ = run_cli(*NOW, "tag", TODO_INBOX, "--set", "Nope,Ghost")
    assert code == 1 and payload["error"] == "no valid tags to apply"
    code, payload, _ = run_cli(*NOW, "--dry-run", "tag", TODO_INBOX, "--add", "Errand,Nope")
    assert code == 0 and payload["ok"] is True


def test_add_json_update_operation_needs_token(run_cli, tmp_path, token_file):
    objects = [{"type": "to-do", "operation": "update", "id": TODO_INBOX, "attributes": {"title": "renamed"}}]
    path = write_json(tmp_path, objects)
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-json", path)
    assert code == 0 and payload["urls"][0].endswith("&auth-token=***") and "SECRET" not in json.dumps(payload)
    os.remove(token_file)
    code, payload, _ = run_cli(*NOW, "add-json", path)
    assert code == 1 and payload["error"] == NOT_FOUND
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-json", path)
    assert code == 0 and PLACEHOLDER_WARNING in payload["warnings"]


def test_add_json_missing_file_is_exit_1(run_cli, tmp_path):
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-json", str(tmp_path / "nope.json"))
    assert code == 1 and payload["ok"] is False


# ---- E.5 doctor ----------------------------------------------------------------------------------------

@linux_only
def test_doctor_fields_on_linux(run_cli, tmp_path):
    code, payload, stderr = run_cli(*NOW, "doctor")
    assert code == 0 and payload["ok"] is True
    data = payload["data"]
    assert list(data) == ["platform", "python", "transport", "database", "token", "things_py", "config", "cli_version"]
    assert data["platform"] == "Linux" and re.fullmatch(r"3\.\d+\.\d+", data["python"])
    assert data["transport"] == "record"
    assert data["database"] == {"path": FIXTURE_DB, "status": "fixture", "error": None}
    assert data["token"] == {"path": "~/.config/things-skills/auth-token", "present": False, "empty": False, "mode_ok": None, "mode": None}
    # The CLI resolves its own location with realpath; the checkout may be reached through a symlink.
    assert os.path.realpath(data["things_py"].pop("path")) == os.path.realpath(
        os.path.join(ROOT, "plugins", "things", "scripts", "vendor", "things"))
    assert data["things_py"] == {"installed": True, "version": "1.0.1", "source": "bundled"}
    assert data["config"]["present"] is False and data["config"]["valid"] is True and data["config"]["missing_tags"] == []
    assert data["config"]["path"] == str(tmp_path / ".config" / "things-skills" / "config.json")
    assert data["cli_version"] == "0.1.0"
    assert run_cli(*NOW, "--transport", "dry", "doctor")[1]["data"]["transport"] == "dry"
    assert run_cli(*NOW, "--dry-run", "doctor")[1]["data"]["transport"] == "dry"


def test_doctor_token_states_never_leak_the_value(run_cli, tmp_path, token_file, config_file):
    config_file({"tags": ["@calls", "Errand", "Home"]})
    code, payload, stderr = run_cli(*NOW, "doctor")
    data = payload["data"]
    assert data["token"] == {"path": "~/.config/things-skills/auth-token", "present": True, "empty": False, "mode_ok": True, "mode": "0600"}
    assert data["config"]["present"] is True and data["config"]["valid"] is True and data["config"]["missing_tags"] == ["@calls"]
    assert "SECRET" not in json.dumps(payload) and "SECRET" not in stderr
    os.chmod(token_file, 0o644)
    data = run_cli(*NOW, "doctor")[1]["data"]
    assert data["token"]["mode_ok"] is False and data["token"]["mode"] == "0644"
    open(token_file, "w").close()
    data = run_cli(*NOW, "doctor")[1]["data"]
    assert data["token"]["present"] is True and data["token"]["empty"] is True


def test_doctor_always_exit_0_even_when_database_and_config_are_broken(run_cli, tmp_path, config_file):
    config_file({"today_cap": "six"})
    code, payload, _ = run_cli(*NOW, "doctor", env={"THINGSDB": str(tmp_path / "missing.sqlite")})
    assert code == 0 and payload["ok"] is True
    data = payload["data"]
    assert data["database"]["status"] == "unavailable" and data["database"]["error"]
    assert data["database"]["path"] == str(tmp_path / "missing.sqlite")
    assert data["config"]["valid"] is False and data["config"]["present"] is True
    assert data["config"]["missing_tags"] is None


# ---- E.4 parse-date, get, today ------------------------------------------------------------------------

def test_parse_date_shape_and_independence_from_things_py(run_cli, tmp_path):
    code, payload, _ = run_cli(*NOW, "parse-date", "明天下午3点给妈妈打电话")
    assert code == 0 and payload["urls"] == [] and payload["verified"] is None
    assert payload["data"] == {"when": "2026-09-10@15:00", "deadline": None, "reminder": "15:00", "remaining": "给妈妈打电话", "language": "zh"}
    code, payload, _ = run_cli(*NOW, "parse-date", "Submit expense report by Friday", env={"THINGSDB": str(tmp_path / "missing.sqlite")})
    assert code == 0, "parse-date never touches things.py"
    assert payload["data"] == {"when": None, "deadline": "2026-09-11", "reminder": None, "remaining": "Submit expense report", "language": "en"}
    code, payload, _ = run_cli(*NOW, "parse-date", "下周五", "--kind", "deadline")
    assert code == 0 and payload["data"]["deadline"] == "2026-09-18", "things-deadlines relies on --kind deadline resolving a bare date"
    code, payload, _ = run_cli(*NOW, "parse-date", "下周五", "--kind", "when")
    assert code == 0 and payload["data"]["when"] == "2026-09-18"
    code, payload, _ = run_cli(*NOW, "parse-date", "")
    assert code == 0 and payload["data"]["remaining"] == "" and payload["data"]["when"] is None


def test_get_shapes(run_cli):
    code, payload, _ = run_cli(*NOW, "get", TODO_CHECKLIST)
    assert code == 0 and isinstance(payload["data"], dict)
    assert isinstance(payload["data"]["checklist"], list) and len(payload["data"]["checklist"]) == 3
    assert payload["data"]["repeating"] is False and payload["data"]["link"] == "things:///show?id=" + TODO_CHECKLIST
    code, payload, _ = run_cli(*NOW, "get", PROJECT)
    assert code == 0 and isinstance(payload["data"]["items"], list)
    assert any(i.get("type") == "heading" and isinstance(i.get("items"), list) for i in payload["data"]["items"])
    code, payload, _ = run_cli(*NOW, "get", REPEATING_TEMPLATE)
    assert code == 0 and payload["data"]["repeating"] is True and payload["data"]["title"] == "Repeating To-Do"
    code, payload, _ = run_cli(*NOW, "get", AREA1)
    assert code == 0 and payload["data"]["type"] == "area"
    code, payload, _ = run_cli(*NOW, "get", "NOPE")
    assert code == 1 and payload["error"] == "no item with id NOPE" and payload["data"] is None


def test_today_shape_and_b6_warning(run_cli):
    code, payload, _ = run_cli(*NOW, "today")
    assert code == 0 and B6 in payload["warnings"]
    assert list(payload["data"]) == ["items", "repeating_hint"]
    assert [i["title"] for i in payload["data"]["items"]] == TODAY_ORDER
    for item in payload["data"]["items"]:
        assert isinstance(item["evening"], bool) and isinstance(item["repeating"], bool)
        assert item["link"] == "things:///show?id=" + item["uuid"]
        assert "days_until_deadline" in item
    assert payload["data"]["repeating_hint"] == {"due": [], "templates": 1, "warning": None}
    repeating = next(i for i in payload["data"]["items"] if i["uuid"] == REPEATING_INSTANCE)
    assert repeating["repeating"] is True
    assert "evening detection unavailable" not in payload["warnings"]


def test_other_reads_fixture_counts(run_cli):
    assert len(run_cli(*NOW, "upcoming")[1]["data"]) == 1
    assert len(run_cli(*NOW, "someday")[1]["data"]) == 1
    assert all(i["type"] == "to-do" for i in run_cli(*NOW, "anytime")[1]["data"])
    assert {i["type"] for i in run_cli(*NOW, "anytime", "--all-types")[1]["data"]} >= {"to-do", "project", "heading"}
    assert len(run_cli(*NOW, "logbook")[1]["data"]) == 0 and len(run_cli(*NOW, "logbook", "--days", "3000")[1]["data"]) == 23
    deadlines = run_cli(*NOW, "deadlines")[1]["data"]
    assert len(deadlines) == 4 and [d["deadline"] for d in deadlines] == sorted(d["deadline"] for d in deadlines)
    assert len(run_cli(*NOW, "deadlines", "--within", "0")[1]["data"]) == 3, "negatives included"
    assert len(run_cli(*NOW, "deadlines", "--within", "100000")[1]["data"]) == 4
    assert [p["title"] for p in run_cli(*NOW, "projects", "--area", "Area 1")[1]["data"]] == ["Project in Area 1"]
    assert [p["title"] for p in run_cli(*NOW, "projects", "--area", AREA1)[1]["data"]] == ["Project in Area 1"]
    assert len(run_cli(*NOW, "projects")[1]["data"]) == 3
    assert sorted(a["title"] for a in run_cli(*NOW, "areas")[1]["data"]) == ["Area 1", "Area 2", "Area 3"]
    assert sorted(t["title"] for t in run_cli(*NOW, "tags")[1]["data"]) == ["Errand", "Home", "Important", "Office", "Pending"]


# ---- E.8 write subcommands: URL shapes -------------------------------------------------------------------

def dry(run_cli, *args):
    code, payload, stderr = run_cli(*NOW, "--dry-run", *args)
    assert code == 0, (payload, stderr)
    return payload


def test_add_url_shapes(run_cli):
    p = dry(run_cli, "add", "买牛奶", "--notes", "a\nb", "--when", "2026-09-11@18:00", "--deadline", "tomorrow", "--tags", "Errand",
            "--tags", "Home,Office", "--checklist", "买菜", "--checklist", "a\nb", "--list", "Work", "--heading", "H")
    assert p["urls"] == ["things:///add?title=%E4%B9%B0%E7%89%9B%E5%A5%B6&notes=a%0Ab&when=2026-09-11%4018%3A00&deadline=tomorrow"
                         "&tags=Errand%2CHome%2COffice&checklist-items=%E4%B9%B0%E8%8F%9C%0Aa%0Ab&list=Work&heading=H"]
    p = dry(run_cli, "add", "x", "--tags", "Errand,Nope", "--list-id", PROJECT, "--heading-id", HEADING, "--completed")
    assert p["urls"] == ["things:///add?title=x&tags=Errand&list-id=%s&heading-id=%s&completed=true" % (PROJECT, HEADING)]
    assert "tag not found in Things, dropped: Nope" in p["warnings"]
    assert p["urls"][0].count("?") == 1 and "auth-token" not in p["urls"][0]


def test_add_project_url_shape(run_cli):
    p = dry(run_cli, "add-project", "Ship 🚀 v2", "--area", "Area 1", "--todo", "Plan", "--todo", "Build", "--when", "someday")
    assert p["urls"] == ["things:///add-project?title=Ship%20%F0%9F%9A%80%20v2&when=someday&area=Area%201&to-dos=Plan%0ABuild"]


def test_update_family_url_shapes(run_cli, token_file):
    tok = "&auth-token=***"
    assert dry(run_cli, "update", TODO_INBOX, "--clear", "deadline", "--clear", "tags", "--reopen")["urls"] == [
        "things:///update?id=%s&deadline=&tags=&completed=false%s" % (TODO_INBOX, tok)]
    assert dry(run_cli, "update", TODO_INBOX, "--clear", "when", "--clear", "notes", "--clear", "checklist")["urls"] == [
        "things:///update?id=%s&notes=&when=&checklist-items=%s" % (TODO_INBOX, tok)]
    assert dry(run_cli, "update", TODO_INBOX, "--canceled", "--append-notes", "x&y")["urls"] == [
        "things:///update?id=%s&append-notes=x%%26y&canceled=true%s" % (TODO_INBOX, tok)]
    assert dry(run_cli, "update", PROJECT, "--title", "P2")["urls"] == ["things:///update-project?id=%s&title=P2%s" % (PROJECT, tok)]
    assert dry(run_cli, "cancel", TODO_INBOX)["urls"] == ["things:///update?id=%s&canceled=true%s" % (TODO_INBOX, tok)]
    assert dry(run_cli, "schedule", TODO_INBOX, TODO_ANYTIME, "--when", "2026-09-11@18:00")["urls"] == [
        "things:///update?id=%s&when=2026-09-11%%4018%%3A00%s" % (TODO_INBOX, tok), "things:///update?id=%s&when=2026-09-11%%4018%%3A00%s" % (TODO_ANYTIME, tok)]
    p = dry(run_cli, "schedule", TODO_INBOX, "--when", "anytime")
    assert p["urls"] == ["things:///update?id=%s&when=anytime%s" % (TODO_INBOX, tok)] and ANYTIME_WARNING in p["warnings"]
    assert ANYTIME_WARNING in dry(run_cli, "update", TODO_INBOX, "--when", "anytime")["warnings"]
    assert ANYTIME_WARNING not in dry(run_cli, "update", TODO_INBOX, "--when", "someday")["warnings"]
    assert dry(run_cli, "deadline", OVERDUE_HIDDEN, "--push", "+3d")["urls"] == ["things:///update?id=%s&deadline=2021-05-24%s" % (OVERDUE_HIDDEN, tok)]
    assert dry(run_cli, "deadline", OVERDUE_HIDDEN, "--push", "+1w")["urls"] == ["things:///update?id=%s&deadline=2021-05-28%s" % (OVERDUE_HIDDEN, tok)]
    assert dry(run_cli, "deadline", OVERDUE_HIDDEN, "--clear")["urls"] == ["things:///update?id=%s&deadline=%s" % (OVERDUE_HIDDEN, tok)]
    assert dry(run_cli, "deadline", TODO_INBOX, "--date", "2026-10-01")["urls"] == ["things:///update?id=%s&deadline=2026-10-01%s" % (TODO_INBOX, tok)]
    p = dry(run_cli, "tag", TODO_INBOX, "--add", "Errand,Nope")
    assert p["urls"] == ["things:///update?id=%s&add-tags=Errand%s" % (TODO_INBOX, tok)] and "tag not found in Things, dropped: Nope" in p["warnings"]
    assert dry(run_cli, "tag", TODO_INBOX, "--set", "Home,Office")["urls"] == ["things:///update?id=%s&tags=Home%%2COffice%s" % (TODO_INBOX, tok)]
    assert dry(run_cli, "move", TODO_INBOX, "--area", "Area 1")["urls"] == ["things:///update?id=%s&list=Area%%201%s" % (TODO_INBOX, tok)]
    assert dry(run_cli, "move", TODO_INBOX, "--area-id", AREA1)["urls"] == ["things:///update?id=%s&list-id=%s%s" % (TODO_INBOX, AREA1, tok)]
    assert dry(run_cli, "move", TODO_INBOX, "--list-id", PROJECT, "--heading-id", HEADING)["urls"] == [
        "things:///update?id=%s&list-id=%s&heading-id=%s%s" % (TODO_INBOX, PROJECT, HEADING, tok)]
    assert dry(run_cli, "move", PROJECT, "--area", "Area 2")["urls"] == ["things:///update-project?id=%s&area=Area%%202%s" % (PROJECT, tok)]
    p = dry(run_cli, "show", TODO_INBOX)
    assert p["urls"] == ["things:///show?id=" + TODO_INBOX] and p["verified"] is None


def test_deadline_push_on_item_without_deadline_is_exit_1(run_cli, token_file):
    code, payload, _ = run_cli(*NOW, "--dry-run", "deadline", TODO_INBOX, "--push", "+3d")
    assert code in (1, 4) and payload["ok"] is False


# ---- audit fixes: verification predicates, --yes on add-json, placeholders, past pushes -------------------

TODO_IN_HEADING = "HbKGAeZKFDkWH5osSBNHvz"          # To-Do in Heading: things.py omits `project` for it
UPCOMING = "7F4vqUNiTvGKaCUfv5pqYG"                 # start Someday + start_date 2026-09-17 (Upcoming)
SOMEDAY = "JLYSEPFkLfBC5rhGJRa5S1"                  # start Someday, no start_date
ELEVEN_UPDATES = [{"type": "to-do", "operation": "update", "id": i, "attributes": {"title": "x"}} for i in ELEVEN_OPEN_TODOS]


def fixture_now():
    from datetime import datetime
    return datetime(2026, 9, 9, 10, 0)


def capture_verify(monkeypatch):
    """Replace verify.verify_updated so a test can inspect the ids and predicate the CLI hands over."""
    from things_lib import verify
    captured = {}

    def fake_verify_updated(ids, predicate, **kwargs):
        captured["ids"], captured["predicate"] = ids, predicate
        return verify.VerifyResult(False, "captured", [], [], [])

    monkeypatch.setattr(verify, "verify_updated", fake_verify_updated)
    return captured


def test_deadline_today_tomorrow_verify_against_iso_dates(run_cli, token_file):
    """Finding 0: VALID_DEADLINE admits today/tomorrow but things.py reports ISO dates; the predicate must normalise."""
    cli = load_cli()
    now = fixture_now()
    assert cli.update_predicate({"deadline": "today"}, now)({"deadline": "2026-09-09"}) is True
    assert cli.update_predicate({"deadline": "tomorrow"}, now)({"deadline": "2026-09-10"}) is True
    assert cli.update_predicate({"deadline": "today"}, now)({"deadline": "2026-09-10"}) is False
    assert cli.update_predicate({"deadline": "2026-09-09"}, now)({"deadline": "2026-09-09"}) is True
    assert cli.update_predicate({"deadline": ""}, now)({}) is True
    objects = [{"type": "to-do", "operation": "update", "id": "X", "attributes": {"deadline": "today"}}]
    assert cli.json_update_predicates(objects, now)["X"]({"uuid": "X", "deadline": "2026-09-09"}) is True
    # the URL keeps the documented vocabulary (SPEC A: today | tomorrow | yyyy-mm-dd)
    assert dry(run_cli, "update", TODO_INBOX, "--deadline", "today")["urls"] == [
        "things:///update?id=%s&deadline=today&auth-token=***" % TODO_INBOX]
    assert dry(run_cli, "deadline", TODO_INBOX, "--date", "tomorrow")["urls"] == [
        "things:///update?id=%s&deadline=tomorrow&auth-token=***" % TODO_INBOX]


def test_deadline_command_predicate_accepts_iso_for_literal_date(run_cli, token_file, monkeypatch, capsys):
    """Finding 0, `deadline --date today`: the predicate that batch_update hands to verify must accept the ISO date."""
    from things_lib import read
    captured = capture_verify(monkeypatch)
    module = load_cli()
    code = module.main(NOW + ["deadline", TODO_INBOX, "--date", "today"])
    capsys.readouterr()
    assert code == 0 and captured["ids"] == [TODO_INBOX]
    item = dict(read.get(TODO_INBOX, fixture_now()), deadline="2026-09-09")
    assert captured["predicate"](item) is True
    assert captured["predicate"](dict(item, deadline="2026-09-10")) is False


def test_move_and_update_into_heading_verify_the_list_through_the_heading(run_cli, token_file, monkeypatch, capsys):
    """Finding 2: a to-do under a heading has no `project` key in things.py; the list check must follow the heading."""
    from things_lib import read
    cli = load_cli()
    now = fixture_now()
    item = read.get(TODO_IN_HEADING, now)
    assert "project" not in item and item["heading"] == HEADING, "fixture precondition (database.py:279)"
    lookup = lambda uuid: read.get(uuid, now)  # noqa: E731
    resolved = cli.project_ref(item, lookup)
    assert resolved["project"] == PROJECT and resolved["project_title"] == "Project in Area 1"
    assert cli.project_ref(item, None) is item, "no lookup -> unchanged"
    assert cli.update_predicate({"list-id": PROJECT, "heading": "Heading"}, now, lookup)(item) is True
    assert cli.update_predicate({"list": "Project in Area 1", "heading-id": HEADING}, now, lookup)(item) is True
    assert cli.update_predicate({"list-id": PROJECT, "heading": "Heading"}, now)(item) is False, "without lookup the defect shows"
    assert cli.update_predicate({"list-id": "OtherProject", "heading": "Heading"}, now, lookup)(item) is False

    captured = capture_verify(monkeypatch)
    code = cli.main(NOW + ["move", TODO_IN_HEADING, "--list-id", PROJECT, "--heading", "Heading"])
    capsys.readouterr()
    assert code == 0 and captured["ids"] == [TODO_IN_HEADING]
    assert captured["predicate"](item) is True, "move predicate resolves the project through the heading"
    code = cli.main(NOW + ["update", TODO_IN_HEADING, "--list", "Project in Area 1", "--heading", "Heading"])
    capsys.readouterr()
    assert code == 0 and captured["predicate"](item) is True
    code = cli.main(NOW + ["move", TODO_IN_HEADING, "--list", "Project without Area", "--heading", "Heading"])
    capsys.readouterr()
    assert captured["predicate"](item) is False, "a different list still fails"


def test_when_someday_predicate_rejects_upcoming_items(run_cli):
    """Finding 7: Upcoming items carry start == 'Someday' plus a start_date; only a bare Someday counts."""
    from things_lib import read
    cli = load_cli()
    now = fixture_now()
    upcoming = read.get(UPCOMING, now)
    assert upcoming["start"] == "Someday" and upcoming["start_date"] == "2026-09-17", "fixture precondition"
    assert cli.when_matches(upcoming, "someday", now) is False
    assert cli.when_matches(read.get(SOMEDAY, now), "someday", now) is True
    assert cli.when_matches(upcoming, "2026-09-17", now) is True


def test_add_json_update_payload_respects_the_yes_threshold(run_cli, tmp_path, token_file):
    """Finding 4: E.3 --yes applies to any write over 10 ids; add-json update objects are such a write."""
    path = write_json(tmp_path, ELEVEN_UPDATES)
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-json", path)
    assert code == 4 and payload["error"] == "refusing to modify 11 items without --yes" and payload["urls"] == []
    code, payload, _ = run_cli(*NOW, "--dry-run", "--yes", "add-json", path)
    assert code == 0 and len(payload["urls"]) == 1 and payload["data"]["objects"] == 11
    code, payload, _ = run_cli(*NOW, "--dry-run", "add-json", write_json(tmp_path, ELEVEN_UPDATES[:10]))
    assert code == 0, "ten ids need no --yes"
    # the same id repeated counts once; creates never count
    path = write_json(tmp_path, [dict(ELEVEN_UPDATES[0]) for _ in range(11)])
    assert run_cli(*NOW, "--dry-run", "add-json", path)[0] == 0
    creates = [{"type": "to-do", "attributes": {"title": "t%d" % i}} for i in range(11)]
    assert run_cli(*NOW, "--dry-run", "add-json", write_json(tmp_path, creates))[0] == 0


@pytest.mark.parametrize("args,flag", [
    (["update", TODO_INBOX, "--list", "<AREA>"], "--list"),
    (["update", TODO_INBOX, "--list-id", "<PROJECT_ID>"], "--list-id"),
    (["update", TODO_INBOX, "--heading", "<HEADING>"], "--heading"),
    (["move", TODO_INBOX, "--area", "<AREA>"], "--area"),
    (["move", TODO_INBOX, "--area-id", "<AREA-ID>"], "--area-id"),
    (["move", TODO_INBOX, "--list-id", PROJECT, "--heading", "<HEADING>"], "--heading"),
    (["move", TODO_INBOX, "--list", "<PROJECT>", "--heading-id", HEADING], "--list"),
    (["add", "x", "--list", "<PROJECT>"], "--list"),
    (["add", "x", "--heading-id", "<HEADING_ID>"], "--heading-id"),
    (["add-project", "P", "--area", "<AREA>"], "--area"),
    (["add-project", "P", "--area-id", "<AREA>"], "--area-id"),
])
def test_unfilled_placeholder_is_refused(run_cli, token_file, args, flag):
    """Finding 95: `<AREA>` left over from a skill template must never reach Things (it would ignore the list)."""
    code, payload, stderr = run_cli(*NOW, "--dry-run", *args)
    assert code == 1, (payload, stderr)
    assert payload["ok"] is False and payload["urls"] == [] and payload["sent"] is False
    placeholder = args[args.index(flag) + 1]
    assert payload["error"] == "placeholder %s for %s was not filled in" % (placeholder, flag)


def test_placeholder_shape_is_narrow(run_cli, token_file):
    """Real titles that merely contain angle brackets or lowercase are not placeholders."""
    assert dry(run_cli, "move", TODO_INBOX, "--list", "<area>")["urls"]
    assert dry(run_cli, "move", TODO_INBOX, "--list", "Q3 <Draft>")["urls"]
    assert dry(run_cli, "add", "<TITLE>")["urls"] == ["things:///add?title=%3CTITLE%3E"], "only container flags are checked"


def test_push_that_stays_in_the_past_warns(run_cli, token_file):
    """Finding 88: pushing an overdue deadline by +3d lands in the past; the user most likely meant today+3d."""
    p = dry(run_cli, "deadline", OVERDUE_TODAY, "--push", "+3d")
    assert p["urls"] == ["things:///update?id=%s&deadline=2021-05-24&auth-token=***" % OVERDUE_TODAY]
    assert ("%s: new deadline 2021-05-24 is still in the past (was 2021-05-21); use --date to pick a future date"
            % OVERDUE_TODAY) in p["warnings"]
    p = dry(run_cli, "deadline", TODO_IN_HEADING, "--push", "+3d")   # 2040-11-04 -> 2040-11-07, still ahead
    assert p["urls"] == ["things:///update?id=%s&deadline=2040-11-07&auth-token=***" % TODO_IN_HEADING]
    assert not any("still in the past" in w for w in p["warnings"])
