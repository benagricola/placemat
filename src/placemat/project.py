"""Finds a script's board (the .zen beside it that declares Board(...)) and
reads the nearest fab-profile.json."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class BoardSource:
    name: str
    zen: Path
    layout_dir: Path
    board_dir: Path

    @property
    def pcb(self) -> Path:
        return self.layout_dir / "layout.kicad_pcb"


_BOARD_RE = re.compile(r"\bBoard\s*\(", re.S)
_NAME_RE = re.compile(r'\bname\s*=\s*"([^"]+)"')
_LAYOUT_RE = re.compile(r'\blayout_path\s*=\s*"([^"]+)"')


def find_board(script_or_dir) -> BoardSource:
    p = Path(script_or_dir).resolve()
    board_dir = p if p.is_dir() else p.parent
    candidates = sorted(board_dir.glob("*.zen"))
    for zen in candidates:
        text = zen.read_text(errors="replace")
        m = _BOARD_RE.search(text)
        if not m:
            continue
        block = text[m.end():]
        depth, end = 1, 0
        for i, ch in enumerate(block):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        block = block[:end]
        name_m, layout_m = _NAME_RE.search(block), _LAYOUT_RE.search(block)
        if not name_m:
            continue
        name = name_m.group(1)
        layout_dir = board_dir / (layout_m.group(1) if layout_m else "layout/%s" % name)
        return BoardSource(name, zen, layout_dir, board_dir)
    raise FileNotFoundError("no .zen declaring Board(name=...) in %s (looked at %s)" % (
        board_dir, ", ".join(c.name for c in candidates) or "nothing"))


@dataclass(frozen=True)
class FabProfile:
    via_drill: float = 0.3
    via_size: float = 0.6
    courtyard_excess: float = 0.10
    track_widths: tuple = tuple(round(0.15 + 0.05 * i, 2) for i in range(18))
    path: Path | None = None


def fab_profile(start) -> FabProfile:
    d = Path(start).resolve()
    for parent in (d, *d.parents):
        f = parent / "fab-profile.json"
        if f.exists():
            try:
                data = json.loads(f.read_text())
            except json.JSONDecodeError as e:
                raise ValueError("%s is not valid JSON: %s" % (f, e))
            via = data.get("via", {})
            tw = data.get("track_width_presets_mm")
            widths = FabProfile.track_widths
            if tw:
                n = int(round((tw["max"] - tw["min"]) / tw["step"])) + 1
                widths = tuple(round(tw["min"] + i * tw["step"], 2) for i in range(n))
            return FabProfile(via.get("default_drill_mm", 0.3), via.get("default_size_mm", 0.6),
                              data.get("courtyard", {}).get("excess_mm", 0.10), widths, f)
    return FabProfile()
