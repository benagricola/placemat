"""ReversePolarityFet: the return-path reverse-polarity guard for a node's
48 V input. The FET's drain, its exposed pad on the north, is the cable's
V- landing (gnd_in): the board pours the connector's V- pins straight onto
it and the cell draws nothing on that net. The source row on the south is
board ground, pooled into a ground bar that also takes the gate cap's and
the zener's ground ends and the TVS and input cap returns, with vias to
the plane in the bar and in the big pads.

The gate network hangs east of the FET on the gate pad's own axis, one
straight serve from the pad: the gate cap point-blank, the zener beside
it, the bias resistor above the cap fed from the v48 pool. The bus parts,
the TVS and the input cap, stand west; their v48 ends pool along the
north and a track reaches the resistor over the top of the exposed pad.
Everything sits courtyard to courtyard.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

Q, R_G, DZ, C_G, TVS, C_IN = Part("fet"), Part("rg"), Part("dz"), Part("cg"), Part("tvs"), Part("cin")
V48, GND_IN, GND, GATE = Net("v48"), Net("gnd_in"), Net("gnd"), Net("GATE")
F = CopperLayer.F
STROKE = 0.2                            # a pour's outline stroke: copper reaches half of it past each vertex
LIP = STROKE / 2
OVER = 0.05                             # how far a pour's copper edge goes past a pad it swallows
CLR = board.netclass(GND).clearance     # a pour's copper edge to a foreign pad
ORIGIN = Location(12.0, 12.0)           # the FET's origin: a fragment's coordinates are its own


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


CG_ROT, R_ROT, DZ_ROT = upright(C_G, GATE), upright(R_G, V48), upright(DZ, GATE)
TVS_ROT, CIN_ROT = upright(TVS, V48), upright(C_IN, V48)
q_claim, cg_claim, r_claim, dz_claim = board.claim(Q), board.claim(C_G, rotation=CG_ROT), board.claim(R_G, rotation=R_ROT), board.claim(DZ, rotation=DZ_ROT)
tvs_claim, cin_claim = board.claim(TVS, rotation=TVS_ROT), board.claim(C_IN, rotation=CIN_ROT)

gate, ep = PadRef(Q, GATE), PadRef(Q, GND_IN)
s_w, s_e = PadRef(Q, 1), PadRef(Q, 3)                       # the source row's west and east pads
cg_gate, cg_gnd = PadRef(C_G, GATE), PadRef(C_G, GND)
r_v48, r_gate = PadRef(R_G, V48), PadRef(R_G, GATE)
dz_k, dz_a = PadRef(DZ, GATE), PadRef(DZ, GND)
tvs_k, tvs_a = PadRef(TVS, V48), PadRef(TVS, GND)
cin_v48, cin_gnd = PadRef(C_IN, V48), PadRef(C_IN, GND)
gx, _ = pad_off(Q, GATE, 0.0)
cgx, _ = pad_off(C_G, GATE, CG_ROT)
dzx, _ = pad_off(DZ, GATE, DZ_ROT)
tkx, tky = pad_off(TVS, V48, TVS_ROT)
c1x, c1y = pad_off(C_IN, V48, CIN_ROT)
epx, epy = pad_off(Q, GND_IN, 0.0)

# ---------------------------------------------------------------- placement: the FET, the gate column east, the bus parts west
board.place(Q, at=ORIGIN, rotation=0.0, why="drain pad north for the cable's V-, source row south for board ground")
COL = q_claim.right + max(cg_claim.width, r_claim.width) / 2           # the gate column's centre line: the wider of cap and resistor against the FET
board.place(C_G, at=Pin(GATE, X(gate, COL - gx + cgx), Y(gate)), rotation=CG_ROT,
            why="the gate cap point-blank east of the gate pad, its gate pad on the pad's axis")
board.place(R_G, at=Centre(X(C_G), Y(C_G, -(cg_claim.height + r_claim.height) / 2)), rotation=R_ROT,
            why="the bias resistor above the cap, gate end down into it, v48 end up to the pool's run")
board.place(DZ, at=Pin(GATE, X(gate, COL - gx + max(cg_claim.width, r_claim.width) / 2 + (dzx - dz_claim.left)), Y(gate)), rotation=DZ_ROT,
            why="the zener east of the column, cathode on the gate axis, anode down to the ground bar")
tk_w, tk_h = pad_size(TVS, V48, TVS_ROT)
ep_w, ep_h = pad_size(Q, GND_IN, 0.0)
board.place(TVS, at=Pin(V48, X(ep, -(epx - q_claim.left) - (tvs_claim.right - tkx)), Y(ep, -ep_h / 2 + tk_h / 2)), rotation=TVS_ROT,
            why="the bus TVS west of the FET, cathode up by the drain pad's top, anode down to the ground pool")
c1_w, c1_h = pad_size(C_IN, V48, CIN_ROT)
board.place(C_IN, at=Pin(V48, X(tvs_k, -(tkx - tvs_claim.left) - (cin_claim.right - c1x)), Y(tvs_k, tk_h / 2 - c1_h / 2)), rotation=CIN_ROT,
            why="the input cap west of the TVS, its v48 pad's foot on the cathode's, so one rectangle pools both")

# ---------------------------------------------------------------- copper
sw_w, s_h = pad_size(Q, 1, 0.0)
g_w, g_h = pad_size(Q, GATE, 0.0)
cg2_w, cg2_h = pad_size(C_G, GND, CG_ROT)
dzk_w, dzk_h = pad_size(DZ, GATE, DZ_ROT)
dza_w, dza_h = pad_size(DZ, GND, DZ_ROT)
ta_w, ta_h = pad_size(TVS, GND, TVS_ROT)
c2_w, c2_h = pad_size(C_IN, GND, CIN_ROT)
IN = OVER - LIP                                              # a vertex this far past a pad edge puts the copper edge OVER past it
_, cg2y = pad_off(C_G, GND, CG_ROT)
_, cg1y = pad_off(C_G, GATE, CG_ROT)
_, dzky = pad_off(DZ, GATE, DZ_ROT)
_, dzay = pad_off(DZ, GND, DZ_ROT)
_, gy = pad_off(Q, GATE, 0.0)
_, tay = pad_off(TVS, GND, TVS_ROT)
BAR_TOP = max(g_h, dzk_h) / 2 + CLR + LIP                    # the bar's top edge below the gate row: the clearance to the gate and cathode pads
BAR_BOT = max(cg2y - cg1y + cg2_h / 2, dzay - dzky + dza_h / 2,                              # past the lowest ground pad the bar swallows:
              (epy - ep_h / 2 + tk_h / 2 + tay - tky) - gy + ta_h / 2) + IN                 # the cap's, the zener's, the TVS anode's
bar_top, bar_bot = Y(gate, BAR_TOP), Y(gate, BAR_BOT)
board.pour(GND, [(X(s_w, -sw_w / 2 - IN), Y(s_w, -s_h / 2 - IN)), (X(s_e, sw_w / 2 + IN), Y(s_w, -s_h / 2 - IN)),
                 (X(s_e, sw_w / 2 + IN), bar_top), (X(dz_a, dza_w / 2 + IN), bar_top),
                 (X(dz_a, dza_w / 2 + IN), bar_bot), (X(cin_gnd, -c2_w / 2 - IN), bar_bot),
                 (X(cin_gnd, -c2_w / 2 - IN), Y(cin_gnd, -c2_h / 2 - IN)), (X(cin_gnd, c2_w / 2 + IN), Y(cin_gnd, -c2_h / 2 - IN)),
                 (X(cin_gnd, c2_w / 2 + IN), Y(tvs_a, -ta_h / 2 - IN)), (X(tvs_a, ta_w / 2 + IN), Y(tvs_a, -ta_h / 2 - IN)),
                 (X(tvs_a, ta_w / 2 + IN), bar_top), (X(s_w, -sw_w / 2 - IN), bar_top)],
           layer=F, why="the source row pooled into a bar under the gate column, west over the TVS anode, up the cap's ground pad")
board.pour(V48, [(X(cin_v48, -c1_w / 2 - IN), Y(tvs_k, -tk_h / 2 - IN)), (X(tvs_k, tk_w / 2 + IN), Y(tvs_k, -tk_h / 2 - IN)),
                 (X(tvs_k, tk_w / 2 + IN), Y(tvs_k, tk_h / 2 + IN)), (X(cin_v48, -c1_w / 2 - IN), Y(tvs_k, tk_h / 2 + IN))],
           layer=F, why="the bus pool over the TVS cathode and the input cap's v48 pad")
W48 = board.netclass(V48).track_width
run_y = Y(ep, -ep_h / 2 - CLR - W48 / 2)                     # the run's centreline clear of the drain pad's top
board.track(V48, [(X(tvs_k, tk_w / 2 - W48), Y(tvs_k)), (X(tvs_k, tk_w / 2 - W48 + tky - (-ep_h / 2 - CLR - W48 / 2) - (tky - (-ep_h / 2 - CLR - W48 / 2))), run_y),
                  (X(r_v48), run_y), r_v48],
            layer=F, width=W48, why="the bias feed from the pool over the top of the drain pad into the resistor's v48 pad")
board.track(GATE, [gate, cg_gate, dz_k], layer=F, why="the gate along its own axis into the cap pad and on to the zener")
board.track(GATE, [r_gate, cg_gate], layer=F, why="the resistor's gate end straight down into the cap pad")

board.via(GND, tvs_a, why="the ground plane in the TVS anode")
board.via(GND, cin_gnd, why="and in the input cap's ground pad")
board.via(GND, cg_gnd, why="and in the gate cap's")
board.via(GND, (X(s_w, sw_w / 2), Y(gate, (BAR_TOP + BAR_BOT) / 2)), why="two more in the bar under the source row")
board.via(GND, (X(s_e, -sw_w / 2), Y(gate, (BAR_TOP + BAR_BOT) / 2)))
board.via(V48, tvs_k, why="the bus plane in the TVS cathode")
board.via(V48, cin_v48, why="and in the input cap's v48 pad")

board.faces(handoff=Edge.NORTH, why="the cable's V- lands on the drain pad from the north; v48 pools there too")
