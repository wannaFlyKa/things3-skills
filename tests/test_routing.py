"""Routing hints and synonym expansion (SPEC sections C.2, G)."""

import pytest

from things_lib.config import ConfigError, expand_synonyms, route

CONFIG = {"routing_hints": [
    {"pattern": "报销", "area": "Work", "project": "Expenses", "regex": False},
    {"pattern": "Expense", "area": "Work", "project": None, "regex": False},
    {"pattern": r"\b(gym)\b|健身", "area": "Personal", "project": None, "regex": True},
    {"pattern": "gym", "area": "Career", "project": None, "regex": False},
]}


def test_first_match_wins():
    assert route("gym session", "", CONFIG) == {"area": "Personal", "project": None}
    assert route("报销 expense", "", CONFIG) == {"area": "Work", "project": "Expenses"}


def test_case_insensitive_substring():
    assert route("Submit EXPENSE report", "", CONFIG) == {"area": "Work", "project": None}
    assert route("expenses", "", CONFIG) == {"area": "Work", "project": None}


def test_regex_hint_with_word_boundary():
    assert route("GYM tonight", "", CONFIG) == {"area": "Personal", "project": None}
    # "gymnastics" fails the regex word boundary but hits the later plain substring hint
    assert route("gymnastics", "", CONFIG) == {"area": "Career", "project": None}
    # CJK words sit outside the \b group: Han characters are \w, so \b健身\b never matches inside a sentence
    assert route("每周三健身", "", CONFIG) == {"area": "Personal", "project": None}
    assert route("去健身房", "", CONFIG) == {"area": "Personal", "project": None}


def test_notes_are_matched():
    assert route("Call Bob", "about the 报销 form", CONFIG) == {"area": "Work", "project": "Expenses"}
    assert route("Call Bob", "", CONFIG) is None


def test_no_hints_or_no_match():
    assert route("anything", "notes", {"routing_hints": []}) is None
    assert route("anything", "notes", {}) is None


def test_invalid_regex_raises_config_error():
    with pytest.raises(ConfigError):
        route("x", "", {"routing_hints": [{"pattern": "(", "area": "W", "project": None, "regex": True}]})


SYN = {"synonyms": [["报销", "expense", "reimbursement"], ["周报", "weekly report"], ["医生", "牙医", "doctor", "dentist"]]}


def test_expand_symmetric():
    assert expand_synonyms("报销", SYN) == ["报销", "expense", "reimbursement"]
    assert expand_synonyms("reimbursement", SYN) == ["reimbursement", "报销", "expense"]
    assert expand_synonyms("Doctor", SYN) == ["doctor", "医生", "牙医", "dentist"]


def test_defaults_expand_dentist_both_ways():
    from things_lib.config import DEFAULTS
    assert expand_synonyms("牙医", DEFAULTS) == ["牙医", "医生", "doctor", "dentist"]
    assert expand_synonyms("dentist", DEFAULTS) == ["dentist", "医生", "牙医", "doctor"]


def test_expand_casefold_and_dedup():
    assert expand_synonyms("EXPENSE", SYN) == ["expense", "报销", "reimbursement"]
    doubled = {"synonyms": [["a", "b"], ["A", "c"], ["b", "a"]]}
    assert expand_synonyms("a", doubled) == ["a", "b", "c"]


def test_expand_unknown_term():
    assert expand_synonyms("Milk", SYN) == ["milk"]
    assert expand_synonyms("milk", {}) == ["milk"]
