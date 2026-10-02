# Finding suggestions

Date: 2026-10-02
Status: design, revised with the user's answers (2026-10-02)
Source: the user, 2026-10-02: "suggestions for resolving findings would be
great". Follows `findings.py` (kinds and severities) and the studio's Findings
tab, whose rows already hold an empty `fixslot`. The studio design's "no
editing in the page for now" is superseded for applying a suggestion; the
page still has no free-text editor.

## Problem

A finding says what placemat could not do as declared. It rarely says what
to change in the script. Someone reading `[critical] C4: no legal location
within 3.0 mm of (12.0, 8.5) (courtyard x41)` has to know which declaration
to edit and with what form. Some sentences carry advice in prose (a keepout
crossing: "move it, reshape it, or name its net in the keepout's allow="; a
chamfer: "a smaller chamfer= there keeps clear"), most carry none, and
nothing can act on the prose.

A suggestion is therefore a change to the layout script, worded in the
board's own terms ("Move C4 above C1"), that can be applied with one action
and shows whether it helps before it is written.

What exists to build on:

- `Finding(kind, text, severity)` (`findings.py`), pickled and stored in the
  reuse cache as `[kind, text, severity]` (`reuse.py`).
- Every declaration records the file and line it was declared on
  (`preview_json.declared_sites`), and `studio_diff.declaration_span` finds
  the statement that holds a line with `ast`.
- The studio: a watcher that re-resolves after every change to a file the
  script depends on (`studio_watch.py`), a warm worker (`studio_worker.py`)
  that resolves as `preview` does and replays unchanged steps, a `Record` per
  resolve with the text of each file at its start, a compare of any two
  records (`Studio.compare`: plan diff, line diff, trace, findings gained and
  lost, score change), and a script view linked to the board.
- Per-script settings in `placemat.toml` (`[scripts."path".section]`).

## Design

One suggestion engine, two surfaces, one application path. A suggestion is a
**structured script edit plus its wording**, made where the finding is
raised. Both surfaces read the same suggestion records (the structure
`run.json` carries) and apply them through one entry point,
`suggestions.apply_suggestion(suggestions, id, dry_run=False)`: the command
`placemat apply <id>` calls it, and so does the studio. The digest check, the
edit and the write are in that one function; the studio adds no second
method. The studio shows the diff first and offers a try, both built on the
same call with `dry_run=True`.

### What a suggestion is

```
Suggestion
  text      the wording, in the board's terms: "Move C4 above C1"
  edit      what to write (below)
  rank      1 is tried first
  id        short, per run or resolve: "s3a" (finding 3, suggestion a)
  digests   {file: digest} of each file the edit targets, at the plan
```

The same record, as JSON, is what `run.json`, `preview --format json` and the
studio's plan JSON carry.

There is no confidence and no flag that a suggestion is certain: rank is the
order to try, and the studio's try (below) measures the result. A finding with
no suggestion has none; there is no placeholder.

**Concrete, in intent forms.** `text` and `edit` name the parts, pads, nets,
faces and forms of the board. Every value an edit writes is a relation, a
keyword or a setting, never a coordinate or an offset:

| Wording | What the edit writes |
|---|---|
| "Place C4 beside C1, on its north side" | `at=Beside(c1, Edge.NORTH)` on C4's `board.place` |
| "Let C4 take the back face too" | `face=Face.EITHER` on C4's `board.place` |
| "Place C4 before the parts that crowd it" | `priority=Priority.HIGH` |
| "Let net SIG cross keepout `ant`" | `SIG` added to `allow=` of that `board.keepout` |
| "Let the SIG track under GND at the crossing" | `bridge=True` on that `board.track` |
| "Pull C1 pad 1 to U1 pad 3 harder" | `weight=LinkWeight.X` on that `board.link` |
| "Allow U1 to turn to any bearing" | `rotations=Turns.ANY` |
| "Move the label of J1 to its south side" | `side=Edge.SOUTH` on that `board.label` |
| "Let a via give way further: place.via_move 1.0" | a setting in that script's settings table |

A value taken from a measurement (the limit a link achieved, the clearance
that fits) is quoted in the wording and written as the measured figure.

**An edit** is data, not text:

```
Edit
  file      the script, a module it imports, or placemat.toml, by name
  target    the declaration it changes: the item key (or the key of a link,
            track, keepout, label, escape, accept), the file and line it was
            declared on, and the file's digest when the plan was made
  op        one of the operations below
  value     an intent expression, not source: {"form": "Beside",
            "args": [{"item": "C1"}, {"enum": "Edge.NORTH"}]}
```

Operations, each a function of the file's text:

| op | does |
|---|---|
| `set_kwarg(name, value)` | adds or replaces a keyword on the target call |
| `remove_kwarg(name)` | removes one |
| `set_arg(index, value)` | replaces a positional argument |
| `edit_list(arg, add / remove / move, element, before / after)` | changes a list or tuple literal argument: add a net to `allow=`, reorder the members of a `board.row`, drop a waypoint from a track's points |
| `insert_statement(after, value)` | adds a declaration after the target's statement (a `board.place` for an undeclared part, a `board.fanout`, a `board.rule`) |
| `remove_statement` | removes a call that stands alone (an `accept` that matched nothing) |
| `toml_set(table, key, value)` | sets a key in the script's own settings table of the nearest `placemat.toml` |

Rendering a value to source reuses the script's own spelling. `{"item":
"C1"}` is written as the expression the script used where it declared C1
(the first argument of that call: `c1`, `Part("c1")`), found in the AST, never
a name made up. A form or enum the file does not import is not suggested.

An edit is offered only where it changes what it says it does. If the target
call also declares other items (a call in a loop or a helper that runs for
several parts), the suggestion is not offered, since the edit would move the
others too. The plan's sites tell how many items share a `(file, line)`.

### Where they are produced

At the place a finding is raised, where the facts are known. The finding
carries what it needs:

```python
Finding("unplaced", text, case="unplaced.search",
        facts={"item": "C4", "dominant": "courtyard", "blockers": ["C1", "R2"],
               "free_sides": {"C1": ["NORTH", "EAST"]}, "faces": "front"},
        suggestions=[...])
```

- `Finding` gains `case` (a dotted id, `kind.case`) and `suggestions`, a list
  of `Suggestion`. Neither changes the sentence, its equality or its severity.
  The reuse cache stores them with the finding so a replayed step keeps them
  (`[kind, text, severity, case, suggestions]`; an older entry has none).
- The wording and the edit for a case are built by a function in one module,
  `suggestions.py`, that the raising site calls with its facts
  (`suggestions.unplaced_search(facts)`). The site decides nothing about
  wording; `suggestions.py` decides nothing about which finding it is. A case
  with several levers returns several suggestions in order; a lever that does
  not apply to these facts is not returned.
- A fact a suggestion needs that the site does not have (which sides of a
  neighbour are free, how a pad is walled) is measured at the site, from the
  occupancy the site already holds, not recomputed later.
- Findings made from plain-string copper notes (about thirty
  `ctx.notes.append("...")` sites that `_plan_copper` wraps as `copper`
  warnings) are converted to `Finding`s with a case as their suggestions are
  written. Until then those have none.

A suggestion is bound to a script by its target: the item key, the file and
line from `declared_sites`, and the digest of the file at the plan. Locating
the call uses the AST, not the line alone: the call on that line whose
function and first argument match the declaration. If it is not found
exactly once the edit is refused.

### The shared edit function

`script_edit.py`, pure, standard library only (the studio takes no new
dependency): `apply(edit, text) -> new_text`.

- It parses with `ast`, finds the target call, and splices source text at the
  node positions the AST gives (`lineno`, `col_offset`, `end_lineno`,
  `end_col_offset`, converted from UTF-8 offsets). Everything outside the
  spliced range, comments and layout included, is byte for byte what it was.
  Python's `ast` keeps no comments or layout, so a CST library is not needed
  to keep them: the edit never reprints a node it did not change.
- A keyword is added after the last argument. If the call spans lines and the
  last argument stands on its own line, the new keyword goes on its own line
  at the same indent, with the trailing comma the call already uses;
  otherwise it follows `, ` on the same line.
- After the splice the result is checked: it parses, and the AST with the
  target node replaced equals the original AST, so nothing but the intended
  call changed. A failed check refuses the edit.
- `toml_set` edits the one `key = value` line in the named table, or appends
  the key to it, or the table, at its end. The TOML is parsed with `tomllib`
  before and after to check the value landed and nothing else moved.
- The function also gives the inverse: `apply` returns the edit's before and
  after text, and `undo` is the reverse splice (below).

### The studio

**Showing a suggestion.** A finding row's `fixslot` shows the rank 1
suggestion's text with a "more (n)" control for the rest. Each has Show,
Try and Apply. A suggestion whose edit targets another item (the neighbour
in "Move C4 above C1") names it, and Show selects that declaration's line.
The page reads the suggestions from the finding in the plan JSON, the same
records `run.json` holds.

**One path.** The three endpoints take `{resolve, id}`, look the suggestion up
in that resolve's findings, and call `apply_suggestion` on it. The client
never sends source text, so the endpoints cannot write arbitrary content.

**Show: the diff first.** `POST /suggest/show` is `apply_suggestion(...,
dry_run=True)`: it returns the unified diff and the lines changed, and writes
nothing. The page opens the script view at the file, marks the changed lines
as an overlay (old and new), and shows Apply and Cancel.

**Try: resolve the dry-run result.** `POST /suggest/try` takes the edited text
the dry run returns and asks the worker to resolve the script with it in
place of the file on disk. The worker's script loader takes an overlay
`{file: text}` and reads from it first, for the script and for any module it
imports, with the real path as the file name, so declaration lines and
relative paths are unchanged. The try replays unchanged steps from the last
real record's reuse and does not write its own back, so it cannot disturb the
next real resolve. It runs in the same warm worker only when no real resolve
is running or pending; a change to a watched file cancels it at its next
step, as it cancels a resolve. One try at a time, with a timeout,
`[studio] try_timeout_s`.

The result is a record that is not added to the history, compared with the
resolve the suggestion was made on by the existing `Studio.compare`. The page
shows it in the compare view, marked "try, not written":

- whether the finding cleared: the same `(kind, case, item)` is absent from
  the try's findings;
- findings gained and lost, with their severities;
- items that moved, ghosts and arrows;
- the score's change;
- the diff of the script.

**The try replaces a "checked" flag.** An earlier version of this design
marked suggestions `checked` where the raising code had measured that they
clear. A try measures the same thing for every suggestion, on the real
resolve, including what else the edit changes, and it needs no per-site
proof. The page offers the try on click, not automatically, because each is
a resolve (open question 2).

**Apply: written to the file.** `POST /suggest/apply` is
`apply_suggestion(..., dry_run=False)`, which:

1. checks that each target file's digest on disk equals the digest in the
   suggestion (the text the plan was made from). If a file changed, it
   refuses and writes nothing; the page has already been told the files
   changed and marked the plan stale, and shows the new plan's suggestions
   instead. No relocation is attempted: a refusal is cheaper than an edit to
   the wrong line;
2. applies the edit and writes the file atomically (a temporary file in the
   same directory, then `os.replace`, keeping the mode);
3. appends `{id, file, before, after, at}` to the applied log
   (`.placemat/applied.jsonl`, shared with the command line).

The watcher then sees the change as it sees any edit and re-resolves; the
compare with the previous resolve shows what the edit did, and the history
lists it as "applied from a suggestion: <text>".

Only files the studio already watches are written (the script, its modules,
`placemat.toml`), and only under the project root.

**Undo.** The page shows "Undo" beside the applied edit and in the history
row. `POST /suggest/undo` calls the same undo function as `placemat apply --undo`: it restores the logged `before` text if the file's
current text equals the logged `after` (nothing else has touched it since);
otherwise it refuses and says so. Undo of the last applied edit is a stack:
each undo takes the one before. Undone edits are logged as such. The same
log serves the command line's undo.

### The command line

The same suggestion records, through the same `apply_suggestion` the studio
calls: one edit, one digest check, one write.

- `run` (and `preview`) print, under each printed `critical` and `warning`
  finding, a line `    try s3a: Move C4 above C1`. The id is short and tied
  to the run that made it.
- `run.json` `finding_details[i]` gains `suggestions`: `[{id, text, rank,
  edit}]` with the edit as data, and the run record keeps the digest of each
  file an edit targets. A record without the field reads as none.
  `preview --format json` carries the same.
- `placemat apply <id> [--script PATH] [--dry-run]` finds the latest run
  record for the script, rebuilds the edit and prints the diff; without
  `--dry-run` it applies it. It checks each target file's digest against the
  record's: on a mismatch it refuses and says the script changed since the
  run, and does not touch any file. `--dry-run` is the same call with
  `dry_run=True`, which the studio's Show uses. `placemat apply --undo` reverts the last applied edit with the same
  rule as the studio's undo.
- The agent-facing skill documents the field and the command: read
  `finding_details[i].suggestions` after reading the finding as a claim about
  the script; `placemat apply <id> --dry-run` shows the diff; a suggestion is
  a candidate, and the run decides whether the finding cleared. `api.md`
  "Findings and severities" gains a "Suggestions" subsection with the shape
  and the table of cases; a test keeps the table and `api.md` in step.

### Outputs, summarised

| Surface | Carries |
|---|---|
| studio plan JSON, the `findings` event | each finding's `case` and `suggestions`, the same records as `run.json` |
| studio endpoints (token and host as the others) | `/suggest/show`, `/suggest/try`, `/suggest/apply`, `/suggest/undo`, each a call of the shared function |
| `run`, `preview` console | `try <id>: <text>` under critical and warning findings |
| `run.json`, `preview --format json` | `finding_details[i].suggestions` with the edit as data |
| `placemat apply` | applies or undoes by id |

Settings: `[studio] try_timeout_s` (default 60) and `[studio] apply` (true;
false makes the studio show suggestions and diffs but refuse to write). Both
are studio settings and not part of a run's id.

## Cases and suggestions

Forms are those in `api.md` at this version. Each row's wording uses the
names from the finding. Rank follows the order of the list. A case or
circumstance not listed gives no suggestion. "on X" means the edit is to X's
declaration, where X is a blocker or neighbour the finding names.

### unplaced

| Case | Suggestions | Edit |
|---|---|---|
| `unplaced.search`: no legal spot within R of the hint | 1. "Place C4 beside C1, on its <free side> side": one per free side the site measured, up to `[studio] suggestions_max`. 2. "Place C4 before the parts that crowd it". 3. "Let C4 take the back face too". 4. "Let C4 turn to any bearing" for an item on a point; "Let C4 take all four turns" where it is restricted. 5. "Move R2 above C1" / "Place R2 beside U1 with a wider gap": `on` the blocker named by the dominant refusal. 6. "Search C4 within a larger radius". 7. when the dominant refusal is a drawn envelope: "Judge parts by their courtyards" | `set_kwarg at=Beside(...)`, `priority=Priority.HIGH`, `face=Face.EITHER`, `rotations=`, `set_kwarg` on the blocker, `radius=`, `toml_set place.envelope` |
| `unplaced.search`, dominant refusal a reservation | by the reservation's source: "Let C4 into keepout `ant`" (`Part` added to `allow=`); "Stop the label of J1 reserving room" (`reserve=False`); "Shorten the fanout of U1" (smaller `depth=` on `board.fanout`) | `edit_list allow`, `set_kwarg` |
| `unplaced.search`, dominant refusal copper | "Let the SIG track avoid C4's spot": a `Past` waypoint on the track, and the items above | `edit_list` on the track's points |
| `unplaced.search`, a via could not give way | "Thin the drops of cell X" (`drops=Drops.HALF`); "Let a via move further: place.via_move"; "Let a via leave its pad further: place.via_leave" | `set_kwarg`, `toml_set` |
| `unplaced.search`, a rider refuses | "Place R3 (rides C4) beside C4 with a wider gap", or "Let R3 be searched" | `set_kwarg at=` or `remove_kwarg at` on the rider |
| `unplaced.pocket`: no pocket fits | "Pull C4 toward U1 pad 3" (a `board.link`), "Place C4 beside U1", "Let C4 take the back face too", "Search C4 on a finer step" | `insert_statement board.link`, `set_kwarg` |
| `unplaced.slide`: no room along an edge, line, row, run or ring | "Put C4 on the <other> edge" (`OnEdge`), "Turn C4" (`rotation=`), "Take R6 out of the row" | `set_kwarg at=OnEdge(...)`, `edit_list` on the row's items |
| `unplaced.block`: cannot lay out / no legal spot | "Place satellite R3 on its own", "Let the block turn to any of its turns", "Let satellites stand further off: place.block_gap_reach" | `edit_list` on `satellites=`, `insert_statement board.place`, `set_kwarg`, `toml_set` |
| `unplaced.bearing` | "Step bearings finer: place.bearing_step" | `toml_set` |
| `unplaced.rides` | none; the parent's own finding is the fault | - |

### fixed

| Case | Suggestions | Edit |
|---|---|---|
| `fixed.part`: a decided part not legal | "Let C4 be searched" (drop its `at=`), "Slide C4 along its line" (`Centre(None, y)` where it is pinned on both axes), "Move C1 above ...": on the other item named, "Take C4 on the back face" | `remove_kwarg at`, `set_kwarg`, on the other item |
| `fixed.cutout`: web under the minimum or touching the outline | "Place cutout `vent` against the connector's edge instead", "Make the web 1.0 mm" (the minimum, from the finding) | `set_kwarg at=` on `Cutout`, `set_kwarg web=` on the outline form |
| `fixed.keepout` | as `fixed.part`, on the keepout's `at=` and `margin=` | `set_kwarg` |

### copper

| Case | Suggestions | Edit |
|---|---|---|
| `copper.meets`: a track, via or pour meets another net's copper, pad or hole | 1. a track whose waypoints steer it into a pad: "Draw the SIG track pad to pad" (waypoints removed). 2. a chamfered or arc corner: "Cut the corner of the SIG track smaller" (`chamfer=`, `radius=` smaller, measured). 3. "Route the SIG track past U1 pad 4" (a `Past` or `Between` point). 4. "Put the SIG track on the back layer". 5. a via: "Put the via at the nearest free spot to U1 pad 4" (`FreeSpot(near=PadRef(...))`). 6. a pour of exact points: "Fit the GND pour to its pads" (`swallow_pads=True`). 7. "Lower the clearance between SIG and GND to 0.15 mm" (`board.rule`) | `edit_list`, `set_kwarg`, `insert_statement` |
| `copper.keepout`: copper crosses a keepout | "Let net SIG into keepout `ant`" (`allow=`), "Keep keepout `ant` off the back layer" (`layers=`), "Let keepout `ant` forbid parts and vias only" (`excludes=`) | `edit_list`, `set_kwarg` |
| `copper.cross`: two tracks cross and neither may bridge, or one crosses a fixed track | "Let the SIG track pass under GND" (`bridge=True`), "Let GND yield to SIG" (`priority=`), "Put the SIG track on the back layer, through a via" | `set_kwarg`, `edit_list` |
| `copper.corner`: the 45 past a corner leaves no 45 | "Take the SIG track's corner past U1 further out" (`across=`), "Bend the SIG track at its end" (`bend=`), "Cut its corner smaller" | `set_kwarg`, `edit_list` |
| `copper.not_drawn`: a declared track, via, pour or stitch not drawn | by the cause the note names. An arc that does not fit: "Use a smaller radius on the SIG track". A track through an item: as `copper.meets`. A pour with no way round: "Take pad 5 out of the GND pour". A stitch with no room: "Stitch GND at a smaller pitch" (`pitch=`, `size=`) | `set_kwarg`, `edit_list` |
| `copper.note` (notice): a waypoint drawn pad to pad | "Drop the waypoint" | `edit_list` remove |

### escape, pair, link

| Case | Suggestions | Edit |
|---|---|---|
| `escape_walled`, `escape_closed`: a pad closed or walled in by C1, R2 | "Move C1 further from U1" (a wider gap in its relation, or another side), "Keep U1's north side clear" (`board.fanout(u1, depth=, sides=)`), "Turn U1", "Keep the lanes of U1 pins 3 and 4 clear" (`board.escape`) | `set_kwarg`, `insert_statement` |
| `escape_crossed`: escapes of U1 pins 3 and 4 cross | "Turn U1 so the pins' targets match their order", "Place R2 on the side of U1's pin 4" | `set_kwarg rotation=`, `at=` |
| `escape_lane`: a declared lane blocked by C1 | "Move C1 off the lane", "Stand the lane's via further along" (`depth=`, `vias=`), "Allow the lane's via further: place.escape_via_reach" | `set_kwarg`, `toml_set` |
| `pair_crossed`: DP and DN cross between U1, U2 | "Swap R7 and R8 in the row" (the pair's parts), "Turn U2 by 180 degrees" (`rotation=Turned(u2, 180)`) | `edit_list` move, `set_kwarg` |
| `link_over`: C1 pad 1 to U1 pad 3 is 5.1 mm, over its 4.0 mm limit | 1. "Place C1 beside U1". 2. "Pull C1 to U1 pad 3 harder" (`weight=`). 3. "Place C1 before the parts that crowd it". 4. "Raise the limit to 5.1 mm" (the measured figure) | `set_kwarg` on the place or the link |

### label

| Case | Suggestions | Edit |
|---|---|---|
| `label.sits_on`, `label.no_spot` | "Move the label of J1 to its south side" (one per side not tried), "Make the label of J1 smaller" (`size=`) | `set_kwarg side=`, `size=` |
| `label.not_drawn` (notice) | none | - |

### setup, vias

| Case | Suggestions | Edit |
|---|---|---|
| `setup.undeclared`: no declaration places C9 | "Place C9 searched from its links" | `insert_statement board.place(c9)` |
| `setup.lane_unused`: U1 pin 3's lane reserved, no track | "Draw a track from U1 pin 3's lane", "Take pin 3 out of U1's escape" | `insert_statement board.track`, `edit_list` on `pins` |
| `setup.pitch`: net class does not fit the pads' pitch | "Lower the clearance within U1 to 0.15 mm" (`board.rule(..., within=)`, the figure that fits) | `insert_statement board.rule` |
| `setup.frame_reach`: an item outside a fitted frame's axis | "Make the frame 30 mm high" (the item's extent), "Place R6 inside it" | `set_kwarg height=` |
| `setup.accept`: an `accept` that matched nothing or was not needed | "Remove the accept for keep-out SIG" | `remove_statement` |
| `vias` warnings: a via dropped, fewer than declared | "Let a via move further: place.via_move", "Let a via leave its pad further", "Thin the drops of cell X" | `toml_set`, `set_kwarg drops=` |

The kinds `fab`, `facts`, `split`, `route`, `needs`, and the notices of
`vias` and `setup` (a layer the board lacks, a rule not carried, a look-ahead
dropped) have no script edit, so they have no suggestion.

## Charter fit

- *Intent, not coordinates*: an edit writes relations (`Beside`, `OnEdge`,
  `Past`, `Between`), keywords (`face=`, `priority=`, `bridge=`, `allow=`,
  `weight=`) and settings, never a `Location`, an offset or a `reach=`
  distance. A number in an edit is a measured fact from the finding (the limit
  a link achieved, the clearance that fits), and the diff shows it before it
  is written.
- *Judged as KiCad judges*: lowering a clearance or a limit is a suggestion
  the user sees as a diff and chooses; nothing is applied without the click or
  the command.
- *Project-agnostic*: the module, the table and the tests name forms, never a
  project, board, part or net.
- *Tunables are settings*: no weight, threshold or share in `suggestions.py`.
  The dominant refusal is the one with most refusals, ties broken by the
  order `_blame_text` lists them; the count of suggestions per finding is
  `[studio] suggestions_max`.
- *Fitted, never zones*: no suggestion turns a pour into a zone or a plane.
- *Decide alone / ask first*: placemat's agent builds this; applying a
  suggestion to a project's script is the user's act in the studio or the
  command line.

## Phases

1. `Finding.case` and `suggestions`; `script_edit.py` with `set_kwarg`,
   `remove_kwarg`, `edit_list` and the undo; the cases of `unplaced`,
   `fixed`, `copper.keepout`, `copper.cross`, `link_over`, `label`; the
   `suggestions.apply_suggestion` with `dry_run`; the studio's slot, Show,
   Apply and Undo; the applied log.
2. Try (the worker's overlay and the compare of a try); `escape_*`,
   `pair_crossed`, `copper.meets`, `copper.not_drawn` and `setup`;
   `insert_statement`, `remove_statement`, `toml_set`.
3. The command line: `try` lines, `run.json`, `placemat apply`; `api.md` and
   `SKILL.md` text.

## Out of scope

- A free-text editor in the studio page. The script view applies edits that
  suggestions make, and shows them; typing in it stays with the user's editor
  and agents.
- Applying several suggestions at once, or a "fix all".
- Suggestions for design-check verdicts and DRC violations, which are not
  findings.
- Learning from what worked before, and any estimate of how likely a
  suggestion is to clear a finding. The try measures it.
- Changing a finding's kind, severity or sentence, or the run score.

## Testing

All tests use small synthetic boards and scripts, in the style of the
existing findings and studio tests, with generic names (`U1`, `C1`, `R2`, a
net `SIG`); no project or board name appears in a test, a table row or a
fixture.

- `tests/test_script_edit.py`, pure text in and out:
  - each op on a one-line call, a multi-line call with a trailing comma, a
    call with a comment after an argument, a call with `*args` or `**kw`, and
    a keyword that is already present; comments and layout outside the edited
    range are byte for byte unchanged; the result parses; the AST outside the
    target is equal;
  - a script that spells an item as a variable, as `Part("c1")` and through
    an alias gets the script's own spelling in the value;
  - a target call that declares several items (a loop) is refused; a call not
    found exactly once is refused; a changed digest is refused;
  - `edit_list` add, remove and move; `toml_set` into an existing table, a new
    key, a new table, and a table for another script left alone; `undo` is
    the exact inverse, and refuses when the text is not the one the edit made.
- `tests/test_finding_suggestions.py`:
  - every `case=` raised in `src/placemat` has a builder in `suggestions.py`
    and every builder is raised somewhere (by scanning the source);
  - for each case, a synthetic script that produces the finding: the
    suggestions name items and pads that exist in the plan, rank is 1..n, and
    each edit applied to the script gives a script that parses and whose call
    has the keyword written (checked against `inspect.signature` of the board
    method, the enum against `placemat`'s exports, a setting against the
    settings table);
  - the edits that claim to clear a finding do: for a waypoint, a chamfer, a
    bridge, an allow, a link weight and a priority, the edited script is
    resolved and the finding is gone;
  - no value an edit writes is a `Location`, a coordinate pair, `reach=` with a
    number, `board.figure`, or `board.plane` for a pour;
  - the cache and pickle keep `case` and `suggestions`; a three-field cache
    entry loads with none.
- One path: the studio's endpoints and `placemat apply` call
  `apply_suggestion` (a test replaces it and sees both call it); a suggestion
  read from a studio plan equals the one in `run.json` for the same script.
- Studio: `/suggest/show` returns the diff and writes nothing; `/suggest/apply`
  writes the file, appends the log, and the watcher resolves the result; a
  file changed between the plan and the apply gives a conflict and no write;
  `/suggest/undo` restores the text and refuses when the file has moved on;
  the endpoints refuse a request without the token and a body that names
  anything but a resolve, a finding and a suggestion; with `[studio] apply =
  false` apply is refused.
- Try: the worker resolves with an overlay and the file on disk is not read
  for the overlaid file or touched; a try does not change the next real
  resolve's reuse; a change to a watched file cancels a try; a try reports the
  finding cleared when the edit clears it and reports findings gained when it
  adds one.
- Page: the slot is empty and hidden for a finding with none, shows rank 1 and
  "more" for several, Show marks the changed lines, and the try result renders
  in the compare view marked as not written.
- `run` prints a `try` line under critical and
  warning findings only; `run.json` carries the suggestions and the digests;
  `placemat apply <id> --dry-run` prints the diff and writes nothing; apply
  refuses when the script changed since the run, and with an unknown id;
  `--undo` matches the studio's.
- The existing suites for findings, severity, reuse, the studio and the report
  pass. `fixtures/bench.py --jobs 2`: no score moves (no placement or finding
  sentence changes).

## Open questions

1. Where one lever has several variants (which side of C1 to place C4 on), should the studio offer one suggestion per variant up to a limit, or one best guess with the others found by Try?
2. Should Try run only on a click, or also on its own for the rank 1 suggestion of each critical finding when the studio is idle? Each try is a resolve, so on its own it costs CPU.
3. Should an edit be offered when its target call declares several items (a loop or a helper that places many parts), written into the loop for all of them, or not offered, as the design has it?
4. Is writing the script's settings table in `placemat.toml` (for a setting suggestion) in scope, by a line-level edit that keeps the rest of the file as it is, or should suggestions touch the layout script only?
5. May the studio write files when it was started with `--host` for another address than 127.0.0.1, or should apply be refused there unless `[studio] apply` is set explicitly?
6. Is undo as a stack (each undo takes the one before, refused if the file moved on) enough, or should an undo that finds the file changed try to reverse its own lines?
