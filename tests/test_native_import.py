"""placemat runs with no native module built: `geometry` imports it if
present and falls back to pure Python otherwise. See
docs/superpowers/specs/2026-09-24-native-core-design.md."""
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
    from placemat import geometry
    module, status = geometry._load_native()        # not a reload of geometry: that makes every class in it a new one
    assert module is None and not status.in_use


def test_placemat_native_0_forces_the_python_path(monkeypatch):
    monkeypatch.setenv("PLACEMAT_NATIVE", "0")
    from placemat import geometry
    module, status = geometry._load_native()
    assert module is None and status.reason == "disabled_by_env"


def test_native_is_the_built_module_when_present_and_not_disabled():
    pytest.importorskip("placemat_native")
    if os.environ.get("PLACEMAT_NATIVE") == "0":
        pytest.skip("PLACEMAT_NATIVE=0 is set for this run: it forces the Python path by design")
    from placemat import geometry
    module, status = geometry._load_native()
    assert module is not None and status.in_use
