"""Reads a PDF through mupdf and poppler: how many pages, the text, the text
with its boxes, the drawing's paths, and a render of one page.

Nothing here decides what a page is about - that is `datasheet.py`, which is
pure and takes this module's values."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


class PdfError(RuntimeError):
    """A PDF that cannot be read. Carries the path and what the tool said,
    because the usual cause is a file that is not a PDF at all."""


def _run(argv: list, what: str, path) -> str:
    if shutil.which(argv[0]) is None:
        raise PdfError("%s is not on PATH; %s needs it" % (argv[0], what))
    r = subprocess.run(argv, capture_output=True)
    if r.returncode != 0:
        tail = r.stderr.decode("utf8", "replace").strip().splitlines()
        raise PdfError("%s: %s said %s" % (path, argv[0], tail[-1] if tail else "nothing"))
    return r.stdout.decode("utf8", "replace")


def page_count(path) -> int:
    out = _run(["pdfinfo", str(path)], "counting pages", path)
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    raise PdfError("%s: pdfinfo named no page count" % path)


def plain_text(path, page: int | None = None) -> str:
    argv = ["pdftotext", "-layout"]
    if page is not None:
        argv += ["-f", str(page), "-l", str(page)]
    return _run(argv + [str(path), "-"], "reading text", path)
