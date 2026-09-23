"""placemat runs with no native module built: `geometry` imports it if
present and falls back to pure Python otherwise. See
docs/superpowers/specs/2026-09-24-native-core-design.md."""
import importlib
import os

import pytest


def test_geometry_imports_whether_or_not_the_native_module_is_built():
    import placemat.geometry  # noqa: F401 - must not raise either way


def test_native_is_none_when_the_module_is_unavailable(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name == "placemat_native":
            raise ImportError("simulated: not built")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    import placemat.geometry as geometry
    reloaded = importlib.reload(geometry)
    assert reloaded._native is None
    importlib.reload(geometry)  # restore the real state for later tests


def test_placemat_native_0_forces_the_python_path(monkeypatch):
    monkeypatch.setenv("PLACEMAT_NATIVE", "0")
    import placemat.geometry as geometry
    reloaded = importlib.reload(geometry)
    assert reloaded._native is None
    monkeypatch.delenv("PLACEMAT_NATIVE", raising=False)
    importlib.reload(geometry)  # restore


def test_native_is_the_built_module_when_present_and_not_disabled():
    pytest.importorskip("placemat_native")
    if os.environ.get("PLACEMAT_NATIVE") == "0":
        pytest.skip("PLACEMAT_NATIVE=0 is set for this run: it forces the Python path by design")
    import placemat.geometry as geometry
    importlib.reload(geometry)
    assert geometry._native is not None
