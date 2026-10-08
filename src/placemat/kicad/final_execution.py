"""Optional custody hooks at the ordinary route executor's actual sites.

This does not activate a router candidate. Missing proof leaves the ordinary
routing calls and report unchanged; process cancellation always propagates.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import time

from .final_call import ProofUnavailable, file_hash
from .final_route import FinalCopperGrader
from . import final_custody as custody


class FinalExecution:
    def __init__(self, factory, work):
        self.factory, self.work = factory, Path(work)
        self.grader = self.ledger = None
        self.executor = object()
        self.read_identity = self.geometry = None
        self.refusals = (ProofUnavailable,)
        self.active = True
        try:
            try:
                from ..final_authority import RetainedAuthorityFactory, AuthorityRefused
            except ImportError as error:
                raise ProofUnavailable('final_authority_adapter_unavailable') from error
            self.refusals += (AuthorityRefused,)
            if type(factory) is not RetainedAuthorityFactory:
                raise ProofUnavailable('final_authority_factory_required')
            self.deadline = getattr(factory, '_deadline_utc', None)
            if (isinstance(self.deadline, bool) or not isinstance(self.deadline, (int, float))
                    or not math.isfinite(self.deadline) or self.deadline <= time.time()):
                raise ProofUnavailable('final_authority_deadline_unavailable')
        except self.refusals as error:
            self._unavailable(error)

    def _unavailable(self, error):
        self.active = False
        record = error.record()
        try:
            (self.work / 'final_authority_unavailable.json').write_text(
                json.dumps(record, sort_keys=True, indent=2) + '\n')
        except OSError:
            # The absent completion capability still prevents any proof/export.
            # Ordinary routing retains responsibility for its own required files.
            pass

    def _optional(self, operation):
        if not self.active:
            return None
        try:
            return operation()
        except self.refusals as error:
            self._unavailable(error)
        except OSError as error:
            self._unavailable(ProofUnavailable('final_authority_input_unavailable', detail=str(error)))
        return None

    def read(self, path, read_board):
        """Exactly one native read, with an immutable byte snapshot when supported."""
        path = Path(path)
        before = self._optional(lambda: file_hash(path))
        geometry = read_board(str(path))
        if before is None:
            return geometry
        def retain():
            if file_hash(path) != before:
                raise ProofUnavailable('original_read_changed')
            snapshot = self.work / 'final-original-read.kicad_pcb'
            with snapshot.open('xb') as stream:
                stream.write(path.read_bytes())
            if file_hash(path) != before or file_hash(snapshot) != before:
                raise ProofUnavailable('original_read_snapshot_changed')
            self.geometry = deepcopy(geometry)
            self.read_identity = {'original_read_path': str(path), 'read_sha256': before,
                                  'snapshot_path': str(snapshot), 'snapshot_sha256': before}
        self._optional(retain)
        return geometry

    def environment(self, env):
        if not self.active:
            return env
        def constrain():
            inherited = env.get('KRT_ROUTE_DEADLINE_UTC')
            if inherited is not None:
                try:
                    value = float(inherited)
                except (ValueError, TypeError) as error:
                    raise ProofUnavailable('final_authority_deadline_context_mismatch') from error
                if not math.isfinite(value) or value != self.deadline:
                    raise ProofUnavailable('final_authority_deadline_context_mismatch')
            return dict(env, KRT_ROUTE_DEADLINE_UTC=str(self.deadline))
        return self._optional(constrain) or env

    def prepare(self, *, original, cleanup_input, baseline_drc, obligations, phases,
                width_receipt, cfg, counted, open_before, chosen_pours, invocation, selections):
        def bind():
            if self.geometry is None or self.read_identity is None:
                raise ProofUnavailable('original_read_snapshot_unavailable')
            self.grader = FinalCopperGrader(
                original=original, cleanup_input=cleanup_input, rules=original,
                baseline_drc=baseline_drc, obligations=obligations, phases=phases,
                width_receipt=width_receipt, cfg=cfg, counted=counted, open_before=open_before,
                chosen_pours=chosen_pours, invocation=invocation,
                width_receipt_path=self.work / 'width_policy.json')
            manifest = dict(self.grader._inputs)
            manifest[self.read_identity['snapshot_path']] = self.read_identity['snapshot_sha256']
            capture = invocation['capture']
            if capture['path'] is not None:
                manifest[capture['path']] = capture['sha256']
            try:
                baseline = json.loads(Path(baseline_drc).read_bytes())
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ProofUnavailable('original_baseline_malformed', path=str(baseline_drc)) from error
            custody._executor_register_original(
                self.grader, geometry=self.geometry, read_manifest=manifest,
                read_identity=self.read_identity,
                baseline=baseline, counted=counted,
                open_before=open_before, selections=selections, width_receipt=width_receipt,
                deadline_utc=self.deadline)
            self.factory.bind_physical(self.grader)
            self.ledger = custody._executor_begin_calls(self.grader, self.executor)
        self._optional(bind)

    def plan_calls(self, **planned):
        from . import issued_calls
        self._optional(lambda: issued_calls._executor_plan(
            self.grader, self.ledger, self.executor, **planned))

    def issue_call(self, **issued):
        """Capture one actual issued call; no replay/adoption permission."""
        from . import issued_calls
        def retain():
            phase, call, wave = issued['phase'], issued['call'], issued['wave']
            destination = self.work / ('issued-p%d-c%d-w%d-input' % (phase, call, wave))
            return issued_calls._executor_issue(
                self.grader, self.ledger, self.executor, snapshot_dir=destination, **issued)
        return self._optional(retain)

    def raw_call(self, token, returncode):
        if token is None:
            return
        from . import issued_calls
        def retain():
            identity = token.record['identity']
            destination = self.work / ('issued-p%d-c%d-w%d-raw' %
                                      (identity['phase'], identity['call'], identity['wave']))
            issued_calls._executor_raw_result(self.grader, self.ledger, self.executor, token,
                                             returncode=returncode, snapshot_dir=destination)
        self._optional(retain)

    def restored_call(self, token):
        if token is None:
            return
        from . import issued_calls
        self._optional(lambda: issued_calls._executor_restored_result(
            self.grader, self.ledger, self.executor, token))

    def phase(self, index, record, routed):
        def retain():
            paths = [Path(routed.board)]
            calls = []
            for item in routed.summaries:
                if not isinstance(item, (tuple, list)) or len(item) != 3:
                    raise ProofUnavailable('ordinary_call_summary_malformed')
                name, call_index, summary = item
                if (not isinstance(name, str) or name != record.get('name')
                        or type(call_index) is not int or call_index < 0
                        or not isinstance(summary, (str, Path)) or not str(summary)):
                    raise ProofUnavailable('ordinary_call_summary_malformed')
                paths.append(Path(summary))
                calls.append((name, call_index, str(summary)))
            paths = [path if path.is_absolute() else self.work / path for path in paths]
            outputs = {str(path): file_hash(path) for path in paths}
            custody._executor_record_phase(self.grader, self.ledger, self.executor, index,
                                          record, calls=calls, outputs=outputs)
        self._optional(retain)

    def complete(self, report):
        def seal():
            custody._executor_observe_report(self.grader, self.ledger, self.executor, report)
            paths = [report.routed_pcb, self.work / 'route.json', self.work / 'drc_after.json']
            custody._executor_seal_completed(
                self.grader, self.ledger, self.executor, report,
                report_json=self.work / 'route.json',
                outputs={str(path): file_hash(path) for path in paths})
        self._optional(seal)
