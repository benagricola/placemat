# UsbC layout intent

USB-C device port (connector + protection), root `modules/UsbC/`

The spec `UsbC_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: hardware design guide Ch 5.1 chip/connector split.

Split out of the MCU cell because a port is a board concern that may sit far from
the MCU. The chip-side/connector-side boundary comes from the hardware
design guide (RP-008280 Ch 5.1): the 27R series terminators stay in the MCU cell;
everything that serves the CONNECTOR (receptacle, USBLC6-2SC6 ESD array, CC
5.1k pull-downs, VBUS bypass) is this cell. The board routes USB_P/USB_N
between the two cells as a differential pair (about 90R, solid ground
underneath, no plane splits; width/gap is a board NetClass number).

**Entry face (tactic 7, binding on boards):** the receptacle's mating face
points NORTH in the fragment and defines the module's own north edge. A board
lands this face on a real board edge (cable entry + overmold live off-board)
with the outline 0.5 mm PROUD of it (copper at the outline is
DRC-infeasible: `copper_edge_clearance`), and everything else packs south
of it. The connector is the only edge-hard part in the cell.

**Zero overhang:** the cell's outer boundary IS the receptacle's own
northmost copper (its pad row, the 0.27 mm of pad proud of the shell lip).
Nothing else in the cell sits north of it. A connector cell's envelope is
measured from the MATING INTERFACE, not from the footprint's convenient
routing space.

**Connector idioms (all ties inboard):** this TYPE-C-31-M-12's A/B pin order
interleaves DN/DP (B7 < A6 < A7 < B6 by x), so the pair's two flip-ties must
cross each other; with the front of the mouth off-limits the crossing is
forced south of the pad row: exactly one crossing, taken as a B.Cu hop on
USB_N's flip stub (2 vias, about 1.7 mm), with USB_P's stub jogging 0.2 mm
west to open the 0.625 mm a 0.6 mm via needs beside a 0.25 mm pair track.
Acceptable because each pair member's "main" and "stub" are alternative
paths for the two cable orientations (one live at a time) on a USB-FS port.
The pair MAINS stay F.Cu end to end, mirror-symmetric, landing straight on
their ESD pin axes. The two VBUS pads sit outboard of the four signal columns,
so after the fan-out no F.Cu west-east path survives: the west VBUS pad drops
to B.Cu and ties to the east side THROUGH the ESD's pin-5 via-in-pad. VBUS is
the only net allowed off F.Cu in this cell (DC, sense-only). Both VBUS
descents jog around the connector's NPTH alignment posts (hole clearance
0.25 mm). The two SMD shield fingers tie south-outward into the adjacent PTH
shell pads, which ARE the ground plane landing.

**ESD (flow-through):** SOT-23-6 at rot 0 directly south of the connector,
centred on the pair; its north row (IO1b/VBUS/IO2b) faces the connector with
USB_N west / USB_P east, matching the connector's own exit order, so the pair
passes straight through with one 0.2 mm 45 jog per side. The centre VBUS pin
sits between the pair pins, so VBUS reaches it by a short B.Cu hop ending in
a via-in-pad (0.53 mm pad, above the fab's 0.45 floor). CC pull-downs flank
on their own pin columns; each CC gets its OWN 5.1k Rd.

**Module boundary:** USB_P/USB_N end at the ESD's south pins and VBUS at the
bypass cap (no stubs; the io is optional, clamp + bypass live here
regardless). gnd is plane hand-off only: via-in-pad on every 0402-class gnd
pad + the ESD's centre-south pin, stub-away vias on the connector's two SMD
shield fingers, nothing on the four PTH shell pads.

**Placement lesson:** this connector's footprint draws a full-width silk
outline 1.7 mm south of its courtyard; pads that cross it fire
`silk_over_copper` even though courtyard DRC passes. Components south of a
big connector place off the SILK extent when the footprint draws beyond its
courtyard.

**Envelope:** footprint union 10.1 x 13.1 mm (about 85% fill); max extent
beyond the mating face 0.000 mm. **Clearance floor 0.20 mm, part-forced:**
0.5 mm pitch with 0.3 x 1.3 mm pads = 0.200 pad-to-pad, and the A5-A8 / B5-B8
fan-out lanes inherit it (15 pairs at 0.218-0.248; the minimum is VBUS's
descent beside the CC2 column); 0.25 would need 0.15 mm traces on the pair,
below the class floor and off the pair's impedance. Declared in
the floor derived from the consuming boards (`modules/clearance_floors.py`).

**DRC allowances:** `via_dangling` on gnd; `hole_clearance` 2 (USBC1's own
footprint-internal NPTH-vs-shield-finger padstack, a library condition); the
pair's main/stub islands bridge THROUGH the ESD (pins 1/6 and 3/4 are one
node inside the device).

**3D model registration:** the committed `(rotate 0)` transform is correct.
The 12 SMD signal pads sit in one row at footprint y = -2.47 (the -1.71 /
+2.47 entries are the shell's through-hole posts); the model's solder plane
lands 0.38 mm south of that row and the body overhangs the board edge, mouth
outward. Compare model extents to pad rows numerically; renders cannot
settle it.

---
