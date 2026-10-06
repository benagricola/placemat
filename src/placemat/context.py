"""Binds the Board a script declares to. `board` is the proxy the script
imports; run_script executes a script file against a bound Board."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.abc
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import threading

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


_reads: tuple | None = None         # (thread id, [paths]) while `reads` collects
_hooked = False


def _audit(event, args):
    r = _reads
    if r is not None and event == "open" and threading.get_ident() == r[0] and args and \
            isinstance(args[0], (str, bytes, os.PathLike)):
        r[1].append(os.path.abspath(os.fsdecode(args[0])))


@contextmanager
def reads():
    """The files this thread opens while inside, as a list of paths, filled in as they are opened: the script, the modules
    it imports and every file it reads (an audit hook, added once per process, sees each open)."""
    global _reads, _hooked
    if not _hooked:
        sys.addaudithook(_audit)
        _hooked = True
    previous, got = _reads, []
    _reads = (threading.get_ident(), got)
    try:
        yield got
    finally:
        _reads = previous


def _python_dir(p: str) -> str:
    """The folder of the source a .py or .pyc path is for (a .pyc under __pycache__ or under sys.pycache_prefix)."""
    if not p.endswith(".pyc"):
        return os.path.dirname(p)
    pre = sys.pycache_prefix
    if pre and p.startswith(os.path.join(pre, "")):
        return os.path.dirname(p[len(pre):])
    return os.path.dirname(os.path.dirname(p))


def inputs_digest(paths, script) -> str:
    """A digest of what `script` ran from: each file of `paths` (as `reads` collected them) by its path and content, and
    the overlay's texts while a try runs. Two runs of the same script with the same digest declared the same board, given
    the same generated board and settings (the reuse context's). Python files are counted from the folders run_script
    imports afresh each run; a module from anywhere else (placemat, a library) is read once per process."""
    import hashlib
    dirs = [str(d) for d in _import_dirs(Path(script).resolve())]
    h = hashlib.sha256()
    for p in sorted({os.path.realpath(p) for p in paths}):
        if p.endswith((".py", ".pyc")):
            here = _python_dir(p)
            if not any(here == d or here.startswith(os.path.join(d, "")) for d in dirs):
                continue
        h.update(p.encode("utf-8", "surrogateescape") + b"\0")
        try:
            with open(p, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError as e:            # gone, or a folder: what it was is still part of the digest
            h.update(("<%s>" % type(e).__name__).encode())
    for p, text in sorted((_overlay or {}).items()):
        h.update(b"overlay\0" + p.encode("utf-8", "surrogateescape") + b"\0" + text.encode("utf-8", "surrogateescape"))
    return h.hexdigest()


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
