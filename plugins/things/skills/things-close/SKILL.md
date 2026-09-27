---
name: things-close
description: Use when the user says they are done with, finished, or want to mark complete or close Things to-dos, or dropped them ("done with", "finished", "mark complete", "close", "完成了", "关掉", "搞定了", "取消"). Finds the matching open to-dos in Things 3 by title, notes and bilingual synonyms, shows numbered candidates, and after the user picks completes (or cancels) them in one batch with verified links.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/osgate) Bash(${CLAUDE_SKILL_DIR}/scripts/candidates.py) Bash(${CLAUDE_SKILL_DIR}/scripts/candidates.py *) Bash(${CLAUDE_SKILL_DIR}/scripts/report.py) Bash(${CLAUDE_SKILL_DIR}/scripts/report.py *) Bash(${CLAUDE_SKILL_DIR}/scripts/things search *) Bash(${CLAUDE_SKILL_DIR}/scripts/things get *)
---
!`${CLAUDE_SKILL_DIR}/scripts/osgate`

# things-close: complete or cancel what got done

Runtime compatibility: Claude Code expands `${CLAUDE_SKILL_DIR}` automatically. In Codex, resolve it to the
absolute directory containing this `SKILL.md`; run `scripts/osgate` from that directory once before continuing.

If the line above reads "Things skills run only on macOS", tell the user this plugin needs a Mac and stop; run nothing else.

Every shell call goes through `${CLAUDE_SKILL_DIR}/scripts/things` (the shared CLI) or the two helpers in
`${CLAUDE_SKILL_DIR}/scripts/`; use nothing else (no cat, printf, python3 -c). Pre-approved: `candidates.py`,
`report.py` and the read subcommands `things search` / `things get`. The writes `things complete` and
`things cancel` are NOT pre-approved in Claude Code; Codex uses its normal approval and sandbox policy. This is
only a second safety net: always require the skill's explicit user confirmation. Never pass `--yes`. Nothing is ever deleted: `cancel` is the strongest action
this skill takes. Never print, log or ask for the auth token.

## 1. Understand the request
- Split the message into described items, one per thing that got done or dropped, keeping the user's own words
  (they are the search terms) and dropping only the closing verbs:
  "finished the CR review and the dentist thing" -> "CR review", "dentist"; "把周报和报销关掉" -> "周报", "报销".
- Intent per item: done / finished / 完成了 / 搞定了 / 关掉 -> `complete`. Dropped / won't do / 不做了 / 算了 / 取消
  -> `cancel` (never delete). If it is unclear, ask one short question: done, or dropped? Treat it as unclear
  when the closing verb is 取消 / cancel / drop AND either a candidate title itself contains that verb (取消牙医预约)
  or the described item is an event (预约 / appointment / 会议 / meeting): the user may mean the appointment was
  cancelled, which completes the to-do.
- Language: omit `--lang` (default `auto`) when running candidates.py. It applies `config.language` when that
  is zh or en, otherwise detects the language from the described items (any Chinese character -> zh, so mixed
  input counts as zh). Pass `--lang zh` / `--lang en` only when the user explicitly asks for a language.

## 2. Find candidates (read only)
```
${CLAUDE_SKILL_DIR}/scripts/candidates.py --markdown "CR review" "dentist"
```
- Runs `things search --status open` per item for the whole phrase, each meaningful word and CJK bigrams; the CLI
  expands `config.synonyms` (报销 <-> expense, 周报 <-> weekly report, 医生 <-> doctor / dentist). Ranking: title hits
  above notes hits, then most recently modified; duplicates merged; `For` shows which described item matched.
- Columns: #, title (`[project]` prefix for projects), list (project / area / Inbox / Today / Upcoming / Anytime /
  Someday; a to-do under a heading shows its project, resolved through `things get <heading>`, or the heading
  title if that lookup failed), start, deadline, repeating, for, link (`things:///show?id=<id>`; the id is the
  part after `show?id=`).
- After the table: `No open to-do matches: X` with "possibly already closed" hints from the logbook, a note when a
  repeating item is present, and a reminder to re-run with `--pick` once the user has chosen. Without `--pick` it
  prints NO command lines: there is nothing to run yet.
- Options: `--limit N` per item (default 6), `--type to-do` to hide projects, `--config PATH`, `--now`.
- `{"ok": false, ...}` (exit 3): things.py cannot read the database. Tell the user, point at `/things:things-setup`, stop.
  Exit 1 with `{"ok": false, "error": ...}` is bad input (unknown `--pick` number, `--pick` without `--action`,
  `--pick` when no row matched at all).

## 3. Show the set and ask (ALWAYS, even after "直接" / "just do it": that shortcut belongs to things-capture only)
- Show the table as printed (titles verbatim, never translated) and state the action per row (complete / cancel).
- For unmatched items say so, show the "possibly already closed" hint, and offer to search with another word.
- Ask ONE short question: which numbers? Accept `1,3`, `all` / `全部`, `y` / `好` / `确认` (= every listed row),
  `none` / `不用`. `--pick` itself takes only row numbers or `all` / `全部`: translate `y` / `好` / `确认` into
  `--pick all` (or the restated row numbers) before step 4. When more than one row is listed and the answer is
  `y` / `好` / `确认`, restate the row numbers being written before running. `none`: stop and say nothing was
  changed. Optional exact preview: add `--dry-run`
  right after `${CLAUDE_SKILL_DIR}/scripts/things` in the step 4 line; the CLI then sends nothing and report.py prints "Dry run" first,
  "Would complete" / "Would cancel" headings and the masked URLs (the token is already masked there).

## 4. Write: only the picked rows, only the chosen verb
Re-run candidates.py with the SAME described items plus the user's numbers and the ONE verb they chose:
```
${CLAUDE_SKILL_DIR}/scripts/candidates.py --markdown "CR review" "dentist" --pick 1,3 --action complete
```
It prints the picked rows' ids in batches of at most 10 (the CLI refuses more without `--yes`, which this skill
never uses), one ready line per batch, each already piped into report.py, e.g.
`${CLAUDE_SKILL_DIR}/scripts/things complete ID1 ID2 | ${CLAUDE_SKILL_DIR}/scripts/report.py --markdown --lang en`
(printed with the absolute path of this skill's `scripts/` directory and the `--lang` value candidates.py
resolved: report.py has no described items to detect from, so it needs the explicit flag). Run those lines
verbatim, one Bash call each, in order; nothing else. Never run a line containing an id the user did not pick,
and never the other verb.
Picked repeating rows are left out by candidates.py and named in a "Left out" line: tell the user to do them in Things.
If the user picked rows for both verbs, run `--pick ... --action complete` and `--pick ... --action cancel` separately.
- Fallback only when the pipe is not available: run `${CLAUDE_SKILL_DIR}/scripts/things complete ID1 ID2 ...`
  alone (it prints one JSON line), then either
  `${CLAUDE_SKILL_DIR}/scripts/report.py --markdown --lang en --envelope '<that one-line JSON>'` (single-quoted;
  a `'` inside the JSON, e.g. in a skipped title, is written `'\''`), or redirect the first command's stdout to a
  file and run `${CLAUDE_SKILL_DIR}/scripts/report.py --markdown --lang en --file /path/to/envelope.json`,
  or read the envelope fields below yourself. In both forms use the `--lang` value from the ready line
  candidates.py printed.

## 5. Verify -> links
`report.py` re-reads every written id with `things get` and prints: the completed / canceled titles with their
`things:///show?id=` links and the status Things shows now; every `data.skipped` entry (repeating to-dos) with its
link and the explanation that the Things URL scheme cannot complete or cancel a repeating to-do, so it has to be
done in Things; the `verified` line; every warning. Relay it in full, titles verbatim. On a dry run it starts with
"Dry run: nothing was sent to Things.", heads the list "Would complete" / "Would cancel" and lists the masked URLs.

Envelope fields when you read it directly: `ok` + `error` (false: nothing was written; exit 4 means every picked
item is repeating), `data.done` (ids sent), `data.skipped` (`id`, `title`, `reason`), `urls` (masked URLs built),
`ids` / `links` (clickable `things:///show?id=` lines), `verified`, `verify_reason`, `warnings`
(`unknown id: X` means X was not sent). When `verified` is true, say the change was confirmed in Things.
When `verified` is false, say so plainly, quoting `verify_reason` as printed ("Not verified: <verify_reason>"),
and give the links so the user can check. When `verified` is null and `sent` is false (dry run) nothing was sent:
show `urls` and say no change was made. If the token is missing (`error` says so), point at `/things:things-setup`.

## Reply language
Reply in the language of the helper's table and report (candidates.py already applied `config.language`, else
detected it from the described items: Chinese or mixed in -> zh, English in -> en). Titles and notes are never
translated or paraphrased.

## Best practices (cite briefly, do not lecture)
- Today is a promise for today, not a wish list: closing what is done keeps it honest.
- Inbox is for capture only; nothing should live there more than a week. If a closed item was still in Inbox, say so.
- Someday is a parking lot, not a graveyard: when something is dropped "for now", suggest moving it to Someday with
  `/things:things-organize` instead of canceling it.
