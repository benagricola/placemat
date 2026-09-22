"""What a searched item IS, as one number: how much board its courtyard needs
and how many pins it has, both measured against the rest of this board.

PCB placement is big and complex things first, then the small ones fitted
round them. The score says which is which without a threshold anywhere: each
dimension is standardised in log space over this board's own searched items,
and the two are weighted. Log space because the range is wide - a real board
runs from an 0402 at 0.7 mm2 to a module at 116 mm2, and from 1 pin to 57 -
and standardising because it is what makes the weights mean what they say
rather than inheriting whatever spread the board happens to have.

Nothing here knows about a Board, an Occupancy or a placement. It takes
measurements and returns scores.
"""
from __future__ import annotations

import math


def pin_count(fp) -> int:
    """A footprint's pins: distinct non-empty pad NUMBERS, floored at 1.

    The datasheet's count, not the pad count. A terminal whose two legs are
    both numbered `1` is one pin; one numbered `1` and `2` is two. Pads with
    no number are mechanical or thermal and are not pins. A part with no
    numbered pads is the least complex thing on the board, not an error, and
    the floor keeps it out of log(0)."""
    return len({p.number for p in fp.pads if p.number and p.number != "?"}) or 1


def _standardise(values: list) -> list:
    """Log values as z-scores. An all-alike board has no spread, and every
    item is equally typical of it: they all score 0."""
    logs = [math.log(max(v, 1e-9)) for v in values]
    n = len(logs)
    mean = sum(logs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in logs) / n)
    if sd <= 1e-12:
        return [0.0] * n
    return [(x - mean) / sd for x in logs]


def rank_scores(items: dict, area_weight: float, pins_weight: float) -> dict:
    """{key: (courtyard area mm2, pin count)} -> {key: score}, highest first
    in the queue. Ties are exact, so equal items fall through to whatever
    orders them next."""
    if not items:
        return {}
    keys = list(items)
    za = _standardise([items[k][0] for k in keys])
    zp = _standardise([items[k][1] for k in keys])
    return {k: area_weight * za[i] + pins_weight * zp[i] for i, k in enumerate(keys)}
