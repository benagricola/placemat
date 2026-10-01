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
    of: str | None = None               # with `between=(a, b)`: only where the copper on `b` is a pad of this part and the copper on `a` is neither its pad nor a track or a via

    def condition(self) -> str:
        if self.within is not None:
            return "A.memberOf('%s') && B.memberOf('%s')" % (self.within, self.within)
        if self.between is not None:
            a, b = self.between
            if self.of is not None:
                # x on `a`; y a pad of the part on `b`. x is not the part's pad, and not a track or a via: the
                # part's own pad escapes are tracks and vias of its own nets, which no condition can tell from
                # other tracks of those nets. A.Reference is empty on a track or a via. KiCad matches a rule in
                # both orders, written out as `between` is
                def side(x, y):
                    return ("%s.NetName == '%s' && %s.NetName == '%s' && %s.Reference == '%s' && !(%s.Reference == '%s')"
                            " && %s.Type != 'Track' && %s.Type != 'Via'") % (x, a, y, b, y, self.of, x, self.of, x, x)
                return "(%s) || (%s)" % (side("A", "B"), side("B", "A"))
            return "(A.NetName == '%s' && B.NetName == '%s') || (A.NetName == '%s' && B.NetName == '%s')" % (a, b, b, a)
        return "A.NetName == '%s'" % self.on

    def text(self) -> str:
        name = self.why.replace('"', "'")
        return '(rule "%s"\n  (condition "%s")\n  (constraint %s (min %gmm)))' % (name, self.condition(), self.kind, self.min_mm)


class ClearanceRules:
    """The script's clearance rules as KiCad judges them: the clearance
    between two items is that of the LAST declared rule whose condition
    matches them, higher or lower than the netclass pair's; none matching,
    the netclass figure stands (the caller's). A `within=` rule matches when
    both items' owners are among its cell's `owners` (the cell's members'
    refs and the cell's own name, the owner of the copper it carries); an
    item with no owner, a script's declared copper, is in no cell."""

    def __init__(self, rules, cell_owners: dict):
        self.rules = tuple(r for r in rules if r.kind == "clearance")
        self.cell_owners = cell_owners          # cell name -> frozenset of owners

    def __bool__(self) -> bool:
        return bool(self.rules)

    def match(self, net_a: str, net_b: str, owner_a: str = "", owner_b: str = "",
              wire_a: bool = False, wire_b: bool = False):
        """The last rule that matches the pair, or None. `wire_*`: whether that side is a track or a via,
        which a rule of a part does not hold."""
        for r in reversed(self.rules):
            if r.within is not None:
                owners = self.cell_owners.get(r.within, ())
                if owner_a and owner_b and owner_a in owners and owner_b in owners:
                    return r
            elif r.between is not None:
                a, b = r.between
                if r.of is not None:
                    # the part's pad on b, with the copper of a that is not its pad, a track or a via
                    if (net_a == a and net_b == b and owner_b == r.of and owner_a != r.of and not wire_a) \
                            or (net_b == a and net_a == b and owner_a == r.of and owner_b != r.of and not wire_b):
                        return r
                elif (net_a == a and net_b == b) or (net_a == b and net_b == a):
                    return r
            elif r.on in (net_a, net_b):
                return r
        return None

    def native(self) -> list:
        """The rules as the native module takes them, in declaration order: (on, between, within owners, min, of)."""
        return [(r.on, r.between, sorted(self.cell_owners[r.within]) if r.within is not None else None, r.min_mm, r.of)
                for r in self.rules]

    def largest(self) -> float:
        """The most any rule asks for: what a conflict reach must cover."""
        return max((r.min_mm for r in self.rules), default=0.0)

    @classmethod
    def of(cls, geometry, rules) -> "ClearanceRules":
        """The rules over `geometry`'s cells."""
        owners = {}
        for r in rules:
            if r.kind == "clearance" and r.within is not None and r.within not in owners:
                cell = geometry.cell(r.within)
                owners[r.within] = frozenset([cell.name] + [fp.ref for fp in cell.members])
        return cls(rules, owners)


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
