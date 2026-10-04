# A module's alternative arrangements, chosen by the board

Date: 2026-10-04
Status: draft
Source: a board's session, 2026-10-04, and the user's approval of points 1 to 3 of its proposal. Point 4 (a free
board-level override of a member's place) is not in this spec.

Builds on `2026-09-22-fragment-layers-design.md` and `2026-10-02-fragment-notes-out-of-sight-design.md` (what a
fragment carries for the board that stamps it), `2026-09-30-split-modules-for-placement-design.md` (a cell is one
piece), `2026-10-01-cell-bearing-search-design.md` and `2026-10-01-either-face-design.md` (a cell's turn and face as
choices the search makes), and `2026-10-03-declared-copper-room-design.md`.

## Problem

A cell is stamped rigidly and the board places it as one piece, so every member's side and turn inside the cell is
fixed by the module's script before the board exists. Cells repeatedly miss a spot or block routing because of one
member:

- a FET whose gate faces the wrong tab, so a pour cannot reach the sources;
- an input bypass facing away from its partner;
- one capacitor that blocks the cell's best spot.

Each fix is a module edit, a module run and a board run, and each edit trades one board's concern against the
module's own. SKILL.md ("Shaping modules for the board") already tells the agent to turn a bypass or move a part to
the other side of its IC. The module often has two layouts that serve its own reason equally well (a bypass on
either side of the same pin), and only the board can say which one fits.

What is wanted:

1. the module declares alternatives for named members, or for a named group of members, by intent;
2. the module run lays out and checks every alternative against the module's own links, limits and checks, so each
   one offered is proven on the module's own terms;
3. the board's search treats a cell's alternative like its rotation: one more choice per candidate, scored by the
   board's links, crossings and room, and recorded in the run and the lock.

## Terms

An **arrangement** is one complete set of member places for a module: every member's position, turn and face, and
the module's own copper as laid for them. The module as its script says it, with no alternative taken, is the
**default** arrangement.

The word is chosen because "variant" is taken twice already: a `.zen` can declare one `Layout` per variant
(api.md, "Modules"), and explore tries "variants" of a placement.

A module's members are the same in every arrangement. An arrangement moves, turns or flips members; it never adds,
removes or swaps a part. A different part is a capture change.

## Declaration in the module script

Alternatives are written in the module's layout script, beside the declaration they change, with the same forms a
`place()` takes. No coordinates: an alternative is a relation (`Beside`, `Pin`, a turn), as the default is.

### One member

```python
board.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST), why="bypass at VIN")
board.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
board.alternative(Part("r_pull"), "turned", rotation=180)
```

`board.alternative(item, name, **keywords)` adds an option to the item's `place()`. The `place()` call stays the
default option of that item. An option takes the keywords of `place()` that change where an item goes (`at=`,
`rotation=`, `rotations=`, `face=`, `radius=`, `step=`) and inherits every other keyword, and the keywords it does
not give, from the item's `place()` (so `rotation=180` alone keeps the `at=`). `why=` may be given and is shown with
the option.

The item is a part of the module. An item with no `place()` in the script, a row's or a block's member, a part laid
by `board.row()`, a ring or a block, is refused: an arrangement of a row is a named group (below).

A searched member (no `at=`, or `Near`) may have options as well: each arrangement is a full resolve of the module,
so a searched member finds its spot in each.

### A group

```python
board.arrangement("mirrored",
                  Alt(Part("q1"), at=Beside(Part("u1"), Edge.EAST), rotation=180),
                  Alt(Part("q2"), at=Beside(Part("u1"), Edge.WEST)),
                  why="gate toward the east tab")
```

`board.arrangement(name, *alts, why="")` is one arrangement the script names, made of the members' options given
in `Alt(item, **keywords)` (the same keywords as `alternative`). Members not named keep their `place()`. A group is
for members whose alternatives only make sense together, and for a row or a pair that moves as a unit.

### What the arrangements of a module are

- the default;
- every combination of the per-member options (the product: each item contributes its options and its default);
- each named group.

An arrangement is identified by `choices`, a record `{item key: option name}` for a product arrangement or
`{"group": name}` for a group, and by an **id**, its text form, used in the lock, in findings and in
`arrangements=` on the board: the pairs `item.option` joined by `+` in item order (`c_in.east+r_pull.turned`), or
the group's name. `default` is the default's id. Option and group names are lower-case words, digits and `_`;
`default` and a name that is also another arrangement's id are refused.

Two arrangements that resolve to the same member places and copper (compared after the run) are one: the later is
dropped with a notice naming both.

### Limits

Growth is multiplicative, so two settings bound it, under `place`:

- `place.arrangement_options_max` (count, default 4): the most options one item may have, its `place()` included;
- `place.arrangements_max` (count, default 8): the most arrangements a module may have, the default and the named
  groups included.

A module that declares more is not partly accepted: it is a finding `arrangement.limit` (facts: the counts and the
two limits; severity warning), the module run lays out the default only, and the fragment carries no
arrangements. The finding says to name groups for the combinations that matter. `place.arrangements` (bool, default
true) is the switch: false lays out the default only, as before this change.

## What the module run does

### Resolving

The script runs once and collects its declarations, as today. The alternatives are declarations, so the run then
resolves the board once per arrangement: the default first, then each other, in the order the options and groups
were declared. A resolve for an arrangement is the same resolve with the arrangement's options laid over the items'
intents (a copy of each changed `PlaceIntent`); everything else the script declared (copper, keepouts, planes,
pours, links, limits, checks, rules) is shared. The board is put back between resolves from a snapshot of its
declarations' fields, as the copper-room passes already do (`Board._redo_check`, `_Redo`).

There is one generate (`pcb layout`) for the module, whatever the arrangements.

The resolves are sequential. A module run with k arrangements costs about k times one.

Copper declared by intent holds in every arrangement. A track whose waypoints cannot be drawn in an arrangement is
that arrangement's finding, and (below) keeps it from being offered. Copper declared for one arrangement only is
not part of this change (Decisions, 8).

### Proving

An arrangement is proven by the same judgement the default gets, on its own board:

1. its resolve places every member, with no critical finding;
2. the plan is written to a scratch board and KiCad's DRC is run on it; the `real` buckets are empty;
3. the design checks run on that board (`checks.run_checks`, `board.accept` applied): no failed verdict, including
   the limits and `Pm.Limit` pairs, hot loops and keep-outs the module declares.

Warnings, notices and measures are recorded and do not stop an arrangement being offered. An arrangement that fails
any of the three is **not offered**: it is written to the record with its refusals and is absent from the fragment.
The default is always written, as today, whether or not it passes.

The scratch board and everything the run keeps for an arrangement are under the run directory:
`.placemat/runs/<id>/arrangements/<arrangement id>/` holds `layout.kicad_pcb`, `drc.json`, `reuse.json` (and
`reuse.partial.jsonl` while it runs) and, with `--render`, its render. A stopped run (`--max-time`, a crash)
resumes each arrangement from its own partial record, so finished arrangements are not laid again.

### The record

`run.json` is the default arrangement's, as it is now: its metrics, findings, verdicts, steps and placements are
unchanged. It gains one field:

```json
"arrangements": [
  {"id": "default", "choices": {}, "offered": true,
   "metrics": {"drc": {...}, "findings": {"warning": 1}, "measures": {...}}, "dir": "arrangements/default"},
  {"id": "c_in.east", "choices": {"c_in": "east"}, "offered": true, "metrics": {...}, "dir": "arrangements/c_in.east"},
  {"id": "mirrored", "choices": {"group": "mirrored"}, "offered": false,
   "refused": [{"form": "drc", "bucket": "clearance", "count": 2}, {"form": "verdict", "check": "loop", "item": "c_in"}],
   "metrics": {...}, "dir": "arrangements/mirrored"}
]
```

`refused` holds records (a form and its facts), rendered to a sentence only where shown. Each arrangement that is
not offered also raises a finding `arrangement.refused` on the run (facts: the id, the refusals; severity warning),
so a module whose declared alternative failed does not read as clean. Nothing else about the module run's gates
changes: the default's verdicts decide whether the module passes.

The run score is the default's. An arrangement's measures (the run score's inputs, `score.plan_measures`) are
recorded for it so the studio and a reader can compare, and are not summed into the module's score.

### What is written to the fragment

The fragment board `pcb layout` stamps is the default arrangement, as written today. Every other offered
arrangement travels as a text on User.Comments, the transport the faces and the clearance rules already use. A
sidecar beside the fragment is not possible for the reason given in `2026-10-02-fragment-notes-out-of-sight-design.md`:
the stamping board does not know where the module's layout folder is.

One text per offered arrangement: `placemat arrangement <json>`, the document being

```json
{"v": 1, "id": "c_in.east", "choices": {"c_in": "east"}, "base": "<digest>",
 "members": [{"inst": "u1", "x": 12.4, "y": 3.0, "rotation": 90.0, "face": "front"}, ...],
 "ops": [{"kind": "track", "net": "VIN", "layer": "F.Cu", "width": 0.3, "points": [[..], ..]}, {"kind": "via", ...},
         {"kind": "pour", ...}, {"kind": "zone", ...}, {"kind": "text", ...}],
 "keepouts": [{"name": "...", "polygon": [...], "layers": [...], "excludes": [...], "allow": [...]}]}
```

- `members` lists every member, by its instance path within the module (what `CellGeom.member(suffix)` matches), at
  its place in the fragment's own frame: the same frame the default's items are in.
- `ops` are the module's copper for the arrangement, as the plan holds them (`Track`, `Via`, `Pour`, `Text`,
  `Zone` in copper.py) in a JSON form the writer reads back. This is the one new codec in the change; the
  studio's plan.json copper is a drawn form and cannot be written.
- `keepouts` are the rule areas the arrangement declares, as `RuleArea` records. A keepout shaped by a member
  differs per arrangement.
- `base` is a digest of the default arrangement's member places. A parent whose stamped members do not match it
  (a fragment edited by hand in KiCad after its run, or a stamp that moved members) ignores the arrangements of
  that cell with a finding `arrangement.stale` on the parent, so a note never poses members from a layout it was
  not made for.

Net names in `ops` are the fragment's; the parent maps them as it maps a stamped keepout's `allow=` nets
(`board_geometry.stamped_net`).

The note is dropped from the parent's written board with the faces and rule notes (`_drop_stamped_notes`).
A fragment run before this change carries none and reads as a cell with the default only.

Size: a module's arrangement is a few kilobytes. If a text proves too long for KiCad or the generator, the note is
split into numbered texts of `place.arrangement_note_chars` characters (count, default 4000); the reader joins them.
Phase 1 measures it before this is built.

The `faces` declaration (outward, quiet, handoff) is the module's one, not per arrangement.

## What the board does

### Reading

`read.board_geometry_of` reads each arrangement note in a cell's group into `CellGeom.arrangements`, a tuple of
`Arrangement` records:

```
Arrangement(id, choices, members: tuple[MemberPose], ops, rule_areas, geom: CellGeom)
```

`geom` is the cell as that arrangement stands, in the generated board's frame: members' footprints re-posed (pads,
shapes, courtyards and boxes carried by each member's rigid delta from the default), the cell's box, phys box,
courtyard box and copper box recomputed, its own copper from `ops`. The stamp's offset between the fragment's frame
and the generated board's is taken from the members' default places (the note's `base` against the stamped
footprints); members that do not agree on one offset make the cell's arrangements stale.

`CellGeom.arranged(id)` returns the arrangement's `geom` (the default for `""` or `"default"`). A `CellGeom` with
no notes has `arrangements == ()` and behaves as today.

Occupancy builds a cell's geometry from its members' geometries and its own copper (`Occupancy._geometry`,
`cell_geometry`) and caches it by cell name. It is keyed by the cell's name and arrangement id, and an
arrangement's geometry is built from each member's geometry moved by its delta, the way a placed cell's is moved by
its placement. Declaration-time questions (`board.pad(Part("m.u1"), 3)`, `extent()`, `Origin(Cell)`) read the
default arrangement; after a cell is placed they read the arrangement it took, from the committed geometry.

### Placement carries the arrangement

A cell's placement gains `arrangement: str = ""` beside location, rotation and face:

- `Placement` is the record every step, commit, reuse record, lock entry and run record already carries. It is
  serialised as `[x, y, rotation, face]` and gains a fifth element only when the arrangement is not the default, so
  a run with no arrangement writes the bytes it wrote before.
- `Placement.moved` and `Placement.at` keep the arrangement.
- A step's note records the choice (below).

### The search

The candidate space of a searched cell is (arrangement, x, y, rotation, face). `Board._scan_faces` already scans
the front and then the back as two ordinary scans, compares their best, and takes the back only when it beats the
front by `score.back_face`. It becomes a scan over (arrangement, face) pairs, the default arrangement and the front
first:

- each pair is an ordinary `scan()` of the arranged cell (`i.item` becomes `item.arranged(id)`), with its own
  geometry, its own native sweeper (`native_sweeper(item, face, rots, ...)`), its own scorer and native scoring
  (`NativeScoring` is built from the item's pads, so it is per arrangement), its own seeded hint (the back face's
  `_seed_hint` reseeding is the model: a seed is laid from the arranged item's pads), and its own lane pricing;
- the arrangement's score is the Scorer's, as for any candidate: links from the pads where they land, crossings,
  escape weights and lanes, pushes, limit and emitter pairs, the cost of vias giving way;
- a non-default arrangement costs `score.arrangement` more (mm, default 0.5). It is taken when its best score plus
  that is below the best so far, or when nothing earlier has a legal spot. An equal score goes to the arrangement
  earlier in the declared order, so the default;
- the best score so far, less the cost, is passed to the next scan as the pruning floor (`score.best`), as the back
  face does, so the native scoring prunes candidates that cannot win;
- an unscored search (no links, pushes or lanes to price) takes the default arrangement when it has a legal spot,
  and scans the others only when it has none, taking the first that has one. A cell with nothing pulling it does
  not change arrangement for no reason.

A decided place (`Location`, `Centre`, `Pin`, `Origin`, `Mid`, `Beside`, an edge or a row) lays the default
arrangement, or, with `arrangements=` naming others, the first of them in the order given that is legal. It is
never scored. Searched forms with one freedom (`OnEdge(edge)`, a slide) search the arrangements as above.

When no arrangement has a legal spot the cell is unplaced; the finding's refusals are the arrangements' merged and
tagged with the arrangement they came from (as the two faces' are).

The step records which was taken and why, as a structured note:

```json
{"kind": "arrangement", "id": "c_in.east", "score": 41.2, "cost": 0.5, "default_score": 44.9}
{"kind": "arrangement", "id": "c_in.east", "default_blame": {...}}      // the default had no legal spot
```

`step_text` renders it ("arrangement c_in.east: 41.20 and 0.50 for it against 44.90 as the default module
stands"), and the studio and `placemat watch` show that sentence; nothing reads it back. The run's `placements`
gain `"arrangement"` for a cell that took one other than the default.

### Boundaries on the search

- `arrangements=` on a cell's `place()` takes an arrangement id, or a sequence of them. One id pins the cell to it;
  several restrict the search to them, in that order (the order breaks ties). An id the module does not offer is an
  unplaced item with a finding `arrangement.missing` naming the ids offered; with `required=True` it stops the run
  as any required item does. Allowed on a cell only. The field is `omit_default`, so a declaration without it digests
  as it did.
- `place.arrangements` false makes the board ignore `CellGeom.arrangements`.
- The global solve (`solve.py`) and its hints read the default geometry. Cleanup moves and swaps keep an item's
  arrangement as they keep its face, and judge it with its arranged geometry (`movable[k]` must be the arranged
  item; Phase 3 checks this on a board).

### Cost and bounds

A cell with k offered arrangements has up to k scans in its step, so the step can cost up to k times (k at most
`place.arrangements_max`). Three things keep it bounded:

- **The step budget.** `place.step_budget` (or the item's `budget=`) is counted per scan of the cell, that is per
  arrangement and face: the `SearchBudget`'s `judged` and `cut` are reset between arrangements and `cut` is
  reported if any scan was cut. The default arrangement's scan is then the scan the cell had before, with the same
  budget, so it finds what it found. The step's candidates are therefore bounded by k times the budget, and the
  budget is a ceiling rarely met (the finding `setup.step_budget` says when one is).
- **The wall-clock bounds.** `run.step_limit_s` covers the whole step, all arrangements. When it trips between
  scans, the step takes the best of the arrangements scanned so far, default first, with the existing
  `time.step_limit` finding naming the arrangements not reached. `run.max_time_s` and `--step-warn` are unchanged.
- **The native paths.** Each arrangement's scan sweeps natively when the default would (the item carries no push or
  declared escape that the Rust `NativeScoring` cannot score). Nothing in `native/` changes: an arranged cell is an
  ordinary item to it. The floor from the best arrangement so far prunes later arrangements' scoring.

Cells are few and their steps are a small part of a resolve. The cost is measured, not estimated, before Phase 3 is
accepted (Testing). If it is too much, the first measure is a coarse pass over every arrangement and the fine pass
over the best `place.arrangement_refine` of them, as a scored scan already does over spots; it is not built until
measurement asks for it.

### Replay and reuse

- The step key hashes the intent, so `arrangements=` is in it when set. The context digest hashes the geometry
  (`_geometry_digest`), and it gains each cell's arrangements digest only when the cell has any, as escapes are
  added only when declared: a board whose cells carry none digests as before.
- A step record's placement has the arrangement element; `commits` entries become
  `[["cell", name, arrangement], placement]` when the arrangement is not the default, and `_apply_commits` takes the
  arranged cell. Records without it read as the default (`reuse.VERSION` is raised by one so an old reader does not
  misread a new record; a new reader reads old ones).
- Because a new setting changes the settings digest, the first run after the release replays nothing, as with any
  setting added to `place` or `score`. The result is unchanged.

### Explore

An explorable cell with offered arrangements draws from the pool of its best candidates in every arrangement's scan,
each arrangement's score including its cost, by the existing `draw` (slack and rank power from `[explore]`), so an
arrangement within the slack of the best is tried with the weight its rank gives it. The report's `moves` entry
gains `"arrangement": [was, now]` beside `rotation`. A variant's step records the arrangement it drew as a normal
step does.

### Recording and pinning

- **Run.** `placements[cell]["arrangement"]`, and the step note above. `plan.json` and the studio draw the cell as
  arranged because they read the committed geometry; the studio's step panel shows the note and, for a cell with
  arrangements, a list of each arrangement's best score and whether it had a legal spot (a structured field of the
  note).
- **Lock.** `LockEntry` gains `arrangement: str = ""`, left out of the file when empty (`read` takes
  `e.get("arrangement", "")`; `FORMAT` stays 1). An entry's offset is the arranged cell's reference point relative to
  its anchor pad, so applying an entry lays that arrangement first. `declaration_digest` adds the arranged cell's
  member places only when the entry's arrangement is not the default, so existing entries hold. An entry whose
  arrangement the module no longer offers, or whose arrangement's places changed, is released with the lock's
  existing released-entry note and a finding.
- **Freeze.** `placemat freeze` writes `arrangements="<id>"` into the cell's `place()` call along with the spot, by
  the same keyword editor (`script_edit.edit_keywords`), and its check that the edited script places every item as
  the lock did covers the arrangement. The `why=` gains it, as it gains where the spot came from.
- **By hand.** `arrangements="c_in.east"` in the board script pins, without explore. It selects among arrangements
  the module proved; it cannot name a place the module did not.

## Interactions

- **Declared copper room.** A firm cell lays the default or the first legal named arrangement, so the firm passes
  and their dry plans see one arrangement, and a `_Redo` pass that moves a Beside neighbour re-judges the cell with
  the same one. For a searched cell, declared copper whose ends become placed (Decision 2 of the copper-room spec)
  is dry-planned from the committed arrangement's pads. The reuse digest of a firm step includes the arrangement
  it laid, because the placement does.
- **Carried vias and give-way.** An arrangement's vias are its own copper, carried as the default's are. The
  search judges the arranged cell's carried vias giving way (`giveway.for_scan`) per arrangement. `plan.thinned`
  (`drops=`) and `plan.given_way` hold positions "as generated"; the write arranges the cell first, so they are in
  the arranged frame and are applied to the arranged copper (`_thin_cell` and `_given_way` run after the
  arrangement is written).
- **Riders.** A rider is judged with its reference at each candidate (`candidate_pad_locations(i.item, placement)`),
  so it is judged against the arranged item at each arrangement's scan. A rider that suits no spot of an
  arrangement makes that arrangement illegal; the finding for an unplaced reference names the arrangement.
- **Escape lanes.** A lane is laid from a placed part's pad; the arranged cell's pads are where its lane-priced
  scan stands them. Lanes reserved by a cell's own members come with the arranged copper.
- **Pushes, emitters and limits.** Distances are measured from the arranged members' points (an emission or sense
  point is the part's, turned and moved with it), so an arrangement that turns a sensitive member away from an
  aggressor costs that push less.
- **Keepouts and rule areas.** A rule area an arrangement brings follows the cell as a stamped one does. A cell's
  keepouts differing by arrangement come from the note's `keepouts`. A keepout shaped by a member of a *searched*
  cell stays refused as for any searched item.
- **Net ties.** A net tie's exclusion shapes belong to the member and move with it.
- **Split finding.** A cell's groups come from its members' nets, which no arrangement changes.
- **Planes and zones.** A cell's zone (a module's plane) is an op in the arrangement and is merged under the
  board's plane (`_merge_cell_zones`) from the arranged zone.
- **Labels, silk and 3D.** A member's label and model move with the member; the 3D view reads the arranged poses
  from the plan's items.
- **Place forms that name a member.** `Pin(Part("c.member"), point)` lands the arranged member's origin on the
  point; `Beside(Cell("c"), side)` stands against the arranged cell once it is placed.

## Writing the board

`apply_plan` arranges a cell before anything else touches its group, and only when its placement's arrangement is
not the default:

1. each member footprint is set to the arrangement's place (position, orientation and face, by the delta from the
   stamped one);
2. the cell's own tracks, vias, copper polygons, zones and rule areas, which the stamp brought for the default, are
   deleted from the group with `group.RemoveItem(item)` then `board.Delete(item)` (never `board.Remove`:
   CLAUDE.md, "pcbnew: delete board items with `board.Delete`"), and the arrangement's `ops` and keepouts are written
   into the group by the writer the fragment run uses;
3. `_thin_cell`, `_given_way` and `_move_cell` then run as today. `_move_cell` turns the cell about its reference,
   which for an arranged cell is the arranged box's centre, so the arranged geometry the search judged is the
   geometry written.

A default placement takes none of this, which is what makes a board with no arrangements byte-identical.

Deleting items from a group is the operation CLAUDE.md records as breaking pcbnew's bindings on a large board in a
way a small synthetic board does not show. It is checked on the real board fixture, not only on synthetic cells.

## Migration

Nothing changes for a module that declares no alternatives and a board that stamps only such modules: no note is
written, `CellGeom.arrangements` is empty, no new element is written in a placement, lock entry or reuse record, and
the board and run are what they were. The first run after the release replays nothing because of the new settings.

A module that adds alternatives needs its script run again and the board run after it. A board that stamps it then
searches the arrangements by default, so its placements can change: that is the purpose. A board pins one with
`arrangements=` to hold the default.

`references/migration.md` gets an entry (new forms; the `arrangement` word; a re-run is needed to write the notes).
`api.md` gets "Arrangements" under Placement (the three forms, `arrangements=`, the limits, the settings in the
settings table) and the run record's `arrangements` field. SKILL.md, "Shaping modules for the board", gains a
bullet: when the board wants one member on one side and the module is as good either way, declare the alternative in
the module and let the board's search choose, before editing the module's default. The release notes and the gaps
file follow the release procedure.

## Testing

Pure, synthetic modules and boards (the fragment tests' staging helpers):

- declarations: `alternative` and `arrangement` take the `place()` keywords; an item with no `place()`, a row member
  and an unknown keyword are refused; ids are formed as specified; a duplicate id and a reserved name are refused;
  the limits refuse with the finding and leave the default only; `place.arrangements = false` is the default only;
- product and group arrangements are enumerated in declaration order, and two that resolve alike are one;
- the module run lays out each arrangement; one whose copper cannot be drawn, or whose member is unplaced, or whose
  DRC or verdict fails, is not offered and raises `arrangement.refused`; the default is written either way;
- the written fragment's live items are the default's and equal the bytes of a run without alternatives; each
  offered arrangement has a note that round-trips (members, ops, keepouts, `base`); a stale `base` raises
  `arrangement.stale` and is ignored;
- a stopped module run resumes without re-laying finished arrangements;
- the note is dropped from a written parent; a long note splits and rejoins;
- the parent reads `CellGeom.arrangements`; arranged geometry equals the geometry of a cell stamped from a fragment
  whose default is that arrangement (the check that the delta and the note agree);
- search: with links that favour the east side, a cell takes `c_in.east`; with the default at least as good, the
  default; with the default having no legal spot, the first arrangement that has; with no pulls, the default; the
  cost `score.arrangement` flips a close call; a tie goes to the declared order; `arrangements="id"` pins,
  `arrangements=(a, b)` restricts, an unknown id is unplaced with `arrangement.missing`;
- native and Python sweeps choose the same arrangement and place the same;
- riders, escape lanes, a push and a carried via giving way are judged per arrangement (one case each);
- replay: the second run replays an arranged step; a commit with an arrangement applies the arranged cell; an old
  record without the element reads as the default;
- lock and freeze: an accepted entry holds the arrangement and re-places it; the declaration digest of a default
  entry is unchanged; a vanished arrangement releases the entry; freeze writes `arrangements=` and its check passes;
- explore draws arrangements within the slack and reports the change in `moves`;
- the written board (with KiCad): an arranged cell's members and copper are as the arrangement and its group is
  intact (`GetItems()` and `GetPosition()` still work afterwards, as in CLAUDE.md), DRC on the arranged board has no
  more than the module's own arrangement run had;
- `step_text` and `finding_text` render the new notes and findings, and the studio's step panel shows them.

A real module fixture: a module under `fixtures/*/modules/` staged by `tests/real_modules.py`, run with a bypass
alternative on the other side of its IC and a member turn, then stamped by its fixture board and searched. The
check is that the arrangement offered passes the module's real DRC, the board run places the cell, and the two
runs agree on what was written. The test and the CLAUDE.md note about bindings are why this is a real board and not
only a synthetic one.

Bench (`fixtures/bench.py --jobs 2`): the corpus declares no alternatives, so every case is `same`; the tally goes
in the commit. A new case set declares alternatives on fixture modules and is run once to put numbers in the
spec's build notes: the module run's seconds with k arrangements against one, and the whole-board fixture
(`fixtures/bench.py --board`) resolve's seconds and run score with and without arrangements. Budget: a module run
with k arrangements takes at most about k times the default's; a board's resolve with arrangement modules takes at
most 25 percent longer than the same board without. Real-board runs and the full suite run one at a time.

## Phasing

1. **Declaration, module proof, the note** (about 4 days). `alternative`, `arrangement`, `Alt`, the limits and
   settings, the per-arrangement resolve and scratch boards, the offered gate, `run.json`'s `arrangements`, the ops
   codec and the note, `arrangement.limit` and `arrangement.refused`. Measures the note's size. Ends with a module
   run whose fragment is byte-identical without alternatives and carries notes with them.
2. **The board reads and writes arrangements** (about 3 days). `CellGeom.arrangements`, arranged geometry in the
   occupancy, `Placement.arrangement`, the writer's arrange step, `arrangement.stale`. A firm cell lays an arrangement
   by `arrangements=`. Verified on a real board for the group deletion.
3. **The search** (about 4 days). `_scan_faces` over arrangements, `score.arrangement`, notes and findings, replay
   keys, lock and freeze, explore, cleanup. Bench and timing.
4. **Studio and docs** (about 2 days). Step panel and the module run's arrangement list, `api.md`, SKILL.md,
   migration, the release entry.

About 13 working days. Phases 1 and 2 can ship without 3: a module can declare and prove arrangements and a board
can pin one by name, which already removes the module-edit round trip for a fix the agent knows.

## Decisions for the user

1. **The word.** "Variant" is already the name of a `.zen` `Layout` per config and of explore's tries.
   - A: "arrangement" (this spec).
   - B: "variant", with the other two renamed in the docs.
   - C: "stance" or "option".
   Recommendation: A. Cheapest, and no existing page changes.

2. **How per-member alternatives combine.**
   - A: the product of each item's options, capped (this spec), plus named groups for the combinations that matter.
   - B: one change at a time from the default (1 + the sum of the options), plus named groups; no product.
   - C: named groups only; per-member `alternative` is sugar for a group of one.
   Recommendation: A with the caps of 4 and 8. Members interact (a bypass's side with a turned resistor next to it),
   and an arrangement is only proven if it is run, so the product is what the module author would otherwise write
   by hand. B is the fallback if the cap proves too tight on real modules.

3. **What a non-default arrangement costs the board.**
   - A: `score.arrangement` = 0.5 mm, tuned on the bench (this spec).
   - B: 0, a tie going to the default.
   - C: 2.0 mm, as `score.back_face`.
   Recommendation: A. The module's default is its author's first choice, so a gain smaller than noise should not
   change it; the number is set from the bench before the release, not here.

4. **What keeps an arrangement from being offered.**
   - A: an unplaced member, a critical finding, a failed verdict, a `real` DRC violation (this spec).
   - B: A, and any warning.
   - C: only an unplaced member and a `real` DRC violation.
   Recommendation: A. It is the module's own gate, and warnings stay on the record for the reader.

5. **Decided (firm) cells.**
   - A: lay the default, or the first legal of `arrangements=` (this spec).
   - B: search them like a searched cell, scored by their links.
   Recommendation: A. A firm place is a statement that the cell goes there; scoring a firm item has no precedent
   and would change what a point means (the arranged box centre).

6. **The step budget.**
   - A: `place.step_budget` per arrangement scan (this spec).
   - B: one budget split across the arrangements.
   Recommendation: A. The default's scan then equals today's scan, and the ceiling stays a ceiling.

7. **Where the proven arrangements live.**
   - A: texts on the fragment (this spec), as faces and rules do.
   - B: a sidecar in the module's layout folder.
   Recommendation: A. The stamping board cannot find a sidecar (the fragment-notes spec); the cost is the ops codec
   and the note's size, measured in Phase 1.

8. **Copper for one arrangement only.** A module may want a track that exists only in one arrangement.
   - A: not in this change; copper declared by intent holds in all arrangements and an arrangement that cannot draw
     it is not offered.
   - B: `only=`/`not_in=` on `board.track`, `board.via` and `board.pour`, naming arrangement ids.
   Recommendation: A, and add B when a real module needs it. B grows every copper form's signature.

9. **Zones in a module.** A module's plane zone follows its frame, and `board.rect(fit=True)` frames each
   arrangement differently.
   - A: each arrangement carries its own zone (this spec).
   - B: one frame fitted to the union of the arrangements, and one zone for all.
   Recommendation: A. B makes every arrangement carry the largest one's frame and leaves the cell's box larger than
   it needs.

10. **Selecting by name in a board script.** `arrangements=` on the board's `place()` selects among arrangements the
    module proved. It is needed for freeze, and it is not the free override of point 4.
    - A: in this change.
    - B: left out until point 4 is decided; freeze writes the lock only.
    Recommendation: A. It cannot produce a place the module did not prove, so it stays on the module's side of the
    line; without it a frozen board cannot hold the choice.
