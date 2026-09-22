# A back-face part is where the planner says it is

Date: 2026-09-22
Status: design, awaiting approval

## What is wrong today

The occupancy model and the writer disagree about where a footprint's pads land
when it is placed on the back face. The planner decides legality, clearance and
copper endpoints from one answer; KiCad gets the other.

**The planner** (`occupancy.py:153-161`) mirrors left-right and then turns by
the difference between the target rotation and the rotation the generator left
the part at:

```python
t = Transform.translate(-ref.location.x, -ref.location.y)
if flip:
    t = t.then(Transform.mirror_x(Location(0, 0)))
t = t.then(Transform.rotate(placement.rotation - ref.rotation))
```

**The writer** (`write.py:39-43`) flips through KiCad and then sets the
orientation absolutely:

```python
if target.face != current.face:
    fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
fp.SetOrientationDegrees(target.rotation)
```

Probed directly against KiCad 10: `FOOTPRINT::Flip` with
`FLIP_DIRECTION_LEFT_RIGHT` mirrors the footprint's stored pad offsets
**top to bottom** and sets the orientation to `180 - orientation`. The
`SetOrientationDegrees` on the next line then discards that 180.

Writing `r` for the part's rotation in the generated board and `t` for the
rotation the script asked for:

```
writer   =  R(t)          . mirror_y . relative pads
planner  =  R(t - 2r)     . mirror_x . relative pads
         =  R(t - 2r + 180) . mirror_y . relative pads
```

so the two differ by a rotation of `180 + 2r`. Measured end to end on the
committed Breakout - place a part on the back, `apply_plan`, read it back, and
compare against `Occupancy.pad_location`:

```
U7  r=0    t=0    planned->written turn 180
U7  r=0    t=90   planned->written turn 180
U2  r=90   t=0    planned->written turn   0
U8  r=180  t=0    planned->written turn 180
U5  r=270  t=0    planned->written turn   0
```

On `U7`, a four-pad part at generated rotation 0, the planner puts pad 1 at
x 49.45 and the file has it at x 34.21 - the pad order is reversed along the
part.

Everything downstream inherits it: `Pin()` placements, `PadRef` endpoints in
copper, via-in-pad drops, and every clearance the occupancy model judged.

**The workaround in use is not sufficient.** `boards/main/Main_layout.py`
monkeypatches `Occupancy._transform` to mirror top-bottom
(`Transform(d=-1.0)`). That gives `R(t - 2r) . mirror_y`, which agrees with the
writer only when `r` is 0 or 180. It silently breaks the parts the current code
happens to get right, at `r` 90 and 270.

**The planner's convention is the wrong one on its own terms.** Because its
answer depends on `r`, two identical parts the generator happened to drop at
different rotations, both declared `rotation=0, face=Face.BACK`, are planned as
physically different orientations. A script cannot say what it means. The
writer's answer does not depend on `r` and is the one to keep.

## What changes

`Occupancy._transform` loses the `r` term and mirrors the axis the writer
mirrors, for a **footprint**:

```
translate(-loc)  ->  rotate(-r)  ->  mirror_y  ->  rotate(t)  ->  translate(target)
```

That is exactly `R(t) . mirror_y . relative pads`: undo the generator's
rotation to reach the part's own frame, mirror it the way KiCad's flip does,
then apply the rotation the script asked for. The unflipped path is unchanged.

`rotation=` on a back-face part therefore means what it means in KiCad: the
orientation the footprint is set to, read on the back, with the part mirrored
about its own horizontal axis. This is stated in `api.md`, because nothing says
it today.

### Cells keep their own path, and it is tested rather than assumed

`_transform` is shared by footprints and cells, and the writer handles them
differently. `_move_cell` (`write.py:46-64`) flips each item about the cell's
pivot with `FLIP_DIRECTION_LEFT_RIGHT` and then applies a **relative** rotate,
which composes to a genuine world left-right mirror about the pivot - matching
the planner's `mirror_x`. A cell's reference rotation is always 0
(`Placement(body.center, 0.0, Face.FRONT)`), so the `r` term is already absent
and there is nothing to fix.

So the change must be per-kind, not global. `ItemGeometry` gains
`kind: str` ("part" or "cell"), set in `_register` and `_geometry`, and
`_transform` branches on it. Applying the footprint fix to cells would break
the case that currently works.

This asymmetry is real and pre-existing: a lone part placed on the back is
mirrored top-to-bottom, and the same part inside a cell is mirrored
left-to-right, so the two differ by half a turn. **This spec does not change
it**, because doing so would move every back-face cell on every board and is a
separate decision. It does add a cell-flip parity test, so the claim that cells
already agree is verified rather than asserted - and if that test fails, it is a
second finding to be specced on its own.

## Test plan

The parity test is the deliverable, not the transform edit.

With KiCad, against the committed Breakout:

1. **Footprint parity across every generated rotation.** The Breakout carries
   a suitable multi-pad front footprint at each of the four: `U7` at `r=0`,
   `U2` at 90, `U8` at 180, `U5` at 270. Place each on the back at `t` in
   {0, 90, 180, 270}, write the board, read it back, and assert every pad from
   `Occupancy.pad_location` matches the file within 1e-6 mm. Sixteen
   combinations; today eight of them are wrong.
2. **The same for a part left on the front**, so the fix is shown not to
   disturb the unflipped path.
3. **Cell parity.** Flip a cell to the back at each rotation and compare its
   members' pads the same way. Asserted, not assumed.
4. **Byte stability.** Writing the same plan twice is still byte-identical
   (`test_write_roundtrip` already covers this; it must keep passing).

Without KiCad:

5. `_transform` on a synthetic part at `r=90` flipped to the back puts a known
   asymmetric pad at the hand-computed point - a unit test that fails on the
   old transform for a reason that can be read without KiCad.
6. An unflipped placement's transform is unchanged for every `r`.

## Documentation

- `api.md`, under Placement: what `rotation=` means on `face=Face.BACK`, and
  that a cell and a lone part flip about different axes.
- `references/migration.md`: a new section. Back-face parts move; a script
  that monkeypatched `Occupancy._transform` must drop the patch, and one that
  compensated by hand in its rotations must take the compensation out.

## Out of scope

- Making a lone part and a cell member flip about the same axis. Worth
  deciding, but it moves every back-face cell and belongs in its own spec with
  its own migration note.
- `read_board` reporting a placed pad's position as a query. That is the
  `placemat measure` work from `PLACEMAT_GAPS.md`, and this spec's parity test
  builds the mechanism it would use.

## Migration

**Every back-face part moves**, or rather every back-face part that was being
written somewhere other than where it was planned now agrees with the plan. On
a board whose script was tuned against the written result, the parts will
appear to move by half a turn; on one tuned against the plan, they will stop
moving.

`boards/main/Main_layout.py` must drop its `Occupancy._transform`
monkeypatch. The patch is currently masking the bug for the parts at generated
rotation 0 and 180 and creating it for those at 90 and 270, so removing it and
taking the fix is strictly better, but the board will re-place and needs a DRC
read afterwards.

A board with no back-face parts is unaffected. The Breakout is single-sided in
this sense and is expected to write identical bytes.
