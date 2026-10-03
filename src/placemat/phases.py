"""What a step is doing while it takes a while: the phases the placement search reports (`begin` events of kind `phase`).

A phase is data: a `Stage` and the numbers that go with it (`within` [k, n] of the refine pass, `hint` and `radius` of a scan, the
`face` it searches, the `firm_pass` of the resolve it is in). The engine sends exactly that; this module is the one place that
turns it into words for a reader of text (`placemat watch`, a finding), and the studio's page makes its own pill from the same
fields."""
from __future__ import annotations

from enum import Enum


class Stage(str, Enum):
    DECLARED = "declared"           # a firm item put at its declared spot
    SEEDING = "seeding"             # the hint made from the item's connections
    SCAN = "scan"                   # the scan of the board begins (`face`, `hint`, `radius`)
    COARSE = "coarse"               # a scored scan's first pass, a coarse lattice over the whole radius
    COARSE_HALF = "coarse_half"     # the same at half the stride, when the first found nothing
    FINE = "fine"                   # a pass at the scan's own step over the radius
    REFINE = "refine"               # a fine pass round one of the best coarse spots (`within` [k, n])
    GIVE_WAY = "give_way"           # the candidates refused only by carried vias are judged again, the vias giving way

    def __str__(self):
        return self.value


LABEL = {"declared": "declared", "seeding": "seeding", "scan": "scan", "coarse": "coarse", "coarse_half": "coarse (half stride)",
         "fine": "fine", "refine": "refine", "give_way": "give-way", "": "settle"}
"""A stage as one word for a person: the pass a time finding names."""


def label(stage) -> str:
    return LABEL.get(str(stage or ""), str(stage))


def text(info: dict) -> str:
    """A phase event as a sentence fragment: "refining around the best spots, 2 of 3"."""
    stage, within = str(info.get("stage") or ""), info.get("within")
    if stage == "refine":
        return "refining around the best spots" + (", %d of %d" % tuple(within) if within else "")
    if stage == "scan":
        face = info.get("face")
        return "scanning the %s" % ("front or back" if face == "either" else face or "board") + (
            ", radius %g mm" % info["radius"] if info.get("radius") is not None else "")
    return {"declared": "placing at its declared spot", "seeding": "seeding from its connections",
            "coarse": "coarse pass over the radius", "coarse_half": "coarse pass at half the stride",
            "fine": "fine pass over the radius", "give_way": "candidates giving way"}.get(stage, stage or "working")
