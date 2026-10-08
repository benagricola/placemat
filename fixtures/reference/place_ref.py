"""Test (b) of the reference set: place and route a reference board from its minimal intent script, and run our own
module fixtures, judging closure.

    .venv/bin/python fixtures/reference/place_ref.py [name ...] [--modules] [--update] [--changing placemat|krt|pcb ...]

An open board (a manifest board with test "b") is run from a clean copy of fixtures/reference/boards/<name>/ with
`placemat run --route --route-full`: the script is linted first and a lint failure is a failed result. The result is
compared with results.json["b"] and carries the human board's vias and track length and test (a)'s clean closure of
the same board. With --modules the module fixtures (every fixtures/*/modules/*/*_layout.py) are run with
`placemat run --route` instead of the boards. Complete routed evidence is compared by shared validity, original
phase closure, whole closure, routed quality and common score; legacy scalar rows remain diagnostics. Results of runs
whose placemat, router or zener versions differ in a component other than those named in
--changing are not compared. --update rewrites the entries of the boards or modules it ran in results.json, after each
one, and keeps the rest. A refused or failed run is a result with its failure kind, not an error of the runner; so is a
board or module whose preparation raises, with the exception's type as its kind.
Real boards: it takes the realboard lock (lock.py) for the whole run, so it waits for the other real-board runs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import dataclasses
import hashlib
import json
import math
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
    measures: dict = dataclasses.field(default_factory=dict)    # the run's measures (score.py), routed quality included
    route_report: dict = dataclasses.field(default_factory=dict)
    score_settings: dict = dataclasses.field(default_factory=dict)
    reference_drc: dict = dataclasses.field(default_factory=dict)  # distinct prepared-baseline comparison evidence


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
    measures: dict = dataclasses.field(default_factory=dict)    # the run's measures (score.py), routed quality included
    route_report: dict = dataclasses.field(default_factory=dict)
    score_settings: dict = dataclasses.field(default_factory=dict)


def asdict(result) -> dict:
    return route_ref.asdict(result)


def module_scripts(root: pathlib.Path = FIXTURES) -> dict[str, pathlib.Path]:
    """The module fixtures that have a layout script: "<family>/<name>" -> script. A folder with several scripts
    (McuButtons, McuButtonsSide) gives one module per script."""
    found = {}
    for script in sorted(pathlib.Path(root).glob("*/modules/*/*_layout.py")):
        found["%s/%s" % (script.parents[2].name, script.name[:-len("_layout.py")])] = script
    return found


def placement_facts(record: dict | None, folder: pathlib.Path, *, script=None) -> dict:
    """What the placement alone measured, from run.json's metrics, before any route: crossings, airwire_mm, area_mm2, placed,
    findings and run_score. {} when the run recorded no placement (a refused script)."""
    metrics = (record or {}).get("metrics") or {}
    if "placed" not in metrics:
        return {}
    facts = {"crossings": metrics.get("crossings"), "airwire_mm": metrics.get("airwire_mm"), "area_mm2": _area(metrics),
             "placed": metrics["placed"], "findings": metrics.get("findings")}
    if metrics.get("measures"):
        facts["run_score"] = run_score(record, folder) if script is None else run_score(record, folder, script=script)
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


def run_score(record: dict, folder: pathlib.Path, *, script=None) -> float:
    """The run score of run.json's measures, at the settings of the board folder."""
    from placemat import score, settings
    return round(score.total(record["metrics"]["measures"], settings.load(pathlib.Path(folder), script=script)), 3)


def _copy_folder(src: pathlib.Path, dst: pathlib.Path) -> None:
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*STATE_DIRS))


def placemat_run(script: pathlib.Path, extra: tuple = (), *, route: bool = True) -> tuple[dict | None, float]:
    """`placemat run <script>` with RUN_ARGS and `extra`: (run.json as a dict, seconds). The record is the newest run of the
    script's folder, None when the run wrote none (a crash or the timeout); the folder is a clean copy, so it holds this
    run's only."""
    script = pathlib.Path(script)
    started = time.time()
    args = RUN_ARGS if route else tuple(a for a in RUN_ARGS if a != "--route")
    cmd = [sys.executable, "-m", "placemat", "run", str(script), *args, *extra]
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
          versions: dict | None = None, a_closure_clean: float | None = None,
          overrides: dict | None = None) -> BResult:
    """Test (b) of one board: lint the script in `ref_dir` (fixtures/reference/boards/<name>/), run it from a clean copy in
    `work` and judge the routed board against the human board. `prepared` is prepare.prepare's of the board, which gives the
    human copper and the baseline DRC the violations are judged against; it is made in work/human when not given.
    The human board here is the manifest's original board, fetched and stripped as for test (a), not the board `pcb
    layout` generates from the imported capture: prepare works on the original, and the generated board has the standard
    library's footprints, not the human's. So ref_vias, ref_track_mm and the baseline DRC are the original board's.
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
    copied = folder / script.name
    cfg = _apply_overrides(copied, overrides or {})
    record, seconds = placemat_run(copied, FULL_ROUTE)
    versions["krt"] = krt_version(folder)
    placement = placement_facts(record, folder, script=copied)
    kind, message = _failure(record)
    if kind:
        return result(failure=kind, detail=message, seconds=round(seconds, 1), versions=versions, placement=placement)
    route = record["metrics"].get("route")
    if not route or not route.get("routed_pcb"):
        return result(failure=NO_ROUTE, seconds=round(seconds, 1), versions=versions, placement=placement)
    _, routed = prepare.measure(pathlib.Path(route["routed_pcb"]))
    new = route_ref.new_violations(prepare.violations_of(route["drc_after"]), prepared.baseline)
    return result(closure_clean=route.get("closure_clean", NOT_RUN), open=route.get("open_after", 0), new_violations=new,
                  vias=routed.vias, track_mm=routed.track_mm, run_score=run_score(record, folder, script=copied), seconds=round(seconds, 1),
                  versions=versions, placement=placement, measures=record["metrics"].get("measures") or {},
                  route_report=deepcopy(route), score_settings=_score_settings(cfg),
                  reference_drc={"baseline": "prepared_reference", "new_violations": len(new)})


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


def run_module(name: str, script: pathlib.Path, work: pathlib.Path, *, versions: dict | None = None,
               overrides: dict | None = None) -> MResult:
    """A module fixture run as a user runs it: `placemat run --route` on the script inside a copy of its family's workspace in
    `work`, so placemat generates the board fresh with `pcb layout` (the checked-in layout/ holds an old run's copper and is not
    the generation) and the repository's files are not written."""
    script = pathlib.Path(script)
    versions = dict(versions if versions is not None else route_ref.current_versions())
    digest = generation_inputs(script)
    copy = _copy_family(script, pathlib.Path(work) / "workspace")
    cfg = _apply_overrides(copy, overrides or {})
    record, seconds = placemat_run(copy)
    versions["krt"] = krt_version(copy.parent)
    placement = placement_facts(record, copy.parent, script=copy)
    kind, message = _failure(record)
    if kind:
        return MResult(name, NOT_RUN, placement.get("area_mm2", 0.0), 0.0, round(seconds, 1), versions, kind, message, digest,
                       placement)
    metrics = record["metrics"]
    return MResult(name, metrics.get("closure_clean", NOT_RUN), _area(metrics), run_score(record, copy.parent, script=copy), round(seconds, 1),
                   versions, inputs_digest=digest, placement=placement, measures=metrics.get("measures") or {},
                   route_report=deepcopy(metrics.get("route") or {}), score_settings=_score_settings(cfg))


def _score_settings(cfg):
    return {key: getattr(cfg, key) for key in cfg.keys() if key.startswith("score_")}


def _differ(old: dict, new, changing: set[str]) -> list[str]:
    """What differs between two runs other than what is under change: component versions, and "inputs" when the capture's
    digest differs (a changed capture re-baselines, it is not a regression). A run that failed before its digest was read
    has none and is not called "inputs"."""
    differ = route_ref.comparable(old.get("versions", {}), new.versions, changing)
    return differ + (["inputs"] if new.inputs_digest and old.get("inputs_digest", "") != new.inputs_digest else [])


def _compared(old: dict | None, new, changing: set[str], value) -> route_ref.Comparison:
    if old is None:
        return route_ref.Comparison("new", [])
    differ = _differ(old, new, changing)
    verdict = value(old, new)
    if differ:
        return route_ref.Comparison("not comparable", differ, "" if verdict == "not comparable" else verdict)
    if verdict == "not comparable":
        return route_ref.Comparison(verdict, ["routed evidence/settings"])
    return route_ref.Comparison(verdict, [])


def _ranked(old: dict, new) -> str:
    """Compare complete routed evidence at identical effective score settings.

    Legacy closure/area values remain display diagnostics; they cannot certify
    a routed comparison without final phase, width and critical evidence.
    """
    from placemat import score
    from placemat.settings import Settings, SettingsError, _validate
    if new.failure and not old.get("failure"):
        return "worse"
    current = asdict(new)
    prices = current.get("score_settings")
    expected = _score_settings(Settings())
    if (not isinstance(prices, dict) or set(prices) != set(expected)
            or prices != old.get("score_settings")):
        return "not comparable"
    for key, value in prices.items():
        if type(value) not in (int, float):
            return "not comparable"
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            return "not comparable"
        try:
            _validate(key, value, 'reference score settings')
        except SettingsError:
            return "not comparable"
    if (new.failure or old.get("failure") or not new.measures or not old.get("measures")
            or new.measures.get("v") != score.MEASURES_VERSION
            or old["measures"].get("v") != score.MEASURES_VERSION):
        return "not comparable"
    cfg = dataclasses.replace(Settings(), **prices)

    def standing(row):
        report = row.get("route_report")
        if not isinstance(report, dict) or not report:
            return None
        if not _known_widths(report):
            return None
        result = score.Standing.of_route(row["measures"], report)
        if result.validity.unmeasured or not result.phase_names or not result.phase_contracts:
            return None
        reference = row.get("reference_drc")
        if "new_violations" in row:
            if (not isinstance(reference, dict) or reference.get("baseline") != "prepared_reference"
                    or type(reference.get("new_violations")) is not int
                    or reference["new_violations"] != len(row["new_violations"])):
                return None
            result = dataclasses.replace(result, validity=dataclasses.replace(
                result.validity, drc_new=reference["new_violations"]))
        return result
    a, b = standing(current), standing(old)
    if a is None or b is None:
        return "not comparable"
    if (a.phase_contracts != b.phase_contracts or a.phase_names != b.phase_names
            or len(a.closures) != len(b.closures)):
        return "not comparable"
    return {-1: "better", 0: "same", 1: "worse"}[score.rank(a, b, cfg)]


def _known_widths(report):
    """Require graded unknown evidence or complete serialized phase checks."""
    if 'required_width_unknown' in report:
        return type(report['required_width_unknown']) is list and not report['required_width_unknown']
    phases = report.get('phases')
    if type(phases) is not list or not phases:
        return False
    for phase in phases:
        if type(phase) is not dict:
            return False
        asked, joined = phase.get('final_asked'), phase.get('final_joined')
        opened, policy = phase.get('final_open'), phase.get('width_policy')
        if (type(asked) is not int or type(joined) is not int or not 0 <= joined <= asked
                or type(opened) is not list or joined + len(opened) != asked or type(policy) is not list
                or (asked and not policy)):
            return False
        if phase.get('final_closure_clean') != (round(joined / asked, 4) if asked else 1.0):
            return False
        required_nets = set()
        for obligation in opened:
            if (type(obligation) is not dict or obligation.get('width_policy_unknown', False) is not False
                    or obligation.get('width_unknown', False) is not False
                    or type(obligation.get('net')) is not str or not obligation['net']):
                return False
            required_nets.add(obligation['net'])
        known_nets = set()
        for scope in policy:
            if type(scope) is not dict or scope.get('name') != phase.get('name'):
                return False
            nets = scope.get('by_net')
            if type(nets) is not dict or (asked and not nets):
                return False
            if any(type(net) is not str or not net for net in nets):
                return False
            known_nets.update(nets)
            for entry in nets.values():
                if type(entry) is not dict or entry.get('status') != 'known':
                    return False
                widths = entry.get('widths')
                if type(widths) is not dict or not widths:
                    return False
                for layer, width in widths.items():
                    if type(layer) is not str or not layer or type(width) not in (int, float):
                        return False
                    try:
                        finite = math.isfinite(width)
                    except OverflowError:
                        finite = False
                    if not finite or width <= 0:
                        return False
        if not required_nets <= known_nets:
            return False
    return True


def b_by_value(old: dict, new: BResult) -> str:
    return _ranked(old, new)


def module_by_value(old: dict, new: MResult) -> str:
    return _ranked(old, new)


def compare_b(old: dict | None, new: BResult, changing: set[str]) -> route_ref.Comparison:
    """An open board's result against the recorded one: new, same, better, worse, or not comparable."""
    return _compared(old, new, changing, b_by_value)


def compare_module(old: dict | None, new: MResult, changing: set[str]) -> route_ref.Comparison:
    """A module's result against the recorded one: new, same, better, worse, or not comparable."""
    return _compared(old, new, changing, module_by_value)


def save_results(path: pathlib.Path, boards: list[BResult] = (), modules: list[MResult] = ()) -> None:
    """Rewrite the "b" entries of the boards and the "modules" entries of the modules given, keeping every other entry and key."""
    data = route_ref.load_results(path)
    for r in boards:
        data.setdefault("b", {})[r.board] = asdict(r)
    for r in modules:
        data.setdefault("modules", {})[r.script] = asdict(r)
    pathlib.Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def line_b(r: BResult, c: route_ref.Comparison) -> str:
    a = "n/a" if r.a_closure_clean is None else "%.1f%%" % (100 * r.a_closure_clean)
    head = "%-22s b     closure_clean %.1f%% (a %s) open %d new DRC %d vias %d/%d track %.0f/%.0f mm score %.1f %.0fs" % (
        r.board, 100 * r.closure_clean, a, r.open, len(r.new_violations), r.vias, r.ref_vias, r.track_mm, r.ref_track_mm,
        r.run_score, r.seconds)
    return "%s  %s%s" % (head, route_ref.said(c), "  FAILED %s: %s" % (r.failure, r.detail[:200]) if r.failure else "")


def line_module(r: MResult, c: route_ref.Comparison) -> str:
    head = "%-28s closure_clean %.1f%% area %.1f mm2 score %.1f %.0fs" % (
        r.script, 100 * r.closure_clean, r.area_mm2, r.run_score, r.seconds)
    return "%s  %s%s" % (head, route_ref.said(c), "  FAILED %s: %s" % (r.failure, r.detail[:200]) if r.failure else "")


def _apply_overrides(copied, overrides):
    """Validate and write settings only in the copied script's workspace."""
    from placemat import settings
    from placemat.script_edit import toml_set
    settings.load(copied.parent, overrides=overrides, script=copied)
    if overrides:
        path = copied.parent / "placemat.toml"
        text = path.read_text() if path.exists() else ""
        for name, value in overrides.items():
            section, key = settings.split_key(name)
            text = toml_set(text, ["scripts", copied.name, section], key, value)
        path.write_text(text)
    return settings.load(copied.parent, script=copied)


def run_placement(name, script, work, *, module, versions, overrides):
    """Placement only in a clean workspace, with overrides confined to that copy."""
    script = pathlib.Path(script)
    digest = generation_inputs(script)
    if module:
        copied = _copy_family(script, work / "workspace")
    else:
        _copy_folder(script.parent, work / "board")
        copied = work / "board" / script.name
    cfg = _apply_overrides(copied, overrides)
    record, seconds = placemat_run(copied, route=False)
    kind, message = _failure(record)
    return dict(placement_facts(record, copied.parent, script=copied), versions=versions, inputs_digest=digest,
                measures=((record or {}).get("metrics") or {}).get("measures") or {},
                score_settings={k: getattr(cfg, k) for k in cfg.keys() if k.startswith("score_")},
                seconds=round(seconds, 3), failure=kind, detail=message)


def compare_placement(old, new, changing):
    """Placement-only verdict under the current run's weights and common validity."""
    from placemat import score
    from placemat.settings import Settings
    if old is None:
        return "new"
    if route_ref.comparable(old.get("versions", {}), new["versions"], changing) or old.get("inputs_digest") != new.get("inputs_digest"):
        return "not comparable"
    if bool(old.get("failure")) != bool(new.get("failure")):
        return "worse" if new.get("failure") else "better"
    if new.get("failure"):
        return "same"
    a, b = new.get("measures") or {}, old.get("measures") or {}
    if a.get("v") != score.MEASURES_VERSION or b.get("v") != score.MEASURES_VERSION:
        return "not comparable"
    cfg = dataclasses.replace(Settings(), **new.get("score_settings", {}))
    def standing(m):
        return score.Standing(m, score.Validity.of(m, drc_new=m.get("drc")))
    return {-1: "better", 0: "same", 1: "worse"}[score.rank(standing(a), standing(b), cfg)]


def _setting_overrides(values, ap, root):
    from placemat.settings import Settings, SettingsError, load
    overrides = {}
    for setting in values:
        name, equal, value = setting.partition("=")
        name = name.replace(".", "_")
        if not equal or name not in Settings.keys():
            ap.error("--set needs a known setting NAME=VALUE")
        try:
            overrides[name] = json.loads(value)
        except json.JSONDecodeError:
            overrides[name] = value
    try:
        load(root, overrides=overrides)
    except SettingsError as e:
        ap.error(str(e))
    return overrides


def _placement_only(args, ap, root, recorded, versions):
    """Record placement measures independently of the routed reference baseline."""
    overrides = _setting_overrides(args.set, ap, root)
    if args.modules:
        found = module_scripts()
        chosen = {n: p for n, p in found.items() if not args.names or n in args.names or n.split("/")[1] in args.names}
    else:
        boards = [b for b in fetch.load_manifest() if "b" in b.tests and (not args.names or b.name in args.names)]
        chosen = {b.name: lint.find_script(b.name) for b in boards}
    if args.names and not chosen:
        ap.error("no placement fixture among: %s" % ", ".join(args.names))
    results = dict(recorded.get("placement", {}))
    worse = False
    with lock.realboard():
        for name, script in chosen.items():
            try:
                if not args.modules:
                    fixed = next(b.fixed for b in boards if b.name == name)
                    problems = lint.lint(script, fixed).problems
                    if problems:
                        raise ValueError("reference script failed intent lint: " + "; ".join(
                            "line %d %s %s" % (p.line, p.rule, p.ref) for p in problems))
                row = run_placement(name, script, root / name.replace("/", "_"), module=args.modules,
                                    versions=versions, overrides=overrides)
            except Exception as e:
                row = dict(versions=versions, failure=type(e).__name__, detail=str(e), measures={})
            status = compare_placement(results.get(name), row, set(args.changing))
            worse = worse or status == "worse"
            if status != "worse" or args.accept_worse:
                results[name] = row
            print(json.dumps(dict(name=name, comparison=status, **row), sort_keys=True), flush=True)
            if args.update:
                recorded["placement"] = results
                pathlib.Path(args.results).write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n")
    return int(worse or any(results.get(n, {}).get("failure") for n in chosen))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="boards, or with --modules the modules as <family>/<name> or <name> "
                                             "(default: every open board, or every module)")
    ap.add_argument("--modules", action="store_true", help="run the module fixtures instead of the boards")
    ap.add_argument("--place-only", action="store_true", help="measure placement without routing")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="setting override in the copied workspace")
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
    if args.place_only:
        try:
            return _placement_only(args, ap, root, recorded, versions)
        finally:
            if not args.work:
                shutil.rmtree(root, ignore_errors=True)

    def save() -> None:   # after each board or module, so a run that stops keeps the ones it finished
        if args.update:
            write, held[:] = route_ref.ratchet(boards + modules, comparisons, args.accept_worse)
            save_results(pathlib.Path(args.results), [r for r in write if isinstance(r, BResult)],
                         [r for r in write if isinstance(r, MResult)])

    try:
        overrides = _setting_overrides(args.set, ap, root)
        if args.modules:
            found = module_scripts()
            chosen = {n: found[n] for n in found if not args.names or n in args.names or n.split("/")[1] in args.names}
            if args.names and not chosen:
                ap.error("no module among: %s" % ", ".join(args.names))
            with lock.realboard():
                worse = _run_modules(chosen, root, recorded.get("modules", {}), versions, changing, modules, comparisons, save, overrides=overrides)
        else:
            chosen = [b for b in fetch.load_manifest() if "b" in b.tests and (not args.names or b.name in args.names)]
            if args.names and len(chosen) != len(args.names):
                ap.error("no test (b) board among: %s" % ", ".join(sorted(set(args.names) - {b.name for b in chosen})))
            with lock.realboard():
                worse = _run_boards(chosen, root, recorded, versions, changing, boards, comparisons, save, overrides=overrides)
    finally:
        if not args.work:   # a --work folder is the caller's, to inspect
            shutil.rmtree(root, ignore_errors=True)
    for r in held:
        print("held back, worse than the recorded result: %s (--accept-worse writes it)" % (getattr(r, "board", None) or r.script))
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


def _run_boards(boards, root, recorded, versions, changing, results, comparisons, save, *, overrides=None) -> bool:
    """Test (b) on each board; a board whose preparation or run raises is a failed result. `save` is called after each."""
    worse = False
    for board in boards:
        work = root / board.name
        ref_dir = lint.BOARDS_DIR / board.name
        a = recorded.get("a", {}).get(board.name, {}).get("class", {}).get("closure_clean")
        try:
            prepared = prepare.prepare(board, fetch.fetch(board), work / "human")
            r = run_b(board, ref_dir, work, prepared=prepared, versions=versions, a_closure_clean=a, overrides=overrides)
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


def _run_modules(chosen, root, recorded, versions, changing, results, comparisons, save, *, overrides=None) -> bool:
    """Each module fixture; a module whose copy or run raises is a failed result. `save` is called after each."""
    worse = False
    for name, script in chosen.items():
        try:
            r = run_module(name, script, root / name.replace("/", "_"), versions=versions, overrides=overrides)
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
