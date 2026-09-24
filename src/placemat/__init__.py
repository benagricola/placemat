"""placemat: lays out a KiCad board from a Python script.

Exports `board` (the proxy a script declares to) and the typed values a
script uses. Only placemat.kicad imports pcbnew."""
try:                                    # the git tag, written at install (pyproject: hatch-vcs)
    from ._version import __version__
except ImportError:                     # a source tree never installed: ask the metadata, else say so
    try:
        from importlib.metadata import version as _version
        __version__ = _version("placemat")
    except Exception:
        __version__ = "0+unknown"


def release(version: str) -> str:
    """The release a version builds on: 0.31.0 for 0.31.0, 0.31.0.post2.dev0+g1a2b and 0.31.0+d20260924."""
    import re
    m = re.match(r"\d+(?:\.\d+)*", version)
    return m.group(0) if m else version

from .context import board
from .cutouts import Circle, Path, Slot
from .outline import Arc
from .values import (Along, Centre, Cutout, Disc, Fraction, FreeSpot, Near, OnBore, OnEdge, OnRim, Pin, Polar, Box, Cell, CellPadRef, CopperLayer, Edge, Face, LinkWeight, Location, Mid, Net, PadRef,
                     Part, Priority, X, Y)

__all__ = ["board", "Along", "Box", "Cell", "CellPadRef", "Centre", "Pin", "Polar", "OnRim", "OnBore", "Cutout", "Disc", "Arc", "Circle", "Path", "Slot", "CopperLayer", "Edge", "Face", "Fraction",
           "FreeSpot", "LinkWeight", "Location", "Mid", "Near", "Net", "OnEdge", "PadRef", "Part", "Priority", "X", "Y"]
