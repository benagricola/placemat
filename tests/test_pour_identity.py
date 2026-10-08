"""Pour custody supports exact identity normalization, never arbitrary conversion."""
from pathlib import Path

import pytest

from placemat.kicad import pour_identity
from placemat.kicad.final_call import ProofUnavailable

BOARD = '(kicad_pcb (segment (start 1 2) (end 3 4) (width .2) (layer "F.Cu") (net 1)) (zone (net 1) (priority 2) (fill (thermal_gap .2)) (polygon (pts (xy 1 2) (xy 3 4)))))'


@pytest.fixture
def boards(tmp_path):
    source, normalized, output = (tmp_path/name for name in ('source.kicad_pcb', 'normalized.kicad_pcb', 'out.kicad_pcb'))
    for path in (source, normalized, output):
        path.write_text(BOARD)
        path.with_suffix('.kicad_pro').write_text('original rules')
    return source, normalized, output


def test_identical_normalization_and_restored_intent_proved(boards):
    source, given, output = boards
    proof = pour_identity.normalized(source, given)
    output.write_text(BOARD.replace('(fill ', '(fill yes '))
    assert pour_identity.restored(source, output, proof)['domain'] == 'single_net_pour_identity_normalization'


@pytest.mark.parametrize('change', ['bytes', 'marker', 'rules'])
def test_unproved_transform_refused(boards, change):
    source, given, output = boards
    if change == 'bytes':
        given.write_text(BOARD+'\n')
    elif change == 'marker':
        source.write_text(BOARD.replace('(priority 2)', '(name "placemat pour N")'))
        given.write_bytes(source.read_bytes())
    else:
        given.with_suffix('.kicad_pro').write_text('weakened rules')
    with pytest.raises(ProofUnavailable):
        pour_identity.normalized(source, given)


@pytest.mark.parametrize('change', ['zone', 'fixed', 'rules'])
def test_original_intent_and_copper_cannot_be_removed(boards, change):
    source, given, output = boards
    proof = pour_identity.normalized(source, given)
    if change == 'zone':
        output.write_text(BOARD.replace('(priority 2)', '(priority 3)'))
    elif change == 'fixed':
        output.write_text('(kicad_pcb (zone (net 1) (priority 2)))')
    else:
        output.with_suffix('.kicad_pro').write_text('weakened rules')
    with pytest.raises(ProofUnavailable):
        pour_identity.restored(source, output, proof)
