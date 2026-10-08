"""Controlled typed native reply transport, not native geometry qualification."""
import pytest
from placemat.kicad.manufacturing_annular import Unproved
from placemat.kicad.manufacturing_receipt import validate

from tests.test_manufacturing_current_prepare import current, controlled_measurement_reply
from placemat.kicad import manufacturing_current_request as requests


@pytest.fixture
def pair(current, monkeypatch):
    """Current private custody with a controlled complete native reply."""
    from pathlib import Path
    from placemat.kicad import manufacturing_current_measurement as measurement
    from placemat.kicad.final_call import file_hash
    runtime = dict(requests._implementation())
    worker = Path(measurement.__file__).resolve().with_name('manufacturing_worker.py')
    runtime[str(worker)] = file_hash(worker)
    monkeypatch.setattr(requests, '_implementation', lambda: dict(runtime))
    result = []
    def candidate(deadline):
        work = current.tmp / 'codec'
        work.mkdir()
        packet = requests.prepare(current.budget, current.owner, current.token,
            current.raw, current.candidate, current.candidate_files, work=work)
        result.append((packet, controlled_measurement_reply(packet, work)))
        return {'returncode': 0, 'proposals': 1, 'files': current.candidate_files}
    current.budget.run_replay(current.owner.executor, candidate)
    return result[0]

def test_complete_typed_pair(pair):
    checks=[];result=validate(*pair,lambda:checks.append(True))
    assert checks == [True] * 8  # Two outer receipt checks plus six clearance checks.
    assert result['sides']['legacy']['annular']['count']==0
    assert result['sides']['pocket']['original_rules_drc_validated'] is True
    assert result['comparison_authority'] is False

@pytest.mark.parametrize('change',[
    lambda r:r['mandatory_clearance']['rows'].pop('candidate'),
    lambda r:r['mandatory_clearance']['rows'].__setitem__('candidate',None),
    lambda r:r['mandatory_clearance']['rows']['candidate']['original_report'].__setitem__('returncode',False),
    lambda r:r['receipt']['candidate'].__setitem__('via_count',False),
    lambda r:r.__setitem__('mode','saved_pair_diagnostic_only'),
    lambda r:r.__setitem__('request_sha256','other')])
def test_missing_or_malformed_side_cannot_remove_reason(pair,change):
    packet,reply=pair;change(reply)
    with pytest.raises(Unproved):validate(packet,reply,lambda:None)

def test_postcheck_unexpected_defect_propagates(pair):
    checks=[]
    def check():
        checks.append(True)
        if len(checks)==2:raise RuntimeError('actual owner defect')
    with pytest.raises(RuntimeError,match='actual owner defect'):validate(*pair,check)


@pytest.mark.parametrize('side',['original','candidate'])
def test_dangling_absent_companion_refuses_codec_and_current_validation(pair,side):
    from pathlib import Path
    from placemat.kicad.manufacturing_annular import unchanged
    packet,reply=pair
    absent=Path(packet['request'][side]['files']['.kicad_pcb']['path']).with_suffix('.kicad_dru')
    absent.symlink_to(absent.parent/'missing-rules-target')
    assert not absent.exists() and absent.is_symlink()
    with pytest.raises(Unproved,match='source_absence_changed'):
        unchanged(packet['request'])
    with pytest.raises(Unproved):
        validate(packet,reply,lambda:None)
