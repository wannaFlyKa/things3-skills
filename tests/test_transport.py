"""Transport selection and behaviour (SPEC section C.5)."""

import json
import subprocess
from datetime import datetime, timezone

import pytest

from things_lib import transport
from things_lib.transport import SendResult, TransportError, select_transport, send


def test_select_precedence(monkeypatch):
    monkeypatch.setenv("THINGS_SKILLS_TRANSPORT", "dry")
    assert select_transport("record") == "record"
    assert select_transport() == "dry"
    monkeypatch.delenv("THINGS_SKILLS_TRANSPORT")
    monkeypatch.setattr(transport.platform, "system", lambda: "Linux")
    assert select_transport() == "record"
    monkeypatch.setattr(transport.platform, "system", lambda: "Darwin")
    assert select_transport() == "open"


def test_select_invalid(monkeypatch):
    with pytest.raises(TransportError):
        select_transport("mail")
    monkeypatch.setenv("THINGS_SKILLS_TRANSPORT", "bogus")
    with pytest.raises(TransportError):
        select_transport()


def test_open_on_linux_raises(monkeypatch):
    monkeypatch.setattr(transport.platform, "system", lambda: "Linux")
    calls = []
    monkeypatch.setattr(transport.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(TransportError, match="only available on macOS"):
        send("things:///add?title=x", "open", "add")
    assert calls == []


def test_open_on_darwin_uses_list_argv(monkeypatch):
    monkeypatch.setattr(transport.platform, "system", lambda: "Darwin")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(transport.subprocess, "run", fake_run)
    url = "things:///update?id=A&completed=true&auth-token=SECRET"
    result = send(url, "open", "update")
    assert result == SendResult("open", True, "things:///update?id=A&completed=true&auth-token=***", 0, "")
    argv, kwargs = calls[0]
    assert argv == ["open", "-g", url]
    assert isinstance(argv, list) and "shell" not in kwargs
    assert kwargs["timeout"] == 15
    send("things:///show?id=A", "open", "show", foreground=True)
    assert calls[1][0] == ["open", "things:///show?id=A"]


def test_open_nonzero_raises(monkeypatch):
    monkeypatch.setattr(transport.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(transport.subprocess, "run",
                        lambda argv, **k: subprocess.CompletedProcess(argv, 1, stdout="", stderr="no handler\n"))
    with pytest.raises(TransportError, match="open exited 1: no handler"):
        send("things:///version", "open", "version")


def test_record_appends_masked_json_line(tmp_path):
    fixed = lambda: datetime(2026, 9, 9, 2, 0, 0, tzinfo=timezone.utc)
    url = "things:///update?id=A&title=%E4%B9%B0&auth-token=SECRET"
    result = send(url, "record", "update", now=fixed)
    assert result.sent is False and result.masked_url.endswith("auth-token=***")
    send("things:///add?title=x", "record", "add", now=fixed)
    lines = (tmp_path / ".things-skills" / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert list(first.keys()) == ["ts", "command", "url"]
    assert first == {"ts": "2026-09-09T02:00:00Z", "command": "update",
                     "url": "things:///update?id=A&title=%E4%B9%B0&auth-token=***"}
    assert "SECRET" not in lines[0]
    assert "%E4%B9%B0" in lines[0]  # ensure_ascii=False keeps the URL as-is (already ASCII here)


def test_record_timestamp_is_utc_z(tmp_path):
    send("things:///version", "record", "version")
    line = json.loads((tmp_path / ".things-skills" / "outbox.jsonl").read_text(encoding="utf-8"))
    assert line["ts"].endswith("Z") and len(line["ts"]) == 20
    datetime.strptime(line["ts"], "%Y-%m-%dT%H:%M:%SZ")


def test_dry_writes_nothing(tmp_path):
    result = send("things:///add?title=x&auth-token=S", "dry", "add")
    assert result == SendResult("dry", False, "things:///add?title=x&auth-token=***", None, "")
    assert not (tmp_path / ".things-skills").exists()


def test_unknown_transport_in_send():
    with pytest.raises(TransportError):
        send("things:///version", "carrier-pigeon", "version")
