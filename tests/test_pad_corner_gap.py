"""A copper finding measures a pad read from KiCad as the effective shape
KiCad's DRC collides (`PAD::GetEffectiveShape`: a rounded rectangle is a
rectangle and four round-ended segments), not its outline. The outline is
polygonised with the arc error outside the copper, so a track passing a
rounded corner read a few micrometres nearer than KiCad measures it.

fixtures/fairing/pad_corner is a run's board cut down to a 0402 capacitor
(rounded-rectangle pads, turned a quarter) and a 0.127 mm track of another
net running at 45 degrees past pad 1's corner. KiCad's DRC measures them
0.129166 mm apart, clear of the 0.127 mm rule; measured by the pad's outline
they were 0.126421 mm apart, a finding."""
import json
import math
import pathlib
import shutil
import subprocess

import pytest

from placemat.layout import Board
from placemat.values import Bend, CopperLayer, Location, Net, Part
from tests.conftest import needs_kicad

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/pad_corner"
KICAD_GAP = 0.129166          # pcbnew: the pad's effective shape against the track's
RULE = 0.127
NEARER = (-0.003, 0.003)      # moves the track 0.003 * sqrt(2) mm nearer the corner, square to it


def _read():
    import dataclasses
    from placemat.kicad.read import read_board
    g = read_board(str(FIXTURE / "layout.kicad_pcb"))
    (track,) = [c for c in g.copper if c.kind == "track"]
    return dataclasses.replace(g, copper=()), track


def _plan(shift=(0.0, 0.0), turn=0.0):
    """The part placed as the fixture has it, turned `turn` degrees more about its origin, and the track declared
    where the fixture has it, turned with the part and moved by `shift`."""
    g, track = _read()
    (fp,) = g.footprints
    c, a = fp.location, math.radians(turn)

    def at(p):
        x, y = p[0] - c.x, p[1] - c.y
        x, y = x * math.cos(a) + y * math.sin(a), y * math.cos(a) - x * math.sin(a)     # KiCad's sense, y down
        return Location(c.x + x + shift[0], c.y + y + shift[1])
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part(fp.inst), at=c, rotation=fp.rotation + turn)
    b.track(Net("N1"), [at(p) for p in track.anchors], layer=CopperLayer.F, width=track.width_mm,
            bend=Bend.ARC_FREE)         # one straight leg at the angle given
    return b.resolve()


def _gaps(plan) -> list:
    return [f.facts["hit"]["gap_mm"] for f in plan.findings if f.startswith("copper N1")]


@needs_kicad
def test_a_track_past_a_rounded_pad_corner_is_measured_as_kicad_measures_it():
    assert _gaps(_plan()) == []


@needs_kicad
def test_the_same_track_nearer_is_found_at_kicads_gap():
    (gap,) = _gaps(_plan(shift=NEARER))
    assert gap == pytest.approx(KICAD_GAP - math.hypot(*NEARER), abs=2e-6)


@needs_kicad
@pytest.mark.parametrize("turn", [90.0, 180.0, 30.0])
def test_the_pad_is_measured_where_the_part_is_turned(turn):
    (gap,) = _gaps(_plan(shift=_turned(NEARER, turn), turn=turn))
    assert gap == pytest.approx(KICAD_GAP - math.hypot(*NEARER), abs=2e-6)


def _turned(v, turn):
    a = math.radians(turn)
    return (v[0] * math.cos(a) + v[1] * math.sin(a), v[1] * math.cos(a) - v[0] * math.sin(a))


@needs_kicad
def test_pcbnew_measures_the_fixture_at_kicads_gap():
    import pcbnew
    b = pcbnew.LoadBoard(str(FIXTURE / "layout.kicad_pcb"))
    (t,) = list(b.GetTracks())
    pad = next(p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNumber() == "1")
    ps, ts = pad.GetEffectiveShape(pcbnew.F_Cu), t.GetEffectiveShape(pcbnew.F_Cu)
    lo, hi = 0, 1000000         # the least clearance they collide within
    while hi - lo > 1:
        m = (lo + hi) // 2
        lo, hi = (lo, m) if ps.Collide(ts, m) else (m, hi)
    assert hi == round(KICAD_GAP * 1e6)


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")
def test_kicads_drc_passes_the_fixture_and_finds_it_nearer(tmp_path):
    text = (FIXTURE / "layout.kicad_pcb").read_text()
    assert text.count("(start 17.5 42.4)") == 1 and text.count("(end 18.1 43)") == 1

    def clearance(dx, dy):
        pcb = tmp_path / "layout.kicad_pcb"
        pcb.write_text(text.replace("(start 17.5 42.4)", "(start %.6f %.6f)" % (17.5 + dx, 42.4 + dy))
                       .replace("(end 18.1 43)", "(end %.6f %.6f)" % (18.1 + dx, 43.0 + dy)))
        shutil.copy(FIXTURE / "layout.kicad_pro", tmp_path / "layout.kicad_pro")
        out = tmp_path / "drc.json"
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out), str(pcb)],
                       check=True, capture_output=True, cwd=str(tmp_path))
        return [v["description"] for v in json.loads(out.read_text())["violations"] if v["type"] == "clearance"]
    assert clearance(0.0, 0.0) == []
    (v,) = clearance(*NEARER)
    assert "actual 0.1249 mm" in v, v
