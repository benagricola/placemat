"""Binds the Board a script declares to. `board` is the proxy the script
imports; run_script executes a script file against a bound Board."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.abc
import importlib.machinery
import importlib.util
from pathlib import Path
import sys

_active = None
_overlay: dict | None = None        # {absolute path: text} read in place of the files on disk while a try runs (see `overlay`)


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


class _OverlayLoader(importlib.machinery.SourceFileLoader):
    """Runs a file from the text the overlay holds for it, with the real path as its file name, so the lines a traceback or a
    declaration names are the file's own."""

    def get_code(self, fullname):
        text = _overlay[str(Path(self.path).resolve())]
        return compile(text, self.path, "exec", dont_inherit=True)

    def get_source(self, fullname):
        return _overlay[str(Path(self.path).resolve())]


class _OverlayFinder(importlib.abc.MetaPathFinder):
    """A module whose file the overlay holds is loaded from the overlay: the script's helpers and the modules it imports."""

    def find_spec(self, name, path=None, target=None):
        if not _overlay:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        origin = getattr(spec, "origin", None)
        if spec is None or not origin or str(Path(origin).resolve()) not in _overlay:
            return None
        return importlib.util.spec_from_file_location(name, origin, loader=_OverlayLoader(name, origin),
                                                      submodule_search_locations=spec.submodule_search_locations)


@contextmanager
def overlay(texts):
    """Resolve with `texts` ({path: text}) in place of those files on disk: the layout script, the modules it imports and
    placemat.toml are read from them, nothing is written. The studio's try of a suggestion runs inside this."""
    global _overlay
    if not texts:
        yield
        return
    previous, finder = _overlay, _OverlayFinder()
    _overlay = {str(Path(p).resolve()): t for p, t in texts.items()}
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        _overlay = previous
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)


def overlay_text(path):
    """The overlay's text for `path`, or None where there is no overlay or it holds nothing for that file."""
    if not _overlay:
        return None
    return _overlay.get(str(Path(path).resolve()))


def read_source(path) -> str:
    """A script file's text: the overlay's, else the file on disk (`Board.source_reader`)."""
    text = overlay_text(path)
    if text is not None:
        return text
    with open(path, encoding="utf-8") as f:
        return f.read()


def run_script(path, real):
    """Execute a layout script against `real`. Errors propagate with the
    script's own traceback intact."""
    path = Path(path).resolve()
    if overlay_text(path) is not None:
        spec = importlib.util.spec_from_file_location("placemat_layout_script", str(path), loader=_OverlayLoader("placemat_layout_script", str(path)))
    else:
        spec = importlib.util.spec_from_file_location("placemat_layout_script", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    # The script's own directory is importable while it runs, and so is each
    # folder above it up to the one holding the outermost placemat.toml, so
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
    """The script's folder, then each one above it up to and including the one
    that holds the outermost placemat.toml (the project root: the first file
    settings merges); the script's folder alone when no placemat.toml is above
    it. A placemat.toml beside a module does not cut it off from the helpers in
    the folders above."""
    from .settings import _files
    found = _files(path.parent)
    if not found:
        return [path.parent]
    top = found[0].parent
    out = [path.parent]
    while out[-1] != top:
        out.append(out[-1].parent)
    return out
