"""The `board` a script imports is a proxy to the Board the runner bound."""
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
    with bind(real):
        spec.loader.exec_module(module)
    return module
