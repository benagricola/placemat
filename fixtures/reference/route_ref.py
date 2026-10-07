"""Test (a) of the reference set: route each board's human placement with its copper stripped, and judge clean closure and
the DRC errors the route adds to the stripped board's baseline.

    .venv/bin/python fixtures/reference/route_ref.py [name ...] [--update] [--changing placemat|krt|pcb ...]

For each test (a) board it runs the route with the net classes' widths, then with the human's track width where the manifest
gives one, and compares each result with results.json["a"]. Results of runs whose placemat, router or zener versions differ
in a component other than those named in --changing are not compared. --update writes the boards it ran into
results.json["a"], after each board. A board whose preparation or route raises is a failed result, not an error of the
runner.
Real boards: it takes the realboard lock (lock.py) for the whole run, so it waits for the other real-board runs.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

if __package__ in (None, ""):   # run as a script: the repository root, for `fixtures.reference`
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fixtures.reference import fetch, lock, prepare   # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
LOCAL = {"obstructed-route": REPO / "fixtures/obstructed_route"}
LOCAL_PROTOCOL = {"obstructed-route": {"KICAD_NET_RESCUE": "0"}}
RESULTS = HERE / "results.json"
COMPONENTS = ("placemat", "krt", "pcb")
WIDTHS = ("class", "human")
ROUTE_TIMEOUT_S = 3600
GIT_TIMEOUT_S = 30
CLEAN = 1.0
DIRTY = "-dirty"
OWN_OUTPUT = "fixtures/reference/results.json"   # the runners write it; it does not make the checkout dirty
NEAR_MM = 0.05   # a violation this close to a baseline one, of the same type and nets, is that one


@dataclasses.dataclass(frozen=True)
class AResult:
    board: str
    widths: str   # "class" or "human"
    closure_clean: float
    open: int
    open_nets: list[str]
    new_violations: list[prepare.Violation]
    vias: int
    track_mm: float
    human_vias: int
    human_track_mm: float
    passed: bool
    seconds: float
    versions: dict   # placemat, krt, pcb
    failure: str = ""   # "" when the route ran; else the type of the exception that stopped it
    detail: str = ""    # what the exception said


@dataclasses.dataclass(frozen=True)
class FResult:
    fixture: str
    phases: list
    widths_failed: int
    drc_new: int | None
    vias: int
    track_mm: float
    passed: bool
    seconds: float
    versions: dict
    failure: str = ""
    detail: str = ""
    protocol: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class Comparison:
    status: str   # new, same, better, worse or not comparable
    differ: list[str]   # with "not comparable": the components whose versions differ
    value: str = ""     # with "not comparable": what the values alone say (same, better or worse), versions ignored


def lower(c: Comparison) -> bool:
    """Whether a result is below the recorded one: worse, or not comparable and worse on the values alone."""
    return c.status == "worse" or (c.status == "not comparable" and c.value == "worse")


def new_violations(after: list[prepare.Violation], baseline: list[prepare.Violation],
                   tol_mm: float = NEAR_MM) -> list[prepare.Violation]:
    """What `after` has that no baseline violation of the same type and nets matches within `tol_mm`."""
    def known(v):
        return any(b.type == v.type and b.nets == v.nets and abs(b.at_mm[0] - v.at_mm[0]) <= tol_mm
                   and abs(b.at_mm[1] - v.at_mm[1]) <= tol_mm for b in baseline)
    return [v for v in after if not known(v)]


def judge(route_json: dict, new: list[prepare.Violation], template: AResult) -> AResult:
    """The result of a route: `template` (board, widths, the human's copper, versions) with what route.json says, and `new`.
    vias and track_mm are the routed board's, which the caller measures and puts in the report."""
    closure = route_json.get("closure_clean", template.closure_clean)
    return dataclasses.replace(
        template, closure_clean=closure, open=route_json.get("open_after", 0),
        open_nets=sorted(route_json.get("open_nets", ())), new_violations=list(new),
        vias=route_json.get("vias", template.vias), track_mm=route_json.get("track_mm", template.track_mm),
        passed=closure == CLEAN and not new, seconds=route_json.get("seconds", template.seconds))


def comparable(old: dict, new: dict, changing: set[str]) -> list[str]:
    """The components not in `changing` whose versions differ between two results' `versions`."""
    return [c for c in COMPONENTS if c not in changing and old.get(c) != new.get(c)]


def by_value(old: dict, new: AResult) -> str:
    """same, better or worse: a result's values against the recorded one's, whatever the versions. A failure where the
    recorded entry had none is worse."""
    if new.failure and not old.get("failure"):
        return "worse"
    gained = len(new.new_violations) - len(old.get("new_violations", ()))
    if (old["passed"] and not new.passed) or new.closure_clean < old["closure_clean"]:
        return "worse"
    if new.closure_clean == old["closure_clean"] and gained > 0:
        return "worse"
    if (new.passed and not old["passed"]) or new.closure_clean > old["closure_clean"] or (old.get("failure") and not new.failure):
        return "better"
    return "same"


def compare(old: dict | None, new: AResult, changing: set[str]) -> Comparison:
    """A result against the recorded one (its dict): new, same, better, worse, or not comparable."""
    if old is None:
        return Comparison("new", [])
    value = by_value(old, new)
    differ = comparable(old.get("versions", {}), new.versions, changing)
    if differ:
        return Comparison("not comparable", differ, value)
    return Comparison(value, [])


def ratchet(results: list, comparisons: list[Comparison], accept_worse: bool) -> tuple[list, list]:
    """(what --update writes, what it holds back): a result that is `lower` than the recorded one is held back unless
    `accept_worse`, so a baseline is never lowered without the user's approval. Other "not comparable" results are
    written (a re-baseline)."""
    if accept_worse:
        return list(results), []
    held = [r for r, c in zip(results, comparisons) if lower(c)]
    return [r for r, c in zip(results, comparisons) if not lower(c)], held


def _violation_key(v) -> tuple:
    return (v["type"], list(v["nets"]), list(v["at_mm"]))


def asdict(result) -> dict:
    """A result as results.json holds it, its new violations sorted so a rerun does not reorder them."""
    out = dataclasses.asdict(result)
    if "new_violations" in out:
        out["new_violations"] = sorted(out["new_violations"], key=_violation_key)
    return out


def load_results(path: pathlib.Path = RESULTS) -> dict:
    path = pathlib.Path(path)
    return json.loads(path.read_text()) if path.exists() else {}


def save_results(path: pathlib.Path, results: list[AResult]) -> None:
    """Rewrite the "a" entries of the boards `results` are of, keeping the other boards and the other keys."""
    data = load_results(path)
    a = data.setdefault("a", {})
    for r in results:
        a.setdefault(r.board, {})[r.widths] = asdict(r)
    pathlib.Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def save_local(path: pathlib.Path, results: list[FResult]) -> None:
    """Keep local fixture evidence alongside the board and module results."""
    data = load_results(path)
    fixtures = data.setdefault("fixtures", {})
    for result in results:
        fixtures[result.fixture] = asdict(result)
    pathlib.Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _blockers(evidence) -> list[str]:
    names = []
    for blocker in (evidence or {}).get("blocked_by") or ():
        name = blocker.get("ref") or "%s copper" % blocker.get("net", "unidentified")
        if name not in names:
            names.append(name)
    return names


def _local_open(opened: dict) -> dict:
    evidence = opened.get("evidence") or {}
    return dict(net=opened["net"], **{"from": opened["from"], "to": opened["to"]},
                outcome=opened.get("outcome"), diagnosis=evidence.get("diagnosis"), blockers=_blockers(evidence),
                **{key: opened[key] for key in ("widths", "under", "violated", "width_unknown") if key in opened})


def run_local(name: str, work: pathlib.Path, versions: dict | None = None) -> FResult:
    """Route a local board unchanged, retaining phase closure and router failure evidence."""
    src, work = LOCAL[name], pathlib.Path(work)
    versions = dict(versions if versions is not None else current_versions())
    versions.setdefault("krt", "unknown")
    protocol = dict(LOCAL_PROTOCOL.get(name, {}))
    env = dict(os.environ, **protocol)
    try:
        work.mkdir(parents=True, exist_ok=True)
        for filename in ("layout.kicad_pcb", "layout.kicad_pro", "placemat.toml"):
            shutil.copy(src / filename, work / filename)
        versions["krt"] = _krt_version(work / "layout.kicad_pcb")
        report = _route(work / "layout.kicad_pcb", work / "route", (src / "placemat.toml").read_text(), env=env)
        if report.get("error"):
            raise RuntimeError("placemat route failed: %s" % report["error"])
        phases = [{"name": phase["name"], "asked": phase["asked"], "joined": phase["joined"],
                   "closure_clean": phase["closure_clean"],
                   "final_closure_clean": phase.get("final_closure_clean"),
                   "open": [_local_open(opened) for opened in phase.get("open") or ()],
                   **({"final_asked": phase["final_asked"]} if "final_asked" in phase else {}),
                   **({"final_joined": phase["final_joined"]} if "final_joined" in phase else {}),
                   **({"final_open": [_local_open(opened) for opened in phase["final_open"]]}
                      if "final_open" in phase else {})}
                  for phase in report.get("phases") or ()]
    except Exception as error:   # like a failed reference board, keep the failure for inspection
        return _local_record(FResult(name, [], 0, None, 0, 0.0, False, 0.0, versions, type(error).__name__, str(error), protocol), work)
    return _local_record(FResult(name, phases, report.get("widths_failed", 0), report.get("drc_new"), report.get("vias", 0),
                                report.get("track_mm", 0.0), True, report.get("seconds", 0.0), versions, protocol=protocol), work)


def _local_record(result: FResult, work: pathlib.Path) -> FResult:
    """Retain this invocation's provenance even when the shared baseline is not updated."""
    (work / "local_result.json").write_text(json.dumps(asdict(result), indent=2) + "\n")
    return result


def compare_local(old: dict | None, new: FResult, changing: set[str]) -> Comparison:
    """A fixture records observed behavior; comparisons say same or changed, never better or worse."""
    if old is None:
        return Comparison("new", [])
    keys = ("phases", "widths_failed", "drc_new", "passed", "failure", "protocol")
    value = "same" if all(old.get(key) == getattr(new, key) for key in keys) else "changed"
    differ = comparable(old.get("versions", {}), new.versions, changing)
    return Comparison("not comparable", differ, value) if differ else Comparison(value, [])


def local_line(result: FResult, comparison: Comparison) -> str:
    def entry_line(phase, entry, stage):
        status = ("DRC" if entry.get("violated") else "width unproven" if entry.get("width_unknown") else
                  "under width" if entry.get("under") else entry["outcome"] or "open")
        return "%s %s %s %s" % (phase["name"], stage, status, "/".join(entry["blockers"]) or entry["net"])
    opened = [entry_line(phase, entry, "final" if "final_open" in phase else "")
              for phase in result.phases for entry in phase.get("final_open", phase["open"])]
    initial = [entry_line(phase, entry, "initial") for phase in result.phases if "final_open" in phase
               for entry in phase["open"]]
    return "%-22s %s widths failed %d new DRC %s  %s  %s%s" % (
        result.fixture, "ran" if result.passed else "FAIL", result.widths_failed,
        "-" if result.drc_new is None else result.drc_new,
        "; ".join(opened + initial) or "nothing open", said(comparison),
        "  FAILED %s: %s" % (result.failure, result.detail[:200]) if result.failure else "")


def _git(root: str, *args: str) -> str:
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S).stdout.strip()


def _git_head(root: str) -> str:
    """The commit of a checkout, with "-dirty" when it has uncommitted changes to tracked files."""
    head = _git(root, "rev-parse", "HEAD") or "unknown"
    changed = [l for l in _git(root, "status", "--porcelain", "-uno").splitlines() if not l.endswith(OWN_OUTPUT)]
    return head + DIRTY if changed else head


def _krt_version(board_pcb: pathlib.Path) -> str:
    """The commit of the router the route of this board resolves: [route] router_dir of the board's folder, else $KRT_DIR (route.RouterMissing with neither)."""
    from placemat.kicad.route import router_dir
    from placemat.settings import load
    return _git_head(router_dir(load(pathlib.Path(board_pcb).parent)))


def pcb_version() -> str:
    """Commit of the checkout containing the resolved executable, else its version."""
    binary = shutil.which("pcb")
    if binary is None:
        return "unknown"
    executable = pathlib.Path(binary).resolve()
    for parent in executable.parents:
        if (parent / ".git").exists() and _git(str(parent), "rev-parse", "HEAD"):
            return _git_head(str(parent))
    proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    return proc.stdout.strip() or "unknown"


def current_versions() -> dict:
    """The placemat checkout's commit and zener's version; "krt" is the router a route used (run_a)."""
    import placemat
    return {"placemat": _git_head(str(pathlib.Path(placemat.__file__).resolve().parent)), "pcb": pcb_version()}


def _route(pcb: pathlib.Path, work: pathlib.Path, toml: str | None, *, env=None) -> dict:
    """`placemat route pcb --full` into `work`, with `toml` as placemat.toml beside the board; route.json as a dict."""
    config = pathlib.Path(pcb).with_name("placemat.toml")
    if toml is None:
        config.unlink(missing_ok=True)
    else:
        config.write_text(toml)
    cmd = [sys.executable, "-m", "placemat", "route", str(pcb), "--full", "--no-resume", "--out", str(work)]
    out = pathlib.Path(work) / "route.json"
    out.unlink(missing_ok=True)     # only this invocation's report can establish its result
    import math
    import signal
    import time
    child_env = dict(os.environ if env is None else env)
    deadline = time.time() + ROUTE_TIMEOUT_S - min(10.0, ROUTE_TIMEOUT_S / 4)
    if "KRT_ROUTE_DEADLINE_UTC" in child_env:
        try:
            inherited = float(child_env["KRT_ROUTE_DEADLINE_UTC"])
            if not math.isfinite(inherited):
                raise ValueError
        except (TypeError, ValueError):
            raise RuntimeError("invalid inherited router deadline") from None
        deadline = min(deadline, inherited)
    child_env["KRT_ROUTE_DEADLINE_UTC"] = str(deadline)
    # Placemat's ordinary children share this owned group. KRT's isolated candidate/grader groups
    # receive the earlier absolute deadline above and are reaped by their own supervising process.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True, env=child_env)
    try:
        stdout, stderr = proc.communicate(timeout=ROUTE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
        raise RuntimeError("placemat route timed out after %s seconds" % ROUTE_TIMEOUT_S) from None
    if proc.returncode != 0:
        raise RuntimeError("placemat route exited %d: %s" % (proc.returncode, (stderr or stdout)[-500:]))
    if not out.exists():
        raise RuntimeError("placemat route wrote no route.json (rc %d): %s" % (proc.returncode, (stderr or stdout)[-500:]))
    report = json.loads(out.read_text())
    if report.get("error"):
        raise RuntimeError("placemat route failed: %s" % report["error"])
    return report


def phases_for(board: fetch.Board, pcb: pathlib.Path) -> str:
    """Manifest obligations first, then uncaptured board defaults."""
    from placemat.kicad.read import read_board
    from placemat.route_phase import default_phases, phases_toml
    graph = read_board(str(pcb))
    default = {nc.clearance for nc in graph.netclasses.values() if nc.name == "Default"}
    base = min(default) if default else graph.default_clearance
    wide = sorted({nc.name for nc in graph.netclasses.values() if nc.clearance > base + 1e-9})
    return phases_toml(list(board.phases) + default_phases(
        pairs=False, interface_types=[], wide_classes=wide, currents=False))


def run_a(board: fetch.Board, work: pathlib.Path, *, track_mm: float | None = None,
          versions: dict | None = None) -> AResult:
    """Test (a) on a prepared board: `work` holds test.kicad_pcb and baseline-drc.json (prepare's), `track_mm` the human's width
    for the "human" run."""
    work = pathlib.Path(work)
    widths = "class" if track_mm is None else "human"
    toml = ("" if track_mm is None else '[route]\nrouter_args = ["--track-width", "%s"]\n\n' % track_mm) + phases_for(board, work / prepare.TEST)
    out = work / ("route-" + widths)
    report = _route(work / prepare.TEST, out, toml)
    _, routed = prepare.measure(pathlib.Path(report["routed_pcb"]))
    _, human = prepare.measure(work / prepare.REF)
    after = prepare.violations(out / "drc_after.json")
    new = new_violations(after, prepare.violations(work / prepare.BASELINE))
    versions = dict(versions if versions is not None else current_versions(), krt=_krt_version(work / prepare.TEST))
    template = AResult(board.name, widths, 0.0, 0, [], [], 0, 0.0, human.vias, human.track_mm, False, 0.0, versions)
    return judge(dict(report, vias=routed.vias, track_mm=routed.track_mm), new, template)


def failed(board: fetch.Board, widths: str, error: Exception, versions: dict, human: prepare.HumanCopper,
           krt_from: pathlib.Path) -> AResult:
    """The result of a run that raised `error`: the exception's type as the failure, its message as the detail. "krt" is
    the router a route of `krt_from` resolves, where that can be read."""
    try:
        krt = _krt_version(krt_from)
    except Exception:   # the failure is the result; an unreadable router version leaves it "unknown"
        krt = "unknown"
    return AResult(board.name, widths, 0.0, 0, [], [], 0, 0.0, human.vias, human.track_mm, False, 0.0,
                   dict(versions, krt=krt), type(error).__name__, str(error))


def said(c: Comparison) -> str:
    """A comparison as the console lines give it."""
    if c.status == "not comparable":
        return "not comparable: %s differ, values %s" % (", ".join(c.differ), c.value)
    return c.status


def line(r: AResult, c: Comparison) -> str:
    """The console line of a result."""
    return "%-22s %-5s %s closure_clean %.1f%% open %d new DRC %d vias %d/%d track %.0f/%.0f mm %.0fs  %s%s" % (
        r.board, r.widths, "pass" if r.passed else "FAIL", 100 * r.closure_clean, r.open, len(r.new_violations),
        r.vias, r.human_vias, r.track_mm, r.human_track_mm, r.seconds, said(c),
        "  FAILED %s: %s" % (r.failure, r.detail[:200]) if r.failure else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="boards or local fixtures (default: all)")
    ap.add_argument("--update", action="store_true", help="write the results into results.json")
    ap.add_argument("--accept-worse", action="store_true", help="with --update: also write results that are worse than the recorded ones")
    ap.add_argument("--changing", nargs="+", choices=COMPONENTS, default=["placemat"],
                    help="the components under change (after the board names)")
    ap.add_argument("--work", help="where boards are prepared (default: a temporary folder)")
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args(argv)
    boards = [b for b in fetch.load_manifest() if "a" in b.tests and (not args.names or b.name in args.names)]
    local_names = [name for name in LOCAL if not args.names or name in args.names]
    unknown = set(args.names) - {b.name for b in boards} - set(local_names)
    if unknown:
        available = sorted({b.name for b in fetch.load_manifest() if "a" in b.tests} | set(LOCAL))
        ap.error("unknown board or fixture: %s; available: %s" % (", ".join(sorted(unknown)), ", ".join(available)))
    recorded_data = load_results(pathlib.Path(args.results))
    recorded, recorded_fixtures = recorded_data.get("a", {}), recorded_data.get("fixtures", {})
    root = pathlib.Path(args.work) if args.work else pathlib.Path(tempfile.mkdtemp(prefix="placemat-reference-"))
    results, comparisons, held = [], [], []

    def save() -> None:   # after each board, so a run that stops keeps the boards it finished
        if args.update:
            write, held[:] = ratchet(results, comparisons, args.accept_worse)
            save_results(pathlib.Path(args.results), write)

    try:
        with lock.realboard():
            versions = current_versions()
            worse = _run_boards(boards, root, recorded, versions, set(args.changing), results, comparisons, save)
            for name in local_names:
                result = run_local(name, root / name, versions)
                print(local_line(result, compare_local(recorded_fixtures.get(name), result, set(args.changing))), flush=True)
                worse = worse or not result.passed
                if args.update:
                    save_local(pathlib.Path(args.results), [result])
    finally:
        if not args.work:   # a --work folder is the caller's, to inspect
            shutil.rmtree(root, ignore_errors=True)
    for r in held:
        print("held back, worse than the recorded result: %s %s (--accept-worse writes it)" % (r.board, r.widths))
    return 1 if worse or held else 0


def _run_boards(boards, root, recorded, versions, changing, results, comparisons, save) -> bool:
    """Test (a) on each board, at each width; a board whose preparation raises fails at every width, a route that raises
    fails at its own. `save` is called after each board."""
    worse = False
    for board in boards:
        work = root / board.name
        runs = [w for w in WIDTHS if w == "class" or board.human_track_mm]
        try:
            human = prepare.prepare(board, fetch.fetch(board), work).human
            error = None
        except Exception as e:   # a failed result, so the other boards still run and are kept
            human, error = prepare.HumanCopper(0, 0.0), e
        for widths in runs:
            if error is None:
                try:
                    r = run_a(board, work, track_mm=board.human_track_mm if widths == "human" else None, versions=versions)
                except Exception as e:
                    r = failed(board, widths, e, versions, human, work / prepare.TEST)
            else:
                r = failed(board, widths, error, versions, human, work / prepare.TEST)
            c = compare(recorded.get(board.name, {}).get(widths), r, changing)
            print(line(r, c), flush=True)
            worse = worse or lower(c)
            results.append(r)
            comparisons.append(c)
        save()
    return worse


if __name__ == "__main__":
    sys.exit(main())
