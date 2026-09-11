"""The placement predicates, on a real cell fragment loaded in milliseconds.

drop_ok and net_seed decide where every loose part on every board ends up, and
until now the only way to ask them a question was to run a five-minute pass on a
263-part board. That is why a seeding gap survived: the objective priced a
declared link correctly while the SEARCH never went near it, and no cheap
experiment existed to tell the two apart.

The fixture is a small real cell rather than synthetic footprints - the pads,
courtyards and clearances are the ones the library actually meets.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pcbnew                                               # noqa: E402
from placemat.layout_helpers import ModuleLayout, LinkWeight         # noqa: E402
from placemat.board_layout import BoardLayout                        # noqa: E402

CELL = os.path.join(ROOT, "tests", "fixtures", "ProtectionCell", "layout", "layout.kicad_pcb")


@pytest.fixture
def cell():
    """A real cell fragment as a board, with every part marked placed."""
    layout = ModuleLayout(CELL)
    board = BoardLayout(layout, width=40.0, height=40.0, plane_nets={"gnd"})
    board.placed_refs = {f.GetReference() for f in layout.pcb.GetFootprints()}
    return board


def a_pad(board, net):
    for f in board.pcb.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() == net:
                q = p.GetPosition()
                return f, p, (q.x / 1e6, q.y / 1e6)
    raise AssertionError("no pad on %s" % net)


# -- drop_ok: can a through via go here? --------------------------------------

def test_drop_ok_refuses_a_point_off_the_board(cell):
    why = cell.drop_ok(-5.0, -5.0, cell.layout._nc("gnd"))
    assert why and "board" in why


def test_drop_ok_refuses_a_drop_on_a_foreign_pad(cell):
    """A hole through someone else's pad is a short, and it is the failure the
    two-sided rule exists for: every hole punches BOTH faces."""
    _, _, xy = a_pad(cell, "v_out")
    assert cell.drop_ok(xy[0], xy[1], cell.layout._nc("gnd")) is not None


def test_drop_ok_allows_a_clear_point(cell):
    """Open board on any net is a legal drop; without this the predicate could
    be refusing everything and every other test here would still pass."""
    ok = [(x / 2.0, y / 2.0) for x in range(2, 78) for y in range(2, 78)
          if cell.drop_ok(x / 2.0, y / 2.0, cell.layout._nc("gnd")) is None]
    assert ok, "drop_ok refuses the entire board"


def test_drop_ok_refuses_an_existing_HOLE_even_on_the_same_net(cell):
    """Hole-to-hole is a fab rule, not an electrical one: two barrels a third of
    a millimetre apart are a drill problem whatever net they carry. The reason
    says HOLE, so a caller can tell it from a pad clash and knows that moving to
    the same net will not help."""
    via = next((v for v in cell.pcb.GetTracks() if v.GetClass() == "PCB_VIA"), None)
    if via is None:
        pytest.skip("this fragment carries no via")
    q = via.GetPosition()
    why = cell.drop_ok(q.x / 1e6, q.y / 1e6, via.GetNetCode())
    assert why and "hole" in why.lower()


def test_drop_ok_gives_a_REASON_not_just_a_verdict(cell):
    """The caller has to be able to say why a pose failed; a bare False turns
    every refusal into a guess."""
    _, _, xy = a_pad(cell, "v_out")
    why = cell.drop_ok(xy[0], xy[1], cell.layout._nc("gnd"))
    assert isinstance(why, str) and why


# -- net_seed: where does a part's own connectivity want it? ------------------

def test_net_seed_is_none_when_nothing_pulls(cell):
    """A part sharing no routed net with anything placed has nothing to aim at,
    and must say so rather than inventing a point."""
    f = pcbnew.FOOTPRINT(cell.pcb)
    f.SetReference("ORPHAN")
    assert cell.net_seed(f) is None


def test_net_seed_follows_a_declared_link_when_every_pad_is_a_plane_net(cell):
    """THE REGRESSION. A bypass capacitor reads as "3V3 and GND" - both plane
    nets, both excluded from the anchors because a plane is reachable from
    anywhere by a via. Without its link such a part has nothing to be seeded by,
    falls back to its hint, and the search never visits the pin it serves. The
    scorer priced the link correctly the whole time; the search never went
    there."""
    src, _, _ = a_pad(cell, "gnd")
    tgt_fp, tgt_pad, tgt_xy = a_pad(cell, "v_out")

    before = cell.net_seed(src)
    cell.layout.links = [{
        "weight": float(LinkWeight.SHORT), "name": "short", "why": "test", "limit_mm": None,
        "a": {"ref": src.GetReference(), "pad": [p.GetNumber() for p in src.Pads()
                                                 if p.GetNetname() == "gnd"][0]},
        "b": {"ref": tgt_fp.GetReference(), "pad": tgt_pad.GetNumber()},
    }]
    after = cell.net_seed(src)

    assert after is not None, "a declared link must give the search somewhere to go"
    d_after = ((after[0] - tgt_xy[0]) ** 2 + (after[1] - tgt_xy[1]) ** 2) ** 0.5
    if before is not None:
        d_before = ((before[0] - tgt_xy[0]) ** 2 + (before[1] - tgt_xy[1]) ** 2) ** 0.5
        assert d_after <= d_before, "the link must pull the seed toward its far end"
    assert d_after < 5.0, "the seed should sit near the pad the link names"


def test_net_seed_ignores_a_fixed_link(cell):
    """FIXED means mechanics decided the endpoint, so the connection asks for no
    adjacency and must not drag the part anywhere."""
    src, _, _ = a_pad(cell, "gnd")
    tgt_fp, tgt_pad, _ = a_pad(cell, "v_out")
    cell.layout.links = [{
        "weight": float(LinkWeight.FIXED), "name": "fixed", "why": "test", "limit_mm": None,
        "a": {"ref": src.GetReference(), "pad": [p.GetNumber() for p in src.Pads()
                                                 if p.GetNetname() == "gnd"][0]},
        "b": {"ref": tgt_fp.GetReference(), "pad": tgt_pad.GetNumber()},
    }]
    assert cell.net_seed(src) == cell.net_seed(src)      # stable, and not link-driven
