# Migrating a layout script

Sections are per release, newest first. Read the ones between the version a
script was written against and the version in use; `SKILL.md`'s check line says
whether any of it applies.

## To 0.32.1

Nothing to change. A lock written by 0.32.0 released every linked item on
the next run; accept again (`--explore ... --accept`) to rewrite it.

## To 0.32

Nothing to change. New: `--explore` on `run` and `preview`, the lock file
beside the script (`<script stem>.lock.json`, commit it with the script),
`placemat lock` and `placemat freeze`. A declaration's script line is
recorded; comments added above a declaration still replay.

## To 0.31

Nothing to change. placemat's version is its git tag now; an install from
a checkout needs the tags (`git fetch --tags`) to report it. The native module installs with placemat's `native`
extra (a Rust toolchain on the machine), and a native module built for
another placemat release is no longer used: rebuild it after upgrading.

## To 0.30

Nothing to change. An optional native module (`native/`, see its README)
makes placement 2.5-4.6x faster with identical results; placemat runs
without it, and `PLACEMAT_NATIVE=0` turns it off.

## To 0.29

- An item on a line (`Location(x, None)`, `Centre(None, y)`) with parts it
  connects to already placed now starts across from them rather than at an
  even share of the line; one with nothing placed to pull it is as before.
- `[place] courtyard_touch` defaults to 0 (was 0.02): each pair of parts may
  overlap by the margins read from KiCad's own courtyards instead, so
  placements pack as tightly as KiCad's DRC allows and no tighter. A part
  whose courtyard stroke is thin no longer produces a `courtyards_overlap`.
- A label stands at least the board's silk clearance off what it names,
  whatever `gap=` or `[label] gap` says; labels move out by that much.
- In the `physical` and `union` envelopes a row or ring gap below the widest
  gap the envelope enforces is raised to it; a script that set the netclass
  clearance as its row gap can drop it.
- A through-hole part no longer claims its whole courtyard on the far face:
  only its holes, and another part's courtyard may not sit over a lead. A
  chip with vias in its exposed pad claims only their copper on the far
  face. Parts can now sit on the back under through-hole parts.
- The first run after upgrading generates the board again: the cached
  generation has no record of its inputs yet. From then on a changed .zen,
  footprint, symbol or stamped fragment regenerates by itself; `--fresh`
  is only needed for something outside those (a toolchain update).
- A script may import a module beside it without touching `sys.path`; drop
  any `sys.path.insert` added for that. Such a module now counts in the run
  id, so the first run after upgrading has a new id.

## To 0.28

- A keepout (or a stamped cell's rule area) with `"parts"` and `layers=`
  naming one face keeps parts off that face only; before, it kept them off
  both. A script that relied on that should list both faces.
- A part in the netlist that no declaration places is now a finding.
- A part searched from its links or round a `Near()` hint, with neither
  `rotation=` nor `rotations=`, is now tried at all four rotations, so parts
  turn and a board re-runs to a different placement. A part whose turn
  matters says `rotation=`; `[place] rotations = "declared"` in
  `placemat.toml` keeps the old behaviour for the whole board. The
  pocket fallback follows the same rule.
- Two satellites aimed at the same anchor pad no longer both take the one
  spot on its axis: the second is refused, naming the first. Aim it at
  another pad carrying the net, or link it to the pad instead.
- Overlap tests catch outlines that coincide (the same courtyard twice, or
  one slid along a side), which some checks read as clear before.

## To 0.27

Nothing to change. `placemat preview` is new: the placement drawn in
seconds, without building the board (see the API reference). Pads no longer
take capacity in the congestion measure, so `metrics.rudy` reads lower where
large pads were; a part not yet placed no longer blocks a pocket, a planned
track or a cutout, which can let a board place parts it could not before.

## To 0.26

- The cleanup pass defaults to 2 passes at a 0.5 mm step (was 3 at 0.25): a
  board re-runs to a slightly different placement, about 1% more wire at the
  median, in about a third of the pass's time.
- A run replays the previous run up to the first changed step
  (`--no-reuse` to resolve everything); the board written is the same.
- Every run prints its most congested cell by RUDY (`congestion`,
  `metrics.rudy`). Nothing steers by it yet.
- Large boards resolve faster, placing the same.

## To 0.25

Searched parts may move after placement: a cleanup pass moves and swaps the
plain searched parts where that shortens their wire and declared links, so a
board re-runs to a different, shorter placement. Parts with a place of their
own, labelled parts and parts another declaration refers to stay where they
were. `[cleanup] enabled = false` gives the placement of 0.24.

## To 0.24

- A block satellite may name the anchor's pad by number - `(Part(...), 20)` -
  where a net would pick the first of several pads carrying it.
- The run id includes the fab profile's values, so every board's next run
  has a new id; the best-run gate goes by the parts, so it is unaffected.
- `measure` adds box edges, pad outlines and mask/paste layers, and flags a
  courtyard inside its own silk or equal to its body.

## To 0.23

Nothing changes in the default `[place] envelope = "courtyard"`, apart from a
new `footprints` line naming each footprint whose silk or pads pass its
courtyard (not a finding). `physical` and `union` are new; switching the mode
re-places every board. fab-profile.json may set
`courtyard.component_spacing_mm`.

## To 0.22

- A declaration with `layout = False` beside the board is no longer taken for
  a board, so a `.zen` with sub-circuits no longer needs the board declared
  first.
- `board.edge(facing, outermost=True)` takes the run lying furthest out that
  way when several face it; a script filtering `board.edges()` for that can
  use it.
- Of two linked items neither placed, the one with less pull toward what is
  placed now waits for the other, so a part is seeded on the one its link
  joins it to. A script whose linked items were each already pulled to placed
  parts is unchanged; a block made only to force that order can go back to
  links.

## To 0.21.1

Nothing to change. Placement is faster on large boards - a 220-part board's
resolve went from about 16 minutes to under 2 - and lands every part where
0.21 did. Two polygons whose bounding boxes only touch are never counted as
overlapping; before, a vertex lying exactly on the other's boundary could
make them so.

## To 0.21

A part or cell that was UNPLACED because its seeded scan found no legal spot
now takes the free pocket nearest what it connects to, and parts placed after
it can move. A board that placed every part is unchanged. `metrics.pocketed`
counts these, and the run prints them. A searched step's note gives its rank
once instead of twice.

The solve no longer crashes on a board that declares a keepout.

## To 0.20

Nothing changes unless you turn it on. `[solve] enabled = true` gives the
searched tier its starting points from a global solve of the whole netlist
instead of from the pads already placed. Off by default: on the board it was
measured on it did not beat the sequential seed on the best-run objective.

The API reference's account of the placement order was out of date: it still
described an item needing more than a quarter of the free board going first,
a rule the rank replaced in 0.6. It now says what the order is.

## To 0.19

Nothing to change. `placemat occupancy` is new: what copper is at a point or in
a box on each layer, and the nearest spot a via can stand and be reached near a
pad, with why every nearer spot failed. `FreeSpot` is new too: a via written as
`board.via(net, FreeSpot(near=PadRef(...)))` lands at the nearest legal spot
once its part is placed.

`polys_overlap` now finds one polygon inside another even when the first vertex
it tests lies on the other's edge. It could miss that case before; edges that
merely touch still do not count. A run that placed cleanly may, rarely, report
an overlap it used to miss - it is real.

## To 0.18

Nothing to change. Every route now checks the copper the router laid against
the keepouts on the board it was given, prints anything inside a region that
forbids it, and keeps it in `route.json` under `keepout_breaches`. The router
honours KiCad rule areas; this makes that a checked fact on every run, so a
region it ignored would be named instead of appearing as one more
`items_not_allowed` among the ones that are there by permission.

## To 0.17

**Keepout zone names gain a layer marker, and a module's keepout now holds on
the parent's inner layers.** A keepout on every copper layer is written
`keepout <name> [*.Cu]`, and one on layers its board lacks lists them. KiCad
saves a zone on the layers its board has, so a two-layer module could never
carry a keepout onto a four-layer parent's inner pours: one declared on every
layer arrived on F and B, and the parent's pours filled under it on the inner
layers.

To pick it up: re-run each module's placemat script so its keepouts carry the
marker, then regenerate and re-run the boards that stamp it. A parent that
restated a module's clearance by hand still works, and now duplicates a region
the module brings; the copy can come out.

A keepout on a layer its board does not have is now a finding rather than a
region that silently holds nothing.

## To 0.16

Nothing to change in a script. Two additions to every run, and a fix to 0.15:

**The design checks run on every board.** `placemat check` was the only way to
get hot-loop, switch-node, keep-out, crossing, current-path and heat verdicts;
`placemat run` now runs them on the board it wrote and prints a `checks` line.
`run.json` gains `verdicts`, and the metrics gain `checks_failed` and
`checks_unjudged`. A board with no `Pm.*` facts says so on that line. A failed
check does not change the exit code, as a DRC violation does not.

**A run made with `--no-drc` is not judged against the best.** 0.15.0 read its
missing airwire and violations as zeros, so such a run became the best
possible one and every measured run after it failed as a regression against
airwire 0. It now reads "not judged", and a `best.json` that already holds
such a run ignores it: the next measured run takes its place.

## To 0.15

**`placemat run` can now exit 1 on a board that placed.** Every finished run
is judged against the best earlier run of the same parts, and a run that comes
out worse is a finding naming the metric and a non-zero exit. A loop or a CI
job that treated exit 0 as "placed" should read the `best` line: exit 1 with
everything placed means worse than before, not broken.

Nothing in a script changes. The first run after upgrading is the first of its
family, so it becomes the best and passes. `best.json` sits beside
`latest.json` in `.placemat/runs/`; delete it to start the comparison afresh.

`[best] airwire_noise` (default 0.01) is how far airwire may move before it
counts. kicad-cli reports a different set of ratsnest edges each run for a
byte-identical board - four runs of the same inputs gave 2868.87 to 2873.11 mm
- so `airwire_mm` and `crossings` wobble slightly between
identical runs. Neither is exact; compare them across runs with that in mind.

## To 0.14

**A `board.link` on a plane net now pulls, so parts move.** It always measured
the distance and reported it against `limit_mm`; it just never contributed to
where the part went. A limit that is measured and reported reads as a
constraint in force and losing to something, not as one that never ran.

Planes stay excluded from seeding for everything nobody declared - a net with
two hundred pads gives a centroid that means nothing - but a declared link
names two specific pads, so that reason does not apply to it. A link is how
to say two parts belong together when the only net they share is a plane.

If a script worked around this with `at=Near(Part(<the other part>))`, the workaround
still wins - an explicit hint beats a seed - so nothing breaks, but the `Near`
is now redundant and can come out. Re-run and expect the parts that were
reported over their limits to have moved toward the pins they serve.

## To 0.13

Nothing to change. `placemat datasheet` gains `--read`, which lists the facts a
sheet could be made to yield with the page, position, channel and confidence
behind each, and `check`, which compares a `.kicad_mod` against values you
supply and says whether the sheet mentions them at all.

A page with almost no text of its own is now read off its render with
`tesseract` when that is installed. It is optional; `--no-ocr` turns it off.
OCR reads wrong as well as right - on one measured sheet it returns 4.95 for a
dimension the drawing gives as 4.55, at confidence 78 against 86 to 96 for its
correct neighbours - so a confidence travels with every sourced number and
`check` against a real footprint is what catches the rest.

placemat does not recover pad geometry from a drawing. On that same sheet the
pads are drawn as hatching: 276 of the land-pattern view's 453 paths are
two-point line segments, and the largest group of equal boxes on the page is
outlined text. Pad values are supplied, corroborated and compared, not parsed.

## To 0.12

Nothing to change. `placemat datasheet <pdf>` is new: it ranks the pages
against land pattern, package dimensions, layout rules and pin map, prints the
evidence behind each ranking, and `--show` renders the page you should look at.
It shells out to mupdf and poppler, which join kicad-cli as tools placemat
expects to find; `tesseract` is used when installed and skipped with a note
when not.

## To 0.11

**Re-run every board and expect it to move.** A footprint that draws no
courtyard now claims its physical extent - pads, silk and fab together -
where it used to claim exactly its pads. Nothing in a script changes, but the
layout a script produces does, and a script that placed cleanly on 0.10 can
report a collision on 0.11.

The old answer understated any part whose body overhangs its pads by the whole
of the overhang. On one measured board, 13 of 43 footprints draw no courtyard,
and the worst claimed 70 mm2 of the 334 mm2 they stand on: the body overhangs
the pads by about 9 mm on one side. Two things read that number, so two things
change:

- **The placement rank.** Searched items are ordered by courtyard area, so a
  large part with no courtyard used to rank as a small one and go down last,
  among the parts it should have been placed before. Expect a different order, and
  read the printed rank rather than reaching for `priority=`.
- **The collision check.** A part under such a body is now a finding rather
  than silence. Those findings are real: a part under another part's body
  does not assemble. Move the part; do not widen a clearance to silence it.

A collision on the first 0.11 run is therefore a defect the old envelope was
hiding, not a regression. `placemat measure <board> <part>` prints the
`courtyard` box a part now claims beside its `body` and `physical` boxes, which
is the quickest way to see what changed for one part.

## To 0.10

Nothing to change. Two commands are new and one has grown, and an agent that
does not know about them will keep grepping footprints by hand.

`placemat parts <board>` lists every part: instance, refdes, face, cell,
courtyard area, pin count, value.

`placemat measure <board> <part> --pads` prints its position, its `body`,
`courtyard` and `physical` boxes, how near it comes to the board edge, and
every pad's number, net, layers, drill, centre and **copper box**. The copper
box is the box round the pad's outlines: for a custom pad the anchor size is
not the copper, and reading the anchor is how a via ends up inside a pad.

`placemat measure <path>.kicad_mod` does the same for a footprint that is not
on a board, with its SHA-256.

Both take `--json`.

## To 0.9

Nothing to change in a script. Two behaviours are stricter and two reports say
more.

**`placemat drc` now refuses a board with no `.kicad_pro` beside it.** kicad-cli
substitutes its own design rules for a board without one, so the report
measured KiCad rather than the board: on a real four-layer board that is 1263
violations against a true 313, including 199 `track_width` items that do not
exist. If you review a board by copying it somewhere, copy the `.kicad_pro` and
any `.kicad_dru` with it.

**A rerun no longer destroys the previous run's route.** A run directory is
named by a hash of its inputs, so a rerun landing on the same id writes a
byte-identical board and the route taken on the old one is still a route of it.
It used to be deleted silently. A run that routes replaces it, as before.

**Footprint defects have their own bucket.** `lib_footprint_issues`,
`lib_footprint_mismatch`, `malformed_courtyard` and `padstack` now read as
`footprint issues N (extents for those parts are unreliable)` instead of going
into `other`. They do not block a board, but placemat's extent for an affected
part cannot be trusted. A reader of `run.json` will find them gone from
`other`; `[drc] footprint_kinds` sets the list.

**A cross-face courtyard finding says why.** `U9 courtyard overlaps R31
courtyard (U9 holds both faces: 4 through-hole pads, none with a net)`. A pad
with no net is usually a footprint defect rather than a real via field.

## To 0.8

**Back-face parts move. Cells do not.**

A flip to the back now mirrors about the vertical axis - KiCad's F key - for a
part and a cell alike, and `rotation=` is applied after it. Before, a lone part
mirrored top-to-bottom while a cell mirrored left-to-right, and the planner and
the writer disagreed about where a part's pads landed by `180 + 2r`, where `r`
is the rotation the generator left the part at.

**Drop any monkeypatch of `Occupancy._transform`.** It was masking the bug for
parts at generated rotation 0 and 180 and creating it for those at 90 and 270.
`grep -n "Occupancy._transform" <script>` finds it.

**A script that compensated by hand cannot be grepped for.** If a back-face
part carries `rotation=180` where the board wanted it upright, it will now be
upside down. Look for back-face parts whose rotation was chosen by trial rather
than from the mechanics, and read the render.

**KiCad's orientation field now reads `rotation + 180`** for a back-face part.
Nothing is wrong: that is what its own flip produces.

A board with no back-face parts is unaffected.

## To 0.7

Nothing to change in a script. Three things get stricter, and one report is new.

**A keepout's `layers=` is now honoured when copper is checked.** A board that
widened `allow=` to silence a complaint about copper on a layer the region does
not cover should take those nets back out: the `allow=` admits them on the
layers that DO matter. `boards/main/Main_layout.py` is the known case.

**A region that hangs off the board edge now forbids.** It used to be discarded
whole, silently, so a script could read as though a rule were in force when it
was not. Expect new findings from a region that was never being applied - they
are the point. A region WHOLLY off the board is now an error, because it
forbids nothing while the script says otherwise.

**A stamped cell's rule areas are no longer deleted.** `pcb layout` copies a
module fragment's regions into the parent, inside the cell's group; placemat
used to delete every rule area on the board before writing its own. A parent
that stamps a module declaring a clearance will newly report parts and copper
inside it. On a board that filled a ground pour under an antenna, that is the
finding that was missing.

**New: the `seeded` line.** It says which nets pulled how many items into
place. One net seeding most of the board means a missing `board.plane()`.

## To 0.6

Read this only if the check in `SKILL.md` matched, or a script fails at import
with `AttributeError: type object 'Priority' has no attribute 'FIXED'`.

### What changed, in one paragraph

`Priority` used to carry four unrelated facts. It now carries one. Whether a
position is decided is `Freedom`, derived from the place you gave it and never
written by hand. Which searched item goes next is a **rank**, worked out from
the item's courtyard area and pin count. Whether failing to place something
stops the run is `required=`. `Priority` is left with `HIGH`, `DEFAULT` and
`LOW`, which a script sets and nothing else does.

### Find the script's legacy use

```sh
grep -nE "Priority\.(FIXED|EDGE)|priority=Priority\.HIGH|priority=Priority\.LOW" <script>
```

Each hit is one of the four cases below. A script with no hits needs no source
change, but read "What moves without you touching anything" at the end.

### 1. `Priority.FIXED` or `Priority.EDGE` on copper

```python
board.via(GND, Location(12.0, 30.0), priority=Priority.FIXED)
board.track(V48, [pad_a, pad_b], layer=F, priority=Priority.FIXED)
```

**Delete the argument.** When a piece of copper is planned is now derived from
its endpoints: copper whose every endpoint belongs to something nothing will
move - a decided part, a cell already down, or plain coordinates - is planned
before the search and becomes an obstacle to it. Copper naming a searched part
is planned after the search.

```python
board.via(GND, Location(12.0, 30.0))
board.track(V48, [pad_a, pad_b], layer=F)
```

The derivation gives the same answer wherever the endpoints were already
decided, which is every case that used to be legal: `priority=Priority.FIXED`
on copper naming a searched part was refused before, so no script has one.

If the intent was "this track wins at a crossing", that is still a priority and
still spelt the same way, but with a level that exists:
`priority=Priority.HIGH`.

### 2. `Priority.FIXED` or `Priority.EDGE` on a placement

```python
board.place(Part("j1"), at=Location(20, 20), priority=Priority.FIXED)
```

**Delete the argument.** This was already refused at declaration time ("the
declaration decided this position, so ... priority=fixed has nothing to
order"), so a working script cannot contain one. If you find one, the script
was never run.

### 3. `priority=Priority.HIGH` to get a big part down early

```python
board.place(Part("l_vbus"), priority=Priority.HIGH)   # a big inductor that kept getting stranded
```

**Delete the argument and run.** This is the workaround the rank exists to
remove. A large, sparsely connected part now goes down early on its own: the
rank scores courtyard area and pin count, so a 31 mm2 two-pin inductor outranks
a shelf of 0402s whatever their net fan-out.

Read the step line before deciding you still need the override:

```
usbconverter.l_vbus   part   rank 19/220   at (32.01, 18.37) rot 0 face back
```

Keep `priority=Priority.HIGH` only if the rank is demonstrably wrong for that
board, and write the reason beside it. It is now a tier **above** the rank,
not a replacement for it.

### 4. `priority=Priority.HIGH` to make a failure fatal

```python
board.place(Cell("mcu"), priority=Priority.HIGH)   # this MUST be placed
```

**Use `required=True`.**

```python
board.place(Cell("mcu"), required=True, why="the MCU has nowhere else it can go")
```

HIGH used to mean two things at once: go first, and stop the run if there is
nowhere to go. It now means only the first. `required=True` means only the
second, works on a decided placement as well as a searched one, and holds even
under `--keep-going`.

**placemat no longer decides on its own that a failure is fatal.** If a script
relied on the old auto-HIGH stopping a run, nothing stops it now: the item is
left off the board, reported as a finding, and the run carries on. Mark the
items that genuinely cannot be left off.

### What moves without you touching anything

**Every board re-places.** The rank replaces the tier, and link pull drops from
the primary sort key to a tie-break, so the order searched items go down in
changes on every board. Expect a large `impact` diff on the first run. Read the
DRC and crossing numbers, not the diff size.

**Copper at literal coordinates becomes an early obstacle.** A track or via
given plain coordinates is now planned before the search, so a searched part's
pads must clear it. This is the intended behaviour and the most likely source
of new findings on the first run. A part that can no longer find a spot is
telling you the copper was always in its way.

**Every run id changes**, because the tool version moved and the resolved
settings joined the hash. The first run after upgrading has nothing to compare
against; `placemat impact <old> <new>` across the boundary still works.

**A run record reader needs updating.** In `run.json`, a step's `priority` is
now `null` for a decided placement, because it has none:

| was | is |
|---|---|
| `steps[].priority == "fixed"` | `steps[].freedom == "fixed"` |
| `steps[].priority == "edge"` | `steps[].freedom == "edge"` |
| `steps[].priority == "high"` | `steps[].priority == "high"` (unchanged: a script said so) |
| nothing | `steps[].rank`, `steps[].rank_of` on a searched placement |
| nothing | `steps[].freedom` on a copper step: which batch planned it |

**A script that monkeypatched the placer.** `_weigh` and `_CRITICAL_SHARE` are
gone, replaced by `Board._rank` and `placemat.ranking`. A patch against either
name fails loudly rather than silently doing nothing.

### While you are here: placemat.toml

Nothing to migrate - a project with no `placemat.toml` behaves exactly as it
did. But the constants a script used to work around by editing placemat, or by
passing a flag every time, now have a home:

```toml
# electronics/placemat.toml
[place]
step = 0.1              # this board is laid out on a 0.1 grid

[check]
ambient_c = 85.0        # was --ambient 85 on every invocation

[drc]
real_kinds = ["clearance", "shorting_items", "hole_clearance"]
```

`placemat settings` prints every resolved value and the file it came from. The
full table is in `api.md`.
