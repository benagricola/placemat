"""Test (b) of the reference set: place and route a reference board from its minimal intent script, and run our own
module fixtures, judging closure.

    .venv/bin/python fixtures/reference/place_ref.py [name ...] [--modules] [--update] [--changing placemat|krt|pcb ...]

An open board (a manifest board with test "b") is run from a clean copy of fixtures/reference/boards/<name>/ with
`placemat run --route --route-full`: the script is linted first and a lint failure is a failed result. The result is
compared with results.json["b"] and carries the regenerated reference's vias and track length and test (a)'s clean closure of
the same board. With --modules the module fixtures (every fixtures/*/modules/*/*_layout.py) are run with
`placemat run --route` instead of the boards, and compared with results.json["modules"]: closure, then the area of the
fitted frame. Results of runs whose placemat, router or zener versions differ in a component other than those named in
--changing are not compared. --update rewrites the entries of the boards or modules it ran in results.json, after each
one, and keeps the rest. A refused or failed run is a result with its failure kind, not an error of the runner; so is a
board or module whose preparation raises, with the exception's type as its kind.
Real boards: it takes the realboard lock (lock.py) for the whole run, so it waits for the other real-board runs.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

if __package__ in (None, ""):   # run as a script: the repository root, for `fixtures.reference`
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fixtures.reference import fetch, hand, lint, lock, prepare, route_ref   # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent
RESULTS = route_ref.RESULTS
RUN_TIMEOUT_S = 3600
CLEAN = route_ref.CLEAN
NOT_RUN = 0.0           # the closure of a run that did not reach a route
LINT = "lint"           # failure kinds of the runner's own; a refused run carries placemat's (run.json's failure kind)
NO_RECORD = "no run record"
NO_ROUTE = "no route"
TIMEOUT = "timeout"
WORKSPACE_DIRS = ("modules", "parts", "adapted")   # what a module needs of its family folder besides its own
DIGEST_CHARS = 16
STATE_DIRS = (".placemat", ".pcb", "__pycache__")   # never copied into the clean board folder
RUN_ARGS = ("--route", "--no-render", "--no-resume")
FULL_ROUTE = ("--route-full",)


@dataclasses.dataclass(frozen=True)
class BResult:
    board: str
    closure_clean: float
    open: int
    new_violations: list[prepare.Violation]
    vias: int
    track_mm: float
    run_score: float
    ref_vias: int           # the human board's
    ref_track_mm: float
    a_closure_clean: float | None   # test (a)'s clean closure of the same board (class widths), None when not recorded
    seconds: float
    versions: dict          # placemat, krt, pcb
    failure: str = ""       # "" when the run routed; else lint, a placemat failure kind, "no run record" or "no route"
    detail: str = ""        # what the failure said
    inputs_digest: str = ""   # of the capture's generator inputs: a changed capture is a difference, not a regression
    placement: dict = dataclasses.field(default_factory=dict)   # placement_facts: kept when the route fails or is refused
    routing_evidence: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class MResult:
    script: str             # "<family>/<module>"
    closure_clean: float
    area_mm2: float         # the fitted frame's width x height
    run_score: float
    seconds: float
    versions: dict
    failure: str = ""
    detail: str = ""
    inputs_digest: str = ""
    placement: dict = dataclasses.field(default_factory=dict)
    hand: dict = dataclasses.field(default_factory=dict)
    placed_area_mm2: float | None = None


def asdict(result) -> dict:
    return route_ref.asdict(result)


def module_scripts(root: pathlib.Path = FIXTURES) -> dict[str, pathlib.Path]:
    """The module fixtures that have a layout script: "<family>/<name>" -> script. A folder with several scripts
    (McuButtons, McuButtonsSide) gives one module per script."""
    found = {}
    for script in sorted(pathlib.Path(root).glob("*/modules/*/*_layout.py")):
        found["%s/%s" % (script.parents[2].name, script.name[:-len("_layout.py")])] = script
    return found


def placement_facts(record: dict | None, folder: pathlib.Path) -> dict:
    """What the placement alone measured, from run.json's metrics, before any route: crossings, airwire_mm, area_mm2, placed,
    findings and run_score. {} when the run recorded no placement (a refused script)."""
    metrics = (record or {}).get("metrics") or {}
    if "placed" not in metrics:
        return {}
    facts = {"crossings": metrics.get("crossings"), "airwire_mm": metrics.get("airwire_mm"), "area_mm2": _area(metrics),
             "placed": metrics["placed"], "findings": metrics.get("findings")}
    if metrics.get("measures"):
        facts["run_score"] = run_score(record, folder)
    return facts


def generation_inputs(script: pathlib.Path) -> str:
    """A digest (sha256, DIGEST_CHARS hex) of what `pcb layout` reads for the board a script is for: project.generator_inputs,
    the .zen and what it names. A changed capture shows as a difference between results."""
    from placemat.project import find_board, generator_inputs
    inputs = generator_inputs(find_board(pathlib.Path(script)))
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:DIGEST_CHARS]


def krt_version(folder: pathlib.Path) -> str:
    """The commit of the router a route of the board folder resolves."""
    return route_ref._krt_version(pathlib.Path(folder) / "x.kicad_pcb")


def run_score(record: dict, folder: pathlib.Path) -> float:
    """The run score of run.json's measures, at the settings of the board folder."""
    from placemat import score, settings
    return round(score.total(record["metrics"]["measures"], settings.load(pathlib.Path(folder))), 3)


def _copy_folder(src: pathlib.Path, dst: pathlib.Path) -> None:
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*STATE_DIRS))


def _run_identity(path: pathlib.Path) -> tuple:
    """Identity of a saved result: unchanged files from an earlier invocation cannot stand for this one."""
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size, hashlib.sha256(path.read_bytes()).hexdigest()


def _process_text(value) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


def placemat_run(script: pathlib.Path, extra: tuple = ()) -> tuple[dict | None, float]:
    """Run one placement in an owned process group; only RC0 and a fresh run.json can be adopted.

    Logs and the process facts are kept beside the copied script.
    A malformed fresh record, nonzero exit or timeout is a failed result. Signals
    and KeyboardInterrupt reap the owned group before propagating.
    """
    script = pathlib.Path(script)
    started = time.monotonic()
    records = script.parent / ".placemat" / "runs"
    before = {p: _run_identity(p) for p in records.glob("*/run.json")}
    previous_artifacts = {p.resolve(): route_ref._artifact_identity(p) for p in records.rglob("*")
                          if p.is_file() and p.suffix in (".kicad_pcb", ".json")}
    audits = script.parent / ".placemat" / "reference-runs"
    audits.mkdir(parents=True, exist_ok=True)
    audit = pathlib.Path(tempfile.mkdtemp(prefix="invocation-", dir=audits))
    cmd = [sys.executable, "-m", "placemat", "run", str(script), *RUN_ARGS, *extra]
    facts = {"argv": cmd, "cwd": str(pathlib.Path.cwd()), "protocol": "fresh record, RC0, owned process group",
             "timeout_s": RUN_TIMEOUT_S}

    def log(stdout, stderr):
        (audit / "stdout.log").write_text(_process_text(stdout))
        (audit / "stderr.log").write_text(_process_text(stderr))
        (audit / "process.json").write_text(json.dumps(facts, indent=2) + "\n")

    def failed(kind, message):
        return {"status": "failed", "failure": {"kind": kind, "message": message}}, time.monotonic() - started

    try:
        proc = route_ref.run_owned(cmd, timeout=RUN_TIMEOUT_S)
    except BaseException as error:
        facts["exception"] = type(error).__name__
        facts["exitcode"] = error.code if isinstance(error, SystemExit) else None
        log(getattr(error, "output", None), getattr(error, "stderr", None))
        if isinstance(error, subprocess.TimeoutExpired):
            return failed(TIMEOUT, "no result in %s s" % RUN_TIMEOUT_S)
        if isinstance(error, Exception):
            return failed(type(error).__name__, str(error))
        raise
    facts["returncode"] = proc.returncode
    log(proc.stdout, proc.stderr)
    try:
        fresh = [p for p in records.glob("*/run.json") if before.get(p) != _run_identity(p)]
    except OSError as error:
        return failed("malformed run record", str(error))
    record = None
    malformed = None
    if fresh:
        chosen = max(fresh, key=lambda p: p.stat().st_mtime_ns)
        facts["record"] = str(chosen)
        try:
            raw = chosen.read_bytes()
            facts["record_sha256"] = hashlib.sha256(raw).hexdigest()
            record = json.loads(raw)
            if not isinstance(record, dict) or not isinstance(record.get("status"), str):
                raise ValueError("run.json must be an object with a status")
            if record.get("status") == "ok" and not isinstance(record.get("metrics"), dict):
                raise ValueError("completed run.json must contain metrics")
            if record.get("failure") is not None and not isinstance(record["failure"], dict):
                raise ValueError("run.json failure must be an object")
        except (OSError, ValueError) as error:
            malformed = str(error)
    log(proc.stdout, proc.stderr)
    if proc.returncode:
        # A CLI exit cannot be promoted by an apparently completed record.
        message = (_process_text(proc.stderr) or _process_text(proc.stdout))[-500:]
        result, seconds = failed("exit %d" % proc.returncode, message)
        if isinstance(record, dict) and record.get("failure"):
            result = dict(record, status="failed", returncode=proc.returncode)
        if isinstance(record, dict):
            result["raw_record_diagnostic"] = record   # unverified; never adopted as metrics
        if proc.returncode == 1 and malformed is None and isinstance(record, dict):
            metrics = record.get("metrics")
            route = metrics.get("route") if isinstance(metrics, dict) else None
            if isinstance(route, dict) and route.get("routed_pcb"):
                try:
                    route_dir = pathlib.Path(route["routed_pcb"]).resolve().parent
                    if route_dir.is_relative_to(chosen.parent.resolve()):
                        report_path = route_dir / "route.json"
                        report = json.loads(report_path.read_text())
                        if report == route:
                            diagnostic = route_ref._invalid_route_diagnostic(report, report_path, chosen.parent, previous_artifacts)
                            if diagnostic:
                                result["route_diagnostic"] = diagnostic
                except (OSError, ValueError, TypeError):
                    pass
        return result, seconds
    if malformed is not None:
        return failed("malformed run record", malformed)
    return record, time.monotonic() - started


def _failure(record: dict | None) -> tuple[str, str]:
    """(kind, message) of a record that failed, ("", "") for one that did not."""
    if record is None:
        return NO_RECORD, "placemat run wrote no run.json"
    failure = record.get("failure")
    if failure:
        return str(failure.get("kind", "failed")), str(failure.get("message", ""))
    if record.get("status") not in (None, "ok"):
        return str(record["status"]), ""
    return "", ""


def run_b(board: fetch.Board, ref_dir: pathlib.Path, work: pathlib.Path, *, prepared: prepare.Prepared | None = None,
          versions: dict | None = None, a_closure_clean: float | None = None) -> BResult:
    """Run the placement script and judge against a fresh import of the pinned source.

    The regenerated reference uses the same library footprints as the script.
    Its stripped copper supplies the baseline DRC, so generation differences
    are measured consistently. The runner does not take the lock; main does.
    """
    work = pathlib.Path(work)
    versions = dict(versions if versions is not None else route_ref.current_versions())
    human = prepared.human if prepared is not None else prepare.HumanCopper(0, 0.0)
    digest = generation_inputs(lint.find_script(board.name, ref_dir.parent))

    def result(**over) -> BResult:
        fields = dict(board=board.name, closure_clean=NOT_RUN, open=0, new_violations=[], vias=0, track_mm=0.0, run_score=0.0,
                      ref_vias=human.vias, ref_track_mm=human.track_mm, a_closure_clean=a_closure_clean, seconds=0.0,
                      versions=versions, inputs_digest=digest)
        return BResult(**dict(fields, **over))

    script = lint.find_script(board.name, ref_dir.parent)
    report = lint.lint(script, board.fixed)
    if report.problems:
        detail = "; ".join("line %d %s %s" % (p.line, p.rule, p.ref) for p in report.problems)
        return result(failure=LINT, detail=detail)
    if prepared is None:   # after the lint: a refused script costs no fetch or DRC
        prepared = prepare.prepare(board, fetch.fetch(board), work / "reference", regenerated=True)
        human = prepared.human
    folder = work / "board"
    _copy_folder(ref_dir, folder)
    record, seconds = placemat_run(folder / script.name, FULL_ROUTE)
    versions["krt"] = krt_version(folder)
    placement = placement_facts(record, folder)
    kind, message = _failure(record)
    if kind:
        diagnostic = record.get("route_diagnostic", {}) if record else {}
        report = route_ref.verified_invalid_report(diagnostic)
        if report is None:
            return result(failure=kind, detail=message, seconds=round(seconds, 1), versions=versions, placement=placement,
                          routing_evidence={"status": "unmeasured", "measured": False, "certified": False})
        after_path = pathlib.Path(diagnostic["drc_after_path"]) if "drc_after_path" in diagnostic else None
        after = route_ref.diagnostic_violations(after_path)
        new = route_ref.new_violations(after, prepared.baseline) if after is not None else None
        evidence = route_ref.routing_evidence(report, status="completed_invalid", artifacts=diagnostic, after=after, new=new)
        return result(failure=kind, detail=message, closure_clean=report["closure_clean"], open=report["open_after"],
                      vias=report.get("vias", 0), track_mm=report.get("track_mm", 0.0),
                      seconds=round(seconds, 1), versions=versions, placement=placement, new_violations=new or [],
                      routing_evidence=evidence)
    route = record["metrics"].get("route")
    if not route or not route.get("routed_pcb"):
        return result(failure=NO_ROUTE, seconds=round(seconds, 1), versions=versions, placement=placement)
    _, routed = prepare.measure(pathlib.Path(route["routed_pcb"]))
    drc_path = pathlib.Path(route["routed_pcb"]).with_name("drc_after.json")
    after = prepare.violations(drc_path) if drc_path.is_file() else (
        prepare.violations_of(route["drc_after"]) if isinstance(route.get("drc_after", {}).get("violations"), list) else None)
    new = route_ref.new_violations(after, prepared.baseline) if after is not None else []
    evidence = route_ref.routing_evidence(dict(route, vias=routed.vias, track_mm=routed.track_mm),
                                         status="completed_valid" if route.get("valid") is not False else "completed_invalid",
                                         after=after, new=new if after is not None else None)
    return result(closure_clean=route.get("closure_clean", NOT_RUN), open=route.get("open_after", 0), new_violations=new,
                  vias=routed.vias, track_mm=routed.track_mm, run_score=run_score(record, folder), seconds=round(seconds, 1),
                  versions=versions, placement=placement, routing_evidence=evidence,
                  failure="invalid board" if route.get("valid") is False else "",
                  detail=route.get("invalid_reason", ""))


def _area(metrics: dict) -> float:
    """The fitted frame's area: a module's extent, else the outline of a board."""
    w, h = metrics.get("extent") or metrics.get("board") or (0.0, 0.0)
    return round(w * h, 2)


def _copy_family(script: pathlib.Path, dst: pathlib.Path) -> pathlib.Path:
    """The workspace of a module fixture (fixtures/<family>: its pcb.toml, parts/ and modules/) copied into `dst`, so the
    capture's relative paths (`../../parts`) resolve as in the repository; returns the script's path in the copy."""
    root = script.parents[2]
    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True)
    for entry in root.iterdir():
        if entry.name in WORKSPACE_DIRS:
            shutil.copytree(entry, dst / entry.name, ignore=shutil.ignore_patterns(*STATE_DIRS))
        elif entry.is_file():
            shutil.copy(entry, dst / entry.name)
    return dst / script.relative_to(root)


def _placed_board(script: pathlib.Path) -> pathlib.Path:
    from placemat.project import find_board
    return find_board(script).pcb


def run_module(name: str, script: pathlib.Path, work: pathlib.Path, *, versions: dict | None = None) -> MResult:
    """A module fixture run as a user runs it: `placemat run --route` on the script inside a copy of its family's workspace in
    `work`, so placemat generates the board fresh with `pcb layout` (the checked-in layout/ holds an old run's copper and is not
    the generation) and the repository's files are not written."""
    script = pathlib.Path(script)
    versions = dict(versions if versions is not None else route_ref.current_versions())
    digest = generation_inputs(script)
    copy = _copy_family(script, pathlib.Path(work) / "workspace")
    record, seconds = placemat_run(copy)
    versions["krt"] = krt_version(copy.parent)
    placement = placement_facts(record, copy.parent)
    extra = {}
    found = hand.reference_of(script)
    if found is not None:
        config = script.parents[2] / "placemat.toml"
        facts = hand.measure_hand(found, pathlib.Path(work) / "hand", config.read_text() if config.exists() else None, script)
        placed = _placed_board(copy)
        extra = {"hand": dataclasses.asdict(facts),
                 "placed_area_mm2": hand.footprint_area(placed) if placed.exists() else None}
    kind, message = _failure(record)
    if kind:
        return MResult(name, NOT_RUN, placement.get("area_mm2", 0.0), 0.0, round(seconds, 1), versions, kind, message, digest,
                       placement, **extra)
    metrics = record["metrics"]
    return MResult(name, metrics.get("closure_clean", NOT_RUN), _area(metrics), run_score(record, copy.parent), round(seconds, 1),
                   versions, inputs_digest=digest, placement=placement, **extra)


def _differ(old: dict, new, changing: set[str]) -> list[str]:
    """What differs between two runs other than what is under change: component versions, and "inputs" when the capture's
    digest differs (a changed capture re-baselines, it is not a regression). A run that failed before its digest was read
    has none and is not called "inputs"."""
    differ = route_ref.comparable(old.get("versions", {}), new.versions, changing)
    return differ + (["inputs"] if new.inputs_digest and old.get("inputs_digest", "") != new.inputs_digest else [])


def _worse_closure(old: dict, new) -> bool:
    return bool(new.failure) and not old.get("failure") or new.closure_clean < old["closure_clean"]


def _compared(old: dict | None, new, changing: set[str], value) -> route_ref.Comparison:
    if old is None:
        return route_ref.Comparison("new", [])
    if isinstance(new, BResult) and route_ref.unmeasured_failure_comparison(old, new):
        return route_ref.Comparison("not comparable", ["routing measurements"])
    differ = _differ(old, new, changing)
    if differ:
        return route_ref.Comparison("not comparable", differ, value(old, new))
    return route_ref.Comparison(value(old, new), [])


def b_by_value(old: dict, new: BResult) -> str:
    """same, better or worse on the values alone: worse is a lower clean closure or a failure the recorded run had not."""
    if _worse_closure(old, new):
        return "worse"
    if new.closure_clean > old["closure_clean"] or (old.get("failure") and not new.failure):
        return "better"
    return "same"


def module_by_value(old: dict, new: MResult) -> str:
    """same, better or worse on the values alone: worse is a lower clean closure, or at equal closure a larger area."""
    if _worse_closure(old, new):
        return "worse"
    if new.closure_clean > old["closure_clean"]:
        return "better"
    if new.area_mm2 > old["area_mm2"]:
        return "worse"
    return "better" if new.area_mm2 < old["area_mm2"] else "same"


def compare_b(old: dict | None, new: BResult, changing: set[str]) -> route_ref.Comparison:
    """An open board's result against the recorded one: new, same, better, worse, or not comparable."""
    return _compared(old, new, changing, b_by_value)


def compare_module(old: dict | None, new: MResult, changing: set[str]) -> route_ref.Comparison:
    """A module's result against the recorded one: new, same, better, worse, or not comparable."""
    return _compared(old, new, changing, module_by_value)


def save_results(path: pathlib.Path, boards: list[BResult] = (), modules: list[MResult] = ()) -> None:
    """Rewrite the "b" entries of the boards and the "modules" entries of the modules given, keeping every other entry and key."""
    if not boards and not modules:
        return   # every result was held: preserve the existing baseline bytes
    data = route_ref.load_results(path)
    for r in boards:
        data.setdefault("b", {})[r.board] = asdict(r)
    for r in modules:
        data.setdefault("modules", {})[r.script] = asdict(r)
    pathlib.Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def line_b(r: BResult, c: route_ref.Comparison) -> str:
    if r.failure:
        return "%-22s b %s  %s  FAILED %s: %s" % (
            r.board, route_ref.evidence_line(r.routing_evidence), route_ref.said(c), r.failure, r.detail[:200])
    a = "n/a" if r.a_closure_clean is None else "%.1f%%" % (100 * r.a_closure_clean)
    head = "%-22s b     closure_clean %.1f%% (a %s) open %d new DRC %d vias %d/%d track %.0f/%.0f mm score %.1f %.0fs" % (
        r.board, 100 * r.closure_clean, a, r.open, len(r.new_violations), r.vias, r.ref_vias, r.track_mm, r.ref_track_mm,
        r.run_score, r.seconds)
    return "%s  %s" % (head, route_ref.said(c))


def line_module(r: MResult, c: route_ref.Comparison) -> str:
    head = "%-28s closure_clean %.1f%% area %.1f mm2 score %.1f %.0fs" % (
        r.script, 100 * r.closure_clean, r.area_mm2, r.run_score, r.seconds)
    if r.hand:
        h, p = r.hand, r.placement
        head += "  hand closure_clean %.1f%% area %.1f mm2 crossings %d airwire %.0f mm; placed area %s crossings %s airwire %s" % (
            100 * h["closure_clean"], h["area_mm2"], h["crossings"], h["airwire_mm"],
            "n/a" if r.placed_area_mm2 is None else "%.1f mm2" % r.placed_area_mm2,
            p.get("crossings", "n/a"), "n/a" if p.get("airwire_mm") is None else "%.0f mm" % p["airwire_mm"])
        if h.get("failure"):
            head += "  hand FAILED %s: %s" % (h["failure"], h.get("detail", "")[:200])
            diagnostic = h.get('route_diagnostic', {})
            if diagnostic:
                head += "  hand INVALID diagnostic closure_clean %.1f%% open %d" % (
                    100 * diagnostic['closure_clean'], diagnostic['open_after'])
    return "%s  %s%s" % (head, route_ref.said(c), "  FAILED %s: %s" % (r.failure, r.detail[:200]) if r.failure else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="boards, or with --modules the modules as <family>/<name> or <name> "
                                             "(default: every open board, or every module)")
    ap.add_argument("--modules", action="store_true", help="run the module fixtures instead of the boards")
    ap.add_argument("--update", action="store_true", help="write the results into results.json")
    ap.add_argument("--accept-worse", action="store_true", help="with --update: also write results that are worse than the recorded ones")
    ap.add_argument("--changing", nargs="+", choices=route_ref.COMPONENTS, default=["placemat"],
                    help="the components under change (after the names)")
    ap.add_argument("--work", help="where runs are made (default: a temporary folder)")
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args(argv)
    recorded = route_ref.load_results(pathlib.Path(args.results))
    versions = route_ref.current_versions()
    root = pathlib.Path(args.work) if args.work else pathlib.Path(tempfile.mkdtemp(prefix="placemat-reference-"))
    boards, modules, comparisons, held, worse = [], [], [], [], False
    changing = set(args.changing)

    def save() -> None:   # after each board or module, so a run that stops keeps the ones it finished
        if args.update:
            write, held[:] = route_ref.ratchet(boards + modules, comparisons, args.accept_worse)
            save_results(pathlib.Path(args.results), [r for r in write if isinstance(r, BResult)],
                         [r for r in write if isinstance(r, MResult)])

    try:
        if args.modules:
            found = module_scripts()
            chosen = {n: found[n] for n in found if not args.names or n in args.names or n.split("/")[1] in args.names}
            if args.names and not chosen:
                ap.error("no module among: %s" % ", ".join(args.names))
            with lock.realboard():
                worse = _run_modules(chosen, root, recorded.get("modules", {}), versions, changing, modules, comparisons, save)
        else:
            chosen = [b for b in fetch.load_manifest() if "b" in b.tests and (not args.names or b.name in args.names)]
            if args.names and len(chosen) != len(args.names):
                ap.error("no test (b) board among: %s" % ", ".join(sorted(set(args.names) - {b.name for b in chosen})))
            with lock.realboard():
                worse = _run_boards(chosen, root, recorded, versions, changing, boards, comparisons, save)
    finally:
        if not args.work:   # a --work folder is the caller's, to inspect
            shutil.rmtree(root, ignore_errors=True)
    unresolved = {id(r) for r, c in zip(boards + modules, comparisons) if "routing measurements" in c.differ}
    for r in held:
        name = getattr(r, "board", None) or r.script
        if id(r) in unresolved:
            print("held back, unresolved routing measurements: %s" % name)
        else:
            print("held back, worse than the recorded result: %s (--accept-worse writes it)" % name)
    return 1 if worse or held else 0


def _failed_versions(versions: dict, folder: pathlib.Path) -> dict:
    """`versions` with the router a route of `folder` resolves, "unknown" where that cannot be read."""
    try:
        krt = krt_version(folder)
    except Exception:   # the failure is the result; an unreadable router version does not hide it
        krt = "unknown"
    return dict(versions, krt=krt)


def _failed_digest(script_of) -> str:
    """generation_inputs of the script `script_of()` gives, "" where it cannot be read: a failed run's digest."""
    try:
        return generation_inputs(script_of())
    except Exception:   # what raised is the failure recorded
        return ""


def _run_boards(boards, root, recorded, versions, changing, results, comparisons, save) -> bool:
    """Test (b) on each board; a board whose preparation or run raises is a failed result. `save` is called after each."""
    worse = False
    for board in boards:
        work = root / board.name
        ref_dir = lint.BOARDS_DIR / board.name
        a = recorded.get("a", {}).get(board.name, {}).get("class", {}).get("closure_clean")
        try:
            prepared = prepare.prepare(board, fetch.fetch(board), work / "reference", regenerated=True)
            r = run_b(board, ref_dir, work, prepared=prepared, versions=versions, a_closure_clean=a)
        except Exception as e:   # a failed result, so the other boards still run and are kept
            r = BResult(board.name, NOT_RUN, 0, [], 0, 0.0, 0.0, 0, 0.0, a, 0.0, _failed_versions(versions, ref_dir),
                        type(e).__name__, str(e), _failed_digest(lambda: lint.find_script(board.name, ref_dir.parent)))
        c = compare_b(recorded.get("b", {}).get(board.name), r, changing)
        print(line_b(r, c), flush=True)
        worse = worse or route_ref.lower(c)
        results.append(r)
        comparisons.append(c)
        save()
    return worse


def _run_modules(chosen, root, recorded, versions, changing, results, comparisons, save) -> bool:
    """Each module fixture; a module whose copy or run raises is a failed result. `save` is called after each."""
    worse = False
    for name, script in chosen.items():
        try:
            r = run_module(name, script, root / name.replace("/", "_"), versions=versions)
        except Exception as e:   # a failed result, so the other modules still run and are kept
            r = MResult(name, NOT_RUN, 0.0, 0.0, 0.0, _failed_versions(versions, pathlib.Path(script).parent),
                        type(e).__name__, str(e), _failed_digest(lambda: script))
        c = compare_module(recorded.get(name), r, changing)
        print(line_module(r, c), flush=True)
        worse = worse or route_ref.lower(c)
        results.append(r)
        comparisons.append(c)
        save()
    return worse


if __name__ == "__main__":
    sys.exit(main())
