"""board.rect is the rectangular board form; board.size is its old name."""
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint

NOTICE = "board.size(...) is board.rect(...) now; the old name will be removed"


def _resolved(form):
    fps = [footprint("R1", 20, 20, inst="r1"), footprint("R2", 25, 20, inst="r2")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    getattr(b, form)(width=50, height=40, chamfer=2.0)
    b.place(Part("r1"), at=Location(10, 10))
    b.place(Part("r2"), at=Location(30, 20), rotation=90)
    return b, b.resolve()


def _setup_notices(plan):
    return [f for f in plan.findings if f.kind == "setup" and "board.size" in f]


def test_rect_raises_no_notice():
    _, plan = _resolved("rect")
    assert _setup_notices(plan) == []


def test_size_still_works_and_raises_one_notice():
    _, plan = _resolved("size")
    found = _setup_notices(plan)
    assert [(f.kind, str(f), f.severity) for f in found] == [("setup", NOTICE, "notice")]


def test_size_gives_the_same_plan_as_rect():
    rb, rect = _resolved("rect")
    sb, size = _resolved("size")
    assert (sb.width, sb.height) == (rb.width, rb.height) == (50.0, 40.0)
    assert [(s.item, s.placement) for s in size.steps] == [(s.item, s.placement) for s in rect.steps]
    assert [str(f) for f in size.findings if f.kind != "setup" or "board.size" not in f] \
        == [str(f) for f in rect.findings]


def test_size_noticed_once_however_often_it_is_called():
    fps = [footprint("R1", 20, 20, inst="r1")]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.size(width=50, height=40)
    b.size(width=50, height=40)
    b.place(Part("r1"), at=Location(10, 10))
    assert len(_setup_notices(b.resolve())) == 1
