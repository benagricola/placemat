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

from ..settings import (DEFAULT_FOOTPRINT_KINDS, DEFAULT_OUTSTANDING_KINDS,
                        DEFAULT_REAL_KINDS, active)

# Clearance-class violations: a board with any of these is not done. The
# defaults; a project says otherwise with `[drc] real_kinds`.
REAL_KINDS = DEFAULT_REAL_KINDS
# Copper that is not yet joined: not accepted, reported separately so the
# missing plane or trace is named rather than counted with the shorts.
OUTSTANDING_KINDS = DEFAULT_OUTSTANDING_KINDS
# Footprint defects: not a board's fault and not a gate, but they make an
# extent unreliable, so they are named rather than buried.
FOOTPRINT_KINDS = DEFAULT_FOOTPRINT_KINDS


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

    @property
    def violations(self) -> int:
        return sum(self.by_type.values())

    @property
    def real(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in self.real_kinds}

    @property
    def outstanding(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in self.outstanding_kinds}

    @property
    def footprint_issues(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in self.footprint_kinds}

    @property
    def other(self) -> dict:
        return {k: v for k, v in self.by_type.items()
                if k not in self.real_kinds and k not in self.outstanding_kinds
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
        if self.other:
            parts.append("other " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.other.items())))
        if self.permitted:
            parts.append("permitted by their keepout %d" % sum(self.permitted.values()))
        return " | ".join(parts)


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
    from ..board_geometry import split_marker
    counted, permitted = Counter(), Counter()
    for v in data.get("violations", []):
        kind = v.get("type", "")
        m = _AREA_RE.search(v.get("description", ""))
        if kind == "items_not_allowed" and m:
            refs, nets = allow.get(split_marker(m.group(1))[0], (set(), set()))

            def ok(item):
                d = item.get("description", "")
                f = _FOOTPRINT_RE.match(d)
                if f:
                    return f.group(1) in refs
                n = _NET_RE.search(d)
                return bool(n) and n.group(1) in nets
            items = v.get("items", [])
            if items and all(ok(i) for i in items):
                permitted[kind] += 1
                continue
        counted[kind] += 1
    return dict(counted), dict(permitted)


def run_drc(pcb, out_json, refill_zones: bool | None = None, timeout: int | None = None,
            real_kinds=None, outstanding_kinds=None, allow=None) -> DrcReport:
    """Run kicad-cli DRC (zones refilled for the check only; the board file is
    not touched) and parse the JSON into buckets."""
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
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(pcb.parent), timeout=timeout, env=env)
    report = DrcReport(out_json, command=cmd, returncode=proc.returncode,
                       stderr_tail="\n".join(proc.stderr.strip().splitlines()[-5:]),
                       real_kinds=tuple(real_kinds), outstanding_kinds=tuple(outstanding_kinds),
                       footprint_kinds=tuple(footprint_kinds))
    if not out_json.exists():
        raise RuntimeError("kicad-cli drc wrote no report (rc %d): %s" % (proc.returncode, report.stderr_tail))
    data = json.loads(out_json.read_text())
    report.by_type, report.permitted = count_violations(data, allow or {})
    unconnected = data.get("unconnected_items", [])
    report.unconnected = len(unconnected)
    for x in unconnected:
        for i in x.get("items", []):
            m = re.search(r"\[([^\]]+)\]", i.get("description", ""))
            if m:
                report.open_nets[m.group(1)] += 1
                break
    return report
