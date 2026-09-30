"""Under the physical envelope a part claims what it draws. A part that
draws neither silk nor fab claims its courtyard instead, and that claim is
its body: it keeps other parts' drawn shapes out, not only other
courtyards, or a keep-clear drawn only as a courtyard would block nothing."""
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _board():
    keep = footprint("K1", 20, 20, w=12, h=12, inst="k1", nets=("A", "B"))                 # draws no silk, no fab
    p = footprint("P1", 20, 20, w=2, h=1, inst="p1", nets=("C", "D"), fab=(19, 19.5, 21, 20.5))
    b = Board(board_geometry([keep, p], width=50, height=50), edge_margin=0.5, keep_going=True,
              settings=Settings(place_envelope="physical"))
    b.place(Part("k1"), at=Location(20, 20))
    b.place(Part("p1"), at=Location(20, 20))
    return b


def test_a_part_inside_an_undrawn_parts_courtyard_is_refused_under_physical():
    plan = _board().resolve()
    assert [f for f in plan.findings if "P1" in f and "K1" in f], list(plan.findings)


def test_a_searched_part_lands_outside_an_undrawn_parts_courtyard_under_physical():
    """The native sweep judges the same rule: the searched part stands clear
    of the courtyard, not merely clear of its pads."""
    from placemat.values import Near
    keep = footprint("K1", 20, 20, w=12, h=12, inst="k1", nets=("A", "B"))
    p = footprint("P1", 40, 40, w=2, h=1, inst="p1", nets=("C", "D"), fab=(39, 39.5, 41, 40.5))
    b = Board(board_geometry([keep, p], width=50, height=50), edge_margin=0.5, keep_going=True,
              settings=Settings(place_envelope="physical"))
    b.place(Part("k1"), at=Location(20, 20))
    b.place(Part("p1"), at=Near(Location(20, 20), radius=12, rotations=(0,)))
    plan = b.resolve()
    body = plan.occupancy.items["P1"].body
    court = plan.occupancy.items["K1"].shapes[0].box
    assert not body.overlaps(court), (body, court)
