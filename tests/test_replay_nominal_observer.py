"""Real hook/custody observer; controlled factory and router/native boundaries."""
import pytest
from tests.test_final_custody import context
from tests.nominal_lifecycle import completed_hook

@pytest.mark.parametrize('mode',['bound','capability_changed','unsupported','nominal_unknown','context_changed','log_changed'])
def test_actual_hook_records_final_observer(context,monkeypatch,mode):
    completed_hook(context,monkeypatch,mode)
