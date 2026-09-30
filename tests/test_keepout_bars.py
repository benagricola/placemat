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
