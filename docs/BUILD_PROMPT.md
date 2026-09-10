# Build `things-skills`: Claude Code skills for Things 3 (bilingual, URL-scheme writes), developed on Linux, run on macOS

> Historical build brief, frozen 2026-09-08. It describes the original ask, not the shipped plugin:
> `SPEC.md`, `README.md` and `CHANGELOG.md` supersede every fact below (the distribution is now
> `things3-skills` 0.1.0, things.py is bundled, `requirements.txt` no longer exists, the marketplace
> install is `/plugin install things@things3-skills`, and the macOS gate is `scripts/osgate`, which
> warns and always exits 0). `SPEC.md` section A.9 records where the brief and the verified facts
> disagree.

You are starting in `<repo root>` on a Linux development box. This folder is the repository root. Things 3 is NOT installed here and there is no macOS. Everything you build must be developed and unit-tested on Linux without Things. When you are done I will copy the whole folder to my Mac with scp and run setup and live tests there. Design for that split from the first line of code.

Build a publishable set of Claude Code skills that let me manage my Things 3 to-dos from Claude Code in Chinese and English. Use multi-agent orchestration for the build: one spec agent, then parallel implementers, then an adversarial tester and a reviewer. Plan before coding, and show me the plan before Phase 2 starts. This prompt is also saved as `BUILD_PROMPT.md` in this folder; move it to `docs/BUILD_PROMPT.md` and keep it in the repo.

## 1. Hard facts about Things 3 (verified 2026-09-08, do not re-research these)

- The ONLY official write API is the URL scheme. Reference: https://culturedcode.com/things/support/articles/2803573/ . Read that page in full (WebFetch works from this box) before writing any code and treat it as the source of truth. Commands: `add`, `add-project`, `update`, `update-project`, `show`, `search`, `version`, `json`.
- The URL scheme cannot read anything back. `x-success` callbacks only work if the caller owns a URL handler, which a shell script does not. Therefore READS go through the `things.py` library (`pip install things.py`, Apache-2.0, read-only SQLite access to the local Things database). API reference: https://thingsapi.github.io/things.py/things/api.html . Read it in full alongside the URL scheme page. It documents 25 functions: `tasks` (the central query with filters for type, status, area, project, heading, tag, start, start_date, stop_date, deadline, trashed, search_query), `todos`, `projects`, `areas`, `tags`, `checklist_items`, `search`, `get`, `inbox`, `today`, `upcoming`, `anytime`, `someday`, `logbook`, `trash`, `canceled`, `completed`, `deadlines`, `last`, plus URL helpers `token` (reads the auth token from the database), `url` and `link` (build `things:///` URLs and auto-attach the token for `update` and `update-project`), `show`, `complete`, and `pop_database`. `THINGSDB` overrides the database path. Never write to the SQLite database.
- Use `things.url()` as the reference for URL construction and `things.token()` as a fallback when the token file is absent, but the token FILE (section 4) is the primary source because I control it. Headings have no dedicated function; use `tasks(type='heading')`. `today()` does not include repeating tasks that are due today, so `things-today` must add them via `tasks(start='Anytime', ...)` or the recurrence fields and say when it cannot.
- `add` and `add-project` need no token. `update`, `update-project`, and any `json` object with `operation: update` REQUIRE `auth-token`. The token comes from Things → Settings → General → Enable Things URLs → Manage.
- On macOS, `open -g "things:///..."` sends the command without bringing Things to the foreground. It exits 0 even when Things rejects the URL, so every write must be verified by re-reading with `things.py` after a short delay (1 to 2 seconds).
- URL-encode every value with `urllib.parse.quote(value, safe='')`. An unencoded `/` is parsed as a path delimiter and silently truncates the value.
- Limits: 250 items per 10 seconds; 4,000 characters per unencoded value; notes 10,000 characters; 100 checklist items per to-do. The `json` payload must be whitespace-stripped and URL-encoded.
- Tags are NEVER auto-created by the URL scheme. A tag that does not exist is silently ignored. The skills must only apply tags that already exist (verify with `things.tags()`).
- Repeating to-dos refuse `when`, `deadline`, `completed`, `canceled`, `duplicate`. Detect them (things.py exposes the recurrence flag) and tell the user instead of failing silently.
- Hierarchy is fixed: Area > Project > Heading > To-do > Checklist item. No folders, no nested projects, no task dependencies. Checklist items are the only subtasks and hold a title and a status only. Headings can be created only inside a new project via the `json` command; an existing to-do can be placed under an existing heading with `heading` or `heading-id`.
- `when` accepts `today`, `tomorrow`, `evening`, `anytime`, `someday`, `yyyy-mm-dd`, or `yyyy-mm-dd@HH:MM` (sets a reminder). Its natural-language parsing is English-only, so YOU parse dates (including Chinese) and always emit ISO values.
- `things:///show?id=<ID>` opens an item; include these links in output so I can click through.
- On macOS, reads via `things.py` need Full Disk Access for the terminal app that runs Claude Code. Writes need nothing beyond Things being installed and opened once.
- Reference implementation for edge cases (MIT, read but do not copy wholesale): https://github.com/ebowman/mcp-server-things . Do not copy from repositories without a licence.

## 2. Linux-first development constraints

- **Transport abstraction.** All writes go through one function that takes a fully built URL and a transport: `open` (macOS, `subprocess.run(["open", "-g", url])`), `record` (append the URL to `.things-skills/outbox.jsonl` with a timestamp; used on Linux and in tests), `dry` (print with the token masked, send nothing). Select with `THINGS_SKILLS_TRANSPORT`; default is `open` on Darwin and `record` elsewhere. Never call `open` on Linux.
- **Read abstraction.** All reads go through one module that wraps `things.py`. `things.py` honours the `THINGSDB` environment variable for the database path. For Linux tests, download `things.py`'s own test database (`tests/main.sqlite` in https://github.com/thingsapi/things.py , Apache-2.0) into `tests/fixtures/` once and point `THINGSDB` at it; if the download is blocked, build a minimal fixture from the schema `things.py` documents. Every read function must also be mockable for tests that need specific data.
- **No macOS-only behaviour at import time.** Platform checks happen inside functions. `python3 -m pytest` must pass on this Linux box with Python 3.9 or newer, and the code must run on the macOS Command Line Tools `python3`. Dependencies: standard library plus `things.py` only. Pin `things.py` to the current release in `requirements.txt`.
- **Verification after write** is macOS-only (it needs the real database). On Linux, `record` transport returns a synthetic "unverified" result and the CLI says so plainly.
- **The macOS gate in every SKILL.md stays.** The skills warn and stop on Linux; only the CLI's `--dry-run`, `record` transport, and the test suite run here.
- **Devbox limits.** Run at most 5 agents concurrently. Serialize test runs. Write long files in chunks of about 60 lines.

## 3. Repository layout (this folder is the repo root, Claude Code plugin marketplace format)

```
<repo root>/
  .claude-plugin/marketplace.json        # name: things-skills, one plugin: ./plugins/things
  plugins/things/
    .claude-plugin/plugin.json           # name: things, version 0.1.0, license MIT
    skills/
      things-setup/SKILL.md
      things-capture/SKILL.md
      things-close/SKILL.md
      things-organize/SKILL.md
      things-deadlines/SKILL.md
      things-today/SKILL.md
    scripts/
      things_lib/__init__.py
      things_lib/token.py                # read token file
      things_lib/url.py                  # build URLs, encoding, rate limit
      things_lib/transport.py            # open | record | dry
      things_lib/read.py                 # things.py wrappers, JSON output
      things_lib/verify.py               # post-write re-read (macOS)
      things_lib/dates.py                # ZH/EN relative date parsing to ISO
      things_lib/config.py               # load config, defaults
      things                             # single CLI entry point (python3), subcommands below
    config.example.json
  tests/                                 # pytest; runs on Linux with no Things
    fixtures/main.sqlite                 # things.py test database
  docs/BUILD_PROMPT.md
  HANDOFF.md                             # what I do on the Mac after scp
  README.md  LICENSE (MIT)  CHANGELOG.md  requirements.txt  .gitignore
```

Every SKILL.md: frontmatter with `name`, a `description` that contains BOTH English and Chinese trigger phrases, per-skill `allowed-tools` (helpers + read subcommands, never writes) and a first body line `` !`${CLAUDE_SKILL_DIR}/scripts/osgate` `` that warns on non-macOS (always exit 0). Keep each SKILL.md under 120 lines; put logic in scripts, not prose.

`.gitignore` must cover `__pycache__/`, `.pytest_cache/`, `.venv/`, `.things-skills/`, and any local config or token copies. The token and config live outside the repo (section 4), so nothing personal is ever committed.

## 4. Token and config

- Token file: `~/.config/things-skills/auth-token`, plain text, single line, trailing whitespace stripped. I will paste the value myself on the Mac. `token.py` must: expand `~`, refuse to proceed with a clear message if the file is missing or empty, warn once if permissions are wider than 0600, never print the token, never pass it on a command line that ends up in logs (build the URL in Python and call the transport with a list argument).
- Config file: `~/.config/things-skills/config.json`, created by `things-setup` from `config.example.json`. Keys: `areas` (list of my Area names, e.g. Work / Personal / Career), `routing_hints` (keyword or regex → area, both languages), `tags` (the allowed tag vocabulary; setup verifies each exists in Things), `synonyms` (ZH ↔ EN pairs used by search), `today_cap` (default 6), `stale_days` (default 30), `deadline_lead_days` (default 3), `default_reminder_time` (default "09:00"), `language` ("auto"). Only `config.example.json` ships.

## 5. Shared CLI (`scripts/things`) — subcommands the skills call

All subcommands print JSON to stdout, human errors to stderr, non-zero exit on failure.

Reads (things.py): `inbox`, `today`, `upcoming`, `anytime`, `someday`, `logbook --days N`, `deadlines`, `projects`, `areas`, `tags`, `get <id>` (with checklist), `search "<query>" [--status open] [--area X]` (substring search over title AND notes; must work for CJK substrings), `stale --days N`, `overdue`.

Writes (URL scheme): `add` (title, notes, when, deadline, tags, checklist, list or list-id, heading or heading-id), `add-project` (title, notes, when, deadline, tags, area, to-dos), `add-json <file>` (project with headings and to-dos with checklist items in one command), `update <id>` (any update field; token), `complete <id>...` (batch; token), `cancel <id>...`, `move <id> --list|--area|--heading`, `schedule <id> --when`, `deadline <id> --date`, `tag <id> --add`, `show <id>`.

Cross-cutting: `--dry-run` prints the exact URL(s) with the token masked and does not send; rate limiter enforces 250 per 10 s; on macOS, after every write, re-read via things.py to confirm and return the affected IDs and `things:///show?id=` links; `--verify-timeout` default 3 s. Match newly created items by title and creation time within the last 10 s. `things doctor` prints platform, transport, database path and readability, token presence, `things.py` version.

## 6. Skills

### things-setup
Checks: macOS, Things installed and opened once, `things.py` importable (offer `pip3 install --user -r requirements.txt`), database readable (if not, print the exact Full Disk Access steps for the current terminal app), token file present and non-empty, `things:///version` responds, config exists (create from example if not), every tag in `config.tags` exists in Things (print the missing ones and ask me to create them in Things; do not try to create them). Prints a one-screen status table.

### things-capture (create)
Input: free text in Chinese, English, or mixed, possibly several tasks at once, possibly a vague goal.
Behavior:
1. Parse into one or more to-dos. For each: title in MY language as written (do not translate titles), notes (context I gave, plus source link if any), `when` (parse ZH/EN relative dates: 明天, 下周三, 月底, 周五晚上, next Tue, EOD Friday, in 2 weeks → ISO), `deadline` if I said 截止 / due / by / before, `tags` only from the allowed vocabulary, area or project via `routing_hints` and my wording, checklist items when the task has obvious concrete steps (3 to 8 items; never pad).
2. If the input is a multi-step goal with distinct phases, propose a project with headings and to-dos (via `add-json`) instead of one to-do.
3. Show me a compact preview table (title, list, when, deadline, tags, checklist count) and ask for confirmation unless I said "just do it" / "直接建". Then write, verify, and print the `show` links.
Rules: never invent deadlines; if I gave a date but not whether it is a start or a deadline, ask one short question; personal and work items in the same message are routed independently.

### things-close (complete)
Input: high-level description of what got done ("finished the CR review and the dentist thing", "把周报和报销关掉").
Behavior: search open items by title and notes substrings and synonyms in both languages, rank candidates, show the top matches with list and dates, ask me to confirm the set (single keypress answers like `1,3` or `all`), then `complete` in one batch and print what was completed. If a candidate is a repeating to-do, explain it cannot be completed via URL and skip it. Offer `cancel` when I say something was dropped rather than done (取消 / drop / won't do).

### things-organize
Input: optional scope (`inbox`, `today`, `all`, an area or project name). Default: full weekly review.
Behavior, as a dry-run report first, then apply what I approve:
1. Inbox zero: for each Inbox item propose list or project, when, tags, and whether it needs a deadline. Anything under 2 minutes gets flagged "do now".
2. Today overload: if Today has more than `today_cap` items, propose which to push to tomorrow, Anytime, or Someday, keeping items with deadlines within `deadline_lead_days`.
3. Stale: Anytime items untouched for more than `stale_days` → propose Someday, or cancel, or a 15-minute "decide" to-do.
4. Deadline sanity: deadline earlier than start date, deadlines in the past on open items, deadlines with no start date within lead time.
5. Tag hygiene: items with no area or project; tags outside the vocabulary.
6. Evening: items that are clearly personal-evening (gym, calls home, 家里的事) proposed for `when=evening`.
Output a numbered proposal; I answer with numbers to apply. Apply in batches respecting the rate limit.

### things-deadlines (ddl control)
Behavior: list overdue, due today, due within 7 days, due within 30 days, grouped by area, with start dates. Flag at-risk items: deadline within `deadline_lead_days` and no start date, or start date after deadline. Propose backward scheduling: set `when` to deadline minus lead days, with `default_reminder_time` as a reminder if I want one. Support "push": `things-deadlines push <id> +3d` and "clear". Accept Chinese: 逾期 / 本周到期 / 推后三天.

### things-today
Morning brief: Today list, This Evening, overdue, deadlines within 7 days, Inbox count. If Today exceeds `today_cap`, say so and hand off to `things-organize today`. End with one line I can paste into my Obsidian daily note (markdown checklist with `things:///show?id=` links). Answer in the language I used to invoke it.

## 7. Best practices to encode (cite them briefly in the SKILL.md bodies)

- `when` is when I intend to start; `deadline` is the external hard date. Never set a deadline that is really a start intention.
- Today is a promise for today, not a wish list. Cap it.
- Inbox is for capture only; nothing should live there more than a week.
- Someday is a parking lot, not a graveyard: `things-organize` resurfaces items older than 90 days.
- Projects have an outcome in the title ("Ship X", "完成 Y"); to-dos start with a verb. Suggest, do not force, renames.
- Checklists for steps that take under a day each; a project when steps span days or need dates.
- Keep the tag vocabulary small (under 10). Tags are for context (`@calls`, `@errands`, `@deep`), areas are for life domains.

## 8. Bilingual rules

- Detect the language of each invocation and reply in kind. Mixed input gets mixed output as appropriate.
- Never translate my titles or notes. Parse Chinese dates and time words (明天, 后天, 下周X, 月底, 下月初, 晚上, 上午 / 下午 with hours, 周末).
- Search must match Chinese substrings and English case-insensitively, and should try the `synonyms` table from config (报销 ↔ expense, 周报 ↔ weekly report, 医生 ↔ doctor / dentist) which I can extend.
- Skill `description` fields carry both languages so the skills trigger from Chinese requests.

## 9. Safety

- All writes are preview-then-confirm by default. `--yes` / "直接" skips confirmation for capture only; close and organize always show the affected set before writing.
- No tool ever deletes. `cancel` and moving to Someday are the strongest actions.
- Never log the token. Never write to the Things database. Never call Things Cloud.
- If `things.py` cannot open the database on the Mac, writes still work; say so and continue in write-only mode with reduced verification.

## 10. Testing

- Unit tests (pytest, run here on Linux, no Things): URL building and encoding for every command including `/`, `&`, `#`, CJK, emoji; token masking in dry-run; `record` transport output; date parsing table for at least 30 ZH and EN phrases with a frozen "now"; rate limiter; routing hints; synonyms; config defaults; JSON payload construction for `add-json`; read wrappers against `tests/fixtures/main.sqlite` via `THINGSDB`.
- Live tests, macOS only, opt-in via `THINGS_SKILLS_LIVE=1`: create a project named `Things Skills Test <timestamp>`, add to-dos with checklist and heading, update, complete, and verify each via things.py. Leave the test project completed; print its `show` link so I can trash it by hand (the URL scheme cannot delete). These tests must skip cleanly on Linux.
- The tester agent writes tests against SPEC.md, not against the implementation, and must try to break encoding and date parsing.

## 11. Orchestration plan (multi-agent orchestration, max 5 concurrent agents)

Phase 1, one agent: read the URL scheme page and the things.py API reference (https://thingsapi.github.io/things.py/things/api.html), write `SPEC.md` containing the exact command and parameter matrix, the read/write split, the transport and read abstractions from section 2, the CLI contract from section 5, and the skill contracts from section 6. Stop and show me SPEC.md.
Phase 2, after my OK: one agent builds `things_lib`, the `things` CLI, the fixture download, and unit tests (everything depends on it). Then five agents, at most 5 at a time, one per skill (setup, capture, close, organize, deadlines plus today), each writing its SKILL.md and any skill-specific script against the CLI contract only.
Phase 3, two agents in parallel: a tester agent (section 10) and a reviewer agent that checks encoding, token handling, macOS gating, transport selection, rate limiting, dry-run correctness, that no path writes to SQLite or deletes, and that nothing calls `open` on Linux.
Phase 4, one agent: README (install via `/plugin marketplace add <me>/things-skills` or by cloning into `~/.claude/skills/`), `HANDOFF.md` (section 12), CHANGELOG, `config.example.json`, LICENSE, `requirements.txt`. `git init`, commit with a clean history. Do not add a remote and do not push.
Keep the total under 12 agents. Cheap models for the mechanical legs (tests, docs), strong model for SPEC, lib, and review.

## 12. HANDOFF.md (write this file; it is what I follow on the Mac)

1. On the Mac: copy `<repo root>` to `~/Developer/things-skills` (I will adjust the destination).
2. `cd ~/Developer/things-skills && pip3 install --user -r requirements.txt`
3. Create `~/.config/things-skills/auth-token` (0600) with the token from Things → Settings → General → Enable Things URLs → Manage.
4. Grant Full Disk Access to the terminal app I run Claude Code from (System Settings → Privacy & Security → Full Disk Access), then restart that app.
5. `python3 plugins/things/scripts/things doctor` and fix anything red.
6. Install the plugin locally (`/plugin marketplace add ~/Developer/things-skills` then `/plugin install things@things-skills`, or the `~/.claude/skills` clone path), then run `/things:things-setup`.
7. `THINGS_SKILLS_LIVE=1 python3 -m pytest tests/ -m live` and trash the test project it prints.
8. Only then create a GitHub repo and push.

## 13. Definition of done

Done on Linux, before I scp:
- `python3 -m pytest` passes here with no Things and no network beyond the one-time fixture download.
- `python3 plugins/things/scripts/things doctor` runs on Linux and reports transport `record` and database "fixture" or "unavailable" without crashing.
- `things add --dry-run` and `things complete --dry-run` print correctly encoded URLs with the token masked, for CJK and English input.
- `git status` clean; no token, config, or personal data in the repo; `docs/BUILD_PROMPT.md` and `HANDOFF.md` present.

Done on the Mac, which I will run and report back:
- `things-setup` prints green for every check.
- From a fresh Claude Code session: a Chinese capture request creates a to-do with checklist and correct ISO date; an English close request completes the right item after confirmation; `things-organize inbox` produces a numbered proposal and applies the ones I pick; `things-deadlines` lists overdue and at-risk items with clickable links.
- Live tests pass.
