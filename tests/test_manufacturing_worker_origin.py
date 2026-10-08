"""Actual owned bootstrap and source selection; no native board operation."""
import json
import os
from pathlib import Path
import time

import pytest

from placemat.kicad import manufacturing_current_measurement as measurement
from placemat.kicad.final_call import file_hash, ProofUnavailable
from placemat.kicad.final_owned_worker import _execute


def test_actual_installed_worker_ignores_competing_pythonpath_before_native_import(tmp_path):
    source = tmp_path / 'request.json'
    source.write_text(json.dumps({'request': {}, 'context': {
        'mode': 'unsupported', 'comparison_authority': False}}))
    reply = tmp_path / 'reply.json'
    worker = Path(measurement.__file__).resolve().with_name('manufacturing_worker.py')
    before = file_hash(worker)
    competing = tmp_path / 'competing' / 'placemat' / 'kicad'
    competing.mkdir(parents=True)
    (competing.parent / '__init__.py').write_text('')
    (competing / '__init__.py').write_text('')
    (competing / 'manufacturing_worker.py').write_text("raise RuntimeError('wrong_worker')\n")
    command = measurement.worker_command(source, reply, {str(worker): before})
    rc, out, err = _execute(command, time.time() + 10,
                           dict(os.environ, PYTHONPATH=str(competing.parents[1])),
                           cwd=str(tmp_path))
    assert rc != 0 and 'diagnostic_scope' in err and 'wrong_worker' not in err
    assert not reply.exists() and file_hash(worker) == before


@pytest.mark.parametrize('bound', [None, '0' * 64])
def test_missing_or_changed_worker_pin_refuses_before_owned_launch(tmp_path, bound):
    worker = Path(measurement.__file__).resolve().with_name('manufacturing_worker.py')
    runtime = {} if bound is None else {str(worker): bound}
    with pytest.raises(ProofUnavailable, match='current_measurement_worker_unbound'):
        measurement.worker_command(tmp_path / 'request', tmp_path / 'reply', runtime)


def test_wrong_imported_origin_refuses_owned_controlled_package(tmp_path, monkeypatch):
    root = tmp_path / 'src'
    package = root / 'placemat' / 'kicad'
    package.mkdir(parents=True)
    competing = tmp_path / 'other'
    competing.mkdir()
    (package.parent / '__init__.py').write_text('')
    (package / '__init__.py').write_text('__path__ = [' + repr(str(competing)) + ']\n')
    worker = package / 'manufacturing_worker.py'
    worker.write_text("def main(): raise RuntimeError('expected_worker')\n")
    (competing / 'manufacturing_worker.py').write_text("def main(): raise RuntimeError('wrong_worker')\n")
    monkeypatch.setattr(measurement, '__file__', str(package / 'manufacturing_current_measurement.py'))
    command = measurement.worker_command(tmp_path / 'request', tmp_path / 'reply',
                                         {str(worker): file_hash(worker)})
    rc, out, err = _execute(command, time.time() + 10, dict(os.environ), cwd=str(tmp_path))
    assert rc != 0 and 'manufacturing_worker_origin_changed' in err
    assert 'wrong_worker' not in err
