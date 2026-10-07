# placemat generate: -S bom.unspecified
"""usb-c-power-adapter: Antmicro's USB-C Power Delivery Adapter, as a reference-set script (fixtures/reference/README.md,
test b).

What the board is: a 4-layer, 22 x 52.5 mm board that takes power from a USB-C PD source and gives 12 V, up to 75 W.
J1 (USB-C, power only: its data pins are not connected) brings VBUS; U1 (STUSB4500) negotiates the PD contract on CC1
and CC2 and switches VBUS onto VCC through Q1. FB1 feeds VCC to U2 (SiC477 buck), which makes +12V through L1; F1 and
J4 (Molex Nano-Fit) take it off the board. U3 and U4 (AP62301) make +5V and +3V3 from +12V for J3 (JST SH). J2 (JST SH,
Qwiic) is the I2C port that programs U1. The outline is a wide middle with a narrow tongue at each end: J1 and J2 on
the north tongue, J4 on the south one, J3 on the east side.

Fixed (mechanical points, at the human board's coordinates; allowed for the reference set only):
- J1, the USB-C receptacle: on the back, its mouth past the north edge of the north tongue, where the cable plugs in.
- J2, the Qwiic connector: on the front of the north tongue, its mouth to the north edge, where the programming cable
  plugs in.
- J3, the 5 V and 3.3 V output connector: on the back, its mouth to the east edge.
- J4, the 12 V output connector: its mouth past the south edge of the south tongue.
- MP1, the mounting hole.
Each coordinate below is the human board's footprint origin less the outline's north-west corner (81.53, 58.569).
Rotations and faces are the human board's.

Everything else is searched from its connections, on either face: the original is assembled on both. The relations
declared are the datasheets' layout rules (the capture's annotations and NOTES.md give the sources):
- SiC477 (U2): the VIN ceramics, the VCIN, VDD and VDRV capacitors and the boot RC at their pins, L1 at SW; VIN and
  SW as planes on the top layer; a ground plane on the inner layer next to the top. U2, L1 and the VIN ceramics are
  on the front, where the datasheet's layout draws them and its VIN and SW planes are.
- AP62301 (U3, U4): the input capacitor across VIN and GND, the inductor at SW, the feedback divider at FB, the output
  capacitor at GND.
- STUSB4500 (U1): the VREG_1V2 and VREG_2V7 decoupling capacitors.
- TVS2200 (U5, U7, U8) and TPD4E02B04 (U6): as close to the connector they protect as possible.
Current: the capture gives Pm.I on the input path (4.5 A), the 12 V path (6.25 A) and the 5 V and 3.3 V paths (0.5 A).

Labels are the original board's silk texts for what a user plugs in or reads.

The generate line above lets `pcb layout` build a capture whose part wrappers carry no part numbers (NOTES.md).
"""
from placemat import board, CopperLayer, Edge, Face, LinkWeight, Location, Net, OnEdge, PadRef, Part

# The outline: the human board's Edge.Cuts, north-west corner at (81.530, 58.569); widths and heights in mm.
TONGUE_W = 11.700       # both tongues' width (81.530 to 93.230)
BOARD_W = 21.882        # the middle's width (81.530 to 103.412)
STEP_N = 12.501         # the north tongue's length, to the middle's north side at y 71.071
STEP_S = 42.056         # the middle's south side, y 100.625
BOARD_H = 52.481        # to the south tongue's end, y 111.050
board.outline([(0, 0), (TONGUE_W, 0), (TONGUE_W, STEP_N), (BOARD_W, STEP_N), (BOARD_W, STEP_S),
               (TONGUE_W, STEP_S), (TONGUE_W, BOARD_H), (0, BOARD_H)])
NORTH = board.edge(facing=Edge.NORTH, outermost=True)     # the north tongue's end
SOUTH = board.edge(facing=Edge.SOUTH, outermost=True)     # the south tongue's end

GND, VCIN, SW12 = Net("GND"), Net("Net-(U2-V_{CIN})"), Net("Net-(L1-Pad1)")
J1, J2, J3, J4 = Part("J1"), Part("J2"), Part("J3"), Part("J4")
U1, U2, U3, U4, L1 = Part("U1"), Part("U2"), Part("U3"), Part("U4"), Part("L1")
U2_VCIN, U2_VIN, U2_SW, U2_VDRV, U2_VDD, U2_BOOT, U2_PHASE = 1, 7, 12, 16, 26, 4, 5   # SiC47x 77113 rev I p2, pins

# ---------------------------------------------------------------- fixed: connectors and the mounting hole
# J1's mouth and J4's mouth stand past their tongues' ends, as on the human board: an edge part is placed by its
# reach's overhang and its body centre along the run, numbers that put each origin back on the human one (J1 at
# (6.399, 2.505), human (87.929, 61.074); J4 at (5.400, 43.358), human (86.930, 101.927)). The north run starts at
# the west corner, the south run at the east corner.
J1_OVERHANG, J1_ALONG = 1.418, 6.399     # reach past the north edge; body centre from the west corner
J4_OVERHANG, J4_ALONG = 2.902, 7.551     # reach past the south edge; body centre from the east corner
board.place(J1, at=OnEdge(NORTH, along=J1_ALONG, overhang=J1_OVERHANG), rotation=180, face=Face.BACK,
            why="mechanical: the USB-C receptacle on the back, mouth past the north tongue's end, "
                "where the cable plugs in")
board.place(J2, at=Location(6.370, 4.531), rotation=180,           # human (87.900, 63.100)
            why="mechanical: the Qwiic connector on the north tongue, mouth north, "
                "where the programming cable plugs in")
board.place(J3, at=Location(18.771, 29.531), rotation=90, face=Face.BACK,   # human (100.301, 88.100)
            why="mechanical: the 5 V and 3.3 V output connector on the back, mouth to the east edge")
board.place(J4, at=OnEdge(SOUTH, along=J4_ALONG, overhang=J4_OVERHANG), rotation=0,
            why="mechanical: the 12 V output connector, its mouth past the south tongue's end")
board.place(Part("MP1"), at=Location(12.919, 17.117), rotation=0,  # human (94.449, 75.686)
            why="mechanical: the mounting hole")

# ---------------------------------------------------------------- labels: the original board's silk texts
board.label(J2, "I2C", side=Edge.SOUTH, knockout=True)
board.label([PadRef(J4, 1), PadRef(J4, 2)], ["+12V", "GND"], side=Edge.NORTH, line=J4, knockout=True)
board.label([Part("D3"), Part("D6"), Part("D7"), Part("D8"), Part("D9")], ["VBUS", "OK2", "OK3", "+5V", "+3V"],
            side=Edge.SOUTH, size=0.8, knockout=True)
board.label(Part("D4"), "12V", side=Edge.SOUTH, size=0.8, knockout=True)

# ---------------------------------------------------------------- SiC477 (U2), the 12 V buck
SIC = "datasheet: SiC47x doc 77113 rev I"
FRONT = SIC + " p20 Fig. 55 and 57: drawn on the top layer, with the VIN and SW planes"
board.place(U2, face=Face.FRONT, why=FRONT)
board.place(L1, face=Face.FRONT, why=FRONT)
board.place(Part("C3"), face=Face.FRONT, why=FRONT)
board.place(Part("C4"), face=Face.FRONT, why=FRONT)
board.place(Part("C16"), face=Face.FRONT, why=FRONT)
for ref in ("C3", "C4", "C16"):
    board.link(PadRef(Part(ref), VCIN.name), PadRef(U2, U2_VIN), weight=LinkWeight.SHORT,
               why=SIC + " p20 step 1.2: VIN ceramics between VIN and PGND, very close to the device")
board.link(PadRef(Part("C6"), VCIN.name), PadRef(U2, U2_VCIN), weight=LinkWeight.SHORT,
           why=SIC + " p2 pin 1 and p20 step 2: the VCIN capacitor close to the VCIN pin")
board.link(PadRef(Part("C1"), "/DC-DC_Converters/VDD_12V_DCDC"), PadRef(U2, U2_VDD), weight=LinkWeight.SHORT,
           why=SIC + " p20 step 4.1: the VDD capacitor between pins 26 and 23")
board.link(PadRef(Part("C2"), "/DC-DC_Converters/VDRV_12V_DCDC"), PadRef(U2, U2_VDRV), weight=LinkWeight.SHORT,
           why=SIC + " p20 step 4.2: the VDRV capacitor close to VDRV and PGND")
board.link(PadRef(Part("C10"), "Net-(U2-BOOT)"), PadRef(U2, U2_BOOT), weight=LinkWeight.SHORT,
           why=SIC + " p21 step 5: the boot RC very close, between PHASE and BOOT")
board.link(PadRef(Part("R14"), "Net-(R14-Pad2)"), PadRef(U2, U2_PHASE), weight=LinkWeight.SHORT,
           why=SIC + " p21 step 5: the boot RC very close, between PHASE and BOOT")
board.link(PadRef(L1, SW12.name), PadRef(U2, U2_SW), weight=LinkWeight.SHORT,
           why=SIC + " p20 step 3: the output inductor joined to the SW pins by a large plane")
# U2's pad 7 is drawn as two lands: the pin at the package's edge (land 1) and the VIN pad under the package (land 2,
# SiC47x p2 pin 29); the top-layer plane joins the pins at the edge.
board.pour(VCIN, [PadRef(U2, 7, land=1), PadRef(U2, 8), PadRef(Part("C3"), VCIN.name), PadRef(Part("C4"), VCIN.name),
                  PadRef(Part("C16"), VCIN.name)], layer=CopperLayer.F, swallow_pads=True,
           why=SIC + " p20 step 1.1: the VIN plane on the top layer, under the VIN ceramics")
board.pour(SW12, [PadRef(U2, 12), PadRef(U2, 13), PadRef(U2, 14), PadRef(L1, SW12.name)], layer=CopperLayer.F,
           swallow_pads=True, why=SIC + " p20 step 3: the output inductor joined to the SW pins by a large plane")
board.plane(GND, layers=(CopperLayer.IN1,),
            why=SIC + " p22 step 8: the whole inner layer next to the top a ground plane; In1, as on the original")

# ---------------------------------------------------------------- AP62301 (U3 +5V, U4 +3V3)
AP = "datasheet: AP62301 DS41958 rev 2-2 p20 Layout"


def ap62301_rules(u, c_in, l, r_fb, c_out):
    """One AP62301's layout rules: its input capacitor, inductor, feedback divider and output capacitor."""
    sw, fb = "Net-(%s-SW)" % u.inst, "Net-(%s-FB)" % u.inst
    board.link(PadRef(Part(c_in), "+12V"), PadRef(u, "+12V"), weight=LinkWeight.SHORT,
               why=AP + " 2: the input capacitor across VIN and GND, as close as possible")
    board.link(PadRef(Part(l), sw), PadRef(u, sw), weight=LinkWeight.SHORT,
               why=AP + " 3: the inductor as close to SW as possible")
    for r in r_fb:
        board.link(PadRef(Part(r), fb), PadRef(u, fb), weight=LinkWeight.SHORT,
                   why=AP + " 5: the feedback components as close to FB as possible")
    board.link(PadRef(Part(c_out), "GND"), PadRef(u, "GND"), weight=LinkWeight.SHORT,
               why=AP + " 4: the output capacitor as close to GND as possible")


ap62301_rules(U3, "C21", "L2", ("R2", "R41"), "C25")      # +5V; C21 and C25 are drawn with U3 on the sheet
ap62301_rules(U4, "C22", "L3", ("R1", "R27"), "C26")      # +3V3; C22 and C26 with U4

# ---------------------------------------------------------------- STUSB4500 (U1)
ST = "datasheet: STUSB4500 DS12499 rev 2"
board.link(PadRef(Part("C9"), "Net-(U1-VREG_1V2)"), PadRef(U1, "Net-(U1-VREG_1V2)"), weight=LinkWeight.SHORT,
           why=ST + " 2.2.13: VREG_1V2's decoupling capacitor")
board.link(PadRef(Part("C8"), "Net-(U1-VREG_2V7)"), PadRef(U1, "Net-(U1-VREG_2V7)"), weight=LinkWeight.SHORT,
           why=ST + " 2.2.15: VREG_2V7's decoupling capacitor")

# ---------------------------------------------------------------- protection at the connectors
TVS = "datasheet: TI TVS2200 SLVSED5C 9.4.1: as close to the connector as possible"
board.link(PadRef(Part("U5"), "VBUS"), PadRef(J1, "VBUS"), weight=LinkWeight.SHORT, why=TVS)
board.link(PadRef(Part("U7"), "/USB_PD/CC1"), PadRef(J1, "/USB_PD/CC1"), weight=LinkWeight.SHORT, why=TVS)
board.link(PadRef(Part("U8"), "/USB_PD/CC2"), PadRef(J1, "/USB_PD/CC2"), weight=LinkWeight.SHORT, why=TVS)
TPD = "datasheet: TI TPD4E02B04 SLVSD85B 10.1: as close to the connector as possible"
board.link(PadRef(Part("U6"), 2), PadRef(J2, "/USB_PD/SCL"), weight=LinkWeight.SHORT, why=TPD)
board.link(PadRef(Part("U6"), 4), PadRef(J2, "/USB_PD/SDA"), weight=LinkWeight.SHORT, why=TPD)

# ---------------------------------------------------------------- searched: everything else, either face
SEARCHED = [
    "C1", "C2", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13", "C14", "C15", "C17", "C18", "C19", "C20",
    "C21", "C22", "C23", "C24", "C25", "C26", "C27", "C28", "C29", "C30", "C31", "C32", "C33", "C34", "C35", "C36",
    "C37", "C38", "C39", "C40", "C41", "C42", "C43", "C44", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9",
    "F1", "FB1", "FB2", "L2", "L3", "Q1", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12",
    "R13", "R14", "R15", "R16", "R17", "R18", "R19", "R20", "R21", "R22", "R23", "R24", "R25", "R26", "R27", "R28",
    "R29", "R30", "R31", "R32", "R33", "R34", "R38", "R41", "TP1", "TP2", "TP3", "TP4", "TP5", "TP6", "TP7", "TP8",
    "TP9", "TP10", "TP11", "TP12", "TP13", "U1", "U3", "U4", "U5", "U6", "U7", "U8"]
for ref in SEARCHED:
    board.place(Part(ref), face=Face.EITHER,
                why="capture: searched from its connections; on either face, as the original board is assembled on both")
