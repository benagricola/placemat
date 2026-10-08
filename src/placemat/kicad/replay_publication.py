"""Verify complete private publication before exposing detached caller pointers."""
from copy import deepcopy
from pathlib import Path
import json
from placemat.kicad.final_call import ProofUnavailable, file_hash, record_digest
from placemat.kicad.final_worker_protocol import report_record

_MINT = object()


class PublishedRoute:
    def __init__(self, key, authority, candidate, destination, manifest, report):
        if key is not _MINT:
            raise ProofUnavailable('replay_private_publication_required')
        self._authority, self._candidate = authority, candidate
        self._destination = destination
        self._manifest = deepcopy(manifest)
        self.report = report
        self._report_sha = record_digest(report_record(report))

    def verify(self):
        self._authority.verify(self._candidate)
        actual = {path.name:file_hash(path) for path in self._destination.iterdir() if path.is_file()}
        if (record_digest(actual) != record_digest(self._manifest)
                or record_digest(report_record(self.report)) != self._report_sha):
            raise ProofUnavailable('replay_published_bundle_changed')
        return self.report


def detached(authority, candidate, published, *, ordinary_selection=None):
    authority.verify(candidate)
    original = candidate.physical.report
    source = Path(candidate.evidence).parent
    expected = {path.name:file_hash(path) for path in source.iterdir() if path.is_file()}
    published = Path(published).resolve()
    actual = {path.name:file_hash(path) for path in published.iterdir() if path.is_file()}
    if record_digest(actual) != record_digest(expected):
        raise ProofUnavailable('replay_published_bundle_changed')
    report = deepcopy(original)
    report.routed_pcb = published / Path(original.routed_pcb).name
    report.work = published
    if not report.routed_pcb.is_file():
        raise ProofUnavailable('replay_published_board_changed')
    # Keep copied route.json and all minted full-grade evidence byte-original.
    # This distinct caller record makes its relocated pointers explicit.
    caller_record = published/'caller-route.json'
    with caller_record.open('x') as stream:
        json.dump(report.as_dict(), stream, allow_nan=False, indent=2)
        stream.write('\n')
    expected[caller_record.name] = file_hash(caller_record)
    if ordinary_selection is not None:
        marker=published/'ordinary-selection.json'
        with marker.open('x') as stream:
            json.dump({'selection':ordinary_selection,'strict_adoption':False},stream,sort_keys=True,allow_nan=False)
            stream.write('\n')
        expected[marker.name]=file_hash(marker)
    result = PublishedRoute(_MINT,authority,candidate,published,expected,report)
    result.verify()
    return result
