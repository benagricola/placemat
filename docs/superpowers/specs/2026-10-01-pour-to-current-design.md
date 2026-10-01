# A fitted pour that widens until its net's current-path width is met

Status: approved (2026-10-01), follows "A fitted pour that reaches into the
room round it" (2026-10-01-fitted-pour-reach-design.md), which left this as
its follow-up.

Source: a board's session (2026-10-01), with the user's preference relayed:
a fitted pour that widens until its net's current-path width is met is
preferred over `reach=mm`.

## Problem

`reach=mm` takes a distance. For a switch node the distance was picked by
trial: the pour failed `check current-path`, and the script carried a number
that stands in for "carry 3.6 A at a 10 C rise". Nothing derives it, and it
goes stale when the current, the rise, the copper weight or the pads move.
The facts it stands for are already on the board: `Pm.I` on the parts, the
rise `[check] rise_c`, the copper weight from the stackup. The check reads
them; the plan does not use them.

## Design

### The form

```python
board.pour(Net("SW"), [PadRef(Part("q1"), 1), PadRef(Part("l1"), 1)], layer=CopperLayer.F,
           swallow_pads=True, reach=Reach.CURRENT)
```

`Reach.CURRENT` (`values.py`, exported) is a second kind of value for
`reach=`; a number keeps its meaning. It is an explicit form: a default for
fitted pours on nets the check covers would move every existing board, and
the digest of a declaration without it is unchanged.

It takes a fitted pour (`swallow_pads=True` over pads and vias, no `width=`),
as a number does. It is refused at the declaration when the net has no
current to size for: fewer than two parts of the board carry current on the
net (`Pm.I`), which is when `check current-path` does not judge it either.

### The width needed, and the width met

Both are the check's. `checks.py` gains two functions, each a piece of what
`current_paths` already does, and `current_paths` calls them:

- `carriers_of(geometry)`: per net, `{ref: amps}` from the parts' `Pm.I`
  (moved out of `current_paths`);
- `pour_current(...)`: the pour's copper, the member pads and vias and the
  carriers among them are given to `_pairs` (the route search, `_Fill.width`
  and `_need_mm`, IPC-2221 with the check's constants) exactly as a read
  board's items are, and the worst pair is returned: the width reached, the
  width needed, the current, the two parts and the neck's point. Nothing
  here is a second formula.

The inputs are the check's: `[check] rise_c`, `checks.COPPER_OZ` where the
stackup gives no weight, `BoardGeometry.copper_mm` per layer, and
`[check] zone_step` for the raster, so the plan and a later `placemat check`
read the same copper at the same step. The pour's copper is the outline
grown by half the stroke, as the occupancy holds it and as it is read back.

Carriers are the members' own parts. Copper outside the pour that also joins
them (a track) is not counted, so the pour meets the need by itself.

### How far to grow

The grown copper (`reach=` of a distance) only gains with the distance, and
the width the check reads gains with it. The reach is therefore the smallest
multiple of `[copper] pour_reach_step` (default 0.05 mm) whose copper meets the
need, searched by bisection over the multiples up to `[copper]
pour_reach_max` (default 5.0 mm):

1. at 0 (the fitted outline itself) the need is met: the pour is the fitted
   outline, no booleans, no finding;
2. at the maximum the need is met: the smallest multiple that meets it;
3. at the maximum it is not met: the smallest multiple that reaches the width
   the maximum reaches, so the pour does not keep growing where more room
   adds nothing, and a finding is made (below).

Each candidate is `polyops.grow_and_cut` as `reach=mm` does it, cut back by
the same clearance outlines, so the room is the room `reach=` has. It needs
pcbnew at plan time, as `reach=` does.

A uniform reach rather than growth at the neck alone: the neck is found by
the check's raster, which the written outline does not follow, and a
uniform margin keeps the outline's edges parallel to the fit's.

### Where there is not enough room

The pour is drawn at the width it reached, and a finding says: the net, the
current and the rise, the width reached and the width needed, the neck's
point, and the nearest other copper to the neck when one stands within the
reach. `check current-path` then reports the same neck.

When the net's members leave fewer than two carriers (a pour over one part's
pads, the other carrier joined by track), the pour is not drawn and a
finding says which part is missing. Nothing can be sized for a single
carrier.

### Settings

| key | default | meaning |
| --- | --- | --- |
| `copper.pour_reach_step` | 0.05 | mm: the step `Reach.CURRENT` grows by |
| `copper.pour_reach_max` | 5.0 | mm: the furthest it grows |

Both are above zero. No literal in code.

## Verification

Synthetic and written boards as `tests/test_pour_reach.py`'s; a new
`tests/test_pour_to_current.py`.

- Plan: two pads carrying 3.6 A whose hull fails the check pass it with
  `Reach.CURRENT`; the reach chosen is one step under the reach at which the
  check passes, so a smaller one fails; a pour whose hull already passes is
  the fitted outline; the pour equals `reach=` of the distance it chose.
- Room limited by another net's pad: a finding names the neck's point, the
  width reached and the width needed; the pour is drawn at the reach where
  the width stopped gaining.
- Refused at the declaration: a net with no current facts, a net with one
  carrier, `width=`, no `swallow_pads`; a pour whose members hold one
  carrier is a finding and not drawn.
- The settings: a different step changes the chosen distance; a maximum
  below the need leaves the finding.
- Written board (pcbnew, `kicad-cli`): the pour passes `check current-path`
  read back, no zone, DRC clean (no clearance or shorting).
- A declaration without the form digests as before; one with it does not.
- The bench's tally is in the commit message.
