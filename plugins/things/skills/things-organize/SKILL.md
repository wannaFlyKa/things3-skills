---
name: things-organize
description: Weekly review and clean-up for Things 3. Triggers - "weekly review", "organize Things", "inbox zero", "clean up my tasks", "整理", "周回顾", "清空收件箱", "整理 Things". Runs seven read-only checks (Inbox zero, Today overload, stale items, deadline sanity, tag hygiene, evening candidates, Someday resurfacing), prints a numbered dry-run proposal and applies only the numbers the user picks.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/osgate) Bash(${CLAUDE_SKILL_DIR}/scripts/review.py) Bash(${CLAUDE_SKILL_DIR}/scripts/review.py *) Bash(${CLAUDE_SKILL_DIR}/scripts/things get *) Bash(${CLAUDE_SKILL_DIR}/scripts/things search *)
---
!`${CLAUDE_SKILL_DIR}/scripts/osgate`

# things-organize

Runtime compatibility: Claude Code expands `${CLAUDE_SKILL_DIR}` automatically. In Codex, resolve it to the
absolute directory containing this `SKILL.md`; run `scripts/osgate` from that directory once before continuing.

If the line above reads "Things skills run only on macOS", tell the user this plugin needs a Mac and stop; run nothing else.

Weekly review for Things 3: seven read-only checks, one numbered proposal, writes only for the numbers
the user picks. Never pass `--yes`; never delete anything (`cancel` and moving to Someday are the
strongest actions); never print, log or ask for the auth token. All shell work goes through
`${CLAUDE_SKILL_DIR}/scripts/review.py` (read-only helper) and `${CLAUDE_SKILL_DIR}/scripts/things` (CLI).
Pre-approved: the helper and the read subcommands `get` / `search`. The write subcommands the helper prints
(`schedule`, `move`, `deadline`, `tag`, `cancel`, `complete`, `update`, `add`) are NOT pre-approved in Claude Code;
Codex uses its normal approval and sandbox policy. This is only a second safety net: always require the skill's
explicit user confirmation.

## Reply language
Pass `--lang auto --text "<the user's words>"` to the helper: it applies `config.language` and otherwise detects
the language from the invocation (any Chinese character -> `zh`, else `en`). Pass `--lang zh` / `--lang en` only
when the user explicitly asks for a language. Never translate item titles or notes; quote them exactly as Things
stores them.

## Step 1 - pick the scope
From the invocation choose ONE: `inbox` (inbox zero / 清空收件箱), `today` (Today overload / Today 超载),
`all` (default: weekly review / 周回顾 / 整理), or an area or project name exactly as the user said it
(matched case-insensitively against Things). Unknown names make the helper exit 1 and list the valid ones.

## Step 2 - build the dry-run proposal (reads only, nothing is written)
    ${CLAUDE_SKILL_DIR}/scripts/review.py --scope <scope> --lang auto --text "<the user's words>" --markdown
- Exit 3 (`ok: false`, "database unavailable"): reads need Full Disk Access; point to `/things:things-setup`, stop.
- Exit 1: show `error` (bad scope, bad config), stop.
- Otherwise show the Markdown verbatim. It IS the preview: each proposal has a number, the check, the item
  title with its `things:///show?id=` link, where it lives (projects are marked `· project`), the action in
  words, the exact wrapper command and lettered alternatives (`3b`, `3c`). Keep the trailing `saved:` path for
  Step 4 and repeat the `- ` warning lines (repeating hint, skipped repeating to-dos, empty tag vocabulary,
  `when=anytime` note, printed whenever a default command uses it).

| # | check | what it proposes |
|---|-------|------------------|
| 1 | Inbox zero | `update ID --list <project/area> [--when W] [--deadline D] [--add-tags T]` from `config.routing_hints`, dates found in the text and `config.tags`; items that read as under 2 minutes (call / email / reply / 发 / 回 / 打电话, short title) are flagged DO NOW with alt `complete ID` |
| 2 | Today overload | more than `config.today_cap` open to-dos in Today: `schedule ID --when tomorrow\|anytime\|someday`; items due within `config.deadline_lead_days` and repeating items stay |
| 3 | Stale | `stale --days config.stale_days` items with no deadline: `schedule ID --when someday`; alt `cancel ID`; alt a 15-minute `add "Decide: <title>" --when today` |
| 4 | Deadline sanity | past deadline: `deadline ID --clear` (alts `complete`, `cancel`, `--date <YYYY-MM-DD>`); deadline before start: `schedule` earlier (alt move the deadline to the start); due within lead days with no start: `schedule ID --when today` |
| 5 | Tag hygiene | open items with no area and no project: `move ID --area/--list ...` via routing hints; tags outside `config.tags`: `tag ID --set <kept>` or `update ID --clear tags` |
| 6 | Evening | gym / 健身 / calls home / 给家里打电话 / 家里的事 / groceries: `schedule ID --when evening` for Today items, otherwise `<date>@18:00` with the 18:00 reminder noted |
| 7 | Someday resurfacing | Someday items untouched over `config.someday_resurface_days` (default 90): `schedule ID --when anytime`; alt `cancel ID` |

## Step 3 - ask which numbers to apply (always; "just do it" / "直接" only means `all` AFTER the report)
One short question. Accepted answers: `y` / `yes` / `好` / `确认` (apply every default option, the same as
`all` / `全部`), numbers like `1,3`, `2b`, `1-4`, or `none` / `不用`. A command that still contains `<AREA>` or
`<YYYY-MM-DD>` needs a value: use the area or date the user named, else ask.
Stop here when the answer is `none` or empty; nothing has been written.

## Step 4 - batch and run
Normalise the reply to the accepted form first: numbers, ranges like `1-4`, letters like `2b`, separated by commas
("1 and 3" / "1和3" / "第1、3条" -> `1,3`); `all` / `none`; `yes` / `好` = `all`. Then:
    ${CLAUDE_SKILL_DIR}/scripts/review.py --apply "<normalised answer>" --from <saved path> --markdown
Exit 1 = the selection could not be read (or the saved file is malformed): show `error` and ask again; nothing has
been written. It prints the exact wrapper commands, several ids per command where the CLI accepts them (at most 10
ids each, so `--yes` is never needed). Omit `--from` to use the newest saved review (only a file this user
created is trusted; otherwise it refuses and you pass `--from` explicitly). Fill in any placeholder,
then run each printed command unchanged, one at a time, in order (the CLI refuses more than 250 items in one
command; running the commands one at a time keeps Things' 250-per-10-seconds limit safe).
Every command has the form `${CLAUDE_SKILL_DIR}/scripts/things <schedule|move|deadline|tag|cancel|complete|update|add> ...`
(printed with the absolute path of this skill's `scripts/` directory); the helper refuses any other verb.

## Step 5 - report from the envelopes
Read each JSON envelope: `ok`, `data.done`, `data.skipped`, `verified`, `verify_reason`, `links`, `warnings`, `error`.
- One line per proposal number: done / skipped / failed, then its `things:///show?id=` link from `links`.
- `data.skipped` entries are repeating to-dos: quote the `reason` and say the change has to be made in
  Things. Exit 4 means every id in that command was repeating and nothing was sent.
- Print every `warnings` entry verbatim (dropped tags, `when=anytime is undocumented ...`, `unknown id`).
- `verified: false`: say plainly "Not confirmed by things.py: <verify_reason>", note the change may still
  have landed, and ask the user to check the link. Exit 2 is a transport failure or timeout: show `error`,
  do not retry silently.
- `ok: false`: quote `error`, continue with the remaining commands, list the failures at the end.
- `verified: null` with `sent: false` (dry run, or `THINGS_SKILLS_TRANSPORT=dry`): nothing was sent; show `urls`
  and say no change was made.
Offer to re-run Step 2 with the same scope to confirm the new state.

## Best practices (from the build brief)
- Inbox is for capture only; nothing should live there more than a week.
- Someday is a parking lot, not a graveyard: resurface anything older than 90 days.
- Today is a promise for today, not a wish list: cap it.
