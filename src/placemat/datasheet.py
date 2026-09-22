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
