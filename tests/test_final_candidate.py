"""Final-call proof reflects actual work/scope; refusal preserves issued router arguments."""
import json
from types import SimpleNamespace

import pytest

from placemat.kicad.final_candidate import CandidatePlanner
from tests.test_final_call import context  # shared minimal immutable policy/board fixture


@pytest.fixture
def planner_case(context, request):
    pcb, scope, policy, authority = context
    observations = [[{'net': 'SIGNAL', 'from': {'ref': 'U1', 'pad': '1'},
                      'to': {'ref': 'U2', 'pad': '2'}, 'widths': {layer: getattr(request, 'param', .5) for layer, _ in scope.obligations[0].widths}}]]
    receipt_path = pcb.with_name('width_policy.json')
    planner = CandidatePlanner(authority=authority, phases=[SimpleNamespace(name='signals')],
                               obligations=observations, width_receipt=json.loads(policy.receipt),
                               receipt_path=receipt_path, complete=True,
                               capabilities={'schema': 1, 'modules': {'route.py': True},
                                             'flags': {'route.py': ['--final-call-proof', '--candidate-artifacts']}})
    output, summary = pcb.with_name('out.kicad_pcb'), pcb.with_name('summary.json')
    command = ['python', 'route.py', str(pcb), str(output), '--nets', 'SIGNAL', '--layers', 'F.Cu', 'B.Cu',
               '--json-out', str(summary)]
    arguments = dict(phase_index=0, call_index=0, calls=[object()], call_id='p0_0', board=pcb,
                     output=output, summary=summary, command=command, launch=['python', 'route.py'],
                     nets=['SIGNAL'], layers=['F.Cu', 'B.Cu'], deadline_utc=200, now=100)
    return planner, arguments, observations


def test_actual_final_ordinary_call_gets_one_bound_request(planner_case):
    planner, args, _ = planner_case
    planner.note('p0_0', 'rest')
    issued = planner.prepare(**args)
    assert issued[:len(args['command'])] == args['command']
    assert issued[-4] == '--final-call-proof' and issued[-2] == '--candidate-artifacts'
    proof = json.loads(open(issued[-3]).read())
    assert proof['copper_work'] == [{'id': 'p0_0', 'kind': 'single'}]
    assert proof['call']['routing_flags'] == args['command'][4:-2]
    assert planner.prepare(**args) == args['command']
    assert planner.refusals[-1]['code'] == 'candidate_request_already_issued'


@pytest.mark.parametrize('kind', ['pairs', 'pour', 'tasks', 'bus_tasks', 'bus', 'unknown'])
def test_unenumerated_prior_pipeline_preserves_ordinary_router_call(planner_case, kind):
    planner, args, _ = planner_case
    planner.note('prior', kind)
    planner.note('p0_0', 'nets')
    assert planner.prepare(**args) == args['command'] and not planner.requests
    assert planner.refusals[-1]['code'] == 'completed_work_custody_unproved'


def test_resumed_pipeline_is_not_fabricated_as_current_issued_work(planner_case):
    planner, args, _ = planner_case
    planner.resumed('earlier')
    planner.note('p0_0', 'nets')
    assert planner.prepare(**args) == args['command']
    assert planner.refusals[-1]['facts']['calls'] == ['resumed:earlier']


def test_later_actual_call_cannot_be_declared_final(planner_case):
    planner, args, _ = planner_case
    planner.note('p0_0', 'nets')
    args['calls'] = [object(), object()]
    assert planner.prepare(**args) == args['command'] and not planner.requests
    assert planner.refusals[-1]['code'] == 'later_copper_work'


@pytest.mark.parametrize('planner_case', [.8], indirect=True)
def test_original_requested_width_cannot_be_replaced_by_weaker_nominal(planner_case):
    planner, args, observations = planner_case
    planner.note('p0_0', 'nets')
    assert planner.prepare(**args) == args['command']
    assert planner.refusals[-1]['code'] == 'terminal_policy_mismatch'


def test_mutating_caller_obligations_does_not_change_request(planner_case):
    planner, args, observations = planner_case
    observations[0][0]['widths']['F.Cu'] = .1
    planner.note('p0_0', 'nets')
    command = planner.prepare(**args)
    proof = json.loads(open(command[-3]).read())
    assert proof['call']['obligations'][0]['widths']['F.Cu'] == .5


@pytest.mark.parametrize('caps', [None, {}, {'schema': 1, 'modules': {'route.py': True},
                                          'flags': {'route.py': ['--nets']}},
                                {'schema': 1, 'modules': {'route.py': True},
                                 'flags': {'route.py': [['--final-call-proof']]}},
                                {'schema': 1, 'modules': [], 'flags': {}},
                                {'schema': 1, 'modules': {'route.py': True}, 'flags': []},
                                {'schema': True, 'modules': {'route.py': True},
                                 'flags': {'route.py': ['--final-call-proof', '--candidate-artifacts']}}])
def test_missing_or_malformed_optional_capability_preserves_ordinary_call(planner_case, caps):
    planner, args, _ = planner_case
    planner._capabilities = caps
    planner.note('p0_0', 'nets')
    assert planner.prepare(**args) == args['command'] and not planner.requests
    assert planner.refusals[-1]['code'] == 'final_call_capability_unavailable'


@pytest.mark.parametrize('complete', [False, None, 1, 'complete', []])
def test_only_literal_complete_proof_enables_request(planner_case, complete):
    planner, args, _ = planner_case
    planner._complete = complete
    planner.note('p0_0', 'nets')
    assert planner.prepare(**args) == args['command']
    assert planner.refusals[-1]['code'] == 'partial_route'


def test_incomplete_original_contract_is_structured_refusal(planner_case):
    planner, args, _ = planner_case
    planner._obligations = '[]'
    planner.note('p0_0', 'nets')
    assert planner.prepare(**args) == args['command']
    assert planner.refusals[-1]['code'] == 'original_contract_count_mismatch'


@pytest.mark.parametrize('caps', [{'flags': object()}, {'schema': float('nan')}])
def test_unserializable_capability_does_not_prevent_ordinary_routing(planner_case, caps):
    _, args, _ = planner_case
    planner = CandidatePlanner(authority=None, phases=[], obligations=[], width_receipt={},
                               receipt_path=args['summary'], complete=True, capabilities=caps)
    planner.note('p0_0', 'nets')
    assert planner.prepare(**args) == args['command']
    assert planner.refusals[-1]['code'] == 'final_call_capability_unavailable'
