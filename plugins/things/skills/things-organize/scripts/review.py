#!/usr/bin/env python3
"""things-organize helper: build the numbered review proposal, then batch the user's picks.

Read-only. Every Things read goes through things_lib.read; nothing is ever sent to Things.
The commands it prints are for the model to run AFTER the user has picked numbers.

  review.py [--scope inbox|today|all|<area or project>] [--now YYYY-MM-DDTHH:MM]
            [--lang auto|zh|en] [--text INVOCATION] [--config PATH] [--cli PATH] [--markdown]
  review.py --apply "1,3,5b" [--from FILE] [--cli PATH] [--markdown]

Printed commands start with `--cli` (default: the ABSOLUTE path of the sibling scripts/things wrapper;
Claude Code substitutes ${CLAUDE_SKILL_DIR} only in SKILL.md text, never in tool output, so the model
can paste the printed lines unchanged); it is never shell-quoted.

Exit codes: 0 ok, 1 usage/config/scope/selection error, 3 Things database unavailable.
"""
import argparse
import glob
import json
import os
import re
import shlex
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts"))
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from things_lib import config as config_mod  # noqa: E402
from things_lib import dates, read  # noqa: E402
from things_lib.url import show_url  # noqa: E402

DEFAULT_CLI = os.path.join(HERE, "things")
SAVED_PREFIX = "things-organize-"
SAVED_TTL_SECONDS = 24 * 3600  # saved reviews hold task titles; this user's older ones are pruned on each run
MAX_IDS_PER_COMMAND = 10  # the CLI demands --yes above this; skills never pass --yes
# The only CLI verbs a saved review may ask the model to run (SKILL.md step 4 promises exactly these).
ALLOWED_SUBS = frozenset(("schedule", "move", "deadline", "tag", "cancel", "complete", "update", "add"))
EVENING_TIME = "18:00"
DO_NOW_MAX_LEN = 40
CHECK_ORDER = ["inbox", "today", "stale", "deadline", "tags", "evening", "someday"]
PLAN = {
    "all": CHECK_ORDER,
    "inbox": ["inbox"],
    "today": ["today", "deadline", "evening"],
    "area": ["stale", "deadline", "tags", "evening", "someday"],
    "project": ["stale", "deadline", "tags", "evening", "someday"],
}

# Communication verbs only, at the start of the title or as verb + object: bare send/ask/confirm/book and
# 确认/预约 flagged 'Read the book' / 'Confirm architecture with team' / '确认需求文档终稿' as two-minute tasks.
DO_NOW_RE = re.compile(
    r"^(call|phone|ring|email|e-mail|reply(?: to)?|respond to|text|ping|rsvp)\b"
    r"|\b(call|phone|email|e-mail|text|ping) (?:back|him|her|them|(?-i:[A-Z])[\w-]*)\b"
    r"|^(打电话|回电|回复|回邮件|发邮件|发个|发给|发一下|问一下|问问|转发|回一下)"
    r"|(打电话|回电|回邮件|发邮件)$",
    re.IGNORECASE)
EVENING_RE = re.compile(
    r"\b(gym|workout|work out|yoga|jog|jogging|groceries|grocery|laundry|dinner|cook|cooking"
    r"|call (?:home|mom|dad|mum|parents|family))\b"
    r"|(健身|跑步|瑜伽|买菜|超市|洗衣|做饭|晚饭|晚餐|给家里打电话|给爸妈|给父母|家里的事|遛狗|接孩子)",
    re.IGNORECASE)
# (regex over title+notes, candidate vocabulary names). A tag is proposed only when one of the
# candidate names is in config.tags AND exists in Things.
TAG_HINTS = [
    (re.compile(r"\b(call|phone|email|e-mail|reply|respond|text|ping)\b|打电话|回电|回复|邮件|发消息|联系", re.I),
     ("@calls", "calls", "call", "电话")),
    (re.compile(r"\b(buy|pick up|pickup|return|drop off|groceries|errand|post office|pharmacy)\b|买|取|寄|退货|药店|超市|跑腿", re.I),
     ("@errands", "errands", "errand", "跑腿")),
    (re.compile(r"\b(write|draft|design|plan|research|review|read|study|analy[sz]e|prepare)\b|写|设计|研究|规划|复习|阅读|分析|准备", re.I),
     ("@deep", "deep", "deep work", "deepwork", "专注")),
    (re.compile(r"\b(waiting|wait for|blocked|pending|follow up|followup)\b|等待|等.*回复|跟进|待回复", re.I),
     ("@waiting", "waiting", "wait", "等待")),
]

TEXT = {
    "en": {
        "check_inbox": "Inbox zero",
        "check_today": "Today overload",
        "check_stale": "Stale Anytime items (untouched over {days} days)",
        "check_deadline": "Deadline sanity",
        "check_tags": "Tag hygiene",
        "check_evening": "Evening candidates",
        "check_someday": "Someday resurfacing (parked over {days} days)",
        "header": "Things review — scope {scope} — {now} — DRY RUN, nothing has been written",
        "counts": "Open items {open} · Inbox {inbox} · Today {today}/{cap} · stale {stale} · Someday to resurface {someday}",
        "nothing": "nothing to do",
        "n_proposals": "{n} proposals",
        "n_proposals_one": "1 proposal",
        "footer": "Reply with the numbers to apply (1,3 or 2b or 1-4), all, or none.",
        "apply_note": "Run each command exactly as printed, in order; fill in <...> placeholders first.",
        "apply_empty": "nothing selected; nothing will be written",
        "opt_apply": "apply",
        "loc_inbox": "Inbox",
        "loc_today": "Today",
        "loc_evening": "This Evening",
        "loc_upcoming": "Upcoming",
        "loc_someday": "Someday",
        "loc_anytime": "Anytime",
        "route_project": "move to project “{project}”",
        "route_area": "move to area “{area}”",
        "route_none": "no routing hint matched, pick an area ({areas})",
        "route_missing": "routing hint matched {kind} “{target}” but Things has no such {kind}: create it or pick an area ({areas})",
        "route_none_noareas": "no routing hint matched and Things has no areas yet: create one, or for a to-do name a project ({projects})",
        "route_missing_noareas": "routing hint matched {kind} “{target}” but Things has no such {kind} and no areas yet: create it, or for a to-do name a project ({projects})",
        "sep": "; ",
        "list_sep": ", ",
        "kind_project": "project",
        "kind_area": "area",
        "orphan_project": "project with no area: {route}",
        "when_found": "start {when}",
        "when_none": "no date in the text, lands in Anytime",
        "deadline_found": "deadline {deadline}",
        "deadline_none": "no deadline needed",
        "tags_add": "add tags {tags}",
        "do_now": "DO NOW (under 2 minutes)",
        "opt_complete": "already done: mark complete",
        "today_ok": "{count} to-dos in Today, cap {cap}: within the cap",
        "today_over": "{count} to-dos in Today, cap {cap}: push {excess} out; items due within {lead} days stay",
        "push_tomorrow": "push to tomorrow (deadline {deadline} is beyond the {lead}-day lead)",
        "push_anytime": "push to Anytime (no deadline)",
        "push_someday": "push to Someday (in Today since {start}, no deadline)",
        "opt_tomorrow": "tomorrow instead",
        "opt_anytime": "Anytime instead",
        "opt_someday": "Someday instead",
        "stale_default": "untouched for {age} days: park in Someday",
        "opt_cancel": "cancel it",
        "opt_decide": "add a 15-minute “{title}” to-do in Today",
        "decide_prefix": "Decide: ",
        "decide_notes": "15 minutes: keep it, park it in Someday, or cancel it. {link}",
        "dl_before_start": "deadline {deadline} is before start {start}: start {when} instead",
        "opt_dl_to_start": "move the deadline to the start date {start}",
        "dl_past": "deadline {deadline} passed {days} days ago: clear it if it was never a hard date",
        "opt_dl_new": "set a new deadline (fill in the date)",
        "dl_soon": "due in {days} days with no start date: start today",
        "orphan": "no area or project: {route}",
        "vocab_keep": "tags outside the vocabulary ({bad}): keep only {keep}",
        "vocab_clear": "tags outside the vocabulary ({bad}): clear the tags",
        "evening_today": "reads as a personal-evening item: move to This Evening",
        "evening_other": "reads as a personal-evening item but is not in Today: schedule {when} (18:00 reminder)",
        "someday_default": "parked in Someday for {age} days: bring back to Anytime",
        "warn_repeating": "deadline check skipped repeating to-do “{title}”: when/deadline can only be changed in Things (moving it to an area or project still works)",
        "warn_tags_empty": "config.tags is empty: tag vocabulary check skipped",
        "warn_repeating_hint": "Repeating to-dos may be missing: things.py only sees instances Things has already generated. Open Things once to refresh.",
        "warn_anytime": "when=anytime is undocumented for update; the CLI will warn, check the result in Things",
    },
    "zh": {
        "check_inbox": "清空收件箱",
        "check_today": "Today 超载",
        "check_stale": "陈旧的 Anytime 事项（超过 {days} 天未动）",
        "check_deadline": "截止日期检查",
        "check_tags": "标签与归属检查",
        "check_evening": "晚上做的事",
        "check_someday": "Someday 回收（搁置超过 {days} 天）",
        "header": "Things 回顾 — 范围 {scope} — {now} — 预演，尚未写入任何内容",
        "counts": "未完成 {open} · 收件箱 {inbox} · Today {today}/{cap} · 陈旧 {stale} · 待回收的 Someday {someday}",
        "nothing": "无需处理",
        "n_proposals": "{n} 条建议",
        "n_proposals_one": "1 条建议",
        "footer": "回复要执行的编号（如 1,3、2b 或 1-4）、全部，或 不用。",
        "apply_note": "按顺序逐条运行下面的命令，先把 <...> 占位符填好。",
        "apply_empty": "没有选中任何建议，不会写入任何内容",
        "opt_apply": "执行",
        "loc_inbox": "收件箱",
        "loc_today": "Today",
        "loc_evening": "今晚",
        "loc_upcoming": "Upcoming",
        "loc_someday": "Someday",
        "loc_anytime": "Anytime",
        "route_project": "移到项目「{project}」",
        "route_area": "移到领域「{area}」",
        "route_none": "没有匹配的路由规则（config.routing_hints），请选一个领域（{areas}）",
        "route_missing": "路由规则命中{kind}「{target}」，但 Things 里没有这个{kind}：请先创建，或从（{areas}）中选一个领域",
        "route_none_noareas": "没有匹配的路由规则，且 Things 里还没有领域：先创建一个，或（待办）填一个项目（{projects}）",
        "route_missing_noareas": "路由规则命中{kind}「{target}」，但 Things 里没有这个{kind}，也还没有领域：请先创建，或（待办）填一个项目（{projects}）",
        "sep": "；",
        "list_sep": "、",
        "kind_project": "项目",
        "kind_area": "领域",
        "orphan_project": "项目没有领域：{route}",
        "when_found": "开始时间 {when}",
        "when_none": "文中没有日期，进入 Anytime",
        "deadline_found": "截止 {deadline}",
        "deadline_none": "不需要截止日期",
        "tags_add": "加标签 {tags}",
        "do_now": "马上做（不到 2 分钟）",
        "opt_complete": "已经做完：标记完成",
        "today_ok": "Today 有 {count} 个待办，上限 {cap}：未超载",
        "today_over": "Today 有 {count} 个待办，上限 {cap}：移出 {excess} 个；{lead} 天内到期的保留",
        "push_tomorrow": "推到明天（截止 {deadline} 在 {lead} 天提前期之外）",
        "push_anytime": "推到 Anytime（没有截止日期）",
        "push_someday": "推到 Someday（从 {start} 起一直在 Today，没有截止日期）",
        "opt_tomorrow": "改为明天",
        "opt_anytime": "改为 Anytime",
        "opt_someday": "改为 Someday",
        "stale_default": "{age} 天未动：放进 Someday",
        "opt_cancel": "取消",
        "opt_decide": "在 Today 新建 15 分钟的「{title}」待办",
        "decide_prefix": "决定：",
        "decide_notes": "15 分钟：保留、放进 Someday，还是取消？{link}",
        "dl_before_start": "截止 {deadline} 早于开始 {start}：改为 {when} 开始",
        "opt_dl_to_start": "把截止日期改到开始日期 {start}",
        "dl_past": "截止 {deadline} 已过 {days} 天：如果本来不是硬性日期就清掉",
        "opt_dl_new": "设一个新截止日期（填日期）",
        "dl_soon": "{days} 天内到期但没有开始日期：今天开始",
        "orphan": "没有领域也没有项目：{route}",
        "vocab_keep": "标签不在词表内（{bad}）：只保留 {keep}",
        "vocab_clear": "标签不在词表内（{bad}）：清空标签",
        "evening_today": "像是晚上的私事：移到今晚",
        "evening_other": "像是晚上的私事但不在 Today：安排到 {when}（18:00 提醒）",
        "someday_default": "在 Someday 搁置了 {age} 天：拿回 Anytime",
        "warn_repeating": "截止日期检查跳过了重复任务「{title}」：when/deadline 只能在 Things 里改（移到领域/项目仍可执行）",
        "warn_tags_empty": "config.tags 为空：跳过标签词表检查",
        "warn_repeating_hint": "重复任务可能不完整：things.py 只能看到 Things 已生成的实例，请先打开一次 Things。",
        "warn_anytime": "update 的 when=anytime 未见文档，CLI 会给出警告，请在 Things 里确认结果",
    },
}


class ScopeError(Exception):
    """Unknown --scope value."""


def T(lang: str, key: str, **kw: Any) -> str:
    table = TEXT.get(lang) or TEXT["en"]
    return (table.get(key) or TEXT["en"][key]).format(**kw)


def count_words(lang: str, n: int) -> str:
    """Check summary tail: 'nothing to do' / '1 proposal' / '{n} proposals'."""
    if n == 0:
        return T(lang, "nothing")
    if n == 1:
        return T(lang, "n_proposals_one")
    return T(lang, "n_proposals", n=n)


def pick_lang(flag: str, cfg: Dict, text: Optional[str]) -> str:
    """Explicit --lang zh|en wins (the user asked for it); else config.language; else detect from the invocation."""
    if flag in ("zh", "en"):
        return flag
    if cfg.get("language") in ("zh", "en"):
        return cfg["language"]
    return dates.detect_language(text) if text else "en"


def parse_now(text: Optional[str]) -> datetime:
    if not text:
        return datetime.now().replace(second=0, microsecond=0)
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError("invalid --now value %r; use YYYY-MM-DDTHH:MM" % text)


def iso_or_keyword(day: date, today: date) -> str:
    if day <= today:
        return "today"
    if day == today + timedelta(days=1):
        return "tomorrow"
    return day.isoformat()


def option(label: str, sub: str, ids: List[str], flags: List[str],
           batchable: bool = True, needs_input: bool = False) -> Dict[str, Any]:
    return {"label": label, "sub": sub, "ids": list(ids), "flags": [str(f) for f in flags],
            "batchable": bool(batchable) and not needs_input, "needs_input": bool(needs_input)}


def render(cli: str, sub: str, ids: List[str], flags: List[str]) -> str:
    """`cli` is printed verbatim (the wrapper path, an absolute path); everything else is shell-quoted."""
    return " ".join([cli, shlex.quote(sub)] + [shlex.quote(part) for part in list(ids) + list(flags)])


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


def location(item: Dict, ctx: Dict) -> str:
    lang = ctx["lang"]
    uid = item.get("uuid")
    if item.get("start") == "Inbox":
        bucket = T(lang, "loc_inbox")
    elif uid in ctx["today_ids"]:
        bucket = T(lang, "loc_evening") if uid in ctx["evening_ids"] else T(lang, "loc_today")
    elif item.get("start_date") and item["start_date"] > ctx["today"].isoformat():
        bucket = T(lang, "loc_upcoming")
    elif item.get("start") == "Someday":
        bucket = T(lang, "loc_someday")
    else:
        bucket = T(lang, "loc_anytime")
    container = item.get("project_title") or item.get("heading_title") or item.get("area_title")
    return "%s · %s" % (bucket, container) if container else bucket


def proposal(ctx: Dict, check: str, item: Dict, action: str, options: List[Dict],
             do_now: bool = False) -> Dict[str, Any]:
    return {"n": 0, "check": check, "id": item["uuid"], "type": item.get("type"),
            "title": item.get("title") or "", "link": item.get("link") or show_url(item["uuid"]),
            "location": location(item, ctx), "action": action, "do_now": do_now, "options": options}


def is_do_now(title: str) -> bool:
    text = (title or "").strip()
    return 0 < len(text) <= DO_NOW_MAX_LEN and DO_NOW_RE.search(text) is not None


def looks_evening(text: str) -> bool:
    return EVENING_RE.search(text or "") is not None


def suggest_tags(text: str, ctx: Dict) -> List[str]:
    allowed = {t.casefold(): t for t in ctx["allowed_tags"]}
    out: List[str] = []
    for regex, names in TAG_HINTS:
        if not regex.search(text):
            continue
        for name in names:
            tag = allowed.get(name.casefold())
            if tag and tag not in out:
                out.append(tag)
                break
    return out


def canonical(name: Optional[str], titles: List[str]) -> Optional[str]:
    if not name:
        return None
    for title in titles:
        if title.casefold() == name.casefold():
            return title
    return None


def in_scope(ids: Optional[Set[str]], item: Dict) -> bool:
    return ids is None or item.get("uuid") in ids


def load_context(cfg: Dict, now: datetime, lang: str) -> Dict[str, Any]:
    """Run every read once (things_lib.read) and index what the checks need."""
    ctx: Dict[str, Any] = {"config": cfg, "now": now, "today": now.date(), "lang": lang, "warnings": []}
    ctx["areas"] = read.areas()
    ctx["projects"] = read.projects(None, now)
    headings = read.tasks_raw(type="heading", status="incomplete")
    repeating = read.repeating_uuids()
    universe: List[Dict] = []
    for raw in read.tasks_raw(type=None, status="incomplete"):
        if raw.get("trashed") or raw.get("type") not in ("to-do", "project"):
            continue
        universe.append(read.enrich(raw, now, repeating))
    ctx["universe"] = universe
    ctx["inbox"] = read.inbox(now)
    ctx["today_items"] = read.today(now)
    ctx["stale"] = read.stale(cfg["stale_days"], now)
    ctx["someday"] = read.someday(now)
    tag_titles = read.tag_titles()
    ctx["warnings"].extend(read.take_warnings())
    ctx["today_ids"] = {i["uuid"] for i in ctx["today_items"]}
    ctx["evening_ids"] = {i["uuid"] for i in ctx["today_items"] if i.get("evening")}
    ctx["area_titles"] = [a.get("title") or "" for a in ctx["areas"]]
    ctx["project_titles"] = [p.get("title") or "" for p in ctx["projects"]]
    ctx["allowed_tags"] = [t for t in (cfg.get("tags") or []) if t in tag_titles]
    project_area = {p["uuid"]: p.get("area") for p in ctx["projects"]}
    heading_project = {h["uuid"]: h.get("project") for h in headings}

    def container_of(item: Dict) -> Tuple[Optional[str], Optional[str]]:
        proj = item.get("project") or heading_project.get(item.get("heading") or "")
        area = item.get("area") or project_area.get(proj or "")
        return proj, area

    ctx["container_of"] = container_of
    return ctx


def resolve_scope(scope: Optional[str], ctx: Dict) -> Tuple[str, Optional[Set[str]], str]:
    """-> (kind, restricted uuid set or None, label). kind: all | inbox | today | area | project."""
    key = (scope or "all").strip().casefold()
    if key in ("", "all", "full", "review", "weekly", "全部", "所有", "周回顾", "全面"):
        return "all", None, "all"
    if key in ("inbox", "收件箱"):
        return "inbox", None, "inbox"
    if key in ("today", "今天", "今日"):
        return "today", None, "today"
    for area in ctx["areas"]:
        if key in (area["uuid"].casefold(), (area.get("title") or "").casefold()):
            ids = {i["uuid"] for i in ctx["universe"]
                   if i["uuid"] == area["uuid"] or ctx["container_of"](i)[1] == area["uuid"]}
            return "area", ids, area.get("title") or area["uuid"]
    for proj in ctx["projects"]:
        if key in (proj["uuid"].casefold(), (proj.get("title") or "").casefold()):
            ids = {i["uuid"] for i in ctx["universe"]
                   if i["uuid"] == proj["uuid"] or ctx["container_of"](i)[0] == proj["uuid"]}
            return "project", ids, proj.get("title") or proj["uuid"]
    raise ScopeError("unknown scope %r; use inbox, today, all, or an area/project name. areas: %s; projects: %s"
                     % (scope, ", ".join(ctx["area_titles"]) or "-", ", ".join(ctx["project_titles"]) or "-"))


def resolve_route(ctx: Dict, item: Dict) -> Tuple[str, str, str, bool]:
    """-> (words, target title, 'project'|'area', needs_input) from config.routing_hints."""
    lang = ctx["lang"]
    areas = T(lang, "list_sep").join(ctx["area_titles"]) or "-"
    projects = T(lang, "list_sep").join(ctx.get("project_titles") or []) or "-"
    # Things without any area: 'pick an area (-)' offers nothing, so name the projects a to-do may go to instead
    # (config.areas is informational only, README; it is not a vocabulary). The '<AREA>' slot stays.
    suffix = "" if ctx["area_titles"] else "_noareas"
    route = config_mod.route(item.get("title") or "", item.get("notes") or "", ctx["config"])
    if route:
        proj = canonical(route.get("project"), ctx["project_titles"])
        if proj and item.get("type") == "to-do":
            return T(lang, "route_project", project=proj), proj, "project", False
        area = canonical(route.get("area"), ctx["area_titles"])
        if area:
            return T(lang, "route_area", area=area), area, "area", False
        # the hint matched but its target is not in Things: say so instead of 'no routing hint matched'
        kind = "area" if route.get("area") else "project"
        words = T(lang, "route_missing" + suffix, kind=T(lang, "kind_project") if kind == "project" else T(lang, "kind_area"),
                  target=route.get("area") or route.get("project"), areas=areas, projects=projects)
        return words, "<AREA>", "area", True
    return T(lang, "route_none" + suffix, areas=areas, projects=projects), "<AREA>", "area", True


def check_inbox(ctx: Dict) -> Tuple[List[Dict], str]:
    lang, cfg = ctx["lang"], ctx["config"]
    props: List[Dict] = []
    for item in ctx["inbox"]:
        uid = item["uuid"]
        title = item.get("title") or ""
        notes = item.get("notes") or ""
        text = title + "\n" + notes
        words, target, _kind, needs_input = resolve_route(ctx, item)
        flags = ["--list", target]
        parts = [words]
        parsed = dates.extract_dates(title + " " + notes.replace("\n", " "), ctx["now"],
                                     cfg.get("default_reminder_time") or "09:00")
        when, deadline = parsed.get("when"), parsed.get("deadline")
        do_now = is_do_now(title)
        if do_now and not when:
            when = "today"
        if when and when != "anytime":
            flags += ["--when", when]
            parts.append(T(lang, "when_found", when=when))
        else:
            parts.append(T(lang, "when_none"))
        if deadline:
            flags += ["--deadline", deadline]
            parts.append(T(lang, "deadline_found", deadline=deadline))
        else:
            parts.append(T(lang, "deadline_none"))
        tags = suggest_tags(text, ctx)
        if tags:
            flags += ["--add-tags", ",".join(tags)]
            parts.append(T(lang, "tags_add", tags=", ".join(tags)))
        options = [option(T(lang, "opt_apply"), "update", [uid], flags, batchable=False, needs_input=needs_input)]
        if do_now:
            options.append(option(T(lang, "opt_complete"), "complete", [uid], []))
        props.append(proposal(ctx, "inbox", item, T(lang, "sep").join(parts), options, do_now=do_now))
    return props, count_words(lang, len(props))


def check_today(ctx: Dict) -> Tuple[List[Dict], str]:
    lang, cfg, today = ctx["lang"], ctx["config"], ctx["today"]
    cap, lead = cfg["today_cap"], cfg["deadline_lead_days"]
    todos = [i for i in ctx["today_items"] if i.get("type") == "to-do"]
    excess = len(todos) - cap
    if excess <= 0:
        return [], T(lang, "today_ok", count=len(todos), cap=cap)
    summary = T(lang, "today_over", count=len(todos), cap=cap, excess=excess, lead=lead)

    def urgent(item: Dict) -> bool:
        days = item.get("days_until_deadline")
        return days is not None and days <= lead

    candidates = [i for i in todos if not i.get("repeating") and not urgent(i)]
    candidates.sort(key=lambda i: (i.get("deadline") is not None, i.get("start_date") or "", i.get("modified") or ""))
    props: List[Dict] = []
    for item in candidates[:excess]:
        uid, start = item["uuid"], item.get("start_date")
        lingering = False
        if start:
            try:
                lingering = (today - date.fromisoformat(start)).days >= 7
            except ValueError:
                lingering = False
        if item.get("deadline"):
            when, words = "tomorrow", T(lang, "push_tomorrow", deadline=item["deadline"], lead=lead)
        elif lingering:
            when, words = "someday", T(lang, "push_someday", start=start)
        else:
            when, words = "anytime", T(lang, "push_anytime")
        options = [option(T(lang, "opt_apply"), "schedule", [uid], ["--when", when])]
        for alt in ("tomorrow", "anytime", "someday"):
            if alt != when:
                options.append(option(T(lang, "opt_" + alt), "schedule", [uid], ["--when", alt]))
        props.append(proposal(ctx, "today", item, words, options))
    return props, summary


def check_stale(ctx: Dict, ids: Optional[Set[str]]) -> Tuple[List[Dict], str]:
    lang = ctx["lang"]
    props: List[Dict] = []
    for item in ctx["stale"]:
        if item.get("deadline") or not in_scope(ids, item):
            continue  # items with a deadline are handled by the deadline check
        uid, title = item["uuid"], item.get("title") or ""
        decide_title = TEXT[dates.detect_language(title)]["decide_prefix"] + title
        notes = T(lang, "decide_notes", link=item.get("link") or show_url(uid))
        options = [
            option(T(lang, "opt_apply"), "schedule", [uid], ["--when", "someday"]),
            option(T(lang, "opt_cancel"), "cancel", [uid], []),
            option(T(lang, "opt_decide", title=decide_title), "add", [],
                   [decide_title, "--when", "today", "--notes", notes], batchable=False),
        ]
        props.append(proposal(ctx, "stale", item, T(lang, "stale_default", age=item.get("age_days", 0)), options))
    return props, count_words(lang, len(props))


def check_deadline(ctx: Dict, ids: Optional[Set[str]]) -> Tuple[List[Dict], str]:
    lang, today, lead = ctx["lang"], ctx["today"], ctx["config"]["deadline_lead_days"]
    props: List[Dict] = []
    for item in ctx["universe"]:
        deadline, days = item.get("deadline"), item.get("days_until_deadline")
        if not deadline or days is None or not in_scope(ids, item):
            continue
        uid, start = item["uuid"], item.get("start_date")
        if item.get("repeating"):
            ctx["warnings"].append(T(lang, "warn_repeating", title=item.get("title") or uid))
            continue
        if days < 0:
            words = T(lang, "dl_past", deadline=deadline, days=-days)
            options = [
                option(T(lang, "opt_apply"), "deadline", [uid], ["--clear"]),
                option(T(lang, "opt_complete"), "complete", [uid], []),
                option(T(lang, "opt_cancel"), "cancel", [uid], []),
                option(T(lang, "opt_dl_new"), "deadline", [uid], ["--date", "<YYYY-MM-DD>"], needs_input=True),
            ]
        elif start and start > deadline:
            try:
                target = max(today, date.fromisoformat(deadline) - timedelta(days=lead))
            except ValueError:
                continue
            when = iso_or_keyword(target, today)
            words = T(lang, "dl_before_start", deadline=deadline, start=start, when=when)
            options = [
                option(T(lang, "opt_apply"), "schedule", [uid], ["--when", when]),
                option(T(lang, "opt_dl_to_start", start=start), "deadline", [uid], ["--date", start]),
            ]
        elif days <= lead and not start:
            words = T(lang, "dl_soon", days=days)
            options = [option(T(lang, "opt_apply"), "schedule", [uid], ["--when", "today"])]
        else:
            continue
        props.append(proposal(ctx, "deadline", item, words, options))
    return props, count_words(lang, len(props))


def check_tags(ctx: Dict, ids: Optional[Set[str]]) -> Tuple[List[Dict], str]:
    lang, cfg = ctx["lang"], ctx["config"]
    vocab = cfg.get("tags") or []
    if not vocab:
        ctx["warnings"].append(T(lang, "warn_tags_empty"))
    props: List[Dict] = []
    for item in ctx["universe"]:
        if item.get("start") == "Inbox" or not in_scope(ids, item):
            continue  # Inbox items are routed by the inbox check
        uid = item["uuid"]
        proj, area = ctx["container_of"](item)
        if not proj and not area:
            words, target, kind, needs_input = resolve_route(ctx, item)
            flag = "--list" if kind == "project" else "--area"
            options = [option(T(lang, "opt_apply"), "move", [uid], [flag, target], needs_input=needs_input)]
            orphan_key = "orphan_project" if item.get("type") == "project" else "orphan"
            props.append(proposal(ctx, "tags", item, T(lang, orphan_key, route=words), options))
        if vocab and item.get("tags"):
            bad = [t for t in item["tags"] if t not in vocab]
            if not bad:
                continue
            keep = [t for t in item["tags"] if t in vocab]
            if keep:
                words = T(lang, "vocab_keep", bad=", ".join(bad), keep=", ".join(keep))
                options = [option(T(lang, "opt_apply"), "tag", [uid], ["--set", ",".join(keep)])]
            else:
                words = T(lang, "vocab_clear", bad=", ".join(bad))
                options = [option(T(lang, "opt_apply"), "update", [uid], ["--clear", "tags"], batchable=False)]
            props.append(proposal(ctx, "tags", item, words, options))
    return props, count_words(lang, len(props))


def check_evening(ctx: Dict, ids: Optional[Set[str]]) -> Tuple[List[Dict], str]:
    lang, today = ctx["lang"], ctx["today"]
    tomorrow = (today + timedelta(days=1)).isoformat()
    props: List[Dict] = []
    for item in ctx["universe"]:
        uid = item["uuid"]
        if item.get("type") != "to-do" or item.get("repeating") or uid in ctx["evening_ids"]:
            continue
        if item.get("start") == "Inbox" or (item.get("start") == "Someday" and not item.get("start_date")):
            # Inbox items belong to the inbox check, undated Someday items to the someday check (one proposal per
            # item). things.py reports Upcoming and scheduled-Today items as start='Someday' WITH a start_date;
            # those stay eligible (read.someday() never returns them, so no check would otherwise see them).
            continue
        if not in_scope(ids, item) or not looks_evening((item.get("title") or "") + "\n" + (item.get("notes") or "")):
            continue
        if uid in ctx["today_ids"]:
            when, words = "evening", T(lang, "evening_today")
        else:
            start = item.get("start_date")
            day = start if start and start > today.isoformat() else tomorrow
            when = day + "@" + EVENING_TIME
            words = T(lang, "evening_other", when=when)
        props.append(proposal(ctx, "evening", item, words,
                              [option(T(lang, "opt_apply"), "schedule", [uid], ["--when", when])]))
    return props, count_words(lang, len(props))


def check_someday(ctx: Dict, ids: Optional[Set[str]]) -> Tuple[List[Dict], str]:
    lang, now, limit = ctx["lang"], ctx["now"], ctx["config"]["someday_resurface_days"]
    props: List[Dict] = []
    for item in ctx["someday"]:
        if item.get("repeating") or item.get("type") not in ("to-do", "project") or not in_scope(ids, item):
            continue
        try:
            modified = datetime.strptime(item.get("modified") or "", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        age = (now - modified).days
        if age <= limit:
            continue
        uid = item["uuid"]
        options = [option(T(lang, "opt_apply"), "schedule", [uid], ["--when", "anytime"]),
                   option(T(lang, "opt_cancel"), "cancel", [uid], [])]
        props.append(proposal(ctx, "someday", item, T(lang, "someday_default", age=age), options))
    return props, count_words(lang, len(props))


CHECKS = {"inbox": check_inbox, "today": check_today, "stale": check_stale, "deadline": check_deadline,
          "tags": check_tags, "evening": check_evening, "someday": check_someday}


def finalize(proposals: List[Dict], cli: str) -> None:
    for prop in proposals:
        opts = prop["options"]
        prop["command"] = render(cli, opts[0]["sub"], opts[0]["ids"], opts[0]["flags"])
        prop["needs_input"] = opts[0]["needs_input"]
        prop["alternatives"] = [
            {"key": "%d%s" % (prop["n"], chr(ord("a") + i)), "label": opt["label"],
             "command": render(cli, opt["sub"], opt["ids"], opt["flags"]), "needs_input": opt["needs_input"]}
            for i, opt in enumerate(opts) if i > 0]


def build_review(ctx: Dict, kind: str, ids: Optional[Set[str]], label: str, cli: str = DEFAULT_CLI) -> Dict[str, Any]:
    cfg, lang = ctx["config"], ctx["lang"]
    restrict = ctx["today_ids"] if kind == "today" else ids
    checks: List[Dict] = []
    proposals: List[Dict] = []
    for key in PLAN[kind]:
        props, summary = CHECKS[key](ctx) if key in ("inbox", "today") else CHECKS[key](ctx, restrict)
        for prop in props:
            prop["n"] = len(proposals) + 1
            proposals.append(prop)
        days = cfg["stale_days"] if key == "stale" else cfg["someday_resurface_days"]
        checks.append({"key": key, "name": T(lang, "check_" + key, days=days), "summary": summary,
                       "proposals": [p["n"] for p in props]})
        if key == "today":
            ctx["warnings"].append(T(lang, "warn_repeating_hint"))
    finalize(proposals, cli)
    if any(" --when anytime" in p["command"] for p in proposals):
        ctx["warnings"].append(T(lang, "warn_anytime"))  # whichever check proposed it (today, someday, ...)
    today_todos = [i for i in ctx["today_items"] if i.get("type") == "to-do"]
    seen: List[str] = []
    warnings = [w for w in ctx["warnings"] if not (w in seen or seen.append(w))]
    return {
        "ok": True, "scope": label, "kind": kind, "now": ctx["now"].strftime("%Y-%m-%d %H:%M"),
        "language": lang, "wrapper": cli,
        "settings": {k: cfg[k] for k in ("today_cap", "stale_days", "deadline_lead_days", "someday_resurface_days")},
        "counts": {"open": len(ctx["universe"]), "inbox": len(ctx["inbox"]), "today": len(today_todos),
                   "cap": cfg["today_cap"], "stale": len([i for i in ctx["stale"] if not i.get("deadline")]),
                   "someday": len([p for p in proposals if p["check"] == "someday"])},
        "checks": checks, "proposals": proposals, "warnings": warnings, "saved": None,
    }


def review_markdown(result: Dict) -> str:
    lang = result["language"]
    lines = ["# " + T(lang, "header", scope=result["scope"], now=result["now"]),
             T(lang, "counts", **result["counts"]), ""]
    by_n = {p["n"]: p for p in result["proposals"]}
    for index, check in enumerate(result["checks"], 1):
        lines.append("## %d. %s — %s" % (index, check["name"], check["summary"]))
        for n in check["proposals"]:
            prop = by_n[n]
            flag = " **" + T(lang, "do_now") + "**" if prop.get("do_now") else ""
            kind = " · " + T(lang, "kind_project") if prop.get("type") == "project" else ""
            lines.append("%d. **%s** (%s%s) %s%s" % (n, prop["title"], prop["location"], kind, prop["link"], flag))
            lines.append("   - %s" % prop["action"])
            lines.append("   - `%s`" % prop["command"])
            for alt in prop["alternatives"]:
                lines.append("   - %s) %s — `%s`" % (alt["key"], alt["label"], alt["command"]))
        lines.append("")
    if result["warnings"]:
        lines.extend(["- " + w for w in result["warnings"]] + [""])
    lines.append(T(lang, "footer"))
    lines.append("saved: %s" % result["saved"])
    return "\n".join(lines)


ALL_WORDS = ("all", "全部", "所有", "都", "yes", "y", "好", "好的", "确认", "可以", "ok", "是")
NONE_WORDS = ("", "none", "no", "n", "不用", "不要", "算了", "取消")


def parse_selection(text: str, proposals: List[Dict]) -> List[Tuple[Dict, int]]:
    """'1,3 5b 7-9' -> [(proposal, option index)]. all/全部 -> every default; none/不用 -> []."""
    key = (text or "").strip().casefold()
    if key in ALL_WORDS:
        return [(p, 0) for p in proposals]
    if key in NONE_WORDS:
        return []
    by_n = {p["n"]: p for p in proposals}
    picks: List[Tuple[Dict, int]] = []
    for token in re.split(r"[\s,，、;；]+", key):
        if not token:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?([a-z]?)", token)
        if not match:
            raise ValueError("cannot read selection token %r" % token)
        low, high, letter = int(match.group(1)), int(match.group(2) or match.group(1)), match.group(3)
        for n in range(low, high + 1):
            prop = by_n.get(n)
            if prop is None:
                raise ValueError("no proposal %d" % n)
            index = ord(letter) - ord("a") if letter else 0
            if index >= len(prop["options"]):
                raise ValueError("proposal %d has no option %s" % (n, letter))
            picks.append((prop, index))
    return picks


def batch(picks: List[Tuple[Dict, int]], cli: str = DEFAULT_CLI) -> List[Dict[str, Any]]:
    """Merge batchable picks with identical sub+flags into one command, at most 10 ids each."""
    groups: Dict[Tuple, Dict[str, Any]] = {}
    for prop, index in picks:
        opt = prop["options"][index]
        # a saved review is data from disk: only the fixed verbs and plain strings may reach a printed command
        if not isinstance(opt, dict) or opt.get("sub") not in ALLOWED_SUBS or not all(
                isinstance(x, str) for x in list(opt.get("ids") or []) + list(opt.get("flags") or [])):
            raise ValueError("saved review proposal %s has an unknown command" % prop.get("n"))
        key: Tuple = (opt["sub"], tuple(opt["flags"])) if opt["batchable"] else (opt["sub"], tuple(opt["flags"]), prop["n"], index)
        group = groups.setdefault(key, {"sub": opt["sub"], "flags": opt["flags"], "ids": [], "proposals": [],
                                        "needs_input": opt["needs_input"]})
        for uid in opt["ids"]:
            if uid not in group["ids"]:
                group["ids"].append(uid)
        group["proposals"].append("%d%s" % (prop["n"], chr(ord("a") + index) if index else ""))
    commands: List[Dict[str, Any]] = []
    for group in groups.values():
        chunks = [group["ids"][i:i + MAX_IDS_PER_COMMAND] for i in range(0, len(group["ids"]), MAX_IDS_PER_COMMAND)] or [[]]
        for ids in chunks:
            commands.append({"command": render(cli, group["sub"], ids, group["flags"]), "sub": group["sub"], "ids": ids,
                             "proposals": group["proposals"], "needs_input": group["needs_input"]})
    return commands


def latest_saved() -> Optional[str]:
    files = glob.glob(os.path.join(tempfile.gettempdir(), SAVED_PREFIX + "*.json"))
    return max(files, key=os.path.getmtime) if files else None


def owned_by_me(path: str) -> bool:
    """Only a review file this user created is trusted when --from is omitted."""
    try:
        return os.stat(path).st_uid == os.getuid()
    except OSError:
        return False


def prune_saved(directory: str) -> None:
    """Remove this user's saved reviews older than SAVED_TTL_SECONDS (they hold task titles and notes)."""
    cutoff = time.time() - SAVED_TTL_SECONDS
    for old in glob.glob(os.path.join(directory, SAVED_PREFIX + "*.json")):
        try:
            st = os.stat(old)
            if st.st_uid == os.getuid() and st.st_mtime < cutoff:
                os.remove(old)
        except OSError:
            pass


def valid_saved_proposals(saved: Dict[str, Any]) -> Optional[str]:
    """None when saved['proposals'] is a list of objects with an int `n` and an options list; else the problem."""
    proposals = saved.get("proposals")
    if not isinstance(proposals, list):
        return "saved review has no proposals list"
    for prop in proposals:
        if not isinstance(prop, dict) or not isinstance(prop.get("n"), int) or not isinstance(prop.get("options"), list):
            return "saved review proposal is malformed (expected an object with an integer n and an options list)"
    return None


def fail(message: str, code: int) -> int:
    sys.stderr.write("error: %s\n" % message)
    print(json.dumps({"ok": False, "error": message, "proposals": [], "commands": [], "warnings": []}, ensure_ascii=False))
    return code


def run_review(args: argparse.Namespace) -> int:
    try:
        now = parse_now(args.now)
        cfg = config_mod.load_config(args.config)
    except (ValueError, config_mod.ConfigError) as exc:
        return fail(str(exc), 1)
    lang = pick_lang(args.lang, cfg, args.text)
    try:
        ctx = load_context(cfg, now, lang)
        kind, ids, label = resolve_scope(args.scope, ctx)
    except read.ReadError as exc:
        return fail("Things database unavailable: %s" % exc, 3)
    except ScopeError as exc:
        return fail(str(exc), 1)
    result = build_review(ctx, kind, ids, label, args.cli)
    prune_saved(tempfile.gettempdir())
    fd, result["saved"] = create_private_file(tempfile.gettempdir(),
                                              "%s%d-%d" % (SAVED_PREFIX, int(time.time()), os.getpid()), ".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)
    print(review_markdown(result) if args.markdown else json.dumps(result, ensure_ascii=False))
    return 0


def run_apply(args: argparse.Namespace) -> int:
    path = args.from_file or latest_saved()
    if not path or not os.path.isfile(path):
        return fail("no saved review found; run review.py --scope ... first", 1)
    if not args.from_file and not owned_by_me(path):
        return fail("newest saved review %s belongs to another user; pass --from <your saved path>" % path, 1)
    try:
        with open(path, encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError) as exc:
        return fail("saved review %s is not readable JSON: %s" % (path, exc), 1)
    if not isinstance(saved, dict):
        return fail("saved review %s must be a JSON object" % path, 1)
    problem = valid_saved_proposals(saved)
    if problem:
        return fail("%s: %s" % (problem, path), 1)
    lang = saved.get("language") or "en"
    try:
        picks = parse_selection(args.apply, saved["proposals"])
        commands = batch(picks, args.cli)
    except ValueError as exc:
        return fail(str(exc), 1)
    result = {"ok": True, "from": path, "language": lang, "selected": sorted({p["n"] for p, _ in picks}),
              "commands": commands, "needs_input": [c["command"] for c in commands if c["needs_input"]],
              "note": T(lang, "apply_note") if commands else T(lang, "apply_empty")}
    if args.markdown:
        lines = ["## " + result["note"]] + ["%d. `%s`  (%s)" % (i, c["command"], ", ".join(c["proposals"]))
                                            for i, c in enumerate(commands, 1)]
        print("\n".join(lines))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="things-organize review helper (read-only)")
    parser.add_argument("--scope", default="all", help="inbox | today | all | <area or project name>")
    parser.add_argument("--now", help="freeze now: YYYY-MM-DDTHH:MM")
    parser.add_argument("--lang", choices=["auto", "zh", "en"], default="auto",
                        help="explicit reply language; auto = config.language, else detected from --text")
    parser.add_argument("--text", help="the user's invocation, for language detection with --lang auto")
    parser.add_argument("--config", help="config file (default: $THINGS_SKILLS_CONFIG or ~/.config/things-skills/config.json)")
    parser.add_argument("--cli", default=DEFAULT_CLI, help="wrapper path printed in commands (never shell-quoted)")
    parser.add_argument("--markdown", action="store_true", help="print Markdown instead of JSON")
    parser.add_argument("--apply", metavar="SELECTION", help="turn picked numbers into batched wrapper commands")
    parser.add_argument("--from", dest="from_file", metavar="FILE", help="saved review to apply (default: newest)")
    args = parser.parse_args(argv)
    return run_apply(args) if args.apply is not None else run_review(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
