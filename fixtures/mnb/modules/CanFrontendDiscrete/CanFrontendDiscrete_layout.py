"""CanFrontendDiscrete: the MCP2518FD controller and MCP2542 transceiver
CAN-FD front end, in two rows. The south row is the bus cell, the
CanFrontendNative idiom: the transceiver's supply caps standing west of
it on the midline, the VIO cap under its VIO pin, the choke against it,
straight bus rails at the choke's pad pitch, the split termination
standing on the rails, the term cap in the channel between them, the
ESD at the bus edge and the CAN-TERM header under the termination. The
north row, west to east: the CAN-MODE header centred over the
transceiver so its always-populated column lands above the
transceiver's digital pads, the crystal hard against the controller's
oscillator pins with its load caps beside it, and the controller turned
so its CAN column faces the header and its host column faces east, its
two VDD caps lying at its north-east corner with their v3v3 pads on the
VDD pin's row. Everything sits courtyard to courtyard.

The controller's TXCAN and RXCAN ride two lanes across the north band
into the header's controller column; the transceiver's TXD climbs its
pin's axis into the header's middle column and its RXD, the crossing
net, drops to a via under its pin and climbs on the back face. Nets
that leave the cell end at their pads: the host's CAN pair at the
header's third column, the SPI nets at the controller, int_pin at its
escape via. gnd, v5 and v3v3 are the rails the module owns and take
vias; each IC's ground pins rely on the board's fill to reach the
exposed pad's vias.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Mid, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

CTRL, XCVR, XTAL, CHOKE, ESD = Part("ctrl"), Part("xcvr"), Part("xtal"), Part("choke"), Part("esd")
H_MODE, H_TERM, R_A, R_B, C_TERM = Part("mode_jumper"), Part("term_jumper"), Part("term_ra"), Part("term_rb"), Part("term_cap")
C_SI_P, C_SI_N, C_O1, C_O2 = Part("si_can_p"), Part("si_can_n"), Part("osc1_cap"), Part("osc2_cap")
C_X1U, C_X100, C_XVIO, C_C1U, C_C100 = Part("xcvr_vdd_1u"), Part("xcvr_vdd_100n"), Part("xcvr_vio_100n"), Part("ctrl_vdd_1u"), Part("ctrl_vdd_100n")
V5, V3V3, GND, INT = Net("v5"), Net("v3v3"), Net("gnd"), Net("int_pin")
CAN_P, CAN_N, TX_P, TX_N = Net("CAN_P"), Net("CAN_N"), Net("CAN_TX_P"), Net("CAN_TX_N")
TERM_MID, TERM_JLEG = Net("TERM_MID"), Net("TERM_JLEG")
CTRL_TX, CTRL_RX, XCVR_TXD, XCVR_RXD = Net("CTRL_TXCAN"), Net("CTRL_RXCAN"), Net("XCVR_TXD"), Net("XCVR_RXD")
OSC1, OSC2 = Net("OSC1"), Net("OSC2")
F, B = CopperLayer.F, CopperLayer.B
W = board.netclass(CAN_P).track_width
CLR = board.netclass(CAN_P).clearance
VIA = 0.6                           # the house via's outer diameter
ORIGIN = Location(152.0, 100.0)     # the transceiver's origin: a fragment's coordinates are its own
XCVR_ROT, CTRL_ROT, XTAL_ROT, ESD_ROT, MODE_ROT = 270.0, 270.0, 270.0, 180.0, 180.0


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


def pad_size(part, key, rotation):
    """A pad's (width, height) once its part is turned."""
    b = board.pad(part, key).box
    return (b.height, b.width) if rotation % 180 == 90 else (b.width, b.height)


xcvr_claim, ctrl_claim, xtal_claim = board.claim(XCVR, rotation=XCVR_ROT), board.claim(CTRL, rotation=CTRL_ROT), board.claim(XTAL, rotation=XTAL_ROT)
choke_claim, esd_claim, mode_claim, term_claim = board.claim(CHOKE), board.claim(ESD, rotation=ESD_ROT), board.claim(H_MODE, rotation=MODE_ROT), board.claim(H_TERM)
cap_up, cap_flat = board.claim(C_X100, rotation=90.0), board.claim(C_X100)
si_claim = board.claim(C_SI_P)
ra_claim, rb_claim, ct_claim = board.claim(R_A, rotation=90.0), board.claim(R_B, rotation=90.0), board.claim(C_TERM)
pin_v5, pin_vio, pin_txd, pin_rxd = PadRef(XCVR, V5), PadRef(XCVR, V3V3), PadRef(XCVR, XCVR_TXD), PadRef(XCVR, XCVR_RXD)
lp_p, lp_n = PadRef(CHOKE, CAN_P), PadRef(CHOKE, CAN_N)
lp_dx, _ = pad_off(CHOKE, CAN_N, 0.0)
_, vio_dy = pad_off(XCVR, V3V3, XCVR_ROT)
cvio_rot = upright(C_XVIO, V3V3)
_, cvio_dy = pad_off(C_XVIO, V3V3, cvio_rot)
x_o1, x_o2 = PadRef(XTAL, OSC1), PadRef(XTAL, OSC2)
u_tx, u_rx, u_o1, u_o2, u_int, u_vdd = (PadRef(CTRL, CTRL_TX), PadRef(CTRL, CTRL_RX), PadRef(CTRL, OSC1), PadRef(CTRL, OSC2),
                                        PadRef(CTRL, INT), PadRef(CTRL, V3V3))
h_ctx, h_crx, h_xtx, h_xrx = PadRef(H_MODE, CTRL_TX), PadRef(H_MODE, CTRL_RX), PadRef(H_MODE, XCVR_TXD), PadRef(H_MODE, XCVR_RXD)

# ---------------------------------------------------------------- the south row: the bus cell
board.place(XCVR, at=ORIGIN, rotation=XCVR_ROT, why="digital side west under the mode header, CAN side east to the bus")
board.place(C_X100, at=Centre(X(XCVR, -(xcvr_claim.width + cap_up.width) / 2), Y(XCVR)), rotation=upright(C_X100, GND),
            why="the HF supply cap standing against the transceiver, v5 south to the VDD pin, ground north")
board.place(C_X1U, at=Centre(X(C_X100, -cap_up.width), Y(XCVR)), rotation=upright(C_X1U, GND), why="the bulk cap beside it")
board.place(C_XVIO, at=Pin(V3V3, X(pin_vio), Y(pin_vio, (xcvr_claim.bottom - vio_dy) - cap_up.top + cvio_dy)), rotation=cvio_rot,
            why="the VIO cap standing under the VIO pin on its axis, v3v3 pad up")
board.place(CHOKE, at=Centre(X(XCVR, (xcvr_claim.width + choke_claim.width) / 2), Y(XCVR)), rotation=0.0,
            why="the choke against the transceiver: TX pair in west, bus pair out east")
board.place(C_SI_P, at=Centre(X(lp_p), Y(CHOKE, choke_claim.top - si_claim.height / 2)), rotation=flat(C_SI_P, CAN_P),
            why="the DNF CAN_P cap lying over the choke's CAN_P pad")
RB_X = choke_claim.right + rb_claim.width / 2
RA_X = RB_X + (rb_claim.width + ra_claim.width) / 2
board.place(R_A, at=Pin(CAN_P, X(CHOKE, RA_X), Y(lp_p)), rotation=upright(R_A, CAN_P), why="term_ra standing with its CAN_P pad on the CAN_P rail")
board.place(R_B, at=Pin(TERM_MID, X(CHOKE, RB_X), Y(PadRef(R_A, TERM_MID))), rotation=upright(R_B, TERM_MID),
            why="term_rb across the CAN_N rail, its TERM_MID pad on term_ra's")
rbj_w, _ = pad_size(R_B, TERM_JLEG, upright(R_B, TERM_MID))
board.place(C_SI_N, at=Pin(CAN_N, X(PadRef(R_B, TERM_JLEG), -(rbj_w / 2 + CLR + W / 2)), Y(R_B, (rb_claim.height + si_claim.height) / 2)),
            rotation=flat(C_SI_N, GND), why="the DNF CAN_N cap lying under term_rb, its CAN_N pad west of term_rb's pad so the tap off the rail clears it")
board.place(C_TERM, at=Centre(X(R_A, (ra_claim.width + ct_claim.width) / 2), Y(CHOKE)), rotation=flat(C_TERM, GND),
            why="the term cap in the channel between the rails, TERM_MID pad west")
board.place(ESD, at=Centre(X(C_TERM, (ct_claim.width + esd_claim.width) / 2), Y(CHOKE)), rotation=ESD_ROT,
            why="the ESD at the bus edge, line pads on the rails' line, ground outboard")
board.place(H_TERM, at=Centre(X(R_B, (rb_claim.width + term_claim.width) / 2), Y(R_A, (ra_claim.height + term_claim.height) / 2)),
            rotation=flat(H_TERM, CAN_N), why="the CAN-TERM header under the termination beside term_rb, TERM_JLEG pad west")

# ---------------------------------------------------------------- the north row: the mode header, the crystal, the controller
lp_px, lp_py = pad_off(CHOKE, CAN_P, 0.0)
ra_rot = upright(R_A, CAN_P)
_, ra_pad_dy = pad_off(R_A, CAN_P, ra_rot)
CHOKE_X = (xcvr_claim.width + choke_claim.width) / 2                                  # the choke's centre from the transceiver's
CTRL_X = max(mode_claim.right + cap_up.width + xtal_claim.width + (CLR + W + CLR) + (VIA + CLR), CHOKE_X + lp_px + si_claim.width / 2) + ctrl_claim.width / 2   # east of the crystal cell and its channel, and of the DNF cap over the choke
board.place(H_MODE, at=Centre(X(XCVR), Y(CHOKE, choke_claim.top - mode_claim.height / 2)), rotation=MODE_ROT,
            why="the CAN-MODE header over the transceiver, clear of the choke: the controller column east, the transceiver column centre, the host column west")
board.place(CTRL, at=Centre(X(XCVR, CTRL_X), Y(PadRef(R_A, CAN_P), -ra_pad_dy + ra_claim.top - ctrl_claim.height / 2)), rotation=CTRL_ROT,
            why="the controller east of the crystal cell, over the termination: CAN column west toward the header, host column east")
CHANNEL = (CLR + W + CLR) + (VIA + CLR)                      # between the crystal and the controller: OSC2's descent and int_pin's escape via
board.place(XTAL, at=Centre(X(CTRL, -(ctrl_claim.width / 2 + CHANNEL + xtal_claim.width / 2)), Y(CTRL)), rotation=XTAL_ROT,
            why="the crystal a channel west of the controller's oscillator pins: OSC1 on its south-east pad nearest the OSC1 pin")
board.place(C_O2, at=Pin(OSC2, X(XTAL, -(xtal_claim.width + cap_up.width) / 2), Y(x_o2)), rotation=upright(C_O2, OSC2),
            why="the OSC2 load cap standing west of the crystal, its OSC2 pad on the crystal's north-west pad row")
board.place(C_O1, at=Centre(X(C_SI_P, -(si_claim.width + cap_flat.width) / 2), Y(C_SI_P)), rotation=flat(C_O1, OSC1),
            why="the OSC1 load cap lying over the choke beside the DNF cap, OSC1 pad east under the OSC1 lane")
u_vdd_x, u_vdd_y = pad_off(CTRL, V3V3, CTRL_ROT)
c100_rot, c1u_rot = flat(C_C100, GND), flat(C_C1U, GND)
c100_vx, _ = pad_off(C_C100, V3V3, c100_rot)
board.place(C_C100, at=Pin(V3V3, X(u_vdd, (ctrl_claim.right - u_vdd_x) - cap_flat.left + c100_vx), Y(u_vdd)), rotation=c100_rot,
            why="the controller's HF cap lying at its north-east corner, v3v3 pad on the VDD pin's row")
board.place(C_C1U, at=Centre(X(C_C100), Y(C_C100, -cap_flat.height)), rotation=c1u_rot, why="the bulk cap stacked above it")

# ---------------------------------------------------------------- copper: the bus cell
board.track(TX_P, [PadRef(XCVR, TX_P), PadRef(CHOKE, TX_P)], layer=F)
board.track(TX_N, [PadRef(XCVR, TX_N), PadRef(CHOKE, TX_N)], layer=F)
board.track(CAN_P, [lp_p, PadRef(ESD, CAN_P)], layer=F, why="the CAN_P rail, straight through term_ra's pad")
board.track(CAN_N, [lp_n, PadRef(ESD, CAN_N)], layer=F, why="the CAN_N rail")
board.track(CAN_N, [PadRef(H_TERM, CAN_N), PadRef(ESD, CAN_N)], layer=F, why="the header's CAN_N pad up into the ESD pad")
board.track(CAN_P, [lp_p, PadRef(C_SI_P, CAN_P)], layer=F)
board.track(CAN_N, [(X(PadRef(C_SI_N, CAN_N)), Y(lp_n)), PadRef(C_SI_N, CAN_N)], layer=F, why="the DNF cap tapped off the rail on its pad's axis")
board.track(TERM_MID, [PadRef(R_B, TERM_MID), PadRef(R_A, TERM_MID), PadRef(C_TERM, TERM_MID)], layer=F)
board.track(TERM_JLEG, [PadRef(R_B, TERM_JLEG), PadRef(H_TERM, TERM_JLEG)], layer=F)
board.track(V5, [PadRef(C_X1U, V5), PadRef(C_X100, V5), pin_v5], layer=F, why="the supply along the caps' v5 pads into the VDD pin")
board.track(V3V3, [pin_vio, PadRef(C_XVIO, V3V3)], layer=F, why="straight down the VIO pin's axis")

# ---------------------------------------------------------------- copper: the mode header and the north band
board.track(XCVR_TXD, [pin_txd, h_xtx], layer=F,
            why="TXD up its pin's axis, one 45 into the header's transceiver column")
RXD_DROP = VIA / 2 + CLR + W / 2 + 0.3                      # the RXD via under its pin, clear of the pin row
board.track(XCVR_RXD, [pin_rxd, (X(pin_rxd), Y(pin_rxd, RXD_DROP))], layer=F, why="RXD, the crossing net, drops to a via under its pin")
board.via(XCVR_RXD, (X(pin_rxd), Y(pin_rxd, RXD_DROP)))
rxd_gap = X(Mid(h_xrx, PadRef(H_MODE, Net("mcu_can_rx"))))   # the barrel gap between the transceiver and host columns
board.track(XCVR_RXD, [(X(pin_rxd), Y(pin_rxd, RXD_DROP)), (rxd_gap, Y(pin_rxd)), (rxd_gap, Y(h_xrx, term_claim.height / 2)), h_xrx], layer=B,
            why="and climbs the gap between the header's columns on the back face into the transceiver column's pad")
board.via(XCVR_RXD, h_xrx, why="a through hole is its own layer change")
xg_w, xg_h = pad_size(XTAL, 4, XTAL_ROT)
_, xg_dy = pad_off(XTAL, 4, XTAL_ROT)
OSC_CORRIDOR = xg_dy - xg_h / 2 - CLR - W / 2                 # OSC2's run over the crystal's north edge, clear of its north-east ground pad
LANE_RX = OSC_CORRIDOR - W - CLR                              # the north band's inner lane, above it
LANE_TX = LANE_RX - W - CLR                                   # the outer lane
gap_x = X(Mid(h_ctx, h_xtx))                                  # the barrel gap between the header's controller and transceiver columns
board.track(CTRL_TX, [u_tx, (X(CTRL, -(ctrl_claim.width / 2 + CHANNEL)), Y(XTAL, LANE_TX)), (gap_x, Y(XTAL, LANE_TX)), (gap_x, Y(h_ctx)), h_ctx], layer=F, chamfer=0.4,
            why="TXCAN west off its pin, along the band's outer lane, down the gap between the header's columns, into its pad from the west; short 45s, the gap is one pad wide")
board.track(CTRL_RX, [u_rx, (X(CTRL, -(ctrl_claim.width / 2 + CHANNEL) + W + CLR), Y(XTAL, LANE_RX)), (X(h_crx, term_claim.height / 2), Y(XTAL, LANE_RX)), h_crx], layer=F,
            why="RXCAN on the lane beside it, into the column's other pad from the east: the two never share an x")
board.track(OSC1, [x_o1, u_o1], layer=F, why="OSC1 east off the crystal's pad, one 45 onto the pin's row")
board.track(OSC1, [PadRef(C_O1, OSC1), x_o1], layer=F, why="the load cap up into that pad")
board.track(OSC2, [PadRef(C_O2, OSC2), x_o2], layer=F, why="the OSC2 load cap straight east into the crystal's pad")
board.track(OSC2, [x_o2, (X(x_o2), Y(XTAL, OSC_CORRIDOR)), (X(XTAL, xtal_claim.right + CLR + W / 2), Y(XTAL, OSC_CORRIDOR)),
                   (X(XTAL, xtal_claim.right + CLR + W / 2), Y(u_o2)), u_o2], layer=F, chamfer=0.3,
            why="OSC2 over the crystal's north edge, down the channel between crystal and controller, into the pin; a short 45 at the corner, the escape via sits beside it")
INT_X = xtal_claim.right + (CLR + W + CLR) + VIA / 2          # the escape via beside OSC2's descent in the channel
board.track(INT, [u_int, (X(XTAL, INT_X), Y(u_int))], layer=F, why="int_pin west to its escape via in the channel")
board.via(INT, (X(XTAL, INT_X), Y(u_int)))
board.track(V3V3, [u_vdd, PadRef(C_C100, V3V3)], layer=F, why="the controller's VDD straight east into the HF cap")
board.track(V3V3, [PadRef(C_C1U, V3V3), PadRef(C_C100, V3V3)], layer=F, why="the bulk cap's v3v3 pad down onto it")

# ---------------------------------------------------------------- vias: the rails the module owns
board.via(GND, PadRef(XCVR, 9), why="the transceiver's exposed pad")
board.via(GND, PadRef(CTRL, 15), why="the controller's exposed pad, centre")
ep_w, ep_h = pad_size(CTRL, 15, CTRL_ROT)
board.via(GND, (X(PadRef(CTRL, 15)), Y(PadRef(CTRL, 15), -(ep_h / 2 - VIA / 2 - CLR))), why="and near each end")
board.via(GND, (X(PadRef(CTRL, 15)), Y(PadRef(CTRL, 15), ep_h / 2 - VIA / 2 - CLR)))
for part in (C_SI_N, C_SI_P, C_TERM, C_X1U, C_X100, C_XVIO, ESD, C_O1, C_O2, C_C1U, C_C100):
    board.via(GND, PadRef(part, GND))
board.via(GND, PadRef(XTAL, 2))
board.via(GND, PadRef(XTAL, 4))
board.via(V5, PadRef(C_X1U, V5))
board.via(V5, PadRef(C_X100, V5))
board.via(V3V3, PadRef(C_XVIO, V3V3))
board.via(V3V3, PadRef(C_C1U, V3V3))
board.via(V3V3, PadRef(C_C100, V3V3))

board.faces(handoff=Edge.WEST, outward=Edge.EAST, why="the host's CAN pair and SPI leave west and east of the north row; the bus side faces the connector")
