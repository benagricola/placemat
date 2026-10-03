"""Two switch cells of a real generation, each carrying a drawn track from the switch's ground pin to its resistor's ground
pad, which holds a via to the ground planes. The first cell stands where the script says, the others are searched in turn."""
from placemat import board, Cell, CopperLayer, Face, Location, Net

board.rect(width=60, height=60)
board.plane(Net("GND"), layers=(CopperLayer.IN1, CopperLayer.IN4))
board.plane(Net("V3V3"), layers=(CopperLayer.IN3,))
board.place(Cell("usbpd.esd"), face=Face.FRONT, at=Location(20, 30), why="stands first, so the cells after it are searched")
board.place(Cell("usbpd.sink"), face=Face.EITHER, radius=40, rotations=(0, 90, 180, 270))
board.place(Cell("usbpd.source"), face=Face.EITHER, radius=40, rotations=(0, 90, 180, 270))
