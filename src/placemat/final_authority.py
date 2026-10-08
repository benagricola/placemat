"""Retain original layout/check intent for optional final copper comparison.

A descriptor has no authority. The retained factory binds the executor's actual
original selector/width context once, before any candidate call, and only its
own independently regraded artifacts can be compared or published.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import math
import time
from pathlib import Path
import shutil
import tempfile

from . import score
from .pinmap_common import CandidateRefused


class AuthorityRefused(CandidateRefused):
    pass


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _context(board, plan):
    occ = plan.occupancy
    return _digest({'settings': board.settings.json(), 'geometry': repr(plan.geometry),
                    'items': repr(sorted(occ.items.items())), 'copper': repr(occ.copper),
                    'pending': sorted(occ.pending), 'areas': repr(occ._cell_rule_areas),
                    'links': repr(plan.links), 'pushes': repr(plan.pushes),
                    'steps': repr(plan.steps), 'acceptances': repr(plan.acceptances),
                    'rules': repr(board._rules), 'escapes': repr(board._escapes),
                    'placements': repr(board._placements()),
                    'quiet': sorted(occ.quiet_nets), 'planes': sorted(occ.plane_nets)})



@dataclass(frozen=True)
class AuthoritativeCandidate:
    """Public artifact handles; mutable Standing data is verified before use."""
    physical: object
    standing: score.Standing
    evidence: Path


class RetainedAuthorityFactory:
    def __init__(self, board, plan, measures, source, context_files, invocation, deadline_utc):
        if isinstance(deadline_utc, bool) or not isinstance(deadline_utc, (int, float)) or not math.isfinite(deadline_utc) or deadline_utc <= time.time():
            raise AuthorityRefused("authority_deadline_unavailable", "a finite original absolute deadline is required")
        self._deadline_utc = deadline_utc
        self._invocation = json.loads(json.dumps(invocation, allow_nan=False))
        self._invocation_sha = _digest(self._invocation)
        self._board, self._plan = board, plan
        self._measures = copy.deepcopy(measures)
        self._source = Path(source).resolve()
        paths = [self._source, self._source.with_suffix('.kicad_pro'), self._source.with_suffix('.kicad_dru')]
        paths += [Path(p).resolve() for p in context_files]
        if not self._source.is_file() or not self._source.with_suffix('.kicad_pro').is_file():
            raise AuthorityRefused('authority_original_missing', 'original board/project authority is missing')
        if any(not Path(p).is_file() for p in context_files):
            raise AuthorityRefused('authority_capture_missing', 'original capture authority is missing')
        self._inputs = {str(p): _hash(p) if p.is_file() else None for p in paths}
        self._context = _context(board, plan)
        self._geometry = None
        self._bound = False
        self._authority = self._grader = None

    def _verify(self):
        if time.time() >= self._deadline_utc or _digest(self._invocation) != self._invocation_sha:
            raise AuthorityRefused("authority_deadline_or_invocation_changed", "original deadline expired or invocation changed")
        if _context(self._board, self._plan) != self._context:
            raise AuthorityRefused('authority_original_context_changed', 'original layout/check context changed')
        for raw, expected in self._inputs.items():
            path = Path(raw)
            actual = _hash(path) if path.is_file() else None
            if actual != expected:
                raise AuthorityRefused('authority_original_input_changed', 'original artifact changed', path=raw)

    def bind_physical(self, grader):
        """Bind only a real original executor context, once before candidate calls."""
        try:
            from .kicad.final_route import FinalCopperGrader
        except ImportError as error:
            raise AuthorityRefused('authority_selection_unavailable',
                                   'reviewed physical execution context is unavailable') from error
        if type(grader) is not FinalCopperGrader:
            raise AuthorityRefused('authority_selection_missing', 'actual original selector/width authority is required')
        self._verify()
        if self._bound:
            raise AuthorityRefused('authority_already_bound', 'original physical authority was already bound')
        binding = grader.binding()
        contract = binding['contract']
        original = contract['source_inputs']
        if (Path(binding['paths']['original']).resolve() != self._source
                or original['original'] != self._inputs[str(self._source)]
                or original['rules'] != {ext: self._inputs[str(self._source.with_suffix(ext))]
                                         for ext in ('.kicad_pro', '.kicad_dru')}
                or contract['settings'] != json.loads(self._board.settings.json())):
            raise AuthorityRefused('authority_selection_context_mismatch', 'physical authority does not match retained source/settings')
        if not hasattr(grader, 'original_snapshot'):
            raise AuthorityRefused('authority_original_snapshot_missing', 'typed executor original read snapshot is unavailable')
        from .kicad.final_custody import CustodyUnavailable
        try:
            snapshot = grader.original_snapshot()
        except CustodyUnavailable as error:
            raise AuthorityRefused('authority_original_snapshot_unavailable', 'actual executor original custody could not be verified',
                                   custody_code=error.code, custody_facts=error.facts) from error
        from .board_geometry import BoardGeometry
        required = {'custody_record', 'geometry', 'read_manifest', 'read_identity', 'original_facts',
                    'geometry_sha256', 'worker_geometry_record', 'worker_geometry_sha256'}
        if not isinstance(snapshot, dict) or set(snapshot) != required or type(snapshot['geometry']) is not BoardGeometry:
            raise AuthorityRefused('authority_original_snapshot_malformed', 'executor original snapshot is malformed')
        manifest = snapshot['read_manifest']
        identity = snapshot['read_identity']
        if (not isinstance(manifest, dict) or not isinstance(identity, dict)
                or set(identity) != {'original_read_path', 'read_sha256', 'snapshot_path', 'snapshot_sha256'}):
            raise AuthorityRefused('authority_original_snapshot_malformed', 'executor read manifest is malformed')
        if any(manifest.get(path, object()) != expected for path, expected in self._inputs.items()):
            raise AuthorityRefused('authority_original_snapshot_changed', 'executor read-time inputs differ from retained original files')
        if (Path(snapshot['geometry'].path).resolve() != Path(identity['original_read_path']).resolve()
                or identity['read_sha256'] != identity['snapshot_sha256']
                or manifest.get(str(Path(identity['snapshot_path']).resolve())) != identity['snapshot_sha256']):
            raise AuthorityRefused('authority_original_snapshot_changed', 'original read path and immutable snapshot identities differ')
        self._original_snapshot = copy.deepcopy(snapshot)
        # Integration supplies this exact helper after independent review. It
        # reconstructs original selectors/width requests, without native reads.
        from .original_binding import verify_original_binding
        try:
            verify_original_binding(self, binding, snapshot['geometry'])
        except CandidateRefused as error:
            raise AuthorityRefused(error.code, str(error), **error.facts) from error
        except ImportError as error:
            raise AuthorityRefused('authority_selection_unavailable',
                                   'reviewed original selector/width verification is unavailable') from error
        self._geometry = copy.deepcopy(snapshot['geometry'])
        from .final_check_context import encode, ContextRefused
        try:
            self._critical = encode(self._board, self._plan, self._measures, self._source,
                                    source_geometry=self._geometry)
        except ContextRefused as error:
            raise AuthorityRefused('authority_critical_context_unavailable', 'original critical context cannot be transported exactly',
                                   context_code=error.code, context_facts=error.facts) from error
        self._critical_sha = _digest(self._critical)
        self._bound = True
        self._grader = grader
        self._authority = FullStandingAuthority(self, grader, binding, _SEAL)
        return self._authority


    def completed_authority(self):
        """Private factory custody, never a report or serialized token."""
        self._verify()
        if not self._bound or self._authority is None or self._grader is None:
            raise AuthorityRefused('authority_completion_unavailable', 'original authority has not been bound and completed')
        try:
            from .kicad.final_custody import require_completed, CustodyUnavailable
        except ImportError as error:
            raise AuthorityRefused('authority_completion_unavailable', 'executor completion custody is unavailable') from error
        try:
            require_completed(self._grader)
        except CustodyUnavailable as error:
            raise AuthorityRefused('authority_completion_unavailable', 'original executor completion could not be verified',
                                   custody_code=error.code, custody_facts=error.facts) from error
        if self._authority._factory is not self or self._authority._grader is not self._grader:
            raise AuthorityRefused('authority_completion_mismatch', 'completed authority does not match the privately bound original grader')
        return self._authority


class FullStandingAuthority:
    """Only the retained factory may create this after original proof succeeds."""
    def __init__(self, factory, grader, binding, seal):
        if seal is not _SEAL:
            raise AuthorityRefused('authority_factory_missing', 'retained factory proof is required')
        self._factory, self._grader = factory, grader
        self._binding = copy.deepcopy(binding)
        self._minted = {}
        self._adapter_sha = _hash(Path(__file__))

    def descriptor(self):
        from .kicad.final_call import StandingAuthority
        self._verify_context()
        return StandingAuthority(self._binding['contract_sha256'],
                                 _digest(json.loads(self._factory._board.settings.json())),
                                 self._factory._context, self._adapter_sha)

    def _verify_context(self):
        self._factory._verify()
        if _hash(Path(__file__)) != self._adapter_sha or self._grader.binding() != self._binding:
            raise AuthorityRefused('authority_adapter_context_changed', 'retained grading implementation or physical context changed')

    def regrade(self, raw_board, destination, *, candidate_summary=None):
        from .kicad.final_worker_protocol import export
        from .kicad.final_owned_worker import grade_owned
        self._verify_context()
        request = export(self._grader, raw_board, destination,
                         deadline_utc=self._factory._deadline_utc,
                         candidate_summary=candidate_summary)
        physical, critical, execution = grade_owned(
            self._grader, request, copy.deepcopy(self._factory._critical),
            deadline_utc=self._factory._deadline_utc)
        self._grader.verify(physical)
        if _digest(self._factory._critical) != self._factory._critical_sha:
            raise AuthorityRefused('authority_critical_context_changed', 'retained original check context changed')
        if not isinstance(critical, dict) or set(critical) != {'measures', 'evidence', 'preservation'}:
            raise AuthorityRefused('authority_final_evidence_missing', 'verified final check/preservation evidence is incomplete')
        preserved = critical['preservation']
        # The verified worker binds actual source and final manifests. A
        # boolean asserted by an arbitrary caller is never accepted here.
        if (not isinstance(preserved, dict) or set(preserved) != {'original_manifest', 'held_and_fixed_preserved'}
                or _digest(preserved['original_manifest']) != _digest(self._factory._critical['source_physical'])
                or preserved['held_and_fixed_preserved'] is not True):
            raise AuthorityRefused('authority_held_or_fixed_changed', 'final board does not preserve original held geometry/copper')
        report = physical.report.as_dict()
        report.update(critical['evidence'])
        # An unjoined path may have no measurable span at all. That is distinct
        # from a joined path whose required width is unproved: losing the join
        # must not make unknown width authority into a smaller known failure.
        if len(physical.report.asked) != len(physical.report.final_judged):
            raise AuthorityRefused('authority_width_judgement_missing', 'final phase width judgement is incomplete')
        width_unknown = []
        for phase_index, (obligations, judged) in enumerate(zip(
                physical.report.asked, physical.report.final_judged)):
            if len(obligations) != len(judged):
                raise AuthorityRefused('authority_width_judgement_missing', 'final width judgement is incomplete')
            for obligation_index, (obligation, verdict) in enumerate(zip(obligations, judged)):
                if obligation.get('width_policy_unknown') or verdict.get('width_unknown'):
                    width_unknown.append({'phase': phase_index, 'obligation': obligation_index,
                                          'policy_unknown': bool(obligation.get('width_policy_unknown')),
                                          'path_unknown': bool(verdict.get('width_unknown'))})
        report['required_width_unknown'] = width_unknown
        standing = score.Standing.of_route(critical['measures'], report)
        evidence = Path(destination) / 'full-standing.json'
        record = {'schema': 1, 'authority': self.descriptor().record(),
                  'physical': self._grader.verify(physical), 'final_report': report,
                  'final_measures': critical['measures'], 'preservation': preserved,
                  'owned_execution': execution}
        text = json.dumps(record, sort_keys=True, allow_nan=False, indent=2) + '\n'
        evidence.write_text(text)
        result = AuthoritativeCandidate(physical, standing, evidence)
        self._minted[id(result)] = (result, text, copy.deepcopy(standing))
        self.verify(result)
        return result

    def verify(self, candidate):
        self._verify_context()
        owned = self._minted.get(id(candidate))
        if owned is None or owned[0] is not candidate:
            raise AuthorityRefused('authority_foreign_candidate', 'candidate was not minted in this original context')
        self._grader.verify(candidate.physical)
        if candidate.evidence.read_text() != owned[1] or candidate.standing != owned[2]:
            raise AuthorityRefused('authority_candidate_changed', 'final candidate evidence changed')
        return candidate

    def compare(self, incumbent, candidate):
        self.verify(incumbent)
        self.verify(candidate)
        if incumbent.standing.validity.unmeasured or candidate.standing.validity.unmeasured:
            raise AuthorityRefused('authority_final_unmeasured', 'final checks are unmeasured; adoption is withheld')
        for result in (incumbent, candidate):
            evidence = json.loads(result.evidence.read_text())
            if evidence['final_report'].get('required_width_unknown'):
                raise AuthorityRefused('authority_required_width_unproved',
                                       'required width proof is unknown; adoption is withheld',
                                       unknown=evidence['final_report']['required_width_unknown'])
        # Default full configured phase order. Per-run explore overrides do not
        # apply to final-call acceptance.
        return score.rank(candidate.standing, incumbent.standing, self._factory._board.settings) < 0

    def publish(self, incumbent, candidate, destination):
        """Compare again, copy privately, reverify all bytes, then publish atomically."""
        chosen = candidate if self.compare(incumbent, candidate) else incumbent
        destination = Path(destination)
        if destination.exists():
            raise AuthorityRefused('authority_destination_exists', 'publication destination must be fresh')
        source = chosen.evidence.parent
        with tempfile.TemporaryDirectory(prefix='placemat-final-', dir=destination.parent) as temporary:
            temporary = Path(temporary)
            files = {p.name: _hash(p) for p in source.iterdir() if p.is_file()}
            for name in files:
                shutil.copy2(source / name, temporary / name)
            if {p.name: _hash(p) for p in temporary.iterdir()} != files:
                raise AuthorityRefused('authority_copy_changed', 'publication copy does not match verified evidence')
            self.verify(incumbent)
            self.verify(candidate)
            if {p.name: _hash(p) for p in source.iterdir() if p.is_file()} != files:
                raise AuthorityRefused('authority_publication_source_changed', 'verified publication source changed')
            temporary.rename(destination)
        return destination


_SEAL = object()


def retain(board, plan, measures, source_pcb, *, invocation, deadline_utc, context_files=()):
    return RetainedAuthorityFactory(board, plan, measures, source_pcb, tuple(context_files), invocation, deadline_utc)
