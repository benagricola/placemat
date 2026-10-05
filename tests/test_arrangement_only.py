import pytest

from placemat import reuse
from placemat.values import Beside, CopperLayer, Edge, Net, PadRef, Part
from tests.arrangement_support import module

F = CopperLayer.F


def declared(b):
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("mirrored", __import__("placemat").Alt(Part("c_in"), rotation=180))
    return b


def track(b, **kw):
    return b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=F, **kw)


def test_a_declaration_without_only_is_in_every_arrangement():
    b = declared(module())
    c = track(b)
    assert c.only == () and c.applies_in("default") and c.applies_in("c_in.east")


def test_only_names_the_arrangements_a_declaration_exists_in():
    b = declared(module())
    c = track(b, only=("mirrored", "c_in.east+r_pull.turned"))
    assert c.only == ("mirrored", "c_in.east+r_pull.turned")
    assert c.applies_in("mirrored") and not c.applies_in("default") and not c.applies_in("c_in.east")
    b.finish_declarations()


@pytest.mark.parametrize("only", [("nope",), ("east",), ("r_pull.turned+c_in.east",)])
def test_an_unknown_id_is_refused_with_the_line_and_the_ids_the_module_has(only):
    b = declared(module())
    track(b, only=only)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    text = str(e.value)
    assert "test_arrangement_only.py:" in text and "only=" in text and "c_in.east" in text and "mirrored" in text
    assert "arrangements:" in text and "groups:" in text


def test_an_empty_only_and_a_bare_string_are_refused_where_written():
    b = declared(module())
    with pytest.raises(ValueError):
        track(b, only=())
    with pytest.raises(TypeError):
        track(b, only="default")
    with pytest.raises(TypeError):
        b.place(Part("r_free"), only=("default",))                    # a form that takes no only=


def test_default_names_the_default_arrangement():
    b = declared(module())
    assert track(b).applies_in("default")
    narrowed = track(b, only=("default",))
    assert narrowed.applies_in("default")
    other = track(b, only=("mirrored",))
    assert not other.applies_in("default")
    b.finish_declarations()


def test_every_copper_form_takes_only():
    import inspect
    from placemat.layout import Board
    for form in ("track", "pair", "vias", "via", "stitch", "pour", "plane", "finger"):
        assert "only" in inspect.signature(getattr(Board, form)).parameters, form


def test_only_is_in_the_reuse_digest_only_when_given():
    b = declared(module())
    plain, narrowed = track(b), track(b, only=("mirrored",))
    assert "only=" not in reuse.canonical(plain) and "only=" in reuse.canonical(narrowed)


def test_finish_declarations_is_idempotent():
    b = declared(module())
    track(b, only=("mirrored",))
    b.finish_declarations()
    b.finish_declarations()


def test_a_pour_fitted_round_a_via_that_exists_in_fewer_arrangements_is_refused():
    b = declared(module())
    v = b.via(Net("VIN"), PadRef(Part("u1"), 1), only=("mirrored",))
    b.pour(Net("VIN"), [PadRef(Part("u1"), 1), v], layer=F, swallow_pads=True)           # in every arrangement, its via in one
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert "via" in str(e.value) and "only" in str(e.value)


def test_a_stitch_over_a_pour_that_exists_in_fewer_arrangements_is_refused():
    b = declared(module())
    pour = b.pour(Net("VIN"), [PadRef(Part("u1"), 1), PadRef(Part("c_in"), 1)], layer=F, swallow_pads=True, only=("c_in.east",))
    b.stitch(Net("VIN"), pour)                                                          # in every arrangement, its pour in one
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert "stitch" in str(e.value) and "only" in str(e.value)
    held = declared(module())
    pour = held.pour(Net("VIN"), [PadRef(Part("u1"), 1), PadRef(Part("c_in"), 1)], layer=F, swallow_pads=True,
                     only=("c_in.east",))
    held.stitch(Net("VIN"), pour, only=("c_in.east",))
    held.finish_declarations()


def _module_with_only_copper_before_a_lane_via(trailing):
    """A module (a frame not drawn) with a QFN escaping west and a part `r5` that may turn; a track that exists in the default only
    is declared before a board via at the end of pin 30's lane, which `escape.via_unneeded` names by its key. `trailing` declares
    another track after the via."""
    from placemat.values import Location
    from tests.escape_fixtures import PD_NETS, board_with, qfn
    from tests.fixtures import footprint
    size = 16.0
    b = board_with([qfn(cx=size / 2, cy=size / 2, nets=PD_NETS), footprint("R5", 13.0, 14.0, w=2.0, h=1.0, nets=("Z", "Z"))],
                   width=size, height=size, keep_going=True, nets=("Z",))
    b.rect(size, size, draw=False)
    b.place(Part("pd"), at=Location(size / 2, size / 2))
    b.place(Part("r5"), at=Location(13.0, 14.0))
    b.alternative(Part("r5"), "turned", rotation=180)
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, why="north row")
    b.track(Net("Z"), [Location(12.0, 12.0), Location(14.0, 12.0)], layer=F, only=("default",))
    for n, net in PD_NETS.items():
        b.track(Net(net), [esc[n]], layer=F)
    via = b.via(Net("PGOOD"), esc[30].end, why="the lane's end")
    if trailing:
        b.track(Net("Z"), [Location(12.0, 13.0), Location(14.0, 13.0)], layer=F)
    return b, via


@pytest.mark.parametrize("trailing", [False, True])
def test_an_arrangement_without_only_copper_names_a_lane_via_by_its_own_declaration(tmp_path, trailing):
    from placemat import arrangement_run as run
    from placemat.findings import FindingCause as C
    from placemat.layout import copper_id
    b, via = _module_with_only_copper_before_a_lane_via(trailing)
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default", "r5.turned"]
    default = run.resolve_spec(prepared, prepared.specs[0])
    (resolved,) = run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, lambda ident: None)
    assert resolved.refused == [] and resolved.plan is not None
    for plan in (default, resolved.plan):
        (f,) = [f for f in plan.findings if f.cause is C.ESCAPE_VIA_UNNEEDED]
        assert f.facts["via"]["kind"] == "via" and f.facts["via"]["key"] == copper_id(via)


def test_an_adopted_routes_copper_takes_an_index_no_kept_declaration_has(monkeypatch):
    """`ctx.ops_at` is keyed by a copper declaration's index: an adopted route's must not be a kept one's once an arrangement has
    left out copper before it."""
    from placemat import arrangement_run as run, routes
    from placemat.layout import Board
    from placemat.values import Location
    from tests.fixtures import board_geometry, footprint
    from tests.test_routes import _parts, _routed
    placed, routed = _routed()
    (entry,) = routes.entries_from(placed, routed, ["X"])
    parts = _parts() + [footprint("R2", 30, 30, w=2, h=1, inst="r2", nets=("A", "B"))]
    b = Board(board_geometry(parts, width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"), at=Location(20, 16))
    b.place(Part("r2"), at=Location(30, 30))
    b.alternative(Part("r2"), "turned", rotation=180)
    b.track(Net("B"), [Location(26.0, 34.0), Location(28.0, 34.0)], layer=F, only=("default",))
    b.track(Net("B"), [Location(26.0, 36.0), Location(28.0, 36.0)], layer=F)
    seen = []
    real = Board._plan_copper

    def spy(self, occ, ctx, intents, *a, **k):
        if any(c.key.startswith("adopted") for c in intents):
            seen.append(({c.index for c in self._copper}, [c.index for c in intents]))
        return real(self, occ, ctx, intents, *a, **k)
    monkeypatch.setattr(Board, "_plan_copper", spy)
    prepared = run.begin(b)
    plan = run.resolve_spec(prepared, prepared.specs[1], routes=[entry])
    assert prepared.specs[1].id == "r2.turned" and plan.adopted == {"X": "held"}
    ((kept, adopted),) = seen
    assert kept == {1} and not kept & set(adopted)
