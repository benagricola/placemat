"""Shared routing budgets and live-only paired handoff controls."""
from types import SimpleNamespace

import pytest

from placemat.pinmap_common import CandidateRefused
from placemat import pinmap_explore_route as paired


def test_budget_retains_earlier_deadline_and_restores_environment(monkeypatch):
    monkeypatch.setattr(paired.time, 'time', lambda: 100.0)
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC', '125.0')
    with pytest.raises(RuntimeError):
        with paired.budget(SimpleNamespace(timeout_route=180)) as deadline:
            assert deadline == 125.0
            assert paired.os.environ['KRT_ROUTE_DEADLINE_UTC'] == '125.0'
            raise RuntimeError('injected writer failure')
    assert paired.os.environ['KRT_ROUTE_DEADLINE_UTC'] == '125.0'


@pytest.mark.parametrize('value', ['nan', 'inf', 'invalid', '99'])
def test_bad_or_expired_inherited_budget_refuses_before_work(monkeypatch, value):
    monkeypatch.setattr(paired.time, 'time', lambda: 100.0)
    monkeypatch.setenv('KRT_ROUTE_DEADLINE_UTC', value)
    with pytest.raises(CandidateRefused):
        with paired.budget(SimpleNamespace(timeout_route=180)):
            pytest.fail('invalid budget admitted')
    assert paired.os.environ['KRT_ROUTE_DEADLINE_UTC'] == value


def test_live_finish_uses_same_deadline_full_scope_and_withholds_publication(tmp_path, monkeypatch):
    from placemat import pinmap_logical_compare
    events = []
    monkeypatch.setattr(paired.time, 'time', lambda: 100.0)
    source = SimpleNamespace(routed_pcb=tmp_path / 'source.pcb', as_dict=lambda: {'raw': 'source'})
    candidate = SimpleNamespace(routed_pcb=tmp_path / 'final.pcb', as_dict=lambda: {'raw': 'candidate'})
    class Router:
        def route(self, pcb, folder, **kwargs):
            events.append(('route', kwargs))
            assert paired.os.environ['KRT_ROUTE_DEADLINE_UTC'] == '125.0'
            assert kwargs['quick'] is False and kwargs['capture_path'] == str(tmp_path / 'candidate.capture')
            return candidate
    class Authority:
        def regrade(self, pcb, destination):
            events.append(('grade', pcb))
            assert paired.os.environ['KRT_ROUTE_DEADLINE_UTC'] == '125.0'
            return SimpleNamespace(physical=pcb)
    class Comparison:
        def rank(self):
            events.append(('rank',))
            return -1
        def verify(self):
            events.append(('verify',))
        def diagnostic(self):
            return {'checked': True}
    monkeypatch.setattr(pinmap_logical_compare, 'evaluate', lambda *args: Comparison())
    original_factory = SimpleNamespace(completed_authority=lambda: Authority())
    final_factory = SimpleNamespace(completed_authority=lambda: Authority(),
        _invocation={'capture': {'path': str(tmp_path / 'candidate.capture')}})
    with paired.budget(SimpleNamespace(timeout_route=25)) as deadline:
        returned, diagnostic, live = paired._finish(Router(), source, tmp_path / 'candidate.pcb', tmp_path,
            {'plane'}, True, original_factory, final_factory, object(), deadline)
    assert returned is source
    assert diagnostic['candidate_rank'] == -1
    assert diagnostic['improving_proposal'] is True and isinstance(live, Comparison)
    assert diagnostic['adoption_refusal']['code'] == 'logical_mapping_publication_unsupported'
    assert diagnostic['source_report'] == {'raw': 'source'}
    assert diagnostic['candidate_report'] == {'raw': 'candidate'}
    assert [event[0] for event in events] == ['route', 'grade', 'grade', 'rank', 'verify']


def test_expired_prior_seed_is_incomparable_without_extending_deadline():
    old = object()
    class Live:
        def compare_candidate(self, incumbent, **kwargs):
            assert incumbent is old
            raise CandidateRefused('authority_deadline_or_invocation_changed', 'prior seed expired')
    diagnostic = {'improving_proposal': True}
    assert paired.compare_live(old, Live(), diagnostic) is old
    assert diagnostic['cross_seed_refusal']['code'] == 'authority_deadline_or_invocation_changed'
    assert 'cross_seed_candidate_rank' not in diagnostic


def test_nonimproving_mapping_never_enters_cross_seed_ranking():
    class Live:
        def compare_candidate(self, *args, **kwargs):
            pytest.fail('nonimproving candidate was compared')
    old = object()
    diagnostic = {'improving_proposal': False}
    assert paired.compare_live(old, Live(), diagnostic) is old


@pytest.mark.parametrize('refusal_type', ['route', 'proof'])
def test_known_candidate_refusal_retains_completed_source(monkeypatch, refusal_type):
    class RouteRefused(ValueError):
        code, facts = 'route_refused', {'detail': 'measured refusal'}
    class ProofUnavailable(ValueError):
        code, facts = 'proof_unavailable', {'detail': 'missing proof'}
    monkeypatch.setattr(paired, '_known_refusals', lambda: (RouteRefused, ProofUnavailable))
    source = object()
    error = (RouteRefused if refusal_type == 'route' else ProofUnavailable)('refused')
    def fail():
        raise error
    with pytest.raises(paired.PairedUnavailable) as caught:
        paired._after_source(source, fail)
    assert caught.value.source is source
    assert caught.value.code == error.code and caught.value.facts == error.facts


def test_unexpected_candidate_defect_propagates_with_source_diagnostic():
    source = object()
    error = RuntimeError('unexpected defect')
    def fail():
        raise error
    with pytest.raises(RuntimeError) as caught:
        paired._after_source(source, fail)
    assert caught.value is error and caught.value.completed_source_route is source


def test_candidate_cancellation_propagates_unchanged():
    def cancel():
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        paired._after_source(object(), cancel)


def test_real_router_failure_retains_source_and_exit_artifacts(tmp_path, monkeypatch):
    from placemat.kicad.route import RouterFailed
    error = RouterFailed('candidate failed', 7, tmp_path / 'route.log', 'last output')
    error.code, error.facts = 'router_failed', {'stage': 'REST'}
    monkeypatch.setattr(paired, '_known_refusals', lambda: (RouterFailed,))
    source = object()
    def fail():
        raise error
    with pytest.raises(paired.PairedUnavailable) as caught:
        paired._after_source(source, fail)
    assert caught.value.source is source
    assert caught.value.facts == {'stage': 'REST', 'exit_code': 7,
                                 'log': str(tmp_path / 'route.log'), 'tail': 'last output'}


def test_actual_worker_expiry_retains_prior_seed_without_rerouting():
    final_call = pytest.importorskip('placemat.kicad.final_call')
    old = object()
    class Live:
        def compare_candidate(self, incumbent, **kwargs):
            assert incumbent is old
            raise final_call.ProofUnavailable('final_worker_deadline_expired')
    diagnostic = {'improving_proposal': True}
    assert paired.compare_live(old, Live(), diagnostic) is old
    assert diagnostic['cross_seed_refusal'] == {'code': 'final_worker_deadline_expired', 'facts': {}}


def test_full_route_presentation_does_not_claim_executable_mapping():
    from placemat.explore import route_line, routes_summary
    row = {'seed': 1, 'score': 10.0, 'closure_clean': 1.0, 'closure': 1.0,
           'open_after': 0, 'seconds': 2.0, 'routing_mode': 'full_configured_shared_deadline',
           'remap_refusal': {'code': 'unsupported', 'facts': {}}}
    line = route_line(row)
    assert 'full configured scope with shared deadline' in line
    assert 'source-board diagnostic only' in line
    assert 'routed with its pin remap' not in line
    summary = routes_summary({'routes': [row], 'taken_seed': 1})[0]
    assert '1 full configured with shared deadlines, 0 quick' in summary
