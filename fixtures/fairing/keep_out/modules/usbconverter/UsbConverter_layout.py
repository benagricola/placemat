"""UsbConverter: the TPS55288 buck-boost that makes VBUS from the bike supply.

A fragment, stamped onto the core's back face as the cell `usbconverter`.
TPS55288 datasheet figure 10-1 (section 10.2) as Ben laid it out by hand on
2026-10-01 (kept at `boards/core/hand/usbconverter/layout_hand-2026-10-01-0729.kicad_pcb`):

  input capacitors
  AON7934 half-bridge   c_boot2   settings (north)
  inductor (lying)    | TPS55288 | output capacitor, shunt
              c_boot1                VBUS reservoir

The input capacitors lie over the half-bridge's drain and source corners, so
the buck side's critical loop closes at the column's top. The inductor lies
under the half-bridge, SW1 under its switch pad, its SW2 terminal facing the
controller's pins 20-23, so SW2 is one short pour into pins 21 and 25 (TI's
figure 10-1). The boost side's critical loop (VOUT, the output capacitor and
PGND) closes east of the controller, where VBUS leaves through the shunt.

Every part stands against another part (a side, a pin it is level with, a
row along the controller); copper is pours over the pads they join, tracks
between pads and vias in pads or a clearance past pins. The gate drives and
VIN reach the controller's south pins on In2, SW1's return beside DR1H. The
ISP and ISN sense lines are their own nets, joined to the shunt's pads by
net ties (UsbConverter.zen item 4). Copper stays on the component face and
In2: the opposite outer layer is the core's other face.

Pins, from docs/decisions/schematics/core-netlist.xml. TPS55288: DR1L 1, DR1H 2, VIN 3, EN 4,
SCL 5, SDA 6, DITH 7, FSW 8, PGND 9 and 24, AGND 10, VOUT 11 and 26, ISP 12,
ISN 13, FAULT 14, MODE 15, CDC 16, ILIM 17, COMP 18, VCC 19, BOOT2 20, SW2
21 and 25, BOOT1 22, SW1 23. AON7934: G1 1, D1 2-4 and 9, S2 5-7, G2 8,
S1/D2 10.

Evidence and limits: ../../../../docs/decisions/layout/converter-internal-routing-2026-09-26.md.
"""
from placemat import (board, Along, Bend, Beside, CopperLayer, Corner, Cover, Edge, Facing, FreeSpot, LinkWeight, Location, Net, PadRef,
                      Mid, Part, Past, Pin, Reach, X, Y)

from fragment_frame import frame_planes, inner_layers

SIGNAL_INNER, _ = inner_layers()   # the core's signal layer, In2

VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
CLEAR = board.netclass(Net("SW1")).clearance
TRACK = board.netclass(Net("SW1")).track_width
FILLET = 0.15              # the pours' corner radius
KELVIN_LANE = CLEAR + TRACK + CLEAR          # east of the controller: room for ISP's sense track up past the output capacitor
VIA_ROWS = CLEAR + VIA + CLEAR + VIA + CLEAR  # under the south pins: two staggered rows of vias
ISP_CHAMFER = TRACK        # ISP turns east just past the output capacitor's VOUT corner: the default cut passes it inside the clearance
BOOT_PAIR = TRACK + CLEAR + TRACK            # BOOT1 and SW1 side by side, from pins 22-23 down to c_boot1
DECOUPLING_LIMIT = 2.0     # a bypass beyond this is a bulk capacitor, not a bypass
BOOT1_LIMIT = 4.0          # c_boot1 stands upright under pins 22-23, its BOOT1 pad the far one (Ben's hand layout, 2026-10-01: 3.4 mm)
SETTING_LIMIT = 4.0        # a setting resistor beside the pin it sets
FAN_START = TRACK / 2.0 + CLEAR   # the settings' risers end where a track clears the pin tips: the fan's 45s start there (Ben's hand layout)

CONTROLLER_ROTATION = 90   # BOOT2/SW2/BOOT1/SW1 (pins 20-23) face west, the settings (14-19) north, VOUT east

CTL = Part("vbus_conv")
F = CopperLayer.F


def pad(part, key):
    return PadRef(Part(part), key)


def pin(n):
    return PadRef(CTL, n)


def turn(part, pad_key, edge):
    """The turn that puts `part`'s pad `pad_key` on its `edge` side."""
    return Facing(PadRef(Part(part), pad_key), edge)


board.free_net(Net("GND"))
board.free_net(Net("VSHUNT"))
board.rect(fit=True)   # the frame is the content plus the keep-in

# --- the controller and its settings -------------------------------------------
board.place(CTL, at=Location(0, 0), rotation=CONTROLLER_ROTATION,
            why="the datum: SW2 west to the inductor, VOUT and PGND east to the output capacitor")
# The settings (Ben's hand layout, 2026-09-30): each pin from VCC (19, a
# corner pin, from its north land) to FAULT (14) rises on its own riser (an
# escape). COMP's resistor and VCC's capacitor stand upright just north of the risers, signal pads south, COMP's
# over its own riser and VCC's west of it; ILIM's east of COMP's, raised so
# CDC's track passes under it. FAULT's, MODE's and CDC's resistors lie in a column east of the pins,
# signal pads west, FAULT's lowest: its pad a clearance east of pin 13 and
# north of the risers, over the sense pair's run, so their tracks fan out
# north-east in nested 45s.
SETTINGS = [("c_vcc_bb", "VCC_BB", "AGND"), ("r_comp", "COMP_BB", "COMP_MID"), ("r_ilim_bb", "ILIM_BB", "AGND"),
            ("r_cdc", "CDC_SET", "AGND"), ("r_mode_bb", "MODE_BB", "AGND"), ("r_bb_fault", "BB_FAULT", "V3V3")]
esc_settings = board.escape(CTL, [19, 18, 17, 16, 15, 14], depth=FAN_START,
                            why="each setting's pin straight north, so the fan's 45s start level")
board.place(Part("r_comp"), at=Beside(esc_settings, Edge.NORTH, align=("COMP_BB", esc_settings[18])),
            rotation=turn("r_comp", "COMP_BB", Edge.SOUTH), why="COMP's resistor over its own riser, COMP south")
board.place(Part("c_vcc_bb"), at=Beside(Part("r_comp"), Edge.WEST, align=Along.END),
            rotation=turn("c_vcc_bb", "VCC_BB", Edge.SOUTH), why="VCC's capacitor west of COMP's resistor, VCC south")
board.place(Part("r_ilim_bb"), at=Beside(Part("r_comp"), Edge.EAST, align=("ILIM_BB", Past([pad("r_comp", "COMP_BB")], Edge.NORTH))),
            rotation=turn("r_ilim_bb", "ILIM_BB", Edge.SOUTH),
            why="ILIM's resistor east of COMP's, its pad over COMP's so CDC's 45 passes under it")
board.place(Part("r_bb_fault"), at=Beside(esc_settings, Edge.NORTH, align=("BB_FAULT", Past([pin(13)], Edge.EAST))),
            rotation=turn("r_bb_fault", "BB_FAULT", Edge.WEST),
            why="FAULT's resistor lying east of the pins, over the sense pair's run, BB_FAULT west")
board.place(Part("r_mode_bb"), at=Beside(Part("r_bb_fault"), Edge.NORTH, align=Along.START),
            rotation=turn("r_mode_bb", "MODE_BB", Edge.WEST), why="MODE's resistor over FAULT's, MODE west")
board.place(Part("r_cdc"), at=Beside(Part("r_mode_bb"), Edge.NORTH, align=Along.START),
            rotation=turn("r_cdc", "CDC_SET", Edge.WEST), why="CDC's resistor over MODE's, CDC west")
# COMP's capacitor lies over ILIM's resistor, its COMP_MID pad over COMP's
# resistor; r_agnd ties AGND to PGND at the VCC capacitor (section 10.1) a
# silk gap west of it.
board.place(Part("c_comp"), at=Beside(Part("r_ilim_bb"), Edge.NORTH, align=pad("r_comp", "COMP_MID")),
            rotation=turn("c_comp", "AGND", Edge.EAST),
            why="the compensation's capacitor over ILIM's resistor, COMP_MID over its own resistor's, AGND east")
board.place(Part("r_agnd"), at=Beside(Part("c_vcc_bb"), Edge.NORTH, align=pad("c_vcc_bb", "AGND")),
            rotation=turn("r_agnd", "GND", Edge.WEST),
            why="the AGND tie over the VCC capacitor, its AGND pad over the capacitor's, GND west")

# --- the SW2 side: the bootstrap capacitors, the half-bridge and the inductor --------
# Ben's hand layout of 2026-10-01: the inductor lies under the half-bridge
# with its SW2 terminal facing pins 20-23, as TI's figure 10-1 has it, so
# SW2 is one short pour from that terminal into pins 21 and 25. c_boot2 lies
# north-west of the controller, its SW2 pad on that pour; the half-bridge
# stands west of it. c_boot1 stands upright under pins 22-23, SW1 north and
# BOOT1 south; BOOT1 runs down a lane between it and the inductor's SW2
# terminal.
board.place(Part("c_boot2"), at=Beside(CTL, Edge.WEST, align=Along.START), rotation=turn("c_boot2", "SW2", Edge.WEST),
            why="north-west of the controller, its top flush with the controller's, BOOT2 east toward pin 20")
board.place(Part("q_buck"), at=Beside(Part("c_boot2"), Edge.WEST, align=Along.END),
            rotation=Facing([PadRef(Part("q_buck"), n) for n in (1, 2, 3, 4)], Edge.EAST),
            why="west of c_boot2, the two flush at the foot, the drain (pins 1-4) east and the source (5-8) west")
board.place(Part("c_vbus_in_a"), at=Beside(Part("q_buck"), Edge.NORTH), rotation=turn("c_vbus_in_a", 1, Edge.EAST),
            why="closes the buck loop over the drain and source corners")
board.place(Part("c_vbus_in_b"), at=Beside(Part("c_vbus_in_a"), Edge.NORTH), rotation=turn("c_vbus_in_b", 1, Edge.EAST),
            why="the second input capacitor over the first")
board.place(Part("c_boot1"), at=Beside(CTL, Edge.SOUTH, align=("SW1", Past([pin(23)], Edge.WEST))),
            rotation=turn("c_boot1", "SW1", Edge.NORTH),
            why="upright under pins 22-23, its SW1 pad a clearance west of pin 23's end, SW1 north")
board.place(Part("l_vbus"), at=Beside(Part("q_buck"), Edge.SOUTH,
                                      align=("SW2", Past([pad("c_boot1", "BOOT1"), pad("c_boot1", "SW1")], Edge.WEST,
                                                         lane=Net("BOOT1")))),
            rotation=turn("l_vbus", "SW1", Edge.WEST),
            why="lying under the half-bridge, its SW2 terminal facing pins 20-23, BOOT1's lane between it and c_boot1")

# --- the output side ---------------------------------------------------------
# East of the controller, past a lane for ISP's sense track: the output
# capacitor, its VOUT pad level with the ISP pin so the sense pair runs over
# its top and AGND's escape via stands between its pads; the shunt beside
# it, VBUS's reservoir under the shunt's VBUS terminal and FSW's resistor
# under the capacitor.
board.place(Part("c_vbus_out"), at=Beside(CTL, Edge.EAST, gap=KELVIN_LANE, align=("VOUT", pin(12))),
            rotation=turn("c_vbus_out", "VOUT", Edge.NORTH),
            why="closes the boost loop at VOUT and PGND; its VOUT pad level with the ISP pin, so the sense pair runs over its top")
board.place(Part("r_vbus_sense"), at=Beside(Part("c_vbus_out"), Edge.EAST), rotation=turn("r_vbus_sense", "VOUT", Edge.NORTH),
            why="VOUT terminal beside the output capacitor's VOUT pad, VBUS south")
# The Kelvin taps (UsbConverter.zen item 4): each sense net meets its shunt
# pad through a net tie beside the shunt, the tie's power pad joined to the
# pad's centre by a stub (Ben's hand layout, 2026-10-01 10:09). ISP's tie
# lies north of the shunt over its VOUT pad, its ISP pad a clearance off
# that pad copper to copper (a tie's own nets are exempt in KiCad, so this
# is said, not checked), sense pad west toward pin 12; ISN's east of the shunt, in the gap between its
# pads, sense pad east.
board.place(Part("nt_isp"), at=Beside(Part("r_vbus_sense"), Edge.NORTH, copper=True, align=pad("r_vbus_sense", "VOUT")),
            rotation=turn("nt_isp", 2, Edge.WEST), why="ISP's net tie north of the shunt, over its VOUT pad, sense pad west")
board.place(Part("nt_isn"), at=Beside(Part("r_vbus_sense"), Edge.EAST, align=(1, Past([pad("r_vbus_sense", "VOUT")], Edge.SOUTH))),
            rotation=turn("nt_isn", 2, Edge.EAST), why="ISN's net tie east of the shunt, in the gap between its pads")
board.place(Part("c_vbus_pd"), at=Beside(Part("r_vbus_sense"), Edge.SOUTH, align=pad("r_vbus_sense", "VBUS")),
            rotation=turn("c_vbus_pd", "VBUS", Edge.EAST), why="under the shunt's VBUS terminal, so load current leaves through it")
board.place(Part("r_fsw"), at=Beside(Part("c_vbus_out"), Edge.SOUTH, align=Along.START),
            rotation=turn("r_fsw", "FSW_SET", Edge.WEST), why="FSW west under the output capacitor, AGND east")
# EN's pull-down stands under the via rows, its EN pad under pin 4.
board.place(Part("r_vbus_en"), at=Beside(CTL, Edge.SOUTH, gap=VIA_ROWS, align=pin(4)),
            rotation=turn("r_vbus_en", "GND", Edge.EAST), why="EN's pull-down under the via rows, EN under pin 4, GND east")

for part, net, target in (("c_vcc_bb", "VCC_BB", 19), ("c_boot2", "BOOT2", 20)):
    board.link(pad(part, net), pin(target), weight=LinkWeight.SHORT, limit_mm=DECOUPLING_LIMIT, why="a bypass at its pin")
board.link(pad("c_boot1", "BOOT1"), pin(22), weight=LinkWeight.SHORT, limit_mm=BOOT1_LIMIT,
           why="the bootstrap capacitor upright under its pins, BOOT1 its far pad")

# --- power copper -----------------------------------------------------------------


def pour(net, pads):
    """One pour over these pads' copper, fitted round every other net's."""
    board.pour(Net(net), pads, layer=F, swallow_pads=True)


# --- the sense pair -------------------------------------------------------------
# ISP and ISN run in parallel from the shunt's net ties to pins 12 and 13
# (section 10.1). ISP leaves pin 12 east into the lane, rises past the
# output capacitor and runs east over it into its tie. ISN rises out of pin
# 13, runs east a clearance over ISP, rounds ISP's tie and comes down the
# shunt's east side into its own (Ben's hand layout, 2026-09-30).
_isp_end = PadRef(Part("nt_isp"), 2)
_isn_end = PadRef(Part("nt_isn"), 2)
board.track(Net("VOUT"), [PadRef(Part("nt_isp"), 1), pad("r_vbus_sense", "VOUT")], layer=F)
board.track(Net("VBUS"), [PadRef(Part("nt_isn"), 1), pad("r_vbus_sense", "VBUS")], layer=F, bend=Bend.END)
_isp = board.track(Net("ISP"), [pin(12), Past([pin(12)], Edge.EAST, across=pin(12)),
                                Past([pad("c_vbus_out", "VOUT")], Corner.NW),
                                Past([pad("c_vbus_out", "VOUT")], Edge.NORTH, across=Along.END), _isp_end],
                   layer=F, chamfer=ISP_CHAMFER)
_isp_tie = [PadRef(Part("nt_isp"), 1), PadRef(Part("nt_isp"), 2)]
_isn = board.track(Net("ISN"), [pin(13), Past([_isp] + _isp_tie, Edge.NORTH, across=pin(13)),
                                Past([_isp, PadRef(Part("nt_isn"), 1)] + _isp_tie, Corner.NE), _isn_end], layer=F)

# --- signals -------------------------------------------------------------------
board.track(Net("BOOT2"), [pin(20), pad("c_boot2", "BOOT2")], layer=F)

# The south pins take their vias in two rows a clearance under the pin ends:
# DR1H (2), EN (4) and SDA (6) in the near row, DR1L (1), VIN (3), SCL (5)
# and DITH (7) in the far row past them.
SOUTH_PINS = [pin(n) for n in range(1, 8)]
_near = {n: board.via(Net(net), at=Past(SOUTH_PINS, Edge.SOUTH, across=pin(n)), size=VIA, drill=VIA_DRILL)
         for n, net in ((2, "DR1H"), (4, "VBUS_EN"), (6, "SDA_PWR"))}
_far = {n: board.via(Net(net), at=Past(SOUTH_PINS + list(_near.values()), Edge.SOUTH, across=pin(n)), size=VIA, drill=VIA_DRILL)
        for n, net in ((1, "DR1L"), (3, "VSHUNT"), (5, "SCL_PWR"), (7, "AGND"))}
for n, net in ((2, "DR1H"), (4, "VBUS_EN"), (6, "SDA_PWR")):
    board.track(Net(net), [pin(n), _near[n]], layer=F)
for n, net in ((1, "DR1L"), (3, "VSHUNT"), (5, "SCL_PWR"), (7, "AGND")):
    board.track(Net(net), [pin(n), _far[n]], layer=F)
# EN runs on to its pull-down, which carries a via for the core's route.
board.track(Net("VBUS_EN"), [_near[4], pad("r_vbus_en", "VBUS_EN")], layer=F)
board.via(Net("VBUS_EN"), pad("r_vbus_en", "VBUS_EN"), size=VIA, drill=VIA_DRILL)

# BOOT1 and SW1 run down from pins 22-23 to c_boot1: SW1 off its pin's end
# and down into its north pad, BOOT1 on a 45 off its pin's end and down
# the lane west of c_boot1 into its south pad.
board.track(Net("SW1"), [pin(23), PadRef(CTL, 23, edge=Edge.WEST, along=Along.MID), pad("c_boot1", "SW1")], layer=F, bend=Bend.START)
board.track(Net("BOOT1"), [pin(22), PadRef(CTL, 22, edge=Edge.WEST, along=Along.MID),
                           Past([pad("c_boot1", "BOOT1"), pad("c_boot1", "SW1")], Edge.WEST, across=pad("c_boot1", "BOOT1")),
                           pad("c_boot1", "BOOT1")], layer=F, bend=Bend.START)
board.track(Net("BOOT2"), [pin(20), pad("c_boot2", "BOOT2")], layer=F)

# The gate drives on In2 (Ben's hand layout, 2026-10-01 07:29). SW1 returns
# from a via in c_boot1's SW1 pad straight to a via in the half-bridge's
# switch pad; DR1H runs beside it, up from its via and on a 45 into its
# gate, so the high-side drive (out on DR1H, back on SW1) encloses only the gap between
# them. DR1L leaves the far row west, under c_boot1's SW1 via, and runs
# under the inductor to its gate; its return is the ground plane under it.
# VIN rises from the drain pad parallel to DR1H on its north-east side.
_sw1_boot = board.via(Net("SW1"), pad("c_boot1", "SW1"), size=VIA, drill=VIA_DRILL)
_sw1_fet = board.via(Net("SW1"), pad("q_buck", 10), size=VIA, drill=VIA_DRILL)
board.track(Net("SW1"), [_sw1_boot, _sw1_fet], layer=SIGNAL_INNER, bend=Bend.END)
_dr1h_fet = board.via(Net("DR1H"), pad("q_buck", 1), size=VIA, drill=VIA_DRILL)
board.track(Net("DR1H"), [_near[2], _dr1h_fet], layer=SIGNAL_INNER, bend=Bend.END)
_dr1l_fet = board.via(Net("DR1L"), pad("q_buck", 8), size=VIA, drill=VIA_DRILL)
board.track(Net("DR1L"), [_far[1], Past([_sw1_boot], Edge.SOUTH, across=_far[1]), Past([_dr1l_fet], Edge.SOUTH, across=_dr1l_fet),
                          _dr1l_fet], layer=SIGNAL_INNER, bend=Bend.END)
_vin = board.via(Net("VSHUNT"), pad("q_buck", 9), size=VIA, drill=VIA_DRILL)
board.track(Net("VSHUNT"), [_vin, Past([_dr1h_fet], Corner.NE), _far[3]], layer=SIGNAL_INNER)

# FSW east off its pin into the lane and down past the output capacitor's
# ground pad to its resistor; the settings
# to theirs; COMP's capacitor on its
# resistor.
board.track(Net("FSW_SET"), [pin(8), Past([pin(8)], Edge.EAST, across=pin(8)), Past([pad("c_vbus_out", "GND")], Corner.SW),
                             pad("r_fsw", "FSW_SET")], layer=F)
# Each setting's track rises on its riser, so the fan's 45s start level and
# run parallel.
for (part, signal, _), n in zip(SETTINGS[:5], (19, 18, 17, 16, 15)):
    board.track(Net(signal), [esc_settings[n], pad(part, signal)], layer=F)
board.track(Net("BB_FAULT"), [esc_settings[14], pad("r_bb_fault", "BB_FAULT")], layer=F)
board.track(Net("COMP_MID"), [pad("r_comp", "COMP_MID"), pad("c_comp", "COMP_MID")], layer=F)

# --- drops, in the pads ----------------------------------------------------------
# FAULT's pull-up drops to the 3V3 plane in its pad.
_fault_3v3 = board.via(Net("V3V3"), pad("r_bb_fault", "V3V3"), size=VIA, drill=VIA_DRILL)
# AGND: the settings' AGND terminals to an AGND zone on In2 under them (figure
# 10-1 puts AGND on an inner layer); pin 10 reaches it from a via east of
# the pins, between the VOUT and PGND bands.
AGND_PARTS = ["c_vcc_bb", "c_comp", "r_ilim_bb", "r_cdc", "r_mode_bb", "r_agnd"]
_agnd_vias = {p: board.via(Net("AGND"), pad(p, "AGND"), size=VIA, drill=VIA_DRILL) for p in AGND_PARTS}
_agnd = board.via(Net("AGND"), FreeSpot(near=pin(10)), size=VIA, drill=VIA_DRILL)
board.track(Net("AGND"), [pin(10), _agnd], layer=F)
board.track(Net("AGND"), [_agnd, Past([pad("c_vbus_out", "VOUT")], Edge.WEST, across=_agnd),
                          Past([_fault_3v3], Edge.WEST, across=_agnd_vias["r_mode_bb"]), _agnd_vias["r_mode_bb"]],
            layer=SIGNAL_INNER, bend=Bend.END)   # up the lane west of the In2 VOUT area, and west of FAULT's 3V3 drop
board.plane(Net("AGND"), layers=(SIGNAL_INNER,), over=[Part(p) for p in AGND_PARTS + ["r_comp", "r_bb_fault"]])
# FSW's resistor and DITH (pin 7) return to AGND too (UsbConverter.zen item
# 5): a via in the resistor's AGND pad, and In2 tracks from DITH's via and it
# to pin 10's AGND via.
_fsw_agnd = board.via(Net("AGND"), pad("r_fsw", "AGND"), size=VIA, drill=VIA_DRILL)
board.track(Net("AGND"), [_fsw_agnd, _agnd], layer=SIGNAL_INNER)
board.track(Net("AGND"), [_far[7], _fsw_agnd], layer=SIGNAL_INNER)
# GND and V3V3 terminals to their planes.
for part, key in (("c_vbus_in_a", 2), ("c_vbus_in_b", 2), ("c_vbus_out", "GND"), ("r_agnd", "GND"),
                  ("r_vbus_en", "GND"), ("c_vbus_pd", "GND")):
    board.via(Net("GND"), pad(part, key), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), pin(24), size=VIA, drill=VIA_DRILL)   # PGND's thermal via to the ground planes (item 8): the exposed bar takes one
# VBUS leaves for the core from its reservoir's pad.
board.via(Net("VBUS"), pad("c_vbus_pd", "VBUS"), size=VIA, drill=VIA_DRILL)

# --- power copper, after the tracks and vias it goes round -------------------------
# Each pour names the pads it joins; its outline is fitted round every other
# net's clearance (placemat's fitted pour).
# The input bank: VSHUNT over the capacitors' east pads, the drain pad and
# D1's pins. GND is the component face's ground zone, filled round the rest.
pour("VSHUNT", [pad("c_vbus_in_a", 1), pad("c_vbus_in_b", 1), pad("q_buck", 9), pad("q_buck", 2), pad("q_buck", 3), pad("q_buck", 4)])
# SW1: one pour over the half-bridge's switch pad and the inductor's SW1
# terminal under it, grown as wide as its current needs.
board.pour(Net("SW1"), [pad("q_buck", 10), pad("l_vbus", "SW1")], layer=F, swallow_pads=True, reach=Reach.CURRENT)
# SW2: one pour over the inductor's SW2 terminal, c_boot2's SW2 pad, pin 21
# and the exposed SW2 pad (25), fitted past BOOT1's and BOOT2's pins and
# tracks (Ben's drawing, boards/core/hand/usbconverter/vout-shape-2026-10-01.kicad_pcb).
pour("SW2", [pad("c_boot2", "SW2"), pin(25), pin(21), pad("l_vbus", "SW2")])
# VOUT: one pour over the exposed VOUT pad (26), pin 11, the output
# capacitor's VOUT pad and the shunt's, fitted clear of ISP's pin and track
# (Ben's drawing, as above).
pour("VOUT", [pin(26), pin(11), pad("c_vbus_out", "VOUT"), pad("r_vbus_sense", "VOUT")])
# The large VOUT area of 10.1 (UsbConverter.zen item 8): an In2 pour fitted
# over the vias in the output capacitor's and the shunt's VOUT pads, in
# parallel with the pour on the component face. The exposed VOUT pad's one
# via (it takes no more) is a thermal drop: AGND's In2 lane runs between it
# and the area.
board.via(Net("VOUT"), pin(26), size=VIA, drill=VIA_DRILL)
_vout_cap = board.vias(Net("VOUT"), pad("c_vbus_out", "VOUT"), size=VIA, drill=VIA_DRILL)
_vout_shunt = board.vias(Net("VOUT"), pad("r_vbus_sense", "VOUT"), size=VIA, drill=VIA_DRILL)
board.pour(Net("VOUT"), [_vout_cap, _vout_shunt], layer=SIGNAL_INNER, swallow_pads=True,
           why="TPS55288 10.1: the large VOUT area, on In2 under the output's drops")
# VBUS from the shunt's VBUS terminal to its reservoir.
pour("VBUS", [pad("r_vbus_sense", "VBUS"), pad("c_vbus_pd", "VBUS")])

# The ground zones (the component face, In1, In4) and the 3V3 plane (In3),
# as the core has them, bounded to the content so the stamped cell brings no
# copper beyond what it occupies. The component face's ground fills round
# the drawn copper and joins the input bank's, the half-bridge's source, PGND
# and the output capacitor's ground.
frame_planes(FILLET)

