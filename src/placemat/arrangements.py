# src/placemat/arrangements.py
"""A module's alternative arrangements as declarations: the options an item may take, the units, the exclusions, the ids and the
limits.

Pure: no Board, no KiCad. `Board.alternative`, `Board.unit`, `Board.arrangement` and `Board.exclude` (layout.py) validate against
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
    """One member's option inside `board.arrangement(name, Alt(item, **keywords), ...)`: the keywords of `board.alternative`."""
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
    name: str                   # the option's name, or the group's for a group's member
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
    adds each of its `alternatives`. `board.arrangement(name, *alts)`, the 0.99.15 form, is a unit with one option named as the
    unit, its members' options in `options`: its id is the unit's name alone."""
    name: str
    options: tuple = ()         # the 0.99.15 form: (Option, ...), one per member its one option moves
    why: str = ""
    file: str = ""
    line: int = 0
    members: tuple = ()         # board.unit: the members' item keys
    alternatives: tuple = ()    # board.unit: (GroupOption, ...), in declaration order

    @property
    def positional(self) -> bool:
        """The 0.99.15 form (board.arrangement)."""
        return not self.members

    def unit_options(self) -> tuple:
        """Its options as GroupOption: the 0.99.15 form's one, named as the unit, or board.unit's."""
        if self.positional:
            return (GroupOption(self.name, self.name, self.options, self.why, self.file, self.line),)
        return self.alternatives

    def moves(self) -> frozenset:
        """The item keys its options move."""
        return frozenset(o.item for go in self.unit_options() for o in go.options)


@dataclass(frozen=True)
class Exclusion:
    """`board.exclude(*choices)`: every combination holding all of `choices` (`item.option`, `unit.option`, or a 0.99.15 board.arrangement's
    name) is not laid out."""
    choices: tuple
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Choice:
    """One choice a unit offers: its unit's and option's names, its id in a combination, and the options it lays over members'
    places."""
    unit: str
    option: str
    id: str
    overrides: tuple            # ((item key, Option), ...)


@dataclass(frozen=True)
class Unit:
    """An item with options, or a unit: it contributes its default and each choice to the product."""
    name: str
    choices: tuple              # (Choice, ...)
    moves: frozenset            # the item keys its choices move: two units that share one never combine
    positional: bool = False    # a board.arrangement: alone, its arrangement keeps the unit's name and why
    why: str = ""


@dataclass(frozen=True)
class Spec:
    """One arrangement a module run lays out: its id, its choices as (unit, option) pairs (a board.arrangement's option is named as
    the unit), and the options to lay over the items' places, in unit order."""
    id: str
    pairs: tuple
    overrides: tuple            # ((item key, Option), ...)
    group: str = ""             # a board.arrangement laid alone: its name
    why: str = ""

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
            choices = tuple(Choice(g.name, go.name, g.name if g.positional else "%s.%s" % (g.name, go.name),
                                   tuple((o.item, o) for o in go.options)) for go in g.unit_options())
            out.append(Unit(g.name, choices, g.moves(), g.positional, g.why if g.positional else ""))
        elif options.get(name):
            out.append(Unit(name, tuple(Choice(name, o.name, "%s.%s" % (name, o.name), ((name, o),)) for o in options[name]),
                            frozenset((name,))))
    return out


def combinations(us):
    """Every combination of the units' choices in `itertools.product` order over `us` (the first unit changing slowest), each a
    tuple of the Choices taken, the empty one (the default) first. Two units that move one item never combine: a combination
    holding both is not one."""
    for picked in itertools.product(*[(None,) + u.choices for u in us]):
        taken = [(u, c) for u, c in zip(us, picked) if c is not None]
        moved = [k for u, _ in taken for k in u.moves]
        if len(moved) == len(set(moved)):
            yield tuple(c for _, c in taken)


def _excluded_by(combo, exclusions):
    """The first exclusion all of whose choices `combo` holds, or None."""
    ids = {c.id for c in combo}
    return next((e for e in exclusions if set(e.choices) <= ids), None)


def tally(us, exclusions=()) -> tuple:
    """(kept, excluded): how many combinations the units make, the default included, less those an exclusion leaves out; and how
    many the exclusions leave out. Only the units an exclusion names, or that move an item another unit moves, are walked; each of
    their combinations stands for the product of the other units' sizes."""
    named = {i for e in exclusions for i in e.choices}
    walked = [u for u in us if any(c.id in named for c in u.choices) or any(v is not u and u.moves & v.moves for v in us)]
    walked_names = {u.name for u in walked}
    free = math.prod(1 + len(u.choices) for u in us if u.name not in walked_names)
    kept = excluded = 0
    for combo in combinations(walked):
        if _excluded_by(combo, exclusions) is None:
            kept += free
        else:
            excluded += free
    return kept, excluded


def _spec(combo, positional: dict) -> Spec:
    pairs = tuple((c.unit, c.option) for c in combo)
    overrides = tuple(o for c in combo for o in c.overrides)
    ident = "+".join(c.id for c in combo)
    if len(combo) == 1 and combo[0].unit in positional:          # a board.arrangement alone: its name and why, as in 0.99.15
        return Spec(ident, pairs, overrides, combo[0].unit, positional[combo[0].unit])
    return Spec(ident, pairs, overrides)


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
    positional = {u.name: u.why for u in us if u.positional}
    specs, left_out = [DEFAULT_SPEC], []
    for combo in combinations(us):
        if not combo:
            continue
        spec, rule = _spec(combo, positional), _excluded_by(combo, exclusions)
        if rule is None:
            specs.append(spec)
        else:
            left_out.append((spec, rule))
    return Enumeration(tuple(specs), None, declared, tuple(left_out))


def known_id(ident: str, order, options: dict, groups) -> bool:
    """Whether `ident` is an id this module's declarations make, as written, without enumerating the product (a module over its
    limit still says which ids it meant): `default`, or choice ids in unit order joined by `+`, no two moving one item."""
    if ident == DEFAULT:
        return True
    where = {c.id: (n, u) for n, u in enumerate(units(order, options, groups)) for c in u.choices}
    last, moved = -1, frozenset()
    for piece in ident.split("+"):              # the id as the script wrote it: text to check, not a record
        got = where.get(piece)
        if got is None or got[0] <= last or moved & got[1].moves:
            return False
        last, moved = got[0], moved | got[1].moves
    return True


def all_ids(order, options: dict, groups, cap: int = 64) -> list:
    """The ids the declarations make, for a message: the default, then the combinations in product order, at most `cap`."""
    out = [DEFAULT]
    for combo in combinations(units(order, options, groups)):
        if combo:
            out.append("+".join(c.id for c in combo))
        if len(out) >= cap:
            break
    return out
