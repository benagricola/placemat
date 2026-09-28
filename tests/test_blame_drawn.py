"""An unplaced item's finding names what stood in its way under a drawn
envelope too: the refusals were counted under the sentence's first word
("cell x709") and the blockers by kind, so no owner was named."""
import dataclasses

from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Cell, Location, Near, Part
from tests.fixtures import board_geometry, footprint


def test_a_cell_with_no_legal_location_under_a_physical_envelope_names_the_body_in_the_way():
    fps = [footprint("C1", 10, 10, w=6, h=4, cell="m", inst="m.c1", nets=("A", "B"), fab=(7, 8, 13, 12)),
           footprint("W1", 30, 30, w=20, h=20, inst="w1", nets=("X", "Y"), fab=(20, 20, 40, 40))]
    b = Board(board_geometry(fps, cells=["m"], width=50, height=50), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), place_envelope="physical"))
    b.place(Part("w1"), at=Location(25, 25))
    b.place(Cell("m"), at=Near(Location(25, 25), radius=3))
    (finding,) = [f for f in b.resolve().findings if "no legal location" in f]
    assert "W1 front face" in finding and "cell x" not in finding


def test_a_rim_or_cutout_refusal_is_the_edges_not_a_drawn_one():
    """On a round board, or past a cutout, the edge's sentence starts "body
    box ... is past the rim's keep-in", so it counts under "body": it is the
    edge's refusal, not silk or a body in the way."""
    from collections import Counter
    from types import SimpleNamespace
    from placemat.layout import _blame_text
    r = SimpleNamespace(rejected=Counter({"body": 120, "C1": 5}),
                        blockers=Counter({("edge", "", ""): 120, ("body", "W1", "front"): 5}))
    text = _blame_text(r)
    assert text.startswith("edge x120") and text.count("W1") == 1, text
