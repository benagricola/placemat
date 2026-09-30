# Keepouts drawn for hand placement, and a push

Status: draft, for approval.

Source: Ben, through a board's session (2026-09-30).

## 1. Keepouts drawn for hand placement

**Today.** Every keepout is written as a KiCad rule area named
`keepout <name>`, on its copper layers, with KiCad's flags for what it
excludes (`write._draw_keepouts`).

KiCad shows a rule area only on a copper layer, as a hatch, and nothing on
it says what the keepout admits. A keepout that admits parts by height or
by name looks the same as one that admits nothing. KiCad's DRC reports the
admitted parts inside it as `items_not_allowed`; placemat's DRC grading
already counts those as permitted.

**Design.** Alongside the rule area, the write draws each keepout that
admits something (`allow=` or `max_height=`) on a drawing layer, as:
- its outline, as a closed polyline at `write.keepout_line` width
  (0.1 mm);
- a text at the outline's centroid, `write.keepout_text` high (0.8 mm),
  saying its name and what it admits:
  - `<name>: parts <= 0.90 mm` for a height;
  - `<name>: U3, U4` for parts named by `allow=`, and `<name>: GND copper`
    for nets;
  - joined with `; ` when there are several.

The layer is the Fab layer of the keepout's face (`F.Fab` for a keepout on
F.Cu), or `User.Comments` for one on both faces or on inner layers only.
`write.keepout_drawings` chooses which keepouts are drawn:
- `"admitting"` (the default): those that admit something;
- `"all"`: every keepout;
- `"none"`.

These drawings are placemat's own:
- They belong to one group, `keepout drawings`.
- A rerun replaces the group whole, removing the old items with
  `board.Delete`.
- A stamped fragment's own keepout drawings belong to its cell's group and
  move with it, as its rule areas do.

## 2. A push

**Problem.** A part that must stand far from a source (a field sensor from
a magnet, a temperature-sensitive part from a heat source) is placed today
with `Near` on a hand-picked far point. The script then carries the
geometry that the physics decides, and the spot it reaches depends on the
hint rather than on how strong the effect is.

**Design.**

```python
board.push(Part("m.u2"), from_=Part("m.m1"), falloff=3, reference=(13.5, 3.2),
           limit=0.3, why="field at the sensor")
```

**The model.** The effect at distance `r` mm from the source is
`value(r) = v_ref * (r_ref / r) ** falloff`, from `reference=(r_ref, v_ref)`
in the script's own units:
- a dipole's field falls off as the cube (`falloff=3`);
- heat spreading through a plane falls off roughly linearly (`falloff=1`).

`r` runs from the source's point to the item's point:
- **The source** (`from_=`) is a part or a cell (its body centre), a
  `PadRef`, a keepout by name (its centroid), or a `Location`.
- **The item** is a part (its body centre) or a `PadRef` on it, for
  where the sensing element is.

**Hard limit.** Where `value(r)` exceeds `limit=`, the item may not stand.
That is a disc round the source of radius
`r_ref * (v_ref / limit) ** (1 / falloff)`, reserved for this item alone.
It is refused like any reservation, naming the push: "u2: the field
from m1 would be 0.41 at 11.9 mm (limit 0.3)".

**Soft score.** Within what is legal, each candidate is priced by
`score.push` (default 10) times `value(r) / limit`. So the search moves the
item as far out as its other terms (links, priority, room) allow. The price
is the physics, not a distance.

**Several pushes.**
- Several pushes on one item add their values.
- A source that is itself searched is placed first: the push is an order
  dependency, as a link is.
- A push does not move the source.

**Report.** The item's step notes the modelled value where it landed and the
limit: "push from m1: 0.21 at 15.9 mm (limit 0.3)". `placemat check` does
not re-judge it: the model is the script's.

**The search.** A searched item with a push and no position hint is searched
over the whole board, with the push's price in the score, not near a hint.
It is also a new reason for a wide scan: that is what "as far as the board
allows" asks for.

## Verification

- Keepout drawings:
  - a height keepout on F.Cu writes an outline and "k: parts <= 0.90 mm"
    on F.Fab in the `keepout drawings` group;
  - one admitting nothing is not drawn under the default and is drawn
    under `"all"`;
  - a rerun leaves one group, not two;
  - both-face keepouts go on User.Comments.
- Push:
  - a part pushed from a source with falloff 3 and a limit lands at a spot
    whose modelled value is at or under the limit, and further out than a
    run without the push;
  - a spot inside the limit disc is refused with the sentence;
  - two pushes add;
  - a pushed item waits for its source;
  - `falloff=1` against 3 gives a different disc radius, from the
    formula;
  - the step note gives the value and the distance.
- The full suite, a release, then the bench (the push is a placement
  change, though no bench module declares one).
