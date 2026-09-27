"""Binds the Board a script declares to. `board` is the proxy the script
imports; run_script executes a script file against a bound Board."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys

_active = None


class _BoardProxy:
    def __getattr__(self, name):
        if _active is None:
            raise RuntimeError("no board is bound: run this script with `placemat run`, "
                               "or bind a Board first")
        return getattr(_active, name)

    def __repr__(self):
        return "<placemat.board proxy -> %r>" % (_active,)


board = _BoardProxy()


@contextmanager
def bind(real):
    global _active
    previous = _active
    _active = real
    try:
        yield real
    finally:
        _active = previous


def unbind():
    global _active
    _active = None


def run_script(path, real):
    """Execute a layout script against `real`. Errors propagate with the
    script's own traceback intact."""
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("placemat_layout_script", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    # The script's own directory is importable while it runs, and so is each
    # folder above it up to the one holding the nearest placemat.toml, so
    # helpers shared by the scripts of a board's modules can live in the
    # board's folder. What it imported from them is dropped afterwards: the
    # next run reads it again.
    dirs = _import_dirs(path)
    had = set(sys.modules)
    added = [str(d) for d in dirs]
    sys.path[0:0] = added                      # innermost first
    try:
        with bind(real):
            spec.loader.exec_module(module)
    finally:
        for d in added:
            if d in sys.path:
                sys.path.remove(d)
        for name in set(sys.modules) - had:
            f = getattr(sys.modules[name], "__file__", None) or ""
            if f and any(Path(f).resolve().parent.is_relative_to(d) for d in dirs):
                del sys.modules[name]
    return module


def _import_dirs(path: Path) -> list:
    """The script's folder, then each one above it up to and including the
    one that holds the nearest placemat.toml; the script's folder alone when
    no placemat.toml is above it."""
    out = [path.parent]
    for d in path.parent.parents:
        if (out[-1] / "placemat.toml").exists():
            return out
        out.append(d)
    return [path.parent]
