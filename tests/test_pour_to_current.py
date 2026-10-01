"""`reach=Reach.CURRENT` on a fitted pour: its copper grows into the room round
it only as far as its net's current-path width needs, the width and the need
being the check's own (`checks.pour_current`, over `_pairs`), the distance the
smallest multiple of `[copper] pour_reach_step` that meets it (at most
`pour_reach_max`), and where room runs out a finding names the neck and the
width reached.

Plan tests are pure (synthetic boards); the written-board test builds a
from-scratch pcbnew board with two parts carrying current."""
import dataclasses

import pcbnew
import pytest

from placemat import checks, pourfit
from placemat.checks import current_paths
from placemat.geometry import poly_distance
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Net, PadRef, Part, Reach
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, declared_findings
from tests.test_pour_fitted import CLEARANCE, _part, _pours, _refs
from tests.test_pour_reach import _declared as _declared_reach, _written_node

F = CopperLayer.F
STEP = Settings().copper_pour_reach_step


def _carry(fp, amps):
    return dataclasses.replace(fp, fields={"Pm.I": amps})


def _node(extra=(), reach=Reach.CURRENT, amps=("3.6A", "3.6A"), settings=None, **kw):
    """A switch node of a 1.0 x 0.8 pad and a 1.4 x 0.8 pad offset diagonally, each part carrying `amps`."""
    a = _carry(_part("S0", "SW", 10.0, 10.0, 1.0, 0.8), amps[0])
    b = _carry(_part("S1", "SW", 12.5, 11.5, 1.4, 0.8), amps[1])
    geometry = board_geometry([a, b] + list(extra), width=60, height=60, clearance=CLEARANCE)
    board = Board(geometry, edge_margin=1.0, **({"settings": settings} if settings else {}))
    board.pour(Net("SW"), _refs("s", 2), layer=F, swallow_pads=True, reach=reach, **kw)
    return board, (a, b)


def _reading(plan, parts, settings=None, amps=3.6):
    """What `check current-path` reads off the pour the plan drew: (width, need) or None where nothing narrows."""
    settings = settings or Settings()
    (p,) = _pours(plan)
    pads = [(fp.ref, "1", fp.pads[0].outlines[0]) for fp in parts]
    carriers = {fp.ref: amps for fp in parts}
    return checks.pour_current("SW", F, pads, [], [pourfit.offset(p.points, p.stroke / 2.0)], carriers, {},
                               settings.check_rise_c, checks.COPPER_OZ, settings.check_zone_step)


def _grown(plan, bare):
    """How far the plan's pour is grown past the bare fitted outline, on its left side."""
    (p,) = _pours(plan)
    return Box.of_points(bare.points).left - Box.of_points(p.points).left


def _bare():
    board, parts = _node(reach=None)
    return _pours(board.resolve())[0], parts


def test_the_pour_grows_until_the_check_passes_and_no_further():
    bare, parts = _bare()
    assert _reading(_node(reach=None)[0].resolve(), parts).width < _reading(_node(reach=None)[0].resolve(), parts).need
    board, parts = _node()
    plan = board.resolve()
    assert not declared_findings(plan), plan.findings
    got = _reading(plan, parts)
    assert got is not None and got.width >= got.need
    chosen = _grown(plan, bare)
    assert chosen > 0.0 and chosen / STEP == pytest.approx(round(chosen / STEP), abs=1e-3)
    # it is `reach=` of that distance, and a step less than it fails the check
    same, _ = _node(reach=round(chosen, 6))
    assert _pours(same.resolve())[0].points == _pours(plan)[0].points
    less, _ = _node(reach=round(chosen - STEP, 6))
    short = _reading(less.resolve(), parts)
    assert short.width < short.need


def test_a_hull_that_already_meets_the_need_is_the_fitted_outline_with_no_finding():
    bare, _ = _bare()
    board, _ = _node(amps=("0.3A", "0.3A"))
    plan = board.resolve()
    assert _pours(plan)[0].points == bare.points
    assert not declared_findings(plan), plan.findings


def test_the_need_follows_the_current_on_the_parts():
    bare, _ = _bare()
    plan_less = _node(amps=("3.3A", "3.3A"))[0].resolve()
    plan_more = _node(amps=("3.6A", "3.6A"))[0].resolve()
    assert 0.0 < _grown(plan_less, bare) < _grown(plan_more, bare)


def test_the_lesser_current_of_the_two_parts_is_what_flows_between_them():
    bare, _ = _bare()
    same = _node(amps=("3.3A", "3.3A"))[0].resolve()
    mixed = _node(amps=("3.6A", "3.3A"))[0].resolve()
    assert _pours(mixed)[0].points == _pours(same)[0].points


def test_room_limited_by_another_nets_pad_is_a_finding_naming_the_neck_and_the_width_reached():
    """Foreign pads stand on both sides of the gap between the two pads: the copper cannot widen there."""
    above = _part("B0", "B", 12.0, 9.8, 1.5, 0.6)
    below = _part("B1", "B", 11.0, 12.2, 1.5, 0.6)
    board, parts = _node([above, below], amps=("3.3A", "3.3A"))
    plan = board.resolve()
    (note,) = [f for f in declared_findings(plan) if f.startswith("pour SW")]
    assert "SW" in note and "3.3 A" in note and "mm" in note
    got = _reading(plan, parts, amps=3.3)
    assert got.width < got.need
    assert "%.2f mm" % got.width in note and "%.2f mm" % got.need in note
    assert "(%.2f, %.2f)" % got.point in note
    assert "B0" in note or "B1" in note                       # the copper in the way
    # drawn at the reach where the width stopped gaining: not grown to the maximum
    bare, _ = _bare()
    assert _grown(plan, bare) < Settings().copper_pour_reach_max / 2.0


def test_the_pour_keeps_the_clearance_of_the_copper_it_grew_towards():
    other = _part("B0", "B", 11.2, 7.9, 0.8, 0.8)
    board, _ = _node([other])
    (p,) = _pours(board.resolve())
    assert poly_distance(pourfit.offset(p.points, p.stroke / 2.0), other.pads[0].outlines[0]) >= CLEARANCE - 1e-6


def test_a_smaller_step_is_a_closer_fit_and_a_larger_one_a_coarser():
    bare, _ = _bare()
    fine = _grown(_node(settings=Settings(copper_pour_reach_step=0.02))[0].resolve(), bare)
    coarse = _grown(_node(settings=Settings(copper_pour_reach_step=0.5))[0].resolve(), bare)
    assert coarse / 0.5 == pytest.approx(round(coarse / 0.5), abs=1e-3)
    assert fine / 0.02 == pytest.approx(round(fine / 0.02), abs=1e-3)
    assert fine <= coarse + 1e-6 and coarse - fine < 0.5 + 1e-6


def test_a_maximum_under_the_need_leaves_a_finding():
    board, parts = _node(settings=Settings(copper_pour_reach_max=0.1))
    plan = board.resolve()
    assert any(f.startswith("pour SW") and "needs" in f for f in declared_findings(plan)), plan.findings
    got = _reading(plan, parts)
    assert got.width < got.need
    bare, _ = _bare()
    assert _grown(plan, bare) <= 0.1 + 1e-6


def test_a_net_no_part_carries_current_on_is_refused():
    a, b = _part("S0", "SW", 10.0, 10.0, 1.0, 2.5), _part("S1", "SW", 12.7, 11.1, 1.9, 2.5)
    board = Board(board_geometry([a, b], width=60, height=60, clearance=CLEARANCE), edge_margin=1.0)
    with pytest.raises(ValueError, match=r"Pm\.I"):
        board.pour(Net("SW"), _refs("s", 2), layer=F, swallow_pads=True, reach=Reach.CURRENT)


def test_a_net_one_part_carries_current_on_is_refused():
    a = _carry(_part("S0", "SW", 10.0, 10.0, 1.0, 2.5), "3.6A")
    b = _part("S1", "SW", 12.7, 11.1, 1.9, 2.5)
    board = Board(board_geometry([a, b], width=60, height=60, clearance=CLEARANCE), edge_margin=1.0)
    with pytest.raises(ValueError, match="two parts"):
        board.pour(Net("SW"), _refs("s", 2), layer=F, swallow_pads=True, reach=Reach.CURRENT)


def test_members_that_hold_one_carrier_are_a_finding_and_the_pour_is_not_drawn():
    a = _carry(_part("S0", "SW", 10.0, 10.0, 1.0, 2.5), "3.6A")
    b = _part("S1", "SW", 12.7, 11.1, 1.9, 2.5)
    c = _carry(_part("S2", "SW", 30.0, 30.0, 1.0, 1.0), "3.6A")
    board = Board(board_geometry([a, b, c], width=60, height=60, clearance=CLEARANCE), edge_margin=1.0)
    board.pour(Net("SW"), _refs("s", 2), layer=F, swallow_pads=True, reach=Reach.CURRENT)
    plan = board.resolve()
    assert not _pours(plan)
    assert any(f.startswith("pour SW") and "S2" not in f and "carr" in f for f in declared_findings(plan)), plan.findings


def test_the_form_is_refused_with_width_and_without_swallow_pads():
    board, _ = _node(reach=None)
    with pytest.raises(ValueError, match="reach= grows a fitted pour"):
        board.pour(Net("SW"), _refs("s", 2), layer=F, reach=Reach.CURRENT)
    with pytest.raises(ValueError, match="reach= grows a fitted pour"):
        board.pour(Net("SW"), _refs("s", 2), layer=F, swallow_pads=True, width=1.0, reach=Reach.CURRENT)


def test_a_declaration_with_the_form_digests_apart_from_one_without_and_a_number_stays_as_it_was():
    from placemat import reuse
    plain, cur, num = _node(reach=None)[0], _node()[0], _node(reach=0.4)[0]
    d = {k: reuse.canonical(x._copper) for k, x in (("plain", plain), ("cur", cur), ("num", num))}
    assert "reach" not in d["plain"]
    assert d["cur"] != d["plain"] and d["cur"] != d["num"] and "reach=0.4" in d["num"]


def test_a_current_pour_is_a_graphic_polygon_and_never_a_zone():
    plan = _node()[0].resolve()
    (p,) = _pours(plan)
    assert p.fitted


def test_the_settings_have_defaults_above_zero():
    s = Settings()
    assert s.copper_pour_reach_step > 0 and s.copper_pour_reach_max > s.copper_pour_reach_step


# ---------------------------------------------------------------- written boards


@needs_kicad
def test_the_written_pour_passes_current_path_and_drc(tmp_path):
    from placemat.kicad.drc import run_drc
    pcb = _written_node(tmp_path)
    plan = _declared_reach(pcb, Reach.CURRENT).resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    apply_plan(pcb, plan)
    assert not list(pcbnew.LoadBoard(str(pcb)).Zones())
    v = {x.subject: x for x in current_paths(read_board(pcb))}["SW"]
    assert v.ok is True, v
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.by_type.get("clearance", 0) == 0 and report.by_type.get("shorting_items", 0) == 0, report.by_type


@needs_kicad
def test_a_pad_in_the_room_is_kept_clear_of_and_the_written_pour_still_passes(tmp_path):
    from placemat.kicad.drc import run_drc
    pcb = _written_node(tmp_path, foreign=[("1", "PROBE", 11.0, 8.6, 0.8, 0.8)])
    plan = _declared_reach(pcb, Reach.CURRENT).resolve()
    apply_plan(pcb, plan)
    v = {x.subject: x for x in current_paths(read_board(pcb))}["SW"]
    assert v.ok is True, v
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.by_type.get("clearance", 0) == 0 and report.by_type.get("shorting_items", 0) == 0, report.by_type
