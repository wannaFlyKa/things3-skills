---
name: things-today
description: Use for "morning brief", "what's on today", "today's plan", 今天要做什么, 今日安排, 早报. Prints a short morning brief (Today, This Evening, overdue, deadlines within 7 days, Inbox count) plus an Obsidian daily-note checklist with Things links.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/osgate) Bash(${CLAUDE_SKILL_DIR}/scripts/brief.py) Bash(${CLAUDE_SKILL_DIR}/scripts/brief.py *) Bash(${CLAUDE_SKILL_DIR}/scripts/things today) Bash(${CLAUDE_SKILL_DIR}/scripts/things today *) Bash(${CLAUDE_SKILL_DIR}/scripts/things overdue) Bash(${CLAUDE_SKILL_DIR}/scripts/things overdue *) Bash(${CLAUDE_SKILL_DIR}/scripts/things deadlines) Bash(${CLAUDE_SKILL_DIR}/scripts/things deadlines *) Bash(${CLAUDE_SKILL_DIR}/scripts/things inbox) Bash(${CLAUDE_SKILL_DIR}/scripts/things inbox *)
---
!`${CLAUDE_SKILL_DIR}/scripts/osgate`

# things-today

Runtime compatibility: Claude Code expands `${CLAUDE_SKILL_DIR}` automatically. In Codex, resolve it to the
absolute directory containing this `SKILL.md`; run `scripts/osgate` from that directory once before continuing.

If the line above reads "Things skills run only on macOS", tell the user this plugin needs a Mac and stop; run nothing else.

Read-only morning brief. Nothing in this skill writes to Things.
Pre-approved: `${CLAUDE_SKILL_DIR}/scripts/brief.py` and the read subcommands `today`, `overdue`, `deadlines`, `inbox` of
`${CLAUDE_SKILL_DIR}/scripts/things`; no write subcommand is. Do all work through the helper below, never `cat`,
`python3 -c`, pipes or the Write tool.

## Steps
1. Do not pick the language yourself: the helper applies `config.language` and otherwise detects it from the invocation
   (any Chinese character -> `zh`, else `en`, so mixed input gets `zh`). Titles and notes are never translated.
2. Run the helper. It calls `things today`, `things overdue`, `things deadlines --within 7` and `things inbox`, and reads
   `today_cap` from the config:
       ${CLAUDE_SKILL_DIR}/scripts/brief.py --lang auto --text '<the user's words, single quotes removed>' --markdown
   Pass `--lang zh` or `--lang en` instead only when the user explicitly asks for a specific language.
3. Print the Markdown exactly as returned: do not reorder, translate, summarise or drop lines. It already contains
   - Today (count; evening items marked), This Evening, "Repeating, probably due" (only when non-empty), Overdue,
     Deadlines within 7 days, Inbox count, each item with its `things:///show?id=` link;
   - the mandatory sentence about repeating to-dos (English or Chinese, from the CLI's `today` warning);
   - a notice when Today exceeds `today_cap`, pointing to `/things:things-organize today`;
   - ONE fenced block at the very end: the Obsidian daily-note checklist, one line per Today item in the form
     `- [ ] <title> ([Things](things:///show?id=<id>))` (empty when Today is empty). Leave it as the last thing in your reply.
4. If the helper prints JSON with `"ok": false`, quote its `error` plainly and stop. Exit 3 means things.py could not read
   the database: suggest `/things:things-setup` (Full Disk Access for the terminal app).
5. You may add at most one sentence of your own (for example which item to start with). Keep the reply short.

## Envelope fields, if you ever call the CLI directly
`${CLAUDE_SKILL_DIR}/scripts/things today` returns `ok`, `data.items` (each with `evening`, `deadline`,
`days_until_deadline`, `repeating`, `link`), `data.repeating_hint.due`, `warnings` (always includes the repeating sentence)
and `error`. `urls`, `verified`, `verify_reason` and `links` describe writes; this skill makes none, so they stay empty or null.

## Hand-offs (do not do these here)
- Today over the cap -> `/things:things-organize today`. Overdue or at-risk deadlines -> `/things:things-deadlines`.
- "Done with X" -> `/things:things-close`. A new task -> `/things:things-capture`.

## Rules
- Reply in the helper's language (`config.language`, else the invocation language); never translate titles or notes.
- Today is a promise for today, not a wish list: respect `today_cap` and say so when it is exceeded.
- No writes, no deletes, never print or ask for the auth token.
