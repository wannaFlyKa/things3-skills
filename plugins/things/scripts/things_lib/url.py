"""Things URL construction (SPEC sections A, C.4, D) and the rate limiter (C.7)."""

import collections
import json
import re
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
from urllib.parse import quote

VALID_WHEN = re.compile(r"^(today|tomorrow|evening|anytime|someday|\d{4}-\d{2}-\d{2}(@\d{2}:\d{2})?)$")
VALID_DEADLINE = re.compile(r"^(today|tomorrow|\d{4}-\d{2}-\d{2})$")

RATE_LIMIT_ITEMS = 250
RATE_LIMIT_WINDOW = 10.0
MAX_STRING = 4000
MAX_NOTES = 10000
MAX_CHECKLIST = 100

PARAM_ORDER: Dict[str, List[str]] = {
    "add": ["title", "titles", "notes", "when", "deadline", "tags", "checklist-items",
            "list-id", "list", "heading-id", "heading", "completed", "canceled"],
    "add-project": ["title", "notes", "when", "deadline", "tags", "area-id", "area",
                    "to-dos", "completed", "canceled"],
    "update": ["id", "title", "notes", "prepend-notes", "append-notes", "when", "deadline",
               "tags", "add-tags", "checklist-items", "prepend-checklist-items",
               "append-checklist-items", "list-id", "list", "heading-id", "heading",
               "completed", "canceled"],
    "update-project": ["id", "title", "notes", "prepend-notes", "append-notes", "when",
                       "deadline", "tags", "add-tags", "area-id", "area", "completed", "canceled"],
    "show": ["id", "query", "filter"],
    "json": ["data"],
    "version": [],
}

NOTES_KEYS = ("notes", "prepend-notes", "append-notes")
COMMA_LIST_KEYS = ("tags", "add-tags", "filter")
NEWLINE_LIST_KEYS = ("titles", "checklist-items", "prepend-checklist-items",
                     "append-checklist-items", "to-dos")
CHECKLIST_KEYS = ("checklist-items", "prepend-checklist-items", "append-checklist-items")
BOOL_KEYS = ("completed", "canceled")


class UrlError(Exception):
    """Limit exceeded, unknown parameter or invalid value (CLI exit 1)."""


def encode(value: str) -> str:
    """Percent-encode every character outside the unreserved set (space -> %20, never +)."""
    return quote(value, safe="")


def _serialise(key: str, value: Any) -> Optional[str]:
    """Turn a Python value into the unencoded string form of section D.1. None = omit."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
        if key in COMMA_LIST_KEYS:
            items = [item.strip() for item in items if item.strip()]
            return ",".join(items) if items else None
        if key in NEWLINE_LIST_KEYS:
            return "\n".join(items) if items else None
        raise UrlError(f"parameter {key} does not accept a list")
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        raise UrlError(f"parameter {key} has unsupported type {type(value).__name__}")
    return value


def _validate(key: str, serialised: str) -> None:
    """Enforce section A.7 limits and the when/deadline vocabularies on one value."""
    if key in NOTES_KEYS:
        if len(serialised) > MAX_NOTES:
            raise UrlError(f"{key} exceeds {MAX_NOTES} characters")
        return
    if key in NEWLINE_LIST_KEYS:
        lines = serialised.split("\n") if serialised else []
        if key in CHECKLIST_KEYS and len(lines) > MAX_CHECKLIST:
            raise UrlError(f"{key} has {len(lines)} items; the limit is {MAX_CHECKLIST}")
        for line in lines:
            if len(line) > MAX_STRING:
                raise UrlError(f"an item of {key} exceeds {MAX_STRING} characters")
        # The newline-joined string is itself one URL value (A.7), so the limit applies to it too.
        if len(serialised) > MAX_STRING:
            raise UrlError(f"{key} exceeds {MAX_STRING} characters when joined")
        return
    if len(serialised) > MAX_STRING:
        raise UrlError(f"{key} exceeds {MAX_STRING} characters")
    if key == "when" and serialised and not VALID_WHEN.match(serialised):
        raise UrlError(f"invalid when value '{serialised}'")
    if key == "deadline" and serialised and not VALID_DEADLINE.match(serialised):
        raise UrlError(f"invalid deadline value '{serialised}'")
    if key in BOOL_KEYS and serialised not in ("true", "false"):
        raise UrlError(f"{key} must be true or false")


def build(command: str, params: Dict[str, Any], token: Optional[str] = None) -> str:
    """Build `things:///<command>?...` with parameters in canonical order, auth-token last."""
    if command not in PARAM_ORDER:
        raise UrlError(f"unknown command: {command}")
    order = PARAM_ORDER[command]
    for key in params:
        if key not in order:
            raise UrlError(f"unknown parameter for {command}: {key}")
    parts: List[str] = []
    for key in order:
        if key not in params:
            continue
        serialised = _serialise(key, params[key])
        if serialised is None:
            continue
        _validate(key, serialised)
        parts.append(key + "=" + encode(serialised))
    if token is not None:
        parts.append("auth-token=" + encode(token))
    url = "things:///" + command
    if parts:
        url += "?" + "&".join(parts)
    return url


def show_url(item_id: str) -> str:
    return "things:///show?id=" + encode(item_id)


# --- JSON payload validation (section A.6) -------------------------------------------------

_TODO_KEYS = ("title", "notes", "when", "deadline", "tags", "checklist-items", "list-id", "list",
              "heading-id", "heading", "completed", "canceled", "creation-date", "completion-date")
_TODO_UPDATE_KEYS = ("prepend-notes", "append-notes", "add-tags",
                     "prepend-checklist-items", "append-checklist-items")
_PROJECT_KEYS = ("title", "notes", "when", "deadline", "tags", "area-id", "area", "completed",
                 "canceled", "creation-date", "completion-date")
_PROJECT_CREATE_KEYS = ("items",)
_PROJECT_UPDATE_KEYS = ("prepend-notes", "append-notes", "add-tags")
_HEADING_KEYS = ("title", "archived")
_CHECKLIST_KEYS = ("title", "completed", "canceled")
_BOOL_ATTRS = ("completed", "canceled", "archived")
_STRING_ATTRS = ("title", "notes", "when", "deadline", "list-id", "list", "heading-id", "heading",
                 "area-id", "area", "creation-date", "completion-date", "prepend-notes",
                 "append-notes", "add-tags", "prepend-checklist-items", "append-checklist-items")


def _check_string(path: str, key: str, value: Any) -> None:
    if not isinstance(value, str):
        raise UrlError(f"{path}.{key}: must be a string")
    limit = MAX_NOTES if key in NOTES_KEYS else MAX_STRING
    if len(value) > limit:
        raise UrlError(f"{path}.{key}: exceeds {limit} characters")
    if key == "when" and value and not VALID_WHEN.match(value):
        raise UrlError(f"{path}.{key}: invalid when value '{value}'")
    if key == "deadline" and value and not VALID_DEADLINE.match(value):
        raise UrlError(f"{path}.{key}: invalid deadline value '{value}'")
    if key in ("prepend-checklist-items", "append-checklist-items"):
        if len(value.split("\n")) > MAX_CHECKLIST:
            raise UrlError(f"{path}.{key}: more than {MAX_CHECKLIST} checklist items")


def _check_attributes(path: str, attrs: Any, allowed: Tuple[str, ...]) -> None:
    if not isinstance(attrs, dict):
        raise UrlError(f"{path}: must be an object")
    for key, value in attrs.items():
        if key not in allowed:
            raise UrlError(f"{path}.{key}: not an allowed attribute here")
        if key in _BOOL_ATTRS:
            if not isinstance(value, bool):
                raise UrlError(f"{path}.{key}: must be a boolean")
        elif key == "tags":
            if not isinstance(value, list) or not all(isinstance(tag, str) for tag in value):
                raise UrlError(f"{path}.{key}: must be an array of strings")
            for index, tag in enumerate(value):
                if len(tag) > MAX_STRING:
                    raise UrlError(f"{path}.{key}[{index}]: exceeds {MAX_STRING} characters")
        elif key in ("checklist-items", "items"):
            pass  # validated by the caller, which knows the nesting rules
        elif key in _STRING_ATTRS:
            _check_string(path, key, value)


def _check_object(path: str, obj: Any, allowed_types: Tuple[str, ...], nested: bool) -> None:
    """Validate one object of the json payload; `path` names it for error messages."""
    if not isinstance(obj, dict):
        raise UrlError(f"{path}: must be an object")
    obj_type = obj.get("type")
    if obj_type not in ("to-do", "project", "heading", "checklist-item"):
        raise UrlError(f"{path}.type: must be one of to-do, project, heading, checklist-item")
    if obj_type not in allowed_types:
        raise UrlError(f"{path}.type: '{obj_type}' is not allowed here")
    operation = obj.get("operation", "create")
    if operation not in ("create", "update"):
        raise UrlError(f"{path}.operation: must be create or update")
    if operation == "update":
        if obj_type not in ("to-do", "project"):
            raise UrlError(f"{path}.operation: update is only valid for to-do and project")
        if nested:
            raise UrlError(f"{path}.operation: update is not allowed for nested objects")
        if not isinstance(obj.get("id"), str) or not obj["id"]:
            raise UrlError(f"{path}.id: required when operation is update")
    for key in obj:
        if key not in ("type", "operation", "id", "attributes"):
            raise UrlError(f"{path}.{key}: unknown key")
    if "attributes" not in obj:
        raise UrlError(f"{path}.attributes: required")
    attrs = obj["attributes"]
    attr_path = path + ".attributes"
    if obj_type == "to-do":
        allowed = _TODO_KEYS + (_TODO_UPDATE_KEYS if operation == "update" else ())
        _check_attributes(attr_path, attrs, allowed)
        items = attrs.get("checklist-items")
        if items is not None:
            if not isinstance(items, list):
                raise UrlError(f"{attr_path}.checklist-items: must be an array")
            if len(items) > MAX_CHECKLIST:
                raise UrlError(f"{attr_path}.checklist-items: more than {MAX_CHECKLIST} items")
            for index, item in enumerate(items):
                _check_object(f"{attr_path}.checklist-items[{index}]", item, ("checklist-item",), True)
    elif obj_type == "project":
        allowed = _PROJECT_KEYS + (_PROJECT_UPDATE_KEYS if operation == "update" else _PROJECT_CREATE_KEYS)
        _check_attributes(attr_path, attrs, allowed)
        items = attrs.get("items")
        if items is not None:
            if not isinstance(items, list):
                raise UrlError(f"{attr_path}.items: must be an array")
            for index, item in enumerate(items):
                _check_object(f"{attr_path}.items[{index}]", item, ("to-do", "heading"), True)
    elif obj_type == "heading":
        _check_attributes(attr_path, attrs, _HEADING_KEYS)
    else:
        _check_attributes(attr_path, attrs, _CHECKLIST_KEYS)


def validate_json(objects: Any) -> None:
    """Raise UrlError("<path>: <message>") on the first A.6 violation."""
    if not isinstance(objects, list):
        raise UrlError("data: must be a JSON array")
    if not objects:
        raise UrlError("data: array is empty")
    for index, obj in enumerate(objects):
        _check_object(f"[{index}]", obj, ("to-do", "project"), False)


def has_update(objects: List[Dict]) -> bool:
    return any(isinstance(obj, dict) and obj.get("operation") == "update" for obj in objects)


def build_json(objects: List[Dict], token: Optional[str] = None) -> str:
    """Build `things:///json?data=...`; auth-token appended only when an update op exists."""
    validate_json(objects)
    data = json.dumps(objects, separators=(",", ":"), ensure_ascii=False)
    url = "things:///json?data=" + encode(data)
    if has_update(objects):
        if token is None:
            raise UrlError("json payload contains an update operation; auth token required")
        url += "&auth-token=" + encode(token)
    return url


# --- Rate limiting (section C.7) -----------------------------------------------------------

def _line_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return len(value)
    return len(str(value).split("\n")) if str(value) else 0


def _count_json_items(objects: Any) -> int:
    total = 0
    for obj in objects or []:
        if not isinstance(obj, dict):
            continue
        if obj.get("type") in ("to-do", "project", "heading"):
            total += 1
        attrs = obj.get("attributes") or {}
        if isinstance(attrs, dict) and isinstance(attrs.get("items"), list):
            total += _count_json_items(attrs["items"])
    return total


def count_items(command: str, params_or_objects: Any) -> int:
    """Rate-limit weight of one send (table C.7)."""
    if command == "add":
        titles = (params_or_objects or {}).get("titles")
        return _line_count(titles) or 1
    if command == "add-project":
        return 1 + _line_count((params_or_objects or {}).get("to-dos"))
    if command == "json":
        return _count_json_items(params_or_objects)
    return 1


class RateLimiter:
    """Rolling-window limiter: at most `limit` items per `window` seconds."""

    def __init__(self, limit: int = RATE_LIMIT_ITEMS, window: float = RATE_LIMIT_WINDOW,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self.sleep = sleep
        self._events: Deque[Tuple[float, int]] = collections.deque()

    def _evict(self, now: float) -> None:
        while self._events and self._events[0][0] <= now - self.window:
            self._events.popleft()

    def acquire(self, items: int = 1) -> float:
        """Block (via the injected sleep) until `items` fit; return the seconds slept."""
        if items > self.limit:
            raise UrlError(f"batch of {items} items exceeds {self.limit} per {self.window:g} s; split it")
        slept = 0.0
        while True:
            now = self.clock()
            self._evict(now)
            used = sum(count for _, count in self._events)
            if used + items <= self.limit:
                self._events.append((now, items))
                return slept
            wait = self._events[0][0] + self.window - now
            if wait <= 0:
                wait = 0.001
            self.sleep(wait)
            slept += wait
