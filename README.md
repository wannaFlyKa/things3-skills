# things3-skills

Claude Code skills for managing [Things 3](https://culturedcode.com/things/) to-dos. They reply
in Chinese or English and work with input in any language the model understands; only the
deterministic date parser is limited to Chinese and English phrases (see Known limitations).
Writes go through the official Things URL scheme; reads go through
[things.py](https://github.com/thingsapi/things.py) 1.0.1, which opens the local Things database
read-only and ships inside the plugin, so there is nothing to `pip install`. The skills run on
macOS only, because that is where Things and its database live; on any other platform each skill
prints a one-line warning and stops.
The code was developed and unit-tested on Linux without Things, so the test suite, the
`--dry-run` mode and the `record` transport work anywhere Python 3.9+ runs.

## The six skills

Once installed as a plugin the skills are invoked as `/things:<name>` or triggered by the
phrases in each skill's description. Titles and notes are never translated; replies come
back in the language you used.

| Skill | Purpose | Example invocations |
|---|---|---|
| `things-setup` | Health check: macOS, Things, things.py, database access, token file, config file and tag vocabulary. Prints a one-screen status table with the fix for every failed row. Creates the config file from the example if missing. | "set up Things", "check Things", "things doctor" |
| `things-capture` | Turns free text into one or more to-dos, or one project with headings, with parsed `when` / `deadline`, routing to an area or project, allowed tags and a checklist when the steps are obvious. Previews, asks once, writes, verifies. | "add to Things", "remind me to call the dentist Friday", "capture", "just do it" |
| `things-close` | Finds open to-dos matching what you say got done (title, notes, configurable synonyms), shows numbered candidates, completes or cancels the ones you pick in one batch; after you pick, only the picked rows and the verb you chose are ever sent. | "done with the CR review", "finished", "mark complete", "cancel the dentist appointment" |
| `things-organize` | Weekly review: Inbox zero, Today overload, stale items, deadline sanity, tag hygiene, evening candidates, Someday resurfacing. Numbered dry-run proposal first; applies only the numbers you choose. | "weekly review", "organize Things", "inbox zero", "clean up my tasks" |
| `things-deadlines` | Lists overdue and upcoming deadlines grouped by area, flags at-risk items, proposes backward scheduling, and pushes, sets or clears deadlines after confirmation. | "deadlines", "overdue", "due this week", "push deadline", "DDL" |
| `things-today` | Read-only morning brief: Today, This Evening, overdue, deadlines within 7 days, Inbox count, plus an Obsidian daily-note checklist with `things:///show?id=` links. | "morning brief", "what's on today", "today's plan" |

## Installation

Prerequisites: macOS; Things 3 installed and opened at least once; Python 3.9 or newer (the
`python3` that ships with macOS Command Line Tools is fine); Claude Code. There are no Python
dependencies to install: things.py 1.0.1 is bundled in the plugin at
`plugins/things/scripts/vendor/things/`, and the CLI prefers that copy over any system-installed
things.py.

Two ways. Both need the first-time setup in the next section afterwards.

**(a) From a GitHub marketplace.** Inside Claude Code:

```
/plugin marketplace add wannaFlyKa/things3-skills
/plugin install things@things3-skills
```

`/plugin marketplace add owner/repo` clones over SSH by default. If you have no SSH key on your
GitHub account, set `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` in the environment Claude Code runs in
and it clones over HTTPS instead.

**(b) From a local clone.** Clone the repository, then point the marketplace at the folder:

```
git clone https://github.com/wannaFlyKa/things3-skills ~/Developer/things3-skills
/plugin marketplace add ~/Developer/things3-skills
/plugin install things@things3-skills
```

You can also copy the six skill folders from `plugins/things/skills/` into `~/.claude/skills/`
and invoke them as `/things-setup` and so on. Each skill ships a tiny `scripts/things` wrapper
that runs the shared CLI three directory levels up (`../../../scripts/things`), which inside the
plugin tree is `plugins/things/scripts/things`. If you copy only the skill folders it resolves to
`~/.claude/scripts/things`, so also copy `plugins/things/scripts/` to `~/.claude/scripts/`. In that
layout `setup_check.py` cannot find `plugins/things/config.example.json`, so it writes the built-in
defaults to `~/.config/things-skills/config.json` instead (edit `areas`, `routing_hints` and `tags`
afterwards), and the slash names lose the `things:` prefix (`/things-setup`, `/things-today`, ...), so
the cross-references inside the skills point at names that do not exist there. Keeping the whole
`plugins/things` tree together, as routes (a) and (b) do, avoids both problems.

## First-time setup (macOS)

Nothing to install: the plugin already contains things.py. Three steps remain.

1. Create the token file. In Things open Settings → General → Enable Things URLs → Manage,
   copy the token, then:

   ```
   mkdir -p ~/.config/things-skills && chmod 700 ~/.config/things-skills
   ( umask 077; pbpaste > ~/.config/things-skills/auth-token )
   ```

   The file must be mode 0600. Its first non-blank line is used; a UTF-8 BOM and trailing
   whitespace are ignored. Only `update`-style writes (complete, cancel, move, schedule,
   deadline, tag, update) need the token; `add` and `add-project` do not.

   When Full Disk Access (step 2) is granted the CLI can also read the token from the Things
   database: if the file is missing it uses that copy and prints
   `note: using auth token from the Things database; create ~/.config/things-skills/auth-token to silence this`
   to stderr. The file makes the token source explicit and works without Full Disk Access.

2. Grant Full Disk Access to the terminal app that runs Claude Code (System Settings →
   Privacy & Security → Full Disk Access → add the app), then quit and reopen that app.
   Without it, writes still work but nothing can be read back or verified.

3. Run `/things:things-setup` in Claude Code, or `python3 plugins/things/scripts/things doctor`
   in a shell, and fix every row that is not green. Setup creates the config file for you: it
   copies `config.example.json` to `~/.config/things-skills/config.json` if it does not exist yet.

## Configuration

`~/.config/things-skills/config.json` (override with `--config PATH` or `THINGS_SKILLS_CONFIG`).
A missing file silently yields the defaults below; a malformed file makes every command exit 1
except `doctor`, which reports it. Only `plugins/things/config.example.json` ships in the repo.

| Key | Meaning | Default |
|---|---|---|
| `areas` | Your Things area names. Informational: only `things-setup` reads it, to warn when one does not exist in Things; routing uses `routing_hints` and `search --area` matches the database. | `[]` |
| `routing_hints` | List of `{"pattern", "area", "project", "regex"}`. Matched in order against title plus notes, case-insensitively; first match wins. `regex: false` is a plain substring test, `regex: true` uses `re.search`. `project` non-null sends the item into that project. Python `\b` does not delimit CJK words (Han characters count as `\w`), so put CJK alternatives outside the `\b(...)\b` group as plain alternations, as `config.example.json` does. | `[]` |
| `tags` | The allowed tag vocabulary (keep it under 10). Setup verifies each exists in Things; the CLI drops tags Things does not have. Tags are never created. | `[]` |
| `synonyms` | Groups of interchangeable search terms, in any language. Any member expands to all members; a multi-word member such as `weekly report` is matched as one term in a query. | Three example groups pairing common Chinese task words with `expense` / `reimbursement`, `weekly report`, and `doctor` / `dentist` (see `DEFAULTS` in `config.py`). |
| `today_cap` | Maximum open to-dos in Today before `things-organize` proposes pushing some. | `6` |
| `stale_days` | Anytime to-dos untouched this long are "stale". | `30` |
| `deadline_lead_days` | Lead time for at-risk detection and backward scheduling. | `3` |
| `default_reminder_time` | `HH:MM` used when you ask for a reminder without a time. | `"09:00"` |
| `language` | `"auto"` (reply in the invocation language), `"zh"` or `"en"`. | `"auto"` |
| `someday_resurface_days` | Someday items older than this are resurfaced by `things-organize`. | `90` |

## CLI reference

Every write the skills make goes through one CLI, `plugins/things/scripts/things`; reads use the
same CLI or its bundled read-only library (`things_lib.read`). You can run the CLI directly. Every
subcommand prints exactly one JSON object to stdout; human-readable messages go to stderr.

### Read subcommands (things.py; exit 3 when the database is unavailable)

| Subcommand | Flags | Returns in `data` |
|---|---|---|
| `inbox`, `upcoming`, `someday`, `areas`, `tags` | | list of items; `upcoming` compares start dates against `--now`, not the SQLite clock |
| `today` | | `{"items": [...], "repeating_hint": {...}}`; each item has `evening: bool`; `warnings` always carries the repeating-to-do sentence; the yellow-dot and overdue unions compare against `--now` |
| `anytime` | `--all-types` | Anytime to-dos (projects and headings only with the flag) |
| `logbook` | `--days N` (default 7) | completed and canceled items, newest first |
| `deadlines` | `--within N` | open items with a deadline, ascending; `--within` keeps `days_until_deadline <= N` |
| `overdue` | | open items whose deadline has passed |
| `projects` | `--area NAME_OR_ID` | projects, optionally within an area |
| `get ID` | | one item; to-dos include `checklist`, projects include `items` |
| `search QUERY` | `--status {open,completed,canceled,all}`, `--area X`, `--project X`, `--type {to-do,project,all}`, `--limit N`, `--no-synonyms` | substring match over title and notes, CJK exact, ASCII case-insensitive, synonyms expanded per term (a run of words equal to a multi-word synonym member, e.g. `weekly report`, is one term); `--area` also includes to-dos of projects in that area |
| `stale` | `--days N` (default `stale_days`) | Anytime to-dos without a start date and untouched for N days |
| `parse-date TEXT` | `--kind {when,deadline,auto}` | `{"when", "deadline", "reminder", "remaining", "language"}`; never touches things.py |
| `doctor` | | environment report (below); always exit 0 |
| `ping` | | sends `things:///version`; `sent` tells whether macOS has a handler |

### Write subcommands (URL scheme)

| Subcommand | Arguments and flags | Token |
|---|---|---|
| `add TITLE` | `--notes`, `--when`, `--deadline`, `--tags a,b`, `--checklist ITEM` (repeatable), `--list` / `--list-id`, `--heading` / `--heading-id`, `--completed`, `--canceled` | no |
| `add-project TITLE` | `--notes`, `--when`, `--deadline`, `--tags`, `--area` / `--area-id`, `--todo TITLE` (repeatable) | no |
| `add-json FILE` | the file is the Things `json` data array; `-` reads stdin; the only way to create headings | only for update objects |
| `update ID` | `--title`, `--notes`, `--prepend-notes`, `--append-notes`, `--when`, `--deadline`, `--tags` (replace), `--add-tags`, `--checklist` (replace), `--prepend-checklist`, `--append-checklist`, `--list` / `--list-id`, `--heading` / `--heading-id`, `--completed`, `--reopen`, `--canceled`, `--clear {when,deadline,tags,notes,checklist}` | yes |
| `complete ID...`, `cancel ID...` | one URL per id | yes |
| `move ID...` | exactly one of `--list`, `--list-id`, `--area`, `--area-id`, `--heading`, `--heading-id` (`--heading*` may be combined with one `--list*`) | yes |
| `schedule ID... --when W` | `W` must be `today`, `tomorrow`, `evening`, `anytime`, `someday`, `yyyy-mm-dd` or `yyyy-mm-dd@HH:MM`; run `parse-date` first for natural language | yes |
| `deadline ID...` | one of `--date yyyy-mm-dd`, `--push +Nd` / `+Nw`, `--clear`. Negative pushes use the `--push=-3d` form. `--push` reads the current deadline from the database; a push of an overdue deadline that still lands in the past goes through with the warning `<id>: new deadline <date> is still in the past (was <old>); use --date to pick a future date` | yes |
| `tag ID...` | `--add a,b` (keeps existing) or `--set a,b` (replaces) | yes |
| `show ID` | reveals the item in Things (foreground); no verification | no |

On macOS every write is followed by a re-read through things.py (up to `--verify-timeout`
seconds, default 3) and the envelope reports the affected `ids` and `links`. A repeated id in a
batch (`complete A A B`, or two `add-json` update objects with the same `id`) is written and
verified once. An unfilled placeholder such as `<AREA>` or `<PROJECT>` in `--list`, `--list-id`,
`--area`, `--area-id`, `--heading` or `--heading-id` (`add`, `add-project`, `update`, `move`) is
refused before anything is sent: exit 1, error `placeholder <AREA> for --list was not filled in`.

### Global flags (before or after the subcommand)

| Flag | Effect |
|---|---|
| `--dry-run` | Build and print the masked URLs, send nothing. Works without a token: a placeholder is used (masked as `***`) and the warning `auth token not found; dry-run continues with a placeholder` is added. `sent` is false, `verified` is null. |
| `--yes` | Required when a write targets more than 10 ids (`complete`/`cancel`/`schedule`/`deadline`/`tag`/`move` ids, or `add-json` update objects; duplicate ids count once), otherwise exit 4. The CLI never prompts. |
| `--verify-timeout SECONDS` | How long to wait for things.py to show the write (default 3.0). `0` disables verification. |
| `--transport {open,record,dry}` | Overrides `THINGS_SKILLS_TRANSPORT`. Default is `open` on macOS and `record` elsewhere; `open` is refused off macOS. |
| `--config PATH` | Config file (see above). |
| `--now ISO` | Freezes "now" for date parsing, verification windows and the date-relative reads (`today`, `upcoming`, `overdue`, `stale`, `logbook`, `deadlines --within`) (`YYYY-MM-DDTHH:MM` or `YYYY-MM-DD HH:MM[:SS]`, local). |
| `--project` | Treat the given ids as projects (use `update-project`) when the database cannot tell. |
| `--version` | Prints `things-skills 0.1.0`. |
| `--json-input FILE` | Reserved, not implemented yet. |

### Envelope

Every command prints one JSON object with all of these keys, always present:

```
{"ok": bool, "command": str, "data": object|list|null, "urls": [str], "sent": bool,
 "verified": bool|null, "verify_reason": str|null, "ids": [str], "links": [str],
 "warnings": [str], "error": str|null}
```

`urls` are the masked URLs that were built (`auth-token=***`). `sent` is true only when the
`open` transport returned 0 for every URL. `verified` is null for reads and dry runs.
`links` are `things:///show?id=` links you can click. Batch write commands put
`{"done": [ids], "skipped": [{"id", "title", "reason"}]}` in `data`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success, including dry runs and unverified writes on non-`open` transports |
| 1 | Usage error, malformed config, limit exceeded, invalid value, unfilled `<PLACEHOLDER>` in a list/area/heading flag, token file missing (and no token readable from the Things database) or empty, unknown id, or an unexpected internal error (reported in the envelope as `unexpected error: ...`, never as a traceback) |
| 2 | Transport failure, or `open` transport with a verification timeout |
| 3 | things.py not importable or database unavailable when the command needs a read |
| 4 | Refused: every targeted item is a repeating to-do, or `--yes` missing for a batch over 10 ids, including `add-json` payloads with more than 10 update objects |

### `things doctor` and `things parse-date`

`doctor` never prints or reports the token value (it opens the file only to tell whether it is
empty). It reports `platform`, `python`,
`transport`, `database` (`path`, `status` of `readable` / `fixture` / `unavailable`, `error`),
`token` (`path`, `present`, `empty`, `mode_ok`, `mode`), `things_py` (below),
`config` (`path`, `present`, `valid`, `missing_tags`) and `cli_version`. `missing_tags` lists
config tags Things does not have, or null when the database cannot be read.

`data.things_py` describes the things.py the CLI actually imported:

| Key | Meaning |
|---|---|
| `installed` | `true` when things.py could be imported |
| `version` | its `__version__`, normally `"1.0.1"`; null when not importable |
| `source` | `"bundled"` when the copy under `plugins/things/scripts/vendor/things/` was used (the normal case), `"system"` when `plugins/things/scripts/vendor/things/__init__.py` is absent and a system-installed things.py was imported instead, null when nothing could be imported |
| `path` | directory of the imported package, or null |

`source` is `"system"` only when `plugins/things/scripts/vendor/things/__init__.py` is absent (the
vendor directory is missing or incomplete) and a system-installed things.py was found instead, or
when another things.py was already imported into the process before the CLI ran. A bundled copy
that is present but damaged (for example a truncated `api.py`) does not fall back to the system:
it shows up as `installed: false` with `source` and `path` null.

`parse-date` converts Chinese or English date phrases to the Things vocabulary and never
touches the database. Try `things parse-date "next Monday, done by Friday" --now 2026-09-09T10:00`:
`when` becomes `2026-09-14`, `deadline` becomes `2026-09-11`, `remaining` is `done`.

## Safety model

- Every writing skill previews the exact changes and asks before writing. Only
  `things-capture` accepts "just do it" to skip the question. Confirmation is enforced
  by the skill text AND by Claude Code permissions: each skill's `allowed-tools` pre-approves only
  its own helper scripts and the read subcommands it runs, so every write subcommand (`complete`,
  `cancel`, `update`, `move`, `schedule`, `deadline`, `tag`, `add`, `add-project`, `add-json`)
  goes through the normal permission prompt. The CLI itself never asks.
- Nothing ever deletes. `cancel` and moving to Someday are the strongest actions. The URL
  scheme has no delete command, so even the live test leaves its project for you to trash.
- The token is never printed, never logged, never written to the outbox, and never passed
  through a shell. URLs are built in Python and handed to `open` as one list argument; the token
  is part of that argument, so it is visible in the local process list for the fraction of a
  second `open` runs. Every URL the CLI shows has the token masked as `***`.
- The Things database is only ever read, through a read-only SQLite connection. No network
  calls, no Things Cloud.
- `--dry-run` needs no token and sends nothing.
- A rate limiter enforces the Things limit of 250 items per 10 seconds within one invocation
  (one batch or one `add-json` payload); larger batches are refused with a message to split
  them. Separate invocations share no window.
- Tags that do not exist in Things are dropped with a warning; tags are never created.
- Capture payloads (`${TMPDIR:-/tmp}/things-capture-<epoch>.json`) and saved weekly reviews
  (`${TMPDIR:-/tmp}/things-organize-*.json`) are written with mode 0600 and hold task text; the
  helper that owns them prunes your files older than 24 hours on its next run. Delete them
  sooner if you prefer.
- `open -g` exits 0 even when Things rejects a URL, so every write on macOS is verified by
  re-reading the database and the envelope says plainly when it could not be confirmed.

## Known limitations

- Repeating to-dos cannot have `when`, `deadline`, `completed` or `canceled` changed through
  the URL scheme. The CLI detects them (templates and generated instances alike) and refuses
  before sending: they appear in `data.skipped` with a reason, and if every target is repeating
  the command exits 4.
- things.py only sees repeating instances that Things has already generated. An instance Things
  has not created yet (because the app has not run) has no row anywhere, so `things today` and
  the morning brief always carry the warning "Repeating to-dos may be missing ... Open Things
  once to refresh", plus a best-effort list of repeating templates that look due.
- Reads need Full Disk Access. Without it the CLI runs in write-only mode: writes go out,
  verification is skipped, and `verified` is false with reason `database unavailable`.
- `M/D` slash dates are month-first (`10/1` is October 1). Two-digit years are not parsed.
- Date phrases are parsed deterministically for Chinese and English only (`things parse-date`,
  `plan.py`). In any other language, write the date in English or as `yyyy-mm-dd` inside the
  request, or answer the skill's start-or-deadline question; `things-capture` also accepts
  explicit `when` / `deadline` values per candidate. Helper tables and labels are rendered in
  Chinese or English (`config.language`, else detected from the invocation); the model's own
  sentences follow the language you used.
- Open questions, answered by the live test on a Mac and then folded back into `SPEC.md`:
  1. Does `update?when=anytime` work on an existing to-do? The CLI allows it with a warning.
  2. Is `TMTask.startBucket = 1` really "This Evening"? things.py does not expose it.
  3. Does Things refuse `completed=true` on generated instances of repeating to-dos, or only on
     the hidden template? The CLI refuses both until proven otherwise.
  4. Does `move` (`update?list=...`) work on a repeating to-do? The CLI allows it.
  5. Should capture warn when an open item with the same title exists (current), or add anyway?
  6. Should every dated `when` get a reminder by default, or only when asked (current)?

## Development

Everything except the skills themselves runs on Linux without Things. The only thing to
install is pytest; the runtime has no third-party dependencies:

```
python3 -m pip install --user pytest   # or pipx, a venv, or your distribution's package
python3 -m pytest
```

The unit tests read `tests/fixtures/main.sqlite`, which is things.py's own test database
(Apache-2.0, copied unmodified from the v1.0.1 tag; see `tests/fixtures/SOURCE.txt` and the
third-party notices in `LICENSE`). Opening it creates `-shm` and `-wal` sidecars, which are
gitignored. `tests/conftest.py` points `THINGSDB` at the fixture, sets
`THINGS_SKILLS_TRANSPORT=record` as the default, and gives every test a fresh `HOME` so your real
token and config are never touched. That default is only a default (a test's own `--transport open`
still wins), so the suite also fails closed against the real `open(1)`: conftest prepends a PATH
shim named `open` that refuses with exit 97 and the message
`things-skills tests: refused to launch the real open(1)`, and wraps `subprocess.run` in-process so
any `open` argv raises `AssertionError`. Only `tests/test_live.py` restores the real PATH, HOME and
`subprocess.run`, and only when the live tests are armed (below). `tests/test_safety_guard.py`
proves both layers on every platform. The offline suite is therefore safe to run on a Mac with
Things installed: it sends nothing to Things.

things.py itself is vendored, unmodified, at `plugins/things/scripts/vendor/things/`
(`__init__.py`, `api.py`, `database.py` from the things.py 1.0.1 sdist) next to its licence
`plugins/things/scripts/vendor/LICENSE-things.py` and a short `vendor/README.md`. `read.py` puts
`plugins/things/scripts/vendor` at the front of `sys.path` before its first `import things`, so
the bundled copy wins over anything installed system-wide; if the directory is missing it falls
back to a plain `import things`. To refresh it, download the new sdist from PyPI
(`https://pypi.org/project/things.py/`), copy the three files over the old ones, update the
version in `vendor/README.md`, and rerun the tests.

Environment variables the CLI and tests honour:

| Variable | Meaning |
|---|---|
| `THINGS_SKILLS_TRANSPORT` | `open`, `record` or `dry`. `record` appends masked URLs to `.things-skills/outbox.jsonl` in the current directory. With `dry` or `record` exported, `/things:things-setup` row 2 reads "not attempted" and tells you to unset the variable; it never says to reinstall Things. |
| `THINGSDB` | Path to a Things database; things.py reads this. Point it at the fixture to run reads on Linux. When `THINGSDB` is set, post-write verification is skipped (`verify_reason`: `database overridden by THINGSDB; verification runs only against the default Things database`) and the database token fallback is disabled. |
| `THINGS_SKILLS_CONFIG` | Config file path, below the `--config` flag in precedence. |
| `THINGS_SKILLS_LIVE` | `1` enables the live tests (macOS with Things only); they also require `-m live` on the pytest command line, so a plain `pytest` never runs them. |
| `THINGS_SKILLS_LIVE_REPEATING_ID` | Optional id of an existing repeating to-do for the live repeating probes. Use one you do not mind being touched: the probe sends `completed=true` straight to Things, then attempts `completed=false` (a new instance may have been generated). |

Live tests, on a Mac with Things installed, the token file in place and Full Disk Access
granted:

```
THINGS_SKILLS_LIVE=1 python3 -m pytest tests/ -m live -s
```

`-m live` is required; with only the env var set the live tests are skipped. They create a project
named `Things Skills Test <timestamp>` (and a second one with a `(json)` suffix), exercise every
write, leave the projects completed, and print each project's `things:///show?id=` link to stderr as
it is created and the full list again at the end (also after `-x` or Ctrl-C) so you can trash them by
hand. They also print answers to the open questions above. `HANDOFF.md` is the step-by-step
first-run checklist with the expected output of each command.

## Licence

MIT, see `LICENSE`. The test fixture database is Apache-2.0 and is redistributed unmodified
with attribution.

Third-party notice: this plugin bundles things.py 1.0.1, Copyright the things.py authors
(https://github.com/thingsapi/things.py), licensed under the Apache License 2.0. The copy at
`plugins/things/scripts/vendor/things/` is unmodified; its licence text is at
`plugins/things/scripts/vendor/LICENSE-things.py`.
