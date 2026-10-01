"""A decided place is judged at the edge by what each member is: its body and courtyard by their shapes
against the edge itself, its copper by its shapes against the keep-in, when the boxes fail. The real
fragment is a ring of arc-sector windings turned 45 degrees on a 26.5 mm radius board."""
import dataclasses
import math
import pathlib

import pytest

from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import Cell, Face, Part, Pin
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry

FRAGMENT = str(pathlib.Path(__file__).resolve().parents[1] / "fixtures/fairing/modules/ringsensor/layout/layout.kicad_pcb")


def _fragment():
    """The fragment's footprints stamped as the cell `ring` (an instance path `ring.<name>`)."""
    from placemat.kicad.read import read_board
    g = read_board(FRAGMENT)
    fps = tuple(dataclasses.replace(fp, cell="ring", inst="ring." + fp.inst) for fp in g.footprints)
    return fps


def _board(fps, how="outline", margin=0.4):
    b = Board(board_geometry(list(fps), cells=["ring"], width=60, height=60), edge_margin=margin, keep_going=True)
    if how == "disc":
        b.disc(53.0)
    else:
        b.outline(Circle(53.0))
    return b


def _edge_findings(plan):
    return [f for f in plan.findings if "keep-in" in str(f) or "board edge" in str(f) or "outside" in str(f)
            or "edge" in str(f)]


def _stamp(b, centre=26.5, shift=(0.0, 0.0)):
    b.place(Cell("ring"), face=Face.FRONT, rotation=45,
            at=Pin(Part("ring.l_ring0"), centre + shift[0], centre + shift[1]))
    return b.resolve()


def _shifts(distance):
    return [(distance * math.cos(math.radians(a)), distance * math.sin(math.radians(a))) for a in range(0, 360, 15)]


@needs_kicad
@pytest.mark.parametrize("how", ["outline", "disc"])
def test_the_fragment_of_arc_windings_is_placed_on_the_disc(how):
    """The windings' origin is the disc's centre: copper reaches the keep-in (26.1 of 26.5), the body 26.1 and
    the courtyard 26.2, while the boxes' far corners are past the edge."""
    plan = _stamp(_board(_fragment(), how))
    assert not _edge_findings(plan), plan.findings


@needs_kicad
@pytest.mark.parametrize("how", ["outline", "disc"])
def test_a_body_polygon_that_crosses_the_edge_is_refused(how):
    """No keep-in: only the courtyard and body, which reach 26.2, meet the edge. Moved off the centre they
    cross it, and the sentence names the edge."""
    refused = []
    for shift in _shifts(0.45):
        plan = _stamp(_board(_fragment(), how, margin=0.01), shift=shift)
        refused.append(_edge_findings(plan))
    assert any(refused)
    for found in filter(None, refused):
        assert "keep-in" not in found[0], found


@needs_kicad
def test_copper_past_the_keep_in_is_refused():
    """A keep-in of 0.5 holds the copper (26.1) inside r 26.0."""
    plan = _stamp(_board(_fragment(), margin=0.5))
    assert _edge_findings(plan), plan.findings


@needs_kicad
def test_an_edge_refusal_names_the_edge_not_a_keep_in_of_nothing():
    for shift in _shifts(1.0):
        for found in _edge_findings(_stamp(_board(_fragment(), margin=0.01), shift=shift)):
            assert "(0.00" not in found, found
