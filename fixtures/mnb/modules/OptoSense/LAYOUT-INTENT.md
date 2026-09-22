# OptoSense layout intent

24 V opto input, LTV-357T-C + per-input NPN/PNP select

The spec `OptoSense_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: overview field-input NPN/PNP spec.

Not a datasheet-layout module: the spec source is the locked electrical
standard ("IO: fixed 24 V, NPN/PNP selectable per field input; switches are
dry contacts") and the overview's field-input paragraph ("the shared opto
cell swaps its bias: pull-up-to-24 V for NPN/sinking sensors,
pull-down-to-GND for PNP/sourcing"). The pin-level circuit is derived from
standard industrial 24 V digital-input practice and recorded in the module's
`.zen` header.

**Electrical topology (why two selects, not one):** a 3-wire NPN/PNP sensor
presents exactly ONE field wire to the opto loop; the loop's other terminal
must be a local fixed rail (+24 V for NPN, GND for PNP) AND the fixed rail
must sit on the LED's anode side for NPN but the cathode side for PNP. Two
independent 3-throw selects (H1 on the R-chain input, H2 on the CAT pin; XFCN
PZ200V-11-03P 1x3 2.00 mm THT + shunt) swap which side is fixed and which is
field, with ONE reverse-protection diode (D1) spanning the whole
an_src-to-cat string so the series indicator LED is inside its clamp. Pad "1"
of both headers is the NPN throw, pad "3" the PNP throw; the crossed
combination (H1 to 3, H2 to 1) is the floating 2-wire loop for every
dry-contact instance. The full NPN/PNP current-path proof is in
`OptoSense.zen`'s header.

**Activity LED:** KT-0603Y yellow (the ecosystem's IO-activity colour) in
series with the opto LED string, sharing its about 4.6 mA (about 28 mcd);
series R 2 x 2.2k 0603. It is electrically field-side (upstream of the
barrier), so it sits field-side in the layout; the barrier is a hard
constraint.

**Structure:** one band 4.45 mm tall. West to east: the stacked header block,
D1, R2, R3, D2, U1, R1. The series chain STANDS UP across the band (each 0603
spans the two rows, so a chain element costs 1.65-1.70 mm of x instead of
3.30) and alternates rows (an_src north, R2, RMID south, R3, LEDA north, D2,
AN into U1). The bleed R1 also stands up, on the COL/out row east of U1 (out
pad north on the row, v3v3 pad south), so the cell ends one 0402 width past
the opto's pads. The cell is entirely on F.Cu (tactic 14); the only vias are
plane landings and the `out` escape via on R1's out pad.

**The two headers are a STACKED BLOCK, not two parts in the row:** both rot 0
(keyed pad = NPN throw, west on both), same x centre, 2.60 mm apart in y,
centred on U1's band midline, so the NPN column and the PNP column line up
across both headers and "both shunts left = NPN, both right = PNP" is one
visual. The 2.60 pitch is set by SILK, not copper: two body outlines at
+/-1.155 (with stroke) plus the 0.20 silk rule need 2.51; courtyards need
2.25; one corridor lane for the an_src common needs 2.20; 0.60 mm of board
shows between two fitted shunts. Only `an_src` takes the inter-header
corridor (dead centre); `cat` leaves its common southward into the south
corridor, which already carries cat under the chain to D1.A and U1.CAT. A
3-pad jumper's common is approached PERPENDICULAR to its own throw axis;
both commons leave their header vertically.

**Plane landings are free on a THT part:** the v24 and gnd THROW pads are
plated barrels through every layer, so the board's plane lands on the pad
itself and no drop via is drawn. Both are throw pads (dead copper until a
shunt bridges them), so the crossed dry-contact mode still leaves the field
loop floating; the plane goes live only in the NPN/PNP modes.

**Routing, all F.Cu:** `an_src` south into the corridor, east, then one 45
onto D1's row 0.50 mm east of the throw-pad column, and one straight run
through D1.K into R2; `cat` leaves its common on ONE 45 straight into the
south corridor (0.35 off the header pads), runs east under the block as one
segment, and turns up onto U1.CAT's axis; D1.A drops onto it with a spur.
The field nets `in_p`/`in_n` carry NO copper: each ends at its throw pad
(H1's pin 3, H2's pin 1), which is the board's pickup. `out` runs COL to
R1's north pad and ends there with an escape via.

**Silk:** knockout "NPN" / "PNP", 0.80 mm (KiCad's `text_height` floor), one
band north of the stack 1.90 mm above the header centre (outline edge + 0.20
+ the 0.526 rect half-height of 0.80 mm text; measure the rect, the text bbox
lies). No separate pin-1 digit: the keyed pad marks it and "NPN" sits over
that column. The silk band is the cell's tallest extent, ink only.

**Envelope:** body about 21.4 x 4.45 mm (24.3 x 7.0 with the silk band). The block stands 5.7 mm proud with shunts fitted, and
its six 0.9 mm holes punch the far face: a consuming board keeps the shadow
under each block clear on the far side and the shunt volume above it
uncrowded. Consumers: Featherweight estop1/estop2/mirror, Middleweight
opto_in1/opto_in2, Flyweight endstop/probe/toolsetter/toolpresent,
CNC Expansion door_mon/probe/toolsetter.

**Instantiation:** every instance passes a `v24` net in addition to
`in_p`/`in_n`/`v3v3`/`gnd`/`out`. For dry-contact instances `v24` lands on
H1's unshunted NPN throw, inert unless a shunt moves, and is the v24 plane
landing.

**Clearance: as built 0.25 mm** (above the 0.20 class floor
holds with margin). The corridors under the headers sit 0.35 off the 1.4 mm
pads, which is what a 0.2 trace needs.

**Known cosmetic DRC item:** `silk_over_copper` on D2's own pin-1 marker vs
its pad (stock KT-0603 footprint self-clip).

**Part note:** `parts/XFCN_PZ200V_11_03P/HDR-TH_3P-P2.00-V-M.kicad_mod`
carries a body-only courtyard (+/-3.0 x +/-1.0) where the house rule wants
union(pads, body) + 0.10; the layout is dimensioned against the fixed
numbers, so `--fix` moves nothing here and grows the reported envelope by
0.10 per side.

---
