"""Generated-wall provenance does not grant rerouting or Standing authority."""
import json
from pathlib import Path

import pytest

from placemat.kicad import issued_calls, replay_inventory
from placemat.kicad.final_call import ProofUnavailable
from tests.test_issued_calls import pour_execution, pour_issue, issued, finish, issue
from tests.test_final_custody import context

WALL = '(segment (start 2 0) (end 3 0) (width 0.2) (layer "F.Cu") (net 1) (uuid "wall"))'


@pytest.fixture
def walls(pour_execution, tmp_path, request):
    hook = pour_execution
    token, options = pour_issue(hook, tmp_path)
    source = hook.grader._original.read_text()
    output = options['output_board']
    output.write_text(source[:-1] + WALL + ')')
    summary = options['summary']
    summary.write_text(json.dumps(dict(successful=1, failed=0, total_iterations=1, total_vias=0, total_time=.1)))
    issued_calls._executor_raw_result(hook.grader, hook.ledger, hook.executor, token,
                                     returncode=0, snapshot_dir=tmp_path / 'raw')
    output.with_suffix('.kicad_pro').write_bytes(hook.grader._original.with_suffix('.kicad_pro').read_bytes())
    issued_calls._executor_restored_result(hook.grader, hook.ledger, hook.executor, token)
    fixed, _ = replay_inventory._forms(output)
    selected = [form for form in fixed if '"wall"' in str(form)]
    if getattr(request, 'param', False):
        prior = output
        later, next_options = pour_issue(hook, tmp_path, call=1, source=prior, input_board=prior,
                                         output_board=tmp_path/'later.kicad_pcb',
                                         summary=tmp_path/'later_summary.json', snapshot_dir=tmp_path/'later-before')
        output = next_options['output_board']
        output.write_text(prior.read_text()[:-1] + WALL.replace('"wall"', '"later"')
                          .replace('(start 2 0) (end 3 0)', '(start 4 0) (end 5 0)') + ')')
        output.with_suffix('.kicad_pro').write_bytes(prior.with_suffix('.kicad_pro').read_bytes())
        next_options['summary'].write_text(summary.read_text())
        issued_calls._executor_raw_result(hook.grader, hook.ledger, hook.executor, later,
                                         returncode=0, snapshot_dir=tmp_path/'later-raw')
        issued_calls._executor_restored_result(hook.grader, hook.ledger, hook.executor, later)
    return hook, token, output, selected


def proof(walls, **changes):
    hook, token, output, selected = walls
    return replay_inventory.proved_walls(hook.grader, hook.ledger, hook.executor, token,
                                        final_input=changes.get('final_input', output),
                                        selected=changes.get('selected', selected))


def test_only_exact_generated_unique_wall_is_bound(walls):
    result = proof(walls)
    assert len(result['removed_forms']) == 1
    assert result['identity']['kind'] == 'pour'
    assert result['final_input_sha256']
    assert walls[2].read_text().count('"wall"') == 1


def test_original_fixed_item_cannot_be_selected(walls):
    fixed, _ = replay_inventory._forms(walls[0].grader._original)
    with pytest.raises(ProofUnavailable, match='origin_ambiguous'):
        proof(walls, selected=[fixed[0]])


def test_duplicate_attribution_refuses(walls):
    with pytest.raises(ProofUnavailable, match='unsupported'):
        proof(walls, selected=walls[3] * 2)


def test_ambiguous_current_multiplicity_refuses(walls, tmp_path):
    current = tmp_path / 'current.kicad_pcb'
    text = walls[2].read_text()
    current.write_text(text[:-1] + WALL + ')')
    with pytest.raises(ProofUnavailable, match='origin_ambiguous'):
        proof(walls, final_input=current)


def test_changed_zone_intent_refuses(walls, tmp_path):
    current = tmp_path / 'current.kicad_pcb'
    current.write_text(walls[2].read_text()[:-1] + '(zone (net 1) (priority 99)) )')
    with pytest.raises(ProofUnavailable, match='intent_unproved'):
        proof(walls, final_input=current)


def test_different_uuid_same_physical_geometry_is_not_unique_attribution(walls, tmp_path):
    current = tmp_path / 'current.kicad_pcb'
    text = walls[2].read_text()
    duplicate = WALL.replace('"wall"', '"different-uuid"').replace('(width 0.2)', '(width .20)')
    current.write_text(text[:-1] + duplicate + ')')
    with pytest.raises(ProofUnavailable, match='origin_ambiguous'):
        proof(walls, final_input=current)


def test_reversed_endpoints_different_uuid_is_same_physical_wall(walls, tmp_path):
    current = tmp_path / 'current.kicad_pcb'
    text = walls[2].read_text()
    duplicate = WALL.replace('(start 2 0) (end 3 0)', '(end 2 0) (start 3 0)').replace('"wall"', '"reversed"')
    current.write_text(text[:-1] + duplicate + ')')
    with pytest.raises(ProofUnavailable, match='origin_ambiguous'):
        proof(walls, final_input=current)


@pytest.fixture
def final_call(walls, tmp_path, request):
    from placemat.kicad.phase_run import Call
    hook, prior, input_board, selected = walls
    prior_count = len(hook.ledger.issued)
    issued_calls._executor_plan(hook.grader, hook.ledger, hook.executor, phase=0,
                               calls=[Call('pour', ('N',)) for _ in range(prior_count)] + [Call('nets', ('N',))],
                               layers=['F.Cu'], input_board=hook.grader._original)
    output, summary = tmp_path / 'final.kicad_pcb', tmp_path / 'final_summary.json'
    token = issued_calls._executor_issue(
        hook.grader, hook.ledger, hook.executor, phase=0, call=prior_count, wave=0, kind='single',
        command=['python', 'route.py', str(input_board), '--nets', 'N', '--layers', 'F.Cu'], source=input_board,
        input_board=input_board, output_board=output, summary=summary,
        layers=['F.Cu'], nets=['N'], tasks=[], constraint_files=(),
        snapshot_dir=tmp_path / 'final-before')
    output.write_bytes(input_board.read_bytes())
    output.with_suffix('.kicad_pro').write_bytes(input_board.with_suffix('.kicad_pro').read_bytes())
    summary.write_text(json.dumps(getattr(request, 'param', {})))
    issued_calls._executor_raw_result(hook.grader, hook.ledger, hook.executor, token,
                                     returncode=0, snapshot_dir=tmp_path / 'final-raw')
    issued_calls._executor_restored_result(hook.grader, hook.ledger, hook.executor, token)
    return token


def test_inventory_binds_actual_final_call_input(walls, final_call):
    hook, prior, actual_input, selected = walls
    result = replay_inventory.walls_at_final_call(hook.grader, hook.ledger, hook.executor,
                                                 prior, final_call, selected=selected)
    assert result['final_input'] == str(actual_input.resolve())
    assert result['final_issued_call_sha256']


def test_changed_actual_final_input_withholds_inventory(walls, final_call):
    hook, prior, actual_input, selected = walls
    actual_input.write_text('changed input')
    with pytest.raises(ProofUnavailable):
        replay_inventory.walls_at_final_call(hook.grader, hook.ledger, hook.executor,
                                             prior, final_call, selected=selected)


def test_complete_supported_work_uses_actual_prior_and_final_receipts(walls, final_call):
    hook = walls[0]
    result = replay_inventory.supported_completed_work(hook.grader, hook.ledger, hook.executor)
    assert result['plans_sha256'] and result['issued_calls_sha256']


def test_missing_actual_pipeline_plan_cannot_be_reconstructed_from_selector(walls):
    hook = walls[0]
    with pytest.raises(ProofUnavailable, match='work_list_incomplete'):
        replay_inventory.supported_completed_work(hook.grader, hook.ledger, hook.executor)


def test_later_unrecorded_pair_call_withholds_complete_work(walls, final_call):
    from copy import deepcopy
    from placemat.kicad.final_call import record_digest
    hook = walls[0]
    plan = deepcopy(hook.ledger.call_plans[0][0])
    plan['calls'].append(dict(kind='pairs', nets=['N'], excluded=[], tasks=[], width=None, clearance=None))
    hook.ledger.call_plans[0] = (plan, record_digest(plan))
    with pytest.raises(ProofUnavailable, match='work_list_unsupported'):
        replay_inventory.supported_completed_work(hook.grader, hook.ledger, hook.executor)


def test_connection_work_matches_actual_completed_task_wave(issued, tmp_path):
    from placemat.kicad.phase_run import Call
    from placemat.kicad.phase_select import Task
    grader, ledger, executor, options = issued
    task = Task('N', ('A', '1'), ('B', '1'), (('F.Cu', .2),))
    issued_calls._executor_plan(grader, ledger, executor, phase=0, calls=[Call('tasks', tasks=(task,))],
                               layers=['F.Cu'], input_board=options['input_board'])
    token = issue(issued)
    finish(issued, token, tmp_path)
    assert replay_inventory.supported_completed_work(grader, ledger, executor)


def test_unissued_planned_task_is_not_completed_work(issued, tmp_path):
    from placemat.kicad.phase_run import Call
    from placemat.kicad.phase_select import Task
    grader, ledger, executor, options = issued
    tasks = (Task('N', ('A', '1'), ('B', '1'), (('F.Cu', .2),)),
             Task('N', ('A', '1'), ('C', '1'), (('F.Cu', .2),)))
    issued_calls._executor_plan(grader, ledger, executor, phase=0, calls=[Call('tasks', tasks=tasks)],
                               layers=['F.Cu'], input_board=options['input_board'])
    token = issue(issued)
    finish(issued, token, tmp_path)
    with pytest.raises(ProofUnavailable, match='task_wave_scope_incomplete'):
        replay_inventory.supported_completed_work(grader, ledger, executor)
