"""A via field a conflict meets is re-laid in its pad: vias shifted to free sites, a row or column
shifted, the pitch closed or made uneven, a row or column removed, the cheapest legal layout taken
(docs/superpowers/specs/2026-10-01-via-field-relay-design.md)."""
import dataclasses

import pytest

from placemat.board_geometry import CopperItem
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.settings import Settings
from placemat.values import Box, Cell, CopperLayer, Face, Location, Near, Net, Part
from tests.fixtures import board_geometry, footprint, pad

F, B = CopperLayer.F, CopperLayer.B
SHIFT = 20.0            # the cell is searched this far up and left of where it is drawn


def _via(net, x, y, owner, size=0.45, drill=0.2):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", net, frozenset([F, B]), (ring,), Box.of_points(ring), owner, size, drill, ((x, y),))


def _wide(fp, number, cx, cy, w, h, alone=False):
    """`fp` with its pad `number` replaced by one `w` x `h` at (cx, cy); with `alone`, its only pad,
    the part's box that pad's."""
    pads = tuple(pad(fp.ref, fp.inst, number, p.net, cx, cy, w, h, False, fp.face) if p.number == str(number) else p
                 for p in fp.pads)
    if alone:
        pads = tuple(p for p in pads if p.number == str(number))
        box = Box.union([p.box for p in pads])
    else:
        box = Box.union([fp.body_box] + [p.box for p in pads])
    return dataclasses.replace(fp, pads=pads, body_box=box, courtyard_box=box.inflate(0.1), phys_box=box)


def _grid(x0, y0, nx, ny, pitch):
    return [(round(x0 + i * pitch, 6), round(y0 + j * pitch, 6)) for j in range(ny) for i in range(nx)]


def _board(vias, backs, pad_h=3.0, pad_w=2.6, net="GND", settings=None, planes=("GND",), extra=(), cell_first=False):
    """Cell m: U1 with a GND pad `pad_w` x `pad_h` at (38.1, 40) holding the carried `vias` (drawn
    coordinates), and R9, R10... on the back, each with a pad `(cx, cy, w, h)` of `backs` in the placed
    frame, over the field once the cell lands SHIFT up and left. The cell is searched there with no
    room to move; with `cell_first` it is put there firmly and the back parts are searched after it."""
    u1 = _wide(footprint("U1", 40, 40, w=5, h=2, inst="m.u1", nets=(net, "X"), cell="m"), 1, 38.1, 40.0, pad_w, pad_h)
    fps = [u1]
    for k, r in enumerate(backs):
        ref = "R%d" % (9 + k)
        fp = _wide(footprint(ref, 5, 5, w=2, h=1, inst=ref.lower(), nets=("S", "T"), face=Face.BACK), 1, r[0], r[1], r[2], r[3], alone=True)
        fps.append(dataclasses.replace(fp, location=Location(r[0], r[1])))
    copper = [_via(net, x, y, "m") for x, y in vias] + list(extra)
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=(net,))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    kw = {"settings": settings} if settings is not None else {}
    b = Board(g, edge_margin=0.5, keep_going=True, **kw)
    for n in planes:
        b.plane(Net(n), [B])
    at = Location(centre.x - SHIFT, centre.y - SHIFT)
    if cell_first:
        b.place(Cell("m"), at=at)
        for k, r in enumerate(backs):
            b.place(Part("r%d" % (9 + k)), at=Near(Location(r[0], r[1]), radius=0, rotations=(0,)), face=Face.BACK)
    else:
        for k, r in enumerate(backs):
            b.place(Part("r%d" % (9 + k)), at=Location(r[0], r[1]), face=Face.BACK)
        b.place(Cell("m"), at=Near(at, radius=0, rotations=(0,)))
    return b


def _placed(plan):
    return sorted((round(c.points[0][0], 3), round(c.points[0][1], 3)) for c in plan.occupancy.copper
                  if c.owner == "m" and c.kind == "through")


# a 3 x 3 field, 0.6 mm apart, in a 2.6 x 3.0 pad with its free row on the south side
FIELD = _grid(37.5, 39.1, 3, 3, 0.6)


def test_the_field_is_laid_as_drawn_where_nothing_meets_it():
    plan = _board(FIELD, [(60.0, 60.0, 1.0, 1.0)]).resolve()
    assert plan.step("m").placement is not None
    assert not plan.occupancy.given_way
    assert _placed(plan) == sorted((round(x - SHIFT, 3), round(y - SHIFT, 3)) for x, y in FIELD)


TOP_ROW = (18.1, 19.1, 2.4, 0.3)        # R9's pad on the back, along the field's north row once placed
NO_LEAVE = Settings(place_via_leave_distance=0.0)


def _moves(plan):
    return sorted((a.kind, a.via, tuple(round(v, 3) for v in a.at), None if a.to is None else tuple(round(v, 3) for v in a.to))
                  for a in plan.occupancy.given_way.values())


def _vias_findings(plan):
    return [str(f) for f in plan.findings if f.kind == "vias"]


def test_a_row_under_another_items_pad_moves_to_the_free_side_and_the_count_stays():
    plan = _board(FIELD, [TOP_ROW], settings=NO_LEAVE).resolve()
    step = plan.step("m")
    assert step.placement is not None, step.note
    steps = list(plan.occupancy.given_way.values())
    assert [a.kind for a in steps] == ["relay-move"] * 3
    assert sorted(round(a.to[1], 3) for a in steps) == [20.9] * 3 and sorted(round(a.at[1], 3) for a in steps) == [19.1] * 3
    assert {a.field for a in steps} == {"field m U1.1"}
    assert (steps[0].before, steps[0].after, steps[0].want) == (9, 9, 9)
    assert _placed(plan) == sorted([(x, y) for x in (17.5, 18.1, 18.7) for y in (19.7, 20.3, 20.9)])
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced")], list(plan.findings)
    assert _vias_findings(plan) == ["m: GND field in U1 pad 1 re-laid by shift vias, 9 vias before, 9 after under R9"]


def test_a_field_is_re_laid_before_its_vias_leave_the_pad():
    plan = _board(FIELD, [TOP_ROW]).resolve()           # via_leave at its default: 1.0 mm
    assert {a.kind for a in plan.occupancy.given_way.values()} == {"relay-move"}


def test_a_relay_costs_score_via_relay_once_and_score_via_relay_moved_for_each_via_it_moves():
    from placemat.placement import Placement
    from placemat.placer import scan
    b = _board(FIELD, [TOP_ROW], settings=NO_LEAVE)
    occ = Occupancy(b.geometry, 0.5, settings=b.settings)
    occ.plane_nets = frozenset(["GND"])
    occ.commit(b.geometry.footprint("R9"), Placement(Location(18.1, 19.1), 0.0, Face.BACK))
    centre = occ._geometry(b.geometry.cells["m"]).reference.location
    hint = Placement(Location(centre.x - SHIFT, centre.y - SHIFT), 0.0, Face.FRONT)
    r = scan(occ, b.geometry.cells["m"], hint, 0.0, 0.2, (0.0,), score=lambda p: 0.0)
    assert r.chosen is not None and r.score == pytest.approx(3.0 + 3 * 0.5)


# a pad too small for a free line, its field squeezed against R9's pad: only the pitch can give way
NOROOM = _grid(37.5, 39.3, 3, 3, 0.6)
NOROOM_PAD = (18.1, 19.245, 2.4, 0.45)      # R9's pad meets the north row only, and leaves no room below it


def test_a_field_with_no_room_falls_back_to_drop_and_reports_what_it_holds():
    plan = _board(NOROOM, [NOROOM_PAD], pad_h=2.0, settings=NO_LEAVE).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    assert [a.kind for a in plan.occupancy.given_way.values()] == ["drop"] * 3
    assert len(_placed(plan)) == 6
    assert _vias_findings(plan) == ["m: 3 GND vias dropped under R9 (U1 pad 1 holds 6 of 9)"]


def test_with_relay_off_the_row_is_dropped_as_before():
    plan = _board(FIELD, [TOP_ROW], settings=Settings(place_via_leave_distance=0.0, place_via_relay=False)).resolve()
    assert [a.kind for a in plan.occupancy.given_way.values()] == ["drop"] * 3
    assert len(_placed(plan)) == 6


def test_a_field_of_a_net_that_is_no_plane_has_no_drop_to_fall_back_to():
    plan = _board(NOROOM, [NOROOM_PAD], pad_h=2.0, net="SIG", planes=(), settings=NO_LEAVE).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "SIG is not a plane net, so it is no drop" in step.note, step.note


def test_a_field_of_a_net_that_is_no_plane_is_re_laid_where_there_is_room():
    plan = _board(FIELD, [TOP_ROW], net="SIG", planes=(), settings=NO_LEAVE).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    assert [a.kind for a in plan.occupancy.given_way.values()] == ["relay-move"] * 3
    assert len(_placed(plan)) == 9


def test_closing_the_pitch_keeps_every_via_where_only_that_makes_room():
    rows = (38.95, 39.75, 40.55)            # 0.8 mm apart, and the pad holds no further row
    plan = _board([(x, y) for y in rows for x in (37.5, 38.1, 38.7)], [(18.1, 18.95, 2.4, 0.3)], pad_h=2.6,
                  settings=NO_LEAVE).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    assert {a.way for a in plan.occupancy.given_way.values()} == {"close the pitch"}
    ys = sorted({y for _, y in _placed(plan)})
    assert ys == [19.55, 20.05, 20.55] and len(_placed(plan)) == 9


def test_an_uneven_pitch_moves_only_the_row_that_meets_it_where_the_gap_beside_it_allows():
    rows = (38.95, 40.0, 40.8)              # the first gap holds the row's move
    plan = _board([(x, y) for y in rows for x in (37.5, 38.1, 38.7)], [(18.1, 18.95, 2.4, 0.3)], pad_h=2.6,
                  settings=NO_LEAVE).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    assert {a.way for a in plan.occupancy.given_way.values()} == {"uneven pitch"}
    assert [a.kind for a in plan.occupancy.given_way.values()] == ["relay-move"] * 3
    assert sorted({y for _, y in _placed(plan)}) == [19.55, 20.0, 20.8]


TWO_CORNERS = [(17.5, 19.3, 0.3, 0.3), (18.7, 19.3, 0.3, 0.3)]      # two back pads, one on each corner via of the north row


def test_taking_out_vias_that_meet_it_is_left_to_drop():
    plan = _board(NOROOM, TWO_CORNERS, pad_h=2.0, settings=NO_LEAVE).resolve()
    assert [a.kind for a in plan.occupancy.given_way.values()] == ["drop"] * 2
    assert len(_placed(plan)) == 7


def test_a_whole_row_is_taken_out_where_an_irregular_grid_costs_more_than_the_vias():
    plan = _board(NOROOM, TWO_CORNERS, pad_h=2.0, settings=Settings(place_via_leave_distance=0.0, score_via_relay_gap=100.0)).resolve()
    steps = list(plan.occupancy.given_way.values())
    assert [a.kind for a in steps] == ["relay-drop"] * 3 and {a.way for a in steps} == {"remove a row"}
    assert len(_placed(plan)) == 6
    assert _vias_findings(plan) == ["m: GND field in U1 pad 1 re-laid by remove a row, 9 vias before, "
                                    "6 after (9 drawn) under R10, R9"]


def test_a_relay_never_takes_a_pad_below_the_keep_share():
    plan = _board(NOROOM, TWO_CORNERS, pad_h=2.0, settings=Settings(place_via_leave_distance=0.0, score_via_relay_gap=100.0,
                                                                     place_drops_keep_share=0.8)).resolve()
    step = plan.step("m")                   # ceil(0.8 * 9) = 8 stay: neither the row nor the two vias may go
    assert step.placement is None and "U1 pad 1 keeps 8 of its 9 drops, and must keep 8" in step.note, step.note
    assert not plan.occupancy.given_way


def test_a_later_drop_counts_the_vias_a_relay_took():
    """Three back parts, each over one via of a different row. Whichever lands first has its row taken out
    (6 of 9 stay, the pad keeps 5), the second takes one more by drop, and the third is refused."""
    backs = [(17.5, 19.3, 0.3, 0.3), (18.1, 19.9, 0.3, 0.3), (17.5, 20.5, 0.3, 0.3)]
    plan = _board(NOROOM, backs, pad_h=2.0, cell_first=True,
                  settings=Settings(place_via_leave_distance=0.0, score_via_relay_gap=100.0)).resolve()
    steps = [plan.step(r) for r in ("r9", "r10", "r11")]
    assert sorted(s.placement is None for s in steps) == [False, False, True]
    refused = next(s for s in steps if s.placement is None)
    assert "U1 pad 1 keeps 5 of its 9 drops, and must keep 5" in refused.note, refused.note
    assert sorted(a.kind for a in plan.occupancy.given_way.values()) == ["drop", "relay-drop", "relay-drop", "relay-drop"]


def test_a_field_already_re_laid_is_re_laid_again_for_the_next_item():
    r9, r10 = TOP_ROW, (18.7, 20.5, 0.3, 1.8)
    plan = _board(FIELD, [r9, r10], pad_w=3.2, cell_first=True, settings=NO_LEAVE).resolve()
    assert plan.step("r9").placement is not None and plan.step("r10").placement is not None
    steps = list(plan.occupancy.given_way.values())
    assert {a.kind for a in steps} == {"relay-move"}
    assert {a.field for a in steps} == {"field m U1.1"}
    assert len(_placed(plan)) == 9
    one = [a for a in steps if a.via == "m via 2"][0]        # moved twice: a row, then a column
    assert one.at == pytest.approx((18.7, 19.1)) and one.to == pytest.approx((16.9, 20.9))


def test_undoing_one_via_of_a_relay_puts_the_whole_field_back_as_drawn():
    from placemat import giveway
    plan = _board(FIELD, [TOP_ROW], settings=NO_LEAVE).resolve()
    occ = plan.occupancy
    assert len(occ.given_way) == 3
    giveway.undo(occ, "m via 1")
    assert not occ.given_way
    assert _placed(plan) == sorted((round(x - SHIFT, 3), round(y - SHIFT, 3)) for x, y in FIELD)


def test_undoing_a_via_a_relay_added_takes_it_out_and_brings_the_others_back():
    from placemat import giveway
    from placemat.giveway_field import FieldStep
    plan = _board(FIELD, [TOP_ROW], settings=NO_LEAVE).resolve()
    occ = plan.occupancy
    old = next(iter(occ.given_way.values()))
    shapes = tuple(dataclasses.replace(x, carried="m relay 0", given="m relay 0") for x in old.shapes)
    add = FieldStep(kind="relay-add", via="m relay 0", owner="m", home="m", net="GND", at=(19.0, 20.0), to=(19.0, 20.0),
                    shapes=shapes, field=old.field, way="shift vias", before=9, after=10, want=10)
    occ.given_way["m relay 0"] = add
    occ.copper = occ.copper + list(shapes)
    giveway.undo(occ, "m relay 0")
    assert not occ.given_way
    assert not [c for c in occ.copper if c.carried == "m relay 0"]
    assert _placed(plan) == sorted((round(x - SHIFT, 3), round(y - SHIFT, 3)) for x, y in FIELD)


def test_a_candidate_refused_for_another_via_leaves_the_field_as_it_was():
    """The field's row is re-laid for R9, but a via of the cell's that cannot give way is under R10: the
    resolution is refused and nothing was applied."""
    from placemat import giveway
    from placemat.placement import Placement
    sig = _via("X", 42.9, 40.0, "m")
    b = _board(FIELD, [TOP_ROW, (22.9, 20.0, 1.0, 1.0)], settings=NO_LEAVE, extra=[sig])
    occ = Occupancy(b.geometry, 0.5, settings=b.settings)
    occ.plane_nets = frozenset(["GND"])
    for ref, at in (("R9", (18.1, 19.1)), ("R10", (22.9, 20.0))):
        occ.commit(b.geometry.footprint(ref), Placement(Location(*at), 0.0, Face.BACK))
    cell = b.geometry.cells["m"]
    centre = occ._geometry(cell).reference.location
    before = list(occ.copper)
    res = giveway.resolve(occ, cell, Placement(Location(centre.x - SHIFT, centre.y - SHIFT), 0.0, Face.FRONT))
    assert res.why is not None and "cannot give way" in str(res.why)
    assert any(a.kind == "relay-move" for a in res.actions)         # decided, then refused with the rest
    assert not occ.given_way and occ.copper == before


@pytest.mark.parametrize("flags", [dict(), dict(_NATIVE_MOVE_SEARCH=False), dict(_NATIVE_FIRST_MOVE=False),
                                   dict(_NATIVE_TAIL_CLEAR=False, _NATIVE_MOVE_SEARCH=False, _NATIVE_FIRST_MOVE=False)])
def test_a_relay_is_the_same_whichever_native_calls_judge_the_vias_beside_it(monkeypatch, flags):
    from placemat import giveway
    want = _moves(_board(FIELD, [TOP_ROW], settings=NO_LEAVE).resolve())
    for name, value in flags.items():
        monkeypatch.setattr(giveway, name, value)
    assert _moves(_board(FIELD, [TOP_ROW], settings=NO_LEAVE).resolve()) == want


def test_the_relay_settings_have_defaults_and_are_settable(tmp_path):
    from placemat import settings as S
    d = S.Settings()
    assert (d.place_via_relay, d.score_via_relay, d.score_via_relay_moved, d.score_via_relay_gap,
            d.score_via_relay_pitch) == (True, 3.0, 0.5, 1.0, 4.0)
    (tmp_path / "placemat.toml").write_text("[place]\nvia_relay = false\n[score]\nvia_relay = 2.0\nvia_relay_gap = 3\n")
    got = S.load(tmp_path)
    assert (got.place_via_relay, got.score_via_relay, got.score_via_relay_gap) == (False, 2.0, 3.0)
    (tmp_path / "placemat.toml").write_text("[score]\nvia_relay_pitch = -1\n")
    with pytest.raises(Exception):
        S.load(tmp_path)


def test_the_least_give_way_cost_counts_a_relay():
    from placemat.giveway import least_cost
    off = dict(place_via_share_distance=0.0, place_via_move_distance=0.0, place_via_leave_distance=0.0, place_via_route_distance=0.0)
    assert least_cost(Settings(**off)) == Settings().score_via_relay
    assert least_cost(Settings(place_via_relay=False, **off)) == Settings().score_via_drop


def test_a_routed_via_of_the_field_stays_and_the_rest_of_the_field_is_re_laid_round_it():
    from tests.fixtures import track
    legs = [track("GND", 38.1, 40.3, 36.0, 40.3, w=0.2, owner="m"), track("GND", 38.1, 40.3, 38.1, 42.0, w=0.2, owner="m")]
    plan = _board(FIELD, [TOP_ROW], settings=NO_LEAVE, extra=legs).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    steps = list(plan.occupancy.given_way.values())
    assert [a.kind for a in steps] == ["relay-move"] * 3
    assert "m via 4" not in {a.via for a in steps}               # the via the two tracks end on
    assert len(_placed(plan)) == 9 and (18.1, 20.3) in _placed(plan)


def test_a_thinned_field_keeps_its_count_too():
    """A checkerboard (`Drops.HALF`): five of nine sites. Its row's two corner vias move to free sites."""
    half = [(37.5, 39.1), (38.7, 39.1), (38.1, 39.7), (37.5, 40.3), (38.7, 40.3)]
    plan = _board(half, [TOP_ROW], settings=NO_LEAVE).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    assert [a.kind for a in plan.occupancy.given_way.values()] == ["relay-move"] * 2
    assert len(_placed(plan)) == 5


def test_the_field_frame_follows_the_pads_edges_whatever_its_turn():
    import math
    from placemat.giveway_field import _axis
    turn = math.radians(30.0)

    def rot(x, y):
        return (x * math.cos(turn) - y * math.sin(turn), x * math.sin(turn) + y * math.cos(turn))
    pad_poly = [rot(x, y) for x, y in ((-1.5, -1.0), (1.5, -1.0), (1.5, 1.0), (-1.5, 1.0))]
    pts = [rot(x, y) for x in (-0.6, 0.0, 0.6) for y in (-0.6, 0.0, 0.6)]
    assert math.degrees(_axis(pad_poly, pts)) == pytest.approx(30.0, abs=1e-6)
    assert math.degrees(_axis([(math.cos(a / 12.0 * math.pi), math.sin(a / 12.0 * math.pi)) for a in range(24)],
                              [rot(x, y) for x in (-0.3, 0.3) for y in (-0.3, 0.3)])) == pytest.approx(30.0, abs=1e-6)
