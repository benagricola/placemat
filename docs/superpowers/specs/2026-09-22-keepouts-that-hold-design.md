# A keepout that holds: layers, the board edge, and a stamped cell's own

Date: 2026-09-22
Status: design, awaiting approval

Three ways a declared region is not enforced, and two reports that would have
named the cause. Every one of them is recorded in `PLACEMAT_GAPS.md` and
verified in the source.

## What is wrong today

### A keepout's `layers=` is ignored when copper is checked

`_check_keepouts` (`layout.py:824-841`) never reads `k.layers`. It tests the
excludes, the allow list and a polygon overlap, and reports. Reproduced:

```python
board.keepout(Circle(10.0), "antenna", at=Location(20, 20), layers=(CopperLayer.F,))
board.track(Net("GND"), [Location(5, 20), Location(35, 20)], layer=CopperLayer.B)
# -> track GND crosses keepout 'antenna' ...
```

The track is on B and the region is on F. `PlacedKeepout` already carries
`layers`; nothing asks it. On the main board this reported SW1 and SW2 on B
against the MCU's antenna keepout on F, IN1 and IN2, and was worked round with
`allow=`, which admits those nets on every layer including the ones that
mattered.

### A keepout that reaches off the board is discarded whole

`settle_keepout` (`layout.py:1782-1808`): when `_keepout_illegal` returns
`"reaches outside the board"` it appends a finding and skips both `occ.reserve`
and `plan.keepouts`. No reservation, no rule area, and the script still reads as
though the rule is in force. Reproduced: `plan.keepouts` empty,
`occupancy.reservations` empty, one soft finding.

On `fairing-instrument` this silently dropped `coated_zone`, a sealing
requirement, and placed 27 parts in coated territory. The cause was geometric
and tiny: the fence's outer boundary was the board outline sampled into chords,
and a chord across an arc bulges a fraction outside the true curve.

A free-placed keepout does not even stop the run without `--keep-going`,
because it settles after `place_ranked`'s collision check.

### A stamped cell's rule areas are destroyed

`_draw_keepouts` (`write.py:113-115`) deletes **every** rule area on the board
before writing the plan's own:

```python
for z in list(board.Zones()):
    if z.GetIsRuleArea():
        board.Delete(z)                 # a rerun replaces them, never doubles them
```

and `read.py` never reads a rule area, so `BoardGeometry` has no idea they
exist and the placer cannot honour them.

**The generator does its part.** In `boards/main/.placemat/generated/Main/layout.kicad_pcb`
- the unscripted board straight from `pcb layout` - the gnss_antenna module's
two keepouts are present as `keepout antenna_1` and `keepout antenna_c_1`, and
**both are members of the `ant_rf` group**. `_move_cell` moves every item of a
cell's group, so they would travel with the cell correctly. placemat deletes
them a moment later.

The cost was a board: the ground pours filled under the antenna on all four
layers, and nothing in the run or the DRC said so.

### Two reports that would have named a cause

`_reason_key` (`placer.py:132-136`) collapses every rejection to one word, so a
finding reads `courtyard x1842` and the reader cannot tell whether one
neighbour or forty is in the way, or on which face. `Occupancy.who()` already
formats an owner with its cell; the sentence is computed and thrown away.

And a board with no `plane()` declared pulls every part sharing GND to one
centroid: 155 of 220 on the modular core, all seeded within a few millimetres
of the board centre. `_targets` excludes declared plane nets from the pull, so
the fix is to declare the plane - but nothing says that is what happened.

## What changes

### 1. Layers are part of the test

`_check_keepouts` skips an op whose layer the region does not cover:

```python
if k.layers is not None and not (_layers_of(op) & set(k.layers)):
    continue
```

`_layers_of` is the op's own: `{op.layer}` for a `Track` or a `Pour`, and every
copper layer for a `Via`, which spans the stack. `k.layers is None` keeps
meaning "every copper layer the board has", so nothing narrows by accident.

### 2. A region is used as declared, and only a wholly-absent one is an error

`"reaches outside the board"` stops being a reason to discard. The region is
reserved and written exactly as declared, and the step says how much of it fell
outside.

A region **wholly** outside the board - every one of its points outside - is
still an error, because it forbids nothing and the script says otherwise. That
is the one case the original check was right about. It raises `ValueError` from
`settle_keepout` and is NOT subject to `--keep-going`, because it is a script
error of the same class as declaring two keepouts with one name, which
`board.keepout` already raises for.

**No polygon clipping is performed, and none is needed.** `Occupancy.legal`
refuses a part for crossing the keep-in before it tests any reservation, so the
off-board part of a region can never refuse anything; and KiCad clips a zone to
Edge.Cuts itself. Clipping would be observably identical - the same parts
fenced, the same rule area - and would mean either writing a polygon-boolean
primitive (the board outline may be concave, so Sutherland-Hodgman does not
suffice) or reaching into pcbnew from `layout.py`, which would break the rule
that everything outside `kicad/` is pure Python.

The measurement reported is the count of the region's own points that fall
outside the board, which `_keepout_illegal` already walks and throws away:

```
coated_zone   keepout   fixed   kept clear at 0.00, 0.00; 4 of its 361 points are off the board
```

An area fraction was the obvious thing to report and is the wrong one. The
`coated_zone` case is a region whose boundary IS the board outline, so its area
and its bounding box are both indistinguishable from the board's and any area
measure reads as 0% - useless for exactly the case this exists to catch. A
point count is cheap, needs no boolean, and says the diagnostic thing: four
chords bulge past the arc.

Cutouts are untouched. A hole over the sea removes no material, and "that is a
notch, and it belongs in the board's own outline path" is already the right
message.

### 3. A rule area placemat did not write is kept, read and honoured

**Kept.** `_draw_keepouts` deletes only rule areas that belong to no group:

```python
for z in list(board.Zones()):
    if z.GetIsRuleArea() and _group_of(z) is None:
        board.Delete(z)
```

Group membership is exactly the right discriminator, and it needs no marker or
naming convention:

| rule area | in a group? | what happens |
|---|---|---|
| placemat's own, this board's script | no | deleted and rewritten each run |
| a stamped cell's, from its module | yes, the cell's | kept, and moved by `_move_cell` |
| one whose declaration was deleted from the script | no | deleted, so nothing leaks |

**Read.** `BoardGeometry` gains `rule_areas: tuple[RuleArea, ...]`:

```python
@dataclass(frozen=True)
class RuleArea:
    name: str                     # the zone name, e.g. "keepout antenna_1"
    cell: str | None              # the group that owns it, if any
    polygon: Polygon              # in the generated board's coordinates
    layers: frozenset[CopperLayer]
    excludes: frozenset[str]      # parts | fill | tracks | vias | pads
```

read through `GetIsRuleArea`, `GetZoneName`, `Outline`, `GetLayerSet` and the
five `GetDoNotAllow*` getters, all confirmed present in KiCad 10.

**Honoured.** A rule area that excludes `"parts"` becomes a reservation:

- one owned by no cell is reserved at `resolve()` time, in the coordinates it
  was read at, because nothing will move it;
- one owned by a cell is reserved when that cell is **committed**, from the
  polygon put through the same transform the cell's shapes take, because its
  position is not known until the cell lands.

The second has a consequence worth stating: items placed **before** the cell do
not see its keepout. That is inherent - the region has no position yet - and it
is exactly how the cell's own courtyard already behaves.

`allow` is empty for a read rule area: the module that declared it named its
own parts, and those names do not survive stamping. A parent that needs to
admit something restates the region itself, which is what it does today.

**A name collision is refused.** `board.keepout(shape, name, ...)` raises when
`"keepout %s" % name` matches a rule area already on the generated board, so a
script cannot shadow a stamped cell's region and quietly have one of them win.

### 4. A finding names who blocked, and on which face

`Occupancy.legal` gains an optional `blame` list. When one is passed it appends
a `Blocker(kind, owner, faces)` for the conflict it found; every existing caller
is unaffected because the parameter defaults to `None` and the return type does
not change.

`scan()` passes a list and tallies by `(kind, owner, face)`. The finding then
spends what was already computed:

```
logic.l_rf_supply: no legal location within 6.0 mm of (24.1, 30.5)
  (courtyard x1842: cell logic's U18 back face x1204, cell logic's C30 front
  face x410, cell display's U4 front face x228; edge x310)
```

Three owners, because the fairing case needed exactly one name to point at the
MCU's via field and a list of forty is unreadable. The owner string is
`Occupancy.who()`, which already names a cell member with its cell.

### 5. The run says which nets seeded what

`Board` tallies the nets named in each `seeded on ...` step note, and the run
prints them largest first:

```
script   165 placed, 71 finding(s)
seeded   GND 155, V3V3 40, SPI1 12, I2C 9, +5 more
```

No threshold and no verdict: `GND 155` beside a 220-part board is self-evident,
and a declared plane net never appears at all, because `_targets` already
excludes plane nets from the pull. The same counts go into `run.json` as
`metrics.seeded_by_net`.

## Errors and findings, in full

| situation | today | after |
|---|---|---|
| copper crosses a region on a layer it covers | finding | unchanged |
| copper crosses a region on a layer it does NOT cover | finding | silent |
| region partly off the board | finding, region discarded | region enforced; step notes the fraction |
| region wholly off the board | finding, region discarded | `ValueError` naming the region, not silenced by `--keep-going` |
| a script name collides with a stamped region | silent, one wins | error naming both |
| a stamped cell's region | deleted | kept, moved, and reserved |

## Test plan

Without KiCad, on synthetic geometry:

1. a track on B is silent against a keepout declared `layers=(F,)`, and a track
   on F is still a finding;
2. a via is caught by a region on any single layer, because it spans the stack;
3. a region with `layers=None` still catches copper on every layer;
4. a region partly off the board is in `plan.keepouts` and in
   `occupancy.reservations`, and a part inside its on-board part is refused;
5. that region's step note counts the points that were outside;
6. a region wholly off the board raises `ValueError` naming it, and still
   raises under `keep_going=True`;
7. a keepout named to collide with a rule area on the generated board raises;
8. `legal(..., blame=[])` appends the blocking owner and its faces, and the
   return value is unchanged;
9. a scan that fails reports the top three owners with faces and counts;
10. seeded-net counts are tallied and reported largest first, and a declared
    plane net never appears.

With KiCad:

11. a board carrying a rule area in a group keeps it after `apply_plan`, and a
    group-less one is replaced;
12. reading a board with rule areas fills `BoardGeometry.rule_areas` with the
    name, cell, layers and excludes;
13. a part is refused for sitting in a cell's stamped keepout after that cell is
    committed;
14. against the committed Breakout, which declares no keepouts, the written
    bytes are unchanged.

## Documentation

- `api.md`, Keepouts: `layers=` narrows what is CHECKED as well as what is
  written; a region may hang off the board edge and only the on-board part
  does anything; a stamped cell's regions arrive with it and are honoured.
- `api.md`: `metrics.seeded_by_net` in the run record.
- `SKILL.md`: read the `seeded` line - one net seeding most of the board means
  a missing `plane()`, not a placement problem.
- `references/migration.md`: a board that worked round the layer bug with
  `allow=` should take the nets back out.

## Out of scope

- Passing the regions to the external router as obstacles. KRT ignores rule
  areas; that is a separate entry in `PLACEMAT_GAPS.md` and a separate piece of
  work.
- A first-class `Ring(inner, outer)` region, and "the board minus this shape".
  Both would have removed the need for the hand-traced path that caused the
  off-board case, and both are worth doing; neither is needed to make a
  declared region hold.
- `allow=` on a read rule area. A module's part names do not survive stamping,
  and inventing a mapping is a bigger question than this spec.

## Migration

No script changes are required, and no existing test changes behaviour except
by getting stricter.

A board that worked round the layer bug by widening `allow=` keeps working; the
`allow=` is now unnecessary and slightly dangerous, because it admits those nets
on the layers that DO matter. `boards/main/Main_layout.py` is the known case.

A board whose stamped cell keepouts were being deleted will newly report parts
and copper inside them. On the fairing main board that is the antenna
clearance, and those findings are the point.
