"""Read side: the only module that imports things.py (SPEC sections B and C.8).

`import things` happens inside functions only, through `_import_things()`, which prefers the copy
bundled under <scripts>/vendor over any system-installed things.py. Nothing here ever writes to SQLite.
"""

import glob
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .url import show_url

ENV_DB = "THINGSDB"
VENDOR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
_DEFAULT_GLOB = ("~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/"
                 "ThingsData-*/Things Database.thingsdatabase/main.sqlite")
_DEFAULT_OLD = ("~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/"
                "Things Database.thingsdatabase/main.sqlite")
_REPEATING_WHERE = "rt1_repeatingTemplate IS NOT NULL OR rt1_recurrenceRule IS NOT NULL"
_TEMPLATES_SQL = (
    "SELECT uuid, title, CASE WHEN rt1_nextInstanceStartDate THEN printf('%d-%02d-%02d', "
    "(rt1_nextInstanceStartDate & 134152192) >> 16, (rt1_nextInstanceStartDate & 61440) >> 12, "
    "(rt1_nextInstanceStartDate & 3968) >> 7) END AS next_instance_date FROM TMTask "
    "WHERE rt1_recurrenceRule IS NOT NULL AND rt1_instanceCreationPaused = 0 "
    "AND trashed = 0 AND status = 0"
)
STATUS_MAP = {"open": "incomplete", "completed": "completed", "canceled": "canceled", "all": None}

_last_error: Optional[str] = None
_warnings: List[str] = []


class ReadError(Exception):
    """things.py not importable or the database unavailable (CLI exit 3)."""


def _warn(message: str) -> None:
    if message not in _warnings:
        _warnings.append(message)


def take_warnings() -> List[str]:
    """Return and clear warnings accumulated by read functions (evening/repeating detection)."""
    items = list(_warnings)
    del _warnings[:]
    return items


def _default_path_without_things() -> str:
    hits = glob.glob(os.path.expanduser(_DEFAULT_GLOB))
    return hits[0] if hits else os.path.expanduser(_DEFAULT_OLD)


def _import_things():
    """Import things.py, preferring the copy bundled under <scripts>/vendor (function-level by design).

    The vendor directory goes to the FRONT of sys.path before the first import, so the plugin runs the
    version it was tested against even when another things.py is installed system-wide. Without a
    vendor directory this is a plain `import things`. A `things` module that some earlier code already
    imported is reused as-is (Python would anyway); `things_py_info()` reports where it really came from.
    Any failure while importing (a missing package, or a damaged copy that raises SyntaxError and the
    like) surfaces as ImportError, so every caller has one error to handle.
    """
    module = sys.modules.get("things")
    if module is None:
        if os.path.isfile(os.path.join(VENDOR_DIR, "things", "__init__.py")) and sys.path[:1] != [VENDOR_DIR]:
            if VENDOR_DIR in sys.path:
                sys.path.remove(VENDOR_DIR)
            sys.path.insert(0, VENDOR_DIR)
        try:
            import things  # noqa: WPS433 (function-level import by design, SPEC C)
        except ImportError:
            raise
        except Exception as exc:  # a truncated or corrupt bundled file (SyntaxError, NameError, ...)
            raise ImportError(f"things.py is damaged: {type(exc).__name__}: {exc}") from exc
        module = things
    return module


def _module_dir(module: Any) -> Optional[str]:
    file = getattr(module, "__file__", None)
    return os.path.dirname(os.path.abspath(file)) if file else None


def things_py_info() -> Dict[str, Any]:
    """installed, version, source ("bundled" | "system" | None) and path (package directory) of things.py."""
    try:
        module = _import_things()
    except ImportError:
        return {"installed": False, "version": None, "source": None, "path": None}
    path = _module_dir(module)
    vendor_root = os.path.realpath(VENDOR_DIR) + os.sep
    bundled = path is not None and os.path.realpath(path).startswith(vendor_root)
    return {"installed": True, "version": getattr(module, "__version__", None),
            "source": "bundled" if bundled else "system", "path": path}


def database_path() -> str:
    """$THINGSDB if set, else the path things.py would use."""
    env = os.environ.get(ENV_DB)
    if env:
        return env
    try:
        things_database = _import_things().database
        return things_database.DEFAULT_FILEPATH
    except (ImportError, AttributeError):
        return _default_path_without_things()


def _import_error_text(exc: BaseException) -> str:
    """What doctor reports for a things.py import failure: the damaged-copy detail, else the plain fact."""
    text = str(exc)
    return text if text.startswith("things.py is damaged") else "things.py not installed"


def _call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a things.py call, translating its failures into ReadError."""
    global _last_error
    try:
        return func(*args, **kwargs)
    except ImportError as exc:
        _last_error = _import_error_text(exc)
        raise ReadError(f"things.py not installed: {exc}")
    except (sqlite3.Error, AssertionError, ValueError, OSError) as exc:
        _last_error = str(exc)
        raise ReadError(str(exc))


def _things():
    return _import_things()


def database_status() -> str:
    """"fixture" ($THINGSDB set, query works), "readable" (default path works) or "unavailable"."""
    global _last_error
    try:
        things = _things()
    except ImportError as exc:
        _last_error = _import_error_text(exc)
        return "unavailable"
    try:
        things.tasks(count_only=True)
    except Exception as exc:  # any failure means the database is not usable
        _last_error = str(exc) or type(exc).__name__
        return "unavailable"
    _last_error = None
    return "fixture" if os.environ.get(ENV_DB) else "readable"


def database_error() -> Optional[str]:
    return _last_error


def things_version() -> Optional[str]:
    try:
        return _things().__version__
    except ImportError:
        return None


def tasks_raw(**filters: Any) -> List[Dict]:
    """things.tasks(**filters) without enrichment (verification and search use this)."""
    return _call(lambda: _things().tasks(**filters))


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database_path()}?mode=ro", uri=True)


def _query(sql: str, params: tuple = ()) -> List[tuple]:
    """Read-only SQL on the Things database; the connection is always closed."""
    conn = _connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def repeating_uuids() -> Set[str]:
    """Templates (rule set) and generated instances (template pointer set)."""
    try:
        rows = _query(f"SELECT uuid FROM TMTask WHERE {_REPEATING_WHERE}")
    except sqlite3.Error:
        _warn("repeating detection unavailable")
        return set()
    return {row[0] for row in rows}


def is_repeating(item_id: str) -> Optional[bool]:
    """True/False for a known row, None when there is no row or the database is unavailable."""
    try:
        rows = _query(f"SELECT {_REPEATING_WHERE} FROM TMTask WHERE uuid = ?", (item_id,))
    except sqlite3.Error:
        return None
    if not rows:
        return None
    return bool(rows[0][0])


def _evening_uuids() -> Optional[Set[str]]:
    try:
        return {row[0] for row in _query("SELECT uuid FROM TMTask WHERE startBucket = 1")}
    except sqlite3.Error:
        return None


def repeating_templates(now: date) -> Dict[str, Any]:
    """Best-effort prediction of repeating instances Things has not generated yet (B.6)."""
    today = now.date() if isinstance(now, datetime) else now
    try:
        rows = _query(_TEMPLATES_SQL)
    except sqlite3.Error:
        return {"due": [], "templates": 0, "warning": "repeating to-dos could not be predicted"}
    due = []
    for uuid, title, next_date in rows:
        if not next_date:
            continue
        try:
            parsed = date.fromisoformat(next_date) if len(next_date) == 10 else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.year < 2000:
            continue
        if parsed <= today:
            due.append({"uuid": uuid, "title": title, "next_instance_date": next_date})
    return {"due": due, "templates": len(rows), "warning": None}


def token_from_database() -> Optional[str]:
    """things.token() guarded; None on any error (the CLI only offers it when the database is readable)."""
    try:
        value = _things().token()
    except Exception:
        return None
    return value or None


def _as_date(now: Optional[Any]) -> date:
    if now is None:
        return date.today()
    return now.date() if isinstance(now, datetime) else now


def enrich(item: Dict, now: Optional[Any] = None, repeating: Optional[Set[str]] = None) -> Dict:
    """Add `repeating`, `link` and `days_until_deadline` to one task dict (in place)."""
    if repeating is None:
        repeating = repeating_uuids()
    item["repeating"] = item.get("uuid") in repeating
    item["link"] = show_url(item.get("uuid", ""))
    deadline = item.get("deadline")
    days: Optional[int] = None
    if deadline:
        try:
            days = (date.fromisoformat(deadline) - _as_date(now)).days
        except ValueError:
            days = None
    item["days_until_deadline"] = days
    for child in item.get("items") or []:
        if isinstance(child, dict) and child.get("type") in ("to-do", "project", "heading"):
            enrich(child, now, repeating)
    return item


def _enrich_all(items: List[Dict], now: Optional[Any] = None) -> List[Dict]:
    repeating = repeating_uuids()
    return [enrich(item, now, repeating) for item in items]


def inbox(now: Optional[Any] = None) -> List[Dict]:
    return _enrich_all(_call(lambda: _things().inbox()), now)


def _today_query(cutoff: str) -> List[Dict]:
    """things.today() with `cutoff` (ISO date) in place of the SQLite wall clock.

    Same three unions and the same sort as things.py 1.0.1 `today()`: confirmed Today items, scheduled
    items whose start date has arrived (yellow dot) and unscheduled overdue items. things.py spells the
    date as 'past' (`<= date('now')`), which ignores --now; an explicit `<=YYYY-MM-DD` keeps it injectable.
    """
    api = _things()
    regular = api.tasks(start_date=True, start="Anytime", index="todayIndex")
    scheduled = api.tasks(start_date=f"<={cutoff}", start="Someday", index="todayIndex")
    overdue_items = api.tasks(start_date=False, deadline=f"<={cutoff}", deadline_suppressed=False)
    items = [*regular, *scheduled, *overdue_items]
    items.sort(key=lambda item: (item["today_index"], item["start_date"] or ""))
    return items


def today(now: Optional[Any] = None) -> List[Dict]:
    cutoff = _as_date(now).isoformat()
    items = _enrich_all(_call(_today_query, cutoff), now)
    evening = _evening_uuids()
    if evening is None:
        _warn("evening detection unavailable")
        evening = set()
    for item in items:
        item["evening"] = item.get("uuid") in evening
    return items


def upcoming(now: Optional[Any] = None) -> List[Dict]:
    """things.upcoming() (start='Someday', start_date='future') with `now` instead of the wall clock."""
    cutoff = _as_date(now).isoformat()
    return _enrich_all(_call(lambda: _things().tasks(start_date=f">{cutoff}", start="Someday")), now)


def anytime(now: Optional[Any] = None) -> List[Dict]:
    return _enrich_all(_call(lambda: _things().anytime()), now)


def someday(now: Optional[Any] = None) -> List[Dict]:
    return _enrich_all(_call(lambda: _things().someday()), now)


def logbook(days: int, now: Any) -> List[Dict]:
    cutoff = (_as_date(now) - timedelta(days=days)).isoformat()
    items = _call(lambda: _things().logbook(stop_date=f">={cutoff}"))
    items.sort(key=lambda item: item.get("stop_date") or "", reverse=True)
    return _enrich_all(items, now)


def deadlines(now: Optional[Any] = None) -> List[Dict]:
    return _enrich_all(_call(lambda: _things().deadlines()), now)


def areas() -> List[Dict]:
    return _call(lambda: _things().areas())


def _resolve_area(area: str) -> Optional[str]:
    """Accept an area uuid or title (casefolded); return the uuid or None."""
    folded = area.casefold()
    for entry in areas():
        if entry.get("uuid") == area or (entry.get("title") or "").casefold() == folded:
            return entry["uuid"]
    return None


def projects(area: Optional[str] = None, now: Optional[Any] = None) -> List[Dict]:
    if area is None:
        return _enrich_all(_call(lambda: _things().projects()), now)
    uuid = _resolve_area(area)
    if uuid is None:
        _warn(f"unknown area: {area}")
        return []
    return _enrich_all(_call(lambda: _things().projects(area=uuid)), now)


def tags() -> List[Dict]:
    return _call(lambda: _things().tags())


def tag_titles() -> List[str]:
    return _call(lambda: _things().tags(titles_only=True))


def get(item_id: str, now: Optional[Any] = None) -> Optional[Dict]:
    """things.get: to-dos carry `checklist` (list), projects carry `items`; None when unknown."""
    try:
        item = _call(lambda: _things().get(item_id))
    except ReadError as exc:
        if "No such task uuid" in str(exc):
            return None
        raise
    if item is None:
        return None
    if item.get("type") in ("to-do", "project", "heading"):
        enrich(item, now)
        if item["type"] == "to-do" and not isinstance(item.get("checklist"), list):
            item["checklist"] = []
    return item


def resolve_type(item_id: str) -> Optional[str]:
    """"to-do" | "project" | "heading" | "area" | "tag" | None (unknown or database unavailable)."""
    try:
        item = _things().get(item_id)
    except Exception:
        return None
    return item.get("type") if isinstance(item, dict) else None


class _Containers:
    """Project and heading lookups built once per search call (SPEC E.6 step 1).

    An item belongs to area X when its own area is X, or when its project (directly, or via its
    heading's project) lives in area X. It belongs to project P when it sits directly in P or
    under any heading of P.
    """

    def __init__(self) -> None:
        self.projects: Dict[str, Dict[str, Optional[str]]] = {}
        self.headings: Dict[str, Dict[str, Optional[str]]] = {}
        for project in tasks_raw(type="project", status=None):
            self.projects[project["uuid"]] = {"area": project.get("area"), "area_title": project.get("area_title")}
        for heading in tasks_raw(type="heading", status=None):
            self.headings[heading["uuid"]] = {"project": heading.get("project"),
                                              "project_title": heading.get("project_title")}

    @staticmethod
    def _same(uuid: Optional[str], title: Optional[str], wanted: str) -> bool:
        return uuid == wanted or bool(title) and (title or "").casefold() == wanted.casefold()

    def project_of(self, item: Dict) -> Tuple[Optional[str], Optional[str]]:
        """(project uuid, project title) of an item, following its heading when needed."""
        if item.get("project"):
            return item.get("project"), item.get("project_title")
        heading = self.headings.get(item.get("heading") or "")
        if heading:
            return heading.get("project"), heading.get("project_title")
        return None, None

    def in_project(self, item: Dict, wanted: str) -> bool:
        uuid, title = self.project_of(item)
        return self._same(uuid, title, wanted)

    def in_area(self, item: Dict, wanted: str) -> bool:
        if self._same(item.get("area"), item.get("area_title"), wanted):
            return True
        uuid, _title = self.project_of(item)
        project = self.projects.get(uuid or "")
        return bool(project) and self._same(project.get("area"), project.get("area_title"), wanted)


def _phrase_members(synonyms: Optional[List[List[str]]]) -> List[List[str]]:
    """Casefolded, whitespace-split synonym members with more than one word, longest first."""
    phrases: List[List[str]] = []
    for group in synonyms or []:
        for member in group:
            words = str(member).casefold().split()
            if len(words) > 1 and words not in phrases:
                phrases.append(words)
    phrases.sort(key=len, reverse=True)
    return phrases


def _query_variants(query: str, synonyms: Optional[List[List[str]]],
                    expand: Callable[[str, Dict[str, Any]], List[str]]) -> List[List[str]]:
    """One variant list per query term (SPEC E.6 step 2).

    Terms are whitespace tokens, except that a run of tokens equal to a multi-word synonym member
    ("weekly report") is one term, so the phrase expands to its group (周报) the same way a single
    word does. Longest phrase wins at each position; unmatched tokens expand one by one.
    """
    tokens = [token.casefold() for token in query.split()]
    if synonyms is None:
        return [[token] for token in tokens]
    phrases = _phrase_members(synonyms)
    config = {"synonyms": synonyms}
    variants: List[List[str]] = []
    i = 0
    while i < len(tokens):
        for words in phrases:
            if tokens[i:i + len(words)] == words:
                variants.append(expand(" ".join(words), config))
                i += len(words)
                break
        else:
            variants.append(expand(tokens[i], config))
            i += 1
    return variants


def search(query: str, status: str = "open", area: Optional[str] = None,
           project: Optional[str] = None, item_type: str = "all", limit: int = 20,
           synonyms: Optional[List[List[str]]] = None, now: Optional[Any] = None) -> List[Dict]:
    """Python-side casefolded substring search over title and notes (SPEC E.6)."""
    from .config import expand_synonyms  # local import keeps read.py's import surface small

    things_type = None if item_type in (None, "all") else item_type
    candidates = tasks_raw(type=things_type, status=STATUS_MAP.get(status, "incomplete"))
    containers = _Containers() if (area or project) else None
    variants = _query_variants(query, synonyms, expand_synonyms)
    results: List[Dict] = []
    for item in candidates:
        if item.get("type") == "heading" or item.get("trashed"):
            continue
        if area and not containers.in_area(item, area):
            continue
        if project and not containers.in_project(item, project):
            continue
        title = (item.get("title") or "").casefold()
        notes = (item.get("notes") or "").casefold()
        matched_terms: List[str] = []
        hit_title = False
        ok = True
        for group in variants:
            group_hit = False
            for variant in group:
                in_title = variant in title
                in_notes = variant in notes
                if in_title or in_notes:
                    group_hit = True
                    hit_title = hit_title or in_title
                    if variant not in matched_terms:
                        matched_terms.append(variant)
            if not group_hit:
                ok = False
                break
        if not ok:
            continue
        item["match"] = "title" if hit_title else "notes"
        item["matched_terms"] = matched_terms
        results.append(item)
    results.sort(key=lambda item: (0 if item["match"] == "title" else 1, item.get("modified") or ""))
    ordered: List[Dict] = []
    for group_key in ("title", "notes"):
        group = [item for item in results if item["match"] == group_key]
        group.sort(key=lambda item: item.get("modified") or "", reverse=True)
        ordered.extend(group)
    return _enrich_all(ordered[:limit], now)


def stale(days: int, now: datetime) -> List[Dict]:
    """Open Anytime to-dos with no start date, not repeating, untouched for `days` (E.7)."""
    cutoff = now - timedelta(days=days)
    repeating = repeating_uuids()
    results: List[Dict] = []
    for item in tasks_raw(type="to-do", status="incomplete"):
        if item.get("trashed") or item.get("start") != "Anytime" or item.get("start_date"):
            continue
        if item["uuid"] in repeating:
            continue
        try:
            modified = datetime.strptime(item.get("modified") or "", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if modified >= cutoff:
            continue
        item["age_days"] = (now - modified).days
        results.append(enrich(item, now, repeating))
    results.sort(key=lambda item: item.get("modified") or "")
    return results


def overdue(now: Any) -> List[Dict]:
    """Open to-dos and projects whose deadline is before today, earliest first (E.7)."""
    today_iso = _as_date(now).isoformat()
    repeating = repeating_uuids()
    results = []
    for item in tasks_raw(status="incomplete"):
        if item.get("type") not in ("to-do", "project") or item.get("trashed"):
            continue
        deadline = item.get("deadline")
        if deadline and deadline < today_iso:
            results.append(enrich(item, now, repeating))
    results.sort(key=lambda item: (item.get("deadline") or "", item.get("title") or ""))
    return results
