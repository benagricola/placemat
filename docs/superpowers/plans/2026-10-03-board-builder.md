# Studio board builder: implementation plan

Spec: `docs/superpowers/specs/2026-10-03-studio-board-builder-design.md` (decided, including its "As built in phase 5").
Branch `board-builder`, from main at 0.93.0. Phases B0 to B4 in order; each ends with a report appended to the scratchpad
`builder-report.md`.

## What exists, what is missing

Built (0.93.0, `tests/test_builder_ops.py`): `script_edit.create_file`, `ensure_import`, `remove_constant`,
`move_statement`, `confirm_facts`, region inserts with `bind`, `read_intent`, `skeleton`, `apply_edits`;
`suggestions.apply_edits`, `redo_last`; `facts.confirmed_text`.

Missing, built in B0 (each with tests):

| Piece | Where |
|---|---|
| `set_constant` of a list of number pairs (polygon outline) | `script_edit._constant_text` |
| `skeleton` docstring rule (`Name: description`, else `Name layout.`) | `script_edit.skeleton` |
| `find_board(..., wanted=)` for a script that does not exist yet | `project.py` |
| `.zen` dialect: stackup layers, pair net classes, `load(...)` names | new `zen_edit.py`, ops `zen_stackup`, `zen_netclasses` |
| JSON dialect for `fab-profile.json` | new `json_edit.py`, op `json_set` |
| ratsnest crossings per quarter turn | `builder.turn_crossings` |
| facts read-back after regeneration | `builder.readback` |

## Layout of the new code

- `builder.py`: pure functions, no pcbnew, no web. Records in, records out.
  - `outline_edits(text, spec)`, `new_script(name, description, spec)` (the skeleton text with the outline in it, made by
    applying the same edits to an in-memory file, so a created script and a later change are one code path),
    `suggest_size(...)`, `polygon_problems(points)`.
  - `parts_rows(board, plan, texts, script)`: the rows, status and the relation read from the script.
  - `offers(ctx, subjects, target)`: the intents for a click, each a `Suggestion`; `search_rest(...)`; `edit_item(...)`.
  - `facts_model(...)`, `facts_edits(...)`, `confirm_edit(...)`, `gate(...)`.
  - `turn_crossings(...)`.
- `zen_edit.py`, `json_edit.py`: the two dialects, text in, text out, using `script_edit._Seq`/`Src` for layout.
- `builder_worker.py`: a one-shot subprocess (`python -m placemat.builder_worker`), JSON on stdin and lines on stdout. It
  generates (`runner.generate`), reads the generated board (pcbnew stays out of the studio server) and returns parts,
  cells, nets, courtyard areas and the facts document. The server relays its progress lines as `build` events on the
  studio's event stream.
- `studio.py` additions (kept in one block, `# ---- the board builder`): `GET /build/state`, `POST /build/start`,
  `/build/facts`, `/build/facts/apply`, `/build/facts/confirm`, `/build/outline`, `/build/create`, `/build/offer`,
  `/build/search`, `/build/item`; the four `/suggest/*` endpoints accept a builder suggestion. A studio can start with no
  script and no layout script at all (only `.zen` files).
- `studio_builder.js` (served at `/builder.js`): the Build mode. It adds its own tab, panels and dialogs and hooks the page
  through globals (`S`, `render`, `renderPicker`); the page file gains one loader line.
- Settings: `[studio] builder_grid_mm`, `builder_max_fill`, `builder_aspect`.

## Phase B0: engine

TDD, text in and text out, `tests/test_builder_engine.py`, `tests/test_zen_edit.py`, `tests/test_json_edit.py`.

1. `set_constant` with `[(x, y), ...]`; refuses ragged or non-number. Golden: the polygon constant of the spec.
2. `skeleton`: docstring rule; golden for `Demo: layout.` and `Demo layout.`.
3. `find_board(wanted=)`; the board named when a folder's `.zen` declares several.
4. `zen_edit`: parse with `ast`; locate `Board(name=...)`; `config` -> `BoardConfig` -> `stackup` -> `Stackup` -> `layers`, and
   `design_rules` -> `DesignRules` -> `netclasses`; create a missing branch in place; add the needed names to the
   `board_config.zen` `load(...)` (made if absent); keyword spelling follows the file (`a = 1` or `a=1`); masked `ast`
   check (everything outside the target equal); a `config=` that is not a literal call is refused naming the expression; a
   file `ast` cannot read is refused. Reads: `read_stackup`, `read_netclasses` for prefilling forms.
5. `json_edit`: scanner over `raw_decode` for value spans; replace or insert a key in the file's indentation; `json.loads`
   before and after differ only in the target; a file that does not parse is refused. `fab_profile_target` picks the file
   by the root-vs-board rule.
6. Ops `zen_stackup`, `zen_netclasses`, `json_set` in `script_edit.OPS`/`apply_all`, so one `apply_edits` batch writes
   `.zen`, `fab-profile.json` and `placemat.toml` with one log entry.
7. `turn_crossings`: four counts from the plan's pads, via `ratsnest.mst` and `ratsnest.crossings`; the tie rule.
8. `readback`.

## Phase B1: a new board, the first loop

1. `builder_worker` and the server's `/build/start`: list `.zen` files with no layout script (`unbuilt`) in the hello and the
   start view; generate; read; progress events; a failure shows the generator's log tail and writes nothing.
2. Facts: `facts_model` (states: decided, undecided, flagged, changed, from `facts_of`, `unconfirmed_reasons`, the files);
   forms to edits; a batch = one `apply_edits`, then regenerate and read back; `gate`; confirm through `confirm_facts`.
3. Outline: `suggest_size`, rect/rounded/chamfered/disc/bore templates, the size and fill fields, `new_script`, `create_file`
   with the confirmation to follow once the script exists; the studio switches to the new script.
4. Parts list from the board data and the plan; status; filters; counts; shared nets with the selection.
5. Intents for edge, beside, searched; "Search the rest"; Show and Apply through the suggestion endpoints; undo and redo.
6. Timeline rows from the studio's resolve history, labelled by the applied log's text.
7. Page: Build tab, start dialogs, facts panel, outline dialog, parts list, relation menu.

## Phase B2: the rest of the vocabulary

Polygon (templates L, notch, cut corners, free vertex list) and slot outlines; holes; rows and rings; links ("close to a
pad"); `Near`; in-line `Centre`; rotation, `Facing`, `Turned`, suggested turn with counts; `move_statement` reordering; face,
priority, required, why; editing a placed item (`read_intent`, rewriting `at=`, `remove_constant` of orphans); the shape change
with its list of invalidated placements.

## Phase B3: existing scripts

`by hand` rows; loops and helpers refuse; insertion after the right statement; the script's own spelling; the outline editor on
`rect`, `disc`, `outline` with constant or literal arguments; the unplaced-part flow on a script someone else wrote.

## Phase B4

The spec marks it as later work (keepouts, `behind=`, `overhang=`, `Pin`, two-axis `Centre`, between two pads). Not built;
stated in the final report.

## Tests (all phases)

- Golden scripts: `tests/builder_golden.py` (fixtures: a `.zen`, the action list as data, the expected text byte for byte);
  after every action the text parses, the `ast` outside the inserted node is unchanged, and the script resolves on the
  synthetic board with the expected status per part.
- No coordinates: property test over every golden script and every offer the offer function can return.
- Size suggestion, turns, reorder, facts, undo/redo, offers, one path, start, existing scripts: as the spec's Testing section.
- Server: endpoint tests on a staged fixture project (`tests/test_studio_builder.py`).
- Page: Playwright on a scratch copy of a fixture project at desktop and 412x892 (`tests/browser/builder_check.py`, run by hand;
  it needs `uvx --with playwright` and Chrome, so it is not part of the default suite).
- Default suite before each report; new tests over 2 s go in `tests/slow_tests.txt`.

## Docs

`skills/placemat/SKILL.md` (a short paragraph: agents can point the user at the builder), `references/api.md` (the studio builder
section, endpoints, settings), `references/migration.md` under `## Unreleased`.
