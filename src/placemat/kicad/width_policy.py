"""Required widths resolved by the configured router, before any copper changes.

This boundary imports no router CLI. One read-only query supplies every phase's
nominal class/rule/fabrication policy; explicit connection tasks keep their own
widths. Unknown derived geometry remains uncertified.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
import time
from pathlib import Path

_REAP_SECONDS = 5.0                 # shutdown allowance, never a routing/search budget


def requests_of(phases, selections, cfg):
    """The actual single-ended and pair flag scopes, with named power requests."""
    if len(phases) != len(selections):
        raise ValueError('width policy phase/selection count mismatch')
    out = []
    prior_pairs = {}
    for phase, sel in zip(phases, selections):
        pairs = {n for pair in sel.pairs for n in pair}
        singles = set(sel.nets) | set(sel.pour_nets) | {n for bus in sel.buses for n in bus}
        task_nets = {t.net for t in sel.tasks}
        singles -= task_nets - set(sel.pour_nets)
        # Default rest is a fallback for still-open copper. A prior pair's
        # completed geometry remains governed by its pair width, rather than
        # acquiring an unrelated single-ended class width on the final board.
        if sel.rest and sel.width is None and not sel.tasks:
            inherited = {}
            for net in sorted(singles & set(prior_pairs)):
                owner, pair, args = prior_pairs[net]
                inherited.setdefault(owner, {'pairs': set(), 'nets': set(), 'args': args})
                inherited[owner]['pairs'].add(pair)
                inherited[owner]['nets'].add(net)
            for owner, group in inherited.items():
                out.append({'name': phase.name, 'kind': 'pairs', 'owner': owner,
                            'nets': sorted(group['nets']), 'pairs': [list(p) for p in sorted(group['pairs'])],
                            'layers': list(sel.layers), 'args': list(group['args']),
                            'rest_phase_args': list(phase.router_args),
                            'rest_single_args': list(cfg.route_router_args) + list(phase.router_args)})
            singles -= set(prior_pairs)
        if singles:
            power = {n: sel.width for n in singles} if sel.width else {}
            for net in sel.pour_nets:
                own = [width for task in sel.tasks if task.net == net for _, width in task.widths]
                if own and net not in power:
                    power[net] = max(own)
            out.append({'name': phase.name, 'kind': 'nets', 'nets': sorted(singles), 'layers': list(sel.layers),
                        'args': list(cfg.route_router_args) + list(phase.router_args), 'power': power})
        if pairs:
            out.append({'name': phase.name, 'kind': 'pairs', 'nets': sorted(pairs), 'pairs': [list(p) for p in sel.pairs],
                        'layers': list(sel.layers),
                        'args': list(cfg.route_pair_router_args) + list(phase.router_args)})
            for pair in sel.pairs:
                for net in pair:
                    prior_pairs[net] = phase.name, tuple(pair), tuple(cfg.route_pair_router_args) + tuple(phase.router_args)
    return out


def resolve(rpy, router_dir, pcb, phases, selections, cfg, env=None, *, timeout=None):
    """Versioned policy receipt; unavailable or malformed policy is unknown."""
    requests = requests_of(phases, selections, cfg)
    packet = {'board': str(Path(pcb).resolve()), 'requests': requests}
    contract = hashlib.sha256(json.dumps(requests, sort_keys=True).encode()).hexdigest()
    script = Path(router_dir) / 'py_router' / 'nominal_width_policy.py'

    def unknown(reason, code='unavailable'):
        return {'schema': 1, 'config_sha256': contract, 'unknown': reason, 'failure': {'code': code}, 'policies': [
            {'name': r['name'], 'kind': r['kind'], 'by_net': {
                n: {'status': 'unknown', 'widths': None, 'reason': reason} for n in r['nets']}} for r in requests]}

    if not requests:
        return {'schema': 1, 'config_sha256': contract, 'policies': []}
    if not script.is_file():
        return unknown('configured router has no nominal width policy')
    budget = float(cfg.timeout_route if timeout is None else timeout)
    if (env or {}).get('KRT_ROUTE_DEADLINE_UTC'):
        try:
            deadline = float(env['KRT_ROUTE_DEADLINE_UTC'])
            if not math.isfinite(deadline):
                raise ValueError
        except (TypeError, ValueError):
            return unknown('invalid shared router deadline', 'invalid_deadline')
        budget = min(budget, deadline - time.time())
    if not math.isfinite(budget):
        return unknown('invalid width policy timeout', 'invalid_deadline')
    if budget <= 0:
        return unknown('shared router deadline expired before width policy', 'deadline')
    try:
        proc = subprocess.Popen([str(rpy), str(script)], cwd=str(router_dir), env=dict(env) if env else None,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
    except OSError as error:
        return unknown('nominal width policy unavailable: ' + str(error))
    def terminate():
        # This read-only policy owns a separate process group. Kill its pipe
        # holders too, so a timed-out helper cannot leave communicate blocked.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            # A separately sessioned writer is outside this group's ownership.
            # Close our pipes rather than wait indefinitely for its EOF.
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
            proc.wait(timeout=_REAP_SECONDS)

    try:
        if (env or {}).get('KRT_ROUTE_DEADLINE_UTC'):
            budget = min(budget, float(env['KRT_ROUTE_DEADLINE_UTC']) - time.time())
        if budget <= 0:
            terminate()
            return unknown('shared router deadline expired while launching width policy', 'deadline')
        stdout, stderr = proc.communicate(json.dumps(packet), timeout=budget)
    except subprocess.TimeoutExpired:
        terminate()
        return unknown('nominal width policy timed out', 'timeout')
    except BaseException:
        terminate()
        raise
    if proc.returncode:
        return unknown('nominal width policy exited %d: %s' % (proc.returncode, stderr[-500:]), 'failed')
    try:
        line = next(line for line in reversed(stdout.splitlines()) if line.startswith('PLACEMAT_WIDTH_POLICY '))
        policy = json.loads(line.removeprefix('PLACEMAT_WIDTH_POLICY '))
        if not isinstance(policy, dict) or type(policy.get('schema')) is not int or policy['schema'] != 1 or policy.get('config_sha256') != contract:
            raise ValueError('policy schema/configuration mismatch')
        if policy.get('board') != packet['board']:
            raise ValueError('policy board mismatch')
        expected = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                    for path in (Path(packet['board']), Path(packet['board']).with_suffix('.kicad_pro'),
                                 Path(packet['board']).with_suffix('.kicad_dru'))}
        if policy.get('inputs') != expected:
            raise ValueError('policy input digest mismatch')
        sources = set(Path(router_dir).glob('*.py')) | set(script.parent.rglob('*.py'))
        expected_sources = {str(path.relative_to(router_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted(sources)}
        if policy.get('sources') != expected_sources:
            raise ValueError('policy source digest mismatch')
        external = policy.get('external_inputs', {})
        if not isinstance(external, dict) or any(
                hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest for path, digest in external.items()):
            raise ValueError('policy external input digest mismatch')
        records = policy['policies']
        if not isinstance(records, list) or len(records) != len(requests):
            raise ValueError('policy scope count mismatch')
        for record, request in zip(records, requests):
            if record['name'] != request['name'] or record['kind'] != request['kind']:
                raise ValueError('policy scope identity mismatch')
            if set(record['by_net']) != set(request['nets']):
                raise ValueError('policy net membership mismatch')
            for entry in record['by_net'].values():
                if entry['status'] == 'unknown':
                    if not isinstance(entry.get('reason'), str) or not entry['reason']:
                        raise ValueError('unknown policy without reason')
                    continue
                if entry['status'] != 'known' or set(entry['widths']) != set(request['layers']):
                    raise ValueError('policy layer membership mismatch')
                if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0
                       for w in entry['widths'].values()):
                    raise ValueError('invalid policy width')
        return policy
    except (KeyError, TypeError, ValueError, OSError, StopIteration) as error:
        return unknown('malformed nominal width policy: ' + str(error), 'malformed')


def apply(obligations, selections, phases, policy):
    """Attach the same requested-width policy to diagnostic and stable obligations.

    S9: a pour routes at the widest task width, but each task's obligation keeps
    its own declared widths. Ordinary fixed tasks also outrank global tuning.
    """
    if len(obligations) != len(selections) or len(selections) != len(phases):
        raise ValueError('width policy obligation/selection/phase count mismatch')
    records = {}
    for record in policy['policies']:
        for net, entry in record['by_net'].items():
            key = record['name'], net
            if key in records and records[key] != entry:
                records[key] = {'status': 'unknown', 'reason': 'selected net has conflicting pair/single width policies'}
            else:
                records[key] = entry
    out = []
    for obs, sel, phase in zip(obligations, selections, phases):
        own = []
        for obligation in obs:
            item = dict(obligation)
            if policy.get('config_sha256'):
                # Unknown policies still bind the requested impedance/flag scope;
                # two unproved but different requests are not comparable.
                item['width_policy_contract'] = policy['config_sha256']
            if not sel.tasks:
                entry = records.get((phase.name, item['net']))
                if entry is None or entry['status'] != 'known':
                    item['widths'] = None
                    item['width_policy_unknown'] = True
                    item['width_policy_reason'] = (entry or {}).get('reason', 'no width policy for selected net')
                else:
                    item['widths'] = dict(entry['widths'])
            own.append(item)
        out.append(own)
    return out


def authority(policy):
    """Cache identity without board paths or diagnostic wording."""
    return {'schema': policy['schema'], 'config_sha256': policy['config_sha256'],
            'sources': policy.get('sources', {}), 'external_inputs': sorted(policy.get('external_inputs', {}).values()),
            'policies': [{'name': record['name'], 'kind': record['kind'],
                          'by_net': {net: {'status': entry['status'], 'widths': entry.get('widths')}
                                     for net, entry in record['by_net'].items()}}
                         for record in policy['policies']]}
