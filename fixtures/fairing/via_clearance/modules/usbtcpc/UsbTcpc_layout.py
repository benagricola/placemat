"""UsbTcpc: the RT1715 port controller and its CC, VBUS and supply parts.

A fragment, stamped onto the core as the cell `usbpd.tcpc`. Richtek RT1715
DS1715-04 p3-p4 (Typical Application Circuit, Tables 1-2).

- The RT1715 (WL-CSP-9, 0.4 mm pitch) stands at the frame's origin, its A
  row (CC2, VBUS, VDD) north and its C row (CC1, GND, SDA) south.
- VDD's 100 nF lies east, flush with the part's north edge, V3V3 toward
  VDD (A3); INT_N's pull-up north of it; VBUS's 4.7k north over VBUS (A2);
  VCONN's 1k west of VCONN (B1). The CC capacitors stand where their links
  pull them along their lines. Each outer ball leaves outward on the component face:
  CC2 north, VBUS north, VDD east, VCONN west, CC1 and GND south, SCL
  east under VDD's bypass (Ben, 2026-10-02), SDA south-east.
- INT_N is the centre ball: it reaches In2 through a 0.25/0.15 mm via in
  its pad (Ben, 2026-10-02: the smaller via's JLC charge accepted), since
  no track fits between the balls at the board's rules.

Handoffs the core routes: CC1, CC2 (to the receptacle), VBUS, SCL_PWR,
SDA_PWR and PD_IRQ. Plane drops go in the pads (filled and capped). The
frame is the content and the keep-in.
"""
from placemat import board, Along, Beside, CopperLayer, Edge, Facing, FreeSpot, LinkWeight, Location, Net, PadRef, Part

from fragment_frame import frame_planes, inner_layers

VIA, VIA_DRILL = 0.45, 0.20       # the core's via
INT_VIA, INT_VIA_DRILL = 0.25, 0.15   # JLC's smallest through via, in the centre ball (Ben, 2026-10-02)
SIGNAL_INNER, _ = inner_layers()   # the core's signal layer, In2
FILLET = 0.15                     # the pours' corner radius
BYPASS_LIMIT = 2.0                # the core's local-decoupling target
CC_CAP_LIMIT = 3.0                # each CC capacitor on its line near the part (DS1715-04 p3 draws C1/C2 on the connector side of CC)
CC2, VBUS, VDD, VCONN, INT_N, SCL, CC1, GND, SDA = "A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"


def pad(part, key):
    return PadRef(Part(part), key)


FINE_CLEAR = 0.10                 # at the 0.4 mm-pitch balls: JLC's 0.09 mm six-layer minimum, rounded up

board.size(fit=True)   # the frame is the content plus the keep-in
for _a, _b in (("USB_CC1", "GND"), ("USB_CC2", "TCPC_VBUS"), ("TCPC_VCONN", "USB_CC1"), ("TCPC_VCONN", "USB_CC2"),
               ("PD_IRQ", "GND"), ("SDA_PWR", "GND"), ("SCL_PWR", "V3V3"), ("SCL_PWR", "PD_IRQ"),
               ("SCL_PWR", "SDA_PWR")):
    board.rule(clearance=FINE_CLEAR, between=(_a, _b), why="the RT1715's 0.4 mm-pitch balls (WL-CSP-9)")
board.place(Part("tcpc"), at=Location(0, 0), rotation=0, why="the port controller at the frame's origin, its A row north")
board.place(Part("c_vdd"), at=Beside(Part("tcpc"), Edge.EAST, align=Along.START),
            rotation=Facing(pad("c_vdd", "V3V3"), Edge.WEST),
            why="VDD's 100 nF east of the part, flush with its north edge, so SCL (B3) leaves east under it")
board.place(Part("r_vbus"), at=Beside(Part("tcpc"), Edge.NORTH, align=("TCPC_VBUS", pad("tcpc", VBUS))),
            rotation=Facing(pad("r_vbus", "TCPC_VBUS"), Edge.SOUTH), why="VBUS's 4.7k over VBUS (A2)")
board.place(Part("c_cc2"))
board.place(Part("c_cc1"))
board.place(Part("r_vconn"), at=Beside(Part("tcpc"), Edge.WEST, align=("TCPC_VCONN", pad("tcpc", VCONN))),
            rotation=Facing(pad("r_vconn", "TCPC_VCONN"), Edge.EAST), why="VCONN's 1k west of its ball, straight out")
board.place(Part("r_irq"), at=Beside(Part("c_vdd"), Edge.NORTH, align=Along.END),
            rotation=Facing(pad("r_irq", "PD_IRQ"), Edge.WEST), why="INT_N's pull-up north of VDD's bypass, clear of SCL's and SDA's exits; INT_N reaches it on In2")

board.link(pad("c_vdd", "V3V3"), pad("tcpc", VDD), weight=LinkWeight.SHORT, limit_mm=BYPASS_LIMIT, why="VDD's bypass")
board.link(pad("c_cc1", "USB_CC1"), pad("tcpc", CC1), weight=LinkWeight.SHORT, limit_mm=CC_CAP_LIMIT, why="CC1's capacitor")
board.link(pad("c_cc2", "USB_CC2"), pad("tcpc", CC2), weight=LinkWeight.SHORT, limit_mm=CC_CAP_LIMIT, why="CC2's capacitor")
board.link(pad("r_vconn", "TCPC_VCONN"), pad("tcpc", VCONN), weight=LinkWeight.SHORT, why="VCONN's 1k to ground")

frame_planes(FILLET)

F = CopperLayer.F
board.track(Net("V3V3"), [pad("tcpc", VDD), pad("c_vdd", "V3V3")], layer=F)
board.track(Net("TCPC_VBUS"), [pad("tcpc", VBUS), pad("r_vbus", "TCPC_VBUS")], layer=F)
board.track(Net("USB_CC2"), [pad("tcpc", CC2), pad("c_cc2", "USB_CC2")], layer=F)
board.track(Net("USB_CC1"), [pad("tcpc", CC1), pad("c_cc1", "USB_CC1")], layer=F)
board.track(Net("TCPC_VCONN"), [pad("tcpc", VCONN), pad("r_vconn", "TCPC_VCONN")], layer=F)
board.via(Net("PD_IRQ"), pad("tcpc", INT_N), size=INT_VIA, drill=INT_VIA_DRILL,
          why="the centre ball's only way out (Ben, 2026-10-02)")
board.via(Net("V3V3"), pad("c_vdd", "V3V3"), size=VIA, drill=VIA_DRILL)
for part in ("c_vdd", "c_cc1", "c_cc2", "r_vconn"):
    board.via(Net("GND"), pad(part, "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), FreeSpot(near=pad("tcpc", GND), radius=1.5), size=VIA, drill=VIA_DRILL)
