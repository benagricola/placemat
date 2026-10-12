"""Backlight: the PT4115 LED driver and its switching loop.

A fragment, stamped onto the core as the cell `backlight`. The layout follows
the PT4115 datasheet's layout considerations (PT4115_DS Rev EN_2.9, p14): the
coil and the input capacitor close to the pins, the sense resistor straight
across VIN and CSN with no other current in those tracks, and the Schottky
diode's current kept out of the track between the sense resistor and VIN.

Pins, from docs/decisions/schematics/core-netlist.xml: SW 1, GND 2, DIM 3, CSN 4, VIN 5. The
LED string (the panel's backlight, through the FFC) returns on BL_LEDK to the
coil's far end.

Turned 180 degrees, the driver has SW and DIM on its west side and VIN and
CSN on its east, its ground tab reaching east between VIN and CSN.

Ben packed the cell by hand on 2026-09-27; the script states that layout's
relationships (not its coordinates), and every net is a pour over pads that
stand next to each other:

- The sense resistor stands upright a silk gap east of the driver, VSHUNT
  level with VIN and VLED south.
- The diode lies north, a silk gap above the driver and a silk gap east of
  the coil, its anode west toward SW; the input capacitor lies a silk gap
  east of it on the same row, VSHUNT west against the diode's cathode.
- The coil lies a silk gap west of the driver, its SW end level with SW; its
  far end is the BL_LEDK handoff. DIM's pull-down lies west of DIM, under the
  coil.
- SW is one pour over the coil's SW end, SW and the diode's anode. VSHUNT is
  two: the diode's cathode and the input capacitor's pad, coming down onto
  the sense resistor's VSHUNT end from the north; and VIN's own leg into
  that end, a silk gap under the first, so the diode's current stays out of
  the copper between VIN and the sense resistor. VLED joins CSN to the
  sense resistor's other end, and BL_PWM DIM to its pull-down.

The PT4115 cannot run from 5 V (6 V minimum); its replacement is an open
parts decision (docs/decisions/schematics/approval-decisions-2026-09-26.md), and this
layout is redone with the replacement.
Routing evidence: docs/decisions/layout/backlight-module-routing-2026-09-26.md.
"""
from placemat import board, LinkWeight, Net, PadRef, Part, X, Y

from fragment_frame import Content, drawn_from_pad, frame_planes, placed_size, pour, pour_box, shifted

VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
CLEAR = board.netclass(Net("GND")).clearance
VIA_PITCH = VIA + CLEAR
GAP = 0.2                     # the board's silk-to-silk clearance (board_rules.zen)
FILLET = 0.15                 # the ground zone's corner radius
SWITCH_NODE_LIMIT = 3.0       # the switch node is the loop that radiates
DECOUPLING_LIMIT = 4.0        # the input capacitor beyond the sense resistor, which sits at VIN
KELVIN_LIMIT = 3.0            # the sense resistor across VIN and CSN, nothing between
DRIVER_ROTATION = 180         # SW and DIM west, VIN and CSN east
SW_PIN, TAB, DIM_PIN, CSN_PIN, VIN_PIN = 1, 2, 3, 4, 5
UP_PAD1_NORTH, LYING_FLIPPED = 270, 180

board.rect(fit=True)   # the frame is the content plus the keep-in
g = Content("bl", DRIVER_ROTATION)
g.place(why="the driver at the frame's origin; the rest from its pads")


def env(part, pad, rot):
    return drawn_from_pad(part, pad, rot)


def gx(part, pad):
    return g.pad(part, pad)[0]


def gy(part, pad):
    return g.pad(part, pad)[1]


def put(part, pad, x, y, rot, ref_part, ref_pad, why):
    """Place `part` with `pad` at (x, y) in the driver's coordinates, said as an
    offset from a pad already placed."""
    g.beside(part, pad, ref_part, ref_pad, x - gx(ref_part, ref_pad), y - gy(ref_part, ref_pad), rot, why)


CHIP = env("bl", VIN_PIN, DRIVER_ROTATION)
_chip_east, _chip_west = gx("bl", VIN_PIN) + CHIP[2], gx("bl", VIN_PIN) + CHIP[0]
RS = env("r_bl_sense", "VSHUNT", UP_PAD1_NORTH)
put("r_bl_sense", "VSHUNT", _chip_east + GAP - RS[0], gy("bl", VIN_PIN), UP_PAD1_NORTH, "bl", VIN_PIN,
    "the sense resistor a silk gap east of the driver, VSHUNT level with VIN")
CO = env("l_bl", "SW_BL", 0)
put("l_bl", "SW_BL", _chip_west - GAP - CO[2], gy("bl", SW_PIN), 0, "bl", SW_PIN,
    "the coil a silk gap west of the driver, its SW end level with SW")
DK = env("d_bl", "VSHUNT", LYING_FLIPPED)
DA = env("d_bl", "SW_BL", LYING_FLIPPED)
_chip_north = gy("bl", VIN_PIN) + CHIP[1]
_coil_east = gx("l_bl", "SW_BL") + CO[2]
put("d_bl", "SW_BL", _coil_east + GAP - DA[0], min(gy("r_bl_sense", "VSHUNT") + RS[1], _chip_north) - GAP - DA[3],
    LYING_FLIPPED, "l_bl", "SW_BL", "the diode north of the driver, a silk gap east of the coil, its anode west")
CI = env("c_bl_in", "VSHUNT", 0)
put("c_bl_in", "VSHUNT", gx("d_bl", "VSHUNT") + DK[2] + GAP - CI[0], gy("d_bl", "VSHUNT"), 0, "d_bl", "VSHUNT",
    "the input capacitor a silk gap east of the diode on its row, VSHUNT west")
RD = env("r_bl_dim", "BL_PWM", LYING_FLIPPED)
put("r_bl_dim", "BL_PWM", _chip_west - GAP - RD[2], gy("bl", DIM_PIN), LYING_FLIPPED, "bl", DIM_PIN,
    "DIM's pull-down west of DIM, under the coil")
board.link(PadRef(Part("l_bl"), "SW_BL"), PadRef(Part("bl"), "SW_BL"),
           weight=LinkWeight.SHORT, limit_mm=SWITCH_NODE_LIMIT, why="the driver's own switch node")
board.link(PadRef(Part("d_bl"), "SW_BL"), PadRef(Part("bl"), "SW_BL"),
           weight=LinkWeight.SHORT, limit_mm=SWITCH_NODE_LIMIT, why="the catch diode on the switch node")
board.link(PadRef(Part("r_bl_sense"), "VSHUNT"), PadRef(Part("bl"), "VSHUNT"),
           weight=LinkWeight.SHORT, limit_mm=KELVIN_LIMIT, why="the sense resistor's VIN end straight to VIN")
board.link(PadRef(Part("c_bl_in"), "VSHUNT"), PadRef(Part("bl"), "VSHUNT"),
           weight=LinkWeight.SHORT, limit_mm=DECOUPLING_LIMIT, why="the input capacitor at VIN, past the sense resistor")

frame_planes(FILLET, supply=None)
board.free_net(Net("VSHUNT"))


def pad(part, key):
    return PadRef(Part(part), key)


def west(part, key, rot):
    return X(pad(part, key), -placed_size(part, key, rot)[0] / 2.0)


def east(part, key, rot):
    return X(pad(part, key), placed_size(part, key, rot)[0] / 2.0)


def north(part, key, rot):
    return Y(pad(part, key), -placed_size(part, key, rot)[1] / 2.0)


def south(part, key, rot):
    return Y(pad(part, key), placed_size(part, key, rot)[1] / 2.0)


# SW: the coil's SW end, SW and the diode's anode, one pour.
pour("SW_BL", [(X(pad("l_bl", "SW_BL")), north("d_bl", "SW_BL", LYING_FLIPPED), 1, 1),
               (east("d_bl", "SW_BL", LYING_FLIPPED), north("d_bl", "SW_BL", LYING_FLIPPED), -1, 1),
               (east("d_bl", "SW_BL", LYING_FLIPPED), north("bl", SW_PIN, DRIVER_ROTATION), -1, 1),
               (east("bl", SW_PIN, DRIVER_ROTATION), north("bl", SW_PIN, DRIVER_ROTATION), -1, 1),
               (east("bl", SW_PIN, DRIVER_ROTATION), south("bl", SW_PIN, DRIVER_ROTATION), -1, -1),
               (X(pad("l_bl", "SW_BL")), south("bl", SW_PIN, DRIVER_ROTATION), 1, -1)], FILLET)
# VSHUNT: the diode's cathode and the input capacitor's pad, down onto the
# sense resistor's VSHUNT end from the north, a silk gap clear of VIN's leg.
_vin_top = north("bl", VIN_PIN, DRIVER_ROTATION)
pour("VSHUNT", [(west("d_bl", "VSHUNT", LYING_FLIPPED), north("c_bl_in", "VSHUNT", 0), 1, 1),
                (east("r_bl_sense", "VSHUNT", UP_PAD1_NORTH), north("c_bl_in", "VSHUNT", 0), -1, 1),
                (east("r_bl_sense", "VSHUNT", UP_PAD1_NORTH), Y(pad("r_bl_sense", "VSHUNT")), -1, -1),
                (west("r_bl_sense", "VSHUNT", UP_PAD1_NORTH), Y(pad("r_bl_sense", "VSHUNT")), 1, -1),
                (west("r_bl_sense", "VSHUNT", UP_PAD1_NORTH), shifted(_vin_top, -GAP), 1, -1),
                (west("d_bl", "VSHUNT", LYING_FLIPPED), shifted(_vin_top, -GAP), 1, -1)], FILLET)
# VIN's own leg into the sense resistor's VSHUNT end.
pour_box("VSHUNT", west("bl", VIN_PIN, DRIVER_ROTATION), _vin_top, X(pad("r_bl_sense", "VSHUNT")),
         south("bl", VIN_PIN, DRIVER_ROTATION), FILLET)
# VLED: CSN east and up onto the sense resistor's VLED end.
pour("VLED", [(west("bl", CSN_PIN, DRIVER_ROTATION), north("bl", CSN_PIN, DRIVER_ROTATION), 1, 1),
              (west("r_bl_sense", "VLED", UP_PAD1_NORTH), north("bl", CSN_PIN, DRIVER_ROTATION), 1, 1),
              (west("r_bl_sense", "VLED", UP_PAD1_NORTH), north("r_bl_sense", "VLED", UP_PAD1_NORTH), 1, 1),
              (east("r_bl_sense", "VLED", UP_PAD1_NORTH), north("r_bl_sense", "VLED", UP_PAD1_NORTH), -1, 1),
              (east("r_bl_sense", "VLED", UP_PAD1_NORTH), south("bl", CSN_PIN, DRIVER_ROTATION), -1, -1),
              (west("bl", CSN_PIN, DRIVER_ROTATION), south("bl", CSN_PIN, DRIVER_ROTATION), 1, -1)], FILLET)
# BL_PWM: DIM west to its pull-down.
pour_box("BL_PWM", west("r_bl_dim", "BL_PWM", LYING_FLIPPED), north("bl", DIM_PIN, DRIVER_ROTATION),
         east("bl", DIM_PIN, DRIVER_ROTATION), south("bl", DIM_PIN, DRIVER_ROTATION), FILLET)
# Ground: the tab's via array (datasheet: the ground pin soldered to the
# plane), the input capacitor's and the pull-down's drops.
board.vias(Net("GND"), PadRef(Part("bl"), TAB), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
board.vias(Net("GND"), PadRef(Part("c_bl_in"), "GND"), pitch=VIA_PITCH, size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), pad("r_bl_dim", "GND"), size=VIA, drill=VIA_DRILL)
