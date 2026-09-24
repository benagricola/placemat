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
    assert _manifest_version(path) == placemat.release(placemat.__version__)


def test_the_installed_package_reports_that_version_too():
    """The version file and the package metadata are written from the same
    tag at install: they agree unless the install is stale."""
    from importlib.metadata import version
    assert version("placemat") == placemat.__version__


def test_the_version_is_what_names_a_run():
    """The reason any of this matters: change the tool, change the run id, so
    an impact report across an upgrade has two ids to compare."""
    from placemat.report import run_id
    same = ("board.size(40, 40)", b"PCB")
    assert run_id(*same, placemat.__version__) != run_id(*same, "0.0.0")


def test_the_native_module_reports_the_release_it_was_built_from():
    """Both versions come from the git tag: placemat's through hatch-vcs, the
    module's through build.rs. They agree on the release."""
    try:
        import placemat_native
    except ImportError:
        pytest.skip("placemat_native is not built")
    assert placemat.release(placemat_native.__version__) == placemat.release(placemat.__version__)


@pytest.mark.parametrize("version, base", [("0.31.0", "0.31.0"), ("0.31.0.post2.dev0+g1a2b3c4", "0.31.0"),
                                           ("0.31.0+d20260924", "0.31.0"), ("1.2", "1.2")])
def test_a_version_s_release_is_the_tag_it_builds_on(version, base):
    assert placemat.release(version) == base


def test_the_version_is_the_checkout_s_git_tag():
    """No version is typed anywhere: the tag is it."""
    import subprocess
    try:
        tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout with a v* tag")
    assert placemat.release(placemat.__version__) == tag[1:]


def test_a_native_module_from_another_release_is_not_used():
    """An old build could place differently after an upgrade without a word:
    placemat uses a native module only when it is its own version."""
    from placemat.geometry import _accept_native

    class Module:
        __version__ = "0.0.1"
    module, note = _accept_native(Module(), "0.31.0.post2.dev0+g1a2b3c4")
    assert module is None and "0.0.1" in note
    Module.__version__ = "0.31.0"                       # built at the tag, placemat two commits on
    module, note = _accept_native(Module(), "0.31.0.post2.dev0+g1a2b3c4")
    assert module is not None and note == ""


def test_a_native_module_with_no_version_is_not_used():
    from placemat.geometry import _accept_native
    module, note = _accept_native(object(), placemat.__version__)
    assert module is None and "no version" in note
