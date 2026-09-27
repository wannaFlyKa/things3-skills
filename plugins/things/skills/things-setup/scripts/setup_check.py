#!/usr/bin/env python3
"""things-setup helper: run `things doctor` / `things ping` / `things tags` / `things areas`
through the shared CLI, create the config file from config.example.json when it is missing
(step 6), and print the seven-row ✅/❌ status table as JSON (default) or Markdown (--markdown).

Never sends a Things write, never reads or prints the auth token value.
Python 3.9, standard library only. Honours THINGSDB / THINGS_SKILLS_CONFIG / THINGS_SKILLS_TRANSPORT.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.abspath(os.path.join(SKILL_DIR, "..", ".."))
REPO_ROOT = os.path.abspath(os.path.join(PLUGIN_DIR, "..", ".."))
SCRIPTS_DIR = os.path.join(PLUGIN_DIR, "scripts")
CLI = os.path.join(SCRIPTS_DIR, "things")
EXAMPLE_CONFIG = os.path.join(PLUGIN_DIR, "config.example.json")
TOKEN_PATH = "~/.config/things-skills/auth-token"
OK, BAD = "✅", "❌"

sys.path.insert(0, SCRIPTS_DIR)
from things_lib import config as config_mod  # noqa: E402
from things_lib.dates import detect_language  # noqa: E402

STEP_IDS = ("macos", "things", "things_py", "database", "token", "config", "tags")

TEXT = {
    "en": {
        "title": "Things setup status",
        "columns": ("Check", "Status", "Detail"),
        "labels": {
            "macos": "macOS",
            "things": "Things installed and opened once",
            "things_py": "things.py importable",
            "database": "Things database readable",
            "token": "Auth token file",
            "config": "Config file",
            "tags": "Config tags exist in Things",
        },
        "next": "Next steps",
        "notes": "Notes",
        "all_ok": "All seven checks passed. The Things skills are ready.",
        "some_bad": "{n} check(s) failed. Fix them in order, then run $things-setup in Codex or /things:things-setup in Claude Code again.",
    },
    "zh": {
        "title": "Things 配置状态",
        "columns": ("检查项", "状态", "说明"),
        "labels": {
            "macos": "macOS",
            "things": "已安装 Things 并打开过一次",
            "things_py": "things.py 可导入",
            "database": "Things 数据库可读",
            "token": "授权令牌文件",
            "config": "配置文件",
            "tags": "配置中的标签在 Things 里存在",
        },
        "next": "下一步",
        "notes": "备注",
        "all_ok": "七项检查全部通过，Things 技能已就绪。",
        "some_bad": "有 {n} 项未通过。请按顺序处理，然后在 Codex 中运行 $things-setup，或在 Claude Code 中运行 /things:things-setup。",
    },
}


def run_cli(*args, now=None):
    """Run the shared CLI; return (envelope dict, exit code). Never raises."""
    argv = [sys.executable, CLI]
    if now:
        argv += ["--now", now]
    argv += list(args)
    fallback = {"ok": False, "data": None, "sent": False, "warnings": [], "error": None}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.SubprocessError) as exc:
        fallback["error"] = "could not run the things CLI: {}".format(exc)
        return fallback, 1
    try:
        envelope = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        envelope = None
    if not isinstance(envelope, dict):
        fallback["error"] = (proc.stderr or "").strip() or "no JSON envelope from the things CLI"
        return fallback, proc.returncode or 1
    return envelope, proc.returncode


TERM_PROGRAMS = {
    "apple_terminal": "Terminal", "iterm.app": "iTerm2", "iterm2": "iTerm2", "vscode": "Visual Studio Code",
    "warpterminal": "Warp", "ghostty": "Ghostty", "wezterm": "WezTerm", "hyper": "Hyper",
    "alacritty": "Alacritty", "kitty": "kitty", "rio": "Rio", "tabby": "Tabby",
}
PROCESS_NAMES = {
    "terminal": "Terminal", "iterm2": "iTerm2", "code": "Visual Studio Code", "code helper": "Visual Studio Code",
    "cursor": "Cursor", "electron": None, "stable": "Warp", "warp": "Warp", "ghostty": "Ghostty",
    "wezterm-gui": "WezTerm", "alacritty": "Alacritty", "kitty": "kitty", "hyper": "Hyper",
}


def terminal_app():
    """Best-effort name of the terminal app that must get Full Disk Access; None when unknown."""
    program = os.environ.get("TERM_PROGRAM", "").strip()
    if program and program.casefold() != "tmux":
        return TERM_PROGRAMS.get(program.casefold(), program)
    pid = os.getppid()
    for _ in range(15):
        if pid <= 1:
            break
        try:
            out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            break
        parts = out.split(None, 1)
        if len(parts) < 2:
            break
        ppid, comm = parts
        match = re.search(r"/([^/]+)\.app/", comm)
        if match:
            return match.group(1)
        known = PROCESS_NAMES.get(os.path.basename(comm).casefold())
        if known:
            return known
        try:
            pid = int(ppid)
        except ValueError:
            break
    return None


def ensure_config(create):
    """Step 6: copy config.example.json to the config path when it is missing. Returns (path, action)."""
    path = config_mod.config_path(None)
    if os.path.isfile(path):
        return path, "present"
    if not create:
        return path, "missing"
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        if os.path.isfile(EXAMPLE_CONFIG):
            shutil.copyfile(EXAMPLE_CONFIG, path)
        else:
            # copy-the-folders install (README alternative): the plugin root is absent, write the defaults instead
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(config_mod.DEFAULTS, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        os.chmod(path, 0o600)
    except OSError as exc:
        return path, "error: {}".format(exc)
    return path, "created"


def example_tags():
    """Tag vocabulary of config.example.json; empty when the plugin root is absent (copy-the-folders install)."""
    try:
        with open(EXAMPLE_CONFIG, encoding="utf-8") as handle:
            return set(json.load(handle).get("tags") or [])
    except (OSError, ValueError, AttributeError):
        return set()


def pick(lang, en, zh):
    return zh if lang == "zh" else en


def step(step_id, ok, detail, fix=None):
    return {"id": step_id, "ok": bool(ok), "detail": detail, "fix": fix}


def token_fix(lang):
    return pick(
        lang,
        "In Things open Settings → General → Enable Things URLs → Manage, copy the token, then in YOUR OWN "
        "terminal run: mkdir -p ~/.config/things-skills && (umask 077; pbpaste > {p}) . Do not paste the "
        "token into this chat.".format(p=TOKEN_PATH),
        "在 Things 中打开 设置 → 通用 → 启用 Things URL → 管理，复制令牌，然后在你自己的终端运行："
        "mkdir -p ~/.config/things-skills && (umask 077; pbpaste > {p}) 。不要把令牌粘贴到对话里。".format(p=TOKEN_PATH),
    )


SOURCE_LABELS = {"en": {"bundled": "bundled", "system": "system"}, "zh": {"bundled": "内置", "system": "系统"}}


def things_py_detail(lang, tpy):
    """Row 3 detail: "bundled 1.0.1" / "内置 1.0.1" (or "system ..." when a system copy was imported)."""
    if not tpy.get("installed"):
        return pick(lang, "cannot import things.py (bundled copy missing or damaged)", "无法导入 things.py（内置副本缺失或损坏）")
    label = SOURCE_LABELS[lang if lang in SOURCE_LABELS else "en"].get(tpy.get("source"))
    return "{} {}".format(label or "things.py", tpy.get("version"))


def things_py_fix(lang):
    """things.py ships inside the plugin, so the only repair is to reinstall or update the plugin."""
    return pick(
        lang,
        "things.py is bundled with the plugin; nothing needs installing by hand. Reinstall or update it with "
        "`codex plugin add things@things3-skills` in Codex, `/plugin update things@things3-skills` in Claude Code, "
        "or re-clone the repository, then rerun the check.",
        "things.py 已随插件内置，无需手动安装。请重新安装或更新插件：在 Codex 中运行 "
        "`codex plugin add things@things3-skills`，在 Claude Code 中运行 `/plugin update things@things3-skills`，"
        "或重新克隆仓库，然后重新运行检查。",
    )


def fda_fix(lang, app):
    name = app or pick(lang, "the app you run Codex or Claude Code from", "你运行 Codex 或 Claude Code 的 App")
    return pick(
        lang,
        "Grant Full Disk Access to {a}: System Settings → Privacy & Security → Full Disk Access → click + and add {a} "
        "→ quit and reopen {a}. If Things has never been launched, open it once first. Until then writes still "
        "work but cannot be verified (write-only mode).".format(a=name),
        "给 {a} 授予完全磁盘访问权限：系统设置 → 隐私与安全性 → 完全磁盘访问权限 → 点 + 添加 {a} → 退出并重新打开 {a}。"
        "如果 Things 从未启动过，请先打开一次。此前写入仍可用，但无法回读验证（只写模式）。".format(a=name),
    )


def build_steps(lang, doctor_env, ping, ping_code, config_action, config_path, cfg, app, requested_transport=None):
    d = doctor_env.get("data") or {}
    doctor_warnings = [w for w in (doctor_env.get("warnings") or []) if w]
    db = d.get("database") or {}
    tok = d.get("token") or {}
    tpy = d.get("things_py") or {}
    cfgd = d.get("config") or {}
    valid = cfgd.get("valid", True)
    config_fix = pick(lang, "Fix the Config file row, then rerun.", "先处理“配置文件”一行，然后重新运行。")
    steps = []

    system = d.get("platform") or platform.system()
    if system == "Darwin":
        os_detail = "macOS {}".format(platform.mac_ver()[0] or platform.release())  # product version, not the kernel's
    else:
        os_detail = "{} {}".format(system, platform.release())
    steps.append(step("macos", system == "Darwin", os_detail,
                      None if system == "Darwin" else pick(lang, "Run the Things skills on a Mac.", "请在 Mac 上运行 Things 技能。")))

    sent = bool(ping.get("sent"))
    transport = (ping.get("data") or {}).get("transport") or "?"
    # main() pings with --transport dry whenever the user exported record, so the envelope says "dry" while the
    # variable the user must unset holds "record": echo what they set, not what the ping was forced to
    shown = requested_transport or transport
    if sent:
        detail = pick(lang, "things:///version was delivered", "things:///version 已送达")
        fix = None
    elif valid is False and ping.get("error"):
        # the CLI refuses every command but doctor while the config is malformed: nothing about Things was tested
        detail = pick(lang, "not checked: the CLI refuses every command while the config file is invalid",
                      "未检查：配置文件无效时 CLI 拒绝执行所有命令")
        fix = config_fix
    elif ping_code == 2 or transport == "open":
        # exit 2 is a transport (URL handler) failure: Things is missing or was never opened
        detail = ping.get("error") or pick(lang, "things:///version not delivered (transport open, exit {c})",
                                           "things:///version 未送达（传输 open，退出码 {c}）").format(c=ping_code)
        fix = pick(lang, "Install Things 3 from the Mac App Store and open it once.", "从 Mac App Store 安装 Things 3 并打开一次。")
    elif ping.get("error"):
        detail = ping["error"]
        fix = pick(lang, "Fix the CLI error shown, then rerun.", "先处理上面的 CLI 错误，然后重新运行。")
    else:
        # dry / record never deliver by design: Things may well be installed, so do not send the user to the App Store
        detail = pick(lang, "not attempted: transport is {t} (nothing was sent to Things)",
                      "未尝试送达：传输为 {t}（没有向 Things 发送任何内容）").format(t=shown)
        fix = pick(lang, "Delivery was skipped because THINGS_SKILLS_TRANSPORT={t}. Unset it and rerun to test the things: URL handler.",
                   "因 THINGS_SKILLS_TRANSPORT={t} 未尝试送达。取消该环境变量后重新运行，以测试 things: URL 处理程序。").format(t=shown)
    steps.append(step("things", sent, detail, fix))

    if d.get("platform") is None and doctor_env.get("error"):
        # `things doctor` produced no envelope: every doctor-derived row is unknown, not failed for the reason it would name
        detail = pick(lang, "not checked: things doctor failed", "未检查：things doctor 运行失败")
        fix = pick(lang, "Fix the doctor error shown under Notes, then rerun.", "先处理“备注”中的 doctor 错误，然后重新运行。")
        for step_id in ("things_py", "database", "token", "config", "tags"):
            steps.append(step(step_id, False, detail, fix))
        return steps

    installed = bool(tpy.get("installed"))
    steps.append(step("things_py", installed, things_py_detail(lang, tpy), None if installed else things_py_fix(lang)))

    status = db.get("status")
    if not installed:
        steps.append(step("database", False, pick(lang, "not checked: fix the things.py row first", "未检查：请先处理 things.py 一行"),
                          pick(lang, "Fix the things.py row, then rerun.", "先处理 things.py 一行，然后重新运行。")))
    elif status == "readable":
        steps.append(step("database", True, db.get("path")))
    elif status == "fixture":
        steps.append(step("database", True, pick(lang, "readable via THINGSDB override: {p}", "通过 THINGSDB 覆盖可读：{p}").format(p=db.get("path"))))
    else:
        steps.append(step("database", False, "{}: {}".format(db.get("error") or "unavailable", db.get("path")), fda_fix(lang, app)))

    present, empty, mode_ok = tok.get("present"), tok.get("empty"), tok.get("mode_ok")
    if not present:
        steps.append(step("token", False, pick(lang, "{p} is missing", "{p} 不存在").format(p=TOKEN_PATH), token_fix(lang)))
    elif empty:
        steps.append(step("token", False, pick(lang, "{p} is empty", "{p} 为空").format(p=TOKEN_PATH), token_fix(lang)))
    elif mode_ok is False:
        steps.append(step("token", False, pick(lang, "{p} has mode {m}; others can read it", "{p} 权限为 {m}，其他用户可读").format(
            p=TOKEN_PATH, m=tok.get("mode")), "chmod 600 {}".format(TOKEN_PATH)))
    else:
        steps.append(step("token", True, "{} ({})".format(TOKEN_PATH, tok.get("mode"))))

    if config_action == "created":
        steps.append(step("config", True, pick(lang, "created from config.example.json: {p}", "已从 config.example.json 创建：{p}").format(p=config_path),
                          pick(lang, "Edit areas, routing_hints and tags in that file to match your Things.",
                               "请编辑该文件中的 areas、routing_hints 和 tags 以匹配你的 Things。")))
    elif config_action.startswith("error"):
        steps.append(step("config", False, "{}: {}".format(config_action, config_path),
                          pick(lang, "Copy {e} to {p} by hand.", "请手动把 {e} 复制到 {p}。").format(e=EXAMPLE_CONFIG, p=config_path)))
    elif not cfgd.get("present"):
        steps.append(step("config", False, pick(lang, "{p} is missing", "{p} 不存在").format(p=config_path),
                          pick(lang, "Rerun without --no-create-config to copy the example.", "去掉 --no-create-config 重新运行即可复制示例配置。")))
    elif not valid:
        steps.append(step("config", False, pick(lang, "{p} is invalid: {w}", "{p} 无效：{w}").format(
            p=config_path, w="; ".join(doctor_warnings) or "malformed"),
            pick(lang, "Fix the JSON in that file, or move it aside and rerun to recreate it from the example.",
                 "修正该文件的 JSON，或把它移走后重新运行以从示例重建。")))
    else:
        steps.append(step("config", True, config_path))

    wanted = list(cfg.get("tags") or [])
    missing = cfgd.get("missing_tags")
    if valid is False:
        # cfg fell back to the defaults (tags []) because the file did not parse: no vocabulary was checked
        steps.append(step("tags", False, pick(lang, "not checked: fix the config row first", "未检查：请先处理配置文件一行"), config_fix))
    elif missing is None:
        steps.append(step("tags", False, pick(lang, "not checked (database unavailable)", "未检查（数据库不可用）"),
                          pick(lang, "Fix the database row, then rerun.", "先处理数据库一行，然后重新运行。")))
    elif missing and (config_action == "created" or (wanted and set(wanted) == example_tags())):
        # the config was just copied from the example, or still carries the example vocabulary untouched: placeholder tags
        steps.append(step("tags", False, pick(lang, "example tags not in Things: {m}", "示例标签在 Things 中不存在：{m}").format(m=", ".join(missing)),
                          pick(lang, "These are the example tags. Replace config.tags in {p} with your own tag names "
                                     "(or create them in Things), then rerun.",
                               "这些是示例标签。请把 {p} 中的 config.tags 改成你自己的标签名（或在 Things 中创建它们），然后重新运行。").format(p=config_path)))
    elif missing:
        steps.append(step("tags", False, pick(lang, "missing in Things: {m}", "Things 中不存在：{m}").format(m=", ".join(missing)),
                          pick(lang, "Create these tags in Things (Window → Tags, or type them on any to-do), then rerun. "
                                     "The skills never create tags.",
                               "请在 Things 中创建这些标签（窗口 → 标签，或在任意待办上输入），然后重新运行。技能不会自动创建标签。")))
    elif not wanted:
        steps.append(step("tags", True, pick(lang, "config.tags is empty; nothing to check", "config.tags 为空，无需检查")))
    else:
        steps.append(step("tags", True, pick(lang, "all {n} tags exist", "全部 {n} 个标签都存在").format(n=len(wanted))))
    return steps



def collect_notes(lang, cfg, tags_env, areas_env, doctor_env, ping_env, config_action="present"):
    notes = []
    tags = cfg.get("tags") or []
    if len(tags) > 10:
        notes.append(pick(lang, "config.tags has {n} entries; keep the vocabulary under 10 (tags for context, areas for life domains).",
                          "config.tags 有 {n} 项；建议保持在 10 个以内（标签表示情境，领域表示生活领域）。").format(n=len(tags)))
    things_tags = [t.get("title") for t in (tags_env.get("data") or []) if isinstance(t, dict)] if tags_env.get("ok") else None
    things_areas = [a.get("title") for a in (areas_env.get("data") or []) if isinstance(a, dict)] if areas_env.get("ok") else None
    if things_areas is not None:
        # config.areas plus every area a routing hint points at: a hint whose area is missing can never route
        wanted = list(cfg.get("areas") or [])
        for hint in cfg.get("routing_hints") or []:
            area = hint.get("area") if isinstance(hint, dict) else None
            if area and area not in wanted:
                wanted.append(area)
        absent = [a for a in wanted if a not in things_areas]
        if absent and config_action == "created":
            notes.append(pick(lang, "config.areas / routing_hints still name the example areas ({a}), which are not in Things: "
                                    "set them to your real area names.",
                              "config.areas / routing_hints 仍是示例领域（{a}），Things 中不存在：请改成你真实的领域名。").format(a=", ".join(absent)))
        elif absent:
            notes.append(pick(lang, "config.areas / routing_hints name areas not found in Things: {a}. Rename them in the config or create the areas in Things.",
                              "config.areas / routing_hints 中的领域在 Things 中不存在：{a}。请在配置里改名，或在 Things 中创建这些领域。").format(a=", ".join(absent)))
    for env in (doctor_env, ping_env, tags_env, areas_env):
        for warning in env.get("warnings") or []:
            if warning not in notes:
                notes.append(warning)
    return notes, things_tags, things_areas


def render_markdown(report):
    lang = report["lang"]
    t = TEXT[lang]
    lines = ["## {}".format(t["title"]), ""]
    lines.append("| {} | {} | {} |".format(*t["columns"]))
    lines.append("|---|---|---|")
    for s in report["steps"]:
        detail = (s["detail"] or "").replace("|", "\\|").replace("\n", " ")
        lines.append("| {} | {} | {} |".format(s["label"], OK if s["ok"] else BAD, detail))
    failed = [s for s in report["steps"] if not s["ok"]]
    lines.append("")
    lines.append(t["all_ok"] if not failed else t["some_bad"].format(n=len(failed)))
    numbered = [s for s in report["steps"] if not s["ok"] and s["fix"]]   # the numbering equals the failed count
    extra = [s for s in report["steps"] if s["ok"] and s["fix"]]         # advice on a passed row stays a bullet
    if numbered or extra:
        lines += ["", "### {}".format(t["next"])]
        for i, s in enumerate(numbered, 1):
            lines.append("{}. **{}** — {}".format(i, s["label"], s["fix"]))
        for s in extra:
            lines.append("- **{}** — {}".format(s["label"], s["fix"]))
    if report["notes"]:
        lines += ["", "### {}".format(t["notes"])]
        lines += ["- {}".format(n) for n in report["notes"]]
    return "\n".join(lines) + "\n"


def resolve_lang(requested, cfg, text=None):
    """Explicit --lang zh|en wins (the user asked for it); else config.language; else detect from the invocation."""
    if requested in ("zh", "en"):
        return requested
    configured = cfg.get("language")
    if configured in ("zh", "en"):
        return configured
    return detect_language(text) if text else "en"


def main(argv=None):
    parser = argparse.ArgumentParser(description="things-setup status check (doctor + ping + config bootstrap)")
    parser.add_argument("--markdown", action="store_true", help="print a Markdown table instead of JSON")
    parser.add_argument("--lang", choices=("zh", "en", "auto"), default="auto",
                        help="report language; auto follows config.language, else detects it from --text, else en")
    parser.add_argument("--text", help="the user's invocation, for language detection with --lang auto")
    parser.add_argument("--now", metavar="YYYY-MM-DDTHH:MM", help="frozen clock forwarded to the CLI (tests)")
    parser.add_argument("--no-create-config", action="store_true", help="do not copy config.example.json (report only)")
    args = parser.parse_args(argv)

    doctor_env, _ = run_cli("doctor", now=args.now)
    config_path, config_action = ensure_config(create=not args.no_create_config)
    if config_action == "created":
        doctor_env, _ = run_cli("doctor", now=args.now)
    try:
        cfg = config_mod.load_config(None)
    except config_mod.ConfigError:
        cfg = dict(config_mod.DEFAULTS)
    lang = resolve_lang(args.lang, cfg, args.text)

    # Only the `open` transport can prove the URL handler; record and dry never deliver, and record would append
    # ./.things-skills/outbox.jsonl in whatever directory Claude Code was launched from, which this skill promises not to do.
    transport = os.environ.get("THINGS_SKILLS_TRANSPORT") or ("open" if platform.system() == "Darwin" else "record")
    ping_args = ["ping"] if transport == "open" else ["--transport", "dry", "ping"]
    ping_env, ping_code = run_cli(*ping_args, now=args.now)
    tags_env, _ = run_cli("tags", now=args.now)
    areas_env, _ = run_cli("areas", now=args.now)

    app = terminal_app()
    steps = build_steps(lang, doctor_env, ping_env, ping_code, config_action, config_path, cfg, app, transport)
    for s in steps:
        s["label"] = TEXT[lang]["labels"][s["id"]]
    notes, things_tags, things_areas = collect_notes(lang, cfg, tags_env, areas_env, doctor_env, ping_env, config_action)
    notes = [n for n in notes if not any(n in (s["detail"] or "") for s in steps)]  # already shown in a row
    if doctor_env.get("error"):
        notes.insert(0, "doctor: {}".format(doctor_env["error"]))

    report = {
        "ok": all(s["ok"] for s in steps),
        "lang": lang,
        "platform": platform.system(),
        "repo_root": REPO_ROOT,
        "terminal_app": app,
        "config_path": config_path,
        "config_action": config_action,
        "token_path": TOKEN_PATH,
        "steps": steps,
        "things": {"tags": things_tags, "areas": things_areas},
        "notes": notes,
        "doctor": doctor_env.get("data"),
        "ping": {"ok": ping_env.get("ok"), "sent": ping_env.get("sent"), "exit": ping_code, "error": ping_env.get("error")},
    }
    if args.markdown:
        sys.stdout.write(render_markdown(report))
    else:
        sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
