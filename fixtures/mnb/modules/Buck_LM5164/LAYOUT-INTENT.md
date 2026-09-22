# Buck_LM5164 layout intent

Compact 100 V synchronous buck, 1 A, LM5164 in SO-8-EP: the rail cell for
footprint- and height-limited boards.

The spec `Buck_LM5164_layout.py` implements and the fragment in `layout/` must
satisfy. Rules that apply to every module are in `modules/README.md`; how
layout is done is the `pcb-layout` skill. History lives in git.

## Structure

Spec source: the datasheet's own layout section (SNVSAU4A 10.1).

**One column, not a block.** Every small-signal part except the divider's top
stands in a single column east of the package at a 2.00 mm pitch, so each net's
pads are neighbours on one line and the chain reads down it: the FB pair
adjacent, RIPPLE either side of RA's switch-node pad, then the output tap and
RON. The regular pitch is what reduces the column's own routing to four short
segments.

**The divider's top sits on the FB pin's own axis**, north of the package,
sharing that row with the bootstrap cap, so the pin's sense connection is one
straight run up its own centreline.

**The output caps form a row with their ground pads outboard** - a via fence on
one line, the vout pads inboard where a single pool swallows them and the
inductor's output together. The input bank's supply pads line up on the VIN
pin's x, and each is its own plane tap.

**Every local net is a pool, not a trace.** vout, SW, vin, FB, EN and BST are
each a polygon covering exactly the pads it can physically swallow. The board's
planes do the distributing, so the cell owns local copper plus four runs and
nothing else.

**The vout sense goes UNDER the package**, through the annulus between the
exposed pad and the south pad row. That is why this cell claims no perimeter: a
sense line round the outside reserves the whole edge from every board that
stamps it, and the annulus is free board on this layer.

Envelope 11.61 x 13.82 mm including copper (10.97 x 13.82 by courtyard).

Where the datasheet's numbered rules land:
- **1/2** input bypass across the ADJACENT VIN and GND pins, HF cap straddling
  them and the bulk behind it; nothing else inside that rectangle.
- **3** inductor on the west flank, SW pad facing the pin; the SW pool covers
  the inductor pad, the SW pin and the bootstrap cap's SW pad, necked where it
  only serves a pin.
- **6** single-point analog ground: FB, RON and EN each return on their own via,
  so no switched current runs in them.
- **8** FB divider hard against the pin, VOUT sense reaching it the long way
  round - away from SW, the inductor and VIN.
- **9** RON as close to its pin as the column allows. It is ~2.0 mm of 0.20 mm
  trace, which adds order 0.05 pF against the part's 20 pF budget to ground.
- **10** an ARRAY of thermal vias in the exposed pad: the part dissipates about
  a watt on the 24 V rail and the ground plane it reaches is the heat path.

**Accepted, and quantified so it is not re-litigated:** RA taps the switch node
along a ~5 mm 0.20 mm trace east to the column. It carries microamps (240 kohm),
it runs 0.5 mm above the exposed pad - which references it for most of its
length - and it passes ~0.9 mm from the FB pool for ~1.3 mm. CB injects SW's own
ramp into FB by design, so that coupling runs with the design rather than
against it.

## Copper contract

Structural, stamped as drawn: the six pools, the exposed pad's via array, and
the four runs. **Every net the cell owns is closed inside the cell** - a rail
cell that hands its own feedback divider to the consumer ships a converter whose
sense node depends on someone else's routing round.

The cell **pours no ground**. The datasheet's "localized top-side planes that
connect to the GND pin and GND PAD" (rule 1b) is the consuming board's fill on
this face: it reaches every ground via here and bridges the GND pin to the
exposed pad across its own gap. A pour in the fragment would only block that
fill.

Handoff: `vin` and `vout` land via-in-pad on every one of their pads for the
board's own distribution; `gnd` is the board's plane. In the fragment's own DRC
the ground pads and the GND pin read as unconnected, which is the accepted
bucket for a plane net.

**The cell reserves no perimeter.** Its only far-layer presence is via lands, so
a consuming board may place against all four edges.

Floor 0.20 mm, the stdlib default. Every pour neck clears its class width
(`tools/poly_audit.py` is the gate): vout 3.14, SW 0.90, vin 0.80, FB 0.75,
EN 0.75, BST 0.61.
