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

from ..settings import DEFAULT_OUTSTANDING_KINDS, DEFAULT_REAL_KINDS, active

# Clearance-class violations: a board with any of these is not done. The
# defaults; a project says otherwise with `[drc] real_kinds`.
REAL_KINDS = DEFAULT_REAL_KINDS
# Copper that is not yet joined: not accepted, reported separately so the
# missing plane or trace is named rather than counted with the shorts.
OUTSTANDING_KINDS = DEFAULT_OUTSTANDING_KINDS


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
    def other(self) -> dict:
        return {k: v for k, v in self.by_type.items()
                if k not in self.real_kinds and k not in self.outstanding_kinds}

    def summary(self) -> str:
        parts = []
        parts.append("DRC clean" if not self.real else "DRC " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.real.items())))
        parts.append("unconnected %d" % self.unconnected)
        if self.outstanding:
            parts.append("outstanding " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.outstanding.items())))
        if self.other:
            parts.append("other " + ", ".join("%d %s" % (v, k) for k, v in sorted(self.other.items())))
        return " | ".join(parts)


def run_drc(pcb, out_json, refill_zones: bool | None = None, timeout: int | None = None,
            real_kinds=None, outstanding_kinds=None) -> DrcReport:
    """Run kicad-cli DRC (zones refilled for the check only; the board file is
    not touched) and parse the JSON into buckets."""
    cfg = active()
    refill_zones = cfg.drc_refill_zones if refill_zones is None else refill_zones
    timeout = cfg.timeout_drc if timeout is None else timeout
    real_kinds = cfg.drc_real_kinds if real_kinds is None else real_kinds
    outstanding_kinds = cfg.drc_outstanding_kinds if outstanding_kinds is None else outstanding_kinds
    pcb, out_json = Path(pcb), Path(out_json)
    cmd = ["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out_json), str(pcb)]
    if refill_zones:
        cmd.insert(3, "--refill-zones")
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(pcb.parent), timeout=timeout, env=env)
    report = DrcReport(out_json, command=cmd, returncode=proc.returncode,
                       stderr_tail="\n".join(proc.stderr.strip().splitlines()[-5:]),
                       real_kinds=tuple(real_kinds), outstanding_kinds=tuple(outstanding_kinds))
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
