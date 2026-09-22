"""What a datasheet page is about, decided from what is on it.

Pure: no PDF is opened here, so every rule is pinned by tests that run
anywhere. `pdf/read.py` produces the values this module scores.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .values import Box


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


# A decimal with a fractional part. A bare integer is a page number, a pin
# number or a year far more often than it is a dimension, so it is not one.
_DECIMAL = re.compile(r"(?<![\w.])(\d{1,3}\.\d{1,3})(?![\w.])")
_UNIT = ((re.compile(r"\bmm\b|\bmillimet", re.I), "mm"),
         (re.compile(r"\binch(es)?\b|\bmils?\b", re.I), "inch"))


# Nothing a drawing repeats is twenty times longer than it is wide except a
# rule or a border. The antenna's terminal-function page draws nine boxes of
# 1 x 42, and counting those made a page of prose look like a page of drawing.
MAX_PAD_ASPECT = 20.0

# Smaller than this in PDF points and a path cannot be sized meaningfully: it
# is a hatch stroke, a hairline or a border corner. A real pad on these
# drawings is a few points across.
MIN_PAD_SIDE = 0.5


def rectangles(paths) -> tuple:
    """The paths that are an axis-aligned box a pad could be."""
    out = []
    for p in paths:
        if not p.rect:
            continue
        w, h = p.box.width, p.box.height
        if w < MIN_PAD_SIDE or h < MIN_PAD_SIDE:
            continue
        if max(w, h) / min(w, h) > MAX_PAD_ASPECT:
            continue                    # a rule, a leader or a border
        out.append(p)
    return tuple(out)


def clusters(rects, tol: float = 0.5) -> list:
    """Rectangles of the same size, largest group first, in PDF points.

    This says a shape repeats on the page. It does NOT say the shape is a pad:
    on the TYPE-C sheet the biggest group is 183 boxes of 3 x 5 pt sitting on
    42 evenly spaced rows in the notes column - glyph strokes in outlined
    text. What the signal is good for is telling a page of drawing from a page
    of prose, which is the index's question. Finding the pads themselves is a
    different job and a harder one."""
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


TOPICS = ("land", "package", "rules", "pins")

# One vendor's words for a thing are not another's: the W3011 says "MECHANICAL
# DRAWING" and "PWB Layout" where TDK says "RECOMMENDED LAND PATTERN". Measured
# over 67 datasheets, a keyword list alone finds a land pattern on half of
# them, which is why it is one signal beside the geometry and never the answer.
KEYWORDS = {
    # `p\.?\s?[cw]\.?\s?b\.?` covers PCB, PWB and the dotted P.C.B that OCR
    # returns for the TYPE-C heading; without the dots that page stayed at
    # `fair` with the only evidence it had sitting unread.
    "land": (r"recommended land", r"land pattern", r"recommended pad",
             r"p\.?\s?[cw]\.?\s?b\.?\s*layout", r"mounting pad", r"solder pad",
             r"recommended solder", r"suggested (pad|land)", r"footprint"),
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

# The topics a drawing can argue for. Repeated drawn detail says "this page is
# a drawing", which narrows it to a land pattern or a package outline; it says
# nothing about a pin table or a paragraph of layout rules, and offering it to
# those made a text-free connector rank every topic alike.
_DRAWN_TOPICS = ("land", "package")


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


# A contents line names a topic and sits on page 2, so it beats the page that
# covers it. Dot leaders, or a trailing page number after them, are what make
# one recognisable without knowing the document's shape.
_CONTENTS = re.compile(r"\.{4,}\s*\d*\s*$|\.{6,}")


def is_contents(text: str) -> bool:
    """True for a line of a table of contents rather than a heading."""
    return bool(_CONTENTS.search(text.strip()))


def page_evidence(topic: str, runs, paths) -> tuple:
    """Everything on this page that argues it is about `topic`. Each item
    says what was seen, so a ranking can be judged instead of trusted."""
    out = []
    for r in runs:
        if is_contents(r.text):
            continue                    # a contents line points elsewhere
        if any(p.search(r.text) for p in _COMPILED[topic]):
            out.append(Evidence("keyword", '"%s"' % r.text.strip()[:60]))
            break
    if topic in _DRAWN_TOPICS:
        groups = clusters(rectangles(paths))
        if groups and groups[0][1] >= CLUSTER_FLOOR:
            (w, h), n = groups[0]
            out.append(Evidence("rects", "%d repeated %.3g x %.3g pt" % (n, w, h)))
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
            out.append("  %-4s %-13s %-7s nothing on any page argued for it"
                       % ("-", _TOPIC_NAME[c.topic], c.band))
            continue
        out.append("  p%-3d %-13s %-7s %s" % (
            c.page, _TOPIC_NAME[c.topic], c.band, ", ".join(e.detail for e in c.evidence)))
    best = [c for c in candidates if c.band != "none"]
    if best:
        out.append("  look: placemat datasheet <pdf> --show p%d" % best[0].page)
    return out


# tesseract scores every word; below this a word is noise rather than a read.
# Measured on the TYPE-C sheet: correct dimensions scored 86 to 96, a misread
# scored 78, and the rubbish scored 16 to 39.
MIN_OCR_CONFIDENCE = 70.0

# Under this many characters a page has not really got text of its own, and is
# worth the second and a half OCR costs. 7 of the 67 datasheets measured for
# this feature are like this, and they are the connectors and the inductors.
OCR_TEXT_FLOOR = 200


def runs_from_tsv(tsv: str, page: int, min_conf: float = MIN_OCR_CONFIDENCE) -> tuple:
    """tesseract's TSV, as one run per LINE.

    The TSV is one row per word. A run per word splits "RECOMMEND P.C.B
    LAYOUT" into three and no heading ever matches, so words are gathered by
    the block, paragraph and line columns tesseract already numbers them with.

    The floor is applied to the LINE, not the word, and a line passes when any
    word in it reads well. Dropping weak words first returned `UNIT: | SCALE:`
    for the TYPE-C's `UNIT: mm SCALE: 1:1`, losing the unit of the whole
    drawing: tesseract scores `mm` at 23 - two identical letters, small - while
    the `SCALE:` beside it scores 96 and both reads are right. Noise is a line
    with no good word in it, and that is what goes.

    The confidence reported is the weakest word's, because that is what a
    reader should judge by - but only among the words tesseract actually
    scored. It gives 0 to stray punctuation, the `_` and `|` in
    `UNIT: mm _ | SCALE:`, and a 0 there means "not a word" rather than "read
    badly"; letting one stand reported 0 for a line that was read correctly."""
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
        lines.setdefault((f[2], f[3], f[4]), []).append((left, top, width, height, conf, f[11]))
    out = []
    for words in lines.values():
        if max(w[4] for w in words) < min_conf:
            continue                    # nothing in this line read well
        text = " ".join(w[5] for w in words)
        box = Box(min(w[0] for w in words), min(w[1] for w in words),
                  max(w[0] + w[2] for w in words), max(w[1] + w[3] for w in words))
        scored = [w[4] for w in words if w[4] > 0]
        out.append(TextRun(page, text, box, source="ocr",
                           confidence=min(scored) if scored else max(w[4] for w in words)))
    return tuple(out)


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
        runs = by_page[page][0]
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
        seen.append(max(hit, key=lambda f: f.confidence))
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


def _shown(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, (tuple, list)):
        return " x ".join("%g" % x for x in v)
    return "%g" % v if isinstance(v, float) else str(v)


def check_lines(comparisons) -> list:
    out = []
    for c in comparisons:
        out.append("  %-6s %-14s %-14s %-9s %s" % (
            c.name, _shown(c.supplied), _shown(c.measured), c.verdict, c.corroboration))
    bad = [c for c in comparisons if c.verdict == "MISMATCH"]
    checked = [c for c in comparisons if c.verdict != "unchecked"]
    if not checked:
        out.append("  nothing was supplied to check against; --read the sheet first")
    elif bad:
        out.append("  %d of %d checks disagree" % (len(bad), len(checked)))
    else:
        out.append("  %d check(s) agree" % len(checked))
    return out


def _plain_value(v):
    return list(v) if isinstance(v, tuple) else v


def check_rows(comparisons) -> list:
    return [{"name": c.name, "supplied": _plain_value(c.supplied),
             "measured": _plain_value(c.measured), "verdict": c.verdict,
             "corroboration": c.corroboration} for c in comparisons]
