"""The facts a board carries, from the board's own stackup and net classes
and from fab-profile.json, and whether they match the last `placemat facts
--confirm`. Each fact's home is
docs/superpowers/specs/2026-09-30-board-facts-fixed-and-preferred-design.md's
rule: placemat.toml holds none of this."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .board_geometry import BoardGeometry, stackup_order
from .project import FabProfile

_VIA_KINDS = ("micro", "blind", "buried")


@dataclass(frozen=True)
class FactsDocument:
    layers: dict                     # {layer name: {"role": str, "copper_mm": float|None}}
    pairs: dict                      # {net class name: [nets], sorted}
    via_types: dict                  # {"micro"/"blind"/"buried": "yes"/"no"/"if-needed"}
    fab_min: dict                    # fab.min, as given
    rise_c: float
    plane_mismatches: tuple = ()     # sentences: a signal layer with a plane, or a power layer without one
    via_named: tuple = ()            # the via types fab-profile.json names a tier for; the rest default to "no"

    def _digest_doc(self) -> dict:
        return {"layers": self.layers, "pairs": self.pairs, "via_types": self.via_types,
                "fab_min": self.fab_min, "rise_c": self.rise_c}

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self._digest_doc(), sort_keys=True).encode()).hexdigest()


def facts_of(geometry: BoardGeometry, fab: FabProfile, rise_c: float,
            plane_layers: frozenset = frozenset()) -> FactsDocument:
    """The board's facts: each copper layer's role and weight, the pair
    classes and their nets (the Default class never makes pairs), each via
    type's tier, the fab minimums and the rise. `plane_layers`: the layers
    the script's own board.plane() calls declare (facts_of does not run a
    script itself; a caller that has one passes what it found)."""
    stack = sorted(geometry.layers, key=stackup_order)
    layers = {l.value: {"role": geometry.layer_types.get(l, "signal"), "copper_mm": geometry.copper_mm.get(l)}
             for l in stack}
    by_class: dict = {}
    for net, nc in geometry.netclasses.items():
        if nc.name == "Default" or nc.diff_pair_width is None or nc.diff_pair_gap is None:
            continue
        by_class.setdefault(nc.name, []).append(net)
    pairs = {name: sorted(nets) for name, nets in by_class.items()}
    via_types = {kind: fab.tier(kind) for kind in _VIA_KINDS}
    mismatches = []
    for l in stack:
        role = geometry.layer_types.get(l, "signal")
        has_plane = l in plane_layers
        if role == "signal" and has_plane:
            mismatches.append("%s is signal but carries a plane()" % l.value)
        elif role == "power" and not has_plane:
            mismatches.append("%s is power (ground) but carries no plane()" % l.value)
    named = tuple(k for k in _VIA_KINDS if k in fab.via_tiers)
    return FactsDocument(layers, pairs, via_types, dict(fab.min), rise_c, tuple(mismatches), named)


def unconfirmed_reasons(doc: FactsDocument, confirmed_digest: str) -> list:
    """Why `doc` is unconfirmed (a list of {"reason": ...} records, finding_text.facts_reason_text says each),
    or [] when it matches the last `placemat facts --confirm`. A board with no confirmation record yet is
    unconfirmed outright (nothing else is worth checking); a via type
    fab-profile.json names no tier for, or no min, is unconfirmed even when
    the rest of the digest matches: its default was never decided by
    anyone. A type named "no" is a decision, and is confirmed."""
    if not confirmed_digest:
        return [{"reason": "no_record"}]
    out = []
    missing = [k for k in _VIA_KINDS if k not in doc.via_named]
    if len(missing) == len(_VIA_KINDS):
        out.append({"reason": "no_via_section"})
    elif missing:
        out.append({"reason": "no_via_tier", "kinds": list(missing)})
    if not doc.fab_min:
        out.append({"reason": "no_min_section"})
    if doc.digest() != confirmed_digest:
        out.append({"reason": "changed"})
    return out


def unconfirmed_line(reasons: list) -> str:
    """The run's own line when its facts do not match the last
    confirmation."""
    return "facts: unconfirmed - placemat facts"


def render(doc: FactsDocument, reasons: list) -> list:
    """The lines `placemat facts` prints."""
    from .values import CopperLayer
    lines = []
    for name, info in sorted(doc.layers.items(), key=lambda kv: stackup_order(CopperLayer.of(kv[0]))):
        weight = "%.4f mm" % info["copper_mm"] if info["copper_mm"] is not None else "unknown (no stackup declared)"
        lines.append("layer      %-8s role %-6s weight %s" % (name, info["role"], weight))
    for name, nets in sorted(doc.pairs.items()):
        lines.append("pair class %-12s %s" % (name, ", ".join(nets)))
    for kind, tier in sorted(doc.via_types.items()):
        lines.append("via        %-8s %s" % (kind, tier))
    for key, value in sorted(doc.fab_min.items()):
        lines.append("fab min    %-12s %g mm" % (key, value))
    lines.append("rise       %g C" % doc.rise_c)
    for m in doc.plane_mismatches:
        lines.append("flagged    %s" % m)
    if reasons:
        from .finding_text import facts_reason_text
        lines.append("unconfirmed: " + "; ".join(facts_reason_text(r) for r in reasons))
    else:
        lines.append("confirmed")
    return lines


_FACTS_SECTION_RE = re.compile(r"^\[facts\][ \t]*$", re.M)
_BOARDS_SECTION_RE = re.compile(r"^\[facts\.boards\][ \t]*$", re.M)
_CONFIRMED_LINE_RE = re.compile(r'^confirmed\s*=\s*"[^"]*"\s*$', re.M)


def script_key(script, toml) -> str:
    """The key a script's digest has in [facts.boards]: its path relative
    to the folder of the placemat.toml that holds the table, with forward
    slashes. The path is what the digest is computed from (the script's own
    plane() calls, over the board it declares), and it is unique where a
    board's name is not: variants of one board share a name."""
    return Path(script).resolve().relative_to(Path(toml).resolve().parent).as_posix()


def confirmed_digest(cfg, script) -> str:
    """The digest last confirmed for `script`: its own entry in [facts.boards]
    (keyed relative to the placemat.toml that holds the table), else the old
    single `confirmed` key, else ""."""
    boards = cfg.facts_boards
    if boards:
        try:
            key = script_key(script, cfg.source_of("facts_boards"))
        except ValueError:
            key = None
        if key in boards:
            return boards[key]
    return cfg.facts_confirmed


def _section_bounds(text: str, header_re) -> tuple:
    """(start, end) of a section's body: after its header line, up to the
    next header or the end of the text; None when it has no header."""
    m = header_re.search(text)
    if m is None:
        return None
    nxt = re.search(r"^\[", text[m.end():], re.M)
    return m.end(), (m.end() + nxt.start() if nxt else len(text))


def write_confirmed(path, digest: str, key: str = None) -> None:
    """Record a confirmed digest in a placemat.toml, touching only [facts].
    With `key` (a script's path relative to the file's folder) it is
    `[facts.boards] "<key>" = "<digest>"`, replacing that key's value or
    adding it; the old single `confirmed = "<digest>"` is dropped when it
    holds this same digest (it is this script's, now keyed) and left for
    the other scripts it may belong to otherwise. Without `key`, the old
    single `confirmed` key. Never fed into a run's id: this is placemat's
    own record, not a board fact."""
    p = Path(path)
    text = p.read_text() if p.exists() else ""
    if key is not None:
        text = _drop_old_key(text, digest)
        line = "%s = %s" % (json.dumps(key), json.dumps(digest))
        b = _section_bounds(text, _BOARDS_SECTION_RE)
        if b is None:
            if text and not text.endswith("\n"):
                text += "\n"
            text += "%s[facts.boards]\n%s\n" % ("\n" if text else "", line)
        else:
            body = text[b[0]:b[1]]
            entry = re.compile(r"^%s[ \t]*=.*$" % re.escape(json.dumps(key)), re.M)
            body = entry.sub(lambda _m: line, body, count=1) if entry.search(body) else "\n" + line + body
            text = text[:b[0]] + body + text[b[1]:]
        p.write_text(text)
        return
    m = _FACTS_SECTION_RE.search(text)
    if m is None:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "%s[facts]\nconfirmed = \"%s\"\n" % ("\n" if text else "", digest)
    else:
        b = _section_bounds(text, _FACTS_SECTION_RE)
        section = text[b[0]:b[1]]
        line = 'confirmed = "%s"\n' % digest
        if _CONFIRMED_LINE_RE.search(section):
            section = _CONFIRMED_LINE_RE.sub(line.rstrip("\n"), section, count=1)
        else:
            section = "\n" + line.rstrip("\n") + section
        text = text[:b[0]] + section + text[b[1]:]
    p.write_text(text)


def _drop_old_key(text: str, digest: str) -> str:
    """`text` without its [facts] confirmed line when that line holds
    `digest`, and without the [facts] header if nothing else is left under
    it."""
    b = _section_bounds(text, _FACTS_SECTION_RE)
    if b is None:
        return text
    section = text[b[0]:b[1]]
    m = _CONFIRMED_LINE_RE.search(section)
    if m is None or '"%s"' % digest not in m.group(0):
        return text
    section = section[:m.start()] + section[m.end():].lstrip("\n")
    head = _FACTS_SECTION_RE.search(text)
    if not section.strip():
        return text[:head.start()] + text[b[1]:].lstrip("\n")
    return text[:b[0]] + section + text[b[1]:]
