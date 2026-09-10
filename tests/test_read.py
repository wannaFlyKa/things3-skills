"""Read wrappers against the fixture database (SPEC sections B, C.8, E.7, J)."""

from datetime import date, datetime

import pytest

from things_lib import read
from things_lib.read import ReadError

TODAY_TITLES = ["Upcoming To-Do in Today (yellow)", "Project in Today", "To-Do in Today", "Repeating To-Do",
                "Overdue Todo automatically shown in Today"]


def titles(items):
    return [item["title"] for item in items]


def test_database_status_and_path():
    assert read.database_status() == "fixture"
    assert read.database_error() is None
    assert read.database_path().endswith("tests/fixtures/main.sqlite")
    assert read.things_version() == "1.0.1"


def test_unavailable_when_thingsdb_missing(monkeypatch):
    monkeypatch.setenv("THINGSDB", "/nonexistent/dir/main.sqlite")
    assert read.database_status() == "unavailable"
    assert "unable to open database file" in read.database_error()
    with pytest.raises(ReadError):
        read.inbox()
    assert read.is_repeating("K9bx7h1xCJdevvyWardZDq") is None
    assert read.repeating_uuids() == set()
    assert "repeating detection unavailable" in read.take_warnings()
    assert read.repeating_templates(date(2026, 9, 9)) == {"due": [], "templates": 0,
                                                          "warning": "repeating to-dos could not be predicted"}
    assert read.resolve_type("K9bx7h1xCJdevvyWardZDq") is None
    assert read.token_from_database() is None


def test_lists(now):
    assert len(read.inbox(now)) == 2
    assert titles(read.today(now)) == TODAY_TITLES
    assert len(read.upcoming(now)) == 1
    assert len(read.someday(now)) == 1
    assert len(read.deadlines(now)) == 4
    assert len(read.anytime(now)) == 14
    assert len(read.projects()) == 3
    assert sorted(titles(read.areas())) == ["Area 1", "Area 2", "Area 3"]
    assert sorted(read.tag_titles()) == ["Errand", "Home", "Important", "Office", "Pending"]
    assert len(read.tags()) == 5 and all(tag["type"] == "tag" for tag in read.tags())


def test_today_and_upcoming_follow_now_not_the_wall_clock(now):
    """--now is injectable everywhere (SPEC): the fixture's 2026-09-17 to-do moves Upcoming -> Today with `now`."""
    future = read.upcoming(now)
    assert [item["start_date"] for item in future] == ["2026-09-17"]
    later = datetime(2026, 9, 17, 10, 0)
    assert read.upcoming(later) == []
    moved = read.today(later)
    assert len(moved) == len(TODAY_TITLES) + 1
    assert "To-Do in Upcoming" in titles(moved)
    assert read.upcoming(datetime(2026, 9, 16, 23, 59)) and "To-Do in Upcoming" not in titles(read.today(datetime(2026, 9, 16)))
    # a date far in the past: the scheduled (yellow) and overdue predictions have not arrived yet, so only the
    # confirmed Anytime items remain, and every dated item is Upcoming
    early = read.today(date(2000, 1, 1))
    assert titles(early) == ["Project in Today", "To-Do in Today", "Repeating To-Do"]
    assert set(titles(read.upcoming(date(2000, 1, 1)))) >= {"To-Do in Upcoming", "Upcoming To-Do in Today (yellow)"}


def test_today_has_evening_and_repeating_flags(now):
    items = read.today(now)
    assert all(item["evening"] is False for item in items)
    by_title = {item["title"]: item for item in items}
    assert by_title["Repeating To-Do"]["repeating"] is True
    assert by_title["To-Do in Today"]["repeating"] is False
    assert read.take_warnings() == []


def test_projects_by_area_uuid_or_title():
    assert titles(read.projects("Area 1")) == ["Project in Area 1"]
    assert titles(read.projects("DciSFacytdrNG1nRaMJPgY")) == ["Project in Area 1"]
    assert read.projects("Nowhere") == []
    assert read.take_warnings() == ["unknown area: Nowhere"]


def test_get_variants(now):
    todo = read.get("3Eva4XFof6zWb9iSfYy4ej", now)
    assert todo["type"] == "to-do" and len(todo["checklist"]) == 3
    assert todo["link"] == "things:///show?id=3Eva4XFof6zWb9iSfYy4ej" and todo["repeating"] is False
    plain = read.get("5pUx6PESj3ctFYbgth1PXY", now)
    assert plain["checklist"] == []
    assert read.get("does-not-exist") is None
    template = read.get("N1PJHsbjct4mb1bhcs7aHa", now)
    assert template["title"] == "Repeating To-Do" and template["repeating"] is True
    project = read.get("3x1QqJqfvZyhtw8NSdnZqG", now)
    assert project["type"] == "project" and any(item["type"] == "heading" for item in project["items"])
    heading = next(item for item in project["items"] if item["type"] == "heading")
    assert titles(heading["items"]) == ["To-Do in Heading"] and heading["items"][0]["repeating"] is False
    assert read.get("DciSFacytdrNG1nRaMJPgY")["type"] == "area"


def test_headings_and_repeating_detection(now):
    assert len(read.tasks_raw(type="heading")) == 1
    assert read.repeating_uuids() == {"K9bx7h1xCJdevvyWardZDq", "N1PJHsbjct4mb1bhcs7aHa"}
    assert read.is_repeating("K9bx7h1xCJdevvyWardZDq") is True
    assert read.is_repeating("N1PJHsbjct4mb1bhcs7aHa") is True
    assert read.is_repeating("5pUx6PESj3ctFYbgth1PXY") is False
    assert read.is_repeating("nope") is None
    assert read.repeating_templates(now) == {"due": [], "templates": 1, "warning": None}
    assert read.repeating_templates(now.date()) == {"due": [], "templates": 1, "warning": None}


def test_enrich(now):
    item = read.enrich({"uuid": "K9bx7h1xCJdevvyWardZDq", "deadline": "2021-03-28"}, now)
    assert item["repeating"] is True and item["link"] == "things:///show?id=K9bx7h1xCJdevvyWardZDq"
    assert item["days_until_deadline"] == (date(2021, 3, 28) - date(2026, 9, 9)).days
    assert read.enrich({"uuid": "x", "deadline": None}, now)["days_until_deadline"] is None
    assert read.enrich({"uuid": "x", "deadline": "2026-09-12"}, now, repeating=set())["days_until_deadline"] == 3


def test_stale_per_e7(now):
    items = read.stale(30, now)
    assert sorted(titles(items)) == sorted(["Overdue Todo automatically shown in Today", "Overdue Todo not shown in Today",
                                            "To-Do in Anytime", "To-Do in Area 1", "To-Do in Heading", "To-Do in Project",
                                            "Todo in Area 1", "Todo in Area 3"])
    assert [item["modified"] for item in items] == sorted(item["modified"] for item in items)
    assert all(item["age_days"] > 30 and item["repeating"] is False for item in items)
    assert read.stale(10000, now) == []


def test_overdue_per_e7(now):
    items = read.overdue(now.date())
    assert [item["uuid"] for item in items] == ["K9bx7h1xCJdevvyWardZDq", "KisAmSsnzCcRRumjY4TkVV", "Cc73oaq1C2mDMpZZUJaBxe"]
    assert items[0]["repeating"] is True and items[1]["repeating"] is False
    assert [item["deadline"] for item in items] == sorted(item["deadline"] for item in items)
    assert read.overdue(datetime(2020, 1, 1)) == []


def test_logbook(now):
    assert read.logbook(7, now.date()) == []
    days = (now.date() - date(2020, 1, 1)).days
    items = read.logbook(days, now)
    assert len(items) == 23
    stops = [item["stop_date"] for item in items]
    assert stops == sorted(stops, reverse=True)


def test_resolve_type_and_token():
    assert read.resolve_type("3x1QqJqfvZyhtw8NSdnZqG") == "project"
    assert read.resolve_type("5pUx6PESj3ctFYbgth1PXY") == "to-do"
    assert read.resolve_type("6QpDLSHZMRAUSAeZ9mNvgt") == "heading"
    assert read.resolve_type("DciSFacytdrNG1nRaMJPgY") == "area"
    assert read.resolve_type("nope") is None
    assert read.token_from_database() == "vKkylosuSuGwxrz7qcklOw"


def test_damaged_things_py_reports_the_import_error(monkeypatch):
    """A damaged bundled copy must not be reported as 'not installed' (doctor's database.error)."""
    def broken():
        raise ImportError("things.py is damaged: SyntaxError: invalid syntax (api.py, line 1)")
    monkeypatch.setattr(read, "_import_things", broken)
    assert read.database_status() == "unavailable"
    assert read.database_error() == "things.py is damaged: SyntaxError: invalid syntax (api.py, line 1)"
    with pytest.raises(ReadError, match="damaged"):
        read.inbox()
    assert read.database_error() == "things.py is damaged: SyntaxError: invalid syntax (api.py, line 1)"


def test_functions_are_monkeypatchable(monkeypatch):
    monkeypatch.setattr(read, "inbox", lambda now=None: [{"title": "fake"}])
    assert read.inbox()[0]["title"] == "fake"
