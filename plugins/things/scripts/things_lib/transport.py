"""The single write path: every Things URL leaves through `send` (SPEC section C.5)."""

import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from typing import Callable, NamedTuple, Optional

from .token import mask_url

TRANSPORTS = ("open", "record", "dry")
OUTBOX_DIR = ".things-skills"
OUTBOX_PATH = ".things-skills/outbox.jsonl"
ENV_VAR = "THINGS_SKILLS_TRANSPORT"
OPEN_TIMEOUT = 15


class TransportError(Exception):
    """`open` unavailable or non-zero, or an unknown transport name (CLI exit 2)."""


class SendResult(NamedTuple):
    transport: str
    sent: bool
    masked_url: str
    returncode: Optional[int]
    stderr: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def select_transport(explicit: Optional[str] = None) -> str:
    """--transport flag > $THINGS_SKILLS_TRANSPORT > open on macOS, record elsewhere."""
    choice = explicit or os.environ.get(ENV_VAR) or None
    if choice is None:
        choice = "open" if platform.system() == "Darwin" else "record"
    if choice not in TRANSPORTS:
        raise TransportError(f"unknown transport '{choice}'; expected one of {', '.join(TRANSPORTS)}")
    return choice


def send(url: str, transport: str, command: str, foreground: bool = False,
         now: Callable[[], datetime] = _utcnow) -> SendResult:
    """Deliver one URL. Only `open` on macOS actually reaches Things."""
    masked = mask_url(url)
    if transport == "open":
        if platform.system() != "Darwin":
            raise TransportError("transport 'open' is only available on macOS")
        argv = ["open", url] if foreground else ["open", "-g", url]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=OPEN_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            # str(TimeoutExpired) repeats argv, so the token must be masked here too.
            raise TransportError(mask_url(f"open failed: {exc}"))
        stderr = mask_url(proc.stderr or "")
        if proc.returncode != 0:
            # macOS echoes the failing URL in `open`'s stderr; never let the token through.
            raise TransportError(f"open exited {proc.returncode}: {stderr.strip()}")
        return SendResult("open", True, masked, proc.returncode, stderr)
    if transport == "record":
        os.makedirs(OUTBOX_DIR, exist_ok=True)
        stamp = now().astimezone(timezone.utc)   # a naive datetime is taken as local time
        line = json.dumps(
            {"ts": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "command": command, "url": masked},
            ensure_ascii=False,
        )
        with open(OUTBOX_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return SendResult("record", False, masked, None, "")
    if transport == "dry":
        return SendResult("dry", False, masked, None, "")
    raise TransportError(f"unknown transport '{transport}'; expected one of {', '.join(TRANSPORTS)}")
