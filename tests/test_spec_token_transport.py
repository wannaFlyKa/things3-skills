"""Token file, transport, rate limiter and verify tests written from SPEC.md C.3, C.4, C.5, C.6, C.7."""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

import pytest

from things_lib import read, token as token_mod, transport as transport_mod, url as url_mod, verify
from things_lib.token import TokenError, mask_url, read_token, resolve_token
from things_lib.transport import SendResult, TransportError, select_transport, send
from things_lib.url import RateLimiter, UrlError

NOT_FOUND = ("Things auth token not found: ~/.config/things-skills/auth-token is missing. "
             "Create it from Things → Settings → General → Enable Things URLs → Manage.")
EMPTY = "Things auth token file is empty: ~/.config/things-skills/auth-token"
PERM_WARNING = ("warning: ~/.config/things-skills/auth-token is readable by others; "
                "run: chmod 600 ~/.config/things-skills/auth-token")
FALLBACK_NOTE = ("note: using auth token from the Things database; "
                 "create ~/.config/things-skills/auth-token to silence this")
FIXTURE_TOKEN = "vKkylosuSuGwxrz7qcklOw"


def write_token(tmp_path, content, mode=0o600, name="auth-token"):
    directory = tmp_path / ".config" / "things-skills"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    path.chmod(mode)
    return path


# ---- C.3 token file ----------------------------------------------------------------------------------

def test_missing_file_exact_text(tmp_path):
    with pytest.raises(TokenError) as exc:
        read_token()
    assert str(exc.value) == NOT_FOUND
    assert "~" in str(exc.value) and str(tmp_path) not in str(exc.value)  # printed literally, not expanded


def test_missing_file_explicit_path_still_uses_literal_tilde_text(tmp_path):
    with pytest.raises(TokenError) as exc:
        read_token(str(tmp_path / "nope"))
    assert str(exc.value) == NOT_FOUND


@pytest.mark.parametrize("content", ["", "\n", "   \n\n", "\r\n", "\t \r\n \n"])
def test_empty_or_whitespace_only_file_exact_text(tmp_path, content):
    write_token(tmp_path, content)
    with pytest.raises(TokenError) as exc:
        read_token()
    assert str(exc.value) == EMPTY


@pytest.mark.parametrize("content,expected", [
    ("SECRET\n", "SECRET"), ("SECRET\r\n", "SECRET"), ("SECRET", "SECRET"), ("SECRET   \n\n", "SECRET"),
    ("SECRET\nsecond line\n", "SECRET"), ("SECRET\r\nJUNK\r\n", "SECRET"), ("SECRET\n\n\nJUNK", "SECRET"),
    ("vKkylosuSuGwxrz7qcklOw\n", "vKkylosuSuGwxrz7qcklOw"),
])
def test_trailing_whitespace_crlf_and_first_line_only(tmp_path, content, expected):
    write_token(tmp_path, content)
    assert read_token() == expected


def test_utf8_bom_is_not_part_of_the_token(tmp_path):
    """Stricter reading of 'read the file as UTF-8': a BOM written by an editor must not poison the token."""
    write_token(tmp_path, b"\xef\xbb\xbfSECRET\r\n")
    assert read_token() == "SECRET"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660, 0o666, 0o777, 0o601])
def test_group_or_world_readable_warns_once_per_process(tmp_path, mode):
    write_token(tmp_path, "SECRET\n", mode=mode)
    warnings = []
    assert read_token(warn=warnings.append) == "SECRET"
    assert warnings == [PERM_WARNING]
    assert read_token(warn=warnings.append) == "SECRET"
    assert read_token(warn=warnings.append) == "SECRET"
    assert warnings == [PERM_WARNING], "second and third reads must be silent"


@pytest.mark.parametrize("mode", [0o600, 0o400, 0o700])
def test_owner_only_modes_do_not_warn(tmp_path, mode):
    write_token(tmp_path, "SECRET\n", mode=mode)
    warnings = []
    assert read_token(warn=warnings.append) == "SECRET"
    assert read_token(warn=warnings.append) == "SECRET"
    assert warnings == []


def test_warning_goes_to_stderr_by_default_and_never_prints_the_token(tmp_path, capsys):
    write_token(tmp_path, "SECRET\n", mode=0o644)
    read_token()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == PERM_WARNING
    assert "SECRET" not in captured.err


def test_symlinked_token_file_is_followed(tmp_path):
    target = tmp_path / "real-token"
    target.write_text("SECRET\r\n", encoding="utf-8")
    target.chmod(0o600)
    directory = tmp_path / ".config" / "things-skills"
    directory.mkdir(parents=True)
    os.symlink(str(target), str(directory / "auth-token"))
    warnings = []
    assert read_token(warn=warnings.append) == "SECRET"
    assert warnings == []


def test_dangling_symlink_is_missing(tmp_path):
    directory = tmp_path / ".config" / "things-skills"
    directory.mkdir(parents=True)
    os.symlink(str(tmp_path / "gone"), str(directory / "auth-token"))
    with pytest.raises(TokenError) as exc:
        read_token()
    assert str(exc.value) == NOT_FOUND


def test_explicit_path_with_tilde_is_expanded(tmp_path):
    write_token(tmp_path, "SECRET\n", name="alt-token")
    assert read_token("~/.config/things-skills/alt-token") == "SECRET"


# ---- C.3 resolve_token fallback ----------------------------------------------------------------------

def test_resolve_token_prefers_the_file(tmp_path):
    write_token(tmp_path, "FILETOKEN\n")
    calls = []
    assert resolve_token(fallback=lambda: calls.append(1) or "DBTOKEN") == "FILETOKEN"
    assert calls == []


def test_resolve_token_uses_fallback_only_when_file_absent_and_prints_exact_note(tmp_path):
    warnings = []
    assert resolve_token(warn=warnings.append, fallback=lambda: "DBTOKEN") == "DBTOKEN"
    assert warnings == [FALLBACK_NOTE]


def test_resolve_token_empty_file_never_falls_back(tmp_path):
    write_token(tmp_path, "\n")
    calls = []
    with pytest.raises(TokenError) as exc:
        resolve_token(fallback=lambda: calls.append(1) or "DBTOKEN")
    assert str(exc.value) == EMPTY
    assert calls == []


@pytest.mark.parametrize("fallback", [lambda: None, lambda: "", lambda: (_ for _ in ()).throw(RuntimeError("db down"))])
def test_resolve_token_fallback_failure_raises_not_found(tmp_path, fallback):
    with pytest.raises(TokenError) as exc:
        resolve_token(fallback=fallback)
    assert str(exc.value) == NOT_FOUND


def test_resolve_token_without_fallback_raises_not_found(tmp_path):
    with pytest.raises(TokenError) as exc:
        resolve_token()
    assert str(exc.value) == NOT_FOUND


def test_resolve_token_against_fixture_database(tmp_path):
    warnings = []
    assert resolve_token(warn=warnings.append, fallback=read.token_from_database) == FIXTURE_TOKEN
    assert warnings == [FALLBACK_NOTE]
    assert read.token_from_database() == FIXTURE_TOKEN


# ---- C.5 select_transport --------------------------------------------------------------------------

def test_select_transport_precedence_explicit_over_env_over_platform(monkeypatch):
    monkeypatch.setenv("THINGS_SKILLS_TRANSPORT", "dry")
    assert select_transport("record") == "record"
    assert select_transport(None) == "dry"
    monkeypatch.delenv("THINGS_SKILLS_TRANSPORT")
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Linux")
    assert select_transport() == "record"
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Darwin")
    assert select_transport() == "open"
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Windows")
    assert select_transport() == "record"


@pytest.mark.parametrize("bad", ["bogus", "OPEN", "Record", "dry ", "open,record"])
def test_select_transport_invalid_values_raise(monkeypatch, bad):
    with pytest.raises(TransportError):
        select_transport(bad)
    monkeypatch.setenv("THINGS_SKILLS_TRANSPORT", bad)
    with pytest.raises(TransportError):
        select_transport()


def test_transports_constant():
    assert transport_mod.TRANSPORTS == ("open", "record", "dry")
    assert transport_mod.OUTBOX_PATH == ".things-skills/outbox.jsonl"


# ---- C.5 send: open ----------------------------------------------------------------------------------

def test_open_on_linux_raises_exact_text_and_never_spawns(monkeypatch, tmp_path):
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Linux")

    def boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called on Linux")
    monkeypatch.setattr(transport_mod.subprocess, "run", boom)
    with pytest.raises(TransportError) as exc:
        send("things:///add?title=x", "open", "add")
    assert str(exc.value) == "transport 'open' is only available on macOS"
    assert not (tmp_path / ".things-skills").exists()


class FakeCompleted:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def test_open_on_fake_darwin_uses_list_argv_with_dash_g_and_no_shell(monkeypatch):
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Darwin")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return FakeCompleted(0)
    monkeypatch.setattr(transport_mod.subprocess, "run", fake_run)
    url = "things:///update?id=X&completed=true&auth-token=SECRET"
    result = send(url, "open", "update")
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert isinstance(argv, list) and argv == ["open", "-g", url]
    assert not kwargs.get("shell"), "never shell=True"
    assert kwargs.get("timeout") == 15
    assert kwargs.get("capture_output") is True and kwargs.get("text") is True
    assert result == SendResult("open", True, mask_url(url), 0, "")
    assert result.masked_url.endswith("auth-token=***") and "SECRET" not in result.masked_url


def test_open_foreground_omits_dash_g(monkeypatch):
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Darwin")
    calls = []
    monkeypatch.setattr(transport_mod.subprocess, "run", lambda argv, **kw: calls.append(argv) or FakeCompleted(0))
    send("things:///show?id=X", "open", "show", foreground=True)
    assert calls == [["open", "things:///show?id=X"]]


def test_open_nonzero_exit_raises_with_rc_and_stderr(monkeypatch):
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(transport_mod.subprocess, "run", lambda argv, **kw: FakeCompleted(1, "  boom \n"))
    with pytest.raises(TransportError) as exc:
        send("things:///add?title=x", "open", "add")
    assert str(exc.value) == "open exited 1: boom"


def test_open_oserror_becomes_transport_error(monkeypatch):
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Darwin")

    def missing(argv, **kw):
        raise FileNotFoundError(2, "No such file or directory: 'open'")
    monkeypatch.setattr(transport_mod.subprocess, "run", missing)
    with pytest.raises(TransportError):
        send("things:///add?title=x", "open", "add")


# ---- C.5 send: record and dry ------------------------------------------------------------------------

UTC_NOW = datetime(2026, 9, 9, 2, 0, 0, tzinfo=timezone.utc)


def read_outbox(tmp_path):
    with open(tmp_path / ".things-skills" / "outbox.jsonl", encoding="utf-8") as handle:
        return handle.read()


def test_record_appends_one_line_with_key_order_and_z_timestamp(tmp_path):
    url = "things:///update?id=X&title=%E4%B9%B0&completed=true&auth-token=SECRET"
    result = send(url, "record", "update", now=lambda: UTC_NOW)
    assert result == SendResult("record", False, mask_url(url), None, "")
    raw = read_outbox(tmp_path)
    assert raw.endswith("\n") and raw.count("\n") == 1
    entry = json.loads(raw)
    assert list(entry.keys()) == ["ts", "command", "url"]
    assert entry == {"ts": "2026-09-09T02:00:00Z", "command": "update", "url": mask_url(url)}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", entry["ts"])
    assert "SECRET" not in raw
    assert raw.strip() == json.dumps(entry, ensure_ascii=False)


def test_record_converts_non_utc_timestamps_to_utc_z(tmp_path):
    plus8 = datetime(2026, 9, 9, 10, 30, 5, tzinfo=timezone(timedelta(hours=8)))
    send("things:///add?title=x", "record", "add", now=lambda: plus8)
    assert json.loads(read_outbox(tmp_path))["ts"] == "2026-09-09T02:30:05Z"


def test_record_default_clock_is_utc_now_with_z(tmp_path):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    send("things:///add?title=x", "record", "add")
    stamp = json.loads(read_outbox(tmp_path))["ts"]
    parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before - timedelta(seconds=1) <= parsed <= datetime.now(timezone.utc) + timedelta(seconds=1)


def test_record_appends_across_calls_and_lands_in_cwd(tmp_path, monkeypatch):
    send("things:///add?title=1", "record", "add")
    send("things:///add?title=2", "record", "add")
    assert read_outbox(tmp_path).count("\n") == 2
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    send("things:///add?title=3", "record", "add")
    assert (other / ".things-skills" / "outbox.jsonl").exists()
    assert read_outbox(tmp_path).count("\n") == 2


def test_dry_writes_nothing_anywhere(tmp_path):
    url = "things:///update?id=X&auth-token=SECRET"
    result = send(url, "dry", "update")
    assert result == SendResult("dry", False, "things:///update?id=X&auth-token=***", None, "")
    assert not (tmp_path / ".things-skills").exists()
    assert list(tmp_path.iterdir()) == []


def test_send_unknown_transport_raises():
    with pytest.raises(TransportError):
        send("things:///add?title=x", "bogus", "add")


# ---- C.4 / C.7 RateLimiter ---------------------------------------------------------------------------

def test_250_pass_instantly_and_251st_sleeps_the_full_window(fake_clock, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("real time.sleep called"))
    limiter = RateLimiter(clock=fake_clock, sleep=fake_clock.sleep)
    assert [limiter.acquire() for _ in range(250)] == [0.0] * 250
    assert fake_clock.slept == []
    assert limiter.acquire() == 10.0
    assert fake_clock.slept == [10.0]
    assert fake_clock.t == 10.0


def test_weights(fake_clock):
    limiter = RateLimiter(clock=fake_clock, sleep=fake_clock.sleep)
    assert limiter.acquire(200) == 0.0
    assert limiter.acquire(50) == 0.0
    assert limiter.acquire(1) == 10.0
    assert fake_clock.slept == [10.0]


def test_partial_eviction_sleeps_only_until_the_oldest_entry_leaves(fake_clock):
    limiter = RateLimiter(clock=fake_clock, sleep=fake_clock.sleep)
    limiter.acquire(100)          # t=0
    fake_clock.advance(5.0)
    limiter.acquire(150)          # t=5, total 250
    fake_clock.advance(1.0)       # t=6
    assert limiter.acquire(1) == pytest.approx(4.0)   # 0 + 10 - 6
    assert fake_clock.slept == [pytest.approx(4.0)]
    assert limiter.acquire(99) == 0.0                  # 150 + 1 + 99 = 250 fits


def test_window_eviction_at_exactly_the_boundary(fake_clock):
    limiter = RateLimiter(clock=fake_clock, sleep=fake_clock.sleep)
    for _ in range(250):
        limiter.acquire()
    fake_clock.advance(10.0)
    assert limiter.acquire() == 0.0
    assert fake_clock.slept == []


def test_batch_over_limit_raises_exact_text(fake_clock):
    limiter = RateLimiter(clock=fake_clock, sleep=fake_clock.sleep)
    with pytest.raises(UrlError) as exc:
        limiter.acquire(251)
    assert str(exc.value) == "batch of 251 items exceeds 250 per 10 s; split it"
    assert limiter.acquire(250) == 0.0
    assert fake_clock.slept == []


def test_custom_limit_and_window(fake_clock):
    limiter = RateLimiter(limit=3, window=2.0, clock=fake_clock, sleep=fake_clock.sleep)
    assert [limiter.acquire() for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limiter.acquire() == 2.0
    with pytest.raises(UrlError):
        limiter.acquire(4)


def test_multiple_sleeps_when_two_batches_expire_at_different_times(fake_clock):
    limiter = RateLimiter(clock=fake_clock, sleep=fake_clock.sleep)
    limiter.acquire(125)          # t=0
    fake_clock.advance(3.0)
    limiter.acquire(125)          # t=3
    slept = limiter.acquire(200)  # needs both to leave: 0->10 frees 125 (not enough), then 3->13
    assert slept == pytest.approx(10.0)
    assert fake_clock.t == pytest.approx(13.0)


# ---- C.6 verify ---------------------------------------------------------------------------------------

SINCE = datetime(2026, 9, 9, 10, 0, 0)


def fake_item(uuid, title, created, status="incomplete"):
    return {"uuid": uuid, "type": "to-do", "title": title, "status": status, "created": created,
            "modified": created, "notes": "", "start": "Anytime", "start_date": None, "deadline": None,
            "stop_date": None, "index": 0, "today_index": 0}


@pytest.mark.parametrize("transport", ["record", "dry"])
def test_verify_short_circuits_on_non_open_transports_without_reading(transport, monkeypatch):
    monkeypatch.setattr(verify, "sleep", lambda s: pytest.fail("must not sleep"), raising=False)
    reader = lambda: pytest.fail("reader must not be called")
    result = verify.verify_created(["x"], SINCE, transport=transport, reader=reader, sleep=lambda s: None)
    assert result == verify.VerifyResult(False, "transport %s: nothing was sent to Things" % transport, [], [], [])
    result = verify.verify_updated(["X"], lambda item: True, transport=transport, reader=reader, sleep=lambda s: None)
    assert result == verify.VerifyResult(False, "transport %s: nothing was sent to Things" % transport, [], [], [])


def test_verify_reports_database_unavailable(monkeypatch):
    monkeypatch.setattr(read, "database_status", lambda: "unavailable")
    result = verify.verify_created(["x"], SINCE, transport="open", sleep=lambda s: None)
    assert result == verify.VerifyResult(False, "database unavailable", [], [], [])
    result = verify.verify_updated(["X"], lambda item: True, transport="open", sleep=lambda s: None)
    assert result == verify.VerifyResult(False, "database unavailable", [], [], [])


def test_verify_created_matches_title_and_recent_created_most_recent_wins(monkeypatch, fake_clock):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    items = [fake_item("OLD", "买牛奶", "2026-09-09 09:00:00"),
             fake_item("A1", "买牛奶", "2026-09-09 10:00:01"),
             fake_item("A2", "买牛奶", "2026-09-09 10:00:05"),
             fake_item("B", "Call mom", "2026-09-09 09:59:55"),     # within the 10 s slack before `since`
             fake_item("C", "Unrelated", "2026-09-09 10:00:02")]
    slept = []
    result = verify.verify_created(["买牛奶", "Call mom"], SINCE, timeout=3.0, transport="open", poll=0.5,
                                   sleep=lambda s: slept.append(s) or fake_clock.advance(s), clock=fake_clock, reader=lambda: items)
    assert result.verified is True and result.reason is None
    assert result.ids == ["A2", "B"]
    assert result.links == ["things:///show?id=A2", "things:///show?id=B"]
    assert [i["uuid"] for i in result.items] == ["A2", "B"]
    assert slept[0] == 0.5, "poll delay comes first"


def test_verify_created_times_out_with_exact_reason_and_partial_findings(monkeypatch, fake_clock):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    items = [fake_item("A", "买牛奶", "2026-09-09 10:00:01"), fake_item("OLD", "Call mom", "2026-09-09 09:00:00")]
    calls = []
    result = verify.verify_created(["买牛奶", "Call mom"], SINCE, timeout=2.0, transport="open", poll=0.5,
                                   sleep=lambda s: fake_clock.advance(s), clock=fake_clock, reader=lambda: calls.append(1) or items)
    assert result.verified is False
    assert result.reason == "timeout after 2.0s"
    assert result.ids == ["A"] and result.links == ["things:///show?id=A"]
    assert len(calls) >= 3, "polls every 0.5 s until the timeout"
    assert time.monotonic  # untouched: only the injected clock advanced


def test_verify_created_ignores_items_created_before_the_window(monkeypatch, fake_clock):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    items = [fake_item("OLD", "x", "2026-09-09 09:59:49")]   # 11 s before since: outside the 10 s slack
    result = verify.verify_created(["x"], SINCE, timeout=1.0, transport="open", sleep=lambda s: fake_clock.advance(s),
                                   clock=fake_clock, reader=lambda: items)
    assert result.verified is False and result.ids == []


def test_verify_updated_predicate_and_timeout(monkeypatch, fake_clock):
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    store = {"X": fake_item("X", "t", "2026-09-09 10:00:00", status="completed"),
             "Y": fake_item("Y", "u", "2026-09-09 10:00:00", status="incomplete")}
    monkeypatch.setattr(read, "get", lambda item_id: store.get(item_id))
    ok = verify.verify_updated(["X"], lambda item: item["status"] == "completed", timeout=1.0, transport="open",
                               sleep=lambda s: fake_clock.advance(s), clock=fake_clock)
    assert ok.verified is True and ok.ids == ["X"] and ok.links == ["things:///show?id=X"] and ok.reason is None
    fake_clock.t = 0.0
    bad = verify.verify_updated(["X", "Y"], lambda item: item["status"] == "completed", timeout=1.5, transport="open",
                                sleep=lambda s: fake_clock.advance(s), clock=fake_clock)
    assert bad.verified is False and bad.reason == "timeout after 1.5s"


def test_verify_result_shape():
    result = verify.VerifyResult(False, "x", [], [], [])
    assert result._fields == ("verified", "reason", "ids", "links", "items")


# ---- C.3 / C.5 / C.7 as seen through the CLI, in-process with a fake Darwin --------------------------

import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402

from conftest import CLI_PATH  # noqa: E402

TODO_INBOX = "DfYoiXcNLQssk9DkSoJV3Y"
TODO_ANYTIME = "QqhVksfbsAVaNnwB1x3CuD"
NOW = ["--now", "2026-09-09T10:00"]


def run_main(capsys, argv):
    loader = importlib.machinery.SourceFileLoader("things_cli_tt", CLI_PATH)
    spec = importlib.util.spec_from_loader("things_cli_tt", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    code = module.main(argv)
    out = capsys.readouterr()
    assert out.out.count("\n") == 1
    return code, json.loads(out.out), out.err


def fake_darwin(monkeypatch, returncode=0, stderr=""):
    monkeypatch.setattr(transport_mod.platform, "system", lambda: "Darwin")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return FakeCompleted(returncode, stderr)
    monkeypatch.setattr(transport_mod.subprocess, "run", fake_run)
    return calls


def test_cli_open_sends_list_argv_token_only_inside_the_url_and_times_out_with_exit_2(monkeypatch, capsys, tmp_path):
    write_token(tmp_path, "SECRET\n")
    calls = fake_darwin(monkeypatch)
    monkeypatch.setattr(read, "database_status", lambda: "readable")   # fixture never flips to completed -> timeout
    code, payload, err = run_main(capsys, NOW + ["--transport", "open", "--verify-timeout", "0.6", "complete", TODO_INBOX])
    url = "things:///update?id=%s&completed=true&auth-token=SECRET" % TODO_INBOX
    assert calls and calls[0][0] == ["open", "-g", url]
    assert isinstance(calls[0][0], list) and not calls[0][1].get("shell")
    assert code == 2, (payload, err)
    assert payload["sent"] is True and payload["verified"] is False
    assert payload["verify_reason"].startswith("timeout after 0.6")
    assert payload["urls"] == [mask_url(url)]
    assert "SECRET" not in json.dumps(payload) and "SECRET" not in err
    assert not (tmp_path / ".things-skills").exists(), "open transport writes no outbox"


def test_cli_open_success_path_verified_true_exit_0(monkeypatch, capsys, tmp_path):
    write_token(tmp_path, "SECRET\n")
    fake_darwin(monkeypatch)
    monkeypatch.setattr(read, "database_status", lambda: "readable")
    monkeypatch.setattr(read, "get", lambda item_id, *a, **k: {"uuid": item_id, "title": "x", "status": "completed", "type": "to-do"})
    code, payload, err = run_main(capsys, NOW + ["--transport", "open", "--verify-timeout", "1", "complete", TODO_INBOX])
    assert code == 0 and payload["ok"] is True and payload["sent"] is True and payload["verified"] is True
    assert payload["verify_reason"] is None
    assert payload["ids"] == [TODO_INBOX] and payload["links"] == ["things:///show?id=" + TODO_INBOX]


def test_cli_ping_and_show_on_fake_darwin(monkeypatch, capsys):
    calls = fake_darwin(monkeypatch)
    code, payload, _ = run_main(capsys, NOW + ["--transport", "open", "ping"])
    assert code == 0 and payload["sent"] is True and payload["urls"] == ["things:///version"]
    assert calls[-1][0] == ["open", "-g", "things:///version"]
    code, payload, _ = run_main(capsys, NOW + ["--transport", "open", "show", TODO_INBOX])
    assert code == 0 and payload["sent"] is True and payload["verified"] is None
    assert calls[-1][0] == ["open", "things:///show?id=" + TODO_INBOX], "show is foreground: no -g"


def test_cli_open_nonzero_is_exit_2_with_open_error(monkeypatch, capsys, tmp_path):
    write_token(tmp_path, "SECRET\n")
    fake_darwin(monkeypatch, returncode=1, stderr="LSOpenURLsWithRole() failed\n")
    code, payload, err = run_main(capsys, NOW + ["--transport", "open", "ping"])
    assert code == 2 and payload["ok"] is False and payload["error"] == "open exited 1: LSOpenURLsWithRole() failed"
    assert payload["sent"] is False
    code, payload, err = run_main(capsys, NOW + ["--transport", "open", "complete", TODO_INBOX])
    assert code == 2 and payload["error"].startswith("open exited 1") and "SECRET" not in json.dumps(payload) + err


def test_cli_default_transport_on_fake_darwin_is_open(monkeypatch, capsys):
    monkeypatch.delenv("THINGS_SKILLS_TRANSPORT")
    fake_darwin(monkeypatch)
    code, payload, _ = run_main(capsys, NOW + ["doctor"])
    assert code == 0 and payload["data"]["transport"] == "open" and payload["data"]["platform"] == "Darwin"


def test_cli_acquires_rate_limiter_per_url_for_record_but_not_for_dry(monkeypatch, capsys, tmp_path):
    write_token(tmp_path, "SECRET\n")
    acquired = []
    original = RateLimiter.acquire

    def spy(self, items=1):
        acquired.append(items)
        return original(self, items)
    monkeypatch.setattr(RateLimiter, "acquire", spy)
    code, payload, _ = run_main(capsys, NOW + ["complete", TODO_INBOX, TODO_ANYTIME])
    assert code == 0 and acquired == [1, 1], "one acquire per URL, weight 1 each"
    acquired.clear()
    run_main(capsys, NOW + ["add-project", "P", "--todo", "a", "--todo", "b"])
    assert acquired == [3], "add-project weighs 1 + number of to-dos"
    acquired.clear()
    payload_file = tmp_path / "p.json"
    payload_file.write_text(json.dumps([{"type": "project", "attributes": {"title": "p", "items": [
        {"type": "heading", "attributes": {"title": "h"}}, {"type": "to-do", "attributes": {"title": "t", "checklist-items": [
            {"type": "checklist-item", "attributes": {"title": "c"}}]}}]}}]), encoding="utf-8")
    run_main(capsys, NOW + ["add-json", str(payload_file)])
    assert acquired == [3], "json weighs project + heading + to-do, not checklist items"
    acquired.clear()
    run_main(capsys, NOW + ["--dry-run", "complete", TODO_INBOX])
    run_main(capsys, NOW + ["--dry-run", "add", "x"])
    assert acquired == [], "dry-run never touches the limiter"
    acquired.clear()
    run_main(capsys, NOW + ["inbox"])
    assert acquired == [], "reads never touch the limiter"
