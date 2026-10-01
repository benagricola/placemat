"""LogicSupply: the TPS62933 3.3 V buck and its switching loop.

A fragment, stamped onto the core as the cell `logicsupply`. The layout
ports the TPS62933 datasheet's Figure 12-2 (SLUSEA4D section 12.2) and the
section 12.1 guidelines: the 100 nF input capacitor closest across VIN and
GND, the 10 uF beside it, the inductor on SW, the output capacitors at the
inductor's output end with their grounds returned to the input capacitors',
the boot capacitor at BST and SW, and the feedback divider and soft-start
capacitor close to FB and SS, away from SW.

Pins, from the datasheet's pin table and docs/decisions/schematics/core-netlist.xml: RT 1,
EN 2, VIN 3, GND 4, SW 5, BST 6, SS 7, FB 8. EN floats (it is rated 6 V and
floating enables the part), so it has no copper. RT goes to GND for 1.2 MHz.

Turned 180 degrees the part stands as Figure 12-2 draws it: RT, EN, VIN
and GND down the west column, FB, SS, BST and SW down the east.

- The 100 nF stands a silk gap west of VIN, VSHUNT level with it; the 10 uF
  stands a silk gap west of the 100 nF, VSHUNT level with it.
- The boot capacitor stands east of BST, BST level with it, far enough east
  that the SW pour keeps its width beyond it; its SW end is in that pour.
- The inductor stands south of the boot capacitor, which reaches further
  south than the chip's own edge, centred on it, SW end north.
- The two 22 uF output capacitors lie west of the inductor, output east
  toward its output end, the second stacked under the first.
- The feedback divider's bottom stands north of the part over FB, its top
  a silk gap west of it, FB ends level; the soft-start capacitor stands a
  silk gap east of the divider's bottom, SS end level with FB, so SS
  reaches its capacitor without crossing FB.
- The output capacitors' output pads and the inductor's output end drop to
  the 3V3 plane.
- The divider's top and bottom are sense nets (LogicSupply.zen): each
  leaves a net tie, at the first output capacitor's 3V3 pad and at the GND
  pin, drops to In2 and comes up in the divider's pad.

Evidence: docs/decisions/layout/logic-supply-routing-2026-09-26.md.
Circuit: docs/decisions/schematics/logic-buck-tps62933-2026-09-27.md.
"""
from placemat import board, Along, Bend, Beside, CopperLayer, Corner, Edge, Facing, FreeSpot, Location, LinkWeight, Net, PadRef, Part, Past, Pin

from fragment_frame import frame_planes, inner_layers

SIGNAL_INNER, _ = inner_layers()   # the core's signal layer, In2, under the ground plane

VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
CLEAR = board.netclass(Net("GND")).clearance
TRACK = board.netclass(Net("GND")).track_width
VIA_PITCH = VIA + CLEAR
FILLET = 0.15                 # pour corner radius
DECOUPLING_LIMIT = 2.0        # a bypass beyond this is a bulk capacitor, not a bypass
SIGNAL_TRACK = 0.254          # TI 12.1: BST, FB, SS and RT traces over 10 mil
SW_NECK = 1.13                # the SW pour past the boot capacitor: 2.6 A peak at 10 C rise on 1 oz (placemat current-path)
SS_CHAMFER = 0.1              # SS turns north just past the pin row's east end: the default cut passes FB's pour inside the clearance
BUCK_ROTATION = 180           # Figure 12-2's orientation
COIL_ROTATION = 270           # SW end north
RT_PIN, EN_PIN, VIN_PIN, GND_PIN, SW_PIN, BST_PIN, SS_PIN, FB_PIN = 1, 2, 3, 4, 5, 6, 7, 8
LYING, LYING_FLIPPED, UPRIGHT, UPRIGHT_FLIPPED = 0, 180, 90, 270   # two-pad parts: pad 1 west, east, south, north


def pad(part, key):
    return PadRef(Part(part), key)


def pin(n):
    return pad("buck3v3", n)


board.size(fit=True)   # the frame is the content plus the keep-in
board.place(Part("buck3v3"), at=Location(0, 0), rotation=BUCK_ROTATION,
            why="the regulator at the frame's origin; the rest from its pads")

# --- input: the 100 nF, then the 10 uF, west of VIN -------------------------------
board.place(Part("c_3v3_hf"), at=Beside(Part("buck3v3"), Edge.WEST, align=pin(VIN_PIN)), rotation=UPRIGHT_FLIPPED,
            why="the 100 nF a silk gap west of VIN, VSHUNT level with it")
board.place(Part("c_3v3_in"), at=Beside(Part("c_3v3_hf"), Edge.WEST, align=pad("c_3v3_hf", "VSHUNT")),
            rotation=UPRIGHT_FLIPPED, why="the 10 uF a silk gap west of the 100 nF, VSHUNT level with it")

# --- the boot capacitor, east of BST, far enough for the SW pour's neck -----------
board.place(Part("c_bst"), at=Beside(Part("buck3v3"), Edge.EAST, align=pin(BST_PIN), gap=SW_NECK),
            rotation=UPRIGHT_FLIPPED, why="the boot capacitor east of BST, level with it, the SW pour's width beyond")

# --- the inductor, south of the boot capacitor (it reaches further south than
# the chip's own edge), centred on it, SW end north --------------------------------
board.place(Part("l_3v3"), at=Beside(Part("c_bst"), Edge.SOUTH, align=Along.MID), rotation=COIL_ROTATION,
            why="the inductor south of the boot capacitor, centred on it, SW end north")

# --- the output capacitors, west of the inductor, stacked --------------------------
board.place(Part("c_3v3_out"), at=Beside(Part("l_3v3"), Edge.WEST, align=pad("l_3v3", "V3V3")), rotation=LYING_FLIPPED,
            why="the first 22 uF west of the inductor's output end, output east")
board.place(Part("c_3v3_out2"), at=Beside(Part("c_3v3_out"), Edge.SOUTH, align=pad("c_3v3_out", "V3V3")),
            rotation=LYING_FLIPPED, why="the second 22 uF stacked under the first")

# --- the feedback divider and soft-start capacitor, north of the part -------------
board.place(Part("r_fb_bottom"), at=Beside(Part("buck3v3"), Edge.NORTH, align=pin(FB_PIN)), rotation=UPRIGHT,
            why="the divider's bottom north of FB, FB end south")
board.place(Part("r_fb_top"), at=Beside(Part("r_fb_bottom"), Edge.WEST, align=pad("r_fb_bottom", "FB_3V3")),
            rotation=UPRIGHT_FLIPPED, why="the divider's top a silk gap west of its bottom, FB end level with it")
board.place(Part("c_ss"), at=Beside(Part("r_fb_bottom"), Edge.EAST, align=("SS_3V3", pad("r_fb_bottom", "FB_3V3"))),
            rotation=UPRIGHT, why="the soft-start capacitor a silk gap east of the divider, SS end level with FB, "
            "so SS reaches it clear of FB")

# The divider's sense ties (LogicSupply.zen): V3V3_SENSE's on the first
# output capacitor's 3V3 pad, its north edge, sense pad north; FB_3V3_GND's
# on the GND pin's south edge, sense pad south.
board.place(Part("nt_v3v3_sense"), at=Pin(1, PadRef(Part("c_3v3_out"), "V3V3", edge=Edge.NORTH, along=Along.MID)),
            rotation=Facing(PadRef(Part("nt_v3v3_sense"), 2), Edge.NORTH), why="V3V3_SENSE's tie on the output capacitor's 3V3 pad, sense pad north")
board.place(Part("nt_fb_gnd"), at=Pin(1, PadRef(Part("buck3v3"), GND_PIN, edge=Edge.SOUTH, along=Along.MID)),
            rotation=Facing(PadRef(Part("nt_fb_gnd"), 2), Edge.SOUTH), why="FB_3V3_GND's tie on the GND pin's south edge, sense pad south")

for part, net, host, hpin, limit in (("c_3v3_hf", "VSHUNT", "buck3v3", VIN_PIN, DECOUPLING_LIMIT),
                                     ("c_bst", "BST_3V3", "buck3v3", BST_PIN, DECOUPLING_LIMIT)):
    board.link(PadRef(Part(part), net), PadRef(Part(host), hpin), weight=LinkWeight.SHORT, limit_mm=limit,
               why="TI 12.1: at its pin")

frame_planes(FILLET)
board.free_net(Net("V3V3"))
board.free_net(Net("VSHUNT"))


# --- copper -------------------------------------------------------------------------
F = CopperLayer.F


def pour(net, pads, width=None):
    """One pour over these pads' copper, fitted round every other net's (a
    neck at `width` when given)."""
    board.pour(Net(net), pads, layer=F, swallow_pads=True, width=width)


def via_in(part, key, net):
    board.via(Net(net), pad(part, key), size=VIA, drill=VIA_DRILL)


board.track(Net("BST_3V3"), [pin(BST_PIN), pad("c_bst", "BST_3V3")], layer=F, width=SIGNAL_TRACK)
# SS: east off the pin, then a 45 into the capacitor, clear of FB's pin,
# which is not between them.
board.track(Net("SS_3V3"), [pin(SS_PIN), Past([pin(FB_PIN), pin(SS_PIN)], Edge.EAST, across=pin(SS_PIN)),
                            pad("c_ss", "SS_3V3")], layer=F, width=SIGNAL_TRACK, bend=Bend.END, chamfer=SS_CHAMFER)
for part in ("c_3v3_out", "c_3v3_out2"):
    board.vias(Net("V3V3"), pad(part, "V3V3"), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
# Ground drops: the capacitors' ground pads, the divider's and soft-start's
# ground ends, and RT beside its pin.
for part in ("c_3v3_in", "c_3v3_out", "c_3v3_out2"):
    board.vias(Net("GND"), pad(part, "GND"), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
_hf_gnd = board.via(Net("GND"), pad("c_3v3_hf", "GND"), size=VIA, drill=VIA_DRILL)
via_in("c_ss", "GND", "GND")
_rt_via = board.via(Net("GND"), FreeSpot(near=pin(RT_PIN)), size=VIA, drill=VIA_DRILL)
board.track(Net("GND"), [pin(RT_PIN), _rt_via], layer=F, width=SIGNAL_TRACK)

# The divider's sense lines: each leaves its tie's sense pad, drops to In2
# beside it, and comes up in the divider's pad: V3V3_SENSE passes west of
# the 100 nF's ground drop, well clear of FB_3V3_GND's via, so the two never
# cross (TI 12.1: a separate VOUT trace to
# the upper resistor, away from SW, under the ground plane).
_fg_down = board.via(Net("FB_3V3_GND"), FreeSpot(near=PadRef(Part("nt_fb_gnd"), 2)), size=VIA, drill=VIA_DRILL)
board.track(Net("FB_3V3_GND"), [PadRef(Part("nt_fb_gnd"), 2), _fg_down], layer=F)
_vs_down = board.via(Net("V3V3_SENSE"), FreeSpot(near=PadRef(Part("nt_v3v3_sense"), 2)), size=VIA, drill=VIA_DRILL)
board.track(Net("V3V3_SENSE"), [PadRef(Part("nt_v3v3_sense"), 2), _vs_down], layer=F)
_vs_up = board.via(Net("V3V3_SENSE"), pad("r_fb_top", "V3V3_SENSE"), size=VIA, drill=VIA_DRILL)
board.track(Net("V3V3_SENSE"), [_vs_down, Past([_hf_gnd], Corner.SW), Past([_hf_gnd], Edge.WEST, across=_hf_gnd), _vs_up],
            layer=SIGNAL_INNER)
_fg_up = board.via(Net("FB_3V3_GND"), pad("r_fb_bottom", "FB_3V3_GND"), size=VIA, drill=VIA_DRILL)
board.track(Net("FB_3V3_GND"), [_fg_down, _fg_up], layer=SIGNAL_INNER)

# --- pours, after the tracks and vias they fit round ---------------------------------
# VSHUNT: VIN to the 100 nF, then to the 10 uF, a pour over each pair.
pour("VSHUNT", [pin(VIN_PIN), pad("c_3v3_hf", "VSHUNT")])
pour("VSHUNT", [pad("c_3v3_hf", "VSHUNT"), pad("c_3v3_in", "VSHUNT")])
# SW: the pin, the boot capacitor's SW end and the inductor's SW end, one
# pour fitted round the boot capacitor's BST pad. (GND is the component
# face's ground zone.)
pour("SW_3V3", [pin(SW_PIN), pad("c_bst", "SW_3V3"), pad("l_3v3", "SW_3V3")])
# FB: the pin and the divider's two FB ends, one pour.
pour("FB_3V3", [pin(FB_PIN), pad("r_fb_bottom", "FB_3V3"), pad("r_fb_top", "FB_3V3")])
# V3V3: the inductor's output end and both output capacitors' output pads,
# which drop to the 3V3 plane.
pour("V3V3", [pad("l_3v3", "V3V3"), pad("c_3v3_out", "V3V3"), pad("c_3v3_out2", "V3V3")])
