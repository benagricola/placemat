"""`measure --pads` prints a custom pad's copper outline, not only its box:
the box of an exposed pad with lead fingers hides the fingers."""
import dataclasses

from placemat.describe import pad_facts, part_lines
from tests.fixtures import footprint

FINGERED = ((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (2.4, 1.0), (2.4, 1.3), (2.0, 1.3), (2.0, 2.0), (0.0, 2.0))


def _part():
    fp = footprint("Q1", 10, 10, w=4, h=3, nets=("D", "S"))
    drain = dataclasses.replace(fp.pads[0], outlines=(FINGERED,), custom=True)
    return dataclasses.replace(fp, pads=(drain, fp.pads[1]))


def test_a_custom_pads_outline_is_printed_under_it():
    lines = part_lines(_part(), pads=True)
    i = next(k for k, l in enumerate(lines) if l.lstrip().startswith("pad 1"))
    assert lines[i + 1].strip().startswith("outline")
    assert "(2.400, 1.000)" in lines[i + 1] and "(2.000, 1.300)" in lines[i + 1]


def test_a_plain_pad_has_no_outline_line():
    lines = part_lines(_part(), pads=True)
    i = next(k for k, l in enumerate(lines) if l.lstrip().startswith("pad 2"))
    assert i == len(lines) - 1 or not lines[i + 1].strip().startswith("outline")


def test_the_json_says_which_pads_are_custom():
    fp = _part()
    assert pad_facts(fp, fp.pads[0])["custom"] is True and pad_facts(fp, fp.pads[1])["custom"] is False
