"""Genuine retained original producer; native reads/critical encoding controlled.

This protects copied transport bytes, not completed report/selection authority.
"""
from pathlib import Path
import pytest
from tests.test_manufacturing_retained_producer import bound
from placemat.kicad.manufacturing_inventory import retained_original
from placemat.kicad.manufacturing_current_request import copy_current_family
from placemat.kicad.final_call import ProofUnavailable,file_hash
from placemat.kicad import manufacturing_current_request as current_request
def copied(bound,tmp_path):
    original=retained_original(bound)['original']['files']
    raw=tmp_path/'raw.kicad_pcb';raw.write_bytes(bound._source.read_bytes())
    folder=tmp_path/'copy';folder.mkdir()
    return raw,folder/'board.kicad_pcb',file_hash(raw),original


def test_current_copy_uses_exact_raw_and_retained_original_companions(bound,tmp_path):
    raw,target,expected,original=copied(bound,tmp_path)
    copy_current_family(raw,target,expected,original)
    assert file_hash(target)==expected
    assert file_hash(target.with_suffix('.kicad_pro'))==original['.kicad_pro']['sha256']
    assert not target.with_suffix('.kicad_dru').exists()


@pytest.mark.parametrize('which',['pcb','project'])
def test_corrupted_copy_refuses_with_genuine_original_bound(bound,tmp_path,monkeypatch,which):
    raw,target,expected,original=copied(bound,tmp_path)
    copy=current_request.shutil.copyfile
    def corrupt(source,destination):
        result=copy(source,destination)
        if Path(destination).suffix==('.kicad_pcb' if which=='pcb' else '.kicad_pro'):
            Path(destination).write_text('different bytes')
        return result
    monkeypatch.setattr(current_request.shutil,'copyfile',corrupt)
    with pytest.raises(ProofUnavailable,match='current_measurement_copied_'):
        copy_current_family(raw,target,expected,original)
    assert file_hash(bound._source)==original['.kicad_pcb']['sha256']


def test_genuine_original_absence_not_replaced_by_dangling_link(bound,tmp_path):
    raw,target,expected,original=copied(bound,tmp_path)
    target.with_suffix('.kicad_dru').symlink_to(tmp_path/'missing')
    with pytest.raises(ProofUnavailable,match='current_measurement_copied_absence_changed'):
        copy_current_family(raw,target,expected,original)
