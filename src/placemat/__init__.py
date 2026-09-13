"""placemat: lays out a KiCad board from a Python script.

Exports `board` (the proxy a script declares to) and the typed values a
script uses. Only placemat.kicad imports pcbnew."""
from .context import board
from .values import (Box, Cell, CellPadRef, CopperLayer, Edge, Face, Location, Net, PadRef, Part,
                     Priority, X, Y)

__all__ = ["board", "Box", "Cell", "CellPadRef", "CopperLayer", "Edge", "Face", "Location", "Net",
           "PadRef", "Part", "Priority", "X", "Y"]
