"""The search prices each candidate by the declared escape lanes it blocks. An escape the candidate comes nowhere near
keeps its count on the board the candidate was lifted from, without being laid out again; one it comes near is laid out
again, and both give the count a full layout gives."""
from placemat.score_delta import Delta
from placemat.placement import Placement
from placemat.values import Location, Part
from tests.escape_fixtures import PD_NETS, board_with, qfn, small_part


def _lifted():
    b = board_with([qfn(nets=PD_NETS), small_part("R1", "r1", ("VOUT", "SENSE"), cx=50.0, cy=50.0)], keep_going=True)
    b.place(Part("pd"), at=Location(30, 30))
    b.place(Part("r1"), at=Location(50, 50))
    b.escape(Part("pd"), [32, 31, 30], why="the north row")
    plan = b.resolve()
    occ = plan.occupancy
    item = b.geometry.footprint("R1")
    occ.lift({"R1"})
    return b, occ, item, plan


def _count(b, occ, item, plan, at, monkeypatch):
    delta = Delta(b, occ, item, plan.links, plan=plan)
    laid = []
    real = b._escape_layout
    monkeypatch.setattr(b, "_escape_layout", lambda *a, **k: laid.append(1) or real(*a, **k))
    view, geometries, copper = delta._view(Placement(at, 0.0, occ._geometry(item).reference.face))
    got = delta._lanes_blocked(view, geometries, copper)
    monkeypatch.setattr(b, "_escape_layout", real)
    return got, b._declared_lanes_blocked(view, plan), len(laid)


def test_a_candidate_far_from_an_escape_keeps_its_count_without_laying_it_out(monkeypatch):
    b, occ, item, plan = _lifted()
    got, full, laid = _count(b, occ, item, plan, Location(50, 50), monkeypatch)
    assert (got, laid) == (full, 0)


def test_a_candidate_on_an_escapes_lanes_lays_it_out_again(monkeypatch):
    b, occ, item, plan = _lifted()
    got, full, laid = _count(b, occ, item, plan, Location(29.5, 26.8), monkeypatch)
    assert laid == 1 and got == full and full > 0
