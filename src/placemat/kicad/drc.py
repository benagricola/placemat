"""Runs kicad-cli DRC on a board and parses the JSON report into violation
buckets, unconnected count and open nets."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess

from ..childenv import child_env
from ..settings import (DEFAULT_FOOTPRINT_KINDS, DEFAULT_OUTSTANDING_KINDS,
                        DEFAULT_REAL_KINDS, active)

# Clearance-class violations: a board with any of these is not done. The
# defaults; a project says otherwise with `[drc] real_kinds`.
REAL_KINDS = DEFAULT_REAL_KINDS


@dataclass(frozen=True)
class LibraryTable:
    """Whether the board's own folder gives KiCad its footprint libraries: `state` is "missing" (no fp-lib-table
    beside the board), "unresolved" (its entries `unresolved`, by name, do not exist as the project's folder
    reaches them) or "resolved"."""
    path: Path | None
    state: str
    unresolved: tuple = ()

    def record(self) -> dict:
        return {"path": str(self.path) if self.path else None, "state": self.state, "unresolved": list(self.unresolved)}

    @property
    def from_where_the_board_sits(self) -> bool:
        return self.state != "resolved"


_LIB_RE = re.compile(r'\(lib\s+\(name\s+"([^"]*)"\).*?\(uri\s+"([^"]*)"\)', re.S)


def library_table(pcb) -> LibraryTable:
    """The fp-lib-table beside `pcb`, and which of its libraries reach a folder from there. An entry through
    `${KIPRJMOD}` is resolved against the board's folder; one through another variable or an absolute path is
    taken as found, since KiCad's own settings supply those."""
    folder = Path(pcb).parent
    table = folder / "fp-lib-table"
    if not table.is_file():
        return LibraryTable(None, "missing")
    unresolved = []
    for name, uri in _LIB_RE.findall(table.read_text(errors="replace")):
        m = re.match(r"\$[({]KIPRJMOD[)}]/?(.*)$", uri)
        if m and not Path(os.path.normpath(folder / m.group(1))).exists():
            unresolved.append(name)
    return LibraryTable(table, "unresolved" if unresolved else "resolved", tuple(unresolved))


@dataclass
class DrcReport:
    path: Path
    by_type: dict = field(default_factory=dict)
    unconnected: int = 0
    open_nets: Counter = field(default_factory=Counter)
    command: list = field(default_factory=list)
    returncode: int = 0
    stderr_tail: str = ""
    real_kinds: tuple = DEFAULT_REAL_KINDS
    outstanding_kinds: tuple = DEFAULT_OUTSTANDING_KINDS
    footprint_kinds: tuple = DEFAULT_FOOTPRINT_KINDS
    permitted: dict = field(default_factory=dict)      # what a keepout's allow list lets stand, by kind
    severities: dict = field(default_factory=dict)     # each kind's severity as KiCad reports it (the highest of its violations)
    libraries: LibraryTable | None = None              # where the board's footprint libraries come from; None when not looked at

    @property
    def violations(self) -> int:
        return sum(self.by_type.values())

    def is_real(self, kind: str) -> bool:
        """A kind counts in the headline when it is in `real_kinds` whatever its severity, or KiCad reports it as an
        error and it has no line of its own (footprint issues, outstanding)."""
        if kind in self.real_kinds:
            return True
        return (self.severities.get(kind) == "error"
                and kind not in self.footprint_kinds and kind not in self.outstanding_kinds)

    @property
    def real(self) -> dict:
        return {k: v for k, v in self.by_type.items() if self.is_real(k)}

    @property
    def outstanding(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in self.outstanding_kinds}

    @property
    def footprint_issues(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in self.footprint_kinds}

    @property
    def other(self) -> dict:
        return {k: v for k, v in self.by_type.items()
                if not self.is_real(k) and k not in self.outstanding_kinds
                and k not in self.footprint_kinds}

    def summary(self) -> str:
        parts = []
        parts.append("DRC clean" if not self.real else "DRC " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.real.items())))
        parts.append("unconnected %d" % self.unconnected)
        if self.outstanding:
            parts.append("outstanding " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.outstanding.items())))
        if self.footprint_issues:
            n = sum(self.footprint_issues.values())
            parts.append("footprint issues %d (extents for those parts are unreliable)" % n)
            lib = self.by_type.get("lib_footprint_issues")
            if lib and self.libraries is not None and self.libraries.from_where_the_board_sits:
                parts.append("the %d lib_footprint_issues come from where the board sits (%s), not from the board" % (
                    lib, "no fp-lib-table beside it" if self.libraries.state == "missing"
                    else "its fp-lib-table does not resolve from there"))
        if self.other:
            parts.append("other " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.other.items())))
        if self.permitted:
            parts.append("permitted by their keepout %d" % sum(self.permitted.values()))
        return " | ".join(parts)


_RANK = {"error": 3, "warning": 2, "exclusion": 1, "ignore": 0}


def violation_severities(data: dict, allow: dict) -> dict:
    """{kind: severity} of the violations that count: the highest severity KiCad gave any of that kind."""
    out = {}
    for v in data.get("violations", []):
        if _permitted(v, allow):
            continue
        kind, sev = v.get("type", ""), v.get("severity", "")
        if kind not in out or _RANK.get(sev, -1) > _RANK.get(out[kind], -1):
            out[kind] = sev
    return out


def patch_rule_severities(pcb_path, severities: dict) -> None:
    """KiCad rule severities from `[drc.severities]` into the .kicad_pro
    beside the board: the generator writes a new project on every fresh
    generation, so a hand edit of it does not last. KiCad's DRC reads them
    there; nothing else in the project changes."""
    if not severities:
        return
    pro = Path(pcb_path).with_suffix(".kicad_pro")
    if not pro.exists():
        return
    try:
        d = json.loads(pro.read_text())
    except ValueError:
        return
    rs = d.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})
    rs.update(severities)
    pro.write_text(json.dumps(d, indent=2))


_AREA_RE = re.compile(r"keepout area '([^']+)'")
_FOOTPRINT_RE = re.compile(r"^Footprint (\S+)")
_NET_RE = re.compile(r"\[([^\]]+)\]")


def count_violations(data: dict, allow: dict) -> tuple:
    """(counted, permitted), each {kind: n}, from a kicad-cli DRC report.
    KiCad writes a rule area with no allow list, so a part or a net the
    script let into a keepout comes back as `items_not_allowed`; `allow`
    maps a keepout's name (without its layer marker) to (refdes, nets) it
    permits, and a violation every item of which it permits is set aside."""
    counted, permitted = Counter(), Counter()
    for v in data.get("violations", []):
        kind = v.get("type", "")
        if _permitted(v, allow):
            permitted[kind] += 1
        else:
            counted[kind] += 1
    return dict(counted), dict(permitted)


def _permitted(v: dict, allow: dict) -> bool:
    """A keepout's `items_not_allowed` every item of which its allow list lets in."""
    from ..board_geometry import split_marker
    m = _AREA_RE.search(v.get("description", ""))
    if v.get("type", "") != "items_not_allowed" or not m:
        return False
    refs, nets = allow.get(split_marker(m.group(1))[0], (set(), set()))

    def ok(item):
        d = item.get("description", "")
        f = _FOOTPRINT_RE.match(d)
        if f:
            return f.group(1) in refs
        n = _NET_RE.search(d)
        return bool(n) and n.group(1) in nets
    items = v.get("items", [])
    return bool(items) and all(ok(i) for i in items)


_PART_RE = re.compile(r"(?:\bof|^Footprint)\s+(\S+)")


def _items(v: dict, insts: dict | None = None) -> list:
    out = []
    for i in v.get("items", []):
        d = i.get("description", "")
        item = {"description": d, "at": [i["pos"]["x"], i["pos"]["y"]] if isinstance(i.get("pos"), dict) else None}
        m = _PART_RE.search(d) if insts else None
        if m and m.group(1) in insts:
            item["instance"] = insts[m.group(1)]       # the run's name for the part KiCad names by refdes
        out.append(item)
    return out


def violation_items(data: dict, allow: dict, insts: dict | None = None) -> list:
    """Each violation that counts, as KiCad describes it: its kind, severity,
    description and the items it is between, each with where it is (mm) and,
    given `insts` (refdes -> instance path), the instance of the part it is on."""
    return [{"kind": v.get("type", ""), "severity": v.get("severity", ""), "description": v.get("description", ""),
             "items": _items(v, insts)} for v in data.get("violations", []) if not _permitted(v, allow)]


def unconnected_items(data: dict, insts: dict | None = None) -> list:
    """Each open connection: its net and the two items it is between."""
    out = []
    for x in data.get("unconnected_items", []):
        net = ""
        for i in x.get("items", []):
            m = re.search(r"\[([^\]]+)\]", i.get("description", ""))
            if m:
                net = m.group(1)
                break
        out.append({"net": net, "items": _items(x, insts)})
    return out


def run_drc(pcb, out_json, refill_zones: bool | None = None, timeout: int | None = None,
            real_kinds=None, outstanding_kinds=None, allow=None) -> DrcReport:
    """Run kicad-cli DRC (zones refilled for the check only; the board file is
    not touched) and parse the JSON into buckets."""
    pcb, out_json = Path(pcb).absolute(), Path(out_json).absolute()   # kicad-cli runs in the board's folder
    cfg = active()
    refill_zones = cfg.drc_refill_zones if refill_zones is None else refill_zones
    timeout = cfg.timeout_drc if timeout is None else timeout
    real_kinds = cfg.drc_real_kinds if real_kinds is None else real_kinds
    outstanding_kinds = cfg.drc_outstanding_kinds if outstanding_kinds is None else outstanding_kinds
    footprint_kinds = cfg.drc_footprint_kinds
    pcb, out_json = Path(pcb), Path(out_json)
    project = pcb.with_suffix(".kicad_pro")
    if not project.exists():
        raise FileNotFoundError(
            "%s has no %s beside it. kicad-cli substitutes its own defaults for a board with no "
            "project file, so the report would measure KiCad rather than this board - on a real "
            "four-layer board that is four times the violations, including hundreds of track_width "
            "and clearance items that do not exist. Copy the .kicad_pro (and any .kicad_dru) next "
            "to the board and run it again." % (pcb, project.name))
    cmd = ["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out_json), str(pcb)]
    if refill_zones:
        cmd.insert(3, "--refill-zones")
    env = child_env()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(pcb.parent), timeout=timeout, env=env)
    report = DrcReport(out_json, command=cmd, returncode=proc.returncode,
                       stderr_tail="\n".join(proc.stderr.strip().splitlines()[-5:]),
                       real_kinds=tuple(real_kinds), outstanding_kinds=tuple(outstanding_kinds),
                       footprint_kinds=tuple(footprint_kinds))
    if not out_json.exists():
        raise RuntimeError("kicad-cli drc wrote no report (rc %d): %s" % (proc.returncode, report.stderr_tail))
    data = json.loads(out_json.read_text())
    report.by_type, report.permitted = count_violations(data, allow or {})
    report.severities = violation_severities(data, allow or {})
    report.libraries = library_table(pcb)
    unconnected = data.get("unconnected_items", [])
    report.unconnected = len(unconnected)
    for x in unconnected:
        for i in x.get("items", []):
            m = re.search(r"\[([^\]]+)\]", i.get("description", ""))
            if m:
                report.open_nets[m.group(1)] += 1
                break
    return report
