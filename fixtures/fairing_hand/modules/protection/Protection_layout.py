"""Protection: the input's reverse blocking, eFuse and current monitor.

A fragment, stamped onto the core as the cell `protect`, every part on one
face. The current runs VBIKE -> the MDDG06R10Q blocking FET -> the TPS16630
eFuse -> the 10 mOhm shunt -> VSHUNT.
Routing record: ../../../../docs/decisions/layout/protection-module-routing-2026-09-27.md.

Pins, from docs/decisions/schematics/core-netlist.xml. TPS16630: IN 1-3, P_IN 6, UVLO 7, OVP 8,
GND 9, dVdT 10, ILIM 11, MODE 12, FLT 15, PGOOD 16, OUT 18-20, EP 21.
LM74700: VCAP 1, GND 2, EN 3, CATHODE 4, GATE 5, ANODE 6. MDDG06R10Q: S 1-3,
G 4, D 5 (the exposed pad and its four leads). INA226: VS+ 6, VBUS 8, VIN- 9,
VIN+ 10.

Arrangement, after TI's layout examples (TPS1663 ZHCSIV1E figure 39,
LM74700-Q1 ZHCSHV4G figure 12-1):

Every part stands against another part: a side, a pin it is level with, or
a lane past pins. Copper is pours over the pads they join and tracks
between pads.

- The eFuse stands with IN at the top of its west column and OUT at the top
  of its east column. The FET stands north of it, turned so the drain
  faces south: one VPROT_IN zone joins the drain, IN and P_IN, and the IN
  bypass lies west of IN in that zone.
- The shunt stands upright over the OUT pins, VPROT south: a VPROT zone
  joins OUT and the shunt; the OUT bypass lies east of OUT. The FET stands a
  silk gap west of the shunt. VSHUNT leaves the shunt's north end.
- The LM74700 stands a silk gap west of the FET with ANODE, GATE and
  CATHODE facing it (TI: close to source, gate and drain). The FET's gate is
  the west end of its north row, nearest GATE; CATHODE reaches the drain.
  The charge-pump capacitor lies north of the controller, centred on it (TI:
  away from the FET), its VBIKE end in the VBIKE zone over the source row; a
  pour joins it to ANODE.
- The UVLO/OVP divider hangs west of UVLO and OVP as an upright chain, its
  top in the VPROT_IN zone; OVP reaches it down a lane beside the pin ends.
  Its foot stands upright a silk gap west of it, OVP end level with OVP's
  pin, and dVdT's capacitor upright under the foot. ILIM's resistor and
  PGOOD's pull-up stand upright east of their pins, each level with it, and
  the OUT bypass stands east of the eFuse level with OUT's middle pin, north
  of the pull-up, joined to OUT's pins by a pour (TI: at their pins, ground ends short; Ben's hand
  layout, 2026-09-30).
- The INA226 stands a silk gap east of the shunt with VIN+ and VIN- on its
  north row. The two filter resistors lie at two levels above them, the
  pin nearest the shunt lowest, shunt ends west. One filter capacitor
  across VIN+ and VIN- (TI's Figure 6-3) lies a level above them, its
  INA_P end over VIN+'s resistor, joined on In2, and its INA_N end east,
  reached from VIN-'s resistor on the component face, so the two never
  cross. The shunt
  (Yageo PE1206 on Yageo's recommended land) is sensed at its pads' inner
  edges (Kelvin): each tap is a track off its pad's inner edge, out of the
  gap between the pads to the east, all on the face. VSHUNT's runs up the
  lane nearer the shunt into VIN-'s resistor; VPROT's runs straight east
  under the monitor's body into VBUS's pin, and VIN+'s resistor branches
  off it up the outer lane. VS+'s bypass stands upright over its pin,
  inside the height the filter already takes above the monitor; the GND
  pins drop at the nearest free spots.
"""
from placemat import (board, Along, Between, Beside, Corner, CopperLayer, Cover, Edge, FreeSpot, LinkWeight, Location, Net,
                      PadRef, Part, Past, X, Y)

from fragment_frame import frame_planes

VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
CLEAR = board.netclass(Net("GND")).clearance
TRACK = board.netclass(Net("GND")).track_width
OVP_LANE = CLEAR + TRACK + CLEAR   # between the eFuse's west pin ends and the divider: OVP's track runs down it
FILLET = 0.15                 # zone corner radius
DECOUPLING_LIMIT = 2.0        # a bypass beyond this is a bulk capacitor, not a bypass
FET_ROTATION = 180            # the drain south toward the eFuse, the source-gate row north, the gate west
INA_ROTATION = 0              # VIN+, VIN-, VBUS, GND, VS+ along its north row from the west
LYING, LYING_FLIPPED, UP_PAD1_SOUTH, UP_PAD1_NORTH = 0, 180, 90, 270   # two-pad parts: pad 1 west, east, south, north
IN_TOP, P_IN, UVLO, OVP, EF_GND, DVDT, ILIM, MODE, PGOOD, OUT_TOP, OUT_BOTTOM, EP = 1, 6, 7, 8, 9, 10, 11, 12, 16, 20, 18, 21
IN_MID, IN_BOTTOM = 2, 3
OUT_MID = 19
FET_GATE, FET_DRAIN, S_EAST = 4, 5, 1        # the FET's gate, its drain pad, and the source at the row's east end
FET_SOURCES = (1, 2, 3)
VCAP_PIN, CTL_GND, EN_PIN, CATHODE, GATE, ANODE = 1, 2, 3, 4, 5, 6
INA_GND_SOUTH, INA_GND_SOUTH2, VS, INA_GND_NORTH, VBUS, VIN_N, VIN_P = 1, 2, 6, 7, 8, 9, 10


def pad(part, key):
    return PadRef(Part(part), key)


def ef(n):
    return pad("efuse", n)


board.rect(fit=True)   # the frame is the content plus the keep-in
board.place(Part("efuse"), at=Location(0, 0), rotation=0, why="the eFuse at the frame's origin; the rest from its pads")

# --- the shunt over OUT, the FET west of it ---------------------------------------
board.place(Part("r_shunt"), at=Beside(Part("efuse"), Edge.NORTH, align=ef(OUT_MID)), rotation=UP_PAD1_SOUTH,
            why="the shunt upright over OUT, VPROT south, on OUT's middle pin")
board.place(Part("q_revpol"), at=Beside(Part("r_shunt"), Edge.WEST, align=Along.END), rotation=FET_ROTATION,
            why="the FET west of the shunt, its south end level with the shunt's, drain south")

# --- the controller west of the FET -------------------------------------------------
board.place(Part("revpol"), at=Beside(Part("q_revpol"), Edge.WEST), rotation=0,
            why="the ideal-diode controller west of the FET, GATE level with the package's middle")
board.place(Part("c_rev_cap"), at=Beside(Part("revpol"), Edge.NORTH), rotation=LYING,
            why="the charge-pump capacitor north of the controller, centred on it, VBIKE east")

# --- the eFuse's own parts -----------------------------------------------------------
board.place(Part("c_vprot_in"), at=Beside(Part("revpol"), Edge.SOUTH, align=("VPROT_IN", Past([ef(IN_TOP)], Edge.WEST))),
            rotation=LYING_FLIPPED, why="the IN bypass under the controller, VPROT_IN east at IN's top pin's outer end")
board.place(Part("r_div_top"), at=Beside(Part("efuse"), Edge.WEST, align=ef(UVLO), gap=OVP_LANE), rotation=UP_PAD1_NORTH,
            why="the divider's top upright, UVLO level with its pin, a lane for OVP west of the pin ends")
board.place(Part("r_div_mid"), at=Beside(Part("r_div_top"), Edge.SOUTH), rotation=UP_PAD1_NORTH,
            why="the divider's middle under its top, joined at UVLO")
board.place(Part("r_div_bot"), at=Beside(Part("r_div_mid"), Edge.WEST, align=ef(OVP)), rotation=UP_PAD1_SOUTH,
            why="the divider's foot upright west of its middle, OVP_SET level with OVP")
board.place(Part("c_dvdt"), at=Beside(Part("r_div_bot"), Edge.SOUTH), rotation=UP_PAD1_SOUTH,
            why="dVdT's capacitor upright under the divider's foot, DVDT south")
board.place(Part("r_ilim"), at=Beside(Part("efuse"), Edge.EAST, align=ef(ILIM)), rotation=UP_PAD1_SOUTH,
            why="ILIM's resistor upright east of the eFuse, level with its pin, ground end north")
board.place(Part("r_pgood"), at=Beside(Part("efuse"), Edge.EAST, align=ef(PGOOD)), rotation=UP_PAD1_NORTH,
            why="PGOOD's pull-up upright east of the eFuse, level with its pin, 3V3 end north")
board.place(Part("c_vprot"), at=Beside(Part("efuse"), Edge.EAST, align=ef(OUT_MID)), rotation=LYING,
            why="the OUT bypass east of the eFuse, VPROT west level with OUT's middle pin")

# --- the monitor -----------------------------------------------------------------------
board.place(Part("isense"), at=Beside(Part("r_shunt"), Edge.EAST), rotation=INA_ROTATION,
            why="the monitor east of the shunt, level with it, VIN pins north")
# The filter parts over VIN+ stand a clearance west of VIN-'s pin, so VIN-'s
# rise up its pin's axis passes them.
_vin_n_past = Past([pad("isense", VIN_N)], Edge.WEST)
board.place(Part("r_ina_p"), at=Beside(Part("isense"), Edge.NORTH, align=("INA_P", _vin_n_past)), rotation=LYING,
            why="VIN+'s filter resistor over VIN+, clear of VIN-'s rise, shunt end west")
board.place(Part("r_ina_n"), at=Beside(Part("r_shunt"), Edge.NORTH), rotation=UP_PAD1_SOUTH,
            why="VIN-'s filter resistor upright on the shunt's centre line, north of it")
board.place(Part("c_ina"), at=Beside(Part("r_ina_p"), Edge.NORTH, align=("INA_P", _vin_n_past)), rotation=LYING_FLIPPED,
            why="the differential filter capacitor a level over VIN+'s resistor, INA_P over its INA_P end, INA_N west")
# VS+'s bypass stands upright over its pin, inside the height the filter
# already takes above the monitor, so the monitor's east side is the cell's.
board.place(Part("c_isense"), at=Beside(Part("isense"), Edge.NORTH, align=pad("isense", VS)), rotation=UP_PAD1_SOUTH,
            why="VS+'s bypass upright over VS+, ground north")

for part, net, host, pin in (("c_vprot_in", "VPROT_IN", "efuse", IN_MID), ("c_vprot", "VPROT", "efuse", OUT_MID),
                             ("c_isense", "V3V3", "isense", VS)):
    board.link(PadRef(Part(part), net), PadRef(Part(host), pin), weight=LinkWeight.SHORT, limit_mm=DECOUPLING_LIMIT,
               why="a bypass at its pin")

frame_planes(FILLET, component_face=False)
board.free_net(Net("GND"))
board.free_net(Net("V3V3"))


# --- copper -------------------------------------------------------------------------------
F = CopperLayer.F


def pour(net, pads):
    """One pour over these pads' copper, pulled back from every other net's."""
    board.pour(Net(net), pads, layer=F, swallow_pads=True)


def via_in(part, key, net):
    board.via(Net(net), pad(part, key), size=VIA, drill=VIA_DRILL)


# VPROT_IN: the drain, IN's pins and their bypass, one pour; P_IN and the
# divider's top down the pins' column (the two unused pins between IN
# and P_IN stay clear).
pour("VPROT_IN", [pad("q_revpol", FET_DRAIN), ef(IN_TOP), ef(IN_MID), ef(IN_BOTTOM), pad("c_vprot_in", "VPROT_IN")])
pour("VPROT_IN", [ef(IN_BOTTOM), ef(P_IN), pad("r_div_top", "VPROT_IN")])
# VPROT: OUT's pins, the shunt's VPROT end and the OUT bypass.
board.pour(Net("VPROT"), [ef(OUT_TOP), ef(OUT_BOTTOM), pad("r_shunt", "VPROT"), pad("c_vprot", "VPROT")], layer=F,
           swallow_pads=True)
# VBIKE: one pour over the FET's sources; the controller's ANODE joins its
# charge-pump capacitor's VBIKE end by a neck and senses at the sources by a
# track that rises past the gate pad's north-west corner and runs a
# clearance north of it.
pour("VBIKE", [pad("q_revpol", n) for n in FET_SOURCES])
pour("VBIKE", [pad("revpol", ANODE), pad("c_rev_cap", "VBIKE")])
board.track(Net("VBIKE"), [pad("revpol", ANODE), Past([pad("q_revpol", FET_GATE)], Corner.NW),
                           Past([pad("q_revpol", FET_GATE)], Edge.NORTH), pad("q_revpol", FET_SOURCES[-1])], layer=F)

# The controller: GATE to the gate; CATHODE to the drain; VCAP to the
# capacitor; GND down through a via in its pad. EN (REV_EN) and the eFuse's
# SHDN (EFUSE_SHDN) come from the supervisor and are left to the core's
# router.
board.track(Net("REV_GATE"), [pad("revpol", GATE), Past([pad("revpol", ANODE)], Corner.SE), pad("q_revpol", FET_GATE)],
            layer=F)   # its 45 held off ANODE's corner
board.track(Net("VPROT_IN"), [pad("revpol", CATHODE), pad("q_revpol", FET_DRAIN)], layer=F)
board.track(Net("REV_CAP"), [pad("revpol", VCAP_PIN), pad("c_rev_cap", "REV_CAP")], layer=F)
via_in("revpol", CTL_GND, "GND")

# The eFuse's settings. UVLO: the pin and the divider's two UVLO ends, one
# pour. OVP leaves its pin west through the gap between the divider middle's
# UVLO pad and GND's pin into the middle's OVP_SET pad, and on to the foot's
# through the gap between the middle's UVLO pad and dVdT's capacitor's
# ground pad. dVdT, ILIM and PGOOD run
# pin to pad.
pour("UVLO_SET", [ef(UVLO), pad("r_div_top", "UVLO_SET"), pad("r_div_mid", "UVLO_SET")])
board.track(Net("OVP_SET"), [ef(OVP), Between(pad("r_div_mid", "UVLO_SET"), ef(EF_GND)), pad("r_div_mid", "OVP_SET")],
            layer=F)
board.track(Net("OVP_SET"), [pad("r_div_mid", "OVP_SET"), Between(pad("r_div_mid", "UVLO_SET"), pad("c_dvdt", "GND")),
                             pad("r_div_bot", "OVP_SET")], layer=F)
board.track(Net("DVDT_SET"), [ef(DVDT), pad("c_dvdt", "DVDT_SET")], layer=F)
board.track(Net("ILIM_SET"), [ef(ILIM), pad("r_ilim", "ILIM_SET")], layer=F)
board.track(Net("PGOOD"), [ef(PGOOD), pad("r_pgood", "PGOOD")], layer=F)
via_in("r_pgood", "V3V3", "V3V3")
# Ground: the exposed pad's thermal array; the GND and MODE pins join it
# under the package; every ground pad drops.
board.vias(Net("GND"), ef(EP), size=VIA, drill=VIA_DRILL)
board.track(Net("GND"), [ef(EF_GND), ef(EP)], layer=F)
board.track(Net("GND"), [ef(MODE), ef(EP)], layer=F)
for part in ("c_vprot_in", "c_vprot"):
    board.vias(Net("GND"), pad(part, "GND"), size=VIA, drill=VIA_DRILL)
for part in ("r_div_bot", "c_dvdt", "r_ilim", "c_isense"):
    via_in(part, "GND", "GND")

# The monitor: Kelvin taps off the shunt pads' inner edges, where Yageo's
# PE footprint (Fig. 19) draws its sensing traces, clear of the load
# current's path through the pads' outer ends. Each tap touches its pad's
# inner edge at its east end and runs out of the gap between the pads to the
# east. VSHUNT's rises in the lane a clearance off the shunt, round the
# VSHUNT pad's corner, into VIN-'s resistor; VPROT's runs east under the
# monitor into VBUS, and a second VPROT tap runs a lane further out, past
# VSHUNT's, up to VIN+'s resistor.
_vs, _vp = pad("r_shunt", "VSHUNT"), pad("r_shunt", "VPROT")
_vs_tap = PadRef(Part("r_shunt"), "VSHUNT", edge=Edge.SOUTH, along=Along.END)
_vp_tap = PadRef(Part("r_shunt"), "VPROT", edge=Edge.NORTH, along=Along.END)
_vs_run = board.track(Net("VSHUNT"), [_vs_tap, Past([_vs], Edge.EAST, across=_vs_tap), Past([_vs], Corner.NE),
                                      pad("r_ina_n", "VSHUNT")], layer=F)
board.track(Net("VPROT"), [_vp_tap, Past([_vp], Edge.EAST, across=_vp_tap), pad("isense", VBUS)], layer=F)
board.track(Net("VPROT"), [_vp_tap, Past([_vs_run], Edge.EAST, across=_vp_tap), pad("r_ina_p", "VPROT")], layer=F)
board.track(Net("INA_P"), [pad("isense", VIN_P), pad("r_ina_p", "INA_P")], layer=F)
pour("INA_P", [pad("c_ina", "INA_P"), pad("r_ina_p", "INA_P")])
# INA_N: VIN- rises east of the filter, passes the capacitor's INA_P pad's
# north-east corner and runs west a clearance over the capacitor into its
# INA_N pad; VIN-'s resistor's INA_N end joins that pad by a pour.
board.track(Net("INA_N"), [pad("isense", VIN_N), Past([pad("c_ina", "INA_P")], Corner.NE),
                           Past([pad("c_ina", "INA_P"), pad("c_ina", "INA_N")], Edge.NORTH, across=pad("c_ina", "INA_N")),
                           pad("c_ina", "INA_N")], layer=F)
pour("INA_N", [pad("r_ina_n", "INA_N"), pad("c_ina", "INA_N")])
board.track(Net("V3V3"), [pad("isense", VS), pad("c_isense", "V3V3")], layer=F)
via_in("c_isense", "V3V3", "V3V3")
board.via(Net("GND"), FreeSpot(near=pad("isense", INA_GND_NORTH)), size=VIA, drill=VIA_DRILL)
board.track(Net("GND"), [pad("isense", INA_GND_SOUTH), pad("isense", INA_GND_SOUTH2)], layer=F)
board.via(Net("GND"), FreeSpot(near=pad("isense", INA_GND_SOUTH2)), size=VIA, drill=VIA_DRILL)
