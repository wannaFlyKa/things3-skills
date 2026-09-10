#!/usr/bin/env python3
"""things-today helper: build the morning brief from the shared CLI's reads.

Read-only; it never sends a write. Honours THINGSDB and --now for testing on Linux.

  brief.py [--now YYYY-MM-DDTHH:MM] [--lang zh|en|auto] [--text INVOCATION] [--config PATH] [--markdown]

Sections: Today (evening items marked), This Evening, Repeating probably due, Overdue,
Deadlines within 7 days, Inbox count, the SPEC B.6 repeating sentence, a today_cap notice,
and ONE fenced block with the Obsidian daily-note checklist as the last thing printed.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts"))
CLI = os.path.join(SCRIPTS, "things")
sys.path.insert(0, SCRIPTS)
from things_lib import config as config_mod  # noqa: E402
from things_lib.dates import detect_language  # noqa: E402
from things_lib.url import show_url  # noqa: E402

REPEATING_SENTENCE = {
    "en": "Repeating to-dos may be missing: things.py only sees instances Things has already generated. "
          "Open Things once to refresh.",
    "zh": "重复任务可能不完整：things.py 只能看到 Things 已生成的实例，请先打开一次 Things。",
}
WEEKDAYS = {"en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "zh": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]}
LABELS = {
    "en": {
        "brief": "Morning brief", "today": "Today", "evening": "This Evening", "evening_mark": "(evening)",
        "evening_unavailable": "evening detection unavailable; check the Today list in Things",
        "repeating_due": "Repeating, probably due", "next": "next", "overdue": "Overdue",
        "deadlines": "Deadlines within 7 days", "inbox": "Inbox: {n} item(s)", "none": "nothing",
        "deadline": "deadline", "ago": "{n} days ago", "in": "in {n} days", "today_word": "today",
        "tomorrow": "tomorrow", "project": "project", "repeating": "repeating", "start": "start",
        "over_cap": "Today has {n} items, above your cap of {cap}. Trim it with /things:things-organize today.",
        "obsidian": "Obsidian daily note:", "warning": "warning",
        "repeating_unavailable": "repeating detection unavailable; 'repeating' marks may be missing",
        "repeating_unpredicted": "repeating to-dos could not be predicted from the database",
    },
    "zh": {
        "brief": "早报", "today": "今天", "evening": "今晚", "evening_mark": "（今晚）",
        "evening_unavailable": "无法识别今晚项目，请在 Things 里查看今天列表",
        "repeating_due": "重复任务（可能到期）", "next": "下次", "overdue": "逾期",
        "deadlines": "7 天内到期", "inbox": "收件箱：{n} 条", "none": "无",
        "deadline": "截止", "ago": "已过 {n} 天", "in": "还剩 {n} 天", "today_word": "今天",
        "tomorrow": "明天", "project": "项目", "repeating": "重复任务", "start": "开始",
        "over_cap": "今天有 {n} 项，超过上限 {cap}，建议运行 /things:things-organize today 精简一下。",
        "obsidian": "Obsidian 日记清单：", "warning": "警告",
        "repeating_unavailable": "无法识别重复任务，重复标记可能缺失",
        "repeating_unpredicted": "无法从数据库预测重复任务的下次到期",
    },
}
# Raw CLI warnings the Markdown localises. None = already rendered by the This Evening placeholder, so it is not
# repeated as a warning line. Unknown warnings are printed as they come. The JSON `warnings` stays raw.
EVENING_UNAVAILABLE = "evening detection unavailable"
KNOWN_WARNINGS: Dict[str, Optional[str]] = {
    EVENING_UNAVAILABLE: None,
    "repeating detection unavailable": "repeating_unavailable",
    "repeating to-dos could not be predicted": "repeating_unpredicted",
}


CLI_TIMEOUT = 90


def run_cli(args: List[str], now: str, config_path: Optional[str]) -> Tuple[int, Dict[str, Any]]:
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


def compact(item: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("uuid", "type", "title", "evening", "start_date", "deadline", "days_until_deadline",
            "area_title", "project_title", "link", "repeating")
    return {k: item.get(k) for k in keys}


def pick_lang(flag: str, cfg: Dict[str, Any], text: Optional[str]) -> str:
    if flag in ("zh", "en"):
        return flag
    if cfg.get("language") in ("zh", "en"):
        return cfg["language"]
    return detect_language(text) if text else "en"


def build(now_dt: datetime, cfg: Dict[str, Any], lang: str, config_path: Optional[str]) -> Dict[str, Any]:
    now_str = now_dt.strftime("%Y-%m-%dT%H:%M")
    envs = {}
    for name, args in (("today", ["today"]), ("overdue", ["overdue"]),
                       ("deadlines", ["deadlines", "--within", "7"]), ("inbox", ["inbox"])):
        code, env = run_cli(args, now_str, config_path)
        if not env.get("ok"):
            fail(env, code)
        envs[name] = env
    warnings: List[str] = []
    for env in envs.values():
        for w in env.get("warnings") or []:
            if w not in warnings and w != REPEATING_SENTENCE["en"]:
                warnings.append(w)
    today_items = [compact(i) for i in envs["today"]["data"]["items"]]
    hint = envs["today"]["data"].get("repeating_hint") or {}
    cap = int(cfg.get("today_cap", 6))
    evening_ok = EVENING_UNAVAILABLE not in warnings
    checklist = "\n".join("- [ ] %s ([Things](%s))" % (i["title"], i["link"]) for i in today_items)
    repeating_due = [dict(d, link=show_url(d["uuid"])) for d in hint.get("due") or [] if d.get("uuid")]
    return {
        "ok": True, "now": now_dt.date().isoformat(), "weekday": WEEKDAYS[lang][now_dt.weekday()], "lang": lang,
        "today_cap": cap,
        "today": {"count": len(today_items), "over_cap": len(today_items) > cap, "items": today_items},
        "evening": {"available": evening_ok, "items": [i for i in today_items if i.get("evening")]},
        "repeating_due": repeating_due, "repeating_templates": hint.get("templates", 0),
        "overdue": [compact(i) for i in envs["overdue"]["data"]],
        "deadlines_7": [compact(i) for i in envs["deadlines"]["data"] if (i.get("days_until_deadline") or 0) >= 0],
        "inbox_count": len(envs["inbox"]["data"]),
        "repeating_sentence": REPEATING_SENTENCE[lang],
        "organize_hint": "/things:things-organize today" if len(today_items) > cap else None,
        "warnings": warnings, "checklist": checklist,
    }


def rel(days: Optional[int], labels: Dict[str, str]) -> str:
    if days is None:
        return ""
    if days < 0:
        return " (%s)" % labels["ago"].format(n=-days)
    if days == 0:
        return " (%s)" % labels["today_word"]
    if days == 1:
        return " (%s)" % labels["tomorrow"]
    return " (%s)" % labels["in"].format(n=days)


def line(item: Dict[str, Any], labels: Dict[str, str], mark_evening: bool) -> str:
    parts = []
    if mark_evening and item.get("evening"):
        parts.append(labels["evening_mark"])
    if item.get("type") == "project":
        parts.append(labels["project"])
    if item.get("deadline"):
        parts.append("%s %s%s" % (labels["deadline"], item["deadline"], rel(item.get("days_until_deadline"), labels)))
    if item.get("project_title"):
        parts.append(item["project_title"])
    if item.get("repeating"):
        parts.append(labels["repeating"])
    parts.append("[Things](%s)" % item["link"])
    return "- %s · %s" % (item["title"], " · ".join(parts))


def section(out: List[str], title: str, items: List[Dict[str, Any]], labels: Dict[str, str], mark: bool = False) -> None:
    out.append("## %s (%d)" % (title, len(items)))
    out.extend(line(i, labels, mark) for i in items) if items else out.append("- %s" % labels["none"])
    out.append("")


def render_markdown(b: Dict[str, Any]) -> str:
    labels = LABELS[b["lang"]]
    out = ["# %s — %s %s" % (labels["brief"], b["now"], b["weekday"]), ""]
    section(out, labels["today"], b["today"]["items"], labels, mark=True)
    if b["evening"]["available"]:
        section(out, labels["evening"], b["evening"]["items"], labels)
    else:
        out.extend(["## %s" % labels["evening"], "- %s" % labels["evening_unavailable"], ""])
    if b["repeating_due"]:
        out.append("## %s (%d)" % (labels["repeating_due"], len(b["repeating_due"])))
        out.extend("- %s · %s %s · [Things](%s)" % (d["title"], labels["next"], d["next_instance_date"], d["link"])
                   for d in b["repeating_due"])
        out.append("")
    section(out, labels["overdue"], b["overdue"], labels)
    section(out, labels["deadlines"], b["deadlines_7"], labels)
    out.extend(["## %s" % labels["inbox"].format(n=b["inbox_count"]), ""])
    out.append(b["repeating_sentence"])
    if b["today"]["over_cap"]:
        out.append(labels["over_cap"].format(n=b["today"]["count"], cap=b["today_cap"]))
    for w in b["warnings"]:
        key = KNOWN_WARNINGS.get(w, "")
        if key is None:
            continue  # the This Evening placeholder already says it, in the brief's language
        out.append("%s: %s" % (labels["warning"], labels[key] if key else w))
    # the fenced block is empty when Today is empty: a bare `- [ ]` would paste an empty task into the daily note
    out.extend(["", labels["obsidian"], "```", b["checklist"], "```"])
    return "\n".join(out) + "\n"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now", help="freeze now as YYYY-MM-DDTHH:MM (default: wall clock)")
    ap.add_argument("--lang", choices=("zh", "en", "auto"), default="auto")
    ap.add_argument("--text", help="the user's invocation, for language detection with --lang auto")
    ap.add_argument("--config", help="config file (default: things_lib resolution)")
    ap.add_argument("--markdown", action="store_true", help="print the brief as Markdown instead of JSON")
    args = ap.parse_args(argv)
    try:
        now_dt = datetime.strptime(args.now, "%Y-%m-%dT%H:%M") if args.now else datetime.now()
    except ValueError:
        fail({"command": "now", "error": "invalid --now value %r; use YYYY-MM-DDTHH:MM" % args.now}, 1)
    try:
        cfg = config_mod.load_config(config_mod.config_path(args.config))
    except config_mod.ConfigError as exc:
        fail({"command": "config", "error": str(exc)}, 1)
    brief = build(now_dt, cfg, pick_lang(args.lang, cfg, args.text), args.config)
    if args.markdown:
        sys.stdout.write(render_markdown(brief))
    else:
        print(json.dumps(brief, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
