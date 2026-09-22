"""PermitReceiver: the opto-isolated PERMIT channel receiver. The same SOP-4
opto and isolation barrier as OptoSense, with a bleed resistor across the
raw field pins, an emitter output (active high), a channel-energized LED
in the anode chain and a pluggable header-and-shunt bypass.

The chain stands on the opto's midline, west to east: the field bleed,
the two series resistors, the reverse clamp, the LED, then the opto, all
courtyards touching, so the band is the same height as OptoSense's and a
board can stamp opto inputs and PERMIT channels in one row pitch. The
field pair leaves at the bleed's pads on the west. East of the opto the
bypass header lies on the collector's row with its v3v3 pad toward the
opto, and the output pull-down tucks under the header beside the opto's
emitter pin. The clamp is anti-parallel with the LED and the opto's LED
in series, so its cathode taps the anode chain and its anode taps the
field return. The opto's collector rail and the pull-down's ground take
a via each; out ends at the header's pad for the board.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

R_BLEED, R_A, R_B, D_REV, LED, OPTO, JUMPER, R_PD = (Part("rbleed_field"), Part("rser_a"), Part("rser_b"), Part("dprot"),
                                                    Part("led_act"), Part("opto"), Part("bypass_jumper"), Part("rpd_out"))
PERM_P, PERM_N, V3V3, GND, OUT = Net("perm_p"), Net("perm_n"), Net("v3v3"), Net("gnd"), Net("out")
R_MID, AN, OPTO_AN = Net("PERMIT_RMID"), Net("PERMIT_AN"), Net("PERMIT_OPTO_AN")
F = CopperLayer.F
W = board.netclass(AN).track_width
CLR = board.netclass(AN).clearance
ORIGIN = Location(26.29, 22.0)      # the opto's origin: a fragment's coordinates are its own


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


opto_claim, jp_claim = board.claim(OPTO), board.claim(JUMPER)
rb_claim, r_claim, d_claim, led_claim, pd_claim = (board.claim(R_BLEED, rotation=90.0), board.claim(R_A, rotation=90.0),
                                                   board.claim(D_REV, rotation=90.0), board.claim(LED, rotation=90.0), board.claim(R_PD))
u_an, u_cat, u_col, u_em = PadRef(OPTO, OPTO_AN), PadRef(OPTO, PERM_N), PadRef(OPTO, V3V3), PadRef(OPTO, OUT)
d_k, d_a = PadRef(D_REV, AN), PadRef(D_REV, PERM_N)
jp_v3v3, jp_out = PadRef(JUMPER, V3V3), PadRef(JUMPER, OUT)

# ---------------------------------------------------------------- the chain on the midline, west of the opto
board.place(OPTO, at=ORIGIN, rotation=0.0, why="the opto: LED side west, transistor side east, the barrier under its body")
board.place(LED, at=Centre(X(OPTO, -(opto_claim.width + led_claim.width) / 2), Y(OPTO)), rotation=upright(LED, AN),
            why="the indicator LED against the opto, anode north on the chain, cathode south toward the opto's anode pin")
board.place(D_REV, at=Centre(X(LED, -(led_claim.width + d_claim.width) / 2), Y(OPTO)), rotation=upright(D_REV, AN),
            why="the reverse clamp beside it, cathode north on the anode chain, anode south on the field return")
board.place(R_B, at=Centre(X(D_REV, -(d_claim.width + r_claim.width) / 2), Y(OPTO)), rotation=upright(R_B, AN),
            why="the second series resistor, anode-chain pad north, midpoint south")
board.place(R_A, at=Centre(X(R_B, -r_claim.width), Y(OPTO)), rotation=upright(R_A, PERM_P),
            why="the first, field pad north, midpoint south to meet the second's")
board.place(R_BLEED, at=Centre(X(R_A, -(r_claim.width + rb_claim.width) / 2), Y(OPTO)), rotation=upright(R_BLEED, PERM_P),
            why="the field bleed at the west end across the raw pair: the module's entry point")
board.place(JUMPER, at=Pin(V3V3, X(OPTO, (opto_claim.width + jp_claim.width) / 2 + 0.0), Y(u_col)), rotation=flat(JUMPER, OUT),
            why="the bypass header east of the opto on the collector's row, v3v3 pad toward the opto")
board.place(R_PD, at=Centre(X(JUMPER), Y(JUMPER, (jp_claim.height + pd_claim.height) / 2)), rotation=flat(R_PD, GND),
            why="the output pull-down under the header, out pad west toward the emitter")

# ---------------------------------------------------------------- copper
SOUTH = Y(OPTO, opto_claim.bottom + CLR + W / 2)              # the field return's corridor under the chain
board.track(PERM_P, [PadRef(R_BLEED, PERM_P), PadRef(R_A, PERM_P)], layer=F, why="the field's positive along the north pads")
board.track(PERM_N, [PadRef(R_BLEED, PERM_N), (X(R_BLEED, 0.0), SOUTH), (X(d_a), SOUTH), d_a], layer=F,
            why="the field return down into the corridor under the chain, along it, up into the clamp's anode")
board.track(PERM_N, [d_a, (X(d_a), SOUTH), (X(u_cat, -(0.0)), SOUTH), u_cat], layer=F,
            why="and on under the LED into the opto's cathode")
board.track(R_MID, [PadRef(R_A, R_MID), PadRef(R_B, R_MID)], layer=F)
board.track(AN, [PadRef(R_B, AN), d_k, PadRef(LED, AN)], layer=F, why="the anode chain along the north pads")
board.track(OPTO_AN, [PadRef(LED, OPTO_AN), u_an], layer=F, why="the LED's cathode east on one 45 up into the opto's anode")
board.track(V3V3, [u_col, jp_v3v3], layer=F, why="the collector straight into the header's v3v3 pad")
board.track(OUT, [u_em, PadRef(R_PD, OUT)], layer=F, why="the emitter into the pull-down")
board.track(OUT, [PadRef(R_PD, OUT), jp_out], layer=F, why="and up into the header's out pad")

board.via(V3V3, u_col, why="the collector's rail")
board.via(GND, PadRef(R_PD, GND), why="the pull-down's ground")

board.faces(handoff=Edge.EAST, why="out leaves at the header east; the field pair leaves at the bleed's pads west")
