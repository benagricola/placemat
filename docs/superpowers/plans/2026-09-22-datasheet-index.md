# Datasheet Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `placemat datasheet <pdf>` ranks every page against the four topics with the evidence that produced the ranking, and `--show` renders the page an agent should look at.

**Architecture:** `datasheet.py` is pure - it scores pages from `TextRun` and `DrawPath` values and never opens a PDF, so the scoring is pinned by tests that run anywhere. `pdf/read.py` holds every shell-out (mutool, pdftotext, pdftoppm) and returns those values, the same split as `kicad/` holds every pcbnew import.

**Tech Stack:** Python 3.12 stdlib only (`xml.etree`, `subprocess`), mupdf's `mutool`, poppler's `pdftotext`/`pdftoppm`/`pdfinfo`.

**Spec:** `docs/superpowers/specs/2026-09-22-datasheet-design.md`

## Global Constraints

- **Zero runtime dependencies.** `pyproject.toml` keeps `dependencies = []`. mutool and poppler are shelled out, exactly as `kicad-cli` is.
- **No pcbnew and no PDF tool outside its package.** `pdf/read.py` is the only module that runs a PDF tool, as `kicad/` is the only package that imports pcbnew.
- **Punctuation is plain ASCII** in every file: no em dashes, en dashes or unicode arrows.
- **Commit messages carry no reference to Claude, Anthropic or a session.**
- **A path's coordinates mean nothing without its transform.** mutool's trace emits pre-transform coordinates and a `transform="a b c d e f"` matrix; a real datasheet scales by 0.12 and rotates (`0 -.12 -.12 -0 840 593`). Every point is put through `geometry.Transform` before it is measured.
- **Never claim a number that was not sourced.** Evidence travels with every score.

## File Structure

- `src/placemat/datasheet.py` - pure. The `TextRun` and `DrawPath` values, rectangle and cluster detection, keyword tables, evidence, banding, the index and its lines.
- `src/placemat/pdf/__init__.py` - empty package marker.
- `src/placemat/pdf/read.py` - `page_count`, `plain_text`, `text_runs`, `draw_paths`, `render`, `have_ocr`, `PdfError`.
- `src/placemat/cli.py` - `cmd_datasheet` and its parser.
- `tests/test_datasheet.py` - the pure scoring, no PDF.
- `tests/test_pdf_read.py` - the readers, against PDFs the tests build with `mutool create`.
- `tests/fixtures.py` - `make_pdf(tmp_path, content)`.

---

## Task 1: A PDF the tests build themselves

**Files:**
- Create: `src/placemat/pdf/__init__.py`, `src/placemat/pdf/read.py`
- Modify: `tests/fixtures.py`, `tests/conftest.py`
- Test: `tests/test_pdf_read.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `pdf.read.page_count(path) -> int`, `pdf.read.plain_text(path, page=None) -> str`, `pdf.read.PdfError`, and `tests.fixtures.make_pdf(path, body) -> Path`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pdf_read.py
"""The PDF readers, against PDFs the tests build with mutool, so nothing here
depends on a datasheet that happens to be on this machine."""
import shutil

import pytest

from placemat.pdf import read
from tests.fixtures import make_pdf

needs_mupdf = pytest.mark.skipif(shutil.which("mutool") is None, reason="mutool is not here")
needs_poppler = pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler is not here")
pytestmark = [needs_mupdf, needs_poppler]

LAND = """%%MediaBox 0 0 300 300
%%Font Helv Helvetica
BT /Helv 12 Tf 20 250 Td (RECOMMENDED LAND PATTERN) Tj ET
BT /Helv 10 Tf 20 230 Td ([ Unit : mm ]) Tj ET
10 10 40 20 re f
60 10 40 20 re f
110 10 40 20 re f
"""


def test_a_built_pdf_reads_back_its_page_count_and_text(tmp_path):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert read.page_count(p) == 1
    assert "RECOMMENDED LAND PATTERN" in read.plain_text(p)


def test_a_file_that_is_not_a_pdf_says_so(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("this is not a pdf")
    with pytest.raises(read.PdfError) as e:
        read.page_count(bad)
    assert "notes.txt" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pdf_read.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'placemat.pdf'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/placemat/pdf/__init__.py
"""Everything that runs a PDF tool. No other package shells out to mupdf or
poppler, the same way no package outside `kicad/` imports pcbnew."""
```

```python
# src/placemat/pdf/read.py
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
```

```python
# append to tests/fixtures.py
def make_pdf(path, body: str):
    """A one-page PDF built with mutool from a content stream, so a test can
    state exactly what is on the page it then reads back."""
    import subprocess
    src = Path(path).with_suffix(".txt")
    src.write_text(body)
    subprocess.run(["mutool", "create", "-o", str(path), str(src)],
                   capture_output=True, check=True)
    return Path(path)
```

`tests/fixtures.py` needs `from pathlib import Path` if it has none.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pdf_read.py -q`
Expected: PASS, 2 tests

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pdf tests/test_pdf_read.py tests/fixtures.py
git commit -m "A PDF read through poppler, and a PDF the tests build themselves"
```

---

## Task 2: Text with its box

**Files:**
- Create: (none)
- Modify: `src/placemat/datasheet.py` (create), `src/placemat/pdf/read.py`
- Test: `tests/test_pdf_read.py`

**Interfaces:**
- Consumes: Task 1's `_run`.
- Produces: `datasheet.TextRun(page: int, text: str, box: Box)` and `pdf.read.text_runs(path, page) -> tuple[TextRun, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pdf_read.py
def test_text_comes_back_with_the_box_it_sits_in(tmp_path):
    """A number is only useful when its position is known: that is what ties
    a dimension to the feature it labels."""
    p = make_pdf(tmp_path / "land.pdf", LAND)
    runs = read.text_runs(p, 1)
    hit = [r for r in runs if "RECOMMENDED" in r.text]
    assert len(hit) == 1
    r = hit[0]
    assert r.page == 1
    assert r.box.left == pytest.approx(20, abs=1.0)
    assert r.box.width > 100 and 0 < r.box.height < 30


def test_an_escaped_character_comes_back_decoded(tmp_path):
    p = make_pdf(tmp_path / "dia.pdf", """%%MediaBox 0 0 200 200
%%Font Helv Helvetica
BT /Helv 10 Tf 20 100 Td (VIA 0.2mm) Tj ET
""")
    assert any("VIA" in r.text for r in read.text_runs(p, 1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pdf_read.py -q -k text_comes_back`
Expected: FAIL, `AttributeError: module 'placemat.pdf.read' has no attribute 'text_runs'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/placemat/datasheet.py
"""What a datasheet page is about, decided from what is on it.

Pure: no PDF is opened here, so every rule is pinned by tests that run
anywhere. `pdf/read.py` produces the values this module scores.
"""
from __future__ import annotations

from dataclasses import dataclass

from .values import Box


@dataclass(frozen=True)
class TextRun:
    """One line of text and the box it occupies, in PDF points."""
    page: int
    text: str
    box: Box


@dataclass(frozen=True)
class DrawPath:
    """One path from the page's drawing, already put through its transform.
    `rect` is the only shape question asked here: a path whose points took
    exactly two x values and two y values is an axis-aligned box. Four points
    alone do not make one - a diamond has four too."""
    page: int
    box: Box
    points: int
    rect: bool
    filled: bool
```

```python
# append to src/placemat/pdf/read.py
import xml.etree.ElementTree as ET

from ..datasheet import DrawPath, TextRun
from ..values import Box


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pdf_read.py -q`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add src/placemat/datasheet.py src/placemat/pdf/read.py tests/test_pdf_read.py
git commit -m "Text with the box it sits in, so a number has a place on the page"
```

---

## Task 3: The drawing's paths, through their transform

**Files:**
- Modify: `src/placemat/pdf/read.py`
- Test: `tests/test_pdf_read.py`

**Interfaces:**
- Consumes: `datasheet.DrawPath`, `geometry.Transform`.
- Produces: `pdf.read.draw_paths(path, page) -> tuple[DrawPath, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pdf_read.py
def test_a_drawn_rectangle_comes_back_at_its_real_size(tmp_path):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    paths = read.draw_paths(p, 1)
    rects = [d for d in paths if d.rect]
    assert len(rects) == 3
    assert all(d.box.width == pytest.approx(40, abs=0.5) for d in rects)
    assert all(d.box.height == pytest.approx(20, abs=0.5) for d in rects)


def test_a_scaled_path_is_measured_after_its_transform(tmp_path):
    """mutool emits pre-transform coordinates. A real datasheet scales by 0.12
    and rotates, so a path measured before its matrix is applied is wrong by
    almost an order of magnitude."""
    p = make_pdf(tmp_path / "scaled.pdf", """%%MediaBox 0 0 300 300
q 0.5 0 0 0.5 0 0 cm
10 10 40 20 re f
Q
""")
    (rect,) = [d for d in read.draw_paths(p, 1) if d.rect]
    assert rect.box.width == pytest.approx(20, abs=0.5)     # 40 * 0.5
    assert rect.box.height == pytest.approx(10, abs=0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pdf_read.py -q -k drawn_rectangle`
Expected: FAIL, `AttributeError: ... has no attribute 'draw_paths'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/pdf/read.py
from ..geometry import Transform

_POINT_TAGS = ("moveto", "lineto")


def _transform_of(el) -> Transform:
    """mutool writes `transform="a b c d e f"` on every path and the points
    inside it are in the space that matrix maps from."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pdf_read.py -q`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pdf/read.py tests/test_pdf_read.py
git commit -m "The drawing's paths, measured after the matrix that places them"
```

---

## Task 4: Rectangles, clusters and the unit

**Files:**
- Modify: `src/placemat/datasheet.py`
- Test: `tests/test_datasheet.py` (create)

**Interfaces:**
- Consumes: `TextRun`, `DrawPath`.
- Produces: `datasheet.rectangles(paths) -> tuple[DrawPath, ...]`, `datasheet.clusters(rects, tol=0.5) -> list[tuple[tuple, int]]`, `datasheet.dimension_numbers(runs) -> tuple[float, ...]`, `datasheet.unit_of(runs) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_datasheet.py
"""What a datasheet page is about, from what is on it. Pure: no PDF, so these
run anywhere."""
import pytest

from placemat import datasheet as ds
from placemat.values import Box


def _run(text, x=0.0, y=0.0, w=50.0, h=10.0, page=1):
    return ds.TextRun(page, text, Box(x, y, x + w, y + h))


def _rect(w, h, x=0.0, y=0.0, page=1):
    return ds.DrawPath(page, Box(x, y, x + w, y + h), points=4, rect=True, filled=True)


def test_only_four_corner_paths_count_as_rectangles():
    diamond = ds.DrawPath(1, Box(0, 0, 9, 9), points=4, rect=False, filled=False)
    curve = ds.DrawPath(1, Box(0, 0, 9, 9), points=17, rect=False, filled=False)
    assert len(ds.rectangles([_rect(2, 1), _rect(2, 1), diamond, curve])) == 2


def test_rectangles_of_the_same_size_cluster():
    rects = [_rect(2.0, 1.0), _rect(2.0, 1.0), _rect(2.02, 1.01), _rect(5.0, 5.0)]
    top = ds.clusters(rects)[0]
    assert top[1] == 3 and top[0] == (pytest.approx(2.0, abs=0.1), pytest.approx(1.0, abs=0.1))


def test_dimension_numbers_are_the_decimals_on_the_page():
    runs = [_run("0.50"), _run("1.30"), _run("Page 7 of 11"), _run("ANT016008LCS2442MA1")]
    assert sorted(ds.dimension_numbers(runs)) == [0.5, 1.3]


def test_the_unit_is_read_where_the_page_states_it():
    assert ds.unit_of([_run("[ Unit : mm ]")]) == "mm"
    assert ds.unit_of([_run("All dimensions are in mm / inches")]) == "mm"
    assert ds.unit_of([_run("nothing to say")]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q`
Expected: FAIL, `AttributeError: module 'placemat.datasheet' has no attribute 'rectangles'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/datasheet.py
import re

# A decimal with a fractional part. A bare integer is a page number, a pin
# number or a year far more often than it is a dimension, so it is not one.
_DECIMAL = re.compile(r"(?<![\w.])(\d{1,3}\.\d{1,3})(?![\w.])")
_UNIT = ((re.compile(r"\bmm\b|\bmillimet", re.I), "mm"),
         (re.compile(r"\binch(es)?\b|\bmils?\b", re.I), "inch"))


def rectangles(paths) -> tuple:
    """The paths that are an axis-aligned box. `corners` is 4 only when the
    points took two distinct x values and two distinct y values."""
    return tuple(p for p in paths if p.rect and p.box.width > 0 and p.box.height > 0)


def clusters(rects, tol: float = 0.5) -> list:
    """Rectangles of the same size, largest group first. A land pattern is a
    row of identical pads, so the biggest group of equal rectangles is the
    strongest geometric evidence a page carries."""
    groups = {}
    for r in rects:
        key = (round(r.box.width / tol) * tol, round(r.box.height / tol) * tol)
        groups.setdefault(key, []).append(r)
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [(k, len(v)) for k, v in ranked]


def dimension_numbers(runs) -> tuple:
    out = []
    for r in runs:
        out.extend(float(m) for m in _DECIMAL.findall(r.text))
    return tuple(out)


def unit_of(runs):
    for r in runs:
        for pattern, name in _UNIT:
            if pattern.search(r.text):
                return name
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add src/placemat/datasheet.py tests/test_datasheet.py
git commit -m "A page's rectangles, its equal-sized groups, its decimals and its unit"
```

---

## Task 5: Evidence, and the band it earns

**Files:**
- Modify: `src/placemat/datasheet.py`
- Test: `tests/test_datasheet.py`

**Interfaces:**
- Consumes: Task 4's helpers.
- Produces: `datasheet.TOPICS`, `datasheet.Evidence(kind, detail)`, `datasheet.Candidate(page, topic, score, band, evidence)`, `datasheet.page_evidence(topic, runs, paths) -> tuple[Evidence, ...]`, `datasheet.band_of(evidence) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_datasheet.py
def test_a_keyword_and_geometry_together_are_strong():
    runs = [_run("RECOMMENDED LAND PATTERN"), _run("0.50"), _run("1.30"), _run("[ Unit : mm ]")]
    rects = [_rect(2, 1) for _ in range(6)]
    ev = ds.page_evidence("land", runs, rects)
    assert any(e.kind == "keyword" for e in ev)
    assert any(e.kind == "rects" for e in ev)
    assert ds.band_of(ev) == "strong"


def test_geometry_with_no_keyword_is_fair():
    """The text-free connectors: 36 equal rectangles and nothing said."""
    rects = [_rect(2, 1) for _ in range(36)]
    ev = ds.page_evidence("land", [], rects)
    assert ds.band_of(ev) == "fair"


def test_a_page_with_nothing_earns_no_evidence():
    assert ds.page_evidence("land", [_run("Ordering information")], []) == ()
    assert ds.band_of(()) == "none"


def test_every_topic_has_a_keyword_table():
    for topic in ds.TOPICS:
        assert ds.KEYWORDS[topic], topic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q -k keyword_and_geometry`
Expected: FAIL, `AttributeError: ... has no attribute 'page_evidence'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/datasheet.py
TOPICS = ("land", "package", "rules", "pins")

# One vendor's words for a thing are not another's: the W3011 says "MECHANICAL
# DRAWING" and "PWB Layout" where TDK says "RECOMMENDED LAND PATTERN". Measured
# over 67 datasheets, a keyword list alone finds a land pattern on half of
# them, which is why it is one signal beside the geometry and never the answer.
KEYWORDS = {
    "land": (r"recommended land", r"land pattern", r"recommended pad", r"pcb layout",
             r"pwb layout", r"mounting pad", r"solder pad", r"recommended solder",
             r"suggested (pad|land)", r"footprint"),
    "package": (r"package (outline|dimension)", r"mechanical (data|drawing|dimension)",
                r"outline drawing", r"product outline", r"physical dimension",
                r"dimensions? \(mm\)", r"body size"),
    "rules": (r"keep ?out", r"keep-out", r"layout (guideline|consideration|recommendation)",
              r"thermal pad", r"via.in.pad", r"ground plane", r"placement guideline"),
    "pins": (r"pin (configuration|description|assignment|function|map)",
             r"terminal (function|description)", r"pinout", r"pin list"),
}
_COMPILED = {t: [re.compile(p, re.I) for p in pats] for t, pats in KEYWORDS.items()}

# A group this size is a pad row rather than a coincidence. Below it the
# geometry says nothing, so it is not offered as evidence at all.
CLUSTER_FLOOR = 4


@dataclass(frozen=True)
class Evidence:
    kind: str           # keyword | rects | dims | unit
    detail: str


@dataclass(frozen=True)
class Candidate:
    page: int
    topic: str
    score: float
    band: str
    evidence: tuple


def page_evidence(topic: str, runs, paths) -> tuple:
    """Everything on this page that argues it is about `topic`. Each item
    says what was seen, so a ranking can be judged instead of trusted."""
    out = []
    for r in runs:
        for pattern in _COMPILED[topic]:
            m = pattern.search(r.text)
            if m:
                out.append(Evidence("keyword", '"%s"' % r.text.strip()[:60]))
                break
        if out and out[-1].kind == "keyword":
            break
    groups = clusters(rectangles(paths))
    if groups and groups[0][1] >= CLUSTER_FLOOR:
        (w, h), n = groups[0]
        out.append(Evidence("rects", "%d of %.3g x %.3g" % (n, w, h)))
    dims = dimension_numbers(runs)
    if len(dims) >= 3:
        out.append(Evidence("dims", "%d dimension(s)" % len(dims)))
    unit = unit_of(runs)
    if unit:
        out.append(Evidence("unit", "unit %s" % unit))
    return tuple(out)


# What a band means, said in evidence rather than in a cut-off: a page that
# both names the topic and carries the geometry for it is as good as this gets.
_WEIGHT = {"keyword": 3.0, "rects": 2.0, "dims": 1.0, "unit": 0.5}


def score_of(evidence) -> float:
    return sum(_WEIGHT.get(e.kind, 0.0) for e in evidence)


def band_of(evidence) -> str:
    kinds = {e.kind for e in evidence}
    if not kinds:
        return "none"
    if "keyword" in kinds and kinds & {"rects", "dims"}:
        return "strong"
    if "keyword" in kinds or "rects" in kinds:
        return "fair"
    return "weak"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add src/placemat/datasheet.py tests/test_datasheet.py
git commit -m "The evidence a page offers for a topic, and the band it earns"
```

---

## Task 6: The index

**Files:**
- Modify: `src/placemat/datasheet.py`
- Test: `tests/test_datasheet.py`

**Interfaces:**
- Consumes: Task 5's `page_evidence`, `score_of`, `band_of`.
- Produces: `datasheet.index(by_page) -> tuple[Candidate, ...]`, `datasheet.index_rows(candidates) -> list[dict]`, `datasheet.index_lines(name, pages, candidates) -> list[str]`. `by_page` is `{page: (runs, paths)}`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_datasheet.py
def _page(page, words=(), rects=0, size=(2.0, 1.0)):
    runs = [_run(w, page=page) for w in words]
    paths = [_rect(size[0], size[1], page=page) for _ in range(rects)]
    return runs, paths


def test_the_index_puts_the_best_candidate_for_a_topic_first():
    by_page = {
        1: _page(1, ("Ordering information",)),
        6: _page(6, ("MECHANICAL DIMENSIONS (mm)", "1.20", "3.40", "5.60"), rects=20),
        7: _page(7, ("RECOMMENDED LAND PATTERN", "[ Unit : mm ]", "0.50", "1.30", "2.10"), rects=8),
    }
    land = [c for c in ds.index(by_page) if c.topic == "land"]
    assert land[0].page == 7 and land[0].band == "strong"


def test_a_topic_with_no_candidate_still_appears():
    by_page = {1: _page(1, ("Ordering information",))}
    got = {c.topic: c for c in ds.index(by_page)}
    assert set(got) == set(ds.TOPICS)
    assert got["pins"].band == "none" and got["pins"].page == 0


def test_the_index_lines_name_the_page_the_band_and_the_evidence():
    by_page = {7: _page(7, ("RECOMMENDED LAND PATTERN", "0.50", "1.30", "2.10"), rects=8)}
    text = "\n".join(ds.index_lines("TDK-ANT016008", 11, ds.index(by_page)))
    assert "p7" in text and "land" in text and "strong" in text
    assert "RECOMMENDED LAND PATTERN" in text


def test_index_rows_carry_the_same_facts_as_the_lines():
    by_page = {7: _page(7, ("RECOMMENDED LAND PATTERN", "0.50", "1.30", "2.10"), rects=8)}
    rows = ds.index_rows(ds.index(by_page))
    land = [r for r in rows if r["topic"] == "land"][0]
    assert land["page"] == 7 and land["band"] == "strong" and land["evidence"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q -k index`
Expected: FAIL, `AttributeError: ... has no attribute 'index'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/datasheet.py
def index(by_page: dict) -> tuple:
    """The best page for each topic, best topic first. A topic nothing argued
    for gets a candidate at page 0 with band "none", because "placemat found
    nothing" and "placemat did not look" are different facts."""
    out = []
    for topic in TOPICS:
        best = None
        for page in sorted(by_page):
            runs, paths = by_page[page]
            ev = page_evidence(topic, runs, paths)
            if not ev:
                continue
            c = Candidate(page, topic, score_of(ev), band_of(ev), ev)
            if best is None or c.score > best.score:
                best = c
        out.append(best or Candidate(0, topic, 0.0, "none", ()))
    return tuple(sorted(out, key=lambda c: -c.score))


def index_rows(candidates) -> list:
    return [{"page": c.page, "topic": c.topic, "score": round(c.score, 2), "band": c.band,
             "evidence": [{"kind": e.kind, "detail": e.detail} for e in c.evidence]}
            for c in candidates]


_TOPIC_NAME = {"land": "land pattern", "package": "package", "rules": "rules", "pins": "pins"}


def index_lines(name: str, pages: int, candidates) -> list:
    out = ["%s  %d page(s)" % (name, pages)]
    for c in candidates:
        if c.band == "none":
            out.append("  %-4s %-13s %-7s nothing on any page argued for it" % ("-", _TOPIC_NAME[c.topic], c.band))
            continue
        out.append("  p%-3d %-13s %-7s %s" % (
            c.page, _TOPIC_NAME[c.topic], c.band, ", ".join(e.detail for e in c.evidence)))
    best = [c for c in candidates if c.band != "none"]
    if best:
        out.append("  look: placemat datasheet <pdf> --show p%d" % best[0].page)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add src/placemat/datasheet.py tests/test_datasheet.py
git commit -m "The index: the best page for each topic, and why it won"
```

---

## Task 7: Rendering a page, and the command

**Files:**
- Modify: `src/placemat/pdf/read.py`, `src/placemat/cli.py`
- Test: `tests/test_pdf_read.py`, `tests/test_datasheet_cli.py` (create)

**Interfaces:**
- Consumes: everything above.
- Produces: `pdf.read.render(path, page, out_dir, dpi=300) -> Path`, `pdf.read.have_ocr() -> bool`, `cli.cmd_datasheet(args) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pdf_read.py
def test_a_page_renders_to_a_png(tmp_path):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    png = read.render(p, 1, tmp_path / "out")
    assert png.exists() and png.suffix == ".png" and png.stat().st_size > 0
```

```python
# tests/test_datasheet_cli.py
"""placemat datasheet, end to end on a PDF the test builds."""
import shutil

import pytest

from placemat.cli import main
from tests.fixtures import make_pdf
from tests.test_pdf_read import LAND

pytestmark = [pytest.mark.skipif(shutil.which("mutool") is None, reason="mutool is not here"),
              pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler is not here")]


def test_the_index_prints_the_land_pattern_page(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p)]) == 0
    out = capsys.readouterr().out
    assert "land pattern" in out and "p1" in out


def test_show_renders_a_page_and_names_the_file(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--show", "p1", "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert ".png" in out
    assert list((tmp_path / "o").glob("*.png"))


def test_show_resolves_a_topic_to_its_best_page(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--show", "land", "--out", str(tmp_path / "o")]) == 0
    assert ".png" in capsys.readouterr().out


def test_show_for_a_topic_with_no_candidate_says_so(tmp_path, capsys):
    p = make_pdf(tmp_path / "bare.pdf", """%%MediaBox 0 0 200 200
%%Font Helv Helvetica
BT /Helv 10 Tf 20 100 Td (Ordering information) Tj ET
""")
    assert main(["datasheet", str(p), "--show", "pins", "--out", str(tmp_path / "o")]) == 1
    assert "no candidate" in capsys.readouterr().out


def test_json_carries_the_same_rows(tmp_path, capsys):
    import json
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["pages"] == 1
    assert any(r["topic"] == "land" and r["page"] == 1 for r in doc["index"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet_cli.py -q`
Expected: FAIL, `argparse` exits 2 on the unknown command `datasheet`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/pdf/read.py
def render(path, page: int, out_dir, dpi: int = 300):
    """One page as a PNG. This is the channel that always works: a datasheet
    whose every dimension is an outlined curve still renders."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / ("%s-p%d" % (Path(path).stem, page))
    _run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
          "-singlefile", str(path), str(stem)], "rendering a page", path)
    return stem.with_suffix(".png")


def have_ocr() -> bool:
    """tesseract reads the outlined dimension text that carries no characters.
    It is optional: placemat needs nothing installed for the ordinary path."""
    return shutil.which("tesseract") is not None
```

```python
# in src/placemat/cli.py parser(), after the `parts` block
    dsp = sub.add_parser("datasheet", help="what is in a datasheet and where: the page for each "
                                          "of land pattern, package, rules and pins")
    dsp.add_argument("pdf", help="a datasheet PDF")
    dsp.add_argument("--show", metavar="PAGE|TOPIC", default=None,
                     help="render a page (p7) or a topic's best page (land) and print its text")
    dsp.add_argument("--out", default=None, help="where renders go (default: beside the PDF)")
    dsp.add_argument("--dpi", type=int, default=300)
    dsp.add_argument("--json", action="store_true")
```

```python
# in src/placemat/cli.py, beside cmd_parts
def cmd_datasheet(args) -> int:
    from . import datasheet as ds
    from .pdf import read as pdf
    path = Path(args.pdf)
    try:
        pages = pdf.page_count(path)
        by_page = {n: (pdf.text_runs(path, n), pdf.draw_paths(path, n))
                   for n in range(1, pages + 1)}
    except pdf.PdfError as e:
        console.say("datasheet", str(e))
        return 1
    found = ds.index(by_page)
    if args.show:
        page = _page_for(args.show, found)
        if page is None:
            console.say("datasheet", "no candidate for %r; the index says what was found, "
                                     "or name a page as p<N>" % args.show)
            return 1
        out_dir = Path(args.out) if args.out else path.parent
        png = pdf.render(path, page, out_dir, args.dpi)
        runs, _ = by_page[page]
        if args.json:
            console.data(json.dumps({"page": page, "png": str(png),
                                     "text": [r.text for r in runs]}, indent=2))
            return 0
        console.say("datasheet", "page %d rendered to %s" % (page, png))
        for r in runs:
            console.say("datasheet", "  %-6.0f %-6.0f %s" % (r.box.left, r.box.top, r.text.strip()))
        return 0
    if args.json:
        console.data(json.dumps({"pdf": str(path), "pages": pages, "ocr": pdf.have_ocr(),
                                 "index": ds.index_rows(found)}, indent=2))
        return 0
    console.lines("datasheet", "\n".join(ds.index_lines(path.stem, pages, found)))
    if not pdf.have_ocr():
        console.say("datasheet", "tesseract is not installed: a page whose dimensions are "
                                 "outlined curves has no text to read")
    return 0


def _page_for(what: str, candidates):
    """`p7` is a page; `land` is a topic, resolved through the index."""
    if re.fullmatch(r"p?\d+", what):
        return int(what.lstrip("p"))
    for c in candidates:
        if c.topic == what and c.band != "none":
            return c.page
    return None
```

`cli.py` needs `import re` if it has none, and `"datasheet": cmd_datasheet` in `main`'s dispatch table.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, whole suite

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pdf/read.py src/placemat/cli.py tests/
git commit -m "placemat datasheet: the index, and the page it tells you to look at"
```

---

## Task 8: Against the real corpus, then the documentation

**Files:**
- Modify: `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, `skills/placemat/references/migration.md`, `src/placemat/__init__.py`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Test: `tests/test_datasheet_corpus.py` (create)

**Interfaces:** no new code interface.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_datasheet_corpus.py
"""Against real datasheets, when they are on this machine. These are the two
measurements the spec argues from, so they are checked rather than quoted."""
import os
import pathlib
import shutil

import pytest

from placemat import datasheet as ds
from placemat.pdf import read

CORPUS = pathlib.Path("/home/ben/Documents/Hardware/fairing-instrument/electronics/datasheets")
pytestmark = [pytest.mark.skipif(shutil.which("mutool") is None, reason="mutool is not here"),
              pytest.mark.skipif(not CORPUS.is_dir(), reason="the datasheet corpus is not here")]

TDK = CORPUS / "TDK-ANT016008LCS2442MA1_C76585.pdf"
TYPEC = CORPUS / "Korean_Hroparts_Elec-TYPE_C_31_M_12_C165948.pdf"


@pytest.mark.skipif(not TDK.exists(), reason="no TDK antenna datasheet")
def test_the_antennas_land_pattern_is_found_on_page_7():
    by_page = {n: (read.text_runs(TDK, n), read.draw_paths(TDK, n))
               for n in range(1, read.page_count(TDK) + 1)}
    land = [c for c in ds.index(by_page) if c.topic == "land"][0]
    assert land.page == 7 and land.band == "strong"


@pytest.mark.skipif(not TYPEC.exists(), reason="no TYPE-C datasheet")
def test_a_datasheet_with_no_text_still_yields_its_rectangles():
    """55 characters of text on the whole page; every dimension is an outlined
    curve. The geometry is still there, and it is what makes this part
    tractable at all."""
    runs = read.text_runs(TYPEC, 1)
    assert sum(len(r.text) for r in runs) < 200
    groups = ds.clusters(ds.rectangles(read.draw_paths(TYPEC, 1)))
    assert groups and groups[0][1] >= 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet_corpus.py -q`
Expected: FAIL or SKIP. If it fails on page 7, the keyword table or `CLUSTER_FLOOR` needs the adjustment the failure names - fix it, do not weaken the test.

- [ ] **Step 3: Write minimal implementation**

In `api.md`, in the Commands block:

```
placemat datasheet <pdf> [--show PAGE|TOPIC] [--out DIR] [--dpi N] [--json]
```

and after that block:

````markdown
`datasheet` ranks a PDF's pages against four topics - land pattern, package
dimensions, layout rules and pin map - and prints the evidence that produced
each ranking, so the ranking can be judged rather than trusted. `--show p7`
renders that page to a PNG and prints its text with positions; `--show land`
resolves the topic through the index first. Measured over 67 datasheets, a
keyword list alone names a land pattern on half of them, so the geometry
counts too: a page holding a row of identical rectangles is a pad row whether
or not it says so. A datasheet whose every dimension is an outlined curve
carries no text at all - the TYPE-C receptacles are like this - and `--show`
is the answer for those.
````

In `SKILL.md`, in Placement tactics, after the `placemat parts` bullet:

> Before extracting images from a datasheet or grepping its text, run
> `placemat datasheet <pdf>` to see which page carries the land pattern, the
> package dimensions, the layout rules or the pin map, then `--show` that page.
> Deciding for yourself how to get at a datasheet is the habit this replaces.

In `references/migration.md`, above `## To 0.11`:

````markdown
## To 0.12

Nothing to change. `placemat datasheet <pdf>` is new: it ranks the pages
against land pattern, package dimensions, layout rules and pin map, prints the
evidence behind each ranking, and `--show` renders the page you should look at.
It shells out to mupdf and poppler, which join kicad-cli as tools placemat
expects to find; `tesseract` is used when installed and skipped with a note
when not.
````

- [ ] **Step 4: Run the whole suite and bump the version**

```bash
sed -i 's/__version__ = "0.11.0"/__version__ = "0.12.0"/' src/placemat/__init__.py
sed -i 's/"version": "0.11.0"/"version": "0.12.0"/' .claude-plugin/plugin.json .claude-plugin/marketplace.json
uv pip install -q -e .
.venv/bin/python -m pytest -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Plugin 0.12.0: placemat datasheet"
```

---

## Acceptance criteria

1. `.venv/bin/python -m pytest -q` passes in full, and a four-point path that
   is not axis-aligned is not counted as a rectangle.
2. `placemat datasheet <pdf>` prints one line per topic, each naming a page, a
   band and the evidence behind it.
3. A topic nothing argued for prints its own line saying so, rather than being
   absent.
4. `--show p7` renders page 7 to a PNG and prints the path and the page's text
   with positions.
5. `--show land` resolves the topic through the index; a topic with no
   candidate exits 1 and says so.
6. A path is measured after its transform: a rectangle drawn under a 0.5 scale
   reports half its raw size.
7. Text comes back with its box, and an XML-escaped character is decoded.
8. `--json` carries the same rows as the tables.
9. Against the corpus, the TDK antenna's land pattern is page 7 at band
   `strong`, and the TYPE-C 31-M-12 yields a cluster of at least 10 equal
   rectangles from a page with under 200 characters of text.
10. A file that is not a PDF exits 1 naming the path and what the tool said.
11. `tesseract` absent is reported, not fatal.
12. `api.md`, `SKILL.md` and `references/migration.md` carry the new command
    and a `## To 0.12` section.
13. `git log --format=%B <base>..HEAD | grep -iE "claude|anthropic|session|co-authored"`
    returns nothing.
