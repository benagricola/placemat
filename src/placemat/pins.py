"""Pin names for pads. The generated board and the generator's netlist give a
pad its number only; the netlist names each part's symbol, and the symbol
libraries a board's .zen files use give every pin's number and name."""
from __future__ import annotations

from pathlib import Path
import re

_SYMBOL_RE = re.compile(r'^(?:\t| {2})\(symbol "([^"]+)"', re.M)     # a library's top-level symbols: one indent
_COMP_RE = re.compile(r'\(comp \(ref "([^"]+)"\)(?:(?!\(comp ).)*?\(libsource \(lib "[^"]*"\) \(part "([^"]+)"\)', re.S)


def _blocks(text: str):
    """(name, body) for each top-level symbol of a .kicad_sym, its units included."""
    starts = [(m.start(), m.group(1)) for m in _SYMBOL_RE.finditer(text)]
    for k, (at, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(text)
        yield name, text[at:end]


def symbol_pins(path) -> dict:
    """{symbol name: {pin number: pin name}} for every symbol in a library."""
    out = {}
    for name, body in _blocks(Path(path).read_text(errors="replace")):
        pins = {}
        for chunk in body.split("(pin ")[1:]:
            n = re.search(r'\(name "([^"]*)"', chunk)
            m = re.search(r'\(number "([^"]*)"', chunk)
            if n and m:
                pins[m.group(1)] = n.group(1)
        if pins:
            out[name] = pins
    return out


def netlist_symbols(path) -> dict:
    """{refdes: symbol name} from a KiCad-format netlist's components."""
    return {ref: part for ref, part in _COMP_RE.findall(Path(path).read_text(errors="replace"))}


_FP_RE = re.compile(r'\(comp \(ref "([^"]+)"\)(?:(?!\(comp ).)*?\(footprint "(?:[^":]*:)?([^"]+)"\)', re.S)
_PAIR_RES = (re.compile(r'footprint\s*=\s*File\("([^"]+)"\)(?:(?!Component\().){0,600}?symbol\s*=\s*Symbol\("([^"]+)"\)', re.S),
             re.compile(r'symbol\s*=\s*Symbol\("([^"]+)"\)(?:(?!Component\().){0,600}?footprint\s*=\s*File\("([^"]+)"\)', re.S))


def netlist_footprints(path) -> dict:
    """{refdes: footprint name} (the library item, without its library)."""
    return dict(_FP_RE.findall(Path(path).read_text(errors="replace")))


def zen_symbols(zens) -> dict:
    """{footprint name: symbol library path} from components that name both:
    a component's name need not be its symbol's, its footprint is shared."""
    out = {}
    for zen in zens:
        zen = Path(zen)
        text = zen.read_text(errors="replace")
        pairs = [(f, s) for f, s in _PAIR_RES[0].findall(text)] + [(f, s) for s, f in _PAIR_RES[1].findall(text)]
        for fp, sym in pairs:
            out.setdefault(Path(fp).stem, (zen.parent / sym).resolve())
    return out


def pin_names(netlist, libraries, zens=()) -> dict:
    """{refdes: {pad number: pin name}}. A part's symbol is found through
    the .zen that names its footprint (its library's only symbol, or the one
    the netlist names), else by the netlist's name among `libraries`. A
    symbol two libraries define differently is not found by name."""
    found: dict = {}
    for lib in libraries:
        for name, pins in symbol_pins(lib).items():
            found.setdefault(name, []).append(pins)
    by_symbol = {name: v[0] for name, v in found.items() if all(p == v[0] for p in v)}
    by_footprint = zen_symbols(zens)
    footprints = netlist_footprints(netlist)
    out = {}
    for ref, part in sorted(netlist_symbols(netlist).items()):
        lib = by_footprint.get(footprints.get(ref, ""))
        if lib is not None and lib.exists():
            syms = symbol_pins(lib)
            pins = syms.get(part) or (next(iter(syms.values())) if len(syms) == 1 else None)
            if pins:
                out[ref] = dict(pins)
                continue
        if part in by_symbol:
            out[ref] = dict(by_symbol[part])
    return out


def board_pin_names(src, generated_dir) -> dict:
    """The pin names for a board: its generation's netlist, and the symbol
    libraries and .zen files among its generator inputs."""
    from .project import generator_inputs
    net = Path(generated_dir) / "default.net"
    if not net.exists():
        return {}
    base = Path(src.board_dir)
    files = [(base / rel).resolve() for rel in generator_inputs(src) if not rel.startswith("(")]
    return pin_names(net, [f for f in files if f.suffix == ".kicad_sym" and f.exists()],
                     zens=[f for f in files if f.suffix == ".zen" and f.exists()])
