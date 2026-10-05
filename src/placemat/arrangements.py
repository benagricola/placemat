# src/placemat/arrangements.py
"""A module's alternative arrangements as declarations: the options an item may take, the units, the exclusions, the ids and the
limits.

Pure: no Board, no KiCad. `Board.alternative`, `Board.unit` and `Board.exclude` (layout.py) validate against
the board and build the records here; `enumerate_specs` turns them into the arrangements a module run lays out, the default first."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
import re

DEFAULT = "default"
NAME = re.compile(r"[a-z0-9_]+\Z")
KEYWORDS = ("at", "rotation", "rotations", "face", "radius", "step")        # what an option may change in place()
ALLOWED = KEYWORDS + ("why",)


class Alt:
    """What one member does in a unit's option, `board.alternative(unit, option, Alt(member, **keywords), ...)`: the keywords of an
    item's `board.alternative`."""
    __slots__ = ("item", "keywords")

    def __init__(self, item, **keywords):
        self.item, self.keywords = item, keywords

    def __repr__(self) -> str:
        return "Alt(%r%s)" % (self.item, "".join(", %s=%r" % kv for kv in self.keywords.items()))

    def __eq__(self, other) -> bool:
        return isinstance(other, Alt) and (self.item, self.keywords) == (other.item, other.keywords)

    __hash__ = None


@dataclass(frozen=True)
class Option:
    """What an item does in one arrangement: the place() keywords it changes (in the order given, `why` apart)."""
    item: str                   # the item's key
    name: str                   # the option's name (a unit's option's, for a member it moves)
    keywords: tuple             # ((keyword, value), ...)
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class GroupOption:
    """One option of a unit, `board.alternative(unit, name, Alt(...), ...)`: an Option for each member it moves, named as the
    option; the members it does not name keep their place()."""
    group: str
    name: str
    options: tuple              # (Option, ...)
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Group:
    """The record of a unit: members that move as one unit of a module's arrangements. (Named Group in code; every name a script
    or a message shows says unit.) `board.unit(name, *members)` declares one with its `members`, and `board.alternative(unit, ...)`
    adds each of its `alternatives`."""
    name: str
    members: tuple = ()         # the members' item keys
    alternatives: tuple = ()    # (GroupOption, ...), in declaration order
    why: str = ""
    file: str = ""
    line: int = 0

    def moves(self) -> frozenset:
        """The item keys its options move."""
        return frozenset(o.item for go in self.alternatives for o in go.options)


@dataclass(frozen=True)
class Exclusion:
    """`board.exclude(*choices)`: every combination holding all of `choices` (`item.option` or `unit.option`) is not laid out."""
    choices: tuple
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Choice:
    """One choice a unit offers: its unit's and option's names, its id in a combination, the options it lays over members'
    places, and the reasons the script gave: the option's `why` and, for a unit's option, the unit's. `item` is true for an
    item's own option."""
    unit: str
    option: str
    id: str
    overrides: tuple            # ((item key, Option), ...)
    why: str = ""
    unit_why: str = ""
    item: bool = False


@dataclass(frozen=True)
class Unit:
    """An item with options, or a unit: it contributes its default and each choice to the product."""
    name: str
    choices: tuple              # (Choice, ...)


@dataclass(frozen=True)
class Spec:
    """One arrangement a module run lays out: its id, its choices as (unit, option) pairs, the options to lay over the items'
    places, in unit order, and the ids of the choices it holds."""
    id: str
    pairs: tuple
    overrides: tuple            # ((item key, Option), ...)
    held: frozenset = frozenset()   # the choice ids (`item.option`, `unit.option`)

    @property
    def choices(self) -> dict:
        return dict(self.pairs)


DEFAULT_SPEC = Spec(DEFAULT, (), ())


@dataclass(frozen=True)
class Enumeration:
    specs: tuple                # the default first, then the combinations in product order, less the excluded
    over: dict | None           # the facts of arrangement.limit when a limit is passed; the specs are then the default alone
    declared: int               # how many arrangements the declarations make after exclusions, the default included
    excluded: tuple = ()        # ((Spec, Exclusion), ...): the combinations an exclusion leaves out, in product order


def check_name(what: str, name) -> None:
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError("%s name %r: lower-case words, digits and _ only" % (what, name))
    if name == DEFAULT:
        raise ValueError("%s name %r is the module's own layout and cannot be declared" % (what, name))


def check_keywords(who: str, keywords: dict) -> None:
    bad = sorted(set(keywords) - set(ALLOWED))
    if bad:
        raise TypeError("%s: an alternative changes where an item goes, so it takes %s, not %s; every other keyword is "
                        "the item's place() own" % (who, ", ".join(ALLOWED), ", ".join(bad)))


def merged_call(at, raw: dict, option: Option) -> dict:
    """The keywords of `place()` for an option laid over the item's own call: the call as the script made it (`at` and `raw`,
    the keywords as given), with the option's changes. A turn the option gives replaces the call's way of turning: a
    `rotation=` clears `rotations=` and a `rotations=` clears `rotation=` (a `Turned` too)."""
    call = dict(raw)
    call["at"] = at
    given = dict(option.keywords)
    if "rotation" in given and "rotations" not in given:
        call["rotations"] = ()
    if "rotations" in given and "rotation" not in given:
        call["rotation"] = None
    call.update(given)
    return call


def units(order, options: dict, groups) -> list:
    """The units in `order` (item keys and unit names, the first declared first), then each declared unit `order` does not name, in the
    order given: an item with options, or a declared unit, each as a Unit of its choices."""
    by_name = {g.name: g for g in groups}
    out = []
    for name in list(order) + [g.name for g in groups if g.name not in order]:
        g = by_name.get(name)
        if g is not None:
            out.append(Unit(g.name, tuple(Choice(g.name, go.name, "%s.%s" % (g.name, go.name), tuple((o.item, o) for o in go.options),
                                                 go.why, g.why) for go in g.alternatives)))
        elif options.get(name):
            out.append(Unit(name, tuple(Choice(name, o.name, "%s.%s" % (name, o.name), ((name, o),), o.why, item=True)
                                        for o in options[name])))
    return out


def combinations(us):
    """Every combination of the units' choices in `itertools.product` order over `us` (the first unit changing slowest), each a
    tuple of the Choices taken, the empty one (the default) first. No two units move one item (a member of a unit has no option of
    its own and is in one unit), so every combination is one."""
    for picked in itertools.product(*[(None,) + u.choices for u in us]):
        yield tuple(c for c in picked if c is not None)


def _excluded_by(combo, exclusions):
    """The first exclusion all of whose choices `combo` holds, or None."""
    ids = {c.id for c in combo}
    return next((e for e in exclusions if set(e.choices) <= ids), None)


def _named(us, ids) -> list:
    """The units, in order, that offer a choice whose id is in `ids`."""
    return [u for u in us if any(c.id in ids for c in u.choices)]


def tally(us, exclusions=()) -> tuple:
    """(kept, excluded): how many combinations the units make, the default included, less those an exclusion leaves out; and how
    many the exclusions leave out. Only the units an exclusion names are walked; each of their combinations stands for the product
    of the other units' sizes."""
    walked = _named(us, {i for e in exclusions for i in e.choices})
    walked_names = {u.name for u in walked}
    free = math.prod(1 + len(u.choices) for u in us if u.name not in walked_names)
    kept = excluded = 0
    for combo in combinations(walked):
        if _excluded_by(combo, exclusions) is None:
            kept += free
        else:
            excluded += free
    return kept, excluded


def _spec(combo) -> Spec:
    return Spec("+".join(c.id for c in combo), tuple((c.unit, c.option) for c in combo), tuple(o for c in combo for o in c.overrides),
                frozenset(c.id for c in combo))


def enumerate_specs(order, options: dict, groups, max_options: int, max_arrangements: int, exclusions=()) -> Enumeration:
    """The arrangements of a module: the default, then every combination of the units' choices (each unit contributes its default
    and each choice; `combinations` order), less those an exclusion leaves out, which are returned apart. Over either limit (a
    unit's options, its default counted; the arrangements after exclusions) nothing is partly accepted: the default alone, and
    the facts of the finding."""
    us = units(order, options, groups)
    sizes = {u.name: 1 + len(u.choices) for u in us}
    declared, excluded = tally(us, exclusions)
    wide = any(n > max_options for n in sizes.values())
    if wide or declared > max_arrangements:
        facts = {"variant": "options" if wide else "arrangements", "arrangements": declared,
                 "max_arrangements": max_arrangements, "options": sizes, "max_options": max_options, "excluded": excluded}
        return Enumeration((DEFAULT_SPEC,), facts, declared)
    specs, left_out = [DEFAULT_SPEC], []
    for combo in combinations(us):
        if not combo:
            continue
        spec, rule = _spec(combo), _excluded_by(combo, exclusions)
        if rule is None:
            specs.append(spec)
        else:
            left_out.append((spec, rule))
    return Enumeration(tuple(specs), None, declared, tuple(left_out))


def known_id(ident: str, order, options: dict, groups) -> bool:
    """Whether `ident` is an id this module's declarations make, as written, without enumerating the product (a module over its
    limit still says which ids it meant): `default`, or choice ids in unit order joined by `+`."""
    if ident == DEFAULT:
        return True
    where = {c.id: n for n, u in enumerate(units(order, options, groups)) for c in u.choices}
    last = -1
    for piece in ident.split("+"):              # the id as the script wrote it: text to check, not a record
        n = where.get(piece)
        if n is None or n <= last:
            return False
        last = n
    return True


def only_entry(entry: str):
    """The choice ids an `only=` entry names, as the script wrote it: `default` is None (the module's own layout alone), any other
    entry a frozenset of the choices joined by `+` (a choice, or a combination)."""
    return None if entry == DEFAULT else frozenset(entry.split("+"))


def only_holds(only: tuple, held: frozenset) -> bool:
    """Whether copper with `only=` exists in an arrangement holding the choice ids `held`: an empty `only=` everywhere; else the
    arrangement holds every choice of some entry, `default` matching the module's own layout alone."""
    if not only:
        return True
    for entry in only:
        need = only_entry(entry)
        if (not held) if need is None else need <= held:
            return True
    return False


def only_within(inner: tuple, outer: tuple) -> bool:
    """Whether every arrangement copper with `only=inner` exists in is one with `only=outer` too: each entry of `inner` holds
    every choice of some entry of `outer` (`default` only within `default`)."""
    if not outer:
        return True
    if not inner:
        return False
    outs = [only_entry(e) for e in outer]
    for e in inner:
        need = only_entry(e)
        if not any((o is None) if need is None else (o is not None and o <= need) for o in outs):
            return False
    return True


def entry_laid(entry: str, us, exclusions=()) -> bool:
    """Whether some combination the units make holds every choice of the `only=` entry `entry` (known_id true for it) and is not
    left out by an exclusion. Only the units the entry or an exclusion names are walked: the others can take their default."""
    need = only_entry(entry)
    if need is None:
        return True
    for combo in combinations(_named(us, need | {i for e in exclusions for i in e.choices})):
        if need <= {c.id for c in combo} and _excluded_by(combo, exclusions) is None:
            return True
    return False
