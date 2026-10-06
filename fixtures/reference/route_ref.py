"""Test (a) of the reference set: route each board's human placement with its copper stripped, and judge clean closure and
the DRC errors the route adds to the stripped board's baseline.

    .venv/bin/python fixtures/reference/route_ref.py [name ...] [--update] [--changing placemat|krt|pcb]

For each test (a) board it runs the route with the net classes' widths, then with the human's track width where the manifest
gives one, and compares each result with results.json["a"]. Results of runs whose placemat, router or zener versions differ
in a component other than --changing are not compared. --update writes the boards it ran into results.json["a"].
Real boards: it takes the realboard lock (lock.py) for the whole run, so it waits for the other real-board runs.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import subprocess
import sys
import tempfile

if __package__ in (None, ""):   # run as a script: the repository root, for `fixtures.reference`
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from fixtures.reference import fetch, lock, prepare   # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
RESULTS = HERE / "results.json"
COMPONENTS = ("placemat", "krt", "pcb")
WIDTHS = ("class", "human")
ROUTE_TIMEOUT_S = 3600
GIT_TIMEOUT_S = 30
CLEAN = 1.0
DIRTY = "-dirty"
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


@dataclasses.dataclass(frozen=True)
class Comparison:
    status: str   # new, same, better, worse or not comparable
    differ: list[str]   # with "not comparable": the components whose versions differ


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


def comparable(old: dict, new: dict, changing: str) -> list[str]:
    """The components other than `changing` whose versions differ between two results' `versions`."""
    return [c for c in COMPONENTS if c != changing and old.get(c) != new.get(c)]


def compare(old: dict | None, new: AResult, changing: str) -> Comparison:
    """A result against the recorded one (its dict): new, same, better, worse, or not comparable."""
    if old is None:
        return Comparison("new", [])
    differ = comparable(old.get("versions", {}), new.versions, changing)
    if differ:
        return Comparison("not comparable", differ)
    gained = len(new.new_violations) - len(old.get("new_violations", ()))
    if (old["passed"] and not new.passed) or new.closure_clean < old["closure_clean"]:
        return Comparison("worse", [])
    if new.closure_clean == old["closure_clean"] and gained > 0:
        return Comparison("worse", [])
    if (new.passed and not old["passed"]) or new.closure_clean > old["closure_clean"]:
        return Comparison("better", [])
    return Comparison("same", [])


def asdict(result: AResult) -> dict:
    return dataclasses.asdict(result)


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


def _git(root: str, *args: str) -> str:
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S).stdout.strip()


def _git_head(root: str) -> str:
    """The commit of a checkout, with "-dirty" when it has uncommitted changes to tracked files."""
    head = _git(root, "rev-parse", "HEAD") or "unknown"
    return head + DIRTY if _git(root, "status", "--porcelain", "-uno") else head


def _krt_version(board_pcb: pathlib.Path) -> str:
    """The commit of the router the route of this board resolves: [route] router_dir of the board's folder, else $KRT_DIR, else the built-in."""
    from placemat.kicad.route import router_dir
    from placemat.settings import load
    return _git_head(router_dir(load(pathlib.Path(board_pcb).parent)))


def current_versions() -> dict:
    """The placemat checkout's commit and zener's version; "krt" is the router a route used (run_a)."""
    import placemat
    pcb = subprocess.run(["pcb", "--version"], capture_output=True, text=True, timeout=GIT_TIMEOUT_S).stdout.strip()
    return {"placemat": _git_head(str(pathlib.Path(placemat.__file__).resolve().parent)), "pcb": pcb or "unknown"}


def _route(pcb: pathlib.Path, work: pathlib.Path, islands: tuple, toml: str | None) -> dict:
    """`placemat route pcb --full --islands ...` into `work`, with `toml` as placemat.toml beside the board; route.json as a dict."""
    config = pathlib.Path(pcb).with_name("placemat.toml")
    if toml is None:
        config.unlink(missing_ok=True)
    else:
        config.write_text(toml)
    cmd = [sys.executable, "-m", "placemat", "route", str(pcb), "--full", "--no-resume", "--out", str(work)]
    if islands:
        cmd += ["--islands", *islands]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=ROUTE_TIMEOUT_S)
    out = pathlib.Path(work) / "route.json"
    if not out.exists():
        raise RuntimeError("placemat route wrote no route.json (rc %d): %s" % (proc.returncode, (proc.stderr or proc.stdout)[-500:]))
    return json.loads(out.read_text())


def run_a(board: fetch.Board, work: pathlib.Path, *, track_mm: float | None = None,
          versions: dict | None = None) -> AResult:
    """Test (a) on a prepared board: `work` holds test.kicad_pcb and baseline-drc.json (prepare's), `track_mm` the human's width
    for the "human" run."""
    work = pathlib.Path(work)
    widths = "class" if track_mm is None else "human"
    toml = None if track_mm is None else '[route]\nrouter_args = ["--track-width", "%s"]\n' % track_mm
    out = work / ("route-" + widths)
    report = _route(work / prepare.TEST, out, board.islands, toml)
    _, routed = prepare.measure(pathlib.Path(report["routed_pcb"]))
    _, human = prepare.measure(work / prepare.REF)
    after = prepare.violations(out / "drc_after.json")
    new = new_violations(after, prepare.violations(work / prepare.BASELINE))
    versions = dict(versions if versions is not None else current_versions(), krt=_krt_version(work / prepare.TEST))
    template = AResult(board.name, widths, 0.0, 0, [], [], 0, 0.0, human.vias, human.track_mm, False, 0.0, versions)
    return judge(dict(report, vias=routed.vias, track_mm=routed.track_mm), new, template)


def line(r: AResult, c: Comparison) -> str:
    """The console line of a result."""
    said = {"not comparable": "not comparable: %s differ" % ", ".join(c.differ)}.get(c.status, c.status)
    return "%-22s %-5s %s closure_clean %.1f%% open %d new DRC %d vias %d/%d track %.0f/%.0f mm %.0fs  %s" % (
        r.board, r.widths, "pass" if r.passed else "FAIL", 100 * r.closure_clean, r.open, len(r.new_violations),
        r.vias, r.human_vias, r.track_mm, r.human_track_mm, r.seconds, said)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="boards (default: every test (a) board)")
    ap.add_argument("--update", action="store_true", help="write the results into results.json")
    ap.add_argument("--changing", choices=COMPONENTS, default="placemat", help="the component under change")
    ap.add_argument("--work", help="where boards are prepared (default: a temporary folder)")
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args(argv)
    boards = [b for b in fetch.load_manifest() if "a" in b.tests and (not args.names or b.name in args.names)]
    if args.names and len(boards) != len(args.names):
        ap.error("no test (a) board among: %s" % ", ".join(sorted(set(args.names) - {b.name for b in boards})))
    recorded = load_results(pathlib.Path(args.results)).get("a", {})
    versions = current_versions()
    root = pathlib.Path(args.work) if args.work else pathlib.Path(tempfile.mkdtemp(prefix="placemat-reference-"))
    results, worse = [], False
    with lock.realboard():
        worse = _run_boards(boards, root, recorded, versions, args.changing, results)
    if args.update:
        save_results(pathlib.Path(args.results), results)
    return 1 if worse else 0


def _run_boards(boards, root, recorded, versions, changing, results) -> bool:
    worse = False
    for board in boards:
        work = root / board.name
        prepare.prepare(board, fetch.fetch(board), work)
        for widths in WIDTHS:
            if widths == "human" and not board.human_track_mm:
                continue
            r = run_a(board, work, track_mm=board.human_track_mm if widths == "human" else None, versions=versions)
            c = compare(recorded.get(board.name, {}).get(widths), r, changing)
            print(line(r, c), flush=True)
            worse = worse or c.status == "worse"
            results.append(r)
    return worse


if __name__ == "__main__":
    sys.exit(main())
