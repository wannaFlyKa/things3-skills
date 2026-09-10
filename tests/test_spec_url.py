"""Adversarial encoding tests written from SPEC.md section D (A.6, A.7, C.4, C.7, D.1-D.3).

Expected strings are derived from the spec rules (quote(value, safe='') semantics spelled out in D.1,
canonical order in D.2, worked examples in D.3), never from the implementation.
"""

import json
import re
from urllib.parse import unquote

import pytest

from things_lib import url as url_mod
from things_lib.token import mask_url
from things_lib.url import UrlError, build, build_json, count_items, encode, show_url

# The exact vocabulary regexes from SPEC C.4, re-declared so the test does not trust the module.
SPEC_VALID_WHEN = re.compile(r"^(today|tomorrow|evening|anytime|someday|\d{4}-\d{2}-\d{2}(@\d{2}:\d{2})?)$")
SPEC_VALID_DEADLINE = re.compile(r"^(today|tomorrow|\d{4}-\d{2}-\d{2})$")


def pct(text):
    """UTF-8 percent triples/quads with UPPERCASE hex, as SPEC D.1 demands for every non-safe byte."""
    return "".join("%%%02X" % b for b in text.encode("utf-8"))


# ---- D.1: every reserved / control character -------------------------------------------------------

RESERVED = [
    (" ", "%20"), ("/", "%2F"), ("&", "%26"), ("#", "%23"), ("?", "%3F"), ("=", "%3D"), ("+", "%2B"),
    (",", "%2C"), ("@", "%40"), (":", "%3A"), ("%", "%25"), ('"', "%22"), ("'", "%27"), (";", "%3B"),
    ("[", "%5B"), ("]", "%5D"), ("{", "%7B"), ("}", "%7D"), ("|", "%7C"), ("\\", "%5C"), ("^", "%5E"),
    ("<", "%3C"), (">", "%3E"), ("`", "%60"), ("\t", "%09"), ("\r", "%0D"), ("\n", "%0A"),
    ("\r\n", "%0D%0A"), ("\x01", "%01"), ("\x1f", "%1F"), ("\x7f", "%7F"), ("$", "%24"), ("!", "%21"),
    ("*", "%2A"), ("(", "%28"), (")", "%29"),
]


@pytest.mark.parametrize("char,expected", RESERVED, ids=[repr(c) for c, _ in RESERVED])
def test_reserved_character_in_title(char, expected):
    assert build("add", {"title": "a" + char + "b"}) == "things:///add?title=a" + expected + "b"
    assert encode(char) == expected


def test_unreserved_characters_pass_through():
    assert encode("~-_.abcXYZ019") == "~-_.abcXYZ019"
    assert build("add", {"title": "~"}) == "things:///add?title=~"


def test_space_is_never_plus():
    assert "+" not in build("add", {"title": "a b c"})
    assert build("add", {"title": "a+b c"}) == "things:///add?title=a%2Bb%20c"


def test_percent_is_not_double_decoded_or_collapsed():
    assert build("add", {"title": "100%25"}) == "things:///add?title=100%2525"
    assert build("add", {"title": "%E4%B9%B0"}) == "things:///add?title=%25E4%25B9%25B0"


def test_hex_is_uppercase_everywhere():
    url = build("add", {"title": "\n/&#?=+,@:%\"'买🎉"})
    assert not re.search(r"%[0-9A-F]?[a-f]", url), url


# ---- D.1: Unicode -----------------------------------------------------------------------------------

UNICODE_CASES = [
    ("cjk", "买牛奶"),
    ("cjk_ext_a", "㐀㑇"),
    ("fullwidth_punct", "买菜，做饭！注意：好？"),
    ("fullwidth_digits", "１０月１日"),
    ("emoji", "Party 🎉"),
    ("emoji_zwj_family", "👨‍👩‍👧"),
    ("emoji_variation_selector", "❤️"),
    ("keycap", "1️⃣"),
    ("flag_regional_indicators", "🇨🇳"),
    ("combining_marks", "é ñ ä"),
    ("rtl_arabic_with_rlm", "‏مرحبا بالعالم"),
    ("hebrew", "שלום"),
    ("mixed_bidi", "Call אבא at 5"),
    ("japanese_kana", "こんにちは"),
    ("korean", "안녕하세요"),
    ("thai_combining", "สวัสดี"),
    ("zero_width_space", "a​b"),
    ("nbsp", "a b"),
    ("ideographic_space", "a　b"),
    ("bom_inside", "a﻿b"),
    ("surrogate_pair_math", "𝔘𝔫𝔦"),
]


@pytest.mark.parametrize("name,text", UNICODE_CASES, ids=[n for n, _ in UNICODE_CASES])
def test_unicode_value_is_utf8_percent_encoded(name, text):
    expected = "things:///add?title=" + "".join(
        ch if ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~" else pct(ch)
        for ch in text)
    url = build("add", {"title": text})
    assert url == expected
    assert url.isascii()
    assert unquote(url[len("things:///add?title="):]) == text


def test_cjk_example_3_and_emoji_example_4():
    assert build("add", {"title": "买牛奶", "when": "today"}) == "things:///add?title=%E4%B9%B0%E7%89%9B%E5%A5%B6&when=today"
    assert build("add", {"title": "Party 🎉"}) == "things:///add?title=Party%20%F0%9F%8E%89"


# ---- D.3: worked examples byte-for-byte -------------------------------------------------------------

def test_example_1_slash_ampersand_hash():
    assert build("add", {"title": "Review a/b test & ship #1"}) == "things:///add?title=Review%20a%2Fb%20test%20%26%20ship%20%231"


def test_example_2_question_equals_plus():
    assert build("add", {"title": "Ship it? x=1 C++"}) == "things:///add?title=Ship%20it%3F%20x%3D1%20C%2B%2B"


def test_example_5_newline_and_url_in_notes():
    assert build("add", {"title": "Buy milk", "notes": "line1\nsee https://x.y/z?a=1&b=2"}) == (
        "things:///add?title=Buy%20milk&notes=line1%0Asee%20https%3A%2F%2Fx.y%2Fz%3Fa%3D1%26b%3D2")


def test_example_6_tags_checklist_list_reminder():
    url = build("add", {"title": "Review a/b test & ship #1", "notes": "see https://x.y/z?a=1&b=2",
                        "when": "2026-09-11@18:00", "tags": ["Errand", "Home"], "checklist-items": ["买菜", "做饭"],
                        "list": "Work"})
    assert url == ("things:///add?title=Review%20a%2Fb%20test%20%26%20ship%20%231&notes=see%20https%3A%2F%2Fx.y%2Fz"
                   "%3Fa%3D1%26b%3D2&when=2026-09-11%4018%3A00&tags=Errand%2CHome&checklist-items=%E4%B9%B0%E8%8F%9C"
                   "%0A%E5%81%9A%E9%A5%AD&list=Work")


def test_example_7_update_with_token_cjk_and_deadline():
    url = build("update", {"id": "ABC123", "title": "完成 Q3 复盘", "deadline": "2026-09-30"}, token="SECRET")
    assert url == "things:///update?id=ABC123&title=%E5%AE%8C%E6%88%90%20Q3%20%E5%A4%8D%E7%9B%98&deadline=2026-09-30&auth-token=SECRET"
    assert mask_url(url).endswith("&deadline=2026-09-30&auth-token=***")
    assert "SECRET" not in mask_url(url)


def test_example_8_complete():
    assert build("update", {"id": "ABC123", "completed": True}, token="SECRET") == "things:///update?id=ABC123&completed=true&auth-token=SECRET"


def test_example_9_clear_deadline_keeps_empty_value():
    assert build("update", {"id": "ABC123", "deadline": ""}, token="SECRET") == "things:///update?id=ABC123&deadline=&auth-token=SECRET"


def test_example_10_add_project_emoji_todos():
    assert build("add-project", {"title": "Ship 🚀 v2", "area": "Work", "to-dos": ["Plan", "Build", "Ship"]}) == (
        "things:///add-project?title=Ship%20%F0%9F%9A%80%20v2&area=Work&to-dos=Plan%0ABuild%0AShip")


def test_example_11_json_minimal():
    assert build_json([{"type": "to-do", "attributes": {"title": "Buy milk"}}]) == (
        "things:///json?data=%5B%7B%22type%22%3A%22to-do%22%2C%22attributes%22%3A%7B%22title%22%3A%22Buy%20milk%22%7D%7D%5D")


EXAMPLE_12_INPUT = [{"type": "project", "attributes": {"title": "发布 v2", "area": "Work", "items": [
    {"type": "heading", "attributes": {"title": "准备"}},
    {"type": "to-do", "attributes": {"title": "写文档", "checklist-items": [
        {"type": "checklist-item", "attributes": {"title": "大纲"}}]}}]}}]
EXAMPLE_12_URL = ("things:///json?data=%5B%7B%22type%22%3A%22project%22%2C%22attributes%22%3A%7B%22title%22%3A%22%E5%8F%91"
                  "%E5%B8%83%20v2%22%2C%22area%22%3A%22Work%22%2C%22items%22%3A%5B%7B%22type%22%3A%22heading%22%2C%22attributes"
                  "%22%3A%7B%22title%22%3A%22%E5%87%86%E5%A4%87%22%7D%7D%2C%7B%22type%22%3A%22to-do%22%2C%22attributes%22%3A%7B"
                  "%22title%22%3A%22%E5%86%99%E6%96%87%E6%A1%A3%22%2C%22checklist-items%22%3A%5B%7B%22type%22%3A%22checklist-item"
                  "%22%2C%22attributes%22%3A%7B%22title%22%3A%22%E5%A4%A7%E7%BA%B2%22%7D%7D%5D%7D%7D%5D%7D%7D%5D")


def test_example_12_json_project_heading_cjk_checklist():
    assert build_json(EXAMPLE_12_INPUT) == EXAMPLE_12_URL


def test_example_13_percent_and_quotes():
    assert build("add", {"title": "100% done \"ok\" don't"}) == "things:///add?title=100%25%20done%20%22ok%22%20don%27t"


def test_example_14_show_link():
    assert show_url("K9bx7h1xCJdevvyWardZDq") == "things:///show?id=K9bx7h1xCJdevvyWardZDq"
    assert show_url("a b/c") == "things:///show?id=a%20b%2Fc"


def test_example_15_mask_only_touches_the_token():
    url = "things:///update?id=A&title=auth-token%3Dx&auth-token=SECRET"
    assert mask_url(url) == "things:///update?id=A&title=auth-token%3Dx&auth-token=***"
    assert mask_url(mask_url(url)) == mask_url(url)
    assert mask_url("things:///add?title=x") == "things:///add?title=x"


def test_json_data_uses_compact_separators_and_ensure_ascii_false():
    objects = [{"type": "to-do", "attributes": {"title": "买 牛奶 🥛", "notes": "a\nb\"c\\d", "tags": ["家", "Errand"]}}]
    url = build_json(objects)
    data = unquote(url[len("things:///json?data="):])
    assert data == json.dumps(objects, separators=(",", ":"), ensure_ascii=False)
    assert "\\u" not in data and ": " not in data and ", " not in data
    assert json.loads(data) == objects
    assert url.isascii()


# ---- D.2: canonical parameter order for every command ----------------------------------------------

D2_ORDER = {
    "add": ["title", "titles", "notes", "when", "deadline", "tags", "checklist-items", "list-id", "list",
            "heading-id", "heading", "completed", "canceled"],
    "add-project": ["title", "notes", "when", "deadline", "tags", "area-id", "area", "to-dos", "completed", "canceled"],
    "update": ["id", "title", "notes", "prepend-notes", "append-notes", "when", "deadline", "tags", "add-tags",
               "checklist-items", "prepend-checklist-items", "append-checklist-items", "list-id", "list",
               "heading-id", "heading", "completed", "canceled"],
    "update-project": ["id", "title", "notes", "prepend-notes", "append-notes", "when", "deadline", "tags",
                       "add-tags", "area-id", "area", "completed", "canceled"],
    "show": ["id", "query", "filter"],
}
SAMPLE_VALUES = {"when": "today", "deadline": "2026-09-30", "completed": True, "canceled": False,
                 "tags": ["A", "B"], "add-tags": ["C"], "checklist-items": ["x", "y"], "to-dos": ["p", "q"],
                 "prepend-checklist-items": ["x"], "append-checklist-items": ["y"], "titles": ["t1", "t2"],
                 "filter": "Home,Errand"}


def names_in(url):
    query = url.split("?", 1)[1]
    return [part.split("=", 1)[0] for part in query.split("&")]


@pytest.mark.parametrize("command", sorted(D2_ORDER))
def test_parameter_order_is_canonical_regardless_of_input_order(command):
    params = {key: SAMPLE_VALUES.get(key, "v") for key in reversed(D2_ORDER[command])}
    token = "SECRET" if command.startswith("update") else None
    url = build(command, params, token=token)
    expected = D2_ORDER[command] + (["auth-token"] if token else [])
    assert names_in(url) == expected
    assert url.startswith("things:///" + command + "?")
    assert url.count("?") == 1


def test_param_order_dict_matches_spec_d2():
    for command, order in D2_ORDER.items():
        assert list(url_mod.PARAM_ORDER[command]) == order, command
    assert list(url_mod.PARAM_ORDER["json"]) == ["data"]
    assert list(url_mod.PARAM_ORDER["version"]) == []


def test_version_has_no_parameters():
    assert build("version", {}) == "things:///version"


def test_json_command_via_build_encodes_data_then_token():
    assert build("json", {"data": "[]"}) == "things:///json?data=%5B%5D"
    assert build("json", {"data": "[]"}, token="SECRET") == "things:///json?data=%5B%5D&auth-token=SECRET"


def test_auth_token_is_last_even_when_given_first_and_masked_url_ends_with_stars():
    url = build("update", {"completed": True, "id": "X", "title": "auth-token=zzz"}, token="SECRET")
    assert url == "things:///update?id=X&title=auth-token%3Dzzz&completed=true&auth-token=SECRET"
    assert mask_url(url).endswith("auth-token=***")
    assert mask_url(url).count("***") == 1
    assert "SECRET" not in mask_url(url)


def test_literal_auth_token_text_in_notes_is_encoded_and_survives_masking():
    url = build("add", {"title": "x", "notes": "auth-token=SECRET&auth-token=SECRET"})
    assert url == "things:///add?title=x&notes=auth-token%3DSECRET%26auth-token%3DSECRET"
    assert mask_url(url) == url  # nothing to mask: the '=' is encoded, so it is not a real parameter


def test_no_token_for_add_and_update_without_token_has_no_auth_param():
    assert "auth-token" not in build("add", {"title": "x"})
    assert "auth-token" not in build("update", {"id": "X", "title": "t"})


# ---- D.1: serialisation of Python values ------------------------------------------------------------

def test_none_dropped_empty_string_kept():
    url = build("update", {"id": "X", "title": None, "notes": "", "deadline": "", "when": None}, token="S")
    assert url == "things:///update?id=X&notes=&deadline=&auth-token=S"


def test_bools_serialise_lowercase():
    assert build("add", {"title": "x", "completed": True, "canceled": False}) == "things:///add?title=x&completed=true&canceled=false"
    assert build("update", {"id": "X", "completed": False}, token="S") == "things:///update?id=X&completed=false&auth-token=S"


def test_tags_are_stripped_joined_and_encoded_and_empty_list_omitted():
    assert build("add", {"title": "x", "tags": ["  Errand ", "Home"]}) == "things:///add?title=x&tags=Errand%2CHome"
    assert build("add", {"title": "x", "tags": []}) == "things:///add?title=x"
    assert build("add", {"title": "x", "tags": ["家 务", "a,b"]}) == "things:///add?title=x&tags=%E5%AE%B6%20%E5%8A%A1%2Ca%2Cb"
    assert build("update", {"id": "X", "add-tags": ["A", "B"]}, token="S") == "things:///update?id=X&add-tags=A%2CB&auth-token=S"


def test_newline_lists_join_with_percent_0A():
    assert build("add", {"titles": ["a", "b", "c"]}) == "things:///add?titles=a%0Ab%0Ac"
    assert build("add", {"title": "x", "checklist-items": ["a b", "c/d"]}) == "things:///add?title=x&checklist-items=a%20b%0Ac%2Fd"
    assert build("update", {"id": "X", "prepend-checklist-items": ["1"], "append-checklist-items": ["2", "3"]}, token="S") == (
        "things:///update?id=X&prepend-checklist-items=1&append-checklist-items=2%0A3&auth-token=S")
    assert build("add-project", {"title": "p", "to-dos": ["买菜", "做饭"]}) == "things:///add-project?title=p&to-dos=%E4%B9%B0%E8%8F%9C%0A%E5%81%9A%E9%A5%AD"


def test_when_with_time_encodes_at_and_colon():
    assert build("add", {"title": "x", "when": "2026-09-11@18:00"}).endswith("&when=2026-09-11%4018%3A00")


@pytest.mark.parametrize("value", ["today", "tomorrow", "evening", "anytime", "someday", "2026-09-11", "2026-09-11@18:00", "2026-12-31@00:00"])
def test_valid_when_accepted(value):
    assert url_mod.VALID_WHEN.match(value)
    assert SPEC_VALID_WHEN.match(value)
    assert build("add", {"title": "x", "when": value})


@pytest.mark.parametrize("value", ["Today", "next week", "2026-9-1", "2026-09-11@18:0", "2026-09-11 18:00", "tomorrow@18:00",
                                   "2026-09-11@", "evening@18:00", " today", "today ", "明天", "2026-09-11T18:00", "someday@09:00"])
def test_invalid_when_rejected(value):
    assert not SPEC_VALID_WHEN.match(value)
    assert not url_mod.VALID_WHEN.match(value)
    with pytest.raises(UrlError):
        build("add", {"title": "x", "when": value})


@pytest.mark.parametrize("value", ["today", "tomorrow", "2026-09-30"])
def test_valid_deadline_accepted(value):
    assert url_mod.VALID_DEADLINE.match(value)
    assert build("add", {"title": "x", "deadline": value}).endswith("&deadline=" + value)


@pytest.mark.parametrize("value", ["evening", "anytime", "someday", "2026-09-11@18:00", "Tomorrow", "2026/09/11", "eod", " today"])
def test_invalid_deadline_rejected(value):
    assert not SPEC_VALID_DEADLINE.match(value)
    with pytest.raises(UrlError):
        build("add", {"title": "x", "deadline": value})


def test_clearing_when_or_deadline_with_empty_string_is_not_a_vocabulary_violation():
    assert build("update", {"id": "X", "when": ""}, token="S") == "things:///update?id=X&when=&auth-token=S"
    assert build("update", {"id": "X", "deadline": ""}, token="S") == "things:///update?id=X&deadline=&auth-token=S"


# ---- A.7: limits exactly at and one over -----------------------------------------------------------

def test_string_limit_4000_unencoded_characters_not_bytes():
    assert build("add", {"title": "买" * 4000}).count("%E4%B9%B0") == 4000  # 36,000 encoded chars is fine
    with pytest.raises(UrlError):
        build("add", {"title": "买" * 4001})
    assert build("add", {"title": "a" * 4000})
    with pytest.raises(UrlError):
        build("add", {"title": "a" * 4001})
    with pytest.raises(UrlError):
        build("add", {"title": "x", "list": "L" * 4001})
    with pytest.raises(UrlError):
        build("add-project", {"title": "x", "area": "A" * 4001})


@pytest.mark.parametrize("command,key", [("add", "notes"), ("add-project", "notes"), ("update", "notes"),
                                         ("update", "prepend-notes"), ("update", "append-notes"),
                                         ("update-project", "prepend-notes"), ("update-project", "append-notes")])
def test_notes_limit_10000(command, key):
    base = {"id": "X"} if command.startswith("update") else {"title": "x"}
    assert build(command, dict(base, **{key: "n" * 10000}), token="S")
    assert build(command, dict(base, **{key: "买" * 4001}), token="S"), "notes are not bound by the 4,000 string limit"
    with pytest.raises(UrlError):
        build(command, dict(base, **{key: "n" * 10001}), token="S")


@pytest.mark.parametrize("command,key", [("add", "checklist-items"), ("update", "checklist-items"),
                                         ("update", "prepend-checklist-items"), ("update", "append-checklist-items")])
def test_checklist_limit_100(command, key):
    base = {"id": "X"} if command == "update" else {"title": "x"}
    assert build(command, dict(base, **{key: ["i%d" % i for i in range(100)]}), token="S")
    with pytest.raises(UrlError):
        build(command, dict(base, **{key: ["i%d" % i for i in range(101)]}), token="S")


def test_checklist_joined_value_is_still_one_value_under_the_4000_limit():
    """Stricter reading of A.7 'every value': the %0A-joined checklist string is one URL value."""
    ok = ["x" * 39 for _ in range(100)]  # 100*39 + 99 newlines = 3,999 chars
    assert build("add", {"title": "x", "checklist-items": ok})
    with pytest.raises(UrlError):
        build("add", {"title": "x", "checklist-items": ["x" * 41 for _ in range(100)]})  # 4,199 chars


def test_id_and_tags_values_are_bound_by_the_4000_limit():
    with pytest.raises(UrlError):
        build("update", {"id": "X", "tags": ["t" * 4001]}, token="S")
    with pytest.raises(UrlError):
        build("show", {"id": "i" * 4001})


# ---- D.2: unknown parameters and unknown commands --------------------------------------------------

@pytest.mark.parametrize("command,key", [
    ("add", "area"), ("add", "to-dos"), ("add", "add-tags"), ("add", "prepend-notes"), ("add", "reveal"),
    ("add", "show-quick-entry"), ("add", "creation-date"), ("add", "use-clipboard"), ("add", "Title"),
    ("add-project", "checklist-items"), ("add-project", "heading"), ("add-project", "list"), ("add-project", "list-id"),
    ("add-project", "titles"), ("update", "to-dos"), ("update", "area"), ("update", "duplicate"), ("update", "titles"),
    ("update", "completion-date"), ("update-project", "list"), ("update-project", "checklist-items"),
    ("update-project", "heading-id"), ("show", "title"), ("show", "auth-token"), ("json", "title"), ("version", "id"),
])
def test_unknown_parameter_raises_with_exact_message(command, key):
    params = {"id": "X"} if command in ("update", "update-project", "show") else ({"data": "[]"} if command == "json" else {"title": "x"})
    if command == "version":
        params = {}
    params[key] = "v"
    with pytest.raises(UrlError) as exc:
        build(command, params, token="S")
    assert str(exc.value) == "unknown parameter for %s: %s" % (command, key)


@pytest.mark.parametrize("command", ["add-json", "search", "delete", "ADD", ""])
def test_unknown_command_raises_url_error_never_emits_deprecated_add_json(command):
    with pytest.raises(UrlError):
        build(command, {"title": "x"})


# ---- A.6 / E.10: build_json validation error paths --------------------------------------------------

def todo(**attrs):
    return {"type": "to-do", "attributes": attrs}


JSON_ERRORS = [
    ("bad_type", [{"type": "task", "attributes": {"title": "x"}}], "[0].type"),
    ("missing_type", [{"attributes": {"title": "x"}}], "[0].type"),
    ("heading_at_top_level", [{"type": "heading", "attributes": {"title": "H"}}], "[0].type"),
    ("checklist_item_at_top_level", [{"type": "checklist-item", "attributes": {"title": "c"}}], "[0].type"),
    ("checklist_item_in_project_items", [{"type": "project", "attributes": {"items": [
        {"type": "checklist-item", "attributes": {"title": "c"}}]}}], "[0].attributes.items[0].type"),
    ("project_in_project_items", [{"type": "project", "attributes": {"items": [
        {"type": "heading", "attributes": {"title": "h"}}, {"type": "to-do", "attributes": {"title": "t"}},
        {"type": "project", "attributes": {"title": "nested"}}]}}], "[0].attributes.items[2].type"),
    ("heading_in_checklist", [todo(title="t", **{"checklist-items": [{"type": "heading", "attributes": {"title": "h"}}]})],
     "[0].attributes.checklist-items[0].type"),
    ("tags_as_string", [todo(title="t", tags="a,b")], "[0].attributes.tags"),
    ("tags_with_non_string", [todo(title="t", tags=["a", 1])], "[0].attributes.tags"),
    ("checklist_101", [todo(title="t", **{"checklist-items": [{"type": "checklist-item", "attributes": {"title": "c%d" % i}} for i in range(101)]})],
     "[0].attributes.checklist-items"),
    ("checklist_items_as_strings", [todo(title="t", **{"checklist-items": ["a", "b"]})], "[0].attributes.checklist-items"),
    ("update_without_id", [{"type": "to-do", "operation": "update", "attributes": {"title": "x"}}], "[0].id"),
    ("unknown_attribute", [todo(title="t", foo=1)], "[0].attributes.foo"),
    ("unknown_attribute_second_object", [todo(title="a"), todo(title="b", reveal=True)], "[1].attributes.reveal"),
    ("heading_unknown_attribute", [{"type": "project", "attributes": {"items": [{"type": "heading", "attributes": {"notes": "n"}}]}}],
     "[0].attributes.items[0].attributes.notes"),
    ("heading_archived_not_bool", [{"type": "project", "attributes": {"items": [{"type": "heading", "attributes": {"archived": "yes"}}]}}],
     "[0].attributes.items[0].attributes.archived"),
    ("heading_update_operation", [{"type": "project", "attributes": {"items": [
        {"type": "heading", "operation": "update", "id": "H", "attributes": {"title": "h"}}]}}], "[0].attributes.items[0]"),
    ("bad_operation", [{"type": "to-do", "operation": "delete", "attributes": {}}], "[0].operation"),
    ("items_on_project_update", [{"type": "project", "operation": "update", "id": "P", "attributes": {"items": []}}], "[0].attributes.items"),
    ("add_tags_on_create", [todo(title="t", **{"add-tags": "a"})], "[0].attributes.add-tags"),
    ("items_on_todo", [todo(title="t", items=[])], "[0].attributes.items"),
    ("missing_attributes", [{"type": "to-do"}], "[0].attributes"),
    ("attributes_not_object", [{"type": "to-do", "attributes": "x"}], "[0].attributes"),
    ("completed_not_bool", [todo(title="t", completed="true")], "[0].attributes.completed"),
    ("title_not_string", [todo(title=5)], "[0].attributes.title"),
    ("title_over_4000", [todo(title="x" * 4001)], "[0].attributes.title"),
    ("notes_over_10000", [todo(title="t", notes="n" * 10001)], "[0].attributes.notes"),
    ("nested_notes_over_10000", [{"type": "project", "attributes": {"items": [todo(title="t", notes="n" * 10001)]}}],
     "[0].attributes.items[0].attributes.notes"),
    ("object_not_dict", ["to-do"], "[0]"),
]


@pytest.mark.parametrize("name,objects,path", JSON_ERRORS, ids=[e[0] for e in JSON_ERRORS])
def test_build_json_validation_error_mentions_path(name, objects, path):
    with pytest.raises(UrlError) as exc:
        build_json(objects, token="S")
    assert path in str(exc.value), str(exc.value)


@pytest.mark.parametrize("bad", [{}, {"type": "to-do", "attributes": {}}, "[]", None, 5])
def test_build_json_top_level_must_be_a_list(bad):
    with pytest.raises(UrlError):
        build_json(bad)


def test_build_json_empty_array_is_a_no_op_or_a_clean_error():
    """A.6 does not say whether an empty top-level array is valid; either the no-op URL or UrlError is acceptable."""
    try:
        assert build_json([]) == "things:///json?data=%5B%5D"
    except UrlError:
        pass


def test_build_json_valid_shapes_accepted():
    assert build_json([todo(title="t", notes="n" * 10000, tags=["a"], when="today", deadline="2026-10-01", completed=False)])
    assert build_json([todo(title="t", **{"checklist-items": [{"type": "checklist-item", "attributes": {"title": "c", "completed": True}} for _ in range(100)]})])
    assert build_json([{"type": "project", "attributes": {"items": [{"type": "heading", "attributes": {"title": "h", "archived": False}}]}}])
    assert build_json([{"type": "to-do", "operation": "create", "attributes": {}}])


def test_build_json_update_needs_token_and_appends_it_last():
    objects = [{"type": "to-do", "operation": "update", "id": "X", "attributes": {"title": "t", "add-tags": "a,b", "append-notes": "n"}}]
    with pytest.raises(UrlError):
        build_json(objects)
    url = build_json(objects, token="SECRET")
    assert url.endswith("&auth-token=SECRET") and url.startswith("things:///json?data=")
    assert mask_url(url).endswith("&auth-token=***")
    assert build_json([todo(title="t")], token="SECRET") == build_json([todo(title="t")]), "create-only payloads carry no token"


def test_build_json_never_emits_deprecated_add_json():
    assert build_json([todo(title="t")]).startswith("things:///json?")


# ---- C.7 count_items --------------------------------------------------------------------------------

@pytest.mark.parametrize("command,params,expected", [
    ("add", {"title": "x"}, 1), ("add", {"titles": ["a", "b", "c"]}, 3), ("add", {"titles": "a\nb"}, 2),
    ("add", {"title": "x", "checklist-items": ["a"] * 50}, 1),
    ("add-project", {"title": "p"}, 1), ("add-project", {"title": "p", "to-dos": ["a", "b"]}, 3),
    ("add-project", {"title": "p", "to-dos": "a\nb\nc"}, 4),
    ("update", {"id": "X", "completed": True}, 1), ("update-project", {"id": "X"}, 1), ("show", {"id": "X"}, 1),
    ("json", [todo(title="a"), todo(title="b")], 2),
    ("json", EXAMPLE_12_INPUT, 3),  # project + heading + to-do; the checklist item is not counted
    ("json", [{"type": "project", "attributes": {"items": [{"type": "heading", "attributes": {}}] + [todo(title="t", **{"checklist-items": [{"type": "checklist-item", "attributes": {"title": "c"}}] * 5})] * 4}}], 6),
    ("json", [], 0),
])
def test_count_items_table(command, params, expected):
    assert count_items(command, params) == expected
