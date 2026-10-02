# Studio phase 1 plan

Spec: `docs/superpowers/specs/2026-10-02-studio-design.md`, phase 1 only.
Order is TDD: each task starts with its failing tests.

1. `project.script_files(script)`: the files `script_fingerprint` reads, in
   its order; the fingerprint is rebuilt from it and stays byte-identical.
   Test: files named, fingerprint equal to the old text.
2. `[studio]` settings: `port` 0, `debounce_ms` 300, `open` true, `keep` 10,
   plus `poll_ms` and `cancel_grace_ms` (tunables). Left out of the run id
   and the reuse context. Test: defaults, a placemat.toml value, run id
   unchanged.
3. Layout hooks: `PlaceIntent.file` beside `line` (the declaring file, not
   what it decides), and `Board.resolve(on_step=None)`, called with the plan
   and the step each time an item settles. Test: placements and findings
   equal with and without the callback; the callback sees each step once
   in order, and the declaring file and line.
4. `preview_json.py`: the plan as JSON from the model `preview.py` draws
   (outline, keepouts, reservations, items with shapes, copper, links,
   congestion, findings, steps) and one item's JSON for a streamed step.
   Test: deterministic, counts and shapes match what `draw` draws.
5. `studio_diff.py`: `diff_plans` (moved, added, removed, copper changed,
   findings gained and lost, score change), `line_diff` (hunks with old and
   new numbers), `trace` (changed lines <-> moved items by declaration
   span). Test on small boards and texts.
6. `studio_watch.py`: `Debounce` (a clock-free state machine: quiet period,
   cancel on a change mid-resolve) and `Poller` (mtime scan of a file set).
   Test with a fake clock.
7. `previewer.resolve_plan`: the resolve `preview()` does, factored out so
   the worker shares it (reuse of its own reuse.json, geometry cached by
   the generated board's mtime); `preview()` calls it, output unchanged.
8. `studio_worker.py`: a process speaking JSON lines; keeps the imports and
   the generation warm; streams step events; cancels at the next step or
   progress call; the server restarts it when it does not stop in
   `cancel_grace_ms`.
9. `studio.py`: the HTTP server (127.0.0.1, token on every request, Host
   check), SSE hub with a replay for late joiners, history of `keep`
   resolves, `/diff`, the watch loop. Test: bind, token refusal, end to end
   on a staged module (edit the script, receive started, step and finished
   with the moved item).
10. `studio_page.html`: board, steps, findings, hover, linked script,
    compare. Checked by serving it and, when a headless browser is
    available, by loading it.
11. CLI `placemat studio`, docs (api.md Studio section and settings rows,
    SKILL.md line, migration.md Unreleased/New).
12. Real boards: staged mcu module and, if a script exists, the larger core
    fixture: timings and the comparison with `placemat preview`; bench with
    `--jobs 2`; the full suite once.

## Left for phase 2

Watching an explore feeds the same compare: `studio_diff.diff_plans(a, b,
partial=True)` takes any two documents with an `items` list of {key, at,
rotation, face} (a partial set of placements compares only the items in
both), and the page draws a diff with `diffLayerSVG(diff, itemsA, itemsB,
face, text)`, which reads nothing but its arguments.
