"""Token file handling (SPEC section C.3)."""

import os

import pytest

from things_lib import read, token
from things_lib.token import TokenError, mask_url, read_token, resolve_token

NOT_FOUND = ("Things auth token not found: ~/.config/things-skills/auth-token is missing. "
             "Create it from Things → Settings → General → Enable Things URLs → Manage.")
EMPTY = "Things auth token file is empty: ~/.config/things-skills/auth-token"
PERM = ("warning: ~/.config/things-skills/auth-token is readable by others; "
        "run: chmod 600 ~/.config/things-skills/auth-token")


def test_missing_file_exact_text(tmp_path):
    with pytest.raises(TokenError) as info:
        read_token()
    assert str(info.value) == NOT_FOUND
    assert token.token_path() == str(tmp_path / ".config" / "things-skills" / "auth-token")


def test_empty_file_exact_text(token_file):
    with open(token_file, "w", encoding="utf-8") as handle:
        handle.write("  \n\n")
    with pytest.raises(TokenError) as info:
        read_token()
    assert str(info.value) == EMPTY


def test_trailing_whitespace_and_extra_lines_stripped(token_file):
    with open(token_file, "w", encoding="utf-8") as handle:
        handle.write("SECRET  \t\nsecond line\n")
    assert read_token() == "SECRET"


def test_wide_permissions_warn_once(token_file):
    os.chmod(token_file, 0o644)
    warnings = []
    assert read_token(warn=warnings.append) == "SECRET"
    assert read_token(warn=warnings.append) == "SECRET"
    assert warnings == [PERM]


def test_strict_permissions_no_warning(token_file):
    warnings = []
    assert read_token(warn=warnings.append) == "SECRET"
    assert warnings == []


def test_token_never_leaks_into_outputs(token_file, run_cli, tmp_path):
    code, payload, stderr = run_cli("--transport", "record", "complete", "ABC123", env={"THINGSDB": "/nonexistent.sqlite"})
    assert code == 0, stderr
    blob = repr(payload) + stderr
    assert "SECRET" not in blob
    assert payload["urls"] == ["things:///update?id=ABC123&completed=true&auth-token=***"]
    outbox = (tmp_path / ".things-skills" / "outbox.jsonl").read_text(encoding="utf-8")
    assert "SECRET" not in outbox and "auth-token=***" in outbox


def test_mask_url():
    assert mask_url("things:///update?id=A&auth-token=abc") == "things:///update?id=A&auth-token=***"
    assert mask_url("things:///add?title=x") == "things:///add?title=x"


def test_fallback_to_database_only_when_file_absent(capsys):
    assert read.database_status() == "fixture"
    notes = []
    value = resolve_token(warn=notes.append, fallback=read.token_from_database)
    assert value == "vKkylosuSuGwxrz7qcklOw"
    assert notes == ["note: using auth token from the Things database; create ~/.config/things-skills/auth-token to silence this"]


def test_fallback_not_used_for_empty_file(token_file):
    with open(token_file, "w", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(TokenError) as info:
        resolve_token(warn=lambda _m: None, fallback=read.token_from_database)
    assert str(info.value) == EMPTY


def test_fallback_not_used_when_database_unavailable(monkeypatch):
    monkeypatch.setenv("THINGSDB", "/nonexistent/main.sqlite")
    with pytest.raises(TokenError) as info:
        resolve_token(warn=lambda _m: None, fallback=read.token_from_database)
    assert str(info.value) == NOT_FOUND


def test_file_wins_over_fallback(token_file):
    assert resolve_token(warn=lambda _m: None, fallback=lambda: "FROMDB") == "SECRET"
