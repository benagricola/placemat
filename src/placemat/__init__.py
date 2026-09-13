"""placemat: lay out a KiCad board from a Python script.

A script imports `board` and the value types, declares what goes where, and
`placemat run` does the rest. Only `placemat.kicad` touches pcbnew.
"""
from .context import board
from .values import (Box, Cell, CellPadRef, CopperLayer, Edge, Face, Location, Net, PadRef, Part,
                     Priority, X, Y)

__all__ = ["board", "Box", "Cell", "CellPadRef", "CopperLayer", "Edge", "Face", "Location", "Net",
           "PadRef", "Part", "Priority", "X", "Y"]
