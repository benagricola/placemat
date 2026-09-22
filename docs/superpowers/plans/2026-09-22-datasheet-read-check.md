# Datasheet Read and Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `placemat datasheet <pdf> --read` prints the facts the sheet can be made to yield, each carrying where it came from, and `placemat datasheet check <pdf> <footprint.kicad_mod>` compares a footprint against values that are supplied or sourced and names every disagreement.

**Architecture:** OCR joins text, geometry and render as the fourth channel, feeding the same `TextRun` values the other text channel produces so nothing downstream learns a new type. `datasheet.py` stays pure and gains `Fact` (a value with its provenance) and `Comparison` (a value against a footprint). `pdf/read.py` gains the tesseract shell-out. The footprint side reuses `read_footprint` from the read surface.

**Tech Stack:** Python 3.12 stdlib only, mupdf, poppler, tesseract (optional).

**Spec:** `docs/superpowers/specs/2026-09-22-datasheet-design.md`

## Global Constraints

- **Zero runtime dependencies.** `pyproject.toml` keeps `dependencies = []`.
- **No PDF tool outside `pdf/read.py`.** `datasheet.py` stays pure and testable with no PDF.
- **Punctuation is plain ASCII.** No em dashes, en dashes or unicode arrows.
- **Commit messages carry no reference to Claude, Anthropic or a session.**
- **Never claim a number that was not sourced.** Every `Fact` carries page, box, channel and confidence. A value that was supplied says so; a value that was neither supplied nor sourced is absent, not zero.
- **A supplied value beats a parse, and the report says it happened.**

## What this plan does NOT build, and why

**Automatic pad geometry from the vector drawing.** Measured on the
TYPE-C 31-M-12's `RECOMMEND P.C.B LAYOUT` view: 453 paths, of which 276 are
two-point line segments. The contacts are drawn as hatching, not as
rectangles. Across the whole page there is no regular run of five or more
equal-sized boxes on a shared line, and the largest equal-size group (183 of
3 x 5 pt) is glyph strokes in outlined text on 9 pt line spacing. A pad finder
built on that would be guesswork, so `check` takes its expected values from a
flag or from text, and the drawing contributes corroboration rather than
geometry. This is recorded in the spec as an open problem.

## File Structure

- `src/placemat/datasheet.py` - `TextRun` gains `source` and `confidence`; new `Fact`, `Comparison`, `runs_from_tsv`, `facts`, `read_lines`, `read_rows`, `compare`, `check_lines`, `check_rows`.
- `src/placemat/pdf/read.py` - `ocr_runs`, `text_is_thin`.
- `src/placemat/describe.py` - `pitch_of`, `pad_size_of`, `span_of` (pure, over pads).
- `src/placemat/layout.py` - `Board.pitch` delegates to `describe.pitch_of`.
- `src/placemat/cli.py` - `--read`, `--no-ocr`, the `check` sub-form and its overrides.
- `tests/test_datasheet.py` - the pure parsing, facts and comparison.
- `tests/test_pdf_read.py` - `ocr_runs` against a built PDF.
- `tests/test_datasheet_cli.py` - `--read` and `check` end to end.
- `tests/test_datasheet_corpus.py` - OCR against the real text-free connector.

---

## Task 1: A text run that knows where it came from

**Files:**
- Modify: `src/placemat/datasheet.py`
- Test: `tests/test_datasheet.py`

**Interfaces:**
- Produces: `TextRun(page, text, box, source="text", confidence=100.0)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_datasheet.py
def test_a_text_run_says_which_channel_read_it():
    """A number read by OCR is not as good as one read from the PDF's own
    text, and a reader has to be able to tell which they are looking at."""
    plain = ds.TextRun(1, "0.50", Box(0, 0, 10, 5))
    assert plain.source == "text" and plain.confidence == 100.0
    seen = ds.TextRun(1, "0.50", Box(0, 0, 10, 5), source="ocr", confidence=78.0)
    assert seen.source == "ocr" and seen.confidence == 78.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q -k which_channel`
Expected: FAIL, `TypeError: TextRun.__init__() got an unexpected keyword argument 'source'`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/datasheet.py`, replace the `TextRun` dataclass with:

```python
@dataclass(frozen=True)
class TextRun:
    """One line of text and the box it occupies, in PDF points.

    `source` is the channel that read it and `confidence` is how sure that
    channel is. The PDF's own text is certain by construction; OCR is not, and
    a reader must be able to tell the two apart at a glance."""
    page: int
    text: str
    box: Box
    source: str = "text"
    confidence: float = 100.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/datasheet.py tests/test_datasheet.py
git commit -m "A text run that says which channel read it, and how sure it is"
```

---

## Task 2: tesseract's TSV, grouped into lines

**Files:**
- Modify: `src/placemat/datasheet.py`
- Test: `tests/test_datasheet.py`

**Interfaces:**
- Produces: `datasheet.runs_from_tsv(tsv: str, page: int, min_conf: float = 70.0) -> tuple[TextRun, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_datasheet.py
TSV = "\t".join(["level", "page_num", "block_num", "par_num", "line_num", "word_num",
                 "left", "top", "width", "height", "conf", "text"]) + "\n" + "\n".join([
    "5\t1\t1\t1\t1\t1\t100\t50\t90\t12\t92\tRECOMMEND",
    "5\t1\t1\t1\t1\t2\t200\t50\t40\t12\t88\tP.C.B",
    "5\t1\t1\t1\t1\t3\t250\t50\t80\t12\t73\tLAYOUT(COMPONEN",
    "5\t1\t2\t1\t1\t1\t400\t80\t30\t10\t96\t6.65",
    "5\t1\t3\t1\t1\t1\t500\t90\t30\t10\t16\tYUUUUUUUU",
    "5\t1\t4\t1\t1\t1\t600\t99\t10\t10\t95\t",
])


def test_ocr_words_are_grouped_into_the_line_they_came_from():
    """tesseract's TSV is one row per WORD. Building a run per word split
    "RECOMMEND P.C.B LAYOUT" into three, and no keyword matched any of them."""
    runs = ds.runs_from_tsv(TSV, page=1)
    texts = [r.text for r in runs]
    assert "RECOMMEND P.C.B LAYOUT(COMPONEN" in texts
    assert "6.65" in texts


def test_a_low_confidence_word_is_dropped_and_an_empty_one_ignored():
    runs = ds.runs_from_tsv(TSV, page=1)
    assert not any("YUUUUUUUU" in r.text for r in runs)
    assert all(r.text.strip() for r in runs)


def test_a_grouped_run_carries_the_box_round_its_words_and_the_lowest_confidence():
    (heading,) = [r for r in ds.runs_from_tsv(TSV, page=1) if "RECOMMEND" in r.text]
    assert heading.box.left == 100 and heading.box.right == 330      # 250 + 80
    assert heading.source == "ocr"
    assert heading.confidence == 73.0        # the weakest word decides the line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q -k ocr_words`
Expected: FAIL, `AttributeError: module 'placemat.datasheet' has no attribute 'runs_from_tsv'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/datasheet.py
# tesseract scores every word; below this a word is noise rather than a read.
# Measured on the TYPE-C sheet: correct dimensions scored 86 to 96, a misread
# scored 78, and the rubbish scored 16 to 39.
MIN_OCR_CONFIDENCE = 70.0


def runs_from_tsv(tsv: str, page: int, min_conf: float = MIN_OCR_CONFIDENCE) -> tuple:
    """tesseract's TSV, as one run per LINE.

    The TSV is one row per word. A run per word splits "RECOMMEND P.C.B
    LAYOUT" into three and no heading ever matches, so words are gathered by
    the block, paragraph and line columns tesseract already numbers them with.
    A line is only as good as its worst word, so the weakest confidence in it
    is the line's."""
    lines = {}
    for row in tsv.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        try:
            conf = float(f[10])
            left, top, width, height = (float(v) for v in f[6:10])
        except ValueError:
            continue
        if conf < min_conf:
            continue
        lines.setdefault((f[2], f[3], f[4]), []).append((left, top, width, height, conf, f[11]))
    out = []
    for words in lines.values():
        text = " ".join(w[5] for w in words)
        box = Box(min(w[0] for w in words), min(w[1] for w in words),
                  max(w[0] + w[2] for w in words), max(w[1] + w[3] for w in words))
        out.append(TextRun(page, text, box, source="ocr",
                           confidence=min(w[4] for w in words)))
    return tuple(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/datasheet.py tests/test_datasheet.py
git commit -m "tesseract's words, gathered back into the lines they came from"
```

---

## Task 3: The OCR channel, and the keyword table that survives it

**Files:**
- Modify: `src/placemat/pdf/read.py`, `src/placemat/datasheet.py`, `src/placemat/cli.py`
- Test: `tests/test_pdf_read.py`, `tests/test_datasheet.py`, `tests/test_datasheet_corpus.py`

**Interfaces:**
- Produces: `pdf.read.ocr_runs(path, page, out_dir, dpi=300, min_conf=70.0) -> tuple[TextRun, ...]`, `pdf.read.text_is_thin(runs) -> bool`, `datasheet.OCR_TEXT_FLOOR`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pdf_read.py
needs_ocr = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not here")


@needs_ocr
def test_ocr_reads_a_rendered_page(tmp_path):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    runs = read.ocr_runs(p, 1, tmp_path / "o")
    assert any("LAND PATTERN" in r.text.upper() for r in runs)
    assert all(r.source == "ocr" for r in runs)
    assert all(70.0 <= r.confidence <= 100.0 for r in runs)


def test_a_page_with_almost_no_text_is_thin():
    thin = (ds.TextRun(1, "ROHS", Box(0, 0, 10, 5)), ds.TextRun(1, "A", Box(0, 0, 3, 5)))
    assert read.text_is_thin(thin)
    fat = tuple(ds.TextRun(1, "x" * 40, Box(0, 0, 10, 5)) for _ in range(10))
    assert not read.text_is_thin(fat)
```

```python
# append to tests/test_datasheet.py
def test_a_dotted_pcb_still_matches_the_land_keyword():
    """OCR reads the TYPE-C heading as "RECOMMEND P.C.B LAYOUT(COMPONEN".
    The pattern `pcb layout` does not match it, and that one gap kept the
    only page of a text-free datasheet at `fair`."""
    runs = [_run("RECOMMEND P.C.B LAYOUT(COMPONEN")]
    ev = ds.page_evidence("land", runs, [_rect(2, 1) for _ in range(6)])
    assert any(e.kind == "keyword" for e in ev)
    assert ds.band_of(ev) == "strong"
```

```python
# append to tests/test_datasheet_corpus.py
@pytest.mark.skipif(not TYPEC.exists(), reason="no TYPE-C datasheet")
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not here")
def test_ocr_turns_the_text_free_connector_into_a_strong_land_pattern(tmp_path):
    """Its own text is six runs. Read off the render it yields the heading,
    the dimension stack and the unit."""
    runs = read.ocr_runs(TYPEC, 1, tmp_path)
    assert len(runs) > 50
    assert any("LAYOUT" in r.text.upper() for r in runs)
    assert ds.unit_of(runs) == "mm"
    ev = ds.page_evidence("land", runs, read.draw_paths(TYPEC, 1))
    assert ds.band_of(ev) == "strong"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pdf_read.py tests/test_datasheet.py -q -k "ocr_reads or thin or dotted_pcb"`
Expected: FAIL, `AttributeError: ... has no attribute 'ocr_runs'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/pdf/read.py
from ..datasheet import OCR_TEXT_FLOOR, runs_from_tsv


def text_is_thin(runs) -> bool:
    """True when a page carries too little of its own text to be worth
    scoring. On these datasheets a drawing whose dimensions are outlined
    curves comes back with a handful of characters and nothing else."""
    return sum(len(r.text.strip()) for r in runs) < OCR_TEXT_FLOOR


def ocr_runs(path, page: int, out_dir, dpi: int = 300, min_conf: float = 70.0) -> tuple:
    """The page read off its own render. Returns the same TextRun values the
    PDF's text channel produces, so nothing downstream learns a new type."""
    png = render(path, page, out_dir, dpi)
    tsv = _run(["tesseract", str(png), "-", "--psm", "11", "tsv"],
               "reading a page with OCR", path)
    return runs_from_tsv(tsv, page, min_conf)
```

```python
# in src/placemat/datasheet.py, beside MIN_OCR_CONFIDENCE
# Under this many characters a page has not really got text, and is worth the
# second and a half OCR costs. 7 of the 67 datasheets measured are like this.
OCR_TEXT_FLOOR = 200
```

In `src/placemat/datasheet.py`, add to `KEYWORDS["land"]` the pattern
`r"p\.?\s?c\.?\s?b\.?\s*layout"` and drop the now-redundant `r"pcb layout"`
and `r"pwb layout"`, replacing both with `r"p\.?\s?[cw]\.?\s?b\.?\s*layout"`.

In `src/placemat/cli.py` `cmd_datasheet`, replace the page-gathering loop:

```python
        by_page = {}
        for n in range(1, pages + 1):
            runs = pdf.text_runs(path, n)
            if not args.no_ocr and pdf.have_ocr() and pdf.text_is_thin(runs):
                runs = runs + pdf.ocr_runs(path, n, Path(args.out or path.parent), args.dpi)
            by_page[n] = (runs, pdf.draw_paths(path, n))
```

and add the flag beside `--dpi`:

```python
    dsp.add_argument("--no-ocr", action="store_true",
                     help="do not read a text-poor page off its render")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat tests/
git commit -m "OCR as the fourth channel, for the pages that have no text of their own"
```

---

## Task 4: A fact, and where it came from

**Files:**
- Modify: `src/placemat/datasheet.py`
- Test: `tests/test_datasheet.py`

**Interfaces:**
- Produces: `datasheet.Fact(name, value, page, box, source, confidence, detail)`, `datasheet.facts(by_page) -> tuple[Fact, ...]`, `datasheet.read_rows(facts) -> list[dict]`, `datasheet.read_lines(name, facts) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_datasheet.py
def test_a_fact_carries_the_page_the_box_and_the_channel():
    by_page = {1: ([_run("[ Unit : mm ]", x=20, y=30)], [])}
    (unit,) = [f for f in ds.facts(by_page) if f.name == "unit"]
    assert unit.value == "mm" and unit.page == 1
    assert unit.box.left == 20 and unit.source == "text"
    assert "Unit" in unit.detail


def test_every_decimal_becomes_a_dimension_fact_with_its_place():
    by_page = {7: ([_run("0.50", x=100, y=200), _run("Page 7 of 11")], [])}
    dims = [f for f in ds.facts(by_page) if f.name == "dimension"]
    assert [f.value for f in dims] == [0.5]
    assert dims[0].box.left == 100 and dims[0].page == 7


def test_an_ocr_fact_keeps_the_confidence_that_read_it():
    runs = [ds.TextRun(1, "4.95", Box(0, 0, 10, 5), source="ocr", confidence=78.0)]
    (dim,) = [f for f in ds.facts({1: (runs, [])}) if f.name == "dimension"]
    assert dim.source == "ocr" and dim.confidence == 78.0


def test_a_topic_heading_becomes_a_fact_a_reader_can_check():
    by_page = {7: ([_run("RECOMMENDED LAND PATTERN")], [])}
    found = [f for f in ds.facts(by_page) if f.name == "land"]
    assert found and "RECOMMENDED LAND PATTERN" in found[0].detail


def test_read_lines_name_the_value_and_its_provenance():
    runs = [ds.TextRun(1, "0.50", Box(10, 20, 40, 30), source="ocr", confidence=88.0)]
    text = "\n".join(ds.read_lines("TYPE_C", ds.facts({1: (runs, [])})))
    assert "0.5" in text and "p1" in text and "ocr" in text and "88" in text


def test_read_rows_carry_the_same_facts_as_the_lines():
    runs = [_run("[ Unit : mm ]")]
    rows = ds.read_rows(ds.facts({1: (runs, [])}))
    assert any(r["name"] == "unit" and r["value"] == "mm" and r["source"] == "text"
               for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q -k "fact_carries"`
Expected: FAIL, `AttributeError: module 'placemat.datasheet' has no attribute 'facts'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/datasheet.py
@dataclass(frozen=True)
class Fact:
    """One thing the sheet was made to say, and everything needed to check it
    against the render: which page, where on it, which channel read it and how
    sure that channel was."""
    name: str           # unit | scale | dimension | land | package | rules | pins
    value: object
    page: int
    box: Box
    source: str
    confidence: float
    detail: str

    @property
    def where(self) -> str:
        at = "p%d (%.0f,%.0f)" % (self.page, self.box.left, self.box.top)
        if self.source == "text":
            return "%s text" % at
        return "%s %s conf %.0f" % (at, self.source, self.confidence)


_SCALE = re.compile(r"scale\s*[:=]?\s*(\d+\s*:\s*\d+)", re.I)


def _fact(name, value, run, detail=None) -> Fact:
    return Fact(name, value, run.page, run.box, run.source, run.confidence,
                detail if detail is not None else run.text.strip())


def facts(by_page: dict) -> tuple:
    """Everything the sheet could be made to say, with its provenance. A value
    that could not be sourced is simply absent: an invented number costs more
    than a missing one."""
    out = []
    for page in sorted(by_page):
        runs, _ = by_page[page]
        for r in runs:
            for pattern, unit in _UNIT:
                if pattern.search(r.text):
                    out.append(_fact("unit", unit, r))
                    break
            m = _SCALE.search(r.text)
            if m:
                out.append(_fact("scale", m.group(1).replace(" ", ""), r))
            for value in _DECIMAL.findall(r.text):
                out.append(_fact("dimension", float(value), r))
            if is_contents(r.text):
                continue
            for topic in TOPICS:
                if any(p.search(r.text) for p in _COMPILED[topic]):
                    out.append(_fact(topic, r.text.strip()[:60], r))
                    break
    return tuple(out)


def read_rows(found) -> list:
    return [{"name": f.name, "value": f.value, "page": f.page, "source": f.source,
             "confidence": round(f.confidence, 1), "detail": f.detail,
             "at": [round(f.box.left, 1), round(f.box.top, 1)]} for f in found]


def read_lines(name: str, found) -> list:
    if not found:
        return ["%s: nothing could be sourced; --show the page and read it" % name]
    out = ["%s  %d fact(s)" % (name, len(found))]
    for f in found:
        value = ("%g" % f.value) if isinstance(f.value, float) else str(f.value)
        out.append("  %-10s %-22s %-22s %s" % (f.name, value[:22], f.where, f.detail[:40]))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/datasheet.py tests/test_datasheet.py
git commit -m "A fact, the page it sits on and the channel that read it"
```

---

## Task 5: What the footprint itself measures

**Files:**
- Modify: `src/placemat/describe.py`, `src/placemat/layout.py`
- Test: `tests/test_describe.py`

**Interfaces:**
- Produces: `describe.pitch_of(pads) -> float | None`, `describe.pad_size_of(pads) -> tuple[float, float] | None`, `describe.span_of(pads) -> float | None`. `Board.pitch` delegates to `pitch_of`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_describe.py
def test_the_pitch_is_the_nearest_gap_between_pad_centres():
    g = _geom()
    fp = g.footprint("U1")
    assert describe.pitch_of(fp.pads) == pytest.approx(2.8, abs=1e-6)
    assert describe.pitch_of(fp.pads[:1]) is None       # one pad has no pitch
    assert describe.pitch_of(()) is None


def test_the_pad_size_is_the_commonest_one():
    from tests.fixtures import pad
    pads = (pad("U9", "u9", 1, "A", 0.0, 0.0, 1.0, 2.0),
            pad("U9", "u9", 2, "B", 3.0, 0.0, 1.0, 2.0),
            pad("U9", "u9", 3, "C", 6.0, 0.0, 4.0, 4.0))
    w, h = describe.pad_size_of(pads)
    assert (round(w, 3), round(h, 3)) == (1.0, 2.0)


def test_the_span_is_the_width_across_every_pad():
    from tests.fixtures import pad
    pads = (pad("U9", "u9", 1, "A", 0.0, 0.0, 1.0, 2.0),
            pad("U9", "u9", 2, "B", 8.0, 0.0, 1.0, 2.0))
    assert describe.span_of(pads) == pytest.approx(9.0, abs=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_describe.py -q -k "pitch_is_the_nearest"`
Expected: FAIL, `AttributeError: module 'placemat.describe' has no attribute 'pitch_of'`

- [ ] **Step 3: Write minimal implementation**

`describe.py` needs `from collections import Counter` at the top with its
other imports, not at the append point.

```python
# append to src/placemat/describe.py
def pitch_of(pads):
    """The nearest gap between two pad centres: a connector's pin pitch. None
    when there are not two pads to measure between."""
    centres = [p.box.center for p in pads]
    if len(centres) < 2:
        return None
    return round(min(min(a.distance(b) for b in centres if b is not a) for a in centres), 6)


def pad_size_of(pads):
    """The commonest pad size. A connector has a shell pad or two that are not
    the contacts, and the contacts are what a land pattern is checked on."""
    if not pads:
        return None
    sizes = Counter((round(p.box.width, 3), round(p.box.height, 3)) for p in pads)
    return sizes.most_common(1)[0][0]


def span_of(pads):
    """How far the copper reaches across every pad."""
    box = Box.union([p.box for p in pads]) if pads else None
    return round(box.width, 6) if box is not None else None
```

In `src/placemat/layout.py`, make `Board.pitch` delegate so there is one
definition of a pitch:

```python
    def pitch(self, part) -> float:
        """The spacing of a part's pads: the distance between neighbouring
        pad centres, read from the footprint (a connector's pin pitch, a
        two-pad part's pad spacing)."""
        from .describe import pitch_of
        fp = self.geometry.footprint(part)
        found = pitch_of(fp.pads)
        if found is None:
            raise ValueError("%s has %d pad(s): no pitch" % (fp.ref, len(fp.pads)))
        return found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, including the existing `board.pitch` tests

- [ ] **Step 5: Commit**

```bash
git add src/placemat/describe.py src/placemat/layout.py tests/test_describe.py
git commit -m "Pitch, pad size and span, measured off the pads and defined once"
```

---

## Task 6: The comparison, and the corroboration

**Files:**
- Modify: `src/placemat/datasheet.py`
- Test: `tests/test_datasheet.py`

**Interfaces:**
- Produces: `datasheet.Comparison(name, supplied, measured, verdict, corroboration)`, `datasheet.compare(expected: dict, pads, found, tol=0.02) -> tuple[Comparison, ...]`, `datasheet.check_lines`, `datasheet.check_rows`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_datasheet.py
def _pads(*boxes):
    from tests.fixtures import pad
    return tuple(pad("U9", "u9", i + 1, "N%d" % i, x, 0.0, w, h)
                 for i, (x, w, h) in enumerate(boxes))


def test_a_supplied_value_that_matches_the_footprint_is_ok():
    pads = _pads((0.0, 1.0, 2.0), (2.8, 1.0, 2.0))
    (c,) = [c for c in ds.compare({"pitch": 2.8}, pads, ()) if c.name == "pitch"]
    assert c.verdict == "ok" and c.supplied == 2.8 and c.measured == pytest.approx(2.8)


def test_a_supplied_value_that_disagrees_is_a_mismatch():
    pads = _pads((0.0, 1.0, 2.0), (2.8, 1.0, 2.0))
    (c,) = [c for c in ds.compare({"pitch": 0.5}, pads, ()) if c.name == "pitch"]
    assert c.verdict == "MISMATCH"


def test_a_value_nobody_supplied_is_unchecked_not_zero():
    pads = _pads((0.0, 1.0, 2.0), (2.8, 1.0, 2.0))
    (c,) = [c for c in ds.compare({}, pads, ()) if c.name == "pitch"]
    assert c.verdict == "unchecked" and c.supplied is None
    assert c.measured == pytest.approx(2.8)


def test_a_supplied_value_is_corroborated_when_the_page_carries_it():
    """placemat cannot tell which number on a page is the pitch, but it can
    say whether the number you gave it appears there at all."""
    runs = [ds.TextRun(1, "0.50", Box(0, 0, 9, 9), source="ocr", confidence=86.0)]
    found = ds.facts({1: (runs, [])})
    pads = _pads((0.0, 1.0, 2.0), (0.5, 1.0, 2.0))
    (c,) = [c for c in ds.compare({"pitch": 0.5}, pads, found) if c.name == "pitch"]
    assert c.verdict == "ok"
    assert "p1" in c.corroboration and "ocr" in c.corroboration


def test_a_supplied_value_the_page_never_mentions_says_so():
    pads = _pads((0.0, 1.0, 2.0), (0.65, 1.0, 2.0))
    (c,) = [c for c in ds.compare({"pitch": 0.65}, pads, ()) if c.name == "pitch"]
    assert c.corroboration == "not on the page"


def test_the_pad_count_is_compared_too():
    pads = _pads((0.0, 1.0, 2.0), (0.5, 1.0, 2.0), (1.0, 1.0, 2.0))
    (c,) = [c for c in ds.compare({"pads": 2}, pads, ()) if c.name == "pads"]
    assert c.verdict == "MISMATCH" and c.measured == 3


def test_check_lines_and_rows_agree():
    pads = _pads((0.0, 1.0, 2.0), (0.5, 1.0, 2.0))
    got = ds.compare({"pitch": 0.5, "pads": 9}, pads, ())
    text = "\n".join(ds.check_lines(got))
    assert "MISMATCH" in text and "pitch" in text
    rows = ds.check_rows(got)
    assert {r["name"] for r in rows} == {c.name for c in got}
    assert any(r["verdict"] == "MISMATCH" for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q -k supplied_value`
Expected: FAIL, `AttributeError: module 'placemat.datasheet' has no attribute 'compare'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/placemat/datasheet.py
@dataclass(frozen=True)
class Comparison:
    name: str
    supplied: object
    measured: object
    verdict: str        # ok | MISMATCH | unchecked
    corroboration: str


# What `check` knows how to measure off a footprint. `pad` is a pair, so it is
# compared component-wise; the rest are single numbers.
CHECKS = ("pitch", "pad", "pads", "span")


def _measured(pads) -> dict:
    from .describe import pad_size_of, pitch_of, span_of
    return {"pitch": pitch_of(pads), "pad": pad_size_of(pads),
            "pads": len(pads), "span": span_of(pads)}


def _agrees(supplied, measured, tol: float) -> bool:
    if isinstance(supplied, (tuple, list)):
        return (measured is not None and len(supplied) == len(measured)
                and all(abs(a - b) <= tol for a, b in zip(supplied, measured)))
    if isinstance(supplied, float) or isinstance(measured, float):
        return measured is not None and abs(supplied - measured) <= tol
    return supplied == measured


def _corroboration(supplied, found, tol: float) -> str:
    """Whether the number supplied appears on the sheet at all.

    placemat cannot tell which decimal on a drawing is the pitch - that is
    semantics no parser here recovers - but it can say whether the value came
    from somewhere on the page or from nowhere, which is what makes an
    override safe to trust rather than blind."""
    if supplied is None:
        return ""
    wanted = list(supplied) if isinstance(supplied, (tuple, list)) else [supplied]
    seen = []
    for want in wanted:
        if not isinstance(want, (int, float)):
            continue
        hit = [f for f in found if f.name == "dimension" and abs(f.value - want) <= tol]
        if not hit:
            return "not on the page"
        seen.append(min(hit, key=lambda f: -f.confidence))
    return seen[0].where if seen else "not on the page"


def compare(expected: dict, pads, found, tol: float = 0.02) -> tuple:
    """A footprint against what the datasheet is said to require. Every check
    appears, including the ones nobody supplied a value for: a check that is
    absent from a report reads as one that passed."""
    measured = _measured(pads)
    out = []
    for name in CHECKS:
        supplied = expected.get(name)
        got = measured.get(name)
        if supplied is None:
            out.append(Comparison(name, None, got, "unchecked", ""))
            continue
        verdict = "ok" if _agrees(supplied, got, tol) else "MISMATCH"
        out.append(Comparison(name, supplied, got, verdict,
                              _corroboration(supplied, found, tol)))
    return tuple(out)


def _show(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, (tuple, list)):
        return " x ".join("%g" % x for x in v)
    return "%g" % v if isinstance(v, float) else str(v)


def check_lines(comparisons) -> list:
    out = []
    for c in comparisons:
        out.append("  %-6s %-14s %-14s %-9s %s" % (
            c.name, _show(c.supplied), _show(c.measured), c.verdict, c.corroboration))
    bad = [c for c in comparisons if c.verdict == "MISMATCH"]
    checked = [c for c in comparisons if c.verdict != "unchecked"]
    if not checked:
        out.append("  nothing was supplied to check against; --read the sheet first")
    elif bad:
        out.append("  %d of %d checks disagree" % (len(bad), len(checked)))
    else:
        out.append("  %d check(s) agree" % len(checked))
    return out


def check_rows(comparisons) -> list:
    return [{"name": c.name, "supplied": _plain_value(c.supplied),
             "measured": _plain_value(c.measured), "verdict": c.verdict,
             "corroboration": c.corroboration} for c in comparisons]


def _plain_value(v):
    return list(v) if isinstance(v, tuple) else v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_datasheet.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/datasheet.py tests/test_datasheet.py
git commit -m "A footprint against what the sheet is said to require, and whether the sheet says it"
```

---

## Task 7: `--read` and `check` on the command line

**Files:**
- Modify: `src/placemat/cli.py`
- Test: `tests/test_datasheet_cli.py`

**Interfaces:**
- Produces: `placemat datasheet <pdf> --read [--json]` and `placemat datasheet check <pdf> <footprint.kicad_mod> [--pitch F] [--pad WxH] [--pads N] [--span F] [--tol F] [--json]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_datasheet_cli.py
def test_read_prints_the_facts_with_their_provenance(tmp_path, capsys):
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--read"]) == 0
    out = capsys.readouterr().out
    assert "unit" in out and "mm" in out and "p1" in out


def test_read_json_carries_the_same_facts(tmp_path, capsys):
    import json
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", str(p), "--read", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert any(f["name"] == "unit" and f["value"] == "mm" for f in doc["facts"])


def test_read_on_a_sheet_that_yields_nothing_says_so(tmp_path, capsys):
    p = make_pdf(tmp_path / "bare.pdf", """%%MediaBox 0 0 200 200
%%Font Helv Helvetica
BT /Helv 10 Tf 20 100 Td (Ordering) Tj ET
""")
    assert main(["datasheet", str(p), "--read"]) == 0
    assert "nothing could be sourced" in capsys.readouterr().out
```

```python
# append to tests/test_datasheet_cli.py, needing KiCad for the footprint reader
import pathlib
from tests.conftest import needs_kicad

PARTS = pathlib.Path("/home/ben/Documents/Hardware/fairing-instrument/electronics/parts")


@needs_kicad
@pytest.mark.skipif(not PARTS.is_dir(), reason="the fairing parts are not here")
def test_check_names_a_disagreement_and_exits_one(tmp_path, capsys):
    mods = sorted(PARTS.glob("*/*.kicad_mod"))
    assert mods, "no footprints to check"
    p = make_pdf(tmp_path / "land.pdf", LAND)
    code = main(["datasheet", "check", str(p), str(mods[0]), "--pads", "999"])
    out = capsys.readouterr().out
    assert code == 1 and "MISMATCH" in out and "pads" in out


@needs_kicad
@pytest.mark.skipif(not PARTS.is_dir(), reason="the fairing parts are not here")
def test_check_with_nothing_supplied_still_reports_every_measurement(tmp_path, capsys):
    mods = sorted(PARTS.glob("*/*.kicad_mod"))
    p = make_pdf(tmp_path / "land.pdf", LAND)
    assert main(["datasheet", "check", str(p), str(mods[0])]) == 0
    out = capsys.readouterr().out
    for name in ("pitch", "pad", "pads", "span"):
        assert name in out
    assert "unchecked" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet_cli.py -q -k read_prints`
Expected: FAIL, `argparse` rejects `--read`

- [ ] **Step 3: Write minimal implementation**

In `src/placemat/cli.py`, add to the `datasheet` parser:

```python
    dsp.add_argument("--read", action="store_true",
                     help="the facts the sheet could be made to yield, with their provenance")
```

`check` is a form of the same command rather than a second one, recognised by
its first positional, which keeps one `datasheet` entry in the help. Change the
existing `pdf` positional's help text and add `rest` and the check flags beside
it (the `pdf` argument itself already exists from the index plan):

```python
    dsp.add_argument("pdf", help="a datasheet PDF, or the word `check`")
    dsp.add_argument("rest", nargs="*", help="for `check`: <pdf> <footprint.kicad_mod>")
    dsp.add_argument("--pitch", type=float, default=None, help="check: the pitch the sheet requires, mm")
    dsp.add_argument("--pad", default=None, metavar="WxH", help="check: the pad size the sheet requires, mm")
    dsp.add_argument("--pads", type=int, default=None, help="check: how many pads the sheet shows")
    dsp.add_argument("--span", type=float, default=None, help="check: the span across the pads, mm")
    dsp.add_argument("--tol", type=float, default=0.02, help="how far a value may differ and still agree, mm")
```

and in `cmd_datasheet`, before anything else:

```python
    if args.pdf == "check":
        return _datasheet_check(args)
```

with:

```python
def _expected_from(args) -> dict:
    """Only the values a flag actually set. A check nobody asked for is
    reported as unchecked, never as passed."""
    out = {}
    if args.pitch is not None:
        out["pitch"] = args.pitch
    if args.pads is not None:
        out["pads"] = args.pads
    if args.span is not None:
        out["span"] = args.span
    if args.pad:
        w, _, h = args.pad.lower().partition("x")
        out["pad"] = (float(w), float(h))
    return out


def _datasheet_check(args) -> int:
    from . import datasheet as ds
    from .kicad.read import read_footprint
    from .pdf import read as pdf
    if len(args.rest) != 2:
        console.say("datasheet", "check takes a datasheet and a footprint: "
                                 "placemat datasheet check <pdf> <footprint.kicad_mod>")
        return 1
    pdf_path, mod = Path(args.rest[0]), Path(args.rest[1])
    try:
        pages = pdf.page_count(pdf_path)
        by_page = {}
        for n in range(1, pages + 1):
            runs = pdf.text_runs(pdf_path, n)
            if not args.no_ocr and pdf.have_ocr() and pdf.text_is_thin(runs):
                runs = runs + pdf.ocr_runs(pdf_path, n, Path(args.out or pdf_path.parent), args.dpi)
            by_page[n] = (runs, ())
    except pdf.PdfError as e:
        console.say("datasheet", str(e))
        return 1
    fp, digest = read_footprint(mod)
    got = ds.compare(_expected_from(args), fp.pads, ds.facts(by_page), args.tol)
    if args.json:
        console.data(json.dumps({"pdf": str(pdf_path), "footprint": str(mod),
                                 "sha256": digest, "checks": ds.check_rows(got)}, indent=2))
    else:
        console.say("check", "%s against %s" % (mod.name, pdf_path.name))
        console.lines("check", "\n".join(ds.check_lines(got)))
    return 1 if any(c.verdict == "MISMATCH" for c in got) else 0
```

and in `cmd_datasheet`, after `found = ds.index(by_page)`:

```python
    if args.read:
        sourced = ds.facts(by_page)
        if args.json:
            console.data(json.dumps({"pdf": str(path), "facts": ds.read_rows(sourced)}, indent=2))
            return 0
        console.lines("datasheet", "\n".join(ds.read_lines(path.stem, sourced)))
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/placemat/cli.py tests/test_datasheet_cli.py
git commit -m "placemat datasheet --read, and check against a footprint"
```

---

## Task 8: Against the real connector, then the documentation

**Files:**
- Modify: `skills/placemat/references/api.md`, `skills/placemat/SKILL.md`, `skills/placemat/references/migration.md`, `src/placemat/__init__.py`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Test: `tests/test_datasheet_corpus.py`, `tests/test_describe.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_datasheet_corpus.py
@pytest.mark.skipif(not TYPEC.exists(), reason="no TYPE-C datasheet")
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not here")
def test_the_connectors_dimension_stack_is_sourced_with_confidence(tmp_path):
    """0.50 1.50 2.50 3.50 5.05 6.15 6.65 are on the sheet and readable only
    off the render. 4.55 is there too and tesseract reads it as 4.95, which is
    why a sourced number carries its confidence."""
    runs = read.ocr_runs(TYPEC, 1, tmp_path)
    found = ds.facts({1: (runs, ())})
    dims = {round(f.value, 2) for f in found if f.name == "dimension"}
    assert {0.5, 1.5, 2.5, 3.5, 5.05, 6.15, 6.65} <= dims
    assert all(f.confidence >= 70 for f in found if f.source == "ocr")
```

```python
# append to tests/test_describe.py
def test_the_docs_cover_read_and_check():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "--read" in api and "datasheet check" in api
    mig = Path("skills/placemat/references/migration.md").read_text()
    assert "0.13" in mig
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_datasheet_corpus.py tests/test_describe.py -q -k "dimension_stack or read_and_check"`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `api.md`, extend the `datasheet` line and add after the existing paragraph:

```
placemat datasheet <pdf> [--show PAGE|TOPIC] [--read] [--no-ocr] [--out DIR] [--dpi N] [--json]
placemat datasheet check <pdf> <footprint.kicad_mod> [--pitch F] [--pad WxH] [--pads N] [--span F] [--tol F] [--json]
```

````markdown
`--read` prints the facts the sheet could be made to yield - its unit, its
scale, every dimension on it and the headings that name a topic - each with the
page, the position, the channel that read it and that channel's confidence. A
value that could not be sourced is absent rather than guessed.

`check` compares a `.kicad_mod` against what the sheet is said to require.
placemat cannot tell which decimal on a drawing is the pitch, so the values are
supplied as flags; what it does automatically is measure the footprint and say
whether the number you supplied appears on the sheet at all, which is what
makes an override safe rather than blind. Every check is reported including the
ones nobody supplied a value for, because a check missing from a report reads
as one that passed. Exit 1 when any check disagrees.

A page carrying almost no text of its own is read off its render with
`tesseract` when it is installed; `--no-ocr` turns that off. It costs about a
second and a half a page and only runs on pages under 200 characters.
````

In `SKILL.md`, extend the datasheet bullet:

> ... then `--show` that page. `placemat datasheet <pdf> --read` lists what
> could be sourced and where from, and `placemat datasheet check <pdf>
> <part>.kicad_mod --pitch ... --pad WxH --pads N` checks a footprint against
> it. A number placemat prints carries its provenance; a number it could not
> source is absent rather than guessed.

In `references/migration.md`, above `## To 0.12`:

````markdown
## To 0.13

Nothing to change. `placemat datasheet` gains `--read`, which lists the facts a
sheet could be made to yield with the page, position, channel and confidence
behind each, and `check`, which compares a `.kicad_mod` against values you
supply and says whether the sheet mentions them at all.

A page with almost no text of its own is now read off its render with
`tesseract` when that is installed. It is optional; `--no-ocr` turns it off.
OCR reads wrong as well as right - on the TYPE-C 31-M-12 it returns 4.95 for a
dimension the drawing gives as 4.55, at confidence 78 against 86 to 96 for its
correct neighbours - so a confidence travels with every sourced number and
`check` against a real footprint is what catches the rest.

placemat does not recover pad geometry from a drawing. On that same sheet the
contacts are drawn as hatching: 276 of the land-pattern view's 453 paths are
two-point line segments, and the largest group of equal boxes on the page is
outlined text. Pad values are supplied, corroborated and compared, not parsed.
````

- [ ] **Step 4: Run the whole suite and bump the version**

```bash
sed -i 's/__version__ = "0.12.0"/__version__ = "0.13.0"/' src/placemat/__init__.py
sed -i 's/"version": "0.12.0"/"version": "0.13.0"/' .claude-plugin/plugin.json .claude-plugin/marketplace.json
uv pip install -q -e .
.venv/bin/python -m pytest -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Plugin 0.13.0: datasheet --read and check"
```

---

## Acceptance criteria

1. `.venv/bin/python -m pytest -q` passes in full.
2. `TextRun` carries `source` and `confidence`; a run from the PDF's own text
   is `text` at 100.
3. tesseract's word-level TSV is grouped into lines by its block, paragraph
   and line columns, a line takes its weakest word's confidence, and words
   below the floor are dropped.
4. `ocr_runs` returns `TextRun` values, so nothing downstream learns a type.
5. Only a page under 200 characters is read off its render, and `--no-ocr`
   turns it off.
6. `RECOMMEND P.C.B LAYOUT(COMPONEN` matches the land keyword, and against the
   real TYPE-C the page reaches band `strong` with OCR on.
7. Every `Fact` carries name, value, page, box, source and confidence; a value
   that could not be sourced is absent rather than zero.
8. `--read` prints those facts with provenance and says so plainly when a sheet
   yields nothing.
9. `pitch_of`, `pad_size_of` and `span_of` are pure over pads, and
   `Board.pitch` delegates to `pitch_of` so a pitch has one definition.
10. `compare` reports every check including unsupplied ones as `unchecked`,
    never as passed, and a disagreement is `MISMATCH`.
11. A supplied value is corroborated against the sheet's own dimensions and
    reads `not on the page` when it is absent.
12. `check` exits 1 when any check disagrees and 0 when none does.
13. `--json` carries the same values as the tables for both `--read` and
    `check`.
14. Against the real TYPE-C, the dimension stack 0.50 1.50 2.50 3.50 5.05 6.15
    6.65 is sourced, every OCR fact carries confidence >= 70.
15. `api.md`, `SKILL.md` and `references/migration.md` carry `--read`, `check`
    and a `## To 0.13` section, and the migration note records both the OCR
    misread and that pad geometry is not recovered.
16. `git log --format=%B <base>..HEAD | grep -iE "claude|anthropic|session|co-authored"`
    returns nothing.
