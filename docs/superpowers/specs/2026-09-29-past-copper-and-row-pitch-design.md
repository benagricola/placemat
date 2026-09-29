# Past over copper, and a row at a pitch on a pad

Status: draft, for approval.

Source: fairing `PLACEMAT_GAPS.md`, 2026-09-29 entries "a lane held off a
via, and a via held off pad ends" and "beside a part, offset along its side
by a pitch". Both are cases where a module script still computes a
coordinate from pad tips or a pad centre, with 0.54.0.

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

## Design

### 1. Past takes copper, and a via may stand at it

`Past(items, edge, across=None)`:

- `items` holds pads (`PadRef`/`CellPadRef`), vias (what `board.via()` or
  `board.vias(along=)` returns) and tracks (what `board.track()` returns),
  in any mix. The edge is read off their combined copper box. The offset is
  the worst clearance from the thing standing at the point to any of them,
  by net pair (the default clearance for a pad with no net, as now).
- `across=` sets where the point lies across `edge`, in place of the
  middle of the box:
  - a `PadRef` or a via: on that item's centre line;
  - an `Along.START/MID/END` of the box's side (default `MID`, as now).
- A track point at `Past(...)` is offset by half the track's width, as now.
- `board.via(net, at=Past(...))` is new: the via's radius plus its
  clearance, so it stands just clear of the items.
- It waits for every item: pads to be placed, and vias and tracks to be
  planned. A via that finds no spot is the same finding a track ending on
  it gets now.

The USB case, with no coordinates:

```python
d_minus = [board.via(Net("D-"), at=Past(TIPS, Edge.SOUTH, across=PadRef(J1, p)))
           for p in ("A7", "B7")]
board.track(Net("D+"), [PadRef(J1, "A6"), Past(d_minus, Edge.SOUTH), PadRef(J1, "B6")], layer=F)
```

### 2. A row along a part, centred on a pad, at a pitch

`board.row(items, Edge.X, of=Part(...), centre=PadRef(...), pitch=2.7)`:

- `centre=` with `of=` takes a `PadRef`: the pad of `of` or of any part
  placed firmly by then. The row's middle lands on that pad's centre line
  along the side, instead of at `Along.START/MID/END`. It cannot be given
  together with `align=`.
- `pitch=` is the distance between neighbouring items' centres along the
  row, in place of `gap=` between their envelopes. A pitch that brings two
  envelopes closer than the envelope gap is refused at declaration, naming
  both items and the pitch needed. It cannot be given together with `gap=`.
  The row still stands the envelope gap off `of`.

The pogo case:

```python
board.row([Part("pogo_a"), Part("pogo_b")], Edge.NORTH, of=Part("u1"),
          centre=PadRef(Part("u1"), 8), pitch=2.7)
```

## Out of scope

- Placing a part itself at a `Past` point (a resistor standing in a lane).
  `Beside` already stands a part off a part. The lane cases in the gaps file
  need a part off a track, and that waits on a concrete case.
- `pitch=` on a row along the board's own edge.

## Verification

- Unit tests for each form:
  - a via at `Past` over pads and over vias;
  - a track point `Past` over vias and over tracks;
  - `across=` a pad, a via and an `Along`;
  - mixed nets taking the worst clearance;
  - the row at a pitch centred on a pad;
  - the refusals.
- Migration tests: the USB lane and the pogo pair, hand-computed against
  the intent form, equal within 0.01 mm, as the 0.54 migration tests are.
- The full suite, then the bench (the row change is a placement change).
