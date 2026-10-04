"""A via that two or more of a stamped cell's tracks end on moves with them: the tracks are rebuilt from
their far ends to the new spot by octilinear legs, judged as one unit
(docs/superpowers/specs/2026-10-01-routed-via-moves-design.md)."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from placemat import giveway
from placemat.copper import Track
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.settings import Settings
from placemat.values import Cell, CopperLayer, Face, Location, Near, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint, track
from tests.test_vias_give_way import _via

F, B = CopperLayer.F, CopperLayer.B


def _board(extra=(), settings=None, a_tracks=True, onward_via=False, on_pad=False, beside=None):
    """Cell m: U1 (front) with SIG pads at (39.1, 40) and (40.9, 40), and a SIG via of the cell's at
    (39.1, 42.2) joined by two tracks that end on it: a straight one up to pad 1, and the first leg of an L
    (east to a corner at (40.9, 42.2), which runs on up to pad 2). It lands 20 mm up and left, the via at
    (19.1, 22.2), 0.075 mm above the back pad S of R9 (top edge 22.5): 0.15 mm up, on the 0.05 mm grid, it
    clears it."""
    copper = [_via("SIG", 39.1, 42.2, owner="m"),
              track("SIG", 39.1, 40.0, 39.1, 42.2, w=0.2, owner="m"),
              track("SIG", 39.1, 42.2, 40.9, 42.2, w=0.2, owner="m"),
              track("SIG", 40.9, 42.2, 40.9, 40.0, w=0.2, owner="m")]
    if not a_tracks:
        copper = copper[:2] + copper[3:]
    if onward_via:
        copper += [_via("SIG", 40.9, 42.2, owner="m")]
    copper += list(extra)
    fps = [footprint("U1", 40, 42.2 if on_pad else 40, w=3, h=1, inst="m.u1", nets=("SIG", "SIG"), cell="m"),
           footprint("R9", 19.5, 23.0, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK)]
    if beside is not None:              # another net's part of the cell, where its pads are the item's own copper near the via
        fps.append(footprint("R1", 39.1 + beside[0], 42.2 + beside[1], w=1, h=0.6, inst="m.r1", nets=("Y", "Y"), cell="m"))
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=("SIG", "Y"))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=True, settings=settings or Settings())
    b.place(Part("r9"), at=Location(19.5, 23.0), face=Face.BACK)
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    return b


def _tracks(plan):
    return [c for c in plan.copper if isinstance(c, Track)]


def _octilinear(t) -> bool:
    dx, dy = t.end.x - t.start.x, t.end.y - t.start.y
    return abs(dx) < 1e-6 or abs(dy) < 1e-6 or abs(abs(dx) - abs(dy)) < 1e-6


def _connected(tracks, p, q) -> bool:
    """Whether `tracks` join the point `p` to `q` end to end."""
    key = lambda x, y: (round(x, 6), round(y, 6))
    seen, todo = {key(*p)}, [key(*p)]
    while todo:
        here = todo.pop()
        for t in tracks:
            for a, b in ((key(t.start.x, t.start.y), key(t.end.x, t.end.y)), (key(t.end.x, t.end.y), key(t.start.x, t.start.y))):
                if a == here and b not in seen:
                    seen.add(b)
                    todo.append(b)
    return key(*q) in seen


def _route(plan):
    [a] = plan.occupancy.given_way.values()
    return a


def test_a_via_joined_by_two_tracks_moves_and_both_are_rebuilt():
    plan = _board().resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    a = _route(plan)
    assert (a.kind, a.via, a.net, a.under) == ("route", "m via 0", "SIG", "R9")
    assert a.to == (19.1, 22.05) and round(a.moved_mm, 6) == 0.15
    assert a.cost == pytest.approx(3.0)
    drawn = _tracks(plan)
    assert drawn and all(_octilinear(t) for t in drawn), drawn
    assert all(t.layer is F and t.width == 0.2 for t in drawn)
    assert _connected(drawn, (19.1, 20.0), a.to) and _connected(drawn, (20.9, 22.2), a.to), drawn
    assert len([t for t in drawn if a.to in ((round(t.start.x, 6), round(t.start.y, 6)), (round(t.end.x, 6), round(t.end.y, 6)))]) == 2
    [ring] = [c for c in plan.occupancy.copper if c.owner == "m" and c.kind == "through"]
    assert ring.points == ((19.1, 22.05),)
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced")], list(plan.findings)
    assert [str(f) for f in plan.findings if f.kind == "vias"] == ["m: 1 SIG via re-routed 0.15 mm under R9"]


def test_the_old_tracks_are_named_as_the_write_takes_them_off():
    a = _route(_board().resolve())
    assert sorted(tuple(tuple(round(c, 6) for c in p) for p in t) for t in a.old_tracks) == sorted([((19.1, 22.2), (19.1, 20.0)), ((19.1, 22.2), (20.9, 22.2))])


def test_a_leg_that_would_meet_another_net_refuses_the_spot_and_the_next_is_tried():
    """Another net's copper beside the straight track's way: the spot straight up from the via is refused
    for it (the track stays on its column), and the nearest spot that clears it is 0.1 mm left as well, reached by a 45 off the
    pad."""
    plan = _board(extra=[track("Y", 19.4, 20.9, 19.4, 21.4, w=0.2)]).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    a = _route(plan)
    assert a.to == (19.0, 22.05)                                    # 0.1 mm left: its column clears the other net by 0.2 mm
    drawn = _tracks(plan)
    assert all(_octilinear(t) for t in drawn)
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced")], list(plan.findings)


def test_nothing_within_reach_is_refused_with_the_reason():
    plan = _board(settings=Settings(place_via_route_distance=0.1)).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "via SIG at (19.10, 22.20)" in step.note and "cannot give way" in step.note, step.note
    assert "no spot within 0.10 mm is clear with its 2 tracks rebuilt" in step.note, step.note
    assert not plan.occupancy.given_way


def test_a_leg_across_another_net_in_every_spot_is_refused():
    wall = track("Y", 20.0, 21.0, 20.0, 22.4, w=0.2)                # across both ways to the via
    plan = _board(extra=[wall]).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "with its 2 tracks rebuilt" in step.note, step.note


def test_via_route_zero_leaves_a_routed_via_as_drawn():
    plan = _board(settings=Settings(place_via_route_distance=0.0)).resolve()
    step = plan.step("m")
    assert step.placement is None
    assert "cannot give way" not in step.note, step.note


def test_a_via_with_one_track_still_moves_as_before():
    plan = _board(a_tracks=False).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    [a] = plan.occupancy.given_way.values()
    assert a.kind == "move"


def test_a_via_whose_track_runs_on_to_another_via_is_not_carried():
    occ = Occupancy(_board(onward_via=True).geometry)
    assert not [s for s in occ.copper if s.carried and s.net == "SIG"]


def test_routing_costs_score_via_route_in_the_search():
    from placemat.placement import Placement
    from placemat.placer import scan
    b = _board()
    occ = Occupancy(b.geometry, 0.5, settings=b.settings)
    occ.commit(b.geometry.footprint("R9"), Placement(Location(19.5, 23.0), 0.0, Face.BACK))
    centre = occ._geometry(b.geometry.cells["m"]).reference.location
    hint = Placement(Location(centre.x - 20, centre.y - 20), 0.0, Face.FRONT)
    r = scan(occ, b.geometry.cells["m"], hint, 0.0, 0.2, (0.0,), score=lambda p: 0.0)
    assert r.chosen is not None and r.score == 3.0


def test_undo_puts_the_via_and_every_track_back():
    plan = _board().resolve()
    occ = plan.occupancy
    before = sorted((s.kind, s.points) for s in occ.copper if s.owner == "m" and not s.given)
    assert _route(plan).kind == "route"
    giveway.undo(occ, "m via 0")
    assert not occ.given_way
    assert not [s for s in occ.copper if s.given]
    after = sorted((s.kind, s.points) for s in occ.copper if s.owner == "m")
    assert any(k == "through" for k, _ in after)
    assert len([s for s in occ.copper if s.owner == "m" and s.kind == "copper" and s.carried]) == 2
    ring = next(s for s in occ.copper if s.owner == "m" and s.kind == "through")
    assert ring.points == ((19.1, 22.2),)
    assert before is not None


def test_the_native_and_the_python_judging_choose_the_same_spot(monkeypatch):
    blocker = [track("Y", 19.4, 20.9, 19.4, 21.4, w=0.2)]
    native = _route(_board(extra=blocker).resolve())
    monkeypatch.setattr(giveway, "_NATIVE_MOVE_SEARCH", False)
    monkeypatch.setattr(giveway, "_NATIVE_TAIL_CLEAR", False)
    monkeypatch.setattr(giveway, "_NATIVE_FIRST_MOVE", False)
    python = _route(_board(extra=blocker).resolve())
    assert (native.to, native.tracks, native.old_tracks) == (python.to, python.tracks, python.old_tracks)


def test_the_native_prefilter_of_the_spots_judges_and_charges_as_the_python_loop_does(monkeypatch):
    """Spots the item's own copper or a pad refuses are left out by one native call; the action chosen and the
    judgments charged to the resolution (they limit a give-way's work) are those of the loop that judges every spot."""
    import random
    rnd = random.Random(20261004)
    total = [0]
    real = giveway._Judge.count

    def counting(self, n):
        total[0] += n
        return real(self, n)
    monkeypatch.setattr(giveway._Judge, "count", counting)
    kinds = {}
    for case in range(24):
        extra = []
        for _ in range(rnd.randint(1, 4)):
            x, y = 19.1 + rnd.uniform(-1.2, 1.2), 22.2 + rnd.uniform(-1.2, 1.2)
            x1, y1 = x + rnd.choice([0, 0.6, -0.6]), y + rnd.choice([0, 0.6, -0.6])
            extra.append(track(rnd.choice(["Y", "Y", "SIG"]), x, y, x1, y1, w=rnd.choice([0.2, 0.3])))
        beside = (rnd.uniform(-0.9, 0.9), rnd.uniform(-0.9, 0.9)) if case % 3 else None
        out = []
        for on in (False, True):
            monkeypatch.setattr(giveway, "_NATIVE_FIRST_MOVE", on)
            total[0] = 0
            plan = _board(extra=extra, on_pad=case % 2 == 1, beside=beside).resolve()
            acted = [(a.kind, a.to, a.tracks, a.old_tracks) for a in plan.occupancy.given_way.values()]
            out.append((plan.step("m").placement is not None, acted, total[0]))
        assert out[0] == out[1], "case %d" % case
        kind = out[0][1][0][0] if out[0][1] else ("placed" if out[0][0] else "refused")
        kinds[kind] = kinds.get(kind, 0) + 1
    assert kinds.get("route", 0) >= 5 and len(kinds) >= 2, kinds
# ------------------------------------------------------------------ KiCad

@needs_kicad
def test_the_written_cell_passes_kicads_drc(tmp_path):
    pcbnew = pytest.importorskip("pcbnew")
    from placemat.kicad.write import _given_way

    plan = _board().resolve()
    assert plan.step("m").placement is not None

    def mm(x, y=None):
        return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6))) if y is not None else pcbnew.FromMM(x)
    board = pcbnew.CreateEmptyBoard()
    nets = {}

    def net(n):
        if n not in nets:
            nets[n] = pcbnew.NETINFO_ITEM(board, n)
            board.Add(nets[n])
        return nets[n]
    for ref, cx, cy, layer, ns in (("U1", 20.0, 20.0, pcbnew.F_Cu, ("SIG", "SIG")), ("R9", 19.5, 23.0, pcbnew.B_Cu, ("S", "T"))):
        kfp = pcbnew.FOOTPRINT(board)
        kfp.SetReference(ref)
        kfp.SetPosition(mm(cx, cy))
        for k, (px, n) in enumerate(zip((cx - 0.9 if ref == "U1" else cx - 0.4, cx + 0.9 if ref == "U1" else cx + 1.1), ns)):
            kp = pcbnew.PAD(kfp)
            kp.SetShape(pcbnew.PAD_SHAPE_RECT)
            kp.SetSize(mm(1.0, 1.0))
            kp.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            ls = pcbnew.LSET()
            ls.AddLayer(layer)
            kp.SetLayerSet(ls)
            kp.SetPosition(mm(px, cy))
            kp.SetNumber(str(k + 1))
            kp.SetNet(net(n))
            kfp.Add(kp)
        board.Add(kfp)
    group = pcbnew.PCB_GROUP(board)
    group.SetName("m")
    board.Add(group)
    via = pcbnew.PCB_VIA(board)
    via.SetViaType(pcbnew.VIATYPE_THROUGH)
    via.SetPosition(mm(19.1, 22.2))
    via.SetWidth(mm(0.45))
    via.SetDrill(mm(0.2))
    via.SetNet(net("SIG"))
    board.Add(via)
    group.AddItem(via)

    def trk(a, b):
        t = pcbnew.PCB_TRACK(board)
        t.SetLayer(pcbnew.F_Cu)
        t.SetWidth(mm(0.2))
        t.SetStart(mm(*a))
        t.SetEnd(mm(*b))
        t.SetNet(net("SIG"))
        board.Add(t)
        return t
    for a, b in (((19.1, 20.0), (19.1, 22.2)), ((19.1, 22.2), (20.9, 22.2)), ((20.9, 22.2), (20.9, 20.0))):
        group.AddItem(trk(a, b))
    _given_way(board, SimpleNamespace(given_way=list(plan.occupancy.given_way.values())), {"m": group})
    for t in _tracks(plan):
        trk((t.start.x, t.start.y), (t.end.x, t.end.y))
    pcb = tmp_path / "cell.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    data = json.loads(report.read_text())
    bad = [v for v in data.get("violations", [])
           if v.get("type") in ("clearance", "hole_clearance", "hole_to_hole", "shorting_items", "tracks_crossing",
                                "track_dangling")]
    assert bad == [], bad
    assert data.get("unconnected_items", []) == [], data["unconnected_items"]
    moved = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
    assert [(round(v.GetPosition().x / 1e6, 3), round(v.GetPosition().y / 1e6, 3)) for v in moved] == [(19.1, 22.05)]
