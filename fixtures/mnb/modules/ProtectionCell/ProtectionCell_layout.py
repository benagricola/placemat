"""ProtectionCell: a freewheel diode and a TVS across a driven output, and
an output-active indicator. Two SMB power diodes share the v_out node:
the TVS west and the freewheel east, turned so their v_out pads face
each other, courtyards touching, the node pooled between them by one
filled polygon that carries the coil's recirculation current. The
polygon reaches south of the pads to the cell's full-width handoff
face, so the board picks v_out up on wide copper, not a neck. v_supply
and gnd land on the outboard pads, each with a via in the pad for the
board's planes; v_out is the board's net to continue and takes no via.

The indicator chain, v_supply through two series resistors and the LED
to v_out, is one row north of the diodes, courtyards touching them,
its v_supply end on the freewheel diode's v_supply pad axis so that
serve is one straight track; the LED's cathode drops to the TVS's
v_out pad. Every other track is pad to pad along the row.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

D_FW, D_TVS, LED, R_A, R_B = Part("dfw"), Part("dtvs"), Part("led_act"), Part("rled_act_a"), Part("rled_act_b")
V_OUT, V_SUPPLY, GND, R_MID, LED_MID = Net("v_out"), Net("v_supply"), Net("gnd"), Net("PROT_LED_RMID"), Net("PROT_LED_MID")
F = CopperLayer.F
W = board.netclass(LED_MID).track_width   # the indicator's tracks: mA, the class width

ORIGIN = Location(20.0, 20.0)   # the TVS's origin: a fragment's coordinates are its own
POOL_SOUTH = 1.7                # the v_out polygon reaches this far south of the pads: the handoff face, wide copper for the coil current


def pad_off(part, key, rotation):
    """A pad's offset from its part's origin once the part is turned."""
    p, o = board.pad(part, key).location, board.part(part).location
    return Transform.rotate(rotation).apply((p.x - o.x, p.y - o.y))


def flat(part, east_net):
    """The rotation that lays a two-pad part along a row with `east_net`'s pad east."""
    return 0.0 if pad_off(part, east_net, 0.0)[0] > 0 else 180.0


def pad_size(part, key, rotation):
    """A pad's (width, height) once its part is turned."""
    b = board.pad(part, key).box
    return (b.height, b.width) if rotation % 180 == 90 else (b.width, b.height)


TVS_ROT, FW_ROT = flat(D_TVS, V_OUT), flat(D_FW, V_SUPPLY)          # v_out pads facing each other
LED_ROT, RA_ROT, RB_ROT = flat(LED, LED_MID), flat(R_A, V_SUPPLY), flat(R_B, R_MID)
tvs_claim, fw_claim = board.claim(D_TVS, rotation=TVS_ROT), board.claim(D_FW, rotation=FW_ROT)
r_claim, led_claim = board.claim(R_A, rotation=RA_ROT), board.claim(LED, rotation=LED_ROT)
tvs_out, fw_out, fw_supply = PadRef(D_TVS, V_OUT), PadRef(D_FW, V_OUT), PadRef(D_FW, V_SUPPLY)
tox, toy = pad_off(D_TVS, V_OUT, TVS_ROT)               # the TVS's v_out pad from its origin
fox, foy = pad_off(D_FW, V_OUT, FW_ROT)                  # the freewheel diode's
POOL_GAP = (tvs_claim.right - tox) + (fox - fw_claim.left)   # between the facing pads' centres: the courtyards touching
ROW_UP = min(tvs_claim.top - toy, fw_claim.top - foy) - r_claim.height / 2   # the indicator row's centre line above the pad line: courtyards on the taller diode's

# ---------------------------------------------------------------- the two diodes, v_out pooled between them
board.place(D_TVS, at=ORIGIN, rotation=TVS_ROT, why="the TVS west, gnd outboard")
board.place(D_FW, at=Pin(V_OUT, X(tvs_out, POOL_GAP), Y(tvs_out)), rotation=FW_ROT,
            why="the freewheel diode east, v_supply outboard, its v_out pad facing the TVS's on one line")

# ---------------------------------------------------------------- the indicator row north of them
board.place(R_A, at=Pin(V_SUPPLY, X(fw_supply), Y(tvs_out, ROW_UP)), rotation=RA_ROT,
            why="the first resistor's v_supply pad on the diode's v_supply pad axis: one straight serve")
board.place(R_B, at=Centre(X(R_A, -r_claim.width), Y(R_A)), rotation=RB_ROT, why="the second resistor along the row")
board.place(LED, at=Centre(X(R_B, -(r_claim.width + led_claim.width) / 2), Y(R_A)), rotation=LED_ROT,
            why="the LED at the row's west end, cathode toward the TVS's v_out pad")

# ---------------------------------------------------------------- copper
tw, th = pad_size(D_TVS, V_OUT, TVS_ROT)
fw_w, fh = pad_size(D_FW, V_OUT, FW_ROT)
board.pour(V_OUT, [(X(tvs_out, -tw / 2), Y(tvs_out, -th / 2)), (X(fw_out, fw_w / 2), Y(fw_out, -fh / 2)),
                   (X(fw_out, fw_w / 2), Y(fw_out, fh / 2 + POOL_SOUTH)), (X(tvs_out, -tw / 2), Y(tvs_out, th / 2 + POOL_SOUTH))],
           layer=F, why="the pooled node over both v_out pads, down to the full-width handoff face")
board.track(V_SUPPLY, [fw_supply, PadRef(R_A, V_SUPPLY)], layer=F, width=W, why="straight up the pad axis into the chain")
board.track(R_MID, [PadRef(R_A, R_MID), PadRef(R_B, R_MID)], layer=F, width=W)
board.track(LED_MID, [PadRef(R_B, LED_MID), PadRef(LED, LED_MID)], layer=F, width=W)
board.track(V_OUT, [PadRef(LED, V_OUT), tvs_out], layer=F, width=W, why="the cathode down into the pooled node")

board.via(V_SUPPLY, fw_supply, why="the supply plane lands in the freewheel diode's pad")
board.via(GND, PadRef(D_TVS, GND), why="the ground plane lands in the TVS's pad")

board.faces(handoff=Edge.SOUTH, why="v_out leaves on the pool's south face")
