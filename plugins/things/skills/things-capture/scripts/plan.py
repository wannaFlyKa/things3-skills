#!/usr/bin/env python3
"""Planner for the things-capture skill (SPEC H.2, row things-capture).

The MODEL splits the user's free text into candidate tasks and pipes them here as a JSON
array (--candidates-json '<json>', --input FILE, or stdin). Candidate keys (all optional except one of text/title):
  text       the user's own words for this task; when/deadline are parsed from here
  title      title exactly as the user wrote it (default: text minus the date phrase)
  notes, source, checklist [str], tags [str]
  area, project      only when the user's wording names a list
  when, deadline     explicit F.1 values (e.g. after the user answered a question)
  date_is            "when" | "deadline": the answer to the start-or-deadline question
  kind               "to-do" | "project"
  todos    [ {text|title, notes, checklist, tags, when, deadline} | str ]   flat project
  phases   [ {"title": str, "todos": [...]} ]   multi-phase goal -> project with headings

Output: JSON (default) or Markdown (--markdown): a preview table plus the exact wrapper
commands (absolute path of the sibling scripts/things wrapper; options first, the title after
`--`). A candidate that still needs the start-or-deadline answer gets NO command: it is listed
under `blocked` (JSON) / as a `# [n] blocked` comment (Markdown). This script NEVER sends a
write. Its only side effect is the add-json payload file ${TMPDIR:-/tmp}/things-capture-<epoch>.json
for a project with headings; payload files older than one day are pruned on the next run.
Honours THINGSDB, --config and --now YYYY-MM-DDTHH:MM (for tests). Python 3.9, stdlib only.
"""

import argparse
import glob
import json
import os
import re
import shlex
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "scripts")))

from things_lib import config as config_mod  # noqa: E402
from things_lib import dates  # noqa: E402
from things_lib import read  # noqa: E402
from things_lib.url import show_url  # noqa: E402

# Claude Code substitutes ${CLAUDE_SKILL_DIR} only inside SKILL.md text, never in tool output, so the
# printed commands carry the real path of the sibling wrapper (HERE is the skill's scripts/ dir).
DEFAULT_CLI = os.path.join(HERE, "things")
NOW_FORMATS = ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")
VALID_WHEN = re.compile(r"^(today|tomorrow|evening|anytime|someday|\d{4}-\d{2}-\d{2}(@\d{2}:\d{2})?)$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Wording that makes a bare date a clear START intention (no question needed).
START_INTENT = re.compile(
    r"开始|安排|计划|出发|动手|开会|见面|约了|打电话|电话|拜访|见客户|后天|天后|天以后|周后|星期后|个月后|礼拜后"
    r"|\b(start|begin|schedule|plan|on|meet|meeting|call|visit|kick-?off|day after tomorrow"
    r"|in \d+ (days?|weeks?|months?))\b", re.IGNORECASE)
CHECKLIST_MIN, CHECKLIST_MAX = 3, 8
PAYLOAD_TTL_SECONDS = 86400  # add-json payload files older than this are pruned from TMPDIR
TEXT = {
    "zh": {"headers": ("标题", "列表", "开始", "截止", "标签", "清单"), "inbox": "收件箱",
           "dup": "已有同名未完成项", "question": "需要先回答", "blocked": "已阻止：需要先回答，暂无命令",
           "confirm": "要创建这 {n} 项吗？(y / 编号如 1,3 / 全部)",
           "ask": "「{title}」的 {date} 是开始日期还是截止日期？(开始 / 截止)",
           "todos": "{n} 个待办", "headings": "{h} 个标题、{n} 个待办", "payload": "add-json 文件"},
    "en": {"headers": ("Title", "List", "When", "Deadline", "Tags", "Checklist"), "inbox": "Inbox",
           "dup": "open item with the same title", "question": "answer first",
           "blocked": "blocked: answer first, no command yet",
           "confirm": "Create these {n} item(s)? (y / numbers like 1,3 / all)",
           "ask": "For \"{title}\", is {date} the start date or the deadline? (start / deadline)",
           "todos": "{n} to-dos", "headings": "{h} headings, {n} to-dos", "payload": "add-json file"},
}


class PlanError(Exception):
    """Bad input; main() turns it into {"ok": false, "error": ...} with exit 1 (SPEC H.1: no traceback)."""


def parse_now(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now()
    for fmt in NOW_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise PlanError("invalid --now value %r; expected YYYY-MM-DDTHH:MM" % value)


def q(value: Any) -> str:
    return shlex.quote(str(value))


def cell(value: Any) -> str:
    text = "-" if value in (None, "", []) else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def one_line(text: Any) -> str:
    """Titles are single-line: a newline would put its tail on an uncommented line of the ```sh block."""
    return " ".join(str(text or "").splitlines())


def clean_title(text: str) -> str:
    return text.strip().strip(":：,，、;；-").strip()


class Planner:
    """Deterministic routing, dates, tags, duplicates and command building. No writes."""

    def __init__(self, cfg: Dict[str, Any], now: datetime, cli: str, yes: bool) -> None:
        self.cfg, self.now, self.cli, self.yes = cfg, now, cli, yes
        self.warnings: List[str] = []
        self.areas: List[Dict] = []
        self.projects: List[Dict] = []
        known: Optional[Dict[str, str]] = None
        self.db = read.database_status()
        if self.db != "unavailable":
            try:
                self.areas = read.areas()
                self.projects = read.projects(now=now)
                known = {t.casefold(): t for t in read.tag_titles()}
            except read.ReadError as exc:
                self.db = "unavailable"
                self.warn("read failed: %s" % exc)
        if self.db == "unavailable":
            self.warn("database unavailable: lists, tags and duplicates were not verified; "
                      "the CLI will run write-only (reduced verification)")
        # Allowed tags = config.tags that also exist in Things (E.8); canonical spelling from Things.
        self.allowed: Dict[str, str] = {}
        self.missing_config_tags: List[str] = []
        for tag in cfg.get("tags") or []:
            if known is None:
                self.allowed[tag.casefold()] = tag
            elif tag.casefold() in known:
                self.allowed[tag.casefold()] = known[tag.casefold()]
            else:
                self.missing_config_tags.append(tag)
        if self.missing_config_tags:
            self.warn("config.tags missing in Things (create them in Things, never here): "
                      + ", ".join(self.missing_config_tags))
        # Second chance for "calls" vs "@calls": the prefix is part of the Things name, users omit it.
        self.allowed_loose: Dict[str, str] = {k.lstrip("@#"): v for k, v in self.allowed.items()}

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    # --- lookups ------------------------------------------------------------------------
    @staticmethod
    def _find(rows: List[Dict], name: str) -> Optional[Dict]:
        folded = name.casefold()
        for row in rows:
            if row.get("uuid") == name or (row.get("title") or "").casefold() == folded:
                return row
        return None

    def base(self) -> str:
        return self.cli + (" --yes" if self.yes else "")

    # --- routing (config.route + the user's wording; personal/work independent per candidate) ---
    def resolve_list(self, cand: Dict, title: str, notes: str, w: List[str]) -> Dict[str, Any]:
        area, project = cand.get("area"), cand.get("project")
        source = "user" if (area or project) else None
        if not (area or project):
            hit = config_mod.route(title, notes, self.cfg)
            if hit:
                area, project, source = hit.get("area"), hit.get("project"), "routing_hints"
        if project:
            found = self._find(self.projects, str(project))
            if found:
                return {"list": found["title"], "list_id": found["uuid"], "list_kind": "project", "source": source}
            if self.db == "unavailable":
                return {"list": str(project), "list_id": None, "list_kind": "project", "source": source}
            w.append("project not found in Things: %s (create it in Things or fix routing_hints; "
                     "run things-setup to check)" % project)
        if area:
            found = self._find(self.areas, str(area))
            if found:
                return {"list": found["title"], "list_id": found["uuid"], "list_kind": "area", "source": source}
            if self.db == "unavailable":
                return {"list": str(area), "list_id": None, "list_kind": "area", "source": source}
            w.append("area not found in Things: %s (create it in Things or fix routing_hints; "
                     "run things-setup to check)" % area)
        return {"list": None, "list_id": None, "list_kind": "inbox", "source": None}

    # --- dates (things_lib.dates.extract_dates; never invent a deadline) ------------------------
    def _as_date(self, when: str) -> Optional[str]:
        if when == "today":
            return self.now.date().isoformat()
        if when == "tomorrow":
            return (self.now.date() + timedelta(days=1)).isoformat()
        if when[:4].isdigit():
            return when.split("@")[0]
        return None

    def resolve_dates(self, cand: Dict, text: str, title: str, lang: str,
                      w: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Dict]:
        ex = dates.extract_dates(text, self.now, self.cfg["default_reminder_time"])
        when, deadline, reminder = ex["when"], ex["deadline"], ex["reminder"]
        date_is = cand.get("date_is")
        if date_is == "deadline" and when and deadline is None:
            moved = self._as_date(when)
            if moved:
                deadline, when = moved, None
        for key, pattern in (("when", VALID_WHEN), ("deadline", ISO_DATE)):
            value = cand.get(key)
            if value is None:
                continue
            if value == "":
                when, deadline = (None, deadline) if key == "when" else (when, None)
            elif pattern.match(str(value)):
                when, deadline = (str(value), deadline) if key == "when" else (when, str(value))
            else:
                w.append("ignored invalid %s %r; use the F.1 vocabulary (run: things parse-date)" % (key, value))
        question = None
        if (when and ISO_DATE.match(when) and deadline is None and date_is not in ("when", "deadline")
                and cand.get("when") is None and not START_INTENT.search(text)):
            question = TEXT[lang]["ask"].format(title=title, date=when)
        return when, deadline, reminder, question, ex

    # --- tags, checklist, duplicates ---------------------------------------------------------
    def resolve_tags(self, raw: Any, w: List[str]) -> Tuple[List[str], List[str]]:
        kept: List[str] = []
        dropped: List[str] = []
        for tag in raw or []:
            tag = str(tag).strip()
            folded = tag.casefold()
            canonical = self.allowed.get(folded) or self.allowed_loose.get(folded.lstrip("@#"))
            if canonical and canonical not in kept:
                kept.append(canonical)
            elif tag and not canonical and tag not in dropped:
                dropped.append(tag)
        if dropped:
            w.append("tags outside config.tags or missing in Things, dropped: %s (allowed: %s)"
                     % (", ".join(dropped), ", ".join(sorted(set(self.allowed.values()))) or "none"))
        return kept, dropped

    @staticmethod
    def resolve_checklist(raw: Any, w: List[str]) -> List[str]:
        items = [str(s).strip() for s in (raw or []) if str(s).strip()]
        if items and not CHECKLIST_MIN <= len(items) <= CHECKLIST_MAX:
            w.append("checklist has %d steps; guideline is %d-%d (fewer: notes, more: project)"
                     % (len(items), CHECKLIST_MIN, CHECKLIST_MAX))
        return items[:100]

    @staticmethod
    def _brief(item: Dict) -> Dict[str, Any]:
        return {"uuid": item.get("uuid"), "title": item.get("title"),
                "list": item.get("project_title") or item.get("area_title") or item.get("start"),
                "start_date": item.get("start_date"), "deadline": item.get("deadline"),
                "link": show_url(item.get("uuid") or "")}

    def find_duplicates(self, title: str, kind: str) -> Tuple[List[Dict], List[Dict]]:
        if self.db == "unavailable" or not title.strip():
            return [], []
        try:
            hits = read.search(title, status="open", item_type=kind, limit=10, synonyms=None, now=self.now)
        except read.ReadError as exc:
            self.warn("duplicate check failed: %s" % exc)
            return [], []
        folded = title.casefold()
        exact = [self._brief(h) for h in hits if (h.get("title") or "").casefold() == folded]
        similar = [self._brief(h) for h in hits if (h.get("title") or "").casefold() != folded][:3]
        return exact, similar

    # --- nested to-dos of a project -------------------------------------------------------------
    def nested_todo(self, raw: Any, lang: str, w: List[str]) -> Dict[str, Any]:
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict):
            raise PlanError("todo entries must be JSON objects or strings, got %s" % type(raw).__name__)
        text = str(raw.get("text") or raw.get("title") or "")
        title = one_line(raw.get("title"))
        when, deadline, _reminder, _question, ex = self.resolve_dates(raw, text, title or text, lang, w)
        if not title:
            title = one_line(clean_title(ex["remaining"]) or text.strip())
        tags, _dropped = self.resolve_tags(raw.get("tags"), w)
        notes = self.merge_notes(raw)
        return {"title": title, "notes": notes, "when": when, "deadline": deadline, "tags": tags,
                "checklist": self.resolve_checklist(raw.get("checklist"), w)}

    @staticmethod
    def merge_notes(raw: Dict) -> str:
        notes = str(raw.get("notes") or "").strip()
        source = str(raw.get("source") or "").strip()
        if source and source not in notes:
            notes = (notes + "\n" + source).strip()
        return notes

    # --- one candidate -> plan entry ------------------------------------------------------------
    def plan(self, index: int, cand: Any) -> Dict[str, Any]:
        if isinstance(cand, str):
            cand = {"text": cand}
        if not isinstance(cand, dict):
            raise PlanError("candidate %d must be a JSON object or string, got %s" % (index, type(cand).__name__))
        w: List[str] = []
        text = str(cand.get("text") or cand.get("title") or "")
        lang = dates.detect_language(text + " " + str(cand.get("title") or ""))
        title = one_line(cand.get("title"))
        when, deadline, reminder, question, ex = self.resolve_dates(cand, text, title or text, lang, w)
        if not title:
            title = one_line(clean_title(ex["remaining"]) or text.strip())
            question = TEXT[lang]["ask"].format(title=title, date=when) if question else None
        notes = self.merge_notes(cand)
        phases = [p for p in (cand.get("phases") or []) if isinstance(p, dict)]
        todos_raw = cand.get("todos") or []
        is_project = bool(phases or todos_raw or cand.get("kind") == "project")
        kind = "project" if is_project else "to-do"
        listing = self.resolve_list(cand, title, notes, w)
        tags, dropped = self.resolve_tags(cand.get("tags"), w)
        checklist = [] if is_project else self.resolve_checklist(cand.get("checklist"), w)
        exact, similar = self.find_duplicates(title, kind) if title else ([], [])
        entry: Dict[str, Any] = {
            "index": index, "kind": kind, "title": title, "notes": notes, "language": lang,
            "list": listing["list"], "list_id": listing["list_id"], "list_kind": listing["list_kind"],
            "list_source": listing["source"], "when": when, "deadline": deadline, "reminder": reminder,
            "tags": tags, "dropped_tags": dropped, "checklist": checklist, "checklist_count": len(checklist),
            "duplicate": bool(exact), "duplicates": exact, "similar": similar,
            "needs_question": question is not None, "question": question,
            "headings": [], "todos": [], "method": "add", "command": None, "payload": None, "warnings": w,
        }
        if not title:
            w.append("candidate %d has no title; skipped" % index)
            entry["method"] = "skip"
            return entry
        if is_project and listing["list_kind"] == "project":
            w.append("a project cannot live inside another project; using its area instead")
            parent = self._find(self.projects, listing["list_id"] or listing["list"] or "") or {}
            area_title = parent.get("area_title")
            found = self._find(self.areas, area_title) if area_title else None
            entry["list"], entry["list_id"] = (found["title"], found["uuid"]) if found else (None, None)
            entry["list_kind"] = "area" if found else "inbox"
        if not is_project:
            entry["command"] = self.cmd_add(entry)
            return entry
        rich = False
        for phase in phases:
            heading = {"title": str(phase.get("title") or "").strip(), "todos": []}
            for raw in phase.get("todos") or []:
                heading["todos"].append(self.nested_todo(raw, lang, w))
            if heading["title"]:
                entry["headings"].append(heading)
            else:
                entry["todos"].extend(heading["todos"])
        for raw in todos_raw:
            entry["todos"].append(self.nested_todo(raw, lang, w))
        for todo in entry["todos"] + [t for h in entry["headings"] for t in h["todos"]]:
            if todo["notes"] or todo["when"] or todo["deadline"] or todo["tags"] or todo["checklist"]:
                rich = True
        if entry["headings"] or rich:
            entry["method"] = "add-json"
            entry["payload"] = self.json_project(entry)
        else:
            entry["method"] = "add-project"
            entry["command"] = self.cmd_add_project(entry)
        return entry

    # --- command and payload builders (values already in F.1 vocabulary) ------------------------
    # Options go first in `--flag=value` form and the title last after `--`: a value such as `-v` or
    # `-draft` has no space, so shlex leaves it bare and argparse would read it as an option.
    def cmd_add(self, e: Dict[str, Any]) -> str:
        parts = [self.base(), "add"]
        if e["notes"]:
            parts.append("--notes=" + q(e["notes"]))
        if e["when"]:
            parts.append("--when=" + q(e["when"]))
        if e["deadline"]:
            parts.append("--deadline=" + q(e["deadline"]))
        if e["tags"]:
            parts.append("--tags=" + q(",".join(e["tags"])))
        for step in e["checklist"]:
            parts.append("--checklist=" + q(step))
        if e["list_id"]:
            parts.append("--list-id=" + q(e["list_id"]))
        elif e["list"]:
            parts.append("--list=" + q(e["list"]))
        parts += ["--", q(e["title"])]
        return " ".join(parts)

    def cmd_add_project(self, e: Dict[str, Any]) -> str:
        parts = [self.base(), "add-project"]
        if e["notes"]:
            parts.append("--notes=" + q(e["notes"]))
        if e["when"]:
            parts.append("--when=" + q(e["when"]))
        if e["deadline"]:
            parts.append("--deadline=" + q(e["deadline"]))
        if e["tags"]:
            parts.append("--tags=" + q(",".join(e["tags"])))
        if e["list_id"]:
            parts.append("--area-id=" + q(e["list_id"]))
        elif e["list"]:
            parts.append("--area=" + q(e["list"]))
        for todo in e["todos"]:
            parts.append("--todo=" + q(todo["title"]))
        parts += ["--", q(e["title"])]
        return " ".join(parts)

    def cmd_add_json(self, path: str) -> str:
        return " ".join([self.base(), "add-json", q(path)])

    @staticmethod
    def _attrs(item: Dict[str, Any]) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {"title": item["title"]}
        for key in ("notes", "when", "deadline"):
            if item.get(key):
                attrs[key] = item[key]
        if item.get("tags"):
            attrs["tags"] = list(item["tags"])
        return attrs

    def json_project(self, e: Dict[str, Any]) -> Dict[str, Any]:
        attrs = self._attrs(e)
        if e["list_id"]:
            attrs["area-id"] = e["list_id"]
        elif e["list"]:
            attrs["area"] = e["list"]
        items: List[Dict[str, Any]] = []
        for heading in e["headings"]:
            items.append({"type": "heading", "attributes": {"title": heading["title"]}})
            items.extend(self._todo_object(t) for t in heading["todos"])
        items.extend(self._todo_object(t) for t in e["todos"])
        if items:
            attrs["items"] = items
        return {"type": "project", "attributes": attrs}

    def _todo_object(self, todo: Dict[str, Any]) -> Dict[str, Any]:
        attrs = self._attrs(todo)
        if todo.get("checklist"):
            attrs["checklist-items"] = [{"type": "checklist-item", "attributes": {"title": s}}
                                        for s in todo["checklist"]]
        return {"type": "to-do", "attributes": attrs}


def preview_markdown(entries: List[Dict[str, Any]], lang: str, payload_files: Dict[int, str]) -> str:
    t = TEXT[lang]
    lines = ["| " + " | ".join(t["headers"]) + " |", "|---|---|---|---|---|---|"]
    for e in entries:
        list_name = e["list"] or t["inbox"]
        if e["kind"] == "project":
            n_todos = len(e["todos"]) + sum(len(h["todos"]) for h in e["headings"])
            count = (t["headings"].format(h=len(e["headings"]), n=n_todos) if e["headings"]
                     else t["todos"].format(n=n_todos))
        else:
            count = str(e["checklist_count"])
        lines.append("| %d. %s | %s | %s | %s | %s | %s |" % (
            e["index"], cell(e["title"]), cell(list_name), cell(e["when"]), cell(e["deadline"]),
            cell(", ".join(e["tags"])), cell(count)))
        for heading in e["headings"]:
            lines.append("| &nbsp;&nbsp;## %s | %s | - | - | - | - |" % (cell(heading["title"]), cell(e["title"])))
            for todo in heading["todos"]:
                lines.append("| &nbsp;&nbsp;&nbsp;&nbsp;- %s | %s | %s | %s | %s | %d |" % (
                    cell(todo["title"]), cell(heading["title"]), cell(todo["when"]),
                    cell(todo["deadline"]), cell(", ".join(todo["tags"])), len(todo["checklist"])))
        for todo in e["todos"]:
            lines.append("| &nbsp;&nbsp;- %s | %s | %s | %s | %s | %d |" % (
                cell(todo["title"]), cell(e["title"]), cell(todo["when"]), cell(todo["deadline"]),
                cell(", ".join(todo["tags"])), len(todo["checklist"])))
    flags: List[str] = []
    for e in entries:
        for dup in e["duplicates"]:
            flags.append("- [%d] %s: %s (%s)" % (e["index"], t["dup"], dup["title"], dup["link"]))
        if e["question"]:
            flags.append("- [%d] %s: %s" % (e["index"], t["question"], e["question"]))
        for message in e["warnings"]:
            flags.append("- [%d] %s" % (e["index"], message))
    if flags:
        lines += [""] + flags
    for index, path in sorted(payload_files.items()):
        lines.append("- [%d] %s: %s" % (index, t["payload"], path))
    return "\n".join(lines)


def commands_markdown(commands: List[Dict[str, Any]], blocked: List[Dict[str, Any]], lang: str) -> str:
    """The ```sh block: one comment + one command per runnable entry; a blocked entry is a comment only."""
    lines = ["```sh"]
    by_index = {c["index"]: ("command", c) for c in commands}
    by_index.update({b["index"]: ("blocked", b) for b in blocked})
    for index in sorted(by_index):
        kind, c = by_index[index]
        if kind == "blocked":
            lines.append("# [%d] %s — %s" % (index, one_line(c["title"]), TEXT[lang]["blocked"]))
        else:
            lines.append("# [%d] %s" % (index, one_line(c["title"])))
            lines.append(c["command"])
    lines.append("```")
    return "\n".join(lines)


def prune_payloads(directory: str) -> None:
    """Remove this user's add-json payload files older than PAYLOAD_TTL_SECONDS (they hold task text)."""
    cutoff = time.time() - PAYLOAD_TTL_SECONDS
    for old in glob.glob(os.path.join(directory, "things-capture-*.json")):
        try:
            st = os.stat(old)
            if st.st_uid == os.getuid() and st.st_mtime < cutoff:
                os.remove(old)
        except OSError:
            pass


def write_payloads(entries: List[Dict[str, Any]], planner: Planner) -> Dict[int, str]:
    """One add-json file per project with headings, so numbered selection stays possible.

    A project still waiting for the start-or-deadline answer gets no file: the payload would carry the
    unconfirmed `when`, and the entry must have no command until the planner is re-run.
    """
    pending = [e for e in entries if e["method"] == "add-json" and not e["needs_question"]]
    files: Dict[int, str] = {}
    epoch = int(time.time())
    tmpdir = os.environ.get("TMPDIR") or "/tmp"
    if pending:
        prune_payloads(tmpdir)
    for e in pending:
        suffix = "" if len(pending) == 1 else "-%d" % e["index"]
        fd, path = create_private_file(tmpdir, "things-capture-%d%s" % (epoch, suffix), ".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump([e["payload"]], handle, ensure_ascii=False, indent=2)
        e["command"] = planner.cmd_add_json(path)
        e["payload_file"] = path
        files[e["index"]] = path
    return files


def create_private_file(directory: str, stem: str, suffix: str) -> Tuple[int, str]:
    """Create <stem><suffix> exclusively with mode 0600; on collision append -1, -2, ... to the stem."""
    counter = 0
    while True:
        name = "%s%s%s" % (stem, "-%d" % counter if counter else "", suffix)
        path = os.path.join(directory, name)
        try:
            return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), path
        except FileExistsError:
            counter += 1


def load_candidates(source: Optional[str], inline: Optional[str] = None) -> List[Any]:
    """Candidates from --candidates-json (inline), else --input FILE, else stdin."""
    try:
        if inline is not None:
            raw = inline
        elif source and source != "-":
            with open(source, encoding="utf-8") as handle:
                raw = handle.read()
        else:
            raw = sys.stdin.read()
    except OSError as exc:
        raise PlanError("cannot read %s: %s" % (source, exc))
    if not raw.strip():
        raise PlanError("no candidates given (expected a JSON array via --candidates-json or stdin)")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PlanError("invalid JSON: %s" % exc)
    if isinstance(data, dict):
        data = data.get("candidates", [data])
    if not isinstance(data, list):
        raise PlanError("expected a JSON array of candidates")
    return data


def fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    return 1


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Plan a things-capture write: preview + wrapper commands.")
    parser.add_argument("--input", metavar="FILE", help="candidates JSON file (default: stdin)")
    parser.add_argument("--candidates-json", metavar="JSON", help="candidates JSON array given inline instead of stdin")
    parser.add_argument("--now", metavar="ISO", help="freeze now: YYYY-MM-DDTHH:MM")
    parser.add_argument("--config", metavar="PATH", help="config file (default: things_lib rules)")
    parser.add_argument("--cli", default=DEFAULT_CLI, help="wrapper path used in printed commands")
    parser.add_argument("--yes", action="store_true", help="user said 直接建 / just do it: skip confirmation")
    parser.add_argument("--markdown", action="store_true", help="print Markdown instead of JSON")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except PlanError as exc:
        return fail(str(exc))
    except config_mod.ConfigError as exc:
        return fail(str(exc))


def run(args: argparse.Namespace) -> int:
    now = parse_now(args.now)
    cfg = config_mod.load_config(args.config)
    planner = Planner(cfg, now, args.cli, args.yes)
    entries = [planner.plan(i, c) for i, c in enumerate(load_candidates(args.input, args.candidates_json), 1)]
    payload_files = write_payloads(entries, planner)
    langs = {e["language"] for e in entries}
    lang = cfg.get("language") if cfg.get("language") in ("zh", "en") else ("zh" if "zh" in langs else "en")
    # A candidate whose start-or-deadline question is still open gets NO command anywhere in the output (it
    # would carry the unconfirmed --when); it is reported under `blocked` until the planner is re-run.
    for e in entries:
        if e["needs_question"]:
            e["command"] = None
    commands = [{"index": e["index"], "title": e["title"], "command": e["command"]}
                for e in entries if e["command"]]
    blocked = [{"index": e["index"], "title": e["title"], "question": e["question"]}
               for e in entries if e["needs_question"]]
    questions = [e["question"] for e in entries if e["question"]]
    # the prompt exists only when something is runnable and no question is pending (Markdown prints the
    # questions instead of the prompt; JSON follows the same rule)
    confirm = None if (args.yes or questions or not commands) else TEXT[lang]["confirm"].format(n=len(commands))
    preview = preview_markdown(entries, lang, payload_files)
    if args.markdown:
        out = [preview, "", commands_markdown(commands, blocked, lang)]
        if planner.warnings:
            out += [""] + ["- " + w for w in planner.warnings]
        if questions:
            out += [""] + questions
        elif confirm:
            out += ["", confirm]
        print("\n".join(out))
        return 0
    for e in entries:
        e.pop("payload", None)
    result = {"ok": True, "now": now.strftime("%Y-%m-%dT%H:%M"), "database": planner.db,
              "reply_language": lang, "mixed": len(langs) > 1, "yes": args.yes,
              "candidates": entries, "commands": commands, "blocked": blocked, "payload_files": payload_files,
              "questions": questions, "confirm_prompt": confirm, "preview_markdown": preview,
              "warnings": planner.warnings}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
