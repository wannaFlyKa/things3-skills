"""Config loading (SPEC sections C.2, G)."""

import copy
import json
import os
import re

import pytest

from things_lib import config as config_mod
from things_lib.config import DEFAULTS, ConfigError, config_path, load_config

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "plugins", "things", "config.example.json")
NUMERIC_KEYS = ("today_cap", "stale_days", "deadline_lead_days", "default_reminder_time", "language",
                "someday_resurface_days")


def test_defaults_when_file_missing():
    result = load_config()
    assert result == DEFAULTS
    assert result is not DEFAULTS and result["synonyms"] is not DEFAULTS["synonyms"]
    assert DEFAULTS["synonyms"] == [["报销", "expense", "reimbursement"], ["周报", "weekly report"],
                                    ["医生", "牙医", "doctor", "dentist"]]
    assert (DEFAULTS["today_cap"], DEFAULTS["stale_days"], DEFAULTS["deadline_lead_days"],
            DEFAULTS["default_reminder_time"], DEFAULTS["language"], DEFAULTS["someday_resurface_days"]) == \
        (6, 30, 3, "09:00", "auto", 90)


def test_partial_file_merges(config_file):
    config_file({"areas": ["Work"], "today_cap": 4, "extra": {"x": 1}})
    result = load_config()
    assert result["areas"] == ["Work"] and result["today_cap"] == 4
    assert result["stale_days"] == 30 and result["synonyms"] == DEFAULTS["synonyms"]
    assert result["extra"] == {"x": 1}  # unknown keys are kept


@pytest.mark.parametrize("key,value", [
    ("areas", "Work"), ("areas", [1]), ("tags", "a,b"), ("synonyms", ["a", "b"]), ("synonyms", [[1]]),
    ("today_cap", 0), ("today_cap", "6"), ("today_cap", True), ("stale_days", -1), ("deadline_lead_days", -1),
    ("deadline_lead_days", 1.5), ("default_reminder_time", "9am"), ("default_reminder_time", "25:00"),
    ("language", "fr"), ("someday_resurface_days", 0),
    ("routing_hints", [{"area": "Work"}]), ("routing_hints", [{"pattern": "x"}]),
    ("routing_hints", [{"pattern": "x", "area": "W", "regex": "yes"}]),
    ("routing_hints", [{"pattern": "(", "area": "W", "regex": True}]), ("routing_hints", "x"),
])
def test_type_errors(config_file, key, value):
    path = config_file({key: value})
    with pytest.raises(ConfigError):
        load_config(path)


def test_malformed_json(config_file, tmp_path):
    path = tmp_path / ".config" / "things-skills" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_config()
    assert str(info.value).startswith(f"invalid JSON in {path}: ")
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config()


def test_path_precedence(monkeypatch, tmp_path):
    assert config_path() == str(tmp_path / ".config" / "things-skills" / "config.json")
    monkeypatch.setenv("THINGS_SKILLS_CONFIG", "~/env.json")
    assert config_path() == str(tmp_path / "env.json")
    assert config_path("/flag/config.json") == "/flag/config.json"
    monkeypatch.setenv("THINGS_SKILLS_CONFIG", "")
    assert config_path() == str(tmp_path / ".config" / "things-skills" / "config.json")


def test_env_path_is_used_by_load(monkeypatch, tmp_path):
    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"today_cap": 9}), encoding="utf-8")
    monkeypatch.setenv("THINGS_SKILLS_CONFIG", str(custom))
    assert load_config()["today_cap"] == 9


def test_example_config_loads_and_matches_defaults():
    with open(EXAMPLE, encoding="utf-8") as handle:
        raw = json.load(handle)
    loaded = load_config(EXAMPLE)
    for key in NUMERIC_KEYS:
        assert loaded[key] == DEFAULTS[key], key
        assert raw[key] == DEFAULTS[key], key
    assert loaded["synonyms"] == DEFAULTS["synonyms"]
    assert loaded["areas"] and loaded["tags"] and loaded["routing_hints"]
    patterns = " ".join(hint["pattern"] for hint in loaded["routing_hints"])
    assert any("一" <= ch <= "鿿" for ch in patterns) and any(ch.isascii() and ch.isalpha() for ch in patterns)
    assert set(raw) == set(DEFAULTS)
    for hint in loaded["routing_hints"]:
        assert set(hint) == {"pattern", "area", "project", "regex"}


def test_example_regex_hints_match_cjk_inside_a_sentence():
    """Python `\\b` never sits between two Han characters (they are \\w), so CJK words must stay outside it."""
    from things_lib.config import route
    loaded = load_config(EXAMPLE)
    for text in ("每周三健身", "去健身房", "明天跑步", "gym tonight"):
        assert route(text, "", loaded) == {"area": "Personal", "project": None}, text
    assert route("去看牙医", "", loaded) == {"area": "Personal", "project": None}
    for hint in loaded["routing_hints"]:
        if not hint["regex"]:
            continue
        # every CJK word in a regex hint must survive being embedded between other Han characters
        for word in re.findall(r"[一-鿿]+", hint["pattern"]):
            assert re.search(hint["pattern"], f"要{word}了", re.IGNORECASE), (hint["pattern"], word)


def test_defaults_not_mutated_by_loading(config_file):
    snapshot = copy.deepcopy(DEFAULTS)
    config_file({"synonyms": [["a", "b"]]})
    result = load_config()
    result["synonyms"].append(["c"])
    result["areas"].append("X")
    assert DEFAULTS == snapshot
