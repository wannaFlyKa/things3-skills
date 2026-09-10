#!/usr/bin/env python3
"""candidates.py: find the open Things items that match what the user says got done.

Input: described items as a JSON array on stdin, or as positional arguments.
For each item the shared CLI `search --status open` is run for the cleaned phrase,
for every meaningful word and for CJK bigrams (the CLI expands config synonyms
across ZH/EN). Hits are merged, ranked (title hits above notes hits, then most
recently modified), de-duplicated and numbered. Output is JSON (default) or a
Markdown table (--markdown). This script never writes to Things. Command lines
are printed ONLY when the user's picks are passed back with `--pick 1,3 --action
complete|cancel`: then it prints the picked, non-repeating ids in batches of ten
for that one verb, each piped into report.py.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts"))
CLI = os.path.join(SCRIPTS, "things")
sys.path.insert(0, SCRIPTS)
from things_lib import config as config_mod  # noqa: E402
from things_lib import dates  # noqa: E402

# Claude Code substitutes ${CLAUDE_SKILL_DIR} only inside SKILL.md text, never in tool output, so the
# printed commands carry the real paths of the sibling wrapper and helper (HERE is the skill's scripts/ dir).
WRAPPER = os.path.join(HERE, "things")
REPORT = os.path.join(HERE, "report.py")
BATCH = 10  # the CLI refuses more ids than this without --yes, which this skill never uses
ACTIONS = ("complete", "cancel")
NOW_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")
KIND_SCORE = {"phrase": 30, "word": 20, "bigram": 10}
EXACT_BONUS = 1000   # the title IS the described text
TITLE_BONUS = 100    # any title hit outranks any notes hit
MAX_EXTRA = 30       # distinct-query bonus can never lift a notes hit above a title hit
CLI_TIMEOUT = 90

EN_STOP = {
    "a", "an", "the", "and", "or", "with", "for", "to", "of", "my", "our", "that", "this", "these",
    "those", "thing", "things", "stuff", "task", "tasks", "todo", "todos", "to-do", "to-dos", "item", "items", "one",
    "ones", "done", "finished", "finish", "finishing", "complete", "completed", "completing", "close",
    "closed", "closing", "mark", "marked", "drop", "dropped", "dropping", "cancel", "canceled",
    "cancelled", "won't", "wont", "will", "not", "do", "did", "it", "is", "was", "are", "were", "i",
    "me", "we", "you", "up", "off", "out", "on", "in", "at", "as", "be", "been", "also", "too", "both",
    "already", "just", "get", "got", "please", "pls", "so", "then", "now", "today", "yesterday",
    "won", "don", "didn", "doesn", "isn", "wasn", "can", "cannot", "couldn", "shouldn", "wouldn", "haven",
    "hasn", "ve", "ll", "re", "ok", "okay", "yes", "no", "want", "need", "anymore", "longer", "going",
    "gonna", "let", "lets", "skip", "skipped", "skipping", "abandon", "abandoned", "scrap", "scrapped",
    "ditch", "ditched", "forget", "about", "from", "by", "into", "over", "all", "some", "any", "each",
    "every", "other", "another", "them", "they", "he", "she", "his", "her", "their", "its", "your",
    "handled", "wrapped", "sorted", "resolved", "finally", "am", "pm",
}
# Longest first so that "关闭" is removed before "关" would split a real word.
ZH_STOP = sorted([
    "已经完成", "已经搞定", "已经做完", "不做了", "不用做", "不需要", "不要了", "算了", "取消掉",
    "完成了", "搞定了", "做完了", "关掉了", "关闭了", "弄完了", "结束了", "处理完", "解决了",
    "完成", "搞定", "做完", "关掉", "关闭", "弄完", "结束", "取消", "放弃", "删掉", "帮我", "把",
    "那个", "这个", "那件", "这件", "一下", "已经", "都", "也", "就", "给", "我", "你", "他", "她",
    "它", "事情", "事儿", "任务", "待办", "东西", "个", "了", "的", "呢", "吧", "啊", "哦", "嗯",
    "今天", "昨天", "刚刚", "刚才", "顺便", "还有", "以及", "和", "与", "跟", "及", "然后",
], key=len, reverse=True)
CJK = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")
SPLIT = re.compile(r"[\s,，、;；。!！?？:：()（）\[\]【】\"'“”‘’<>《》/|]+")


def tokenize(text: str) -> Tuple[List[str], List[str]]:
    """Return (words, bigrams) for one described item, stopwords removed."""
    lowered = text.strip().casefold()
    for stop in ZH_STOP:
        lowered = lowered.replace(stop, " ")
    words: List[str] = []
    for chunk in SPLIT.split(lowered):
        if not chunk or (len(chunk) < 2 and not chunk.isdigit()) or chunk in EN_STOP:
            continue
        if chunk not in words:
            words.append(chunk)
    bigrams: List[str] = []
    for word in words:
        if CJK.match(word) and len(word) >= 3:
            for i in range(len(word) - 1):
                gram = word[i:i + 2]
                if gram not in words and gram not in bigrams:
                    bigrams.append(gram)
    return words, bigrams


def run_cli(args: argparse.Namespace, *cli_args: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """Run the shared CLI; return (envelope, error, exit_code)."""
    cmd = [sys.executable, CLI]
    if args.now:
        cmd += ["--now", args.now]
    if args.config:
        cmd += ["--config", args.config]
    cmd += list(cli_args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "the things CLI did not answer in %d s" % CLI_TIMEOUT, 1
    except OSError as exc:
        return None, "cannot run the things CLI: %s" % exc, 1
    try:
        envelope = json.loads(proc.stdout)
    except ValueError:
        return None, (proc.stderr.strip() or "the things CLI printed no JSON"), proc.returncode or 1
    if not envelope.get("ok"):
        return envelope, envelope.get("error") or "unknown error", proc.returncode
    return envelope, None, proc.returncode


def search(args: argparse.Namespace, query: str, status: str) -> Tuple[List[Dict[str, Any]], Optional[str], int]:
    envelope, error, code = run_cli(args, "search", query, "--status", status, "--type", args.type,
                                    "--limit", str(args.per_query))
    if error:
        return [], error, code
    return list(envelope.get("data") or []), None, 0


class InputError(Exception):
    """Bad input; main() prints {"ok": false, "error": ...} and exits 1 (SPEC H.1: no traceback)."""


def parse_now(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now()
    for fmt in NOW_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise InputError("invalid --now value %r; expected YYYY-MM-DDTHH:MM" % value)


def list_of(item: Dict[str, Any], today: str) -> str:
    """The column called 'list': project, heading or area title, else Inbox / Today / Upcoming / Someday / Anytime.

    A to-do under a heading has no project_title in things.py output; resolve_headings() fills it in from
    the heading row, and heading_title stays the fallback when that lookup failed (same order as
    things-organize/review.py). things.py reports every dated item with start == 'Someday'; the date
    decides Today vs Upcoming (same rule as review.py location()).
    """
    container = item.get("project_title") or item.get("heading_title") or item.get("area_title")
    if container:
        return str(container)
    start, start_date = item.get("start") or "", item.get("start_date")
    if start == "Inbox":
        return "Inbox"
    if start_date:
        return "Upcoming" if str(start_date) > today else "Today"
    if start == "Someday":
        return "Someday"
    return "Anytime"


def queries_for(text: str) -> List[Tuple[str, str]]:
    """Ordered (kind, query) pairs for one described item, without duplicates."""
    words, bigrams = tokenize(text)
    out: List[Tuple[str, str]] = []
    phrase = " ".join(words)
    if len(words) > 1:
        out.append(("phrase", phrase))
    for word in words:
        if not word.isdigit():  # a bare number only helps inside the phrase ("area 1")
            out.append(("word", word))
    for gram in bigrams:
        out.append(("bigram", gram))
    if not out:
        raw = text.strip()
        if raw:
            out.append(("phrase", raw))
    return out


def collect(args: argparse.Namespace, text: str, warnings: List[str]) -> Tuple[List[Dict[str, Any]], bool]:
    """Search one described item; return (ranked hits for this item, database_ok)."""
    hits: Dict[str, Dict[str, Any]] = {}
    for kind, query in queries_for(text):
        results, error, code = search(args, query, "open")
        if error:
            warnings.append("search %r failed: %s" % (query, error))
            if code == 3:
                return [], False
            continue
        for item in results:
            uid = item["uuid"]
            entry = hits.get(uid)
            if entry is None:
                entry = dict(item)
                entry["_kinds"] = set()
                entry["_queries"] = []
                entry["_title_hit"] = False
                entry["_exact"] = (item.get("title") or "").casefold().strip() == text.casefold().strip()
                entry["_terms"] = []
                hits[uid] = entry
            entry["_kinds"].add(kind)
            entry["_queries"].append(query)
            entry["_title_hit"] = entry["_title_hit"] or item.get("match") == "title"
            for term in item.get("matched_terms") or []:
                if term not in entry["_terms"]:
                    entry["_terms"].append(term)
    # Highest score first; ties broken by most recently modified (ISO strings sort correctly).
    ranked = sorted(hits.values(), key=lambda e: (score(e), e.get("modified") or ""), reverse=True)
    return ranked[:args.limit], True


def score(entry: Dict[str, Any]) -> int:
    """Exact (casefolded) title first, then other title hits, then notes hits; ties: modified desc.

    Inside a tier, phrase hits beat word hits beat bigram hits and distinct queries add a little.
    """
    base = max(KIND_SCORE[k] for k in entry["_kinds"])
    extra = min(MAX_EXTRA, 3 * (len(set(entry["_queries"])) - 1))
    tier = (EXACT_BONUS if entry.get("_exact") else 0) + (TITLE_BONUS if entry["_title_hit"] else 0)
    return tier + base + extra


def maybe_closed(args: argparse.Namespace, text: str, warnings: List[str]) -> List[Dict[str, Any]]:
    """For an item with no open match: recently closed items that match (maybe it is already done)."""
    found: Dict[str, Dict[str, Any]] = {}
    for kind, query in queries_for(text):
        if kind == "bigram":
            continue
        results, error, _ = search(args, query, "all")
        if error:
            warnings.append("search %r failed: %s" % (query, error))
            continue
        for item in results:
            if item.get("status") != "incomplete" and item["uuid"] not in found:
                found[item["uuid"]] = {"uuid": item["uuid"], "title": item.get("title") or "",
                                       "status": item.get("status"), "stop_date": item.get("stop_date"),
                                       "link": item.get("link") or "things:///show?id=%s" % item["uuid"]}
    closed = sorted(found.values(), key=lambda c: c.get("stop_date") or "", reverse=True)
    return closed[:3]


def resolve_headings(args: argparse.Namespace, per_item: List[Tuple[str, List[Dict[str, Any]]]],
                     warnings: List[str]) -> None:
    """things.py leaves `project` empty for a to-do under a heading (the gap the CLI closes with project_ref).

    One `things get <heading>` per distinct heading copies the heading's project / project_title onto every
    such hit, so the List column names the real project. A failed lookup is reported once and the row keeps
    heading_title as its container (list_of()).
    """
    cache: Dict[str, Optional[Dict[str, Any]]] = {}
    for _text, ranked in per_item:
        for entry in ranked:
            heading = entry.get("heading")
            if not heading or entry.get("project") or entry.get("project_title"):
                continue
            if heading not in cache:
                envelope, error, _ = run_cli(args, "get", str(heading))
                data = (envelope or {}).get("data")
                cache[heading] = data if not error and isinstance(data, dict) else None
                if error:
                    warnings.append("get %r (heading of %r) failed: %s" % (heading, entry.get("title") or entry["uuid"], error))
            row = cache[heading]
            if row:
                for key in ("project", "project_title"):
                    if row.get(key) is not None:
                        entry[key] = row[key]


def merge(per_item: List[Tuple[str, List[Dict[str, Any]]]], today: str) -> List[Dict[str, Any]]:
    """Interleave the ranked lists of every described item; an item seen twice keeps its STRONGEST hit.

    Ranking must not depend on which described item happened to surface the row first: a title hit
    found by a later described item still has to outrank a notes hit found by an earlier one.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for text, ranked in per_item:
        for entry in ranked:
            uid = entry["uuid"]
            if uid not in merged:
                merged[uid] = {
                    "uuid": uid, "type": entry.get("type"), "title": entry.get("title") or "",
                    "list": list_of(entry, today), "start": entry.get("start"), "start_date": entry.get("start_date"),
                    "deadline": entry.get("deadline"), "repeating": bool(entry.get("repeating")),
                    "modified": entry.get("modified"), "link": entry.get("link") or "things:///show?id=%s" % uid,
                    "match": "title" if entry["_title_hit"] else "notes", "matched_terms": list(entry["_terms"]),
                    "score": score(entry), "for": [],
                }
                order.append(uid)
            else:
                row = merged[uid]
                if entry["_title_hit"]:
                    row["match"] = "title"
                row["score"] = max(row["score"], score(entry))
                for term in entry["_terms"]:
                    if term not in row["matched_terms"]:
                        row["matched_terms"].append(term)
            if text not in merged[uid]["for"]:
                merged[uid]["for"].append(text)
    rows = [merged[uid] for uid in order]
    rows.sort(key=lambda r: (r["score"], r.get("modified") or ""), reverse=True)
    for number, row in enumerate(rows, 1):
        row["n"] = number
    return rows


def parse_pick(value: str, rows: List[Dict[str, Any]]) -> List[int]:
    """`1,3` / `1 3` / `all` / `全部` -> sorted row numbers; anything else is an InputError."""
    if not rows:
        raise InputError("no candidates to pick from; nothing matched the described items")
    if value.strip().casefold() in ("all", "全部"):
        return [r["n"] for r in rows]
    numbers: List[int] = []
    for token in re.split(r"[\s,，、]+", value.strip()):
        if not token:
            continue
        if not token.isdigit() or int(token) < 1 or int(token) > len(rows):
            raise InputError("pick %r: no such candidate (rows are 1-%d)" % (token, len(rows)))
        if int(token) not in numbers:
            numbers.append(int(token))
    if not numbers:
        raise InputError("pick %r selects nothing; expected numbers like 1,3 or all" % value)
    return sorted(numbers)


def commands(rows: List[Dict[str, Any]], picked: List[int], action: str, lang: str) -> Dict[str, Any]:
    """Command lines for the PICKED rows only, for ONE verb: batches of at most BATCH non-repeating ids,
    each piped into report.py. Repeating rows are listed under `left_out`; the CLI cannot change them."""
    chosen = [r for r in rows if r["n"] in picked]
    ids = [r["uuid"] for r in chosen if not r["repeating"]]
    lines = ["%s %s %s | %s --markdown --lang %s" % (WRAPPER, action, " ".join(ids[start:start + BATCH]), REPORT, lang)
             for start in range(0, len(ids), BATCH)]
    return {"action": action, "picked": picked, "ids": ids, "lines": lines,
            "left_out": [{"n": r["n"], "uuid": r["uuid"], "title": r["title"]} for r in chosen if r["repeating"]]}


LABELS = {
    "en": {"head": ["#", "Title", "List", "Start", "Deadline", "Repeating", "For", "Link"], "yes": "yes",
           "none": "No open to-do matches: %s", "closed": "  possibly already closed: %s (%s, %s) %s",
           "hint": "After the user picks numbers, re-run with `--pick 1,3 --action complete` (or `cancel`) "
                   "to get the exact command lines; run nothing before that.",
           "next": "Run these lines one at a time (%s, rows %s only; each pipes into report.py):",
           "left_out": "Left out (repeating; do it in Things): %s",
           "nothing": "Nothing to run: every picked row is a repeating to-do.",
           "repeat": "Repeating items cannot be completed or canceled through the URL scheme; do them in Things.",
           "empty": "No open to-do matches anything described.", "warn": "Warnings:"},
    "zh": {"head": ["#", "标题", "列表", "开始", "截止", "重复", "对应", "链接"], "yes": "是",
           "none": "没有找到未完成的匹配项：%s", "closed": "  可能已经关掉了：%s（%s，%s）%s",
           "hint": "等用户选好编号后，加上 `--pick 1,3 --action complete`（或 `cancel`）重新运行，"
                   "得到要执行的命令行；在此之前不要执行任何写操作。",
           "next": "逐行执行下面的命令（%s，仅第 %s 行；每行都接入 report.py）：",
           "left_out": "已排除（重复任务，请在 Things 里处理）：%s",
           "nothing": "没有可执行的命令：选中的都是重复任务。",
           "repeat": "重复任务无法通过 URL scheme 完成或取消，请在 Things 里处理。",
           "empty": "描述的事项都没有未完成的匹配项。", "warn": "警告："},
}
STATUS_ZH = {"completed": "已完成", "canceled": "已取消", "incomplete": "未完成"}


def pick_language(args: argparse.Namespace, items: List[str], cfg: Dict[str, Any]) -> str:
    if args.lang in ("zh", "en"):
        return args.lang
    if cfg.get("language") in ("zh", "en"):
        return str(cfg["language"])
    return dates.detect_language(" ".join(items))


def cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def render_markdown(result: Dict[str, Any], lang: str) -> str:
    text = LABELS[lang]
    lines: List[str] = []
    rows = result["candidates"]
    if rows:
        lines.append("| " + " | ".join(text["head"]) + " |")
        lines.append("|" + "---|" * len(text["head"]))
        for r in rows:
            title = ("[project] " if r["type"] == "project" else "") + r["title"]
            lines.append("| %d | %s | %s | %s | %s | %s | %s | %s |" % (
                r["n"], cell(title), cell(r["list"]), cell(r["start_date"] or r["start"]), cell(r["deadline"]),
                text["yes"] if r["repeating"] else "", cell(" / ".join(r["for"])), r["link"]))
    else:
        lines.append(text["empty"])
    for miss in result["unmatched"]:
        lines.append(text["none"] % miss["item"])
        for c in miss["maybe_closed"]:
            status = c["status"] or ""
            shown = STATUS_ZH.get(status, status) if lang == "zh" else status
            lines.append(text["closed"] % (c["title"], shown, c["stop_date"] or "", c["link"]))
    if any(r["repeating"] for r in rows):
        lines.append(text["repeat"])
    picked = result["commands"]
    if picked is None:
        if rows:
            lines.append(text["hint"])
    else:
        if picked["left_out"]:
            lines.append(text["left_out"] % ", ".join("%d %s" % (r["n"], r["title"]) for r in picked["left_out"]))
        if picked["lines"]:
            lines.append(text["next"] % (picked["action"], ",".join(str(n) for n in picked["picked"])))
            lines.extend("    " + command for command in picked["lines"])
        else:
            lines.append(text["nothing"])
    if result["warnings"]:
        lines.append(text["warn"])
        lines.extend("  - " + w for w in result["warnings"])
    return "\n".join(lines) + "\n"


def read_items(args: argparse.Namespace) -> List[str]:
    if args.items:
        raw: Any = list(args.items)
    else:
        data = sys.stdin.read().strip()
        if not data:
            return []
        try:
            raw = json.loads(data)
        except ValueError:
            raw = [line for line in data.splitlines()]
        if isinstance(raw, str):
            raw = [raw]
    if not isinstance(raw, list):
        raise InputError("stdin must be a JSON array of described items")
    items: List[str] = []
    for value in raw:
        value = str(value).strip()
        if value and value not in items:
            items.append(value)
    return items


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Rank open Things items matching what the user says got done.")
    parser.add_argument("items", nargs="*", help="described items; omit to read a JSON array from stdin")
    parser.add_argument("--markdown", action="store_true", help="print a numbered Markdown table instead of JSON")
    parser.add_argument("--lang", choices=["auto", "zh", "en"], default="auto", help="label language")
    parser.add_argument("--limit", type=int, default=6, help="max candidates kept per described item")
    parser.add_argument("--per-query", type=int, default=20, help="--limit passed to each CLI search")
    parser.add_argument("--type", choices=["to-do", "project", "all"], default="all")
    parser.add_argument("--now", help="freeze now, YYYY-MM-DDTHH:MM (forwarded to the CLI)")
    parser.add_argument("--config", help="config file (forwarded to the CLI)")
    parser.add_argument("--pick", metavar="1,3|all", help="row numbers the user picked; prints command lines for them only")
    parser.add_argument("--action", choices=ACTIONS, help="the verb the user chose (required with --pick)")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (InputError, config_mod.ConfigError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


def run(args: argparse.Namespace) -> int:
    if bool(args.pick) != bool(args.action):
        raise InputError("--pick and --action go together (e.g. --pick 1,3 --action complete)")
    today = parse_now(args.now).date().isoformat()
    cfg = config_mod.load_config(args.config)
    items = read_items(args)
    lang = pick_language(args, items, cfg)
    warnings: List[str] = []
    per_item: List[Tuple[str, List[Dict[str, Any]]]] = []
    unmatched: List[Dict[str, Any]] = []
    for text in items:
        ranked, db_ok = collect(args, text, warnings)
        if not db_ok:
            error = warnings[-1] if warnings else "database unavailable"
            print(json.dumps({"ok": False, "error": error, "items": items}, ensure_ascii=False))
            return 3
        per_item.append((text, ranked))
        if not ranked:
            unmatched.append({"item": text, "maybe_closed": maybe_closed(args, text, warnings)})
    resolve_headings(args, per_item, warnings)
    rows = merge(per_item, today)
    picked = commands(rows, parse_pick(args.pick, rows), args.action, lang) if args.pick else None
    result = {"ok": True, "language": lang, "now": args.now, "items": items, "candidates": rows,
              "unmatched": unmatched, "commands": picked, "warnings": warnings}
    if args.markdown:
        sys.stdout.write(render_markdown(result, lang))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
