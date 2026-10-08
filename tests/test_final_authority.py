"""Optional full authority requires privately retained execution custody."""
import time

import pytest

from placemat.final_authority import AuthorityRefused, retain
from tests.test_pinmap_common import scene
from tests.test_pinmap_written import _source


def factory(tmp_path, **overrides):
    board, plan, _, _ = scene()
    values = dict(invocation={}, deadline_utc=time.time() + 60)
    values.update(overrides)
    return retain(board, plan, {}, _source(tmp_path), **values)


@pytest.mark.parametrize('deadline', [True, float('inf'), 0])
def test_unavailable_absolute_deadline_refuses(tmp_path, deadline):
    with pytest.raises(AuthorityRefused) as error:
        factory(tmp_path, deadline_utc=deadline)
    assert error.value.code == 'authority_deadline_unavailable'


def test_completion_without_actual_bound_executor_is_unavailable(tmp_path):
    value = factory(tmp_path)
    with pytest.raises(AuthorityRefused) as error:
        value.completed_authority()
    assert error.value.code == 'authority_completion_unavailable'


def test_changed_original_source_refuses_without_native_read(tmp_path):
    value = factory(tmp_path)
    value._source.write_text('changed source')
    with pytest.raises(AuthorityRefused) as error:
        value.completed_authority()
    assert error.value.code == 'authority_original_input_changed'
