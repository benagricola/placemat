"""Sources and sensitive parts, read from the parts' own fields.

`Pm.Emits` marks a part that emits something (a field, heat), `Pm.Limit` a
part that tolerates only so much of it. A source and a sensitive part pair
when they name the same kind. The model is board.push's:
value(r) = v_ref * (r_ref / r) ** falloff. This module reads the four keys
and does the frame arithmetic; layout.py turns pairs into pushes and
checks.py judges the finished board with the same numbers.

    Pm.Emits    <kind>:<value><unit>@<r>mm^<falloff>, several joined by spaces
    Pm.EmitsAt  x,y in mm in the footprint's own frame, or pad:<number>
    Pm.Limit    <kind>:<value><unit>, several joined by spaces
    Pm.SensesAt pad:<number>
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from .geometry import Transform
from .values import Face, Location

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_EMITS = re.compile(r"^([^:\s@]+):(%s)([^@\s]*)@(%s)(?:mm)?\^(%s)$" % (_NUM, _NUM, _NUM))
_LIMIT = re.compile(r"^([^:\s@]+):(%s)(\S*)$" % _NUM)
_POINT = re.compile(r"^\s*(%s)\s*,\s*(%s)\s*$" % (_NUM, _NUM))
_PAD = re.compile(r"^\s*pad:\s*(\S+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Emission:
    kind: str
    value: float
    unit: str
    r_ref: float
    falloff: float

    def at(self, r: float) -> float:
        """The value at `r` mm from the source."""
        return self.value * (self.r_ref / max(r, 1e-6)) ** self.falloff

    def radius(self, limit: float) -> float:
        """The distance inside which this emission alone exceeds `limit`;
        inf when the formula gives none that is finite."""
        try:
            return self.r_ref * (self.value / limit) ** (1.0 / self.falloff)
        except OverflowError:
            return float("inf")


@dataclass(frozen=True)
class Source:
    ref: str
    emissions: tuple
    at: tuple | None = None         # None: the footprint's origin; ("xy", x, y) in its own frame; ("pad", number)


@dataclass(frozen=True)
class Sensitive:
    ref: str
    limits: tuple                   # ((kind, value, unit), ...)
    senses: str | None = None       # a pad number; None: the body centre


@dataclass
class Annotations:
    sources: dict = field(default_factory=dict)         # refdes -> Source
    sensitives: dict = field(default_factory=dict)      # refdes -> Sensitive

    def __bool__(self) -> bool:
        return bool(self.sources or self.sensitives)


def _fields(fp) -> dict:
    return {k.lower(): v.strip() for k, v in fp.fields.items() if k.lower().startswith("pm.") and v and v.strip()}


def _pad(fp, key: str, text: str) -> str:
    m = _PAD.match(text)
    if m is None:
        raise ValueError("%s: %s %r is not pad:<number>" % (fp.ref, key, text))
    number = m.group(1)
    if not any(p.number == number for p in fp.pads):
        raise ValueError("%s: %s %r names pad %s, which the part does not have" % (fp.ref, key, text, number))
    return number


def _emissions(fp, text: str) -> tuple:
    out = []
    for word in text.split():
        m = _EMITS.match(word)
        if m is None:
            raise ValueError("%s: Pm.Emits %r is not <kind>:<value><unit>@<r>mm^<falloff> (in %r)" % (fp.ref, word, text))
        kind, value, unit, r_ref, falloff = m.group(1), float(m.group(2)), m.group(3), float(m.group(4)), float(m.group(5))
        if not (value > 0 and r_ref > 0 and falloff > 0):
            raise ValueError("%s: Pm.Emits %r needs a value, a radius and a falloff above 0" % (fp.ref, word))
        out.append(Emission(kind, value, unit, r_ref, falloff))
    return tuple(out)


def _limits(fp, text: str) -> tuple:
    out = []
    for word in text.split():
        m = _LIMIT.match(word)
        if m is None:
            raise ValueError("%s: Pm.Limit %r is not <kind>:<value><unit> (in %r)" % (fp.ref, word, text))
        value = float(m.group(2))
        if not value > 0:
            raise ValueError("%s: Pm.Limit %r needs a value above 0" % (fp.ref, word))
        out.append((m.group(1), value, m.group(3)))
    return tuple(out)


def _emits_at(fp, text: str | None):
    if text is None:
        return None
    m = _POINT.match(text)
    if m is not None:
        return ("xy", float(m.group(1)), float(m.group(2)))
    return ("pad", _pad(fp, "Pm.EmitsAt", text))


def read(geometry) -> Annotations:
    """Every source and sensitive part on the board. Raises ValueError, naming
    the part, for a value that does not parse or a pad the part lacks, and
    naming both parts for a kind given in two units."""
    out = Annotations()
    units: dict = {}            # kind -> (unit, ref, key)

    def unit_of(kind, unit, ref, key):
        first = units.setdefault(kind, (unit, ref, key))
        if first[0] != unit:
            raise ValueError("%s: %s gives %s in %r but %s: %s gives it in %r; one kind is in one unit"
                             % (ref, key, kind, unit, first[1], first[2], first[0]))

    for fp in geometry.footprints:
        f = _fields(fp)
        if "pm.emits" in f:
            emissions = _emissions(fp, f["pm.emits"])
            if emissions:
                for e in emissions:
                    unit_of(e.kind, e.unit, fp.ref, "Pm.Emits")
                out.sources[fp.ref] = Source(fp.ref, emissions, _emits_at(fp, f.get("pm.emitsat")))
        if "pm.limit" in f:
            limits = _limits(fp, f["pm.limit"])
            if limits:
                for kind, _, unit in limits:
                    unit_of(kind, unit, fp.ref, "Pm.Limit")
                senses = _pad(fp, "Pm.SensesAt", f["pm.sensesat"]) if "pm.sensesat" in f else None
                out.sensitives[fp.ref] = Sensitive(fp.ref, limits, senses)
    return out


def local_to_board(location: Location, rotation: float, face: Face, x: float, y: float) -> Location:
    """A point in a footprint's own frame, where the footprint stands: a back
    face mirrors x first, then the footprint turns by `rotation` (KiCad's
    counter-clockwise on screen, y down), then it moves to `location`."""
    t = Transform.mirror_x(Location(0, 0)) if face is Face.BACK else Transform()
    t = t.then(Transform.rotate(rotation)).then(Transform.translate(location.x, location.y))
    return t.apply_location(Location(x, y))
