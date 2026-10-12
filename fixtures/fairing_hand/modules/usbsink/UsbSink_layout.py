"""UsbSink: the 5 V PC input, from the receptacle's VBUS to the protected rail.

A fragment, stamped onto the core as the cell `usbpd.sink`. The TPS259470
takes VBUS to VSHUNT with a 6 V OVLO and a 0.5 A limit, and starts itself:
a divider from VBUS lifts EN/UVLO past 1.20 V at 3.84 V, and a 5.1 V Zener
holds EN/UVLO under 5 V when the port sources up to 21 V. TPS25947 ZHCSL91B
section 11.1: local input and output bypasses and short setting nodes.

- The TPS259470 stands at the frame's origin, its IN and OUT lands running
  north-south down its middle.
- The output bypass lies north against EN's divider, OUT running straight
  north and turning 45 into its VSHUNT pad; the input
  bypass lies south, its VBUS pad on IN's axis and ground west. Each is
  joined to its land at the land's width.
- The ILM resistor stands upright east, SINK_LIMIT level with ILM (pin 9),
  its ground end joined to GND (pin 8); the dV/dt capacitor lies south of
  the switch beside the input bypass, SINK_SLEW under DVDT (pin 7).
- The OVLO divider stands west, its top's SINK_OVLO level with OVLO (pin 2)
  and VBUS north, the bottom west of it with SINK_OVLO in line. EN's
  divider stands over the OVLO divider's top, SINK_EN toward EN (pin 1):
  its bottom upright, its top west of it with SINK_EN in line, and the
  Zener west of the top, its cathode level with SINK_EN and its anode south.

Handoffs the core routes: VBUS (at the input bypass) and VSHUNT (at the
output bypass). Plane drops go in the pads (filled and capped). The frame
is the content and the keep-in.
"""
from placemat import (board, Along, Beside, Bend, Corner, CopperLayer, Edge, Facing, FreeSpot, Land, LinkWeight, Location, Net, PadRef,
                      Part, Past)

from fragment_frame import frame_planes, inner_layers, size

VIA, VIA_DRILL = 0.45, 0.20   # the core's via
SIGNAL_INNER, _ = inner_layers()   # the core's signal layer, In2
FILLET = 0.15                 # the pours' corner radius
BYPASS_LIMIT = 2.0            # local IN/OUT/GND loops, TPS25947 ZHCSL91B section 11.1
SETTING_LIMIT = 2.0           # keep ILM and slew nodes away from switching noise
EN_PIN, OVLO_PIN, IN_PIN, OUT_PIN, DVDT_PIN, GND_PIN, ILM_PIN = 1, 2, 5, 6, 7, 8, 9
LAND_W, LAND_H = size(board.pad(Part("sink_switch"), IN_PIN).box)   # the IN/OUT lands' width and length
LAND_LIMIT = BYPASS_LIMIT + LAND_H / 2.0   # a bypass at a land's end, measured from the land's centre


def lying(part, east, west):
    """The turn that lays a two-pad part with pad `east` east of pad `west`."""
    return Facing(PadRef(Part(part), east), Edge.EAST)


def upright(part, north, south):
    """The turn that stands a two-pad part with pad `north` north of pad `south`."""
    return Facing(PadRef(Part(part), north), Edge.NORTH)


SW = Part("sink_switch")

board.rect(fit=True)
board.place(SW, at=Location(0, 0), rotation=0, why="the switch at the frame's origin")
board.place(Part("c_sink_out"), at=Beside(Part("r_sink_en"), Edge.EAST, align=Along.MID),
            rotation=lying("c_sink_out", "GND", "VSHUNT"),
            why="the output bypass north, against EN's divider so its ground stays inside the ILM resistor (Ben, 2026-10-03)")
board.place(Part("c_sink_in"), at=Beside(SW, Edge.SOUTH, align=PadRef(SW, IN_PIN)),
            rotation=lying("c_sink_in", "VBUS", "GND"), why="the input bypass south, VBUS on IN's axis, ground west")
board.place(Part("r_sink_limit"), at=Beside(SW, Edge.EAST, align=PadRef(SW, ILM_PIN)),
            rotation=upright("r_sink_limit", "SINK_LIMIT", "GND"), why="the ILM resistor east, SINK_LIMIT level with ILM")
board.place(Part("c_sink_slew"), at=Beside(SW, Edge.SOUTH, align=PadRef(SW, DVDT_PIN, land=Land.LARGEST)),
            rotation=lying("c_sink_slew", "GND", "SINK_SLEW"), why="the dV/dt capacitor south of DVDT, SINK_SLEW under it")
board.place(Part("r_sink_ov_top"), at=Beside(SW, Edge.WEST, align=PadRef(SW, OVLO_PIN)),
            rotation=upright("r_sink_ov_top", "VBUS", "SINK_OVLO"), why="the OVLO divider's top west, SINK_OVLO level with OVLO")
board.place(Part("r_sink_ov_bottom"), at=Beside(Part("r_sink_ov_top"), Edge.WEST, align=PadRef(Part("r_sink_ov_top"), "SINK_OVLO")),
            rotation=upright("r_sink_ov_bottom", "SINK_OVLO", "GND"), why="the divider's bottom west of its top, SINK_OVLO in line")
board.place(Part("r_sink_en"), at=Beside(Part("r_sink_ov_top"), Edge.NORTH, align=Along.MID),
            rotation=upright("r_sink_en", "GND", "SINK_EN"), why="EN's divider bottom over the OVLO divider, SINK_EN toward EN")
board.place(Part("r_sink_en_top"), at=Beside(Part("r_sink_en"), Edge.WEST, align=("SINK_EN", PadRef(Part("r_sink_en"), "SINK_EN"))),
            rotation=upright("r_sink_en_top", "VBUS", "SINK_EN"), why="EN's divider top west of its bottom, SINK_EN in line")
board.place(Part("d_sink_en"), at=Beside(Part("r_sink_en_top"), Edge.WEST, align=("SINK_EN", PadRef(Part("r_sink_en_top"), "SINK_EN"))),
            rotation=Facing(PadRef(Part("d_sink_en"), "SINK_EN"), Edge.NORTH),
            why="the EN clamp west of the divider's top, its cathode on SINK_EN and its anode south beside the OVLO divider (Ben, 2026-10-03)")

for part, net, limit in (("c_sink_out", "VSHUNT", LAND_LIMIT), ("c_sink_in", "VBUS", LAND_LIMIT),
                         ("r_sink_limit", "SINK_LIMIT", SETTING_LIMIT), ("c_sink_slew", "SINK_SLEW", SETTING_LIMIT)):
    board.link(PadRef(Part(part), net), PadRef(SW, net), weight=LinkWeight.SHORT, limit_mm=limit, why="local to its pin")

frame_planes(FILLET, supply=None)   # no 3V3 in this cell

F = CopperLayer.F


def pad(part, key, land=None):
    return PadRef(Part(part), key) if land is None else PadRef(Part(part), key, land=land)


board.track(Net("VSHUNT"), [pad("sink_switch", OUT_PIN), pad("c_sink_out", "VSHUNT")], layer=F, width=LAND_W, bend=Bend.END)
board.track(Net("VBUS"), [pad("sink_switch", IN_PIN), pad("c_sink_in", "VBUS")], layer=F, width=LAND_W)
# The divider's top takes VBUS from the input bypass on In2: on the
# component face EN's corner land and the output bypass close IN's north end.
board.via(Net("VBUS"), pad("r_sink_ov_top", "VBUS"), size=VIA, drill=VIA_DRILL)
board.via(Net("VBUS"), pad("c_sink_in", "VBUS"), size=VIA, drill=VIA_DRILL)
board.track(Net("VBUS"), [pad("r_sink_ov_top", "VBUS"), pad("c_sink_in", "VBUS")], layer=SIGNAL_INNER)
board.track(Net("SINK_LIMIT"), [pad("sink_switch", ILM_PIN), pad("r_sink_limit", "SINK_LIMIT")], layer=F)
board.track(Net("GND"), [pad("sink_switch", GND_PIN), pad("r_sink_limit", "GND")], layer=F)
board.track(Net("SINK_SLEW"), [pad("sink_switch", DVDT_PIN, Land.LARGEST), pad("c_sink_slew", "SINK_SLEW")], layer=F)
board.track(Net("SINK_OVLO"), [pad("sink_switch", OVLO_PIN), pad("r_sink_ov_top", "SINK_OVLO"),
                               pad("r_sink_ov_bottom", "SINK_OVLO")], layer=F)
# SINK_EN leaves EN north and turns 45 round the OVLO divider top's VBUS pad
# onto the divider's row (Ben, 2026-10-03).
board.track(Net("SINK_EN"), [pad("sink_switch", EN_PIN, Land.LARGEST),
                             Past([pad("r_sink_ov_top", "VBUS")], Corner.NE),
                             pad("r_sink_en", "SINK_EN"),
                             pad("r_sink_en_top", "SINK_EN"), pad("d_sink_en", "SINK_EN")], layer=F)
board.via(Net("VBUS"), pad("r_sink_en_top", "VBUS"), size=VIA, drill=VIA_DRILL)
board.track(Net("VBUS"), [pad("r_sink_en_top", "VBUS"), pad("r_sink_ov_top", "VBUS")], layer=SIGNAL_INNER)
for part in ("c_sink_out", "c_sink_in", "r_sink_limit", "c_sink_slew", "r_sink_ov_bottom", "r_sink_en", "d_sink_en"):
    board.via(Net("GND"), pad(part, "GND"), size=VIA, drill=VIA_DRILL)
