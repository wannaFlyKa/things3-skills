# HANDOFF: first run on a Mac

A step-by-step checklist for the first run of things3-skills on a Mac, with the expected output of
every command. The code was developed and unit-tested on Linux without Things 3; these five steps
are what remains once the repository is on a Mac. They are in order; do not skip ahead. Every
command is meant to be run from the repository root unless it starts with `/`, which is a Claude
Code slash command, or `$`, which names a Codex skill.

Before you start, clone the repository and enter it:

```
git clone https://github.com/wannaFlyKa/things3-skills ~/Developer/things3-skills
cd ~/Developer/things3-skills
```

Adjust the destination as you like; every later step assumes you are in that directory.

Expected: `ls` shows `plugins/`, `tests/`, `docs/`, `README.md`, `HANDOFF.md`, `LICENSE`,
`CHANGELOG.md`, `SPEC.md`, `pytest.ini`, `.gitignore`, `.agents/`, and `.claude-plugin/`.
`ls plugins/things/scripts/vendor/things` shows `__init__.py`, `api.py` and `database.py`: that is
things.py 1.0.1, bundled, so there is nothing to `pip install` on the Mac.
`ls -l tests/fixtures/main.sqlite` shows 180224 bytes. `git status` is clean (sidecar files such
as `main.sqlite-wal`, `__pycache__/` and `.things-skills/` may appear later; they are gitignored
and harmless).

Throughout: the CLI is `python3 plugins/things/scripts/things`. It prints one JSON object per
call. When something is wrong, the `error` field says what, and stderr repeats it prefixed
with `error:`.

## Step 1: create the token file

In Things: Settings → General → Enable Things URLs → Manage → copy the token to the clipboard.
Then, without pasting the token anywhere else (not into Codex or Claude Code, and not into shell history):

```
mkdir -p ~/.config/things-skills
chmod 700 ~/.config/things-skills
( umask 077; pbpaste > ~/.config/things-skills/auth-token )
chmod 600 ~/.config/things-skills/auth-token
ls -l ~/.config/things-skills/auth-token
wc -c ~/.config/things-skills/auth-token
```

Expected: the `ls -l` line starts with `-rw-------`, and `wc -c` prints a number above 0
(the token is a short ASCII string; a trailing newline from pbpaste is fine).

Rules the CLI applies to this file: the first non-blank line is the token, trailing
whitespace is stripped, a UTF-8 BOM is ignored. If the file is world- or group-readable the
CLI warns once per process and keeps going. If the file is missing, the CLI falls back to the
token stored in the Things database when it can read that database (step 2) and prints
`note: using auth token from the Things database; create ~/.config/things-skills/auth-token to
silence this` to stderr; if neither source yields a token, or the file exists but is empty, every
token-needing command exits 1 (except with `--dry-run`, which uses a placeholder). The file makes
the token source explicit and works without Full Disk Access.

If it fails: `wc -c` prints 0 when the clipboard was empty; copy the token again and rerun the
`pbpaste` line. If `ls -l` shows anything other than `-rw-------`, run
`chmod 600 ~/.config/things-skills/auth-token`. Never `cat` the file in a shared screen, and
never paste the token into an agent conversation; the skills are written to never ask for it.

## Step 2: grant Full Disk Access to the terminal app

Reads go through things.py, which opens the Things database under
`~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/`. macOS blocks that unless
the app running the process has Full Disk Access.

1. System Settings → Privacy & Security → Full Disk Access.
2. Click `+`, add the app you run Codex or Claude Code from (ChatGPT/Codex desktop, Terminal,
   iTerm2, Warp, VS Code, Cursor, or the Claude desktop app), and make sure its toggle is on.
3. Quit that app completely (Cmd-Q, not just the window) and reopen it. The permission only
   applies to processes started after the grant.
4. Open Things 3 at least once so the database exists.

Then check:

```
python3 plugins/things/scripts/things inbox
```

Expected: `"ok": true` and a `data` list (possibly empty), exit 0.

If it fails: exit 3 with `unable to open database file` means Full Disk Access is still missing
for this app, or you did not restart it, or Things has never been opened on this Mac. If you
use several terminal apps, each needs its own grant. Writes work without this step, but the CLI
then runs in write-only mode: `verified` is false with reason `database unavailable`, and
`things-close`, `things-organize`, `things-deadlines` and `things-today` cannot read anything.

## Step 3: run the doctor and fix anything red

```
python3 plugins/things/scripts/things doctor
python3 plugins/things/scripts/things ping
```

Expected in the `doctor` output (all inside `data`):

| Field | Expected |
|---|---|
| `platform` | `"Darwin"` |
| `transport` | `"open"` |
| `database.status` | `"readable"` (and `database.error` null) |
| `token.present` / `token.empty` / `token.mode_ok` | `true` / `false` / `true` (`token.mode` is `"0600"`) |
| `things_py.installed` / `things_py.version` / `things_py.source` | `true` / `"1.0.1"` / `"bundled"` (`things_py.path` ends in `plugins/things/scripts/vendor/things`) |
| `config.present` / `config.valid` | `true` / `true` (`present` is `false` until step 4 creates the file; that is fine here) |
| `config.missing_tags` | `[]` once the config exists (null while the database is unreadable) |
| `cli_version` | `"0.2.0"` |

Expected in the `ping` output: `"sent": true`, exit 0. That means macOS found a handler for
`things:` URLs. Things may briefly react; `ping` sends only `things:///version`.

If a field is off:

- `database.status` `unavailable`: back to step 2.
- `token.present` false or `token.empty` true: back to step 1. `token.mode_ok` false: `chmod 600`.
- `things_py.installed` false (`source` and `path` null): the bundled copy at
  `plugins/things/scripts/vendor/things/` is damaged or absent and nothing else could be imported.
  `things_py.source` `"system"`: `vendor/things/__init__.py` is missing, so a things.py installed
  elsewhere on the Mac was used instead of the bundled one. Either way, clone the repository
  again; `ls plugins/things/scripts/vendor/things` must list the three `.py` files.
- `config.valid` false: the file at `config.path` is not valid JSON; fix or move it.
- `ping` exit 2 or `"sent": false` with `transport` `"open"`: Things is not installed, or has
  never been opened. Install from the Mac App Store, open it once, rerun. With `transport`
  `"dry"` or `"record"` nothing was sent on purpose: unset `THINGS_SKILLS_TRANSPORT` and rerun.

A quick token-free smoke test that sends nothing:

```
python3 plugins/things/scripts/things add "Buy milk" --when tomorrow --dry-run
python3 plugins/things/scripts/things complete SOMEID --dry-run
```

Both exit 0; the second shows `auth-token=***` in `urls` and, if the token file is still
missing, the warning `auth token not found; dry-run continues with a placeholder`.

## Step 4: install the plugin and run things-setup

For Codex, register this clone as a local marketplace and install the plugin:

```
codex plugin marketplace add ~/Developer/things3-skills
codex plugin add things@things3-skills
```

Start a new Codex chat after installation, then run `$things-setup` or say "check Things". The new
chat is important because an existing chat does not reload newly installed skills.

For Claude Code, started from the app you granted access to in step 2:

```
/plugin marketplace add ~/Developer/things3-skills
/plugin install things@things3-skills
/things:things-setup
```

Claude Code alternative without the marketplace: copy the six folders from `plugins/things/skills/` into
`~/.claude/skills/` and `plugins/things/scripts/` to `~/.claude/scripts/` (the skill wrappers
look for the shared CLI three directory levels up), then invoke `/things-setup`. In that layout
`setup_check.py` cannot find `plugins/things/config.example.json`, so it writes the built-in
defaults to `~/.config/things-skills/config.json` instead (edit `areas`, `routing_hints` and
`tags` afterwards), and the slash names lose the `things:` prefix (`/things-setup`,
`/things-today`, ...), so the cross-references inside the skills point at names that do not
exist there. The marketplace route avoids both problems.

Expected from `things-setup`: a table with seven rows, all ✅: macOS, Things installed and
opened once, things.py importable (its detail reads `bundled 1.0.1`), database readable, token
file present, config file present, config tags exist in Things. On the first run the config row
says the helper created `~/.config/things-skills/config.json` from `config.example.json`, and
the tags row is ❌ with "example tags not in Things": that is expected, the example vocabulary
is a placeholder. If step 1 was skipped but the database is readable (step 2), writes already
work through the token stored in the database; the token row still asks for the file, which
makes the token explicit.

Then edit `~/.config/things-skills/config.json`: set `areas` to your real area names, adapt
`routing_hints` and `synonyms` to your vocabulary, and set `tags` to tags that exist in Things
(or create the missing ones in Things; the skills never create tags). Rerun `$things-setup` in Codex
or `/things:things-setup` in Claude Code until every row is green, then try `$things-today` or
`/things:things-today` as the first real skill.

If a row is ❌ the table gives the exact fix; the rows map to steps 1 to 3 above (the things.py
row means the vendored copy is damaged: clone the repository again). If the plugin does not
show up in Codex, run `codex plugin list` and confirm that `things@things3-skills` is installed and
enabled; reinstall with `codex plugin add things@things3-skills`, then start a new chat. In Claude
Code, run `/plugin` to check that the marketplace `things3-skills` is listed and the plugin `things`
is enabled, then restart Claude Code once.

## Step 5: run the live tests and trash the test projects

```
THINGS_SKILLS_LIVE=1 python3 -m pytest tests/ -m live -s
```

`-m live` is required; with only the env var set the live tests are skipped. A plain
`python3 -m pytest` runs the offline suite, which sends nothing to Things even on this Mac
(`tests/conftest.py` blocks the real `open(1)`).

Optional: set `THINGS_SKILLS_LIVE_REPEATING_ID=<uuid>` to the id of an existing repeating to-do
to also probe open questions 3 and 8. Only do this with a repeating to-do you do not mind being
touched: the probe sends `completed=true` straight to Things to see whether Things refuses it,
attempts `completed=false` afterwards when Things accepted it (a new instance may have been
generated; check by hand), then moves the item into the test project and back. Without the
variable that one test is skipped.

What the run does: `doctor` and `ping` sanity, then `add-project`, `add-json` with a heading and
a to-do with a checklist, `add` into the project, `update` title, `schedule`, `deadline` set,
push and clear, `tag`, `complete` every child and then the projects, and finally the probes for
the open questions. Every write is verified by re-reading the database through things.py.

Expected: all tests pass (one skipped without the repeating id). Each project's link is printed to
stderr the moment it is created (`[live] created things:///show?id=...`), and at the end a block like:

```
[live] trash these by hand (the URL scheme cannot delete): things:///show?id=... things:///show?id=...

Open-question answers:
  K.extra: update?deadline= clears a deadline: yes
  K.1 update?when=anytime on an existing to-do: WORKS ...
  K.2 TMTask.startBucket = 1 means This Evening: CONFIRMED ...
  K.3 ...   (only with THINGS_SKILLS_LIVE_REPEATING_ID)
  K.8 ...   (only with THINGS_SKILLS_LIVE_REPEATING_ID)
```

The run creates a project named `Things Skills Test <timestamp>` and a second one with a `(json)`
suffix, leaves both completed (they sit in the Logbook), and prints their `things:///show?id=`
links. Click each link and trash the project by hand: the URL scheme has no delete command, so
neither the CLI nor the tests can do it for you.

The "Open-question answers" lines answer `SPEC.md` section K questions 1, 2, 3 and 8. If one of
them contradicts what the spec assumes (K.1 fails, K.2 is not confirmed, K.3 shows instances
completing fine), open an issue with those lines so the spec and the affected skills can be
updated.

If it fails: `test_00_doctor_and_ping` failing points at steps 1 to 3. A `verified` assertion
with reason `timeout after 3.0s` means Things did not show the item within 3 seconds; rerun
with Things already open in the foreground, or widen the window by adding `--verify-timeout 6`
to the argument list in the `cli()` helper of `tests/test_live.py`. `test_07` skips when your Things
has no tags at all. If a test fails midway (or you stop it with `-x` or Ctrl-C), the projects it
already created still exist; their links were printed to stderr as they were created and are
printed again at module teardown, or search Things for `Things Skills Test`.
