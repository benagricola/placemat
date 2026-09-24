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


def test_the_native_crate_carries_the_same_version():
    """The compiled module is built from the same tree: its version is
    placemat's, so a module left over from another release can be told."""
    cargo = ROOT / "native" / "Cargo.toml"
    if not cargo.exists():
        pytest.skip("not a source checkout: %s" % cargo)
    import re
    m = re.search(r'^version = "([^"]+)"', cargo.read_text(), re.M)
    assert m and m.group(1) == placemat.__version__


def test_a_native_module_from_another_release_is_not_used():
    """An old build could place differently after an upgrade without a word:
    placemat uses a native module only when it is its own version."""
    from placemat.geometry import _accept_native

    class Module:
        __version__ = "0.0.1"
    module, note = _accept_native(Module(), placemat.__version__)
    assert module is None and "0.0.1" in note and placemat.__version__ in note
    Module.__version__ = placemat.__version__
    module, note = _accept_native(Module(), placemat.__version__)
    assert module is not None and note == ""


def test_a_native_module_with_no_version_is_not_used():
    from placemat.geometry import _accept_native
    module, note = _accept_native(object(), placemat.__version__)
    assert module is None and "no version" in note
