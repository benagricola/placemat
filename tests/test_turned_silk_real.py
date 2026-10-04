"""A real board (fixtures/fairing/turned_silk, three parts of one stamped cell as a run wrote them, turned 295 degrees): a
package's silk and two capacitors' silk stand at the board's 0.2 mm silk clearance, and KiCad finds them 0.199999 mm apart.

KiCad compares silk at the clearance itself on geometry rounded to the nanometre: the parts' positions written to the
nanometre, each footprint's silk turned and rounded on load, and the nearest point between two segments rounded again
(SEG::NearestPoint), then `dist_sq < (width / 2 + clearance) ** 2` with no DRC epsilon. Laid in the cell's own frame at
the nearest spot placement allows and turned as the writer turns a cell, the pair comes out a nanometre short at about
half of the whole-degree turns. Placement keeps `[place] silk_margin` past the clearance, which none of them lose."""
import dataclasses
import json
import pathlib
import shutil
import subprocess

import pytest

from tests.conftest import needs_kicad

pytestmark = [needs_kicad, pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")]

pcbnew = pytest.importorskip("pcbnew")

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/turned_silk"
PACKAGE, CAPS = "U30", ("C59", "C58")
# where the cell put each capacitor against the package, in the package's frame (the cell's own, unturned)
ALONG = {"C59": -0.98, "C58": 0.78}
ACROSS = 2.025
X, Y = 30.0, 30.0
# turns at which the pair at the bare clearance comes out short, with this pivot and shift
TURNS = (47.0, 155.0)


def _silk_overlaps(pcb: pathlib.Path) -> list:
    out = pcb.with_suffix(".json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out), str(pcb)],
                   check=True, capture_output=True, cwd=str(pcb.parent))
    return [v["description"] for v in json.loads(out.read_text())["violations"] if v["type"] == "silk_overlap"]


def _laid(tmp_path, across: dict, turn: float = 0.0, name: str = "layout") -> pathlib.Path:
    """The three parts in the cell's frame, each capacitor `across[ref]` from the package, then turned by `turn` about
    a pivot off every part and shifted, as the writer moves a cell (`write._move_cell`: Rotate, then Move)."""
    b = pcbnew.LoadBoard(str(FIXTURE / "layout.kicad_pcb"))
    fps = {fp.GetReference(): fp for fp in b.GetFootprints()}

    def put(fp, x, y, rot):
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    put(fps[PACKAGE], X, Y, 0.0)
    for ref in CAPS:
        put(fps[ref], X + ALONG[ref], Y + across[ref], 180.0)
    pivot = pcbnew.VECTOR2I(pcbnew.FromMM(X + 0.3), pcbnew.FromMM(Y + 0.7))
    for fp in b.GetFootprints():
        if turn:
            fp.Rotate(pivot, pcbnew.EDA_ANGLE(turn, pcbnew.DEGREES_T))
        fp.Move(pcbnew.VECTOR2I(pcbnew.FromMM(1.2345671), pcbnew.FromMM(-0.7654329)))
    path = tmp_path / (name + ".kicad_pcb")
    b.Save(str(path))
    shutil.copy(FIXTURE / "layout.kicad_pro", path.with_suffix(".kicad_pro"))
    return path


def _nearest_legal(tmp_path, **settings) -> dict:
    """How far from the package each capacitor may stand, to the nanometre: the nearest spot placement's silk check
    allows, under the physical envelope, in the cell's frame."""
    from placemat.kicad.read import read_board
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.settings import Settings
    from placemat.values import Location
    g = read_board(str(_laid(tmp_path, {r: ACROSS for r in CAPS}, name="probe")))
    occ = Occupancy(g, 0.5, settings=dataclasses.replace(Settings(), place_envelope="physical", **settings))
    u = g.footprint(PACKAGE)
    occ.commit(u, Placement(u.location, u.rotation, u.face))
    out = {}
    for ref in CAPS:
        c = g.footprint(ref)
        lo, hi = 0, 5000                        # nm past ACROSS
        while lo < hi:
            mid = (lo + hi) // 2
            at = Placement(Location(c.location.x, c.location.y + mid * 1e-6), c.rotation, c.face)
            if occ.legal(c, at) is None:
                hi = mid
            else:
                lo = mid + 1
        out[ref] = ACROSS + lo * 1e-6
    return out


def test_kicad_finds_the_reported_pair_a_nanometre_short(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "board")
    found = _silk_overlaps(tmp_path / "board/layout.kicad_pcb")
    assert len(found) == 2 and all("actual 0.199999 mm" in d for d in found), found


def test_at_the_bare_clearance_a_turn_loses_the_nanometre(tmp_path):
    bare = _nearest_legal(tmp_path, place_silk_margin=0.0)
    assert _silk_overlaps(_laid(tmp_path, bare, 0.0, "flat")) == []
    for turn in TURNS:
        assert _silk_overlaps(_laid(tmp_path, bare, turn, "t%g" % turn)), turn


def test_with_the_margin_no_turn_does(tmp_path):
    kept = _nearest_legal(tmp_path)
    assert all(kept[r] >= ACROSS + 0.001 for r in CAPS), kept
    for turn in (0.0,) + TURNS:
        assert _silk_overlaps(_laid(tmp_path, kept, turn, "t%g" % turn)) == [], turn
