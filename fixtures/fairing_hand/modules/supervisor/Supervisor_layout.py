"""Supervisor: the always-on regulator, the MSPM0L1106 on it and their parts.

A fragment, stamped onto the core's front face as the cell `supervisor`. The
MSPM0L1106 (VQFN-24) stands at the frame's origin; each part stands a band
(one escape track and its clearances) outside its pin sides, by the pin it
serves:

- West (pins 1-6): VDD's 100 nF level with VDD, V_AON east (TI SLASEX5C
  9.1.1); NRST's 47k stacked north of it, its V_AON pad over the 100 nF's;
  NRST's 10 nF north of the 47k, its NRST pad over the 47k's. One V_AON
  pour joins VDD's pin, the 100 nF's and the 47k's V_AON pads; one SUP_NRST
  pour joins the 47k's and the 10 nF's NRST pads, and NRST (pin 2) runs up
  the band a clearance off the pin ends and over the 10 nF into its pad.
- South-west: the enable FET upright, gate east on a lane held off
  VPROT_IN's pad (clear for the gate's own track); the EN pull-up south of
  it, level with its drain, and the gate's pull-down south of that, level
  with the pull-up.
- North (pins 19-24, where VCORE and PA25 sit): VCORE's 470 nF over pin 23;
  the sense filter and the divider's two legs in a row east of it. One
  VIN_SENSE pour joins the three parts' VIN_SENSE pads and PA25 (pin 21).
- PA2 (pin 5) escapes to a via beside its pin. SCL and SDA are the core's
  to route, restated from the pads.
- East (pins 14-18): PA18's pull-down level with pin 14.
- South (pins 7-13, unconnected): the TPS7B6933, centred under the chip;
  its input 1 uF west and output 10 uF east, each joined to its pin by a
  pour. V_AON runs under the regulator's body to In2 and up to the 100 nF's
  pad; VBIKE runs on In2 from the EN pull-up round the regulator's south
  side and up the east side to the divider's upper leg.

Every ground drop is a via in its pad; VSS and the exposed pad take their
own since the west column's own parts wall VSS off from the F.Cu plane.

VBIKE (R6) shows as crossing REV_EN (U3) in the pre-route ratsnest, as it
did in the hand layout.
Evidence: ../../../../docs/decisions/layout/supervisor-module-layout-2026-09-29.md.
"""
from placemat import Along, Beside, CopperLayer, Corner, Edge, Facing, FreeSpot, Location, Mid, Net, PadRef, Part, Past, board

from fragment_frame import frame_planes, inner_layers

VIA, VIA_DRILL = 0.45, 0.20   # the core's via
FILLET = 0.15                 # the frame plane's corner radius (frame_planes)
CLEAR = board.netclass(Net("V_AON")).clearance
TRACK = board.netclass(Net("V_AON")).track_width
BAND = TRACK + 2.0 * CLEAR    # round the chip's pin sides: one escape track and its clearances
SIGNAL_INNER, _ = inner_layers()   # its signals on In2

SCL_PIN, NRST_PIN, VDD_PIN, VSS_PIN, SHDN_PIN, EN_GATE_PIN, BSL_PIN, SENSE_PIN, VCORE_PIN, SDA_PIN, EP = \
    1, 2, 3, 4, 5, 6, 14, 21, 23, 24, 25
LDO_ROTATION = 180            # IN and OUT north, IN west
Q_ROTATION = 90               # the FET upright, gate and source north, drain south


def pad(part, key):
    return PadRef(Part(part), key)


def mcu(n):
    return pad("mcu", n)


def lying(part, east):
    """The turn that lays a two-pad part with pad `east` east."""
    return Facing(pad(part, east), Edge.EAST)


def up(part, south):
    """The turn that stands a two-pad part with pad `south` south."""
    return Facing(pad(part, south), Edge.SOUTH)


board.rect(fit=True)   # the frame is the content plus the keep-in
board.place(Part("mcu"), at=Location(0, 0), rotation=0, why="the supervisor at the frame's origin; the rest from its pads")

# --- west: VDD's bypass, NRST's divider ---------------------------------------
R_SUP = lying("c_sup", "V_AON")
board.place(Part("c_sup"), at=Beside(Part("mcu"), Edge.WEST, align=mcu(VDD_PIN), gap=BAND), rotation=R_SUP,
            why="VDD's 100 nF level with VDD, V_AON east")
R_RN = lying("r_nrst", "V_AON")
board.place(Part("r_nrst"), at=Beside(Part("c_sup"), Edge.NORTH, align=pad("c_sup", "V_AON")), rotation=R_RN,
            why="NRST's 47k north of the 100 nF, its V_AON pad over the 100 nF's")
R_CN = lying("c_nrst", "GND")
board.place(Part("c_nrst"), at=Beside(Part("r_nrst"), Edge.NORTH, align=pad("r_nrst", "SUP_NRST")), rotation=R_CN,
            why="NRST's 10 nF north of the 47k, its NRST pad over the 47k's")

# --- south-west: the enable FET and its two resistors -------------------------
# The gate stands on a lane held off the input capacitor's pad (below), clear
# for the gate's own track; the pull-down and the pull-up continue south of
# it, each level with the pad above.
board.place(Part("q_en"), at=Beside(Part("c_sup"), Edge.SOUTH,
                                    align=("REV_EN_GATE", Past([pad("c_aon_in", "VPROT_IN")], Edge.WEST, lane=Net("REV_EN_GATE")))),
            rotation=Q_ROTATION, why="the enable FET south of the 100 nF, gate on a lane west of the input capacitor")
R_EP = lying("r_en_pull", "REV_EN")
board.place(Part("r_en_pull"), at=Beside(Part("q_en"), Edge.SOUTH, align=("REV_EN", pad("q_en", "REV_EN"))),
            rotation=R_EP, why="EN's pull-up south of the FET, level with its drain, REV_EN east")
R_EG = lying("r_en_gate", "REV_EN_GATE")
board.place(Part("r_en_gate"), at=Beside(Part("r_en_pull"), Edge.SOUTH, align=("REV_EN_GATE", pad("r_en_pull", "REV_EN"))),
            rotation=R_EG, why="the gate's pull-down south of the pull-up, level with it")

# --- south: the always-on regulator, centred under the chip -------------------
board.place(Part("ldo_aon"), at=Beside(Part("mcu"), Edge.SOUTH, align=Along.MID, gap=BAND), rotation=LDO_ROTATION,
            why="the regulator centred under the chip, where its pins are unconnected")
R_AO = up("c_aon_out", "GND")
board.place(Part("c_aon_out"), at=Beside(Part("ldo_aon"), Edge.EAST, align=pad("ldo_aon", "V_AON")), rotation=R_AO,
            why="the output's 10 uF east, V_AON level with OUT")
R_AI = up("c_aon_in", "GND")
board.place(Part("c_aon_in"), at=Beside(Part("ldo_aon"), Edge.WEST, align=pad("ldo_aon", "VPROT_IN")), rotation=R_AI,
            why="the input's 1 uF west, VPROT_IN level with IN")

# --- north: VCORE's bypass, the sense filter and divider ----------------------
R_VC = up("c_vcore", "SUP_VCORE")
board.place(Part("c_vcore"), at=Beside(Part("mcu"), Edge.NORTH, align=mcu(VCORE_PIN), gap=BAND), rotation=R_VC,
            why="VCORE's 470 nF over its pin")
R_CS = up("c_sense", "VIN_SENSE")
board.place(Part("c_sense"), at=Beside(Part("c_vcore"), Edge.EAST, align=("VIN_SENSE", pad("c_vcore", "SUP_VCORE"))),
            rotation=R_CS, why="the sense filter east of VCORE's, level with it")
R_SB = up("r_sense_bot", "VIN_SENSE")
board.place(Part("r_sense_bot"), at=Beside(Part("c_sense"), Edge.EAST, align=pad("c_sense", "VIN_SENSE")), rotation=R_SB,
            why="the divider's lower leg east of the filter, level with it")
R_ST = up("r_sense_top", "VIN_SENSE")
board.place(Part("r_sense_top"), at=Beside(Part("r_sense_bot"), Edge.EAST, align=pad("r_sense_bot", "VIN_SENSE")),
            rotation=R_ST, why="the divider's upper leg east of the lower, level with it")

# --- east: PA18's pull-down -----------------------------------------------------
R_BSL = up("r_bsl", "SUP_BSL")
board.place(Part("r_bsl"), at=Beside(Part("mcu"), Edge.EAST, align=mcu(BSL_PIN), gap=BAND), rotation=R_BSL,
            why="PA18's pull-down east of its pin, level with it")

frame_planes(FILLET, supply=None)   # the cell's rail is its own V_AON


# --- copper -------------------------------------------------------------------
F = CopperLayer.F


def via_in(part, key, net):
    return board.via(Net(net), pad(part, key), size=VIA, drill=VIA_DRILL)


# V_AON: pin 3, the 100 nF's and the 47k's V_AON pads, one pour.
board.pour(Net("V_AON"), [mcu(VDD_PIN), pad("c_sup", "V_AON")], layer=F, swallow_pads=True)
board.track(Net("V_AON"), [pad("c_sup", "V_AON"), pad("r_nrst", "V_AON")], layer=F)
# NRST: the 47k's and the 10 nF's NRST pads, one pour; pin 2 runs up the
# band a clearance off the pin ends, past the 10 nF's north-east corner and
# over it into its NRST pad, clear of the V_AON link between the columns.
board.pour(Net("SUP_NRST"), [pad("r_nrst", "SUP_NRST"), pad("c_nrst", "SUP_NRST")], layer=F, swallow_pads=True)
_c_nrst = [pad("c_nrst", "GND"), pad("c_nrst", "SUP_NRST")]
board.track(Net("SUP_NRST"),
            [mcu(NRST_PIN), Past([mcu(NRST_PIN)], Edge.WEST, across=mcu(NRST_PIN)), Past(_c_nrst, Corner.NE),
             Past(_c_nrst, Edge.NORTH, across=pad("c_nrst", "SUP_NRST")), pad("c_nrst", "SUP_NRST")], layer=F)

# VIN_SENSE: one pour over the three sense pads and PA25.
board.pour(Net("VIN_SENSE"),
           [mcu(SENSE_PIN), pad("c_sense", "VIN_SENSE"), pad("r_sense_bot", "VIN_SENSE"), pad("r_sense_top", "VIN_SENSE")],
           layer=F, swallow_pads=True)
board.track(Net("SUP_VCORE"), [mcu(VCORE_PIN), pad("c_vcore", "SUP_VCORE")], layer=F)
board.track(Net("SUP_BSL"), [mcu(BSL_PIN), pad("r_bsl", "SUP_BSL")], layer=F)

# The regulator's pins to their capacitors, a pour each.
board.pour(Net("VPROT_IN"), [pad("c_aon_in", "VPROT_IN"), pad("ldo_aon", "VPROT_IN")], layer=F, swallow_pads=True)
board.pour(Net("V_AON"), [pad("ldo_aon", "V_AON"), pad("c_aon_out", "V_AON")], layer=F, swallow_pads=True)
# V_AON under the regulator's body to In2 and up to the 100 nF's pad.
_aon_via = board.via(Net("V_AON"), Mid(pad("ldo_aon", "VPROT_IN"), pad("ldo_aon", "V_AON")), size=VIA, drill=VIA_DRILL)
board.track(Net("V_AON"), [_aon_via, pad("ldo_aon", "V_AON")], layer=F)
board.via(Net("V_AON"), pad("c_sup", "V_AON"), size=VIA, drill=VIA_DRILL)
board.track(Net("V_AON"), [pad("c_sup", "V_AON"), _aon_via], layer=SIGNAL_INNER)

# Ground and VBIKE drops in the south-west column, placed before its
# tracks so they route clear of the vias. VSS is walled in by the west
# column's own parts, so it takes its own via rather than relying on the
# F.Cu plane to reach it.
_gnd = {part: via_in(part, "GND", "GND")
        for part in ("c_sup", "c_vcore", "c_nrst", "c_sense", "r_sense_bot", "r_en_gate", "r_bsl", "c_aon_out", "c_aon_in")}
via_in("q_en", "GND", "GND")
board.via(Net("GND"), at=FreeSpot(near=mcu(VSS_PIN)), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), mcu(EP), size=VIA, drill=VIA_DRILL)
_vbike_a = board.via(Net("VBIKE"), pad("r_en_pull", "VBIKE"), size=VIA, drill=VIA_DRILL)
_vbike_b = board.via(Net("VBIKE"), pad("r_sense_top", "VBIKE"), size=VIA, drill=VIA_DRILL)

# PA3 into the gate, on to the gate's pull-down; the drain to the pull-up.
board.track(Net("REV_EN_GATE"), [mcu(EN_GATE_PIN), pad("q_en", "REV_EN_GATE"), pad("r_en_gate", "REV_EN_GATE")], layer=F)
board.track(Net("REV_EN"), [pad("q_en", "REV_EN"), pad("r_en_pull", "REV_EN")], layer=F)

# VBIKE on In2, from the EN pull-up round the regulator's south side and up
# the cell's east side to the divider's upper leg, so it never meets V_AON's
# run from the 100 nF down to the regulator.
_regulator_row = [pad("c_aon_in", "GND"), pad("ldo_aon", 3), pad("ldo_aon", 4), pad("c_aon_out", "GND")]
board.track(Net("VBIKE"), [_vbike_a, Past(_regulator_row, Edge.SOUTH), Past(_regulator_row + [_gnd["c_aon_out"]], Corner.SE),
                           Past([pad("c_aon_out", "GND"), pad("c_aon_out", "V_AON")], Edge.EAST),
                           Past([pad("r_bsl", "GND"), pad("r_bsl", "SUP_BSL")], Edge.EAST), _vbike_b], layer=SIGNAL_INNER)

# PA2 escapes to a via beside its pin for the core; SCL and SDA are the
# core's to route from their pins.
board.via(Net("EFUSE_SHDN"), at=FreeSpot(near=mcu(SHDN_PIN)), size=VIA, drill=VIA_DRILL)
