"""Runs one layout attempt: generate the board with pcb, execute the script,
resolve, write through pcbnew, run DRC, render, and save the run record."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback

from .childenv import child_env
from .console import configure, console
from .layout import Board
from .context import run_script
from . import arrangement_run, checks, settings, stop
from .checkpoint import ResumeRefused
from .project import BoardSource, fab_profile, find_board, generator_inputs, script_fingerprint
from .report import (RunRecord, _drc_total, against_best, airwires_from_drc, best_for, comparable, congestion,
                     family_of, impact, is_better, latest_for, record_latest, run_id, score_line)


class RunFailure(Exception):
    def __init__(self, kind: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.kind, self.details = kind, details or {}

    def record(self) -> dict:
        """The failure as data, for the live channel and the studio's worker: `failure` (the stage: generation, script, placement,
        explore, escape), the `item` a placement failure names, and `detail`, the free text of what raised it (the script's own
        error, or an exception's message). The sentence is channel.failure_text's."""
        constant = ("generation", "script", "placement")
        detail = self.details.get("error") or ("" if self.kind in constant and "item" not in self.details else str(self))
        return {"failure": self.kind, **({"item": self.details["item"]} if self.details.get("item") else {}), "detail": detail}


def _merged_by_cell(merged) -> list:
    """(cell, "GND on In1.Cu, In4.Cu; V3V3 on In3.Cu (its pads were ...)")
    per cell, in the order the write met them."""
    out = {}
    for m in merged:
        nets = out.setdefault(m.cell, {})
        layers, notes = nets.setdefault(m.net, ([], []))
        layers.append(m.layer.value)
        if m.note and m.note not in notes:
            notes.append(m.note)
    return [(cell, "; ".join("%s on %s%s" % (net, ", ".join(layers), " (%s)" % "; ".join(notes) if notes else "")
                             for net, (layers, notes) in nets.items()))
            for cell, nets in out.items()]


def placements_record(plan) -> dict:
    """run.json's `placements`: each placed part and cell's x, y, rotation and face, and a cell's `arrangement` when it stands in
    one other than its module's own layout."""
    return {s.item: {"x": s.placement.location.x, "y": s.placement.location.y,
                     "rotation": s.placement.rotation, "face": s.placement.face.value,
                     **({"arrangement": s.placement.arrangement} if s.placement.arrangement else {})}
            for s in plan.steps if s.placement is not None and s.kind != "block"}


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
    if plan.cleanup:
        metrics["cleanup"] = dict(plan.cleanup)
    if getattr(plan, "rudy", None) is not None:
        r = plan.rudy
        metrics["rudy"] = {"worst": r.worst, "worst_at": [r.worst_at.x, r.worst_at.y], "p99": r.p99,
                           "overflow": r.overflow, "cell": r.cell}
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


def cached_generation(src: BoardSource) -> Path:
    """Where a board's cached generation is: the board `pcb layout` wrote,
    copied aside by the first run."""
    return src.board_dir / ".placemat" / "generated" / src.name


# What placemat itself writes into a layout folder, beside what the generator
# writes (the cached generation's files): anything else there is someone's.
_OURS = (".kicad_pcb", ".kicad_pro", ".kicad_prl", ".kicad_dru")


def missing_rules(pcb: Path) -> list:
    """The project and design-rules files KiCad reads a board's rules from that are not beside `pcb` (".kicad_pro",
    ".kicad_dru"): without them a DRC or a route judges the board by KiCad's defaults."""
    return [ext for ext in (".kicad_pro", ".kicad_dru") if not pcb.with_suffix(ext).exists()]


def copy_board(pcb: Path, run_dir: Path) -> None:
    """The board into a run folder as layout.kicad_pcb, with its project and design rules (the .kicad_pro and .kicad_dru beside
    it) as layout.kicad_pro and layout.kicad_dru: KiCad reads a board's rules from those, so `placemat drc` and `placemat
    route` on the run's copy judge it by the board's own rules."""
    shutil.copy(pcb, run_dir / "layout.kicad_pcb")
    for ext in (".kicad_pro", ".kicad_dru"):
        beside = pcb.with_suffix(ext)
        if beside.exists():
            shutil.copy(beside, run_dir / ("layout" + ext))
_RENDERS = ("layout.png", "layout-iso.png", "layout-bottom.png")
_OUR_FILES = _RENDERS + ("drc.json",)


def _set_aside(src: BoardSource, run_dir: Path, cache: Path, quiet: bool, keep_renders: bool = False) -> list:
    """Before the layout folder is replaced: every file in it that neither
    placemat nor the generator wrote is copied into the run's `kept/` and
    returned with what was said, to be put back and logged; and a board
    edited since its last run (a hand edit in KiCad) is copied there too,
    since placemat writes over it. Both are said on the terminal.
    `keep_renders`: a run that makes no renders keeps the last ones too."""
    if not src.layout_dir.exists():
        return [], []
    generated = {p.relative_to(cache) for p in cache.rglob("*")} if cache.exists() else set()
    ours = {Path(src.pcb.stem + ext) for ext in _OURS} | \
        {Path(n) for n in _OUR_FILES if not (keep_renders and n in _RENDERS)}
    kept_dir = run_dir / "kept"
    foreign = []
    for p in sorted(src.layout_dir.rglob("*")):
        rel = p.relative_to(src.layout_dir)
        if p.is_file() and rel not in generated and rel not in ours:
            (kept_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, kept_dir / rel)
            foreign.append(rel)
    notes = []
    hand = [r for r in foreign if str(r) not in _RENDERS]
    if hand:
        notes.append("kept %d file(s) placemat did not write, put back after generation: %s" % (
            len(hand), ", ".join(str(r) for r in hand)))
    try:
        last = latest_for(src.board_dir / ".placemat" / "runs", src.name)
    except (ValueError, OSError):
        last = None
    written = Path(last.paths.get("run_dir", "")) / "layout.kicad_pcb" if last else None
    if src.pcb.exists() and written is not None and written.exists() and written.read_bytes() != src.pcb.read_bytes():
        kept_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src.pcb, kept_dir / src.pcb.name)
        notes.append("%s was edited since run %s: kept as %s" % (src.pcb.name, last.run_id, kept_dir / src.pcb.name))
    for n in notes:
        _say(quiet, "board   " + n)
    return foreign, notes


def _put_back(src: BoardSource, run_dir: Path, foreign: list) -> None:
    for rel in foreign:
        (src.layout_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run_dir / "kept" / rel, src.layout_dir / rel)


def generate(src: BoardSource, run_dir: Path, fresh: bool, quiet: bool,
             timeout: int = 900, keep_renders: bool = False) -> bool:
    """Put a freshly generated (unscripted) board in src.layout_dir. A copy of
    the generation is cached beside the runs so a rerun of the script does not
    pay for `pcb layout` again; `fresh` forces it. Returns True when the
    generator ran."""
    cache = cached_generation(src)
    log = run_dir / "generate.log"
    inputs = generator_inputs(src)
    stale = stale_inputs(src, inputs) if cache.exists() else None
    foreign, notes = _set_aside(src, run_dir, cache, quiet, keep_renders)
    if cache.exists() and not fresh and not stale:
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(cache, src.layout_dir)
        _put_back(src, run_dir, foreign)
        log.write_text("restored the cached generation from %s\n" % cache + "".join(n + "\n" for n in notes))
        _say(quiet, "board   restored from cache (%s)" % cache.relative_to(src.board_dir))
        return False
    if stale and not fresh:
        _say(quiet, "board   the cached generation is out of date: %s" % stale)
    env = generation_env()
    shutil.rmtree(src.layout_dir, ignore_errors=True)
    src.layout_dir.mkdir(parents=True, exist_ok=True)
    _say(quiet, "board   generating %s with pcb layout ..." % src.zen.name)
    cmd = ["pcb", "layout", "--no-open"] + list(src.generate_args) + [src.zen.name]
    rc, dt = _sh(cmd, src.board_dir, log, timeout, env)
    if stale and not fresh:
        with open(log, "a") as f:
            f.write("\ngenerated again: %s\n" % stale)
    if rc != 0 or not src.pcb.exists():
        raise RunFailure("generation", "Schematic generation failed",
                         {"command": " ".join(cmd), "cwd": str(src.board_dir),
                          "exit_code": rc, "log": str(log), "tail": _tail(log)})
    shutil.rmtree(cache, ignore_errors=True)
    shutil.copytree(src.layout_dir, cache)
    _put_back(src, run_dir, foreign)            # after the cache is taken: it holds only what was generated
    with open(log, "a") as f:
        f.writelines(n + "\n" for n in notes)
    _inputs_record(src).write_text(json.dumps(inputs, indent=1, sort_keys=True))
    _say(quiet, "board   generated in %.0fs" % dt)
    return True


def generation_env() -> dict[str, str]:
    """The environment `pcb layout` runs in. KIPRJMOD is dropped: pcb takes the board's folder for it only when it is unset, and
    pcbnew sets it (to an empty string) in a process that creates or saves a board, so a process that has done that, and the
    children it starts, would resolve every footprint library against the wrong folder."""
    return child_env()


def _inputs_record(src: BoardSource) -> Path:
    """Where a cached generation's inputs are recorded: beside the cache."""
    cache = cached_generation(src)
    return cache.with_name(cache.name + ".inputs.json")


def stale_record(src: BoardSource, inputs: dict | None = None) -> dict | None:
    """Why the cached generation no longer matches what the generator would read, as data, or None when it does: `{"form":
    "no_record"}`, or `{"form": "changed", "files": [the inputs that changed, appeared or went]}`."""
    try:
        was = json.loads(_inputs_record(src).read_text())
    except (OSError, ValueError):
        return {"form": "no_record"}
    now = generator_inputs(src) if inputs is None else inputs
    changed = sorted(k for k in set(was) | set(now) if was.get(k) != now.get(k))
    return {"form": "changed", "files": changed} if changed else None


def stale_text(rec: dict | None) -> str:
    """A `stale_record` in words, "" for none."""
    if rec is None:
        return ""
    if rec["form"] == "no_record":
        return "no record of the files it was generated from"
    files = rec["files"]
    shown = ", ".join(files[:4]) + (" and %d more" % (len(files) - 4) if len(files) > 4 else "")
    return "%s changed since it was generated" % shown


def stale_inputs(src: BoardSource, inputs: dict | None = None) -> str:
    """`stale_record` in words: why the cached generation no longer matches what the generator would read, or "" when it does."""
    return stale_text(stale_record(src, inputs))


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
        route_exclude=(), keep_going: bool = False, overrides=None, reuse: bool = True, explore=None,
        resume: bool = True) -> RunResult:
    """One layout attempt, with this board's settings resolved and bound for
    the whole of it: the deep geometry helpers read the binding, and the run
    id carries the settings so a changed one cannot collide with a previous
    run and delete it."""
    script = Path(script).resolve()
    src = find_board(script)
    cfg = settings.load(src.board_dir, overrides=overrides or {}, script=script)
    with settings.bind(cfg):
        return _run(script, src, cfg, label=label, fresh=fresh, render=render, drc=drc,
                    quiet=quiet, verbose=verbose, route=route, route_quick=route_quick,
                    route_exclude=route_exclude, keep_going=keep_going, reuse=reuse, explore=explore, resume=resume)


def drc_metrics(report, aw: dict, free: float) -> dict:
    """What a run records from its DRC: the buckets, the airwire in all and
    per net (longest first, so the nets to look at lead), the crossings and
    the congestion of the free board."""
    per_net = dict(sorted(aw.get("per_net", {}).items(), key=lambda kv: (-kv[1], kv[0])))
    return {"drc_real": report.real, "outstanding": report.outstanding, "other": report.other,
            "permitted": report.permitted, "expected": report.expected,
            "unconnected": report.unconnected, "airwire_mm": aw["total_mm"], "airwire_per_net": per_net,
            "crossings": aw["crossings"], "crossings_per_net": aw["crossings_per_net"],
            "free_area_mm2": round(free, 1), "congestion": congestion(aw["crossings"], free),
            "open_nets": dict(report.open_nets)}


def rule_notes(geometry) -> list:
    """What the generated board's own rules leave unchecked. A module
    fragment declared with Layout() and no board config is generated with
    the stdlib's defaults - no silk clearance among them - and is laid out
    by those, not by the board that stamps it."""
    notes = []
    if not geometry.silk_clearance:
        notes.append("the generated board's minimum silk clearance is 0, so nothing keeps silk apart; a module "
                     "fragment is generated with the stdlib's default rules unless its .zen declares "
                     "Board(..., config=) with the rules of the board that stamps it")
    return notes


def scripted_board(script, src, cfg, fab, keep_going: bool, pcb=None, geometry=None) -> Board:
    """The generated board read (`pcb`, else the board's own file), a Board
    over it with this board's fab profile and settings, and the script run
    against it. A script that raises is a RunFailure naming its line.
    `geometry`, when given, is the board already read: a fresh Board over it
    runs the script again without reading the file (an explore variant)."""
    if geometry is None:
        from .kicad.read import read_board
        geometry = read_board(pcb or src.pcb, courtyard_excess_mm=fab.courtyard_excess)
        from .pins import board_pin_names
        import dataclasses as _dc
        geometry = _dc.replace(geometry, pin_names=board_pin_names(src, Path(pcb or src.pcb).parent))
    board = Board(geometry, via_drill=fab.via_drill, via_size=fab.via_size, keep_going=keep_going,
                  courtyard_excess=fab.courtyard_excess, settings=cfg, component_spacing=fab.component_spacing,
                  fab_via_tiers=fab.via_tiers, fab_source=str(fab.path) if fab.path else "")
    board.script_file = str(Path(script).resolve())     # what a finding's suggestions edit
    board._script = script
    from . import context as context_mod
    if context_mod._overlay:                            # a try of a suggestion: declarations' digests are of the text it ran
        board.source_reader = context_mod.read_source
    try:
        run_script(script, board)
        board.finish_declarations()                     # an only= naming no arrangement is the script's error
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        from .project import script_files
        mine = {Path(f).resolve() for f in script_files(script, missing=True)} | {script}      # the script and what it imports
        frames = [f for f in tb if Path(f.filename).resolve() in mine]
        where = frames[-1] if frames else None
        raise RunFailure("script", "Layout script failed", {
            "script": str(Path(where.filename).resolve()) if where else str(script), "line": where.lineno if where else None,
            "source": where.line if where else None, "error": "%s: %s" % (type(e).__name__, e),
            "traceback": "".join(traceback.format_exception(e))})
    return board


def reuse_parts(src, cfg, fab, pcb=None, board_digest: str | None = None) -> dict:
    """What a reuse record's context is made of beyond the script: digests
    of the tool version, the generated board, the settings and the fab
    profile, kept apart so a run can say which of them changed.
    `board_digest` is the board file's, when the caller already has it."""
    import hashlib
    from . import __version__
    from . import reuse as reuse_mod
    return {"tool": __version__, "board": board_digest or hashlib.sha256((pcb or src.pcb).read_bytes()).hexdigest(),
            "settings": hashlib.sha256(reuse_mod.placement_settings(cfg).encode()).hexdigest(),
            "fab": hashlib.sha256(fab.json().encode()).hexdigest()}


def _run(script, src, cfg, label: str | None = None, fresh: bool = False, render: bool = True,
         drc: bool = True, quiet: bool = False, verbose: bool = False, route: bool = False,
         route_quick: bool = True, route_exclude=(), keep_going: bool = False, reuse: bool = True, explore=None,
         resume: bool = True) -> RunResult:
    configure(quiet=quiet)
    say = console.say
    from . import timecap
    timecap.arm(cfg)                        # --max-time, --step-warn, --step-limit, when the command has them
    runs = src.board_dir / ".placemat" / "runs"
    from . import reuse as reuse_mod
    # The previous run's record is read now: a rerun with the same id replaces its directory.
    previous_reuse, previous_id = None, None
    previous_arr = {}                       # each arrangement's record in that run, by id
    if reuse:
        try:
            last = latest_for(runs, src.name)
            if last is not None:
                previous_reuse = reuse_mod.read(Path(last.paths.get("run_dir", "")) / "reuse.json")
                previous_id = last.run_id
                previous_arr = arrangement_run.read_previous(Path(last.paths.get("run_dir", "")))
        except (json.JSONDecodeError, TypeError, KeyError, OSError):
            previous_reuse = None
    # Which run made the renders in the layout folder: a run that renders none keeps them, and says whose
    renders_from = None
    try:
        last_any = latest_for(runs, src.name)
        if last_any is not None:
            renders_from = (last_any.metrics or {}).get("renders_from") or \
                (last_any.run_id if "render" in (last_any.timing_s or {}) else None)
    except (json.JSONDecodeError, TypeError, KeyError, OSError, ValueError):
        renders_from = None
    staging = runs / ("." + time.strftime("%Y%m%d-%H%M%S-") + str(os.getpid()))
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    run_dir = staging
    rec = RunRecord(run_id="", board=src.name, status="running",
                    paths={"pcb": str(src.pcb), "script": str(script)})
    say("run", "%s: %s" % (src.name, script.relative_to(src.board_dir)))
    generated = False
    plan = None
    stage, began, stopped, explored = "generate", time.time(), None, None
    # the layout folder as the last run left it: a run that fails before it
    # writes the board puts it back, rather than leave the unplaced generation
    before = staging / "before"
    if src.layout_dir.exists():
        shutil.copytree(src.layout_dir, before)
    try:
        t0 = time.time()
        generated = generate(src, run_dir, fresh, quiet, cfg.timeout_generate, keep_renders=not render)
        rec.timing_s["generate"] = round(time.time() - t0, 1)
        # The run's name: a hash of the script, the generated board and the tool.
        from . import __version__
        fab = fab_profile(src.board_dir)
        rid = run_id(script_fingerprint(script), src.pcb.read_bytes(), __version__, cfg.json(), fab.json())
        final_dir = runs / rid
        # a run of these very inputs that died while resolving left its steps: read before its folder is replaced
        died = reuse_mod.read_partial(final_dir / "reuse.partial.jsonl") if reuse else None
        died_arr = arrangement_run.read_died(final_dir) if reuse else {}
        keep_route(final_dir, staging)
        shutil.rmtree(final_dir, ignore_errors=True)
        staging.rename(final_dir)
        run_dir = final_dir
        rec.run_id = rid
        rec.paths["run_dir"] = str(run_dir)
        rec.pid = os.getpid()               # a record still "running" whose pid is gone is a run that died
        rec.save(run_dir / "run.json")
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

        stage = "read"
        from . import facts as facts_mod
        facts_geometry = read_board(src.pcb, courtyard_excess_mm=fab.courtyard_excess)
        facts_doc = facts_mod.facts_of(facts_geometry, fab, cfg.check_rise_c)
        facts_reasons = facts_mod.unconfirmed_reasons(facts_doc, facts_mod.confirmed_digest(cfg, script))
        if facts_reasons:
            say("facts", facts_mod.unconfirmed_line(facts_reasons))

        t0 = time.time()
        from . import channel
        channel.hint_progress(run_dir / "progress.jsonl")      # the run's crash trail sits in its folder
        board = scripted_board(script, src, cfg, fab, keep_going)
        for note in rule_notes(board.geometry):
            say("note", note)
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
        from .lanes import EscapeError
        parts = reuse_parts(src, cfg, fab)
        board.reuse_extra = "|".join(parts[k] for k in ("tool", "board", "settings", "fab"))
        from .kicad.write import strip_stamped_notes
        # Their facts are read, and the reuse record has the generation's digest: the board the run leaves
        # in the folder while it works shows none
        strip_stamped_notes(src.pcb, keep_loose_faces=not board._draw_outline)
        from . import explore as explore_mod, routes as routes_mod
        stage = "explore" if explore is not None else "resolve"
        try:
            with timecap.cap_only():            # an explore's own resolves are not timed step by step
                lock_entries, explored = explore_mod.before_resolve(
                    script, board, explore_mod.BoardFactory(script, src, cfg, fab, keep_going, board.geometry),
                    explore, say, run_id=rid, keep_state=True)
        except (explore_mod.FocusError, ResumeRefused) as e:
            raise RunFailure("explore", str(e), {"tail": str(e)})
        stage = "resolve"
        if died is not None and reuse_mod.better_of(previous_reuse, died) is died:
            previous_reuse, previous_id = died, "%s (interrupted)" % rid
        partial = reuse_mod.PartialLog(run_dir / "reuse.partial.jsonl")
        declared = arrangement_run.begin(board)
        routes = routes_mod.read(routes_mod.path_for(script))
        try:
            plan = board.resolve(progress=progress, reuse=previous_reuse, lock=lock_entries,
                                 routes=routes, partial=partial)
        except PlacementCollision as e:
            (run_dir / "script.log").write_text("\n".join(log_lines) + "\n")
            raise RunFailure("placement", "Firm placements collide; fix the script (or --keep-going to see the rest)",
                             {"collisions": e.collisions, "tail": "\n".join(e.collisions)})
        except EscapeError as e:                    # a declared escape the part as placed cannot lay out
            (run_dir / "script.log").write_text("\n".join(log_lines) + "\n")
            raise RunFailure("escape", str(e), {"tail": "fix the escape's declaration, or the part's placement"})
        except CriticalUnplaced as e:
            (run_dir / "script.log").write_text("\n".join(log_lines) + "\n")
            apply_plan(src.pcb, e.plan)                      # the board as it stood when the critical item failed
            for note in e.plan.group_notes:
                say("groups", note)
            from .models import models_line
            if models_line(e.plan.models):
                say("models", models_line(e.plan.models))
            finish_board(src.pcb, fab, refs_to_fab=getattr(board, "refs_on_fab", True))
            copy_board(src.pcb, run_dir)
            if render:
                render_board(src.pcb, run_dir / "render.log", both_faces=True)
            raise RunFailure("placement", str(e), {"item": e.key, "tail": "board written as it stood: %s" % src.pcb})
        resolve_s = round(time.time() - t0, 1)              # the default's: the arrangements are timed apart
        plan.reuse["parts"] = parts
        t0 = time.time()
        others = arrangement_run.resolve_others(declared, plan, run_dir, previous_arr, died_arr, lock_entries, routes,
                                                lambda ident: say("arrangement", "resolving %s" % ident))
        others_s = time.time() - t0
        timecap.placement_done()            # the placement is in hand: the cap is lifted for the stages after it
        (run_dir / "script.log").write_text("\n".join(log_lines) + "\n")
        rec.timing_s["resolve"] = resolve_s
        from .project import fab_min_findings
        plan.findings += fab_min_findings(board.geometry.netclasses, fab)
        if not plan.draw_outline:               # a module: the members that set its extent with no alternative
            plan.findings += arrangement_run.extent_findings(board, arrangement_run.extent_of(plan), cfg.place_extent_notice_mm)
        if facts_reasons:
            from .findings import Finding, FindingCause
            plan.findings.append(Finding(FindingCause.FACTS_UNCONFIRMED, {"reasons": facts_reasons}))
        n_place = sum(1 for s in plan.steps if s.placement is not None)
        n_copper = sum(s.ops for s in plan.steps)
        from .findings import summary
        say("script", "%d placed, %d copper op(s), %d finding(s)%s  (%.1fs)" % (
            n_place, n_copper, len(plan.findings), " (%s)" % summary(plan.findings) if plan.findings else "",
            rec.timing_s["resolve"]))
        from .report import extent_of
        ext = extent_of(plan)
        extent_metrics = {}
        if ext is not None:
            say("script", "extent %.2f x %.2f mm, %.0f%% of it empty" % (ext.width, ext.height, 100 * ext.empty))
            extent_metrics = {"extent": [round(ext.width, 3), round(ext.height, 3)], "empty": round(ext.empty, 3)}
        for f in plan.findings.most_serious_first()[: (50 if verbose else 8)]:
            console.finding(f)
        if len(plan.findings) > 8 and not verbose:
            say("finding", "... %d more in %s" % (len(plan.findings) - 8, run_dir / "run.json"), level="finding")

        t0 = time.time()
        stage = "write"
        apply_plan(src.pcb, plan)
        for cell, zones in _merged_by_cell(plan.merged_zones):
            say("zones", "%s: %s merged into the board's plane" % (cell, zones))
        for k in plan.kept_zones:
            say("zones", "%s: its %s zone on %s kept under the board's plane: %s" % (k.cell, k.net, k.layer.value, k.note))
        for note in plan.group_notes:
            say("groups", note)
        from .models import models_line
        line = models_line(plan.models)
        if line:
            say("models", line)
        finish_board(src.pcb, fab, refs_to_fab=getattr(board, "refs_on_fab", True))
        rec.timing_s["write"] = round(time.time() - t0, 1)
        copy_board(src.pcb, run_dir)
        say("board", "written %s (%.1fs)" % (src.pcb.relative_to(src.board_dir), rec.timing_s["write"]))

        if plan.seeded_by_net:
            top = plan.seeded_by_net.most_common(4)
            more = len(plan.seeded_by_net) - len(top)
            say("seeded", ", ".join("%s %d" % kv for kv in top) + (", +%d more" % more if more else ""))
        if getattr(plan, "rudy", None) is not None:
            r = plan.rudy
            say("congestion", "worst cell %.2f of capacity at (%.1f, %.1f), 99th percentile %.2f (RUDY, %.1f mm cells)" % (
                r.worst, r.worst_at.x, r.worst_at.y, r.p99, r.cell))
        if plan.footprints:
            say("footprints", "%d courtyard(s) understate their part: %s%s" % (
                len(plan.footprints), "; ".join(plan.footprints[:8]), "; ..." if len(plan.footprints) > 8 else ""))
        if plan.pocketed:
            say("pocketed", "%d item(s) had no room by what they connect to and took a pocket: %s" % (
                len(plan.pocketed), ", ".join(plan.pocketed[:8]) + (", ..." if len(plan.pocketed) > 8 else "")))
        reuse_mod.write(run_dir / "reuse.json", plan.reuse)
        partial.remove()                    # the whole record is written: the partial one is not needed
        line = reuse_mod.summary(plan.reuse, previous_reuse, "run %s" % previous_id)
        if line:
            say("reused", line[len("reused "):])
        metrics = run_metrics(plan, n_place, n_copper, extent_metrics)
        from . import score as score_mod
        metrics["measures"] = score_mod.plan_measures(board, plan)
        if explored is not None:
            metrics["explore"] = explored
        if plan.adopted:
            metrics["adopted"] = dict(plan.adopted)
        held = explore_mod.lock_summary(plan)
        if held:
            say("lock", held)
        kept = routes_mod.summary(plan)
        if kept:
            say("adopted", kept)
        metrics["resolve_seconds"] = round(plan.seconds, 3)
        if previous_reuse:
            metrics["reused"] = {"steps": plan.reuse["reused"], "of": len(plan.reuse["steps"]),
                                 "from": previous_id, "first_change": plan.reuse["first_change"]}
        if drc:
            t0 = time.time()
            stage = "drc"
            # KiCad's rule area has no allow list: what a keepout lets in is set aside.
            allow = {"keepout %s" % k.name: (set(k.owners), set(k.allow)) for k in plan.keepouts.values()}
            report = run_drc(src.pcb, run_dir / "drc.json", allow=allow, frame_only=not plan.draw_outline)
            quiet = set(board._plane_nets()) | set(board._free_nets)
            from .pairs import board_pairs
            aw = airwires_from_drc(json.loads((run_dir / "drc.json").read_text()), quiet,
                                   board_pairs(board.geometry.netclasses))
            free = plan.occupancy.free_area()
            metrics.update(drc_metrics(report, aw, free))
            # KiCad's own ratsnest and DRC replace the plan's estimates in the score
            metrics["measures"].update(drc=_drc_total(metrics), airwire_mm=aw["total_mm"],
                                       crossings={"signal": aw["crossings"] - aw["crossings_quiet"],
                                                  "plane": aw["crossings_quiet"],
                                                  "pair": aw.get("crossings_pair", 0)})
            cong = metrics["congestion"]
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
        stage = "checks"
        written = read_board(src.pcb)
        check_kwargs = checks.kwargs_from(cfg)
        verdicts, outcomes = checks.judge(checks.run_checks(written, **check_kwargs), plan.acceptances)
        for line in checks.record(rec, verdicts, outcomes):
            say("checks", line)
        stale = checks.findings_of(outcomes) + checks.keep_out_findings(written, check_kwargs["keep_out_mm"])  # after the finding lines printed above: said here, kept in run.json
        plan.findings.extend(stale)
        from . import suggestions as suggestions_mod
        suggestions_mod.bind(plan.findings, board)
        for f in stale:
            console.finding(f)
        rec.timing_s["checks"] = round(time.time() - t0, 1)
        if len(declared.specs) > 1 or board.arrangement_limit() is not None:
            t0 = time.time()
            stage = "arrangements"
            outcome = arrangement_run.finish(declared, plan, others, src=src, cfg=cfg, fab=fab, run_dir=run_dir,
                                             default_report=report if drc else None, board=board, drc=drc, render=render)
            rec.arrangements = outcome.record
            plan.findings.extend(outcome.findings)
            if outcome.texts:
                from .kicad.arrange import write_notes
                write_notes(src.pcb, outcome.texts)
                copy_board(src.pcb, run_dir)
            from .finding_text import arrangement_row_text
            for row in arrangement_run.lines(outcome.record):
                say("arrangements", arrangement_row_text(row))
            rec.timing_s["arrangements"] = round(others_s + time.time() - t0, 1)     # their resolves and their proofs
        if route:
            from .kicad.route import route_board
            t0 = time.time()
            stage = "route"
            say("route", "%s routing on a copy of the board ..." % ("quick" if route_quick else "full"))
            try:                                    # the placement as the studio draws it: the build replay's first half (the route's record is its second)
                from .preview_json import declared_sites, plan_json
                (run_dir / "plan.json").write_text(json.dumps(plan_json(plan, declared_sites(board)), separators=(",", ":")))
            except Exception as e:                  # a courtesy: the run goes on without it
                say("route", "no plan.json for the build replay: %s: %s" % (type(e).__name__, e))
            report = route_board(src.pcb, run_dir / "route", exclude_nets=set(plan.plane_nets) | set(route_exclude),
                                 quick=route_quick, resume=resume, board_info={"run": rec.run_id, "script": str(script)},
                                 on_setup=lambda fs: [console.finding(f, "route") for f in fs])
            if report.resumed:
                say("route", "took %s from an earlier route of the same inputs (--no-resume routes again)" %
                    ", ".join(report.resumed))
            metrics["route"] = report.as_dict()
            metrics["closure_clean"] = report.closure_clean
            rec.timing_s["route"] = round(time.time() - t0, 1)
            say("route", "%s  (%.0fs)" % (report.summary(), rec.timing_s["route"]))
            for breach in report.keepout_breaches:
                say("route", breach, level="finding")
            if report.has_findings():
                from .findings import FindingCause
                from .kicad.route_widths import stated_currents
                short = report.findings(stated_currents(read_board(src.pcb)) if report.widths else {})
                plan.findings.extend(short)
                for f in short:
                    if f.cause is not FindingCause.SETUP_NET_HALO:    # said before the route started
                        console.finding(f, "route")
            if report.open_nets:
                worst = sorted(report.open_nets.items(), key=lambda kv: -kv[1])[:8]
                say("route", "still open: " + ", ".join("%s %d" % kv for kv in worst))
        if render:
            t0 = time.time()
            stage = "render"
            render_board(src.pcb, run_dir / "render.log", both_faces=getattr(board, "both_faces", False))
            rec.timing_s["render"] = round(time.time() - t0, 1)
            say("render", "%s  (%.1fs)" % (", ".join(p.name for p in src.layout_dir.glob("layout*.png")), rec.timing_s["render"]))
            metrics["renders_from"] = rec.run_id
        else:
            kept = [n for n in _RENDERS if (src.layout_dir / n).exists()]
            if kept:
                metrics["renders_from"] = renders_from
                say("render", "not rendered: %s kept from %s, the board as that run placed it" % (
                    ", ".join(kept), "run %s" % renders_from if renders_from else "an earlier run"))
        rec.metrics = metrics
        rec.placements = placements_record(plan)
        rec.cutouts = {n: {"x": c.centre.x, "y": c.centre.y, "rotation": c.rotation}
                       for n, c in plan.cutouts_placed.items()}
        rec.steps = [{"item": s.item, "kind": s.kind,
                      "freedom": s.freedom.value if s.freedom else None,
                      "priority": s.priority.value if s.priority else None,
                      "rank": s.rank, "rank_of": s.rank_of, "note": s.note, "notes": list(s.notes),
                      "why": s.why, "moved_mm": round(s.moved_mm, 3), "ops": s.ops,
                      "seconds": round(s.seconds, 3), "first_seconds": None if s.first_seconds is None else round(s.first_seconds, 3)}
                     for s in plan.steps]
        from .geometry import native_status
        rec.native = native_status().facts()
        rec.findings = list(plan.findings)
        rec.finding_details = [f.detail() for f in plan.findings]
        rec.status = "ok"
    except RunFailure as e:
        rec.status = "failed"
        rec.failure = {"kind": e.kind, "message": str(e), **e.details}
        from . import channel
        channel.error("run_failure", str(e.details.get("script") or ""), e.details.get("line"), **e.record())
        say("fail", str(e), level="fail")
        kept = run_dir / "before"
        if kept.exists() and "item" not in e.details:     # a critical item's failure writes the board as it stood
            shutil.rmtree(src.layout_dir, ignore_errors=True)
            shutil.copytree(kept, src.layout_dir)
            say("fail", "the layout folder is as the last run left it")
        for k in ("script", "line", "source", "error", "command", "cwd", "exit_code", "log"):
            if e.details.get(k) is not None:
                say("fail", "%-9s %s" % (k, e.details[k]))
        if e.details.get("tail"):
            console.lines("fail", e.details["tail"])
        if verbose and e.details.get("traceback"):
            console.lines("fail", e.details["traceback"])
    except stop.Stopped as s:
        stopped = s
        s.stage = s.stage or stage
        rec.status = "stopped"
        rec.failure = {"kind": "stopped", "signal": s.name, "stage": s.stage, "elapsed_s": round(time.time() - began, 1),
                       "explore": s.explore, **stop.cause_fields(s)}
        kept = run_dir / "before"
        if kept.exists():                  # whatever the stop left half written: the folder as the last run left it
            shutil.rmtree(src.layout_dir, ignore_errors=True)
            shutil.copytree(kept, src.layout_dir)
    if rec.status == "ok":
        shutil.rmtree(run_dir / "before", ignore_errors=True)    # only a failure needs it
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
        regressed = _against_best(rec, run_dir.parent / "best.json", say, cfg)
    rec.save(run_dir / "run.json")
    from . import channel
    if stopped is not None:
        say("record", str(run_dir / "run.json"))
        info = stop.record(stopped, run_id=rec.run_id, elapsed_s=rec.failure["elapsed_s"], record=str(run_dir / "run.json"),
                           explore=stopped.explore)
        stop.say(stop.line(info))
        stopped.said = True
        channel.stopped(info)               # the studios and `placemat watch` are told it was stopped, not that it died
        channel.finish(run_dir / "run.json")
        raise stopped
    channel.finish(run_dir / "run.json")                  # the studios are told where the record is
    text = ""
    if rec.status == "ok":
        try:
            previous = latest_for(run_dir.parent, rec.board)
            if previous is not None:
                if previous.run_id != rec.run_id:
                    text = impact(previous, rec)
                else:
                    text = "same inputs as the previous run: id %s again, nothing to compare" % rec.run_id
                (run_dir / "impact.txt").write_text(text + "\n")
                console.lines("impact", text)
        except (json.JSONDecodeError, TypeError):
            pass
        record_latest(run_dir.parent, run_dir / "run.json", rec.board)
        try:                                        # `placemat apply <id>` finds this plan's suggestions here
            from . import suggestions as suggestions_mod
            suggestions_mod.remember(src.board_dir, script, "run %s" % rec.run_id, plan.findings)
        except OSError:
            pass
        if explored is not None:            # its result is in the record: the explore's checkpoint is not needed
            from . import checkpoint
            checkpoint.finish_dir(checkpoint.state_dir(src.board_dir, script))
    say("record", str(run_dir / "run.json"))
    return RunResult(rec, run_dir, generated, text, plan, regressed)


def _against_best(rec: RunRecord, best_path: Path, say, cfg) -> str | None:
    """Judge a finished run against the best of its family - the runs whose
    script asked to place the same things - by the run score, and record it
    if it is the new best. A regression becomes a note naming the score and
    the term that moved it most.

    It is appended after the measures were taken, so the score goes on
    measuring the layout rather than the verdict about it."""
    if not comparable(rec):
        say("best", "not judged: this run measured no DRC, so it has nothing to compare")
        return None
    prior = best_for(best_path, family_of(rec))
    say("score", score_line(rec, prior if prior is not None and prior.run_id != rec.run_id else None, cfg))
    said, prior = against_best(best_path, rec, cfg)
    if said:
        rec.add_finding("worse than the best run of these parts: %s" % said)
        say("best", "worse than %s: %s" % (prior.run_id, said), level="fail")
    elif prior is None:
        say("best", "the first run of these parts, so the best so far")
    elif prior.run_id == rec.run_id or not is_better(rec, prior, cfg):
        say("best", "matches %s, the best run of these parts" % prior.run_id)
    else:
        say("best", "better than %s: now the best run of these parts" % prior.run_id)
    return said
