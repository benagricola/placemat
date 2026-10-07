"""Measure hand placements beside generated module placements, under the runner's lock."""
from __future__ import annotations

import dataclasses
import json
import pathlib
import shutil

from . import prepare, route_ref

HAND_DIR = 'hand'


@dataclasses.dataclass(frozen=True)
class HandFacts:
    area_mm2: float
    crossings: int
    airwire_mm: float
    closure_clean: float
    open: int
    failure: str = ''
    detail: str = ''


def reference_of(script: pathlib.Path) -> pathlib.Path | None:
    script = pathlib.Path(script)
    pcb = script.parents[2] / HAND_DIR / (script.name.removesuffix('_layout.py') + '.kicad_pcb')
    return pcb if pcb.is_file() else None


def footprint_area(pcb: pathlib.Path) -> float:
    """Box enclosing front/back courtyards, or the footprint bounds if absent."""
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    xs, ys = [], []
    for footprint in board.GetFootprints():
        footprint.BuildCourtyardCaches()
        boxes = [footprint.GetCourtyard(layer).BBox() for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd)
                 if footprint.GetCourtyard(layer).OutlineCount()]
        for box in boxes or [footprint.GetBoundingBox(False)]:
            xs.extend((box.GetLeft(), box.GetRight()))
            ys.extend((box.GetTop(), box.GetBottom()))
    if not xs:
        return 0.0
    return round(pcbnew.ToMM(max(xs) - min(xs)) * pcbnew.ToMM(max(ys) - min(ys)), 2)


def measure_hand(pcb: pathlib.Path, work: pathlib.Path, toml: str | None) -> HandFacts:
    from placemat.kicad.drc import run_drc
    from placemat.report import airwires_from_drc
    pcb, work = pathlib.Path(pcb), pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    ref, test = work / 'hand.kicad_pcb', work / prepare.TEST
    area, airwires = 0.0, {'crossings': 0, 'total_mm': 0.0}
    try:
        shutil.copy2(pcb, ref)
        prepare._copy_project(pcb, ref, prepare.PROJECT_SUFFIXES)
        prepare.strip(ref, test)
        prepare._copy_project(ref, test, prepare.PROJECT_SUFFIXES)
        area = footprint_area(test)
        report_path = work / 'hand-drc.json'
        run_drc(test, report_path, refill_zones=True)
        airwires = airwires_from_drc(json.loads(report_path.read_text()))
        report = route_ref._route(test, work / 'route', toml)
        if report.get('error'):
            raise RuntimeError(str(report['error']))
    except Exception as error:  # Keep a failed reference beside the module result.
        return HandFacts(area, airwires['crossings'], airwires['total_mm'], 0.0, 0,
                         type(error).__name__, str(error)[:500])
    return HandFacts(area, airwires['crossings'], airwires['total_mm'],
                     report.get('closure_clean', 0.0), report.get('open_after', 0))
