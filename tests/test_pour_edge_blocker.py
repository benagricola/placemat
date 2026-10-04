"""A fitted pour that the board edge keeps from its pads names the edge: its blocker is a record like any other copper's."""
from placemat import finding_text, pourfit
from placemat.findings import FindingCause as C


def test_the_board_edge_is_a_blocker_record():
    from placemat.values import Box
    pieces = pourfit.edge_pieces([[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]], 0.5, 0.01, Box(0, 0, 10, 10))
    assert pieces and all(p.what == {"form": "edge"} for p in pieces)


def test_a_pour_kept_from_its_pads_by_the_edge_renders():
    facts = {"variant": "pour_no_way", "net": "VBIKE", "noun": "pad", "what": {"form": "edge"},
             "between": [["pad", "J1", "1"], ["pad", "D1", "2"]]}
    text = finding_text.render(C.COPPER_NOT_DRAWN, facts)
    assert text == "pour VBIKE: the board edge leaves no way between pads J1.1 and D1.2; the pour is not drawn"
