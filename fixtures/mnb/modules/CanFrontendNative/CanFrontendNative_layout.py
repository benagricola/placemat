"""CanFrontendNative: the MCP2542 transceiver front end for a native FDCAN
host. One chain west to east: transceiver, common-mode choke, split
termination, ESD at the bus edge, with the CAN-TERM header tucked under
the ESD's flank. The transceiver's digital side faces west toward the
MCU and its CAN side east toward the bus.

The two supply caps stand side by side west of the transceiver on the
midline, v5 pads south and ground pads north, each plane-fed by a via
in the pad, the nearer one's v5 pad reaching the VDD pin; the VIO cap
lies under the VIO pin with its v3v3 pad on the pin's axis. The bus
rails run dead straight at the choke's own pad pitch from the choke
east: term_ra stands with its CAN_P pad on the CAN_P rail, term_rb
across the CAN_N rail with its TERM_MID pad on term_ra's, the term cap
in the channel between the rails, the ESD's pads on the rails' line and
the header's CAN_N pad riding one 45 into the ESD pad. The DNF signal
integrity caps lie beside the choke's bus pads. Everything sits
courtyard to courtyard.

Nets that leave the cell end at their pads: txd and rxd at the
transceiver, CAN_P and CAN_N at the ESD and header. gnd, v5 and v3v3
are the rails the module owns and take vias to the board's planes; the
transceiver's exposed pad carries the ground via and the board's fill
joins the ground pins to it.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

XCVR, CHOKE, ESD, JUMPER = Part("xcvr"), Part("choke"), Part("esd"), Part("term_jumper")
R_A, R_B, C_TERM = Part("term_ra"), Part("term_rb"), Part("term_cap")
C_1U, C_100N, C_VIO = Part("vdd_1u"), Part("vdd_100n"), Part("vio_100n")
C_SI_P, C_SI_N = Part("si_can_p"), Part("si_can_n")
V5, V3V3, GND = Net("v5"), Net("v3v3"), Net("gnd")
CAN_P, CAN_N, TX_P, TX_N = Net("CAN_P"), Net("CAN_N"), Net("CAN_TX_P"), Net("CAN_TX_N")
TERM_MID, TERM_JLEG = Net("TERM_MID"), Net("TERM_JLEG")
F = CopperLayer.F

ORIGIN = Location(150.12, 100.0)    # the transceiver's origin: a fragment's coordinates are its own
XCVR_ROT = 270.0                    # digital pins west, CAN pins east
ESD_ROT = 180.0                     # the ESD's line pads west on the rails, ground east


def pad_off(part, key, rotation):
    """A pad's offset from its part's origin once the part is turned."""
    p, o = board.pad(part, key).location, board.part(part).location
    return Transform.rotate(rotation).apply((p.x - o.x, p.y - o.y))


def upright(part, north_net):
    """The rotation that stands a two-pad part on end with `north_net`'s pad north."""
    return 90.0 if pad_off(part, north_net, 90.0)[1] < 0 else -90.0


def flat(part, east_net):
    """The rotation that lays a two-pad part along a row with `east_net`'s pad east."""
    return 0.0 if pad_off(part, east_net, 0.0)[0] > 0 else 180.0


xcvr_claim, choke_claim, esd_claim = board.claim(XCVR, rotation=XCVR_ROT), board.claim(CHOKE), board.claim(ESD, rotation=ESD_ROT)
cap_claim = board.claim(C_100N, rotation=90.0)
vio_claim = board.claim(C_VIO)
si_claim = board.claim(C_SI_P)
ra_claim, rb_claim, ct_claim, jp_claim = board.claim(R_A, rotation=90.0), board.claim(R_B, rotation=90.0), board.claim(C_TERM), board.claim(JUMPER)
pin_v5, pin_vio = PadRef(XCVR, V5), PadRef(XCVR, V3V3)
lp_p, lp_n = PadRef(CHOKE, CAN_P), PadRef(CHOKE, CAN_N)
_, vio_dy = pad_off(XCVR, V3V3, XCVR_ROT)
lp_dx, _ = pad_off(CHOKE, CAN_N, 0.0)

# ---------------------------------------------------------------- the chain on the midline
board.place(XCVR, at=ORIGIN, rotation=XCVR_ROT, why="digital side west to the MCU, CAN side east to the bus")
board.place(C_100N, at=Centre(X(XCVR, -(xcvr_claim.width + cap_claim.width) / 2), Y(XCVR)), rotation=upright(C_100N, GND),
            why="the HF supply cap standing against the transceiver, v5 pad south to the VDD pin, ground north")
board.place(C_1U, at=Centre(X(C_100N, -cap_claim.width), Y(XCVR)), rotation=upright(C_1U, GND),
            why="the bulk cap beside it, the same way up")
board.place(C_VIO, at=Pin(V3V3, X(pin_vio), Y(pin_vio, (xcvr_claim.bottom - vio_dy) + vio_claim.height / 2)), rotation=flat(C_VIO, V3V3),
            why="the VIO cap lying under the VIO pin, its v3v3 pad on the pin's axis")
board.place(CHOKE, at=Centre(X(XCVR, (xcvr_claim.width + choke_claim.width) / 2), Y(XCVR)), rotation=0.0,
            why="the choke against the transceiver: TX pair in west, bus pair out east")
board.place(C_SI_P, at=Centre(X(lp_p), Y(CHOKE, choke_claim.top - si_claim.height / 2)), rotation=flat(C_SI_P, CAN_P),
            why="the DNF CAN_P cap lying over the choke's CAN_P pad, CAN pad inboard")
board.place(C_SI_N, at=Centre(X(lp_n), Y(CHOKE, choke_claim.bottom + si_claim.height / 2)), rotation=flat(C_SI_N, CAN_N),
            why="the DNF CAN_N cap under the choke's CAN_N pad")
RB_X = max(choke_claim.right, lp_dx + si_claim.width / 2) + rb_claim.width / 2   # term_rb against the choke, or the DNF cap lying past it
RA_X = RB_X + (rb_claim.width + ra_claim.width) / 2                # term_ra against it
board.place(R_A, at=Pin(CAN_P, X(CHOKE, RA_X), Y(lp_p)), rotation=upright(R_A, CAN_P),
            why="term_ra standing with its CAN_P pad on the CAN_P rail")
board.place(R_B, at=Pin(TERM_MID, X(CHOKE, RB_X), Y(PadRef(R_A, TERM_MID))), rotation=upright(R_B, TERM_MID),
            why="term_rb across the CAN_N rail, its TERM_MID pad on term_ra's")
board.place(C_TERM, at=Centre(X(R_A, (ra_claim.width + ct_claim.width) / 2), Y(CHOKE)), rotation=flat(C_TERM, GND),
            why="the term cap in the channel between the rails, TERM_MID pad west")
board.place(ESD, at=Centre(X(C_TERM, (ct_claim.width + esd_claim.width) / 2), Y(CHOKE)), rotation=ESD_ROT,
            why="the ESD at the bus edge, its line pads on the rails' line, ground outboard")
board.place(JUMPER, at=Centre(X(R_B, (rb_claim.width + jp_claim.width) / 2), Y(R_A, (ra_claim.height + jp_claim.height) / 2)),
            rotation=flat(JUMPER, CAN_N), why="the CAN-TERM header under the termination, TERM_JLEG pad west")

# ---------------------------------------------------------------- copper
board.track(TX_P, [PadRef(XCVR, TX_P), PadRef(CHOKE, TX_P)], layer=F, why="off the pin, one 45, into the choke pad")
board.track(TX_N, [PadRef(XCVR, TX_N), PadRef(CHOKE, TX_N)], layer=F)
board.track(CAN_P, [lp_p, PadRef(ESD, CAN_P)], layer=F, why="the CAN_P rail, straight through term_ra's pad, one 45 into the ESD")
board.track(CAN_N, [lp_n, PadRef(ESD, CAN_N)], layer=F, why="the CAN_N rail")
board.track(CAN_N, [PadRef(JUMPER, CAN_N), PadRef(ESD, CAN_N)], layer=F, why="the header's CAN_N pad up into the ESD pad")
board.track(CAN_P, [lp_p, PadRef(C_SI_P, CAN_P)], layer=F, why="the DNF cap's tap")
board.track(CAN_N, [lp_n, PadRef(C_SI_N, CAN_N)], layer=F)
board.track(TERM_MID, [PadRef(R_B, TERM_MID), PadRef(R_A, TERM_MID), PadRef(C_TERM, TERM_MID)], layer=F,
            why="the split node along the inner pads into the cap")
board.track(TERM_JLEG, [PadRef(R_B, TERM_JLEG), PadRef(JUMPER, TERM_JLEG)], layer=F)
board.track(V5, [PadRef(C_1U, V5), PadRef(C_100N, V5), pin_v5], layer=F, why="the supply along the caps' v5 pads into the VDD pin")
board.track(V3V3, [pin_vio, PadRef(C_VIO, V3V3)], layer=F, why="straight down the VIO pin's axis")

board.via(GND, PadRef(XCVR, 9), why="the exposed pad: the board's fill joins the ground pins to it")
board.via(GND, PadRef(C_1U, GND))
board.via(GND, PadRef(C_100N, GND))
board.via(GND, PadRef(C_VIO, GND))
board.via(GND, PadRef(C_SI_P, GND))
board.via(GND, PadRef(C_SI_N, GND))
board.via(GND, PadRef(C_TERM, GND))
board.via(GND, PadRef(ESD, GND))
board.via(V5, PadRef(C_1U, V5), why="each supply cap fed from the plane in its own pad")
board.via(V5, PadRef(C_100N, V5))
board.via(V3V3, PadRef(C_VIO, V3V3))

board.faces(handoff=Edge.WEST, outward=Edge.EAST, why="txd and rxd leave west to the MCU; the bus side faces the connector")
