"""URL building and encoding (SPEC sections C.4, D)."""

import pytest

from things_lib import url
from things_lib.token import mask_url
from things_lib.url import UrlError, build, build_json, count_items, encode, show_url

EXAMPLE_12 = [{"type": "project", "attributes": {"title": "发布 v2", "area": "Work", "items": [
    {"type": "heading", "attributes": {"title": "准备"}},
    {"type": "to-do", "attributes": {"title": "写文档", "checklist-items": [
        {"type": "checklist-item", "attributes": {"title": "大纲"}}]}}]}}]


def test_example_1_slash_ampersand_hash():
    assert build("add", {"title": "Review a/b test & ship #1"}) == \
        "things:///add?title=Review%20a%2Fb%20test%20%26%20ship%20%231"


def test_example_2_question_equals_plus():
    assert build("add", {"title": "Ship it? x=1 C++"}) == "things:///add?title=Ship%20it%3F%20x%3D1%20C%2B%2B"


def test_example_3_cjk():
    assert build("add", {"title": "买牛奶", "when": "today"}) == "things:///add?title=%E4%B9%B0%E7%89%9B%E5%A5%B6&when=today"


def test_example_4_emoji():
    assert build("add", {"title": "Party 🎉"}) == "things:///add?title=Party%20%F0%9F%8E%89"


def test_example_5_newline_and_url_in_notes():
    assert build("add", {"title": "Buy milk", "notes": "line1\nsee https://x.y/z?a=1&b=2"}) == \
        "things:///add?title=Buy%20milk&notes=line1%0Asee%20https%3A%2F%2Fx.y%2Fz%3Fa%3D1%26b%3D2"


def test_example_6_full_add():
    params = {"title": "Review a/b test & ship #1", "notes": "see https://x.y/z?a=1&b=2",
              "when": "2026-09-11@18:00", "tags": ["Errand", "Home"], "checklist-items": ["买菜", "做饭"],
              "list": "Work"}
    assert build("add", params) == (
        "things:///add?title=Review%20a%2Fb%20test%20%26%20ship%20%231&notes=see%20https%3A%2F%2Fx.y%2Fz%3Fa%3D1%26b%3D2"
        "&when=2026-09-11%4018%3A00&tags=Errand%2CHome&checklist-items=%E4%B9%B0%E8%8F%9C%0A%E5%81%9A%E9%A5%AD&list=Work")


def test_example_7_update_with_token_and_mask():
    built = build("update", {"id": "ABC123", "title": "完成 Q3 复盘", "deadline": "2026-09-30"}, token="SECRET")
    assert built == "things:///update?id=ABC123&title=%E5%AE%8C%E6%88%90%20Q3%20%E5%A4%8D%E7%9B%98&deadline=2026-09-30&auth-token=SECRET"
    assert mask_url(built).endswith("&deadline=2026-09-30&auth-token=***")
    assert "SECRET" not in mask_url(built)


def test_example_8_complete():
    assert build("update", {"id": "ABC123", "completed": True}, token="SECRET") == \
        "things:///update?id=ABC123&completed=true&auth-token=SECRET"


def test_example_9_clear_deadline():
    assert build("update", {"id": "ABC123", "deadline": ""}, token="SECRET") == \
        "things:///update?id=ABC123&deadline=&auth-token=SECRET"


def test_example_10_add_project():
    assert build("add-project", {"title": "Ship 🚀 v2", "area": "Work", "to-dos": ["Plan", "Build", "Ship"]}) == \
        "things:///add-project?title=Ship%20%F0%9F%9A%80%20v2&area=Work&to-dos=Plan%0ABuild%0AShip"


def test_example_11_json_minimal():
    assert build_json([{"type": "to-do", "attributes": {"title": "Buy milk"}}]) == \
        "things:///json?data=%5B%7B%22type%22%3A%22to-do%22%2C%22attributes%22%3A%7B%22title%22%3A%22Buy%20milk%22%7D%7D%5D"


def test_example_12_json_project_with_heading():
    assert build_json(EXAMPLE_12) == (
        "things:///json?data=%5B%7B%22type%22%3A%22project%22%2C%22attributes%22%3A%7B%22title%22%3A%22%E5%8F%91%E5%B8%83%20v2%22"
        "%2C%22area%22%3A%22Work%22%2C%22items%22%3A%5B%7B%22type%22%3A%22heading%22%2C%22attributes%22%3A%7B%22title%22%3A"
        "%22%E5%87%86%E5%A4%87%22%7D%7D%2C%7B%22type%22%3A%22to-do%22%2C%22attributes%22%3A%7B%22title%22%3A%22%E5%86%99%E6%96%87"
        "%E6%A1%A3%22%2C%22checklist-items%22%3A%5B%7B%22type%22%3A%22checklist-item%22%2C%22attributes%22%3A%7B%22title%22%3A"
        "%22%E5%A4%A7%E7%BA%B2%22%7D%7D%5D%7D%7D%5D%7D%7D%5D")


def test_example_13_percent_and_quotes():
    assert build("add", {"title": "100% done \"ok\" don't"}) == "things:///add?title=100%25%20done%20%22ok%22%20don%27t"


def test_example_14_show_url():
    assert show_url("K9bx7h1xCJdevvyWardZDq") == "things:///show?id=K9bx7h1xCJdevvyWardZDq"


def test_example_15_mask_is_idempotent_and_targeted():
    masked = mask_url("things:///update?id=A&title=auth-token%3Dx&auth-token=SECRET")
    assert masked == "things:///update?id=A&title=auth-token%3Dx&auth-token=***"
    assert mask_url(masked) == masked


@pytest.mark.parametrize("raw,expected", [
    (" ", "%20"), ("/", "%2F"), ("&", "%26"), ("#", "%23"), ("?", "%3F"), ("=", "%3D"), ("+", "%2B"),
    (",", "%2C"), ("@", "%40"), (":", "%3A"), ("%", "%25"), ('"', "%22"), ("'", "%27"), ("\n", "%0A"),
    ("~-_.", "~-_."), ("买", "%E4%B9%B0"), ("🎉", "%F0%9F%8E%89"),
])
def test_encode_table(raw, expected):
    assert encode(raw) == expected


def test_parameter_order_is_canonical_not_input_order():
    built = build("add", {"completed": True, "list": "Work", "tags": ["A"], "when": "today", "title": "t"})
    assert built == "things:///add?title=t&when=today&tags=A&list=Work&completed=true"
    built = build("update-project", {"canceled": False, "area": "W", "id": "X"}, token="T")
    assert built == "things:///update-project?id=X&area=W&canceled=false&auth-token=T"


def test_none_dropped_empty_kept_bools_and_lists():
    assert build("add", {"title": "t", "notes": None}) == "things:///add?title=t"
    assert build("update", {"id": "X", "notes": ""}, token="T") == "things:///update?id=X&notes=&auth-token=T"
    assert build("add", {"title": "t", "canceled": False}) == "things:///add?title=t&canceled=false"
    assert build("add", {"title": "t", "tags": []}) == "things:///add?title=t"
    assert build("add", {"title": "t", "tags": [" A ", "B"]}) == "things:///add?title=t&tags=A%2CB"


def test_version_has_no_parameters():
    assert build("version", {}) == "things:///version"


def test_unknown_parameter_and_command_raise():
    with pytest.raises(UrlError, match="unknown parameter for add: area"):
        build("add", {"title": "t", "area": "W"})
    with pytest.raises(UrlError, match="unknown parameter for update-project: list"):
        build("update-project", {"id": "X", "list": "W"}, token="T")
    with pytest.raises(UrlError, match="unknown command"):
        build("add-json", {})


def test_limits_raise():
    with pytest.raises(UrlError):
        build("add", {"title": "x" * 4001})
    build("add", {"title": "x" * 4000})
    with pytest.raises(UrlError):
        build("add", {"title": "t", "notes": "n" * 10001})
    build("add", {"title": "t", "notes": "n" * 10000})
    with pytest.raises(UrlError):
        build("add", {"title": "t", "checklist-items": [str(i) for i in range(101)]})
    build("add", {"title": "t", "checklist-items": [str(i) for i in range(100)]})
    with pytest.raises(UrlError):
        build("update", {"id": "X", "append-checklist-items": "\n".join(str(i) for i in range(101))}, token="T")


@pytest.mark.parametrize("value,ok", [
    ("today", True), ("tomorrow", True), ("evening", True), ("anytime", True), ("someday", True),
    ("2026-09-11", True), ("2026-09-11@18:00", True), ("2026-09-11 18:00", False), ("next week", False),
    ("明天", False), ("Tomorrow", False), ("2026-9-1", False), ("2026-09-11@6pm", False),
])
def test_valid_when(value, ok):
    assert bool(url.VALID_WHEN.match(value)) is ok
    if not ok:
        with pytest.raises(UrlError):
            build("add", {"title": "t", "when": value})


@pytest.mark.parametrize("value,ok", [
    ("today", True), ("tomorrow", True), ("2026-09-30", True), ("evening", False), ("someday", False),
    ("2026-09-30@18:00", False), ("anytime", False),
])
def test_valid_deadline(value, ok):
    assert bool(url.VALID_DEADLINE.match(value)) is ok
    if not ok:
        with pytest.raises(UrlError):
            build("add", {"title": "t", "deadline": value})


def test_build_json_validation_paths():
    with pytest.raises(UrlError, match=r"^\[0\]\.type: 'heading' is not allowed here"):
        build_json([{"type": "heading", "attributes": {"title": "h"}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes\.items\[1\]\.type: 'checklist-item' is not allowed here"):
        build_json([{"type": "project", "attributes": {"items": [
            {"type": "heading", "attributes": {}}, {"type": "checklist-item", "attributes": {}}]}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.id: required when operation is update"):
        build_json([{"type": "to-do", "operation": "update", "attributes": {"title": "x"}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes\.tags: must be an array of strings"):
        build_json([{"type": "to-do", "attributes": {"tags": "a,b"}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes\.checklist-items: more than 100 items"):
        build_json([{"type": "to-do", "attributes": {"checklist-items": [
            {"type": "checklist-item", "attributes": {"title": "i"}} for _ in range(101)]}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes\.notes: exceeds 10000"):
        build_json([{"type": "to-do", "attributes": {"notes": "n" * 10001}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes\.title: exceeds 4000"):
        build_json([{"type": "to-do", "attributes": {"title": "t" * 4001}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes\.when: invalid when value"):
        build_json([{"type": "to-do", "attributes": {"when": "next week"}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes\.heading: not an allowed attribute"):
        build_json([{"type": "project", "attributes": {"heading": "x"}}])
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes\.items: not an allowed attribute"):
        build_json([{"type": "project", "operation": "update", "id": "P", "attributes": {"items": []}}], token="T")
    with pytest.raises(UrlError, match=r"^\[0\]\.attributes: required"):
        build_json([{"type": "to-do"}])
    with pytest.raises(UrlError, match=r"^\[0\]\.operation: must be create or update"):
        build_json([{"type": "to-do", "operation": "delete", "attributes": {}}])
    with pytest.raises(UrlError, match="^data: "):
        build_json({"type": "to-do"})


def test_build_json_update_needs_token_and_appends_it_last():
    objects = [{"type": "to-do", "operation": "update", "id": "ABC", "attributes": {"title": "x"}}]
    with pytest.raises(UrlError, match="auth token required"):
        build_json(objects)
    built = build_json(objects, token="SECRET")
    assert built.endswith("&auth-token=SECRET")
    assert mask_url(built).endswith("&auth-token=***")
    assert "auth-token" not in build_json([{"type": "to-do", "attributes": {}}], token="SECRET")


def test_count_items_table():
    assert count_items("add", {"title": "t"}) == 1
    assert count_items("add", {"titles": ["a", "b", "c"]}) == 3
    assert count_items("add", {"titles": "a\nb"}) == 2
    assert count_items("add-project", {"title": "p", "to-dos": ["a", "b"]}) == 3
    assert count_items("add-project", {"title": "p"}) == 1
    for command in ("update", "update-project", "show"):
        assert count_items(command, {"id": "x"}) == 1
    assert count_items("json", EXAMPLE_12) == 3  # project + heading + to-do; checklist item not counted
    assert count_items("json", [{"type": "to-do", "attributes": {}}] * 4) == 4
