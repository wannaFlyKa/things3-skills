"""Python-side search semantics (SPEC section E.6)."""

from things_lib import read

SYN = [["报销", "expense", "reimbursement"], ["周报", "weekly report"]]


def titles(items):
    return [item["title"] for item in items]


def test_fixture_inbox_case_insensitive():
    assert set(titles(read.search("inbox"))) == {"To-Do in Inbox", "To-Do in Inbox with Checklist Items"}
    assert set(titles(read.search("INBOX"))) == {"To-Do in Inbox", "To-Do in Inbox with Checklist Items"}
    assert all(item["match"] == "title" for item in read.search("inbox"))


def test_fixture_with_notes_matches_tokens_separately():
    results = read.search("with notes", item_type="to-do")
    assert len(results) == 8
    assert all(item["match"] == "notes" for item in results)
    assert all(sorted(item["matched_terms"]) == ["notes", "with"] for item in results)


def test_fixture_heading_status_all_excludes_heading_row():
    results = read.search("heading", status="all")
    assert set(titles(results)) == {"Cancelled To-Do in Heading", "Completed To-Do in Heading", "To-Do in Heading"}
    assert all(item["type"] != "heading" for item in results)


def test_status_and_type_filters():
    assert titles(read.search("heading", status="completed")) == ["Completed To-Do in Heading"]
    assert titles(read.search("heading", status="canceled")) == ["Cancelled To-Do in Heading"]
    assert set(titles(read.search("project", item_type="project"))) == \
        {"Project in Area 1", "Project in Today", "Project without Area"}
    assert all(item["type"] == "to-do" for item in read.search("project", item_type="to-do"))


def test_area_and_project_filters_accept_uuid_or_title():
    by_title = read.search("to-do", area="area 1", status="all")
    by_uuid = read.search("to-do", area="DciSFacytdrNG1nRaMJPgY", status="all")
    assert titles(by_title) == titles(by_uuid) and by_title
    # E.6 step 1: membership is inclusive, so items of "Project in Area 1" count as being in Area 1 too.
    area1_projects = {"3x1QqJqfvZyhtw8NSdnZqG", "SkLdfSe1MXR5vMV1gMYkHE"}   # Project in Area 1, Cancelled Project in Area
    area1_headings = {"6QpDLSHZMRAUSAeZ9mNvgt"}                             # Heading (in Project in Area 1)
    assert all(item.get("area") == "DciSFacytdrNG1nRaMJPgY" or item.get("project") in area1_projects
               or item.get("heading") in area1_headings for item in by_title)
    assert "To-Do in Heading" in titles(by_title), "heading children inherit the project's area"
    in_project = read.search("heading", project="Project in Area 1", status="all")
    assert set(titles(in_project)) == {"Cancelled To-Do in Heading", "Completed To-Do in Heading", "To-Do in Heading"}
    assert read.search("heading", project="3x1QqJqfvZyhtw8NSdnZqG", status="all")


def test_limit():
    assert len(read.search("to-do", status="all", limit=3)) == 3
    assert len(read.search("to-do", status="all", limit=100)) > 3


def test_enriched_results():
    item = read.search("inbox")[0]
    assert item["link"].startswith("things:///show?id=") and item["repeating"] is False
    assert "days_until_deadline" in item


def fake_tasks(**filters):
    return [
        {"uuid": "1", "type": "to-do", "title": "提交报销单", "notes": "", "modified": "2026-09-01 10:00:00"},
        {"uuid": "2", "type": "to-do", "title": "Expense report", "notes": "", "modified": "2026-09-03 10:00:00"},
        {"uuid": "3", "type": "to-do", "title": "Call Bob", "notes": "about the reimbursement", "modified": "2026-09-05 10:00:00"},
        {"uuid": "4", "type": "to-do", "title": "写周报", "notes": "weekly", "modified": "2026-09-02 10:00:00"},
        {"uuid": "5", "type": "heading", "title": "报销 heading", "notes": "", "modified": "2026-09-09 10:00:00"},
        {"uuid": "6", "type": "to-do", "title": "trashed 报销", "notes": "", "modified": "2026-09-09 10:00:00", "trashed": True},
        {"uuid": "7", "type": "to-do", "title": "Milk", "notes": "买牛奶 and 报销", "modified": "2026-09-04 10:00:00"},
    ]


def test_cjk_substring_and_synonyms(monkeypatch):
    monkeypatch.setattr(read, "tasks_raw", fake_tasks)
    monkeypatch.setattr(read, "repeating_uuids", lambda: set())
    plain = read.search("报销")
    assert [item["uuid"] for item in plain] == ["1", "7"]  # title hit first, then notes hit
    assert plain[0]["match"] == "title" and plain[1]["match"] == "notes"
    expanded = read.search("报销", synonyms=SYN)
    assert [item["uuid"] for item in expanded] == ["2", "1", "3", "7"]
    assert expanded[0]["matched_terms"] == ["expense"]
    assert read.search("牛奶", synonyms=SYN)[0]["uuid"] == "7"
    assert read.search("周报", synonyms=SYN)[0]["uuid"] == "4"  # 周报 expands to the phrase "weekly report" too


def test_multi_word_synonym_expands_from_the_phrase_side(monkeypatch):
    """E.6 step 2: 'weekly report' is one term when it equals a synonym member, so it reaches 周报 too."""
    monkeypatch.setattr(read, "tasks_raw", fake_tasks)
    monkeypatch.setattr(read, "repeating_uuids", lambda: set())
    hit = read.search("weekly report", synonyms=SYN)
    assert [item["uuid"] for item in hit] == ["4"]
    assert hit[0]["matched_terms"] == ["周报"]
    assert [i["uuid"] for i in read.search("Weekly  REPORT", synonyms=SYN)] == ["4"]     # casefold + odd spacing
    assert [i["uuid"] for i in read.search("the weekly report", synonyms=SYN)] == []     # "the" still must match
    assert [i["uuid"] for i in read.search("weekly report 报销", synonyms=SYN)] == []    # phrase + extra term
    # without synonyms the phrase is two ordinary tokens, both of which must match
    assert read.search("weekly report") == []
    assert [i["uuid"] for i in read.search("weekly 周报")] == ["4"]


def test_default_synonyms_reach_dentist_from_yaiyi(monkeypatch):
    from things_lib.config import DEFAULTS
    monkeypatch.setattr(read, "tasks_raw", lambda **f: [
        {"uuid": "d", "type": "to-do", "title": "Dentist appointment", "notes": "", "modified": "2026-09-01 10:00:00"}])
    monkeypatch.setattr(read, "repeating_uuids", lambda: set())
    hit = read.search("牙医", synonyms=DEFAULTS["synonyms"])
    assert [item["title"] for item in hit] == ["Dentist appointment"]
    assert hit[0]["matched_terms"] == ["dentist"]


def test_ranking_title_before_notes_then_modified_desc(monkeypatch):
    monkeypatch.setattr(read, "tasks_raw", fake_tasks)
    monkeypatch.setattr(read, "repeating_uuids", lambda: set())
    results = read.search("e", synonyms=None)
    kinds = [item["match"] for item in results]
    assert kinds == sorted(kinds, key=lambda k: 0 if k == "title" else 1)
    title_group = [item for item in results if item["match"] == "title"]
    assert [item["modified"] for item in title_group] == sorted((i["modified"] for i in title_group), reverse=True)


def test_every_token_must_match(monkeypatch):
    monkeypatch.setattr(read, "tasks_raw", fake_tasks)
    monkeypatch.setattr(read, "repeating_uuids", lambda: set())
    assert read.search("expense nothing") == []
    assert [i["uuid"] for i in read.search("call reimbursement")] == ["3"]
