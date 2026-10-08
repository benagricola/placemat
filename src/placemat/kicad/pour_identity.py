"""Literal single-net pour custody, limited to byte-identical normalization.

A graphic-to-zone or guard-removal conversion is unsupported in this first
bounded domain. This does not turn a pour call into a single-ended net call.
"""
from collections import Counter
from pathlib import Path

from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest


def normalized(source, given):
    source, given = Path(source), Path(given)
    if file_hash(source) != file_hash(given):
        raise ProofUnavailable('pour_transform_nonidentity_unproved')
    # These markers are owned by conversion/guard helpers. Existing source
    # marker custody is unsupported, even when a particular helper is a no-op.
    text = source.read_text()
    if 'placemat graphic pour' in text or 'placemat pour' in text:
        raise ProofUnavailable('pour_transform_marker_custody_unproved')
    companions = {}
    for ext in ('.kicad_pro', '.kicad_dru'):
        a, b = source.with_suffix(ext), given.with_suffix(ext)
        ah = file_hash(a) if a.is_file() else None
        bh = file_hash(b) if b.is_file() else None
        if ah != bh:
            raise ProofUnavailable('pour_transform_rules_changed')
        companions[ext] = ah
    return {'schema': 1, 'domain': 'single_net_pour_identity_normalization',
            'source_sha256': file_hash(source), 'normalized_sha256': file_hash(given),
            'original_rules': companions}


def restored(source, output, proof):
    from placemat.kicad.board_forms import protected_forms
    def refuse(reason):
        raise ProofUnavailable('pour_restoration_unproved', reason=reason)
    if file_hash(source) != proof['source_sha256']:
        raise ProofUnavailable('pour_transform_source_changed')
    fixed, zones = protected_forms(source, refuse)
    actual_fixed, actual_zones = protected_forms(output, refuse)
    if Counter(fixed) - Counter(actual_fixed) or zones != actual_zones:
        raise ProofUnavailable('pour_original_intent_changed')
    for ext, expected in proof['original_rules'].items():
        path = Path(output).with_suffix(ext)
        actual = file_hash(path) if path.is_file() else None
        if actual != expected:
            raise ProofUnavailable('pour_restored_rules_changed')
    return dict(proof, restored_sha256=file_hash(output),
                original_protected_sha256=record_digest([fixed, zones]),
                restored_protected_sha256=record_digest([actual_fixed, actual_zones]))
