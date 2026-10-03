"""board.rect is the rectangular board form; board.size, its old name, is gone."""
import pytest

from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("R1", 20, 20, inst="r1"), footprint("R2", 25, 20, inst="r2")]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def test_rect_resolves_with_no_notice_about_its_name():
    b = _board()
    b.rect(width=50, height=40, chamfer=2.0)
    b.place(Part("r1"), at=Location(10, 10))
    plan = b.resolve()
    assert not [f for f in plan.findings if "board.size" in f]


def test_size_is_refused_naming_rect_and_the_migration():
    with pytest.raises(AttributeError, match=r"board\.size\(\.\.\.\) is board\.rect\(\.\.\.\) since 0\.85\.0.*migration"):
        _board().size(width=50, height=40)
