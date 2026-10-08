"""Executor evidence for an optional final-call escape candidate.

This module never certifies router flags or widths. The router validates the
literal issued vector with its own parser and policy. A complete-board authority
is required; an unavailable authority preserves ordinary router behavior.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import time
from types import MappingProxyType

FINALIZATION = ('remove_guards', 'refill_zones', 'remove_dangling_router_copper',
                'original_rules_drc', 'phase_recheck', 'critical_checks')
CALL_KINDS = frozenset(('single', 'connections', 'bus'))
WORK_KINDS = CALL_KINDS | frozenset(('pairs', 'pour', 'tuning'))


class ProofUnavailable(ValueError):
    """No candidate proof; callers retain the ordinary two-slot policy."""

    def __init__(self, code, **facts):
        self.code, self.facts = code, facts
        super().__init__(code)

    def record(self):
        return {'code': self.code, 'facts': dict(self.facts)}


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ProofUnavailable('invalid_identity')
    return value


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_digest(value):
    """Version-one semantic receipt hash, shared with KRT final_escape.py."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class StandingAuthority:
    """Receipt of the integrated writer/read/check/full Standing authority.

    A descriptor alone is not an adopter. The executor must retain its matching
    authority object and grade both finalized boards before publishing a change.
    """
    contract_sha256: str
    settings_sha256: str
    check_context_sha256: str
    adapter_sha256: str

    def record(self):
        return {'schema': 1, 'available': True,
                **{name: _hash(getattr(self, name)) for name in (
                    'contract_sha256', 'settings_sha256', 'check_context_sha256', 'adapter_sha256')}}


@dataclass(frozen=True)
class CopperWork:
    id: str
    kind: str

    def record(self):
        if not isinstance(self.id, str) or not self.id or not isinstance(self.kind, str) or self.kind not in WORK_KINDS:
            raise ProofUnavailable('invalid_copper_work')
        return {'id': self.id, 'kind': self.kind}


@dataclass(frozen=True)
class Terminal:
    ref: str
    pad: str

    def record(self):
        if not isinstance(self.ref, str) or not self.ref or not isinstance(self.pad, str) or not self.pad:
            raise ProofUnavailable('invalid_terminal')
        return {'ref': self.ref, 'pad': self.pad}


@dataclass(frozen=True)
class RequiredJoin:
    net: str
    start: Terminal
    end: Terminal
    widths: tuple[tuple[str, float], ...]

    def __post_init__(self):
        if (not isinstance(self.widths, (tuple, list)) or any(not isinstance(pair, (tuple, list))
                or len(pair) != 2 or not isinstance(pair[0], str) or isinstance(pair[1], bool)
                or not isinstance(pair[1], (float, int)) or not math.isfinite(pair[1]) or pair[1] <= 0
                for pair in self.widths)):
            raise ProofUnavailable('invalid_terminal_widths')
        object.__setattr__(self, 'widths', tuple((layer, float(width)) for layer, width in self.widths))

    def record(self, scope):
        if self.net not in scope.nets or not isinstance(self.start, Terminal) or not isinstance(self.end, Terminal):
            raise ProofUnavailable('unselected_terminal_obligation')
        if (not isinstance(self.widths, (tuple, list)) or any(not isinstance(pair, (tuple, list))
                or len(pair) != 2 or not isinstance(pair[0], str) or isinstance(pair[1], bool)
                or not isinstance(pair[1], (float, int)) or not math.isfinite(pair[1]) or pair[1] <= 0
                for pair in self.widths)):
            raise ProofUnavailable('invalid_terminal_widths')
        widths = dict(self.widths)
        if len(widths) != len(self.widths) or set(widths) != set(scope.layers):
            raise ProofUnavailable('invalid_terminal_widths')
        start, end = self.start.record(), self.end.record()
        if start == end:
            raise ProofUnavailable('invalid_terminal_obligation')
        record = {'net': self.net, 'from': start, 'to': end, 'widths': widths}
        if scope.kind == 'connections':
            record['task_sha256'] = record_digest(record)
        return record


@dataclass(frozen=True)
class CallScope:
    id: str
    kind: str
    routing_flags: tuple[str, ...]
    nets: tuple[str, ...]
    layers: tuple[str, ...]
    tasks_sha256: str | None = None
    bus_groups: tuple[tuple[str, ...], ...] = ()
    pair_owned_nets: tuple[str, ...] = ()
    obligations: tuple[RequiredJoin, ...] = ()

    def __post_init__(self):
        self.record()
        for name in ('routing_flags', 'nets', 'layers', 'pair_owned_nets', 'obligations'):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, 'bus_groups', tuple(tuple(group) for group in self.bus_groups))

    def record(self):
        if not isinstance(self.kind, str) or self.kind not in CALL_KINDS or not isinstance(self.id, str) or not self.id:
            raise ProofUnavailable('unsupported_call')
        if not isinstance(self.routing_flags, (tuple, list)) or any(not isinstance(arg, str) for arg in self.routing_flags):
            raise ProofUnavailable('invalid_routing_vector')
        if not isinstance(self.nets, (tuple, list)) or not self.nets or any(
                not isinstance(net, str) or not net for net in self.nets) or len(set(self.nets)) != len(self.nets):
            raise ProofUnavailable('invalid_selected_scope')
        if not isinstance(self.layers, (tuple, list)) or not self.layers or any(
                not isinstance(layer, str) or not layer.endswith('.Cu') for layer in self.layers) or len(set(self.layers)) != len(self.layers):
            raise ProofUnavailable('invalid_layer_scope')
        if self.kind == 'connections' and self.tasks_sha256 is None:
            raise ProofUnavailable('missing_connection_scope')
        if self.tasks_sha256 is not None:
            _hash(self.tasks_sha256)
        if self.kind == 'bus':
            if not isinstance(self.bus_groups, (tuple, list)) or not self.bus_groups or any(not isinstance(group, (tuple, list)) or not group or any(
                    not isinstance(net, str) or not net for net in group) or len(set(group)) != len(group)
                    for group in self.bus_groups):
                raise ProofUnavailable('missing_bus_scope')
            members = [net for group in self.bus_groups for net in group]
            if len(set(members)) != len(members) or set(members) != set(self.nets):
                raise ProofUnavailable('invalid_bus_scope')
        elif self.bus_groups:
            raise ProofUnavailable('unsupported_bus_scope')
        if not isinstance(self.pair_owned_nets, (tuple, list)) or any(not isinstance(net, str) or not net for net in self.pair_owned_nets):
            raise ProofUnavailable('invalid_pair_scope')
        if set(self.pair_owned_nets) & set(self.nets):
            raise ProofUnavailable('pair_owned_scope')
        if not isinstance(self.obligations, (tuple, list)) or not self.obligations or any(
                not isinstance(obligation, RequiredJoin) for obligation in self.obligations):
            raise ProofUnavailable('missing_terminal_obligations')
        obligations = [obligation.record(self) for obligation in self.obligations]
        return {'id': self.id, 'kind': self.kind, 'routing_flags': list(self.routing_flags),
                'nets': list(self.nets), 'layers': list(self.layers), 'tasks_sha256': self.tasks_sha256,
                'bus_groups': [list(group) for group in self.bus_groups],
                'pair_owned_nets': list(self.pair_owned_nets), 'obligations': obligations}


@dataclass(frozen=True)
class NominalPolicy:
    receipt_sha256: str
    sources_sha256: str
    by_net: dict
    receipt: bytes = field(repr=False, compare=False, default=b'')

    def __post_init__(self):
        """Snapshot widths and bind them to the exact validated query receipt.

        The factory receives the resolver's already validated receipt; KRT still
        verifies live resolver/source identity before seeding. Hashes alone do
        not make caller-provided widths an authoritative policy.
        """
        if type(self.receipt) is not bytes:
            raise ProofUnavailable('missing_validated_nominal_receipt')
        if not isinstance(self.by_net, Mapping) or any(not isinstance(net, str) or not isinstance(widths, Mapping)
                                                     for net, widths in self.by_net.items()):
            raise ProofUnavailable('policy_unproved')
        copied = {net: dict(widths) for net, widths in self.by_net.items()}
        if any(not isinstance(layer, str) or isinstance(w, bool) or not isinstance(w, (int, float))
               or not math.isfinite(w) or w <= 0 for widths in copied.values() for layer, w in widths.items()):
            raise ProofUnavailable('policy_unproved')
        try:
            document = json.loads(self.receipt)
            sources = json.dumps(document['sources'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            if (hashlib.sha256(self.receipt).hexdigest() != self.receipt_sha256
                    or hashlib.sha256(sources).hexdigest() != self.sources_sha256):
                raise ProofUnavailable('nominal_receipt_mismatch')
            matching = [record for record in document['policies'] if all(
                record['by_net'].get(net, {}).get('status') == 'known'
                and record['by_net'][net].get('widths') == widths for net, widths in copied.items())]
            if not matching:
                raise ProofUnavailable('nominal_receipt_mismatch')
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, ProofUnavailable):
                raise
            raise ProofUnavailable('missing_validated_nominal_receipt') from error
        object.__setattr__(self, 'by_net', MappingProxyType({net: MappingProxyType(widths)
                                                          for net, widths in copied.items()}))

    @classmethod
    def from_validated_receipt(cls, path, validated, name, scope):
        if not isinstance(validated, dict) or not isinstance(validated.get('policies'), list):
            raise ProofUnavailable('missing_validated_nominal_receipt')
        try:
            raw = Path(path).read_bytes()
            saved = json.loads(raw)
        except (OSError, ValueError) as error:
            raise ProofUnavailable('unreadable_nominal_receipt') from error
        if saved != validated:
            raise ProofUnavailable('nominal_receipt_mismatch')
        if any(not isinstance(p, dict) for p in validated['policies']):
            raise ProofUnavailable('missing_validated_nominal_receipt')
        records = [p for p in validated['policies'] if p.get('name') == name]
        if len(records) != 1:
            raise ProofUnavailable('policy_scope_mismatch')
        try:
            chosen = records[0]['by_net']
            if any(chosen[net]['status'] != 'known' for net in scope.nets):
                raise ProofUnavailable('policy_unproved')
            widths = {net: chosen[net]['widths'] for net in scope.nets}
            sources = json.dumps(validated['sources'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            return cls(hashlib.sha256(raw).hexdigest(), hashlib.sha256(sources).hexdigest(), widths, raw)
        except (KeyError, TypeError) as error:
            raise ProofUnavailable('policy_scope_mismatch') from error

    def record(self, scope):
        _hash(self.receipt_sha256)
        _hash(self.sources_sha256)
        if set(self.by_net) != set(scope.nets):
            raise ProofUnavailable('policy_scope_mismatch')
        for net, widths in self.by_net.items():
            if not isinstance(widths, Mapping) or set(widths) != set(scope.layers):
                raise ProofUnavailable('policy_layer_mismatch', net=net)
            if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0
                   for w in widths.values()):
                raise ProofUnavailable('policy_unproved', net=net)
        return {'receipt_sha256': self.receipt_sha256, 'sources_sha256': self.sources_sha256,
                'by_net': {net: dict(widths) for net, widths in self.by_net.items()}}


def issued_flags(command, launch, pcb_in, pcb_out, summary):
    """Exclude only the exact owned positional transport and final JSON pair.

    No options, aliases or width precedence are interpreted here. KRT validates
    the returned literal vector with its real parser, including owned options.
    """
    command = list(command)
    prefix = list(launch) + [str(pcb_in), str(pcb_out)]
    if command[:len(prefix)] != prefix or command[-2:] != ['--json-out', str(summary)]:
        raise ProofUnavailable('unknown_command_transport')
    return tuple(command[len(prefix):-2])


def proof_of(pcb, scope, policy, work, authority, *, deadline_utc, complete_route,
             deferred_work=(), finalization=FINALIZATION, now=None):
    """Bind explicit complete-route work; unknown/later work withholds proof.

    Connection deferral must additionally be checked against the incumbent's
    actual summary by KRT before selecting the escape slot. A request never
    turns an unknown deferred outcome into a completed call.
    """
    if authority is None:
        raise ProofUnavailable('standing_authority_unavailable')
    if not isinstance(authority, StandingAuthority):
        raise ProofUnavailable('invalid_standing_authority')
    if complete_route is not True:
        raise ProofUnavailable('partial_route')
    current = time.time() if now is None else now
    if isinstance(current, bool) or not isinstance(current, (int, float)) or not math.isfinite(current):
        raise ProofUnavailable('invalid_current_time')
    if (isinstance(deadline_utc, bool) or not isinstance(deadline_utc, (int, float))
            or not math.isfinite(deadline_utc) or deadline_utc <= current):
        raise ProofUnavailable('deadline_exhausted')
    if not isinstance(work, (tuple, list)) or any(not isinstance(item, CopperWork) for item in work):
        raise ProofUnavailable('invalid_copper_work')
    ordered = [item.record() for item in work]
    if not ordered or len({item['id'] for item in ordered}) != len(ordered):
        raise ProofUnavailable('invalid_copper_work')
    if ordered[-1] != {'id': scope.id, 'kind': scope.kind}:
        raise ProofUnavailable('later_copper_work')
    if deferred_work:
        raise ProofUnavailable('deferred_copper_work')
    if tuple(finalization) != FINALIZATION:
        raise ProofUnavailable('unknown_finalization')
    pcb = Path(pcb)
    inputs = {ext: file_hash(pcb.with_suffix(ext)) if pcb.with_suffix(ext).is_file() else None
              for ext in ('.kicad_pcb', '.kicad_pro', '.kicad_dru')}
    if inputs['.kicad_pcb'] is None or inputs['.kicad_pro'] is None:
        raise ProofUnavailable('missing_input_rules')
    call_record, nominal = scope.record(), policy.record(scope)
    for obligation in call_record['obligations']:
        if obligation['widths'] != nominal['by_net'][obligation['net']]:
            raise ProofUnavailable('terminal_policy_mismatch', net=obligation['net'])
    return {'schema': 1, 'input_files': inputs, 'call': call_record,
            'nominal_policy': nominal, 'copper_work': ordered, 'deferred_work': [],
            'finalization': list(finalization), 'standing_authority': authority.record(),
            'deadline_utc': deadline_utc}


def write_proof(path, proof):
    """A fresh owned receipt only; a stale existing request is never reused."""
    with Path(path).open('x') as handle:
        handle.write(json.dumps(proof, sort_keys=True, indent=2, allow_nan=False) + '\n')
