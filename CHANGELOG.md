# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-09

Initial public release. Everything before this tag was pre-release iteration; the
audit that preceded publication is recorded in the git history, not here.

### Added

- Six Claude Code skills for Things 3, each triggered by English and Chinese
  phrases: `things-setup`, `things-capture`, `things-close`, `things-organize`,
  `things-deadlines`, `things-today`. They reply in Chinese or English and accept
  input in any language the model understands (dates are parsed for Chinese and
  English). All six follow a preview, confirm, write, verify, links protocol. On anything but macOS the first line of every skill
  (`scripts/osgate`) prints a macOS-only notice and the skill stops; the CLI
  also refuses the `open` transport there.
- Shared CLI `plugins/things/scripts/things` with a fixed JSON envelope, exit
  codes 0 to 4, and subcommands for reads (`inbox`, `today`, `upcoming`,
  `anytime`, `someday`, `logbook`, `deadlines`, `projects`, `areas`, `tags`,
  `get`, `search`, `stale`, `overdue`, `parse-date`, `doctor`, `ping`) and
  writes (`add`, `add-project`, `add-json`, `update`, `complete`, `cancel`,
  `move`, `schedule`, `deadline`, `tag`, `show`). `--now` freezes the clock for
  every date computation, including `today` and `upcoming`.
- things.py 1.0.1 (Apache-2.0) is bundled, unmodified, under
  `plugins/things/scripts/vendor/things` with its licence next to it, so there
  is nothing to `pip install`; `doctor` reports whether the bundled or a system
  copy was imported.
- `things_lib` modules: `token` (token file with 0600 check and masking, with a
  fallback to the token stored in the Things database), `url` (URL building,
  percent-encoding, limits, rate limiter), `transport` (`open`, `record`, `dry`),
  `read` (things.py wrappers plus repeating and evening detection, multi-word
  synonym expansion in both directions), `verify` (post-write re-read on macOS),
  `dates` (bilingual date parsing), `config` (defaults, routing hints, synonyms).
- Bilingual date parsing to the Things `when` and `deadline` vocabulary:
  Chinese and English relative dates, weekdays, month ends (`end of October`),
  offsets, explicit dates, times, deadline keywords (also between a date and its
  time: `tomorrow before 5pm`), reminder words, and past references (`last
  Friday`) that are left in the title instead of becoming dates.
- Per-skill helper scripts (`plan.py`, `candidates.py`, `report.py`,
  `ddl_report.py`, `review.py`, `setup_check.py`, `brief.py`) that do the
  deterministic work, print the exact commands to run with an absolute path, and
  reply in `config.language` or the language of the invocation.
- Three write transports selected by `THINGS_SKILLS_TRANSPORT`: `open`
  (macOS, `open -g`), `record` (append masked URLs to
  `.things-skills/outbox.jsonl`, default off macOS), and `dry` (print masked
  URLs, send nothing, works without a token).
- Repeating to-do detection through a read-only query on the Things database;
  `complete`, `cancel`, `schedule`, `deadline` and `update` refuse repeating
  items instead of failing silently.
- Test suite (pytest) that runs with no Things installed, against things.py's
  own test database shipped as `tests/fixtures/main.sqlite`; an opt-in live test
  (`THINGS_SKILLS_LIVE=1` plus `-m live`, macOS only) that creates a completed
  test project, verifies every write through things.py and prints the project
  links for manual trashing.
- `config.example.json` with example areas, bilingual routing hints, a tag
  vocabulary and synonym groups; `HANDOFF.md` as the first-run checklist.

### Security

- Every skill's `allowed-tools` pre-approves only that skill's helper scripts
  and the read subcommands its body runs. Write subcommands always go through
  Claude Code's permission prompt, a second safety net behind the
  preview-then-confirm protocol; `things-today` and `things-setup` pre-approve
  no write at all.
- The unit-test suite fails closed against the real `open(1)`: `tests/conftest.py`
  prepends a PATH shim named `open` and guards `subprocess.run` in-process, so no
  offline test can reach a real Things even when it passes `--transport open`;
  `tests/test_safety_guard.py` proves both layers on every platform.
- The auth token is never printed, logged, written to the outbox or passed
  through a shell; every URL the CLI shows is masked. Temporary files written by
  the helpers (`things-capture-*.json`, `things-organize-*.json`) are mode 0600
  and pruned after 24 hours.
- Duplicate ids are written once and count once toward the `--yes` threshold
  (also for `add-json` update payloads); an unfilled `<PLACEHOLDER>` in a list,
  area or heading option is refused before anything is sent.

<!-- Create the tag before the first push: `git tag -a v0.1.0 -m "things3-skills 0.1.0"` on the release commit, then `git push origin main --tags`. -->
[Unreleased]: https://github.com/wannaFlyKa/things3-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wannaFlyKa/things3-skills/releases/tag/v0.1.0
