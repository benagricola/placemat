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

from .layout import Board
from .context import run_script
from .project import BoardSource, fab_profile, find_board
from .report import RunRecord, airwires_from_drc, congestion, impact, run_id


class RunFailure(Exception):
    def __init__(self, kind: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.kind, self.details = kind, details or {}


@dataclass
class RunResult:
    record: RunRecord
    run_dir: Path
    generated: bool
    impact_text: str = ""
    plan: object = None

    @property
    def status(self):
        return self.record.status


def _say(quiet, *parts):
    if not quiet:
        print(*parts, flush=True)


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


def generate(src: BoardSource, run_dir: Path, fresh: bool, quiet: bool) -> bool:
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
    rc, dt = _sh(["pcb", "layout", "--no-open", src.zen.name], src.board_dir, log, 900, env)
    if rc != 0 or not src.pcb.exists():
        raise RunFailure("generation", "Schematic generation failed",
                         {"command": "pcb layout --no-open %s" % src.zen.name, "cwd": str(src.board_dir),
                          "exit_code": rc, "log": str(log), "tail": _tail(log)})
    shutil.rmtree(cache, ignore_errors=True)
    shutil.copytree(src.layout_dir, cache)
    _say(quiet, "board   generated in %.0fs" % dt)
    return True


def run(script, label: str | None = None, fresh: bool = False, render: bool = True, drc: bool = True,
        quiet: bool = False, verbose: bool = False, route: bool = False, route_quick: bool = True,
        route_exclude=()) -> RunResult:
    script = Path(script).resolve()
    src = find_board(script)
    runs = src.board_dir / ".placemat" / "runs"
    staging = runs / ("." + time.strftime("%Y%m%d-%H%M%S-") + str(os.getpid()))
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    run_dir = staging
    rec = RunRecord(run_id="", board=src.name, status="running",
                    paths={"pcb": str(src.pcb), "script": str(script)})
    _say(quiet, "run %s: %s" % (src.name, script.relative_to(src.board_dir)))
    generated = False
    plan = None
    try:
        t0 = time.time()
        generated = generate(src, run_dir, fresh, quiet)
        rec.timing_s["generate"] = round(time.time() - t0, 1)
        # The run's name: a hash of the script, the generated board and the tool.
        from . import __version__
        rid = run_id(script.read_text(), src.pcb.read_bytes(), __version__)
        final_dir = runs / rid
        shutil.rmtree(final_dir, ignore_errors=True)
        staging.rename(final_dir)
        run_dir = final_dir
        rec.run_id = rid
        rec.paths["run_dir"] = str(run_dir)
        if label:
            alias = runs / label
            if alias.is_symlink() or alias.exists():
                alias.unlink() if alias.is_symlink() else shutil.rmtree(alias)
            alias.symlink_to(rid)
            rec.paths["label"] = label
        _say(quiet, "id      %s%s" % (rid, ("  (label %s)" % label) if label else ""))

        from .kicad.read import read_board
        from .kicad.write import apply_plan, finish_board, render_board
        from .kicad.drc import run_drc

        fab = fab_profile(src.board_dir)
        t0 = time.time()
        geometry = read_board(src.pcb, courtyard_excess_mm=fab.courtyard_excess)
        board = Board(geometry, via_drill=fab.via_drill, via_size=fab.via_size)
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

        def progress(line):
            log_lines.append(line)
            if verbose:
                print("   " + line, flush=True)
        plan = board.resolve(progress=progress)
        (run_dir / "script.log").write_text("\n".join(log_lines) + "\n")
        rec.timing_s["resolve"] = round(time.time() - t0, 1)
        n_place = sum(1 for s in plan.steps if s.placement is not None)
        n_copper = sum(s.ops for s in plan.steps)
        _say(quiet, "script  %d placed, %d copper op(s), %d finding(s)  (%.1fs)" % (
            n_place, n_copper, len(plan.findings), rec.timing_s["resolve"]))
        for f in plan.findings[: (50 if verbose else 8)]:
            _say(quiet, "   ! " + f)
        if len(plan.findings) > 8 and not verbose:
            _say(quiet, "   ... %d more in %s" % (len(plan.findings) - 8, run_dir / "run.json"))

        t0 = time.time()
        apply_plan(src.pcb, plan)
        finish_board(src.pcb, fab, refs_to_fab=getattr(board, "refs_on_fab", True))
        rec.timing_s["write"] = round(time.time() - t0, 1)
        shutil.copy(src.pcb, run_dir / "layout.kicad_pcb")
        _say(quiet, "board   written %s (%.1fs)" % (src.pcb.relative_to(src.board_dir), rec.timing_s["write"]))

        metrics = {"board": [round(plan.outline.width, 3), round(plan.outline.height, 3)] if plan.outline else None,
                   "findings": len(plan.findings), "placed": n_place, "copper_ops": n_copper}
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
            _say(quiet, "check   %s | airwires %d, %.1f mm, %d crossings, congestion %s  (%.1fs)" % (
                report.summary(), aw["count"], aw["total_mm"], aw["crossings"],
                "-" if cong is None else "%.2f/cm2" % cong, rec.timing_s["drc"]))
            busiest = list(aw["crossings_per_net"].items())[:5]
            if busiest:
                _say(quiet, "        crossings by net: " + ", ".join("%s %d" % kv for kv in busiest))
        if route:
            from .kicad.route import route_board
            t0 = time.time()
            _say(quiet, "route   %s routing on a copy of the board ..." % ("quick" if route_quick else "full"))
            report = route_board(src.pcb, run_dir / "route", exclude_nets=set(plan.plane_nets) | set(route_exclude),
                                 quick=route_quick)
            metrics["route"] = report.as_dict()
            metrics["closure_clean"] = report.closure_clean
            rec.timing_s["route"] = round(time.time() - t0, 1)
            _say(quiet, "route   %s  (%.0fs)" % (report.summary(), rec.timing_s["route"]))
            if report.open_nets:
                worst = sorted(report.open_nets.items(), key=lambda kv: -kv[1])[:8]
                _say(quiet, "        still open: " + ", ".join("%s %d" % kv for kv in worst))
        if render:
            t0 = time.time()
            render_board(src.pcb, run_dir / "render.log", both_faces=getattr(board, "both_faces", False))
            rec.timing_s["render"] = round(time.time() - t0, 1)
            _say(quiet, "render  %s  (%.1fs)" % (", ".join(p.name for p in src.layout_dir.glob("layout*.png")), rec.timing_s["render"]))
        rec.metrics = metrics
        rec.placements = {s.item: {"x": s.placement.location.x, "y": s.placement.location.y,
                                   "rotation": s.placement.rotation, "face": s.placement.face.value}
                          for s in plan.steps if s.placement is not None}
        rec.steps = [{"item": s.item, "kind": s.kind, "priority": s.priority.value, "note": s.note,
                      "why": s.why, "moved_mm": round(s.moved_mm, 3), "ops": s.ops} for s in plan.steps]
        rec.findings = list(plan.findings)
        rec.status = "ok"
    except RunFailure as e:
        rec.status = "failed"
        rec.failure = {"kind": e.kind, "message": str(e), **e.details}
        _say(quiet, "\n%s" % e)
        for k in ("script", "line", "source", "error", "command", "cwd", "exit_code", "log"):
            if e.details.get(k) is not None:
                _say(quiet, "  %-9s %s" % (k, e.details[k]))
        if e.details.get("tail"):
            _say(quiet, "  --- last lines ---\n" + e.details["tail"])
        if verbose and e.details.get("traceback"):
            _say(quiet, e.details["traceback"])
    if not rec.run_id:                       # generation failed before the id could be taken
        rec.run_id = run_dir.name.lstrip(".")
        rec.paths["run_dir"] = str(run_dir)
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
                _say(quiet, text)
            except (json.JSONDecodeError, TypeError):
                pass
        shutil.copy(run_dir / "run.json", latest)
    _say(quiet, "record  %s" % (run_dir / "run.json"))
    return RunResult(rec, run_dir, generated, text, plan)
