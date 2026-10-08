"""Private value comparison after a live owned logical route check.

No decoded record can construct this capability. Raw physical reports and their
contracts stay unchanged; the private value view uses the independently checked
original fixed asks. Publication of an executable pin mapping is separate.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
import json
from pathlib import Path
import weakref

from . import score
from .pinmap_common import CandidateRefused
from .pinmap_logical_packet import _hash, _json

_SEAL = object()
_MINTED = weakref.WeakValueDictionary()
_RECORDS = {}


def _refuse(code, **facts):
    raise CandidateRefused(code, 'logical route comparison is unavailable', **facts)


def _scope(request, response, *, source_semantics=None):
    """Stable logical obligations; actual raw receipt digests are not erased."""
    phases = []
    for phase in request['logical']['phases']:
        asks = [{key: entry['original'][key] for key in ('net', 'from', 'to', 'widths')}
                for entry in phase['asks']]
        phases.append({'definition': phase['definition'], 'asked': asks,
                       'members': [{'net': member['net'], 'original': member['original']}
                                   for member in phase['members']]})
    original = request['critical_original']
    intent = {key: original[key] for key in ('settings', 'rules', 'acceptances', 'edge_margin',
        'component_spacing', 'board_shape', 'board_cutouts', 'quiet', 'planes', 'pending', 'fields')}
    baseline = response['original_verification']['original']
    return {'phases': phases, 'widths': request['logical']['widths'], 'intent': intent,
            'original_roles': [[net, old] for net, old, _ in request['logical']['roles']],
            'sidecars': sorted([[Path(row['original']).name, row['sha256']]
                                for row in request['input_bundle']['sidecars']]),
            'physical_rules': request['expected_readback']['rules'],
            'source_semantics': source_semantics,
            'fixed': response['fixed_preservation'],
            'baseline_semantics_sha256': baseline['baseline_semantics_sha256'],
            'original_open': baseline['open_before'], 'counted': baseline['counted']}


def _standing(physical, judgment):
    """Detached comparison values, retaining all known physical failures."""
    measures = copy.deepcopy(physical.measures)
    measures.update(copy.deepcopy(judgment['critical']['measures']))
    under = sum(bool(verdict['under']) and verdict['joined']
                for phase in judgment['phases'] for verdict in phase['judged'])
    validity = score.Validity.of(measures, drc_new=judgment['drc_new'],
                                widths_failed=max(physical.validity.widths_failed, under))
    # Known physical critical failures must not vanish when another final
    # checker reports fewer. Missing required evidence never becomes success.
    validity = replace(validity, critical=max(validity.critical, physical.validity.critical),
                       unmeasured=tuple(sorted(set(validity.unmeasured) | set(physical.validity.unmeasured))))
    return replace(physical, measures=measures, validity=validity,
                   closures=tuple(phase['closure_clean'] for phase in judgment['phases']),
                   clean=judgment['closure_clean'])


@dataclass(frozen=True)
class LogicalRouteComparison:
    """Live retained evidence; its diagnostic JSON is never a capability."""
    proof: object
    original_authority: object
    original: object
    candidate_authority: object
    candidate: object
    destination: Path
    _seal: object

    def verify(self):
        if type(self) is not LogicalRouteComparison or self._seal is not _SEAL or _MINTED.get(id(self)) is not self:
            _refuse('logical_comparison_not_minted')
        from .pinmap_logical_owned import _pair, _artifact_record
        from .pinmap_logical_worker import _input_bundle
        from .kicad.final_owned_worker import _implementation, _remaining, _validate_original_proof
        from .kicad.final_worker_protocol import export
        from .pinmap_written import _hash as file_hash
        retained = _RECORDS[id(self)]
        if (any(actual is not expected for actual, expected in zip(
                (self.proof, self.original_authority, self.original, self.candidate_authority, self.candidate),
                retained['objects'])) or str(self.destination) != retained['destination']):
            _refuse('logical_comparison_object_changed')
        request, response = json.loads(retained['request']), json.loads(retained['response'])
        a, b = self.original_authority._factory, self.candidate_authority._factory
        self.proof.verify(a._board, a._plan, a._board.settings)
        _remaining(a._deadline_utc)
        for side, authority, candidate in (('original', self.original_authority, self.original),
                                           ('candidate', self.candidate_authority, self.candidate)):
            _pair(authority, candidate)
            expected = request[side]
            actual = export(authority._grader, candidate.physical.report.routed_pcb,
                            self.destination / side, deadline_utc=a._deadline_utc)
            if _json(actual) != _json(expected):
                _refuse('logical_comparison_execution_changed')
            _validate_original_proof(authority._grader, response['original_verification'][side], self.destination / side)
            _artifact_record(response['judgments'][side], self.destination / side)
        if (_implementation() != response['implementation_start']
                or file_hash(self.destination / 'request.json') != retained['request_file_sha256']
                or file_hash(self.destination / 'response.json') != retained['response_file_sha256']):
            _refuse('logical_comparison_evidence_changed')
        _input_bundle(request['input_bundle'], request)
        return request, response

    def diagnostic(self):
        request, response = self.verify()
        return {'schema': 1, 'request_sha256': _hash(request), 'judgments': copy.deepcopy(response['judgments'])}

    def rank(self, *, phase_priority=None):
        """Candidate versus its original; ties retain the original mapping."""
        request, response = self.verify()
        names = tuple(phase['definition']['name'] for phase in request['logical']['phases'])
        indices = None
        if phase_priority is not None:
            if (type(phase_priority) not in (list, tuple) or any(type(name) is not str or name not in names
                    for name in phase_priority) or len(set(phase_priority)) != len(phase_priority)):
                _refuse('logical_phase_priority_invalid')
            indices = tuple(names.index(name) for name in phase_priority)
        a = _standing(self.original.standing, response['judgments']['original'])
        b = _standing(self.candidate.standing, response['judgments']['candidate'])
        if a.validity.unmeasured or b.validity.unmeasured:
            _refuse('logical_final_unmeasured')
        result = score._rank_values(b, a, self.original_authority._factory._board.settings, indices=indices)
        self.verify()
        return result

    def compare_candidate(self, incumbent, *, phase_priority=None):
        """Across seeds, require the same measured baseline and fixed asks."""
        if type(incumbent) is not LogicalRouteComparison:
            _refuse('logical_comparison_not_minted')
        request, response = self.verify()
        old_request, old_response = incumbent.verify()
        if _json(_scope(request, response, source_semantics=self.proof.physical.semantics)) != _json(
                _scope(old_request, old_response, source_semantics=incumbent.proof.physical.semantics)):
            _refuse('logical_seed_obligations_incomparable')
        # Each capability's original/candidate comparison validates the
        # requested phase policy before these shared value tiers are reached.
        self.rank(phase_priority=phase_priority)
        incumbent.rank(phase_priority=phase_priority)
        names = tuple(phase['definition']['name'] for phase in request['logical']['phases'])
        indices = None if phase_priority is None else tuple(names.index(name) for name in phase_priority)
        current = _standing(self.candidate.standing, response['judgments']['candidate'])
        prior = _standing(incumbent.candidate.standing, old_response['judgments']['candidate'])
        result = score._rank_values(current, prior, self.original_authority._factory._board.settings, indices=indices)
        self.verify()
        incumbent.verify()
        return result


def evaluate(proof, original_authority, original, candidate_authority, candidate, destination):
    """The only mint: invoke the actual owned checker on retained live objects."""
    from .pinmap_logical_owned import check
    from .pinmap_written import _hash as file_hash
    response = check(proof, original_authority, original, candidate_authority, candidate, destination)
    destination = Path(destination).absolute()
    request = (destination / 'request.json').read_text()
    from .kicad.final_owned_worker import _json as decode
    if (_hash(decode(request)) != response['request_sha256']
            or _json(decode((destination / 'response.json').read_text())) != _json(response)):
        _refuse('logical_comparison_evidence_changed')
    record = {'request': request, 'response': _json(response),
              'request_file_sha256': file_hash(destination / 'request.json'),
              'response_file_sha256': file_hash(destination / 'response.json'),
              'objects': (proof, original_authority, original, candidate_authority, candidate),
              'destination': str(destination)}
    result = LogicalRouteComparison(proof, original_authority, original, candidate_authority, candidate, destination, _SEAL)
    _MINTED[id(result)] = result
    _RECORDS[id(result)] = record
    weakref.finalize(result, _RECORDS.pop, id(result), None)
    result.verify()
    return result
