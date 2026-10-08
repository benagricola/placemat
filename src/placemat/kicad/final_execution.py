"""Optional custody hooks at the ordinary route executor's actual sites.

This does not activate a router candidate. Missing proof leaves the ordinary
routing calls and report unchanged; process cancellation always propagates.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import time

from .final_call import ProofUnavailable, file_hash, record_digest
from .final_route import FinalCopperGrader
from . import final_custody as custody


class FinalExecution:
    def __init__(self, factory, work):
        self.factory, self.work = factory, Path(work)
        self.grader = self.ledger = None
        self.contexts = {}
        self.replay_budget = self.final_call = None
        self.executor = object()
        self.read_identity = self.geometry = None
        self.refusals = (ProofUnavailable,)
        self.active = True
        try:
            try:
                from ..final_authority import RetainedAuthorityFactory, AuthorityRefused
            except ModuleNotFoundError as error:
                if error.name != 'placemat.final_authority':
                    raise
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
            constrained=dict(env,KRT_ROUTE_DEADLINE_UTC=str(self.deadline))
            # The independent original comparator capsule belongs only to the
            # final issued call; prior ordinary calls must not occupy its path.
            constrained.pop('KRT_INTERNAL_ORDINARY_GRADE_REQUEST',None)
            return constrained
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
            if getattr(self.factory, '_route_execution', None) is not None:
                raise ProofUnavailable('final_authority_execution_already_bound')
            self.factory._route_execution = self
            self.contexts = {}
            self.replay_budget = self.final_call = None
        self._optional(bind)

    def plan_calls(self, **planned):
        from . import issued_calls
        self._optional(lambda: issued_calls._executor_plan(
            self.grader, self.ledger, self.executor, **planned))

    def issue_call(self, *, _context=None, **issued):
        """Capture one actual issued call; no replay/adoption permission."""
        from . import issued_calls
        def retain():
            phase, call, wave = issued['phase'], issued['call'], issued['wave']
            destination = self.work / ('issued-p%d-c%d-w%d-input' % (phase, call, wave))
            token = issued_calls._executor_issue(
                self.grader, self.ledger, self.executor, snapshot_dir=destination, **issued)
            if _context is not None:
                self._remember_context(token, _context)
            return token
        return self._optional(retain)

    @staticmethod
    def _context_digest(ctx):
        return record_digest({'root': str(Path(ctx.router_dir).resolve()), 'script': str(ctx.script),
                              'python': str(Path(ctx.rpy).resolve()), 'env': dict(ctx.env),
                              'settings': json.loads(ctx.cfg.json()), 'layers': list(ctx.layers),
                              'clearances': str(ctx.clearances_file) if ctx.clearances_file else None})

    def _remember_context(self, token, ctx):
        if token in self.contexts:
            raise ProofUnavailable('replay_context_already_retained')
        snapshot = replace(ctx, env=dict(ctx.env), cfg=deepcopy(ctx.cfg), execution=None)
        self.contexts[token] = (snapshot, self._context_digest(snapshot))

    def contexts_for(self, budget):
        from . import issued_calls
        if (self.factory._route_execution is not self or budget is not self.replay_budget
                or self.factory._grader is not self.grader or budget.ledger is not self.ledger
                or budget.executor is not self.executor):
            raise ProofUnavailable('replay_execution_owner_mismatch')
        budget._check(self.executor)
        result = {}
        for token in self.ledger.issued:
            issued_calls.completed_record(self.grader, self.ledger, self.executor, token)
            if token not in self.contexts:
                raise ProofUnavailable('replay_original_execution_context_missing')
            ctx, digest = self.contexts[token]
            if self._context_digest(ctx) != digest:
                raise ProofUnavailable('replay_original_execution_context_changed')
            result[token] = replace(ctx, env=dict(ctx.env), cfg=deepcopy(ctx.cfg))
        return result

    def _prepare_nominal_context(self, ctx, issued, env):
        """Optional observer transport from existing planner + actual prior ledger."""
        from .final_candidate import CandidatePlanner
        from . import replay_backend
        phase, call = issued['phase'], issued['call']
        from hashlib import sha256
        raw_caps = (self.work/'replay-capability'/'stdout.json').read_bytes()
        if (record_digest(self.backend_capability) != self.backend_capability_sha
                or sha256(raw_caps).hexdigest() != self.backend_capability['stdout_sha256']):
            raise ProofUnavailable('nominal_capability_changed')
        caps = json.loads(raw_caps)
        planner = CandidatePlanner(
            authority=self.factory._authority.descriptor(), phases=self.grader._phases,
            obligations=json.loads(self.grader._obligations),
            width_receipt=json.loads(self.grader._widths), receipt_path=self.grader._receipt_path,
            complete=True, capabilities=caps)
        planner._executor_bind_prior(self.grader,self.ledger,self.executor,phase=phase,call=call)
        call_id = 'p%d-c%d-w%d' % (phase,call,issued['wave'])
        planner.note(call_id,self.ledger.call_plans[phase][0]['calls'][call]['kind'])
        command = issued['command']
        _,_,parser_argv = replay_backend._runtime(ctx,command)
        launch = command[:len(command)-len(parser_argv)]
        original = custody.require_original(self.grader)
        original_path = str(Path(self.grader._original).resolve())
        original_sha = original['read_manifest'].get(original_path)
        if original_sha is None or file_hash(original_path) != original_sha:
            raise ProofUnavailable('original_fabrication_source_unproved')
        fabrication_source = {'path': original_path, 'sha256': original_sha,
                              'custody_sha256': original['private_context_sha256']}
        prepared = planner.prepare(
            phase_index=phase,call_index=call,calls=self.ledger.call_plans[phase][0]['calls'],
            call_id=call_id,board=issued['input_board'],output=issued['output_board'],
            summary=issued['summary'],command=command,launch=launch,nets=issued['nets'],
            layers=issued['layers'],deadline_utc=self.deadline,
            original_fabrication=fabrication_source)
        if prepared == command:
            self.nominal_refusal = list(planner.refusals)
            return env
        request = planner.requests[0]
        proof = json.loads(Path(request['proof']).read_bytes())
        identity = {'proof_sha256':record_digest(proof),'call_id':call_id,
                    'deadline_utc':self.deadline,'policy_sha256':record_digest(proof['nominal_policy'])}
        context_path = self.work/'nominal-original-context.json'
        evidence_path = self.work/'nominal-original-evidence.json'
        context = dict(proof=proof,identity=identity,candidate='legacy',
                       evidence_file=str(evidence_path),failures=[])
        with context_path.open('x') as handle:
            json.dump(context,handle,sort_keys=True,allow_nan=False)
        runtime,_,_ = replay_backend._runtime(ctx,command)
        self.nominal_observation = {'runtime':runtime,'request':request,'context':str(context_path),
            'context_sha256':file_hash(context_path),'evidence':str(evidence_path),
            'proof':proof,'identity':identity}
        self.nominal_observation_sha = record_digest(self.nominal_observation)
        return dict(env,KRT_INTERNAL_FINAL_CALL_CONTEXT=str(context_path),
                    KRT_INTERNAL_FINAL_CALL_KIND='legacy',
                    KRT_INTERNAL_FINAL_CALL_PROOF=identity['proof_sha256'],
                    KRT_INTERNAL_FINAL_CALL_ID=call_id)

    def _retain_nominal_receipt(self, log):
        """Detach telemetry only after the same actual owned incumbent completed."""
        from . import issued_calls
        record = getattr(self,'nominal_observation',None)
        if record is None:
            return
        try:
            if record_digest(record) != self.nominal_observation_sha:
                raise ProofUnavailable('nominal_observer_context_changed')
            if (file_hash(record['context']) != record['context_sha256']
                    or file_hash(record['request']['proof']) != record['request']['proof_sha256']):
                raise ProofUnavailable('nominal_observer_context_changed')
            issued_calls._unchanged(record['runtime'])
            evidence = Path(record['evidence'])
            from hashlib import sha256
            raw_evidence = evidence.read_bytes()
            evidence_sha = sha256(raw_evidence).hexdigest()
            raw_log = Path(log).read_bytes()
            log_sha = sha256(raw_log).hexdigest()
            completed = []
            refused = False
            for line in raw_log.decode('utf-8').splitlines():
                if line.startswith('FINAL_CALL_EVIDENCE_REFUSED: '):
                    refused = True
                elif line.startswith('FINAL_CALL_EVIDENCE_COMPLETE: '):
                    completed.append(json.loads(line.split(': ',1)[1]))
            expected = {'schema':1,'proof_sha256':record['identity']['proof_sha256'],
                        'call_id':record['identity']['call_id'],'evidence_sha256':evidence_sha}
            if refused or len(completed)!=1 or record_digest(completed[0])!=record_digest(expected):
                raise ProofUnavailable('nominal_observer_completion_unproved')
            files = {record['context']:record['context_sha256'],
                     record['request']['proof']:record['request']['proof_sha256'],
                     str(evidence):evidence_sha,str(Path(log)):log_sha}
            record['source_files'] = dict(files)
            record['log'] = str(Path(log))
            record['detached_files'] = issued_calls._snapshot(files,self.work/'nominal-original-snapshot')
            self.nominal_observation_sha = record_digest(record)
        except (ProofUnavailable,OSError,ValueError,TypeError,KeyError) as error:
            self.nominal_refusal = [error.record() if isinstance(error,ProofUnavailable) else
                {'code':'nominal_observer_receipt_unavailable','facts':{'error':type(error).__name__}}]

    def issue_single(self, ctx, **issued):
        """Reserve before final token; unsupported proof preserves ordinary argv/env."""
        phase, call = issued['phase'], issued['call']
        final = (self.active and phase == len(self.grader._phases)-1
                 and phase < len(self.ledger.call_plans)
                 and call == len(self.ledger.call_plans[phase][0]['calls'])-1)
        if not final:
            return ctx, self.issue_call(_context=ctx, **issued)
        def prepare():
            from . import issued_calls, replay_budget
            from . import replay_backend as replay_backend
            from . import replay_capability as owned_capability
            for plan, digest in self.ledger.call_plans:
                if record_digest(plan) != digest or any(item['kind'] not in ('nets','rest','tasks','pour') for item in plan['calls']):
                    raise ProofUnavailable('replay_pipeline_scope_unproved')
            for token in self.ledger.issued:
                prior = issued_calls.completed_record(self.grader,self.ledger,self.executor,token)
                if token not in self.contexts:
                    raise ProofUnavailable('replay_original_execution_context_missing')
                prior_ctx, digest = self.contexts[token]
                if self._context_digest(prior_ctx) != digest:
                    raise ProofUnavailable('replay_original_execution_context_changed')
                replay_backend._original_effective(prior,prior_ctx,final=False)
            self.backend_capability = owned_capability.query(ctx,self.deadline,self.work/'replay-capability')
            self.backend_capability_sha=record_digest(self.backend_capability)
            # Actual completed prior calls only; final token does not exist yet.
            self.replay_budget = replay_budget._executor_reserve(self.grader,self.ledger,self.executor)
            env = dict(ctx.env, KRT_INTERNAL_ROUTE_CANDIDATE='1', KRT_ROUTE_DEADLINE_UTC=str(self.deadline),
                       KRT_INTERNAL_ORDINARY_GRADE_REQUEST=str(self.work/'ordinary-grade-original.json'))
            env.pop('KRT_INTERNAL_POCKET_WALLS',None)
            # A missing observer does not disable original cohort/pocket routing.
            try:
                env = self._prepare_nominal_context(ctx,issued,env)
            except (ProofUnavailable,OSError,ValueError,KeyError,TypeError) as error:
                self.nominal_refusal = [error.record() if isinstance(error,ProofUnavailable) else
                    {'code':'nominal_observer_unavailable','facts':{'error':type(error).__name__}}]
            candidate_ctx = replace(ctx,env=env)
            issued['environment'] = env
            token = self.issue_call(_context=candidate_ctx,**issued)
            if token is None:
                # issue_call already recorded the precise issuer refusal.
                # Preserve it instead of overwriting it with a generic wrapper.
                if not self.active:
                    return None
                raise ProofUnavailable('replay_final_call_issuance_unavailable')
            self.final_call = token
            return candidate_ctx,token
        result = self._optional(prepare)
        if result is None:
            # No backend call has been issued: disable this optional reservation.
            # Do not reopen or reuse it through another execution path.
            self.replay_budget = self.final_call = None
            self.contexts = {}
            return ctx, None
        return result

    def execute_single(self, ctx, cmd, log, what, source, output, token):
        from .phase_run import _completed_single_call
        if (not self.active or token is None or self.final_call is None
                or self.replay_budget is None or token is not self.final_call):
            return _completed_single_call(ctx,cmd,log,what,source,output,token)
        from . import replay_ordinary_completion as ordinary_completed
        self.ordinary_receipt, self.backend_eligibility = ordinary_completed.run_completed(
            self.replay_budget,token,ctx,log,
            lambda run: _completed_single_call(ctx,cmd,log,what,source,output,token,run=run))
        self._retain_nominal_receipt(log)

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
            if self.replay_budget is not None:
                self.replay_budget.seal_incumbent(self.executor)
        self._optional(seal)
