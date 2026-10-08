"""Retained original physical route contract for private final-copper grading.

This is the physical half of grading, not the full Standing authority. The
integrated adapter must additionally read final placement and critical checks.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .final_call import ProofUnavailable, file_hash, record_digest


@dataclass(frozen=True)
class FinalCopperResult:
    report: object
    receipt: dict


class FinalCopperGrader:
    """Retain source identities and frozen obligations before considering a candidate.

    A candidate can supply copper only. Source rule/baseline changes invalidate
    this context; neither candidate reports nor candidate-derived selections
    can replace its original obligations and width policy.
    """
    def __init__(self, *, original, cleanup_input, rules, baseline_drc, obligations,
                 phases, width_receipt, cfg, counted, open_before, chosen_pours, template=None,
                 invocation=None, width_receipt_path=None):
        self._original = Path(original)
        self._cleanup_input = Path(cleanup_input)
        self._rules = Path(rules)
        self._baseline = Path(baseline_drc)
        paths = [self._original, self._cleanup_input, self._baseline]
        paths += [self._rules.with_suffix(ext) for ext in ('.kicad_pro', '.kicad_dru')]
        self._inputs = {str(path): file_hash(path) if path.is_file() else None for path in paths}
        self._receipt_path = Path(width_receipt_path) if width_receipt_path is not None else None
        if self._receipt_path is not None:
            try:
                receipt_bytes = self._receipt_path.read_bytes()
                actual_receipt = json.loads(receipt_bytes)
                self._inputs[str(self._receipt_path)] = hashlib.sha256(receipt_bytes).hexdigest()
            except (OSError, ValueError, UnicodeError) as error:
                raise ProofUnavailable('width_receipt_unavailable') from error
            if actual_receipt != width_receipt:
                raise ProofUnavailable('width_receipt_mismatch')
        if self._inputs[str(self._rules.with_suffix('.kicad_pro'))] is None:
            raise ProofUnavailable('missing_input_rules')
        self._obligations = json.dumps(obligations, sort_keys=True, allow_nan=False)
        self._widths = json.dumps(width_receipt, sort_keys=True, allow_nan=False)
        self._phases = tuple(deepcopy(phases))
        self._cfg = deepcopy(cfg)
        self._counted = frozenset(counted)
        self._open_before = dict(open_before)
        self._chosen_pours = frozenset(chosen_pours)
        self._template = deepcopy(template)
        self._minted = {}
        source_contract = {'original': file_hash(self._original), 'cleanup_input': file_hash(self._cleanup_input),
                           'baseline_drc': file_hash(self._baseline),
                           'rules': {ext: self._inputs[str(self._rules.with_suffix(ext))]
                                     for ext in ('.kicad_pro', '.kicad_dru')}}
        self._semantic_contract = {'obligations': json.loads(self._obligations),
                                              'width_authority': json.loads(self._widths),
                                              'phases': [phase.key() for phase in self._phases],
                                              'settings': json.loads(self._cfg.json()),
                                              'source_inputs': source_contract,
                                              'counted': sorted(self._counted), 'open_before': self._open_before,
                                              'chosen_pours': sorted(self._chosen_pours)}
        self._semantic_contract['invocation'] = json.loads(json.dumps(invocation, sort_keys=True, allow_nan=False))
        self._semantic_contract['width_receipt_sha256'] = (self._inputs[str(self._receipt_path)]
                                                          if self._receipt_path is not None else None)
        self._contract_sha256 = record_digest(self._semantic_contract)

    @property
    def contract_sha256(self):
        return self._contract_sha256

    def binding(self):
        """Detached context for the real retained adapter's original-intent validation."""
        self._unchanged()
        return {'contract_sha256': self.contract_sha256, 'contract': deepcopy(self._semantic_contract),
                'paths': {'original': str(self._original), 'cleanup_input': str(self._cleanup_input),
                          'rules': str(self._rules), 'baseline_drc': str(self._baseline),
                          'width_receipt': str(self._receipt_path) if self._receipt_path is not None else None}}

    def bind_execution(self, report):
        """Retain the executor's actual completed incumbent diagnostics once."""
        if self._template is not None:
            raise ProofUnavailable('execution_already_bound')
        if report.asked != json.loads(self._obligations) or len(report.phases) != len(self._phases):
            raise ProofUnavailable('execution_contract_mismatch')
        self._unchanged()
        self._template = deepcopy(report)

    def _unchanged(self):
        for raw, expected in self._inputs.items():
            path = Path(raw)
            actual = file_hash(path) if path.is_file() else None
            if actual != expected:
                raise ProofUnavailable('original_grading_input_changed', path=raw)

    def regrade(self, raw_board, destination, *, candidate_summary=None):
        """Finalize a fresh owned artifact and remeasure every original physical obligation."""
        from . import route
        self._unchanged()
        if self._template is None:
            raise ProofUnavailable('completed_incumbent_unavailable')
        destination = Path(destination)
        destination.mkdir(exist_ok=False, parents=True)
        raw_board = Path(raw_board)
        raw_hash = file_hash(raw_board)
        summary_hash = file_hash(candidate_summary) if candidate_summary is not None else None
        output, drc_path = destination / 'routed.kicad_pcb', destination / 'drc_after.json'
        cleanup, after = route.finalize_copper(raw_board, output, self._cleanup_input, self._rules, drc_path)
        by_net = route._violations_by_net(json.loads(drc_path.read_text()))
        open_after = {net: value for net, value in after.open_nets.items() if net not in self._counted}
        score = route.score(self._open_before, open_after, set(by_net) - self._counted)
        report = deepcopy(self._template)
        report.execution_provenance = {
            'kind': 'saved_copper_physical_regrade',
            'seconds_log_stage_widths_and_outcomes': 'incumbent_execution_diagnostics',
            'valid_and_invalid_reason': 'original_placement_baseline',
            'final_phase_drc_and_copper_metrics': 'fresh_saved_board_measurements',
            'candidate_summary_sha256': summary_hash}
        report.routed_pcb, report.work, report.record = output, destination, ''
        report.closure, report.closure_clean = round(score.closure, 4), round(score.closure_clean, 4)
        report.open_after, report.open_nets, report.shorted = sum(open_after.values()), dict(sorted(open_after.items())), score.shorted
        report.drc_after, report.dangling_removed = after.by_type, cleanup.record()
        report.violations = {net: by_net[net] for net in score.shorted}
        report.keepout_breaches = [breach for breach in route.router_breaches(self._original, output)
                                   if not route.own_pour_breach(breach, self._chosen_pours)]
        route.recheck_final_phases(report, json.loads(self._obligations), self._phases,
                                  json.loads(self._widths), output, drc_path, after, self._cfg)
        report.drc_new = route.new_error_count(self._baseline, drc_path, after.is_real)
        report.vias, report.track_mm, report.segments = route.routed_copper(self._original, output)
        self._unchanged()
        if file_hash(raw_board) != raw_hash:
            raise ProofUnavailable('candidate_input_changed')
        if candidate_summary is not None and file_hash(candidate_summary) != summary_hash:
            raise ProofUnavailable('candidate_summary_changed')
        report_path = destination / 'route.json'
        report_path.write_text(json.dumps(report.as_dict(), sort_keys=True, indent=2) + '\n')
        receipt = {'schema': 1, 'contract_sha256': self.contract_sha256,
                   'original_inputs': dict(self._inputs), 'raw_board_sha256': raw_hash,
                   'execution_provenance': deepcopy(report.execution_provenance),
                   'outputs': {path.name: file_hash(path) for path in
                               (output, output.with_suffix('.kicad_pro'), drc_path, report_path)},
                   'width_authority_sha256': record_digest(json.loads(self._widths)),
                   'full_standing': 'requires_retained_integrated_adapter'}
        custom = output.with_suffix('.kicad_dru')
        receipt['outputs'][custom.name] = file_hash(custom) if custom.is_file() else None
        evidence = destination / 'physical_grade.json'
        evidence.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
        result = FinalCopperResult(report, receipt)
        self._minted[id(result)] = (result, deepcopy(receipt), destination, raw_board, candidate_summary,
                                   file_hash(evidence), deepcopy(report))
        return result

    def verify(self, result):
        """Adoption boundary: accept only unchanged outputs minted by this retained context.

        The integrated adapter must call this immediately before comparison and
        publication, alongside its own final critical/intent evidence checks.
        """
        self._unchanged()
        owned = self._minted.get(id(result))
        if owned is None or owned[0] is not result:
            raise ProofUnavailable('foreign_physical_grade')
        _, receipt, destination, raw_board, summary, evidence_hash, report_snapshot = owned
        evidence = destination / 'physical_grade.json'
        if not evidence.is_file() or file_hash(evidence) != evidence_hash:
            raise ProofUnavailable('physical_grade_evidence_changed')
        if result.report != report_snapshot:
            raise ProofUnavailable('physical_grade_report_changed')
        if result.receipt != receipt:
            raise ProofUnavailable('physical_grade_receipt_changed')
        for name, expected in receipt['outputs'].items():
            path = destination / name
            actual = file_hash(path) if path.is_file() else None
            if actual != expected:
                raise ProofUnavailable('physical_grade_output_changed', file=name)
        serialized = json.dumps(result.report.as_dict(), sort_keys=True, indent=2) + '\n'
        if hashlib.sha256(serialized.encode()).hexdigest() != receipt['outputs']['route.json']:
            raise ProofUnavailable('physical_grade_report_changed')
        if file_hash(raw_board) != receipt['raw_board_sha256']:
            raise ProofUnavailable('candidate_input_changed')
        if summary is not None and file_hash(summary) != receipt['execution_provenance']['candidate_summary_sha256']:
            raise ProofUnavailable('candidate_summary_changed')
        return deepcopy(receipt)
