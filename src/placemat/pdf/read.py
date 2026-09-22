"""Reads a PDF through mupdf and poppler: how many pages, the text, the text
with its boxes, the drawing's paths, and a render of one page.

Nothing here decides what a page is about - that is `datasheet.py`, which is
pure and takes this module's values."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from ..datasheet import DrawPath, TextRun
from ..geometry import Transform
from ..values import Box


class PdfError(RuntimeError):
    """A PDF that cannot be read. Carries the path and what the tool said,
    because the usual cause is a file that is not a PDF at all."""


def _complaint(stderr: bytes) -> str:
    """The line that says what went wrong. mutool prints its warnings after
    the error and exits non-zero for a warning alone, so the last line is
    usually not the reason and reporting it sends a reader the wrong way."""
    lines = [l.strip() for l in stderr.decode("utf8", "replace").splitlines() if l.strip()]
    for line in lines:
        if line.lower().startswith("error"):
            return line
    return lines[-1] if lines else "nothing"


def _run(argv: list, what: str, path, expect_stdout: bool = True) -> str:
    """A PDF tool's output. A non-zero exit is only fatal when nothing came
    back with it: mutool exits 1 for `warning: ICC support is not available`
    having produced the whole trace, and 4 of the 67 datasheets measured for
    this feature do exactly that."""
    if shutil.which(argv[0]) is None:
        raise PdfError("%s is not on PATH; %s needs it" % (argv[0], what))
    r = subprocess.run(argv, capture_output=True)
    out = r.stdout.decode("utf8", "replace")
    if r.returncode != 0 and not (expect_stdout and out.strip()):
        raise PdfError("%s: %s said %s" % (path, argv[0], _complaint(r.stderr)))
    return out


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


# mutool wraps a tagged PDF's trace in <structure> and <metatext> markers and
# does not balance them, so the document as a whole is not always well-formed
# XML. Each path block is, so the blocks are cut out and parsed one at a time:
# a real parser for the attributes, and immunity to whatever encloses them.
_PATH_BLOCK = re.compile(r"<(fill|stroke)_path\b.*?</\1_path>", re.S)


def _path_elements(text: str):
    for m in _PATH_BLOCK.finditer(text):
        try:
            yield ET.fromstring(m.group(0))
        except ET.ParseError:
            continue                    # one unreadable path is not a bad page


def draw_paths(path, page: int) -> tuple:
    """Every filled or stroked path on the page, measured in page space."""
    text = _run(["mutool", "draw", "-F", "trace", "-o", "-", "-i", str(path), str(page)],
                "reading the drawing", path)
    out = []
    for el in _path_elements(text):
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


def render(path, page: int, out_dir, dpi: int = 300):
    """One page as a PNG. This is the channel that always works: a datasheet
    whose every dimension is an outlined curve still renders."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / ("%s-p%d" % (Path(path).stem, page))
    png = stem.with_suffix(".png")
    try:
        _run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
              "-singlefile", str(path), str(stem)], "rendering a page", path,
             expect_stdout=False)
    except PdfError:
        if not png.exists():            # a warning that still drew the page is not a failure
            raise
    if not png.exists():
        raise PdfError("%s: pdftoppm wrote no page %d" % (path, page))
    return png


def have_ocr() -> bool:
    """tesseract reads the outlined dimension text that carries no characters.
    It is optional: placemat needs nothing installed for the ordinary path."""
    return shutil.which("tesseract") is not None
