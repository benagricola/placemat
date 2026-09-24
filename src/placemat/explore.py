"""Exploring a layout: seeded variants of the placer's own choices for the
items in focus, scored, the best kept. See
docs/superpowers/specs/2026-09-25-explore-design.md."""
from __future__ import annotations

from dataclasses import dataclass, field

from .values import Freedom


@dataclass(frozen=True)
class Explore:
    """One variant: `seed` 0 is the plain placement; `focus` the item keys
    that may vary; `slack` how much worse than the best a drawn candidate may
    score (a fraction); `swap` the chance two focused neighbours in the
    placement order trade turns."""
    seed: int = 0
    focus: frozenset = field(default_factory=frozenset)
    slack: float = 0.25
    swap: float = 0.2


def explorable(intent) -> bool:
    """An item whose spot the scan chooses: searched from its links or round
    a Near() hint. An edge, a line, a rim, a run or a spoke slides by its own
    rule, and a decided item has nothing to choose."""
    return (intent.freedom is Freedom.SEARCHED and intent.edge is None and intent.run is None
            and intent.rim is None and intent.pin_x is None and intent.pin_y is None
            and intent.angle is None and intent.radius_at is None)


def focus_keys(board, keys=(), after_line: int | None = None, box=None, baseline=None) -> frozenset:
    """The keys of the explorable items in focus: named by key, declared at
    or after a script line, or placed inside `box` by `baseline` (a plan).
    With none of these, every explorable item."""
    pool = {i.key: i for i in board._placements() if explorable(i)}
    chosen = set()
    if keys:
        for k in keys:
            if k not in pool:
                raise KeyError("%s: no searched item by that key (explorable: %s)" % (k, ", ".join(sorted(pool))))
            chosen.add(k)
    if after_line is not None:
        chosen |= {k for k, i in pool.items() if i.line >= after_line}
    if box is not None:
        if baseline is None:
            raise ValueError("a focus box is judged on a plain run's placements: pass baseline=")
        for k in pool:
            try:
                c = baseline.box(k).center
            except (KeyError, AttributeError, TypeError):
                continue
            if box.left <= c.x <= box.right and box.top <= c.y <= box.bottom:
                chosen.add(k)
    if not keys and after_line is None and box is None:
        chosen = set(pool)
    return frozenset(chosen)
