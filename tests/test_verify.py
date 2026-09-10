"""Post-write verification with injected readers and clocks (SPEC section C.6)."""

from datetime import datetime

from things_lib import read, verify
from things_lib.verify import VerifyResult, verify_created, verify_updated


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def test_non_open_transport_returns_immediately():
    clock = Clock()
    result = verify_created(["x"], datetime(2026, 9, 9, 10, 0), transport="record", sleep=clock.sleep, clock=clock)
    assert result == VerifyResult(False, "transport record: nothing was sent to Things", [], [], [])
    result = verify_updated(["a"], lambda item: True, transport="dry", sleep=clock.sleep, clock=clock)
    assert result.reason == "transport dry: nothing was sent to Things"
    assert clock.slept == []


def test_database_unavailable(monkeypatch):
    monkeypatch.setattr(read, "database_status", lambda: "unavailable")
    result = verify_created(["x"], datetime(2026, 9, 9, 10, 0), transport="open")
    assert result == VerifyResult(False, "database unavailable", [], [], [])


def test_created_matches_title_and_creation_window(monkeypatch):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    since = datetime(2026, 9, 9, 10, 0, 0)
    items = [
        {"uuid": "old", "title": "Buy milk", "created": "2026-09-09 09:59:40"},   # 20 s before since: too old
        {"uuid": "ok1", "title": "Buy milk", "created": "2026-09-09 09:59:55"},   # within the 10 s slack
        {"uuid": "ok2", "title": "Buy milk", "created": "2026-09-09 10:00:02"},   # newest wins
        {"uuid": "other", "title": "Other", "created": "2026-09-09 10:00:01"},
    ]
    clock = Clock()
    result = verify_created(["Buy milk", "Other"], since, timeout=3.0, transport="open", poll=0.5,
                            sleep=clock.sleep, clock=clock, reader=lambda: items)
    assert result.verified is True and result.reason is None
    assert result.ids == ["ok2", "other"]
    assert result.links == ["things:///show?id=ok2", "things:///show?id=other"]
    assert [item["uuid"] for item in result.items] == ["ok2", "other"]
    assert clock.slept == [0.5]


def test_created_times_out_with_partial_findings(monkeypatch):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    since = datetime(2026, 9, 9, 10, 0, 0)
    items = [{"uuid": "a", "title": "A", "created": "2026-09-09 10:00:01"}]
    clock = Clock()
    result = verify_created(["A", "Missing"], since, timeout=3.0, transport="open", poll=0.5,
                            sleep=clock.sleep, clock=clock, reader=lambda: items)
    assert result.verified is False and result.reason == "timeout after 3.0s"
    assert result.ids == ["a"] and result.links == ["things:///show?id=a"]
    assert clock.t >= 3.0 and len(clock.slept) >= 6


def test_updated_polls_until_predicate_holds(monkeypatch):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    state = {"calls": 0}

    def reader(item_id):
        state["calls"] += 1
        status = "completed" if state["calls"] >= 3 else "incomplete"
        return {"uuid": item_id, "status": status}

    clock = Clock()
    result = verify_updated(["X"], lambda item: item["status"] == "completed", timeout=3.0, transport="open",
                            poll=0.5, sleep=clock.sleep, clock=clock, reader=reader)
    assert result.verified is True and result.ids == ["X"] and result.links == ["things:///show?id=X"]
    assert result.items[0]["status"] == "completed"


def test_updated_timeout_and_read_error(monkeypatch):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    clock = Clock()
    result = verify_updated(["X", "Y"], lambda item: item["uuid"] == "X", timeout=1.0, transport="open",
                            poll=0.5, sleep=clock.sleep, clock=clock, reader=lambda i: {"uuid": i})
    assert result.verified is False and result.reason == "timeout after 1.0s" and result.ids == ["X"]

    def broken(_item_id):
        raise read.ReadError("boom")

    result = verify_updated(["X"], lambda item: True, timeout=1.0, transport="open", poll=0.5,
                            sleep=clock.sleep, clock=clock, reader=broken)
    assert result.verified is False and result.reason == "read error: boom"


def test_default_reader_uses_fixture(monkeypatch):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    clock = Clock()
    # every fixture row was created in 2021, so nothing is "new" relative to 2026
    result = verify_created(["To-Do in Today"], datetime(2026, 9, 9, 10, 0), timeout=0.5, transport="open",
                            poll=0.5, sleep=clock.sleep, clock=clock)
    assert result.verified is False and result.reason == "timeout after 0.5s"
    old = verify_created(["To-Do in Today"], datetime(2021, 1, 1), timeout=0.5, transport="open",
                         poll=0.5, sleep=clock.sleep, clock=clock)
    assert old.verified is True and old.ids == ["5pUx6PESj3ctFYbgth1PXY"]


def test_updated_duplicate_ids_verify_once(monkeypatch):
    """Finding 1: `good` is keyed by id, so [u, u] must compare against one id, not two."""
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    clock = Clock()
    reader = lambda item_id: {"uuid": item_id, "status": "completed"}  # noqa: E731
    result = verify_updated(["U", "U"], lambda item: True, timeout=3.0, transport="open",
                            poll=0.5, sleep=clock.sleep, clock=clock, reader=reader)
    assert result.verified is True and result.reason is None
    assert result.ids == ["U"] and result.links == ["things:///show?id=U"] and len(result.items) == 1
    assert clock.slept == [0.5], "first poll succeeds; no timeout"
    result = verify_updated(["U", "V", "U"], lambda item: True, timeout=3.0, transport="open",
                            poll=0.5, sleep=clock.sleep, clock=clock, reader=reader)
    assert result.verified is True and result.ids == ["U", "V"]


def test_fixture_database_is_reported_as_overridden_not_unavailable(monkeypatch):
    """Finding 6: THINGSDB set -> status 'fixture'; verification is skipped with an accurate reason."""
    monkeypatch.setattr(read, "database_status", lambda: "fixture")
    expected = "database overridden by THINGSDB; verification runs only against the default Things database"
    result = verify_created(["x"], datetime(2026, 9, 9, 10, 0), transport="open")
    assert result == VerifyResult(False, expected, [], [], [])
    result = verify_updated(["a"], lambda item: True, transport="open")
    assert result == VerifyResult(False, expected, [], [], [])
    monkeypatch.setattr(read, "database_status", lambda: "unavailable")
    assert verify_updated(["a"], lambda item: True, transport="open").reason == "database unavailable"
