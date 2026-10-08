from collections import Counter

import pytest

from placemat.kicad import board_forms as module


class Refused(ValueError):
    pass


def refuse(reason):
    raise Refused(reason)


def forms(tmp_path, text, name='board.kicad_pcb'):
    path = tmp_path / name
    path.write_text(text)
    return module.protected_forms(path, refuse)


@pytest.mark.parametrize('text', ['(kicad_pcb (zone (net 1))', '(kicad_pcb (zone)) extra',
                                  '(wrong_root (zone (net 1)))', '(kicad_pcb (zone (net 1))))'])
def test_malformed_zone_board_boundary_uses_supplied_refusal(tmp_path, text):
    with pytest.raises(Refused):
        forms(tmp_path, text)


def test_original_fixed_multiplicity_remains_protected(tmp_path):
    segment = '(segment (start 1 2) (end 3 4) (width .2) (layer "F.Cu") (net 1))'
    original, _ = forms(tmp_path, '(kicad_pcb '+segment+segment+')')
    final, _ = forms(tmp_path, '(kicad_pcb '+segment+')', 'final.kicad_pcb')
    assert len(original) == 2
    assert sum((Counter(original)-Counter(final)).values()) == 1


def test_refill_records_allowed_but_zone_priority_and_vertex_order_retained(tmp_path):
    zone = '(zone (net 1) (priority 2) (fill (thermal_gap .2)) (polygon (pts (xy 1 2) (xy 3 4))))'
    _, before = forms(tmp_path, '(kicad_pcb '+zone+')')
    refill = zone.replace('(fill ', '(fill yes ').replace(' (polygon', ' (filled_polygon (layer "F.Cu") (pts (xy 1 2))) (polygon')
    _, after = forms(tmp_path, '(kicad_pcb '+refill+')', 'refill.kicad_pcb')
    assert before == after
    for changed in (zone.replace('(priority 2)', '(priority 3)'),
                    zone.replace('(xy 1 2) (xy 3 4)', '(xy 3 4) (xy 1 2)'),
                    zone.replace('(thermal_gap .2)', '(thermal_gap .3)')):
        assert forms(tmp_path, '(kicad_pcb '+changed+')', 'changed.kicad_pcb')[1] != before
