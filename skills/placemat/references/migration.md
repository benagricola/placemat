# Migrating a layout script

Sections are per release, newest first. Read the ones between the version a
script was written against and the version in use; `SKILL.md`'s check line says
whether any of it applies.

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
