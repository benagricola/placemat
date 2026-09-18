"""One version number for one artifact.

placemat is shipped twice - as a Python package and as a Claude Code plugin -
and each carried its own version. The package's sat at 0.2.0-dev from the
rewrite's first commit while the plugin's climbed, which mattered because
`run_id` hashes the tool version into a run's name: a frozen version meant an
upgrade never changed a run id, and the runner reported "same inputs as the
previous run, nothing to compare" across a release that changed placement.
"""
import json
from pathlib import Path

import pytest

import placemat

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = [ROOT / ".claude-plugin" / "plugin.json",
             ROOT / ".claude-plugin" / "marketplace.json"]


def _manifest_version(path: Path) -> str:
    d = json.loads(path.read_text())
    return d["version"] if "version" in d else d["metadata"]["version"]


@pytest.mark.parametrize("path", MANIFESTS, ids=[p.name for p in MANIFESTS])
def test_the_package_and_the_plugin_say_the_same_version(path):
    if not path.exists():
        pytest.skip("not a source checkout: %s" % path)
    assert _manifest_version(path) == placemat.__version__


def test_the_installed_package_reports_that_version_too():
    """pyproject reads __init__, so a bump in one place moves both. If this
    fails, the dynamic version has been replaced by a literal again."""
    from importlib.metadata import version
    assert version("placemat") == placemat.__version__


def test_the_version_is_what_names_a_run():
    """The reason any of this matters: change the tool, change the run id, so
    an impact report across an upgrade has two ids to compare."""
    from placemat.report import run_id
    same = ("board.size(40, 40)", b"PCB")
    assert run_id(*same, placemat.__version__) != run_id(*same, "0.0.0")
