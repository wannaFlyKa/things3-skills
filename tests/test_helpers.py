"""Skill helper scripts: black-box runs against the fixture and static source checks (SPEC H, C rules)."""

import ast
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

import pytest

from conftest import CLI_PATH, EXAMPLE_CONFIG, FIXTURE_DB, ROOT, SCRIPTS

SKILLS_DIR = os.path.join(ROOT, "plugins", "things", "skills")
HELPERS = {
    "setup_check.py": "things-setup", "plan.py": "things-capture", "candidates.py": "things-close",
    "report.py": "things-close", "review.py": "things-organize", "ddl_report.py": "things-deadlines",
    "brief.py": "things-today",
}
NOW = "2026-09-09T10:00"
B6_EN = "Repeating to-dos may be missing: things.py only sees instances Things has already generated. Open Things once to refresh."
B6_ZH = "重复任务可能不完整：things.py 只能看到 Things 已生成的实例，请先打开一次 Things。"
WHEN_VOCAB = re.compile(r"^(today|tomorrow|evening|anytime|someday|\d{4}-\d{2}-\d{2}(@\d{2}:\d{2})?)$")
DEADLINE_VOCAB = re.compile(r"^(today|tomorrow|\d{4}-\d{2}-\d{2})$")
PLACEHOLDER = "${CLAUDE_SKILL_DIR}"
TODO_TODAY = "5pUx6PESj3ctFYbgth1PXY"
REPEATING = "N1PJHsbjct4mb1bhcs7aHa"


def helper(name):
    return os.path.join(SKILLS_DIR, HELPERS[name], "scripts", name)


def wrapper_ref(name):
    """Claude Code substitutes ${CLAUDE_SKILL_DIR} only in SKILL.md text, never in tool output, so a helper
    prints the ABSOLUTE path of the wrapper next to it (which is what the substituted allowed-tools rule matches)."""
    return os.path.join(SKILLS_DIR, HELPERS[name], "scripts", "things")


def load_module(name):
    loader = importlib.machinery.SourceFileLoader(name.replace(".py", "_mod"), helper(name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def snapshot(root):
    """(path, size, mtime_ns) for every file under root except caches and sqlite sidecars."""
    seen = set()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache", ".git", ".claude", ".venv", "node_modules")]
        for name in files:
            if name.endswith((".pyc", ".sqlite-shm", ".sqlite-wal", ".sqlite-journal")):
                continue
            path = os.path.join(base, name)
            st = os.stat(path)
            seen.add((path, st.st_size, st.st_mtime_ns))
    return seen


@pytest.fixture
def run_helper(tmp_path):
    """run_helper(name, *args, stdin=None) -> (code, stdout, stderr); TMPDIR/HOME/cwd all inside tmp_path."""
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir()

    def run(name, *args, stdin=None, env_extra=None):
        env = dict(os.environ)
        env.update({"THINGSDB": FIXTURE_DB, "HOME": str(tmp_path), "TMPDIR": str(tmpdir),
                    "THINGS_SKILLS_TRANSPORT": "record"})
        env.pop("THINGS_SKILLS_CONFIG", None)
        env.update(env_extra or {})
        before = snapshot(ROOT)
        proc = subprocess.run([sys.executable, helper(name), *args], capture_output=True, text=True, env=env,
                              input=stdin, timeout=120, cwd=str(tmp_path))
        after = snapshot(ROOT)
        assert after - before == set(), "helper wrote inside the repo: %r" % sorted(after - before)
        assert "Traceback" not in proc.stderr, proc.stderr
        return proc.returncode, proc.stdout, proc.stderr
    run.tmpdir = tmpdir
    return run


def parse_json(stdout):
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload


# ---- things-setup/setup_check.py ---------------------------------------------------------------------

def test_setup_check_json_no_create_config(run_helper, tmp_path):
    code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW)
    assert code == 0, err
    report = parse_json(out)
    assert isinstance(report["ok"], bool)
    assert isinstance(report["steps"], list) and len(report["steps"]) == 7, "seven rows (H.2 things-setup)"
    ids = [s["id"] for s in report["steps"]]
    assert len(set(ids)) == 7
    for step in report["steps"]:
        assert set(step) >= {"id", "ok", "detail", "fix", "label"}
        assert isinstance(step["ok"], bool)
    assert report["config_action"] == "missing"
    assert not (tmp_path / ".config" / "things-skills" / "config.json").exists()
    assert report["doctor"]["database"]["status"] == "fixture"
    assert report["doctor"]["cli_version"] == "0.1.0"
    assert "vKkylosuSuGwxrz7qcklOw" not in out and "vKkylosuSuGwxrz7qcklOw" not in err, "token value never printed"
    assert set(report["things"]["tags"]) == {"Errand", "Home", "Important", "Office", "Pending"}
    assert set(report["things"]["areas"]) == {"Area 1", "Area 2", "Area 3"}


def test_setup_check_markdown(run_helper):
    code, out, err = run_helper("setup_check.py", "--no-create-config", "--markdown", "--now", NOW, "--lang", "en")
    assert code == 0, err
    assert "✅" in out or "❌" in out
    assert "|" in out, "one-screen status table"
    assert "Full Disk Access" in out or "readable" in out
    assert out.count("\n") < 80, "one screen"
    with pytest.raises(ValueError):
        json.loads(out)
    code, out_zh, _ = run_helper("setup_check.py", "--no-create-config", "--markdown", "--now", NOW, "--lang", "zh")
    assert code == 0 and re.search(r"[一-鿿]", out_zh)


def test_setup_check_creates_config_from_example_once(run_helper, tmp_path):
    code, out, err = run_helper("setup_check.py", "--now", NOW)
    assert code == 0, err
    report = parse_json(out)
    assert report["config_action"] == "created"
    created = tmp_path / ".config" / "things-skills" / "config.json"
    assert created.exists()
    with open(EXAMPLE_CONFIG, encoding="utf-8") as handle:
        assert json.load(handle) == json.loads(created.read_text(encoding="utf-8"))
    code, out, _ = run_helper("setup_check.py", "--now", NOW)
    assert parse_json(out)["config_action"] == "present"


def test_setup_check_never_writes_to_things(run_helper, tmp_path):
    """Finding 64: under THINGS_SKILLS_TRANSPORT=record the ping used to append ./.things-skills/outbox.jsonl in the cwd."""
    code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW)
    assert code == 0, err
    assert not (tmp_path / ".things-skills").exists(), "the check never writes the record outbox"
    assert parse_json(out)["ping"]["sent"] is False
    assert not any(p.name.startswith(".things-skills") for p in tmp_path.iterdir() if p.is_dir() and p.name != "tmpdir")


def test_setup_check_dry_transport_row_two_blames_the_env_var_not_things(run_helper, tmp_path):
    """Findings 62/1001: with a non-open transport row 2 told the user to install Things from the App Store.
    Finding 2003: with record exported the ping is forced to dry, and row 2 echoed 'dry', a value the user never set."""
    for lang, transport, wrong in (("en", "dry", "App Store"), ("zh", "dry", "App Store"), ("en", "record", "App Store")):
        code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW, "--lang", lang,
                                    env_extra={"THINGS_SKILLS_TRANSPORT": transport})
        assert code == 0, err
        row = [s for s in parse_json(out)["steps"] if s["id"] == "things"][0]
        assert row["ok"] is False and transport in row["detail"], row
        assert "THINGS_SKILLS_TRANSPORT=" + transport in row["fix"] and wrong not in row["fix"], row
        assert not (tmp_path / ".things-skills").exists(), "ping must still run with --transport dry under record"
    code, md, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW, "--lang", "en", "--markdown",
                               env_extra={"THINGS_SKILLS_TRANSPORT": "dry"})
    assert "Install Things 3" not in md and "not attempted: transport is dry" in md


def test_setup_check_invalid_config_never_blames_things_and_leaves_tags_unchecked(run_helper, tmp_path):
    """Findings 2000/2002: a malformed config.json makes the CLI exit 1 on ping; row 2 then sent the user to the App
    Store and row 7 turned green ('config.tags is empty') for a file that was never parsed."""
    cfg = tmp_path / ".config" / "things-skills" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('{"areas": ["Work",', encoding="utf-8")
    for lang, not_checked_2, not_checked_7 in (
            ("en", "not checked: the CLI refuses every command while the config file is invalid", "not checked: fix the config row first"),
            ("zh", "未检查：配置文件无效时 CLI 拒绝执行所有命令", "未检查：请先处理配置文件一行")):
        code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW, "--lang", lang,
                                    env_extra={"THINGS_SKILLS_TRANSPORT": "dry"})
        assert code == 0, err
        report = parse_json(out)
        by_id = {s["id"]: s for s in report["steps"]}
        assert report["ping"]["exit"] == 1 and report["ping"]["error"], "the CLI refused ping because of the config"
        assert by_id["config"]["ok"] is False
        assert by_id["things"]["ok"] is False and by_id["things"]["detail"] == not_checked_2, by_id["things"]
        assert "App Store" not in by_id["things"]["fix"] and "invalid JSON" not in by_id["things"]["detail"]
        assert by_id["tags"]["ok"] is False and by_id["tags"]["detail"] == not_checked_7, by_id["tags"]
        assert by_id["things"]["fix"] == by_id["tags"]["fix"], "both rows point at the config row"
    code, md, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW, "--lang", "en", "--markdown",
                               env_extra={"THINGS_SKILLS_TRANSPORT": "dry"})
    assert "Install Things 3" not in md and "config.tags is empty" not in md
    assert "Fix the Config file row, then rerun." in md


def test_setup_check_users_own_missing_tags_are_not_called_example_tags(run_helper, tmp_path):
    """Finding 2001: any vocabulary entirely absent from Things was labelled 'example tags' and the user was told to
    edit config.tags; only the untouched config.example.json vocabulary is the example."""
    cfg = tmp_path / ".config" / "things-skills" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"tags": ["foo", "bar"]}), encoding="utf-8")
    code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW, "--lang", "en")
    assert code == 0, err
    row = [s for s in parse_json(out)["steps"] if s["id"] == "tags"][0]
    assert row["ok"] is False and row["detail"] == "missing in Things: foo, bar", row
    assert "Create these tags in Things" in row["fix"] and "example" not in row["fix"]
    # one example tag plus one of the user's own: still not the example vocabulary
    cfg.write_text(json.dumps({"tags": ["@calls", "foo"]}), encoding="utf-8")
    code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW, "--lang", "en")
    row = [s for s in parse_json(out)["steps"] if s["id"] == "tags"][0]
    assert row["detail"] == "missing in Things: @calls, foo" and "Create these tags in Things" in row["fix"]
    # the example vocabulary itself (hand-copied, config_action=present) keeps the edit-the-config advice
    with open(EXAMPLE_CONFIG, encoding="utf-8") as handle:
        cfg.write_text(json.dumps({"tags": json.load(handle)["tags"]}), encoding="utf-8")
    code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW, "--lang", "en")
    row = [s for s in parse_json(out)["steps"] if s["id"] == "tags"][0]
    assert row["detail"].startswith("example tags not in Things:") and "These are the example tags" in row["fix"]


def test_setup_check_macos_row_names_macos_not_darwin(run_helper):
    """Finding 1000: row 1 printed 'Darwin 26.6.2', the macOS product version under the kernel's name."""
    code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW)
    row = [s for s in parse_json(out)["steps"] if s["id"] == "macos"][0]
    if sys.platform == "darwin":
        assert row["ok"] is True and row["detail"].startswith("macOS ") and "Darwin" not in row["detail"]
    else:
        assert row["ok"] is False


def test_setup_check_first_run_points_at_the_example_tags_and_numbers_only_failed_rows(run_helper, tmp_path):
    """Findings 63 + 67 + 1011: on run one the tags row asked the user to CREATE the four example tags while row 6 told
    them to edit the same tags; Next steps numbered advice for a passed row so the count never matched."""
    code, md, err = run_helper("setup_check.py", "--now", NOW, "--lang", "en", "--markdown")
    assert code == 0, err
    assert "Create these tags in Things" not in md
    assert "These are the example tags. Replace config.tags in" in md
    assert "example areas" in md and "Work, Personal, Career" in md
    failed = int(re.search(r"(\d+) check\(s\) failed", md).group(1))
    numbered = re.findall(r"^(\d+)\. \*\*", md, re.MULTILINE)
    assert [int(n) for n in numbered] == list(range(1, failed + 1)), md
    assert re.search(r"^- \*\*Config file\*\* — Edit areas", md, re.MULTILINE), "advice on the passed row is a bullet"
    # second run: config present, still the example vocabulary -> still the edit-the-config advice, no numbering drift
    code, md, err = run_helper("setup_check.py", "--now", NOW, "--lang", "en", "--markdown")
    assert "These are the example tags" in md and "- **Config file**" not in md
    # a real config whose routing hint names an area Things lacks: the note names it (1011)
    cfg = tmp_path / ".config" / "things-skills" / "config.json"
    cfg.write_text(json.dumps({"areas": ["Area 1"], "tags": ["Errand"],
                               "routing_hints": [{"pattern": "报销", "area": "Nowhere", "project": None, "regex": False}]}),
                   encoding="utf-8")
    code, out, err = run_helper("setup_check.py", "--now", NOW, "--lang", "en")
    report = parse_json(out)
    assert any("Nowhere" in n and "routing_hints" in n for n in report["notes"]), report["notes"]
    assert [s for s in report["steps"] if s["id"] == "tags"][0]["ok"] is True


def test_setup_check_lang_auto_text_and_config_language(run_helper, tmp_path):
    code, out, err = run_helper("setup_check.py", "--no-create-config", "--now", NOW, "--lang", "auto", "--text", "检查 Things")
    assert parse_json(out)["lang"] == "zh"
    cfg = tmp_path / ".config" / "things-skills" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    code, out, err = run_helper("setup_check.py", "--now", NOW, "--lang", "auto", "--text", "检查 Things")
    assert parse_json(out)["lang"] == "en", "config.language wins over the invocation language"


def test_setup_check_doctor_failure_marks_rows_not_checked(tmp_path, monkeypatch, capsys):
    """Finding 62 (bundled): when `things doctor` produced no envelope, rows 3/5/6 printed confident wrong diagnoses."""
    module = load_module("setup_check.py")
    stub = tmp_path / "things-stub"
    stub.write_text("import sys\nsys.stderr.write('boom: no JSON\\n')\nsys.exit(1)\n", encoding="utf-8")
    monkeypatch.setattr(module, "CLI", str(stub))
    assert module.main(["--no-create-config", "--now", NOW, "--lang", "en"]) == 0
    report = json.loads(capsys.readouterr().out)
    by_id = {s["id"]: s for s in report["steps"]}
    assert len(report["steps"]) == 7
    for step_id in ("things_py", "database", "token", "config", "tags"):
        assert by_id[step_id]["ok"] is False and by_id[step_id]["detail"] == "not checked: things doctor failed"
        assert "Notes" in by_id[step_id]["fix"]
    assert "auth-token is missing" not in json.dumps(report) and "bundled copy missing" not in json.dumps(report)
    assert report["notes"][0].startswith("doctor: boom")


def test_setup_check_writes_defaults_when_the_example_config_is_absent(tmp_path, monkeypatch):
    """Finding 28: the copy-the-folders install has no plugin root, so config.example.json does not exist there."""
    module = load_module("setup_check.py")
    monkeypatch.setattr(module, "EXAMPLE_CONFIG", str(tmp_path / "nope" / "config.example.json"))
    path, action = module.ensure_config(True)
    assert action == "created" and path.startswith(str(tmp_path))
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle) == module.config_mod.DEFAULTS
    assert os.stat(path).st_mode & 0o777 == 0o600


# ---- things-today/brief.py ---------------------------------------------------------------------------

@pytest.mark.parametrize("lang,sentence", [("zh", B6_ZH), ("en", B6_EN)])
def test_brief_json_and_markdown_contain_b6_sentence_in_requested_language(run_helper, lang, sentence):
    code, out, err = run_helper("brief.py", "--lang", lang, "--now", NOW)
    assert code == 0, err
    brief = parse_json(out)
    assert brief["ok"] is True
    assert sentence in out
    assert brief["today"]["count"] == 5 and len(brief["today"]["items"]) == 5
    assert brief["inbox_count"] == 2
    assert len(brief["overdue"]) == 3
    assert brief["repeating_due"] == [] and brief["repeating_templates"] == 1
    for item in brief["today"]["items"]:
        assert item["link"].startswith("things:///show?id=") and isinstance(item["evening"], bool)
    code, md, err = run_helper("brief.py", "--lang", lang, "--now", NOW, "--markdown")
    assert code == 0, err
    assert sentence in md
    other = B6_EN if lang == "zh" else B6_ZH
    assert other not in md, "only the requested language"
    checklist = re.findall(r"^- \[ \] (.+) \(\[Things\]\(things:///show\?id=([A-Za-z0-9]{22})\)\)$", md, re.MULTILINE)
    assert len(checklist) == 5
    assert md.rstrip().endswith("```"), "the Obsidian block is the last thing"
    assert "/things:things-organize today" not in md, "5 items do not exceed the default cap of 6"


def test_brief_over_cap_hands_off_to_organize(run_helper, tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"today_cap": 2}), encoding="utf-8")
    code, md, err = run_helper("brief.py", "--lang", "en", "--now", NOW, "--markdown", "--config", str(cfg))
    assert code == 0, err
    assert "/things:things-organize today" in md


def test_brief_invalid_now_is_a_json_error_envelope(run_helper):
    """Finding 34: `--now nope` escaped as a ValueError traceback."""
    code, out, err = run_helper("brief.py", "--now", "nope")
    assert code == 1 and parse_json(out)["ok"] is False and "invalid --now" in parse_json(out)["error"]
    assert "Traceback" not in err


def test_brief_lang_auto_text_respects_config_language(run_helper, tmp_path):
    """Finding 69: SKILL.md told the model to force --lang zh|en, overriding config.language (SPEC H.1)."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    code, md, err = run_helper("brief.py", "--lang", "auto", "--text", "早报", "--now", NOW, "--markdown", "--config", str(cfg))
    assert code == 0 and md.startswith("# Morning brief")
    cfg.write_text(json.dumps({}), encoding="utf-8")
    code, md, err = run_helper("brief.py", "--lang", "auto", "--text", "早报", "--now", NOW, "--markdown", "--config", str(cfg))
    assert code == 0 and md.startswith("# 早报")


def patched_fixture(tmp_path, sql):
    """A private copy of the fixture with one statement applied (tests only; helpers never touch SQLite)."""
    import shutil
    import sqlite3
    copy = tmp_path / "patched.sqlite"
    shutil.copyfile(FIXTURE_DB, str(copy))
    conn = sqlite3.connect(str(copy))
    conn.execute(sql)
    conn.commit()
    conn.close()
    return str(copy)


def test_brief_repeating_due_carries_a_things_link(run_helper, tmp_path):
    """Findings 70/1004: the 'Repeating, probably due' lines had no things:///show?id= link although the uuid was there."""
    db = patched_fixture(tmp_path, "UPDATE TMTask SET rt1_nextInstanceStartDate=132813824 WHERE uuid='%s'" % REPEATING)
    code, out, err = run_helper("brief.py", "--lang", "en", "--now", NOW, env_extra={"THINGSDB": db})
    assert code == 0, err
    due = parse_json(out)["repeating_due"]
    assert len(due) == 1 and due[0]["link"] == "things:///show?id=" + REPEATING and due[0]["next_instance_date"] == "2026-09-08"
    code, md, err = run_helper("brief.py", "--lang", "en", "--now", NOW, "--markdown", env_extra={"THINGSDB": db})
    block = md.split("## Repeating, probably due (1)\n", 1)[1].split("\n\n", 1)[0]
    assert re.fullmatch(r"- Repeating To-Do · next 2026-09-08 · \[Things\]\(things:///show\?id=%s\)" % REPEATING, block), block


def test_brief_evening_unavailable_is_said_once_in_the_brief_language(run_helper, tmp_path):
    """Findings 71/1006: the raw English CLI warning was printed again under a zh brief that already carried the placeholder."""
    db = patched_fixture(tmp_path, "ALTER TABLE TMTask DROP COLUMN startBucket")
    code, md, err = run_helper("brief.py", "--lang", "zh", "--now", NOW, "--markdown", env_extra={"THINGSDB": db})
    assert code == 0, err
    assert "evening detection unavailable" not in md
    assert md.count("无法识别今晚项目") == 1 and "警告:" not in md
    code, md, err = run_helper("brief.py", "--lang", "en", "--now", NOW, "--markdown", env_extra={"THINGSDB": db})
    assert md.count("evening detection unavailable") == 1 and "warning:" not in md
    code, out, err = run_helper("brief.py", "--lang", "zh", "--now", NOW, env_extra={"THINGSDB": db})
    assert "evening detection unavailable" in parse_json(out)["warnings"], "JSON keeps the raw machine-readable warning"


def test_brief_markdown_localises_known_warnings_and_keeps_the_block_empty_for_an_empty_today():
    brief = load_module("brief.py")
    b = {"lang": "zh", "now": "2026-09-09", "weekday": "周三", "today": {"count": 0, "over_cap": False, "items": []},
         "evening": {"available": True, "items": []}, "repeating_due": [], "overdue": [], "deadlines_7": [], "inbox_count": 0,
         "repeating_sentence": B6_ZH, "today_cap": 6, "warnings": ["repeating detection unavailable", "something else"],
         "checklist": ""}
    md = brief.render_markdown(b)
    assert "警告: 无法识别重复任务，重复标记可能缺失" in md and "警告: something else" in md
    assert "repeating detection unavailable" not in md
    assert md.rstrip().endswith("```\n\n```"), "no bare `- [ ]` for an empty Today"


# ---- things-deadlines/ddl_report.py ------------------------------------------------------------------

def test_ddl_report_json_and_markdown(run_helper):
    code, out, err = run_helper("ddl_report.py", "--now", NOW, "--lang", "en")
    assert code == 0, err
    report = parse_json(out)
    assert report["ok"] is True and report["lead_days"] == 3 and report["reminder_time"] == "09:00"
    assert isinstance(report["proposals"], list)
    for n, proposal in enumerate(report["proposals"], 1):
        assert proposal["n"] == n
        if proposal["command"]:
            assert proposal["command"].startswith(wrapper_ref("ddl_report.py") + " schedule ")
            assert re.search(r"--when (\d{4}-\d{2}-\d{2}(@\d{2}:\d{2})?|today|tomorrow)$", proposal["command"])
    dumped = json.dumps(report, ensure_ascii=False)
    assert "things:///show?id=" in dumped
    assert PLACEHOLDER not in out, "the placeholder is never substituted in tool output (finding 86)"
    assert report["proposals"], "the fixture has at-risk items"
    code, md, err = run_helper("ddl_report.py", "--now", NOW, "--lang", "zh", "--markdown")
    assert code == 0, err
    assert "things:///show?id=" in md and re.search(r"[一-鿿]", md)
    assert "Overdue Todo automatically shown in Today" in md, "titles never translated"
    assert PLACEHOLDER not in md and wrapper_ref("ddl_report.py") + " deadline <id> --push +3d" in md
    # finding 91: one punctuation system per language
    assert "# 截止日期报告 — 2026-09-09（提前量 3 天）" in md and "## 逾期（3）" in md and "（已过 " in md
    assert "**有风险：已逾期且没有开始日期**" in md and "## 今天到期（0）" in md
    assert "(提前量" not in md and "有风险: " not in md
    code, md_en, err = run_helper("ddl_report.py", "--now", NOW, "--lang", "en", "--markdown")
    assert "# Deadlines report — 2026-09-09 (lead 3 days)" in md_en and "## Overdue (3)" in md_en
    assert "**at risk: overdue, no start date**" in md_en


def test_ddl_report_invalid_now_is_a_json_error_envelope(run_helper):
    """Finding 34: `--now nope` escaped as a ValueError traceback."""
    code, out, err = run_helper("ddl_report.py", "--now", "nope")
    assert code == 1 and parse_json(out)["ok"] is False and "invalid --now" in parse_json(out)["error"]
    assert "Traceback" not in err


@pytest.mark.parametrize("phrase,spec", [("推后三天", "+3d"), ("push +3d", "+3d"), ("postpone two weeks", "+2w"),
                                         ("推后两周", "+2w"), ("+1w", "+1w"), ("推迟5天", "+5d"),
                                         # finding 31: no left boundary let 'an'+'d' match inside and/hand/stand
                                         ("push the design and the review by two weeks", "+2w"),
                                         ("hand it in 2 days later", "+2d"), ("stand by for 3 weeks", "+3w"),
                                         ("push it a day", "+1d"), ("推后十二天", "+12d"),
                                         # finding 31: English 'push back by' is a postponement, not an earlier marker
                                         ("push the deadline back by 3 days", "+3d"), ("move the deadline back by a week", "+1w"),
                                         ("提前一周", "-1w"), ("bring forward 2d", "-2d"), ("two days earlier", "-2d")])
def test_ddl_push_spec_conversion(run_helper, phrase, spec):
    code, out, err = run_helper("ddl_report.py", "--push-spec", phrase)
    assert code == 0, err
    assert parse_json(out)["spec"] == spec and parse_json(out)["flag"] == "--push=" + spec


# ---- things-organize/review.py -----------------------------------------------------------------------

@pytest.mark.parametrize("scope", ["all", "inbox", "today"])
def test_review_scope_numbered_proposals_with_links_and_commands(run_helper, scope):
    code, out, err = run_helper("review.py", "--scope", scope, "--now", NOW, "--lang", "en")
    assert code == 0, err
    review = parse_json(out)
    assert review.get("ok", True) is not False
    proposals = review["proposals"]
    assert isinstance(proposals, list) and proposals, "the fixture yields proposals for scope %s" % scope
    assert [p["n"] for p in proposals] == list(range(1, len(proposals) + 1)), "numbered 1..N"
    for proposal in proposals:
        dumped = json.dumps(proposal, ensure_ascii=False)
        assert "things:///show?id=" in dumped, proposal
        assert re.search(r"scripts/things (schedule|move|deadline|tag|cancel|complete|update|add) ", dumped), "each proposal carries a CLI command"
        assert "--yes" not in dumped
    assert review["saved"].startswith(str(run_helper.tmpdir)), "saved review lives in TMPDIR"
    assert os.path.isfile(review["saved"])
    code, md, err = run_helper("review.py", "--scope", scope, "--now", NOW, "--lang", "en", "--markdown")
    assert code == 0 and "things:///show?id=" in md and re.search(r"(^|\n)\s*1[.)]", md)


def test_review_bad_scope_exit_1_json(run_helper):
    code, out, err = run_helper("review.py", "--scope", "NoSuchAreaOrProject", "--now", NOW)
    assert code == 1
    assert parse_json(out)["ok"] is False


def test_review_apply_turns_numbers_into_batched_commands(run_helper):
    code, out, _ = run_helper("review.py", "--scope", "all", "--now", NOW, "--lang", "en")
    review = parse_json(out)
    code, out, err = run_helper("review.py", "--apply", "1", "--from", review["saved"])
    assert code == 0, err
    applied = parse_json(out)
    assert applied["ok"] is True and applied["selected"] == [1]
    for command in applied["commands"]:
        assert re.search(r"scripts/things (schedule|move|deadline|tag|cancel|complete|update|add) ", command["command"])
        assert len(command["ids"]) <= 10 and "--yes" not in command["command"]


def test_review_commands_use_the_wrapper_form_its_skill_promises(run_helper):
    """things-organize/SKILL.md: every command is `<skill scripts dir>/things <sub> ...`, printed as a real path (H.1 form)."""
    code, out, _ = run_helper("review.py", "--scope", "inbox", "--now", NOW, "--lang", "en")
    review = parse_json(out)
    commands = re.findall(r'"command": "([^"]+)"', json.dumps(review, ensure_ascii=False))
    assert commands
    assert all(c.startswith(wrapper_ref("review.py") + " ") for c in commands), commands[:3]
    assert PLACEHOLDER not in out, "the placeholder is never substituted in tool output"


def test_review_lang_auto_text_and_config_language(run_helper, tmp_path):
    """Finding 24: config.language could never take effect because SKILL.md forced --lang zh|en and there was no --text."""
    code, md, err = run_helper("review.py", "--scope", "inbox", "--now", NOW, "--lang", "auto", "--text", "周回顾", "--markdown")
    assert code == 0 and md.startswith("# Things 回顾"), md[:80]
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"language": "en"}), encoding="utf-8")
    code, md, err = run_helper("review.py", "--scope", "inbox", "--now", NOW, "--lang", "auto", "--text", "周回顾", "--markdown",
                               "--config", str(cfg))
    assert code == 0 and md.startswith("# Things review"), "config.language wins over the invocation language"
    code, md, err = run_helper("review.py", "--scope", "inbox", "--now", NOW, "--lang", "auto", "--markdown")
    assert code == 0 and md.startswith("# Things review"), "no text, no config -> en"


def test_review_zh_inbox_lines_use_chinese_punctuation_and_name_the_config_key(run_helper):
    """Finding 98: '没有匹配的 routing hint，...; 文中没有日期...' mixed prose English with an ASCII join."""
    code, md, err = run_helper("review.py", "--scope", "inbox", "--now", NOW, "--lang", "zh", "--markdown")
    assert code == 0, err
    line = [l for l in md.splitlines() if "路由规则" in l][0]
    assert "没有匹配的路由规则（config.routing_hints），请选一个领域（Area 3、Area 2、Area 1）；文中没有日期，进入 Anytime；不需要截止日期" in line
    assert "routing hint" not in md and "; " not in line


def test_review_apply_rejects_tampered_or_malformed_saved_files(run_helper, tmp_path):
    """Findings 60 + 34: a saved review is data from disk; an injected `sub` reached the printed command unquoted, and a
    non-list `proposals` crashed with a traceback."""
    code, out, _ = run_helper("review.py", "--scope", "inbox", "--now", NOW, "--lang", "en")
    saved = parse_json(out)
    saved["proposals"][0]["options"][0]["sub"] = "schedule; echo PWNED #"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(saved), encoding="utf-8")
    code, out, err = run_helper("review.py", "--apply", "1", "--from", str(tampered))
    assert code == 1 and parse_json(out)["ok"] is False and "unknown command" in parse_json(out)["error"]
    assert "PWNED" not in out
    for bad in ('{"proposals": [1]}', '{"proposals": {"a": 1}}', '{"proposals": [{"n": "1", "options": []}]}'):
        (tmp_path / "bad.json").write_text(bad, encoding="utf-8")
        code, out, err = run_helper("review.py", "--apply", "1", "--from", str(tmp_path / "bad.json"))
        assert code == 1 and parse_json(out)["ok"] is False, bad
        assert "Traceback" not in err
    review = load_module("review.py")
    assert review.render("/cli", "sched ule", ["X"], []) == "/cli 'sched ule' X", "sub is shell-quoted like everything else"


def test_review_prunes_this_users_saved_reviews_older_than_a_day(run_helper):
    """Finding 35 (2): saved reviews (task titles and notes) accumulated in TMPDIR forever."""
    old = run_helper.tmpdir / "things-organize-1.json"
    recent = run_helper.tmpdir / "things-organize-2.json"
    other = run_helper.tmpdir / "not-ours-1.json"
    for path in (old, recent, other):
        path.write_text("{}", encoding="utf-8")
    stale = time.time() - 2 * 86400
    os.utime(str(old), (stale, stale))
    os.utime(str(other), (stale, stale))
    code, out, err = run_helper("review.py", "--scope", "inbox", "--now", NOW, "--lang", "en")
    assert code == 0, err
    assert not old.exists() and recent.exists() and other.exists()


def test_review_all_words_include_common_chinese_and_english_yes(run_helper):
    """Finding 26: '好的' / 'ok' made --apply exit 1."""
    code, out, _ = run_helper("review.py", "--scope", "inbox", "--now", NOW, "--lang", "en")
    saved = parse_json(out)["saved"]
    for answer in ("好的", "ok", "可以", "是", "all"):
        code, out, err = run_helper("review.py", "--apply", answer, "--from", saved)
        assert code == 0 and parse_json(out)["selected"], answer
    code, out, err = run_helper("review.py", "--apply", "1 and 3", "--from", saved)
    assert code == 1 and "cannot read selection token 'and'" in parse_json(out)["error"], "unknown tokens still fail loud"


def test_review_do_now_flags_only_communication_verbs():
    """Finding 94: bare send/ask/confirm/book/确认/预约 flagged ordinary tasks as two-minute DO NOW items."""
    review = load_module("review.py")
    for title in ("Read the book", "Fix text alignment in header", "Confirm architecture with team", "Book flights for Q4 offsite",
                  "确认需求文档终稿", "Send Q3 report to finance", "Ask legal about the contract", "预约体检", "Write the design doc",
                  "Forward-looking roadmap draft", "Draft a respond-to-RFP checklist"):
        assert review.is_do_now(title) is False, title
    for title in ("Call mom", "Reply to Bob", "回复 Bob 的邮件", "给 Bob 打电话", "Email Alice about the invoice", "Text Bob", "call back Dr Lee"):
        assert review.is_do_now(title) is True, title


def test_review_route_missing_is_distinguished_from_no_hint():
    """Finding 93: a hint that matched but whose area is not in Things said 'no routing hint matched'."""
    review = load_module("review.py")
    ctx = {"lang": "en", "project_titles": [], "area_titles": ["Home"],
           "config": {"routing_hints": [{"pattern": "报销", "area": "Work", "project": None, "regex": False}]}}
    words, target, kind, needs_input = review.resolve_route(ctx, {"title": "报销 8 月发票", "notes": ""})
    assert words == "routing hint matched area “Work” but Things has no such area: create it or pick an area (Home)"
    assert (target, kind, needs_input) == ("<AREA>", "area", True)
    assert review.resolve_route(ctx, {"title": "nothing", "notes": ""})[0] == "no routing hint matched, pick an area (Home)"
    ctx["lang"] = "zh"
    assert review.resolve_route(ctx, {"title": "报销", "notes": ""})[0] == "路由规则命中领域「Work」，但 Things 里没有这个领域：请先创建，或从（Home）中选一个领域"


def test_review_evening_check_skips_inbox_and_someday_items():
    """Finding 92: a Someday '健身' got both `schedule --when <date>@18:00` (evening) and `schedule --when anytime` (someday)."""
    review = load_module("review.py")
    from datetime import datetime as dt
    ctx = {"lang": "en", "now": dt(2026, 9, 9, 10, 0), "today": dt(2026, 9, 9).date(), "today_ids": set(), "evening_ids": set(),
           "universe": [{"uuid": "k1", "type": "to-do", "title": "健身", "start": "Someday"},
                        {"uuid": "k2", "type": "to-do", "title": "买菜", "start": "Inbox"},
                        {"uuid": "k3", "type": "to-do", "title": "gym", "start": "Anytime"}]}
    props, _ = review.check_evening(ctx, None)
    assert [p["id"] for p in props] == ["k3"]


def test_review_warn_anytime_follows_the_commands_and_projects_are_marked(run_helper):
    """Findings 97 + 96: the when=anytime note came only from the someday check; the Markdown never showed an item's type."""
    review = load_module("review.py")
    code, out, err = run_helper("review.py", "--scope", "all", "--now", NOW, "--lang", "en")
    result = parse_json(out)
    uses_anytime = any(" --when anytime" in p["command"] for p in result["proposals"])
    assert uses_anytime and any(w.startswith("when=anytime is undocumented") for w in result["warnings"])
    assert result["warnings"].count([w for w in result["warnings"] if w.startswith("when=anytime")][0]) == 1
    ctx = {"lang": "en", "now": review.datetime(2026, 9, 9, 10, 0), "config": {"someday_resurface_days": 90}, "someday": [], "warnings": []}
    review.check_someday(ctx, None)
    assert ctx["warnings"] == [], "check_someday no longer appends the note itself"
    result["proposals"][0]["type"] = "project"
    md = review.review_markdown(result)
    first = [l for l in md.splitlines() if l.startswith("1. **")][0]
    assert " · project) " in first
    assert md.count(" · project)") == 1 + sum(1 for p in result["proposals"][1:] if p.get("type") == "project")


# ---- things-close/candidates.py ----------------------------------------------------------------------

def check_candidates(result):
    rows = result["candidates"]
    assert rows and rows[0]["n"] == 1
    by_title = {r["title"]: r for r in rows}
    assert "To-Do in Inbox" in by_title and by_title["To-Do in Inbox"]["n"] <= 2
    assert by_title["To-Do in Inbox"]["link"] == "things:///show?id=DfYoiXcNLQssk9DkSoJV3Y"
    assert by_title["To-Do in Inbox"]["match"] == "title"
    assert [r["n"] for r in rows] == list(range(1, len(rows) + 1))
    assert result["commands"] is None, "no write command exists before the user has picked rows"


def test_candidates_positional_and_stdin(run_helper):
    code, out, err = run_helper("candidates.py", "To-Do in Inbox", "--now", NOW)
    assert code == 0, err
    check_candidates(parse_json(out))
    code, out, err = run_helper("candidates.py", "--now", NOW, stdin='["To-Do in Inbox"]')
    assert code == 0, err
    check_candidates(parse_json(out))
    code, md, err = run_helper("candidates.py", "To-Do in Inbox", "--now", NOW, "--markdown", "--lang", "en")
    assert code == 0 and "| 1 |" in md and "things:///show?id=DfYoiXcNLQssk9DkSoJV3Y" in md
    assert "scripts/things complete" not in md and "scripts/things cancel" not in md, "no runnable line before a pick"
    assert "--pick" in md, "tells the model how to get the command lines after the pick"


def test_candidates_pick_prints_only_picked_ids_for_one_verb_via_report_pipe(run_helper):
    """Findings 22/30: before, every candidate id was printed under BOTH verbs before the user picked anything."""
    code, out, err = run_helper("candidates.py", "To-Do in Inbox", "repeating", "--now", NOW, "--lang", "en")
    assert code == 0, err
    rows = parse_json(out)["candidates"]
    by_title = {r["title"]: r for r in rows}
    inbox, repeating = by_title["To-Do in Inbox"], by_title["Repeating To-Do"]
    assert repeating["repeating"] is True and len(rows) >= 3
    unpicked = [r["uuid"] for r in rows if r["n"] not in (inbox["n"], repeating["n"])]
    assert unpicked, "the fixture yields at least one row the user does not pick"
    pick = "%d,%d" % (inbox["n"], repeating["n"])
    code, out, err = run_helper("candidates.py", "To-Do in Inbox", "repeating", "--now", NOW, "--lang", "en",
                                "--pick", pick, "--action", "complete")
    assert code == 0, err
    picked = parse_json(out)["commands"]
    assert picked["action"] == "complete" and picked["picked"] == sorted([inbox["n"], repeating["n"]])
    assert picked["ids"] == [inbox["uuid"]], "the repeating row is left out, the unpicked rows never appear"
    assert [r["uuid"] for r in picked["left_out"]] == [repeating["uuid"]]
    assert len(picked["lines"]) == 1
    line = picked["lines"][0]
    report = os.path.join(SKILLS_DIR, "things-close", "scripts", "report.py")
    assert line == "%s complete %s | %s --markdown --lang en" % (wrapper_ref("candidates.py"), inbox["uuid"], report)
    assert " cancel " not in line and PLACEHOLDER not in out and "--yes" not in line
    for uid in unpicked:
        assert uid not in line
    code, md, err = run_helper("candidates.py", "To-Do in Inbox", "repeating", "--now", NOW, "--lang", "zh",
                               "--pick", pick, "--action", "cancel", "--markdown")
    assert code == 0, err
    assert "    %s cancel %s | " % (wrapper_ref("candidates.py"), inbox["uuid"]) in md
    assert md.count("scripts/things cancel ") == 1 and "scripts/things complete" not in md
    assert "已排除" in md and "Repeating To-Do" in md


def test_candidates_pick_batches_of_ten_and_all(run_helper):
    items = ["Inbox", "Today", "Area", "Project", "Heading", "Upcoming", "Someday"]
    code, out, err = run_helper("candidates.py", *items, "--now", NOW, "--limit", "30", "--pick", "all", "--action", "complete")
    assert code == 0, err
    result = parse_json(out)
    rows = [r for r in result["candidates"] if not r["repeating"]]
    lines = result["commands"]["lines"]
    assert len(rows) > 10, "the fixture has more than ten non-repeating hits for these items"
    assert result["commands"]["ids"] == [r["uuid"] for r in rows]
    assert len(lines) == (len(rows) + 9) // 10
    for line in lines:
        ids = line.split(" | ")[0].split()[2:]
        assert 1 <= len(ids) <= 10 and "--yes" not in line


@pytest.mark.parametrize("args,needle", [
    (["--pick", "99", "--action", "complete"], "no such candidate"),
    (["--pick", "1"], "--pick and --action go together"),
    (["--pick", "x", "--action", "cancel"], "no such candidate"),
])
def test_candidates_bad_pick_is_a_json_error(run_helper, args, needle):
    code, out, err = run_helper("candidates.py", "To-Do in Inbox", "--now", NOW, *args)
    assert code == 1, err
    payload = parse_json(out)
    assert payload["ok"] is False and needle in payload["error"]


@pytest.mark.parametrize("pick", ["all", "全部", "1"])
def test_candidates_pick_with_no_candidates_is_a_json_error(run_helper, pick):
    """Finding 2019: `--pick all` on zero rows exited 0 and printed 'every picked row is a repeating to-do'."""
    code, out, err = run_helper("candidates.py", "zzzqqq", "--now", NOW, "--pick", pick, "--action", "cancel")
    assert code == 1, err
    payload = parse_json(out)
    assert payload["ok"] is False and "no candidates to pick from" in payload["error"]
    assert "rows are 1-0" not in payload["error"] and "repeating" not in payload["error"]
    code, md, err = run_helper("candidates.py", "zzzqqq", "--now", NOW, "--markdown", "--lang", "en")
    assert code == 0 and "No open to-do matches anything described." in md and "Nothing to run" not in md


def test_candidates_list_column_names_the_project_of_a_to_do_under_a_heading(run_helper):
    """Finding 2018: things.py leaves project/project_title empty under a heading; the row said 'Anytime'."""
    code, out, err = run_helper("candidates.py", "Heading", "--now", NOW, "--lang", "en")
    assert code == 0, err
    result = parse_json(out)
    by_title = {r["title"]: r for r in result["candidates"]}
    row = by_title["To-Do in Heading"]
    assert row["uuid"] == "HbKGAeZKFDkWH5osSBNHvz" and row["start"] == "Anytime"
    assert row["list"] == "Project in Area 1", "resolved through `things get <heading>`"
    assert result["warnings"] == []
    candidates = load_module("candidates.py")
    fallback = {"uuid": "X", "heading": "H", "heading_title": "Heading", "start": "Anytime", "start_date": None}
    assert candidates.list_of(fallback, "2026-09-09") == "Heading", "heading title when the lookup failed"
    assert candidates.list_of({"start": "Anytime", "start_date": None}, "2026-09-09") == "Anytime"


def test_candidates_malformed_input_is_a_json_error_not_plain_text(run_helper):
    """Finding 34: SPEC H.1 promises {"ok": false, "error": ...} with a non-zero exit, never a bare `error:` line."""
    code, out, err = run_helper("candidates.py", "--now", NOW, stdin='{"a": 1}')
    assert code == 1 and parse_json(out)["ok"] is False and "JSON array" in parse_json(out)["error"]
    code, out, err = run_helper("candidates.py", "To-Do in Inbox", "--now", "nope")
    assert code == 1 and parse_json(out)["ok"] is False and "invalid --now" in parse_json(out)["error"]


def test_candidates_to_do_is_a_stopword_so_the_for_column_discriminates(run_helper):
    """Finding 1015: 'to-do' survived EN_STOP ('todo' did not) and matched every fixture title."""
    candidates = load_module("candidates.py")
    assert candidates.tokenize("to-do in today") == ([], [])
    assert candidates.queries_for("to-do in today") == [("phrase", "to-do in today")], "raw phrase fallback"
    code, out, err = run_helper("candidates.py", "to-do in today", "repeating to-do", "--now", NOW, "--lang", "en")
    assert code == 0, err
    rows = parse_json(out)["candidates"]
    by_title = {r["title"]: r for r in rows}
    assert by_title["To-Do in Today"]["for"] == ["to-do in today"]
    assert by_title["Repeating To-Do"]["for"] == ["repeating to-do"]


def test_candidates_list_column_says_upcoming_or_today_for_dated_items(run_helper):
    """Finding 1014: things.py reports every dated item as start='Someday'; the date decides Today vs Upcoming."""
    code, out, err = run_helper("candidates.py", "To-Do in Upcoming", "To-Do in Today", "--now", NOW, "--lang", "en")
    assert code == 0, err
    by_title = {r["title"]: r for r in parse_json(out)["candidates"]}
    assert by_title["To-Do in Upcoming"]["start_date"] == "2026-09-17"
    assert by_title["To-Do in Upcoming"]["list"] == "Upcoming"
    assert by_title["To-Do in Today"]["list"] == "Today"
    assert "Someday" not in {r["list"] for r in by_title.values() if r["start_date"]}


def test_candidates_maybe_closed_status_is_localised_in_chinese():
    """Finding 1016: the 'possibly already closed' hint printed the raw English status inside the Chinese sentence."""
    candidates = load_module("candidates.py")
    result = {"candidates": [], "unmatched": [{"item": "牙医", "maybe_closed": [
        {"title": "预约牙医", "status": "completed", "stop_date": "2025-09-09", "link": "things:///show?id=X"}]}],
        "commands": None, "warnings": []}
    zh = candidates.render_markdown(result, "zh")
    assert "预约牙医（已完成，2025-09-09）" in zh and "completed" not in zh
    en = candidates.render_markdown(result, "en")
    assert "预约牙医 (completed, 2025-09-09)" in en


def test_candidates_exact_title_match_ranks_first(run_helper):
    """Stricter reading of H.2 'rank candidates': the item whose title IS the described text outranks superstring hits."""
    code, out, err = run_helper("candidates.py", "To-Do in Inbox", "--now", NOW)
    assert code == 0, err
    assert parse_json(out)["candidates"][0]["title"] == "To-Do in Inbox"


def test_candidates_chinese_labels_keep_titles_verbatim(run_helper):
    code, md, err = run_helper("candidates.py", "收件箱 Inbox", "--now", NOW, "--markdown", "--lang", "zh")
    assert code == 0, err
    assert "To-Do in Inbox" in md and re.search(r"[一-鿿]", md)


# ---- things-capture/plan.py --------------------------------------------------------------------------

PLAN_INPUT = [
    {"text": "明天下午3点给妈妈打电话", "title": "给妈妈打电话"},
    {"text": "finish the expense report by Friday", "title": "finish the expense report", "notes": "see https://x.y/z?a=1&b=2"},
]


def commands_of(plan):
    return [c["command"] for c in plan["commands"]]


def test_plan_json_chinese_and_english(run_helper, tmp_path):
    path = tmp_path / "cands.json"
    path.write_text(json.dumps(PLAN_INPUT, ensure_ascii=False), encoding="utf-8")
    code, out, err = run_helper("plan.py", "--input", str(path), "--now", NOW)
    assert code == 0, err
    plan = parse_json(out)
    assert plan["ok"] is True and plan["mixed"] is True
    cands = plan["candidates"]
    assert [c["title"] for c in cands] == ["给妈妈打电话", "finish the expense report"], "titles never translated"
    assert cands[0]["language"] == "zh" and cands[1]["language"] == "en"
    assert cands[0]["when"] == "2026-09-10@15:00" and cands[0]["deadline"] is None
    assert cands[1]["deadline"] == "2026-09-11" and cands[1]["when"] is None
    commands = commands_of(plan)
    assert len(commands) == 2
    for command in commands:
        assert command.startswith(wrapper_ref("plan.py") + " add ")
        for flag, value in re.findall(r"--(when|deadline)=(\S+)", command):
            value = value.strip("'\"")
            assert (WHEN_VOCAB if flag == "when" else DEADLINE_VOCAB).match(value), command
    assert "--when=2026-09-10@15:00" in commands[0] or "--when='2026-09-10@15:00'" in commands[0]
    assert "--deadline=2026-09-11" in commands[1]
    assert "--yes" not in " ".join(commands)
    assert plan["confirm_prompt"], "asks for confirmation unless --yes"
    assert "SECRET" not in out and "auth-token" not in out
    assert plan["payload_files"] == {} or plan["payload_files"] == []
    assert PLACEHOLDER not in out, "the placeholder is never substituted in tool output"


def test_plan_stdin_custom_cli_and_yes(run_helper):
    code, out, err = run_helper("plan.py", "--now", NOW, "--cli", "/opt/x/things", "--yes", stdin=json.dumps(PLAN_INPUT, ensure_ascii=False))
    assert code == 0, err
    plan = parse_json(out)
    assert all(c.startswith("/opt/x/things ") and " add " in c for c in commands_of(plan)), commands_of(plan)
    assert all("${CLAUDE_SKILL_DIR}" not in c for c in commands_of(plan))
    assert plan["confirm_prompt"] is None and plan["yes"] is True
    code, md, err = run_helper("plan.py", "--now", NOW, "--markdown", stdin=json.dumps(PLAN_INPUT, ensure_ascii=False))
    assert code == 0 and "给妈妈打电话" in md and "|" in md and wrapper_ref("plan.py") + " add" in md


def run_wrapper_dry(skill, *args):
    """Run `<skill>/scripts/things --dry-run <args>` the way the model would run a printed command."""
    env = dict(os.environ)
    env.update({"THINGSDB": FIXTURE_DB, "THINGS_SKILLS_TRANSPORT": "dry"})
    wrapper = os.path.join(SKILLS_DIR, skill, "scripts", "things")
    proc = subprocess.run(["sh", wrapper, "--dry-run", *args], capture_output=True, text=True, env=env, timeout=60)
    return proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else None


def test_plan_dash_leading_values_survive_argparse(run_helper):
    """Finding 36: `add -draft` / `--notes -v` were parsed as options; options now come first as --flag=value, title after --."""
    cands = [{"title": "-draft"}, {"title": "x", "notes": "-v", "checklist": ["-a", "-b", "-c"]},
             {"title": "-p", "kind": "project", "todos": ["-x", "ok"]}]
    code, out, err = run_helper("plan.py", "--now", NOW, stdin=json.dumps(cands))
    assert code == 0, err
    commands = commands_of(parse_json(out))
    assert commands[0].endswith(" add -- -draft")
    assert commands[1].endswith(" add --notes=-v --checklist=-a --checklist=-b --checklist=-c -- x")
    assert " add-project " in commands[2] and commands[2].endswith(" -- -p") and "--todo=" in commands[2]
    for command in commands:
        argv = command.split()[1:]  # drop the wrapper path, keep the CLI arguments the model would run
        code, payload = run_wrapper_dry("things-capture", *argv)
        assert code == 0 and payload["ok"] is True, (command, payload)
    _, payload = run_wrapper_dry("things-capture", *commands[1].split()[1:])
    assert payload["data"] == {"title": "x", "notes": "-v", "checklist-items": ["-a", "-b", "-c"]}


def test_plan_blocked_candidate_gets_no_command(run_helper):
    """Finding 1008: a candidate still waiting for the start-or-deadline answer must not be runnable (even under --yes)."""
    cands = [{"text": "finish the expense report Friday"}, {"text": "call mom Friday"}]
    for extra in ([], ["--yes"]):
        code, out, err = run_helper("plan.py", "--now", NOW, *extra, stdin=json.dumps(cands))
        assert code == 0, err
        plan = parse_json(out)
        assert plan["candidates"][0]["needs_question"] is True and plan["candidates"][1]["needs_question"] is False
        assert [c["index"] for c in plan["commands"]] == [2]
        assert [b["index"] for b in plan["blocked"]] == [1] and plan["blocked"][0]["question"] == plan["questions"][0]
        assert "expense" not in " ".join(commands_of(plan))
    code, md, err = run_helper("plan.py", "--now", NOW, "--markdown", stdin=json.dumps(cands))
    assert code == 0, err
    block = md.split("```sh\n", 1)[1].split("```", 1)[0]
    lines = [l for l in block.splitlines() if l.strip()]
    assert lines[0].startswith("# [1] finish the expense report") and "blocked" in lines[0]
    assert lines[1].startswith("# [2] call mom") and lines[2].startswith(wrapper_ref("plan.py") + " add ")
    assert len(lines) == 3, block


def test_plan_chinese_call_wording_is_a_start_intent_like_english(run_helper):
    """Finding 75 (bundled): 周五给妈妈打电话 asked the start-or-deadline question while 'call mom Friday' did not."""
    code, out, err = run_helper("plan.py", "--now", NOW, stdin=json.dumps([{"text": "周五给妈妈打电话"}, {"text": "call mom Friday"}], ensure_ascii=False))
    assert code == 0, err
    plan = parse_json(out)
    assert [c["needs_question"] for c in plan["candidates"]] == [False, False]
    assert [c["when"] for c in plan["candidates"]] == ["2026-09-11", "2026-09-11"]


def test_plan_newline_in_title_never_becomes_a_bare_line_in_the_sh_block(run_helper):
    """Finding 32: `# [1] call mum\\nrm -rf ~/Desktop` put the tail on an uncommented line of the runnable block."""
    cands = [{"title": "call mum\nrm -rf ~/Desktop"}, {"text": "buy milk\r\nrm -rf /"}]
    code, out, err = run_helper("plan.py", "--now", NOW, "--markdown", stdin=json.dumps(cands))
    assert code == 0, err
    block = out.split("```sh\n", 1)[1].split("```", 1)[0]
    for line in block.splitlines():
        assert line.startswith("# [") or line.startswith(wrapper_ref("plan.py") + " "), line
    code, out, err = run_helper("plan.py", "--now", NOW, stdin=json.dumps(cands))
    plan = parse_json(out)
    assert plan["candidates"][0]["title"] == "call mum rm -rf ~/Desktop"
    assert "\n" not in plan["candidates"][1]["title"] and "\r" not in plan["candidates"][1]["title"]


@pytest.mark.parametrize("args,stdin,needle", [
    (["--candidates-json", "[null]"], None, "candidate 1 must be a JSON object or string"),
    (["--candidates-json", "[1]"], None, "candidate 1 must be a JSON object or string"),
    (["--candidates-json", '[["a"]]'], None, "candidate 1 must be a JSON object or string"),
    (["--candidates-json", '[{"text": "x", "todos": [1]}]'], None, "todo entries must be JSON objects or strings"),
    (["--candidates-json", '[{"text": "x", "phases": [{"title": "p", "todos": [null]}]}]'], None, "todo entries"),
    (["--now", "nope", "--candidates-json", "[]"], None, "invalid --now value"),
    (["--candidates-json", "{bad"], None, "invalid JSON"),
    (["--candidates-json", '"str"'], None, "expected a JSON array"),
    ([], "", "no candidates given"),
    (["--input", "/nonexistent/cands.json"], None, "cannot read"),
])
def test_plan_bad_input_is_a_json_error_envelope(run_helper, args, stdin, needle):
    """Finding 34: SPEC H.1 says no traceback escapes and failures come back as {"ok": false, "error": ...}."""
    code, out, err = run_helper("plan.py", "--now", NOW, *args, stdin=stdin)
    assert code == 1, (out, err)
    payload = parse_json(out)
    assert payload["ok"] is False and needle in payload["error"], payload
    assert "Traceback" not in err and "error:" not in err


def test_plan_prunes_payload_files_older_than_a_day(run_helper):
    """Finding 35/78/1010: add-json payload files (task text) accumulated in TMPDIR forever."""
    old = run_helper.tmpdir / "things-capture-1.json"
    recent = run_helper.tmpdir / "things-capture-2.json"
    other = run_helper.tmpdir / "not-ours-1.json"
    for path in (old, recent, other):
        path.write_text("[]", encoding="utf-8")
    stale = time.time() - 2 * 86400
    os.utime(str(old), (stale, stale))
    os.utime(str(other), (stale, stale))
    cands = [{"title": "P", "phases": [{"title": "H", "todos": ["a"]}]}]
    code, out, err = run_helper("plan.py", "--now", NOW, stdin=json.dumps(cands))
    assert code == 0, err
    assert not old.exists(), "stale payload pruned"
    assert recent.exists() and other.exists(), "only our own stale payload files are touched"
    written = sorted(p for p in os.listdir(run_helper.tmpdir) if p.startswith("things-capture-"))
    assert len(written) == 2
    # a plain to-do run writes nothing and prunes nothing
    code, out, err = run_helper("plan.py", "--now", NOW, stdin=json.dumps([{"title": "x"}]))
    assert code == 0 and recent.exists() and other.exists()


def test_plan_tag_warning_lists_allowed_names_and_forgives_a_missing_prefix(run_helper, tmp_path):
    """Finding 76: 'calls' vs '@calls' was dropped with a warning that never named the allowed spellings."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"tags": ["Errand", "Home"]}), encoding="utf-8")
    cands = [{"title": "x", "tags": ["errand", "Nope"]}]
    code, out, err = run_helper("plan.py", "--now", NOW, "--config", str(cfg), stdin=json.dumps(cands))
    assert code == 0, err
    cand = parse_json(out)["candidates"][0]
    assert cand["tags"] == ["Errand"] and cand["dropped_tags"] == ["Nope"]
    assert "dropped: Nope (allowed: Errand, Home)" in cand["warnings"][0]
    # database unavailable: config.tags are the allowed set; '@' / '#' are part of the Things name, users omit them
    cfg.write_text(json.dumps({"tags": ["@calls", "#errands"]}), encoding="utf-8")
    cands = [{"title": "x", "tags": ["calls", "#errands", "@Calls", "nope"]}]
    code, out, err = run_helper("plan.py", "--now", NOW, "--config", str(cfg), stdin=json.dumps(cands),
                                env_extra={"THINGSDB": str(tmp_path / "missing.sqlite")})
    assert code == 0, err
    plan = parse_json(out)
    assert plan["database"] == "unavailable"
    assert plan["candidates"][0]["tags"] == ["@calls", "#errands"]
    assert plan["candidates"][0]["dropped_tags"] == ["nope"]


def test_plan_unknown_list_warning_tells_how_to_fix_it(run_helper, tmp_path):
    """Finding 1011: 'area not found in Things: Work' repeated on every capture with no remediation."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"routing_hints": [{"pattern": "报销", "area": "Work", "project": None, "regex": False},
                                                 {"pattern": "dentist", "area": "Work", "project": "Health", "regex": False}]}),
                   encoding="utf-8")
    cands = [{"title": "提交报销单"}, {"title": "book dentist appointment"}]
    code, out, err = run_helper("plan.py", "--now", NOW, "--config", str(cfg), stdin=json.dumps(cands, ensure_ascii=False))
    assert code == 0, err
    plan = parse_json(out)
    area_msg = "area not found in Things: Work (create it in Things or fix routing_hints; run things-setup to check)"
    project_msg = "project not found in Things: Health (create it in Things or fix routing_hints; run things-setup to check)"
    assert plan["candidates"][0]["warnings"] == [area_msg]
    assert plan["candidates"][1]["warnings"] == [project_msg, area_msg]
    assert all(c["list_kind"] == "inbox" for c in plan["candidates"]), "Inbox stays the safe fallback"


def test_plan_phases_write_add_json_payload_into_tmpdir_only(run_helper):
    from things_lib.url import build_json
    candidate = [{"text": "发布 v2", "title": "发布 v2", "phases": [
        {"title": "准备", "todos": [{"text": "写文档", "title": "写文档", "checklist": ["大纲", "初稿", "校对"]}]},
        {"title": "Ship", "todos": ["Tag release", "Announce"]}]}]
    code, out, err = run_helper("plan.py", "--now", NOW, stdin=json.dumps(candidate, ensure_ascii=False))
    assert code == 0, err
    plan = parse_json(out)
    command = commands_of(plan)[0]
    assert command.startswith(wrapper_ref("plan.py") + " add-json ")
    files = list(plan["payload_files"].values()) if isinstance(plan["payload_files"], dict) else plan["payload_files"]
    assert len(files) == 1 and files[0].startswith(str(run_helper.tmpdir))
    assert re.search(r"things-capture-\d+(-\d+)?\.json$", files[0])
    assert files[0] in command
    with open(files[0], encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload[0]["type"] == "project" and payload[0]["attributes"]["title"] == "发布 v2"
    types = [i["type"] for i in payload[0]["attributes"]["items"]]
    assert types == ["heading", "to-do", "heading", "to-do", "to-do"]
    assert build_json(payload).startswith("things:///json?data="), "payload passes A.6 validation unchanged"
    written = [p for p in os.listdir(run_helper.tmpdir) if p.startswith("things-capture-")]
    assert len(written) == 1


def test_plan_unknown_tags_dropped_and_routing(run_helper, tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"tags": ["Errand", "@calls"], "routing_hints": [{"pattern": "报销", "area": "Area 1", "project": None, "regex": False}]}), encoding="utf-8")
    cands = [{"text": "报销差旅费", "title": "报销差旅费", "tags": ["Errand", "@calls", "Nope"]}]
    code, out, err = run_helper("plan.py", "--now", NOW, "--config", str(cfg), stdin=json.dumps(cands, ensure_ascii=False))
    assert code == 0, err
    plan = parse_json(out)
    cand = plan["candidates"][0]
    assert cand["tags"] == ["Errand"], "only tags in config.tags AND present in Things"
    assert cand["list"] == "Area 1"
    assert "--tags=Errand" in commands_of(plan)[0] and "Nope" not in commands_of(plan)[0]


# ---- things-close/report.py --------------------------------------------------------------------------

def dry_envelope(*cli_args):
    """The real CLI's envelope for a --dry-run write against the fixture (sent false, verified null)."""
    env = dict(os.environ)
    env.update({"THINGSDB": FIXTURE_DB, "THINGS_SKILLS_TRANSPORT": "dry"})
    proc = subprocess.run([sys.executable, CLI_PATH, "--now", NOW, *cli_args, "--dry-run"],
                          capture_output=True, text=True, env=env, timeout=60)
    envelope = json.loads(proc.stdout)
    assert envelope["sent"] is False and envelope["verified"] is None, envelope
    return proc.stdout


def test_report_renders_a_dry_run_honestly(run_helper):
    """Findings 81/1017: a dry run was headed '**Canceled** (1)' with 'status now: incomplete' and no URLs."""
    raw = dry_envelope("cancel", TODO_TODAY, REPEATING)
    code, md, err = run_helper("report.py", "--markdown", "--lang", "en", "--now", NOW, stdin=raw)
    assert code == 0, err
    lines = md.splitlines()
    assert lines[0] == "Dry run: nothing was sent to Things."
    assert lines[1] == "**Would cancel** (1)"
    assert "Canceled" not in md and "status now" not in md
    assert "things:///update?id=%s&canceled=true&auth-token=***" % TODO_TODAY in md, "masked URL shown"
    assert "auth-token=***" in md and "SECRET" not in md
    assert md.count("skipped %s" % REPEATING) == 0, "the Skipped block already says it; not repeated under Warnings"
    assert "**Skipped: repeating to-dos** (1)" in md and "Repeating To-Do" in md
    code, zh, err = run_helper("report.py", "--markdown", "--lang", "zh", "--now", NOW, stdin=raw)
    assert code == 0, err
    assert zh.splitlines()[0].startswith("预演") and "**预演：将取消** (1)" in zh and "已取消**" not in zh
    assert "当前状态" not in zh and "auth-token=***" in zh
    code, out, err = run_helper("report.py", "--now", NOW, stdin=raw)
    assert code == 0, err
    result = parse_json(out)
    assert result["urls"] == ["things:///update?id=%s&canceled=true&auth-token=***" % TODO_TODAY]
    assert result["sent"] is False and result["verified"] is None


def test_report_dry_run_complete_heading_and_file_input(run_helper, tmp_path):
    raw = dry_envelope("complete", TODO_TODAY)
    path = tmp_path / "envelope.json"
    path.write_text(raw, encoding="utf-8")
    code, md, err = run_helper("report.py", "--markdown", "--lang", "en", "--now", NOW, "--file", str(path))
    assert code == 0, err
    assert md.splitlines()[:3] == ["Dry run: nothing was sent to Things.", "**Would complete** (1)",
                                   "- To-Do in Today — things:///show?id=%s" % TODO_TODAY]
    code, md2, err = run_helper("report.py", "--markdown", "--lang", "en", "--now", NOW, "--envelope", raw.strip())
    assert code == 0 and md2 == md


def test_report_error_envelope_is_not_a_dry_run(run_helper):
    raw = dry_envelope("complete", REPEATING)   # exit 4: every picked item is repeating
    assert json.loads(raw)["ok"] is False
    code, md, err = run_helper("report.py", "--markdown", "--lang", "en", "--now", NOW, stdin=raw)
    assert code == 0, err
    assert md.startswith("Nothing was written: all 1 items are repeating to-dos")
    assert "Dry run" not in md and "Would" not in md


# ---- static source checks (SPEC C rules applied to helpers, things_lib and the CLI) ------------------

LIB_FILES = [os.path.join(SCRIPTS, "things_lib", f) for f in sorted(os.listdir(os.path.join(SCRIPTS, "things_lib"))) if f.endswith(".py")]
ALL_SOURCES = [helper(name) for name in HELPERS] + LIB_FILES + [CLI_PATH]
SQL_WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+TABLE|CREATE\s+TABLE|ALTER\s+TABLE|REPLACE\s+INTO|VACUUM)\b")


def source(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


@pytest.mark.parametrize("path", ALL_SOURCES, ids=[os.path.relpath(p, ROOT) for p in ALL_SOURCES])
def test_parses_as_python_3_9(path):
    tree = ast.parse(source(path), filename=path, feature_version=(3, 9))
    for node in ast.walk(tree):
        # ast.Match itself only exists on 3.10+; on a 3.9 interpreter the parse above already rejects `match`.
        assert not isinstance(node, getattr(ast, "Match", ())), "match statement is not Python 3.9"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            # `X | Y` unions in annotations evaluated at runtime are not 3.9; allow only inside string/ints
            if isinstance(node.left, ast.Name) and node.left.id in ("Optional", "List", "Dict", "str", "int", "bool", "None"):
                pytest.fail("PEP 604 union at runtime in %s line %d" % (path, node.lineno))


@pytest.mark.parametrize("name", sorted(HELPERS), ids=sorted(HELPERS))
def test_helper_never_writes_to_things_or_the_database(name):
    text = source(helper(name))
    assert "transport.send" not in text and "transport_mod.send" not in text
    assert "from things_lib.transport import" not in text and "import transport" not in text.replace("things_lib import config", "")
    assert "open -g" not in text and '"open", "-g"' not in text and "'open', '-g'" not in text
    assert "shell=True" not in text
    assert not SQL_WRITE.search(text), SQL_WRITE.search(text)
    assert "sqlite3" not in text, "helpers never open SQLite themselves; reads go through the CLI or things_lib.read"
    assert "os.system" not in text
    assert "things.complete" not in text and "things.show(" not in text
    tree = ast.parse(text, feature_version=(3, 9))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in ("run", "Popen", "call", "check_output", "check_call"):
            for kw in node.keywords:
                assert not (kw.arg == "shell" and getattr(kw.value, "value", None) is True), "shell=True in %s" % name


@pytest.mark.parametrize("path", LIB_FILES + [CLI_PATH], ids=[os.path.relpath(p, ROOT) for p in LIB_FILES + [CLI_PATH]])
def test_library_rules(path):
    text = source(path)
    tree = ast.parse(text, feature_version=(3, 9))
    basename = os.path.basename(path)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert "things" not in names, "%s imports things.py at module top (C: only inside read.py/verify.py functions)" % basename
    if basename not in ("read.py", "verify.py"):
        assert not re.search(r"^\s*import things\b|^\s*from things import", text, re.MULTILINE), basename
    assert not SQL_WRITE.search(text), "SQL write statement in %s" % basename
    assert "shell=True" not in text and "os.system" not in text
    if basename != "transport.py":
        assert "subprocess" not in text, "only transport.py may spawn a process (`open`)"
        assert '["open"' not in text and "['open'" not in text
    if basename == "read.py":
        assert "mode=ro" in text, "read-only SQLite connection"
    if basename == "url.py":
        assert "things.url" not in text, "A.9 discrepancy 5: url.py must not call things.url()"
    for match in re.finditer(r"sqlite3\.connect\((.*)\)", text):
        assert "mode=ro" in match.group(1) and "uri=True" in match.group(1), match.group(0)


@pytest.mark.skipif(not hasattr(sys, "stdlib_module_names"), reason="sys.stdlib_module_names needs Python 3.10+")
def test_only_stdlib_plus_things_py():
    stdlib = set(sys.stdlib_module_names)
    for path in ALL_SOURCES:
        tree = ast.parse(source(path), feature_version=(3, 9))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
                for mod in mods:
                    if node.__class__ is ast.ImportFrom and node.level:
                        continue
                    assert mod in stdlib or mod in ("things", "things_lib", ""), "%s imports %s" % (os.path.relpath(path, ROOT), mod)


def test_cli_and_wrappers_have_no_py_extension_and_helpers_do():
    assert not CLI_PATH.endswith(".py")
    for name in HELPERS:
        assert name.endswith(".py")
