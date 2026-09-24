"""The benchmark's scoring and baseline, without KiCad."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "bench", pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)
import sys as _sys
_sys.modules.setdefault("bench", bench)        # pickle finds ModuleBoard by its module's name


def row(placed, findings=0, hpwl=100.0):
    return {"placed": placed, "findings": findings, "hpwl": hpwl}


def test_more_placed_wins_over_findings_and_wire():
    assert bench.verdict(row(5, 3, 900.0), row(4, 0, 10.0)) == 1
    assert bench.verdict(row(4, 0, 10.0), row(5, 3, 900.0)) == -1


def test_fewer_findings_wins_when_as_many_are_placed():
    assert bench.verdict(row(5, 1, 900.0), row(5, 2, 10.0)) == 1


def test_wire_decides_last_and_one_percent_is_the_same():
    assert bench.verdict(row(5, 0, 98.0), row(5, 0, 100.0)) == 1
    assert bench.verdict(row(5, 0, 102.0), row(5, 0, 100.0)) == -1
    assert bench.verdict(row(5, 0, 100.9), row(5, 0, 100.0)) == 0
    assert bench.verdict(row(5, 0, 99.1), row(5, 0, 100.0)) == 0


def _results(**modules):
    return {"configs": {"default": {"seconds": 1.0}},
            "modules": {m: {"parts": 5, "hand": None, "default": r} for m, r in modules.items()}}


def test_diff_names_new_and_gone_rows_and_tally_counts_them():
    base = _results(a=row(4), b=row(5), c=row(5))
    run = _results(a=row(5), b=row(5, hpwl=200.0), d=row(5))
    changes = bench.diff(run, base)
    assert changes == [("default", "a", "better"), ("default", "b", "worse"),
                       ("default", "c", "gone"), ("default", "d", "new")]
    assert bench.tally(changes) == {"default": {"better": 1, "worse": 1, "same": 0, "new": 1, "gone": 1}}


def test_a_baseline_written_twice_is_the_same_bytes_and_reads_back():
    r = _results(b=row(5), a=row(4, 1, 12.3))
    text = bench.dump(r)
    assert text == bench.dump(bench.load(text))
    assert bench.load(text) == r
    assert text.index('"a"') < text.index('"b"')
    assert len([l for l in text.splitlines() if l.lstrip().startswith('"a"')]) == 1


def test_hpwl_sums_each_nets_box_and_skips_planes_and_lone_pads():
    pads = [("N1", 0, 0), ("N1", 3, 4), ("N1", 1, 1), ("GND", 0, 0), ("GND", 50, 50), ("LONE", 9, 9)]
    assert bench.hpwl(pads, skip={"GND"}) == 7.0


def test_a_module_board_pickles_and_builds_what_the_bench_places():
    """--explore sends each module's board builder to spawned workers."""
    import pickle
    from placemat.values import Freedom
    from tests.fixtures import board_geometry, footprint
    g = board_geometry([footprint("R1", 10, 10, inst="r1", nets=("A", "B")),
                        footprint("R2", 20, 20, inst="r2", nets=("A", "C"))], width=40, height=40)
    make = pickle.loads(pickle.dumps(bench.ModuleBoard(g, {}, set(), (30.0, 30.0))))
    b = make()
    assert {i.key for i in b._placements()} == {"r1", "r2"}
    assert all(i.freedom is Freedom.SEARCHED for i in b._placements())


def test_explore_tally_counts_variants_better_than_the_plain_run():
    rows = {"a": {"baseline": [-3, 0, 5, 10.0], "best": [-3, 0, 4, 11.0]},
            "b": {"baseline": [-3, 0, 5, 10.0], "best": [-3, 0, 5, 10.0]},
            "c": {"baseline": [-2, 1, 5, 10.0], "best": [-3, 0, 6, 12.0]}}
    assert bench.explore_tally(rows) == {"better": 2, "same": 1, "placed": 1}
