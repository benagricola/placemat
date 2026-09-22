"""BrakeChopper: the machine's one regen brake chopper: a comparator with
hysteresis watching the 48 V trunk through a divider, driving a low-side
FET that puts the external dump resistor across the bus. Three bands,
because laid end to end the parts are a strip with empty corners.

The comparator's own pin order is the floorplan: on the LM393 the
output, the inverting input and the non-inverting input are three
adjacent pins on one row, so the comparator is turned to put that row
north and the front end stands on it in pin order: the bus divider on
the IN+ pin, the reference cap on the IN- pin with the bias resistor
and the shunt beside it, and the output's lane climbing east of the
reference group to the hysteresis resistor, which stands at the
divider's west end with its tap pad on the divider's rail. The middle
band carries the comparator, the gate driver a lane east of it, and the
gate loop closed in the width of one resistor: driver output, gate
resistor, FET gate and the pull-down in one rectangle at the FET's gate
corner. The 48 V dropper lies over the FET with the zener beyond it,
one lane above the driver's supply caps, which sit on the driver. The
south band has the comparator's supply cap on the VCC pin's axis, the
pull-up beside it, the status divider under them, and the diode-OR
under the driver it feeds with its pull-down beside it. Everything sits
courtyard to courtyard, and the OV_DIV tap, the highest-impedance node,
stays one rail of pads at the pin.

The dump path is the drain row and the exposed pad pooled into one
polygon, the widest copper here, which the board carries on to the
resistor's terminal. Every ground pad takes a via; v5 and v48 are the
board's rails and end at their pads; the driver's 12 V is the module's
own and stays on top copper.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, Pin, X, Y
from placemat.geometry import Transform

CMP, TL, DRV, FET, D_OR, D_Z = Part("cmp"), Part("tl"), Part("u_drv"), Part("q_chop"), Part("d_or"), Part("d_zener")
R_DIV_TOP, R_DIV_BOT, C_DIV, R_HYST = Part("r_div_top"), Part("r_div_bot"), Part("c_div_filt"), Part("r_hyst")
R_TL_BIAS, C_TL, R_PU, C_CMP = Part("r_tl_bias"), Part("c_tl_filt"), Part("r_cmp_pu"), Part("c_cmp_dec")
R_ST_TOP, R_ST_BOT, C_ST = Part("r_status_top"), Part("r_status_bot"), Part("c_status_filt")
R_OR_PD, R_ZEN, C_DRV_BULK, C_DRV_DEC, R_G, R_PD = (Part("r_or_pd"), Part("r_zener_series"), Part("c_drv_bulk"),
                                                    Part("c_drv_dec"), Part("rg"), Part("rpd"))
V48, GND, V5, CHOP, DRIVE_IN, STATUS = Net("v48"), Net("gnd"), Net("v5"), Net("chop_node"), Net("drive_in"), Net("status")
OV_DIV, OV_REF, OV_OUT, DRV_12V, DRV_OR, DRV_OUT, CHOP_GATE = (Net("OV_DIV"), Net("OV_REF"), Net("OV_OUT"), Net("DRV_12V"),
                                                              Net("DRV_OR"), Net("DRV_OUT"), Net("CHOP_GATE"))
F = CopperLayer.F
W = board.netclass(OV_DIV).track_width
CLR = board.netclass(OV_DIV).clearance
STROKE = 0.2
LIP = STROKE / 2
OVER = 0.05
IN = OVER - LIP
LANE = CLR + W + CLR                    # a track's lane between two courtyards
ORIGIN = Location(25.0, 25.0)           # the comparator's origin: a fragment's coordinates are its own
CMP_ROT, FET_ROT, TL_ROT, DOR_ROT = 180.0, 180.0, 180.0, 270.0


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


cmp_claim, tl_claim, drv_claim, fet_claim, dor_claim, dz_claim = (board.claim(CMP, rotation=CMP_ROT), board.claim(TL, rotation=TL_ROT),
                                                                  board.claim(DRV), board.claim(FET, rotation=FET_ROT),
                                                                  board.claim(D_OR, rotation=DOR_ROT), board.claim(D_Z))
r_up, r_flat, c_up, c_flat = board.claim(R_HYST, rotation=90.0), board.claim(R_HYST), board.claim(C_DIV, rotation=90.0), board.claim(C_DIV)
rt_up, rz_claim, bulk_flat = board.claim(R_DIV_TOP, rotation=90.0), board.claim(R_ZEN), board.claim(C_DRV_BULK)
cmp_out, cmp_in_neg, cmp_in_pos, cmp_vcc = PadRef(CMP, OV_OUT), PadRef(CMP, OV_REF), PadRef(CMP, OV_DIV), PadRef(CMP, V5)
drv_vdd, drv_in_pos, drv_out = PadRef(DRV, DRV_12V), PadRef(DRV, DRV_OR), PadRef(DRV, DRV_OUT)
gate, ep = PadRef(FET, CHOP_GATE), PadRef(FET, 9)
d_w, d_e = PadRef(FET, 5), PadRef(FET, 8)                     # the drain row's ends
tl_k, tl_ref = PadRef(TL, 1), PadRef(TL, 2)
dor_k, dor_out = PadRef(D_OR, DRV_OR), PadRef(D_OR, OV_OUT)
zr_v48, zr_12v = PadRef(R_ZEN, V48), PadRef(R_ZEN, DRV_12V)
_, outx = 0.0, pad_off(DRV, DRV_OUT, 0.0)[0]
rg_rot = flat(R_G, CHOP_GATE)
rgx, _ = pad_off(R_G, DRV_OUT, rg_rot)
c_cmp_rot = upright(C_CMP, V5)
_, ccm_dy = pad_off(C_CMP, V5, c_cmp_rot)
rt_rot = upright(R_DIV_TOP, V48)
_, rt_div_dy = pad_off(R_DIV_TOP, OV_DIV, rt_rot)
tlb_rot = upright(R_TL_BIAS, OV_REF)
tlb_w, tlb_h = pad_size(R_TL_BIAS, V5, tlb_rot)
_, tlb_v5_dy = pad_off(R_TL_BIAS, V5, tlb_rot)
_, tl_ref_dy = pad_off(TL, 2, TL_ROT)
_, cip_dy = pad_off(CMP, OV_DIV, CMP_ROT)
_, cvcc_dy = pad_off(CMP, V5, CMP_ROT)
CMP_TOP = cmp_claim.top - cip_dy                              # the comparator's courtyard top, above its IN+ pad
CMP_BOTTOM = cmp_claim.bottom - cvcc_dy                       # and its bottom, below its VCC pad
s_w, s_h = pad_size(FET, 1, FET_ROT)
rz_w, rz_h = pad_size(R_ZEN, V48, 0.0)

# ---------------------------------------------------------------- the middle band: comparator, driver, gate loop, FET
board.place(CMP, at=ORIGIN, rotation=CMP_ROT, why="signal row north in chain order: gnd, IN+, IN-, OUT; supply row south")
cip_dx, _ = pad_off(CMP, OV_DIV, CMP_ROT)
TL_X = cip_dx + (rt_up.width + c_up.width) / 2 + c_up.width / 2 + r_up.width + tl_claim.width / 2   # the shunt's centre from the comparator's: past the divider's top, the cap and the bias resistor
DRV_X = max(cmp_claim.width / 2 + LANE, TL_X + tl_claim.width / 2 + LANE) + drv_claim.width / 2   # the driver past the output's lane, which climbs east of the shunt
board.place(DRV, at=Centre(X(CMP, DRV_X), Y(CMP)), rotation=0.0,
            why="the gate driver east of the comparator, past the output's lane up the shunt's flank: supply and input west, output east")
board.place(R_G, at=Pin(DRV_OUT, X(drv_out, (drv_claim.right - outx) - r_flat.left + rgx), Y(drv_out)), rotation=rg_rot,
            why="the gate resistor on the driver's output row, one straight serve")
board.place(R_PD, at=Centre(X(R_G), Y(R_G, r_flat.height)), rotation=flat(R_PD, CHOP_GATE),
            why="the gate pull-down under it, gate pad east on the resistor's")
board.place(FET, at=Centre(X(R_G, (r_flat.width + fet_claim.width) / 2), Y(DRV)), rotation=FET_ROT,
            why="the FET east of the gate loop: gate pad at its north-west corner, drain row south")

# ---------------------------------------------------------------- the north band: divider, reference, hysteresis, the 12 V dropper
board.place(R_DIV_TOP, at=Pin(OV_DIV, X(cmp_in_pos), Y(cmp_in_pos, CMP_TOP + rt_up.top + rt_div_dy)), rotation=rt_rot,
            why="the divider's top on the IN+ pin's axis, its tap pad down on the rail, v48 up")
board.place(R_DIV_BOT, at=Pin(OV_DIV, X(R_DIV_TOP, -(rt_up.width + r_up.width) / 2), Y(PadRef(R_DIV_TOP, OV_DIV))), rotation=upright(R_DIV_BOT, GND),
            why="the divider's bottom beside it, tap pad on the rail, ground up")
board.place(C_DIV, at=Pin(OV_DIV, X(R_DIV_BOT, -(r_up.width + c_up.width) / 2), Y(PadRef(R_DIV_TOP, OV_DIV))), rotation=upright(C_DIV, GND),
            why="the tap's filter cap beside that, on the rail")
board.place(R_HYST, at=Pin(OV_DIV, X(C_DIV, -(c_up.width + r_up.width) / 2), Y(PadRef(R_DIV_TOP, OV_DIV))), rotation=upright(R_HYST, OV_OUT),
            why="the hysteresis resistor at the rail's west end, tap pad on the rail, its output end up to the output's lane")
board.place(C_TL, at=Centre(X(R_DIV_TOP, (rt_up.width + c_up.width) / 2), Y(cmp_in_pos, CMP_TOP - c_up.height / 2)), rotation=upright(C_TL, GND),
            why="the reference's filter cap on the IN- pin, reference pad down")
board.place(TL, at=Centre(X(C_TL, c_up.width / 2 + r_up.width + tl_claim.width / 2), Y(cmp_in_pos, CMP_TOP - tl_claim.height / 2)), rotation=TL_ROT,
            why="the shunt beyond the bias resistor, cathode and reference pads west, anode east")
board.place(R_TL_BIAS, at=Pin(V5, X(C_TL, (c_up.width + r_up.width) / 2), Y(tl_ref, -(W / 2 + CLR + tlb_h / 2))), rotation=tlb_rot,
            why="the bias resistor between cap and shunt, v5 pad up clear of the reference track, reference pad up to the cathode")
board.place(C_DRV_DEC, at=Centre(X(DRV, -(drv_claim.width - c_flat.width) / 2), Y(DRV, -(drv_claim.height + c_flat.height) / 2)), rotation=flat(C_DRV_DEC, DRV_12V),
            why="the driver's HF cap on the driver's north-west corner, 12 V pad east, ground west")
board.place(C_DRV_BULK, at=Centre(X(C_DRV_DEC, (c_flat.width + bulk_flat.width) / 2), Y(DRV, -(drv_claim.height + bulk_flat.height) / 2)),
            rotation=flat(C_DRV_BULK, GND), why="the bulk cap beside it, 12 V pads facing")
board.place(R_ZEN, at=Centre(X(FET), Y(PadRef(FET, 1), -(s_h / 2 + LANE + rz_h / 2))), rotation=0.0,
            why="the 2512 dropper over the FET, a lane above the source row for its 12 V run; v48 pad west")
board.place(D_Z, at=Pin(DRV_12V, X(zr_12v, (rz_claim.right - pad_off(R_ZEN, DRV_12V, 0.0)[0]) - dz_claim.left + pad_off(D_Z, DRV_12V, 0.0)[0]), Y(zr_12v)),
            rotation=flat(D_Z, GND), why="the zener beyond the dropper, cathode on the dropper's 12 V pad row, anode east")

# ---------------------------------------------------------------- the south band: supply cap, pull-up, status divider, diode-OR
board.place(C_CMP, at=Pin(V5, X(cmp_vcc), Y(cmp_vcc, CMP_BOTTOM - c_up.top + ccm_dy)), rotation=c_cmp_rot,
            why="the comparator's decoupler on the VCC pin's axis, v5 pad up")
board.place(R_PU, at=Centre(X(C_CMP, (c_up.width + r_flat.width) / 2), Y(C_CMP)), rotation=flat(R_PU, OV_OUT),
            why="the output pull-up beside it, v5 west, output east")
board.place(R_ST_TOP, at=Centre(X(R_PU), Y(R_PU, r_flat.height)), rotation=flat(R_ST_TOP, OV_OUT),
            why="the status divider's top under the pull-up, output pads on one column")
board.place(R_ST_BOT, at=Centre(X(R_ST_TOP, -(r_flat.width + r_up.width) / 2), Y(C_CMP, (c_up.height + r_up.height) / 2)), rotation=upright(R_ST_BOT, STATUS),
            why="its bottom standing under the supply cap, status pad up")
board.place(C_ST, at=Centre(X(R_ST_BOT, -r_up.width), Y(R_ST_BOT)), rotation=upright(C_ST, STATUS), why="the status filter beside that")
board.place(D_OR, at=Centre(X(R_ST_TOP, (r_flat.width + dor_claim.width) / 2), Y(DRV, (drv_claim.height + dor_claim.height) / 2)), rotation=DOR_ROT,
            why="the diode-OR under the driver beside the pull-up column, cathode north into the driver's input")
board.place(R_OR_PD, at=Pin(DRV_OR, X(D_OR, (dor_claim.width + r_up.width) / 2), Y(dor_k)), rotation=upright(R_OR_PD, DRV_OR),
            why="its pull-down standing east of it, merged-node pad on the cathode's row")

# ---------------------------------------------------------------- copper
OUT_LANE = X(TL, tl_claim.width / 2 + CLR + W / 2)           # the output's climb, east of the reference group
TOP_LANE = Y(TL, tl_claim.top - CLR - W / 2)                  # its run west over the north band to the hysteresis resistor
SOUTH_LANE = Y(R_ST_BOT, r_up.height / 2 + CLR + W / 2)      # its run east under the status divider to the diode-OR
board.track(OV_DIV, [PadRef(C_DIV, OV_DIV), PadRef(R_DIV_BOT, OV_DIV), PadRef(R_DIV_TOP, OV_DIV)], layer=F,
            why="the tap: three pads on one rail")
board.track(OV_DIV, [PadRef(R_HYST, OV_DIV), PadRef(C_DIV, OV_DIV)], layer=F, why="the hysteresis resistor's end of the rail")
board.track(OV_DIV, [PadRef(R_DIV_TOP, OV_DIV), cmp_in_pos], layer=F, why="straight down into the IN+ pin")
board.track(OV_REF, [cmp_in_neg, PadRef(C_TL, OV_REF)], layer=F, why="the reference cap on the IN- pin")
board.track(OV_REF, [PadRef(C_TL, OV_REF), tl_ref], layer=F, why="on to the shunt's reference pad")
board.track(OV_REF, [tl_k, tl_ref], layer=F, why="cathode and reference, one net, joined")
board.track(OV_REF, [PadRef(R_TL_BIAS, OV_REF), tl_k], layer=F, why="the bias resistor into the cathode")
board.track(V5, [cmp_vcc, PadRef(C_CMP, V5)], layer=F, why="the decoupler straight off the VCC pin")
board.track(V5, [PadRef(R_PU, V5), PadRef(C_CMP, V5)], layer=F, why="the pull-up's supply off the same pad")
board.track(OV_OUT, [cmp_out, (OUT_LANE, Y(cmp_out)), (OUT_LANE, TOP_LANE), (X(PadRef(R_HYST, OV_OUT)), TOP_LANE), PadRef(R_HYST, OV_OUT)], layer=F,
            why="the output east off its pin, up the lane past the reference group, west over the band into the hysteresis resistor")
board.track(OV_OUT, [(X(PadRef(R_PU, OV_OUT)), Y(cmp_out)), PadRef(R_PU, OV_OUT)], layer=F,
            why="and its south rail off that run, down the comparator's east flank to the pull-up")
board.track(OV_OUT, [PadRef(R_PU, OV_OUT), PadRef(R_ST_TOP, OV_OUT)], layer=F, why="on to the status divider")
board.track(OV_OUT, [PadRef(R_ST_TOP, OV_OUT), (X(PadRef(R_ST_TOP, OV_OUT)), SOUTH_LANE), (X(dor_out), SOUTH_LANE), dor_out], layer=F,
            why="and under the status divider to the diode-OR's output-side anode")
board.track(STATUS, [PadRef(R_ST_TOP, STATUS), PadRef(R_ST_BOT, STATUS), PadRef(C_ST, STATUS)], layer=F, why="the status node along the divider column")
board.track(DRV_OR, [dor_k, PadRef(R_OR_PD, DRV_OR)], layer=F, why="the merged node into its pull-down")
board.track(DRV_OR, [dor_k, drv_in_pos], layer=F, why="and up into the driver's input")
board.track(DRV_12V, [zr_12v, PadRef(D_Z, DRV_12V)], layer=F, why="the dropper's output into the zener")
LANE_12V = Y(PadRef(FET, 1), -(s_h / 2 + CLR + W / 2))       # between the FET's source row and the dropper
board.track(DRV_12V, [zr_12v, (X(zr_12v), LANE_12V), (X(PadRef(C_DRV_BULK, DRV_12V)), LANE_12V), PadRef(C_DRV_BULK, DRV_12V)], layer=F,
            why="down from the dropper's pad, west along the lane above the caps, into the bulk cap")
board.track(DRV_12V, [PadRef(C_DRV_BULK, DRV_12V), PadRef(C_DRV_DEC, DRV_12V)], layer=F, why="the two caps' 12 V pads face each other")
board.track(DRV_12V, [PadRef(C_DRV_DEC, DRV_12V), drv_vdd], layer=F, why="the HF cap down into the driver's VDD pin")
board.track(DRV_OUT, [drv_out, PadRef(R_G, DRV_OUT)], layer=F, why="the gate drive straight into its resistor")
board.track(CHOP_GATE, [PadRef(R_G, CHOP_GATE), (X(PadRef(R_G, CHOP_GATE)), Y(gate)), gate], layer=F,
            why="up the resistor's east column, then straight in on the gate pad's own row")
board.track(CHOP_GATE, [PadRef(R_G, CHOP_GATE), PadRef(R_PD, CHOP_GATE)], layer=F, why="and down into the pull-down")
dw_w, d_h = pad_size(FET, 5, FET_ROT)
ep_w, ep_h = pad_size(FET, 9, FET_ROT)
board.pour(CHOP, [(X(d_w, -dw_w / 2 - IN), Y(ep, -ep_h / 2 - IN)), (X(d_e, dw_w / 2 + IN), Y(ep, -ep_h / 2 - IN)),
                  (X(d_e, dw_w / 2 + IN), Y(d_w, d_h / 2 + IN)), (X(d_w, -dw_w / 2 - IN), Y(d_w, d_h / 2 + IN))],
           layer=F, why="the dump path: the drain row and the exposed pad in one region, the board carries it on to the resistor's terminal")

for part in (C_DIV, R_DIV_BOT, C_TL, C_CMP, R_ST_BOT, C_ST, R_OR_PD, D_Z, C_DRV_BULK, C_DRV_DEC, R_PD):
    board.via(GND, PadRef(part, GND))
board.via(GND, PadRef(TL, GND))
for n in (4, 5, 6):
    board.via(GND, PadRef(CMP, n))
board.via(GND, PadRef(DRV, 2))
board.via(GND, PadRef(DRV, 4))
for n in (1, 2, 3):
    board.via(GND, PadRef(FET, n))

board.faces(handoff=Edge.EAST, why="the dump path leaves at the FET's drain region on the east; v48 arrives at the north pads")
