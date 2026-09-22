"""Reads a PDF through mupdf and poppler: how many pages, the text, the text
with its boxes, the drawing's paths, and a render of one page.

Nothing here decides what a page is about - that is `datasheet.py`, which is
pure and takes this module's values."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from ..datasheet import DrawPath, TextRun
from ..geometry import Transform
from ..values import Box


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


def _stext(path, page: int) -> str:
    return _run(["mutool", "draw", "-F", "stext", "-o", "-", "-i", str(path), str(page)],
                "reading positioned text", path)


def text_runs(path, page: int) -> tuple:
    """Every line of text on the page with its box. mutool's stext is valid
    XML, so it is parsed rather than matched: a character comes back as
    `c="&#x3a6;"` and only a parser decodes that correctly."""
    root = ET.fromstring(_stext(path, page))
    out = []
    for line in root.iter("line"):
        text = "".join(c.get("c", "") for c in line.iter("char"))
        if not text.strip():
            continue
        bb = [float(v) for v in line.get("bbox", "0 0 0 0").split()]
        out.append(TextRun(page, text, Box(bb[0], bb[1], bb[2], bb[3])))
    return tuple(out)


_POINT_TAGS = ("moveto", "lineto")


def _transform_of(el) -> Transform:
    """mutool writes `transform="a b c d e f"` on every path and the points
    inside it are in the space that matrix maps from. A real datasheet scales
    by 0.12 and rotates, so this is not decoration."""
    raw = el.get("transform")
    if not raw:
        return Transform()
    a, b, c, d, e, f = (float(v) for v in raw.split())
    return Transform(a=a, b=b, c=c, d=d, tx=e, ty=f)


def draw_paths(path, page: int) -> tuple:
    """Every filled or stroked path on the page, measured in page space."""
    text = _run(["mutool", "draw", "-F", "trace", "-o", "-", "-i", str(path), str(page)],
                "reading the drawing", path)
    out = []
    for el in ET.fromstring(text).iter():
        if el.tag not in ("fill_path", "stroke_path"):
            continue
        t = _transform_of(el)
        pts = [t.apply((float(p.get("x")), float(p.get("y"))))
               for p in el.iter() if p.tag in _POINT_TAGS]
        if len(pts) < 2:
            continue
        xs = {round(x, 2) for x, _ in pts}
        ys = {round(y, 2) for _, y in pts}
        out.append(DrawPath(page, Box.of_points(pts), points=len(pts),
                            rect=len(xs) == 2 and len(ys) == 2 and len(pts) <= 6,
                            filled=el.tag == "fill_path"))
    return tuple(out)
