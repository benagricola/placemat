"""A carried via stands where KiCad lets it: a keepout that excludes vias (and not parts) is a rule area KiCad
tests every via against (pcbexpr_functions.cpp `collidesWithArea`: the via's ring on each layer the area covers,
and its hole; drc_engine.cpp 584-645 builds the rule, drc_test_provider_disallow.cpp `checkDisallow` reports
`items_not_allowed`). A cell's via inside one gives way - moves out - or the cell is refused the spot."""
import json
import subprocess

import pytest

from placemat.copper import Track
from placemat.cutouts import Circle
from placemat.geometry import polys_overlap
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.values import Cell, CopperLayer, Location, Near, Net
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint, track
from tests.test_vias_give_way import _via

F, B = CopperLayer.F, CopperLayer.B


def _board(diameter=0.4, allow=(), excludes=("vias",), layers=None, at=(19.1, 21.9), **kw):
    """Cell m: U1 with a GND pad at (39.1, 40) and a GND via of the cell's 1.9 mm below it, joined by a tail.
    Searched on a hint 20 mm up and left with no room to move it lands there, its via at (19.1, 21.9), where a
    keepout of `diameter` stands."""
    copper = [_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m")]
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m")]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=("GND", "Y"))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=True, **kw)
    b.keepout(Circle(diameter), "nov", at=Location(*at), excludes=excludes, allow=allow, layers=layers,
              why="no vias here")
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    return b


def _vias(plan):
    return [c for c in plan.occupancy.copper if c.kind == "through" and c.owner == "m"]


def _inside(plan, x, y, r=0.225):
    """Whether a via ring at (x, y) is inside the keepout's polygon, as KiCad tests it."""
    from placemat.geometry import circle_polygon
    k = plan.keepouts["nov"]
    return polys_overlap(k.poly, circle_polygon(Location(x, y), r))


def test_a_cells_via_in_a_keepout_that_excludes_vias_moves_out_of_it():
    plan = _board().resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    [a] = plan.occupancy.given_way.values()
    assert a.kind == "move" and a.via == "m via 0"
    assert not _inside(plan, *a.to), a.to
    assert "nov" in a.under


def test_the_via_stays_where_it_is_drawn_when_the_keepout_does_not_reach_it():
    plan = _board(at=(19.1, 24.5)).resolve()
    assert plan.step("m").placement is not None
    assert not plan.occupancy.given_way


def test_a_via_of_a_net_the_keepout_allows_stays():
    plan = _board(allow=(Net("GND"),)).resolve()
    assert plan.step("m").placement is not None
    assert not plan.occupancy.given_way


def test_a_cell_whose_via_cannot_get_out_is_refused_the_spot():
    plan = _board(diameter=3.0).resolve()
    step = plan.step("m")
    assert step.placement is None, step.note
    assert "keepout 'nov' forbids vias" in step.note and "cannot give way" in step.note, step.note


def test_a_keepout_that_excludes_parts_only_leaves_the_via_be():
    plan = _board(excludes=("fill",)).resolve()
    assert plan.step("m").placement is not None
    assert not plan.occupancy.given_way


@needs_kicad
@pytest.mark.parametrize("dy,expected", [(0.0, True), (0.4, True), (0.45, False)])
def test_kicad_flags_a_via_exactly_when_placemat_does(tmp_path, dy, expected):
    """A via ring against a rule area that forbids vias: KiCad's `items_not_allowed` and placemat's test agree."""
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    plan = _board().resolve()
    k = plan.keepouts["nov"]
    x, y = 19.1, 21.9 + dy
    board = pcbnew.CreateEmptyBoard()
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    via.SetWidth(pcbnew.FromMM(0.45))
    via.SetDrill(pcbnew.FromMM(0.2))
    board.Add(via)
    _draw_keepouts(board, plan)
    pcb = tmp_path / "v.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    found = [v for v in json.loads(report.read_text()).get("violations", []) if v.get("type") == "items_not_allowed"]
    assert bool(found) == expected == _inside(plan, x, y), (dy, found)


def _with_rule_area(cell_of_area=None, excludes=frozenset(["vias"])):
    """The board of `_board`, without its declared keepout, but a rule area already on the generated board
    round the via's spot: the board's own, or one a cell `cell_of_area` brought."""
    import dataclasses
    from placemat.board_geometry import RuleArea
    b = _board(excludes=("fill",))
    ring = ((18.5, 21.3), (19.7, 21.3), (19.7, 22.5), (18.5, 22.5))
    ra = RuleArea("keepout nov [*.Cu]", cell_of_area, ring, frozenset([F, B]), excludes)
    b.geometry = dataclasses.replace(b.geometry, rule_areas=(ra,))
    return b


def test_a_rule_area_on_the_generated_board_that_forbids_vias_holds_a_cells_via_out():
    plan = _with_rule_area().resolve()
    step = plan.step("m")
    assert step.placement is None and "forbids vias" in step.note, step.note


def test_a_rule_area_that_forbids_tracks_only_leaves_the_via_be():
    plan = _with_rule_area(excludes=frozenset(["tracks"])).resolve()
    assert plan.step("m").placement is not None
    assert not plan.occupancy.given_way


def test_a_via_stands_clear_of_a_rule_area_a_placed_cell_brought():
    import dataclasses
    from placemat.board_geometry import RuleArea
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m"),
           footprint("K1", 5, 5, w=2, h=1, inst="k.k1", nets=("P", "Q"), cell="k")]
    copper = [_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m")]
    g = board_geometry(fps, cells=["m", "k"], copper=copper, width=50, height=50, extra_nets=("GND", "Y"))
    ra = RuleArea("keepout nov [*.Cu]", "k", ((10.0, 4.0), (12.0, 4.0), (12.0, 6.0), (10.0, 6.0)), frozenset([F, B]),
                  frozenset(["vias"]))
    g = dataclasses.replace(g, rule_areas=(ra,))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    kc = Occupancy(g)._geometry(g.cells["k"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Cell("k"), at=Location(kc.x + 8.1, kc.y + 16.9))                    # the area now stands on (18.1..20.1, 20.9..22.9)
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    plan = b.resolve()
    step = plan.step("m")
    assert step.placement is None and "forbids vias" in step.note, step.note


def test_the_native_and_python_searches_move_the_via_to_the_same_spot(monkeypatch):
    from placemat import geometry, giveway, placer
    if geometry._native is None:
        pytest.skip("no native module")
    got = {}
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        monkeypatch.setattr(giveway, "_NATIVE_MOVE_SEARCH", on)
        plan = _board().resolve()
        [a] = plan.occupancy.given_way.values()
        got[on] = (plan.step("m").placement, a.kind, a.to)
    assert got[True] == got[False]


def test_with_every_way_to_give_way_off_a_via_in_the_keepout_still_refuses_the_spot():
    from placemat.settings import Settings
    off = Settings(place_via_share=0.0, place_via_move=0.0, place_via_leave=0.0, place_via_route=0.0,
                   place_drops_keep=1.0)
    step = _board(settings=off).resolve().step("m")
    assert step.placement is None and "keepout 'nov' forbids vias" in step.note, step.note


def test_a_via_already_placed_gives_way_to_a_rule_area_a_cell_brings_when_it_lands():
    import dataclasses
    from placemat.board_geometry import RuleArea
    from placemat.geometry import circle_polygon
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m"),
           footprint("K1", 5, 5, w=2, h=1, inst="k.k1", nets=("P", "Q"), cell="k")]
    copper = [_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m")]
    g = board_geometry(fps, cells=["m", "k"], copper=copper, width=60, height=60, extra_nets=("GND", "Y"))
    ra = RuleArea("keepout nov [*.Cu]", "k", ((10.0, 4.0), (12.0, 4.0), (12.0, 6.0), (10.0, 6.0)), frozenset([F, B]),
                  frozenset(["vias"]))
    g = dataclasses.replace(g, rule_areas=(ra,))
    mc = Occupancy(g)._geometry(g.cells["m"]).reference.location
    kc = Occupancy(g)._geometry(g.cells["k"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Cell("m"), at=Location(mc.x, mc.y))
    b.place(Cell("k"), at=Location(kc.x + 27.2, kc.y + 36.9))       # its area now stands on (37.2..39.2, 40.9..42.9)
    plan = b.resolve()
    assert plan.step("k").placement is not None, plan.step("k").note
    [a] = plan.occupancy.given_way.values()
    assert a.home == "m" and a.kind == "move", a
    assert not polys_overlap(((37.2, 40.9), (39.2, 40.9), (39.2, 42.9), (37.2, 42.9)),
                             circle_polygon(Location(*a.to), 0.225))


def _holed_board(**kw):
    """The cell of `_board`, searched where its via's tail (x = 19.1, y 20..21.9) runs through a hole in the board."""
    copper = [_via("GND", 39.1, 41.9, owner="m"), track("GND", 39.1, 40.0, 39.1, 41.9, w=0.2, owner="m")]
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m")]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=("GND", "Y"))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    b = Board(g, edge_margin=0.1, keep_going=True, **kw)
    b.size(width=50.0, height=50.0, holes=[Circle(0.6).path_at(Location(19.1, 21.0))])
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    return b


def test_a_cell_whose_carried_tail_runs_through_a_hole_in_the_board_is_refused_the_spot():
    step = _holed_board().resolve().step("m")
    assert step.placement is None, step.note
    assert "GND track from" in step.note and "is inside a cutout" in step.note, step.note
