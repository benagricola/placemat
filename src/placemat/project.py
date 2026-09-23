"""Finds a script's board: the .zen beside it that declares Board(...),
Project(...) or a module fragment's Layout(...) - the stdlib writes Layout()
as Project(schematic=False), and a board that wants a generated schematic
declares Project() itself. Also reads the nearest fab-profile.json."""
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
    generate_args: tuple = ()       # extra `pcb layout` arguments the script asks for (`# placemat generate: ...`)

    @property
    def pcb(self) -> Path:
        return self.layout_dir / "layout.kicad_pcb"


_BOARD_RE = re.compile(r"\b(Board|Layout|Project)\s*\(", re.S)
_NAME_RE = re.compile(r'\bname\s*=\s*"([^"]+)"')
_LAYOUT_RE = re.compile(r'\b(?:layout_path|path)\s*=\s*"([^"]+)"')
_NO_LAYOUT_RE = re.compile(r"\blayout\s*=\s*False\b")
_GENERATE_RE = re.compile(r"^#\s*placemat generate:\s*(.+)$", re.M)


def generate_args_of(script: Path) -> tuple:
    """Arguments a script's header asks `pcb layout` to run with, e.g.
    `# placemat generate: --config switch_style=side` for a variant."""
    if not script.is_file():
        return ()
    m = _GENERATE_RE.search(script.read_text(errors="replace")[:4000])
    return tuple(m.group(1).split()) if m else ()


def find_board(script_or_dir) -> BoardSource:
    """The board a script is for: the .zen beside it declaring Board(),
    Project() or Layout(). A declaration with `layout = False` has no layout
    and is not a candidate. When several remain, the script's name says which
    (`Main_layout.py` means the one named Main)."""
    p = Path(script_or_dir).resolve()
    board_dir = p if p.is_dir() else p.parent
    wanted = p.stem[:-len("_layout")] if p.is_file() and p.stem.endswith("_layout") else None
    candidates = sorted(board_dir.glob("*.zen"))
    found, off = [], []
    for zen in candidates:
        text = zen.read_text(errors="replace")
        for m in _BOARD_RE.finditer(text):           # every Board()/Project()/Layout(): a module may declare one per variant
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
            if _NO_LAYOUT_RE.search(block):         # a sub-circuit with no layout of its own
                off.append(name)
                continue
            layout_dir = board_dir / (layout_m.group(1) if layout_m else "layout/%s" % name)
            found.append(BoardSource(name, zen, layout_dir, board_dir, generate_args_of(p) if p.is_file() else ()))
    if not found:
        raise FileNotFoundError("no .zen declaring Board(name=...), Project(name=...) or Layout(name=...) in %s (looked at %s)%s" % (
            board_dir, ", ".join(c.name for c in candidates) or "nothing",
            "; %s declare layout = False" % ", ".join(off) if off else ""))
    if len(found) == 1:
        return found[0]
    for src in found:
        if src.name == wanted:
            return src
    raise FileNotFoundError("%s declares %d boards (%s); name the script <Board>_layout.py to say which" % (
        board_dir, len(found), ", ".join(s.name for s in found)))


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
