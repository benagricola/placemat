"""The run's extent line measures what each part claims under the envelope
in force: under `physical` a part claims no courtyard, and the line was
missing. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.layout import Board
from placemat.report import extent_of
from placemat.settings import Settings
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


@pytest.mark.parametrize("envelope", ["courtyard", "physical", "union"])
def test_the_extent_is_measured_under_every_envelope(envelope):
    fps = [footprint("U1", 10, 10, w=4, h=2, inst="u1", fab=(8, 9, 12, 11)),
           footprint("C1", 20, 10, w=2, h=1, inst="c1", fab=(19, 9.5, 21, 10.5))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), place_envelope=envelope))
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), at=Location(20, 10))
    ext = extent_of(b.resolve())
    assert ext is not None and ext.width == pytest.approx(13.0, abs=0.3) and 0.0 < ext.empty < 1.0
