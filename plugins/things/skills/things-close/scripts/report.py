#!/usr/bin/env python3
"""report.py: turn a `things complete` / `things cancel` envelope into the user-facing result.

Reads the CLI envelope (JSON) from stdin or --file, re-reads every id in data.done
through the shared CLI `get` (titles plus the status Things shows now), explains
every entry in data.skipped (repeating to-dos the URL scheme cannot touch), quotes
`verified` / `verify_reason` plainly and lists every warning. Prints JSON (default)
or Markdown (--markdown) in English or Chinese (--lang). It never writes anything.
"""
import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts"))
CLI = os.path.join(SCRIPTS, "things")
sys.path.insert(0, SCRIPTS)
from things_lib import config as config_mod  # noqa: E402

EXPECTED = {"complete": "completed", "cancel": "canceled"}
LABELS = {
    "en": {
        "completed": "Completed", "canceled": "Canceled", "changed": "Changed",
        "preview_completed": "Would complete", "preview_canceled": "Would cancel", "preview_changed": "Would change",
        "status": "status now: %s", "pending": "status now: %s (Things has not applied it yet; check the link)",
        "unknown": "status unknown (could not re-read)",
        "skipped": "Skipped: repeating to-dos",
        "why": "The Things URL scheme cannot complete or cancel a repeating to-do; do it in Things.",
        "nothing": "Nothing was written: %s", "dry": "Dry run: nothing was sent to Things.",
        "would_urls": "URLs that would be sent (token masked)",
        "verified": "Verified in Things.", "unverified": "Not verified: %s", "warnings": "Warnings",
    },
    "zh": {
        "completed": "已完成", "canceled": "已取消", "changed": "已修改",
        "preview_completed": "预演：将完成", "preview_canceled": "预演：将取消", "preview_changed": "预演：将修改",
        "status": "当前状态：%s", "pending": "当前状态：%s（Things 尚未应用，请点开链接确认）",
        "unknown": "状态未知（无法重新读取）",
        "skipped": "已跳过：重复任务",
        "why": "Things 的 URL scheme 无法完成或取消重复任务，请在 Things 里手动处理。",
        "nothing": "没有写入任何内容：%s", "dry": "预演（dry run）：没有向 Things 发送任何内容。",
        "would_urls": "将发送的 URL（token 已隐藏）",
        "verified": "已在 Things 中核实。", "unverified": "未核实：%s", "warnings": "警告",
    },
}
STATUS_ZH = {"completed": "已完成", "canceled": "已取消", "incomplete": "未完成"}
CLI_TIMEOUT = 90


def run_get(args: argparse.Namespace, item_id: str) -> Optional[Dict[str, Any]]:
    cmd = [sys.executable, CLI]
    if args.now:
        cmd += ["--now", args.now]
    if args.config:
        cmd += ["--config", args.config]
    cmd += ["get", item_id]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT)
        envelope = json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        sys.stderr.write("warning: the things CLI did not answer in %d s (get %s)\n" % (CLI_TIMEOUT, item_id))
        return None
    except (OSError, ValueError):
        return None
    if not envelope.get("ok") or not isinstance(envelope.get("data"), dict):
        return None
    return envelope["data"]


def build(args: argparse.Namespace, env: Dict[str, Any]) -> Dict[str, Any]:
    command = env.get("command") or ""
    expected = EXPECTED.get(command)
    data = env.get("data") if isinstance(env.get("data"), dict) else {}
    done: List[Dict[str, Any]] = []
    for item_id in data.get("done") or []:
        item = None if args.no_reread else run_get(args, item_id)
        status = item.get("status") if item else None
        done.append({
            "id": item_id,
            "title": (item or {}).get("title") or item_id,
            "type": (item or {}).get("type"),
            "status": status,
            "confirmed": bool(expected and status == expected),
            "link": "things:///show?id=%s" % item_id,
        })
    skipped = [{"id": s.get("id"), "title": s.get("title") or s.get("id"), "reason": s.get("reason"),
                "link": "things:///show?id=%s" % s.get("id")} for s in data.get("skipped") or []]
    return {
        "ok": bool(env.get("ok")), "command": command, "action": expected or "update",
        "sent": bool(env.get("sent")), "verified": env.get("verified"), "verify_reason": env.get("verify_reason"),
        "done": done, "skipped": skipped, "links": env.get("links") or [], "urls": list(env.get("urls") or []),
        "warnings": list(env.get("warnings") or []), "error": env.get("error"),
    }


def render_markdown(result: Dict[str, Any], lang: str) -> str:
    text = LABELS[lang]
    lines: List[str] = []
    # --dry-run / dry transport: ok, nothing sent, verified null (SPEC E.1). Say so FIRST and use
    # "would" headings; the re-read status of an untouched item is noise here.
    dry = bool(result["ok"] and not result["sent"] and result["verified"] is None)
    if not result["ok"]:
        lines.append(text["nothing"] % (result["error"] or "?"))
    if dry:
        lines.append(text["dry"])
    if result["done"]:
        key = result["action"] if result["action"] in ("completed", "canceled") else "changed"
        if dry:
            key = "preview_" + key
        lines.append("**%s** (%d)" % (text[key], len(result["done"])))
        for d in result["done"]:
            if dry:
                lines.append("- %s — %s" % (d["title"], d["link"]))
                continue
            status = d["status"]
            shown = STATUS_ZH.get(status, status) if lang == "zh" else status
            if status is None:
                note = text["unknown"]
            elif d["confirmed"] or not result["sent"]:
                note = text["status"] % shown
            else:
                note = text["pending"] % shown
            lines.append("- %s — %s — %s" % (d["title"], note, d["link"]))
    if result["skipped"]:
        lines.append("**%s** (%d)" % (text["skipped"], len(result["skipped"])))
        for s in result["skipped"]:
            lines.append("- %s — %s" % (s["title"], s["link"]))
        lines.append("  " + text["why"])
    if dry and result["urls"]:
        lines.append("**%s**" % text["would_urls"])
        lines.extend("- " + u for u in result["urls"])
    if result["ok"] or result["done"]:
        if result["verified"] is True:
            lines.append(text["verified"])
        elif result["verified"] is False:
            lines.append(text["unverified"] % (result["verify_reason"] or "?"))
    # The CLI repeats every data.skipped entry as a `skipped <id>: ...` warning; the Skipped block above
    # already says it, so those lines are not printed twice.
    skipped_ids = [s["id"] for s in result["skipped"] if s.get("id")]
    warnings = [w for w in result["warnings"] if not any(w.startswith("skipped %s:" % i) for i in skipped_ids)]
    if warnings:
        lines.append("**%s**" % text["warnings"])
        lines.extend("- " + w for w in warnings)
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Format a things complete/cancel envelope for the user.")
    parser.add_argument("--file", help="envelope JSON file; default stdin")
    parser.add_argument("--envelope", help="envelope JSON given inline instead of stdin")
    parser.add_argument("--markdown", action="store_true", help="print Markdown instead of JSON")
    parser.add_argument("--lang", choices=["auto", "zh", "en"], default="auto")
    parser.add_argument("--no-reread", action="store_true", help="do not re-read done ids with `things get`")
    parser.add_argument("--now", help="freeze now, YYYY-MM-DDTHH:MM (forwarded to the CLI)")
    parser.add_argument("--config", help="config file (forwarded to the CLI)")
    args = parser.parse_args(argv)
    try:
        cfg = config_mod.load_config(args.config)
    except config_mod.ConfigError:
        cfg = {}
    lang = args.lang if args.lang in ("zh", "en") else (cfg.get("language") if cfg.get("language") in ("zh", "en") else "en")
    try:
        if args.envelope:
            raw = args.envelope
        elif args.file:
            raw = open(args.file, encoding="utf-8").read()
        else:
            raw = sys.stdin.read()
        if not raw.strip():
            raise ValueError("empty input")
        env = json.loads(raw.strip().splitlines()[-1])  # the envelope is always the last stdout line
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": "no envelope to report: %s" % exc}, ensure_ascii=False))
        return 1
    if not isinstance(env, dict):
        print(json.dumps({"ok": False, "error": "envelope must be a JSON object"}, ensure_ascii=False))
        return 1
    result = build(args, env)
    if args.markdown:
        sys.stdout.write(render_markdown(result, lang))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
