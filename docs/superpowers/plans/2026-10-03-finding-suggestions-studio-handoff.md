# Finding suggestions: what the studio calls

For the studio side of `docs/superpowers/specs/2026-10-02-finding-suggestions-design.md`. Branch `suggestions-core`.
Everything here is in `src/placemat/suggestions.py` unless another file is named; the studio files
(`studio.py`, `studio_worker.py`, `studio_page.html`) are not touched by the core work.

## Where suggestions are in the JSON

Each entry of `plan_json(...)["findings"]` (`preview_json._findings`) has two new keys:

```
{"text": ..., "kind": "unplaced", "severity": "critical", "item": "c4", ...,
 "case": "unplaced.search",                  # null for a finding with none
 "suggestions": [ <suggestion>, ... ]}       # [] when there are none; best first
```

A suggestion (`Suggestion.to_json()`):

```
{"id": "s3a", "text": "Place c4 beside c1, on its north side", "rank": 1, "lever": "beside",
 "edit": {"op": "set_kwarg", "args": {"name": "at"},
          "target": {"kind": "place", "key": "c4", "file": "/abs/layout.py", "line": 12, "shared": 1, "digest": "..."},
          "value": {"form": "Beside", "args": [{"item": "c1"}, {"enum": "Edge.NORTH"}]},
          "refs": {"c1": {"kind": "place", "key": "c1", "file": "/abs/layout.py", "line": 9, ...}}},
 "digests": {"/abs/layout.py": "..."}}
```

- `id` is `s<finding number><letter>`, the finding number being its 1-based place in the plan's findings. It is
  bound to this plan: a later resolve makes its own ids.
- `edit.target.file` and `.line` are where Show selects the declaration. `edit.refs` holds the declarations of other
  items the wording names ("beside c1"): the same file/line shape, for a second Show target.
- `digests` is `{file: digest}` of every file the edit writes. `edit.op` is one of `set_kwarg`, `remove_kwarg`,
  `set_arg`, `edit_list`, `insert_statement`, `remove_statement`, `set_constant`, `toml_set`.
- `lever` groups variants of one thing (the three sides of c1). At most `[studio] suggestions_per_lever` per lever.
- Only suggestions that bound (`id` set) are in the JSON. A suggestion whose edit cannot be made on the script as it
  stands (a loop, an import missing, a spelling it cannot find) is dropped before it gets here, so every one listed
  has applied cleanly in a dry run against the text the plan was made from.
- `run.json` `finding_details[i]` and `preview --json` carry the same two keys (`case`, `suggestions`; both absent
  when a finding has none).

Rebuild the records from the JSON the page was sent:

```python
from placemat import suggestions as sg
pool = sg.from_json([s for f in plan_doc["findings"] for s in f.get("suggestions", ())])   # list[Suggestion]
```

## The one call

```python
sg.apply_suggestion(suggestions, id, dry_run=False, *, root=None, log=None, now=None) -> sg.Applied
```

`suggestions` is the list above, `id` the suggestion's id. The three endpoints are this call:

| endpoint | call |
|---|---|
| `/suggest/show` | `apply_suggestion(pool, id, dry_run=True)` |
| `/suggest/try` | `apply_suggestion(pool, id, dry_run=True)`, then resolve with the returned texts overlaid |
| `/suggest/apply` | `apply_suggestion(pool, id, root=sg.project_root(board_dir), log=sg.log_path(board_dir))` |
| `/suggest/undo` | `sg.undo_last(sg.log_path(board_dir), root=sg.project_root(board_dir))` |

A write (`dry_run=False`) needs both `root` and `log`; without them it raises `ValueError` (a programming error, not
a refusal). `root` is the folder files may be written under (the outermost `placemat.toml`'s folder, else the board's
folder); a file outside it is refused. Honour `[studio] apply = false` (`settings.studio_apply`) before calling with
`dry_run=False`; the function itself does not read settings.

`Applied`:

```
Applied.id, .text, .dry_run
Applied.files: {absolute path: FileChange}      # every file the edit writes: the script, a shared module a
                                                # constant goes in, placemat.toml for a setting
FileChange.before, .after       # whole text of the file
FileChange.diff                 # unified diff, "a/<path>" and "b/<path>"
FileChange.old_lines            # 1-based lines of `before` the edit changed or removed (the overlay's "old")
FileChange.new_lines            # 1-based lines of `after` the edit wrote ("new")
Applied.diff()                  # all files' diffs, joined
```

Digest check: before anything is computed, each file in `suggestion.digests` must still hash to its digest on disk.
If one does not, nothing is written and `StaleSuggestion` is raised (this applies to a dry run as well).

Atomic write: each file is written to a temporary file beside it and moved over it, keeping its mode; a failure on a
later file puts the earlier ones back. The apply is appended to `<board>/.placemat/applied.jsonl`.

## Errors

All are `sg.SuggestionError` (an `Exception`). Suggested mapping, nothing is written in any of them:

| error | when | status |
|---|---|---|
| `UnknownSuggestion` (also a `KeyError`) | no suggestion has that id | 404 |
| `StaleSuggestion` (`.files`) | a file changed since the plan | 409 |
| `EditRefused` (`.reason`) | the edit cannot be made or is not allowed to write (outside `root`) | 422 |
| `NothingToUndo` | the applied log has nothing left to undo | 409 |
| `UndoRefused` | a file is not as the apply left it | 409 |

`str(error)` is a sentence for the page.

## Undo and history

`undo_last(log, *, root=None, dry_run=False)` reverts the last apply that has not been undone, if every file it wrote
still equals what the apply wrote; the undo is logged, so the next undo reverts the apply before it. It returns an
`Applied` (before and after are the other way round). `dry_run=True` shows the reverse diff.

`sg.applied_entries(log)` lists the log for the history rows, oldest first:
`{"seq", "op": "apply", "id", "text", "at", "files": [{"file", "before", "after"}], "undone": bool}`. The history
row text is "applied from a suggestion: <text>".

## Try

1. `done = apply_suggestion(pool, id, dry_run=True)`; the overlay is `{path: change.after for path, change in done.files.items()}`.
2. Resolve the script with that overlay in place of the files on disk (the worker's loader, yours to build). A
   `Board` reads its script files through `board.source_reader` (a `callable(path) -> text`, default: the file on
   disk); set it to the overlay's reader so declaration digests are of the overlaid text. The reuse cache is not
   written by the try, and the digests in a try's own suggestions are of overlay text, not of anything on disk, so
   a suggestion from a try's plan is never applied.
3. Whether the finding cleared: `sg.cleared(finding_json, try_findings_json)`. A finding is named by
   `(kind, case, item)` (`sg.finding_key`); `cleared` is true when none of the try's findings has that key.
4. Findings gained and lost come from the existing compare; the finding row's severity is in the JSON.

## Settings (already in `settings.py` and `api.md`)

`studio_suggestions_per_lever` (3), `studio_try_timeout_s` (60), `studio_apply` (true), `studio_suggest_factor`
(2.0, how much a suggestion widens a limit). All are `studio_` keys: outside a run's id and the reuse context.

## Other things you may meet

- `Finding.facts` (what the raising site measured) is on the object and pickled but is not in any JSON.
- `Finding.suggestions` of a finding added after a resolve (the design checks' `setup.accept`) are bound by the
  runner (`suggestions.bind(plan.findings, board)`); a studio resolve that adds findings of its own should call it too.
- `placemat apply <id>` reads `<board>/.placemat/suggestions.json`, which `run` and `preview` write (`sg.remember`).
  The studio need not write it.
- The `try` console lines come from `Finding.try_lines()` and `console.finding(f)`.
- `runner.scripted_board` sets `board.script_file`; a worker that builds a `Board` another way should set it too (the
  suggestions that edit `placemat.toml` or put a constant in a shared module read it).
- Suggestions are best-effort: a builder or a measurement that fails gives no suggestion and the resolve goes on. A
  finding the engine could not bind has `suggestions == []` in the JSON; the page shows an empty slot.
- Findings replayed from the reuse cache keep their suggestions (stored unbound, bound again at the end of the resolve to
  the script's lines as they are then), so a replaying resolve gives the same suggestions as a fresh one.
