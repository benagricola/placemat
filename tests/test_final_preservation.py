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


ZONE = ('(zone (net 1) (layer "B.Cu") (uuid "original-zone") (priority 2) '
        '(polygon (pts (xy 1 1) (xy 5 1) (xy 5 5))) '
        '(fill (mode 0) (thermal_gap 0.2) (thermal_bridge_width 0.3) '
        '(hatch_thickness 0.4) (island_removal_mode 1)))')


def test_zone_direct_filled_state_preserves_actual_manifest(tmp_path):
    geometry, source = original(tmp_path)
    source.write_text('(kicad_pcb ' + ZONE + ')')
    final = tmp_path / 'final.kicad_pcb'
    final.write_text(source.read_text().replace('(fill ', '(fill yes '))
    retained = manifest(geometry, source)
    assert manifest(geometry, final) == retained
    assert verify(geometry, source, geometry, final, retained)['held_and_fixed_preserved'] is True


@pytest.mark.parametrize(('old', 'new'), [
    ('(mode 0)', '(mode 1)'),
    ('(thermal_gap 0.2)', '(thermal_gap 0.3)'),
    ('(thermal_bridge_width 0.3)', '(thermal_bridge_width 0.4)'),
    ('(hatch_thickness 0.4)', '(hatch_thickness 0.5)'),
    ('(island_removal_mode 1)', '(island_removal_mode 2)'),
    ('(net 1)', '(net 2)'),
    ('(layer "B.Cu")', '(layer "F.Cu")'),
    ('(uuid "original-zone")', '(uuid "changed-zone")'),
    ('(priority 2)', '(priority 3)'),
    ('(xy 5 5)', '(xy 5.01 5)'),
])
def test_zone_parameters_remain_exact_after_filled_state_normalization(tmp_path, old, new):
    geometry, source = original(tmp_path)
    source.write_text('(kicad_pcb ' + ZONE + ')')
    final = tmp_path / 'final.kicad_pcb'
    final.write_text(source.read_text().replace('(fill ', '(fill yes ').replace(old, new))
    assert manifest(geometry, source) != manifest(geometry, final)
    with pytest.raises(CandidateRefused):
        verify(geometry, source, geometry, final, manifest(geometry, source))


def test_filled_state_normalization_retains_unknown_and_graphic_fill_tokens(tmp_path):
    from placemat.final_preservation import forms
    source = tmp_path / 'source.kicad_pcb'
    final = tmp_path / 'final.kicad_pcb'
    source.write_text('(kicad_pcb (zone (fill (mode 0))) (gr_poly (fill none)))')
    for text in ('(kicad_pcb (zone (fill yes yes (mode 0))) (gr_poly (fill none)))',
                 '(kicad_pcb (zone (fill unknown (mode 0))) (gr_poly (fill none)))',
                 '(kicad_pcb (zone (fill yes (mode 0))) (gr_poly (fill yes)))'):
        final.write_text(text)
        assert forms(source) != forms(final)


def permutation_scene(tmp_path):
    from placemat.board_geometry import CopperItem
    fp = footprint('U1', 10, 10, nets=('A', 'B', 'A'))
    fp = replace(fp, pads=(*fp.pads, pad('U1', fp.inst, '3', 'A', 10, 12)))
    pads = tuple(fp.pads)
    source = board_geometry([fp], copper=(track('A', 2, 2, 4, 2),))
    mapped = replace(fp, pads=tuple(replace(p, net={'1': 'B', '2': 'A'}.get(p.number, p.net)) for p in pads))
    written = replace(source, footprints=(mapped,), copper=tuple(
        CopperItem('pad', p.net, p.layers, p.outlines, p.box, p.owner) for p in mapped.pads) + source.copper[-1:])
    pcb = tmp_path / 'source.kicad_pcb'
    pcb.write_text('(kicad_pcb (segment (start 2 2) (end 4 2) (net 1)))')
    pools = [{'ref': 'U1', 'mapping': [['A', '1', '2'], ['B', '2', '1']]}]
    return source, written, pcb, pools


def test_cross_permutation_preserves_fixed_copper_after_exact_pad_proofs(tmp_path):
    from placemat.final_preservation import verify_fixed_after_permutation, verify_fixed
    source, written, pcb, pools = permutation_scene(tmp_path)
    with pytest.raises(CandidateRefused):
        verify_fixed(source, pcb, written, pcb)
    assert verify_fixed_after_permutation(source, pcb, written, pcb, written, pcb, pools)


@pytest.mark.parametrize('change', ['unselected-net', 'unselected-shape', 'missing-pad', 'owner', 'track-net', 'track-removed'])
def test_cross_permutation_refuses_unproved_land_or_fixed_changes(tmp_path, change):
    from placemat.final_preservation import verify_fixed_after_permutation
    source, written, pcb, pools = permutation_scene(tmp_path)
    fp = written.footprints[0]
    if change == 'unselected-net':
        bad = replace(written, footprints=(replace(fp, pads=(*fp.pads[:2], replace(fp.pads[2], net='OTHER'))),))
    elif change == 'unselected-shape':
        bad = replace(written, footprints=(replace(fp, pads=(*fp.pads[:2], replace(fp.pads[2], outlines=()))),))
    elif change == 'missing-pad':
        bad = replace(written, footprints=(replace(fp, pads=fp.pads[:2]),))
    elif change == 'owner':
        bad = replace(written, footprints=(replace(fp, pads=(replace(fp.pads[0], owner='OTHER'), *fp.pads[1:])),))
    elif change == 'track-net':
        bad = replace(written, copper=(*written.copper[:-1], replace(written.copper[-1], net='OTHER')))
    else:
        bad = replace(written, copper=written.copper[:-1])
    with pytest.raises(CandidateRefused):
        verify_fixed_after_permutation(source, pcb, written, pcb, bad, pcb, pools)


def test_cross_permutation_refuses_ambiguous_same_net_numbered_land(tmp_path):
    from placemat.final_preservation import verify_fixed_after_permutation
    source, written, pcb, pools = permutation_scene(tmp_path)
    fp=source.footprints[0]
    duplicate=replace(fp.pads[0], number='3')
    source=replace(source, footprints=(replace(fp,pads=(*fp.pads[:2],duplicate)),))
    with pytest.raises(CandidateRefused):
        verify_fixed_after_permutation(source,pcb,written,pcb,written,pcb,pools)
