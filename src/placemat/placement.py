"""Placement: a resolved location, rotation and face for a part or cell."""
from __future__ import annotations

from dataclasses import dataclass

from .values import Face, Location


@dataclass(frozen=True, order=True)
class Placement:
    location: Location
    rotation: float = 0.0
    face: Face = Face.FRONT
    arrangement: str = ""           # a cell's: which of its module's proven layouts stands here ("" the module's own)

    def moved(self, dx: float, dy: float) -> "Placement":
        return Placement(self.location.offset(dx, dy), self.rotation, self.face, self.arrangement)

    def at(self, location: Location) -> "Placement":
        return Placement(location, self.rotation, self.face, self.arrangement)
