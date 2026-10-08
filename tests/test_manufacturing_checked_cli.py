"""Exercise the actual report/log capture boundary; only process execution is controlled."""
import hashlib
import json
from pathlib import Path

import pytest
from placemat.kicad.manufacturing_clearance_worker import checked_cli, verify_artifacts
from placemat.kicad.manufacturing_annular import Unproved


def producer(board, report, returncode=0):
    def execute(argv, deadline, env, cwd):
        assert argv[-2:] == [str(report), str(board)]
        assert cwd == str(board.parent)
        data = {'$schema': 'https://schemas.kicad.org/drc.v1.json',
                'coordinate_units': 'mm', 'date': 'controlled', 'ignored_checks': [],
                'included_severities': ['error', 'warning', 'exclusion'],
                'kicad_version': 'controlled', 'source': board.name,
                'violations': [], 'unconnected_items': [], 'schematic_parity': []}
        report.write_text(json.dumps(data))
        return returncode, 'owned stdout', 'owned stderr'
    return execute


@pytest.mark.parametrize('refill,save', [(False, False), (True, True)])
def test_actual_checked_cli_seals_exact_report_and_logs(tmp_path, refill, save):
    board, report = tmp_path / 'board.kicad_pcb', tmp_path / 'report.json'
    result = checked_cli(producer(board, report), 'pinned-cli', board, report,
                         1234, {}, refill=refill, save=save)
    assert result['report_sha256'] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert set(result['artifacts']) == {str(report), str(report.with_suffix('.stdout')),
                                       str(report.with_suffix('.stderr'))}
    verify_artifacts(result['artifacts'])
    assert ('--refill-zones' in result['argv']) is refill
    assert ('--save-board' in result['argv']) is save


@pytest.mark.parametrize('suffix', ['.json', '.stdout', '.stderr'])
def test_actual_checked_cli_later_artifact_mutation_refuses(tmp_path, suffix):
    board, report = tmp_path / 'board.kicad_pcb', tmp_path / 'report.json'
    result = checked_cli(producer(board, report), 'pinned-cli', board, report, 1234, {})
    report.with_suffix(suffix).write_text('changed')
    with pytest.raises(Unproved, match='earlier_measurement_artifact_changed'):
        verify_artifacts(result['artifacts'])


def test_actual_checked_cli_nonzero_preserves_logs_but_refuses(tmp_path):
    board, report = tmp_path / 'board.kicad_pcb', tmp_path / 'report.json'
    with pytest.raises(Unproved, match='floor_cli_failed'):
        checked_cli(producer(board, report, 1), 'pinned-cli', board, report, 1234, {})
    assert report.with_suffix('.stdout').read_text() == 'owned stdout'
    assert report.with_suffix('.stderr').read_text() == 'owned stderr'
