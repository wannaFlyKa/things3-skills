"""SKILL.md and wrapper contract tests written from SPEC.md section H (H.1 shared shape, H.2 per skill)."""

import importlib.machinery
import importlib.util
import json
import os
import platform
import re
import shlex
import subprocess
import sys

import pytest

from conftest import CLI_PATH, ROOT

SKILLS_DIR = os.path.join(ROOT, "plugins", "things", "skills")
SKILLS = ["things-setup", "things-capture", "things-close", "things-organize", "things-deadlines", "things-today"]
# Finding 1019: the gate is a script. An inline `!`[ ... ] || { echo ...; exit 1; }`` fails Claude Code's injected-command
# permission check in default mode ("Contains brace with quote character"), which aborted every skill with no output.
GATE_LINE = "!`${CLAUDE_SKILL_DIR}/scripts/osgate`"
OSGATE_SENTENCE = "Things skills run only on macOS"
SKILL_DIR_VAR = "${CLAUDE_SKILL_DIR}"
WRITE_SUBCOMMANDS = ["add", "add-project", "add-json", "update", "complete", "cancel", "schedule", "deadline", "tag", "move"]
READ_ONLY_SKILLS = ["things-setup", "things-today"]


def bash_rules(*args):
    """Expected allowed-tools rules: a helper gets its bare and `*` forms, a read subcommand the forms listed."""
    return ["Bash(%s/scripts/%s)" % (SKILL_DIR_VAR, item) for item in args]


# Finding 58: per-skill rules cover ONLY that skill's helpers and the read subcommands its body uses. Write subcommands
# fall through to the normal permission prompt in every skill, including the four that write.
EXPECTED_ALLOWED_TOOLS = {
    "things-setup": bash_rules("osgate", "setup_check.py", "setup_check.py *", "things doctor", "things doctor *",
                               "things ping", "things ping *"),
    "things-today": bash_rules("osgate", "brief.py", "brief.py *", "things today", "things today *", "things overdue",
                               "things overdue *", "things deadlines", "things deadlines *", "things inbox", "things inbox *"),
    "things-capture": bash_rules("osgate", "plan.py", "plan.py *", "things search *"),
    "things-close": bash_rules("osgate", "candidates.py", "candidates.py *", "report.py", "report.py *", "things search *",
                               "things get *"),
    "things-organize": bash_rules("osgate", "review.py", "review.py *", "things get *", "things search *"),
    "things-deadlines": bash_rules("osgate", "ddl_report.py", "ddl_report.py *", "things parse-date *", "things search *"),
}
WRAPPER = (
    "#!/bin/sh\n"
    "# Wrapper: forwards to the shared CLI at plugins/things/scripts/things\n"
    'here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
    'exec python3 "$here/../../../scripts/things" "$@"\n'
)
TRIGGERS = {
    "things-setup": ["set up Things", "check Things", "things doctor", "配置 Things", "检查 Things", "Things 设置"],
    "things-capture": ["add to Things", "capture", "new to-do", "remind me to", "记到 Things", "添加任务", "新建待办",
                       "帮我记一下", "直接建"],
    "things-close": ["done with", "finished", "mark complete", "close", "完成了", "关掉", "搞定了", "取消"],
    "things-organize": ["weekly review", "organize Things", "inbox zero", "clean up my tasks", "整理", "周回顾",
                        "清空收件箱", "整理 Things"],
    "things-deadlines": ["deadlines", "overdue", "due this week", "push deadline", "DDL", "逾期", "本周到期", "推后三天",
                         "截止日期"],
    "things-today": ["morning brief", "what's on today", "today's plan", "今天要做什么", "今日安排", "早报"],
}
CJK = re.compile(r"[一-鿿]")


def skill_path(name):
    return os.path.join(SKILLS_DIR, name, "SKILL.md")


def read_skill(name):
    with open(skill_path(name), encoding="utf-8") as handle:
        return handle.read()


def split_frontmatter(text):
    """Return (ordered list of (key, value), body_lines). Frontmatter = lines between the first two '---' lines."""
    lines = text.split("\n")
    assert lines[0] == "---", "SKILL.md must start with a frontmatter fence"
    end = lines.index("---", 1)
    pairs = []
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        assert sep == ":", "frontmatter line without a key: %r" % line
        pairs.append((key.strip(), value.strip()))
    return pairs, lines[end + 1:]


def split_allowed_tools(value):
    """Claude Code splits allowed-tools on spaces or commas outside parentheses (binary 2.1.266, function `td`)."""
    rules, current, depth = [], "", 0
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char in " ," and depth == 0:
            if current.strip():
                rules.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        rules.append(current.strip())
    return rules


def bash_rule_matches(rule, command, skill_dir="/x/skills/s"):
    """Claude Code Bash rule semantics: `Bash(p *)` is a prefix on `p `, `Bash(p)` an exact match; ${CLAUDE_SKILL_DIR} substituted."""
    inner = rule[len("Bash("):-1].replace(SKILL_DIR_VAR, skill_dir)
    if inner.endswith(" *"):
        prefix = inner[:-2]
        return command == prefix or command.startswith(prefix + " ")
    return command == inner


@pytest.mark.parametrize("name", SKILLS)
def test_frontmatter_has_exactly_name_description_allowed_tools(name):
    pairs, _ = split_frontmatter(read_skill(name))
    assert [key for key, _ in pairs] == ["name", "description", "allowed-tools"]
    values = dict(pairs)
    assert values["name"] == name
    assert split_allowed_tools(values["allowed-tools"]) == EXPECTED_ALLOWED_TOOLS[name]


@pytest.mark.parametrize("name", SKILLS)
def test_allowed_tools_never_pre_approve_a_write_subcommand(name):
    """Finding 58: `Bash(${CLAUDE_SKILL_DIR}/scripts/*)` pre-approved complete/cancel/update/... in every skill, even the
    read-only ones, so the preview-then-confirm model was enforced by prose alone."""
    rules = split_allowed_tools(dict(split_frontmatter(read_skill(name))[0])["allowed-tools"])
    skill_dir = "/x/skills/" + name
    for rule in rules:
        assert rule.startswith("Bash(%s/scripts/" % SKILL_DIR_VAR) and rule.endswith(")"), rule
        assert "/scripts/*" not in rule and "/scripts/things *" not in rule and "/scripts/things)" not in rule, rule
    for sub in WRITE_SUBCOMMANDS:
        for command in ("%s/scripts/things %s" % (skill_dir, sub), "%s/scripts/things %s ID1 ID2" % (skill_dir, sub),
                        "%s/scripts/things %s --dry-run ID1" % (skill_dir, sub), "%s/scripts/things --dry-run %s ID1" % (skill_dir, sub)):
            assert not any(bash_rule_matches(r, command, skill_dir) for r in rules), (name, command)
    assert bash_rule_matches(rules[0], skill_dir + "/scripts/osgate", skill_dir), "the gate script itself is pre-approved"
    if name in READ_ONLY_SKILLS:
        # every things subcommand a read-only skill may run is a read
        for rule in rules:
            match = re.search(r"/scripts/things ([a-z-]+)", rule)
            if match:
                assert match.group(1) not in WRITE_SUBCOMMANDS, rule


@pytest.mark.parametrize("name", SKILLS)
def test_body_invocations_are_covered_by_allowed_tools_except_writes(name):
    """Every `${CLAUDE_SKILL_DIR}/scripts/...` line the body tells the model to run matches a rule, unless it is a write
    (which must hit the permission prompt); helpers named in the body have a rule."""
    text = read_skill(name)
    rules = split_allowed_tools(dict(split_frontmatter(text)[0])["allowed-tools"])
    skill_dir = "/x/skills/" + name
    body = "\n".join(split_frontmatter(text)[1])
    for match in re.finditer(r"\$\{CLAUDE_SKILL_DIR\}/scripts/(things [a-z-]+|[A-Za-z0-9_]+\.py)\b", body):
        command = skill_dir + "/scripts/" + match.group(1)
        sub = match.group(1).split()[1] if match.group(1).startswith("things ") else None
        covered = any(bash_rule_matches(r, command, skill_dir) for r in rules)
        if sub in WRITE_SUBCOMMANDS:
            assert not covered, (name, command)
        elif sub is None or name in READ_ONLY_SKILLS:
            assert covered, "%s: %r is neither pre-approved nor a write" % (name, command)


@pytest.mark.parametrize("name", SKILLS)
def test_description_is_bilingual_and_contains_every_h2_trigger(name):
    pairs, _ = split_frontmatter(read_skill(name))
    description = dict(pairs)["description"]
    assert CJK.search(description), "description needs Chinese trigger phrases"
    assert re.search(r"[A-Za-z]", description), "description needs English trigger phrases"
    missing = [phrase for phrase in TRIGGERS[name] if phrase not in description]
    assert missing == [], "missing trigger phrases: %r" % missing
    assert not description.startswith(("'", '"')), "description must be a plain YAML scalar"


@pytest.mark.parametrize("name", SKILLS)
def test_first_body_line_is_the_macos_gate_byte_exact(name):
    _, body = split_frontmatter(read_skill(name))
    assert body[0] == GATE_LINE
    raw = open(skill_path(name), "rb").read()
    assert GATE_LINE.encode("utf-8") in raw
    assert b"\r\n" not in raw, "SKILL.md must use LF line endings"
    assert raw.count(GATE_LINE.encode("utf-8")) == 1
    # the inline form must never come back: it fails the injected-command permission check in default mode
    assert b"exit 1; }" not in raw and b'[ "$(uname)"' not in raw, "inline shell gate is not allowed in SKILL.md"


@pytest.mark.parametrize("name", SKILLS)
def test_body_explains_codex_runtime_path_resolution(name):
    text = read_skill(name)
    assert "In Codex, resolve it to the" in text
    assert "absolute directory containing this `SKILL.md`" in text
    assert "run `scripts/osgate`" in text


def osgate_path(name):
    return os.path.join(SKILLS_DIR, name, "scripts", "osgate")


@pytest.mark.parametrize("name", SKILLS)
def test_osgate_exists_is_executable_and_always_exits_zero(name, tmp_path):
    """Finding 1019/25: the gate is context injection. A non-zero exit aborts the skill silently, so osgate must exit 0
    on every platform and make the printed sentence itself tell the model what to do. Both branches are driven through
    a fake `uname` on PATH so the test itself passes on macOS and on Linux CI (finding 2024)."""
    path = osgate_path(name)
    assert os.path.isfile(path) and not os.path.islink(path)
    mode = os.stat(path).st_mode
    assert mode & 0o111 == 0o111, "osgate must be executable for user, group and other"
    assert not mode & 0o002, "osgate must not be world writable"   # a umask-002 clone (0775) stays legal
    with open(path, "rb") as handle:
        content = handle.read()
    assert content.startswith(b"#!/bin/sh\n") and b"\r\n" not in content
    assert content.rstrip().endswith(b"exit 0"), "an exit 1 aborts the skill with no message to the user"
    assert b"exit 1" not in content
    # run as-is through the shebang: exit 0 everywhere; silent only where uname really says Darwin
    proc = subprocess.run([path], capture_output=True, text=True, timeout=30, cwd=str(tmp_path))
    assert proc.returncode == 0 and proc.stderr == "", proc
    if platform.system() == "Darwin":
        assert proc.stdout == "", proc
    else:
        assert proc.stdout.startswith(OSGATE_SENTENCE), proc
    # macOS (uname faked through PATH): silent, exit 0
    fake = tmp_path / "bin"
    fake.mkdir()
    uname = fake / "uname"
    uname.write_text("#!/bin/sh\necho Darwin\n", encoding="utf-8")
    uname.chmod(0o755)
    env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ.get("PATH", ""))
    proc = subprocess.run(["sh", path], capture_output=True, text=True, timeout=30, cwd=str(tmp_path), env=env)
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == "", proc
    # anywhere else: the sentence, still exit 0
    uname.write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
    proc = subprocess.run(["sh", path], capture_output=True, text=True, timeout=30, cwd=str(tmp_path), env=env)
    assert proc.returncode == 0, proc
    assert proc.stdout.startswith(OSGATE_SENTENCE) and "stop" in proc.stdout and proc.stdout.count("\n") == 1


def test_all_six_osgates_are_byte_identical():
    contents = {name: open(osgate_path(name), "rb").read() for name in SKILLS}
    assert len(set(contents.values())) == 1


@pytest.mark.parametrize("name", SKILLS)
def test_body_tells_the_model_what_the_gate_sentence_means(name):
    """Finding 25: the sentence only appears off-macOS; the body (or the sentence itself) must say: stop."""
    text = read_skill(name)
    sentence = open(osgate_path(name), encoding="utf-8").read()
    assert "tell the user this plugin needs a Mac and stop" in sentence
    if name not in ("things-capture", "things-close"):   # bodies owned by another lane; the sentence covers them
        assert "Things skills run only on macOS" in text.split("\n", 6)[6], "body must reference the gate sentence"
        assert "needs a Mac and stop" in text
    assert "already stopped" not in text


@pytest.mark.parametrize("name", SKILLS)
def test_under_120_lines_and_utf8(name):
    text = read_skill(name)
    assert text.count("\n") < 120
    assert len(text.split("\n")) < 120
    open(skill_path(name), "rb").read().decode("utf-8")  # strict UTF-8


@pytest.mark.parametrize("name", SKILLS)
def test_wrapper_is_a_real_executable_file_with_exact_content(name):
    """Finding 51: git keeps only the executable bit, so a umask-002 clone yields 0775; assert x bits, not 0755."""
    path = os.path.join(SKILLS_DIR, name, "scripts", "things")
    assert os.path.lexists(path), "wrapper missing"
    assert not os.path.islink(path), "wrapper must be a real file, not a symlink"
    assert os.path.isfile(path)
    mode = os.stat(path).st_mode
    assert mode & 0o111 == 0o111, "wrapper must be executable for user, group and other"
    assert not mode & 0o002, "wrapper must not be world writable"   # a umask-002 clone (0775) stays legal
    with open(path, "rb") as handle:
        assert handle.read() == WRAPPER.encode("utf-8")


def test_all_six_wrappers_are_byte_identical():
    contents = {name: open(os.path.join(SKILLS_DIR, name, "scripts", "things"), "rb").read() for name in SKILLS}
    assert len(set(contents.values())) == 1
    assert set(SKILLS) == {d for d in os.listdir(SKILLS_DIR) if os.path.isdir(os.path.join(SKILLS_DIR, d))}, \
        "exactly the six skills, no extras"


@pytest.mark.parametrize("name", SKILLS)
def test_wrapper_runs_doctor_on_this_box(name, tmp_path):
    wrapper = os.path.join(SKILLS_DIR, name, "scripts", "things")
    proc = subprocess.run([wrapper, "doctor"], capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True and payload["command"] == "doctor"
    assert payload["data"]["database"]["status"] == "fixture"
    assert payload["data"]["cli_version"] == "0.2.0"
    assert "Traceback" not in proc.stderr


def test_wrapper_runs_via_sh_from_another_cwd_and_forwards_arguments(tmp_path):
    wrapper = os.path.join(SKILLS_DIR, "things-today", "scripts", "things")
    proc = subprocess.run(["sh", wrapper, "--dry-run", "add", "买 牛奶/测试"], capture_output=True, text=True,
                          timeout=60, cwd="/")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["urls"] == ["things:///add?title=%E4%B9%B0%20%E7%89%9B%E5%A5%B6%2F%E6%B5%8B%E8%AF%95"]


# ---- H.1: CLI resolution and protocol wording -------------------------------------------------------

@pytest.mark.parametrize("name", SKILLS)
def test_cli_is_invoked_only_through_claude_skill_dir(name):
    text = read_skill(name)
    for match in re.finditer(r"scripts/things\b", text):
        prefix = text[max(0, match.start() - len("${CLAUDE_SKILL_DIR}/")):match.start()]
        assert prefix == "${CLAUDE_SKILL_DIR}/", "bare CLI path at offset %d: %r" % (match.start(), text[match.start() - 30:match.end() + 10])
    assert "plugins/things/scripts/things" not in text
    assert "python3 plugins" not in text and "python3 scripts" not in text
    assert "${CLAUDE_SKILL_DIR}/scripts/things" in text


@pytest.mark.parametrize("name", SKILLS)
def test_helpers_referenced_by_skill_exist_and_are_executable(name):
    text = read_skill(name)
    helpers = set(re.findall(r"\$\{CLAUDE_SKILL_DIR\}/scripts/([A-Za-z0-9_]+\.py)", text))
    for helper in helpers:
        path = os.path.join(SKILLS_DIR, name, "scripts", helper)
        assert os.path.isfile(path), helper
        assert os.stat(path).st_mode & 0o111, "%s must be executable" % helper
        with open(path, "rb") as handle:
            assert handle.readline().startswith(b"#!/usr/bin/env python3")


@pytest.mark.parametrize("name", SKILLS)
def test_every_skill_reports_links_warnings_and_never_the_token(name):
    text = read_skill(name)
    if name != "things-setup":   # the setup skill touches no items, so it has no links to print
        assert "things:///show?id=" in text
    assert "warnings" in text
    assert "token" in text.casefold(), "each skill states that it never prints or asks for the token"
    assert re.search(r"never[^.\n]*token|token[^.\n]*never", text, re.IGNORECASE)


WRITING_SKILLS = ["things-capture", "things-close", "things-organize", "things-deadlines"]


@pytest.mark.parametrize("name", WRITING_SKILLS)
def test_writing_skills_follow_preview_confirm_verify_protocol(name):
    text = read_skill(name)
    assert "verified" in text and "verify_reason" in text
    for answer in ("y", "yes", "好", "确认", "1,3", "all", "全部"):
        assert answer in text, "accepted confirmation answer %r missing" % answer


@pytest.mark.parametrize("name", ["things-close", "things-organize", "things-deadlines"])
def test_non_capture_skills_never_use_yes(name):
    text = read_skill(name)
    assert re.search(r"never[^.\n]*--yes|--yes[^.\n]*never|`--yes`[^.\n]*not", text, re.IGNORECASE), \
        "must state that --yes is never used"
    assert not re.search(r"scripts/things\s+(--yes|\S+\s+--yes)", text), "no --yes on a CLI invocation"


BODY_MUST_INCLUDE = {
    "things-setup": ["doctor", "ping", "tags", "areas", "Full Disk Access", "data.things_py.source", "bundled",
                     "/plugin update things@things3-skills", "config.example.json", "~/.config/things-skills/config.json",
                     "missing_tags", "✅", "❌", "sent", "Privacy & Security"],
    # CLI subcommands that a helper script internalises are not required as literal body text.
    "things-capture": ["add-project", "add-json", "search", "routing_hints", "config.tags",
                       "直接建", "--yes", "${TMPDIR:-/tmp}/things-capture-", "checklist", "deadline", "verb",
                       "outcome", "translate", "when"],
    "things-close": ["search", "--status open", "complete", "cancel", "data.skipped", "1,3", "all", "synonym",
                     "取消", "Today is a promise", "Inbox is for capture"],
    "things-organize": ["inbox", "today", "anytime", "someday", "stale", "deadline", "tags",
                        "move", "schedule", "deadline", "tag", "cancel", "complete", "update", "today_cap", "stale_days",
                        "deadline_lead_days", "someday_resurface_days", "evening", "Someday is a parking lot",
                        "Inbox", "Today is a promise"],
    "things-deadlines": ["Overdue", "within 7 days", "30 days", "today", "--push", "--date", "--clear",
                         "schedule", "+3d", "逾期", "本周到期", "推后三天", "deadline_lead_days", "default_reminder_time",
                         "start date", "external hard date"],
    "things-today": ["today", "overdue", "deadlines --within 7", "inbox", "repeating_hint", "today_cap",
                     "/things:things-organize today", "- [ ]", "things:///show?id=", "Today is a promise", "evening"],
}


@pytest.mark.parametrize("name", SKILLS)
def test_body_must_include_h2_items(name):
    text = read_skill(name)
    missing = [needle for needle in BODY_MUST_INCLUDE[name] if needle not in text]
    assert missing == [], "H.2 body items missing: %r" % missing


# ---- Finding 56: the command lines a SKILL.md tells the model to run must parse ----------------------

PLACEHOLDERS = [
    (re.compile(r"<id\d?>|<id1>|<id2>|ID\d"), "5pUx6PESj3ctFYbgth1PXY"),
    (re.compile(r"YYYY-MM-DD@HH:MM|YYYY-MM-DD@09:00"), "2026-01-01@09:00"),
    (re.compile(r"YYYY-MM-DD"), "2026-01-01"),
    (re.compile(r"<words>|<the user's words>|<invocation>|<scope>|<answer>|<normalised answer>|<saved path>|<json>|<that one-line JSON>|<envelope>"), "x"),
    (re.compile(r"<[^>]*>"), "x"),
]


def load_cli():
    loader = importlib.machinery.SourceFileLoader("things_cli_skills", CLI_PATH)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def skill_command_lines(name, prefix):
    """Every `${CLAUDE_SKILL_DIR}/scripts/<prefix> ...` invocation in the body, placeholders substituted."""
    _, body = split_frontmatter(read_skill(name))
    found = []
    for match in re.finditer(r"\$\{CLAUDE_SKILL_DIR\}/scripts/(%s[^`|\n]*)" % re.escape(prefix), "\n".join(body)):
        line = re.split(r"\s+(->|\()", match.group(1))[0].strip()
        for pattern, value in PLACEHOLDERS:
            line = pattern.sub(value, line)
        if line and not line.startswith("things <"):   # `things <schedule|move|...>` describes the form, it is not a call
            found.append(line)
    return found


@pytest.mark.parametrize("name", SKILLS)
def test_skill_cli_invocations_parse(name):
    cli = load_cli()
    lines = skill_command_lines(name, "things ")
    if name not in ("things-capture", "things-organize"):   # their helpers print every CLI line; the body shows none
        assert lines, "the body shows at least one CLI invocation"
    for line in lines:
        try:
            argv = [a for a in shlex.split(line) if a != "..."][1:]
        except ValueError:
            argv = [a for a in line.split() if a != "..."][1:]
        try:
            cli.build_parser().parse_args(argv)
        except (cli.CliError, SystemExit) as exc:
            pytest.fail("%s: %r does not parse: %s" % (name, line, exc))


@pytest.mark.parametrize("name", SKILLS)
def test_skill_helper_flags_exist(name):
    helpers = {}
    for line in skill_command_lines(name, ""):
        head = line.split()[0]
        if head.endswith(".py"):
            helpers.setdefault(head, set()).update(re.findall(r"(--[a-z][a-z-]*)", line))
    assert helpers, "every skill runs at least one helper"
    for helper, flags in helpers.items():
        path = os.path.join(SKILLS_DIR, name, "scripts", helper)
        proc = subprocess.run([sys.executable, path, "--help"], capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        for flag in flags:
            assert flag in proc.stdout, "%s: %s does not accept %s" % (name, helper, flag)


def test_today_skill_carries_the_b6_sentence_in_both_languages():
    """The sentence may be split across adjacent string literals in brief.py; compare with whitespace and quotes removed."""
    text = read_skill("things-today") + open(os.path.join(SKILLS_DIR, "things-today", "scripts", "brief.py"), encoding="utf-8").read()
    flat = re.sub(r'["\s]+', "", text)
    en = "Repeating to-dos may be missing: things.py only sees instances Things has already generated. Open Things once to refresh."
    zh = "重复任务可能不完整：things.py 只能看到 Things 已生成的实例，请先打开一次 Things。"
    assert re.sub(r'["\s]+', "", en) in flat and re.sub(r'["\s]+', "", zh) in flat
    assert "repeating" in read_skill("things-today").casefold()
