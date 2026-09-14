"""placemat: lays out a KiCad board from a Python script.

Exports `board` (the proxy a script declares to) and the typed values a
script uses. Only placemat.kicad imports pcbnew."""
__version__ = "0.2.0-dev"

from .context import board
from .values import (Along, Centre, Fraction, Near, OnEdge, Pin, Box, Cell, CellPadRef, CopperLayer, Edge, Face, LinkWeight, Location, Mid, Net, PadRef,
                     Part, Priority, X, Y)

__all__ = ["board", "Along", "Box", "Cell", "CellPadRef", "Centre", "Pin", "CopperLayer", "Edge", "Face", "Fraction",
           "LinkWeight", "Location", "Mid", "Near", "Net", "OnEdge", "PadRef", "Part", "Priority", "X", "Y"]
