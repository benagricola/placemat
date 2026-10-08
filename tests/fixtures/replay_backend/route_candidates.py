"""FORK DIVERGENCE: one file-isolated repair proposal for an incomplete CLI run.

Direct batch_route callers and quick/preview/mutable-schematic calls stay legacy.
The first candidate is always legacy; complete output is never replaced. Routing
and independent grading share one wall-clock budget, including child processes.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

DEFAULT_BUDGET_S = 3600.0
ARTIFACT_SUFFIXES = ('.kicad_pcb', '.kicad_pro', '.kicad_dru', '.kicad_prl')


def closure_hint(summary):
    """Only a trigger; adoption requires a fresh grade of the shipped file."""
    if not isinstance(summary, dict):
        return None
    records = summary.get('connections')
    if records is not None:
        return sum(not r.get('joined') or r.get('status') in
                   ('failed', 'refused', 'joined_narrow', 'deferred') for r in records)
    if summary.get('status') == 'already_connected':
        return 0
    if not isinstance(summary.get('regrade'), dict):
        return None
    return (len(summary.get('failed_single') or [])
            + len(summary.get('open_single') or [])
            + max(0, (summary.get('multipoint_pads_total') or 0)
                  - (summary.get('multipoint_pads_connected') or 0)))


def prefer_pocket(legacy, pocket):
    """Fail closed on unknown checks; only a physically legal proposal competes.

    Complete legacy is retained without making a proposal. Among remaining
    candidates compare closure; quality is a tie-break only for complete boards.
    Ties always retain legacy, including equal incomplete closure.
    """
    if not legacy or not pocket or not pocket.get('known'):
        return False
    if pocket['drc'] or pocket['undersized'] or pocket['widths_unknown']:
        return False
    if not legacy.get('known'):
        return False
    if pocket['open'] < legacy['open']:
        return True
    if pocket['open'] == legacy['open'] == 0:
        if legacy['drc'] or legacy['undersized'] or legacy['widths_unknown']:
            return True
        return tuple(pocket['quality']) < tuple(legacy['quality'])
    return False


def freeze_scope(requested_scope, candidates, tasks=None):
    """Both proposals owe exactly the same requested and discovered obligations."""
    from route_summary import named_nets
    requested = sorted(set(requested_scope))
    scope = sorted(set(requested) | {net for candidate in candidates
        for net in named_nets([candidate['summary'] or {}])})
    identity = {'requested_nets': requested, 'graded_nets': scope, 'tasks': tasks}
    identity['sha256'] = hashlib.sha256(json.dumps(identity, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    return scope, identity


def child_argv(argv, args, input_file, output_file, summary_file, parser, frozen_files=None):
    """Rewrite by argparse argument positions, never by matching token values."""
    out, positional = [], 0
    i = 0
    while i < len(argv):
        token = argv[i]
        parsed = parser._parse_optional(token)
        if parsed is not None and parsed[0] is not None:
            action, flag, explicit = parsed[0], parsed[1], parsed[-1]
            count = 0
            if explicit is None:
                if action.nargs in ('*', '+'):
                    j = i + 1
                    while j < len(argv) and parser._parse_optional(argv[j]) is None:
                        j += 1
                    count = j - i - 1
                elif action.nargs == '?':
                    count = int(i + 1 < len(argv) and parser._parse_optional(argv[i + 1]) is None)
                else:
                    count = 1 if action.nargs is None else action.nargs
            elif action.nargs in ('*', '+'):
                j = i + 1
                while j < len(argv) and parser._parse_optional(argv[j]) is None:
                    j += 1
                count = j - i - 1
            if action.dest in (frozen_files or {}):
                out.extend([flag, str(frozen_files[action.dest])])
            elif flag not in ('--output', '--json-out'):
                out.extend(argv[i:i + count + 1])
            i += count + 1
            continue
        if token == '--':
            # Insert generated options before the positional-only delimiter.
            out.extend(['--output', str(output_file), '--json-out', str(summary_file), '--'])
            rest = argv[i + 1:]
            for item in rest:
                out.append(str(input_file) if positional == 0 else
                           str(output_file) if positional == 1 else item)
                positional += 1
            return out
        out.append(str(input_file) if positional == 0 else
                   str(output_file) if positional == 1 else token)
        positional += 1
        i += 1
    out.extend(['--output', str(output_file), '--json-out', str(summary_file)])
    return out


def explicit_fields(argv, parser):
    fields = set()
    for token in argv:
        if token == '--':
            break
        parsed = parser._parse_optional(token)
        if parsed is not None and parsed[0] is not None:
            fields.add(parsed[0].dest)
    return fields


def run_child(command, log, env, deadline):
    """Reap this owned process group on deadline, signal, or supervisor error."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('shared candidate deadline expired')
    with open(log, 'w', encoding='utf-8') as sink:
        proc = None
        interrupted = None
        handlers = {}

        def interrupt(signum, frame):
            nonlocal interrupted
            interrupted = signum
            # During Popen, defer the exception until we have its owned PID.
            if proc is not None:
                raise SystemExit(128 + signum)

        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                handlers[signum] = signal.signal(signum, interrupt)
            proc = subprocess.Popen(command, stdout=sink, stderr=subprocess.STDOUT,
                                    env=env, start_new_session=True)
            if interrupted is not None:
                raise SystemExit(128 + interrupted)
            return proc.wait(timeout=max(0, deadline - time.monotonic()))
        except BaseException as error:
            # A repeated interrupt must not interrupt our own kill/reap step.
            for signum in handlers:
                signal.signal(signum, signal.SIG_IGN)
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            if isinstance(error, subprocess.TimeoutExpired):
                raise TimeoutError('shared candidate deadline expired') from None
            raise
        finally:
            for signum, previous in handlers.items():
                signal.signal(signum, previous)


def load_json(path):
    try:
        with open(path, encoding='utf-8') as source:
            return json.load(source)
    except (OSError, ValueError):
        return None


def deadline_from_env(env):
    budget = float(env.get('KRT_ROUTE_BUDGET_S', DEFAULT_BUDGET_S))
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError('KRT_ROUTE_BUDGET_S must be finite and positive')
    caller = env.get('KRT_ROUTE_DEADLINE_UTC')
    if caller is not None:
        end = float(caller)
        if not math.isfinite(end):
            raise ValueError('KRT_ROUTE_DEADLINE_UTC must be finite')
        budget = min(budget, max(0, end - time.time()))
    return time.monotonic() + budget, budget


def publish(candidate, output, json_out, provenance):
    """Publish artifacts and the summary from one selected run, without splicing."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    board = candidate['board']
    summary = candidate['summary']
    replacements = []
    # Stage every payload first. Sidecars and summary publish before the board;
    # if any replacement fails, restore the complete previous artifact set.
    with ExitStack() as stack:
        def stage(destination, source=None, document=None):
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(
                prefix='.krt_publish_', dir=destination.parent)))
            backup = tmp / 'previous'
            existed = destination.exists()
            if existed:
                shutil.copy2(destination, backup)
            staged = tmp / 'new'
            if source is not None:
                shutil.copy2(source, staged)
            elif document is not None:
                staged.write_text(json.dumps(document, sort_keys=True), encoding='utf-8')
            replacements.append((destination, staged if staged.exists() else None, backup, existed))
        for suffix in ARTIFACT_SUFFIXES[1:]:
            source = board.with_suffix(suffix)
            stage(output.with_suffix(suffix), source=source if source.is_file() else None)
        if json_out and isinstance(summary, dict):
            stage(json_out, document=dict(summary, route_candidates=provenance))
        stage(output, source=board)
        touched = []
        try:
            for destination, staged, backup, existed in replacements:
                touched.append((destination, backup, existed))
                if staged is None:
                    destination.unlink(missing_ok=True)
                else:
                    os.replace(staged, destination)
        except OSError:
            for destination, backup, existed in reversed(touched):
                if existed:
                    os.replace(backup, destination)
                else:
                    destination.unlink(missing_ok=True)
            raise
    print(candidate['log'].read_text(encoding='utf-8', errors='replace'), end='')
    print('ROUTE_CANDIDATES: ' + json.dumps(provenance, sort_keys=True))


def frozen_factory_args(args, frozen_files):
    """Resolve grading defaults from the same override bytes as both children."""
    resolved = copy.copy(args)
    if 'fab_overrides' in frozen_files:
        resolved.fab_overrides = str(frozen_files['fab_overrides'])
    return resolved


def manufacturing_envelope(args, original, frozen_files):
    from fab_tiers import fab_floor_min, fab_tier_from_args, count_copper_layers_in_file
    # Freeze the permitted manufacturing envelope before either run; it
    # must never come from a candidate's rewritten project or ledger.
    tier, overrides = fab_tier_from_args(frozen_factory_args(args, frozen_files))
    floors = fab_floor_min(count_copper_layers_in_file(str(original)), tier, overrides)
    fallback = {'clearance': floors['clearance'], 'size_floors': {
                k: floors[k] for k in ('track_width', 'via_diameter', 'via_drill', 'annular')}, 'tier': tier,
                'overrides': overrides, 'source': 'original_invocation_fab_floor_min'}
    if getattr(args, 'escalation', None) == 'off':
        fallback['clearance'] = max(fallback['clearance'], args.clearance)
        fallback['source'] = 'original_invocation_no_escalation'
    return fallback


def ordinary_grade_request(args, supplied, original, board, summary, scope, task_file, fallback):
    return {'board': str(board),
                    'input': str(original), 'summary': summary, 'scope': scope,
                    'manufacturing_defaults': fallback,
                    'explicit_width': args.track_width if 'track_width' in supplied else None,
                    'connections': str(task_file) if task_file else None,
                    'power_nets': getattr(args, 'power_nets', None),
                    'power_nets_widths': getattr(args, 'power_nets_widths', None),
                    'impedance': getattr(args, 'impedance', None),
                    'clearance_unproved': bool({'clearance', 'clearance_ceiling', 'net_clearances', 'hole_to_hole_clearance', 'board_edge_clearance', 'same_net_pad_clearance'} & supplied),
                    'electrical_unproved': bool(getattr(args, 'length_match_groups', None) or getattr(args, 'time_matching', False)),
                    'via_size': args.via_size if 'via_size' in supplied else None,
                    'via_drill': args.via_drill if 'via_drill' in supplied else None}


def maybe_run_candidates(args, argv, route_file, parser, requested_scope, actual_layers=None):
    if os.environ.get('KRT_INTERNAL_ROUTE_CANDIDATE'):
        return None
    unavailable = next((reason for active, reason in (
        (os.environ.get('KRT_ROUTE_QUICK'), 'quick_route'),
        (args.preview, 'preview'), (args.skip_routing, 'skip_routing'),
        (args.schematic_dir, 'mutable_schematic')) if active), None)
    if unavailable:
        print('ROUTE_CANDIDATES: ' + json.dumps(
            {'selected': 'legacy', 'attempts': 1, 'unavailable': unavailable}))
        return None
    try:
        deadline, budget = deadline_from_env(os.environ)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    env = dict(os.environ, KRT_INTERNAL_ROUTE_CANDIDATE='1',
               KRT_INTERNAL_POCKET_WALLS='0', KRT_NO_BANNER='1')
    env.pop('REDO_MANIFEST', None)  # Parent records the original invocation once.
    provenance = {'policy': 'legacy_then_one_pocket', 'budget_s': budget,
                  'max_candidates': 2, 'attempts': 0, 'selected': 'legacy',
                  'grades': {}}
    final_context = None
    if getattr(args, 'final_call_proof', None):
        from final_escape import validate_proof, ProofRefusal, source_fingerprint
        try:
            if not getattr(args, 'candidate_artifacts', None):
                raise ProofRefusal('candidate_artifacts_missing')
            if os.path.lexists(args.candidate_artifacts):
                raise ProofRefusal('candidate_artifacts_exist')
            # Automatic/group bus ownership and mutable geometry require an
            # authoritative endpoint descriptor not supplied by this first
            # bounded implementation. Preserve the ordinary policy.
            if any(getattr(args, field, None) for field in (
                    'bus', 'bus_nets', 'swappable_nets', 'schematic_dir',
                    'can_swap_to_top_layer', 'length_match_groups', 'time_matching')):
                raise ProofRefusal('unsupported_final_call_geometry_or_scope')
            proof = json.loads(Path(args.final_call_proof).read_text(encoding='utf-8'))
            identity = validate_proof(proof, board=args.input_file, argv=argv,
                parser=parser, scope=requested_scope,
                kind='connections' if getattr(args, 'connections', None) else 'single',
                layers=args.layers or actual_layers or [], tasks=getattr(args, 'connections', None),
                pair_owned_nets=proof['call']['pair_owned_nets'])
            if proof['nominal_policy']['sources_sha256'] != source_fingerprint():
                raise ProofRefusal('nominal_source_identity')
            deadline = min(deadline, time.monotonic() + proof['deadline_utc'] - time.time())
            final_context = {'proof': proof, 'identity': identity}
            provenance['final_call'] = {'proof_sha256': identity['proof_sha256'],
                                         'adoption': 'external_full_standing_only'}
        except (ProofRefusal, OSError, ValueError, TypeError, KeyError) as error:
            provenance['final_call_refused'] = str(error)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='krt_candidates_') as root:
        root = Path(root)
        original = root / 'input' / Path(args.input_file).name
        original.parent.mkdir()
        for suffix in ARTIFACT_SUFFIXES:
            source = Path(args.input_file).with_suffix(suffix)
            if source.is_file():
                shutil.copy2(source, original.with_suffix(suffix))
        frozen_files = {}
        provenance['constraint_files'] = {}
        for field in ('connections', 'net_clearances', 'fab_overrides'):
            source = getattr(args, field, None)
            if source:
                frozen = original.parent / (field + Path(source).suffix)
                shutil.copy2(source, frozen)
                frozen_files[field] = frozen
                provenance['constraint_files'][field] = hashlib.sha256(frozen.read_bytes()).hexdigest()
        task_file = frozen_files.get('connections')
        fallback = manufacturing_envelope(args, original, frozen_files)
        provenance['manufacturing_defaults'] = fallback
        output_seed = root / 'output_seed'
        output_seed.mkdir()
        for suffix in ARTIFACT_SUFFIXES[1:]:
            source = Path(args.output_file).with_suffix(suffix)
            if source.is_file():
                shutil.copy2(source, output_seed / ('seed' + suffix))
        candidates = []
        escape_failures = []
        for slot in range(2):
            name = 'legacy' if slot == 0 else ('escape' if escape_failures else 'pocket')
            if name == 'escape':
                provenance['policy'] = 'legacy_then_one_escape_external_adoption'
            folder = root / name
            folder.mkdir()
            board = folder / Path(args.output_file).name
            for suffix in ARTIFACT_SUFFIXES[1:]:
                source = output_seed / ('seed' + suffix)
                if source.is_file():
                    shutil.copy2(source, board.with_suffix(suffix))
            summary_file, log = folder / 'summary.json', folder / 'route.log'
            if name == 'pocket':
                env['KRT_INTERNAL_POCKET_WALLS'] = '1'
            for key in ('CONTEXT', 'KIND', 'PROOF', 'ID'):
                env.pop('KRT_INTERNAL_FINAL_CALL_' + key, None)
            if final_context is not None and name in ('legacy', 'escape'):
                from final_escape import write_record
                context_path = folder / 'context.json'
                try:
                    write_record(context_path, dict(final_context, candidate=name,
                        evidence_file=str(folder / 'evidence.json'), failures=escape_failures))
                except Exception as error:
                    provenance['final_call_refused'] = 'context_write_' + type(error).__name__
                    if name != 'legacy':
                        break  # Discard this optional proposal, retain incumbent.
                    final_context = None
                    escape_failures = []
                else:
                    env['KRT_INTERNAL_FINAL_CALL_CONTEXT'] = str(context_path)
                    env['KRT_INTERNAL_FINAL_CALL_KIND'] = name
                    env['KRT_INTERNAL_FINAL_CALL_PROOF'] = final_context['identity']['proof_sha256']
                    env['KRT_INTERNAL_FINAL_CALL_ID'] = final_context['identity']['call_id']
            command = [sys.executable, str(route_file)] + child_argv(
                argv, args, original, board, summary_file, parser, frozen_files)
            provenance['attempts'] += 1
            try:
                rc = run_child(command, log, env, deadline)
            except TimeoutError as error:
                provenance['stopped'] = str(error)
                if not candidates:
                    if log.exists():
                        print(log.read_text(encoding='utf-8', errors='replace'), end='')
                    print('ROUTE_CANDIDATES: ' + json.dumps(provenance))
                    return 124
                break
            summary = load_json(summary_file)
            candidate = {'name': name, 'board': board, 'summary': summary,
                         'log': log, 'rc': rc}
            if not board.is_file():
                if not candidates:
                    print(log.read_text(encoding='utf-8', errors='replace'), end='')
                    return rc or 1
                provenance['stopped'] = 'pocket output unavailable'
                break
            if name == 'pocket' and rc:
                provenance['stopped'] = 'pocket_process_failed'
                provenance['pocket_returncode'] = rc
                break
            candidates.append(candidate)
            if name == 'legacy':
                if final_context is not None:
                    from final_escape import validate_failure, ProofRefusal
                    raw_evidence = load_json(folder / 'evidence.json')
                    evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
                    evidence_refused = not isinstance(raw_evidence, dict) or bool(evidence.get('disabled'))
                    evidence_complete = False
                    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
                        if line.startswith('FINAL_CALL_EVIDENCE_REFUSED: '):
                            try:
                                refusal = json.loads(line.split(': ', 1)[1])
                            except (ValueError, TypeError):
                                evidence_refused = True
                            else:
                                if not isinstance(refusal, dict) or refusal.get('proof_sha256') == final_context['identity']['proof_sha256']:
                                    evidence_refused = True
                        if line.startswith('FINAL_CALL_EVIDENCE_COMPLETE: '):
                            try:
                                receipt = json.loads(line.split(': ', 1)[1])
                                evidence_complete = (
                                    receipt.get('schema') == 1 and
                                    receipt.get('proof_sha256') == final_context['identity']['proof_sha256'] and
                                    receipt.get('call_id') == final_context['identity']['call_id'] and
                                    receipt.get('evidence_sha256') == hashlib.sha256(
                                        (folder / 'evidence.json').read_bytes()).hexdigest())
                            except (OSError, ValueError, TypeError, AttributeError):
                                evidence_complete = False
                    if evidence_refused:
                        provenance['final_call_refused'] = 'legacy_evidence_failed'
                    summary_record = summary if isinstance(summary, dict) else {}
                    task_records = summary_record.get('connections', [])
                    deferred = bool(summary_record.get('deferred_work') or
                                    summary_record.get('deferred_nets') or
                                    not isinstance(task_records, list) or
                                    any(not isinstance(t, dict) or t.get('status') == 'deferred'
                                        for t in task_records))
                    if deferred:
                        provenance['final_call_refused'] = 'actual_deferred_work'
                    if not evidence_complete:
                        provenance['final_call_refused'] = 'legacy_evidence_custody_unproved'
                    failures = evidence.get('nominal_taps', [])
                    for failure in ([] if deferred or evidence_refused or not evidence_complete or
                                    not isinstance(failures, list) else failures):
                        try:
                            validate_failure(failure, final_context['proof'], final_context['identity'])
                        except ProofRefusal:
                            continue
                        escape_failures.append(failure)
                hint = closure_hint(summary)
                if hint is None or hint == 0 or rc:
                    provenance['stopped'] = ('legacy_reported_scope_complete' if hint == 0
                                              else 'legacy_unmeasured_or_failed')
                    break
        selected = candidates[0]
        supplied = explicit_fields(argv, parser)
        if len(candidates) == 2 and candidates[1]['name'] == 'pocket':
            frozen_scope, scope_identity = freeze_scope(requested_scope, candidates,
                load_json(task_file) if task_file else None)
            provenance['scope'] = scope_identity
            for candidate in candidates:
                grade_file = candidate['board'].parent / 'grade.json'
                request = candidate['board'].parent / 'request.json'
                request.write_text(json.dumps(ordinary_grade_request(
                    args, supplied, original, candidate['board'], candidate['summary'],
                    frozen_scope, task_file, fallback)), encoding='utf-8')
                try:
                    rc = run_child([sys.executable, __file__, '--grade', str(request),
                                    str(grade_file)], grade_file.with_suffix('.log'),
                                   env, deadline)
                    grade = load_json(grade_file) if rc == 0 else None
                except TimeoutError as error:
                    provenance['stopped'] = str(error)
                    break
                provenance['grades'][candidate['name']] = grade
            if prefer_pocket(provenance['grades'].get('legacy'),
                             provenance['grades'].get('pocket')):
                selected = candidates[1]
        if final_context is not None:
            from final_escape import persist_artifacts, ProofRefusal
            # Pocket is the ordinary fallback when no nominal failure is
            # eligible. Its publication policy remains unchanged; only the
            # proof-bound escape proposal goes to external whole-board grade.
            if len(candidates) == 1 or candidates[1]['name'] == 'escape':
                try:
                    provenance['final_call_artifacts'] = persist_artifacts(
                        args.candidate_artifacts, final_context['proof'], final_context['identity'],
                        candidates, {'nominal_failures': escape_failures,
                                     'candidate_evidence': {c['name']: load_json(
                                         c['board'].parent / 'evidence.json') for c in candidates}})
                except (ProofRefusal, OSError, ValueError) as error:
                    provenance['final_call_artifacts_refused'] = str(error)
        provenance['selected'] = selected['name']
        provenance['elapsed_s'] = round(time.monotonic() - started, 3)
        publish(selected, args.output_file, args.json_out, provenance)
        return selected['rc']


def grade_request(request):
    """Independent final-file measurements, executed under the shared deadline."""
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / 'py_tools'))
    import board_score
    from kicad_parser import parse_kicad_pcb
    from improvement_gate import grade_nets, copper_signature
    board = parse_kicad_pcb(request['board'])
    before = parse_kicad_pcb(request['input'])
    # Manual size flags replace per-net rule floors in check_drc. Preserve
    # those original floors here; explicit width obligations are checked below.
    sizes = {}
    # The shipped project may lower its declared floors during writeback.
    # Grade final copper against frozen ORIGINAL project/rules, not that weaker
    # copy. Unknown explicit clearance maps/ceilings withhold adoption below.
    with tempfile.TemporaryDirectory(prefix='krt_original_rules_') as tmp:
        checked = Path(tmp) / Path(request['board']).name
        shutil.copy2(request['board'], checked)
        for suffix in ARTIFACT_SUFFIXES[1:]:
            original = Path(request['input']).with_suffix(suffix)
            if original.is_file():
                shutil.copy2(original, checked.with_suffix(suffix))
        from fix_kicad_drc_settings import project_copper_clearance
        original_project = load_json(Path(request['input']).with_suffix('.kicad_pro')) or {}
        # check_drc invents 0.2 when there is no declared project clearance.
        # Replace only that undeclared fallback with the identical pre-run
        # manufacturing envelope. Every original declared floor still wins.
        declared = project_copper_clearance(original_project)
        fallback = request.get('manufacturing_defaults') or {}
        from list_nets import board_default_netclass_clearance
        embedded_default = board_default_netclass_clearance(request['input'])
        bounds = [v for v in (declared, embedded_default, fallback.get('clearance'))
                  if v is not None]
        if not bounds:
            return {'known': False, 'reason': 'manufacturing_defaults_missing'}
        clearance = max(bounds)
        drc, undersized, _ = board_score.score_drc(str(root), str(checked),
                                                 clearance=clearance, sizes=sizes)
    summary = request['summary']
    if not isinstance(summary, dict):
        return {'known': False, 'reason': 'summary_missing'}
    widths_unknown = False
    if request['connections']:
        import connections
        raw = connections.read_file(request['connections'])
        records = summary.get('connections') or []
        if len(records) != len(raw):
            return {'known': False, 'reason': 'task_records_missing'}
        layers = list(dict.fromkeys(l for r in records for l in r['layers']))
        tasks = connections.resolve(raw, board, layers, 0.0)
        opened = 0
        for task in tasks:
            if task.status == 'refused':
                return {'known': False, 'reason': 'task_refused'}
            connections.measure(board, task)
            opened += not task.joined
            # A joining pour supplies no track-width proof. A narrow path can
            # be an allowed neck; without proof of that allowance, do not adopt.
            if task.joined and (not task.min_width_mm or any(
                    w < task.widths.get(l, 0.0) - 1e-6
                    for l, w in task.min_width_mm.items())):
                widths_unknown = True
        scope = {t.net for t in tasks}
    else:
        scope = set(request['scope'])
        if not scope and summary.get('status') != 'already_connected':
            return {'known': False, 'reason': 'scope_missing'}
        ids = [nid for nid, net in board.nets.items() if net.name in scope]
        if len(ids) != len(scope):
            return {'known': False, 'reason': 'scope_net_missing'}
        grades = grade_nets(board, ids)
        opened = sum(max(1, len(g['failed_pads'])) for g in grades.values() if g['broken'])
    # Explicit electrical widths differ from nominal class draw settings.
    # Netclass widths are preferences; actual rule minima were checked above
    # against the original project, including original Default-class rules.
    import fnmatch
    required = {}
    if request.get('explicit_width') is not None:
        required.update({name: request['explicit_width'] for name in scope})
    power = request.get('power_nets') or []
    power_widths = request.get('power_nets_widths') or []
    if isinstance(power, str):
        power = [power]
    if power and len(power) != len(power_widths):
        widths_unknown = True
    else:
        for patterns, width in zip(power, power_widths):
            for name in scope:
                if any(fnmatch.fnmatchcase(name, p) for p in patterns.split(',')):
                    required[name] = width
    if request.get('via_size') is not None or request.get('via_drill') is not None:
        widths_unknown = True  # Explicit via/neck proof is not implemented.
    if request.get('impedance') is not None:
        widths_unknown = True  # No impedance/neck allowance proof in this worker.
    if not request['connections']:
        for segment in board.segments:
            name = board.nets[segment.net_id].name if segment.net_id in board.nets else None
            if name in scope and not getattr(segment, 'graphic', False) and segment.width < required.get(name, 0) - 1e-6:
                widths_unknown = True
    # Preserve unrelated obligations: charge only changed outside-scope nets
    # whose actual pad connectivity worsened relative to the identical input.
    sig = copper_signature(board.segments, board.vias, lambda i: board.nets[i].name)
    old = copper_signature(before.segments, before.vias, lambda i: before.nets[i].name)
    before_ids = {n.name: i for i, n in before.nets.items()}
    for nid, net in board.nets.items():
        if net.name in scope or sig.get(net.name) == old.get(net.name):
            continue
        now = grade_nets(board, [nid])[nid]
        if not now['broken']:
            continue
        prior = grade_nets(before, [before_ids[net.name]])[before_ids[net.name]]
        opened += max(0, len(now['failed_pads']) - len(prior['failed_pads']))
    quality = board_score.quality(request['board'])
    from design_rules import DesignRules
    original_rules = DesignRules.from_project(before, request['input'])
    unproved = []
    if Path(request['input']).with_suffix('.kicad_dru').is_file():
        unproved.append('custom_clearance_rules_unproved')
    if any(getattr(pad, 'local_clearance', 0) for fp in before.footprints.values()
           for pad in fp.pads):
        unproved.append('local_clearance_overrides_unproved')
    if original_rules.unsupported() or original_rules.notes:
        unproved.append('original_rules_unsupported')
    defaults = request.get('manufacturing_defaults') or {}
    size_floors = defaults.get('size_floors') or {}
    for kind, key, item_type in (('track_width', 'track_width', 'track'),
                                ('via_diameter', 'via_diameter', 'via'),
                                ('hole_size', 'via_drill', 'via'),
                                ('annular_width', 'annular', 'via')):
        permitted = size_floors.get(key)
        if permitted is None:
            continue
        if any(value is not None and value < permitted - 1e-9
               for nid in before.nets
               for layer in before.board_info.copper_layers
               for value in [original_rules.floor(kind, nid, layer, type=item_type)]):
            unproved.append('original_size_floor_below_factory_' + key)
    if defaults.get('tier', 'auto') != 'auto' or defaults.get('overrides'):
        unproved.append('nondefault_factory_settings_unproved')
    if request.get('clearance_unproved'):
        unproved.append('explicit_clearance_unproved')
    if request.get('electrical_unproved'):
        unproved.append('length_or_time_obligation_unproved')
    known = drc.get('ran') and undersized.get('ran') and 'error' not in quality and not unproved
    return {'known': bool(known), 'unproved': unproved, 'drc': drc.get('count'),
            'undersized': undersized.get('count'), 'widths_unknown': widths_unknown,
            'open': opened, 'quality': [quality.get(k) for k in ('vias', 'copper_mm', 'segments')]}


def ordinary_scope_request(request):
    """The existing ordinary comparator's full requested/disclosed scope."""
    scope, identity = freeze_scope(request['requested_scope'], request['candidates'],
        load_json(request['connections']) if request['connections'] else None)
    return {'scope': scope, 'identity': identity}


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--ordinary-scope':
        result = ordinary_scope_request(load_json(sys.argv[2]))
        Path(sys.argv[3]).write_text(json.dumps(result, sort_keys=True), encoding='utf-8')
        sys.exit(0)
    if len(sys.argv) != 4 or sys.argv[1] != '--grade':
        sys.exit('internal grading worker: --grade REQUEST OUTPUT')
    result = grade_request(load_json(sys.argv[2]))
    Path(sys.argv[3]).write_text(json.dumps(result, sort_keys=True), encoding='utf-8')
