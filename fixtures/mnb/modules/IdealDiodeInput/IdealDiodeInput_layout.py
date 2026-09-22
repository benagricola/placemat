"""IdealDiodeInput: the LM5050-1 ideal-diode ORing controller and its 100 V
N-FET pass element (AN-2087). The FET anchors the cell: its drain row
and exposed pad north are vout, its source row and gate south are the raw
input. The controller sits under the FET's gate corner with its GATE pin
on the gate pad's axis; the ground diode lies east of the FET so its gnd
pad faces the vout block and its floating-ground pad faces east; the
input diode lies along the south inside the input lobe; the VS bias
resistor and its cap stand east of the controller; the bus TVS rides
the east end of the vout tongue. Everything sits courtyard to courtyard.

The pass path is two filled polygons the module owns: the input block
over the source row with a lobe south to the input diode, and the vout
block over the drain row and the exposed pad with a tongue east carrying
the TVS. The controller's IN pin reads the input block beside the FET;
its OUT pin is Kelvin'd by a track that climbs between the FET and the
ground diode straight into the drain pad, so the Vds sense reads the
FET's own pad. The VS bias resistor hangs off the vout plane by a via in
its pad, the same node the OUT pin senses. The floating ground pools the controller's
two pads and one diagonal to the ground diode, and a polygon joins the
two diodes' floating pads round the VS block. vout, which the module
produces, takes vias in the exposed pad and the TVS and bias pads;
every ground pad takes one. The raw input and the local nets end at
their pads for the board.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Mid, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

Q, U, D_GND, D_IN, TVS, C_IN, R_VS, C_VS = (Part("fet"), Part("ctrl"), Part("d_gnd"), Part("d_in"), Part("tvs"),
                                          Part("cin_raw"), Part("vs_r"), Part("vs_c"))
VIN, VOUT, GND, GATE, GND_F, VS = Net("vin_raw"), Net("vout"), Net("gnd"), Net("GATE"), Net("GND_FLOAT"), Net("VS")
F = CopperLayer.F
W = board.netclass(GATE).track_width
STROKE = 0.2                            # a pour's outline stroke: copper reaches half of it past each vertex
LIP = STROKE / 2
OVER = 0.05                             # how far a pour's copper edge goes past a pad it swallows
IN = OVER - LIP                         # a vertex this far past a pad edge puts the copper edge OVER past it
HV_CLR = 0.25                           # the strictest clearance a consuming board applies to vin_raw and vout: the 48 V class
CLR = board.netclass(GATE).clearance    # copper to a foreign pad on the logic nets
CH = 0.6                                # a pour's chamfer where a lobe turns
ORIGIN = Location(150.0, 103.0)         # the FET's origin: a fragment's coordinates are its own
U_ROT, D_ROT, TVS_ROT = 0.0, 0.0, 0.0


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


CIN_ROT, RVS_ROT, CVS_ROT = upright(C_IN, VIN), upright(R_VS, VOUT), upright(C_VS, GND)
DG_ROT, DI_ROT, TVS_ROT = flat(D_GND, GND_F), flat(D_IN, GND_F), flat(TVS, GND)
q_claim, u_claim = board.claim(Q), board.claim(U, rotation=U_ROT)
dg_claim, di_claim, tvs_claim = board.claim(D_GND, rotation=DG_ROT), board.claim(D_IN, rotation=DI_ROT), board.claim(TVS, rotation=TVS_ROT)
cin_claim, rvs_claim, cvs_claim = board.claim(C_IN, rotation=CIN_ROT), board.claim(R_VS, rotation=RVS_ROT), board.claim(C_VS, rotation=CVS_ROT)

q_gate, ep = PadRef(Q, GATE), PadRef(Q, 9)
s_w, s_e, d_w = PadRef(Q, 1), PadRef(Q, 3), PadRef(Q, 8)              # the source row's ends, the drain row's west pad
u_gate, u_in, u_out, u_vs = PadRef(U, GATE), PadRef(U, VIN), PadRef(U, VOUT), PadRef(U, VS)
u_gf_n, u_gf_s = PadRef(U, 3), PadRef(U, 2)                           # the controller's two floating-ground pads
dg_gnd, dg_f = PadRef(D_GND, GND), PadRef(D_GND, GND_F)
di_vin, di_f = PadRef(D_IN, VIN), PadRef(D_IN, GND_F)
tvs_v, tvs_g = PadRef(TVS, VOUT), PadRef(TVS, GND)
cin_v, cin_g = PadRef(C_IN, VIN), PadRef(C_IN, GND)
r_vout, r_vs, c_vs, c_gnd = PadRef(R_VS, VOUT), PadRef(R_VS, VS), PadRef(C_VS, VS), PadRef(C_VS, GND)
qgx, qgy = pad_off(Q, GATE, 0.0)
ugx, ugy = pad_off(U, GATE, U_ROT)
epx, epy = pad_off(Q, 9, 0.0)
dgx, dgy = pad_off(D_GND, GND, DG_ROT)
dix, diy = pad_off(D_IN, VIN, DI_ROT)
tvx, tvy = pad_off(TVS, VOUT, TVS_ROT)
cvx, cvy = pad_off(C_IN, VIN, CIN_ROT)
rvx, rvy = pad_off(R_VS, VS, RVS_ROT)
cvsx, cvsy = pad_off(C_VS, VS, CVS_ROT)
_, uvsy = pad_off(U, VS, U_ROT)

# ---------------------------------------------------------------- placement
g_w, g_h = pad_size(Q, GATE, 0.0)
ep_w, ep_h = pad_size(Q, 9, 0.0)
sw_w, s_h = pad_size(Q, 1, 0.0)
dw_w, d_h = pad_size(Q, 8, 0.0)
dg_w, dg_h = pad_size(D_GND, GND, DG_ROT)
dgf_w, dgf_h = pad_size(D_GND, GND_F, DG_ROT)
di_w, di_h = pad_size(D_IN, VIN, DI_ROT)
dif_w, dif_h = pad_size(D_IN, GND_F, DI_ROT)
tv_w, tv_h = pad_size(TVS, VOUT, TVS_ROT)
ci_w, ci_h = pad_size(C_IN, VIN, CIN_ROT)
cg_w, cg_h = pad_size(C_VS, GND, CVS_ROT)
uin_w, uin_h = pad_size(U, VIN, U_ROT)
uvs_w, uvs_h = pad_size(U, VS, U_ROT)
GATE_LANE = uin_w / 2 + CLR + W / 2                  # east of the controller's west pad column: the gate's climb under the body
KELVIN_LANE = GATE_LANE + W + CLR                    # beside it: the OUT sense's climb
D_GND_PAD = KELVIN_LANE + W / 2 + CLR                # the ground diode's gnd pad edge past the sense lane

board.place(Q, at=ORIGIN, rotation=0.0, why="drain row and exposed pad north (vout), source row and gate south (the raw input)")
board.place(U, at=Pin(GATE, X(q_gate), Y(q_gate, (q_claim.bottom - qgy) - u_claim.top + ugy)), rotation=U_ROT,
            why="the controller under the FET's gate corner, its GATE pin on the gate pad's axis, courtyards touching")
board.place(TVS, at=Pin(VOUT, X(q_gate, (q_claim.right - qgx) - tvs_claim.left + tvx), Y(d_w)), rotation=TVS_ROT,
            why="the bus TVS east of the FET on the drain row's line, vout pad west on the tongue, ground east")
board.place(D_GND, at=Pin(GND, X(q_gate, D_GND_PAD + dg_w / 2), Y(tvs_v, -tvy + tvs_claim.bottom - dg_claim.top + dgy)), rotation=DG_ROT,
            why="the ground diode under the TVS, its gnd pad past the sense lane facing the vout block, floating pad east")
board.place(C_IN, at=Pin(VIN, X(Mid(s_w, s_e)), Y(q_gate, (q_claim.bottom - qgy) - cin_claim.top + cvy)), rotation=CIN_ROT,
            why="the input cap under the source row's middle, input pad up into the block, ground down")
board.place(D_IN, at=Pin(VIN, X(cin_v, (cin_claim.right - cvx) - di_claim.left + dix), Y(u_gate, (u_claim.bottom - ugy) - di_claim.top + diy)),
            rotation=DI_ROT, why="the input diode along the south under the controller, beside the input cap, its input pad in the lobe")
board.place(R_VS, at=Centre(X(U, (u_claim.width + rvs_claim.width) / 2), Y(U)), rotation=RVS_ROT,
            why="the bias resistor east of the controller on its centre line, VS pad down on the VS pin's row, vout pad up to its plane via")
board.place(C_VS, at=Centre(X(R_VS, (rvs_claim.width + cvs_claim.width) / 2), Y(R_VS)), rotation=CVS_ROT,
            why="its cap beside it, VS pads on one line, ground up")
_, uvsy = pad_off(U, VS, U_ROT)

# ---------------------------------------------------------------- the pass path: two polygons
board.pour(VIN, [(X(s_w, -sw_w / 2 - IN), Y(s_w, -s_h / 2 - IN)),
                 (X(q_gate, -g_w / 2 - HV_CLR - LIP), Y(s_w, -s_h / 2 - IN)),
                 (X(q_gate, -g_w / 2 - HV_CLR - LIP), Y(di_vin, -di_h / 2 - IN - CH)),
                 (X(q_gate, -g_w / 2 - HV_CLR - LIP + CH), Y(di_vin, -di_h / 2 - IN)),
                 (X(di_vin, di_w / 2 + IN), Y(di_vin, -di_h / 2 - IN)),
                 (X(di_vin, di_w / 2 + IN), Y(di_vin, di_h / 2 + IN)),
                 (X(di_vin, -di_w / 2 - IN), Y(di_vin, di_h / 2 + IN)),
                 (X(di_vin, -di_w / 2 - IN), Y(cin_v, ci_h / 2 + IN + CH)),
                 (X(di_vin, -di_w / 2 - IN - CH), Y(cin_v, ci_h / 2 + IN)),
                 (X(s_w, -sw_w / 2 - IN), Y(cin_v, ci_h / 2 + IN))],
           layer=F, why="the input block over the source row and the cap, its lobe south to the input diode")
board.pour(VOUT, [(X(d_w, -dw_w / 2 - IN), Y(tvs_v, -tv_h / 2 - IN)),
                  (X(tvs_v, tv_w / 2 + IN), Y(tvs_v, -tv_h / 2 - IN)),
                  (X(tvs_v, tv_w / 2 + IN), Y(tvs_v, tv_h / 2 + IN)),
                  (X(ep, ep_w / 2 + IN), Y(tvs_v, tv_h / 2 + IN)),
                  (X(ep, ep_w / 2 + IN), Y(ep, ep_h / 2 + IN)),
                  (X(d_w, -dw_w / 2 - IN), Y(ep, ep_h / 2 + IN))],
            layer=F, why="the vout block over the drain row and the exposed pad, its tongue east carrying the TVS")
board.pour(GND_F, [(X(di_f, -dif_w / 2 - IN), Y(di_f, dif_h / 2 + IN)),
                   (X(dg_f, dgf_w / 2 + IN), Y(di_f, dif_h / 2 + IN)),
                   (X(dg_f, dgf_w / 2 + IN), Y(dg_f, -dgf_h / 2 - IN)),
                   (X(c_gnd, cg_w / 2 + CLR + LIP), Y(dg_f, -dgf_h / 2 - IN)),
                   (X(c_gnd, cg_w / 2 + CLR + LIP), Y(di_f, -dif_h / 2 - IN - CH)),
                   (X(c_gnd, cg_w / 2 + CLR + LIP - CH), Y(di_f, -dif_h / 2 - IN)),
                   (X(di_f, -dif_w / 2 - IN), Y(di_f, -dif_h / 2 - IN))],
           layer=F, why="the floating ground joining the two diodes' pads round the VS block")

# ---------------------------------------------------------------- tracks
board.track(GATE, [u_gate, (X(u_gate, GATE_LANE), Y(u_gate)), (X(u_gate, GATE_LANE), Y(q_gate, g_h / 2 + CLR + W / 2)), q_gate],
            layer=F, why="the gate drive east off its pin, up the lane under the controller, onto the gate pad's row")
board.track(VIN, [u_in, (X(q_gate, -g_w / 2 - HV_CLR - LIP - W), Y(u_in))], layer=F,
            why="the IN sense west along the pin's axis into the input block beside the FET")
board.track(VOUT, [u_out, (X(u_gate, KELVIN_LANE), Y(u_out)), (X(u_gate, KELVIN_LANE), Y(u_in, -uin_h / 2 - CLR - W / 2)),
                   (X(ep, ep_w / 2 - W), Y(ep))],
            layer=F, why="the OUT Kelvin sense: up the lane beside the gate's, between the FET and the ground diode, into the drain pad itself")
board.track(VS, [u_vs, r_vs], layer=F, why="the VS pin east along its row into the resistor's VS pad")
board.track(VS, [r_vs, c_vs], layer=F, why="and across to its cap")
board.track(GND_F, [u_gf_s, u_gf_n], layer=F, why="the controller's two floating-ground pads pooled")
board.track(GND_F, [u_gf_n, dg_f], layer=F, why="one diagonal to the ground diode's floating pad")

# ---------------------------------------------------------------- vias: vout, which the module produces, and every ground
board.via(VOUT, ep, why="the exposed pad: vout enters its plane where the FET makes it")
board.via(VOUT, (X(ep, -ep_w / 4), Y(ep, -ep_h / 4)))
board.via(VOUT, (X(ep, ep_w / 4), Y(ep, -ep_h / 4)))
board.via(VOUT, tvs_v, why="the TVS on the tongue")
board.via(VOUT, r_vout, why="the bias resistor fed from the vout plane: the datasheet's OUT-to-VS tap, taken at the plane the OUT pin senses")
board.via(GND, cin_g)
board.via(GND, c_gnd)
board.via(GND, dg_gnd)
board.via(GND, tvs_g)

board.faces(handoff=Edge.NORTH, why="vout leaves on the block and tongue to the north; the raw input arrives west and south")
