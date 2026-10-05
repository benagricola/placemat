# src/placemat/arrangements.py
"""A module's alternative arrangements as declarations: the options an item may take, the named groups, the ids and the limits.

Pure: no Board, no KiCad. `Board.alternative` and `Board.arrangement` (layout.py) validate against the board and build the
records here; `enumerate_specs` turns them into the arrangements a module run lays out, the default first."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
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
class Group:
    """An arrangement the script names: one option per member it moves, the rest keep their place()."""
    name: str
    options: tuple              # (Option, ...)
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Spec:
    """One arrangement a module run lays out: its id, its choices as pairs ((item, option) or ("group", name)), and the options
    to lay over the items' places, in item order."""
    id: str
    pairs: tuple
    overrides: tuple            # ((item key, Option), ...)
    group: str = ""
    why: str = ""

    @property
    def choices(self) -> dict:
        return dict(self.pairs)


DEFAULT_SPEC = Spec(DEFAULT, (), ())


@dataclass(frozen=True)
class Enumeration:
    specs: tuple                # the default first, then the product, then the groups
    over: dict | None           # the facts of arrangement.limit when a limit is passed; the specs are then the default alone
    declared: int               # how many arrangements the declarations make, the default included


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


def spec_id(pairs) -> str:
    return "+".join("%s.%s" % p for p in pairs)


def count(options: dict, groups) -> int:
    n = 1
    for opts in options.values():
        n *= 1 + len(opts)
    return n + len(groups)


def picks(order, options: dict):
    """The combinations of the items' options in `itertools.product` order over `order` (the first declared item changing
    slowest): each a tuple of (item, Option) for the items that take an option, the default combination (empty) included."""
    order = [k for k in order if options.get(k)]
    for combo in itertools.product(*[[None] + list(options[k]) for k in order]):
        yield tuple((k, o) for k, o in zip(order, combo) if o is not None)


def enumerate_specs(order, options: dict, groups, max_options: int, max_arrangements: int) -> Enumeration:
    """The arrangements of a module: the default, every combination of the items' options (each item contributes its options
    and its default; `picks` order), then each group in the order declared. Over either limit nothing is partly accepted:
    the default alone, and the facts of the finding."""
    order = [k for k in order if options.get(k)]
    sizes = {k: 1 + len(options[k]) for k in order}
    declared = count({k: options[k] for k in order}, groups)
    if any(n > max_options for n in sizes.values()) or declared > max_arrangements:
        facts = {"variant": "options" if any(n > max_options for n in sizes.values()) else "arrangements",
                 "arrangements": declared, "max_arrangements": max_arrangements, "options": sizes,
                 "max_options": max_options}
        return Enumeration((DEFAULT_SPEC,), facts, declared)
    specs = [DEFAULT_SPEC]
    for picked in picks(order, options):
        if picked:
            pairs = tuple((k, o.name) for k, o in picked)
            specs.append(Spec(spec_id(pairs), pairs, picked))
    for g in groups:
        specs.append(Spec(g.name, (("group", g.name),), tuple((o.item, o) for o in g.options), g.name, g.why))
    return Enumeration(tuple(specs), None, declared)


def known_id(ident: str, order, options: dict, groups) -> bool:
    """Whether `ident` is an id this module's declarations make, as written, without enumerating the product (a module over
    its limit still says which ids it meant)."""
    if ident == DEFAULT or any(g.name == ident for g in groups):
        return True
    order = [k for k in order if options.get(k)]
    last = -1
    for part in ident.split("+"):
        item, dot, name = part.rpartition(".")      # an item key may hold dots; an option name never does
        if not dot or item not in order or order.index(item) <= last or name not in {o.name for o in options[item]}:
            return False
        last = order.index(item)
    return True


def all_ids(order, options: dict, groups, cap: int = 64) -> list:
    """The ids the declarations make, for a message: the default, then the product and the groups, at most `cap`."""
    out = [DEFAULT]
    for picked in picks(order, options):
        if picked:
            out.append(spec_id([(k, o.name) for k, o in picked]))
        if len(out) >= cap:
            return out
    return out + [g.name for g in groups]
