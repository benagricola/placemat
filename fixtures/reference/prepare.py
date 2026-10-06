"""Prepare a reference board for test (a): the human copper, the stripped board, and what DRC says of it.

    prepare(board, src, work) -> Prepared

`src` is the folder fetch.fetch returns. `work` gets ref.kicad_pcb (the human
copper, loaded and saved with pcbnew for a KiCad 5 board, which writes the
.kicad_pro with its net classes from the legacy .pro beside it), test.kicad_pcb
(the same with its tracks, arcs, vias and zone fills stripped by the router's
strip_copper_only.py, zone definitions kept) and baseline-drc.json (kicad-cli
DRC of test.kicad_pcb). Copper layers keep their names: placemat reads them by
the standard ones.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import shutil
import subprocess

from placemat.kicad.drc import run_drc
from placemat.kicad.route import router_dir

from . import fetch

REF = "ref.kicad_pcb"
TEST = "test.kicad_pcb"
BASELINE = "baseline-drc.json"
STRIP_SCRIPT = "tests/stress/strip_copper_only.py"
PROJECT_SUFFIXES = (".kicad_pro", ".kicad_dru")
LEGACY_PROJECT_SUFFIX = ".pro"
STRIP_TIMEOUT_S = 600
IGNORED_TYPES = ("courtyards_overlap",)
IGNORED_PREFIXES = ("silk_", "lib_footprint_")
NET_IN_DESCRIPTION = re.compile(r"\[([^\]]+)\]")
NO_NET = "<no net>"   # what KiCad puts in the brackets of an item with no net


@dataclasses.dataclass(frozen=True)
class Violation:
    type: str
    nets: tuple[str, ...]
    at_mm: tuple[float, float]


@dataclasses.dataclass(frozen=True)
class HumanCopper:
    vias: int
    track_mm: float


@dataclasses.dataclass(frozen=True)
class Prepared:
    ref: pathlib.Path
    test: pathlib.Path
    baseline: list[Violation]
    layers: int
    human: HumanCopper


def violations(drc_json: pathlib.Path) -> list[Violation]:
    """The errors of a kicad-cli DRC report, without the silk, courtyard and library kinds. KiCad names an
    item's net inside its description ("Track [GND] on F.Cu"), so `nets` are read from there."""
    out = []
    for v in json.loads(pathlib.Path(drc_json).read_text()).get("violations", []):
        kind = v.get("type", "")
        if v.get("severity") != "error" or kind in IGNORED_TYPES or kind.startswith(IGNORED_PREFIXES):
            continue
        items = v.get("items", [])
        nets = tuple(dict.fromkeys(m.group(1) for i in items for m in [NET_IN_DESCRIPTION.search(i.get("description", ""))] if m and m.group(1) != NO_NET))
        pos = items[0].get("pos", {}) if items else {}
        out.append(Violation(kind, nets, (float(pos.get("x", 0.0)), float(pos.get("y", 0.0)))))
    return out


def measure(pcb: pathlib.Path) -> tuple[int, HumanCopper]:
    """(copper layer count, vias and track length) of a board, with pcbnew."""
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    vias, length = 0, 0
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            vias += 1
        else:
            length += t.GetLength()
    return board.GetCopperLayerCount(), HumanCopper(vias, pcbnew.ToMM(length))


def _upgrade(pcb: pathlib.Path) -> None:
    import pcbnew
    pcbnew.SaveBoard(str(pcb), pcbnew.LoadBoard(str(pcb)))


def _copy_project(src_board: pathlib.Path, dst_board: pathlib.Path, suffixes) -> None:
    for suffix in suffixes:
        beside = src_board.with_suffix(suffix)
        if beside.exists():
            shutil.copy(beside, dst_board.with_suffix(suffix))


def strip(src: pathlib.Path, dst: pathlib.Path) -> None:
    root = pathlib.Path(router_dir())
    python = root / ".venv/bin/python"
    proc = subprocess.run([str(python), "-X", "utf8", str(root / STRIP_SCRIPT), str(src), str(dst)],
                          capture_output=True, text=True, cwd=str(root), timeout=STRIP_TIMEOUT_S)
    if proc.returncode != 0 or not dst.exists():
        raise RuntimeError("strip_copper_only failed (rc %d): %s" % (proc.returncode, proc.stderr.strip()[-500:]))


def prepare(board: fetch.Board, src: pathlib.Path, work: pathlib.Path) -> Prepared:
    work.mkdir(parents=True, exist_ok=True)
    original = pathlib.Path(src) / board.board
    ref, test = work / REF, work / TEST
    shutil.copy(original, ref)
    if board.kicad5:
        # pcbnew reads the legacy .pro beside the board and writes its net classes into the .kicad_pro
        _copy_project(original, ref, (LEGACY_PROJECT_SUFFIX,))
        _upgrade(ref)
    _copy_project(original, ref, PROJECT_SUFFIXES)
    strip(ref, test)
    _copy_project(ref, test, PROJECT_SUFFIXES)
    layers, human = measure(ref)
    run_drc(test, work / BASELINE, refill_zones=True)
    return Prepared(ref, test, violations(work / BASELINE), layers, human)
