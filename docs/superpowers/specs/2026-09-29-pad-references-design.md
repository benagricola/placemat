# Pad edges, envelopes and arithmetic as references; copper from pads

Date: 2026-09-29
Status: approved 2026-09-29 (Ben: implement unless a decision is needed)
Source: PLACEMAT_GAPS.md (fairing), 2026-09-29 "a position that is a sum of an
x and a y" and "pad edges and drawn envelopes as placement and copper
references". The fairing's workaround helpers are the reference behaviour:
`boards/core/fragment_frame.py` (`beside`, `drawn_from_pad`, `pour`,
`pour_box`, `placed_size`) and `modules/usb5v/Usb5v_layout.py` (`edge_at`,
`edge`, `pads_pour`, the SW lane at 228-236).

## The problem

Every fragment script places parts and draws copper from pad edges, drawn
envelopes and 45-degree lanes by doing the arithmetic in Python first:
- A reference names a pad by its centre only: `PadRef`, `.offset()` and
  `.local()` (`values.py:361-393`).
- `X`, `Y` and `Mid` (`values.py:423-442`) take a number offset and add to
  nothing.
- `_locate`/`_coord` (`layout.py:4233-4274`) accept an enumerated set of
  types.
- A drawn envelope is a one-off `Box` (`board.envelope()`,
  `envelope.drawn_envelope`), not a position another item can be placed
  against.
- `X(Part)` is the part's body-box centre, which is not its origin (0.1 mm
  apart on the TPS55288), and nothing says so.

## The change

### References (values.py; resolved in `_locate`/`_coord`; tracked by `_refs_in`)

1. **Pad edges and size.** Each is resolved where the pad stands, from its
   copper box turned with the part:
   - `PadRef(...).edge(side)`: the pad's edge. `side` is "n", "s", "e" or
     "w" in board directions, and gives a coordinate (x for e/w, y for n/s).
     A corner "ne", "nw", "se" or "sw" gives a point.
   - `PadRef(...).width()` and `.height()`: the pad's width and height as it
     stands.
   - The same on `CellPadRef`.
2. **Arithmetic on coordinates.** `X`, `Y`, an edge, a width, a height and
   the types below add and subtract with each other and with numbers, and
   multiply and divide by numbers. Each expression is resolved when
   everything it names is placed, and can go anywhere a coordinate can: in
   `X(...)`/`Y(...)` offsets, `Pin`, `Centre`, `Location`, track points and
   pour corners. Examples:
   - `X(a) + Y(b) - k`, a point on a 45;
   - `(A.edge("e") + B.edge("w")) / 2`.
3. **`Origin(part)`**: the part's footprint origin where it stands, as a
   point. api.md says that a `Part`/`Cell` used as a point is its body box's
   centre, not its origin.
4. **`Envelope(item, side)`**: the side ("n", "s", "e" or "w") of a placed
   part's or cell's drawn envelope as it stands, as a coordinate. The drawn
   envelope is what `envelope.drawn_envelope` gives: pads, mask and silk.

### Placement

5. **`at=Beside(ref, side, gap=, level=None, pad=None)`** places the item on
   `side` of `ref`'s drawn envelope, with its own drawn envelope `gap` away:
   - `ref` is a Part or Cell.
   - `level`, a coordinate reference, sets the other axis: the item's `pad`
     (or, without one, its envelope's centre) is placed level with it.
   - It is a firm placement like `Pin`. It waits for `ref` (and anything
     `level` names) to be placed, and takes the item's own envelope at the
     rotation it is given. This is `fragment_frame.Content.beside` and
     `drawn_from_pad`, said once.

### Copper

6. **`board.lane(pads, side, width=None, clearance=None)`** returns a
   coordinate reference, the centreline a track may run on beside `pads`:
   - It is the furthest `side` edge of the pads, plus the clearance
     (default: the board's clearance for the track's net class, else the
     default clearance), plus half the width (default: the default track
     width).
   - A lane between two sets of pads is two lanes and their midpoint. If the
     gap is narrower than one track and two clearances, that is a finding
     naming both sets. This replaces the hand `assert` in `Usb5v_layout.py`.
7. **`board.pour_pads(net, pads, fillet=0.0, layer=None)`** is a pour whose
   outline is the box round the named pads' copper where they stand.
   - It is inset by `fillet` and stroked at twice it, so only the corners
     round. This is `fragment_frame.pour`'s fillet rule.
   - The layer defaults to the pads' own.
   - A pad of another net inside the box is a finding.
8. **`board.finger(..., width=)`** also takes a coordinate reference
   (`PadRef(...).width()`), so a neck the width of a pin reads from the pin.
9. **Docs**: api.md sections for each, with the Usb5v `pads_pour` and SW
   lane written in the new terms as the example.

## Verification

Pure tests with the synthetic fixtures, each asserting the resolved numbers:
- **Pad edges and size:**
  - `edge()` for each side and corner, on a part at 0, 90 and 180 and on
    the back;
  - `width()`/`height()` turning at 90.
- **Arithmetic:**
  - `X(a) + Y(b) - k` in a track point;
  - `(e1 + e2) / 2` in a `Pin`;
  - dependency waiting (an expression naming a searched part is placed
    after it);
  - an expression with an unplaced reference is refused as `X`/`Y` are
    today.
- **Origin:** `Origin` where the body centre and the origin differ.
- **Envelope and Beside:**
  - `Envelope` sides of a part with silk past its pads;
  - `Beside` on each side, with and without `level=`/`pad=`, the placed
    envelopes `gap` apart (read back with `drawn_envelope`).
- **Lanes:** `board.lane` values; the finding for a too-narrow gap between
  two lanes.
- **Pads-to-pour:** `pour_pads` outline and fillet; the finding for a
  foreign pad inside.
- **Finger width:** `finger` width from a pad.
- **Existing behaviour:** existing reference tests pass; a declaration
  digest that uses none of the new types is unchanged (locks still hold).

## Not in scope

- A general constraint solver; every expression resolves once its names are
  placed.
