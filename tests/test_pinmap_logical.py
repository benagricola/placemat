"""Logical role identity never authorizes arbitrary physical membership changes."""
from dataclasses import replace
import pytest
from placemat.pinmap_common import CandidateRefused
from placemat import pinmap_logical, pinmap_written
from tests.test_pinmap_common import scene
from tests.test_pinmap_written import _source


def proved(tmp_path):
    board, plan, inp, group = scene()
    physical = pinmap_written.mint(board, plan, inp, ((group.refs, group.results[0]),), _source(tmp_path))
    return board, plan, physical


def test_complete_permutation_retains_held_endpoints_and_original_net_roles(tmp_path):
    board, plan, physical = proved(tmp_path)
    proof = pinmap_logical.mint(board, plan, physical)
    proof.verify(board, plan)
    source = {p[:2]: p[2] for p in physical.source_pads}
    final = {p[:2]: p[2] for p in physical.final_pads}
    assert {old for _, old, _ in proof.roles} == set(source)
    assert {new for _, _, new in proof.roles} == set(final)
    for net, old, new in proof.roles:
        assert source[old] == final[new] == net
        assert proof.original_of(new) == old
        if old[0] != 'U1':
            assert old == new


def test_forged_stale_or_unknown_endpoint_cannot_acquire_logical_identity(tmp_path):
    board, plan, physical = proved(tmp_path)
    proof = pinmap_logical.mint(board, plan, physical)
    with pytest.raises(CandidateRefused, match='current minted'):
        replace(proof).verify(board, plan)
    with pytest.raises(CandidateRefused, match='current minted'):
        replace(proof).original_of(proof.roles[0][2])
    with pytest.raises(CandidateRefused) as error:
        proof.original_of(('UNKNOWN', '1'))
    assert error.value.code == 'logical_endpoint_unproved'
    physical.source.write_text('(changed source)')
    with pytest.raises(CandidateRefused) as error:
        proof.verify(board, plan)
    assert error.value.code == 'proof_input_changed'


def test_duplicate_or_conflicting_physical_identity_is_not_inferred():
    pad=('U1','1','A')
    with pytest.raises(CandidateRefused) as error:
        pinmap_logical._terminals((pad,('U1','1','B')))
    assert error.value.code == 'logical_terminal_ambiguous'
    nets, lands=pinmap_logical._terminals((pad,pad))
    assert nets == {('U1','1'):'A'}
    assert lands[('U1','1')] == 2


def test_partial_illegal_permutation_never_reaches_logical_mint(tmp_path):
    board, plan, inp, group=scene()
    assignment=dict(group.results[0].assign)
    assignment['A']=()
    with pytest.raises(CandidateRefused):
        physical=pinmap_written.mint(board, plan, inp,
            ((group.refs,replace(group.results[0],assign=assignment)),),_source(tmp_path))
        pinmap_logical.mint(board,plan,physical)


def test_explicit_endpoint_on_reassigned_part_is_outside_net_level_domain(tmp_path):
    from types import SimpleNamespace
    board, plan, physical=proved(tmp_path)
    proof=pinmap_logical.mint(board,plan,physical)
    endpoint=lambda part,pad:SimpleNamespace(part=part,pad=pad)
    phase=lambda start:SimpleNamespace(name='signals',connections=(SimpleNamespace(
        start=start,end=endpoint('TP1','1')),))
    for name in ('U1','u1'):
        with pytest.raises(CandidateRefused) as error:
            proof.require_net_domain(board,plan,(phase(endpoint(name,'1')),))
        assert error.value.code == 'logical_numeric_endpoint_unsupported'
    proof.require_net_domain(board,plan,(phase(endpoint('TP2','1')),))


def test_unmeasured_electrical_candidate_does_not_acquire_logical_route_proof(tmp_path):
    board,plan,inp,group=scene(fields={'Pm.I':'3A'})
    physical=pinmap_written.mint(board,plan,inp,((group.refs,group.results[0]),),_source(tmp_path))
    with pytest.raises(CandidateRefused) as error:
        pinmap_logical.mint(board,plan,physical)
    assert error.value.code == 'logical_critical_context_unsupported'


def test_physical_subclass_cannot_override_private_mint_check(tmp_path):
    board,plan,physical=proved(tmp_path)
    class Forged(pinmap_written.RemapProof):
        def verify(self,*args,**kwargs):
            pass
    from dataclasses import fields
    forged=Forged(**{field.name:getattr(physical,field.name) for field in fields(physical)})
    with pytest.raises(CandidateRefused) as error:
        pinmap_logical.mint(board,plan,forged)
    assert error.value.code == 'logical_proof_missing'
