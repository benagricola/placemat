# Finding suggestions: core plan

Spec: `docs/superpowers/specs/2026-10-02-finding-suggestions-design.md` (approved 2026-10-03).
Scope: everything but the studio's endpoints, page and worker overlay. Branch `suggestions-core`.
The studio side builds on the interfaces under "Interfaces" below;
`docs/superpowers/plans/2026-10-03-finding-suggestions-studio-handoff.md` restates them once they are stable.

## Decisions fixed by reading the code

- Only `place` intents record `(file, line)` today (`PlaceIntent.file/line`, `preview_json.declared_sites`). Links,
  keepouts, labels, tracks, fanouts, rules and the other declarations need a site too, so `Board` gains a site
  registry: `Board._sites`, a list of `Site(kind, key, file, line)` filled by one call, `self._record_site(kind, key)`,
  in each declaration method. It is not part of any digest (the reuse context never reads it), so replay is unchanged.
  Items sharing a `(file, line, kind)` are the "shared" count: a loop or helper. Such a target is refused.
- A replayed step must keep its suggestions, and a replay may sit on a script whose lines moved. The cache therefore stores
  the suggestions unbound (op, target kind and key, value: no file, line or digest), and `bind` gives them their file,
  line, digest and id at the end of every resolve from the current registry.
- `Finding.facts` is kept on the object (and pickled) but not in the cache: the cache keeps `[kind, text, severity, case,
  suggestions]`.
- Digest: `sha256(text.encode()).hexdigest()[:16]`, taken from the file text the first time a declaration in that file is
  recorded during a resolve (`Board.file_digest(path)`), so a file edited while the resolve runs is not mistaken for the one
  the lines came from.
- One `Edit` per suggestion. A `{"const": ...}` value carries its own `set_constant` (the engine pairs them), so the one edit
  can write two files. `apply_suggestion` returns every file's before and after.
- A value naming another item (`{"item": "C1"}`) is spelled from that item's own `board.place` call, found through
  `edit.refs[item]` (a bound `Target`), read from the file at apply time.
- `placemat apply` reads `<board>/.placemat/suggestions.json` (written by both `run` and `preview`, one entry per script),
  because a `preview` prints ids too and has no run record. `run.json` also carries them, and `apply` falls back to the
  latest run record when the file is absent.

## Interfaces

`placemat.findings.Finding(kind, text, severity=None, case=None, facts=None, suggestions=())`: `.case` (str or None),
`.facts` (dict), `.suggestions` (tuple of `Suggestion`). Equality, text and severity are as before.

`placemat.suggestions`:

```python
@dataclass(frozen=True) class Target: kind, key, file="", line=0, shared=1, digest=""
@dataclass(frozen=True) class Edit:   op, target (Target|None), args (dict), value (dict|None), refs (dict key->Target), file=""
@dataclass(frozen=True) class Suggestion: text, edit, rank, lever, id="", digests={}   # .to_json() / Suggestion.from_json(d)
@dataclass class FileChange: file, before, after, diff, old_lines, new_lines
@dataclass class Applied: id, text, files (dict path->FileChange), dry_run;  .diff() -> str
suggest(case, facts, settings) -> list[Suggestion]          # unbound, from the raise site
bind(findings, board)                                       # file, line, digest, ids; drops a shared or unlocated target
flatten(findings) -> list[Suggestion]                       # in finding order
to_json(suggestions) / from_json(list)
apply_suggestion(suggestions, id, dry_run=False, *, root=None, log=None, now=None) -> Applied
undo_last(log, *, root=None, dry_run=False, now=None) -> Applied
errors: SuggestionError(Exception) > UnknownSuggestion, StaleSuggestion(.files), EditRefused(.reason), UndoRefused, NothingToUndo
```

`placemat.script_edit`: `digest(text)`, `apply(edit, text, *, texts=None) -> str` for one file, `apply_all(edit, read) ->
{file: (before, after)}`, `spelling(text, target) -> str`, `imported(text) -> set`, `EditRefused`.

JSON: each finding's `case` and `suggestions` (list of `Suggestion.to_json()`) under `finding_details[i]` in `run.json`,
`preview --json`, and the studio's plan `findings[i]`.

Settings (`studio_` keys, outside a run's id): `suggestions_per_lever = 3`, `try_timeout_s = 60`, `apply = true`.

## Tasks

Each task: write the test, see it fail, write the code, see it pass, commit (plain message).

### 1. Settings
- No new dependency: the script edits splice source text with the standard library.
- `settings.py`: `studio_suggestions_per_lever`, `studio_try_timeout_s`, `studio_apply`; validation floors.
- Tests: `tests/test_studio_settings.py` (defaults, floors, not in the run id).

### 2. Finding fields, suggestion records, cache
- `findings.py`: `case`, `facts`, `suggestions`; `__reduce__` keeps them.
- `suggestions.py`: `Target`, `Edit`, `Suggestion`, JSON in and out.
- `reuse.py`: `finding_to_json` -> `[kind, text, severity, case, suggestions]`; `finding_from_json` reads 3-field entries.
- Tests: `tests/test_finding_suggestions.py` (cache and pickle round trip; a three-field entry loads with none).

### 3. script_edit: locate, check, set_kwarg, remove_kwarg, set_arg
- `ast` positions and text splices: find the one `Call` by function name, start line (or span), and kind-specific
  name match; refuse not-exactly-once and shared targets.
- `set_kwarg` (new keyword on its own line at the argument indent, trailing-comma style kept; replace in place),
  `remove_kwarg` (comment moves to the previous argument's line, the closing parenthesis keeps its indent), `set_arg`.
- The check: result parses, and `ast.dump` of the module with the target call replaced by a placeholder is equal before
  and after.
- Value rendering from the intent expression: forms, enums, items (script's own spelling), numbers, strings; refuse a
  form or enum the file does not import.
- Tests: `tests/test_script_edit.py`: one-line and multi-line calls with and without trailing comma, comment after an
  argument, `*args`/`**kw`, keyword present, byte-for-byte outside the node, spelling (`c1`, `Part("c1")`, alias).

### 4. script_edit: edit_list, insert_statement, remove_statement, toml_set, set_constant, undo
- `edit_list` add/remove/move on a list or tuple literal argument, comments kept as for a keyword.
- `insert_statement(after, value)`; `remove_statement`.
- `toml_set` line-level, checked with `tomllib` before and after.
- `set_constant` with scopes (shared module, board script, cell block), naming (`ITEM_KEYWORD_UNIT`, counter on a clash,
  imported modules checked), two variants where the call already uses a name, geometric derivations inline.
- Tests: the rest of `tests/test_script_edit.py`.

### 5. Site registry, bind, per-lever cap
- `layout.py`: `_record_site` in place, link, keepout, label, track, fanout, rule, escape, accept (and the other
  copper declarations by their key); `Board.file_digest`.
- `suggestions.bind`: target file, line, shared count, digest, ids `s<finding>` + letter, `digests` per suggestion;
  suggestions on a shared or unlocated target dropped; per-lever cap `suggestions_per_lever`; called at the end of
  `Board.resolve` and by the runner after it adds findings of its own.
- Tests: sites for each declaration; a loop target is dropped; a moved line rebinds a replayed finding.

### 6. apply_suggestion, the applied log, undo
- Digest check on every target file (and the constants file), `dry_run`, atomic write keeping mode, the log
  `.placemat/applied.jsonl` (`{"op": "apply", id, text, at, files: [{file, before, after}]}`; undo appends
  `{"op": "undo", ...}`), undo stack refusing when a file differs from what the apply wrote.
- Tests: in `tests/test_apply_suggestion.py`.

### 7. Phase 1 cases
`suggestions.py` builders and the raise sites pass `case=`, `facts=`, `suggestions=`:
`unplaced.search` (free-side Beside, priority, face, rotations, blocker, radius, envelope setting; the reservation,
copper, via and rider variants), `unplaced.pocket`, `unplaced.slide`, `unplaced.block`, `unplaced.bearing`,
`unplaced.rides` (none); `fixed.part`, `fixed.cutout`, `fixed.keepout`; `copper.keepout`; `copper.cross`; `link_over`;
`label.sits_on`, `label.no_spot`, `label.not_drawn` (none).
- The free sides of a neighbour are measured at the site from the occupancy it holds.
- Tests per case on a synthetic script (a real file, run through `Board`), the edit applied, the finding gone where the
  spec says it clears; plus one real fixture per case through `tests/real_modules.py`.
- `tests/test_finding_suggestions.py`: every raised `case=` has a builder and the reverse (source scan); no edit writes a
  Location, a coordinate pair, `reach=` with a number, `board.figure` or `board.plane`; keywords against
  `inspect.signature`; enums against `placemat`'s exports; settings against the settings table.

### 8. Phase 2 cases
`copper.meets`, `copper.not_drawn`, `copper.corner`, `copper.note`, `escape_walled`, `escape_closed`, `escape_crossed`,
`escape_lane`, `pair_crossed`, `setup.undeclared`, `setup.lane_unused`, `setup.pitch`, `setup.frame_reach`,
`setup.accept`, `vias`; the plain-string copper notes converted to `Finding`s with a case as their suggestions are
written. A case whose facts the site cannot yet supply is listed in the final report, not stubbed.

### 9. Command line
- `run` and `preview` print `    try <id>: <text>` under critical and warning findings; `run.json` and `preview --json`
  carry `case`, `suggestions` and the digests; `.placemat/suggestions.json`.
- `placemat apply <id> [--script PATH] [--dry-run] [--undo]`; errors exit 1 with the reason.
- Tests: `tests/test_cli_suggestions.py`.

### 10. Docs, hand-off, verification
- `api.md` "Suggestions" under "Findings and severities" with the case table (a test keeps the table and `api.md` in step);
  `SKILL.md` text; `migration.md` "## Unreleased" / "### New".
- Studio hand-off note.
- Full suite once; bench once at `--jobs 2`.

## As built: where it differs from the spec

- A copper declaration's site key is `<key>#<index>` (two tracks of one net share `track NET`); a copper finding's facts
  carry it. A finding about copper made of several declarations of one net (`copper.meets` on a merged track) carries no
  key and gets no suggestion.
- The spec's `[studio] suggestions_per_lever` is joined by `studio.suggest_factor` (2.0): suggestions that widen a limit
  multiply it by this and ones that narrow a step divide by it, so no figure is invented in the builder.
- One `Edit` per suggestion; a `{"const": ...}` value brings its own `set_constant` (the constant's file is bound by
  `bind`), so one edit can write two files. A call that already reads a constant gets two suggestions: change the
  constant (`set_constant`, `existing`), or a constant of its own.
- A keyword that the board method takes by position (`at=`, `weight=`) is edited where the script gave it, by position.
- `edit_list` `remove` also takes `indices` (a track's waypoints have no name to find them by) and `add` takes `create`
  (add the keyword with a one-element list where the call has none).
- The applied log has one line per apply with all its files: `{"op", "id", "text", "at", "files": [{file, before, after}]}`.
- `placemat apply` finds a plan's suggestions in `<board>/.placemat/suggestions.json`, written by `run` and by
  `preview`, so a `preview`'s ids work too; `run.json` carries them as well.
- The `try` console line shows the best suggestion; a second line lists the ids of the rest.
- Cases built without a suggestion for some levers, and the levers not built, are listed in the final report of the
  work, not stubbed.
