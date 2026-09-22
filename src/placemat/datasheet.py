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


# A decimal with a fractional part. A bare integer is a page number, a pin
# number or a year far more often than it is a dimension, so it is not one.
_DECIMAL = re.compile(r"(?<![\w.])(\d{1,3}\.\d{1,3})(?![\w.])")
_UNIT = ((re.compile(r"\bmm\b|\bmillimet", re.I), "mm"),
         (re.compile(r"\binch(es)?\b|\bmils?\b", re.I), "inch"))


def rectangles(paths) -> tuple:
    """The paths that are an axis-aligned box."""
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
        if any(p.search(r.text) for p in _COMPILED[topic]):
            out.append(Evidence("keyword", '"%s"' % r.text.strip()[:60]))
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
