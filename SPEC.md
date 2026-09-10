# things3-skills SPEC

Version 0.1.0 of the specification. Source of truth for Phase 2 implementers and the Phase 3 tester.
Where `docs/BUILD_PROMPT.md` left a choice open, this file DECIDES it; such lines are marked **DECISION**.
Facts were verified on 2026-09-09 against the Things URL scheme page
(https://culturedcode.com/things/support/articles/2803573/), the things.py 1.0.1 API page and source
(https://thingsapi.github.io/things.py/things/api.html), and things.py's own test database.

Terminology: "item" = a to-do, project or heading row. "id"/"uuid" = the 22-character Things identifier.
"now" = the local wall-clock datetime used for date math (injectable everywhere, see `--now`).

---

## A. Write API facts (Things URL scheme, version 2)

URL shape: `things:///<command>?<k1>=<v1>&<k2>=<v2>`. Every value percent-encoded (section D).
Only `update`, `update-project`, and `json` with any `operation: "update"` object need `auth-token`.
`add`, `add-project`, `show`, `search`, `version`, `json` (create only) need no token.
The scheme returns data only through `x-success` callbacks, which a shell caller cannot receive. Reads use things.py.

### A.1 `add` (create a to-do). No token. All parameters optional. Without `when` and `list`/`list-id` the to-do lands in Inbox.

| Parameter | Type | Allowed values / notes |
|---|---|---|
| `title` | string | Ignored when `titles` present. |
| `titles` | string, `%0A`-separated | Creates several to-dos; other params apply to all. |
| `notes` | string | Max 10,000 unencoded chars. |
| `when` | string | `today`, `tomorrow`, `evening`, `anytime`, `someday`, `yyyy-mm-dd`, `yyyy-mm-dd@HH:MM` (time sets a reminder; time dropped for anytime/someday). English natural language also accepted, never used by us. |
| `deadline` | date string | `today`, `tomorrow`, `yyyy-mm-dd`. No time part. |
| `tags` | comma-separated titles | Non-existent tags silently skipped. Never auto-created. |
| `checklist-items` | string, `%0A`-separated | Max 100 items. |
| `list-id` | string | ID of project or area. Overrides `list`. |
| `list` | string | Title of project or area. Ignored if `list-id` given. |
| `heading-id` | string | Heading ID inside the target project. Overrides `heading`. |
| `heading` | string | Heading title; ignored unless a project is given and the heading exists. |
| `completed` | boolean | `true`/`false`, default false. Ignored if `canceled=true`. |
| `canceled` | boolean | default false. Wins over `completed`. |
| `show-quick-entry` | boolean | default false. NOT used by this project. |
| `reveal` | boolean | default false. NOT used by this project. |
| `creation-date` | ISO8601 datetime | e.g. `2026-03-10T14:30:00Z`; ignored if in future. NOT used. |
| `completion-date` | ISO8601 datetime | ignored unless completed/canceled. NOT used. |
| `use-clipboard` | string | `replace-title`/`replace-notes`/`replace-checklist-items`. NOT used. |

### A.2 `add-project`. No token. All optional.

| Parameter | Type | Notes |
|---|---|---|
| `title`, `notes`, `when`, `deadline`, `tags` | as in `add` | same limits and vocabularies |
| `area-id` | string | Overrides `area`. |
| `area` | string | Area title; ignored when `area-id` given. |
| `to-dos` | string, `%0A`-separated | Titles of to-dos created inside the project. No headings possible here. |
| `completed`, `canceled` | boolean | Also complete/cancel every child. |
| `reveal`, `creation-date`, `completion-date` | | NOT used. |

There is no `heading`, `checklist-items` or `list` parameter on `add-project`.

### A.3 `update` (modify a to-do). REQUIRES `auth-token` and `id`. A parameter given as `name=` (empty) CLEARS that field.

| Parameter | Type | Notes |
|---|---|---|
| `auth-token` | string | Required. |
| `id` | string | Required. |
| `title` | string | Replaces. |
| `notes` | string | Replaces. 10,000 max. |
| `prepend-notes`, `append-notes` | string | 10,000 max each. |
| `when` | string | `today`, `tomorrow`, `evening`, `someday`, `yyyy-mm-dd`, `yyyy-mm-dd@HH:MM`. `anytime` is NOT documented for update (see Discrepancies). Refused on repeating to-dos. |
| `deadline` | date string | Refused on repeating to-dos. `deadline=` clears. |
| `tags` | comma-separated | REPLACES all tags. |
| `add-tags` | comma-separated | Adds, keeps existing. |
| `checklist-items` | `%0A`-separated | Replaces all. Max 100. |
| `prepend-checklist-items`, `append-checklist-items` | `%0A`-separated | Max 100 each. |
| `list-id` / `list` | string | Move into project or area. |
| `heading-id` / `heading` | string | Move under heading of the (target) project. Usable together with list/list-id. |
| `completed` | boolean | `true` completes, `false` reopens (also reopens a canceled one). Refused on repeating. |
| `canceled` | boolean | `true` cancels, `false` reopens. Wins over completed. Refused on repeating. |
| `duplicate` | boolean | Copies first, updates the copy. Refused on repeating. NOT used. |
| `reveal`, `creation-date`, `completion-date` | | NOT used. `completion-date` refused on repeating. |

### A.4 `update-project`. REQUIRES `auth-token` and `id`. Same clearing rule as `update`.

| Parameter | Notes |
|---|---|
| `auth-token`, `id` | Required. |
| `title`, `notes`, `prepend-notes`, `append-notes`, `when`, `deadline`, `tags`, `add-tags` | as in `update` |
| `area-id` / `area` | Move project into area. `area-id` wins. |
| `completed`, `canceled` | Only take effect when every child to-do is completed/canceled and every heading archived. Refused on repeating projects. |
| `duplicate`, `reveal`, `creation-date`, `completion-date` | NOT used. |

### A.5 `show`, `search`, `version`. No token.

| Command | Parameters | Notes |
|---|---|---|
| `show` | `id` (item id or built-in list id: `inbox`, `today`, `anytime`, `upcoming`, `someday`, `logbook`, `tomorrow`, `deadlines`, `repeating`, `all-projects`, `logged-projects`), `query` (name of area/project/tag/list; ignored if `id` present), `filter` (comma-separated tag titles) | Brings Things to the foreground. `things:///show?id=<id>` is the link format used everywhere in this project. |
| `search` | `query` (optional) | Opens the search screen. NOT used by the CLI. |
| `version` | none | Returns `x-things-scheme-version` (2) and `x-things-client-version` only via `x-success`, which we cannot receive. We use it only to check that macOS has a handler for `things:` (see `things ping`). |

### A.6 `json` (bulk create; the only way to create headings). Token needed only if any object has `operation: "update"`.

URL parameters: `data` (the JSON array, whitespace-stripped then percent-encoded), `auth-token` (conditional), `reveal` (not used).
The old URL command named `add-json` is DEPRECATED by Cultured Code. Our CLI subcommand `add-json <file>` MUST emit `things:///json?data=...`, never `things:///add-json`.

Object envelope (every element of the top-level array):

| Key | Type | Rule |
|---|---|---|
| `type` | `"to-do"` \| `"project"` \| `"heading"` \| `"checklist-item"` | Required. Top level allows only `to-do` and `project`. |
| `operation` | `"create"` \| `"update"` | Default `create`. Only `to-do` and `project` support `update`. |
| `id` | string | Required when `operation` is `update`. |
| `attributes` | object | Required (may be `{}`). Every key optional. |

Allowed `attributes` keys per type:

| Type | Keys |
|---|---|
| `to-do` | `title`, `notes`, `when`, `deadline`, `tags` (ARRAY of strings), `checklist-items` (ARRAY of `checklist-item` objects, max 100), `list-id`, `list`, `heading-id`, `heading`, `completed`, `canceled`, `creation-date`, `completion-date`; update-only: `prepend-notes`, `append-notes`, `add-tags` (comma-separated STRING), `prepend-checklist-items`, `append-checklist-items` (`\n`-separated STRINGS). `list*`/`heading*` are ignored when the to-do is nested in a project's `items`. |
| `project` | `title`, `notes`, `when`, `deadline`, `tags` (array), `area-id`, `area`, `completed`, `canceled`, `creation-date`, `completion-date`; create-only: `items` (array of `to-do` and `heading` objects, positional: to-dos after a heading belong to it); update-only: `prepend-notes`, `append-notes`, `add-tags`. |
| `heading` | `title`, `archived` (boolean). Only valid inside `project.attributes.items`. |
| `checklist-item` | `title`, `completed`, `canceled`. Only valid inside `to-do.attributes["checklist-items"]`. |

Only IDs of TOP-LEVEL objects are ever returned by Things (via x-success), so verification of nested to-dos is by title within the created project (section C.6).
An empty top-level array is rejected before anything is sent: `UrlError("data: array is empty")` (CLI exit 1).

### A.7 Limits (enforced by `url.py` before sending; violation = exit 1)

| Limit | Value | Applies to |
|---|---|---|
| Rate | 250 items per rolling 10 s | every send; `items` counted as in C.7 |
| String value | 4,000 unencoded characters per value; for newline-joined lists (`titles`, `checklist-items`, `prepend-/append-checklist-items`, `to-dos`) the limit applies to each item AND to the joined value | every value unless stated otherwise |
| Notes | 10,000 unencoded characters | `notes`, `prepend-notes`, `append-notes` (URL and JSON) |
| Checklist | 100 items | `checklist-items`, `prepend-/append-checklist-items`, JSON `checklist-items` |

### A.8 Repeating to-dos and projects

`update`/`update-project` refuse to change `when`, `deadline`, `completed`, `canceled`, `completion-date` on repeating items, and refuse `duplicate`. Things does not report the refusal (`open -g` exits 0). The CLI must therefore detect repeating items BEFORE sending (section B.4) and refuse with exit 4.

### A.9 Discrepancies between the fetched pages and BUILD_PROMPT section 1 (not silently resolved)

1. BUILD_PROMPT: "things.py exposes the recurrence flag". FALSE for things.py 1.0.1. No returned dict key marks recurrence, and every list query in `Database.get_tasks` hard-codes `TASK.rt1_recurrenceRule IS NULL`, so repeating TEMPLATES never appear in `tasks()`, `today()`, `anytime()`, etc. Repeating INSTANCES (rows whose `rt1_repeatingTemplate` column is set) DO appear, as ordinary to-dos with no marker. `tasks(uuid=...)` bypasses the filter and returns a template when asked by id. Resolution in this spec: `read.py` runs one extra read-only SQL query on the same database file (section B.4). This is a read, not a write, and is allowed.
2. BUILD_PROMPT: "`today()` does not include repeating tasks that are due today, so `things-today` must add them via `tasks(start='Anytime', ...)`". Partly wrong. The fixture proves `today()` DOES return an already-generated repeating instance ("Repeating To-Do", `K9bx7h1xCJdevvyWardZDq`). What `today()` (and every other things.py call) cannot show is an instance Things has not generated yet because the app was not opened. No `tasks()` filter can surface those; they do not exist as rows. Resolution: `things today` always carries the warning defined in B.6 and never claims completeness for repeating to-dos.
3. BUILD_PROMPT lists `when`, `deadline`, `completed`, `canceled`, `duplicate` as refused on repeating to-dos. The page adds `completion-date`. Harmless for us (not used), recorded for completeness.
4. BUILD_PROMPT: "`when` accepts today, tomorrow, evening, anytime, someday, ...". True for `add`/`add-project`/`json`. For `update` and `update-project` the page lists `today`, `tomorrow`, `evening`, `someday`, date, date-time and does NOT list `anytime`. Whether `when=anytime` works on update is unverified; see Open question 1. The CLI allows it and adds a warning.
5. BUILD_PROMPT: "Use `things.url()` as the reference for URL construction". `things.url()` produces identical encoding to `quote(v, safe='')` (verified: `/`→`%2F`, `&`→`%26`, `,`→`%2C`, newline→`%0A`), but for `update`/`update-project` it always calls `things.token()` against the DEFAULT database path and raises `ValueError` when that fails. It therefore cannot be used on Linux or with the token file. `url.py` must build URLs itself and must not call `things.url()`.
6. BUILD_PROMPT: `add-json` is our CLI subcommand name. Cultured Code's page marks the URL command `add-json` as deprecated in favour of `json`. Not a conflict, but the CLI must never emit `things:///add-json`.
7. things.py API page documents `tag=True`/`tag=False` filters on `tasks()`; things.py 1.0.1 raises `ValueError: Unrecognized tag type: True` because it validates `tag` against the list of tag titles. `read.py` must not pass boolean `tag` values.
8. BUILD_PROMPT: verification delay "1 to 2 seconds" vs. `--verify-timeout` default 3 s. Not a conflict: the CLI polls every 0.5 s up to the timeout (section C.6).
9. BUILD_PROMPT section 1 says the page documents `things://x-callback-url/`. The page only shows `things:///`. We use `things:///` exclusively.

---

## B. Read API facts (things.py 1.0.1, Apache-2.0)

Pin: things.py 1.0.1 (PyPI release 2026-02-28, `requires_python >= 3.7`, pure stdlib, Apache-2.0). `things.__version__ == "1.0.1"`.
**DECISION** (supersedes the earlier `requirements.txt` pin): things.py is VENDORED, not pip-installed. `plugins/things/scripts/vendor/things/` holds `__init__.py`, `api.py`, `database.py` copied verbatim from the 1.0.1 sdist (no `conftest.py`, no edits), next to `plugins/things/scripts/vendor/LICENSE-things.py` (the Apache-2.0 text) and `plugins/things/scripts/vendor/README.md` (provenance and refresh recipe: download the sdist from PyPI, copy the three files). The package cannot sit directly in `scripts/` because the CLI FILE named `things` lives there. A user who enables the plugin installs nothing; `requirements.txt` is deleted (the test suite needs only pytest).
Import resolution (`read.py`, the only importer): one helper runs before the first import; if `<scripts>/vendor/things/__init__.py` exists it inserts `<scripts>/vendor` at the FRONT of `sys.path`, then imports, so the bundled copy wins over any system-installed things.py (the plugin ships the version it was tested against). If the vendor directory is missing it falls back to a plain `import things` (system). If a module named `things` is already in `sys.modules` when the helper first runs, that module is used as is and its source is derived from whether its `__file__` lies under the vendor directory. The resolved source is recorded and exposed by `read.things_py_info()` (C.8) and `doctor` (E.5).
Database path resolution inside things.py: explicit `filepath` kwarg, else `THINGSDB` environment variable, else the default
`~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite`.
The connection is opened with `file:<path>?mode=ro` (read-only). When the file is missing, `sqlite3.OperationalError: unable to open database file` is raised from the first call. Unknown uuid in `tasks(uuid=...)` raises `ValueError("No such task uuid found: ...")`; `get(uuid)` returns `None` instead.

### B.1 Functions the CLI uses

| Function | Parameters used | Returns | Notes |
|---|---|---|---|
| `tasks(uuid=None, include_items=False, **filters)` | `type` (`'to-do'`,`'project'`,`'heading'`,None), `status` (`'incomplete'` default, `'completed'`, `'canceled'`, None=any), `start` (`'Inbox'`,`'Anytime'`,`'Someday'`), `area`/`project`/`heading` (uuid str), `tag` (title str only), `start_date`/`stop_date`/`deadline` (True, False, `'future'`, `'past'`, `'<op>YYYY-MM-DD'`), `deadline_suppressed`, `trashed` (False default), `last` (`'3d'`,`'2w'`,`'1y'`), `search_query` (SQL LIKE, wrapped in `%...%`), `index` (`'index'` or `'todayIndex'`), `count_only` | list of dicts; single dict when `uuid` given; int when `count_only` | `uuid` path forces `include_items=True` (checklist embedded) and skips the recurrence filter. |
| `todos(uuid=None, **f)` | as `tasks` | | `= tasks(type='to-do')` |
| `projects(uuid=None, **f)` | as `tasks`, `include_items` | | With items: `items` list, to-dos without heading first, then headings each with own `items`. |
| `areas(uuid=None, include_items=False)` | | list of `{uuid, type:'area', title, tags?}` | `include_items` adds `items`. |
| `tags(title=None, include_items=False, titles_only=False)` | | list of `{uuid, type:'tag', title, shortcut}`; list of str with `titles_only=True`; one dict with `title=` | Used to validate tag vocabulary. |
| `checklist_items(todo_uuid)` | | list of `{uuid, type:'checklist-item', title, status, stop_date, created, modified}` | Same dicts appear under `checklist` of a to-do fetched by uuid. |
| `search(query)` | | list | `= tasks(search_query=query)`; ASCII case-insensitive LIKE. NOT used for CLI search (E.6 does it in Python). |
| `get(uuid, default=None)` | | task, area or tag dict, or `default` | Tries tasks, then areas, then tags. |
| `inbox()` | | list | `tasks(start='Inbox')` |
| `today()` | | list | Union of (a) `start_date=True, start='Anytime', index='todayIndex'`, (b) `start_date='past', start='Someday'` (yellow dot), (c) `start_date=False, deadline='past', deadline_suppressed=False`; sorted by `(today_index, start_date or '')`. Includes projects. NOT called by the CLI: `'past'` is SQLite's `date('now')`, which ignores `--now`, so `read.today()` reproduces the same three unions and sort with explicit `start_date='<=YYYY-MM-DD'` / `deadline='<=YYYY-MM-DD'` filters built from `now`. |
| `upcoming()` | | list | `tasks(start_date='future', start='Someday')`. Deadline-only items NOT included. NOT called by the CLI for the same reason: `read.upcoming()` runs `tasks(start_date='>YYYY-MM-DD', start='Someday')` with the date from `now`, so `--now` governs Today and Upcoming exactly as the "injectable everywhere" rule promises. |
| `anytime()` | | list | `tasks(start='Anytime')` (includes projects and headings). |
| `someday()` | | list | `tasks(start_date=False, start='Someday')` |
| `logbook(**f)` | `stop_date='>=YYYY-MM-DD'` | list | `canceled() + completed()` sorted by `stop_date` desc. |
| `completed(**f)`, `canceled(**f)` | | list | `status='completed'` / `'canceled'` |
| `deadlines()` | | list | `tasks(deadline=True)` sorted by deadline asc. Open items only by default. |
| `token()` | | str or None | `SELECT uriSchemeAuthenticationToken FROM TMSettings WHERE uuid='RhAzEf6qDxCD5PmnZVtBZR'`. Fallback only (C.4). |
| `url(uuid=None, command='show', **q)` / `link` | | str | `link` is an alias of `url`. NOT used for building (Discrepancy 5). |
| `show(uuid)`, `complete(uuid)` | | | Shell out via `os.system("open ...")`. NEVER used (they bypass our transport and rate limiter). |
| `pop_database(kwargs)` | | `Database` | Internal; not used directly. |

### B.2 Task dict keys (as returned by `tasks()`)

Always present: `uuid`, `type` (`to-do`/`project`/`heading`), `title`, `status` (`incomplete`/`completed`/`canceled`), `notes` (str, may be `''`),
`start` (`Inbox`/`Anytime`/`Someday`), `start_date` (`YYYY-MM-DD` or None), `deadline` (`YYYY-MM-DD` or None), `stop_date` (`YYYY-MM-DD HH:MM:SS` local or None),
`created`, `modified` (`YYYY-MM-DD HH:MM:SS` local), `index` (int), `today_index` (int).
Present only when non-null: `area`, `area_title`, `project`, `project_title`, `heading`, `heading_title`, `reminder_time` (`HH:MM`), `trashed` (True), `tags` (list of titles), `checklist` (True, or list of dicts when items included).
Present with `include_items=True` or uuid lookup: `items` (projects/headings), `checklist` (to-dos).
There is NO recurrence key and NO evening key (see B.4, B.5).

### B.3 Headings

No dedicated function. Use `tasks(type='heading')` (optionally `project=<uuid>`). Heading dicts carry `project`/`project_title`. Fixture: one heading `6QpDLSHZMRAUSAeZ9mNvgt` "Heading" in project `3x1QqJqfvZyhtw8NSdnZqG`.

### B.4 Repeating detection (DECISION, replaces the non-existent "recurrence flag")

`read.py` opens the SAME database file things.py resolves, read-only: path = `os.environ.get("THINGSDB")` else `things.database.DEFAULT_FILEPATH` (things.py constants: `ENVIRONMENT_VARIABLE_WITH_FILEPATH = "THINGSDB"`; `DEFAULT_FILEPATH` = first glob hit of `DEFAULT_FILEPATH_31616502` (`~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite`), else `DEFAULT_FILEPATH_31516502` without the `ThingsData-*` segment), connection `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`. Queries (parameters always bound with `?`, never formatted):
`is_repeating(uuid)`: `SELECT rt1_repeatingTemplate IS NOT NULL OR rt1_recurrenceRule IS NOT NULL FROM TMTask WHERE uuid = ?` -> `bool(row[0])`, `None` if no row or the database is unavailable.
`repeating_uuids()`: `SELECT uuid FROM TMTask WHERE rt1_repeatingTemplate IS NOT NULL OR rt1_recurrenceRule IS NOT NULL` -> set.
things.py's own filter is the constant `IS_NOT_RECURRING = "rt1_recurrenceRule IS NULL"` (database.py), prepended to the WHERE clause of every LIST query in `get_tasks`; the by-uuid path (`get_task_by_uuid`, used by `tasks(uuid=...)` and therefore by `get()`) does NOT apply it. Verified: `things.get('N1PJHsbjct4mb1bhcs7aHa')` returns the template dict, while `search('Repeating')` returns only the instance. Every task dict that leaves `read.py` gets an added key `repeating: bool`. A template (rule set) and its generated instances (template pointer set) are BOTH `repeating: true` and both are refused for `when`/`deadline`/`completed`/`canceled` writes. Fixture: template `N1PJHsbjct4mb1bhcs7aHa` (hidden from lists), instance `K9bx7h1xCJdevvyWardZDq` (visible in `today()`, `anytime()`, `deadlines()`). If the column is missing (`sqlite3.OperationalError`), `repeating_uuids()` returns an empty set and the CLI adds warning `"repeating detection unavailable"`.

### B.5 Evening detection (DECISION)

things.py exposes no "This Evening" flag. `read.today()` adds `evening: bool` from the same read-only connection: `SELECT uuid FROM TMTask WHERE startBucket = 1`. The fixture has no evening rows (all `startBucket = 0`), so this is verified only live (Open question 2). On any error the key is `false` for all rows and warning `"evening detection unavailable"` is added.

### B.6 Why `today()` misses repeating to-dos, and the workaround wording

The database is a snapshot from the last time Things ran. Things creates the next instance of a repeating to-do when the app runs, so an instance that Things has not yet generated has no row anywhere. `today()` returns instances that already exist. Therefore `things today` ALWAYS includes in `warnings`:
`"Repeating to-dos may be missing: things.py only sees instances Things has already generated. Open Things once to refresh."`
`things-today` must print that sentence (translated when replying in Chinese: `"重复任务可能不完整：things.py 只能看到 Things 已生成的实例，请先打开一次 Things。"`).

Best-effort prediction (`read.repeating_templates(now)`), read-only SQL on the same connection:
`SELECT uuid, title, CASE WHEN rt1_nextInstanceStartDate THEN printf('%d-%02d-%02d', (rt1_nextInstanceStartDate & 134152192) >> 16, (rt1_nextInstanceStartDate & 61440) >> 12, (rt1_nextInstanceStartDate & 3968) >> 7) END AS next_instance_date FROM TMTask WHERE rt1_recurrenceRule IS NOT NULL AND rt1_instanceCreationPaused = 0 AND trashed = 0 AND status = 0`
(the packed "Things date" decode is the expression things.py uses for `startDate`, see `convert_thingsdate_sql_expression_to_isodate`). Returns `{"due": [{"uuid", "title", "next_instance_date"} where next_instance_date is not None and <= today], "templates": <row count>, "warning": str|None}`. `rt1_nextInstanceStartDate` is best-effort: in the fixture the template has NULL and the instance holds `69760` (decodes to the sentinel `1-01-01`); values that decode to a year below 2000 are treated as None. On any `sqlite3.Error` return `{"due": [], "templates": 0, "warning": "repeating to-dos could not be predicted"}` and the CLI copies the warning into `warnings`. Fixture: `templates == 1`, `due == []`.

---

## C. Architecture (`plugins/things/scripts/things_lib/`)

Rules for every module: stdlib only plus things.py (the bundled copy, section B); Python 3.9 syntax (no `match`, no `X | Y` unions at runtime; use `typing.Optional`, `List`, `Dict`);
`import things` ONLY inside functions of `read.py` (through its vendor-first import helper, section B; never at module top; `verify.py` only calls `read.*`); no platform check at import time; nothing ever writes to SQLite;
nothing ever calls `open` unless `platform.system() == "Darwin"` at call time. All timestamps written by us are ISO-8601 UTC with `Z`.
The CLI file `plugins/things/scripts/things` inserts its own directory into `sys.path[0]` before `import things_lib`. `plugins/things/scripts/vendor/` (the bundled things.py, section B) is added to `sys.path` only by `read.py`'s import helper, lazily, at the first read.

### C.1 `__init__.py`
`__version__ = "0.1.0"`. Nothing else imported eagerly.

### C.2 `config.py`
```
DEFAULT_CONFIG_PATH = "~/.config/things-skills/config.json"
DEFAULTS: Dict[str, Any]                                # exactly section G defaults
def config_path(override: Optional[str] = None) -> str  # override arg > $THINGS_SKILLS_CONFIG > DEFAULT_CONFIG_PATH; '~' expanded
def load_config(path: Optional[str] = None) -> Dict[str, Any]
    # missing file -> deep copy of DEFAULTS, no error; invalid JSON -> ConfigError(f"invalid JSON in {path}: {msg}")
    # unknown keys kept; known keys type-checked (ConfigError on wrong type); missing keys filled from DEFAULTS
def route(title: str, notes: str, config: Dict) -> Optional[Dict[str, Optional[str]]]
    # returns {"area": str, "project": str|None} of the FIRST routing_hint matching title+"\n"+notes, case-insensitive
    # (casefold); regex hints use re.search with re.IGNORECASE; non-regex hints are substring matches; None if nothing matches
def expand_synonyms(term: str, config: Dict) -> List[str]
    # casefolded term; returns [term] + every member of every synonym group containing it (casefold compare), deduplicated, order kept
class ConfigError(Exception)
```

### C.3 `token.py`
```
TOKEN_PATH = "~/.config/things-skills/auth-token"
class TokenError(Exception)
def token_path() -> str                                  # expanduser(TOKEN_PATH)
def read_token(path: Optional[str] = None, warn: Callable[[str], None] = _stderr) -> str
def mask_url(url: str) -> str                            # re.sub(r"(auth-token=)[^&]*", r"\1***", url)
def resolve_token(path: Optional[str] = None, warn: Callable[[str], None] = _stderr,
                  fallback: Optional[Callable[[], Optional[str]]] = None) -> str   # file first, then fallback (C.3 rules); the CLI passes fallback=read.token_from_database
```
`read_token` rules: read the file as UTF-8 (a BOM is ignored, i.e. decode with `utf-8-sig`); the token is the first non-blank line, stripped; raise `TokenError` with EXACT text
`Things auth token not found: ~/.config/things-skills/auth-token is missing. Create it from Things → Settings → General → Enable Things URLs → Manage.`
when the file is absent, and
`Things auth token file is empty: ~/.config/things-skills/auth-token`
when it exists but contains no non-blank line. (The `~` form is printed literally, not expanded.) If `stat().st_mode & 0o077 != 0`, call `warn` ONCE per process with EXACT text
`warning: ~/.config/things-skills/auth-token is readable by others; run: chmod 600 ~/.config/things-skills/auth-token`.
The token value is never logged, never printed, never interpolated into a shell command line, never in the outbox; the URL that carries it is passed to `open` as one argv element (C.5, list argument, no shell) and is therefore visible in process listings for the lifetime of that `open` process (well under a second). Fallback: when the file is ABSENT (not when empty) and `read.database_status() == "readable"`, use `things.token()`; (the "readable" gate lives in the CLI, which passes `read.token_from_database` as `fallback` only then; `resolve_token` itself applies whatever fallback it is given, so tests may exercise it against the fixture;) if it returns a non-empty string, print `note: using auth token from the Things database; create ~/.config/things-skills/auth-token to silence this` to stderr and proceed. If both fail, raise `TokenError` with the "not found" text.

### C.4 `url.py`
```
VALID_WHEN = re.compile(r"^(today|tomorrow|evening|anytime|someday|\d{4}-\d{2}-\d{2}(@\d{2}:\d{2})?)$")
VALID_DEADLINE = re.compile(r"^(today|tomorrow|\d{4}-\d{2}-\d{2})$")
PARAM_ORDER: Dict[str, List[str]]                        # canonical order per command, section D.2
class UrlError(Exception)                                # limits, unknown parameter, invalid when/deadline -> CLI exit 1
def encode(value: str) -> str                            # urllib.parse.quote(value, safe='')
def build(command: str, params: Dict[str, Any], token: Optional[str] = None) -> str
    # drops keys whose value is None; keeps '' (clear); bool -> 'true'/'false'; list -> joined per D.1; validates limits (A.7);
    # emits params in PARAM_ORDER[command], then any unknown key raises UrlError; appends auth-token LAST when token is not None
def build_json(objects: List[Dict], token: Optional[str] = None) -> str
    # validates against A.6 (raises UrlError with path like "[0].attributes.items[2].type"); data = json.dumps(objects, separators=(',',':'), ensure_ascii=False)
    # url = "things:///json?data=" + encode(data) (+ "&auth-token=" + token if any update op; UrlError if update op and token None)
def show_url(item_id: str) -> str                        # "things:///show?id=" + encode(item_id)
def count_items(command: str, params_or_objects) -> int   # rate-limit weight, C.7
class RateLimiter:
    def __init__(self, limit: int = 250, window: float = 10.0, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep)
    def acquire(self, items: int = 1) -> float          # blocks (via sleep) until `items` fit in the rolling window; returns seconds slept
```
`RateLimiter` keeps a deque of `(timestamp, items)`; `acquire` evicts entries older than `window`, and while `sum(items) + items > limit` sleeps `oldest + window - now`. `items > limit` raises `UrlError("batch of N items exceeds 250 per 10 s; split it")`.

### C.5 `transport.py`
```
TRANSPORTS = ("open", "record", "dry")
OUTBOX_PATH = ".things-skills/outbox.jsonl"              # relative to os.getcwd() at call time
class TransportError(Exception)                          # CLI exit 2
class SendResult(NamedTuple): transport: str; sent: bool; masked_url: str; returncode: Optional[int]; stderr: str
def select_transport(explicit: Optional[str] = None) -> str
    # explicit (--transport) > $THINGS_SKILLS_TRANSPORT > ("open" if platform.system()=="Darwin" else "record"); invalid -> TransportError
def send(url: str, transport: str, command: str, foreground: bool = False, now: Callable[[], datetime] = _utcnow) -> SendResult
```
`send` behaviour by transport:
- `open`: if `platform.system() != "Darwin"` raise `TransportError("transport 'open' is only available on macOS")`. Else `subprocess.run(["open", "-g", url], capture_output=True, text=True, timeout=15)` (omit `-g` when `foreground=True`; only `show` passes it). List argument, never `shell=True`. `returncode != 0` raises `TransportError(f"open exited {rc}: {stderr.strip()}")`. `sent=True` on 0. Note: `open` exits 0 even when Things rejects the URL; hence verification.
  Every `TransportError` message and every `SendResult.stderr` is passed through `mask_url` first: macOS prints the failing URL in `open`'s stderr ("LSOpenURLsWithRole() failed ... for the URL things:///update?...") and `str(TimeoutExpired)` repeats argv, so the raw token can never leak through them.
- `record`: `os.makedirs(".things-skills", exist_ok=True)`; append one line `json.dumps({"ts": <ISO-8601 UTC, e.g. "2026-09-09T02:00:00Z">, "command": <command>, "url": mask_url(url)}, ensure_ascii=False) + "\n"`; `sent=False`. The `Z` suffix is true UTC: an aware `now` is converted with `astimezone(timezone.utc)`, a naive `now` is taken as LOCAL time (never as UTC) and converted the same way. Key order exactly `ts`, `command`, `url`. The raw token NEVER reaches the file.
- `dry`: writes nothing anywhere; `sent=False`; the CLI prints the masked URL in the envelope `urls`.
Every `SendResult.masked_url` is `mask_url(url)`.

### C.6 `verify.py` (macOS only in practice; testable on Linux through injected read functions)
```
class VerifyResult(NamedTuple): verified: bool; reason: Optional[str]; ids: List[str]; links: List[str]; items: List[Dict]
def verify_created(titles: List[str], since: datetime, timeout: float = 3.0, transport: str = "open",
                   poll: float = 0.5, sleep=time.sleep, clock=time.monotonic, reader=None) -> VerifyResult
def verify_updated(ids: List[str], predicate: Callable[[Dict], bool], timeout: float = 3.0, transport: str = "open",
                   poll: float = 0.5, sleep=time.sleep, clock=time.monotonic, reader=None) -> VerifyResult
```
Rules: if `transport != "open"` return immediately `VerifyResult(False, f"transport {transport}: nothing was sent to Things", [], [], [])`.
If `read.database_status() == "unavailable"` return `VerifyResult(False, "database unavailable", [], [], [])`; if it is `"fixture"` (`THINGSDB` set) return `VerifyResult(False, "database overridden by THINGSDB; verification runs only against the default Things database", [], [], [])` (in both cases the writes still went out).
Otherwise sleep `poll` first, then loop until `clock() - start >= timeout`: `verify_created` calls `reader()` (default `lambda: read.tasks_raw(status=None, type=None)`) and matches items whose `title` equals a requested title AND whose `created` (parsed as local `YYYY-MM-DD HH:MM:SS`) is `>= since - 10 s`; every title must match at least once, most recently created wins per title. `verify_updated` de-duplicates `ids` (order kept) before polling, fetches each id via `read.get(id)` and requires `predicate(item)` true for all. Success: `verified=True, reason=None, ids=[...], links=[show_url(i) ...], items=[dicts]`. Failure after timeout: `VerifyResult(False, f"timeout after {timeout:.1f}s", found_ids, found_links, found_items)`.
The `since` timestamp is captured by the CLI immediately before `send()`. Predicates used by the CLI: complete -> `status == "completed"`; cancel -> `status == "canceled"`; schedule -> `start_date == date` or `start` matches, where `when=someday` -> `start == "Someday"` and `start_date is None` (Upcoming items also report `start` Someday, with a date); deadline -> `deadline == date`, with `today`/`tomorrow` resolved to ISO against `now`; move -> `project`/`area`/`heading` uuid or title matches; for a to-do under a heading the project is resolved through the heading row (things.py leaves `TASK.project` NULL there); tag -> requested tags subset of `tags`; update -> every changed scalar field equals (same `when`, `deadline` and list rules).

### C.7 Rate-limit weight (`count_items`)

| Command | items |
|---|---|
| `add` | number of `titles` lines, else 1 |
| `add-project` | 1 + number of `to-dos` lines |
| `update`, `update-project`, `show` | 1 |
| `json` | number of `to-do` + `project` + `heading` objects at any depth (checklist items not counted) |
One process-wide `RateLimiter` instance is used by the CLI; `send()` is always preceded by `acquire(count_items(...))`, including for `record` transport (so tests can observe it with an injected clock), but NOT for `dry`.

### C.8 `read.py` (the only module that imports things.py)
```
class ReadError(Exception)                                # CLI exit 3
def things_py_info() -> Dict                              # {"installed": bool, "version": str|None, "source": "bundled"|"system"|None, "path": str|None (directory of the imported package)}; imports through the vendor-first helper (section B); never raises
def database_path() -> str                                # $THINGSDB if set, else things.py default path (`things.database.DEFAULT_FILEPATH`, imported through the same helper; computed without things when it is not importable)
def database_status() -> str                              # "fixture" if $THINGSDB set and a query succeeds; "readable" if unset and a query succeeds; else "unavailable"
def database_error() -> Optional[str]                     # last exception text, e.g. "unable to open database file", or the ImportError text (e.g. "things.py is damaged: SyntaxError: ...")
def things_version() -> Optional[str]                     # things.__version__ or None if import fails (== things_py_info()["version"])
def tasks_raw(**filters) -> List[Dict]                    # things.tasks(**filters), no enrichment (used by verify)
def enrich(item: Dict) -> Dict                            # adds repeating (B.4), link (things:///show?id=), days_until_deadline (int|None, relative to now), and for today(): evening (B.5)
def inbox() / today() / upcoming() / anytime() / someday() -> List[Dict]
def logbook(days: int, now: date) -> List[Dict]           # things.logbook(stop_date=f">={(now - timedelta(days=days)).isoformat()}")
def deadlines() -> List[Dict]                             # open items with a deadline, ascending
def projects(area: Optional[str] = None) -> List[Dict]    # area is a uuid OR a title (resolved through areas())
def areas() -> List[Dict]
def tags() -> List[Dict]; def tag_titles() -> List[str]
def get(item_id: str) -> Optional[Dict]                   # things.get; to-dos include checklist; projects include items (headings with nested items)
def search(query: str, status: str = "open", area: Optional[str] = None, project: Optional[str] = None, item_type: str = "all",
           limit: int = 20, synonyms: Optional[List[List[str]]] = None) -> List[Dict]   # semantics in E.6
def stale(days: int, now: datetime) -> List[Dict]         # E.7
def overdue(now: date) -> List[Dict]                      # E.7
def repeating_uuids() -> Set[str]; def is_repeating(item_id: str) -> Optional[bool]   # None when database unavailable; SQL in B.4
def repeating_templates(now: date) -> Dict                # B.6 prediction: {"due": [...], "templates": int, "warning": str|None}
def token_from_database() -> Optional[str]                # things.token() guarded; None on any error (used only as resolve_token fallback)
def resolve_type(item_id: str) -> Optional[str]           # "to-do" | "project" | "heading" | "area" | "tag" | None (unknown or db unavailable)
```
Every public function wraps things.py exceptions (`sqlite3.Error`, `ImportError`, `AssertionError`, `ValueError` for unknown uuid -> returns None instead) into `ReadError(str(exc))`. Every function is a module-level name so tests can `monkeypatch.setattr(read, "inbox", fake)`. Status mapping for filters: `open` -> `'incomplete'`, `completed` -> `'completed'`, `canceled` -> `'canceled'`, `all` -> `None`.

### C.9 `dates.py`
Pure functions, no I/O, no things.py. Signatures and rules in section F. `now` is always passed in; the CLI takes it from `--now` or `datetime.now()`.

### C.10 The CLI file `plugins/things/scripts/things`
First line `#!/usr/bin/env python3`, executable (git preserves only the x bit; tests assert the x bits, not 0755), no `.py` extension, `argparse` with subparsers, `main(argv: List[str]) -> int` importable for tests (guarded by `if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`).

---

## D. Encoding rules

### D.1 Value serialisation (before `encode`)

| Python value | Serialised | Example |
|---|---|---|
| `str` | as is | `"买牛奶"` |
| `bool` | `"true"` / `"false"` | `completed=True` -> `completed=true` |
| `None` | parameter omitted | |
| `""` | parameter present, empty (CLEAR) | `deadline=` |
| tags `List[str]` | `",".join(tags)` after stripping each; empty list -> omitted | `["Errand","Home"]` -> `Errand,Home` -> `Errand%2CHome` |
| `checklist-items`, `to-dos`, `titles`, `*-checklist-items` `List[str]` | `"\n".join(items)` | `["a","b"]` -> `a%0Ab` |
| `when` | validated by `VALID_WHEN`; `yyyy-mm-dd@HH:MM` encodes to `yyyy-mm-dd%40HH%3AMM` | `2026-09-11@18:00` -> `2026-09-11%4018%3A00` |
| `deadline` | validated by `VALID_DEADLINE` | |
| json `data` | `json.dumps(obj, separators=(',', ':'), ensure_ascii=False)` then `encode` | see example 10 |

Every serialised value passes through `urllib.parse.quote(value, safe='')`. Consequences the tester must assert: space -> `%20` (never `+`), `/` -> `%2F`, `&` -> `%26`, `#` -> `%23`, `?` -> `%3F`, `=` -> `%3D`, `+` -> `%2B`, `,` -> `%2C`, `@` -> `%40`, `:` -> `%3A`, `%` -> `%25`, `"` -> `%22`, `'` -> `%27`, newline -> `%0A` (uppercase hex), CJK and emoji -> UTF-8 percent triples/quads, `~` and `-`, `_`, `.` unchanged. Parameter NAMES are never encoded (they contain only `[a-z-]`).

### D.2 Parameter order (DECISION: fixed canonical order so tests can assert whole URLs)

| Command | Order |
|---|---|
| `add` | `title`, `titles`, `notes`, `when`, `deadline`, `tags`, `checklist-items`, `list-id`, `list`, `heading-id`, `heading`, `completed`, `canceled` |
| `add-project` | `title`, `notes`, `when`, `deadline`, `tags`, `area-id`, `area`, `to-dos`, `completed`, `canceled` |
| `update` | `id`, `title`, `notes`, `prepend-notes`, `append-notes`, `when`, `deadline`, `tags`, `add-tags`, `checklist-items`, `prepend-checklist-items`, `append-checklist-items`, `list-id`, `list`, `heading-id`, `heading`, `completed`, `canceled`, then `auth-token` |
| `update-project` | `id`, `title`, `notes`, `prepend-notes`, `append-notes`, `when`, `deadline`, `tags`, `add-tags`, `area-id`, `area`, `completed`, `canceled`, then `auth-token` |
| `show` | `id`, `query`, `filter` |
| `json` | `data`, then `auth-token` |
| `version` | none |
Keys not in the list raise `UrlError(f"unknown parameter for {command}: {key}")`. `auth-token` is always the LAST parameter, so `mask_url` yields a URL ending in `auth-token=***`.

### D.3 Worked examples (exact expected strings; `SECRET` stands for the real token, `***` for the masked form)

1. Slash and ampersand and hash in the title, `add`:
   `build("add", {"title": "Review a/b test & ship #1"})` -> `things:///add?title=Review%20a%2Fb%20test%20%26%20ship%20%231`
2. Question mark, equals, plus: `build("add", {"title": "Ship it? x=1 C++"})` -> `things:///add?title=Ship%20it%3F%20x%3D1%20C%2B%2B`
3. CJK: `build("add", {"title": "买牛奶", "when": "today"})` -> `things:///add?title=%E4%B9%B0%E7%89%9B%E5%A5%B6&when=today`
4. Emoji: `build("add", {"title": "Party 🎉"})` -> `things:///add?title=Party%20%F0%9F%8E%89`
5. Newline in notes and a URL inside notes: `build("add", {"title": "Buy milk", "notes": "line1\nsee https://x.y/z?a=1&b=2"})` -> `things:///add?title=Buy%20milk&notes=line1%0Asee%20https%3A%2F%2Fx.y%2Fz%3Fa%3D1%26b%3D2`
6. Tags, checklist (CJK), list, reminder time: `build("add", {"title": "Review a/b test & ship #1", "notes": "see https://x.y/z?a=1&b=2", "when": "2026-09-11@18:00", "tags": ["Errand", "Home"], "checklist-items": ["买菜", "做饭"], "list": "Work"})` ->
   `things:///add?title=Review%20a%2Fb%20test%20%26%20ship%20%231&notes=see%20https%3A%2F%2Fx.y%2Fz%3Fa%3D1%26b%3D2&when=2026-09-11%4018%3A00&tags=Errand%2CHome&checklist-items=%E4%B9%B0%E8%8F%9C%0A%E5%81%9A%E9%A5%AD&list=Work`
7. `update` with token, CJK title and deadline: `build("update", {"id": "ABC123", "title": "完成 Q3 复盘", "deadline": "2026-09-30"}, token="SECRET")` -> `things:///update?id=ABC123&title=%E5%AE%8C%E6%88%90%20Q3%20%E5%A4%8D%E7%9B%98&deadline=2026-09-30&auth-token=SECRET`; masked: `...&deadline=2026-09-30&auth-token=***`
8. Complete: `build("update", {"id": "ABC123", "completed": True}, token="SECRET")` -> `things:///update?id=ABC123&completed=true&auth-token=SECRET`
9. Clear a deadline: `build("update", {"id": "ABC123", "deadline": ""}, token="SECRET")` -> `things:///update?id=ABC123&deadline=&auth-token=SECRET`
10. `add-project` with emoji and to-dos: `build("add-project", {"title": "Ship 🚀 v2", "area": "Work", "to-dos": ["Plan", "Build", "Ship"]})` -> `things:///add-project?title=Ship%20%F0%9F%9A%80%20v2&area=Work&to-dos=Plan%0ABuild%0AShip`
11. `json` minimal: `build_json([{"type": "to-do", "attributes": {"title": "Buy milk"}}])` -> `things:///json?data=%5B%7B%22type%22%3A%22to-do%22%2C%22attributes%22%3A%7B%22title%22%3A%22Buy%20milk%22%7D%7D%5D`
12. `json` project with heading, CJK, checklist:
    input `[{"type":"project","attributes":{"title":"发布 v2","area":"Work","items":[{"type":"heading","attributes":{"title":"准备"}},{"type":"to-do","attributes":{"title":"写文档","checklist-items":[{"type":"checklist-item","attributes":{"title":"大纲"}}]}}]}}]` ->
    `things:///json?data=%5B%7B%22type%22%3A%22project%22%2C%22attributes%22%3A%7B%22title%22%3A%22%E5%8F%91%E5%B8%83%20v2%22%2C%22area%22%3A%22Work%22%2C%22items%22%3A%5B%7B%22type%22%3A%22heading%22%2C%22attributes%22%3A%7B%22title%22%3A%22%E5%87%86%E5%A4%87%22%7D%7D%2C%7B%22type%22%3A%22to-do%22%2C%22attributes%22%3A%7B%22title%22%3A%22%E5%86%99%E6%96%87%E6%A1%A3%22%2C%22checklist-items%22%3A%5B%7B%22type%22%3A%22checklist-item%22%2C%22attributes%22%3A%7B%22title%22%3A%22%E5%A4%A7%E7%BA%B2%22%7D%7D%5D%7D%7D%5D%7D%7D%5D`
13. Percent and quotes: `build("add", {"title": "100% done \"ok\" don't"})` -> `things:///add?title=100%25%20done%20%22ok%22%20don%27t`
14. Show link: `show_url("K9bx7h1xCJdevvyWardZDq")` -> `things:///show?id=K9bx7h1xCJdevvyWardZDq`
15. Masking is idempotent and only touches the token: `mask_url("things:///update?id=A&title=auth-token%3Dx&auth-token=SECRET")` -> `things:///update?id=A&title=auth-token%3Dx&auth-token=***`

---

## E. CLI contract (`plugins/things/scripts/things`)

### E.1 Envelope (DECISION). Every subcommand prints exactly one JSON object to stdout, `ensure_ascii=False`, `indent=None`, trailing newline. All keys ALWAYS present:

```
{"ok": bool, "command": str, "data": object|list|null, "urls": [str], "sent": bool, "verified": bool|null,
 "verify_reason": str|null, "ids": [str], "links": [str], "warnings": [str], "error": str|null}
```
- `urls`: masked URLs that were built (dry-run, record and open alike); `[]` for reads.
- `sent`: true only when transport `open` returned 0 for every URL.
- `verified`: `null` for reads and for `--dry-run`; otherwise `VerifyResult.verified`. `verify_reason`: `VerifyResult.reason`.
- `ids`/`links`: affected item ids and `things:///show?id=` links (from verification when available, else the ids given on the command line; empty for unverified creates).
- `error`: human-readable message on failure (`ok=false`), also written to stderr prefixed `error: `.
Reads put their result in `data`. Human-oriented text goes to stderr only. Nothing else is printed to stdout.
No exception ever escapes as a traceback: anything not mapped in E.2 becomes `ok=false`, exit 1, `error: "unexpected error: <TypeName>: <mask_url(str(exc))>"`. Warnings queued by `read.py` are drained into `warnings` when the envelope is printed, so they survive every error path.

### E.2 Exit codes (DECISION)

| Code | Meaning |
|---|---|
| 0 | success (including `verified: false` on non-`open` transports, and dry-run) |
| 1 | usage, config, limit, invalid value, token missing/empty, unknown id given explicitly |
| 2 | transport failure (`open` non-zero or unavailable) OR `open` transport with `verified: false` and reason starting `timeout` |
| 3 | things.py not importable or database unavailable when the command needs a read (`ReadError`) |
| 4 | refused: every targeted item is repeating (see E.9), or `--yes` missing for a batch over 10 ids, including `add-json` payloads with more than 10 update objects |

### E.3 Global flags (accepted before or after the subcommand; exception: `search` defines its own `--project` filter, so the global `--project` must precede `search`)

| Flag | Type | Default | Effect |
|---|---|---|---|
| `--dry-run` | flag | off | forces transport `dry`; prints masked URLs; `sent=false`, `verified=null`. Token-free: when the token file is missing or empty, the URL is built with a placeholder value (masked as `***` like a real one) and the warning `auth token not found; dry-run continues with a placeholder` is added; without `--dry-run` the same situation is exit 1 |
| `--yes` | flag | off | required when a write targets more than 10 ids (`complete`/`cancel`/`schedule`/`deadline`/`tag`/`move` ids, or `add-json` update objects; duplicate ids count once): exit 4 with `error: "refusing to modify N items without --yes"`; otherwise no effect. The CLI itself never prompts. |
| `--verify-timeout SECONDS` | float | 3.0 | passed to verify; `0` disables verification (`verified=false, verify_reason="verification disabled"`) |
| `--transport {open,record,dry}` | str | see C.5 | overrides `$THINGS_SKILLS_TRANSPORT` |
| `--config PATH` | str | see C.2 | config file; it is loaded eagerly at the start of every subcommand, so a malformed config (explicit path or the default one) is exit 1 `invalid JSON in ...` for every command except `doctor`, which reports `config.valid: false` and exits 0 |
| `--now ISO` | str | wall clock | freezes now for date math, verification windows and every date-relative read (`today`, `upcoming`, `overdue`, `stale`, `logbook`, `days_until_deadline`); accepts `YYYY-MM-DDTHH:MM` or `YYYY-MM-DD HH:MM[:SS]` local |
| `--project` | flag | off | treat the given id(s) as projects when the database cannot tell (uses `update-project`) |
| `--json-input FILE` | str | | reserved, not implemented yet |
| `--version` | flag | | prints `things-skills 0.1.0` and exits 0 |

### E.4 Read subcommands (`things.py`; exit 3 when unavailable). `data` is a list of enriched task dicts (B.2 + `repeating`, `link`, `days_until_deadline`) unless stated.

| Subcommand | Flags | `data` |
|---|---|---|
| `inbox` | | `read.inbox()` |
| `today` | | `{"items": read.today() (each dict also has `evening: bool`), "repeating_hint": read.repeating_templates(now)}`; `warnings` ALWAYS contains the B.6 sentence, plus the prediction warning when present. This is the only list-style read whose `data` is an object (`parse-date` and `doctor` also return objects), not a list. |
| `upcoming` | | `read.upcoming()` |
| `anytime` | | `read.anytime()` filtered to `type == "to-do"` unless `--all-types` |
| `someday` | | `read.someday()` |
| `logbook` | `--days N` (int, default 7) | items with `stop_date >= now - N days`, newest first |
| `deadlines` | `--within N` (int, optional) | open items with a deadline, ascending; `--within` keeps `days_until_deadline <= N` (negatives included) |
| `projects` | `--area NAME_OR_ID` | `read.projects(area)`; an unknown area (neither uuid nor title) gives `[]` plus the warning `unknown area: X`, exit 0 |
| `areas` | | `read.areas()` |
| `tags` | | `read.tags()` |
| `get ID` | | single dict; to-dos include `checklist` (list), projects include `items`; unknown id -> `ok=false`, exit 1, `error: "no item with id X"` |
| `search QUERY` | `--status {open,completed,canceled,all}` (default open), `--area X`, `--project X` (uuid or title), `--type {to-do,project,all}` (default all), `--limit N` (default 20), `--no-synonyms` | E.6 |
| `stale` | `--days N` (default `config.stale_days`) | E.7 |
| `overdue` | | E.7 |
| `parse-date TEXT` | `--kind {when,deadline,auto}` (default auto) | `{"when":..., "deadline":..., "reminder":..., "remaining":..., "language": "zh"|"en"}` from `dates.extract_dates`; never touches things.py. `--kind when`: a lone deadline becomes `when` (`<date>` or `<date>@<reminder>`, keeping `reminder`) and `deadline` is nulled. `--kind deadline`: a lone dated `when` becomes `deadline` (`today`/`tomorrow` resolved to ISO dates against `now`, a `@HH:MM` part dropped) and `when` is nulled; `evening`/`anytime`/`someday` stay in `when` with the warning `'X' cannot be a deadline; kept as when`. `auto` returns the extraction unchanged |
| `doctor` | | E.5; always exit 0 |
| `ping` | | sends `things:///version` through the transport; `sent` tells whether macOS found a handler; exit 2 if `open` fails |

### E.5 `doctor` `data` fields

```
{"platform": "Darwin"|"Linux"|..., "python": "3.x.y", "transport": "open"|"record"|"dry",
 "database": {"path": str, "status": "readable"|"fixture"|"unavailable", "error": str|null},
 "token": {"path": "~/.config/things-skills/auth-token", "present": bool, "empty": bool, "mode_ok": bool|null, "mode": "0600"|null},
 "things_py": {"installed": bool, "version": str|null, "source": "bundled"|"system"|null, "path": str|null},
 "config": {"path": str, "present": bool, "valid": bool, "missing_tags": [str]|null},
 "cli_version": "0.1.0"}
```
`missing_tags` = tags in `config.tags` not present in `read.tag_titles()`; `null` when the database is unavailable. `doctor` never reads the token value into the output.
`things_py` is `read.things_py_info()` verbatim (**DECISION**, section B): `installed` and `version` keep their meaning; `source` is `"bundled"` when the copy under `plugins/things/scripts/vendor/things/` was imported (the expected value), `"system"` when `<scripts>/vendor/things/__init__.py` was absent (vendor directory missing or incomplete) and a system-installed things.py was used, or when a module named `things` from outside the vendor directory was already in `sys.modules`, `null` when nothing could be imported (this includes a bundled copy that exists but fails to import, e.g. a `SyntaxError`: it never falls back to a system copy); `path` is the directory of the imported package or `null`.

### E.6 `search` semantics (DECISION: Python-side matching, not SQL LIKE)

1. Load candidates with `read.tasks_raw(type=None or the requested type, status=<mapped>)`, filtered by `--area`/`--project` (uuid, or title compared casefolded), excluding headings and trashed items. Membership is INCLUSIVE: an item matches `--area X` when its own area is X, OR when its project (directly, or through its heading's project) lives in area X; `--project P` matches items directly in P and items under any of P's headings. The project and heading maps are built once per call from `tasks_raw(type='project')` / `tasks_raw(type='heading')`. Fixture: `search 'area 1' --area 'Area 1'` includes `Todo in Area 1` (it sits in `Project in Area 1`).
2. Split QUERY on whitespace into tokens, then group them into terms: a run of tokens equal to a multi-word synonym member (e.g. `weekly report`) is treated as ONE term, so the phrase expands to its group (周报) the same way a single word does; the longest phrase wins at each position, every other token is a term of its own. Each term is expanded with `config.expand_synonyms` unless `--no-synonyms` (then every token is its own term). A candidate matches when EVERY term has at least one variant that is a casefolded substring of `title` or of `notes`. Casefold is `str.casefold()`, so CJK is exact-substring and ASCII is case-insensitive (`INBOX` matches `Inbox`).
3. Each result gets `match: "title"|"notes"` (title if any variant hit the title) and `matched_terms: [str]`.
4. Ranking: title matches first, then notes matches; within a group by `modified` descending. Truncate to `--limit`.
Fixture expectations (status open, no synonyms): `search inbox` -> 2 to-dos (`To-Do in Inbox`, `To-Do in Inbox with Checklist Items`); `search INBOX` -> same 2; `search "with notes" --type to-do` -> 8 open to-dos, all `match: "notes"` (the fixture notes are the two-line string `"With\nNotes"`, so this passes only because each whitespace-split token is matched separately; a whole-phrase substring would find 0); `search heading --status all` -> 3 items (`Cancelled To-Do in Heading`, `Completed To-Do in Heading`, `To-Do in Heading`); the heading row itself is never returned.
With config synonyms `[["报销","expense","reimbursement"]]`, `search 报销` also matches titles containing `expense`.

### E.7 `stale` and `overdue`

`stale --days N`: open to-dos (`type == "to-do"`, status incomplete, not trashed) with `start == "Anytime"`, `start_date is None`, `repeating == false`, and `modified` older than `now - N days`. Adds `age_days: int`. Sorted oldest first. Fixture at `--now 2026-09-09T10:00 --days 30`: exactly 8 items (`Overdue Todo automatically shown in Today`, `Overdue Todo not shown in Today`, `To-Do in Anytime`, `To-Do in Area 1`, `To-Do in Heading`, `To-Do in Project`, `Todo in Area 1`, `Todo in Area 3`).
`overdue`: open to-dos and projects with `deadline < today`, sorted by deadline ascending. Fixture at `--now 2026-09-09T10:00`: 3 items (`K9bx7h1xCJdevvyWardZDq` with `repeating: true`, `KisAmSsnzCcRRumjY4TkVV`, `Cc73oaq1C2mDMpZZUJaBxe`).

### E.8 Write subcommands (URL scheme). Common flow: resolve/validate -> build URL(s) -> `acquire` -> capture `since` -> `send` -> verify -> envelope.

| Subcommand | Arguments and flags | URL | Token |
|---|---|---|---|
| `add TITLE` | `--notes S`, `--when W`, `--deadline D`, `--tags a,b` (repeatable, comma-split), `--checklist S` (repeatable, `\n` inside splits too), `--list NAME` / `--list-id ID`, `--heading NAME` / `--heading-id ID`, `--completed`, `--canceled` | `add` | no |
| `add-project TITLE` | `--notes`, `--when`, `--deadline`, `--tags`, `--area NAME` / `--area-id ID`, `--todo S` (repeatable) | `add-project` | no |
| `add-json FILE` | `FILE` or `-` for stdin | `json` | only if an `update` op exists |
| `update ID` | `--title`, `--notes`, `--prepend-notes`, `--append-notes`, `--when`, `--deadline`, `--tags` (replace), `--add-tags`, `--checklist` (replace, repeatable), `--prepend-checklist`, `--append-checklist`, `--list`/`--list-id`, `--heading`/`--heading-id`, `--completed`, `--reopen` (completed=false), `--canceled`, `--clear {when,deadline,tags,notes,checklist}` (repeatable; emits `field=`) | `update` or `update-project` (type from `read.resolve_type`, else to-do unless `--project`) | yes |
| `complete ID...` | | one `update?id=X&completed=true` per id | yes |
| `cancel ID...` | | one `update?id=X&canceled=true` per id | yes |
| `move ID...` | exactly one of `--list NAME`, `--list-id ID`, `--area NAME`, `--area-id ID`, `--heading NAME`, `--heading-id ID` (`--heading*` may be combined with one `--list*`) | to-do: `list`/`list-id` for both `--list*` and `--area*`; project: `area`/`area-id` (`--list*`/`--heading*` on a project -> exit 1) | yes |
| `schedule ID... --when W` | `W` must match `VALID_WHEN` (use `parse-date` first) | `update ... when=W` | yes |
| `deadline ID... (--date D | --push +Nd\|+Nw | --clear)` | `--push` needs the current deadline from the database (exit 3 if unavailable); the spec is stripped, then checked with `dates.add_offset` against `now.date()` (the frozen `--now`), so an invalid spec is exit 1 before any read; a negative offset must be written `--push=-Nd` (argparse reads a bare `-3d` as an option); targets without a deadline are skipped with the warning `X has no deadline to push; skipped` and listed in `data.skipped` with reason `no deadline to push`; when EVERY target lacks one: exit 1, `error: "no target has a deadline to push"`, `data` still carries `skipped`; `--clear` emits `deadline=` | `update ... deadline=` | yes |
| `tag ID... (--add a,b | --set a,b)` | `--add` -> `add-tags`; `--set` -> `tags` | `update` | yes |
| `show ID` | | `show?id=` sent with `foreground=True`; no verification (`verified=null`) | no |

Tag handling on every write that carries tags: when the database is readable, tags not in `read.tag_titles()` are DROPPED with warning `"tag not found in Things, dropped: <tag>"`; when unavailable, they pass through with warning `"database unavailable: tags not verified"`. When `tag --add`/`--set` asked for tags and EVERY one was dropped, the write would be a no-op, so it is refused: exit 1, `error: "no valid tags to apply"`, the drop warnings still reported, `urls` empty and nothing sent. Other subcommands that merely carry tags alongside other attributes (`add`, `add-project`, `add-json`, `update`) continue without them. `when` values must already be in the output vocabulary (F.1); anything else -> exit 1 `error: "invalid --when value 'X'; run: things parse-date 'X'"`. `--when anytime` on `update` adds warning `"when=anytime is undocumented for update; check the result in Things"`.
Multi-id commands send one URL per id, in argument order, each through the rate limiter; a repeated id is de-duplicated first (order kept), so it is one write, one verification target and counts once for the `--yes` threshold. Ids that `read.get` cannot find are reported in `warnings` (`"unknown id: X"`) and still sent when the database is unavailable, but skipped (not sent) when the database is readable and says the id does not exist.
Placeholders: an unfilled template slot such as `<AREA>` or `<PROJECT>` (regex `^<[A-Z][A-Z0-9_-]*>$`) given as the value of `--list`/`--list-id`/`--area`/`--area-id`/`--heading`/`--heading-id` on `add`, `add-project`, `update` or `move` is refused before anything is built or sent: exit 1, `error: "placeholder <AREA> for --list was not filled in"` (the skills print such slots for the model to fill in; Things would silently ignore an unknown list). With a readable database, a `--list`/`--area` NAME on `add`, `add-project`, `update` or `move` that matches no project or area title (casefolded; `--list` accepts both, `--area` only areas) is still sent, but the envelope carries a warning such as `unknown area: <name>; no area has that title, Things will ignore it (run: things areas)`.
`deadline --push` on an overdue deadline whose new date is still before `now.date()` goes through (the user asked for it) with the warning `"<id>: new deadline <date> is still in the past (was <old>); use --date to pick a future date"`.

### E.9 Repeating items on `complete`, `cancel`, `schedule`, `deadline`, `update --when/--deadline/--completed/--canceled`

For each id, `read.is_repeating(id)`: `true` -> do not build or send; add to `data.skipped` as `{"id": X, "title": T, "reason": "repeating to-do: Things URL scheme cannot change when/deadline/completed/canceled; do it in Things"}`. `None` (database unavailable) -> proceed with warning `"repeating check unavailable for X"`. `data` for these commands is `{"done": [ids sent], "skipped": [...]}`. That shape holds on success and on exit 4; on usage, token or read errors `data` is `null`. If EVERY id was skipped: `ok=false`, exit 4, `error: "all N items are repeating to-dos"`. If some were skipped: exit 0 (or 2 on verification timeout), the skipped list is in `data.skipped` and each skip also appears in `warnings`.

### E.10 `add-json FILE` input schema (DECISION: the file IS the Things `json` `data` array, no translation)

The skill writes a JSON file containing the top-level array exactly as in A.6. The CLI: parses (exit 1 on invalid JSON with `error: "invalid JSON: <msg>"`); validates every object recursively with `url.build_json` rules (allowed `type`, `operation`, required `id` for update, attribute keys per type, `tags` is an array of strings, `checklist-items` array of `checklist-item` objects with at most 100, notes <= 10,000 chars, every string <= 4,000 chars, top level only `to-do`/`project`, `heading` only inside project items, `checklist-item` only inside to-do `checklist-items`) and reports the first error as `error: "<json path>: <message>"`; validates every `when`/`deadline` against F.1 vocabulary; verifies tags (E.8 rule) at any depth; requires the token only when an update operation exists; counts items per C.7 (exit 1 if over 250 with `error: "payload has N items; split into batches of 250"`); sends ONE URL. Verification matches the TOP-LEVEL titles via `verify_created`; `data` echoes `{"objects": N, "items": M, "top_level_titles": [...]}`.
Update-only payloads (no create object) are verified with `verify_updated` over the update ids, using a per-id predicate built from each object's attributes with the same logic as `update` (C.6): `title`, `notes`, `when` (start_date/start), `deadline`, `completed` -> `status == "completed"`, `canceled` -> `status == "canceled"`, `tags` -> requested tags are a SUBSET of the item's tags (Things drops unknown tags silently). If any update object has no checkable attribute (e.g. only `append-notes`), the result is `VerifyResult(False, "update payload not verifiable", ids, links, [])` with exit 0.
Minimal valid file: `[{"type":"to-do","attributes":{"title":"Buy milk"}}]`. Project with headings: see D.3 example 12.

---

## F. Date parsing (`dates.py`)

### F.1 Signatures and output vocabulary
```
WHEN_VOCAB = today | tomorrow | evening | anytime | someday | yyyy-mm-dd | yyyy-mm-dd@HH:MM
def detect_language(text: str) -> str          # "zh" if any char in U+4E00-U+9FFF, U+3400-U+4DBF, U+3000-U+303F or U+FF00-U+FFEF; else "en"
def parse_when(text: str, now: datetime, default_reminder_time: str = "09:00") -> Optional[str]
def parse_deadline(text: str, now: datetime) -> Optional[str]      # always yyyy-mm-dd or None (today/tomorrow/weekday resolved to a date)
def extract_dates(text: str, now: datetime, default_reminder_time: str = "09:00") -> Dict[str, Optional[str]]
    # {"when": str|None, "deadline": str|None, "reminder": "HH:MM"|None, "remaining": str, "language": "zh"|"en"}
def add_offset(day: date, spec: str) -> date    # "+3d" -> +3 days, "+2w" -> +14 days, "-1d" allowed; anything else raises ValueError (strict: surrounding whitespace is an error too; the CLI strips its --push argument before calling)
```
`parse_when` = `extract_dates(...)["when"]`; `parse_deadline` = `extract_dates(...)["deadline"]`. Matching is case-insensitive, whole-string scan, leftmost phrase first. `now` is a naive local datetime.

### F.2 Rules
- R1 Vocabulary: `when` is always one of `WHEN_VOCAB`; `deadline` is always `yyyy-mm-dd`. Never emit English natural language.
- R2 今天/today -> `today`; 明天/tomorrow -> `tomorrow`; 后天/day after tomorrow -> today+2 as a date; 大后天 -> today+3.
- R3 Bare weekday (周X, 星期X, 礼拜X, 週X with X in 一二三四五六日天; Monday..Sunday; Mon Tue Tues Wed Thu Thur Thurs Fri Sat Sun, optional trailing `.`) -> the next occurrence STRICTLY after today (1..7 days ahead). On a Wednesday, `周三`/`Wednesday` -> +7. Past references 上周X/上个周X/上周末 and `last X`/`last weekend` are NOT dates: the whole phrase is consumed by one match (so the bare weekday inside it cannot re-match) and left intact in `remaining`; a later real date phrase in the same text still sets `when`.
- R4 下周X / next X -> that weekday in the NEXT ISO week (Mon-Sun following the current week). 下下周X -> the week after that. 这周X/本周X/this X -> this week's X if >= today, else same as R3; when that X IS today the output is `today` (not the ISO date).
- R5 周末/这周末/本周末/weekend/this weekend -> Saturday of this week if >= today, else next Saturday. 下周末/next weekend -> Saturday of next week.
- R6 月底/本月底/end of (the) month/EOM -> last day of the current month (may equal today). 下月底/end of next month -> last day of next month. 下月初/下个月初/early next month/beginning of next month -> 1st of next month. 下个月/下月/next month -> 1st of next month (DECISION). 月初 -> 1st of next month unless today is the 1st, in which case `today`. Named months: N月底/N月末/end of <month> -> last day of month N, this year if that day >= today else next year (9月底 on 2026-09-09 -> 2026-09-30; `end of August` -> 2027-08-31); N月初 -> the 1st of month N with the R8 year choice (`today` when it is today); 下个月N号/下月N日 -> day N of next month.
- R7 Relative offsets: N天后/N天以后/in N days/+Nd -> today+N; N周后/N个星期后/N个礼拜后/in N weeks/+Nw -> today+7N; N个月后/in N months -> same day N months later (clamped to month end); 下周/next week -> next Monday; 一周后/in a week -> +7. N may be digits or 一二两三四五六七八九十 (十一..十九, 二十 supported).
- R8 Explicit dates: `YYYY-MM-DD`, `YYYY/MM/DD`, `YYYY年M月D日`, `M月D日`, `M月D号`, `M/D` (MONTH first, DECISION), `Oct 1`, `October 1st`, `1 Oct`, `1st October`; Chinese numeral months/days (十月一日). Missing year -> this year if the date >= today, else next year. Two-digit years unsupported (left in `remaining`).
- R9 Times: `H点`, `H点半` (:30), `H点M分` (the 分 belongs to the matched span: 下午3点15分开会 -> remaining 开会; M may be digits or Chinese numerals), `H点MM` (bare two digits, 3点15), `H:MM`, `Hpm`, `H pm`, `H:MMpm`, `H am`, `H时`. Period words shift the hour, and ONLY these words are periods (a word merely starting with `a` or `p` is not): 上午/早上/早晨/清晨/morning/am/a.m. keep 1..11; 中午/noon/midday -> 12:00; 下午/afternoon/pm/p.m. add 12 to 1..11 (`afternoon 3:30` -> 15:30); 晚上/今晚/傍晚/evening/tonight/night add 12 to 1..11; 凌晨 keeps. A bare `H点` with no period keeps H as written. EOD/eod/end of day/下班前 -> 18:00. Output is zero-padded `HH:MM`.
- R10 A date phrase plus a time -> `yyyy-mm-dd@HH:MM` (today/tomorrow are converted to their ISO date in this case; `tomorrow@..` is never emitted). The time still attaches to its date when the two are separated only by whitespace, the punctuation `，,、`, and/or a joiner `at`/`@`/的/在: `Call mom, tomorrow, at 3pm` -> `2026-09-10@15:00`, reminder `15:00`, remaining `Call mom`; `明天，下午3点开会` -> `2026-09-10@15:00`, remaining `开会`. A date-only phrase also absorbs the NEXT time-only phrase across ordinary words when no other date phrase sits between them: `明天开会，下午3点` -> `2026-09-10@15:00`, reminder `15:00`, remaining `开会`; `tomorrow call mom at 3pm` -> `2026-09-10@15:00`, remaining `call mom` (a joiner `at`/`@`/的/在 immediately before the absorbed time is removed with it: `Friday dentist at 2pm` -> remaining `dentist`, `明天开会，在下午3点` -> remaining `开会`); `Friday dentist 2pm` -> `2026-09-11@14:00`. A time with no date -> today if the time is later than `now`, else tomorrow. The time also fills `reminder`.
- R11 晚上/今晚/tonight/this evening with NO hour and NO other date -> `evening`. With another date (明晚, 周五晚上, tomorrow evening, Friday night) -> `<date>@18:00`, `reminder` = `18:00` (DECISION: `evening` is only valid for today, 18:00 is the fixed evening reminder). With an hour -> R9.
- R12 随便什么时候/什么时候都行/有空/anytime/whenever/no rush -> `anytime`. 以后再说/改天/有时间再说/以后/someday/later/eventually -> `someday`. These never carry a time or deadline. 有空 is not matched inside 有空调/有空间/有空位/有空格/有空隙/有空缺/有空档; `later` followed by today/tonight/this/on/in/at is ordinary text, not `someday` (`Call John later today` -> `today`, remaining `Call John later`).
- R13 Deadline keywords: 截止, 截至, 之前, 前 (immediately after a date phrase), 到期 (also directly AFTER a date phrase: 周五到期 -> deadline Friday), 最晚, DDL/ddl, due, by, before, deadline, until, no later than / not later than (recognised as a whole before R12, so their `later` never yields `someday`: `no later than Friday` -> when None, deadline 2026-09-11). A date phrase adjacent to a keyword (keyword directly before it, or 前/之前/到期 directly after it) becomes `deadline`; the time part of such a phrase goes to `reminder`, and `when` stays None unless a second, non-deadline date phrase exists. `evening`/`anytime`/`someday` phrases are never deadlines. A deadline keyword BETWEEN a date phrase and the time it absorbed (R10) makes the whole moment the deadline: `tomorrow before 5pm`, `Friday by 5pm`, `周五前下午5点`, `下周三之前交报告，下午5点` -> `when` None, `deadline` = the date, `reminder` = the time. Phrasal-verb `by` (drop by / stop by / come by / swing by / pass by) is not a deadline keyword: `Drop by tomorrow` -> `when` tomorrow, remaining `Drop by`. `N天前` (N days ago) is not a date; leave it in `remaining`.
- R14 提醒(我)/remind me/reminder with a date and no time -> `<date>@<default_reminder_time>`; the keyword is removed from `remaining`.
- R15 `remaining` = original text with every matched phrase, keyword and reminder word removed; punctuation `，,、` and whitespace directly adjacent to a removed span become one space; runs of whitespace collapse to one space; result stripped. If nothing matched, `remaining == text.strip()`.
- R16 Language: `detect_language(text)`. Chinese digits and full-width digits (０-９) are normalised to ASCII before matching.

### F.3 Expected values with now = 2026-09-09 10:00 local (Wednesday, ISO week 37)

| # | Input | when | deadline | reminder |
|---|---|---|---|---|
| 1 | 今天 | today | | |
| 2 | 明天 | tomorrow | | |
| 3 | 后天 | 2026-09-11 | | |
| 4 | 今晚 | evening | | |
| 5 | 明晚 | 2026-09-10@18:00 | | 18:00 |
| 6 | 周五 | 2026-09-11 | | |
| 7 | 周五晚上 | 2026-09-11@18:00 | | 18:00 |
| 8 | 下周三 | 2026-09-16 | | |
| 9 | 下周一 | 2026-09-14 | | |
| 10 | 这周末 | 2026-09-12 | | |
| 11 | 周末 | 2026-09-12 | | |
| 12 | 月底 | 2026-09-30 | | |
| 13 | 下月初 | 2026-10-01 | | |
| 14 | 下个月 | 2026-10-01 | | |
| 15 | 明天上午9点 | 2026-09-10@09:00 | | 09:00 |
| 16 | 下午3点 | 2026-09-09@15:00 | | 15:00 |
| 17 | 晚上8点 | 2026-09-09@20:00 | | 20:00 |
| 18 | 上午9点 (already past at 10:00, rolls to tomorrow) | 2026-09-10@09:00 | | 09:00 |
| 19 | 三天后 | 2026-09-12 | | |
| 20 | 两周后 | 2026-09-23 | | |
| 21 | 下周 | 2026-09-14 | | |
| 22 | 随便什么时候 | anytime | | |
| 23 | 以后再说 | someday | | |
| 24 | 10月1日 | 2026-10-01 | | |
| 25 | 十月一日 | 2026-10-01 | | |
| 26 | today | today | | |
| 27 | tomorrow | tomorrow | | |
| 28 | tonight | evening | | |
| 29 | this evening | evening | | |
| 30 | next Tue | 2026-09-15 | | |
| 31 | next Monday | 2026-09-14 | | |
| 32 | Friday | 2026-09-11 | | |
| 33 | fri | 2026-09-11 | | |
| 34 | EOD Friday | 2026-09-11@18:00 | | 18:00 |
| 35 | end of month | 2026-09-30 | | |
| 36 | in 2 weeks | 2026-09-23 | | |
| 37 | in 3 days | 2026-09-12 | | |
| 38 | next week | 2026-09-14 | | |
| 39 | someday | someday | | |
| 40 | anytime | anytime | | |
| 41 | 2026-10-01 | 2026-10-01 | | |
| 42 | 10/1 | 2026-10-01 | | |
| 43 | 1/10 (Jan 10 already past, so next year) | 2027-01-10 | | |
| 44 | +3d | 2026-09-12 | | |
| 45 | +1w | 2026-09-16 | | |
| 46 | Wednesday (today is Wednesday) | 2026-09-16 | | |
| 47 | 下下周三 | 2026-09-23 | | |
| 48 | 1月5日 | 2027-01-05 | | |
| 49 | tomorrow evening | 2026-09-10@18:00 | | 18:00 |
| 50 | Friday night | 2026-09-11@18:00 | | 18:00 |
| 51 | 中午 | 2026-09-09@12:00 | | 12:00 |
| 52 | EOD | 2026-09-09@18:00 | | 18:00 |
| 53 | 截止周五 | | 2026-09-11 | |
| 54 | 周五前 | | 2026-09-11 | |
| 55 | 周五之前 | | 2026-09-11 | |
| 56 | due Friday | | 2026-09-11 | |
| 57 | by next Monday | | 2026-09-14 | |
| 58 | before 10/1 | | 2026-10-01 | |
| 59 | deadline 2026-10-01 | | 2026-10-01 | |
| 60 | DDL 月底 | | 2026-09-30 | |
| 61 | 截止明天 | | 2026-09-10 | |
| 62 | by EOD Friday | | 2026-09-11 | 18:00 |
| 63 | 下班前 | | 2026-09-09 | 18:00 |
| 64 | 下周一开始，周五前完成 | 2026-09-14 | 2026-09-11 | |
| 65 | 提醒我明天交房租 | 2026-09-10@09:00 | | 09:00 |
| 66 | Call the dentist | | | |

`extract_dates` `remaining` examples: 明天下午3点给妈妈打电话 -> `给妈妈打电话`; `Submit expense report by Friday` -> `Submit expense report`; 周五前把周报发出去 -> `把周报发出去`; 提醒我明天交房租 -> `交房租`; `Call the dentist` -> `Call the dentist`; 下周一开始，周五前完成 -> `开始 完成`. Language: rows 1-25, 47, 48, 51, 53-55, 60, 61, 63-65 -> `zh`; the rest -> `en`.

---

## G. Config schema (`plugins/things/config.example.json`, copied by `things-setup` to `~/.config/things-skills/config.json`)

| Key | Type | Default (when the file or key is missing) | Example |
|---|---|---|---|
| `areas` | list of str | `[]` | `["Work", "Personal", "Career"]` |
| `routing_hints` | list of `{"pattern": str, "area": str, "project": str|null, "regex": bool}` | `[]` | `{"pattern": "报销", "area": "Work", "project": null, "regex": false}`, `{"pattern": "\\b(gym)\\b|健身", "area": "Personal", "project": null, "regex": true}` (Python `\b` does not delimit CJK words, Han characters are `\w`, so Chinese alternatives go outside the `\b(...)\b` group) |
| `tags` | list of str (allowed vocabulary, keep under 10) | `[]` | `["@calls", "@errands", "@deep", "@waiting"]` |
| `synonyms` | list of lists of str | `[["报销","expense","reimbursement"],["周报","weekly report"],["医生","牙医","doctor","dentist"]]` | user extends |
| `today_cap` | int >= 1 | `6` | |
| `stale_days` | int >= 1 | `30` | |
| `deadline_lead_days` | int >= 0 | `3` | |
| `default_reminder_time` | str `HH:MM` | `"09:00"` | |
| `language` | `"auto"` \| `"zh"` \| `"en"` | `"auto"` | |
| `someday_resurface_days` | int >= 1 | `90` | used by things-organize (best practice: Someday is not a graveyard) |

Rules: `routing_hints` are matched in order against `title + "\n" + notes`, case-insensitive; `regex: false` is a plain casefolded substring test, `regex: true` uses `re.search(pattern, text, re.IGNORECASE)`; FIRST match wins; `project` non-null means the item goes into that project (which must live in `area`). `synonyms` groups are symmetric: any member expands to all members. Load order: `--config` flag, else `$THINGS_SKILLS_CONFIG`, else `~/.config/things-skills/config.json`; a missing file yields the defaults silently (doctor reports `present: false`); a malformed file is a `ConfigError`: exit 1 for every command except `doctor` (which reports `config.valid: false` and exits 0). `config.example.json` ships with the defaults above plus example `areas`, `routing_hints` (both languages) and `tags`; it must be valid JSON that `load_config` accepts unchanged.

---

## H. Skill contracts (`plugins/things/skills/<name>/SKILL.md`, each under 120 lines)

### H.1 Shared shape

Frontmatter (exact keys):
```
---
name: <skill-name>
description: <English trigger phrases>. <Chinese trigger phrases>. One sentence on what it does.
allowed-tools: <per-skill rules, see below>
---
```
`allowed-tools` (DECISION, supersedes the earlier `Bash(${CLAUDE_SKILL_DIR}/scripts/*)`): per-skill rules covering ONLY `Bash(${CLAUDE_SKILL_DIR}/scripts/osgate)`, that skill's helper(s) (`Bash(${CLAUDE_SKILL_DIR}/scripts/<helper>.py)` and `Bash(${CLAUDE_SKILL_DIR}/scripts/<helper>.py *)`) and the read subcommands its body runs (`Bash(${CLAUDE_SKILL_DIR}/scripts/things <sub>)` / `... <sub> *)`). Write subcommands (`add`, `add-project`, `add-json`, `update`, `complete`, `cancel`, `move`, `schedule`, `deadline`, `tag`, `show`) are never pre-approved and always hit Claude Code's permission prompt, which is the second safety net behind the preview-then-confirm protocol. `tests/test_skills.py` `EXPECTED_ALLOWED_TOOLS` holds the exact list per skill (setup: `doctor`, `ping`; today: `today`, `overdue`, `deadlines`, `inbox`; capture: `search`; close: `search`, `get`; organize: `get`, `search`; deadlines: `parse-date`, `search`, `get`).
Mandatory FIRST body line, verbatim:
!`${CLAUDE_SKILL_DIR}/scripts/osgate`
This is context injection, not a loader gate: `scripts/osgate` (executable, byte-identical in all six skills, `#!/bin/sh`) prints nothing on macOS and the sentence `Things skills run only on macOS: tell the user this plugin needs a Mac and stop; run nothing else.` elsewhere, and ALWAYS exits 0. A non-zero exit would abort the skill silently, and the earlier inline `[ "$(uname)" = Darwin ] || { ...; exit 1; }` failed Claude Code's injected-command permission check in default mode, which killed every skill for any user not in bypassPermissions. The body of each skill repeats what the sentence means (`If the line above reads "Things skills run only on macOS", tell the user this plugin needs a Mac and stop; run nothing else.`), and the CLI refuses the `open` transport off macOS regardless.

CLI resolution (DECISION): `${CLAUDE_SKILL_DIR}` is the skill's own directory, so each skill ships a REAL FILE (not a symlink; `scp -r` and some installers flatten symlinks) at `plugins/things/skills/<name>/scripts/things`, executable (git preserves only the x bit; tests assert the x bits, not 0755), with this exact content:
```
#!/bin/sh
# Wrapper: forwards to the shared CLI at plugins/things/scripts/things
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$here/../../../scripts/things" "$@"
```
Every SKILL.md reaches Things ONLY through `${CLAUDE_SKILL_DIR}/scripts/things <subcommand> ...` — no skill talks to the URL scheme or the database by any other route. All six wrappers are byte-identical. Tests assert existence, executability and content. Helper scripts (`plan.py`, `candidates.py`, `report.py`, `review.py`, `ddl_report.py`) print the ABSOLUTE path of the wrapper next to them (`os.path.join(HERE, "things")`), never the literal `${CLAUDE_SKILL_DIR}`: Claude Code substitutes that placeholder only in SKILL.md text and `allowed-tools`, not in tool output or the Bash environment, and the substituted `allowed-tools` rule matches exactly that absolute path.

Per-skill HELPER SCRIPTS (DECISION): a skill may also ship Python helpers next to its wrapper, in its own `scripts/` directory, when its SKILL.md would otherwise have to specify multi-step read-aggregate-render logic in prose. A helper is a presentation and planning layer only: it reads either by running the shared CLI (`plugins/things/scripts/things`, the same file the sibling wrapper execs, under `sys.executable`) or, for `plan.py` and `review.py`, by importing the CLI's own read-only module `things_lib.read`; it never imports `things_lib.transport`, never sends a URL and never executes a SQL write, so every WRITE still goes through the CLI. The commands a helper PRINTS for the model use the absolute path of the sibling wrapper (previous paragraph). Each prints one JSON object (or, with `--markdown`, the report the skill shows the user) and follows the CLI's error discipline — no traceback escapes; failures come back as `{"ok": false, "error": ...}` with a non-zero exit. The shipped helpers are:

| Skill | Helper | Role |
|---|---|---|
| `things-today` | `brief.py` | renders the morning brief and the Obsidian checkbox block |
| `things-capture` | `plan.py` | plans one capture: routing, duplicate check, tag filtering, the command list |
| `things-close` | `candidates.py`, `report.py` | ranks candidates for a described item; renders the after-write report |
| `things-deadlines` | `ddl_report.py` | buckets deadlines and proposes backward-scheduled start dates |
| `things-organize` | `review.py` | runs the seven review checks and applies the user's numbered picks |
| `things-setup` | `setup_check.py` | runs the seven health-check rows and the config copy |

Interaction protocol for every writing skill: (1) gather reads; (2) print a compact PREVIEW table (Markdown) of the exact changes; (3) ask for confirmation (a single short question; accepted answers `y`/`yes`/`好`/`确认`/numbers like `1,3`/`all`/`全部`); (4) run the writes; (5) report `verified`, the `links` from the envelope as clickable `things:///show?id=` lines, and every `warnings` entry; (6) if `verified` is false, say so plainly using `verify_reason`. Only `things-capture` honours `--yes`/"直接建"/"just do it"/"直接" to skip step 3. `things-close` and `things-organize` ALWAYS show the affected set first. No skill ever deletes anything; `cancel` and moving to Someday are the strongest actions. Skills never print or ask for the token. Reply language: `config.language` if not `auto`, else the language of the invocation (`detect_language`), mixed input gets mixed output; titles and notes are NEVER translated. Each skill quotes at most three of the section 7 best practices, one line each.

### H.2 Per-skill contract

| Skill | Triggers (description must contain) | CLI calls | Body must include |
|---|---|---|---|
| `things-setup` | "set up Things", "check Things", "things doctor", "配置 Things", "检查 Things", "Things 设置" | `doctor`, `ping`, `tags`, `areas` | Step list: macOS (detail is the macOS product version), Things installed (`ping` `sent: true`; under a `dry`/`record` transport the row reads "not attempted" and the fix is to unset `THINGS_SKILLS_TRANSPORT`, not to install Things; `setup_check.py` never writes the `record` outbox; when `doctor` yields no envelope rows 3-7 read "not checked"; when the config file is invalid rows 2 and 7 read "not checked" and point at row 6, the App Store fix requires `ping` exit 2 or transport `open`), things.py importable (`doctor` `data.things_py`; **DECISION**: pass detail `bundled 1.0.1` / `system 1.0.1` (ZH `内置 1.0.1` / `系统 1.0.1`) from `source` and `version`; fail detail `cannot import things.py (bundled copy missing or damaged)` / ZH `无法导入 things.py（内置副本缺失或损坏）`, fix: reinstall or update the plugin, `/plugin update things@things3-skills` or re-clone the repository; NEVER a pip command), database readable (else print the Full Disk Access steps for the terminal app: System Settings → Privacy & Security → Full Disk Access → add the app → restart it), token file present and non-empty (path and how to obtain), config exists (copy `config.example.json` to `~/.config/things-skills/config.json` if not; when the example is absent, as in a copy-the-folders install, write `config.DEFAULTS` instead), every `config.tags` tag exists (`doctor.data.config.missing_tags`; right after the config was created from the example, or while `config.tags` still equals the `config.example.json` vocabulary, ask the user to edit `config.tags` instead, they are the example vocabulary; for a user's own tag names ask them to create the tags in Things, never create). One-screen status table with ✅/❌; "Next steps" numbers only the failed rows, advice on a passed row is a bullet. |
| `things-capture` | "add to Things", "capture", "new to-do", "remind me to", "记到 Things", "添加任务", "新建待办", "帮我记一下", "直接建" | `parse-date`, `areas`, `projects`, `tags`, `add`, `add-project`, `add-json`, `search` (duplicate check) | Parse one or many tasks; title in the user's language as written; notes = context + source link; `when`/`deadline` via `parse-date` (never invent deadlines; if a date is given without start-or-deadline intent, ask ONE short question); tags only from `config.tags` that exist; area/project via `routing_hints` and wording (personal and work items routed independently); checklist 3-8 concrete steps, never padded; multi-phase goal -> project with headings via `add-json` (write the file to `${TMPDIR:-/tmp}/things-capture-<epoch>.json`); preview table columns: title, list, when, deadline, tags, checklist count; honours "直接建"/`--yes`. `plan.py` prints options first as `--flag=value` and the title after `--` (so a title such as `-draft` cannot be read as an option); a candidate whose start-or-deadline question is open gets NO command and is listed under `blocked[]` (Markdown: a `# [n] ... blocked` comment); payload files are written with mode 0600 and those older than one day are pruned from `$TMPDIR`; bad input returns `{"ok": false, "error": ...}` exit 1; newline titles are flattened; a dropped tag warning lists the allowed names and a missing `@`/`#` prefix is forgiven. Cites: when vs deadline; verb-first to-dos, outcome-titled projects; checklist vs project. |
| `things-close` | "done with", "finished", "mark complete", "close", "完成了", "关掉", "搞定了", "取消" | `search` (with synonyms, `--status open`), `get`, `complete`, `cancel` | Search each described item by title/notes substrings and synonyms in both languages; rank; show top matches numbered with list and dates; ask for the set (`1,3`, `all`); re-run `candidates.py --pick <numbers> --action complete|cancel`, which prints only the picked non-repeating ids in batches of 10, one line per batch piped into `report.py`; `candidates.py` prints NO write command before a pick; explain and skip repeating items using `data.skipped`; offer `cancel` when the user says dropped/取消/won't do (ask when the verb may describe the appointment itself, e.g. 取消牙医预约); never `--yes`. `report.py` renders a `--dry-run` envelope with a leading "Dry run" line, "Would complete" / "Would cancel" headings and the masked `urls`; the list column reads Today/Upcoming for dated items and the project of a to-do under a heading (resolved through `get <heading>`, one lookup per heading; the heading title if that lookup fails). Cites: Today is a promise; Inbox is for capture only. |
| `things-organize` | "weekly review", "organize Things", "inbox zero", "clean up my tasks", "整理", "周回顾", "清空收件箱", "整理 Things" | `inbox`, `today`, `anytime`, `someday`, `stale`, `overdue`, `deadlines`, `projects`, `areas`, `tags`, then `move`, `schedule`, `deadline`, `tag`, `cancel`, `complete`, `update` | Scope arg (`inbox`, `today`, `all`, area/project name; default full review). Dry-run report first with the seven checks (inbox zero with "do now" flag for < 2 min; Today overload vs `today_cap` (count only `type == "to-do"` items; projects shown in Today do not count) keeping items with deadline within `deadline_lead_days`; stale via `stale --days stale_days` -> Someday / cancel / 15-minute "decide" to-do; deadline sanity: deadline before start, past deadlines, deadline within lead time and no start; tag hygiene: no area/project, tags outside vocabulary; evening candidates -> `when=evening`; Someday items older than `someday_resurface_days` resurfaced). Numbered proposal; user answers with numbers; apply in batches (the CLI rate-limits); always preview; never `--yes`. Cites: Inbox one week max; Someday is a parking lot; cap Today. |
| `things-deadlines` | "deadlines", "overdue", "due this week", "push deadline", "DDL", "逾期", "本周到期", "推后三天", "截止日期" | `overdue`, `deadlines --within 7`, `deadlines --within 30`, `today`, `deadline --push/--date/--clear`, `schedule` | Groups: overdue, due today, within 7 days, within 30 days, grouped by `area_title`, each with `start_date`, `link`. At-risk: `days_until_deadline <= deadline_lead_days` and no `start_date`, or `start_date > deadline`. Propose backward scheduling `when = deadline - deadline_lead_days` (optionally `@default_reminder_time`). Sub-commands in prose: `push <id> +3d` -> `deadline <id> --push +3d`; `clear <id>` -> `deadline <id> --clear`. Chinese: 逾期 / 本周到期 / 推后三天 (`+3d`). Cites: deadline is the external hard date. |
| `things-today` | "morning brief", "what's on today", "today's plan", "今天要做什么", "今日安排", "早报" | `today`, `overdue`, `deadlines --within 7`, `inbox` | Sections: Today from `data.items` (evening items marked), This Evening, "Repeating, probably due" from `data.repeating_hint.due` (omit when empty), overdue, deadlines within 7 days, Inbox count; the B.6 repeating warning; if Today count > `today_cap` say so and suggest `/things:things-organize today`; END with one line for the Obsidian daily note: `- [ ] <title> ([Things](things:///show?id=<id>))` per Today item, joined with newlines inside one fenced block. Reply in the invocation language. Cites: Today is a promise, not a wish list. |

---

## I. Plugin metadata (exact file contents)

`.claude-plugin/marketplace.json`:
```json
{
  "name": "things3-skills",
  "owner": { "name": "wannaFlyKa" },
  "metadata": { "description": "Claude Code skills for Things 3: capture, close, organize, deadlines and a morning brief. Replies in Chinese or English; works with input in any language the model understands." },
  "plugins": [
    {
      "name": "things",
      "source": "./plugins/things",
      "description": "Manage Things 3 to-dos from Claude Code. Replies in Chinese or English; input in any language the model understands. Writes via the Things URL scheme, reads via things.py."
    }
  ]
}
```
(No `version` in the marketplace entry: Claude Code reads the version from `plugin.json` and silently ignores the marketplace copy, so a second copy could only drift. `tests/test_manifests.py` pins `plugin.json` to `things_lib.__version__`.)
`plugins/things/.claude-plugin/plugin.json`:
```json
{
  "name": "things",
  "version": "0.1.0",
  "description": "Things 3 skills for Claude Code: capture, close, organize, deadlines, today. Replies in Chinese or English; input in any language the model understands. macOS only.",
  "author": { "name": "wannaFlyKa" },
  "license": "MIT",
  "keywords": ["things3", "gtd", "todo", "macos", "chinese"]
}
```
Skills are auto-discovered from `plugins/things/skills/*/SKILL.md`; skill names as invoked: `/things:things-setup` etc.

Plugin tree (everything a user receives): `plugins/things/.claude-plugin/plugin.json`, `plugins/things/config.example.json`, `plugins/things/skills/<six skills>/` (each with `SKILL.md`, the `scripts/things` wrapper, the `scripts/osgate` gate script, and that skill's helper scripts from H.1: `brief.py`, `plan.py`, `candidates.py`, `report.py`, `ddl_report.py`, `review.py`, `setup_check.py`), `plugins/things/scripts/things` (CLI file), `plugins/things/scripts/things_lib/*.py`, and `plugins/things/scripts/vendor/` (`things/__init__.py`, `things/api.py`, `things/database.py`, `LICENSE-things.py`, `README.md`; the bundled things.py 1.0.1, section B). No install step outside Claude Code.

---

## J. Test plan handles (pytest, Linux, no Things)

The suite needs only pytest (`python3 -m pip install --user pytest` or equivalent); there is no `requirements.txt` because the runtime has no third-party dependency (things.py is bundled, section B). Reads in tests resolve to the vendored copy unless a test deliberately removes it.

Repo-root `pytest.ini`:
```
[pytest]
testpaths = tests
markers =
    live: needs macOS, Things 3, THINGS_SKILLS_LIVE=1 and `-m live`
```
`tests/conftest.py`: inserts `plugins/things/scripts` at `sys.path[0]`; autouse fixture sets `THINGSDB` to `tests/fixtures/main.sqlite`, `THINGS_SKILLS_TRANSPORT=record`, `HOME` to a fresh `tmp_path` (so `~/.config/things-skills/*` is empty unless a test writes it), `THINGS_SKILLS_CONFIG` unset, and `chdir`s to `tmp_path` (so `.things-skills/outbox.jsonl` lands in the temp dir); provides fixtures `now` (`datetime(2026, 9, 9, 10, 0)`), `token_file` (writes `SECRET` with mode 0600, returns path), `config_file`, `run_cli(args) -> (code, stdout_json, stderr)` (subprocess `[sys.executable, CLI_PATH, *args]`), `fake_clock` for the rate limiter. Every test also runs under a fail-closed guard against the real `open(1)`: a PATH shim named `open` (exit 97, message `things-skills tests: refused to launch the real open(1)`) and a guarded `subprocess.run` that raises `AssertionError` for any `open` argv; only `tests/test_live.py` (`live_env()`, `undo_isolation()`) restores the real PATH/HOME/`subprocess.run`. Tests marked `live` are skipped unless `THINGS_SKILLS_LIVE=1`, `platform.system() == "Darwin"` AND `-m live` was passed on the command line (the env var alone never arms them).

Fixture: `tests/fixtures/main.sqlite` is ALREADY IN PLACE (things.py's own test database, Apache-2.0, 180,224 bytes, database version 24, taken from the `v1.0.1` tag; `tests/fixtures/SOURCE.txt` records the URL). The lib agent must NOT re-download it. It is committed so the suite needs no network; attribution goes in README and LICENSE (third-party notice). Opening it, even read-only, creates `main.sqlite-shm`/`main.sqlite-wal` sidecars: `.gitignore` must list `tests/fixtures/*.sqlite-shm` and `tests/fixtures/*.sqlite-wal`, and tests must not assert on their absence.
Fixture facts (with `THINGSDB` pointing at it): `tasks()` 19 open items; `inbox()` 2; `today()` 5; `upcoming()` 1; `someday()` 1; `anytime()` 14 (all types); `deadlines()` 4; `projects()` 3; `areas()` 3 (`Area 1`, `Area 2`, `Area 3`); `tags(titles_only=True)` = `Errand, Home, Important, Office, Pending`; `tasks(type='heading')` 1; `TMChecklistItem` 3 rows, all on to-do `3Eva4XFof6zWb9iSfYy4ej`; `completed()` 12; `canceled()` 11; `logbook()` 23; `trash()` 6. Vocabularies: `status` in `incomplete|completed|canceled`; `start` in `Inbox|Anytime|Someday`; `type` in `to-do|project|heading`. Repeating template `N1PJHsbjct4mb1bhcs7aHa` ("Repeating To-Do", hidden from lists, returned by `get`) and its instance `K9bx7h1xCJdevvyWardZDq` (visible; `rt1_repeatingTemplate` set). `things.token()` returns `vKkylosuSuGwxrz7qcklOw`.

| Module | Covers |
|---|---|
| `test_url.py` | every D.3 example byte-for-byte; parameter order per command; `None` dropped, `''` kept; bool and list serialisation; limits (4,000 / 10,000 / 100) raise `UrlError`; unknown parameter raises; `VALID_WHEN`/`VALID_DEADLINE` accept and reject; `build_json` validation paths and error path strings; `count_items` table; `mask_url` incl. example 15 |
| `test_token.py` | missing file -> exact "not found" text; empty file -> exact "empty" text; trailing whitespace stripped; 0644 -> exact warning once (second call silent); 0600 -> no warning; token never in stdout/stderr/outbox; fallback to `things.token()` only when file absent and DB readable (fixture token `vKkylosuSuGwxrz7qcklOw`) with the stderr note |
| `test_transport.py` | `select_transport` precedence and default per platform (monkeypatch `platform.system`); `open` on Linux raises `TransportError`; `open` on fake Darwin calls `subprocess.run` with `["open", "-g", url]` list (mock) and no `-g` for `foreground=True`; `record` appends one JSON line with keys `ts`, `command`, `url` in that order, `auth-token=***`, no raw token, ISO-8601 `Z` timestamp; `dry` writes nothing |
| `test_dates.py` | all 66 rows of F.3 via `extract_dates` (when, deadline, reminder); `remaining` examples; `detect_language`; `add_offset` valid and invalid; month-end clamp; year rollover |
| `test_ratelimit.py` | 250 acquires instantly; 251st sleeps until the window frees; `items` weight; batch > 250 raises; injected clock and sleep, zero real waiting |
| `test_config.py` | defaults when file missing; merge of partial file; type errors -> `ConfigError`; malformed JSON; path precedence flag > env > default; `config.example.json` loads and equals defaults for the numeric keys |
| `test_routing.py` | first match wins; case-insensitive substring; regex hints; notes matched; no match -> None; `expand_synonyms` symmetric and deduplicated |
| `test_search.py` | E.6 fixture expectations; CJK substring via a monkeypatched `read.tasks_raw` returning Chinese titles/notes; synonyms; `--status`, `--type`, `--area`, `--limit`; ranking title before notes |
| `test_read.py` | against the fixture: `inbox` 2, `today` exactly these 5 titles in this order (`Upcoming To-Do in Today (yellow)`, `Project in Today`, `To-Do in Today`, `Repeating To-Do`, `Overdue Todo automatically shown in Today`), `upcoming` 1, `someday` 1, `deadlines` 4, `projects` 3, `areas` 3, `tags` 5 titles, `get` to-do `3Eva4XFof6zWb9iSfYy4ej` has 3 checklist items, `get` unknown -> None, `get('N1PJHsbjct4mb1bhcs7aHa')` returns the template with `repeating: true`, headings via `tasks(type='heading')` = 1, `repeating_templates(now)` == `{"due": [], "templates": 1, "warning": None}`, `repeating_uuids()` == `{K9bx7h1xCJdevvyWardZDq, N1PJHsbjct4mb1bhcs7aHa}`, `enrich` adds `repeating`/`link`/`days_until_deadline`, `stale` and `overdue` per E.7, `database_status()` == `fixture`, `unavailable` when `THINGSDB` points to a missing file, `logbook(days=7)` at the frozen now == 0 and `logbook` with a 2020 cutoff == 23 |
| `test_cli.py` | envelope keys always present; exit codes 0/1/2/3/4 reachable (3 via bad `THINGSDB`, 4 via `complete K9bx7h1xCJdevvyWardZDq`); `--dry-run` prints masked URLs for CJK and English `add`, `complete`, `add-json`; record transport writes the outbox and reports `verified: false` with reason `transport record: nothing was sent to Things`; `doctor` on Linux reports `transport: record`, `database.status: fixture`, exit 0; `parse-date`; `--yes` threshold; unknown-tag drop warning; `add-json` validation errors; wrapper scripts exist in all six skills, are executable (x bits) and byte-identical to H.1 |
| `test_skills.py` | each SKILL.md: frontmatter keys, description contains CJK and ASCII letters, per-skill `allowed-tools` map with no write subcommand matched, exact first body line (`osgate`), osgate present/executable/identical/exit 0, the body sentence explaining the gate line, every body CLI line parses against `build_parser()`, helper flags exist, under 120 lines, wrapper present |
| `test_safety_guard.py` | proves conftest fails closed: PATH shim and in-process guard refuse `open(1)`; `--transport open` and `THINGS_SKILLS_TRANSPORT=open` exit 2 on every platform (shim exit 97 on macOS, "only available on macOS" elsewhere); live tests need env + Darwin + `-m live`; `live_env()`/`undo_isolation()` restore the real PATH/HOME; live links are reported immediately and at teardown |
| `test_manifests.py` | `plugin.json` version == `things_lib.__version__`; `marketplace.json` parses, names plugin `things` with source `./plugins/things` and carries no second `version`; README and CHANGELOG name the same version |
| `test_live.py` (`@pytest.mark.live`) | macOS only: `add-project "Things Skills Test <timestamp>"`, `add-json` with a heading and a to-do with checklist inside it, `add` into that project, `update` title, `schedule`, `deadline`, `tag`, `complete` all children then the project; each verified via things.py; prints each project's `show` link to stderr as it is created and the full list again at module teardown (also after `-x` or Ctrl-C) for manual trashing; also probes Open questions 1, 2 and (with `THINGS_SKILLS_LIVE_REPEATING_ID`) 3 and 8 and prints the answers; the K.3 probe attempts a `completed=false` restore when Things accepted the completion |

---

## K. Open questions for the user

1. Does `things:///update?...&when=anytime` work on an existing to-do? The page omits `anytime` for `update`. The CLI allows it with a warning; the live test probes it. If it fails, `things-organize` must move items to Anytime by clearing `when` (`when=`), which we have also not verified.
2. Is `TMTask.startBucket = 1` really "This Evening"? things.py does not expose evening; the fixture has no evening rows. The live test checks one evening to-do. If wrong, `things-today` shows the Evening section as "unavailable".
3. Are already-generated INSTANCES of repeating to-dos (rows with `rt1_repeatingTemplate` set) also refused by `update?completed=true`, or only the hidden template? The page says "repeating to-dos". This spec refuses both (safe); if the live probe shows instances complete fine, relax E.9 to templates only.
4. Fixture licensing: things.py's `tests/main.sqlite` (Apache-2.0) is already in the tree and will be committed into an MIT repo with a third-party notice in README and LICENSE. Acceptable?
5. `things-capture` dedup: when `search` finds an open item with the same title, should capture warn and ask, or add anyway? Spec assumes warn-and-ask (one line), skipped under `--yes`.
6. `M/D` versus `D/M` for slash dates: the spec fixes month-first (`10/1` = October 1). Confirm.
7. `default_reminder_time` is used only when the user asks for a reminder without a time (R14) and by `things-deadlines` backward scheduling. Should every dated `when` get a reminder by default instead?
8. Does `update?id=X&list=<area or project>` (our `move`) work on a repeating to-do? BUILD_PROMPT section 1 lists only when/deadline/completed/canceled/duplicate as refused, so the CLI allows `move` on repeating items; the live test probes it.
