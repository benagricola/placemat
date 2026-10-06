"""Test (b) of the reference set: place and route a reference board from its minimal intent script, and run our own
module fixtures, judging closure.

    .venv/bin/python fixtures/reference/place_ref.py [name ...] [--modules] [--update] [--changing placemat|krt|pcb]

An open board (a manifest board with test "b") is run from a clean copy of fixtures/reference/boards/<name>/ with
`placemat run --route --route-full`: the script is linted first and a lint failure is a failed result. The result is
compared with results.json["b"] and carries the human board's vias and track length and test (a)'s clean closure of
the same board. With --modules the module fixtures (every fixtures/*/modules/*/*_layout.py) are run with
`placemat run --route` instead of the boards, and compared with results.json["modules"]: closure, then the area of the
fitted frame. Results of runs whose placemat, router or zener versions differ in a component other than --changing are
not compared. --update rewrites the entries of the boards or modules it ran in results.json and keeps the rest.
A refused or failed run is a result with its failure kind, not an error of the runner.
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

from fixtures.reference import fetch, lint, lock, prepare, route_ref   # noqa: E402

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
WORKSPACE_DIRS = ("modules", "parts")   # what a module needs of its family folder besides its own
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


@dataclasses.dataclass(frozen=True)
class MResult:
    script: str             # "<family>/<module>", e.g. "mnb/SwdHeader"
    closure_clean: float
    area_mm2: float         # the fitted frame's width x height
    run_score: float
    seconds: float
    versions: dict
    failure: str = ""
    detail: str = ""
    inputs_digest: str = ""
    placement: dict = dataclasses.field(default_factory=dict)


def asdict(result) -> dict:
    return dataclasses.asdict(result)


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


def placemat_run(script: pathlib.Path, extra: tuple = ()) -> tuple[dict | None, float]:
    """`placemat run <script>` with RUN_ARGS and `extra`: (run.json as a dict, seconds). The record is the newest run of the
    script's folder, None when the run wrote none (a crash or the timeout); the folder is a clean copy, so it holds this
    run's only."""
    script = pathlib.Path(script)
    started = time.time()
    cmd = [sys.executable, "-m", "placemat", "run", str(script), *RUN_ARGS, *extra]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "failure": {"kind": TIMEOUT, "message": "no result in %d s" % RUN_TIMEOUT_S}}, time.time() - started
    seconds = time.time() - started
    records = sorted((script.parent / ".placemat" / "runs").glob("*/run.json"), key=lambda p: p.stat().st_mtime)
    if not records:
        return None, seconds
    record = json.loads(records[-1].read_text())
    if proc.returncode and not record.get("failure") and record.get("status") == "ok":
        record["failure"] = {"kind": "exit %d" % proc.returncode, "message": (proc.stderr or proc.stdout)[-500:]}
    return record, seconds


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
    """Test (b) of one board: lint the script in `ref_dir` (fixtures/reference/boards/<name>/), run it from a clean copy in
    `work` and judge the routed board against the human board. `prepared` is prepare.prepare's of the board, which gives the
    human copper and the baseline DRC the violations are judged against; it is made in work/human when not given.
    A DRC error counts as new unless the stripped human board has one of its type and nets where it is, so the violations of
    the fixed parts' own places are not counted. The runner does not take the lock; main does."""
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
        prepared = prepare.prepare(board, fetch.fetch(board), work / "human")
        human = prepared.human
    folder = work / "board"
    _copy_folder(ref_dir, folder)
    record, seconds = placemat_run(folder / script.name, FULL_ROUTE)
    versions["krt"] = krt_version(folder)
    placement = placement_facts(record, folder)
    kind, message = _failure(record)
    if kind:
        return result(failure=kind, detail=message, seconds=round(seconds, 1), versions=versions, placement=placement)
    route = record["metrics"].get("route")
    if not route or not route.get("routed_pcb"):
        return result(failure=NO_ROUTE, seconds=round(seconds, 1), versions=versions, placement=placement)
    _, routed = prepare.measure(pathlib.Path(route["routed_pcb"]))
    new = route_ref.new_violations(prepare.violations_of(route["drc_after"]), prepared.baseline)
    return result(closure_clean=route.get("closure_clean", NOT_RUN), open=route.get("open_after", 0), new_violations=new,
                  vias=routed.vias, track_mm=routed.track_mm, run_score=run_score(record, folder), seconds=round(seconds, 1),
                  versions=versions, placement=placement)


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
    kind, message = _failure(record)
    if kind:
        return MResult(name, NOT_RUN, placement.get("area_mm2", 0.0), 0.0, round(seconds, 1), versions, kind, message, digest,
                       placement)
    metrics = record["metrics"]
    return MResult(name, metrics.get("closure_clean", NOT_RUN), _area(metrics), run_score(record, copy.parent), round(seconds, 1),
                   versions, inputs_digest=digest, placement=placement)


def _differ(old: dict, new, changing: str) -> list[str]:
    """What differs between two runs other than what is under change: component versions, and "inputs" when the capture's
    digest differs (a changed capture re-baselines, it is not a regression)."""
    differ = route_ref.comparable(old.get("versions", {}), new.versions, changing)
    return differ + (["inputs"] if old.get("inputs_digest", "") != new.inputs_digest else [])


def _worse_closure(old: dict, new) -> bool:
    return bool(new.failure) and not old.get("failure") or new.closure_clean < old["closure_clean"]


def compare_b(old: dict | None, new: BResult, changing: str) -> route_ref.Comparison:
    """An open board's result against the recorded one: worse is a lower clean closure or a lint failure."""
    if old is None:
        return route_ref.Comparison("new", [])
    differ = _differ(old, new, changing)
    if differ:
        return route_ref.Comparison("not comparable", differ)
    if _worse_closure(old, new):
        return route_ref.Comparison("worse", [])
    if new.closure_clean > old["closure_clean"] or (old.get("failure") and not new.failure):
        return route_ref.Comparison("better", [])
    return route_ref.Comparison("same", [])


def compare_module(old: dict | None, new: MResult, changing: str) -> route_ref.Comparison:
    """A module's result against the recorded one: worse is a lower clean closure, or at equal closure a larger area."""
    if old is None:
        return route_ref.Comparison("new", [])
    differ = _differ(old, new, changing)
    if differ:
        return route_ref.Comparison("not comparable", differ)
    if _worse_closure(old, new):
        return route_ref.Comparison("worse", [])
    if new.closure_clean > old["closure_clean"]:
        return route_ref.Comparison("better", [])
    if new.area_mm2 > old["area_mm2"]:
        return route_ref.Comparison("worse", [])
    return route_ref.Comparison("better" if new.area_mm2 < old["area_mm2"] else "same", [])


def save_results(path: pathlib.Path, boards: list[BResult] = (), modules: list[MResult] = ()) -> None:
    """Rewrite the "b" entries of the boards and the "modules" entries of the modules given, keeping every other entry and key."""
    data = route_ref.load_results(path)
    for r in boards:
        data.setdefault("b", {})[r.board] = asdict(r)
    for r in modules:
        data.setdefault("modules", {})[r.script] = asdict(r)
    pathlib.Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _said(c: route_ref.Comparison) -> str:
    return "not comparable: %s differ" % ", ".join(c.differ) if c.status == "not comparable" else c.status


def line_b(r: BResult, c: route_ref.Comparison) -> str:
    a = "n/a" if r.a_closure_clean is None else "%.1f%%" % (100 * r.a_closure_clean)
    head = "%-22s b     closure_clean %.1f%% (a %s) open %d new DRC %d vias %d/%d track %.0f/%.0f mm score %.1f %.0fs" % (
        r.board, 100 * r.closure_clean, a, r.open, len(r.new_violations), r.vias, r.ref_vias, r.track_mm, r.ref_track_mm,
        r.run_score, r.seconds)
    return "%s  %s%s" % (head, _said(c), "  FAILED %s: %s" % (r.failure, r.detail[:200]) if r.failure else "")


def line_module(r: MResult, c: route_ref.Comparison) -> str:
    head = "%-28s closure_clean %.1f%% area %.1f mm2 score %.1f %.0fs" % (
        r.script, 100 * r.closure_clean, r.area_mm2, r.run_score, r.seconds)
    return "%s  %s%s" % (head, _said(c), "  FAILED %s: %s" % (r.failure, r.detail[:200]) if r.failure else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="boards, or with --modules the modules as <family>/<name> or <name> "
                                             "(default: every open board, or every module)")
    ap.add_argument("--modules", action="store_true", help="run the module fixtures instead of the boards")
    ap.add_argument("--update", action="store_true", help="write the results into results.json")
    ap.add_argument("--accept-worse", action="store_true", help="with --update: also write results that are worse than the recorded ones")
    ap.add_argument("--changing", choices=route_ref.COMPONENTS, default="placemat", help="the component under change")
    ap.add_argument("--work", help="where runs are made (default: a temporary folder)")
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args(argv)
    recorded = route_ref.load_results(pathlib.Path(args.results))
    versions = route_ref.current_versions()
    root = pathlib.Path(args.work) if args.work else pathlib.Path(tempfile.mkdtemp(prefix="placemat-reference-"))
    boards, modules, statuses, worse = [], [], [], False
    try:
        if args.modules:
            found = module_scripts()
            chosen = {n: found[n] for n in found if not args.names or n in args.names or n.split("/")[1] in args.names}
            if args.names and not chosen:
                ap.error("no module among: %s" % ", ".join(args.names))
            with lock.realboard():
                worse = _run_modules(chosen, root, recorded.get("modules", {}), versions, args.changing, modules, statuses)
        else:
            chosen = [b for b in fetch.load_manifest() if "b" in b.tests and (not args.names or b.name in args.names)]
            if args.names and len(chosen) != len(args.names):
                ap.error("no test (b) board among: %s" % ", ".join(sorted(set(args.names) - {b.name for b in chosen})))
            with lock.realboard():
                worse = _run_boards(chosen, root, recorded, versions, args.changing, boards, statuses)
    finally:
        if not args.work:   # a --work folder is the caller's, to inspect
            shutil.rmtree(root, ignore_errors=True)
    held = []
    if args.update:
        done = boards + modules
        write, held = route_ref.ratchet(done, statuses, args.accept_worse)
        save_results(pathlib.Path(args.results), [r for r in write if isinstance(r, BResult)],
                     [r for r in write if isinstance(r, MResult)])
        for r in held:
            print("held back, worse than the recorded result: %s (--accept-worse writes it)" % (getattr(r, "board", None) or r.script))
    return 1 if worse or held else 0


def _run_boards(boards, root, recorded, versions, changing, results, statuses) -> bool:
    worse = False
    for board in boards:
        work = root / board.name
        a = recorded.get("a", {}).get(board.name, {}).get("class", {})
        prepared = prepare.prepare(board, fetch.fetch(board), work / "human")
        r = run_b(board, lint.BOARDS_DIR / board.name, work, prepared=prepared, versions=versions,
                  a_closure_clean=a.get("closure_clean"))
        c = compare_b(recorded.get("b", {}).get(board.name), r, changing)
        print(line_b(r, c), flush=True)
        worse = worse or c.status == "worse"
        results.append(r)
        statuses.append(c.status)
    return worse


def _run_modules(chosen, root, recorded, versions, changing, results, statuses) -> bool:
    worse = False
    for name, script in chosen.items():
        r = run_module(name, script, root / name.replace("/", "_"), versions=versions)
        c = compare_module(recorded.get(name), r, changing)
        print(line_module(r, c), flush=True)
        worse = worse or c.status == "worse"
        results.append(r)
        statuses.append(c.status)
    return worse


if __name__ == "__main__":
    sys.exit(main())
