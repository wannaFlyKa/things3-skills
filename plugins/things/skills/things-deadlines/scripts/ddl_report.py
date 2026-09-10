#!/usr/bin/env python3
"""things-deadlines helper: deadline report, at-risk flags, backward-scheduling proposals.

Read-only. It never sends a write; it prints the exact wrapper commands the model may
run after the user confirms. Honours THINGSDB and --now for testing on Linux.

  ddl_report.py [--now YYYY-MM-DDTHH:MM] [--lang zh|en|auto] [--text INVOCATION]
                [--config PATH] [--markdown]
  ddl_report.py --push-spec "推后三天"      -> {"ok": true, "spec": "+3d", "flag": "--push=+3d", ...}
  (paste `flag` as printed: a negative offset must be written `--push=-3d`, argparse rejects `--push -3d`)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts"))
CLI = os.path.join(SCRIPTS, "things")
sys.path.insert(0, SCRIPTS)
from things_lib import config as config_mod  # noqa: E402
from things_lib.dates import detect_language  # noqa: E402

# Printed commands carry the ABSOLUTE path of the sibling wrapper: Claude Code substitutes ${CLAUDE_SKILL_DIR}
# only inside SKILL.md text, never in tool output, and HERE is exactly the substituted <skill>/scripts.
WRAPPER = os.path.join(HERE, "things")
CLI_TIMEOUT = 90

LABELS = {
    "en": {
        "report": "Deadlines report", "lead": "lead {n} days", "overdue": "Overdue",
        "today": "Due today", "week": "Due within 7 days", "month": "Due in 8-30 days",
        "none": "nothing", "no_area": "No area", "deadline": "deadline", "start": "start",
        "no_start": "no start date", "ago": "{n} days ago", "in": "in {n} days",
        "today_word": "today", "tomorrow": "tomorrow", "project": "project", "repeating": "repeating",
        "at_risk": "at risk", "in_today": "in Today", "risk_no_start": "no start date within lead time",
        "risk_start_after": "start date after deadline", "risk_overdue": "overdue, no start date",
        "proposals": "At risk ({n}): proposed backward scheduling", "n": "#", "item": "To-do",
        "risk": "Risk", "when": "Proposed when", "command": "Command",
        "reminder_hint": "Reminder variant: append @{t} to --when (for example --when {d}@{t}).",
        "repeating_hint": "Repeating to-dos cannot be scheduled by URL; change them in Things.",
        "other": "Other actions: push `{w} deadline <id> --push +3d`; set `{w} deadline <id> --date YYYY-MM-DD`; clear `{w} deadline <id> --clear`.",
        "no_risk": "No at-risk items.",
        "paren": " ({s})", "colon": ": ",
    },
    "zh": {
        "report": "截止日期报告", "lead": "提前量 {n} 天", "overdue": "逾期",
        "today": "今天到期", "week": "7 天内到期", "month": "8-30 天内到期",
        "none": "无", "no_area": "无领域", "deadline": "截止", "start": "开始",
        "no_start": "无开始日期", "ago": "已过 {n} 天", "in": "还剩 {n} 天",
        "today_word": "今天", "tomorrow": "明天", "project": "项目", "repeating": "重复任务",
        "at_risk": "有风险", "in_today": "已在今天", "risk_no_start": "临近截止但没有开始日期",
        "risk_start_after": "开始日期晚于截止日期", "risk_overdue": "已逾期且没有开始日期",
        "proposals": "有风险（{n}）：建议倒推安排开始日期", "n": "#", "item": "任务",
        "risk": "风险", "when": "建议开始", "command": "命令",
        "reminder_hint": "要提醒的话，在 --when 后加 @{t}（例如 --when {d}@{t}）。",
        "repeating_hint": "重复任务无法通过 URL 修改日期，请在 Things 里改。",
        "other": "其他操作：推后 `{w} deadline <id> --push +3d`；设定 `{w} deadline <id> --date YYYY-MM-DD`；清除 `{w} deadline <id> --clear`。",
        "no_risk": "没有有风险的任务。",
        "paren": "（{s}）", "colon": "：",
    },
}

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_EN_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
# Left word boundaries on the number AND the unit: without them 'an'+'d' matched inside 'and' / 'hand' / 'stand'.
_PUSH_RE = re.compile(
    r"([+-])?\s*(?<![a-z0-9])(\d+|[零〇一二两三四五六七八九十]+|" + "|".join(sorted(_EN_WORDS, key=len, reverse=True)) + r")"
    r"\s*(个?星期|个?礼拜|周|天|日|(?<![a-z])(?:weeks?|wks?|days?|w|d))(?![a-z])", re.IGNORECASE)
# 'push back by' is a postponement in English, so it is NOT an earlier marker.
_EARLIER_RE = re.compile(r"提前|往前|earlier|pull in|bring forward|sooner", re.IGNORECASE)


def cn_num(token: str) -> int:
    """ASCII digits, English number words or Chinese numerals (三, 十, 十二, 二十)."""
    low = token.lower()
    if low.isdigit():
        return int(low)
    if low in _EN_WORDS:
        return _EN_WORDS[low]
    total = 0
    current = 0
    for char in token:
        if char == "十":
            total += (current or 1) * 10
            current = 0
        elif char in _CN_DIGITS:
            current = current * 10 + _CN_DIGITS[char]
        else:
            raise ValueError("not a number: %s" % token)
    return total + current


def push_spec(text: str) -> Dict[str, Any]:
    """Turn '推后三天' / 'push 2 weeks' / '+3d' / '提前一周' into a --push offset."""
    raw = text.strip()
    direct = re.match(r"^([+-])(\d+)([dw])$", raw)
    if direct:
        days = int(direct.group(2)) * (7 if direct.group(3) == "w" else 1)
        return {"ok": True, "text": raw, "spec": raw, "flag": "--push=" + raw,
                "days": -days if direct.group(1) == "-" else days}
    match = _PUSH_RE.search(raw)
    if not match:
        return {"ok": False, "text": raw, "spec": None, "days": None,
                "error": "cannot read a push offset from %r; say +3d, +2w, 推后三天, push 2 weeks" % raw}
    try:
        amount = cn_num(match.group(2))
    except ValueError:
        return {"ok": False, "text": raw, "spec": None, "days": None, "error": "cannot read the number in %r" % raw}
    unit = match.group(3).lower()
    weekly = unit not in ("天", "日", "days", "day", "d")
    sign = match.group(1) or ("-" if _EARLIER_RE.search(raw) else "+")
    spec = "%s%d%s" % (sign, amount, "w" if weekly else "d")
    return {"ok": True, "text": raw, "spec": spec, "flag": "--push=" + spec,
            "days": (-1 if sign == "-" else 1) * amount * (7 if weekly else 1)}


def run_cli(args: List[str], now: str, config_path: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    """Run the shared CLI with a frozen --now; return (exit code, envelope)."""
    cmd = [sys.executable, CLI, "--now", now]
    if config_path:
        cmd += ["--config", config_path]
    cmd += args
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=CLI_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 1, {"ok": False, "command": args[0], "data": None, "warnings": [],
                   "error": "the things CLI did not answer in %d s" % CLI_TIMEOUT}
    try:
        env = json.loads(proc.stdout)
    except ValueError:
        env = {"ok": False, "command": args[0], "data": None, "warnings": [],
               "error": (proc.stderr.strip() or "CLI produced no JSON")}
    return proc.returncode, env


def fail(env: Dict[str, Any], code: int) -> None:
    print(json.dumps({"ok": False, "command": env.get("command"), "error": env.get("error") or "unknown error",
                      "exit": code, "warnings": env.get("warnings") or []}, ensure_ascii=False))
    sys.exit(code if code else 1)


def resolve_area(item: Dict[str, Any], projects: Dict[str, Dict[str, Any]], headings: Dict[str, Dict[str, Any]],
                 labels: Dict[str, str]) -> str:
    """area_title, else the parent project's area, else project_title, else 'No area'."""
    if item.get("area_title"):
        return item["area_title"]
    project_id = item.get("project")
    if not project_id and item.get("heading") in headings:
        project_id = headings[item["heading"]].get("project")
    project = projects.get(project_id or "")
    if project and project.get("area_title"):
        return project["area_title"]
    if project and project.get("title"):
        return project["title"]
    return item.get("project_title") or labels["no_area"]


def gather(now: str, config_path: Optional[str], labels: Dict[str, str]) -> Dict[str, Any]:
    """Run the reads (overdue, deadlines --within 7/30, today, projects) and merge by uuid."""
    envelopes = {}
    for name, args in (("overdue", ["overdue"]), ("week", ["deadlines", "--within", "7"]),
                       ("month", ["deadlines", "--within", "30"]), ("today", ["today"]), ("projects", ["projects"])):
        code, env = run_cli(args, now, config_path)
        if not env.get("ok"):
            fail(env, code)
        envelopes[name] = env
    warnings = []
    for env in envelopes.values():
        for w in env.get("warnings") or []:
            if w not in warnings and not w.startswith("Repeating to-dos may be missing"):
                warnings.append(w)
    projects = {p["uuid"]: p for p in envelopes["projects"]["data"]}
    in_today = {i["uuid"] for i in envelopes["today"]["data"]["items"]}
    merged: Dict[str, Dict[str, Any]] = {}
    for name in ("overdue", "week", "month"):
        for item in envelopes[name]["data"]:
            if item.get("type") not in ("to-do", "project"):
                continue
            merged.setdefault(item["uuid"], item)
    headings: Dict[str, Dict[str, Any]] = {}
    for item in merged.values():
        hid = item.get("heading")
        if hid and hid not in headings and not item.get("project"):
            code, env = run_cli(["get", hid], now, config_path)
            headings[hid] = env.get("data") or {} if env.get("ok") else {}
    for item in merged.values():
        item["area"] = resolve_area(item, projects, headings, labels)
        item["in_today"] = item["uuid"] in in_today
    return {"items": sorted(merged.values(), key=lambda i: (i.get("deadline") or "", i.get("title") or "")),
            "warnings": warnings}


def bucket(days: Optional[int]) -> Optional[str]:
    if days is None:
        return None
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days <= 7:
        return "week"
    if days <= 30:
        return "month"
    return None


def risk_of(item: Dict[str, Any], lead: int, labels: Dict[str, str]) -> Optional[str]:
    days = item.get("days_until_deadline")
    start = item.get("start_date")
    deadline = item.get("deadline")
    if start and deadline and start > deadline:
        return labels["risk_start_after"]
    if days is not None and not start:
        if days < 0:
            return labels["risk_overdue"]
        if days <= lead:
            return labels["risk_no_start"]
    return None


def compact(item: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("uuid", "type", "title", "area", "project_title", "heading_title", "start_date", "deadline",
            "days_until_deadline", "link", "repeating", "in_today", "at_risk", "risk")
    return {k: item.get(k) for k in keys}


def analyse(items: List[Dict[str, Any]], today: date, lead: int, reminder: str, labels: Dict[str, str]) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {"overdue": {}, "today": {}, "week": {}, "month": {}}
    at_risk: List[Dict[str, Any]] = []
    for item in items:
        risk = risk_of(item, lead, labels)
        item["at_risk"] = risk is not None
        item["risk"] = risk
        name = bucket(item.get("days_until_deadline"))
        if name:
            groups[name].setdefault(item["area"], []).append(compact(item))
        if risk:
            at_risk.append(compact(item))
    proposals = []
    for n, item in enumerate(at_risk, 1):
        when = max(date.fromisoformat(item["deadline"]) - timedelta(days=lead), today).isoformat()
        prop = {"n": n, "id": item["uuid"], "title": item["title"], "deadline": item["deadline"],
                "start_date": item["start_date"], "risk": item["risk"], "repeating": bool(item["repeating"]),
                "when": when, "when_with_reminder": "%s@%s" % (when, reminder),
                "command": None, "command_with_reminder": None, "link": item["link"]}
        if not item["repeating"]:
            prop["command"] = "%s schedule %s --when %s" % (WRAPPER, item["uuid"], when)
            prop["command_with_reminder"] = "%s schedule %s --when %s@%s" % (WRAPPER, item["uuid"], when, reminder)
        proposals.append(prop)
    ordered = {name: [{"area": area, "items": rows} for area, rows in sorted(areas.items())]
               for name, areas in groups.items()}
    counts = {name: sum(len(a["items"]) for a in areas) for name, areas in ordered.items()}
    counts["at_risk"] = len(at_risk)
    return {"groups": ordered, "counts": counts, "at_risk": at_risk, "proposals": proposals}


def fmt_item(item: Dict[str, Any], labels: Dict[str, str]) -> str:
    days = item.get("days_until_deadline")
    if days is None:
        rel = ""
    elif days < 0:
        rel = labels["paren"].format(s=labels["ago"].format(n=-days))
    elif days == 0:
        rel = labels["paren"].format(s=labels["today_word"])
    elif days == 1:
        rel = labels["paren"].format(s=labels["tomorrow"])
    else:
        rel = labels["paren"].format(s=labels["in"].format(n=days))
    parts = ["%s %s%s" % (labels["deadline"], item.get("deadline"), rel),
             "%s %s" % (labels["start"], item["start_date"]) if item.get("start_date") else labels["no_start"]]
    if item.get("project_title"):
        parts.append("%s %s" % (labels["project"], item["project_title"]))
    if item.get("repeating"):
        parts.append(labels["repeating"])
    if item.get("in_today"):
        parts.append(labels["in_today"])
    if item.get("at_risk"):
        parts.append("**%s%s%s**" % (labels["at_risk"], labels["colon"], item["risk"]))
    parts.append("[Things](%s)" % item["link"])
    return "- %s — %s" % (item["title"], " · ".join(parts))


def render_markdown(report: Dict[str, Any], labels: Dict[str, str]) -> str:
    paren = labels["paren"]
    out = ["# %s — %s%s" % (labels["report"], report["now"], paren.format(s=labels["lead"].format(n=report["lead_days"]))), ""]
    for name in ("overdue", "today", "week", "month"):
        out.append("## %s%s" % (labels[name], paren.format(s=report["counts"][name])))
        areas = report["groups"][name]
        if not areas:
            out.append("- %s" % labels["none"])
        for block in areas:
            out.append("**%s**%s" % (block["area"], paren.format(s=len(block["items"]))))
            out.extend(fmt_item(item, labels) for item in block["items"])
        out.append("")
    props = report["proposals"]
    if not props:
        out.append("## %s" % labels["no_risk"])
    else:
        out.append("## %s" % labels["proposals"].format(n=len(props)))
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (labels["n"], labels["item"], labels["deadline"],
                                                           labels["start"], labels["risk"], labels["when"], labels["command"]))
        out.append("|---|---|---|---|---|---|---|")
        for p in props:
            cmd = "`%s`" % p["command"] if p["command"] else labels["repeating"]
            out.append("| %d | %s | %s | %s | %s | %s | %s |" % (p["n"], p["title"], p["deadline"], p["start_date"] or "-",
                                                             p["risk"], p["when"], cmd))
        out.append("")
        out.append(labels["reminder_hint"].format(t=report["reminder_time"], d=props[0]["when"]))
        if any(p["repeating"] for p in props):
            out.append(labels["repeating_hint"])
    out.append(labels["other"].format(w=WRAPPER))
    if report["warnings"]:
        out.append("")
        out.extend("- warning: %s" % w for w in report["warnings"])
    return "\n".join(out) + "\n"


def pick_lang(flag: str, cfg: Dict[str, Any], text: Optional[str]) -> str:
    if flag in ("zh", "en"):
        return flag
    if cfg.get("language") in ("zh", "en"):
        return cfg["language"]
    return detect_language(text) if text else "en"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now", help="freeze now as YYYY-MM-DDTHH:MM (default: wall clock)")
    ap.add_argument("--lang", choices=("zh", "en", "auto"), default="auto")
    ap.add_argument("--text", help="the user's invocation, for language detection with --lang auto")
    ap.add_argument("--config", help="config file (default: things_lib resolution)")
    ap.add_argument("--markdown", action="store_true", help="print the Markdown report instead of JSON")
    ap.add_argument("--push-spec", metavar="TEXT", help="convert a push phrase to +Nd/+Nw and exit")
    args = ap.parse_args(argv)
    if args.push_spec is not None:
        result = push_spec(args.push_spec)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    try:
        now_dt = datetime.strptime(args.now, "%Y-%m-%dT%H:%M") if args.now else datetime.now()
    except ValueError:
        fail({"command": "now", "error": "invalid --now value %r; use YYYY-MM-DDTHH:MM" % args.now}, 1)
    now_str = now_dt.strftime("%Y-%m-%dT%H:%M")
    try:
        cfg = config_mod.load_config(config_mod.config_path(args.config))
    except config_mod.ConfigError as exc:
        fail({"command": "config", "error": str(exc)}, 1)
    labels = LABELS[pick_lang(args.lang, cfg, args.text)]
    data = gather(now_str, args.config, labels)
    lead = int(cfg.get("deadline_lead_days", 3))
    report = {"ok": True, "now": now_dt.date().isoformat(), "lang": "zh" if labels is LABELS["zh"] else "en",
              "lead_days": lead, "reminder_time": cfg.get("default_reminder_time", "09:00"), "warnings": data["warnings"]}
    report.update(analyse(data["items"], now_dt.date(), lead, report["reminder_time"], labels))
    if args.markdown:
        sys.stdout.write(render_markdown(report, labels))
    else:
        print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
