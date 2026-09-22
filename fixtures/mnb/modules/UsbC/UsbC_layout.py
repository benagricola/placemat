"""UsbC: the USB-C device port: the receptacle, a flow-through ESD array,
the CC pulldowns and the VBUS bypass. The MCU's series terminators are
chip-side in the MCU cell, so this cell hands the pair off at the ESD.

The receptacle is turned so its solder tails are on its south and its
mouth overhangs north: the cell's north face is the mating face a board
puts at its edge. Everything else sits south of the connector's pad row:
the ESD centred on the pair with its north pins toward the connector,
the two CC pulldowns flanking it under their own pins, the VBUS bypass
under the ESD on the east pulldown's column so the VBUS path runs
through its pad rather than to a spur. The ESD stands one fan band
below the pad row, the band the pair's descents need to clear the
VBUS pin between them; everything else sits courtyard to courtyard.

The connector interleaves the pair, so exactly one crossing is forced:
the P side hops under the connector body on the back face between two
vias, and the N side stays on the front and joins its two pins with a
bridge north of the pad row. VBUS is sized for the ampere a bench
jumper can draw: two feeds from the two VBUS pads on the back face,
one down the east side past the pulldown's via, one under the signal
columns, both landing on the bypass cap's pad. The nets are split across the ESD
(USB_CONN_* on the connector side, USB_* on the board side) so a router
cannot bypass it. The shield's plated posts are their own plane
landings; the ground pads of the small parts take a via each. The pair
ends at the ESD's south pins and VBUS in the bypass cap's pad: the
board draws from those pads.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Mid, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

J, ESD, R_CC1, R_CC2, C_VBUS = Part("usbc"), Part("usbesd"), Part("r_cc1"), Part("r_cc2"), Part("c_vbus")
VBUS, GND, CC1, CC2 = Net("VBUS"), Net("gnd"), Net("USB_CC1"), Net("USB_CC2")
CONN_P, CONN_N = Net("USB_CONN_P"), Net("USB_CONN_N")
F, B = CopperLayer.F, CopperLayer.B
CLR = board.netclass(CONN_P).clearance
W_PAIR = board.netclass(CONN_P).track_width
W_VBUS = 0.5                        # the VBUS feeds: an ampere over a bench jumper, the widest the corridors allow
ORIGIN = Location(151.542, 126.16)  # the receptacle's origin: a fragment's coordinates are its own
J_ROT = 180.0                       # tails south, mouth north over the board edge


def pad_off(part, key, rotation):
    """A pad's offset from its part's origin once the part is turned."""
    p, o = board.pad(part, key).location, board.part(part).location
    return Transform.rotate(rotation).apply((p.x - o.x, p.y - o.y))


def upright(part, north_net):
    """The rotation that stands a two-pad part on end with `north_net`'s pad north."""
    return 90.0 if pad_off(part, north_net, 90.0)[1] < 0 else -90.0


def pad_size(part, key, rotation):
    """A pad's (width, height) once its part is turned."""
    b = board.pad(part, key).box
    return (b.height, b.width) if rotation % 180 == 90 else (b.width, b.height)


j_claim, esd_claim = board.claim(J, rotation=J_ROT), board.claim(ESD)
r_claim, c_claim = board.claim(R_CC1, rotation=90.0), board.claim(C_VBUS, rotation=90.0)
A5, B5 = PadRef(J, "A5"), PadRef(J, "B5")               # CC1 east, CC2 west once turned
A6, B6, A7, B7 = PadRef(J, "A6"), PadRef(J, "B6"), PadRef(J, "A7"), PadRef(J, "B7")
VW, VE = PadRef(J, "B4A9"), PadRef(J, "A4B9")            # the two VBUS pads, west and east
E1, E3, E4, E5, E6 = PadRef(ESD, 1), PadRef(ESD, 3), PadRef(ESD, 4), PadRef(ESD, 5), PadRef(ESD, 6)
RC1, RC2, CV = PadRef(R_CC1, CC1), PadRef(R_CC2, CC2), PadRef(C_VBUS, VBUS)
_, jpy = pad_off(J, "A6", J_ROT)
_, e6y = pad_off(ESD, 6, 0.0)
pw, ph = pad_size(J, "A6", J_ROT)
ew, eh = pad_size(ESD, 6, 0.0)

# ---------------------------------------------------------------- placement
PITCH = board.pitch(J)                                        # the receptacle's 0.5 mm pin pitch
TURN_DY = ph / 2 + (CLR + W_PAIR / 2) * 2 ** 0.5 - (PITCH - pw / 2)   # a pair descent turns onto its 45 this far below the pad row: the 45 clears the neighbouring pin's pad corner
CC_ROOM = 0.2                                                 # and a little more, so the CC pins' 45s clear both the SBU pads above and the ESD's pins below
FAN_BAND = TURN_DY + (CLR + W_PAIR / 2) * 2 ** 0.5 + eh / 2 + CC_ROOM   # the ESD's north pin row below the pad row: the descents' 45s clear the VBUS pin between them
e4x, _ = pad_off(ESD, 4, 0.0)

board.place(J, at=ORIGIN, rotation=J_ROT, why="the receptacle: mouth north on the mating face, tails south")
board.place(ESD, at=Pin(4, X(J, e4x), Y(A6, FAN_BAND)), rotation=0.0,
            why="the ESD centred on the pair, its north pins one fan band below the pad row")
board.place(R_CC1, at=Pin(CC1, X(ESD, (esd_claim.width + r_claim.width) / 2), Y(E4)), rotation=upright(R_CC1, CC1),
            why="CC1's pulldown east of the ESD, its CC pad on the ESD's north row so the pin's 45 clears the ESD")
board.place(R_CC2, at=Pin(CC2, X(ESD, -(esd_claim.width + r_claim.width) / 2), Y(E4)), rotation=upright(R_CC2, CC2),
            why="CC2's pulldown west of the ESD, its mirror")
board.place(C_VBUS, at=Pin(VBUS, X(R_CC1), Y(E1)), rotation=upright(C_VBUS, VBUS),
            why="the VBUS bypass under the east pulldown, its VBUS pad on the ESD's south row: the path runs through it")

# ---------------------------------------------------------------- copper
rc_w, rc_h = pad_size(R_CC1, GND, upright(R_CC1, CC1))
VIA = 0.6                                                     # the house via's outer diameter
BRIDGE_Y = Y(A6, -ph / 2 - CLR - W_PAIR / 2)                 # the N bridge north of the pad row, under the connector body
HOP_Y = Y(A6, -ph / 2 - CLR - W_PAIR - CLR - VIA / 2)        # the P hop's via north of the bridge
COL_X = X(RC1, rc_w / 2 + CLR + W_VBUS / 2)                  # the east VBUS column, past the pulldown's pads
ARM_X = X(PadRef(R_CC2, GND), VIA / 2 + CLR + W_VBUS / 2)    # the back-face arm, past the west pulldown's ground via
e5x, _ = pad_off(ESD, 5, 0.0)
WEST_DROP = (VIA / 2 + CLR + W_VBUS / 2) * 2 ** 0.5 - (e4x - e5x) + CLR / 2     # the west feed drops this far on the back before its 45: clear of the pin-4 via beside it

board.track(CC1, [RC1, A5], layer=F, why="CC1's pin drops onto its pulldown with one 45")
board.track(CC2, [RC2, B5], layer=F, why="CC2's, the mirror")
board.track(CONN_N, [A7, (X(A7), BRIDGE_Y), (X(B7), BRIDGE_Y), B7], layer=F, chamfer=0.05,
            why="the N pins bridged north of the pad row, in the band the receptacle exposes under its body")
e6x, _ = pad_off(ESD, 6, 0.0)
a7x, _ = pad_off(J, "A7", J_ROT)
a6x, _ = pad_off(J, "A6", J_ROT)
board.track(CONN_N, [A7, (X(A7), Y(A7, TURN_DY)), (X(E6), Y(A7, TURN_DY + (a7x - e6x))), E6], layer=F,
            why="A7 south on its axis past its neighbours' pads, one 45 onto the ESD's pin 6 column, down it into the pad")
board.track(CONN_P, [B6, (X(B6), HOP_Y)], layer=F, why="B6 north to its hop via")
board.via(CONN_P, (X(B6), HOP_Y))
board.track(CONN_P, [(X(B6), HOP_Y), E4], layer=B, why="the hop on the back face, south-east onto the ESD's pin 4")
board.via(CONN_P, E4, why="back to the front in the pin's own pad")
board.track(CONN_P, [A6, (X(A6), Y(A6, TURN_DY)), (X(E4), Y(A6, TURN_DY + (e4x - a6x))), E4], layer=F,
            why="A6 south on its axis, one 45 onto the same pin's column, down it into the pad")
COL_B = X(PadRef(R_CC1, GND), VIA / 2 + CLR + W_VBUS / 2)    # the east feed's column on the back, past the east pulldown's ground via
board.track(VBUS, [VE, (COL_B, Y(RC1)), (COL_B, Y(CV)), CV], layer=B, width=W_VBUS,
            why="the east feed on the back face: off the east VBUS pad, down past the pulldown's via, into the bypass's pad; the front has no room between the shield finger and the pulldown")
board.track(VBUS, [VW, (ARM_X, Y(E5)), E5], layer=B, width=W_VBUS,
            why="the west VBUS pad's share under the signal columns on the back face, into the clamp pin")
board.track(VBUS, [E5, (X(E5), Y(E5, WEST_DROP)), CV], layer=B, width=W_VBUS,
            why="and on under the ESD, one 45 into the bypass's pad")
board.via(VBUS, VE)
board.via(VBUS, VW)
board.via(VBUS, E5)
board.via(VBUS, CV, why="the bypass's pad: where both feeds meet and the board picks VBUS up")

board.via(GND, PadRef(C_VBUS, GND))
board.via(GND, PadRef(ESD, GND))
board.via(GND, PadRef(R_CC1, GND))
board.via(GND, PadRef(R_CC2, GND))

board.faces(outward=Edge.NORTH, handoff=Edge.SOUTH, why="the mouth faces the board edge; the pair and VBUS leave south")
