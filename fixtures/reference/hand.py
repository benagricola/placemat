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


def measure_hand(pcb: pathlib.Path, work: pathlib.Path, toml: str | None,
                 context_script: pathlib.Path | None = None) -> HandFacts:
    from placemat.kicad.drc import run_drc
    from placemat.report import airwires_from_drc
    pcb, work = pathlib.Path(pcb), pathlib.Path(work)
    work.mkdir(parents=True, exist_ok=True)
    area, airwires = 0.0, {'crossings': 0, 'total_mm': 0.0}
    try:
        board_dir = work
        if context_script is not None:
            from placemat.settings import load
            from .place_ref import _copy_family
            source_family = pathlib.Path(context_script).parents[2]
            source_config = source_family / 'placemat.toml'
            original_toml = source_config.read_text() if source_config.exists() else None
            if toml != original_toml:
                raise ValueError('hand context must retain the original family configuration')
            copied_script = _copy_family(pathlib.Path(context_script), work / 'family')
            # Keep the original configuration's script paths valid. The hand
            # board is not a layout script, so its settings do not apply any
            # per-script placement overrides.
            board_dir = copied_script.parents[2] / 'hand-board'
            board_dir.mkdir(exist_ok=True)
            original_settings = load(source_family)
            copied_settings = load(board_dir)
            if original_settings != copied_settings:
                raise ValueError('copied hand context changed effective family settings')
            scripted_settings = load(pathlib.Path(context_script).parent, script=context_script)
            routing_keys = [field.name for field in dataclasses.fields(original_settings)
                            if field.name.startswith(('route_', 'check_', 'copper_', 'drc_', 'timeout_'))]
            changed = [key for key in routing_keys
                       if getattr(scripted_settings, key) != getattr(original_settings, key)]
            if changed:
                raise ValueError('hand routing has module-specific settings requiring an explicit association: '
                                 + ', '.join(changed))
            compared = [field.name for field in dataclasses.fields(original_settings) if field.compare]
            (work / 'context-settings.json').write_text(json.dumps({
                'source_family': str(source_family), 'copied_family': str(copied_script.parents[2]),
                'script_overrides_applied': False,
                'module_route_check_settings_equal': True,
                'effective_settings': {key: getattr(original_settings, key) for key in compared},
                'copied_settings_equal': True,
            }, indent=2) + '\n')
            toml = None     # inherit the intact family file above the board
        ref, test = board_dir / 'hand.kicad_pcb', board_dir / prepare.TEST
        shutil.copy2(pcb, ref)
        prepare._copy_project(pcb, ref, prepare.PROJECT_SUFFIXES)
        prepare.strip(ref, test)
        prepare._copy_project(ref, test, prepare.PROJECT_SUFFIXES)
        area = footprint_area(test)
        report_path = work / 'hand-drc.json'
        run_drc(test, report_path, refill_zones=True)
        airwires = airwires_from_drc(json.loads(report_path.read_text()))
        report = route_ref._route(test, work / 'route', toml)
    except Exception as error:  # Keep a failed reference beside the module result.
        return HandFacts(area, airwires['crossings'], airwires['total_mm'], 0.0, 0,
                         type(error).__name__, str(error)[:500])
    return HandFacts(area, airwires['crossings'], airwires['total_mm'],
                     report.get('closure_clean', 0.0), report.get('open_after', 0))
