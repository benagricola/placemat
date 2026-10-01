# Past over copper, a row at a pitch, a part off a lane, a plane over parts

Status: approved (2026-09-29).

Source: A board's `PLACEMAT_GAPS.md` 2026-09-29 entries:

- "a lane held off a via, and a via held off pad ends";
- "beside a part, offset along its side by a pitch";
- "a plane bounded to a group of parts".

Also a board session's report on the ten modules still built from
lanes. Its rough count of lane relations per module:

| module | lanes |
|---|---|
| module A | 34 |
| module B | 55 |
| module C | 38 |
| module D | 23 |
| module E | 15 |
| module F | 11 |
| module G | 9 |
| module H | 8 |
| module I | 6 |
| module J | 3 |

In each case a module script on 0.54 still computes a coordinate by hand,
from pad tips, a pad centre or a group's box.

## Problem

1. `Past([pads], Edge.X)` gives a track waypoint the track's clearance off
   pads. It takes no vias or tracks, is accepted only as a track point, and
   is always centred across the pads. The scripts need:
   - a via a via's clearance past a row of contact tips, on one pin's axis;
   - a track's U-turn a track's clearance past those vias;
   - the same under a converter's pin rows.
2. `row(of=Part(...))` runs items along a part's side at the envelope gap,
   placed by `Along.START/MID/END`. Two pogo pins 2.7 mm apart (a mechanical
   pitch), centred on a driver's pin north of it, cannot be said: `centre=`
   is refused with `of=`, and a row has no centre-to-centre pitch.
3. A part whose pad stands a lane's width (track plus two clearances) past
   another part's pads, so a track runs down between them. Example: the
   enable FET south of the bypass capacitor, with its gate pad a lane west
   of the regulator's input capacitor and PA3's gate line running between
   them. `Beside` decides one axis; nothing decides the other from a lane.
4. A plane over a group of parts only. A plane takes the frame or an
   outline of points. The scripts build the outline from a group's box by
   hand, so a part placed by `Beside` outside that box falls off the plane.

## Design

### 1. Past takes copper, and a via may stand at it

`Past(items, edge, across=None)`:

- `items` holds pads (`PadRef`/`CellPadRef`), vias (what `board.via()` or
  `board.vias(along=)` returns) and tracks (what `board.track()` returns),
  in any mix.
  - The edge is read off their combined copper box.
  - The offset is the worst clearance from the thing standing at the point
    to any of them, by net pair. A pad with no net uses the default
    clearance, as now.
- `across=` sets where the point lies across `edge`, in place of the
  middle of the box:
  - a `PadRef` or a via: on that item's centre line;
  - an `Along.START/MID/END` of the box's side (default `MID`, as now).
- A track point at `Past(...)` is offset by half the track's width, as now.
- `board.via(net, at=Past(...))` is new: the offset is the via's radius
  plus its clearance, so the via stands just clear of the items.
- It waits for every item: pads to be placed, and vias and tracks to be
  planned.
- If a via or track it names found no spot, the point is not drawn. That is
  the same finding a track ending on such a via gets now.

The USB case, with no coordinates:

```python
d_minus = [board.via(Net("D-"), at=Past(TIPS, Edge.SOUTH, across=PadRef(J1, p)))
           for p in ("A7", "B7")]
board.track(Net("D+"), [PadRef(J1, "A6"), Past(d_minus, Edge.SOUTH), PadRef(J1, "B6")], layer=F)
```

### 2. A row along a part, centred on a pad, at a pitch

`board.row(items, Edge.X, of=Part(...), centre=PadRef(...), pitch=2.7)`:

- `centre=` with `of=` takes a `PadRef`: a pad of `of`, or of any part
  placed firmly by then.
  - The row's middle lands on that pad's centre line along the side,
    instead of at `Along.START/MID/END`.
  - It cannot be given together with `align=`.
- `pitch=` is the distance between neighbouring items' centres along the
  row, in place of `gap=` between their envelopes.
  - A pitch that brings two envelopes closer than the envelope gap is
    refused at declaration, naming both items and the pitch needed.
  - It cannot be given together with `gap=`.
  - The row still stands the envelope gap off `of`.

The pogo case:

```python
board.row([Part("pogo_a"), Part("pogo_b")], Edge.NORTH, of=Part("u1"),
          centre=PadRef(Part("u1"), 8), pitch=2.7)
```

### 3. A part's pad a lane past copper

`Past` becomes an `align=` target of `Beside` in the pair form:
`Beside(item, side, align=(own_pad, Past(items, edge, lane=Net(...))))`.

- Across `side`, `own_pad`'s facing edge stands past the items' `edge`:
  - with `lane=` a net, the distance is three parts: the clearance from the
    items to that net, that net's track width, and the clearance from that
    net to `own_pad`'s net. That leaves room for one track of the net
    between them.
  - without `lane=`, the distance is the clearance from `own_pad`'s net to
    the items.
- `items` is the same list as in design item 1 (pads, vias and tracks).
  Their copper must be placed or planned by then, as for any firm
  placement.
- `Beside` still decides the other axis. For the enable FET:

  ```python
  Beside(Part("c_vdd"), Edge.SOUTH,
         align=("G", Past([PadRef(Part("c_in"), 1)], Edge.WEST, lane=Net("PA3"))))
  ```

- The gate track then takes the waypoint `Past([PadRef(Part("c_in"), 1)],
  Edge.WEST)`, which is the same line.

### 4. A plane over named parts

`board.plane(net, layers, over=[Part(...), Cell(...)], margin=0.0)`:

- The zone's outline is the box round the named items' drawn envelopes,
  grown by `margin` and clipped to the frame. The envelope is the same
  region `keepout(item)` takes, including a footprint's copper graphics.
- It waits for the items to be placed.
- `over=` and `outline=` cannot be given together.
- A winding in the same cell is kept off with
  `board.keepout(Part(...), excludes=(Forbid.FILL,))`. That keepout now
  covers the winding's copper graphics.

## Out of scope

- A keepout inside a part's pad ring, such as the region between a
  receiver's two pad columns. That needs a separate form, after this.
- `pitch=` on a row along the board's own edge.

## Verification

- Unit tests for each form:
  - a via at `Past` over pads, and over vias;
  - a track point at `Past` over vias, and over tracks;
  - `across=` a pad, a via and an `Along`;
  - mixed nets taking the worst clearance;
  - the row at a pitch centred on a pad;
  - a pad a lane past pads, with and without `lane=`;
  - a plane over two parts, one of them placed by `Beside`;
  - the refusals.
- Migration tests for the USB lane, the pogo pair and the enable FET. Each
  compares the hand-computed position with the intent form and must agree
  within 0.01 mm, as the 0.54 migration tests do.
- The full suite, then the bench (the row and lane changes are placement
  changes).
