"""`placemat preview`: place the board as a run does - the cached generation,
the settings, the fab profile, the script, the previous record replayed - and
draw the plan (preview.py), without writing the board, running DRC or
rendering it. The PNG comes from an external converter, run here; without
one the SVG is the preview."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import re
import shlex
import subprocess

from .console import console
from . import reuse as reuse_mod


@dataclass
class Preview:
    svg: Path
    png: Path | None
    png_problem: str = ""
    plan: object = None
    reused: str = ""
    lines: list = field(default_factory=list)
    seen_px_per_mm: float = 0.0
    model_edge: int = 0
    notes: list = field(default_factory=list)


def converter_command(template: str, svg, png, width: int) -> list:
    """The converter's argv: the template split as a shell would, each piece
    with {svg}, {png} and {width} filled in."""
    return [piece.format(svg=str(svg), png=str(png), width=int(width)) for piece in shlex.split(template)]


def convert(template: str, svg, png, width: int) -> str:
    """Run the converter. "" when it wrote the PNG, else why not."""
    argv = converter_command(template, svg, png, width)
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return "%s is not installed; the SVG is the preview" % argv[0]
    except subprocess.TimeoutExpired:
        return "%s took over 300 s; the SVG is the preview" % argv[0]
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or ["exit %d" % done.returncode])[-1]
        return "%s failed: %s" % (argv[0], last)
    if not Path(png).exists():
        return "%s wrote no PNG" % argv[0]
    return ""


def newest_record(candidates) -> tuple:
    """(record, where it came from) of the newest readable reuse record among
    `candidates` - (path, label) pairs - or (None, None)."""
    best = None
    for path, label in candidates:
        path = Path(path)
        if not path.exists():
            continue
        record = reuse_mod.read(path)
        if record is None:
            continue
        stamp = path.stat().st_mtime
        if best is None or stamp > best[0]:
            best = (stamp, record, label)
    return (best[1], best[2]) if best else (None, None)


def seen_px_per_mm(width_mm: float, height_mm: float, px_per_mm: float, edge: int = 1568) -> float:
    """The resolution a model reading the PNG sees if it scales an image's
    long edge down to `edge` pixels before reading it - [preview] model_edge,
    an assumption about the model, which placemat cannot know."""
    long_px = max(width_mm, height_mm) * px_per_mm
    return px_per_mm * min(1.0, edge / long_px) if long_px > 0 else px_per_mm


def svg_size_mm(svg_text: str) -> tuple:
    m = re.search(r'viewBox="[-0-9.]+ [-0-9.]+ ([0-9.]+) ([0-9.]+)"', svg_text)
    return (float(m.group(1)), float(m.group(2))) if m else (100.0, 100.0)


def svg_width_mm(svg_text: str) -> float:
    m = re.search(r'viewBox="[-0-9.]+ [-0-9.]+ ([0-9.]+) ', svg_text)
    return float(m.group(1)) if m else 100.0


def preview(script, faces=("front", "back"), svg_only: bool = False, out=None, heat: bool = True,
            links: bool = True, copper: bool = True, region=None, around: str | None = None,
            margin: float = 5.0, quiet: bool = False, explore=None) -> Preview:
    from .board_geometry import members_of
    from .preview import draw_annotated
    from .project import fab_profile, find_board
    from .runner import RunRecord, cached_generation, reuse_parts, scripted_board, stale_inputs
    from . import settings as settings_mod
    from .values import Box
    script = Path(script).resolve()
    src = find_board(script)
    cfg = settings_mod.load(src.board_dir)
    out = Path(out) if out else src.board_dir / ".placemat" / "preview"
    out.mkdir(parents=True, exist_ok=True)
    # The generation is read where the first run cached it. The board's own
    # file is the last run's placed board, and a preview leaves it alone.
    generated = cached_generation(src) / src.pcb.name
    if not generated.exists():
        raise ValueError("%s has no cached generation yet: run `placemat run %s` once, then preview"
                         % (src.name, script.name))
    stale = stale_inputs(src)
    if stale and not quiet:
        console.say("board", "the cached generation is out of date (%s): this preview shows the old one; "
                             "`placemat run %s` generates it again" % (stale, script.name), level="finding")
    with settings_mod.bind(cfg):
        fab = fab_profile(src.board_dir)
        board = scripted_board(script, src, cfg, fab, keep_going=True, pcb=generated)
        parts = reuse_parts(src, cfg, fab, pcb=generated)
        board.reuse_extra = "|".join(parts[k] for k in ("tool", "board", "settings", "fab"))
        runs = src.board_dir / ".placemat" / "runs"
        candidates = [(out / "reuse.json", "the last preview")]
        if (runs / "latest.json").exists():
            try:
                last = RunRecord.load(runs / "latest.json")
                candidates.append((Path(last.paths.get("run_dir", "")) / "reuse.json", "run %s" % last.run_id))
            except (ValueError, TypeError, KeyError, OSError):
                pass
        previous, source = newest_record(candidates)
        from . import explore as explore_mod
        say = (lambda stage, text: None) if quiet else (lambda stage, text: console.say(stage, text))
        lock_entries, explored = explore_mod.before_resolve(
            script, board, explore_mod.BoardFactory(script, src, cfg, fab, True, board.geometry),
            explore, say)
        plan = board.resolve(reuse=previous, lock=lock_entries)
        held = explore_mod.lock_summary(plan)
        if held and not quiet:
            console.say("lock", held)
        plan.reuse["parts"] = parts
        reuse_mod.write(out / "reuse.json", plan.reuse)
        if around is not None:
            fps = [fp for s in plan.steps if s.item == around and s.placement is not None
                   for fp in members_of(plan._items[around])]
            if not fps:
                raise ValueError("%s is not placed, so there is nothing to draw round" % around)
            box = Box.union([plan.occupancy.items[fp.ref].body for fp in fps])
            region = box.inflate(margin)
        text, notes = draw_annotated(plan, faces=faces, heat=heat, links=links, copper=copper, region=region,
                                     title="%s - preview%s" % (src.name, "" if region is None else " (zoomed)"))
        svg = out / "preview.svg"
        svg.write_text(text)
        result = Preview(svg, None, plan=plan, reused=reuse_mod.summary(plan.reuse, previous, source), notes=notes)
        if not svg_only:
            png = out / "preview.png"
            if png.exists():
                png.unlink()
            width = int(math.ceil(svg_width_mm(text) * cfg.preview_px_per_mm))
            if cfg.preview_model_edge > 0:
                result.seen_px_per_mm = seen_px_per_mm(*svg_size_mm(text), cfg.preview_px_per_mm,
                                                       cfg.preview_model_edge)
                result.model_edge = cfg.preview_model_edge
            result.png_problem = convert(cfg.preview_converter, svg, png, width)
            result.png = None if result.png_problem else png
    return result
