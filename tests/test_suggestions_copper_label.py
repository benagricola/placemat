"""copper.keepout, copper.cross and label cases: suggestions that edit the script, and clear the finding."""
import pytest

from placemat import suggestions as sg
from tests.suggest_support import apply_and_resolve, resolve, suggestions_of

IMPORTS = ("from placemat import (board, Along, Beside, Box, CopperLayer, Edge, Face, Location, Near, Net, OnEdge, PadRef, Part,\n"
           "                      Priority)\nfrom placemat.cutouts import Circle, Path\n")

KEEPOUT = '''board.place(Part("u1"), at=Location(10, 50))
board.place(Part("c1"), at=Location(40, 50))
board.keepout(Path([(20, 20), (30, 20), (30, 30), (20, 30)]), "ant", at=Location(25, 25),
              excludes=("parts", "tracks", "vias"), why="an antenna's clearance")
board.track("VIN", [Location(5, 25), Location(45, 25)], layer=CopperLayer.F)
'''


def keepout_findings(plan):
    return [f for f in plan.findings if f.cause == "copper.keepout"]


def test_a_track_through_a_keepout_offers_the_net_the_layer_and_the_exclusions(tmp_path):
    board, plan, path = resolve(tmp_path, KEEPOUT, imports=IMPORTS)
    (f,) = keepout_findings(plan)
    texts = [s.text for s in f.suggestions]
    assert "Let net VIN into keepout `ant`" in texts
    assert "Keep keepout `ant` off the front layer" in texts
    assert "Let keepout `ant` forbid parts and vias only" in texts
    assert [s.rank for s in f.suggestions] == [1, 2, 3]


@pytest.mark.parametrize("wording", ["Let net VIN into keepout `ant`", "Keep keepout `ant` off the front layer",
                                     "Let keepout `ant` forbid parts and vias only"])
def test_each_keepout_suggestion_clears_the_finding_when_applied(tmp_path, wording):
    board, plan, path = resolve(tmp_path, KEEPOUT, imports=IMPORTS)
    (f,) = keepout_findings(plan)
    s = next(s for s in f.suggestions if s.text == wording)
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not keepout_findings(plan2)


def test_a_keepout_with_allow_gets_the_net_added_to_it(tmp_path):
    script = KEEPOUT.replace("why=", 'allow=[Net("GND")], why=')
    board, plan, path = resolve(tmp_path, script, imports=IMPORTS)
    (f,) = keepout_findings(plan)
    shown = sg.apply_suggestion(suggestions_of(plan), f.suggestions[0].id, dry_run=True)
    assert 'allow=[Net("GND"), Net("VIN")]' in shown.files[str(path)].after


def test_a_keepout_that_bars_parts_is_not_offered_an_allow(tmp_path):
    script = KEEPOUT.replace('excludes=("parts", "tracks", "vias"),', 'excludes=("parts", "tracks", "vias"), bars=[Part("r1")],') \
        .replace('excludes=("parts", "tracks", "vias"), bars', 'bars')
    board, plan, path = resolve(tmp_path, script, imports=IMPORTS)
    fs = keepout_findings(plan)
    assert fs and not [s for f in fs for s in f.suggestions if s.lever == "allow"]


CROSS = '''board.place(Part("u1"), at=Location(10, 55))
board.place(Part("c1"), at=Location(40, 55))
board.track("VIN", [Location(10, 25), Location(50, 25)], layer=CopperLayer.F)
board.track("OUT", [Location(30, 5), Location(30, 45)], layer=CopperLayer.F)
'''


def cross_findings(plan):
    return [f for f in plan.findings if f.cause == "copper.cross"]


def test_two_tracks_that_cross_and_neither_may_bridge_offer_a_bridge(tmp_path):
    board, plan, path = resolve(tmp_path, CROSS, imports=IMPORTS)
    (f,) = cross_findings(plan)
    (s,) = [s for s in f.suggestions if s.lever == "bridge"]
    assert s.text in ("Let the VIN track pass under OUT", "Let the OUT track pass under VIN")
    shown = sg.apply_suggestion(suggestions_of(plan), s.id, dry_run=True)
    assert "bridge=True" in shown.files[str(path)].after


def test_applying_the_bridge_clears_the_finding(tmp_path):
    board, plan, path = resolve(tmp_path, CROSS, imports=IMPORTS)
    (f,) = cross_findings(plan)
    s = next(s for s in f.suggestions if s.lever == "bridge")
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not cross_findings(plan2)


LABEL = '''board.place(Part("u1"), at=Location(20, 20))
board.place(Part("c1"), at=Location(20, 17.2))                    # where a north label on u1 lands
board.label(Part("u1"), "IN", side=Edge.NORTH, gap=0.3, reserve=False)
board.place(Part("r1"), at=Location(50, 50))
board.place(Part("j1"), at=Location(50, 20))
'''


def test_a_label_with_a_part_on_it_offers_the_other_sides(tmp_path):
    board, plan, path = resolve(tmp_path, LABEL, imports=IMPORTS)
    fs = [f for f in plan.findings if f.cause in ("label.sits_on", "label.no_spot")]
    assert fs
    texts = [s.text for s in fs[0].suggestions]
    assert any(t.startswith("Move the label of u1 to its ") for t in texts)
    assert not any("north side" in t for t in texts)         # the side it is on is not offered


def test_moving_the_label_to_another_side_clears_its_finding(tmp_path):
    board, plan, path = resolve(tmp_path, LABEL, imports=IMPORTS)
    f = next(f for f in plan.findings if f.cause == "label.sits_on")
    s = next(s for s in f.suggestions if s.text.startswith("Move the label"))
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not [f for f in plan2.findings if f.cause == "label.sits_on"]


def test_a_replayed_step_keeps_the_facts_of_a_finding_whose_suggestions_are_built_at_the_end(tmp_path):
    from placemat.context import run_script
    from tests.suggest_support import make_board
    board, plan, path = resolve(tmp_path, LABEL, imports=IMPORTS)
    first = [f for f in plan.findings if f.cause == "label.sits_on"]
    assert first and first[0].suggestions
    again = make_board()
    again.script_file = str(path)
    run_script(path, again)
    plan2 = again.resolve(reuse=plan.reuse)
    assert plan2.reuse["reused"] > 0
    second = [f for f in plan2.findings if f.cause == "label.sits_on"]
    assert [s.text for s in second[0].suggestions] == [s.text for s in first[0].suggestions]
