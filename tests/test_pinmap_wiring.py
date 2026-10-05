"""The pin map study at the end of a resolve: once, on the finished board, its findings in the plan and its record on
it; not on an explore's variants or a board that says not to; reused when a resolve reads what the last one read; and it
moves nothing."""
from placemat.explore import Explore
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.pinmap import study_line
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint
from tests.pinmap_boards import quad_footprint, settings


def board(fields=None, **kw):
    """U1 with nets A-D on its east side, north to south, and four resistors east of it in the opposite order."""
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"} if fields is None else fields)]
    for i, net in enumerate(["D", "C", "B", "A"]):
        fps.append(footprint("R%d" % (i + 1), 25, 7 + 2 * i, w=2, h=1, inst="r%d" % (i + 1), nets=(net, "G%d" % i)))
    b = Board(board_geometry(fps, width=40, height=30), edge_margin=1.0, settings=settings(pins_rotations=(0.0,)), **kw)
    b.place(Part("u1"), at=Location(10, 10))
    for i in range(4):
        b.place(Part("r%d" % (i + 1)), at=Location(25, 7 + 2 * i))
    return b


def remaps(plan):
    return [f for f in plan.findings if f.cause is C.PINS_REMAP]


def test_a_resolve_ends_with_the_study_and_keeps_its_record():
    plan = board().resolve()
    (f,) = remaps(plan)
    assert f.startswith("U1: a pin map with 6 fewer weighted crossings exists at its present rotation")
    assert plan.pin_study["reused"] is False and plan.pin_study["parts"] == 1
    assert f.suggestions and f.suggestions[0].lever == "pins" and f.suggestions[0].id


def test_a_board_that_says_not_to_and_an_explore_variant_are_not_studied():
    b = board()
    b.pin_study = False
    assert remaps(b.resolve()) == []
    plan = board().resolve(explore=Explore(3, frozenset({"r1"})))
    assert remaps(plan) == [] and plan.pin_study == {}


def test_the_study_moves_nothing_the_placement_is_the_one_without_a_pool():
    with_pool, without = board().resolve(), board(fields={}).resolve()
    keys = ["u1", "r1", "r2", "r3", "r4"]
    assert [with_pool.placement(k) for k in keys] == [without.placement(k) for k in keys]
    assert remaps(without) == [] and without.pin_study == {}


def test_a_resolve_reading_what_the_last_one_read_reuses_its_study(tmp_path):
    first = board()
    first.pin_study_cache = tmp_path / "pinmap" / "layout.json"
    a = first.resolve()
    second = board()
    second.pin_study_cache = first.pin_study_cache
    b = second.resolve()
    assert (a.pin_study["reused"], b.pin_study["reused"]) == (False, True)
    assert [str(f) for f in remaps(a)] == [str(f) for f in remaps(b)]
    assert study_line(b.pin_study).startswith("1 part, the last study reused")


def _scripted(tmp_path, monkeypatch, overlay=None):
    from types import SimpleNamespace
    from placemat import context, runner
    script = tmp_path / "x_layout.py"
    script.write_text("")
    fab = SimpleNamespace(via_drill=0.3, via_size=0.6, courtyard_excess=0.1, component_spacing=None, via_tiers={}, path=None)
    monkeypatch.setattr(context, "_overlay", overlay)
    return runner.scripted_board(script, SimpleNamespace(board_dir=tmp_path), settings(), fab, False,
                                 geometry=board().geometry)


def test_a_run_keeps_the_study_beside_its_board_and_a_try_keeps_nothing(tmp_path, monkeypatch):
    assert _scripted(tmp_path, monkeypatch).pin_study_cache == tmp_path / ".placemat" / "pinmap" / "x_layout.json"
    tried = _scripted(tmp_path, monkeypatch, overlay={str((tmp_path / "x_layout.py").resolve()): ""})
    assert tried.pin_study_cache is None


def test_an_explore_worker_board_is_not_studied(monkeypatch):
    from placemat import explore, runner
    monkeypatch.setattr(runner, "scripted_board", lambda *a, **k: board())
    assert explore.BoardFactory(None, None, None, None, False, None)().pin_study is False
