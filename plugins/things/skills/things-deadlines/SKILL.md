---
name: things-deadlines
description: Use for "deadlines", "overdue", "due this week", "push deadline", "DDL", 逾期, 本周到期, 推后三天, 截止日期. Lists overdue and upcoming deadlines grouped by area, flags at-risk items, proposes backward scheduling, and pushes, sets or clears deadlines after confirmation.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/osgate) Bash(${CLAUDE_SKILL_DIR}/scripts/ddl_report.py) Bash(${CLAUDE_SKILL_DIR}/scripts/ddl_report.py *) Bash(${CLAUDE_SKILL_DIR}/scripts/things parse-date *) Bash(${CLAUDE_SKILL_DIR}/scripts/things search *)
---
!`${CLAUDE_SKILL_DIR}/scripts/osgate`

# things-deadlines

If the line above reads "Things skills run only on macOS", tell the user this plugin needs a Mac and stop; run nothing else.

Deadline control for Things 3. Reads go through the shared CLI; writes happen only after the user confirms.
Pre-approved: `${CLAUDE_SKILL_DIR}/scripts/ddl_report.py` and the read subcommands `parse-date`, `search` of
`${CLAUDE_SKILL_DIR}/scripts/things`. The write subcommands `schedule` and `deadline` are NOT pre-approved: Claude Code
asks the user's permission for each, which is the intended second safety net. Never call `cat`, `python3 -c`, pipes or the
Write tool.

## Language
Reply in the helper's language: pass `--lang auto --text "<the user's words>"` and it applies `config.language`, else the
invocation language (any Chinese character -> `zh`). Pass `--lang zh` / `--lang en` only when the user explicitly asks for a
language. Never translate task titles or notes.

## Step 1: report (default; also for 逾期, 本周到期, "what's overdue", "due this week")
    ${CLAUDE_SKILL_DIR}/scripts/ddl_report.py --lang auto --text "<the user's words>" --markdown
Print the Markdown as returned. It groups items into Overdue, Due today, Due within 7 days, Due in 8-30 days, each grouped
by area (falling back to the project, else "No area"), one line per item with start date, deadline, days left and a
`things:///show?id=` link. At-risk items are bold with the reason (deadline within `deadline_lead_days` and no start date,
or start date after the deadline). The numbered table at the end proposes backward scheduling: `when = deadline - lead days`
(never earlier than today) and carries the exact `schedule` command for each row.
For "due this week" / 本周到期 you may show only the Overdue, Due today and Due within 7 days sections.
If the helper prints JSON with `"ok": false`, quote its `error` and stop (exit 3 = database unreadable; suggest `/things:things-setup`).

## Step 2: offer the proposals
If the report contains the heading "## No at-risk items." / "## 没有有风险的任务。" (it is followed by an "Other actions"
line and possibly warnings) there is nothing to apply: stop after the report and ask no question; run push / set / clear
only on an explicit request.
Otherwise ask ONE short question: which numbers to apply (`1,3`, `all` / `全部`, `y` / `好` / `确认`, or none) and whether to
add the reminder variant (`@HH:MM`, from config `default_reminder_time`; the helper prints it). Rows marked "repeating" have
no command: tell the user those must be changed in Things.

## Step 3: apply the chosen rows
The numbered table IS the preview and the Step 2 answer IS the confirmation: run the picked rows' commands verbatim (they
carry the absolute path of this skill's wrapper) without `--dry-run`, or merge rows that share a date:
    ${CLAUDE_SKILL_DIR}/scripts/things schedule <id> --when YYYY-MM-DD
    ${CLAUDE_SKILL_DIR}/scripts/things schedule <id1> <id2> --when YYYY-MM-DD@09:00
Then continue at write-protocol step 4 (envelope, verify, links). The full preview -> confirm -> write protocol applies to
the explicit push / set / clear requests below, which have no prior table.

## Push, set, clear (explicit requests)
- push: "push <id> +3d", "推后三天", "postpone two weeks". Convert the words first:
      ${CLAUDE_SKILL_DIR}/scripts/ddl_report.py --push-spec "<the user's words>"  -> {"ok": true, "spec": "+3d", "flag": "--push=+3d"}
      ${CLAUDE_SKILL_DIR}/scripts/things deadline <id> --push +3d
  `+Nd` / `+Nw` move the current deadline forward. 提前 / "earlier" gives a negative offset, which MUST be written
  with `=`: `${CLAUDE_SKILL_DIR}/scripts/things deadline <id> --push=-3d` (a bare `--push -3d` fails with
  `argument --push: expected one argument`). Pasting the helper's `flag` value as printed is always safe. English "push
  back by N days" means later (`+Nd`); only 提前 / "earlier" / "bring forward" / "sooner" give a negative offset.
- set: "set <id> to 下周五", "deadline next Friday". Resolve the date first, then set it:
      ${CLAUDE_SKILL_DIR}/scripts/things parse-date "下周五" --kind deadline        -> data.deadline = YYYY-MM-DD
      ${CLAUDE_SKILL_DIR}/scripts/things deadline <id> --date YYYY-MM-DD
- clear: "clear <id>", 清除截止日期:
      ${CLAUDE_SKILL_DIR}/scripts/things deadline <id> --clear
If the user names a task instead of an id: `${CLAUDE_SKILL_DIR}/scripts/things search "<words>" --status open`, show the
matches with their deadlines, and confirm which one before writing.

## Write protocol: preview -> confirm -> write -> verify -> links
1. Preview: run the exact write command with `--dry-run`. Show a compact Markdown table: title, current deadline / start,
   new value. The envelope's `urls` are masked (`auth-token=***`); never try to unmask them.
2. Confirm with one short question. Accepted: `y`, `yes`, `好`, `确认`, numbers like `1,3`, `all`, `全部`. This skill never
   uses `--yes` and never skips confirmation.
3. Write: re-run the same command without `--dry-run`.
4. Read the envelope: `ok` (false -> quote `error`, stop); `data.done` and `data.skipped` (skipped = repeating to-dos: the URL
   scheme cannot change their when/deadline; say so); `verified`; `verify_reason`; `links`; `warnings`. When `verified` is
   `null` and `sent` is false (dry run, or `THINGS_SKILLS_TRANSPORT=dry`) nothing was sent: show `urls` and say no change was made.
5. Report one line per item with its `things:///show?id=` link from `links`, and print every `warnings` entry.
   If `verified` is false, say so plainly and quote `verify_reason` (for example "not verified: timeout after 3.0s; check
   the item in Things"). Exit 4 means every target was repeating and nothing was sent.

## Rules
- `deadline` is the external hard date; `when` is the start intention. Never set a deadline that is really a start intention.
- Backward scheduling changes `when` only; the deadline moves only when the user asks to push or set it.
- This skill never completes, cancels or deletes anything, and never prints or asks for the auth token.
- Keep replies short: the report, one question when there are proposals, then the result lines with links.
