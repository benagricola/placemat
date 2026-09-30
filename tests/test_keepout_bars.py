"""A keepout that names what it bars: `bars=` keeps the named parts out and
lets every other part in."""
import pytest

from placemat.cutouts import Circle
from placemat.layout import Board, PlacementCollision
from placemat.values import Cell, CopperLayer, Location, Net, Part
from tests.fixtures import board_geometry, footprint


def _board(*specs, extra=()):
    """specs: (inst, height in mm or None). Every part sits off the board's
    middle so the script places it; `extra` are further footprints the
    script never names."""
    fps = []
    for n, (inst, h) in enumerate(list(specs) + [(e, None) for e in extra]):
        fields = {"Pm.Height": "%gmm" % h} if h is not None else None
        fps.append(footprint(inst.upper(), 50.0, 3.0 + n * 6.0, w=2.0, h=2.0, inst=inst,
                             nets=("SIG", "GND"), fields=fields))
    return Board(board_geometry(fps, width=60, height=60), edge_margin=0.5, keep_going=True)


def _cup(b, **kw):
    return b.keepout(Circle(9.0), "cup", at=Location(30.0, 30.0), excludes=("parts",),
                     layers=[CopperLayer.F], why="a part mounted off the board sits over it", **kw)


def test_bars_is_kept_on_the_declaration():
    b = _board(("m1", None))
    intent = _cup(b, bars=(Part("m1"),))
    assert intent.keepout.bars == (Part("m1"),)


def test_a_keepout_bars_nothing_by_default():
    assert _cup(_board(("m1", None))).keepout.bars == ()


def test_bars_and_allowed_parts_are_refused_together():
    b = _board(("m1", None), ("j1", None))
    with pytest.raises(ValueError, match="bars"):
        _cup(b, bars=(Part("m1"),), allow=(Part("j1"),))
    with pytest.raises(ValueError, match="bars"):
        _cup(b, bars=(Part("m1"),), allow=(Cell("rf"),))


def test_bars_and_an_allowed_net_go_together():
    b = _board(("m1", None))
    assert _cup(b, bars=(Part("m1"),), allow=(Net("GND"),)).keepout.allow == (Net("GND"),)


def test_bars_names_parts_or_cells_only():
    b = _board(("m1", None))
    with pytest.raises(TypeError, match="parts or cells"):
        _cup(b, bars=(Net("GND"),))


def _board_run(*specs, extra=()):
    b = _board(*specs, extra=extra)
    b.keep_going = False
    return b


def _in_the_cup(b, inst):
    b.place(Part(inst), at=Location(30.0, 30.0))


def test_a_barred_part_is_refused_and_named_as_barred():
    b = _board_run(("m1", None), ("j1", None))
    _cup(b, bars=(Part("m1"),))
    _in_the_cup(b, "m1")
    with pytest.raises(PlacementCollision, match=r"cup.*M1 is barred"):
        b.resolve()


def test_every_other_part_is_admitted():
    b = _board_run(("m1", None), ("j1", None))
    _cup(b, bars=(Part("m1"),))
    _in_the_cup(b, "j1")
    b.place(Part("m1"), at=Location(10.0, 10.0))
    plan = b.resolve()
    assert plan.box("j1").center == Location(30.0, 30.0)
    assert plan.keepouts["cup"].barred == frozenset({"M1"})


def test_a_part_added_to_the_board_is_admitted_without_a_script_edit():
    def script(extra):
        b = _board_run(("m1", None), extra=extra)
        _cup(b, bars=(Part("m1"),))
        b.place(Part("m1"), at=Location(10.0, 10.0))
        for inst in extra:
            _in_the_cup(b, inst)
        return b.resolve()
    assert script(())
    assert script(("x1",)).box("x1").center == Location(30.0, 30.0)


def _cell_board():
    fps = [footprint("U1", 50, 5, w=2, h=2, cell="rf", inst="rf.u1", nets=("A", "B")),
           footprint("U2", 50, 10, w=2, h=2, cell="rf", inst="rf.u2", nets=("A", "B")),
           footprint("J1", 50, 20, w=2, h=2, inst="j1", nets=("A", "B"))]
    b = Board(board_geometry(fps, cells=["rf"], width=60, height=60), edge_margin=0.5)
    _cup(b, bars=(Cell("rf"),))
    return b


def test_a_barred_cell_is_refused_where_the_keepout_is():
    b = _cell_board()
    b.place(Part("j1"), at=Location(10.0, 10.0))
    b.place(Cell("rf"), at=Location(30.0, 30.0))
    with pytest.raises(PlacementCollision, match=r"cup"):
        b.resolve()


def test_a_barred_cell_bars_each_member_and_lets_other_parts_in():
    b = _cell_board()
    b.place(Cell("rf"), at=Location(10.0, 10.0))
    b.place(Part("j1"), at=Location(30.0, 30.0))
    plan = b.resolve()
    assert plan.keepouts["cup"].barred == frozenset({"U1", "U2"})
    assert plan.box("j1").center == Location(30.0, 30.0)


def _with_height():
    b = _board_run(("m1", 1.0), ("s1", 1.0), ("t1", 4.0), ("n1", None))
    _cup(b, bars=(Part("m1"),), max_height=2.0)
    return b


@pytest.mark.parametrize("inst, refused", [("m1", True), ("s1", False), ("t1", True), ("n1", True)])
def test_bars_with_a_height_limit_bars_the_named_whatever_their_height(inst, refused):
    b = _with_height()
    _in_the_cup(b, inst)
    for n, other in enumerate(o for o in ("m1", "s1", "t1", "n1") if o != inst):
        b.place(Part(other), at=Location(10.0 + 6 * n, 10.0))
    if refused:
        with pytest.raises(PlacementCollision, match="cup"):
            b.resolve()
    else:
        assert b.resolve().box(inst).center == Location(30.0, 30.0)
