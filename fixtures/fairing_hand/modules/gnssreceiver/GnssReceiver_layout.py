"""GnssReceiver: the MAX-M10S (LCC-18), its supply bead and the parts at its
supply pins.

A fragment, stamped onto the core's back face as the cell `gnss.receiver`.
On the core the receiver fills the 11.0 mm between the north arm's seal
bands, its east pad column (RF_IN, VCC_RF: pins 10-18) against the seal
crossing toward the antenna, so everything else stands off its west column
(pins 1-9), which faces the disc:

- The receiver stands at the frame's origin, unturned: pins 1-9 run down the
  west column, pins 10-18 up the east column.
- VCC (pin 8), V_IO (pin 7) and V_BCKP (pin 6) sit together low on the west
  column, V_BCKP and VCC on GNSS_VCC. VCC's 100 nF stands upright a
  clearance off pin 8's tip, GNSS_VCC on the pin's axis and ground south.
  V_IO's 0 ohm link stands across the tips of pins 7 and 6, GNSS_VIO on
  pin 7's axis and GNSS_VCC toward pin 6. The bead stands upright on pin
  8's axis, GNSS_VCC north; the 10 uF stands upright over it in the same
  column, a silk gap west of the link, its GNSS_VCC pad south on pin 6's
  axis, so the two GNSS_VCC pads face each other (Ben's hand layout,
  2026-09-30).
- GNSS_VCC is one pour: over the 10 uF's and the bead's facing GNSS_VCC
  pads, a row from the 10 uF's east along pin 6's axis over the link's
  GNSS_VCC pad, and a row from the bead's to the 100 nF's and pin 8. A
  GNSS_VIO pour joins the link to pin 7 between the rows.
- TXD, RXD and TIMEPULSE (pins 2-4) are handoffs the core routes west from
  their pads; that stretch of the west column is left open for them.
  RF_IN (pin 11) is the core's feed, dropped through a via in the pad from
  the core's front, where the diagnostic u.FL stands; VCC_RF (pin 14) is
  the core's too, to its capacitor on the front (Gnss.zen).

u-blox MAX-M10S Integration Manual UBX-20053088-R05 4.4 (p80-81): ground
under the module on the top and second layers, no signal lines crossing
below it on those layers, ground vias round the RF pins. The component-face
ground fills under the module, a keepout holds tracks off it there, and a
column of ground vias down its middle and vias in the ground pins (1, 10,
12) join the fill to the planes.

Plane drops go in the pads (filled and capped). Copper stays on the
component face and the inner layers. The frame is the content and the
keep-in.
Evidence: ../../../../docs/decisions/layout/gnss-receiver-module-layout-2026-09-29.md.
"""
from placemat import board, Along, Beside, CopperLayer, Edge, Facing, Inside, LinkWeight, Location, Net, PadRef, Part

from fragment_frame import frame_planes

VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
MODULE_PAD_PITCH = 1.10       # the module's pad pitch (SMD-18 P1.10)
STITCH_PITCH = 3 * MODULE_PAD_PITCH   # ground vias under the module every third pad row: UBX-20053088 R05 p80 asks for more GND vias, and each is a hole the core's other face must keep clear of (Ben, 2026-10-01)
FILLET = 0.15                 # the pours' corner radius
BYPASS_LIMIT = 2.0            # the core's decoupling limit: beyond it a bypass is a bulk capacitor

board.faces(outward=Edge.EAST, quiet=Edge.EAST, handoff=Edge.WEST,
            why="the RF column (RF_IN, VCC_RF) faces the antenna across the seal crossing; the UART leaves west")

# MAX-M10S pins (UBX-20035208 table 1; the shared LCC-18 land).
GND_NW, TXD, RXD, PPS, BCKP, VIO, VCC = 1, 2, 3, 4, 6, 7, 8
EXTINT = 5
LNA_EN = 13
GND_S, GND_N = 10, 12


def pad(part, key):
    return PadRef(Part(part), key)


HF_ROT = Facing(pad("c_gnss_hf", "GNSS_VCC"), Edge.NORTH)          # GNSS_VCC on pin 8's axis, ground south
LINK_ROT = Facing(pad("r_gnss_vio", "GNSS_VCC"), Edge.NORTH)  # GNSS_VIO on pin 7's axis, GNSS_VCC toward pin 6
BEAD_ROT = Facing(pad("fb_gnss", "GNSS_VCC"), Edge.NORTH)          # GNSS_VCC north, toward the 10 uF
BULK_ROT = Facing(pad("c_gnss_bulk", "GND"), Edge.NORTH)       # GNSS_VCC south, facing the bead's

board.rect(fit=True)   # the frame is the content plus the keep-in
board.place(Part("gnss"), at=Location(0, 0), rotation=0, why="the receiver at the frame's origin; the core fixes it on the north arm")

# The upright pair beside the receiver's west side (the pins' mask openings).
board.place(Part("c_gnss_hf"), at=Beside(Part("gnss"), Edge.WEST, align=pad("gnss", VCC)), rotation=HF_ROT,
            why="VCC's bypass upright off pin 8's tip, GNSS_VCC on the pin's axis, ground south")
board.place(Part("r_gnss_vio"), at=Beside(Part("gnss"), Edge.WEST, align=pad("gnss", VIO)), rotation=LINK_ROT,
            why="V_IO's link upright off pin 7's tip, GNSS_VCC toward pin 6")
# The 10 uF upright west of the link, its GNSS_VCC pad on pin 6's axis; the
# bead upright under it in the same column: the GNSS_VCC pads face each
# other.
board.place(Part("c_gnss_bulk"), at=Beside(Part("r_gnss_vio"), Edge.WEST, align=pad("gnss", BCKP)), rotation=BULK_ROT,
            why="the 10 uF upright west of the link, GNSS_VCC on pin 6's axis")
board.place(Part("fb_gnss"), at=Beside(Part("c_gnss_bulk"), Edge.SOUTH, align=Along.MID), rotation=BEAD_ROT,
            why="the bead upright under the 10 uF in its column, GNSS_VCC north")

board.link(pad("c_gnss_hf", "GNSS_VCC"), pad("gnss", VCC), weight=LinkWeight.SHORT, limit_mm=BYPASS_LIMIT,
           why="the receiver's VCC bypass")
board.link(pad("r_gnss_vio", "GNSS_VIO"), pad("gnss", VIO), weight=LinkWeight.SHORT, limit_mm=BYPASS_LIMIT,
           why="V_IO's link to VCC at the pin")

# --- supply copper -----------------------------------------------------------
# GNSS_VCC: a strip over the 10 uF's and the bead's GNSS_VCC pads, and a row
# from each east along its pin's axis to V_BCKP (pin 6) and VCC (pin 8),
# through the link's and the 100 nF's GNSS_VCC pads; GNSS_VIO from the
# link to V_IO (pin 7).
F = CopperLayer.F
board.pour(Net("GNSS_VCC"), [pad("c_gnss_bulk", "GNSS_VCC"), pad("fb_gnss", "GNSS_VCC")], layer=F, swallow_pads=True)
board.pour(Net("GNSS_VCC"), [pad("c_gnss_bulk", "GNSS_VCC"), pad("gnss", BCKP)], layer=F, swallow_pads=True)
board.pour(Net("GNSS_VCC"), [pad("fb_gnss", "GNSS_VCC"), pad("c_gnss_hf", "GNSS_VCC")], layer=F, swallow_pads=True)
board.pour(Net("GNSS_VCC"), [pad("c_gnss_hf", "GNSS_VCC"), pad("gnss", VCC)], layer=F, swallow_pads=True)
board.pour(Net("GNSS_VIO"), [pad("r_gnss_vio", "GNSS_VIO"), pad("gnss", VIO)], layer=F, swallow_pads=True)

# --- drops, in the pads ------------------------------------------------------
board.via(Net("GND"), pad("c_gnss_hf", "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), pad("c_gnss_bulk", "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("V3V3"), pad("fb_gnss", "V3V3"), size=VIA, drill=VIA_DRILL)
for pin in (GND_NW, GND_S, GND_N):
    board.vias(Net("GND"), pad("gnss", pin), size=VIA, drill=VIA_DRILL)

# No track crosses under the module on the component face: the box inside
# the west and east pad columns' inner edges, moving and turning with the
# part (api.md, "A region inside a part's pads").
board.keepout(Inside(Part("gnss"), margin=0.0), "gnss_under", layers=(CopperLayer.F,),
              excludes=("tracks",), why="UBX-20053088 4.4: no signal lines crossing below the module")
# Ground vias stitched over the region under the module: the fill there to
# the planes (UBX-20053088 R05 p80: ground the area below the module on
# the top and second layers; more GND vias help).
board.stitch(Net("GND"), "gnss_under", pitch=STITCH_PITCH, size=VIA, drill=VIA_DRILL)

frame_planes(FILLET)   # the component-face ground fills under the module
