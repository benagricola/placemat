"""The routing phases a project states in placemat.toml: `[[route.phase]]` tables, each a named set of connections the
route takes up in the order given, at its own width, on its own layers, with its own router flags. Parsed here into
`Phase` records; what a phase selects on a board is kicad/phase_select.py's, and the engine that runs them is
kicad/route.py's `_route_board`."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re

from .settings import ROUTER_KNOWN, flag_matches, router_owned

SELECTORS = ("nets", "net_classes", "pairs", "buses", "connections", "current_paths", "interfaces", "net_types")
CAPTURE_SELECTORS = frozenset(("pairs", "interfaces", "net_types"))
REST = "rest"
CURRENT = "current"
_KEYS = SELECTORS + ("name", "width", "layers", "neckdown", "router_args")
_FLAGS = ("pairs", "current_paths")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_LAYER = re.compile(r"^(F|B|In([1-9]|[12][0-9]|30))\.Cu$")
PHASE_OWNED = {"--no-power-tap-neckdown": "neckdown = false"}


def phase_owned(arg: str, known=None) -> str | None:
    """The flag of PHASE_OWNED `arg` names, abbreviated (settings.flag_matches); `known`: the router's long flags,
    None: settings.ROUTER_KNOWN."""
    return next((f for f in flag_matches(arg, (ROUTER_KNOWN if known is None else set(known)) | set(PHASE_OWNED))
                 if f in PHASE_OWNED), None)

_TEXT = {
    "not_a_table": "route.phase %(index)d: each phase is a table, [[route.phase]]",
    "no_name": "route.phase %(index)d: a phase needs a name",
    "bad_name": "route.phase %(name)r: a name is letters, digits, '-', '_' and '.', starting with a letter or digit",
    "duplicate_name": "route.phase %(name)r: two phases have this name",
    "unknown_key": "route.phase %(name)r: %(key)s is not a phase key; a phase takes %(keys)s",
    "clearance_key": "route.phase %(name)r: clearance is not a phase key: a net keeps its net class's clearance, raised "
                     "by the clearance field of its net type in the capture",
    "two_selectors": "route.phase %(name)r: %(selectors)s: a phase has at most one selector",
    "flag_true": "route.phase %(name)r: %(key)s takes true; leave it out to not select by it",
    "bad_list": "route.phase %(name)r: %(key)s is a list of one or more names, not %(value)r",
    "bad_pairs": "route.phase %(name)r: pairs is true or a list of pairs of two net names, P first, not %(value)r",
    "bad_buses": "route.phase %(name)r: buses is a list of buses, each a list of net names or globs, not %(value)r",
    "bad_connection": "route.phase %(name)r: connection %(index)d: from and to are each {part = \"...\", pad = \"...\"}",
    "pair_width": "route.phase %(name)r: a pair phase takes its width from the net class; omit width",
    "bad_width": "route.phase %(name)r: width is a number in mm above 0 or \"current\", not %(value)r",
    "bad_layers": "route.phase %(name)r: layers: %(value)r is not a copper layer (F, In1 to In30, B, or their .Cu names)",
    "bad_neckdown": "route.phase %(name)r: neckdown is true or false, not %(value)r",
    "bad_router_args": "route.phase %(name)r: router_args is a list of strings, not %(value)r",
    "router_owned": "route.phase %(name)r: router_args: %(flag)s is set by placemat itself (%(by)s)",
    "needs_capture": "route.phase %(name)r: %(selector)s needs the capture's nets.layout.json with what it selects by; "
                     "this board's generator (%(generator)s) does not export it: generate the board with the Zener fork",
    "not_on_board": "route.phase %(name)r: no %(kind)s %(value)r on this board",
    "layer_missing": "route.phase %(name)r: the board has no %(layers)s (its copper layers: %(board_layers)s)",
    "no_current": "route.phase %(name)r: width = \"current\" needs a stated current (Pm.I) at both ends; none for %(what)s",
    "ends_on_two_nets": "route.phase %(name)r: connection %(index)d joins two nets, %(nets)s",
}


def phase_error_text(code: str, facts: dict) -> str:
    """A PhaseError as a sentence: the edge's rendering of its code and facts."""
    facts = dict(facts)
    if code == "no_current":
        facts["what"] = ", ".join(facts["nets"] if "nets" in facts else
                                  ("%(net)s %(from)s to %(to)s" % c for c in facts["connections"]))
    elif code == "needs_capture":
        g = facts.get("generator")
        facts["generator"] = (g.get("name") if isinstance(g, dict) else g) or "none"
    elif code in ("layer_missing", "ends_on_two_nets"):
        facts = {k: ", ".join(v) if k in ("layers", "board_layers", "nets") else v for k, v in facts.items()}
    return _TEXT[code] % facts


class PhaseError(ValueError):
    """A phase that cannot be obeyed: `code` (a key of _TEXT, or one phase_select adds) and its `facts`."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, dict(facts)
        super().__init__(phase_error_text(code, self.facts) if code in _TEXT else "%s %r" % (code, self.facts))


@dataclass(frozen=True)
class End:
    part: str           # the part's instance path, or its reference
    pad: str            # a pad number, or the name of a net the part has a pad on (its first, as a PadRef takes it)


@dataclass(frozen=True)
class Connection:
    start: End
    end: End


@dataclass(frozen=True)
class Phase:
    name: str
    selector: str                       # one of SELECTORS, or REST
    nets: tuple = ()
    net_classes: tuple = ()
    buses: tuple = ()
    connections: tuple = ()
    interfaces: tuple = ()
    net_types: tuple = ()
    pairs: tuple = ()                   # ((p, n), ...) by net name; empty for pairs = true (the capture's)
    width: float | str | None = None    # mm on every layer, CURRENT, or None: the net classes'
    layers: tuple | None = None         # None: every layer the route uses
    neckdown: bool = True
    router_args: tuple = ()

    def key(self) -> dict:
        return asdict(self)

    def record(self) -> dict:
        return {"name": self.name, "selector": self.selector, "width": self.width,
                "layers": list(self.layers) if self.layers else None, "neckdown": self.neckdown}


def _layer(name: str, phase: str) -> str:
    full = name if name.endswith(".Cu") else (name.upper() + ".Cu" if name.upper() in ("F", "B")
                                              else "In%s.Cu" % name[2:] if name[:2].lower() == "in" else name)
    if not _LAYER.match(full):
        raise PhaseError("bad_layers", name=phase, value=name)
    return full


def _names(t: dict, key: str, name: str) -> tuple:
    v = t[key]
    if not (isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)):
        raise PhaseError("bad_list", name=name, key=key, value=v)
    return tuple(v)


def _end(raw, name: str, index: int) -> End:
    if not (isinstance(raw, dict) and isinstance(raw.get("part"), str) and isinstance(raw.get("pad"), (str, int))
            and not isinstance(raw.get("pad"), bool) and set(raw) == {"part", "pad"}):
        raise PhaseError("bad_connection", name=name, index=index)
    return End(raw["part"], str(raw["pad"]))


def _one(t, index: int, seen: set) -> Phase:
    if not isinstance(t, dict):
        raise PhaseError("not_a_table", index=index)
    name = t.get("name")
    if not name:
        raise PhaseError("no_name", index=index)
    if not (isinstance(name, str) and _NAME.match(name)):
        raise PhaseError("bad_name", name=name)
    if name in seen:
        raise PhaseError("duplicate_name", name=name)
    seen.add(name)
    if "clearance" in t:
        raise PhaseError("clearance_key", name=name)
    for key in t:
        if key not in _KEYS:
            raise PhaseError("unknown_key", name=name, key=key, keys=", ".join(_KEYS))
    chosen = [k for k in SELECTORS if k in t]
    if len(chosen) > 1:
        raise PhaseError("two_selectors", name=name, selectors=", ".join(chosen))
    selector = chosen[0] if chosen else REST
    kw = {}
    if selector in _FLAGS and t[selector] is not True and not (selector == "pairs" and t[selector] is not False):
        raise PhaseError("flag_true", name=name, key=selector)
    if selector == "pairs" and t["pairs"] is not True:
        v = t["pairs"]
        if not (isinstance(v, list) and v and all(isinstance(p, list) and len(p) == 2
                                                  and all(isinstance(x, str) and x for x in p)
                          for p in v)) or len({x for p in v for x in p}) != 2 * len(v):
            raise PhaseError("bad_pairs", name=name, value=v)
        kw["pairs"] = tuple((p[0], p[1]) for p in v)
    if selector in ("nets", "net_classes", "interfaces", "net_types"):
        kw[selector] = _names(t, selector, name)
    if selector == "buses":
        v = t["buses"]
        if not (isinstance(v, list) and v and all(isinstance(b, list) and b and all(isinstance(x, str) and x for x in b)
                                                  for b in v)):
            raise PhaseError("bad_buses", name=name, value=v)
        kw["buses"] = tuple(tuple(b) for b in v)
    if selector == "connections":
        v = t["connections"]
        if not (isinstance(v, list) and v):
            raise PhaseError("bad_connection", name=name, index=0)
        kw["connections"] = tuple(Connection(_end(c.get("from") if isinstance(c, dict) else None, name, i),
                                             _end(c.get("to") if isinstance(c, dict) else None, name, i))
                                  for i, c in enumerate(v))
    width = t.get("width")
    if selector == "pairs" and width is not None:
        raise PhaseError("pair_width", name=name)
    if width is not None and not (width == CURRENT or (isinstance(width, (int, float)) and not isinstance(width, bool)
                                                         and math.isfinite(width) and width > 0)):
        raise PhaseError("bad_width", name=name, value=width)
    layers = t.get("layers")
    if layers is not None:
        if not (isinstance(layers, list) and layers and all(isinstance(x, str) for x in layers)):
            raise PhaseError("bad_layers", name=name, value=layers)
        layers = tuple(dict.fromkeys(_layer(x, name) for x in layers))
    neckdown = t.get("neckdown", True)
    if not isinstance(neckdown, bool):
        raise PhaseError("bad_neckdown", name=name, value=neckdown)
    args = t.get("router_args", [])
    if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
        raise PhaseError("bad_router_args", name=name, value=args)
    for a in args:
        flag = a.split("=", 1)[0]
        owned = phase_owned(a)
        if owned:
            raise PhaseError("router_owned", name=name, flag=flag, by=PHASE_OWNED[owned])
        if router_owned(a):
            raise PhaseError("router_owned", name=name, flag=flag, by="the phase's selector, layers and width")
    return Phase(name, selector, width=float(width) if isinstance(width, (int, float)) else width, layers=layers,
                 neckdown=neckdown, router_args=tuple(args), **kw)


def parse_phases(raw) -> tuple:
    seen: set = set()
    return tuple(_one(t, i, seen) for i, t in enumerate(raw or ()))


def phases_of(cfg) -> tuple:
    return parse_phases(cfg.route_phase)


def default_phases(*, pairs: bool, interface_types: list, wide_classes: list, currents: bool) -> list:
    out = []
    if pairs:
        out.append({"name": "diff-pairs", "pairs": True})
    interface_types = sorted(set(interface_types) - {"DiffPair"})
    if interface_types:
        out.append({"name": "buses", "interfaces": interface_types})
    if wide_classes:
        out.append({"name": "wide-clearance", "net_classes": sorted(wide_classes)})
    if currents:
        out.append({"name": "current", "current_paths": True, "width": "current"})
    out.append({"name": "signals"})
    return out


_NOTES = {"diff-pairs": "the capture's DiffPair instances, routed as pairs",
          "buses": "each interface instance of these types routed together as one bus",
          "wide-clearance": "the net classes whose clearance is above the Default's",
          "current": "each pair of parts that carry current (Pm.I), at the width the lesser current needs",
          "signals": "every connection still open, at the net classes' widths"}


def phases_toml(phases: list, notes: dict | None = None) -> str:
    import json
    notes = dict(_NOTES, **(notes or {}))
    blocks = []
    for p in phases:
        lines = ["# " + notes[p["name"]]] if p["name"] in notes else []
        lines.append("[[route.phase]]")
        lines += ["%s = %s" % (k, json.dumps(v)) for k, v in p.items()]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
