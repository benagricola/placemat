"""`placemat preview`: place the board as a run does - the cached generation,
the settings, the fab profile, the script, the previous record replayed - and
draw the plan (preview.py), without writing the board, running DRC or
rendering it. The PNG comes from an external converter, run here; without
one the SVG is the preview."""
from __future__ import annotations

from contextlib import contextmanager
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
    png_problem: str = ""           # why there is no PNG, in words
    png_failure: dict | None = None  # the same as data: {"code": not_installed | timeout | failed | no_png, "tool", ["returncode"], ["detail"]}
    plan: object = None
    reused: str = ""
    reuse: dict | None = None       # what was reused as data (reuse.summary_record)
    lines: list = field(default_factory=list)
    seen_px_per_mm: float = 0.0
    model_edge: int = 0
    notes: list = field(default_factory=list)


def converter_command(template: str, svg, png, width: int) -> list:
    """The converter's argv: the template split as a shell would, each piece
    with {svg}, {png} and {width} filled in."""
    return [piece.format(svg=str(svg), png=str(png), width=int(width)) for piece in shlex.split(template)]


def convert_failure(template: str, svg, png, width: int) -> dict | None:
    """Run the converter. None when it wrote the PNG, else why not as data: {"code": "not_installed" | "timeout" | "failed" |
    "no_png", "tool": the program, "returncode" and "detail" (its own last line) for a failure}."""
    argv = converter_command(template, svg, png, width)
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return {"code": "not_installed", "tool": argv[0]}
    except subprocess.TimeoutExpired:
        return {"code": "timeout", "tool": argv[0], "limit_s": 300}
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or ["exit %d" % done.returncode])[-1]
        return {"code": "failed", "tool": argv[0], "returncode": done.returncode, "detail": last}
    if not Path(png).exists():
        return {"code": "no_png", "tool": argv[0]}
    return None


def convert_text(f: dict | None) -> str:
    """A `convert_failure` in words, "" for none."""
    if f is None:
        return ""
    if f["code"] == "not_installed":
        return "%s is not installed; the SVG is the preview" % f["tool"]
    if f["code"] == "timeout":
        return "%s took over %d s; the SVG is the preview" % (f["tool"], f["limit_s"])
    if f["code"] == "failed":
        return "%s failed: %s" % (f["tool"], f["detail"])
    return "%s wrote no PNG" % f["tool"]


def convert(template: str, svg, png, width: int) -> str:
    """Run the converter. "" when it wrote the PNG, else why not."""
    return convert_text(convert_failure(template, svg, png, width))


def resolve_like_last_run(script, lock_entries=None) -> tuple:
    """(board, plan, board source, last run's id): the script resolved as
    its last run resolved it - its cached generation, its replay record,
    the lock (or `lock_entries`) - without writing anything. What `lock
    --current` checks against the written board. A script that does not
    resolve is a ValueError saying why."""
    from .lock import path_for as lock_path, read as read_lock
    from .project import fab_profile, find_board
    from .report import latest_for
    from .runner import cached_generation, reuse_parts, scripted_board
    from . import settings as settings_mod
    script = Path(script).resolve()
    src = find_board(script)
    cfg = settings_mod.load(src.board_dir, script=script)
    generated = cached_generation(src) / src.pcb.name
    last = latest_for(src.board_dir / ".placemat" / "runs", src.name)
    if not generated.exists() or last is None or not src.pcb.exists():
        raise ValueError("%s has not been run yet: `placemat run %s` first" % (src.name, script.name))
    from . import reuse as reuse_mod
    from .layout import CriticalUnplaced, PlacementCollision
    from .lanes import EscapeError
    from .runner import RunFailure
    with settings_mod.bind(cfg):
        fab = fab_profile(src.board_dir)
        previous, _ = newest_record([(Path(last.paths.get("run_dir", "")) / "reuse.json", "run %s" % last.run_id)])
        lock_now = read_lock(lock_path(script)) if lock_entries is None else lock_entries
        from . import routes as routes_mod
        kept = routes_mod.read(routes_mod.path_for(script))        # drawn as the run drew them: which held is asked

        def build(keep_going):
            try:
                board = scripted_board(script, src, cfg, fab, keep_going=keep_going, pcb=generated)
            except RunFailure as e:
                raise ValueError("the script does not run: %s" % e)
            parts = reuse_parts(src, cfg, fab, pcb=generated)
            board.reuse_extra = "|".join(parts[k] for k in ("tool", "board", "settings", "fab"))
            return board

        # the keep_going the last run had: the one its replay record's context was made with; with no
        # record to say, a board written past a firm collision was written by a run that kept going
        board, known = build(False), False
        for kg in (False, True):
            board.keep_going = kg
            if previous is not None and previous.get("context") == reuse_mod.context_key(board, board.reuse_extra):
                known = True
                break
        else:
            board.keep_going = False
        try:
            plan = board.resolve(reuse=previous, lock=lock_now, routes=kept)
        except (PlacementCollision, CriticalUnplaced, EscapeError) as e:
            if known or board.keep_going:
                raise ValueError("the script does not place as it stands: %s" % str(e).splitlines()[0])
            board = build(True)
            try:
                plan = board.resolve(reuse=previous, lock=lock_now, routes=kept)
            except (PlacementCollision, CriticalUnplaced, EscapeError) as e2:
                raise ValueError("the script does not place as it stands: %s" % str(e2).splitlines()[0])
    return board, plan, src, last.run_id


def written_pads(pcb) -> dict:
    """{(instance, pad number): (x, y)} of a written board's pads, pads that
    share a number as one (the centre of their union, as the occupancy has it)."""
    from .kicad.read import read_board
    from .routes import _pad_centres
    return {(fp.inst, n): (c.x, c.y) for fp in read_board(pcb).footprints for n, c in _pad_centres(fp).items()}


def newest_record(candidates, memo: dict | None = None) -> tuple:
    """(record, where it came from) of the newest readable reuse record among
    `candidates` - (path, label) pairs - or (None, None). `memo`, kept by the
    caller, holds {path: (mtime_ns, record)}: a file not modified since it was
    read is not read again."""
    best = None
    for path, label in candidates:
        path = Path(path)
        if not path.exists():
            continue
        held = memo.get(str(path)) if memo is not None else None
        if held is not None and held[0] == path.stat().st_mtime_ns:
            record = held[1]
        else:
            record = reuse_mod.read(path)
            if record is not None and memo is not None:
                memo[str(path)] = (path.stat().st_mtime_ns, record)
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


@dataclass
class Resolved:
    """What resolving a script for a view leaves: the board it ran against,
    the plan, the settings and fab profile bound for it, the record replayed
    and where that came from, and what it wrote beside."""
    src: object
    cfg: object
    board: object
    plan: object
    previous: object
    source: object
    parts: dict
    out: Path
    stale: dict | None = None       # why the cached generation is out of date (runner.stale_record), None when it is not


@contextmanager
def resolved(script, out=None, explore=None, quiet: bool = False, progress=None, on_step=None, on_begin=None, cache=None,
             on_board=None, fresh: bool = False, overlay=None, resumable: bool = False):
    """`_resolved` with `overlay` ({path: text}), when given, read in place of those files on disk and nothing written: the
    studio's try of a suggestion. The last record is replayed from as ever; the try writes none of its own."""
    from . import context
    with context.overlay(overlay):
        with _resolved(script, out, explore, quiet, progress, on_step, on_begin, cache, on_board, fresh, keep_record=not overlay,
                       resumable=resumable and not overlay) as r:
            yield r


@contextmanager
def _resolved(script, out=None, explore=None, quiet: bool = False, progress=None, on_step=None, on_begin=None, cache=None,
              on_board=None, fresh: bool = False, keep_record: bool = True, resumable: bool = False):
    """Place the board as a run does - the cached generation, the settings,
    the fab profile, the script, the newest of the last view's record and the
    last run's replayed - and write nothing but this view's own record. The
    settings are bound while the caller holds the result. `progress` and
    `on_step` are `Board.resolve`'s; `on_board` is called with the board once the script has run on it, before it resolves. `cache`, a dict the caller keeps between
    calls, holds the generation read and its digests: a view resolving again
    does not read the board file again unless it changed. `resumable`: the steps finished are also written as they are made
    (reuse.PartialLog), so a resolve that was stopped or died leaves them for the next one to replay."""
    from .project import fab_profile, find_board, note_views
    from .report import latest_for
    from .runner import cached_generation, reuse_parts, scripted_board, stale_record, stale_text
    from . import settings as settings_mod
    script = Path(script).resolve()
    src = find_board(script)
    cfg = settings_mod.load(src.board_dir, script=script)
    out = Path(out) if out else src.board_dir / ".placemat" / "views" / "preview"
    out.mkdir(parents=True, exist_ok=True)
    note_views(out)
    # The generation is read where the first run cached it. The board's own
    # file is the last run's placed board, and a preview leaves it alone.
    generated = cached_generation(src) / src.pcb.name
    if not generated.exists():
        raise ValueError("%s has no cached generation yet: run `placemat run %s` once, then preview"
                         % (src.name, script.name))
    stale = stale_record(src)
    if stale and not quiet:
        console.say("board", "the cached generation is out of date (%s): this preview shows the old one; "
                             "`placemat run %s` generates it again" % (stale_text(stale), script.name), level="finding")
    with settings_mod.bind(cfg):
        from . import timecap
        timecap.arm(cfg)                        # --max-time, --step-warn, --step-limit, when the command has them
        fab = fab_profile(src.board_dir)
        stamp = (generated.stat().st_mtime_ns, generated.stat().st_size, fab.courtyard_excess)
        held = cache.get("generation") if cache is not None else None
        geometry = held[1] if held is not None and held[0] == stamp else None
        board = scripted_board(script, src, cfg, fab, keep_going=True, pcb=generated, geometry=geometry)
        if cache is not None and geometry is None:
            cache["generation"] = (stamp, board.geometry)
        digest = cache.get("digest") if cache is not None else None
        parts = reuse_parts(src, cfg, fab, pcb=generated, board_digest=digest[1] if digest and digest[0] == stamp else None)
        if cache is not None:
            cache["digest"] = (stamp, parts["board"])
        board.reuse_extra = "|".join(parts[k] for k in ("tool", "board", "settings", "fab"))
        if on_board is not None:
            on_board(board)
        runs = src.board_dir / ".placemat" / "runs"
        candidates = [(out / "reuse.json", "the last preview")]
        try:
            last = latest_for(runs, src.name)
            if last is not None:
                candidates.append((Path(last.paths.get("run_dir", "")) / "reuse.json", "run %s" % last.run_id))
        except (ValueError, TypeError, KeyError, OSError):
            pass
        previous, source = newest_record(candidates, memo=None if cache is None else cache.setdefault("records", {}))
        partial = reuse_mod.PartialLog(out / "reuse.partial.jsonl") if resumable and keep_record else None
        if partial is not None and not fresh:       # a preview of these inputs that was stopped left its finished steps
            died = reuse_mod.read_partial(partial.path)
            if died is not None and reuse_mod.better_of(previous, died) is died:
                previous, source = died, "the interrupted preview"
        if fresh:                               # a full resolve: nothing is replayed from an earlier record
            previous, source = None, ""
        from . import explore as explore_mod, stop
        say = (lambda stage, text: None) if quiet else (lambda stage, text: console.say(stage, text))
        try:
            with timecap.cap_only():            # an explore's own resolves are not timed step by step
                lock_entries, explored = explore_mod.before_resolve(
                    script, board, explore_mod.BoardFactory(script, src, cfg, fab, True, board.geometry),
                    explore, say)
        except stop.Stopped as s:
            s.stage = s.stage or "explore"
            raise
        from . import routes as routes_mod
        try:
            plan = board.resolve(reuse=previous, lock=lock_entries, routes=routes_mod.read(routes_mod.path_for(script)),
                                 progress=progress, on_step=on_step, on_begin=on_begin, partial=partial)
        except stop.Stopped as s:
            s.stage = s.stage or "resolve"
            raise
        timecap.placement_done()                # the placement is in hand: the cap is lifted for the drawing
        held = explore_mod.lock_summary(plan)
        if held and not quiet:
            console.say("lock", held)
        kept = routes_mod.summary(plan)
        if kept and not quiet:
            console.say("adopted", kept)
        plan.reuse["parts"] = parts
        if keep_record:
            reuse_mod.write(out / "reuse.json", plan.reuse)
        if partial is not None:
            partial.remove()
        yield Resolved(src, cfg, board, plan, previous, source, parts, out, stale)


def preview(script, faces=("front", "back"), svg_only: bool = False, out=None, heat: bool = True,
            links: bool = True, copper: bool = True, region=None, around: str | None = None,
            margin: float = 5.0, quiet: bool = False, explore=None, tags: bool = True) -> Preview:
    from .board_geometry import members_of
    from .preview import draw_annotated
    from .project import find_board
    from .values import Box
    script = Path(script).resolve()
    out = Path(out) if out else find_board(script).board_dir / ".placemat" / "views" / "preview"
    with resolved(script, out, explore=explore, quiet=quiet, resumable=True) as r:
        src, cfg, plan, previous, source = r.src, r.cfg, r.plan, r.previous, r.source
        if around is not None:
            fps = [fp for s in plan.steps if s.item == around and s.placement is not None
                   for fp in members_of(plan._items[around])]
            if not fps:
                raise ValueError("%s is not placed, so there is nothing to draw round" % around)
            box = Box.union([plan.occupancy.items[fp.ref].body for fp in fps])
            region = box.inflate(margin)
        text, notes = draw_annotated(plan, faces=faces, heat=heat, links=links, copper=copper, region=region, tags=tags,
                                     title="%s - preview%s" % (src.name, "" if region is None else " (zoomed)"))
        svg = out / "preview.svg"
        svg.write_text(text)
        result = Preview(svg, None, plan=plan, reused=reuse_mod.summary(plan.reuse, previous, source),
                         reuse=reuse_mod.summary_record(plan.reuse, previous, source), notes=notes)
        if not svg_only:
            png = out / "preview.png"
            if png.exists():
                png.unlink()
            width = int(math.ceil(svg_width_mm(text) * cfg.preview_px_per_mm))
            if cfg.preview_model_edge_px > 0:
                result.seen_px_per_mm = seen_px_per_mm(*svg_size_mm(text), cfg.preview_px_per_mm,
                                                       cfg.preview_model_edge_px)
                result.model_edge = cfg.preview_model_edge_px
            result.png_failure = convert_failure(cfg.preview_converter, svg, png, width)
            result.png_problem = convert_text(result.png_failure)
            result.png = None if result.png_failure else png
    return result
