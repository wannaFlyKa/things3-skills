"""Post-write verification through things.py (SPEC section C.6).

Only meaningful with the `open` transport on macOS; on Linux tests inject `reader`.
"""

import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, NamedTuple, Optional

from . import read
from .url import show_url

CREATED_SLACK = timedelta(seconds=10)


class VerifyResult(NamedTuple):
    verified: bool
    reason: Optional[str]
    ids: List[str]
    links: List[str]
    items: List[Dict]


def _skip(transport: str) -> Optional[VerifyResult]:
    if transport != "open":
        return VerifyResult(False, f"transport {transport}: nothing was sent to Things", [], [], [])
    status = read.database_status()
    if status == "unavailable":
        return VerifyResult(False, "database unavailable", [], [], [])
    if status != "readable":
        return VerifyResult(False, "database overridden by THINGSDB; verification runs only against the default "
                            "Things database", [], [], [])
    return None


def _parse_created(value: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.strptime(value or "", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _default_reader() -> List[Dict]:
    return read.tasks_raw(status=None, type=None)


def verify_created(titles: List[str], since: datetime, timeout: float = 3.0, transport: str = "open",
                   poll: float = 0.5, sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic,
                   reader: Optional[Callable[[], List[Dict]]] = None) -> VerifyResult:
    """Every requested title must appear as an item created at or after `since` - 10 s."""
    skipped = _skip(transport)
    if skipped is not None:
        return skipped
    reader = reader or _default_reader
    wanted = list(dict.fromkeys(titles))
    floor = since - CREATED_SLACK
    start = clock()
    sleep(poll)
    found: Dict[str, Dict] = {}
    while True:
        try:
            items = reader()
        except read.ReadError as exc:
            return VerifyResult(False, f"read error: {exc}", [], [], [])
        found = {}
        for item in items:
            title = item.get("title")
            if title not in wanted:
                continue
            created = _parse_created(item.get("created"))
            if created is None or created < floor:
                continue
            current = found.get(title)
            if current is None or (item.get("created") or "") > (current.get("created") or ""):
                found[title] = item
        if all(title in found for title in wanted):
            ordered = [found[title] for title in wanted]
            ids = [item["uuid"] for item in ordered]
            return VerifyResult(True, None, ids, [show_url(i) for i in ids], ordered)
        if clock() - start >= timeout:
            break
        sleep(poll)
    ordered = [found[title] for title in wanted if title in found]
    ids = [item["uuid"] for item in ordered]
    return VerifyResult(False, f"timeout after {timeout:.1f}s", ids, [show_url(i) for i in ids], ordered)


def verify_updated(ids: List[str], predicate: Callable[[Dict], bool], timeout: float = 3.0,
                   transport: str = "open", poll: float = 0.5,
                   sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic,
                   reader: Optional[Callable[[str], Optional[Dict]]] = None) -> VerifyResult:
    """Every id must resolve through read.get and satisfy `predicate`."""
    skipped = _skip(transport)
    if skipped is not None:
        return skipped
    reader = reader or read.get
    ids = list(dict.fromkeys(ids))   # `good` is keyed by id, so the success test needs unique ids
    start = clock()
    sleep(poll)
    good: Dict[str, Dict] = {}
    while True:
        good = {}
        for item_id in ids:
            try:
                item = reader(item_id)
            except read.ReadError as exc:
                return VerifyResult(False, f"read error: {exc}", [], [], [])
            if item is not None and predicate(item):
                good[item_id] = item
        if len(good) == len(ids):
            items = [good[i] for i in ids]
            return VerifyResult(True, None, list(ids), [show_url(i) for i in ids], items)
        if clock() - start >= timeout:
            break
        sleep(poll)
    found_ids = [i for i in ids if i in good]
    return VerifyResult(False, f"timeout after {timeout:.1f}s", found_ids,
                        [show_url(i) for i in found_ids], [good[i] for i in found_ids])
