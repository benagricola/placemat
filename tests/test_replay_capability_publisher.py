"""Actual configured source-only capability CLI under the owned query."""
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace
import pytest
from placemat.kicad import replay_capability
from placemat.kicad.final_call import ProofUnavailable

@pytest.fixture
def clone(tmp_path):
    supplied=os.environ.get('KRT_DIR')
    if not supplied:pytest.skip('KRT_DIR required for actual capability source fixture')
    source=Path(supplied);root=tmp_path/'clone';tools=root/'py_router';tools.mkdir(parents=True)
    shutil.copyfile(source/'krt_capabilities.py',root/'krt_capabilities.py')
    shutil.copyfile(source/'py_router/execution_policy_capabilities.py',tools/'execution_policy_capabilities.py')
    (tools/'route.py').write_text("KRT_EXECUTION_POLICIES={'schema':1,'legacy_only':True,'pocket':True,'policy_receipt_schema':2,'parent_scope_schema':2,'ordinary_grade_request_schema':2}\n")
    for name in ('route_execution_receipt.py','route_candidates.py'):(tools/name).write_text('# controlled source-only fixture\n')
    return SimpleNamespace(router_dir=root,script='py_router/route.py',rpy=sys.executable,env=dict(os.environ)),tools

def test_actual_top_cli_and_publisher_pinned(clone,tmp_path):
    ctx,tools=clone;receipt=replay_capability.query(ctx,time.time()+10,tmp_path/'query')
    assert receipt['command']==[sys.executable,str(ctx.router_dir/'krt_capabilities.py')]
    assert str((tools/'execution_policy_capabilities.py').resolve()) in receipt['sources']

@pytest.mark.parametrize('change',['mutation','deletion'])
def test_publisher_changed_during_actual_query_refuses(clone,tmp_path,monkeypatch,change):
    ctx,tools=clone;original=replay_capability._execute;p=tools/'execution_policy_capabilities.py'
    def execute(*args,**kwargs):
        result=original(*args,**kwargs)
        p.write_text(p.read_text()+'\n# changed\n') if change=='mutation' else p.unlink()
        return result
    monkeypatch.setattr(replay_capability,'_execute',execute)
    with pytest.raises(ProofUnavailable,match='replay_execution_capability_changed'):
        replay_capability.query(ctx,time.time()+10,tmp_path/'query')

def test_wrong_advertised_origin_refuses(clone,tmp_path,monkeypatch):
    import json
    ctx,tools=clone;original=replay_capability._execute
    def execute(*args,**kwargs):
        rc,out,err=original(*args,**kwargs);caps=json.loads(out);caps['execution_policy_publisher']['path']='/wrong/publisher.py'
        return rc,json.dumps(caps),err
    monkeypatch.setattr(replay_capability,'_execute',execute)
    with pytest.raises(ProofUnavailable,match='replay_execution_capability_unavailable'):
        replay_capability.query(ctx,time.time()+10,tmp_path/'query')
