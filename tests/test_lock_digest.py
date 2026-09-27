"""A lock accepted by an earlier release still holds: an item's declaration
digest does not change when placemat adds a field its script never set.
The digests below were computed by 0.39.0 for this board."""
from placemat import lock
from placemat.layout import Board
from placemat.values import Location, Near, PadRef, Part
from tests.fixtures import board_geometry, footprint

ACCEPTED_BY_0_39 = {"u1": "e8b850207407e89f", "c1": "75b7cb93e11350f7", "r1": "a89220d03ec744f9"}


def test_a_declaration_digest_is_the_one_0_39_wrote():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("C1", 26, 26, w=2, h=1, inst="c1", nets=("A", "GND")),
           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("B", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("c1"), at=Near(PadRef(Part("u1"), 1).offset(0.5, -2.0), radius=1.0))
    b.place(Part("r1"), rotation=90)
    # a lock written then still holds: the digest by refdes is still accepted
    assert {i.key: lock.declaration_digest(b, i, legacy=True) for i in b._placements()} == ACCEPTED_BY_0_39
