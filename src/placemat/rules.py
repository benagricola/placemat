"""Design rules a script declares, written as KiCad custom rules
(`<board>.kicad_dru` beside the board) so KiCad's DRC judges the board by
them. A rule has one scope: inside one cell, between two nets, or on one
net; its `why` is the rule's name in KiCad, where a violation quotes it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    kind: str                   # clearance
    min_mm: float
    why: str
    within: str | None = None           # a cell (a KiCad group)
    between: tuple[str, str] | None = None
    on: str | None = None               # one net

    def condition(self) -> str:
        if self.within is not None:
            return "A.memberOf('%s') && B.memberOf('%s')" % (self.within, self.within)
        if self.between is not None:
            a, b = self.between
            return "(A.NetName == '%s' && B.NetName == '%s') || (A.NetName == '%s' && B.NetName == '%s')" % (a, b, b, a)
        return "A.NetName == '%s'" % self.on

    def text(self) -> str:
        name = self.why.replace('"', "'")
        return '(rule "%s"\n  (condition "%s")\n  (constraint %s (min %gmm)))' % (name, self.condition(), self.kind, self.min_mm)


@dataclass(frozen=True)
class KeepoutRule:
    """A keepout that admits parts by name or height, said to KiCad: its
    rule area allows footprints, and this rule forbids the parts it does not
    admit. KiCad's own area test is `intersectsArea` (`insideArea` is its
    older name)."""
    area: str                   # the rule area's zone name, as written
    refs: tuple                 # the footprints it forbids
    layer: str | None = None    # "F.Cu" or "B.Cu" for a keepout on one face

    def text(self) -> str:
        cond = ["A.intersectsArea('%s')" % self.area]
        if self.layer:
            cond.append("A.Layer == '%s'" % self.layer)
        cond.append("(%s)" % " || ".join("A.Reference == '%s'" % r for r in self.refs))
        return '(rule "%s"\n  (constraint disallow footprint)\n  (condition "%s"))' % (
            self.area.replace('"', "'"), " && ".join(cond))


def rules_text(rules) -> str:
    return "(version 1)\n" + "\n".join(r.text() for r in rules) + ("\n" if rules else "")


def write_rules(pcb_path: str, rules) -> str | None:
    """The rules file beside the board; removed when the plan declares none,
    so a stale file cannot outlive its declaration."""
    import os
    path = os.path.splitext(str(pcb_path))[0] + ".kicad_dru"
    if not rules:
        if os.path.exists(path):
            os.remove(path)
        return None
    with open(path, "w") as f:
        f.write(rules_text(rules))
    return path
