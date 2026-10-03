"""A finding: what a resolve could not do as declared, as data (its kind, its cause and the facts the site measured), and the
sentence rendered from that data (finding_text.py), so a run can be scored by kind (score.py) and a suggestion can be built
from the facts.

A Finding is a `str`: everything that prints, compares or searches a plan's findings reads it as the sentence it renders.
Nothing inside placemat reads that sentence for data: the kind, the cause and the facts are fields.

Each finding also carries a severity (SEVERITIES): how much it matters to a board's being built and routed. A kind has a
default (SEVERITY), and a finding made where a kind mixes causes says its own."""
from __future__ import annotations

from enum import Enum


class FindingKind(str, Enum):
    """The category of a finding. A str-valued enum: its value is the string form that records and the console show."""
    UNPLACED = "unplaced"               # a part, cell or block the resolve could not place
    LINK_OVER = "link_over"             # a link longer than its limit
    FIXED = "fixed"                     # a decided item (fixed, a cutout, a keepout) not legal where it was put
    COPPER = "copper"                   # planned copper that meets another net, crosses a keepout, or cannot bridge
    LABEL = "label"                     # a label with a part on it
    ESCAPE_CROSSED = "escape_crossed"   # two escapes from one part's pins cross near its pin row
    ESCAPE_CLOSED = "escape_closed"     # a pad's last route toward what it connects to is closed
    ESCAPE_WALLED = "escape_walled"     # a pad with no route out at all
    ESCAPE_LANE = "escape_lane"         # a declared escape lane (board.escape) that another net's pad, hole or copper blocks
    PAIR_CROSSED = "pair_crossed"       # a differential pair's two halves cross: a swap or a turn uncrosses it
    SETUP = "setup"                     # the same every run of the script: an undeclared part, a layer the board lacks
    ROUTE = "route"                     # an adopted route dropped because a part it joins moved: the router routes it again
    VIAS = "vias"                       # carried vias that gave way: shared, moved, left their pad, shortened or dropped
    FAB = "fab"                         # a board rule (a net class's track, clearance or via) below the fab profile's minimum
    FACTS = "facts"                     # the board's facts do not match what `placemat facts --confirm` last confirmed
    NEEDS = "needs"                     # a spot placemat would have used an if-needed fab option for, and did not
    SPLIT = "split"                     # a cell whose members form two or more groups joined only by board-level nets

    def __str__(self):
        return self.value

    __format__ = str.__format__

    @classmethod
    def parse(cls, text) -> "FindingKind | None":
        """The kind a string form names, or None for one this version does not have."""
        try:
            return cls(text)
        except ValueError:
            return None


KINDS = tuple(FindingKind)


class FindingCause(str, Enum):
    """The situation a finding is about. A member carries its kind, so a cause cannot be paired with another kind; its value
    is the string form (`unplaced.search`)."""

    def __new__(cls, kind: FindingKind, text: str):
        obj = str.__new__(cls, text)
        obj._value_ = text
        obj.kind = kind
        return obj

    UNPLACED_SEARCH = (FindingKind.UNPLACED, "unplaced.search")
    UNPLACED_POCKET = (FindingKind.UNPLACED, "unplaced.pocket")
    UNPLACED_SLIDE = (FindingKind.UNPLACED, "unplaced.slide")
    UNPLACED_BLOCK = (FindingKind.UNPLACED, "unplaced.block")
    UNPLACED_BEARING = (FindingKind.UNPLACED, "unplaced.bearing")
    UNPLACED_RIDES = (FindingKind.UNPLACED, "unplaced.rides")
    LINK_OVER = (FindingKind.LINK_OVER, "link_over")
    FIXED_PART = (FindingKind.FIXED, "fixed.part")
    FIXED_CUTOUT = (FindingKind.FIXED, "fixed.cutout")
    FIXED_KEEPOUT = (FindingKind.FIXED, "fixed.keepout")
    COPPER_KEEPOUT = (FindingKind.COPPER, "copper.keepout")
    COPPER_CROSS = (FindingKind.COPPER, "copper.cross")
    COPPER_MEETS = (FindingKind.COPPER, "copper.meets")
    COPPER_NOT_DRAWN = (FindingKind.COPPER, "copper.not_drawn")
    COPPER_CORNER = (FindingKind.COPPER, "copper.corner")
    COPPER_NOTE = (FindingKind.COPPER, "copper.note")
    COPPER_STITCH = (FindingKind.COPPER, "copper.stitch")
    LABEL_SITS_ON = (FindingKind.LABEL, "label.sits_on")
    LABEL_NO_SPOT = (FindingKind.LABEL, "label.no_spot")
    LABEL_NOT_DRAWN = (FindingKind.LABEL, "label.not_drawn")
    ESCAPE_CROSSED = (FindingKind.ESCAPE_CROSSED, "escape_crossed")
    ESCAPE_CLOSED = (FindingKind.ESCAPE_CLOSED, "escape_closed")
    ESCAPE_WALLED = (FindingKind.ESCAPE_WALLED, "escape_walled")
    ESCAPE_LANE = (FindingKind.ESCAPE_LANE, "escape_lane")
    PAIR_CROSSED = (FindingKind.PAIR_CROSSED, "pair_crossed")
    SETUP_UNDECLARED = (FindingKind.SETUP, "setup.undeclared")
    SETUP_LANE_UNUSED = (FindingKind.SETUP, "setup.lane_unused")
    SETUP_PITCH = (FindingKind.SETUP, "setup.pitch")
    SETUP_WEB = (FindingKind.SETUP, "setup.web")
    SETUP_FRAME_REACH = (FindingKind.SETUP, "setup.frame_reach")
    SETUP_ACCEPT = (FindingKind.SETUP, "setup.accept")
    SETUP_LAYER_LOST = (FindingKind.SETUP, "setup.layer_lost")
    SETUP_RULE_NOTE = (FindingKind.SETUP, "setup.rule_note")
    SETUP_SETTING_RENAMED = (FindingKind.SETUP, "setup.setting_renamed")
    SETUP_LOOKAHEAD = (FindingKind.SETUP, "setup.lookahead")
    SETUP_PCBNEW = (FindingKind.SETUP, "setup.pcbnew")
    ROUTE_DROPPED = (FindingKind.ROUTE, "route.dropped")
    VIAS_GAVE_WAY = (FindingKind.VIAS, "vias.gave_way")
    VIAS_DROPPED = (FindingKind.VIAS, "vias.dropped")
    FAB_MINIMUM = (FindingKind.FAB, "fab.minimum")
    FACTS_UNCONFIRMED = (FindingKind.FACTS, "facts.unconfirmed")
    NEEDS_OPTION = (FindingKind.NEEDS, "needs.option")
    SPLIT_GROUPS = (FindingKind.SPLIT, "split.groups")

    def __str__(self):
        return self.value

    __format__ = str.__format__

    @classmethod
    def parse(cls, text) -> "FindingCause | None":
        """The cause a string form names, or None for one this version does not have (a record from a later version)."""
        try:
            return cls(text)
        except ValueError:
            return None


SEVERITIES = ("notice", "warning", "critical")
"""Least to most serious. notice: placemat did something by design that the
user may want to know. warning: a quality issue the board can live with, or
one a person should judge. critical: the board cannot be built or fully
routed as it is."""

SEVERITY = {
    FindingKind.UNPLACED: "critical",
    FindingKind.LINK_OVER: "warning",
    FindingKind.FIXED: "critical",
    FindingKind.COPPER: "critical",
    FindingKind.LABEL: "warning",
    FindingKind.ESCAPE_CROSSED: "warning",
    FindingKind.ESCAPE_CLOSED: "warning",
    FindingKind.ESCAPE_WALLED: "critical",
    FindingKind.ESCAPE_LANE: "warning",
    FindingKind.PAIR_CROSSED: "warning",
    FindingKind.SETUP: "warning",
    FindingKind.ROUTE: "notice",
    FindingKind.VIAS: "notice",
    FindingKind.FAB: "critical",
    FindingKind.FACTS: "warning",
    FindingKind.NEEDS: "notice",
    FindingKind.SPLIT: "warning",
}
"""A kind's default severity: a classification of what the kind means, not a
tunable. A finding of a kind that mixes causes is made with its own."""

DEFAULT_SEVERITY = "warning"
"""What a finding reads as where none was recorded: a run record from before
severities."""

RANK = {s: i for i, s in enumerate(SEVERITIES)}


def check_severity(severity: str) -> str:
    if severity not in RANK:
        raise ValueError("a finding's severity is one of %s, not %r" % (", ".join(SEVERITIES), severity))
    return severity


class Finding(str):
    """The sentence rendered from `.facts`, with `.kind` (a FindingKind), `.cause` (a FindingCause), `.severity` (one of
    SEVERITIES: the kind's own unless the finding says otherwise) and `.suggestions`."""

    def __new__(cls, cause: FindingCause, facts: dict | None = None, severity: str | None = None, suggestions=()):
        if not isinstance(cause, FindingCause):
            raise TypeError("a finding's cause is a FindingCause, not %r" % (cause,))
        from . import finding_text
        facts = dict(facts or {})
        self = str.__new__(cls, finding_text.render(cause, facts))
        self.cause = cause
        self.kind = cause.kind
        self.severity = SEVERITY[self.kind] if severity is None else check_severity(severity)
        self.facts = facts
        self.facts_v = finding_text.facts_version(cause)
        self.suggestions = tuple(suggestions)       # changes to the script that may clear it (suggestions.Suggestion)
        return self

    def __reduce__(self):
        return _unpickle, (self.cause, self.facts, self.severity, self.suggestions)

    def line(self) -> str:
        """The sentence as a run prints it: `[critical] ...`."""
        return "[%s] %s" % (self.severity, self)

    def detail(self) -> dict:
        """The finding as a run record and the JSON outputs carry it: its kind and cause (string forms), severity,
        sentence, facts and their version, and its bound suggestions."""
        out = {"kind": self.kind.value, "cause": self.cause.value if self.cause else None, "severity": self.severity,
               "text": str(self), "facts_v": self.facts_v, "facts": self.facts}
        bound = [s.to_json() for s in self.suggestions if s.id]
        if bound:
            out["suggestions"] = bound
        return out

    def try_lines(self) -> list:
        """What a console prints under a critical or warning finding: the best suggestion and the ids of the rest."""
        bound = [s for s in self.suggestions if s.id]
        if not bound or self.severity == "notice":
            return []
        out = ["    try %s: %s" % (bound[0].id, bound[0].text)]
        if len(bound) > 1:
            out.append("    or %s" % ", ".join(s.id for s in bound[1:]))
        return out


def _unpickle(cause, facts, severity, suggestions):
    return Finding(cause, facts, severity, suggestions)


class Findings(list):
    """A plan's findings: a list that takes only Findings, so every sentence
    added says its cause."""

    def __init__(self, items=()):
        super().__init__()
        self.extend(items)

    @staticmethod
    def _check(item):
        if not isinstance(item, Finding):
            raise TypeError("a plan's finding says its cause: Finding(cause, facts), not %r" % (item,))
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
