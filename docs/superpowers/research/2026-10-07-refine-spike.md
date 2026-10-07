# Refine spike: declarations carried with a cell, and the speed of a move

Research for step 3 (refine) of the 0.100 roadmap, against
docs/superpowers/specs/2026-10-06-refine-pass-design.md. Read-only on main
(38d9b042). The prototype code was throwaway and its worktree is deleted. The
scripts and the prototype's diff are in the session scratchpad
(`spike/q1_*.py`, `spike/q2_*.py`, `spike/refine_item_proto.diff`). Paths are
under src/placemat/ unless given in full.

## Summary

- **Question 1.** The parent board receives a cell's members at their stamped
  poses, its copper, its rule areas, and three kinds of note: faces, clearance
  rules and arrangements. It does not receive the placement declarations, links,
  pushes, escapes, fanout bands or the module's settings. On the fairing core
  modules, 192 of 198 members are decided in their own module (a `Beside` or a
  fixed point), and 4 are searched. If each member stays bound by what its module
  declares, 185 of the 198 move only with the cell. Fine refine would therefore
  have 4 free units on the whole core: 3 single parts and one group of 10.
  Recommendation: option (c). The module run writes a note of the resolved
  constraints, and the parent evaluates it with transforms. The spec's goal,
  "routing can make a part give way or turn inside a cell", needs a decision
  from the user about how much a decided member may move. Today's declarations
  allow almost none.
- **Question 2.** The prototype judges and scores a batch of candidates natively
  for one held item. On the core it takes 10-12 us per candidate, and in a
  single-candidate call 12.5 us, where today's sweep entry takes 99.6 us. An
  end-to-end loop on the core reaches 264 / 1,181 / 3,435 moves a second when it
  makes 20 / 100 / 500 moves per item visit. The 2,000 gate is passed only with
  long visits, and the 10,000 target is not reached. Python's per-visit lift,
  setup and commit set the limit (tens of ms on the core), not the native judge.
  The bench modules reach 17k-43k moves a second at 100-500 moves per visit.

## Question 1: how a module's declarations travel with a stamped cell

### How a cell is stamped today

- The module run resolves the module's own script and writes its fragment
  (`layout/layout.kicad_pcb`). `pcb layout` copies the fragment into the parent's
  generated board as a group per cell: footprints at the fragment's poses,
  tracks, vias, graphic polygons, zones and rule areas, and the User.Comments
  notes (docs/superpowers/specs/2026-09-22-fragment-layers-design.md:36-38;
  2026-10-04-module-member-variants-design.md:216).
- The parent reads each group into a `CellGeom` (kicad/read.py:812-869;
  board_geometry.py:138-155). It holds:
  - the members, as `Footprint`s at their stamped places;
  - the boxes, including the cell's own copper;
  - `faces`, from the `placemat faces` note (kicad/read.py:845-850);
  - `rules`, from `placemat rule` notes (kicad/read.py:853-854; rules.py:126);
  - `arrangements`, from `placemat arrangement` notes (kicad/read.py:855-866).
- Copper the cell owns is read with `owner = <cell>` (kicad/read.py:492 `_copper`).
  Rule areas are read with `cell = <cell>` (`_rule_areas`, kicad/read.py:549). A
  keepout's layers and `allow=` nets travel in its zone name
  (2026-09-22-fragment-layers-design.md).
- An arrangement note (arrangement_note.py:119-127, written by
  arrangement_run.py:358-368 and 415) carries:
  - every member's pose in the fragment's frame, and its default pose (`from`);
  - the module's copper as ops;
  - the keepouts.

  The parent rebuilds an arrangement by the offset between the stamped and the
  default poses (arranged_geometry.py:91-145). Offsets that differ, or a turn
  (:108-114), make the note stale.
- On the parent, a cell is one rigid item. `Occupancy.commit` moves its members
  and its own copper together (occupancy.py:1230, `_commit` 1385).

### What of the declarations survives

Poses survive, along with the geometry of copper and keepouts. These survive as
data:

| Survives | Where |
|---|---|
| member poses (default, and each offered arrangement) | footprints; arrangement notes |
| module copper as drawn (tracks, vias, polys, zones) | group items, `owner` = cell |
| keepouts and their `allow=` nets | rule areas, name markers |
| clearance rules | `placemat rule` notes |
| declared sides (outward, quiet, handoff) | `placemat faces` note |

Lost: everything the module's `Board` held as declarations.
- `PlaceIntent` per member (layout.py:278-323):
  - freedom;
  - `at` / `center` / `edge` / `near` and radius;
  - `rotations=` and `rotation_given`, `turned` (Facing, Turned), face and
    `either`;
  - `beside` (`_BesideSpec`: target, side, align by pads / `Past` / `Along`, gap,
    copper; layout.py:427-443);
  - `pin`, `cell_pin`, `needs`, `pushes`, `arrangements`, `overhang`.
- `Link` (layout.py:491): pads, weight, limit. The parent's `_targets` gives
  module-internal nets the default weight (layout.py:4862-4892).
- `Push` from `board.push` (layout.py:508). Annotation pushes (`Pm.Emits` /
  `Pm.Limit`) are re-derived from footprint fields, so those do survive
  (`_annotated_pushes`, layout.py:5035).
- Escape lanes (`board.escape`) and fanout bands. A fanout band is a reservation,
  never a rule area (layout.py:8929).
- `CopperIntent` (layout.py:463-489): the pads each track or pour joins (`refs`,
  `owners`), widths, priority and bridge. `plan` is a callable, a closure over
  the script, so it cannot be serialised.
- The module's frame (fit frame, edges) and its `placemat.toml` settings
  (envelope, escape depth, weights, free and plane nets).

### What the module's resolve knows that the parent loses

What decides each member, measured. Each fairing core module script was run
in-process against its cached generated board (a copy), and its declarations
were read back (`spike/q1_modules.py`). 26 modules ran. ringsensor and
usbmoisture failed against stale cached boards. displayterms and userpanel had
no cached board.

| | members |
|---|---|
| all members | 198 |
| decided (fixed point or `Beside`) | 192 (Beside 166, a fixed `at`/`Centre` 26: one datum per module) |
| searched | 4 (mcu 1, usbsource 1, usbtcpc 2) |
| block members | 2 blocks |
| rigid with the cell's frame (rule below) | 185 |
| free units left | 4: one group of 10 (mcu), three single parts |

The latest module run records agree: 230 fixed, 18 edge, 5 searched, out of 262
members across 31 modules.

Also declared in these modules:
- 54 links, 49 of them with a limit;
- 10 keepouts;
- 12 escapes (mcu 8, and 1 each in status, usbconverter, usbesd, usbsource);
- 121 pour intents;
- 0 pushes.

A `Beside` is "Firm, like `Pin`: the position is decided, not searched"
(values.py:347-349). Its freedom is `FIXED` (layout.py:3389-3390). "A decided
item goes down first and nothing may move it" (values.py:406-418). So "a member
moves only within what its module declares" means:
- a `Beside` member moves only with its target;
- the module's datum moves only with the cell.

The rule used above:
- a decided member is rigid with every member its place refers to
  (`PlaceIntent.needs`);
- one that refers to none is rigid with the frame;
- members a pour names are rigid together.

**Consequence for the spec:** under its own constraint rule, fine refine on the
fairing core has 4 free units and 26 rigid cells. Moving members for routing
needs one of:
- the module scripts to leave members searched;
- a new rule letting fine refine relax a decided member, for example a `Beside`
  keeping its side and gap but sliding along the side.

That is a user decision. The spec says no constraint form is added.

### Which members a module's pours join

- **Module side:** a pour's `CopperIntent.refs` and `owners` name the pads that
  declare it (`_copper_intent`, layout.py:5773). A pour given by points alone
  names none.
- **Parent side:** this can be worked out from geometry: a member's pad on the
  pour's net whose outline meets a cell-owned `poly` or `zone`. On the core
  fixture's generated board (`spike/q1_cells.py`), 121 of 258 members touch one
  of the cells' 98 pours. Per cell it ranges from 0 (convtemp, debug, display,
  ring, usbpd.moisture and others) to all members (backlight, monitoring,
  inputfilter, statuspulls; usb5v 20 of 21).
- **Other cell copper on the fixture:** 425 module tracks and 420 vias. Fine
  refine deletes the module tracks that touch a moved member.
- splits.py:45-75 already groups a cell's members by local nets with
  union-find. The pour grouping is the same shape.

### Options

**(a) Serialise the declarations into a note carried with the stamp.** Write
each member's `PlaceIntent`, links, pushes, escapes and keepouts as data. Rebuild
them as declaration objects in the parent's `Board`, and judge a member with the
parent's own settle code.
- Cost: a codec for every declaration form (`Beside`, `Past`, `Along`, `Pin`,
  `Facing`, `Turned`, `Parallel`, `Centre`, `Polar`, `Tangent`, runs, rows,
  blocks, escapes...). That is far larger than the arrangement codec.
  `reuse.canonical` (reuse.py:29-75) already walks these objects, but only one
  way, to text for a digest.
- The parent also needs:
  - the module's settings, since the default `Beside` gap depends on the
    envelope, and envelope and clearances differ between module and parent;
  - a map from the module's frame and edges to the cell's pose.
- Reproducible: it is written by the module run and versioned with the fragment.
  The arrangement note's `base` digest (arrangement_note.py:112-116) shows how to
  catch a stale note.
- In board coordinates: inst paths map to parent refs (`<cell>.<inst>`,
  arranged_geometry.py:24-30), nets through `stamped_net`
  (board_geometry.py:285-294), and frame coordinates through the cell's pose.
  Then the module's own settle logic runs.

**(b) Re-run the module script in the parent's process as a sub-board.**
- Cost: reading the 26 modules' generated boards plus running their scripts and
  `finish_declarations` took 0.49 s + 0.23 s in total (about 30 ms a module).
  But the script needs the module's generated board:
  - on a fresh checkout, that is a `pcb layout` per module;
  - the parent has no map from a cell to the module's folder. Finding it means
    parsing the `.zen` imports, which the notes design rejected for a sidecar
    (docs/superpowers/specs/2026-10-02-fragment-notes-out-of-sight-design.md:34-41).
- Reproducibility is the weak point: the script can change after the fragment
  was written. 2 of 28 scripts failed here against their stale cached boards.
  The declarations would then not match the stamped layout, so an inputs-digest
  check is needed.
- The declarations bind to the module's own `Footprint` objects, so they still
  need the ref, net and frame mapping of (a). Every module script then runs on
  every parent resolve.

**(c) The module run writes the resolved constraints as a note (recommended).**
The module run knows the outcome, so it records what each member is bound to,
in the fragment's frame, rather than the API calls:
- Rigid groups:
  - the frame group: the datum, edge members, and everything riding on them by
    `needs`;
  - groups riding a searched member;
  - groups a pour joins.

  Each member's pose is stored in its group's frame.
- For each searched member, its residual bounds:
  - allowed turns, relative to the cell's turn;
  - face set;
  - `Near` centre (a frame point or a pad) and radius;
  - the one free axis or edge, if any;
  - its pushes (source as a member and pad or a frame point, falloff, reference
    and limit).
- Links: inst and pad pairs, weight, limit.
- Module-time reservations the stamp drops (fanout bands, escape lanes), as
  polygons in the frame with their owners.
- The module's tracks, each with the members' pads it touches, so refine knows
  which to delete when a member moves. The ops codec exists
  (arrangement_note.py:48-94).

Cost: one more note per module, written where arrangement notes are written
(arrangement_run.py:415) and read where they are read (kicad/read.py:855). Size
is about that of an arrangement note: a few kB, with the chunking that already
exists.

Reproducible: the note is produced and stamped together with the fragment, so
it cannot drift from it. A `base` digest guards a hand-edited fragment.

In board coordinates, each check is a transform plus a simple predicate:
- group pose = cell pose composed with the group offset;
- Near: a distance;
- link limit: the distance between two pads;
- turns: set membership;
- keepouts and bands: polygons moved with their owner.

Each is cheap enough to run natively per candidate, and none needs the module's
settle code.

The cost of (c): it is exact only while a decided member's references stay
inside its rigid group. Every fairing module meets that, since every `Beside` and
`Past` refers to members of the same module. It does not capture "re-settle this
`Beside` against a moved target" for relaxed semantics. If the user wants
decided members relaxed (above), the note would also carry the relaxable
relation, for example a `Beside` slide range. That is a design change and should
be specified, not inferred.

The spec removes `board.alternative` and `board.unit` with their notes. The note
transport (arrangement_note.encode/read_notes, kicad/arrange.py:25) can be reused
for (c).

Outline of the note (`placemat members <json>`, version 1):
```json
{"v": 1, "base": "<digest of default member poses>",
 "groups": [{"id": "frame", "members": [{"inst": "mcu", "pose": [x, y, rot, face]}, ...]},
            {"id": "l_rf_match", "rides": null, "members": [...]}],
 "free": [{"inst": "l_rf_match", "turns": [0, 180], "faces": ["front"],
           "near": {"pad": ["mcu", "1"], "radius": 1.5}, "axis": null,
           "pushes": []}],
 "links": [{"a": ["mcu", "46"], "b": ["c_cpu", "1"], "weight": 3, "limit_mm": 2.0}],
 "pours": [{"net": "V3V3", "members": ["c_a", "c_b"]}],
 "bands": [{"kind": "fanout", "owner": "mcu", "polygon": [...], "layers": ["F.Cu"]}],
 "tracks": [{"op": 12, "pads": [["mcu", "20"], ["c_rtc", "1"]]}]}
```

## Question 2: can refine reach the speed it needs?

### What was measured

Boards:
- the fairing whole-board fixture as fixtures/bench.py `bench_board` builds it
  (24 searched cells, 1,591 shapes; resolve 6.1 s);
- three bench modules, every part a bare `place()` as `ModuleBoard` builds them:
  fairing Mcu (50 parts), fairing UsbPd (14), mnb BrakeChopper (23).

Method:
- Candidates are nudges within plus or minus 1 mm on a 0.2 mm grid, at 4 turns.
- Scorer with `prune=False`: refine needs each candidate's full score, not only
  the best.
- Medians are over the items. Runs went one at a time under the lock.

The prototype was `RefineItem`, a throwaway pyclass in native/src/lib.rs (diff
saved). It holds one lifted item's sweep inputs, converted once: origin shapes,
bodies, edges, parts, judged reservations, yards, silk, the obstacle index and a
`NativeScoring`. `judge(cands)` returns legality and score per (x, y, turn),
running the same tests in the same order as `sweep` (lib.rs, `sweep`). Against
`sweep` it agreed on legality and score for every candidate and every item on all
four boards.

### Today's Python move (lift, targets, Scorer, scan at radius 0, unlift)

| median per item | core (cells) | Mcu | UsbPd | BrakeChopper |
|---|---|---|---|---|
| rejected move, whole | 25.0 ms | 1.22 ms | 0.93 ms | 0.82 ms |
| of which lift + unlift | 15.2 ms | 0.78 ms | 0.64 ms | 0.54 ms |
| targets | 2.1 ms | 26 us | 18 us | 16 us |
| `occ.legal` | 224 us | 48 us | 42 us | 40 us |
| Scorer (Python) | 739 us | 44 us | 43 us | 38 us |
| accepted move, extra (commit) | 36.6 ms | 0.99 ms | 0.84 ms | 0.68 ms |

At about 40 moves a second on the core, a Python loop is far below the gate. On
the core, lift and unlift split into ratsnest refresh (5.4 + 6.0 ms) and escapes
refresh (0.9 + 2.8 ms) (`spike/q2_anneal.py` split).

### Native parts

| median | core | Mcu | UsbPd | BrakeChopper |
|---|---|---|---|---|
| legality only, per candidate (`sweep`) | 2.4 us | 0.56 us | 0.60 us | 0.45 us |
| legality + score, per candidate, batch | 12.0 us | 1.7 us | 2.4 us | 1.1 us |
| score per legal candidate (full) | 136 us | 8.3 us | 7.7 us | 5.3 us |
| of which wire only / wire + crossings | 52 / 77 us | 1.1 / 1.5 us | 1.0 / 1.2 us | 0.9 / 1.2 us |
| legal share of candidates | 8-12% | 22% | 30-34% | 13% |
| one candidate per call, today's `sweep` | 99.6 us | 7.2 us | 7.9 us | 6.7 us |
| one candidate per call, prototype | 12.5 us | 2.0 us | 2.7 us | 1.5 us |
| per-item setup (obstacles + sweeper + scoring + targets), measured alone | about 5 ms | 0.3 ms | 0.2 ms | 0.2 ms |

Notes:
- Today's `sweep` converts every argument on each call, including per-reservation
  `judged` lists, and builds its reservation pass. The prototype keeps them, so a
  single candidate costs the same as one in a batch.
- On the core cells the score dominates a legal candidate: 136 us, not the
  1-2 us the spec assumed. That figure was a part's, with pruning on.
  - The wire term alone is 52 us: a cell's pads times their placed targets.
  - `leaf_costs` scans every anchor of each pad's net (ratsnest.rs:331-357), and
    allocates a `seen` array the size of the edge list for each call (:362).
  - The escapes term adds the rest.
- The one-score spec replaces this scorer with an MST delta, so this cost will
  change. Its gate (under about 5 us a candidate) is not met by today's scorer on
  cells.

### End-to-end loop (prototype, `spike/q2_anneal.py`)

Each visit:
1. lifts one item and builds its judge;
2. judges K candidates in one call (80% nudges of 1-5 grid steps, 20% turns);
3. runs Metropolis over them in order;
4. commits the last accepted pose once, or unlifts.

This is exact for one item. While only the lifted item moves, the board it is
judged against does not change, so a visit's K moves need no commit between
them. Moves are proposals, legal or not, as `refine.moves` counts them. 6,000
moves per run.

| moves a second | K = 20 | K = 100 | K = 500 |
|---|---|---|---|
| core | 264 | 1,181 | 3,435 |
| Mcu | 4,936 | 24,519 | 43,017 |
| UsbPd | 3,911 | 16,847 | 41,422 |
| BrakeChopper | 5,797 | 26,212 | 106,331 |

Core time split at K = 100:
- setup and lift: 2.7 s;
- commit or unlift: 2.1 s;
- native judging: 0.28 s.

A core visit costs 45-85 ms of Python (lift, obstacle index, sweeper, scorer
mirrors, commit). That is more than the 5 ms measured per part in isolation,
since a visit also lifts, commits and rebuilds the escape turns.

### Pushes and declared lanes

- `Scorer.native` returns None for an item with a push or a declared lane
  (layout.py:889). Riders, exposure and look-ahead `accept` tests
  (layout.py:11262-11268) and carried vias giving way (placer.py:337) are also
  outside the native judge. A candidate refused by a carried via needs Python's
  give-way.
- The core fixture's 24 items had native scoring throughout.
- The real core's last run (fairing-instrument core run 3f67fdf0) has 29 searched
  items (20 cells, 9 parts). Of these:
  - 1 carries a push: `sensors`, from Core_layout.py:462.
  - 0 have declared lanes: the core script has no `board.escape`.
  - Annotation pushes add none: the board has one `Pm.Limit` and no `Pm.Emits`.
- For fine refine, the modules' 12 escapes sit on decided members (the mcu chip
  and others), so they are not refined alone.

### Estimate (not measured)

The native judge is not the limit. On the core it allows about 80,000 candidates
a second (12 us). What has to change to reach the target:
1. **A held native board:**
   - one obstacle index for the whole board, with the moving item's shapes
     skipped by id instead of rebuilt per item. `first_clear_offset` already
     takes a skip set (lib.rs:312).
   - the ratsnest and escape refreshes on lift and commit done natively, instead
     of in `_ratsnest_refresh` and `Escapes.refresh` (occupancy.py:1299,
     escapes.py:218).

   If a visit then costs about 2 ms on the core, a reasoned guess: K = 100 gives
   about 100 x 12 us + 2 ms = 3.2 ms a visit, about 30,000 moves a second.
   K = 20 gives about 6,000.
2. **The cell scorer:**
   - a spatial index over net anchors in `leaf_costs`;
   - no per-call allocation of `seen`;
   - or the one-score MST delta, if it is built native-first.
3. **The accepted-move commit (37 ms on the core):** it matters when acceptance
   is high. At the spec's example (312 kept of 20,000) commits alone are about
   12 s on the core today.

Without (1), long visits pass the gate: K of 300 or more gives over 2,000 a
second on the core. But refine then becomes an item-at-a-time local search.
Whether that anneals well is untested.

### Recommendation

- **Build the batched per-item judge.** It is the prototype's shape: an item
  handle that keeps converted inputs, and `judge(cands)` returning legality and
  score. Visits of many moves per lifted item are exact and cheap.
- **Before the full build, port lift and commit natively** (point 1 above). That
  is the work that decides whether 10,000 a second is reached on the core.
- **Fix the cell scorer cost** (point 2), or let the one-score work deliver it.
- **Stated limits.** Keep these items in Python or out of the movable set, as the
  spec says:
  - pushes: 1 core item;
  - lanes: 0 core items;
  - riders and give-way.
