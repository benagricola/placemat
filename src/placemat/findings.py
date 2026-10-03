"""A finding: one sentence saying what a resolve could not do as declared,
and the kind of thing it is, so a run can be scored by kind (score.py).

A Finding is a `str`: everything that prints, compares or searches a
plan's findings reads it as the sentence it always was.

Each finding also carries a severity (SEVERITIES): how much it matters to a
board's being built and routed. A kind has a default (SEVERITY), and a
finding made where a kind mixes cases says its own."""
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
    "escape_lane",      # a declared escape lane (board.escape) that another net's pad, hole or copper blocks
    "pair_crossed",     # a differential pair's two halves cross: a swap or a turn uncrosses it
    "setup",            # the same every run of the script: an undeclared part, a layer the board lacks
    "route",            # an adopted route dropped because a part it joins moved: the router routes it again
    "vias",             # carried vias that gave way: shared, moved, left their pad, shortened or dropped (giveway.py)
    "fab",              # a board rule (a net class's track, clearance or via) below the fab profile's minimum
    "facts",            # the board's facts do not match what `placemat facts --confirm` last confirmed
    "needs",            # a spot placemat would have used an if-needed fab option for, and did not
    "split",            # a cell whose members form two or more groups joined only by board-level nets
)


SEVERITIES = ("notice", "warning", "critical")
"""Least to most serious. notice: placemat did something by design that the
user may want to know. warning: a quality issue the board can live with, or
one a person should judge. critical: the board cannot be built or fully
routed as it is."""

SEVERITY = {
    "unplaced": "critical",
    "link_over": "warning",
    "fixed": "critical",
    "copper": "critical",
    "label": "warning",
    "escape_crossed": "warning",
    "escape_closed": "warning",
    "escape_walled": "critical",
    "escape_lane": "warning",
    "pair_crossed": "warning",
    "setup": "warning",
    "route": "notice",
    "vias": "notice",
    "fab": "critical",
    "facts": "warning",
    "needs": "notice",
    "split": "warning",
}
"""A kind's default severity: a classification of what the kind means, not a
tunable. A finding of a kind that mixes cases is made with its own."""

DEFAULT_SEVERITY = "warning"
"""What a finding reads as where none was recorded: a run record from before
severities."""

RANK = {s: i for i, s in enumerate(SEVERITIES)}


def check_severity(severity: str) -> str:
    if severity not in RANK:
        raise ValueError("a finding's severity is one of %s, not %r" % (", ".join(SEVERITIES), severity))
    return severity


class Finding(str):
    """The sentence, with `.kind` one of KINDS and `.severity` one of
    SEVERITIES (the kind's own unless the finding says otherwise)."""

    def __new__(cls, kind: str, text: str, severity: str | None = None, case: str | None = None,
                facts: dict | None = None, suggestions=()):
        if kind not in KINDS:
            raise ValueError("a finding's kind is one of %s, not %r" % (", ".join(KINDS), kind))
        self = str.__new__(cls, text)
        self.kind = kind
        self.severity = SEVERITY[kind] if severity is None else check_severity(severity)
        self.case = case                    # "kind.case": which of a kind's situations this is (suggestions.py)
        self.facts = dict(facts or {})      # what the raising site measured, for building its suggestions
        self.suggestions = tuple(suggestions)   # changes to the script that may clear it (suggestions.Suggestion)
        return self

    def __reduce__(self):
        return Finding, (self.kind, str(self), self.severity, self.case, self.facts, self.suggestions)

    def with_suggestions(self, suggestions) -> "Finding":
        """The same finding with these suggestions."""
        return Finding(self.kind, str(self), self.severity, self.case, self.facts, suggestions)

    def line(self) -> str:
        """The sentence as a run prints it: `[critical] ...`."""
        return "[%s] %s" % (self.severity, self)


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

    def by_severity(self) -> dict:
        """{severity: count} for the severities present, most serious first."""
        out: dict = {}
        for sev in reversed(SEVERITIES):
            n = sum(1 for f in self if f.severity == sev)
            if n:
                out[sev] = n
        return out

    def most_serious_first(self) -> list:
        """The findings, most serious first, each severity in the order found."""
        return sorted(self, key=lambda f: -RANK[f.severity])

    def by_kind(self) -> dict:
        """{kind: [finding, ...]} in the order they were found."""
        out: dict = {}
        for f in self:
            out.setdefault(f.kind, []).append(f)
        return out


def summary(findings) -> str:
    """"2 critical, 1 warning, 5 notice" for the severities present, "" for none."""
    counts = Findings(findings).by_severity()
    return ", ".join("%d %s" % (n, sev) for sev, n in counts.items())
