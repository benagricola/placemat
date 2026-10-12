"""Independent USB source isolation and 5 V PC input protection.

TPS25947 ZHCSL91B section 11.1: each switch has local input/output bypasses and
short analog setting nodes. The parent places this cell between the PD's
sink FET pair, converter output and connector. No high-current rail is a
global plane here: the parent must provide short, wide connections sized
for twice the load current, and thermal spreading at IN/OUT.

The two switches stand side by side, the source west and the PC-input
(sink) east, laid out from their pads as Ben's hand layout of 2026-09-27
arranged them (its intent, not its coordinates), with the passives lying
where a lying part closes the frame up:

- each output bypass lies north of its switch, its output pad on the
  switch's centre line, ground east; the source's EN pull-down stands in
  the west column over the input bypass's ground end, the sink's a silk gap
  west of its output bypass, both on the bypass's row;
- each ILM resistor stands upright a silk gap east of its switch, ILM
  straight across to its upper pad and GND stepping from pin 8 to its lower;
- the sink's OVLO divider stands as one column between the switches, the
  top a silk gap east of the source's ILM resistor and a step below OVLO's
  row, the bottom under it; the sink switch stands a silk gap east of it;
- under the source, its input bypass lies below the IN land and the enable
  gate's bypass under that; the gate stands a silk gap east of them, VCC on
  the input bypass's row, with the PD_SOURCE pull-down lying east of it on
  the bottom row;
- under the sink, the dV/dt capacitor lies below DVDT and the input bypass
  on the same row, a silk gap east of the divider column, the IN land
  stepping across to it.

SOURCE_EN and the divider's PC_IN feed cross the cell on In2 (the component
face's other side is the core's other face, so the fragment draws nothing on
B.Cu); SOURCE_EN runs round the west side rather than under the source
switch. The frame is the content and the keep-in round it.

Internal routing is checked separately from load-path and thermal qualification.
Evidence: docs/decisions/layout/usb-power-path-routing-2026-09-26.md.
"""
from placemat import board, CopperLayer, FreeSpot, LinkWeight, Net, PadRef, Part, X, Y

from fragment_frame import Content, drawn_from_pad, frame_planes, pad_from_origin, size, inner_layers

SIGNAL_INNER, _ = inner_layers()   # the core's signal layer, In2

BYPASS_LIMIT = 2.0            # local IN/OUT/GND loops, TPS25947 ZHCSL91B section 11.1
SETTING_LIMIT = 2.0           # keep ILM and slew nodes away from switching noise
VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
GAP = 0.2                     # the board's silk-to-silk clearance (board_rules.zen)
FILLET = 0.15                 # the ground zone's corner radius
DIVIDER_DROP = 0.3            # the divider's top stands this far below OVLO's row, so the sink's EN
                              # track can step past its upper pad (Ben's hand layout, 2026-09-27)
EN_PIN, OVLO_PIN, IN_PIN, OUT_PIN, DVDT_PIN, GND_PIN, ILM_PIN = 1, 2, 5, 6, 7, 8, 9
GATE_B_PIN, GATE_Y_PIN, GATE_VCC_PIN = 2, 4, 6   # SN74LVC1G08 DRY: A 1, B 2, GND 3, Y 4, NC 5, VCC 6
UPRIGHT, UPRIGHT_FLIPPED, AS_GENERATED, FLIPPED = 90, 270, 0, 180   # a two-pad part's turns: pad 1 south, north, west, east
LEFT, TOP, RIGHT, BOTTOM = 0, 1, 2, 3   # drawn_from_pad()'s sides
LAND_W = size(board.pad(Part("source_switch"), IN_PIN).box)[0]   # the IN/OUT lands' width
CLEAR = board.netclass(Net("GND")).clearance
TRACK = board.netclass(Net("GND")).track_width
GATE_PAD_HALF = size(board.pad(Part("source_permit"), GATE_B_PIN).box)[1] / 2.0


def edge(part, pad, rotation, side):
    """One side of a part's drawn envelope (copper, mask and silk), from one of
    its pads' centre, the part turned."""
    return drawn_from_pad(part, pad, rotation)[side]


def centre_line(part, pad, rotation):
    """How far east of one of its pads the part's origin stands."""
    return -pad_from_origin(part, pad, rotation)[0]


def same_row(part, pad, rotation, ref_part, ref_pad, ref_rotation):
    """The y offset from ref_pad that puts part's origin on ref_part's origin row."""
    return pad_from_origin(part, pad, rotation)[1] - pad_from_origin(ref_part, ref_pad, ref_rotation)[1]


g = Content("source_switch")


def efuse_parts(switch, c_out, out_net, c_in, in_net, r_limit, limit_net):
    """The output bypass north and the ILM resistor east; the input bypass is
    linked here and placed by its switch's own rule."""
    g.beside(c_out, out_net, switch, OUT_PIN, centre_line(switch, OUT_PIN, 0),
             edge(switch, OUT_PIN, 0, TOP) - GAP - edge(c_out, out_net, AS_GENERATED, BOTTOM), AS_GENERATED,
             "output bypass lying north of the switch, its output pad on the centre line, ground east")
    g.beside(r_limit, limit_net, switch, ILM_PIN,
             edge(switch, ILM_PIN, 0, RIGHT) + GAP - edge(r_limit, limit_net, UPRIGHT_FLIPPED, LEFT), 0.0,
             UPRIGHT_FLIPPED, "the ILM resistor upright east of ILM, its ground end below pin 8's row")
    for part, net in ((c_out, out_net), (c_in, in_net), (r_limit, limit_net)):
        board.link(PadRef(Part(part), net), PadRef(Part(switch), net), weight=LinkWeight.SHORT,
                   limit_mm=BYPASS_LIMIT if part != r_limit else SETTING_LIMIT, why="local to its pin")


# --- the source switch and what stands round it ------------------------------
efuse_parts("source_switch", "c_source_out", "VBUS", "c_source_in", "USB_HV", "r_source_limit", "SOURCE_LIMIT")
g.beside("c_source_in", "USB_HV", "source_switch", IN_PIN, 0.0,
         edge("source_switch", IN_PIN, 0, BOTTOM) + GAP - edge("c_source_in", "USB_HV", FLIPPED, TOP), FLIPPED,
         "input bypass lying under the IN land, ground west")
g.beside("r_source_en", "SOURCE_EN", "c_source_out", "VBUS",
         g.pad("c_source_in", "GND")[0] - g.pad("c_source_out", "VBUS")[0],
         same_row("r_source_en", "SOURCE_EN", UPRIGHT, "c_source_out", "VBUS", AS_GENERATED), UPRIGHT,
         "the default-off EN pull-down in the west column, on the output bypass's row")
g.beside("c_logic", "V3V3", "c_source_in", "USB_HV", 0.0,
         edge("c_source_in", "USB_HV", FLIPPED, BOTTOM) + GAP - edge("c_logic", "V3V3", FLIPPED, TOP), FLIPPED,
         "the gate's bypass lying under the input bypass")
g.beside("source_permit", GATE_VCC_PIN, "c_source_in", "USB_HV",
         edge("c_source_in", "USB_HV", FLIPPED, RIGHT) + GAP - edge("source_permit", GATE_VCC_PIN, 0, LEFT), 0.0,
         0, "the enable gate a silk gap east of the bypasses, VCC on the input bypass's row")
# The pull-down's row is where PD_SOURCE can run east from B under the gate's
# GND pad: a clearance and half a track below the south pads.
g.beside("r_source_permission", "PD_SOURCE", "source_permit", GATE_B_PIN,
         edge("source_permit", GATE_B_PIN, 0, RIGHT) + GAP - edge("r_source_permission", "PD_SOURCE", AS_GENERATED, LEFT),
         GATE_PAD_HALF + CLEAR + TRACK / 2.0, AS_GENERATED,
         "default-off PD source permission lying east of the gate, its row clear under the gate's south pads")

# --- the divider column, then the sink switch and what stands round it -------
g.beside("r_sink_ov_top", "SINK_OVLO", "r_source_limit", "SOURCE_LIMIT",
         edge("r_source_limit", "SOURCE_LIMIT", UPRIGHT_FLIPPED, RIGHT) + GAP
         - edge("r_sink_ov_top", "SINK_OVLO", UPRIGHT_FLIPPED, LEFT), DIVIDER_DROP, UPRIGHT_FLIPPED,
         "the OVLO divider's top a silk gap east of the source's ILM resistor, PC_IN north")
g.beside("r_sink_ov_bottom", "SINK_OVLO", "r_sink_ov_top", "SINK_OVLO", 0.0,
         edge("r_sink_ov_top", "SINK_OVLO", UPRIGHT_FLIPPED, BOTTOM) + GAP
         - edge("r_sink_ov_bottom", "SINK_OVLO", UPRIGHT_FLIPPED, TOP), UPRIGHT_FLIPPED,
         "the divider's bottom under its top, joined at OVLO")
g.beside("sink_switch", OVLO_PIN, "r_sink_ov_top", "SINK_OVLO",
         edge("r_sink_ov_top", "SINK_OVLO", UPRIGHT_FLIPPED, RIGHT) + GAP - edge("sink_switch", OVLO_PIN, 0, LEFT),
         -DIVIDER_DROP, 0, "the PC-input switch a silk gap east of the divider column")
efuse_parts("sink_switch", "c_sink_out", "VSHUNT", "c_sink_in", "PC_IN", "r_sink_limit", "SINK_LIMIT")
g.beside("r_sink_en", "PD_SINK", "c_sink_out", "VSHUNT",
         edge("c_sink_out", "VSHUNT", AS_GENERATED, LEFT) - GAP - edge("r_sink_en", "PD_SINK", UPRIGHT, RIGHT),
         same_row("r_sink_en", "PD_SINK", UPRIGHT, "c_sink_out", "VSHUNT", AS_GENERATED), UPRIGHT,
         "the default-off EN pull-down a silk gap west of the output bypass, on its row")
g.beside("c_sink_slew", "SINK_SLEW", "sink_switch", DVDT_PIN, 0.0,
         edge("sink_switch", DVDT_PIN, 0, BOTTOM) + GAP - edge("c_sink_slew", "SINK_SLEW", AS_GENERATED, TOP),
         AS_GENERATED, "the dV/dt capacitor lying under DVDT, ground east")
# The input bypass on the dV/dt capacitor's row, a silk gap east of the
# divider column: under the IN land it would sit on the divider's silk.
_bottom_right = g.pad("r_sink_ov_bottom", "SINK_OVLO")[0] + edge("r_sink_ov_bottom", "SINK_OVLO", UPRIGHT_FLIPPED, RIGHT)
g.beside("c_sink_in", "PC_IN", "c_sink_slew", "SINK_SLEW",
         _bottom_right + GAP - edge("c_sink_in", "PC_IN", FLIPPED, LEFT) - g.pad("c_sink_slew", "SINK_SLEW")[0],
         0.0, FLIPPED, "the input bypass on the dV/dt row, a silk gap east of the divider, ground west")
board.link(PadRef(Part("c_sink_slew"), "SINK_SLEW"), PadRef(Part("sink_switch"), "SINK_SLEW"),
           weight=LinkWeight.SHORT, limit_mm=SETTING_LIMIT, why="local slew timing capacitor")

board.rect(fit=True)   # the frame is the content plus the keep-in
g.place(why="the source switch at the frame's origin")
frame_planes(FILLET)
board.free_net(Net("V3V3"))


# --- copper -------------------------------------------------------------------
def pin(part, n):
    return PadRef(Part(part), n)


def via_in(part, net):
    """A plane or layer drop in the pad, filled and capped."""
    board.via(Net(net), PadRef(Part(part), net), size=VIA, drill=VIA_DRILL)


def step(from_part, from_pad, to_part, to_pad):
    """How far apart two pads stand east-west: the length of a 45-degree step
    between their columns."""
    return abs(g.pad(to_part, to_pad)[0] - g.pad(from_part, from_pad)[0])


def switch_copper(switch, c_out, out_net, c_in, in_net, r_limit, limit_net):
    """One eFuse's local copper."""
    # The bypass branches are as wide as the lands they leave; the load
    # paths are the core's. Each leaves its land straight, then steps 45
    # degrees onto its bypass's pad.
    out = pin(switch, OUT_PIN)
    board.track(Net(out_net), [out, (X(out), Y(PadRef(Part(c_out), out_net), step(switch, OUT_PIN, c_out, out_net))),
                               PadRef(Part(c_out), out_net)], layer=CopperLayer.F, width=LAND_W)
    inp = pin(switch, IN_PIN)
    board.track(Net(in_net), [inp, (X(inp), Y(PadRef(Part(c_in), in_net), -step(switch, IN_PIN, c_in, in_net))),
                              PadRef(Part(c_in), in_net)], layer=CopperLayer.F, width=LAND_W)
    board.track(Net(limit_net), [pin(switch, ILM_PIN), PadRef(Part(r_limit), limit_net)], layer=CopperLayer.F)
    # GND leaves pin 8 east and steps 45 degrees down onto the ILM resistor's
    # ground end, clear of its ILM pad: the quiet return TI asks for.
    _drop = g.pad(r_limit, "GND")[1] - g.pad(switch, GND_PIN)[1]
    board.track(Net("GND"), [pin(switch, GND_PIN), (X(PadRef(Part(r_limit), "GND"), -_drop), Y(pin(switch, GND_PIN))),
                             PadRef(Part(r_limit), "GND")], layer=CopperLayer.F)
    for part in (c_out, c_in, r_limit):
        via_in(part, "GND")


def enable_copper(switch, r_en, en_net):
    """EN steps 45 degrees from its pin into the pull-down's column, then runs
    north to it."""
    en = pin(switch, EN_PIN)
    board.track(Net(en_net), [en, (X(PadRef(Part(r_en), en_net)), Y(en, -step(switch, EN_PIN, r_en, en_net))),
                              PadRef(Part(r_en), en_net)], layer=CopperLayer.F)
    via_in(r_en, "GND")


switch_copper("source_switch", "c_source_out", "VBUS", "c_source_in", "USB_HV", "r_source_limit", "SOURCE_LIMIT")
switch_copper("sink_switch", "c_sink_out", "VSHUNT", "c_sink_in", "PC_IN", "r_sink_limit", "SINK_LIMIT")
enable_copper("source_switch", "r_source_en", "SOURCE_EN")
enable_copper("sink_switch", "r_sink_en", "PD_SINK")

# The sink's OVLO divider: west from OVLO, a step down to the top's lower
# pad, on to the bottom's upper; and the dV/dt capacitor under DVDT.
_ovlo = pin("sink_switch", OVLO_PIN)
board.track(Net("SINK_OVLO"), [_ovlo, (X(PadRef(Part("r_sink_ov_top"), "SINK_OVLO"), DIVIDER_DROP), Y(_ovlo)),
                               PadRef(Part("r_sink_ov_top"), "SINK_OVLO"),
                               PadRef(Part("r_sink_ov_bottom"), "SINK_OVLO")], layer=CopperLayer.F)
board.track(Net("SINK_SLEW"), [pin("sink_switch", DVDT_PIN), PadRef(Part("c_sink_slew"), "SINK_SLEW")],
            layer=CopperLayer.F)
via_in("r_sink_ov_bottom", "GND")
via_in("c_sink_slew", "GND")
# The divider's top takes PC_IN from the input bypass on In2: a 45-degree
# step into the sink's IN column, down it, and a step onto the bypass.
via_in("r_sink_ov_top", "PC_IN")
via_in("c_sink_in", "PC_IN")
_pc_top = PadRef(Part("r_sink_ov_top"), "PC_IN")
_pc_cap = PadRef(Part("c_sink_in"), "PC_IN")
_sink_in = pin("sink_switch", IN_PIN)
board.track(Net("PC_IN"), [_pc_top, (X(_sink_in), Y(_pc_top, step("r_sink_ov_top", "PC_IN", "sink_switch", IN_PIN))),
                           (X(_sink_in), Y(_pc_cap, -step("sink_switch", IN_PIN, "c_sink_in", "PC_IN"))), _pc_cap],
            layer=SIGNAL_INNER)

# The gate: its bypass steps 45 degrees up to VCC, its pull-down turns off B
# along the bottom row, and Y drops beside its pin and reaches the source
# switch's EN on In2 round the west side, clear of the ground drops under the
# input bypass.
_vcc = pin("source_permit", GATE_VCC_PIN)
_logic = PadRef(Part("c_logic"), "V3V3")
board.track(Net("V3V3"), [_logic, (X(_logic), Y(_vcc, step("c_logic", "V3V3", "source_permit", GATE_VCC_PIN))), _vcc],
            layer=CopperLayer.F)
_b = pin("source_permit", GATE_B_PIN)
_permission = PadRef(Part("r_source_permission"), "PD_SOURCE")
board.track(Net("PD_SOURCE"), [_b, (X(_b), Y(_permission)), _permission], layer=CopperLayer.F)
via_in("c_logic", "V3V3")
via_in("c_logic", "GND")
via_in("r_source_permission", "GND")
_y = pin("source_permit", GATE_Y_PIN)
_y_via = board.via(Net("SOURCE_EN"), FreeSpot(near=_y), size=VIA, drill=VIA_DRILL)
via_in("r_source_en", "SOURCE_EN")
_en_pull = PadRef(Part("r_source_en"), "SOURCE_EN")
_hv = PadRef(Part("c_source_in"), "USB_HV")
# It turns up a via's room short of the input bypass's column, so the core's
# USB_HV drop can stand in that pad (the load path is the core's).
_hv_half = max(size(board.pad(Part("c_source_in"), "USB_HV").box)) / 2.0
DROP_ROOM = _hv_half + CLEAR + TRACK / 2.0 + VIA / 2.0          # from the pad's centre to SOURCE_EN's turn
_away = 1.0 if g.pad("r_source_en", "SOURCE_EN")[0] < g.pad("c_source_in", "USB_HV")[0] else -1.0   # from the pull-down, toward the gate
board.track(Net("SOURCE_EN"), [_y_via, (X(_hv, _away * DROP_ROOM), Y(_y)),
                               (X(_en_pull), Y(_y, -(step("c_source_in", "USB_HV", "r_source_en", "SOURCE_EN") + DROP_ROOM))),
                               _en_pull], layer=SIGNAL_INNER)
