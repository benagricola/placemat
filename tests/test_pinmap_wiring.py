"""The pin map study at the end of a resolve: once, on the finished board, its findings in the plan and its record on
it; not on an explore's variants or a board that says not to; reused when a resolve reads what the last one read; and it
moves nothing."""
from placemat.explore import Explore
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.pinmap import study_line
from placemat.values import Face, Location, Part
from tests.fixtures import board_geometry, footprint
from tests.pinmap_boards import quad_footprint, settings


def board(fields=None, face=Face.FRONT, u1_at=Location(10, 10), **kw):
    """U1 with nets A-D on its east side, north to south, and four resistors east of it in the opposite order."""
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"} if fields is None else fields)]
    for i, net in enumerate(["D", "C", "B", "A"]):
        fps.append(footprint("R%d" % (i + 1), 25, 7 + 2 * i, w=2, h=1, inst="r%d" % (i + 1), nets=(net, "G%d" % i)))
    b = Board(board_geometry(fps, width=40, height=30), edge_margin=1.0, settings=settings(pins_rotations=(0.0,)), **kw)
    b.place(Part("u1"), at=u1_at, face=face)
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


def test_a_study_that_fails_leaves_the_resolve_standing_and_says_so(monkeypatch):
    from placemat import pinmap

    def broken(*a, **k):
        raise RuntimeError("boom")
    expected = board().resolve()
    monkeypatch.setattr(pinmap, "study_findings", broken)
    plan = board().resolve()
    keys = ["u1", "r1", "r2", "r3", "r4"]
    assert [plan.placement(k) for k in keys] == [expected.placement(k) for k in keys]
    (f,) = [f for f in plan.findings if f.cause is C.SETUP_PINS]
    assert (f.facts["code"], f.facts["type"], f.facts["message"]) == ("study_failed", "RuntimeError", "boom")
    assert plan.pin_study == {"error": {"type": "RuntimeError", "message": "boom"}}
    assert "RuntimeError: boom" in study_line(plan.pin_study)
    assert remaps(plan) == []


def test_a_part_that_may_stand_on_either_face_is_studied_as_one_that_may_flip():
    from placemat.pinmap import placed_from_plan
    b = board(face=Face.EITHER, u1_at=None)          # an either-face part's spot is searched
    plan = b.resolve()
    parts = placed_from_plan(b, plan)[1]
    assert parts["U1"].may_flip and not parts["R1"].may_flip


def test_a_kept_study_that_is_not_an_object_is_not_reused(tmp_path):
    for text in ("[]", "1"):
        b = board()
        b.pin_study_cache = tmp_path / "layout.json"
        b.pin_study_cache.write_text(text)
        plan = b.resolve()
        assert plan.pin_study["reused"] is False and len(remaps(plan)) == 1


class PanicException(BaseException):
    """What pyo3 raises for a panic in the native core (pyo3_runtime.PanicException): a BaseException."""


def test_a_panic_in_the_native_core_is_a_failed_study_and_an_interrupt_still_ends_the_resolve(monkeypatch):
    import pytest
    from placemat import pinmap

    def panics(*a, **k):
        raise PanicException("index out of bounds")
    monkeypatch.setattr(pinmap, "study_findings", panics)
    plan = board().resolve()
    assert plan.pin_study == {"error": {"type": "PanicException", "message": "index out of bounds"}}

    def interrupted(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(pinmap, "study_findings", interrupted)
    with pytest.raises(KeyboardInterrupt):
        board().resolve()
