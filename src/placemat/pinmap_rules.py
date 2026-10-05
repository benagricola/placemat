"""The pin map study's constraints: which of a part's pins may carry which nets, read from its capture annotations.

`Pm.PinPool`, `Pm.PinFixed`, `Pm.PinAllow`, `Pm.PinDeny` and `Pm.PinGroup` on a part (capture.md, "Annotations"). A pin is
named by its pad number or by its pin name, as `PadRef` names it, and a range is `3-8` or `GPIO1-GPIO10`. An entry that
names a pin the part does not have, or a net it does not carry, is left out and returned as a `Problem`, which the study
reports as a `setup.pins` finding. Pure: it reads a part's fields, its pads' numbers and nets, and the board's pin names."""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from .checks import _net_named

SHOWN = {"pm.pinpool": "Pm.PinPool", "pm.pinfixed": "Pm.PinFixed", "pm.pinallow": "Pm.PinAllow",
         "pm.pindeny": "Pm.PinDeny", "pm.pingroup": "Pm.PinGroup"}
_TAIL = re.compile(r"^(.*?)(\d+)$")


def has_pools(footprints) -> bool:
    """Whether any part carries a `Pm.PinPool`: a board with none is not studied, and nothing is read for it."""
    return any(k.lower() == "pm.pinpool" and (v or "").strip() for fp in footprints for k, v in fp.fields.items())


@dataclass(frozen=True)
class Problem:
    """An annotation entry the study runs without, or a part it cannot study: the facts of a `setup.pins` finding. `key`
    is the annotation as capture.md spells it, `entry` the text that was left out, `name` the pin or net it names and
    `code` what is wrong: no_pin (the part has no such pin), no_names (a pin named by name, and no pin names were read
    for the part), no_net (no pin of the part carries the net), unreadable (the entry is not `name:pins`), not_in_pool
    (a group's pin outside the pool, or on a fixed pin), two_groups (a pin already in an earlier group), no_legal_pin (a
    net that no pin may take: the part is not studied), no_legal_map (no matching places every net: the part is not
    studied), present_breaks (a net that stands on a pin its own `Pm.PinAllow` or `Pm.PinDeny` bars: the study adds
    `pin` and `rule` to the facts), study_failed (the study raised: no part, and `type` and `message` in the facts).
    A no_legal_pin left so by another net held onto the net's only pin has no `key` or `entry`, and `held_net`
    and `held_pin` name the holder."""
    ref: str
    key: str
    entry: str
    code: str
    name: str
    held_net: str = ""
    held_pin: str = ""

    def facts(self) -> dict:
        return {"ref": self.ref, "key": self.key, "entry": self.entry, "code": self.code, "name": self.name,
                "held_net": self.held_net, "held_pin": self.held_pin}


@dataclass(frozen=True)
class PinRules:
    """One part's constraints, in pad numbers. `pool` keeps the order the annotation lists the pins in: a group moves to a
    run of consecutive entries of it. `allow` and `deny` are keyed by the net as the board names it."""
    ref: str
    pool: tuple
    fixed: frozenset = frozenset()
    allow: dict = None
    deny: dict = None
    groups: tuple = ()              # (name, (pad number, ...)) in the order written

    def __post_init__(self):
        object.__setattr__(self, "allow", dict(self.allow or {}))
        object.__setattr__(self, "deny", dict(self.deny or {}))


def natural(number: str) -> tuple:
    """A pad number's sort key: numeric ones in number order, then the rest (`A1`, `EP`) as text."""
    return (0, int(number), "") if number.isdigit() else (1, 0, number)


def fields_of(fields: dict) -> dict:
    """The part's pin annotations, keys lower-cased as KiCad title-cases them (`Pm.Pinpool`), blank ones left out."""
    return {k.lower(): v.strip() for k, v in fields.items() if k.lower() in SHOWN and v and v.strip()}


def _items(text: str) -> list:
    return [w for w in re.split(r"[,\s]+", text.strip()) if w]


def pin_numbers(numbers, names: dict, item: str) -> tuple:
    """(pad numbers, names not found) for one item of a pin list: a pad number, a pin name (every pad that carries it), or
    a range of either. `numbers` are the part's pad numbers, `names` {pad number: pin name}."""
    by_name: dict = {}
    for n, nm in names.items():
        by_name.setdefault(nm, []).append(n)
    lower = {}
    for nm, ns in by_name.items():
        lower.setdefault(nm.lower(), []).extend(ns)

    def one(word):
        if word in numbers:
            return [word]
        hit = by_name.get(word) or lower.get(word.lower())
        return sorted(set(hit), key=natural) if hit else None

    whole = one(item)
    if whole is not None:
        return whole, []
    lo, dash, hi = item.partition("-")
    a, b = (_TAIL.match(lo), _TAIL.match(hi)) if dash else (None, None)
    if a is None or b is None or a.group(1) != b.group(1):
        return [], [item]
    prefix, i, j = a.group(1), int(a.group(2)), int(b.group(2))
    step = 1 if j >= i else -1
    out, missing = [], []
    for k in range(i, j + step, step):
        word = "%s%d" % (prefix, k)
        got = one(word)
        if got is None:
            missing.append(word)
        else:
            out += [g for g in got if g not in out]
    return out, missing


def _pin_list(ref, key, text, numbers, names, problems) -> list:
    out = []
    for item in _items(text):
        got, missing = pin_numbers(numbers, names, item)
        if missing and not names and not all(m.isdigit() for m in missing):    # a name, and none to look in: one problem
            problems.append(Problem(ref, key, item, "no_names", item))
            continue
        problems += [Problem(ref, key, item, "no_pin", m) for m in missing]
        out += [g for g in got if g not in out]
    return out


def _entries(text: str) -> list:
    return [e.strip() for e in text.split(";") if e.strip()]


def read_rules(ref: str, fields: dict, pads, names: dict) -> tuple:
    """(PinRules or None, [Problem]) for one part: `fields` its footprint's fields, `pads` its (pad number, net) pairs,
    `names` {pad number: pin name}. None when the part has no `Pm.PinPool`: it is not studied."""
    f = fields_of(fields)
    if "pm.pinpool" not in f:
        return None, []
    numbers = {n for n, _ in pads}
    nets = sorted({net for _, net in pads if net})
    problems: list = []
    pool = _pin_list(ref, "Pm.PinPool", f["pm.pinpool"], numbers, names, problems)
    fixed = frozenset(_pin_list(ref, "Pm.PinFixed", f.get("pm.pinfixed", ""), numbers, names, problems))
    rules = {}
    for low in ("pm.pinallow", "pm.pindeny"):
        key, out = SHOWN[low], {}
        for entry in _entries(f.get(low, "")):
            name, colon, pins = entry.partition(":")
            if not colon or not name.strip() or not pins.strip():
                problems.append(Problem(ref, key, entry, "unreadable", entry))
                continue
            hit = [n for n in nets if _net_named(name.strip(), n)]
            if not hit:
                problems.append(Problem(ref, key, entry, "no_net", name.strip()))
                continue
            got = frozenset(_pin_list(ref, key, pins, numbers, names, problems))
            for n in hit:
                out[n] = out.get(n, frozenset()) | got
        rules[low] = out
    groups, taken = [], set()
    for entry in _entries(f.get("pm.pingroup", "")):
        name, colon, pins = entry.partition(":")
        if not colon or not name.strip() or not pins.strip():
            problems.append(Problem(ref, "Pm.PinGroup", entry, "unreadable", entry))
            continue
        got = _pin_list(ref, "Pm.PinGroup", pins, numbers, names, problems)
        outside = [p for p in got if p not in pool or p in fixed]
        twice = [p for p in got if p in taken]
        if outside or twice:
            problems.append(Problem(ref, "Pm.PinGroup", entry, "not_in_pool" if outside else "two_groups",
                                    (outside or twice)[0]))
            continue
        if got:
            taken |= set(got)
            groups.append((name.strip(), tuple(got)))
    return PinRules(ref, tuple(pool), fixed, rules["pm.pinallow"], rules["pm.pindeny"], tuple(groups)), problems


@dataclass(frozen=True)
class Held:
    """A net kept on its pin: `why` is fixed (`Pm.PinFixed`), allow (`Pm.PinAllow` and `Pm.PinDeny` leave it only the pin
    it is on) or unplaced (no pad of it but this one is placed: nothing pulls it anywhere yet)."""
    net: str
    pin: str
    why: str


@dataclass(frozen=True)
class PartPins:
    """What may move on one studied part. `present` is every studied net's pin now (movable or held); `movable` the nets
    the search may move, each to a pin of `allowed[net]` (pool order); `free` the pool pins no studied net stands on now;
    `groups` (name, nets in order, "" for a pin with none) move whole, to one of `windows[name]`, each a run of
    consecutive pool pins; `places[name]` is the group's pins as written, where it stands. `breaks` (net, pin, key) are
    the movable nets whose present pin `Pm.PinAllow` or `Pm.PinDeny` (`key`) bars them from: the capture as it stands
    breaks its own rule."""
    ref: str
    present: dict
    movable: tuple
    allowed: dict
    free: tuple
    groups: tuple
    windows: dict
    held: tuple
    places: dict = field(default_factory=dict)
    breaks: tuple = ()


def part_pins(rules: PinRules, pads, connected, quiet, waiting=frozenset()) -> tuple:
    """(PartPins or None, [Problem]): `pads` the part's (pad number, net, no_connect), `connected` the nets with a pad
    elsewhere on the board, placed or not, `quiet` the plane and free nets, `waiting` the nets with no pad placed but
    this part's, which keep their pins (Held "unplaced"). A pool pin with no net, with a net that reaches nothing else
    (a single-pad net, KiCad's `unconnected-(...)`) or that the capture marks unconnected is free. A net on one pool pin
    that is not fixed moves. A net on two pins, a quiet net and a net outside the pool stay, and so do their pins; so
    does a net `Pm.PinAllow` or `Pm.PinDeny` leaves only its own pin. None, with a `no_legal_pin` problem, when a net
    has no pin it may take: the part is not studied."""
    pool = list(rules.pool)
    on: dict = {}
    for number, net, no_connect in pads:
        if net and net in connected and not no_connect:
            on.setdefault(net, []).append(number)
    movable, held, staying = [], [], set()
    for net in sorted(on):
        pins = on[net]
        if net in quiet or len(pins) != 1 or pins[0] not in pool:
            staying |= set(pins)
        elif pins[0] in rules.fixed:
            held.append(Held(net, pins[0], "fixed"))
            staying.add(pins[0])
        elif net in waiting:
            held.append(Held(net, pins[0], "unplaced"))
            staying.add(pins[0])
        else:
            movable.append(net)
    present = {net: on[net][0] for net in movable}

    def legal(net, pins):
        return tuple(p for p in pins if (net not in rules.allow or p in rules.allow[net]) and p not in rules.deny.get(net, ()))
    open_pins = [p for p in pool if p not in rules.fixed and p not in staying]
    for net in list(movable):
        if (net in rules.allow or net in rules.deny) and legal(net, open_pins) == (present[net],):
            held.append(Held(net, present[net], "allow"))
            staying.add(present[net])
            movable.remove(net)
            del present[net]
    open_pins = [p for p in open_pins if p not in staying]
    allowed, problems = {}, []
    for net in movable:
        allowed[net] = legal(net, open_pins)
        if allowed[net]:
            continue
        own = legal(net, pool)
        by = next((h for h in sorted(held, key=lambda h: natural(h.pin)) if h.pin in own), None)
        if by is not None:
            problems.append(Problem(rules.ref, "", "", "no_legal_pin", net, by.net, by.pin))
        else:
            problems.append(Problem(rules.ref, "Pm.PinAllow" if net in rules.allow else "Pm.PinDeny", "", "no_legal_pin", net))
    if problems:
        return None, problems
    breaks = tuple((net, present[net], "Pm.PinAllow" if net in rules.allow and present[net] not in rules.allow[net]
                    else "Pm.PinDeny") for net in movable if not legal(net, (present[net],)))
    taken = set(present.values())
    free = tuple(p for p in open_pins if p not in taken)
    by_pin = {pin: net for net, pin in present.items()}
    groups, windows = [], {}
    for name, pins in rules.groups:
        nets = tuple(by_pin.get(p, "") for p in pins)
        wins = []
        for i in range(len(pool) - len(pins) + 1):
            win = tuple(pool[i:i + len(pins)])
            if all(p in open_pins for p in win) and all(not n or p in allowed[n] for n, p in zip(nets, win)):
                wins.append(win)
        groups.append((name, nets))
        windows[name] = tuple(wins)
    return PartPins(rules.ref, present, tuple(movable), allowed, free, tuple(groups), windows,
                    tuple(sorted(held, key=lambda h: natural(h.pin))),
                    {name: tuple(pins) for name, pins in rules.groups}, breaks), []
