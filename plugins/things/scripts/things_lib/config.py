"""Config file loading, routing hints and synonym expansion (SPEC section C.2 / G)."""

import copy
import json
import os
import re
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_PATH = "~/.config/things-skills/config.json"
ENV_VAR = "THINGS_SKILLS_CONFIG"

DEFAULTS: Dict[str, Any] = {
    "areas": [],
    "routing_hints": [],
    "tags": [],
    "synonyms": [
        ["报销", "expense", "reimbursement"],
        ["周报", "weekly report"],
        ["医生", "牙医", "doctor", "dentist"],
    ],
    "today_cap": 6,
    "stale_days": 30,
    "deadline_lead_days": 3,
    "default_reminder_time": "09:00",
    "language": "auto",
    "someday_resurface_days": 90,
}

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_LANGUAGES = ("auto", "zh", "en")


class ConfigError(Exception):
    """Malformed config file or wrong value type (CLI exit 1)."""


def config_path(override: Optional[str] = None) -> str:
    """Resolve the config path: explicit override > $THINGS_SKILLS_CONFIG > default."""
    path = override or os.environ.get(ENV_VAR) or DEFAULT_CONFIG_PATH
    return os.path.expanduser(path)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _check_routing_hint(index: int, hint: Any) -> Dict[str, Any]:
    if not isinstance(hint, dict):
        raise ConfigError(f"routing_hints[{index}] must be an object")
    pattern = hint.get("pattern")
    area = hint.get("area")
    project = hint.get("project")
    regex = hint.get("regex", False)
    if not isinstance(pattern, str) or not pattern:
        raise ConfigError(f"routing_hints[{index}].pattern must be a non-empty string")
    if not isinstance(area, str) or not area:
        raise ConfigError(f"routing_hints[{index}].area must be a non-empty string")
    if project is not None and not isinstance(project, str):
        raise ConfigError(f"routing_hints[{index}].project must be a string or null")
    if not isinstance(regex, bool):
        raise ConfigError(f"routing_hints[{index}].regex must be a boolean")
    if regex:
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ConfigError(f"routing_hints[{index}].pattern is not a valid regex: {exc}")
    normalised = dict(hint)
    normalised.update({"pattern": pattern, "area": area, "project": project, "regex": regex})
    return normalised


def _check_value(key: str, value: Any) -> Any:
    """Type-check a known key; return the (possibly normalised) value."""
    if key in ("areas", "tags"):
        if not _is_str_list(value):
            raise ConfigError(f"config key {key} must be a list of strings")
        return value
    if key == "routing_hints":
        if not isinstance(value, list):
            raise ConfigError("config key routing_hints must be a list of objects")
        return [_check_routing_hint(i, hint) for i, hint in enumerate(value)]
    if key == "synonyms":
        if not isinstance(value, list) or not all(_is_str_list(group) for group in value):
            raise ConfigError("config key synonyms must be a list of lists of strings")
        return value
    if key in ("today_cap", "stale_days", "someday_resurface_days"):
        if not _is_int(value) or value < 1:
            raise ConfigError(f"config key {key} must be an integer >= 1")
        return value
    if key == "deadline_lead_days":
        if not _is_int(value) or value < 0:
            raise ConfigError("config key deadline_lead_days must be an integer >= 0")
        return value
    if key == "default_reminder_time":
        if not isinstance(value, str) or not _TIME_RE.match(value):
            raise ConfigError("config key default_reminder_time must be a string HH:MM")
        return value
    if key == "language":
        if value not in _LANGUAGES:
            raise ConfigError('config key language must be one of "auto", "zh", "en"')
        return value
    return value


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the config file, merging over DEFAULTS. A missing file yields the defaults."""
    resolved = config_path(path)
    result = copy.deepcopy(DEFAULTS)
    if not os.path.isfile(resolved):
        return result
    try:
        with open(resolved, encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError as exc:
        raise ConfigError(f"invalid JSON in {resolved}: {exc}")
    except OSError as exc:
        raise ConfigError(f"cannot read {resolved}: {exc}")
    if not isinstance(data, dict):
        raise ConfigError(f"invalid config in {resolved}: top level must be a JSON object")
    for key, value in data.items():
        result[key] = _check_value(key, value) if key in DEFAULTS else value
    return result


def route(title: str, notes: str, config: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
    """Return {"area", "project"} of the first routing hint matching title + newline + notes."""
    text = (title or "") + "\n" + (notes or "")
    folded = text.casefold()
    for index, hint in enumerate(config.get("routing_hints") or []):
        pattern = hint.get("pattern") or ""
        if hint.get("regex"):
            try:
                matched = re.search(pattern, text, re.IGNORECASE) is not None
            except re.error as exc:
                raise ConfigError(f"routing_hints[{index}].pattern is not a valid regex: {exc}")
        else:
            matched = pattern.casefold() in folded
        if matched:
            return {"area": hint.get("area"), "project": hint.get("project")}
    return None


def expand_synonyms(term: str, config: Dict[str, Any]) -> List[str]:
    """Casefold `term` and add every member of every synonym group containing it."""
    base = term.casefold()
    result = [base]
    for group in config.get("synonyms") or []:
        members = [str(member).casefold() for member in group]
        if base in members:
            for member in members:
                if member not in result:
                    result.append(member)
    return result
