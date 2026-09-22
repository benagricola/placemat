# BrakeChopper layout intent

The machine's one regen brake chopper: a comparator with hysteresis watching the
48 V trunk through a divider, driving a low-side FET that puts the external
22R/50W dump resistor across the bus. The resistor is a board-level terminal.

The spec `BrakeChopper_layout.py` implements and the fragment in `layout/` must
satisfy. Rules that apply to every module are in `modules/README.md`; how layout
is done is the `pcb-layout` skill. History lives in git.

## Structure

**Three bands, not one chain.** Laid end to end the parts are 37 mm wide, so a
single row can only ever be a strip with empty corners. Folded, the two tall
packages (comparator and FET) and the driver share the MIDDLE band, the front
end and the 48 V chain take the NORTH band, and the status tap, the diode-OR and
its pull-down take the SOUTH.

**The comparator's pin order is the floorplan.** On an LM393 in SOIC-8 the
output, the inverting input and the non-inverting input are three adjacent pins
on one row. At rot 180 that row faces north and reads west to east as gnd, IN+,
IN-, OUT, so the front end sits north of the package in exactly that order: the
bus divider west, the reference in the middle, the output east - and the drive
chain carries on east from there. The supply row faces south, where v5, the
status tap and the diode-OR's input live.

**The hysteresis resistor bridges OUT back to IN+, across IN-.** On this pin
order that link cannot cross the reference's own escape on one layer. So the
whole reference group sits WEST of the lane OV_OUT climbs: the output leaves
east of the package, goes up the gap between the shunt's courtyard and the
driver's HF cap, and turns west along the band's north edge into the hysteresis
resistor. OV_OUT is the open-drain output with a 1k pull-up - the lowest
impedance of the three - so it is the one that pays the distance, not the 100k
divider tap and not the reference.

**The dump path's two ends belong together.** The external resistor hangs
between v48 and chop_node, so both leave at the east: the FET is the east wall
with its drain row and exposed pad facing south, and v48 runs the north edge to
reach the divider's top resistor and the driver's zener dropper.

**The gate loop is the only fast thing here.** The FET turns its gate to face the
driver and sits 2.3 mm from it, so driver output, series resistor, gate pad and
the pull-down close in one rectangle in that gap. The gate run goes west of the
drain region and enters on the gate pad's own row - the drain pour reaches within
a millimetre of the diagonal. Everything else in the cell is DC or kilohertz.

Nets that need care rather than length:
- **OV_DIV** is the 100k/4.64k tap the trip point is set by - the highest
  impedance node in the block. Its three pads sit on one short rail at the pin
  with the filter cap on it, and nothing else runs through them.
- **OV_REF** is the TL431's own cathode, with its filter on the node between the
  shunt and the pin. The shunt's cathode and reference are separate pads on one
  net, so the cell links them and the bias resistor - west of the shunt, clear of
  the lane OV_OUT climbs - lands on the far one.
- The **48 V nets** are the only ones above logic level and they take the north
  edge, away from everything else.

Envelope 25.28 x 16.55 mm, courtyard union 211 mm2, fill 49%. What air is left
is under the FET and east of the zener; both are the shape of the big packages
rather than slack, and moving the zener out of the driver's own supply loop to
take the first would be the wrong trade.

## Copper contract

Structural, stamped as drawn: the chop_node region over the FET's drain row and
exposed pad, the gate loop, and the whole small-signal interconnect. Every net
that is not an io net is closed inside the cell.

The cell **pours no ground**: every ground pad is its own plane tap, including
the comparator's and the driver's ground PINS, because neither package has an
exposed pad to bridge to.

Handoff, all at pads: `v48` lands twice (the divider's top and the dropper) and
`v5` twice (the comparator's VCC and the reference's bias) - joining either pair
inside the cell would cross a rail that is already committed, and both are
board-distributed. `chop_node` is the drain region, `drive_in` a single pad on
the diode-OR, `status` the divider's midpoint, `gnd` the board's plane.

Floor 0.20 mm, the stdlib default. The chop_node region's narrowest section is
4.80 mm against a 0.80 class width.
