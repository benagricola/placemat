# Facing for grids, in rows and by where a pad lands; sides and row order from pads

Status: approved (2026-10-01).

Source: a board's session (2026-10-01), converting scripts to `Facing` (0.69.0).

## Problem

`rotation=Facing(pads, edge)` turns a part so the way out of the pads (their
row's outward axis) points at an edge. Scripts still compute numbers or flags
to say five things it cannot:

1. A ball grid has no pad rows. `Facing([B2, A2], Edge.SOUTH)` on a 2x2 grid
   is refused ("pad B2 has no way out to turn by: it is a square pad at a
   corner of the pad field"), though the intent is plain: that grid column on
   that side.
2. `board.row(items, edge, rotation=...)` takes numbers, not `Facing`: two
   capacitors in a row with pad 1 west, four FETs each with its drain south.
3. A side that depends on where a pad lands after a turn: which end pin 1
   lands at (to pick a `Beside` side), whether a supply pad is east (to put
   pull-ups on that side). Scripts compute `0 if ... else 180` and keep a
   `VCC_EAST` flag.
4. A turn toward a pad: `Facing(PadRef(cap, "SUPPLY"), Edge.WEST if VCC_EAST
   else Edge.EAST)`. The intent is that the supply pad faces the chip's supply
   pin, whichever side that lands on.
5. Row order by the pins the members serve: `[r_sda, r_scl] if SDA_WEST else
   [r_scl, r_sda]`. The intent is that each pull-up stands over the pin it
   pulls.

## Design

### Way out of pads with no row

`facing_rotation` takes each named pad's way out from its row, as now. When
any named pad has none (`_pin_normal` returns None: a square pad at a corner
of the pad field, a lone pad), the way out of the whole named set is the
direction from the pad field's centre (the centre of the box of all the
part's pad centres, as `_pin_normal` reads it) through the named pads'
centroid, snapped to the nearest axis. For a grid the pads named are the
outermost toward the side: a column or row of it.

It is refused, saying why, when the direction is ambiguous: the centroid at
the field's centre (no direction), or its offsets equal on both axes within
1e-6 mm (a diagonal: two axes are equally near). Pads that all have a row
behave as before, including the refusal for pads of two rows.

### Facing in a row and with a bare pad key

A `Facing`'s pads may be bare pad keys (an int number, a net name, a
`Net`, `PinName`) as well as `PadRef`s: the key names a pad of whichever
part is being turned. A `Facing` of keys is for a row, where one value serves
every member, and works in `place()` as well. A `PadRef` of another part is
refused as before; a `Facing` does not mix keys and `PadRef`s.

`row()` (and `ring()`, and a row along a run) take `rotation=` as a number, a
`Facing`, or a list with one of either per member, as they took numbers.
Each member resolves its `Facing` for itself, on the front face.

```python
board.row([Part("c1"), Part("c2")], Edge.NORTH, rotation=Facing(1, Edge.WEST))
board.row(fets, Edge.WEST, rotation=Facing("DRAIN", Edge.SOUTH))
```

### SideOf: the side where a pad lands

`SideOf(pads)` is a side that waits for a part. In `Beside(item, side, ...)`
the side may be a `SideOf`; once the pad's part is placed it is the board
side that the pad's way out points at, with the part's placed turn and face
applied, snapped to the nearest axis (a turn off the right angles that lands
on a diagonal is refused, as in the grid rule). `pads` is a `PadRef` or a
list, as `Facing` takes, and the way out is the one `Facing` reads, so the
two always agree.

```python
board.place(Part("pullup"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC"))))
```

The `SideOf` part is placed before the `Beside` item; with the part itself as
`item` this waits for nothing else. A `SideOf` side with `align=` of a `Past`,
a lane or an `X`/`Y` point is refused: those check the side against the axis
they decide, which is not known until the part is placed. `align=` of
`Along` or a pad is accepted.

### Facing toward a pad

`Facing(pads, toward=PadRef(other, key))` replaces the edge. Its turn is the
one where the pads' way out points opposite the way out of the target pad: the
pad faces the target pad, for a part standing on the side of the target's part
where the target's pad lands (as `Beside(other, SideOf(target))` stands it).
It is settled when the part is placed, which waits for `other`, as a `Turned`
is. `toward` and `edge` are exclusive; `toward` in a row is refused, since a
row measures its members before anything it waits for is placed.

```python
board.place(Part("c"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC"))),
            rotation=Facing(PadRef(Part("c"), "SUPPLY"), toward=PadRef(Part("u"), "VCC")))
```

`Facing(pad, SideOf(...))` as the edge was considered and not built: it
would need a way to say the opposite side as well.

### Row order by the pads served

`board.row(items, edge, over=[target, ...])`: one `PadRef` per member, in the
members' order. The row's order is the order the targets lie along the row's
axis (x for a north or south row, y for east or west, increasing), settled
when the targets are placed; the row waits for them. Equal coordinates are
refused naming the members. `over=` composes with every anchor (`of=`,
`centre=`, `start=`, `align=`); a row with `over=` is measured when its
items are placed, as a row placed by a reference is.

```python
board.row([Part("r_sda"), Part("r_scl")], Edge.NORTH, of=Part("u"),
          centre=PadRef(Part("u"), "SDA"), over=[PadRef(Part("u"), "SDA"), PadRef(Part("u"), "SCL")])
```

An order derived from the members' links was considered and not built. A
member's net reaches several pads of `of=`, or none directly (a series part
between), so the derivation is a guess in the cases that matter; explicit
pairs state the reason.

### Eager query

`board.side_of(PadRef, rotation=Facing(...))` is not built. The cases above
(a `Beside` side, a turn toward a pad, a row's order) are all relations now.
A script that has to branch on a side has a case the relations do not
cover, and the case is what to spec.

## Verification

Tests, all on synthetic boards:

- A 2x2 grid: `Facing([B2, A2], SOUTH)` turns so the east column faces
  south, each of the four edges; the same on the back face. `Facing(B2, ...)`
  alone is refused (diagonal), as is the centre pad of a 3x3 grid; a QFN
  corner pad's refusal now names the diagonal.
- A row of two parts with `Facing(1, Edge.WEST)`; a row of four with
  `Facing("DRAIN", Edge.SOUTH)`; a per-member list mixing a number and a
  `Facing`; `Facing` of another part's `PadRef` in a row refused.
- `Beside(u, SideOf(pad))`: u turned 0, 90, 180, 270 and on the back face, the
  part stands on the side where the pad is (compared to the pad's measured
  position against the part's centre).
- `Facing(pad, toward=...)`: with the target part at each of the four turns
  and on the back face, the placed pad is on the side facing the target pad.
- `row(over=)`: the same four turns and the back face; the members' order
  follows the targets and each sits nearer its own target than the other's.
  Equal coordinates refused; a row with `over=` and a count that does not match
  refused.
- `Facing`, `SideOf` and a row without `over=` digest as before.

## Addendum: the end of a pin row (2026-10-01)

Source: a board's session on 0.72.0. A part's bypass stands past the END of
a package, on the side where pin 1 or a supply pin lands, not on the row's
outward normal that `SideOf(pad)` gives. A flag for which end pin 1 lands at
kept the script's side in step with its turn.

`SideOf(pad, along=True)` is the board side of the row's end the pad is
nearer. The row is the pads sharing the pad's way out (`_pin_normal`); along
its axis (across the way out) the end is the side of the middle between the
row's outermost pad centres that the pad lies on, with the part's placed
turn and face applied as `SideOf` does. It names one pad. It is refused,
saying why, for a pad within 1e-6 mm of the row's middle (the middle pin of
an odd row: neither end is nearer) and for a pad with no row (a grid, a
corner pad, a lone pad), where the pad's row has no ends to name.

Facing toward a row end: `Facing(pads, toward=SideOf(PadRef(other, key),
along=True))`. `toward=` takes a `PadRef` (the pad's way out) or a `SideOf`
(either way); the turn is the one where the pads' way out is opposite that
side, so the pads face `other`, for a part that stands `Beside(other, <the
same SideOf>)`. A `toward=PadRef(...)` is the same as `toward=SideOf(
PadRef(...))`. Chosen over a flag on `PadRef` (`PadRef(u, 1, along=True)`)
because `SideOf` already names "a side that waits for a part" and `toward=`
needs only to accept it; a `PadRef` flag would leave a pad reference that is
not a pad. `along` is omitted from a `SideOf`'s digest while False.

```python
board.place(Part("bypass"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), 1), along=True)),
            rotation=Facing(PadRef(Part("bypass"), "SUPPLY"), toward=SideOf(PadRef(Part("u"), 1), along=True)))
```

Tests (`tests/test_sideof_along.py`): a 10-pin and an 8-pin dual-row package,
the first and last pin of each row, at the four turns and on the back face:
the part stands on the end the placed pad lies at (measured off the placed
pads against the centroid of their row), and a pad of the part faces the
package; declared before the package; a mid-row pad refused; a pad with no
row refused; two pads refused; the digest unchanged until `along` is set.
