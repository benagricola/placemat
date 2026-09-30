"""measure's model check: a footprint's 3D model box, read from its STEP
file and placed as KiCad places it (scale, the model's turn, its offset,
in the model's own y-up frame), against the part's pads and fab outline -
a model off its pads, or one that matches its outline only when turned 90,
is said."""
import dataclasses

import pytest

from placemat.describe import model_check, step_box
from placemat.values import Box, Face, Location
from tests.fixtures import footprint


def _step(tmp_path, x0, y0, x1, y1, name="m.step"):
    pts = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 1), (x0, y1, 1)]
    body = "\n".join("#%d=CARTESIAN_POINT('',(%g,%g,%g));" % (k + 10, *p) for k, p in enumerate(pts))
    path = tmp_path / name
    path.write_text("ISO-10303-21;\nDATA;\n#1=( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );\n"
                    + body + "\nENDSEC;\nEND-ISO-10303-21;\n")
    return path


def _part(path, rot=(0.0, 0.0, 0.0), off=(0.0, 0.0, 0.0), fab=(8.0, 9.0, 12.0, 11.0)):
    # a 4 x 2 part at (10, 10): its pads at x 8.6 and 11.4, its fab outline 4 x 2
    fp = footprint("U1", 10, 10, w=4, h=2, inst="u1", fab=fab)
    return dataclasses.replace(fp, models=((str(path), off, rot, (1.0, 1.0, 1.0)),))


def test_a_step_files_box_is_read_from_its_points(tmp_path):
    assert step_box(_step(tmp_path, -2, -1, 2, 1)) == pytest.approx((-2, -1, 2, 1))


def test_a_model_over_its_pads_and_outline_says_nothing(tmp_path):
    assert model_check(_part(_step(tmp_path, -2, -1, 2, 1)), tmp_path) == []


def test_a_model_turned_off_its_outline_is_said(tmp_path):
    notes = model_check(_part(_step(tmp_path, -2, -1, 2, 1), rot=(0.0, 0.0, 90.0)), tmp_path)
    assert any("turned 90" in n for n in notes), notes


def test_a_model_turned_back_onto_its_outline_says_nothing(tmp_path):
    """A model drawn along y, turned 90 by its transform, lies along x as the
    part does."""
    assert model_check(_part(_step(tmp_path, -1, -2, 1, 2), rot=(0.0, 0.0, 90.0)), tmp_path) == []


def test_a_model_offset_off_its_pads_is_said(tmp_path):
    notes = model_check(_part(_step(tmp_path, -2, -1, 2, 1), off=(6.0, 0.0, 0.0)), tmp_path)
    assert any("off its pads" in n for n in notes), notes


def test_a_model_file_that_is_not_there_is_said(tmp_path):
    notes = model_check(_part(tmp_path / "missing.step"), tmp_path)
    assert any("not found" in n for n in notes), notes
