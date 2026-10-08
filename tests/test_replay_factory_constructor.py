"""Actual retain and FinalExecution constructors on a pure original context."""
import importlib.util,time
from pathlib import Path
from types import SimpleNamespace
import pytest
authority=pytest.importorskip('placemat.final_authority')
retain,AuthorityRefused=authority.retain,authority.AuthorityRefused
from placemat.layout import Board
from placemat.settings import Settings
from tests.fixtures import board_geometry


def test_real_retained_factory_and_execution_constructor_preserve_original(tmp_path):
    geometry=board_geometry([])
    board=Board(geometry,keep_going=True,settings=Settings())
    occupancy=SimpleNamespace(items={},copper=[],pending=set(),_cell_rule_areas={},quiet_nets=set(),plane_nets=set())
    plan=SimpleNamespace(geometry=geometry,occupancy=occupancy,links=[],pushes=[],steps=[],acceptances=[])
    source=tmp_path/'original.kicad_pcb';source.write_text('(kicad_pcb (version 20260101))\n')
    source.with_suffix('.kicad_pro').write_text('{}\n')
    before=source.read_bytes(),source.with_suffix('.kicad_pro').read_bytes()
    deadline=time.time()+60
    factory=retain(board,plan,{},source,invocation={},deadline_utc=deadline)
    from placemat.kicad import final_execution as module
    hook=module.FinalExecution(factory,tmp_path)
    assert hook.active and hook.factory is factory and hook.deadline==deadline
    assert hook.ledger is None and hook.grader is None
    try:factory.completed_authority()
    except AuthorityRefused as error:assert error.code=='authority_completion_unavailable'
    else:raise AssertionError('constructor alone manufactured completion')
    assert before==(source.read_bytes(),source.with_suffix('.kicad_pro').read_bytes())
