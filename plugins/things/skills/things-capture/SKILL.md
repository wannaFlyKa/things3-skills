---
name: things-capture
description: Use when the user says "add to Things", "capture", "new to-do", "remind me to", or in Chinese "记到 Things", "添加任务", "新建待办", "帮我记一下", "直接建". Turns free text in any language (dates are parsed for Chinese and English; give other-language dates in English or as yyyy-mm-dd) into Things 3 to-dos or one project with headings, previews the plan, writes through the Things URL scheme and verifies the result.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/osgate) Bash(${CLAUDE_SKILL_DIR}/scripts/plan.py) Bash(${CLAUDE_SKILL_DIR}/scripts/plan.py *) Bash(${CLAUDE_SKILL_DIR}/scripts/things search *)
---
!`${CLAUDE_SKILL_DIR}/scripts/osgate`

# things-capture

Runtime compatibility: Claude Code expands `${CLAUDE_SKILL_DIR}` automatically. In Codex, resolve it to the
absolute directory containing this `SKILL.md`; run `scripts/osgate` from that directory once before continuing.

If the line above reads "Things skills run only on macOS", tell the user this plugin needs a Mac and stop; run nothing else.

Create to-dos (or a project with headings) from free text. Pre-approved: `${CLAUDE_SKILL_DIR}/scripts/plan.py`
and the read subcommand `search` of `${CLAUDE_SKILL_DIR}/scripts/things`. The write commands the planner prints (`add`, `add-project`,
`add-json`) are NOT pre-approved in Claude Code; Codex uses its normal approval and sandbox policy. This is only a
second safety net: always require the skill's explicit user confirmation. Run nothing else (no cat, python3 -c,
printf, no Write tool). The planner does
all deterministic work; you split the text, show the plan, ask, run the printed commands, report.

## 1. Split the input into candidates (no tool)
For each task the user described build one JSON object:
- `text`: the user's own words for that task, verbatim. Dates are parsed from here, not by you.
- `title`: exactly as the user wrote it, in the user's language, verb-first when natural. Never translate.
- `notes`: the context the user gave. `source`: any link they pasted (appended to notes).
- `checklist`: only when the task has 3 to 8 obvious concrete steps that each take under a day. Never pad.
- `area` / `project`: only when the user's wording names one ("放到工作里", "in my Personal area").
- `tags`: only names from the config vocabulary the user clearly implied. A dropped tag is reported with the
  `allowed:` list in the warning; offer those names, never invent one.
- A vague multi-step goal with distinct phases becomes ONE candidate:
  `{"text": "...", "title": "<outcome>", "phases": [{"title": "<phase>", "todos": [{"text": "...", "title": "...", "checklist": [...]}]}]}`
  Flat project without phases: `"kind": "project", "todos": ["...", "..."]`.
- Personal and work items in one message stay separate candidates; each is routed on its own.

## 2. Plan (preview + exact commands)
One command, the candidates array inline (single-quoted; a `'` inside the text is written `'\''`):
```sh
${CLAUDE_SKILL_DIR}/scripts/plan.py --markdown --candidates-json '[{"text": "明天下午3点 给妈妈打电话", "title": "给妈妈打电话"}, {"text": "finish the expense report by Friday", "title": "finish the expense report"}]'
```
Only for very long input (many candidates, long notes) fall back to a heredoc on stdin:
```sh
${CLAUDE_SKILL_DIR}/scripts/plan.py --markdown <<'EOF'
[{"text": "...", "title": "..."}]
EOF
```
Add `--yes` when the user said 直接建 / 直接 / just do it / --yes. Other flags: `--config PATH`,
`--now YYYY-MM-DDTHH:MM`, `--input FILE`, `--cli PATH` (printed commands default to the absolute path of
`${CLAUDE_SKILL_DIR}/scripts/things`; options come first as `--flag=value`, the title last after `--`);
omit `--markdown` for JSON (`candidates[]` with `when`, `deadline`, `list`, `tags`, `duplicate`,
`needs_question`, `question`; `commands[]`; `blocked[]`; `confirm_prompt`). Bad input comes back as
`{"ok": false, "error": ...}` with exit 1.
The planner never writes to Things. It parses when / deadline / reminder into the CLI vocabulary
(today, tomorrow, evening, anytime, someday, yyyy-mm-dd, yyyy-mm-dd@HH:MM), routes through config
`routing_hints` (otherwise Inbox), keeps only tags that are both in `config.tags` and present in
Things, searches open items for the same title, chooses `add` / `add-project` / `add-json` (payload
written to `${TMPDIR:-/tmp}/things-capture-<epoch>.json`, mode 0600; files older than a day are pruned
on the next run) and prints the numbered preview table (title, list, when, deadline, tags, checklist
count), flag lines, the commands and one question.

## 3. Show, ask once, confirm
1. Show the preview table and every flag line exactly as printed.
2. A line marked `answer first` / `需要先回答` means a date was given without start-or-deadline
   intent: ask that ONE question and stop. That candidate has NO command yet (the ```sh block shows it
   only as a `# [n] ... blocked` comment; JSON lists it under `blocked`). Re-run the planner with
   `"date_is": "deadline"` or `"date_is": "when"` on that candidate (or explicit `"when"` / `"deadline"`
   values) to get its command. Never invent a deadline.
3. `open item with the same title` / `已有同名未完成项`: show the existing link; do not run that
   command unless the user says to create it anyway.
4. Ask the single confirmation the planner printed. Accepted answers: y, yes, 好, 确认, numbers like
   `1,3`, all, 全部. Skip this step only when `--yes` was given (the planner then prints no question).

## 4. Write and verify
Run each selected command verbatim (the planner prints them with the absolute path of this skill's
`scripts/` directory), one Bash call per command, in the printed order. Every command prints one JSON
envelope; read it:
- `ok` false: stop, quote `error`, do not retry blindly.
- `verified` true: created. `verified` false: say so plainly, quoting `verify_reason`
  (e.g. "not confirmed: transport record: nothing was sent to Things"). A reason starting with
  `timeout` means Things did not show the item within the window: ask the user to open Things and look.
- `verified` null with `sent` false: nothing was sent (`--dry-run` or `THINGS_SKILLS_TRANSPORT=dry`);
  say nothing was created and print `urls`.
- `links`: print every entry as a clickable `things:///show?id=...` line.
- `warnings`: repeat every entry (dropped tags, unverified tags, unknown lists).
- `data` echoes what was sent (`title`, `when`, `list-id`, or `top_level_titles` for add-json);
  `urls` are the masked URLs, mention them only on failure or when the user asks.
If the planner or doctor reports the database unavailable, writes still work: continue and state
that verification is reduced (write-only mode).

## 5. Report
Reply in the language of the invocation (mixed in, mixed out); `config.language` overrides when not
`auto`. Titles and notes are never translated. One line per created item: title, list, when or
deadline, link. Then the warnings: flag and warning lines are diagnostics and are relayed in English as printed;
only titles, the table and the questions follow the invocation language. If some commands were skipped
(duplicates, unselected numbers), say which.

## Rules
- Never delete anything, never print or ask for the token, never write to the Things database.
- Skills honour `--yes` here only; still ask the start-or-deadline question when it is raised.
- `when` is when you intend to start; `deadline` is the external hard date. Never set a deadline that is really a start intention.
- To-dos start with a verb; projects name an outcome ("Ship X", "完成 Y"). Suggest, do not force, renames.
- Checklists for steps that take under a day each; a project when steps span days or need dates.
