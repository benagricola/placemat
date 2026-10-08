from pathlib import Path
import pytest
from placemat.kicad.final_call import file_hash
from placemat.kicad.replay_ordinary_trigger import permits_second_slot

@pytest.mark.parametrize('summary,expected',[
 ({},False),({'status':'already_connected'},False),({'regrade':{}},False),
 ({'regrade':{},'failed_single':['A']},True),
 ({'connections':[{'joined':True,'status':'joined_narrow'}]},True),
 ({'connections':[{'joined':True,'status':'deferred'}]},True),
 ({'connections':[{'joined':True,'status':'joined'}]},False),
 ({'regrade':{},'multipoint_pads_total':4,'multipoint_pads_connected':3},True),
])
def test_original_raw_summary_controls_second_slot(summary,expected):
    helper=Path(__file__).parent/'fixtures'/'replay_backend'/'ordinary_grade.py'
    assert permits_second_slot(helper,summary,file_hash(helper)) is expected
