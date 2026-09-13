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

# Clearance-class violations: a board with any of these is not done.
REAL_KINDS = ("clearance", "shorting_items", "track_width", "annular_width", "hole_clearance",
              "hole_to_hole", "courtyards_overlap", "copper_edge_clearance")
# Copper that is not yet joined: not accepted, reported separately so the
# missing plane or trace is named rather than counted with the shorts.
OUTSTANDING_KINDS = ("via_dangling", "track_dangling", "isolated_copper")


@dataclass
class DrcReport:
    path: Path
    by_type: dict = field(default_factory=dict)
    unconnected: int = 0
    open_nets: Counter = field(default_factory=Counter)
    command: list = field(default_factory=list)
    returncode: int = 0
    stderr_tail: str = ""

    @property
    def violations(self) -> int:
        return sum(self.by_type.values())

    @property
    def real(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in REAL_KINDS}

    @property
    def outstanding(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k in OUTSTANDING_KINDS}

    @property
    def other(self) -> dict:
        return {k: v for k, v in self.by_type.items() if k not in REAL_KINDS and k not in OUTSTANDING_KINDS}

    def summary(self) -> str:
        parts = []
        parts.append("DRC clean" if not self.real else "DRC " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.real.items())))
        parts.append("unconnected %d" % self.unconnected)
        if self.outstanding:
            parts.append("outstanding " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.outstanding.items())))
        if self.other:
            parts.append("other " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.other.items())))
        return " | ".join(parts)


def run_drc(pcb, out_json, refill_zones: bool = True, timeout: int = 600) -> DrcReport:
    """Run kicad-cli DRC (zones refilled for the check only; the board file is
    not touched) and parse the JSON into buckets."""
    pcb, out_json = Path(pcb), Path(out_json)
    cmd = ["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out_json), str(pcb)]
    if refill_zones:
        cmd.insert(3, "--refill-zones")
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(pcb.parent), timeout=timeout, env=env)
    report = DrcReport(out_json, command=cmd, returncode=proc.returncode,
                       stderr_tail="\n".join(proc.stderr.strip().splitlines()[-5:]))
    if not out_json.exists():
        raise RuntimeError("kicad-cli drc wrote no report (rc %d): %s" % (proc.returncode, report.stderr_tail))
    data = json.loads(out_json.read_text())
    report.by_type = dict(Counter(v["type"] for v in data.get("violations", [])))
    unconnected = data.get("unconnected_items", [])
    report.unconnected = len(unconnected)
    for x in unconnected:
        for i in x.get("items", []):
            m = re.search(r"\[([^\]]+)\]", i.get("description", ""))
            if m:
                report.open_nets[m.group(1)] += 1
                break
    return report
