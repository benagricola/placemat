"""A finding: one sentence saying what a resolve could not do as declared,
and the kind of thing it is, so a run can be scored by kind (score.py).

A Finding is a `str`: everything that prints, compares or searches a
plan's findings reads it as the sentence it always was."""
from __future__ import annotations

KINDS = (
    "unplaced",         # a part, cell or block the resolve could not place
    "link_over",        # a link longer than its limit
    "fixed",            # a decided item (fixed, a cutout, a keepout) not legal where it was put
    "copper",           # planned copper that meets another net, crosses a keepout, or cannot bridge
    "label",            # a label with a part on it
    "escape_crossed",   # two escapes from one part's pins cross near its pin row
    "escape_closed",    # a pad's last route toward what it connects to is closed
    "escape_walled",    # a pad with no route out at all
    "pair_crossed",     # a differential pair's two halves cross: a swap or a turn uncrosses it
    "setup",            # the same every run of the script: an undeclared part, a layer the board lacks
)


class Finding(str):
    """The sentence, with `.kind` one of KINDS."""

    def __new__(cls, kind: str, text: str):
        if kind not in KINDS:
            raise ValueError("a finding's kind is one of %s, not %r" % (", ".join(KINDS), kind))
        self = str.__new__(cls, text)
        self.kind = kind
        return self

    def __reduce__(self):
        return Finding, (self.kind, str(self))


class Findings(list):
    """A plan's findings: a list that takes only Findings, so every sentence
    added says its kind."""

    def __init__(self, items=()):
        super().__init__()
        self.extend(items)

    @staticmethod
    def _check(item):
        if not isinstance(item, Finding):
            raise TypeError("a plan's finding says its kind: Finding(kind, text), not %r" % (item,))
        return item

    def append(self, item):
        super().append(self._check(item))

    def extend(self, items):
        super().extend(self._check(i) for i in items)

    def __iadd__(self, items):
        self.extend(items)
        return self

    def insert(self, index, item):
        super().insert(index, self._check(item))

    def by_kind(self) -> dict:
        """{kind: [finding, ...]} in the order they were found."""
        out: dict = {}
        for f in self:
            out.setdefault(f.kind, []).append(f)
        return out
