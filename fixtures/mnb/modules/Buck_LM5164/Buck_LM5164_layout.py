"""Buck_LM5164: the compact 100 V synchronous buck, laid out to the
datasheet's layout section (SNVSAU4A 10.1). The IC anchors with its
power pins south and its signal pins north. The HF input cap lies under
the VIN and GND pins straddling them, the bulk cap behind it on the same
axis: the input loop is that rectangle and nothing else is in it. The
inductor stands on the IC's west flank with its SW pad facing the SW
pin, so the switch node is a short bar; the output caps form a row on
the south edge with their ground pads outboard, their vout pads and the
inductor's pooled by one region. Every small-signal part but the
divider's top stands in one column east of the IC at the courtyard
pitch, so each net's pads are neighbours on one line: the divider's
bottom, the ripple network's cap, its resistor and its other cap, then
the RON resistor; the divider's top lies north of the IC with its FB
pad on the FB pin's axis beside the bootstrap cap over the BST and SW
pins; the EN divider lies south beside the input caps.

Every local net is a pool: the switch node, the input pool, the output
pool, and the FB, EN and BST nodes each cover exactly the pads they
reach. Four short runs join what the pools cannot: the ripple node
round the switch-node pad in the column, RON to its pin, the switch
node's tap to the ripple resistor, and the vout sense, which goes
under the package through the annulus between the exposed pad and the
south pin row so the cell claims no perimeter. The exposed pad carries
an array of thermal vias; every supply pad is its own plane tap.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

U, L, C_BST, C_IN_HF, C_IN_BULK, C_OA, C_OB = (Part("ic"), Part("l"), Part("cbst"), Part("cin_hf"), Part("cin_bulk"),
                                              Part("cout_a"), Part("cout_b"))
R_FB_TOP, R_FB_BOT, R_RON, R_EN_TOP, R_EN_BOT, R_A, C_A, C_B = (Part("rfb_top"), Part("rfb_bot"), Part("ron"), Part("ren_top"),
                                                                Part("ren_bot"), Part("ra"), Part("ca"), Part("cb"))
VIN, VOUT, GND, SW, BST, FB, RON, EN, RIPPLE = (Net("vin"), Net("vout"), Net("gnd"), Net("SW"), Net("BST"), Net("FB"),
                                                Net("RON"), Net("EN"), Net("RIPPLE"))
F = CopperLayer.F
W = board.netclass(FB).track_width
CLR = board.netclass(FB).clearance
STROKE = 0.2
LIP = STROKE / 2
OVER = 0.05
IN = OVER - LIP
VIA = 0.6
ORIGIN = Location(20.0, 20.0)       # the IC's origin: a fragment's coordinates are its own
L_ROT = 270.0                       # the inductor stood on end: SW pad north, vout pad south


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


BST_ROT, FBT_ROT, HF_ROT, BULK_ROT = flat(C_BST, BST), flat(R_FB_TOP, VOUT), flat(C_IN_HF, VIN), flat(C_IN_BULK, VIN)
FBB_ROT, CB_ROT, RA_ROT, CA_ROT, RON_ROT = upright(R_FB_BOT, GND), upright(C_B, FB), upright(R_A, SW), upright(C_A, RIPPLE), upright(R_RON, RON)
ENT_ROT, ENB_ROT, OA_ROT, OB_ROT = upright(R_EN_TOP, EN), upright(R_EN_BOT, EN), upright(C_OA, VOUT), upright(C_OB, VOUT)
u_claim, l_claim = board.claim(U), board.claim(L, rotation=L_ROT)
c0402_flat, r0402_up, c0402_up = board.claim(C_BST, rotation=BST_ROT), board.claim(R_FB_BOT, rotation=FBB_ROT), board.claim(C_B, rotation=CB_ROT)
c0603_flat, c1210_flat, c0805_up = board.claim(C_IN_HF, rotation=HF_ROT), board.claim(C_IN_BULK, rotation=BULK_ROT), board.claim(C_OA, rotation=OA_ROT)
u_gnd, u_vin, u_en, u_ron, u_fb, u_bst, u_sw, ep = (PadRef(U, 1), PadRef(U, 2), PadRef(U, 3), PadRef(U, 4), PadRef(U, 5), PadRef(U, 7),
                                                    PadRef(U, 8), PadRef(U, 9))
l_sw, l_vout = PadRef(L, SW), PadRef(L, VOUT)
bst_bst, bst_sw = PadRef(C_BST, BST), PadRef(C_BST, SW)
fbt_fb, fbt_vout, fbb_fb = PadRef(R_FB_TOP, FB), PadRef(R_FB_TOP, VOUT), PadRef(R_FB_BOT, FB)
cb_rip, cb_fb, ra_sw, ra_rip, ca_rip, ca_vout, ron_ron = (PadRef(C_B, RIPPLE), PadRef(C_B, FB), PadRef(R_A, SW), PadRef(R_A, RIPPLE),
                                                         PadRef(C_A, RIPPLE), PadRef(C_A, VOUT), PadRef(R_RON, RON))
hf_vin, bulk_vin, ent_vin, ent_en, enb_en = PadRef(C_IN_HF, VIN), PadRef(C_IN_BULK, VIN), PadRef(R_EN_TOP, VIN), PadRef(R_EN_TOP, EN), PadRef(R_EN_BOT, EN)
oa_vout, ob_vout = PadRef(C_OA, VOUT), PadRef(C_OB, VOUT)
_, uvy = pad_off(U, 2, 0.0)
_, ufby = pad_off(U, 5, 0.0)
usx, _ = pad_off(U, 8, 0.0)
lsx, lsy = pad_off(L, SW, L_ROT)
hfx, _ = pad_off(C_IN_HF, VIN, HF_ROT)
bulkx, _ = pad_off(C_IN_BULK, VIN, BULK_ROT)
fbtx, _ = pad_off(R_FB_TOP, FB, FBT_ROT)
bstx, _ = pad_off(C_BST, BST, BST_ROT)
_, fbb_dy = pad_off(R_FB_BOT, FB, FBB_ROT)
EP_BOTTOM = max(p.box.bottom for p in board.part(U).pads if p.number == "9") - board.part(U).location.y
EP_TOP = min(p.box.top for p in board.part(U).pads if p.number == "9") - board.part(U).location.y
urx, _ = pad_off(U, 4, 0.0)
urw, _ = pad_size(U, 4, 0.0)
qw0, _ = pad_size(R_FB_BOT, FB, FBB_ROT)
COL_X = max(u_claim.right + r0402_up.width / 2, urx + urw / 2 + CLR + W + CLR + qw0 / 2)   # the small-signal column against the IC's east flank, its pads a lane past the RON pin for the vout sense
COL_PITCH = r0402_up.height                                    # its parts at courtyard pitch, one over the other

# ---------------------------------------------------------------- placement
board.place(U, at=ORIGIN, rotation=0.0, why="GND, VIN, EN, RON on the south row; SW, BST, PGOOD, FB north; the exposed pad to ground")
board.place(C_IN_HF, at=Pin(VIN, X(u_vin), Y(u_vin, (u_claim.bottom - uvy) - c0603_flat.top)), rotation=HF_ROT,
            why="the HF input cap under the VIN and GND pins, vin pad on the VIN pin's axis, ground west under GND: the smallest loop")
board.place(C_IN_BULK, at=Pin(VIN, X(hf_vin), Y(C_IN_HF, (c0603_flat.height + c1210_flat.height) / 2)), rotation=BULK_ROT,
            why="the bulk input cap behind it on the same axis")
board.place(L, at=Pin(SW, X(u_sw, (u_claim.left - usx) - l_claim.right + lsx), Y(u_sw)), rotation=L_ROT,
            why="the inductor on the IC's west flank, its SW pad facing the SW pin on the pin's row: the switch node is a short bar")
board.place(C_OA, at=Centre(X(C_IN_HF, -(c0603_flat.width + c0805_up.width) / 2), Y(L, (l_claim.height + c0805_up.height) / 2)), rotation=OA_ROT,
            why="the first output cap under the inductor beside the input cap, vout pad up toward the inductor's pad, ground down")
board.place(C_OB, at=Centre(X(C_OA, -c0805_up.width), Y(C_OA)), rotation=OB_ROT, why="the second beside it: a row, ground pads outboard")
board.place(C_BST, at=Pin(BST, X(u_bst), Y(u_bst, (u_claim.top - ufby) + c0402_flat.top)), rotation=BST_ROT,
            why="the bootstrap cap over the BST and SW pins, BST pad on the BST pin's axis, SW pad west over the SW pin")
board.place(R_FB_TOP, at=Pin(FB, X(u_fb), Y(u_fb, (u_claim.top - ufby) + c0402_flat.top)), rotation=FBT_ROT,
            why="the divider's top over the FB pin, its FB pad on the pin's axis: the sense is one straight run; vout east")
board.place(R_FB_BOT, at=Pin(FB, X(U, COL_X), Y(u_fb, (u_claim.top - ufby) - r0402_up.top + fbb_dy)), rotation=FBB_ROT,
            why="the column's first part: the divider's bottom, ground up at the cell's edge, FB pad down to meet the ripple cap's")
board.place(C_B, at=Centre(X(R_FB_BOT), Y(R_FB_BOT, COL_PITCH)), rotation=CB_ROT, why="the ripple cap under it, FB pad up beside the divider's, ripple down")
board.place(R_A, at=Centre(X(R_FB_BOT), Y(C_B, COL_PITCH)), rotation=RA_ROT, why="the ripple resistor under that, switch-node pad up, ripple down")
board.place(C_A, at=Centre(X(R_FB_BOT), Y(R_A, COL_PITCH)), rotation=CA_ROT, why="the other ripple cap, ripple pad up, vout down")
board.place(R_RON, at=Centre(X(R_FB_BOT), Y(C_A, COL_PITCH)), rotation=RON_ROT, why="the RON resistor at the column's foot, RON pad up, ground down")
board.place(R_EN_BOT, at=Centre(X(R_RON, -r0402_up.width), Y(u_vin, (u_claim.bottom - uvy) - r0402_up.top)), rotation=ENB_ROT,
            why="the EN divider's bottom under the IC beside the column's foot, EN up, ground down")
board.place(R_EN_TOP, at=Centre(X(R_EN_BOT, -r0402_up.width), Y(R_EN_BOT)), rotation=ENT_ROT, why="its top beside that, EN up, vin down")

# ---------------------------------------------------------------- the pools
sw_w, sw_h = pad_size(U, 8, 0.0)
lw, lh = pad_size(L, SW, L_ROT)
lvw, lvh = pad_size(L, VOUT, L_ROT)
bw, bh = pad_size(C_BST, SW, BST_ROT)
ow, oh = pad_size(C_OA, VOUT, OA_ROT)
vw, vh = pad_size(U, 2, 0.0)
hw, hh = pad_size(C_IN_HF, VIN, HF_ROT)
kw, kh = pad_size(C_IN_BULK, VIN, BULK_ROT)
fw, fh = pad_size(U, 5, 0.0)
tw, th = pad_size(R_FB_TOP, FB, FBT_ROT)
qw, qh = pad_size(R_FB_BOT, FB, FBB_ROT)
ew, eh = pad_size(R_EN_TOP, EN, ENT_ROT)
FLUSH = -LIP                                                  # a vertex this far inside a pad edge puts the copper edge on it: the boot cap's two pads are a pad's width apart
board.pour(SW, [(X(l_sw, -lw / 2 - IN), Y(l_sw, -lh / 2 - IN)), (X(bst_sw, bw / 2 + FLUSH), Y(l_sw, -lh / 2 - IN)),
                (X(bst_sw, bw / 2 + FLUSH), Y(u_sw, sw_h / 2 + IN)), (X(u_sw, -sw_w / 2 - IN), Y(u_sw, sw_h / 2 + IN)),
                (X(u_sw, -sw_w / 2 - IN), Y(l_sw, lh / 2 + IN)), (X(l_sw, -lw / 2 - IN), Y(l_sw, lh / 2 + IN))],
           layer=F, why="the switch node: the inductor's pad, the SW pin and the bootstrap cap's SW pad, necked where it only serves the pin")
board.pour(VOUT, [(X(l_vout, -lvw / 2 - IN), Y(l_vout, -lvh / 2 - IN)), (X(l_vout, lvw / 2 + IN), Y(l_vout, -lvh / 2 - IN)),
                  (X(l_vout, lvw / 2 + IN), Y(oa_vout, oh / 2 + IN)), (X(ob_vout, -ow / 2 - IN), Y(oa_vout, oh / 2 + IN))],
           layer=F, why="the output pool: the inductor's own pad and both output caps' supply pads")
board.pour(VIN, [(X(u_vin, -vw / 2 - IN), Y(u_vin, -vh / 2 - IN)), (X(u_vin, vw / 2 + IN), Y(u_vin, -vh / 2 - IN)),
                 (X(u_vin, vw / 2 + IN), Y(bulk_vin, kh / 2 + IN)), (X(bulk_vin, -kw / 2 - IN), Y(bulk_vin, kh / 2 + IN)),
                 (X(bulk_vin, -kw / 2 - IN), Y(hf_vin, -hh / 2 - IN)), (X(u_vin, -vw / 2 - IN), Y(hf_vin, -hh / 2 - IN))],
           layer=F, why="the input pool: the VIN pin and both input caps' vin pads")
board.pour(FB, [(X(fbt_fb, -tw / 2 - IN), Y(fbt_fb, -th / 2 - IN)), (X(fbt_fb, tw / 2 + IN), Y(fbt_fb, -th / 2 - IN)),
                (X(fbt_fb, tw / 2 + IN), Y(fbb_fb, -qh / 2 - IN)), (X(fbb_fb, qw / 2 + IN), Y(fbb_fb, -qh / 2 - IN)),
                (X(fbb_fb, qw / 2 + IN), Y(cb_fb, qh / 2 + IN)), (X(fbb_fb, -qw / 2 - IN), Y(cb_fb, qh / 2 + IN)),
                (X(fbb_fb, -qw / 2 - IN), Y(u_fb, fh / 2 + IN)), (X(u_fb, -fw / 2 - IN), Y(u_fb, fh / 2 + IN))],
           layer=F, why="FB: the pin, the divider's top on its axis, and a band across to the column's two FB pads, under the divider bottom's ground pad")
board.pour(BST, [(X(bst_bst, -bw / 2 - FLUSH), Y(bst_bst, -bh / 2 - IN)), (X(bst_bst, bw / 2 + IN), Y(bst_bst, -bh / 2 - IN)),
                 (X(bst_bst, bw / 2 + IN), Y(u_bst, fh / 2 + IN)), (X(bst_bst, -bw / 2 - FLUSH), Y(u_bst, fh / 2 + IN))],
           layer=F, why="BST: the pin and the bootstrap cap's own pad, nothing more")
board.pour(EN, [(X(ent_en, -ew / 2 - IN), Y(ent_en, -eh / 2 - IN)), (X(enb_en, ew / 2 + IN), Y(ent_en, -eh / 2 - IN)),
                (X(enb_en, ew / 2 + IN), Y(ent_en, eh / 2 + IN)), (X(ent_en, -ew / 2 - IN), Y(ent_en, eh / 2 + IN))],
           layer=F, why="EN: the divider's two EN pads")

# ---------------------------------------------------------------- the runs the pools cannot make
COL_LANE = X(R_FB_BOT, r0402_up.width / 2 + CLR + W / 2)      # east of the column: the ripple node steps round the resistor's switch-node pad
board.track(RIPPLE, [cb_rip, (COL_LANE, Y(cb_rip)), (COL_LANE, Y(ra_rip)), ra_rip, ca_rip], layer=F, chamfer=0.3,
            why="the ripple node east off the cap's pad, down the lane past the resistor's switch-node pad, into its ripple pad, and on to the other cap")
board.track(RON, [ron_ron, u_ron], layer=F, why="RON on one 45 up onto its pin's axis, into the pin")
board.track(EN, [enb_en, u_en], layer=F, why="EN up into its pin")
SW_LANE = Y(u_bst, fh / 2 + OVER + LIP + CLR + W / 2)         # under the north pins and the BST pool's foot
board.track(SW, [u_sw, (X(u_sw), SW_LANE), (X(ra_sw, -(r0402_up.width / 2 + CLR + W / 2)), SW_LANE), ra_sw], layer=F, chamfer=0.3,
            why="the switch node's tap to the ripple resistor along the north pins' foot, short 45s at its corners")
SENSE_Y = Y(u_vin, -(vh / 2 + OVER + LIP + CLR + W / 2))      # the annulus between the exposed pad and the input pool's top over the south pins
board.track(VOUT, [fbt_vout, (X(fbt_vout, CLR + W), Y(fbt_vout)), (X(R_FB_BOT, r0402_up.width / 2 + CLR + W / 2 + W + CLR), Y(ca_vout)), ca_vout],
            layer=F, why="the vout sense from the divider's top down the column's far side into the ripple cap's vout pad")
WEST_LANE = X(u_ron, urw / 2 + CLR + W / 2)                   # up the column's west side, past the RON pin
board.track(VOUT, [ca_vout, (WEST_LANE, Y(ca_vout, -(r0402_up.width / 2 - 0.0))), (WEST_LANE, SENSE_Y), (X(l_vout), SENSE_Y), l_vout], layer=F,
            why="and off the cap's pad on one 45 to the column's west side, up it, then under the package through the annulus to the inductor's pad: the sense reads the pool, the cell claims no perimeter")

# ---------------------------------------------------------------- vias
EP_W = max(p.box.width for p in board.part(U).pads if p.number == "9")
for dx in (-EP_W / 3, 0.0, EP_W / 3):
    for dy in (-(EP_BOTTOM - EP_TOP) / 3, 0.0, (EP_BOTTOM - EP_TOP) / 3):
        board.via(GND, (X(U, dx), Y(u_vin, (EP_TOP + EP_BOTTOM) / 2 - uvy + dy)), why="the thermal array in the exposed pad")
for part in (C_OA, C_OB, C_IN_HF, C_IN_BULK, R_FB_BOT, R_RON, R_EN_BOT):
    board.via(GND, PadRef(part, GND))
board.via(VOUT, oa_vout)
board.via(VOUT, ob_vout)
board.via(VOUT, l_vout)
board.via(VIN, hf_vin)
board.via(VIN, bulk_vin)
board.via(VIN, ent_vin)

board.faces(handoff=Edge.SOUTH, why="vout leaves at the output pool on the south; vin arrives at the input pool beside it")
