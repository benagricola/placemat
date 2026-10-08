"""Source capture bytes and known absence survive private variant copying."""
from pathlib import Path

import pytest

from placemat.explore_capture import copy_capture, verify_capture
from placemat.pinmap_common import CandidateRefused


def test_copy_retains_exact_original_bytes_and_detects_both_sides_changing(tmp_path):
    source, copied = tmp_path / 'source.json', tmp_path / 'copied.json'
    data = b'{"nets": ["unchanged"], "tasks": []}\n'
    source.write_bytes(data)
    receipt = copy_capture(source, copied, explicit=True)
    assert source.read_bytes() == copied.read_bytes() == data
    copied.write_bytes(data + b' ')
    with pytest.raises(CandidateRefused) as refusal:
        verify_capture(receipt)
    assert refusal.value.code == 'explore_capture_changed'
    copied.write_bytes(data)
    source.write_bytes(data + b' ')
    with pytest.raises(CandidateRefused):
        verify_capture(receipt)


def test_default_known_absence_is_preserved_and_reverified(tmp_path):
    source, copied = tmp_path / 'absent.json', tmp_path / 'copied.json'
    receipt = copy_capture(source, copied)
    assert receipt['sha256'] is None and not copied.exists()
    source.write_text('{}')
    with pytest.raises(CandidateRefused):
        verify_capture(receipt)


def test_explicit_missing_input_refuses_without_substitution_or_destination(tmp_path):
    source, copied = tmp_path / 'requested.json', tmp_path / 'copied.json'
    (tmp_path / 'nets.layout.json').write_text('{"other": true}')
    with pytest.raises(CandidateRefused) as refusal:
        copy_capture(source, copied, explicit=True)
    assert refusal.value.code == 'explore_capture_missing'
    assert not copied.exists()


@pytest.mark.parametrize('present', [False, True])
def test_preexisting_destination_mismatch_refuses_without_overwriting(tmp_path, present):
    source, copied = tmp_path / 'source.json', tmp_path / 'copied.json'
    if present:
        source.write_bytes(b'original')
    copied.write_bytes(b'unrelated')
    with pytest.raises(CandidateRefused) as refusal:
        copy_capture(source, copied)
    assert refusal.value.code == 'explore_capture_destination_mismatch'
    assert copied.read_bytes() == b'unrelated'


def test_unreadable_explicit_source_is_structured_refusal(tmp_path, monkeypatch):
    source, copied = tmp_path / 'source.json', tmp_path / 'copied.json'
    source.write_bytes(b'original')
    original = Path.read_bytes
    def denied(path):
        if path == source:
            raise PermissionError('injected unreadable source')
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', denied)
    with pytest.raises(CandidateRefused) as refusal:
        copy_capture(source, copied, explicit=True)
    assert refusal.value.code == 'explore_capture_unreadable' and not copied.exists()
