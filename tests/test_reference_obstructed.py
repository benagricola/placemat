"""An unrelated part blocks a current-width route that can join at class width."""
import json
import pathlib

from tests.conftest import needs_kicad, needs_router

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/obstructed_route"


@needs_kicad
def test_the_board_is_two_carriers_and_a_part_between_them():
    from placemat.checks import carriers_of
    from placemat.kicad.read import read_board
    geometry = read_board(str(FIXTURE / "layout.kicad_pcb"))
    assert carriers_of(geometry) == {"VB": {"J1": 3.0, "J2": 3.0}}
    wall = geometry.footprint("U1")
    assert sorted(p.net for p in wall.pads) == ["N1", "N2", "N3", "N4", "N5"]
    xs = sorted(fp.location.x for fp in geometry.footprints)
    assert xs[0] < wall.location.x < xs[-1]


def test_the_recorded_result_names_the_blocker():
    rec = json.loads((ROOT / "fixtures/reference/results.json").read_text())["fixtures"]["obstructed-route"]
    legs = rec["phases"][0]
    assert (legs["name"], legs["asked"], legs["joined"]) == ("legs", 1, 0)
    (opened,) = legs["open"]
    assert (opened["net"], opened["from"], opened["to"], opened["outcome"]) == (
        "VB", {"ref": "J1", "pad": "1"}, {"ref": "J2", "pad": "1"}, "failed")
    assert "U1" in opened["blockers"]
    assert legs["final_closure_clean"] == 0.0 and rec["widths_failed"] == 1


@needs_kicad
@needs_router
def test_a_route_reproduces_the_recorded_result(tmp_path):
    from fixtures.reference import route_ref
    got = route_ref.run_local("obstructed-route", tmp_path)
    old = json.loads((ROOT / "fixtures/reference/results.json").read_text())["fixtures"]["obstructed-route"]
    comparison = route_ref.compare_local(old, got, {"placemat", "krt", "pcb"})
    assert got.passed and (comparison.status == "same" or
                          comparison.status == "not comparable" and comparison.value == "same"), (comparison, got)
