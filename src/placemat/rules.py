"""Design rules a script declares, written as KiCad custom rules
(`<board>.kicad_dru` beside the board) so KiCad's DRC judges the board by
them. A rule has one scope: inside one cell, between two nets, or on one
net; its `why` is the rule's name in KiCad, where a violation quotes it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


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
        if self.within is not None and (self.between is not None or self.on is not None):
            # a fragment's rule over its nets, held to its cell: both items are the cell's
            return "A.memberOf('%s') && B.memberOf('%s') && (%s)" % (
                self.within, self.within, replace(self, within=None).condition())
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
                if not (owner_a and owner_b and owner_a in owners and owner_b in owners):
                    continue
                if r.between is None and r.on is None:
                    return r
            if r.between is not None:
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


RULE_PREFIX = "placemat rule "      # a User.Comments text a module fragment carries for each clearance rule it declares


def rule_note(rule) -> str:
    """A clearance rule as the text a fragment carries it in, which pcb layout stamps with the cell:
    `placemat rule clearance=0.1 between=A,B why=...`. Every value is percent-escaped, since KiCad reads
    braces and `$` in a text as markup. The rule's net and cell names are the fragment's own."""
    from urllib.parse import quote

    def q(v):
        return quote(str(v), safe="._-")
    words = ["clearance=%g" % rule.min_mm]
    if rule.within is not None:
        words.append("within=" + q(rule.within))
    if rule.between is not None:
        words.append("between=" + ",".join(q(n) for n in rule.between))
    if rule.on is not None:
        words.append("on=" + q(rule.on))
    words.append("why=" + q(rule.why))
    return RULE_PREFIX + " ".join(words)


def parse_rule_note(text: str):
    """The Rule a note says, or None for a text that is not one or does not read."""
    from urllib.parse import unquote
    if not text.startswith(RULE_PREFIX):
        return None
    fields = {}
    for word in text[len(RULE_PREFIX):].split():
        k, _, v = word.partition("=")
        fields[k] = v
    try:
        min_mm = float(fields["clearance"])
        why = unquote(fields["why"])
        between = tuple(unquote(n) for n in fields["between"].split(",")) if "between" in fields else None
        if between is not None and len(between) != 2:
            return None
        within = unquote(fields["within"]) if "within" in fields else None
        on = unquote(fields["on"]) if "on" in fields else None
    except (KeyError, ValueError):
        return None
    if (between is not None and on is not None) or (within is None and between is None and on is None):
        return None
    return Rule("clearance", min_mm, why, within=within, between=between, on=on)


def stamped_rules(geometry) -> tuple:
    """(rules, notes): the clearance rules the cells of `geometry` carry from their fragments, as this board
    names things, and a sentence for each that could not be carried. Each is held to its cell
    (`within=`, by group name) and takes the nets as pcb named them in the cell (`stamped_net`); a
    rule `within=` a cell of the fragment takes that cell's stamped group. Cells in name order, each
    fragment's rules in the order it declared them: a rule the board declares itself stands after
    these, and the last that matches decides."""
    from .board_geometry import stamped_net
    rules, notes = [], []
    for name in sorted(geometry.cells):
        cell = geometry.cells[name]
        for r in cell.rules:
            why = "%s [%s]" % (r.why, name)
            nets = [r.on] if r.on is not None else list(r.between or ())
            mapped = [stamped_net(n, name, geometry.nets) for n in nets]
            if any(m is None for m in mapped):
                notes.append("rule '%s' from the %s cell is not carried: its net %s is not on this board"
                             % (r.why, name, nets[mapped.index(None)]))
                continue
            within = name
            if r.within is not None:
                within = "%s.%s" % (name, r.within)
                if within not in geometry.cells:
                    notes.append("rule '%s' from the %s cell is not carried: its cell %s is not on this board"
                                 % (r.why, name, r.within))
                    continue
            rules.append(replace(r, why=why, within=within,
                                 on=mapped[0] if r.on is not None else None,
                                 between=tuple(mapped) if r.between is not None else None))
    return tuple(rules), tuple(notes)


@dataclass(frozen=True)
class AllowRule:
    """A keepout that lets some nets through, said to KiCad: a rule area has no list of nets, so the area
    is written allowing `types` (tracks, vias, pads) and this rule forbids them in it to every net but
    `nets`. With no `nets` it forbids them to all. KiCad judges the area's own layers."""
    area: str                   # the rule area's zone name, as written
    nets: tuple                 # the nets let through
    types: tuple                # what the area was written allowing: tracks, vias, pads

    _ITEMS = {"tracks": "track", "vias": "via", "pads": "pad"}

    def text(self) -> str:
        from .board_geometry import split_marker
        cond = ["A.intersectsArea('%s')" % self.area] + ["A.NetName != '%s'" % n for n in self.nets]
        name = "%s allows %s" % (split_marker(self.area)[0], ", ".join(self.nets) or "no net")
        items = " ".join(self._ITEMS[t] for t in self._ITEMS if t in self.types)
        return '(rule "%s"\n  (constraint disallow %s)\n  (condition "%s"))' % (
            name.replace('"', "'"), items, " && ".join(cond))


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
