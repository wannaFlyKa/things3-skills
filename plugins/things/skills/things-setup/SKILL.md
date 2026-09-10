---
name: things-setup
description: Use when the user says "set up Things", "check Things", "things doctor", "配置 Things", "检查 Things" or "Things 设置". Checks macOS, Things, things.py, database access, the auth token file, the config file and its tag vocabulary, then prints a one-screen ✅/❌ status table with the exact fix for every failed row.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/osgate) Bash(${CLAUDE_SKILL_DIR}/scripts/setup_check.py) Bash(${CLAUDE_SKILL_DIR}/scripts/setup_check.py *) Bash(${CLAUDE_SKILL_DIR}/scripts/things doctor) Bash(${CLAUDE_SKILL_DIR}/scripts/things doctor *) Bash(${CLAUDE_SKILL_DIR}/scripts/things ping) Bash(${CLAUDE_SKILL_DIR}/scripts/things ping *)
---
!`${CLAUDE_SKILL_DIR}/scripts/osgate`

# things-setup

If the line above reads "Things skills run only on macOS", tell the user this plugin needs a Mac and stop; run nothing else.

Health check for the things-skills plugin. It sends NO writes to Things and never writes the `record` outbox. The
only file it may create is `~/.config/things-skills/config.json` (copied from `config.example.json` when missing).
Pre-approved: `${CLAUDE_SKILL_DIR}/scripts/setup_check.py` and the read subcommands `doctor` and `ping` of
`${CLAUDE_SKILL_DIR}/scripts/things`; nothing else, so do not use `cat`, `python3 -c`, pipes or the Write tool.

## Reply language
- Pass `--lang auto --text "<the user's words>"`: the helper applies `config.language` and otherwise detects the
  language from the invocation (any Chinese character -> `zh`, else `en`). Pass `--lang zh` or `--lang en` only when
  the user explicitly asks for a specific language.
- Never translate tag names, area names, titles or paths; quote them exactly as the helper prints them.

## Step 1 - run the check (one command covers all seven rows)
```
${CLAUDE_SKILL_DIR}/scripts/setup_check.py --markdown --lang auto --text "<the user's words>"
```
The helper runs `${CLAUDE_SKILL_DIR}/scripts/things doctor`, `ping`, `tags` and `areas`, performs the config
copy (row 6) and prints the table, a "Next steps" list (numbered for failed rows, a bullet for advice on a passed
row) and "Notes". Print its Markdown verbatim (it is one screen), then add at most three sentences of your own.
Drop `--markdown` only when you need a field: `ok`, `steps[].{id,ok,detail,fix}`, `repo_root`, `terminal_app`,
`config_path`, `config_action` (`present`|`created`|`missing`|`error: <reason>`), `things.tags`, `things.areas`,
`notes`, `doctor`, `ping`.
If the helper itself fails, fall back to `${CLAUDE_SKILL_DIR}/scripts/things doctor` and
`${CLAUDE_SKILL_DIR}/scripts/things ping` and read the fields listed under each row below.

## Step 2 - the seven rows and what to say for each ❌
1. **macOS** - `setup_check` reports the platform (`data.platform`). ❌: say the skills need a Mac and stop. The gate
   line at the top only prints a warning; it cannot abort the skill.
2. **Things installed and opened once** - `ping` envelope `sent` must be `true`. ❌ with a detail that names transport
   `dry` or `record`: nothing was sent on purpose; tell the user to unset `THINGS_SKILLS_TRANSPORT` and rerun, NOT to
   reinstall Things. ❌ with transport `open` and a delivery error (`ping` exit 2): install Things 3 from the Mac App
   Store, open it once, rerun. ❌ reading "not checked" because the config file is invalid (`ping` exit 1): fix row 6
   first; never suggest reinstalling Things. Any other ❌ quotes a CLI error: relay it and rerun after the user fixes it.
   When `things doctor` itself fails, rows 3-7 read "not checked": relay the doctor error from Notes first.
3. **things.py importable** - `doctor` `data.things_py.installed`; `data.things_py.source` is normally
   `bundled` because things.py ships inside the plugin (`scripts/vendor/`), so there is nothing to install
   by hand. ✅ reads `bundled 1.0.1` (Chinese: `内置 1.0.1`). If the detail instead reads `system 1.0.1`
   (Chinese: `系统 1.0.1`) the row is green but the bundled copy under `scripts/vendor/` was not found and a
   system-installed things.py was used instead; mention that and relay the same reinstall/update fix below.
   ❌ means the bundled copy is missing or damaged: relay the row's fix word for word, reinstall or update
   the plugin (`/plugin update things@things3-skills` in Claude Code, or re-clone the repository), then
   rerun the check. Never suggest a package installer.
4. **Database readable** - `data.database.status == "readable"`. ❌: relay the Full Disk Access steps from the
   fix, naming the terminal app the helper detected (System Settings -> Privacy & Security -> Full Disk Access
   -> add the app -> quit and reopen it). Say plainly that writes still work but cannot be verified until then
   (write-only mode). If `things_py` is ❌ the row reads "not checked"; fix row 3 first.
5. **Token file** - `data.token.present`, not `empty`, `mode_ok` (0600). ❌: explain where the token comes
   from (Things -> Settings -> General -> Enable Things URLs -> Manage) and the exact path
   `~/.config/things-skills/auth-token`. The user saves it themselves (the fix shows a `pbpaste` one-liner or
   `chmod 600`). If row 4 is green, say that writes already work through the token stored in the Things
   database and the file only makes it explicit. NEVER ask the user to paste the token into the chat; never
   read or print the file.
6. **Config file** - `data.config.present` and `valid`. `config_action: created` means the helper just copied
   `config.example.json`; say so and suggest editing `areas`, `routing_hints` and `tags` to match their
   Things. Invalid JSON: quote the error, ask the user to fix or move the file, rerun. `config_action: error: ...`
   means the copy itself failed (permissions or a read-only home): relay row 6's fix, i.e. copy
   `config.example.json` to the printed path by hand, then rerun.
7. **Config tags exist in Things** - `data.config.missing_tags`. ❌ right after `config_action: created` (or when the
   detail says "example tags", i.e. `config.tags` still equals the `config.example.json` vocabulary): those are the
   example vocabulary; ask the user to edit `config.tags` in the printed file. ❌ "missing in Things": these are the
   user's own tag names; list them exactly and ask the user to create them in Things. Never create tags. `null` means
   unchecked because the database is unavailable. When row 6 is invalid, row 7 reads "not checked"; fix the config first.

## Step 3 - rerun to verify
After the user reports a fix, run the same command again and show the new table. Stop when every row is ✅
or the user stops. Once green, suggest `/things:things-today` as the first real skill to try.

## Envelope fields (when calling the CLI directly)
`${CLAUDE_SKILL_DIR}/scripts/things doctor` and `${CLAUDE_SKILL_DIR}/scripts/things ping` print one JSON
object: read `ok`, `data`, `sent`, `warnings`, `error`; print every `warnings` entry. `verified`, `verify_reason`,
`ids` and `links` are empty or `null` here because this skill never writes to Things; `doctor` has `urls: []` and
`ping` has `urls: ["things:///version"]`, the single read-only URL it sends. Should any envelope ever show
`verified: false`, say so plainly and quote `verify_reason` word for word. Never run `add`, `add-project`, `add-json`,
`update`, `complete`, `cancel`, `move`, `schedule`, `deadline` or `tag` from this skill; none of them is pre-approved.

## Rules
- Nothing here deletes anything, creates tags or writes to Things. Do not "fix" a row by running installers or
  `chmod` yourself; the user runs the printed commands in their own terminal.
- Never print, log or ask for the token. Do not read the token file or the config file; use the helper's JSON.
- The writing skills follow preview -> confirm -> write -> verify -> links. Here the only write is the local config
  copy, which the helper does on its own and reports after the fact (`config_action: created`).

## Best practices (one line each, cite when relevant)
- Keep the tag vocabulary small (under 10); tags are for context (`@calls`, `@errands`, `@deep`), areas for life domains.
- `when` is when you intend to start; `deadline` is the external hard date. Never set a deadline that is really a start.
