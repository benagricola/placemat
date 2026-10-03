import os
from pathlib import Path

import pytest

ECOSYSTEM = Path(os.environ.get("MNB_ECOSYSTEM", Path.home() / "Documents/Hardware/mnb-ecosystem"))
BREAKOUT_PCB = ECOSYSTEM / "breakout/layout/Breakout/layout.kicad_pcb"


def _has_pcbnew():
    try:
        import pcbnew  # noqa: F401
        return True
    except ImportError:
        return False


needs_kicad = pytest.mark.skipif(not _has_pcbnew(), reason="pcbnew not importable")


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


def pytest_addoption(parser):
    parser.addoption("--full", action="store_true", help="run the slow tests too (tests/slow_tests.txt)")


def _full(config) -> bool:
    return config.getoption("--full") or os.environ.get("PLACEMAT_FULL") == "1"


def _slow_ids() -> set:
    if not SLOW_LIST.exists():
        return set()
    return {line.strip() for line in SLOW_LIST.read_text().splitlines() if line.strip() and not line.startswith("#")}


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: takes seconds; left out unless --full (tests/slow_tests.txt)")


def pytest_collection_modifyitems(config, items):
    slow = _slow_ids()
    for item in items:
        if item.nodeid in slow:
            item.add_marker(pytest.mark.slow)
    if _full(config) or config.getoption("-m"):
        return
    keep, drop = [], []
    for item in items:
        (drop if item.get_closest_marker("slow") else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
        config._placemat_slow_left_out = len(drop)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    n = getattr(config, "_placemat_slow_left_out", 0)
    if n:
        terminalreporter.write_line("%d slow tests left out; `pytest --full` runs them (before a release)" % n)
    if not _full(config):
        return
    slow = _slow_ids()
    took: dict = {}
    for reports in terminalreporter.stats.values():
        for r in reports:
            if getattr(r, "when", None) in ("setup", "call") and hasattr(r, "duration"):
                took[r.nodeid] = took.get(r.nodeid, 0.0) + r.duration
    missing = sorted((d, k) for k, d in took.items() if d > SLOW_REPORT_S and k not in slow)
    if missing:
        terminalreporter.write_line("tests slower than %.0f s not in tests/slow_tests.txt (run tests/update_slow_tests.py):"
                                    % SLOW_REPORT_S)
        for d, k in reversed(missing):
            terminalreporter.write_line("  %.1f s  %s" % (d, k))


def _placemat_native() -> bool:
    from placemat import geometry
    return geometry._native is not None


# placemat's own native path: the module built, of this release, and not
# switched off with PLACEMAT_NATIVE=0
needs_native = pytest.mark.skipif(not _placemat_native(), reason="placemat's native path is off or not built")
needs_breakout = pytest.mark.skipif(not BREAKOUT_PCB.exists(), reason="committed Breakout board not found")


@pytest.fixture(scope="session")
def breakout_pcb():
    return BREAKOUT_PCB


@pytest.fixture(scope="session")
def breakout(breakout_pcb):
    from placemat.kicad.read import read_board
    return read_board(breakout_pcb, courtyard_excess_mm=0.10)
