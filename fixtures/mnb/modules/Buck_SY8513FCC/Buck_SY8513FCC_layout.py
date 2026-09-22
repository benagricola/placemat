"""Buck_SY8513FCC: the 48 V asynchronous buck. The IC anchors: its supply and
control pins on the south row, the switch, boot and feedback pins on the
north. The boot cap lies over the BS and LX pins with its BS pad on the
BS pin's axis; the freewheel diode stands against the IC's west flank,
cathode up on the switch node; the inductor lies over both, its LX pad
west over the diode; the two bulk output caps stack east of the
inductor over the feedback column, ground pads outboard. The feedback
column east of the IC hangs off the FB pin's own row: the feed-forward
cap with its FB pad on the pin's axis, the output HF cap above it, the
divider's two resistors below, all courtyards touching, their vout pads
east on one column. The input side is under the IC: the HF cap under
the VIN pin with its vin pad on the pin's axis, the 1 uF under that on
the same axis, the bulk cap west of both with its vin pad facing
theirs, the EN divider above the bulk cap against the IC's west corner,
and the frequency resistor beside the HF cap under the FS pin.

Power nets are filled polygons: the switch node (the diode's cathode,
the LX pin, the inductor's LX pad and the boot cap's LX pad, one region
kept small), the input pool (the VIN pin, the three input caps' vin
pads and the EN divider's top), the output bank (the inductor's vout
pad and both bulk caps' vout pads) and the feedback column's vout pads.
EN threads the corridor between the exposed pad and the input pool.
Every ground pad and the exposed pad's holes reach the plane by via;
vout enters its plane at the inductor's pad and the bulk caps; every
input cap is fed from the plane in its own pad.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

U, L, D, C_BS, C_FF = Part("ic"), Part("l"), Part("d"), Part("cbs"), Part("cff")
C_IN_1U, C_IN_BULK, C_IN_HF = Part("cin_1u"), Part("cin_bulk"), Part("cin_hf")
C_OA, C_OB, C_OHF = Part("cout_a"), Part("cout_b"), Part("cout_hf")
R_EN_BOT, R_EN_TOP, R_FB_BOT, R_FB_TOP, R_FS = Part("ren_bot"), Part("ren_top"), Part("rfb_bot"), Part("rfb_top"), Part("rfs")
VIN, VOUT, GND, EN, FB, LX, BS, FS = Net("vin"), Net("vout"), Net("gnd"), Net("EN"), Net("FB"), Net("LX"), Net("BS"), Net("FS")
F = CopperLayer.F
W = board.netclass(FB).track_width
CLR = board.netclass(FB).clearance
STROKE = 0.2
LIP = STROKE / 2
OVER = 0.05
IN = OVER - LIP
CH45 = 0.6                          # a 45 leg where a lane turns onto a pin's column
ORIGIN = Location(22.0, 22.0)       # the IC's origin: a fragment's coordinates are its own


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


D_ROT = upright(D, LX)
BS_ROT, FF_ROT, OHF_ROT, FBT_ROT, FBB_ROT = flat(C_BS, BS), flat(C_FF, VOUT), flat(C_OHF, VOUT), flat(R_FB_TOP, VOUT), flat(R_FB_BOT, GND)
HF_ROT, IN1_ROT, BULK_ROT, FS_ROT = flat(C_IN_HF, GND), flat(C_IN_1U, GND), flat(C_IN_BULK, VIN), flat(R_FS, GND)
ENT_ROT, ENB_ROT, OA_ROT = flat(R_EN_TOP, VIN), flat(R_EN_BOT, EN), flat(C_OA, GND)
u_claim, l_claim, d_claim = board.claim(U), board.claim(L), board.claim(D, rotation=D_ROT)
c0402, r0402 = board.claim(C_BS, rotation=BS_ROT), board.claim(R_FB_TOP, rotation=FBT_ROT)
c0603, c0805, c1210 = board.claim(C_IN_HF, rotation=HF_ROT), board.claim(C_IN_1U, rotation=IN1_ROT), board.claim(C_IN_BULK, rotation=BULK_ROT)
u_vin, u_en, u_fs, u_gnd, u_fb, u_bs, u_lx, ep = (PadRef(U, 1), PadRef(U, 2), PadRef(U, 3), PadRef(U, 4), PadRef(U, 5),
                                                  PadRef(U, 7), PadRef(U, 8), PadRef(U, 9))
l_lx, l_vout, d_lx, d_gnd = PadRef(L, LX), PadRef(L, VOUT), PadRef(D, LX), PadRef(D, GND)
bs_bs, bs_lx = PadRef(C_BS, BS), PadRef(C_BS, LX)
ff_fb, ff_vout, ohf_vout, fbt_fb, fbt_vout, fbb_fb = (PadRef(C_FF, FB), PadRef(C_FF, VOUT), PadRef(C_OHF, VOUT),
                                                     PadRef(R_FB_TOP, FB), PadRef(R_FB_TOP, VOUT), PadRef(R_FB_BOT, FB))
hf_vin, in1_vin, bulk_vin, ent_vin, ent_en, enb_en, fs_fs = (PadRef(C_IN_HF, VIN), PadRef(C_IN_1U, VIN), PadRef(C_IN_BULK, VIN),
                                                            PadRef(R_EN_TOP, VIN), PadRef(R_EN_TOP, EN), PadRef(R_EN_BOT, EN), PadRef(R_FS, FS))
oa_vout, ob_vout = PadRef(C_OA, VOUT), PadRef(C_OB, VOUT)
_, ubsy = pad_off(U, 7, 0.0)
_u = board.part(U)
EP_BOTTOM = max(p.box.bottom for p in _u.pads if p.number == "9") - _u.location.y   # the exposed pad's foot below the IC's origin (its holes share the number)
_, uviny = pad_off(U, 1, 0.0)
ufbx, _ = pad_off(U, 5, 0.0)
ffx, _ = pad_off(C_FF, FB, FF_ROT)
hfx, _ = pad_off(C_IN_HF, VIN, HF_ROT)
in1x, _ = pad_off(C_IN_1U, VIN, IN1_ROT)
bulkx, _ = pad_off(C_IN_BULK, VIN, BULK_ROT)

# ---------------------------------------------------------------- placement
board.place(U, at=ORIGIN, rotation=0.0, why="supply and control pins south, switch, boot and feedback north, the exposed pad's holes to ground")
dgw, _ = pad_size(D, GND, D_ROT)
board.place(C_BS, at=Pin(BS, X(u_bs), Y(u_bs, (u_claim.top - ubsy) + c0402.top)), rotation=BS_ROT,
            why="the boot cap over the BS and LX pins, its BS pad on the BS pin's axis, LX pad west into the switch node")
board.place(D, at=Pin(GND, X(ent_en, -(W / 2 + CLR + dgw / 2)), Y(C_BS, c0402.top + d_claim.height / 2 + pad_off(D, GND, D_ROT)[1])), rotation=D_ROT,
            why="the freewheel diode west of the IC under the inductor, its anode pad one clearance west of EN's climb; cathode up on the switch node")
board.place(L, at=Centre(X(D, (l_claim.width - d_claim.width) / 2), Y(C_BS, c0402.top - l_claim.height / 2)),
            rotation=0.0, why="the inductor over the boot cap and the diode, its west edge on the diode's: LX pad west, vout pad east")
board.place(C_FF, at=Pin(FB, X(u_fb, (u_claim.right - ufbx) - c0402.left + ffx), Y(u_fb)), rotation=FF_ROT,
            why="the feed-forward cap east of the IC with its FB pad on the FB pin's row: the tap is one straight track; vout east")
board.place(C_OHF, at=Centre(X(C_FF), Y(C_FF, -c0402.height)), rotation=OHF_ROT, why="the output HF cap above it, vout east on the column")
board.place(R_FB_TOP, at=Centre(X(C_FF), Y(C_FF, r0402.height)), rotation=FBT_ROT, why="the divider's top below it, FB west, vout east")
board.place(R_FB_BOT, at=Centre(X(C_FF), Y(R_FB_TOP, r0402.height)), rotation=FBB_ROT, why="the divider's bottom below that, FB west, ground east")
board.place(C_OB, at=Centre(X(L, (l_claim.width + c1210.width) / 2), Y(C_OHF, c0402.top - c1210.height / 2)), rotation=OA_ROT,
            why="the lower bulk output cap east of the inductor, on the feedback column's top, vout pad west, ground east")
board.place(C_OA, at=Centre(X(C_OB), Y(C_OB, -c1210.height)), rotation=OA_ROT, why="the upper bulk output cap stacked on it")
board.place(C_IN_HF, at=Pin(VIN, X(u_vin), Y(u_vin, (u_claim.bottom - uviny) - c0603.top)), rotation=HF_ROT,
            why="the HF input cap under the VIN pin, vin pad on the pin's axis, ground east")
board.place(C_IN_1U, at=Pin(VIN, X(hf_vin), Y(C_IN_HF, (c0603.height + c0805.height) / 2)), rotation=IN1_ROT,
            why="the 1 uF under it on the same axis, ground east")
board.place(C_IN_BULK, at=Pin(VIN, X(in1_vin, (c0805.left - in1x) + (bulkx - c1210.right)), Y(C_IN_1U)),
            rotation=BULK_ROT, why="the bulk input cap west of the two, its vin pad facing theirs so one pool covers all three")
board.place(R_EN_TOP, at=Centre(X(U, u_claim.left - r0402.width / 2), Y(C_IN_BULK, c1210.top - r0402.height / 2)), rotation=ENT_ROT,
            why="the EN divider's top on the bulk cap against the IC's south-west corner, vin pad east into the pool")
board.place(R_EN_BOT, at=Centre(X(R_EN_TOP, -r0402.width), Y(R_EN_TOP)), rotation=ENB_ROT, why="its bottom beside it, EN pads facing, ground west")
board.place(R_FS, at=Centre(X(C_IN_HF, (c0603.width + r0402.width) / 2), Y(C_IN_HF)), rotation=FS_ROT,
            why="the frequency resistor beside the HF cap under the FS pin, FS pad west, ground east")

# ---------------------------------------------------------------- the power polygons
lw, lh = pad_size(L, LX, 0.0)
lvw, lvh = pad_size(L, VOUT, 0.0)
bw, bh = pad_size(C_BS, LX, BS_ROT)
uw, uh = pad_size(U, 8, 0.0)
dw, dh = pad_size(D, LX, D_ROT)
ow, oh = pad_size(C_OA, VOUT, OA_ROT)
cw, chh = pad_size(C_OHF, VOUT, OHF_ROT)
rw, rh = pad_size(R_FB_TOP, VOUT, FBT_ROT)
hw, hh = pad_size(C_IN_HF, VIN, HF_ROT)
iw, ih = pad_size(C_IN_1U, VIN, IN1_ROT)
kw, kh = pad_size(C_IN_BULK, VIN, BULK_ROT)
ew, eh = pad_size(R_EN_TOP, VIN, ENT_ROT)
vw, vh = pad_size(U, 1, 0.0)
ep_w, ep_h = pad_size(U, 9, 0.0)
board.pour(LX, [(X(l_lx, -lw / 2 - IN), Y(l_lx, -lh / 2 - IN)), (X(l_lx, lw / 2 + IN), Y(l_lx, -lh / 2 - IN)),
                (X(bs_lx, bw / 2 + IN), Y(bs_lx, -bh / 2 - IN)), (X(bs_lx, bw / 2 + IN), Y(u_lx, uh / 2 + IN)),
                (X(u_lx, -uw / 2 - IN), Y(u_lx, uh / 2 + IN)), (X(d_lx, dw / 2 + IN), Y(d_lx, dh / 2 + IN)),
                (X(d_lx, -dw / 2 - IN), Y(d_lx, dh / 2 + IN)), (X(d_lx, -dw / 2 - IN), Y(d_lx, -dh / 2 - IN)),
                (X(l_lx, -lw / 2 - IN), Y(l_lx, lh / 2 + IN))],
           layer=F, why="the switch node: the inductor's LX pad, down to the boot cap's LX pad and the LX pin, over the diode's cathode; no more")
board.pour(VOUT, [(X(l_vout, -lvw / 2 - IN), Y(oa_vout, -oh / 2 - IN)), (X(oa_vout, ow / 2 + IN), Y(oa_vout, -oh / 2 - IN)),
                  (X(oa_vout, ow / 2 + IN), Y(ob_vout, oh / 2 + IN)), (X(ob_vout, -ow / 2 - IN), Y(ob_vout, oh / 2 + IN)),
                  (X(ob_vout, -ow / 2 - IN), Y(l_vout, lvh / 2 + IN)), (X(l_vout, -lvw / 2 - IN), Y(l_vout, lvh / 2 + IN))],
           layer=F, why="the output bank: the inductor's vout pad and both bulk caps' vout pads in one L-shaped region, clear of the boot cap below the inductor")
board.pour(VOUT, [(X(ohf_vout, -cw / 2 - IN), Y(ohf_vout, -chh / 2 - IN)), (X(fbt_vout, rw / 2 + IN), Y(ohf_vout, -chh / 2 - IN)),
                  (X(fbt_vout, rw / 2 + IN), Y(fbt_vout, rh / 2 + IN)), (X(ohf_vout, -cw / 2 - IN), Y(fbt_vout, rh / 2 + IN))],
           layer=F, why="the feedback column's three vout pads in one region")
board.pour(VIN, [(X(hf_vin, hw / 2 + IN), Y(u_vin, -vh / 2 - IN)), (X(hf_vin, hw / 2 + IN), Y(in1_vin, ih / 2 + IN)),
                 (X(bulk_vin, -kw / 2 - IN), Y(in1_vin, ih / 2 + IN)), (X(bulk_vin, -kw / 2 - IN), Y(bulk_vin, -kh / 2 - IN)),
                 (X(ent_vin, -ew / 2 - IN), Y(bulk_vin, -kh / 2 - IN)), (X(ent_vin, -ew / 2 - IN), Y(ent_vin, -eh / 2 - IN)),
                 (X(ent_vin, ew / 2 + IN), Y(ent_vin, -eh / 2 - IN)), (X(u_vin, -vw / 2 - IN), Y(u_vin, -vh / 2 - IN))],
           layer=F, why="the input pool: the VIN pin, the three input caps' vin pads and the EN divider's top")

# ---------------------------------------------------------------- tracks
board.track(BS, [bs_bs, u_bs], layer=F, why="the boot cap's BS pad straight down its axis into the pin")
board.track(FB, [u_fb, ff_fb], layer=F, why="the FB tap straight off the pin into the feed-forward cap")
board.track(FB, [ff_fb, fbt_fb, fbb_fb], layer=F, why="and down the column through both divider pads: one short rail")
board.track(FS, [fs_fs, u_fs], layer=F, why="the frequency resistor up into its pin")
EN_LANE_DY = EP_BOTTOM - uviny + CLR + W / 2                  # the corridor between the exposed pad and the input pool, below the VIN pad's row
board.track(EN, [enb_en, ent_en], layer=F, why="the EN divider's two EN pads face each other")
board.track(EN, [ent_en, (X(ent_en), Y(u_vin, EN_LANE_DY)), (X(u_en, -CH45), Y(u_vin, EN_LANE_DY)), (X(u_en), Y(u_vin, EN_LANE_DY + CH45)), u_en], layer=F,
            why="EN straight up from the divider past the diode's anode, east along the corridor under the exposed pad, one 45 onto the pin's column, down into it")
board.track(VOUT, [ohf_vout, ob_vout], layer=F, why="the feedback column's vout joined to the bank at the lower bulk cap's pad")

# ---------------------------------------------------------------- vias
for part in (C_IN_1U, C_IN_BULK, C_IN_HF, C_OA, C_OB, C_OHF, D, R_EN_BOT, R_FB_BOT, R_FS):
    board.via(GND, PadRef(part, GND))
board.via(VOUT, oa_vout, why="the bank into the output plane at both caps and the inductor's pad")
board.via(VOUT, ob_vout)
board.via(VOUT, l_vout)
board.via(VIN, hf_vin, why="every input cap fed from the 48 V plane in its own pad")
board.via(VIN, in1_vin)
board.via(VIN, bulk_vin)

board.faces(handoff=Edge.EAST, why="vout leaves at the bank and the column on the east; vin arrives at the pool on the south")
