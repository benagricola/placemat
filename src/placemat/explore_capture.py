"""Exact capture custody for private explore variant inputs."""
from pathlib import Path
import hashlib

from .pinmap_common import CandidateRefused


def _sha(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def copy_capture(source, destination, *, explicit=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    try:
        original = _sha(source)
    except OSError as error:
        raise CandidateRefused('explore_capture_unreadable', 'source routing capture cannot be read',
                               path=str(source), reason=str(error)) from error
    if explicit and original is None:
        raise CandidateRefused('explore_capture_missing', 'explicit routing capture is missing', path=str(source))
    existing = _sha(destination)
    if destination.exists() and existing != original:
        raise CandidateRefused('explore_capture_destination_mismatch', 'variant contains different capture bytes',
                               path=str(destination))
    if original is None:
        if destination.exists():
            raise CandidateRefused('explore_capture_destination_mismatch',
                                   'variant capture does not preserve original absence')
    elif not destination.exists():
        try:
            content = source.read_bytes()
        except OSError as error:
            raise CandidateRefused('explore_capture_unreadable', 'source routing capture cannot be read',
                                   path=str(source), reason=str(error)) from error
        destination.write_bytes(content)
    receipt = {'source': str(source), 'destination': str(destination), 'sha256': original, 'explicit': explicit}
    verify_capture(receipt)
    return receipt


def verify_capture(receipt):
    for key in ('source', 'destination'):
        path = Path(receipt[key])
        if _sha(path) != receipt['sha256'] or (receipt['sha256'] is None and path.exists()):
            raise CandidateRefused('explore_capture_changed', 'source or copied capture changed', path=str(path))


def prepare(source_pcb, variant_pcb, explicit=None):
    """Use only the requested capture, or the actual source PCB's sidecar."""
    try:
        from .capture_nets import SIDECAR
    except ImportError:
        if explicit is not None:
            raise CandidateRefused('explore_capture_unavailable', 'requested capture reader is unavailable')
        return None
    source = Path(explicit) if explicit is not None else Path(source_pcb).with_name(SIDECAR)
    return copy_capture(source, Path(variant_pcb).with_name(SIDECAR), explicit=explicit is not None)
