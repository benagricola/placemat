# placemat generate: -S bom.unspecified
"""pic_programmer: the KiCad demo PIC programmer, as a reference-set script (fixtures/reference/README.md, test b).

What the board is: a two-layer through-hole programmer driven from a PC's serial port. Power comes in on a screw
terminal (P1), through a reverse-polarity diode to a 7805 (VCC, 5 V) and an LT1373 boost converter (VPP, about 13 V).
The PC's lines come in on a DB9 (J1). The target chip goes into one of five sockets (P2, P3, U5, U6, U1).

Fixed (mechanical points, at the human board's coordinates; allowed for the reference set only):
- J1, the DB9: on the west edge, its shell over the edge where the cable plugs in.
- P1, the power terminal: on the west edge, its wire entry facing out.
- P101..P106, the mounting holes: the standoff pattern.
- P2, P3, U5, U6, U1, the target sockets: where the user plugs a chip in; P3 is a ZIF socket whose lever needs its
  room. Their places are the board's user face, not a result of the circuit.
Each coordinate below is the human board's footprint origin less its top-left corner (73.66, 40.64), so that
corner is this board's origin. Rotations are the human board's.

Everything else is searched from its connections. The only relations declared are the LT1373's and the 7805's
datasheet layout rules (the capture's header lists them): the boost converter's switch-diode-capacitor path and
its switch node kept short, and C1 at the regulator output and the converter input. The ground plane under the
switcher is the LT1373's rule; it is on F.Cu, as on the original board.

Labels are the original board's silk texts for what a user plugs in, reads or adjusts.

The generate line above lets `pcb layout` build a capture with no part numbers: the import carries none, and
each part is then a `bom.unspecified` error (NOTES.md, "Skill gaps").
"""
from placemat import board, CopperLayer, Edge, Location, LinkWeight, Net, OnEdge, PadRef, Part

# The outline: the human board's Edge.Cuts rectangle, 160.02 x 99.06 mm, top-left corner at (73.66, 40.64).
board.rect(160.02, 99.06)

GND, VCC, VPP, SW = Net("GND"), Net("VCC"), Net("VPP"), Net("Net-(D10-A)")
U3, U4, L1, D10, C1, C3 = Part("U3"), Part("U4"), Part("L1"), Part("D10"), Part("C1"), Part("C3")
U4_VIN, U4_GND, U4_VSW = 5, 7, 8          # LT1373 rev B p5, pin functions

# ---------------------------------------------------------------- fixed: connectors and holes on the board's edges
# J1's shell stands 8.595 mm past the west edge and P3's lever 15.685 mm past the north edge, as on the human board:
# an edge part is placed by its reach's overhang and its body centre along the edge, which put each origin back on the
# human one (J1 at (8.94, 79.56), human (82.60, 120.20); P3 at (101.60, 10.16), human (175.26, 50.80)).
J1_OVERHANG, J1_ALONG = 8.595, 74.02          # reach west side at x = -8.595; body centre y
P3_OVERHANG, P3_ALONG = 15.685, 109.22        # reach north side (the lever) at y = -15.685; body centre x
board.place(Part("J1"), at=OnEdge(Edge.WEST, along=J1_ALONG, overhang=J1_OVERHANG), rotation=-90,
            why="mechanical: the DB9's shell over the west edge, where the serial cable plugs in")
board.place(Part("P1"), at=Location(8.14, 19.36), rotation=-90,       # human (81.80, 60.00)
            why="mechanical: the power terminal on the west edge, wire entry facing out")
board.place(Part("P106"), at=Location(3.81, 3.81), why="mechanical: mounting hole, north-west")       # human (77.47, 44.45)
board.place(Part("P105"), at=Location(85.09, 3.81), why="mechanical: mounting hole, north middle")    # human (158.75, 44.45)
board.place(Part("P104"), at=Location(156.21, 3.81), why="mechanical: mounting hole, north-east")    # human (229.87, 44.45)
board.place(Part("P101"), at=Location(3.81, 95.25), why="mechanical: mounting hole, south-west")     # human (77.47, 135.89)
board.place(Part("P102"), at=Location(85.09, 95.25), why="mechanical: mounting hole, south middle")  # human (158.75, 135.89)
board.place(Part("P103"), at=Location(156.21, 95.25), why="mechanical: mounting hole, south-east")   # human (229.87, 135.89)

# ---------------------------------------------------------------- fixed: the target sockets, the board's user face
board.place(Part("P3"), at=OnEdge(Edge.NORTH, along=P3_ALONG, overhang=P3_OVERHANG), rotation=0,
            why="mechanical: the 40-pin ZIF socket, its lever over the north edge, where the user plugs a 40-pin PIC")
board.place(Part("P2"), at=Location(133.985, 10.16), rotation=0,      # human (207.645, 50.80)
            why="mechanical: the 28-pin socket, where the user plugs a 28-pin PIC")
board.place(Part("U5"), at=Location(134.239, 67.31), rotation=0,      # human (207.899, 107.95)
            why="mechanical: the 18-pin socket, where the user plugs an 18-pin PIC")
board.place(Part("U6"), at=Location(105.41, 80.01), rotation=0,       # human (179.07, 120.65)
            why="mechanical: the 8-pin socket, where the user plugs an 8-pin PIC")
board.place(Part("U1"), at=Location(105.41, 68.58), rotation=0,       # human (179.07, 109.22)
            why="mechanical: the 8-pin socket, where the user plugs an I2C EEPROM")

# ---------------------------------------------------------------- labels: the original board's silk texts
board.label(Part("P1"), "+8/12V", side=Edge.NORTH)
board.label(Part("P3"), "PIC 40 PINS", side=Edge.NORTH)
board.label(Part("P2"), "PIC 28 PINS", side=Edge.NORTH)
board.label(Part("U5"), "PIC 18 PINS", side=Edge.SOUTH)
board.label(Part("U6"), "PIC 8 PINS", side=Edge.SOUTH)
board.label(Part("U1"), "I2C PROM", side=Edge.WEST)
board.label(Part("D8"), "VPP ON", side=Edge.EAST)
board.label(Part("D9"), "PWR ON", side=Edge.EAST)
board.label(Part("D12"), "VCC ON", side=Edge.EAST)
board.label(Part("RV1"), "13V ADJUST", side=Edge.SOUTH)

# ---------------------------------------------------------------- the boost converter's datasheet relations
board.link(PadRef(U4, U4_VSW), PadRef(D10, "Net-(D10-A)"), weight=LinkWeight.SHORT,
           why="datasheet: LT1373 rev B p10 Figure 3, switch to output diode: the nanosecond path as short as possible")
board.link(PadRef(D10, "VPP"), PadRef(C3, "VPP"), weight=LinkWeight.SHORT,
           why="datasheet: LT1373 rev B p10 Figure 3, output diode to output capacitor: the same path")
board.link(PadRef(C3, "GND"), PadRef(U4, U4_GND), weight=LinkWeight.SHORT,
           why="datasheet: LT1373 rev B p10 Figure 3, output capacitor back to the switch's ground pin: the same path")
board.link(PadRef(L1, "Net-(D10-A)"), PadRef(U4, U4_VSW), weight=LinkWeight.SHORT,
           why="datasheet: LT1373 rev B p10 Switch Node Considerations, the switch node's traces short and small")
board.link(PadRef(C1, "VCC"), PadRef(U4, U4_VIN), weight=LinkWeight.SHORT,
           why="datasheet: LT1373 rev B p5 VIN pin, bypass VIN with 10 uF or more (C1, 100 uF)")
board.link(PadRef(C1, "VCC"), PadRef(U3, "VCC"), weight=LinkWeight.SHORT,
           why="datasheet: TI SNOSBT0L 10.1, the output capacitor as close as possible to the 7805")

# ---------------------------------------------------------------- copper
board.plane(GND, layers=(CopperLayer.F,),
            why="datasheet: LT1373 rev B p5 GND pin and p10, a ground plane under the switcher; F.Cu as on the original")

# ---------------------------------------------------------------- searched: everything else, from its connections
SEARCHED = ["U2", "U3", "U4", "L1", "D10", "C1", "C2", "C3", "C4", "C5", "C9", "C6", "C7", "RV1", "JP1",
            "Q1", "Q2", "Q3", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D11", "D12",
            "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15",
            "R16", "R17", "R18", "R19", "R20", "R21"]
for ref in SEARCHED:
    board.place(Part(ref), why="capture: searched from its connections")
