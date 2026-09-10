"""Auth token file handling (SPEC section C.3). The token value is never printed or logged."""

import os
import re
import sys
from typing import Callable, Optional, Set

TOKEN_PATH = "~/.config/things-skills/auth-token"

NOT_FOUND_TEXT = (
    "Things auth token not found: ~/.config/things-skills/auth-token is missing. "
    "Create it from Things → Settings → General → Enable Things URLs → Manage."
)
EMPTY_TEXT = "Things auth token file is empty: ~/.config/things-skills/auth-token"
PERMISSION_WARNING = (
    "warning: ~/.config/things-skills/auth-token is readable by others; "
    "run: chmod 600 ~/.config/things-skills/auth-token"
)
FALLBACK_NOTE = (
    "note: using auth token from the Things database; "
    "create ~/.config/things-skills/auth-token to silence this"
)

_MASK_RE = re.compile(r"(auth-token=)[^&]*")
_warned_paths: Set[str] = set()


class TokenError(Exception):
    """Token file missing or empty (CLI exit 1)."""


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


def token_path() -> str:
    return os.path.expanduser(TOKEN_PATH)


def reset_warnings() -> None:
    """Forget which files have been warned about (tests only)."""
    _warned_paths.clear()


def read_token(path: Optional[str] = None, warn: Callable[[str], None] = _stderr) -> str:
    """Return the first non-blank line of the token file, stripped (a UTF-8 BOM is ignored).

    Raises TokenError when the file is missing or contains no non-blank line.
    """
    resolved = os.path.expanduser(path) if path else token_path()
    if not os.path.isfile(resolved):
        raise TokenError(NOT_FOUND_TEXT)
    mode = os.stat(resolved).st_mode
    if mode & 0o077 and resolved not in _warned_paths:
        _warned_paths.add(resolved)
        warn(PERMISSION_WARNING)
    with open(resolved, encoding="utf-8-sig") as handle:
        content = handle.read()
    for line in content.splitlines():
        value = line.strip()
        if value:
            return value
    raise TokenError(EMPTY_TEXT)


def mask_url(url: str) -> str:
    """Replace the auth-token value with *** (idempotent, touches nothing else)."""
    return _MASK_RE.sub(r"\1***", url)


def resolve_token(
    path: Optional[str] = None,
    warn: Callable[[str], None] = _stderr,
    fallback: Optional[Callable[[], Optional[str]]] = None,
) -> str:
    """Token file first; when the file is absent, try `fallback` (the Things database)."""
    try:
        return read_token(path, warn)
    except TokenError as exc:
        if str(exc) != NOT_FOUND_TEXT or fallback is None:
            raise
        try:
            value = fallback()
        except Exception:  # the fallback must never break token resolution
            value = None
        if value:
            warn(FALLBACK_NOTE)
            return value
        raise
