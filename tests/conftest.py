import os
import shutil
from pathlib import Path

import pytest

from tests import impact

# Files outside the repository are named by environment variables only; a test that needs one skips, saying which,
# when it is unset.
ECOSYSTEM_ENV = "MNB_ECOSYSTEM"     # the multi-board project whose committed Breakout board some tests read
ROUTER_ENV = "KRT_DIR"              # the KiCadRoutingTools checkout the routing tests run
ECOSYSTEM = Path(os.environ[ECOSYSTEM_ENV]) if os.environ.get(ECOSYSTEM_ENV) else None
BREAKOUT_PCB = ECOSYSTEM / "breakout/layout/Breakout/layout.kicad_pcb" if ECOSYSTEM else None
ROUTER = Path(os.environ[ROUTER_ENV]) if os.environ.get(ROUTER_ENV) else None


def outside_file_missing(path, env) -> str:
    """Why a test that reads `path` (from $`env`; None when unset) cannot run, or "" when it can."""
    if path is None:
        return "$%s is not set" % env
    return "" if Path(path).exists() else "%s not found ($%s)" % (path, env)


ROUTER_NEEDS = (".venv/bin/python", "py_router/route.py", "py_router/route_diff.py", "py_router/list_nets.py")


def router_missing() -> str:
    """Why a test that runs the router cannot, or "" when it can: $KRT_DIR unset, or a checkout without one of
    ROUTER_NEEDS (the interpreter, the router, the pair router, the net lister net_clearance runs)."""
    for f in ROUTER_NEEDS:
        why = outside_file_missing(ROUTER / f if ROUTER else None, ROUTER_ENV)
        if why:
            return why
    return ""


needs_router = pytest.mark.skipif(bool(router_missing()), reason=router_missing() or "router found")


def _has_pcbnew():
    try:
        import pcbnew  # noqa: F401
        return True
    except ImportError:
        return False


needs_kicad = pytest.mark.skipif(not _has_pcbnew(), reason="pcbnew not importable")
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def empty_board(pcb):
    """An empty pcbnew board whose project is the .kicad_pro beside `pcb`, so that saving it, there or elsewhere,
    writes the project with the netclass and rule settings KiCad's DRC reads. KiCad 10.0.7 opens the unnamed project
    of pcbnew.CreateEmptyBoard read-only (SETTINGS_MANAGER::LoadProject), and such a board saves without one."""
    import pcbnew
    Path(pcb).parent.mkdir(parents=True, exist_ok=True)
    return pcbnew.NewBoard(str(pcb))


if not _has_pcbnew():
    @pytest.hookimpl(hookwrapper=True)
    def pytest_make_collect_report(collector):
        """Without KiCad (a CI runner), a test module that imports pcbnew at
        its top is skipped, as a `needs_kicad` test is, not an error that
        stops the whole collection."""
        outcome = yield
        report = outcome.get_result()
        if report.failed and "No module named 'pcbnew'" in str(report.longrepr):
            report.outcome = "skipped"
            report.longrepr = (str(collector.path), 0, "Skipped: pcbnew not importable")


# ------------------------------------------------------------ the slow tests
# tests/slow_tests.txt (written by tests/update_slow_tests.py from a full run)
# names the tests that take seconds each: real boards, native-against-Python
# parity, router runs. A plain `pytest` leaves them out; `pytest --full` (or
# PLACEMAT_FULL=1) runs everything, as a release and CI do.
SLOW_LIST = Path(__file__).with_name("slow_tests.txt")
SLOW_REPORT_S = 2.0         # a full run names any test slower than this that the list does not have
SLOW_FAIL_S = 5.0           # and fails on one slower than this: the margin keeps timing noise from failing it

# ------------------------------------------------------------ the parity tier
# A native-against-Python comparison keeps one case (one module, one config, a small sample) in the full run. The
# other cases are marked `parity` and run only with `--parity` (or PLACEMAT_PARITY=1), which the release workflow
# adds when native/ changed since the last tag. `parity_cases(n, few)` is a sample size: n with the tier on, else few.
PARITY_ENV = "PLACEMAT_PARITY"
parity = pytest.mark.parity


def parity_on() -> bool:
    return os.environ.get(PARITY_ENV) == "1"


def parity_cases(n: int, few: int) -> int:
    return n if parity_on() else few


def pytest_addoption(parser):
    parser.addoption("--full", action="store_true", help="run the slow tests too (tests/slow_tests.txt)")
    parser.addoption("--parity", action="store_true",
                     help="run every native-against-Python case too, not only each comparison's one case")
    parser.addoption("--impact", metavar="REF", default=os.environ.get("PLACEMAT_IMPACT_REF") or None,
                     help="with --full, run only the slow tests a change since REF reaches (tests/impact.py)")


def _full(config) -> bool:
    return config.getoption("--full") or os.environ.get("PLACEMAT_FULL") == "1"


def _slow_ids() -> set:
    if not SLOW_LIST.exists():
        return set()
    return {line.strip() for line in SLOW_LIST.read_text().splitlines() if line.strip() and not line.startswith("#")}


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: takes seconds; left out unless --full (tests/slow_tests.txt)")
    config.addinivalue_line("markers", "parity: a further native-against-Python case; left out unless --parity")
    if config.getoption("--parity"):
        os.environ[PARITY_ENV] = "1"       # before collection and before xdist starts its workers
    global _RECORDER
    if os.environ.get(impact.RECORD_ENV) and _RECORDER is None:
        _RECORDER = impact.Recorder()
        _RECORDER.start()


def pytest_collection_modifyitems(config, items):
    slow = _slow_ids()
    for item in items:
        if item.nodeid in slow:
            item.add_marker(pytest.mark.slow)
    if config.getoption("-m"):
        return
    full, tier = _full(config), parity_on()
    keep, drop = [], []
    for item in items:
        left_out = (item.get_closest_marker("slow") and not full) or (item.get_closest_marker("parity") and not tier)
        (drop if left_out else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
        config._placemat_slow_left_out = sum(1 for i in drop if i.get_closest_marker("slow") and not full)
        config._placemat_parity_left_out = len(drop) - config._placemat_slow_left_out
    config._placemat_parity_ids = {i.nodeid for i in items if i.get_closest_marker("parity")}
    ref = config.getoption("--impact")
    if full and ref:
        slow_items = [i for i in items if i.get_closest_marker("slow")]
        reached = impact.selected(ref, {i.nodeid for i in slow_items}, impact.load_map())
        if reached is not None:
            drop = [i for i in slow_items if i.nodeid not in reached]
            if drop:
                config.hook.pytest_deselected(items=drop)
                gone = {id(i) for i in drop}
                items[:] = [i for i in items if id(i) not in gone]
        config._placemat_impact = (ref, len(slow_items), len(slow_items) if reached is None else len(slow_items) - len(drop))


_RECORDER = None       # tests/impact.py's Recorder, in a run with PLACEMAT_IMPACT_RECORD set


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    recording = _RECORDER is not None and item.get_closest_marker("slow") is not None
    if recording:
        _RECORDER.begin(item.nodeid)
    try:
        yield
    finally:
        if recording:
            _RECORDER.end()


_TOOK: dict = {}       # node id -> seconds of setup and call, from every worker's reports


def pytest_runtest_logreport(report):
    if report.when in ("setup", "call"):
        _TOOK[report.nodeid] = _TOOK.get(report.nodeid, 0.0) + report.duration


def _unlisted_slow(config) -> list:
    """(seconds, node id) of each test in a full run slower than SLOW_REPORT_S that is neither listed slow nor
    in the parity tier, slowest first."""
    if not _full(config):
        return []
    slow, tier = _slow_ids(), getattr(config, "_placemat_parity_ids", set())
    return sorted(((d, k) for k, d in _TOOK.items() if d > SLOW_REPORT_S and k not in slow and k not in tier),
                  reverse=True)


def pytest_sessionfinish(session, exitstatus):
    if _RECORDER is not None and _RECORDER.entries:
        _RECORDER.write(os.environ[impact.RECORD_ENV], os.environ.get("PYTEST_XDIST_WORKER", "main"))
    if exitstatus == 0 and any(d > SLOW_FAIL_S for d, _ in _unlisted_slow(session.config)):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    n = getattr(config, "_placemat_slow_left_out", 0)
    if n:
        terminalreporter.write_line("%d slow tests left out; `pytest --full` runs them (before a release)" % n)
    n = getattr(config, "_placemat_parity_left_out", 0)
    if n:
        terminalreporter.write_line("%d parity cases left out; `pytest --parity` runs them (when native/ changes)" % n)
    got = getattr(config, "_placemat_impact", None)
    if got:
        ref, of, ran = got
        terminalreporter.write_line("%d of %d slow tests run: those a change since %s reaches (tests/impact.py)"
                                    % (ran, of, ref))
    missing = _unlisted_slow(config)
    if missing:
        terminalreporter.write_line("tests slower than %.0f s not in tests/slow_tests.txt (over %.0f s fails the run; "
                                    "make them faster, or run tests/update_slow_tests.py):" % (SLOW_REPORT_S, SLOW_FAIL_S))
        for d, k in missing:
            terminalreporter.write_line("  %.1f s  %s" % (d, k))


def _placemat_native() -> bool:
    from placemat import geometry
    return geometry._native is not None


# placemat's own native path: the module built, of this release, and not
# switched off with PLACEMAT_NATIVE=0
needs_native = pytest.mark.skipif(not _placemat_native(), reason="placemat's native path is off or not built")
needs_breakout = pytest.mark.skipif(bool(outside_file_missing(BREAKOUT_PCB, ECOSYSTEM_ENV)),
                                    reason=outside_file_missing(BREAKOUT_PCB, ECOSYSTEM_ENV) or "Breakout board found")


@pytest.fixture(scope="session")
def breakout_pcb():
    why = outside_file_missing(BREAKOUT_PCB, ECOSYSTEM_ENV)
    if why:
        pytest.skip(why)
    return BREAKOUT_PCB


@pytest.fixture(scope="session")
def breakout(breakout_pcb):
    from placemat.kicad.read import read_board
    return read_board(breakout_pcb, courtyard_excess_mm=0.10)
