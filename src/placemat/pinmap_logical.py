"""Proved logical terminal roles for a written pin candidate.

This is endpoint identity evidence, not routed authority. Physical reports keep
original hashes; only the explore-owned routed authority may consume this proof
with fresh physical/width/critical evidence and the original baseline custody.
"""
from dataclasses import dataclass
import json
import weakref

from .pinmap_common import CandidateRefused
from .pinmap_written import RemapProof

_SEAL = object()
_MINTED = weakref.WeakValueDictionary()


def _terminals(pads):
    """Physical land multiplicity and one net per physical pin identity."""
    from collections import Counter
    nets = {}
    lands = Counter()
    for pad in pads:
        ref, number, net = pad[:3]
        identity = ref, number
        if identity in nets and nets[identity] != net:
            raise CandidateRefused('logical_terminal_ambiguous',
                                   'a physical pin identity belongs to multiple nets', ref=ref, pad=number)
        nets[identity] = net
        lands[identity] += 1
    return nets, lands


@dataclass(frozen=True)
class LogicalTerminals:
    """Original role -> proved final physical pin, retaining every held pin."""
    physical: RemapProof
    roles: tuple                 # (logical net, original (ref,pad), final (ref,pad))
    moved: tuple
    _seal: object

    def _verify_minted(self):
        if self._seal is not _SEAL or _MINTED.get(id(self)) is not self:
            raise CandidateRefused('logical_proof_missing', 'logical roles require a current minted physical proof')
        self.physical._verify_minted()

    def verify(self, board, plan, settings=None):
        self._verify_minted()
        self.physical.verify(board, plan, settings)

    def require_net_domain(self, board, plan, phases, settings=None):
        """Refuse physical task endpoints on a reassigned part before routing.

        The routed consumer supplies phases reconstructed from retained original
        settings; this guard does not certify caller-provided phase metadata.
        """
        self.verify(board, plan, settings)
        refs = {ref for ref, _ in self.moved}
        parts = refs | {fp.inst for fp in plan.occupancy.geometry.footprints if fp.ref in refs}
        for phase in phases:
            for connection in phase.connections:
                if connection.start.part in parts or connection.end.part in parts:
                    raise CandidateRefused("logical_numeric_endpoint_unsupported",
                                           "initial logical comparison excludes explicit endpoints on reassigned parts",
                                           phase=phase.name)

    def original_of(self, physical_endpoint):
        """Resolve a proved final endpoint; never infer an unrelated endpoint."""
        self._verify_minted()
        found = [old for _, old, new in self.roles if new == tuple(physical_endpoint)]
        if len(found) != 1:
            raise CandidateRefused('logical_endpoint_unproved', 'final endpoint lacks one proved original role',
                                   endpoint=physical_endpoint)
        return found[0]


def mint(board, plan, physical, *, settings=None):
    """Bind complete terminal bijection to an existing combined physical proof.

    The physical proof already validates the declared PinPool restrictions and
    simultaneous candidate. Same-net multiple terminals receive stable original
    roles; their final connectivity obligation remains the whole logical net.
    No baseline, phase selector, width receipt or route result is minted here.
    """
    if type(physical) is not RemapProof:
        raise CandidateRefused('logical_proof_missing', 'logical roles require a minted physical candidate')
    physical.verify(board, plan, settings)
    candidate = json.loads(physical.candidate_record)
    if candidate["validity"]["unmeasured"]:
        raise CandidateRefused("logical_critical_context_unsupported",
                               "initial logical comparison excludes unmeasured candidate checks",
                               evidence=candidate["validity"]["unmeasured"])
    source, source_lands = _terminals(physical.source_pads)
    final, final_lands = _terminals(physical.final_pads)
    if source_lands != final_lands:
        raise CandidateRefused('logical_land_membership_changed',
                               'candidate changes original physical pin lands or multiplicities')
    moving = {pin for pin in source if source[pin] != final[pin]}
    roles = [(net, pin, pin) for pin, net in source.items() if pin not in moving]
    for net in sorted(set(source.values()) | set(final.values())):
        old = sorted(pin for pin in moving if source[pin] == net)
        new = sorted(pin for pin in moving if final[pin] == net)
        if len(old) != len(new):
            raise CandidateRefused('logical_terminal_multiplicity',
                                   'candidate changes original logical terminal multiplicity', net=net)
        roles.extend((net, a, b) for a, b in zip(old, new))
    if len({old for _, old, _ in roles}) != len(source) or len({new for _, _, new in roles}) != len(final):
        raise CandidateRefused('logical_terminal_bijection', 'candidate terminal roles are not a complete bijection')
    proof = LogicalTerminals(physical, tuple(sorted(roles)), tuple(sorted(moving)), _SEAL)
    _MINTED[id(proof)] = proof
    return proof
