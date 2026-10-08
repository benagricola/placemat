"""Mechanical shared parser extraction; no native reads or normalization changes."""
import pytest
from placemat.kicad import board_forms as original

draft = original


def refuse(reason):
    raise ValueError(reason)


@pytest.mark.parametrize('text', ['(kicad_pcb (zone (net 1))', '(kicad_pcb) extra',
                                  '(wrong_root)', '(kicad_pcb))'])
def test_malformed_forms_share_original_refusal(tmp_path, text):
    path = tmp_path / 'input.kicad_pcb'
    path.write_text(text)
    with pytest.raises(ValueError):
        draft.read_forms(path, refuse)
    with pytest.raises(ValueError):
        original.protected_forms(path, refuse)


def test_read_retains_net_records_unknown_fields_zone_and_fixed_multiplicity(tmp_path):
    path = tmp_path / 'input.kicad_pcb'
    fixed = '(segment (start 1 2) (end 3 4) (width .2) (layer "F.Cu") (net 1))'
    path.write_text('(kicad_pcb (net 1 "N") (future_field (ordered 2 1)) '+fixed+fixed+
                    ' (zone (net 1) (fill yes (thermal_gap .2)) (priority 3)'+
                    ' (polygon (pts (xy 0 0) (xy 1 0) (xy 0 1)))'+
                    ' (filled_polygon (layer "F.Cu") (pts (xy 0 0)))) )')
    root = draft.read_forms(path, refuse)
    assert ['net', '1', '"N"'] in root
    assert ['future_field', ['ordered', '2', '1']] in root
    fixed, zones = draft.protected_forms(path, refuse)
    assert len(fixed) == 2
    assert zones == (('zone', ('net', '1'), ('fill', ('thermal_gap', '.2')),
                     ('priority', '3'),
                     ('polygon', ('pts', ('xy', '0', '0'), ('xy', '1', '0'), ('xy', '0', '1')))),)
