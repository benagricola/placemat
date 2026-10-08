"""Held physical identity remains exact across the owned worker boundary."""
import copy
from dataclasses import replace

import pytest

from placemat.final_preservation import CandidateRefused, manifest, verify
from tests.fixtures import board_geometry, footprint, pad, track


def original(tmp_path):
    fp = footprint('U1', 10, 10, nets=('A', 'B'))
    geometry = board_geometry([fp], copper=(track('A', 2, 2, 4, 2),))
    source = tmp_path / 'original.kicad_pcb'
    source.write_text('(kicad_pcb (segment (start 2 2) (end 4 2) (net 1)) '
                      '(gr_poly (pts (xy 2 2) (xy 3 2) (xy 3 3)) (layer "F.Cu")) '
                      '(zone (net 1) (priority 2) (polygon (pts (xy 1 1) (xy 5 1) (xy 5 5))) '
                      '(filled_polygon (layer "F.Cu") (pts (xy 2 2) (xy 3 2) (xy 3 3)))))')
    return geometry, source


def test_fill_only_change_preserves_zone_intent(tmp_path):
    geometry, source = original(tmp_path)
    final = tmp_path / 'final.kicad_pcb'
    final.write_text(source.read_text().replace('(xy 2 2) (xy 3 2) (xy 3 3)))))',
                                               '(xy 2 2) (xy 4 2) (xy 4 4)))))'))
    assert verify(geometry, source, geometry, final, manifest(geometry, source))['held_and_fixed_preserved'] is True


@pytest.mark.parametrize('change', ['priority', 'graphic-layer', 'graphic-vertex', 'track-net'])
def test_exact_static_and_zone_intent_mutations_refuse(tmp_path, change):
    geometry, source = original(tmp_path)
    changes = {'priority': ('(priority 2)', '(priority 3)'),
               'graphic-layer': ('(layer "F.Cu")) ', '(layer "B.Cu")) '),
               'graphic-vertex': ('(xy 3 3)) (layer', '(xy 3.01 3)) (layer'),
               'track-net': ('(end 4 2) (net 1)', '(end 4 2) (net 2)')}
    final = tmp_path / 'final.kicad_pcb'
    final.write_text(source.read_text().replace(*changes[change]))
    with pytest.raises(CandidateRefused):
        verify(geometry, source, geometry, final, manifest(geometry, source))


def test_manifest_boolean_does_not_accept_integer_substitution(tmp_path):
    geometry, source = original(tmp_path)
    expected = copy.deepcopy(manifest(geometry, source))
    expected['footprints'][0]['fields']['dnp'] = 0
    with pytest.raises(CandidateRefused):
        verify(geometry, source, geometry, source, expected)
