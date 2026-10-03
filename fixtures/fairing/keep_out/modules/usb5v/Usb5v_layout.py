"""Internal PP5V buck cell: the LM61440-Q1 at 2.2 MHz, ported from TI's
layout example (SNVSBE4C section 12.2, Figure 12-2).

The regulator stands as its footprint is drawn: BIAS, VCC, AGND, FB and
PGOOD down the west column, CBOOT, RBOOT, a VIN pad and PGND2 along the
north row, RT, EN, a VIN pad and PGND1 along the south row, SW east.

- Each VIN/PGND corner takes its own input pair, as the datasheet asks
  (bypass each VIN to its PGND, symmetric for EMI): the 100 nF across the
  pins, the 4.7 uF outside it.
- The coil lies east, its SW end a clearance from the PGND pads and joined
  to the SW pin by a short pour; the two 22 uF lie north and south of it,
  output ends over its output end, and PP5V's two polymer reservoirs stand
  east of it, centred on its output pad.
- SW reaches the boot capacitor under the regulator, through the gap
  between the north VIN pad and RBOOT (TI's routing); RBOOT and CBOOT are
  joined at the pins and the boot capacitor stands north of them.
- The quiet side is west and south: VCC's capacitor and the feedback
  divider in a column west of their pins, the feed-forward capacitor
  beside it; south of the pins, the enable divider west of the south input
  pair, RT's resistor south of the regulator, level with its pin.
- Same-net pads that stand together share one pour, drawn over their
  copper; tracks join pads that stand apart.
- The SW neck between the PGND lands is 1.47 mm, which the package sets,
  and FB's pin stands 1.3 mm from the SW land in the package.
- Two inner layers, as Figure 12-2 uses: the VIN strap on In2 joins the
  two input pairs' VSHUNT vias under the regulator, and the core's VSHUNT
  pour reaches it there; the output sense runs on In3 from an output
  capacitor to BIAS and the divider, and the core's 3V3 plane clears round
  it.
- The divider's top (with BIAS and CFF) and its bottom are sense nets
  (Usb5v.zen): PP5V_SENSE leaves a net tie on the first 22 uF's output pad,
  FB_5V_GND one on the AGND pin. PP5V_SENSE drops to In3 beside its tie;
  FB_5V_GND runs on the component face, through a lane between VCC's
  capacitor and the divider's lower resistor, into that resistor's pad.

Ground drops are vias in the pads; In1 and In4 are ground.
Selection: ../../../../docs/decisions/schematics/pp5v-buck-frequency-screen-2026-09-28.md.
"""
from placemat import board, Along, Bend, Beside, Between, CopperLayer, Edge, Facing, FreeSpot, Net, PadRef, Part, Past, Pin

from fragment_frame import frame_planes, inner_layers

VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
CLEAR = board.netclass(Net("GND")).clearance
TRACK = board.netclass(Net("GND")).track_width
FB_GND_LANE = CLEAR + TRACK + CLEAR   # between VCC's capacitor and the divider's lower resistor: FB_5V_GND's run from its tie
VIA_PITCH = VIA + CLEAR       # vias in one pad, copper a clearance apart
FILLET = 0.05                 # pour corner radius
SIGNAL_INNER, SUPPLY_INNER = inner_layers()   # signals on In2, the 3V3 plane on In3
LYING, LYING_FLIPPED, UP_PAD1_SOUTH, UP_PAD1_NORTH = 0, 180, 90, 270   # two-pad parts: pad 1 west, east, south, north

BIAS_PIN, VCC_PIN, AGND_PIN, FB_PIN = 1, 2, 3, 4
RT_PIN, EN_PIN = 6, 7
VIN_N, PGND_N, VIN_S, PGND_S = 8, 11, 12, 9   # the footprint's north and south VIN/PGND corners
SW_PIN, RBOOT_PIN, CBOOT_PIN = 10, 13, 14


def pad(part, key):
    return PadRef(Part(part), key)


def pin(n):
    return pad("buck", n)


def pour(net, pads, layer=CopperLayer.F, width=None):
    """One pour over these pads' copper, fitted round every other net's (a
    neck at `width` when given)."""
    board.pour(Net(net), pads, layer=layer, swallow_pads=True, width=width)


board.rect(fit=True)   # the frame is the content plus the keep-in
board.place(Part("buck"), why="the regulator at the frame's origin; the rest from its pads")

# --- input pairs, one at each VIN/PGND corner -------------------------------------
# The 100 nF lies across its VIN pad (west) and PGND pad (east), a silk gap
# outside the regulator; the 4.7 uF lies outside it, VIN ends aligned. Each
# pair is two necks, not one hull over all three pads: a single hull grows
# to the capacitors' full pad height and can wall a neighbouring pin in.
board.place(Part("c_hf1"), at=Beside(Part("buck"), Edge.NORTH, align=pin(VIN_N)), rotation=LYING,
            why="the north pair's 100 nF across VIN and PGND2, outside the regulator")
board.place(Part("c_in1"), at=Beside(Part("c_hf1"), Edge.NORTH, align=pad("c_hf1", "VSHUNT")), rotation=LYING,
            why="the north pair's 4.7 uF outside its 100 nF")
board.place(Part("c_hf2"), at=Beside(Part("buck"), Edge.SOUTH, align=pin(VIN_S)), rotation=LYING,
            why="the south pair's 100 nF across VIN and PGND1, outside the regulator")
board.place(Part("c_in2"), at=Beside(Part("c_hf2"), Edge.SOUTH, align=pad("c_hf2", "VSHUNT")), rotation=LYING,
            why="the south pair's 4.7 uF outside its 100 nF")

# --- the coil and the output ------------------------------------------------------
board.place(Part("coil"), at=Beside(Part("buck"), Edge.EAST, align=pin(SW_PIN)), rotation=Facing(pad("coil", "SW_5V"), Edge.WEST),
            why="the coil east, its SW end a clearance from the PGND pads, level with the SW pin")
board.place(Part("c_out1"), at=Beside(Part("coil"), Edge.NORTH, align=pad("coil", "PP5V")), rotation=LYING_FLIPPED,
            why="the first 22 uF north of the coil, PP5V over its output end")
board.place(Part("c_out2"), at=Beside(Part("coil"), Edge.SOUTH, align=pad("coil", "PP5V")), rotation=LYING_FLIPPED,
            why="the second 22 uF south of the coil, PP5V over its output end")

# PP5V's two 100 uF polymer reservoirs east of the coil, centred on its
# output pad, PP5V ends (pad 1) west toward it.
board.row([Part("bulk_a"), Part("bulk_b")], Edge.EAST, of=Part("coil"), centre=pad("coil", "PP5V"),
          rotation=Facing(1, Edge.WEST))

# --- the boot capacitor, north of CBOOT and RBOOT, as close as the board allows ---
board.place(Part("c_boot"), at=Beside(Part("buck"), Edge.NORTH, align=("BST_5V", pin(CBOOT_PIN))),
            rotation=UP_PAD1_SOUTH, why="the boot capacitor north of the regulator, level with CBOOT, SW end north")

# --- the enable gate, in the north-west corner ------------------------------------
# The open-drain buffer that holds EN low while the ESP32's VBUS_EN is low,
# and its 100 nF: the capacitor upright west of the boot capacitor, ground
# ends level; the buffer west of it, turned so its VCC pin is level with the
# capacitor's V3V3 pad. Slow signals: the core routes VBUS_EN in and the
# output down to the enable divider's EN pour.
board.place(Part("c_en_gate"), at=Beside(Part("c_boot"), Edge.WEST, align=("GND", pad("c_boot", "SW_5V"))),
            rotation=UP_PAD1_SOUTH, why="the enable gate's 100 nF upright west of the boot capacitor, level with its SW end")
BUF_ROTATION = 180   # VCC (pin 6) south-east, beside the capacitor; the output (pin 4) south-west
board.place(Part("en_gate"), at=Beside(Part("c_en_gate"), Edge.WEST, align=pad("c_en_gate", "V3V3")),
            rotation=BUF_ROTATION, why="the enable gate west of its 100 nF, VCC level with the capacitor's V3V3 pad")

# --- the quiet side: west of the column ---------------------------------------------
board.place(Part("c_vcc"), at=Beside(Part("buck"), Edge.WEST, align=pin(VCC_PIN)), rotation=LYING_FLIPPED,
            why="VCC's 1 uF west of its pin, VCC end east")
# The column's FB ends face the pins, joined by one FB run beside them; the
# feed-forward capacitor stands west, level with the divider's top pad
# (Figure 12-2's CFF between RFBT and RFF).
board.place(Part("r_fb_bottom"), at=Beside(Part("c_vcc"), Edge.SOUTH, gap=FB_GND_LANE, align=("FB_5V", pad("c_vcc", "VCC_5V"))),
            rotation=LYING_FLIPPED, why="the divider's lower resistor under VCC's capacitor, level with FB, FB end east")
board.place(Part("r_fb_top"), at=Beside(Part("r_fb_bottom"), Edge.SOUTH, align=pad("r_fb_bottom", "FB_5V")),
            rotation=LYING, why="the divider's upper resistor under the lower one, FB ends together")
board.place(Part("r_ff"), at=Beside(Part("r_fb_top"), Edge.SOUTH, align=pad("r_fb_top", "FB_5V")), rotation=LYING,
            why="the feed-forward resistor under the divider, FB end east")
board.place(Part("c_ff"), at=Beside(Part("r_ff"), Edge.WEST, align=("PP5V_SENSE", pad("r_fb_top", "PP5V_SENSE"))),
            rotation=Facing(pad("c_ff", "PP5V_SENSE"), Edge.NORTH), why="the feed-forward capacitor west of the column, its sense end level with the divider's top")

# The divider's sense ties (Usb5v.zen): PP5V_SENSE's on the first 22 uF's
# output pad, its north edge, sense pad north; FB_5V_GND's on AGND's west
# edge, between the VCC and FB runs, sense pad west toward the divider.
board.place(Part("nt_pp5v_sense"), at=Pin(1, PadRef(Part("c_out1"), "PP5V", edge=Edge.NORTH, along=Along.MID)),
            rotation=Facing(PadRef(Part("nt_pp5v_sense"), 2), Edge.NORTH), why="PP5V_SENSE's tie on the first 22 uF's output pad, sense pad north")
board.place(Part("nt_fb_gnd"), at=Pin(1, PadRef(Part("buck"), AGND_PIN, edge=Edge.WEST, along=Along.MID)),
            rotation=Facing(PadRef(Part("nt_fb_gnd"), 2), Edge.WEST), why="FB_5V_GND's tie on AGND's west edge, sense pad west")

# --- the quiet side: south of RT and EN -----------------------------------------------
# The enable divider west of the south 4.7 uF, VSHUNT ends facing, EN ends
# together; RT's resistor centred over the divider's EN ends, as far north
# (toward the regulator) as the board allows, RT end east.
board.place(Part("r_en_top"), at=Beside(Part("c_in2"), Edge.WEST, align=pad("c_in2", "VSHUNT")),
            rotation=LYING_FLIPPED, why="the enable divider's upper resistor west of the south 4.7 uF, VSHUNT ends facing")
board.place(Part("r_en_bottom"), at=Beside(Part("r_en_top"), Edge.WEST, align=pad("r_en_top", "EN_5V")),
            rotation=LYING_FLIPPED, why="the enable divider's lower resistor west of it, EN ends facing")
board.place(Part("r_rt"), at=Beside(Part("buck"), Edge.SOUTH, align=("RT_5V", pin(RT_PIN))),
            rotation=LYING_FLIPPED, why="RT's resistor south of the regulator, level with its pin")

frame_planes(FILLET, supply=None)
for name in ("GND", "VSHUNT", "PP5V"):
    board.free_net(Net(name))


# --- copper -------------------------------------------------------------------------
F = CopperLayer.F


# GND: the component face's ground zone joins each PGND pad with its input
# pair's and its output capacitor's ground and the reservoirs' ground ends
# (Figure 12-2's top-layer ground).

board.track(Net("SW_5V"), [pin(SW_PIN), Between(pin(RBOOT_PIN), pin(VIN_N)), pad("c_boot", "SW_5V")],
            layer=F, width=0.16, why="SW to the boot capacitor")


# The quiet side.
board.track(Net("VCC_5V"), [pin(VCC_PIN), pad("c_vcc", "VCC_5V")], layer=F)
board.track(Net("FB_5V"), [pin(FB_PIN), pad("r_fb_bottom", "FB_5V")], layer=F)
# AGND's pad is too narrow for a via in it, and its west end holds the
# divider's ground tie; the via stands at the nearest legal spot, with a
# short tail to the pin.
_agnd_via = board.via(Net("GND"), FreeSpot(near=pin(AGND_PIN)), size=VIA, drill=VIA_DRILL)
board.track(Net("GND"), [pin(AGND_PIN), _agnd_via], layer=F)
# RT runs pin to resistor, direct. EN's own lane on the front face is
# pinched between RT's track and the VSHUNT neck into the divider, so it
# drops to In2 (the fragment's own signal layer) at each end.
board.track(Net("RT_5V"), [pin(RT_PIN), pad("r_rt", "RT_5V")], layer=F)
_en_via_pin = board.via(Net("EN_5V"), FreeSpot(near=pin(EN_PIN)), size=VIA, drill=VIA_DRILL)
board.track(Net("EN_5V"), [pin(EN_PIN), _en_via_pin], layer=F)
_en_via_r = board.via(Net("EN_5V"), FreeSpot(near=pad("r_en_top", "EN_5V")), size=VIA, drill=VIA_DRILL)
board.track(Net("EN_5V"), [pad("r_en_top", "EN_5V"), _en_via_r], layer=F)
board.track(Net("EN_5V"), [_en_via_pin, _en_via_r], layer=SIGNAL_INNER)

# The output sense on In3 (Figure 12-2's vias to BIAS and to the feedback
# divider, on the layer the VIN strap does not use): from its tie on the
# first 22 uF's output pad, through the gap between the north input pair's
# ground and PGND2, to a via in BIAS's pad, then to a via in the
# feed-forward capacitor's sense pad, clear of every FB copper.
_vs_down = board.via(Net("PP5V_SENSE"), FreeSpot(near=PadRef(Part("nt_pp5v_sense"), 2)), size=VIA, drill=VIA_DRILL)
board.track(Net("PP5V_SENSE"), [PadRef(Part("nt_pp5v_sense"), 2), _vs_down], layer=F)
board.via(Net("PP5V_SENSE"), pin(BIAS_PIN), size=VIA, drill=VIA_DRILL)
board.via(Net("PP5V_SENSE"), pad("c_ff", "PP5V_SENSE"), size=VIA, drill=VIA_DRILL)
board.track(Net("PP5V_SENSE"), [_vs_down, Between(pad("c_hf1", "GND"), pin(PGND_N)), pin(BIAS_PIN)],
            layer=SUPPLY_INNER)
board.track(Net("PP5V_SENSE"), [pin(BIAS_PIN), pad("c_ff", "PP5V_SENSE")], layer=SUPPLY_INNER, bend=Bend.END)

# The divider's ground sense on the component face: from its tie on AGND
# west, a clearance under VCC's capacitor, and down into the lower
# resistor's sense pad (no room for a via between the VCC and FB runs).
board.track(Net("FB_5V_GND"), [PadRef(Part("nt_fb_gnd"), 2),
                               Past([pad("c_vcc", "VCC_5V"), pad("c_vcc", "GND")], Edge.SOUTH, across=PadRef(Part("nt_fb_gnd"), 2)),
                               pad("r_fb_bottom", "FB_5V_GND")], layer=F, bend=Bend.END)


# Drops: as many vias as fit in each power pad, one in each small one.
for n in (PGND_N, PGND_S):
    board.vias(Net("GND"), pin(n), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
for part in ("c_in1", "c_in2"):
    board.vias(Net("GND"), pad(part, "GND"), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
for part in ("c_out1", "c_out2"):   # nearer the GND pour's own edge: one via each, not a grid
    board.via(Net("GND"), pad(part, "GND"), size=VIA, drill=VIA_DRILL)
for part in ("bulk_a", "bulk_b"):
    board.vias(Net("GND"), pad(part, 2), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
_vin_n = board.vias(Net("VSHUNT"), pad("c_in1", "VSHUNT"), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
_vin_s = board.vias(Net("VSHUNT"), pad("c_in2", "VSHUNT"), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
for part in ("c_hf1", "c_hf2", "c_vcc", "r_rt", "r_en_bottom"):
    board.via(Net("GND"), pad(part, "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), pad("c_en_gate", "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), FreeSpot(near=pad("en_gate", "GND")), size=VIA, drill=VIA_DRILL)   # its pin is too narrow to hold one

# --- pours, after the tracks and vias they fit round ---------------------------------
# VSHUNT: each VIN pad to its 100 nF, then to its 4.7 uF, each a neck. The
# south one also takes the enable divider's VSHUNT end.
pour("VSHUNT", [pin(VIN_N), pad("c_hf1", "VSHUNT")])
pour("VSHUNT", [pad("c_hf1", "VSHUNT"), pad("c_in1", "VSHUNT")])
pour("VSHUNT", [pin(VIN_S), pad("c_hf2", "VSHUNT")])
pour("VSHUNT", [pad("c_hf2", "VSHUNT"), pad("c_in2", "VSHUNT")])
pour("VSHUNT", [pad("c_in2", "VSHUNT"), pad("r_en_top", "VSHUNT")])
# SW: the pin to the coil's SW pad, one pour fitted between the PGND lands
# either side, which leave 1.47 mm (the package sets it; SW's 3.4 A wants
# 1.62 mm at a 10 C rise). A thin track runs on to the boot
# capacitor, through the gap between the north VIN pad and RBOOT (TI's
# routing), since that lane is too narrow for the wide pour.
pour("SW_5V", [pin(SW_PIN), pad("coil", "SW_5V")])
# BST: RBOOT and CBOOT joined, up to the boot capacitor: one pour over the
# three pads' copper.
pour("BST_5V", [pin(RBOOT_PIN), pin(CBOOT_PIN), pad("c_boot", "BST_5V")])
# PP5V: the coil's output end, both 22 uF and both reservoirs' PP5V ends (3.4 A).
pour("PP5V", [pad("coil", "PP5V"), pad("c_out1", "PP5V"), pad("c_out2", "PP5V"), pad("bulk_a", 1), pad("bulk_b", 1)])
pour("FB_5V", [pad("r_fb_bottom", "FB_5V"), pad("r_fb_top", "FB_5V"), pad("r_ff", "FB_5V")])
pour("FF_5V", [pad("r_ff", "FF_5V"), pad("c_ff", "FF_5V")])
pour("PP5V_SENSE", [pad("r_fb_top", "PP5V_SENSE"), pad("c_ff", "PP5V_SENSE")])
pour("EN_5V", [pad("r_en_bottom", "EN_5V"), pad("r_en_top", "EN_5V")])
pour("V3V3", [pad("en_gate", "V3V3"), pad("c_en_gate", "V3V3")])
# The VIN strap on In2 (Figure 12-2): the two 4.7 uF's VSHUNT drops joined
# straight under the regulator.
board.pour(Net("VSHUNT"), [_vin_n, _vin_s], layer=SIGNAL_INNER, swallow_pads=True,
           why="LM61440-Q1 SNVSBE4C Figure 12-2: the VIN strap joining the two input pairs on an inner layer")
