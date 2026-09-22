"""OptoSense: a 24 V opto-isolated input: one SOP-4 opto, per-input NPN/PNP
polarity select on two 2 mm header-and-shunt sites, a series activity
LED. The two headers are one stacked block, same x, one shunt's grip
apart, so the NPN column (pin 1, west, the square pad) and the PNP
column (pin 3, east) line up: both shunts left is NPN, both right is
PNP, one visual, with the knockout labels over the columns. The chain
stands on the band between the headers' commons: the reverse clamp
diode, the two series resistors, the LED, then the opto and the bleed
resistor, courtyards touching. The opto's LED-side and transistor-side
pad columns face a copper-free gap under its body: the isolation
barrier is a property of the opto alone.

Only an_src takes the corridor between the headers; cat leaves its
common south and runs east in the corridor under the chain to the
clamp's anode and the opto's cathode, so neither common crosses the
other's throws. The field pair leaves at the headers' throw pads on
the west; v24 and gnd are throw pads too, open until a shunt bridges
them, and through holes are their own plane landings. The module's
own rails, the opto emitter's ground and the bleed's 3V3, take a via
each; out ends at the bleed's pad for the board.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Mid, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

H_AN, H_CAT, D_PROT, R_A, R_B, LED, OPTO, R_BLEED = (Part("jp_an"), Part("jp_cat"), Part("dprot"), Part("rser_a"),
                                                    Part("rser_b"), Part("led_act"), Part("opto"), Part("rbleed"))
V24, IN_P, IN_N, V3V3, GND, OUT = Net("v24"), Net("in_p"), Net("in_n"), Net("v3v3"), Net("gnd"), Net("out")
AN_SRC, R_MID, LED_A, AN, CAT = Net("OPTO_ANSRC"), Net("OPTO_RMID"), Net("OPTO_LEDA"), Net("OPTO_AN"), Net("OPTO_CAT")
F = CopperLayer.F
W = board.netclass(AN).track_width
CLR = board.netclass(AN).clearance
ORIGIN = Location(5.25, 20.7)       # the NPN/PNP header's origin: a fragment's coordinates are its own
SHUNT_GRIP = 0.35                   # between the two headers' courtyards: room for fingers on two fitted shunts
LABEL_SIZE = 0.8                    # the smallest KiCad's text_height rule allows: two words in the header's width


def pad_off(part, key, rotation):
    """A pad's offset from its part's origin once the part is turned."""
    p, o = board.pad(part, key).location, board.part(part).location
    return Transform.rotate(rotation).apply((p.x - o.x, p.y - o.y))


def upright(part, north_net):
    """The rotation that stands a two-pad part on end with `north_net`'s pad north."""
    return 90.0 if pad_off(part, north_net, 90.0)[1] < 0 else -90.0


h_claim, opto_claim = board.claim(H_AN), board.claim(OPTO)
d_claim, r_claim, led_claim, rb_claim = (board.claim(D_PROT, rotation=90.0), board.claim(R_A, rotation=90.0),
                                         board.claim(LED, rotation=90.0), board.claim(R_BLEED, rotation=90.0))
an_common, cat_common = PadRef(H_AN, AN_SRC), PadRef(H_CAT, CAT)
d_k, d_a = PadRef(D_PROT, AN_SRC), PadRef(D_PROT, CAT)
u_an, u_cat, u_col, u_em = PadRef(OPTO, AN), PadRef(OPTO, CAT), PadRef(OPTO, OUT), PadRef(OPTO, GND)
HEADER_PITCH = h_claim.height + SHUNT_GRIP

# ---------------------------------------------------------------- the header block, then the chain along the band
board.place(H_AN, at=ORIGIN, rotation=0.0, why="the anode-side selector: pin 1 (v24, NPN) west, pin 3 (the field) east")
board.place(H_CAT, at=Centre(X(H_AN), Y(H_AN, HEADER_PITCH)), rotation=0.0,
            why="the cathode-side selector stacked under it, columns aligned")
band = Y(Mid(an_common, cat_common))                     # the chain's centre line: the corridor between the commons
board.place(D_PROT, at=Centre(X(H_AN, (h_claim.width + d_claim.width) / 2), band), rotation=upright(D_PROT, AN_SRC),
            why="the reverse clamp against the header block, cathode north on the anode side")
board.place(R_A, at=Centre(X(D_PROT, (d_claim.width + r_claim.width) / 2), band), rotation=upright(R_A, AN_SRC),
            why="the first series resistor, an_src pad north")
board.place(R_B, at=Centre(X(R_A, r_claim.width), band), rotation=upright(R_B, LED_A),
            why="the second, turned so the midpoint pads meet south and its LED pad is north")
board.place(LED, at=Centre(X(R_B, (r_claim.width + led_claim.width) / 2), band), rotation=upright(LED, LED_A),
            why="the activity LED, anode north to the resistor, cathode south toward the opto's anode pin")
board.place(OPTO, at=Centre(X(LED, (led_claim.width + opto_claim.width) / 2), band), rotation=0.0,
            why="the opto: LED side west, transistor side east, the barrier under its body")
board.place(R_BLEED, at=Pin(OUT, X(OPTO, (opto_claim.width + rb_claim.width) / 2), Y(u_col)), rotation=upright(R_BLEED, OUT),
            why="the pull-up standing east of the opto, its out pad on the collector's row")

# ---------------------------------------------------------------- copper
SOUTH = Y(OPTO, opto_claim.bottom + CLR + W / 2)         # the cathode-side corridor under the chain
board.track(AN_SRC, [an_common, (X(an_common), band), (X(H_AN, h_claim.width / 2), band), d_k, PadRef(R_A, AN_SRC)], layer=F,
            why="the anode common down into the corridor between the headers, east, up onto the clamp's cathode, on to the resistor")
board.track(CAT, [cat_common, (X(cat_common, HEADER_PITCH / 2), SOUTH), u_cat], layer=F,
            why="the cathode common south on one 45, east under the chain, up into the opto's cathode")
board.track(CAT, [d_a, (X(d_a, SHUNT_GRIP + CLR), SOUTH)], layer=F, why="the clamp's anode down onto that run")
board.track(R_MID, [PadRef(R_A, R_MID), PadRef(R_B, R_MID)], layer=F)
board.track(LED_A, [PadRef(R_B, LED_A), PadRef(LED, LED_A)], layer=F)
board.track(AN, [PadRef(LED, AN), u_an], layer=F, why="the LED's cathode east on one 45 up into the opto's anode")
board.track(OUT, [u_col, PadRef(R_BLEED, OUT)], layer=F, why="the collector straight into the pull-up")

board.via(GND, u_em, why="the emitter's ground")
board.via(V3V3, PadRef(R_BLEED, V3V3), why="the pull-up's rail")

board.label([PadRef(H_AN, V24), PadRef(H_AN, IN_P)], ["NPN", "PNP"], side=Edge.NORTH, line=H_AN, size=LABEL_SIZE, knockout=True,
            why="the two shunt columns named over their pads, clear of the header's outline")

board.faces(handoff=Edge.EAST, why="out leaves east to the MCU; the field pair leaves at the headers' west throws")
