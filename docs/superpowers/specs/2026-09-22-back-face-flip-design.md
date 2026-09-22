# A flip to the back is one operation, and it is KiCad's

Date: 2026-09-22
Status: design, awaiting approval

## What is wrong today

Two faults, and the second turns out to cause the first.

### The planner and the writer disagree about a back-face part

The occupancy model decides legality, clearance and copper endpoints from one
answer; KiCad gets another.

**The planner** (`occupancy.py:153-161`) mirrors left-right, then turns by the
difference between the target rotation and the rotation the generator left the
part at:

```python
t = Transform.translate(-ref.location.x, -ref.location.y)
if flip:
    t = t.then(Transform.mirror_x(Location(0, 0)))
t = t.then(Transform.rotate(placement.rotation - ref.rotation))
```

**The writer** (`write.py:39-43`) flips through KiCad, then sets the orientation
absolutely:

```python
if target.face != current.face:
    fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
fp.SetOrientationDegrees(target.rotation)
```

Writing `r` for the part's rotation in the generated board and `t` for the
rotation the script asked for, the two compose to `R(t) . mirror_y` and
`R(t - 2r) . mirror_x` respectively, which differ by `180 + 2r`. Measured end
to end on the committed Breakout - place on the back, `apply_plan`, read back,
compare against `Occupancy.pad_location`:

```
U7  r=0    t=0    planned->written turn 180
U7  r=0    t=90   planned->written turn 180
U2  r=90   t=0    planned->written turn   0
U8  r=180  t=0    planned->written turn 180
U5  r=270  t=0    planned->written turn   0
```

On `U7`, a four-pad part at generated rotation 0, the planner puts pad 1 at
x 49.45 and the file has it at x 34.21: the pad order is reversed along the
part. Everything downstream inherits it - `Pin()` placements, `PadRef` copper
endpoints, via-in-pad drops, and every clearance the occupancy model judged.

The workaround in `boards/main/Main_layout.py` - monkeypatching
`Occupancy._transform` to mirror top-bottom - gives `R(t - 2r) . mirror_y`,
which agrees only when `r` is 0 or 180. It fixes half the board and breaks the
half that was accidentally right.

### A part and a cell flip about different axes

A lone part placed on the back is mirrored top-to-bottom. The same part inside
a cell is mirrored left-to-right. The two differ by half a turn, and nothing
says so.

**This is placemat's doing, not KiCad's.** Probed against KiCad 10,
`FOOTPRINT::Flip(pivot, direction)` is a genuine world mirror about the pivot
in the direction named, adjusting the orientation to suit:

```
LEFT_RIGHT rot 0   orient    0.0 ->  180.0   world mirror-x: True   mirror-y: False
LEFT_RIGHT rot 30  orient   30.0 ->  150.0   world mirror-x: True   mirror-y: False
TOP_BOTTOM rot 0   orient    0.0 ->   -0.0   world mirror-x: False  mirror-y: True
TOP_BOTTOM rot 30  orient   30.0 ->  -30.0   world mirror-x: False  mirror-y: True
```

It behaves identically for a lone footprint and for every item of a group.
`_move_cell` (`write.py:46-64`) uses it and lets it stand, so a cell flips
about the vertical axis, correctly. `_place_footprint` calls
`SetOrientationDegrees` on the very next line, discarding the 180 the flip
computed and converting a world x-mirror into a y-mirror.

So one line creates the asymmetry, and the same line creates the parity bug.

## What a flip means, after this

**Left-right, for a part and a cell alike**: the item is mirrored about the
vertical axis and then turned by `rotation=`.

That is KiCad's own default. `editing.flip_left_right` is `true` in the shipped
configuration of KiCad 7, 9 and 10, so pressing F in pcbnew mirrors about the
vertical axis. A part declared `rotation=0, face=Face.BACK` therefore reads
orientation **180** in KiCad's properties - which is exactly what a user gets
by drawing that part upright on the front and pressing F. The gesture and the
number agree.

## What changes

Two lines, no branch by kind.

**The planner** keeps `mirror_x` and adds the reference rotation instead of
subtracting it:

```python
t = t.then(Transform.rotate(placement.rotation + ref.rotation if flip
                            else placement.rotation - ref.rotation))
```

which composes to `R(t) . mirror_x . relative pads`, free of `r`. A cell's
reference rotation is always 0 (`Placement(body.center, 0.0, Face.FRONT)`), so
`t + 0 == t - 0` and **cells are untouched**. One transform serves both kinds;
the `ItemGeometry.kind` field an earlier draft of this spec proposed is not
needed.

**The writer** stops discarding the flip's orientation:

```python
if target.face != current.face:
    fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetOrientationDegrees(target.rotation + 180)
else:
    fp.SetOrientationDegrees(target.rotation)
```

`_move_cell` is unchanged.

### This pair is verified, not derived

Driving the proposed writer through pcbnew against the committed Breakout and
comparing every pad with the proposed planner transform, for a multi-pad
footprint at each generated rotation and each target rotation:

```
U7  r0=0    t=0/90/180/270   worst pad error 0.000000 mm   OK
U2  r0=90   t=0/90/180/270   worst pad error 0.000000 mm   OK
U8  r0=180  t=0/90/180/270   worst pad error 0.000000 mm   OK
U5  r0=270  t=0/90/180/270   worst pad error 0.000000 mm   OK

0 mismatches of 16
```

## Test plan

The parity test is the deliverable; the two-line edit is not.

With KiCad, against the committed Breakout:

1. **Footprint parity across every generated rotation.** The Breakout carries a
   suitable multi-pad front footprint at each: `U7` at `r=0`, `U2` at 90, `U8`
   at 180, `U5` at 270. Place each on the back at `t` in {0, 90, 180, 270},
   write, read back, and assert every pad from `Occupancy.pad_location` matches
   the file within 1e-6 mm. Sixteen combinations; today eight are wrong.
2. **The unflipped path is undisturbed**: the same sixteen with
   `face=Face.FRONT`.
3. **Cell parity**, the same way, at each rotation. Cells are expected to pass
   before and after; the test exists so "cells were already right" is checked
   rather than asserted.
4. **A part and a cell containing only that part land in the same place** when
   both are flipped to the back at the same rotation. This is the asymmetry,
   and it is the test that would have caught it.
5. **Byte stability**: `test_write_roundtrip`'s identical-plan-twice test keeps
   passing.

Without KiCad:

6. `_transform` on a synthetic part at `r=90` flipped to the back puts a known
   asymmetric pad at a hand-computed point; the test fails on the old transform
   for a reason readable without KiCad.
7. An unflipped placement's transform is unchanged for every `r`.

## Documentation

Three files, and none of them is optional: this changes what a script MEANS,
so a reader who does not learn the new rule writes a board that is half a turn
wrong and cannot see why.

**`api.md`**, under Placement and under Layers and faces: a flip to the back
mirrors about the vertical axis, the same for a part and a cell, matching
KiCad's F key; `rotation=` is applied after the mirror; KiCad's orientation
field reads `rotation + 180` for a back-face part, which is what its own flip
produces.

**`SKILL.md`**, two changes:

- A sentence in Placement tactics saying what a flip is, because an agent
  placing a part on the back has no way to know otherwise and the wrong guess
  is invisible until DRC: *"A flip to the back mirrors about the vertical axis
  - KiCad's F key - and `rotation=` is applied after it. A part and a cell flip
  the same way. KiCad's own orientation field will read `rotation + 180`."*
- The legacy-detection line near the top gains this release's marker, so the
  check catches a script written against the old convention:

  ```sh
  grep -nE "Priority\.(FIXED|EDGE)|priority=Priority\.(HIGH|LOW)|Occupancy\._transform" <script>
  ```

  A monkeypatch of `Occupancy._transform` is the one mechanically detectable
  sign. A script that compensated by hand, with `rotation=180` where it meant
  0, cannot be grepped for, which is why the migration section leads with how
  to recognise it on the board.

**`references/migration.md`**: a new section, below.

## Out of scope

- `read_board` reporting a placed pad's position as a query. That is the
  `placemat measure` work in `PLACEMAT_GAPS.md`; this spec's parity test builds
  the mechanism it would use.
- A `[place] flip_axis` setting. A flip axis changes what a script MEANS, so two
  boards in one repository could read the same and differ. It is a definition,
  not a preference.

## Migration

`references/migration.md` is currently one document for one release. It gains a
section per release, newest first, and `SKILL.md`'s check points at the file
rather than at a version - otherwise the second migration overwrites the first
and a project two releases behind is stranded.

**Back-face parts move. Cells do not.** A cell's flip is unchanged, and a board
with no back-face parts is unaffected - the Breakout writes identical bytes.

`boards/main/Main_layout.py` must drop its `Occupancy._transform` monkeypatch.
It is currently masking the bug for parts at generated rotation 0 and 180 and
creating it for those at 90 and 270, so removing it and taking the fix is
strictly better; the board re-places and wants a DRC read afterwards.

A script that compensated by hand - a back-face part carrying `rotation=180`
where `rotation=0` was meant - must take the compensation out. The symptom of a
missed one is a part 180 degrees from where the script reads.

A board that placed a part on the back and a cell containing a similar part on
the back, and tuned both against the written result, will find the part moves
and the cell does not.
