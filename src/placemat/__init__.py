"""placemat: lays out a KiCad board from a Python script.

Exports `board` (the proxy a script declares to) and the typed values a
script uses. Only placemat.kicad imports pcbnew."""
__version__ = "0.25.0"      # the one version: pyproject reads it, and the plugin manifests match it

from .context import board
from .cutouts import Circle, Path, Slot
from .outline import Arc
from .values import (Along, Centre, Cutout, Disc, Fraction, FreeSpot, Near, OnBore, OnEdge, OnRim, Pin, Polar, Box, Cell, CellPadRef, CopperLayer, Edge, Face, LinkWeight, Location, Mid, Net, PadRef,
                     Part, Priority, X, Y)

__all__ = ["board", "Along", "Box", "Cell", "CellPadRef", "Centre", "Pin", "Polar", "OnRim", "OnBore", "Cutout", "Disc", "Arc", "Circle", "Path", "Slot", "CopperLayer", "Edge", "Face", "Fraction",
           "FreeSpot", "LinkWeight", "Location", "Mid", "Near", "Net", "OnEdge", "PadRef", "Part", "Priority", "X", "Y"]
