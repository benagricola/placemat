"""Runs one layout attempt: generate the board with pcb, execute the script,
resolve, write through pcbnew, run DRC, render, and save the run record."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from .console import configure, console
from .layout import Board
from .context import run_script
from . import checks, settings
from .project import BoardSource, fab_profile, find_board
from .report import (RunRecord, against_best, airwires_from_drc, comparable, congestion,
                     impact, is_better, run_id)


class RunFailure(Exception):
    def __init__(self, kind: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.kind, self.details = kind, details or {}


def run_metrics(plan, n_place: int, n_copper: int, extent_metrics: dict) -> dict:
    """What a run records of its plan, before DRC adds its own."""
    metrics = {"board": [round(plan.outline.width, 3), round(plan.outline.height, 3)] if plan.outline else None,
               "findings": len(plan.findings), "placed": n_place, "copper_ops": n_copper,
               "seeded_by_net": dict(plan.seeded_by_net), **extent_metrics}
    if plan.solve:
        metrics["solve"] = dict(plan.solve)
    if plan.pocketed:
        metrics["pocketed"] = len(plan.pocketed)
    if plan.footprints:
        metrics["footprints"] = len(plan.footprints)
    return metrics


@dataclass
class RunResult:
    record: RunRecord
    run_dir: Path
    generated: bool
    impact_text: str = ""
    plan: object = None
    # How this run is worse than the best of its family, or None. A run can be
    # `ok` and still have regressed: it placed, but worse than before.
    regressed: str | None = None

    @property
    def status(self):
        return self.record.status


def _say(quiet, *parts, level=None):
    """Kept for the generate() helper: routes to the console."""
    if quiet:
        return
    text = " ".join(str(p) for p in parts)
    stage, _, rest = text.partition("   ")
    console.say(stage.strip() or "note", rest.strip(), level=level)


def _sh(cmd, cwd, log: Path, timeout: int, env=None) -> tuple[int, float]:
    t0 = time.time()
    with open(log, "w") as f:
        f.write("$ %s\n(cwd %s)\n\n" % (" ".join(str(c) for c in cmd), cwd))
        f.flush()
        try:
            proc = subprocess.run([str(c) for c in cmd], cwd=str(cwd), stdout=f, stderr=subprocess.STDOUT,
                                  timeout=timeout, env=env)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            f.write("\nTIMEOUT after %ds\n" % timeout)
            rc = -1
    return rc, time.time() - t0


def _tail(path: Path, n: int = 12) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def generate(src: BoardSource, run_dir: Path, fresh: bool, quiet: bool,
             timeout: int = 900) -> bool:
    """Put a freshly generated (unscripted) board in src.layout_dir. A copy of
    the generation is cached beside the runs so a rerun of the script does not
    pay for `pcb layout` again; `fresh` forces it. Returns True when the
    generator ran."""
    cache = src.board_dir / ".placemat" / "generated" / src.name
    log = run_dir / "generate.log"
    if cache.exists() and not fresh:
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(cache, src.layout_dir)
        log.write_text("restored the cached generation from %s\n" % cache)
        _say(quiet, "board   restored from cache (%s)" % cache.relative_to(src.board_dir))
        return False
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    shutil.rmtree(src.layout_dir, ignore_errors=True)
    src.layout_dir.mkdir(parents=True, exist_ok=True)
    _say(quiet, "board   generating %s with pcb layout ..." % src.zen.name)
    cmd = ["pcb", "layout", "--no-open"] + list(src.generate_args) + [src.zen.name]
    rc, dt = _sh(cmd, src.board_dir, log, timeout, env)
    if rc != 0 or not src.pcb.exists():
        raise RunFailure("generation", "Schematic generation failed",
                         {"command": " ".join(cmd), "cwd": str(src.board_dir),
                          "exit_code": rc, "log": str(log), "tail": _tail(log)})
    shutil.rmtree(cache, ignore_errors=True)
    shutil.copytree(src.layout_dir, cache)
    _say(quiet, "board   generated in %.0fs" % dt)
    return True


def keep_route(final_dir: Path, staging: Path) -> None:
    """Carry a previous run's routed copy into the run that replaces it.

    A run directory is named by a hash of the script, the generated board, the
    tool version and the settings, so a rerun that lands on the same id writes
    a byte-identical board: the route taken on the old one is still a route of
    this one. Replacing the directory without this loses minutes of routing
    and nothing says it has gone.

    A route this run has already produced wins: the routing path writes into
    the run directory itself, and a preserved older one must never displace a
    fresher one."""
    previous = final_dir / "route"
    if previous.is_dir() and not (staging / "route").exists():
        shutil.move(str(previous), str(staging / "route"))


def run(script, label: str | None = None, fresh: bool = False, render: bool = True, drc: bool = True,
        quiet: bool = False, verbose: bool = False, route: bool = False, route_quick: bool = True,
        route_exclude=(), keep_going: bool = False, overrides=None) -> RunResult:
    """One layout attempt, with this board's settings resolved and bound for
    the whole of it: the deep geometry helpers read the binding, and the run
    id carries the settings so a changed one cannot collide with a previous
    run and delete it."""
    script = Path(script).resolve()
    src = find_board(script)
    cfg = settings.load(src.board_dir, overrides=overrides or {})
    with settings.bind(cfg):
        return _run(script, src, cfg, label=label, fresh=fresh, render=render, drc=drc,
                    quiet=quiet, verbose=verbose, route=route, route_quick=route_quick,
                    route_exclude=route_exclude, keep_going=keep_going)


def _run(script, src, cfg, label: str | None = None, fresh: bool = False, render: bool = True,
         drc: bool = True, quiet: bool = False, verbose: bool = False, route: bool = False,
         route_quick: bool = True, route_exclude=(), keep_going: bool = False) -> RunResult:
    configure(quiet=quiet)
    say = console.say
    runs = src.board_dir / ".placemat" / "runs"
    staging = runs / ("." + time.strftime("%Y%m%d-%H%M%S-") + str(os.getpid()))
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    run_dir = staging
    rec = RunRecord(run_id="", board=src.name, status="running",
                    paths={"pcb": str(src.pcb), "script": str(script)})
    say("run", "%s: %s" % (src.name, script.relative_to(src.board_dir)))
    generated = False
    plan = None
    try:
        t0 = time.time()
        generated = generate(src, run_dir, fresh, quiet, cfg.timeout_generate)
        rec.timing_s["generate"] = round(time.time() - t0, 1)
        # The run's name: a hash of the script, the generated board and the tool.
        from . import __version__
        rid = run_id(script.read_text(), src.pcb.read_bytes(), __version__, cfg.json())
        final_dir = runs / rid
        keep_route(final_dir, staging)
        shutil.rmtree(final_dir, ignore_errors=True)
        staging.rename(final_dir)
        run_dir = final_dir
        rec.run_id = rid
        rec.paths["run_dir"] = str(run_dir)
        files = sorted({v for v in cfg.sources.values() if v not in ("default", "flag")})
        if files:
            rec.paths["settings_files"] = files
        if label:
            alias = runs / label
            if alias.is_symlink() or alias.exists():
                alias.unlink() if alias.is_symlink() else shutil.rmtree(alias)
            alias.symlink_to(rid)
            rec.paths["label"] = label
        say("id", "%s%s" % (rid, ("  (label %s)" % label) if label else ""))

        from .kicad.read import read_board
        from .kicad.write import apply_plan, finish_board, render_board
        from .kicad.drc import run_drc

        fab = fab_profile(src.board_dir)
        t0 = time.time()
        geometry = read_board(src.pcb, courtyard_excess_mm=fab.courtyard_excess)
        board = Board(geometry, via_drill=fab.via_drill, via_size=fab.via_size, keep_going=keep_going,
                      courtyard_excess=fab.courtyard_excess, settings=cfg,
                      component_spacing=fab.component_spacing)
        try:
            run_script(script, board)
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            frames = [f for f in tb if Path(f.filename).resolve() == script]
            where = frames[-1] if frames else None
            raise RunFailure("script", "Layout script failed", {
                "script": str(script), "line": where.lineno if where else None,
                "source": where.line if where else None, "error": "%s: %s" % (type(e).__name__, e),
                "traceback": "".join(traceback.format_exception(e))})
        log_lines = []

        from .layout import STEP_HEADER
        log_lines.append(STEP_HEADER)
        if verbose:
            say("step", STEP_HEADER, level="note")

        def progress(line):
            log_lines.append(line)
            if verbose:
                say("bridge" if line.strip().startswith("bridge:") else "step", line.strip())
        from .layout import CriticalUnplaced, PlacementCollision
        try:
            plan = board.resolve(progress=progress)
        except PlacementCollision as e:
            (run_dir / "script.log").write_text("\n".join(log_lines) + "\n")
            raise RunFailure("placement", "Firm placements collide; fix the script (or --keep-going to see the rest)",
                             {"collisions": e.collisions, "tail": "\n".join(e.collisions)})
        except CriticalUnplaced as e:
            (run_dir / "script.log").write_text("\n".join(log_lines) + "\n")
            apply_plan(src.pcb, e.plan)                      # the board as it stood when the critical item failed
            finish_board(src.pcb, fab, refs_to_fab=getattr(board, "refs_on_fab", True))
            shutil.copy(src.pcb, run_dir / "layout.kicad_pcb")
            if render:
                render_board(src.pcb, run_dir / "render.log", both_faces=True)
            raise RunFailure("placement", str(e), {"item": e.key, "tail": "board written as it stood: %s" % src.pcb})
        (run_dir / "script.log").write_text("\n".join(log_lines) + "\n")
        rec.timing_s["resolve"] = round(time.time() - t0, 1)
        n_place = sum(1 for s in plan.steps if s.placement is not None)
        n_copper = sum(s.ops for s in plan.steps)
        say("script", "%d placed, %d copper op(s), %d finding(s)  (%.1fs)" % (
            n_place, n_copper, len(plan.findings), rec.timing_s["resolve"]))
        from .report import extent_of
        ext = extent_of(plan)
        extent_metrics = {}
        if ext is not None:
            say("script", "extent %.2f x %.2f mm, %.0f%% of it empty" % (ext.width, ext.height, 100 * ext.empty))
            extent_metrics = {"extent": [round(ext.width, 3), round(ext.height, 3)], "empty": round(ext.empty, 3)}
        for f in plan.findings[: (50 if verbose else 8)]:
            say("finding", f, level="finding")
        if len(plan.findings) > 8 and not verbose:
            say("finding", "... %d more in %s" % (len(plan.findings) - 8, run_dir / "run.json"), level="finding")

        t0 = time.time()
        apply_plan(src.pcb, plan)
        finish_board(src.pcb, fab, refs_to_fab=getattr(board, "refs_on_fab", True))
        rec.timing_s["write"] = round(time.time() - t0, 1)
        shutil.copy(src.pcb, run_dir / "layout.kicad_pcb")
        say("board", "written %s (%.1fs)" % (src.pcb.relative_to(src.board_dir), rec.timing_s["write"]))

        if plan.seeded_by_net:
            top = plan.seeded_by_net.most_common(4)
            more = len(plan.seeded_by_net) - len(top)
            say("seeded", ", ".join("%s %d" % kv for kv in top) + (", +%d more" % more if more else ""))
        if plan.footprints:
            say("footprints", "%d courtyard(s) understate their part: %s%s" % (
                len(plan.footprints), "; ".join(plan.footprints[:8]), "; ..." if len(plan.footprints) > 8 else ""))
        if plan.pocketed:
            say("pocketed", "%d item(s) had no room by what they connect to and took a pocket: %s" % (
                len(plan.pocketed), ", ".join(plan.pocketed[:8]) + (", ..." if len(plan.pocketed) > 8 else "")))
        metrics = run_metrics(plan, n_place, n_copper, extent_metrics)
        if drc:
            t0 = time.time()
            report = run_drc(src.pcb, run_dir / "drc.json")
            aw = airwires_from_drc(json.loads((run_dir / "drc.json").read_text()))
            free = plan.occupancy.free_area()
            cong = congestion(aw["crossings"], free)
            metrics.update({"drc_real": report.real, "outstanding": report.outstanding, "other": report.other,
                            "unconnected": report.unconnected, "airwire_mm": aw["total_mm"],
                            "crossings": aw["crossings"], "crossings_per_net": aw["crossings_per_net"],
                            "free_area_mm2": round(free, 1), "congestion": cong,
                            "open_nets": dict(report.open_nets)})
            rec.timing_s["drc"] = round(time.time() - t0, 1)
            say("check", "%s | airwires %d, %.1f mm, %d crossings, congestion %s  (%.1fs)" % (
                report.summary(), aw["count"], aw["total_mm"], aw["crossings"],
                "-" if cong is None else "%.2f/cm2" % cong, rec.timing_s["drc"]))
            busiest = list(aw["crossings_per_net"].items())[:5]
            if busiest:
                say("check", "crossings by net: " + ", ".join("%s %d" % kv for kv in busiest))
        # The design checks, on the board as written: the same judgement as
        # `placemat check`, so a failed hot loop or an over-temperature part
        # is in the run record rather than in a command nobody ran.
        rec.metrics = metrics                 # the checks count into this same dict
        t0 = time.time()
        verdicts = checks.run_checks(read_board(src.pcb), **checks.kwargs_from(cfg))
        for line in checks.record(rec, verdicts):
            say("checks", line)
        rec.timing_s["checks"] = round(time.time() - t0, 1)
        if route:
            from .kicad.route import route_board
            t0 = time.time()
            say("route", "%s routing on a copy of the board ..." % ("quick" if route_quick else "full"))
            report = route_board(src.pcb, run_dir / "route", exclude_nets=set(plan.plane_nets) | set(route_exclude),
                                 quick=route_quick)
            metrics["route"] = report.as_dict()
            metrics["closure_clean"] = report.closure_clean
            rec.timing_s["route"] = round(time.time() - t0, 1)
            say("route", "%s  (%.0fs)" % (report.summary(), rec.timing_s["route"]))
            for breach in report.keepout_breaches:
                say("route", breach, level="finding")
            if report.open_nets:
                worst = sorted(report.open_nets.items(), key=lambda kv: -kv[1])[:8]
                say("route", "still open: " + ", ".join("%s %d" % kv for kv in worst))
        if render:
            t0 = time.time()
            render_board(src.pcb, run_dir / "render.log", both_faces=getattr(board, "both_faces", False))
            rec.timing_s["render"] = round(time.time() - t0, 1)
            say("render", "%s  (%.1fs)" % (", ".join(p.name for p in src.layout_dir.glob("layout*.png")), rec.timing_s["render"]))
        rec.metrics = metrics
        rec.placements = {s.item: {"x": s.placement.location.x, "y": s.placement.location.y,
                                   "rotation": s.placement.rotation, "face": s.placement.face.value}
                          for s in plan.steps if s.placement is not None and s.kind != "block"}
        rec.cutouts = {n: {"x": c.centre.x, "y": c.centre.y, "rotation": c.rotation}
                       for n, c in plan.cutouts_placed.items()}
        rec.steps = [{"item": s.item, "kind": s.kind,
                      "freedom": s.freedom.value if s.freedom else None,
                      "priority": s.priority.value if s.priority else None,
                      "rank": s.rank, "rank_of": s.rank_of, "note": s.note,
                      "why": s.why, "moved_mm": round(s.moved_mm, 3), "ops": s.ops} for s in plan.steps]
        rec.findings = list(plan.findings)
        rec.status = "ok"
    except RunFailure as e:
        rec.status = "failed"
        rec.failure = {"kind": e.kind, "message": str(e), **e.details}
        say("fail", str(e), level="fail")
        for k in ("script", "line", "source", "error", "command", "cwd", "exit_code", "log"):
            if e.details.get(k) is not None:
                say("fail", "%-9s %s" % (k, e.details[k]))
        if e.details.get("tail"):
            console.lines("fail", e.details["tail"])
        if verbose and e.details.get("traceback"):
            console.lines("fail", e.details["traceback"])
    try:
        from .kicad.quiet import drain
        text = drain()
        if text:
            (run_dir / "kicad-stderr.log").write_text(text + "\n")
            rec.paths["kicad_stderr"] = str(run_dir / "kicad-stderr.log")
    except ImportError:
        pass
    if not rec.run_id:                       # generation failed before the id could be taken
        rec.run_id = run_dir.name.lstrip(".")
        rec.paths["run_dir"] = str(run_dir)
    regressed = None
    if rec.status == "ok":
        regressed = _against_best(rec, run_dir.parent / "best.json", say, cfg.best_airwire_noise)
    rec.save(run_dir / "run.json")
    latest = run_dir.parent / "latest.json"
    text = ""
    if rec.status == "ok":
        if latest.exists():
            try:
                previous = RunRecord.load(latest)
                if previous.run_id != rec.run_id:
                    text = impact(previous, rec)
                else:
                    text = "same inputs as the previous run: id %s again, nothing to compare" % rec.run_id
                (run_dir / "impact.txt").write_text(text + "\n")
                console.lines("impact", text)
            except (json.JSONDecodeError, TypeError):
                pass
        shutil.copy(run_dir / "run.json", latest)
    say("record", str(run_dir / "run.json"))
    return RunResult(rec, run_dir, generated, text, plan, regressed)


def _against_best(rec: RunRecord, best_path: Path, say, airwire_noise: float) -> str | None:
    """Judge a finished run against the best of its family - the runs whose
    script asked to place the same things - and record it if it is the new
    best. A regression becomes a finding naming the metric that got worse.

    It is appended after `metrics.findings` was counted, so the objective goes
    on measuring the layout rather than the verdict about it."""
    if not comparable(rec):
        say("best", "not judged: this run measured no DRC, so it has nothing to compare")
        return None
    said, prior = against_best(best_path, rec, airwire_noise)
    if said:
        rec.findings.append("worse than the best run of these parts: %s" % said)
        say("best", "worse than %s: %s" % (prior.run_id, said), level="fail")
    elif prior is None:
        say("best", "the first run of these parts, so the best so far")
    elif prior.run_id == rec.run_id or not is_better(rec, prior, airwire_noise):
        say("best", "matches %s, the best run of these parts" % prior.run_id)
    else:
        say("best", "better than %s: now the best run of these parts" % prior.run_id)
    return said
