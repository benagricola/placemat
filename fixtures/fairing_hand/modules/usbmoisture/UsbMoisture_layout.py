"""Protected SBU moisture probes following TPS25751 Figure 9-9.

A low-current cell for the sealed side of the USB port. Keep the protected
sense nodes short and separate from converter switching nodes.
Verification: ../../../../docs/decisions/layout/moisture-module-routing-2026-09-26.md

The TPD6S300 stands at the frame's origin, its protected SBU pins (LD1 pin
15, LD2 pin 14) on its north row and its connector-side SBU pins on its
south row. North of it, one row of four resistors stands close to the
chip, west to east LD1's pull-down (1M), pull-up (100k), LD2's pull-up,
pull-down, each with its LD pad south toward the chip; a second row of
their four transistors stands further north, west to east the west NMOS,
the two PMOS (their shared V3V3 source pads levelling their gates
too, the same part turned the same way), the east NMOS, each with its
drain south into the resistor below it. Both rows space by their own
envelope gap - the tool's, not a hand-picked pitch. EXCITE is the four
gates' row, joined in one chain (a waypoint clear of each PMOS's own
source pad) to its 100k bias (r_excitation), east of the east NMOS. The PD
LDO rail itself (vias in the PMOS sources, the bias and the protector's
VPWR bypass) runs on the inner layer. VPWR's capacitor stands upright on
its pin's row; VBIAS's lies under its pin.
"""
from placemat import board, Beside, CopperLayer, Edge, Facing, FreeSpot, LinkWeight, Net, PadRef, Part, Past, Location

from fragment_frame import frame_planes, inner_layers

SIGNAL_INNER, _ = inner_layers()   # the core's signal layer, In2

VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
FILLET = 0.15                 # the ground zone's corner radius
BYPASS_LIMIT = 2.0            # local bypass at the protection IC
LD1_PIN, LD2_PIN, GND_NORTH_PIN, VPWR_PIN, SBU2_PIN, VBIAS_PIN, EP_PIN = 15, 14, 13, 10, 2, 3, 21
GND_WEST_PIN = 18
DRAIN_PIN = 3                 # the drain, on both the PMOS and the NMOS footprint
# Turns (a two-pad part lies along x as generated, pad 1 west).
UP_PAD1_NORTH, UP_PAD1_SOUTH, LYING, LYING_FLIPPED = 270, 90, 0, 180


def pin(n):
    return PadRef(Part("protect"), n)


def pad(part, net):
    return PadRef(Part(part), net)


def via_in(part, net):
    """A plane or layer drop in the pad, filled and capped."""
    board.via(Net(net), pad(part, net), size=VIA, drill=VIA_DRILL)



board.rect(fit=True)   # the frame is the content plus the keep-in
board.place(Part("protect"), at=Location(0, 0), rotation=0, why="the protector at the frame's origin")

# VPWR's and VBIAS's bypasses, upright and lying on their own pins' rows.
board.place(Part("c_supply"), at=Beside(Part("protect"), Edge.EAST, align=PadRef(Part("protect"), VPWR_PIN)),
            rotation=UP_PAD1_NORTH, why="VPWR's bypass upright on its pin's row")
board.place(Part("c_bias"), at=Beside(Part("protect"), Edge.SOUTH, align=PadRef(Part("protect"), VBIAS_PIN)),
            rotation=LYING, why="VBIAS's bypass lying under its pin, ground east")
board.link(pad("c_supply", "V3V3"), pin(VPWR_PIN), weight=LinkWeight.SHORT,
           limit_mm=BYPASS_LIMIT, why="local bypass at the protection IC")
board.link(pad("c_bias", "SBU_BIAS"), pin(VBIAS_PIN), weight=LinkWeight.SHORT,
           limit_mm=BYPASS_LIMIT, why="local bypass at the protection IC")

# The four resistors, in one row on the chip's north side, close to the LD
# pins: the row's own envelope gap spaces them (the tool's, not a
# hand-picked pitch), west to east LD1's pull-down, pull-up, LD2's pull-up,
# pull-down. Each stands with its transistor-side pad north, its LD pad
# south, toward the chip.
board.row([Part("r_down1"), Part("r_up1"), Part("r_up2"), Part("r_down2")], Edge.NORTH, of=Part("protect"),
          centre=PadRef(Part("protect"), LD1_PIN),
          rotation=[UP_PAD1_SOUTH, UP_PAD1_NORTH, UP_PAD1_NORTH, UP_PAD1_SOUTH])

# The four transistors, in their own row further north (off the west pull-up,
# which is the resistor row's own reference so the transistor row clears the
# whole resistor row, not just the chip): west to east the west NMOS, the
# two PMOS (their shared V3V3 source row levelling their gates too,
# the same part turned the same way), the east NMOS. Each faces its drain
# south, into its own resistor.
board.row([Part("q_n1"), Part("q_p1"), Part("q_p2"), Part("q_n2")], Edge.NORTH, of=Part("r_up1"),
          centre=PadRef(Part("r_up1"), "PULL1"),
          rotation=Facing(DRAIN_PIN, Edge.SOUTH))

# EXCITE's bias, east of the east NMOS, on its gate's axis.
board.place(Part("r_excitation"), at=Beside(Part("q_n2"), Edge.EAST, align=PadRef(Part("q_n2"), "EXCITE")),
            rotation=LYING_FLIPPED, why="EXCITE's bias, east of the east NMOS, the rail pad east")

frame_planes(FILLET, supply=None)   # no 3V3 in this cell
board.free_net(Net("V3V3"))
board.faces(outward=Edge.SOUTH, quiet=Edge.NORTH,
            why="connector SBU terminals outward, protected probes inward")


# --- copper -------------------------------------------------------------------
# The probe nodes: each LD pin runs to its pull-up, which joins its pull-down.
for ld_pin, up, down, net in ((LD1_PIN, "r_up1", "r_down1", "LD1"), (LD2_PIN, "r_up2", "r_down2", "LD2")):
    board.track(Net(net), [pin(ld_pin), pad(up, net)], layer=CopperLayer.F)
    board.track(Net(net), [pad(up, net), pad(down, net)], layer=CopperLayer.F)
# Each resistor to the drain over it.
for res, q, net in (("r_up1", "q_p1", "PULL1"), ("r_up2", "q_p2", "PULL2"),
                    ("r_down1", "q_n1", "DOWN1"), ("r_down2", "q_n2", "DOWN2")):
    board.track(Net(net), [pad(res, net), pad(q, net)], layer=CopperLayer.F)

# EXCITE: the four gates, west to east, and the bias resistor, one chain,
# a waypoint clear of each PMOS's own source pad on its gate's near side
# (the row puts the source between the previous gate and this one).
board.track(Net("EXCITE"), [pad("q_n1", "EXCITE"), Past([pad("q_p1", "V3V3")], Edge.NORTH),
                            pad("q_p1", "EXCITE"), Past([pad("q_p2", "V3V3")], Edge.NORTH),
                            pad("q_p2", "EXCITE"), pad("q_n2", "EXCITE"), pad("r_excitation", "EXCITE")],
            layer=CopperLayer.F)
for q in ("q_n1", "q_n2"):
    board.via(Net("GND"), FreeSpot(near=pad(q, "GND")), size=VIA, drill=VIA_DRILL)

# The PD LDO rail on the inner layer: vias in the PMOS sources' pads, the
# bias's and the VPWR bypass's, one chain joining them.
for part in ("q_p1", "q_p2", "r_excitation", "c_supply"):
    via_in(part, "V3V3")
board.track(Net("V3V3"), [pad("q_p1", "V3V3"), pad("q_p2", "V3V3"),
                                pad("r_excitation", "V3V3"), pad("c_supply", "V3V3")],
            layer=SIGNAL_INNER)
board.track(Net("V3V3"), [pin(VPWR_PIN), pad("c_supply", "V3V3")], layer=CopperLayer.F)

# VBIAS straight down into its capacitor: its pad already stands on the
# pin's axis (Beside's align), so no waypoint is needed.
board.track(Net("SBU_BIAS"), [pin(VBIAS_PIN), pad("c_bias", "SBU_BIAS")], layer=CopperLayer.F)

# Ground: the bypasses drop in their pads, the exposed pad at its centre; the
# north row's ground pin (walled in by LD2's lane) and the west one join the
# exposed pad.
via_in("c_supply", "GND")
via_in("c_bias", "GND")
board.via(Net("GND"), pin(EP_PIN), size=VIA, drill=VIA_DRILL)
board.track(Net("GND"), [pin(GND_NORTH_PIN), pin(EP_PIN)], layer=CopperLayer.F)
board.track(Net("GND"), [pin(GND_WEST_PIN), pin(EP_PIN)], layer=CopperLayer.F)
