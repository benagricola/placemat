"""Buck_TPS563201: the 5 V to 3.3 V synchronous buck (both FETs internal, no
external diode), to TI's layout rules (SLVSD90B 7.4.1, figure 7-18).

The IC anchors. Its HF input cap stands on the VIN pin's own axis above
the IC, courtyards touching, so the hot loop's connection is one
straight track; the two bulk input caps stand in a row east of it with
their ground pads outboard (north, the via fence) and their vin pads
inboard, pooled with the HF cap's by one polygon that reaches the VIN
pin. The inductor lies against the IC's east flank on the SW pin's row;
the SW polygon is small and necked to the pin's width where it only
serves the pin, full width at the inductor pad, with a lobe down to the
boot cap, which stands under the inductor's SW pad. The two output caps
lie in a column east of the inductor straddling its output pad's row,
ground pads outboard, their vout pads and the inductor's pooled by one
rectangle. The feedback divider is a two-row block over the IC's west
column: the top resistor's vout pad on the VFB pin's axis, the chain
pads sharing one column so the high-impedance VFB node is one short
rail; the vout sense taps the inductor's output pad, the plane's
injection point, and hugs the cell's south and west edges to the
divider, away from the switch node.

Every ground pad drops a via to the board's plane (the hot loop's
return). The input caps and the output caps take vias to their planes,
and the inductor's output pad carries the vout injection via. EN is
tied to vin by a track. The cell's clearances are held to the 48 V
class floor a consuming board applies to vin, not the module's own.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

U, L, C_HF, C_A, C_B, C_BST, C_OA, C_OB, R_TOP, R_BOT = (Part("ic"), Part("l"), Part("cin_hf"), Part("cin_a"), Part("cin_b"),
                                                        Part("cbst"), Part("cout_a"), Part("cout_b"), Part("rfb_top"), Part("rfb_bot"))
VIN, VOUT, GND, SW, VBST, VFB = Net("vin"), Net("vout"), Net("gnd"), Net("SW"), Net("VBST"), Net("VFB")
F = CopperLayer.F
W = board.netclass(VFB).track_width
CLR = board.netclass(VFB).clearance
STROKE = 0.2
LIP = STROKE / 2
OVER = 0.05
IN = OVER - LIP
ORIGIN = Location(20.0, 20.0)       # the IC's origin: a fragment's coordinates are its own


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


HF_ROT, CA_ROT, CB_ROT, BST_ROT = upright(C_HF, GND), upright(C_A, GND), upright(C_B, GND), upright(C_BST, SW)
OA_ROT, OB_ROT, RT_ROT, RB_ROT = flat(C_OA, GND), flat(C_OB, GND), flat(R_TOP, VFB), flat(R_BOT, VFB)
u_claim, l_claim = board.claim(U), board.claim(L)
hf_claim, ca_claim, bst_claim = board.claim(C_HF, rotation=HF_ROT), board.claim(C_A, rotation=CA_ROT), board.claim(C_BST, rotation=BST_ROT)
oa_claim, r_claim = board.claim(C_OA, rotation=OA_ROT), board.claim(R_TOP, rotation=RT_ROT)
u_vin, u_sw, u_gnd, u_vfb, u_en, u_vbst = PadRef(U, 3), PadRef(U, 2), PadRef(U, 1), PadRef(U, 4), PadRef(U, 5), PadRef(U, 6)
l_sw, l_vout = PadRef(L, SW), PadRef(L, VOUT)
hf_vin, ca_vin, cb_vin = PadRef(C_HF, VIN), PadRef(C_A, VIN), PadRef(C_B, VIN)
bst_sw, bst_vbst = PadRef(C_BST, SW), PadRef(C_BST, VBST)
oa_vout, ob_vout = PadRef(C_OA, VOUT), PadRef(C_OB, VOUT)
rt_vout, rt_vfb, rb_vfb, rb_gnd = PadRef(R_TOP, VOUT), PadRef(R_TOP, VFB), PadRef(R_BOT, VFB), PadRef(R_BOT, GND)
uvx, uvy = pad_off(U, 3, 0.0)
_, hf_vin_dy = pad_off(C_HF, VIN, HF_ROT)
_, ca_vin_dy = pad_off(C_A, VIN, CA_ROT)
ROW_DY = (u_claim.top - uvy) + ca_claim.top + ca_vin_dy     # the input caps' vin pad row above the VIN pin: the bulk caps' courtyards on the IC's
lsx, _ = pad_off(L, SW, 0.0)
_, bst_sw_dy = pad_off(C_BST, SW, BST_ROT)
rt_vx, _ = pad_off(R_TOP, VOUT, RT_ROT)

# ---------------------------------------------------------------- placement
board.place(U, at=ORIGIN, rotation=0.0, why="vin, SW, gnd on the east column; VFB, EN, VBST on the west")
board.place(C_HF, at=Pin(VIN, X(u_vin), Y(u_vin, ROW_DY)), rotation=HF_ROT,
            why="the HF input cap on the VIN pin's axis above the IC, vin pad down on the row, ground up: the hot loop is one straight track")
board.place(C_A, at=Pin(VIN, X(C_HF, (hf_claim.width + ca_claim.width) / 2), Y(hf_vin)), rotation=CA_ROT,
            why="the first bulk input cap beside it, vin pad on the same row, ground outboard")
board.place(C_B, at=Pin(VIN, X(C_A, ca_claim.width), Y(hf_vin)), rotation=CB_ROT, why="the second beside that")
board.place(L, at=Pin(SW, X(u_sw, (u_claim.right - uvx) - l_claim.left + lsx), Y(u_sw)), rotation=0.0,
            why="the inductor against the IC's east flank, its SW pad on the SW pin's row")
board.place(C_BST, at=Pin(SW, X(l_sw), Y(l_sw, (l_claim.bottom) - bst_claim.top + bst_sw_dy - pad_off(L, SW, 0.0)[1])), rotation=BST_ROT,
            why="the boot cap standing under the inductor's SW pad, SW pad up into the switch node's lobe, VBST down")
board.place(C_OA, at=Centre(X(L, (l_claim.width + oa_claim.width) / 2), Y(cb_vin, (ca_claim.bottom - ca_vin_dy) + oa_claim.height / 2)), rotation=OA_ROT,
            why="the first output cap east of the inductor, under the input row's courtyards, vout pad west, ground east")
board.place(C_OB, at=Centre(X(C_OA), Y(C_OA, oa_claim.height)), rotation=OB_ROT, why="the second below it: a column beside the inductor's output pad")
board.place(R_TOP, at=Pin(VOUT, X(u_vfb), Y(u_vfb, (u_claim.top - pad_off(U, 4, 0.0)[1]) - r_claim.height / 2)), rotation=RT_ROT,
            why="the divider's top over the IC's west column, its vout pad on the VFB pin's axis, VFB pad east")
board.place(R_BOT, at=Centre(X(R_TOP), Y(R_TOP, -r_claim.height)), rotation=RB_ROT,
            why="the divider's bottom above it, VFB pads on one column, ground west")

# ---------------------------------------------------------------- the power polygons
hw, hh = pad_size(C_HF, VIN, HF_ROT)
cw, ch = pad_size(C_B, VIN, CB_ROT)
vw, vh = pad_size(U, 3, 0.0)
sw_w, sw_h = pad_size(U, 2, 0.0)
lw, lh = pad_size(L, SW, 0.0)
bw, bh = pad_size(C_BST, SW, BST_ROT)
ow, oh = pad_size(C_OA, VOUT, OA_ROT)
lvw, lvh = pad_size(L, VOUT, 0.0)
board.pour(VIN, [(X(hf_vin, -hw / 2 - IN), Y(hf_vin, -hh / 2 - IN)), (X(cb_vin, cw / 2 + IN), Y(hf_vin, -hh / 2 - IN)),
                 (X(cb_vin, cw / 2 + IN), Y(cb_vin, ch / 2 + IN)), (X(u_vin, vw / 2 + IN), Y(cb_vin, ch / 2 + IN)),
                 (X(u_vin, vw / 2 + IN), Y(u_vin, vh / 2 + IN)), (X(u_vin, -vw / 2 - IN), Y(u_vin, vh / 2 + IN)),
                 (X(u_vin, -vw / 2 - IN), Y(hf_vin, hh / 2 + IN)), (X(hf_vin, -hw / 2 - IN), Y(hf_vin, hh / 2 + IN))],
           layer=F, why="the input pool: the three caps' vin pads and the VIN pin in one region, the hot loop's copper")
NECK_END = vw / 2 + OVER + CLR + LIP                          # the neck runs east past the input pool's edge by the clearance before it rises
board.pour(SW, [(X(u_sw, -sw_w / 2 - IN), Y(u_sw, -sw_h / 2 - IN)), (X(u_vin, NECK_END), Y(u_sw, -sw_h / 2 - IN)),
                (X(u_vin, NECK_END), Y(l_sw, -lh / 2 - IN)), (X(l_sw, lw / 2 + IN), Y(l_sw, -lh / 2 - IN)),
                (X(l_sw, lw / 2 + IN), Y(bst_sw, bh / 2 + IN)), (X(bst_sw, -bw / 2 - IN), Y(bst_sw, bh / 2 + IN)),
                (X(bst_sw, -bw / 2 - IN), Y(u_sw, sw_h / 2 + IN)), (X(u_sw, -sw_w / 2 - IN), Y(u_sw, sw_h / 2 + IN))],
           layer=F, why="the switch node: necked to the SW pin's height where it only serves the pin, full width over the inductor pad, a lobe down to the boot cap")
board.pour(VOUT, [(X(l_vout, -lvw / 2 - IN), Y(oa_vout, -oh / 2 - IN)), (X(oa_vout, ow / 2 + IN), Y(oa_vout, -oh / 2 - IN)),
                  (X(oa_vout, ow / 2 + IN), Y(ob_vout, oh / 2 + IN)), (X(l_vout, -lvw / 2 - IN), Y(ob_vout, oh / 2 + IN))],
           layer=F, why="the output pool: the inductor's output pad and both output caps' vout pads in one rectangle")

# ---------------------------------------------------------------- tracks
board.track(VIN, [hf_vin, u_vin], layer=F, why="the hot loop: the HF cap straight down its axis into the VIN pin")
board.track(VIN, [u_en, (X(u_en, vw / 2 + CLR + W / 2), Y(u_en)), (X(u_vin, -vw / 2), Y(u_vin))], layer=F,
            why="EN tied to vin: east off its pin, one 45 up over the body into the input pool at the VIN pin")
board.track(VFB, [u_vfb, rt_vfb, rb_vfb], layer=F, why="VFB off its pin on one 45 onto the divider's chain column, up it")
board.track(VBST, [u_vbst, (X(u_vbst), Y(bst_vbst)), bst_vbst], layer=F,
            why="VBST down off its pin, east under the IC on the boot cap's VBST row, into the pad")
CORRIDOR = X(U, u_claim.left - CLR - W / 2)                   # the vout sense's west corridor, outside the IC
SOUTH = Y(C_BST, bst_claim.bottom + CLR + W / 2)              # and its south run, under the boot cap
board.track(VOUT, [l_vout, (X(l_vout), SOUTH), (CORRIDOR, SOUTH), (CORRIDOR, Y(rt_vout)), rt_vout], layer=F,
            why="the vout sense from the plane's injection point, round the south and west edges, into the divider's top")

# ---------------------------------------------------------------- vias
for part in (C_HF, C_A, C_B, C_OA, C_OB, R_BOT):
    board.via(GND, PadRef(part, GND))
board.via(GND, u_gnd, why="the IC's ground pin: the hot loop's return")
board.via(VIN, ca_vin, why="the bulk input caps fed from the 5 V plane in their own pads")
board.via(VIN, cb_vin)
board.via(VOUT, oa_vout, why="the output caps into the 3V3 plane")
board.via(VOUT, ob_vout)
board.via(VOUT, l_vout, why="vout enters its plane where it is made, at the inductor's pad: the sense taps this point")

board.faces(handoff=Edge.EAST, why="vout leaves at the output pool east; vin arrives at the input pool north")
