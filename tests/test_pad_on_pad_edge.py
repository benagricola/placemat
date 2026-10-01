"""A part's pad placed on another pad's edge: Pin(key, PadRef(..., edge=, along=)),
and a net tie that draws nothing claiming its copper only. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import (Along, Box, CopperLayer, Edge, Face, Location, Net, PadRef, Part, Pin, Turned, X, Y)
from tests.fixtures import board_geometry, footprint, pad, rect

F = CopperLayer.F
OVER = 0.005          # how far a placed pad's copper reaches over the edge it lies against


def _part(ref, pads, cx, cy, fab=True):
    body = Box.union([p.box for p in pads]).inflate(0.2)
    poly = ((body.left, body.top), (body.right, body.top), (body.right, body.bottom), (body.left, body.bottom))
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                     tuple(pads), fab=((Face.FRONT, poly),) if fab else ())


def _shunt(fab=True):
    """An upright shunt RS at (30, 30): V_HI pad north (y 28.05 to 29.62), V_LO pad south (30.38 to
    31.95), each 1.2 wide (x 29.4 to 30.6): a 0.76 gap between them."""
    return _part("RS", [pad("RS", "rs", 1, "V_HI", 30, 28.835, 1.2, 1.57),
                        pad("RS", "rs", 2, "V_LO", 30, 31.165, 1.2, 1.57)], 30, 30, fab)


def _tie(ref, nets, courtyard=False, w=0.3, h=0.3, round_pads=True):
    """A stock 0.3 mm net tie: pad 1 at the origin (20, 20), pad 2 0.5 mm east, a copper bar between
    them, front copper only; no courtyard, silk or fab unless `courtyard`."""
    inst = ref.lower()
    base = footprint(ref, 20.25, 20, w=0.8, h=0.3, inst=inst, nets=nets, excess=0.0, silk=(0, 0, 0, 0))
    pads = []
    for p, cx, net in zip(base.pads, (20.0, 20.5), nets):
        outline = circle_polygon(Location(cx, 20.0), w / 2, 32) if round_pads else rect(cx, 20.0, w, h)
        pads.append(dataclasses.replace(p, net=net, outlines=(outline,), box=Box.of_points(outline)))
    bar = rect(20.25, 20.0, 0.5, h)
    phys = Box.union([p.box for p in pads])
    extra = {}
    if courtyard:
        ct = Box(phys.left - 0.25, phys.top - 0.25, phys.right + 0.25, phys.bottom + 0.25)
        extra = dict(courtyard_poly=rect(ct.center.x, ct.center.y, ct.width, ct.height))
    return dataclasses.replace(base, body_box=phys, courtyard_box=phys, phys_box=phys, pads=tuple(pads), silk=(),
                               fab=(), mask=(), copper=((F, bar),), net_tie_pads=frozenset({"1", "2"}), **extra)


def _board(parts, envelope="courtyard", clearance=0.16, **kw):
    settings = dataclasses.replace(Settings(), place_envelope=envelope)
    return Board(board_geometry(parts, width=60, height=60, clearance=clearance,
                                extra_nets=("V_HI_SENSE", "V_LO_SENSE")),
                 edge_margin=1.0, keep_going=True, settings=settings, **kw)


def _shunt_ties(envelope="courtyard", rotation=0, tie_courtyard=False):
    b = _board([_shunt(), _tie("NT1", ("V_HI", "V_HI_SENSE"), tie_courtyard),
                _tie("NT2", ("V_LO", "V_LO_SENSE"), tie_courtyard)], envelope)
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    b.place(Part("nt1"), at=Pin(1, PadRef(Part("rs"), 1, edge=Edge.SOUTH, along=Along.END)), rotation=rotation)
    b.place(Part("nt2"), at=Pin(1, PadRef(Part("rs"), 2, edge=Edge.NORTH, along=Along.END)), rotation=rotation)
    return b.resolve()


def _pad(plan, ref, number):
    return next(s.box for s in plan.occupancy.items[ref].shapes if s.kind == "pad" and s.label == str(number))


def _own(plan):
    return [f for f in plan.findings if "no declaration places it" not in f]


# ------------------------------------------------------------------ Pin's forms

def test_pin_takes_one_point_or_two_axes():
    p = PadRef(Part("r"), 1)
    assert Pin(1, p).x == p
    one, two = Pin(1, p), Pin(1, X(p), Y(p))
    assert (two.x, two.y) == (X(p), Y(p)) and one != two
    with pytest.raises(ValueError):
        Pin(1, None)


def test_a_pin_of_two_axes_digests_as_before():
    from placemat.reuse import canonical
    assert "None" not in str(canonical(Pin(1, 2.0, 3.0)))


def test_a_pin_of_a_location_point_places_the_pad_there():
    r = footprint("R1", 5, 5, inst="r1")
    b = _board([r])
    b.place(Part("r1"), at=Pin(1, Location(20, 20)), rotation=0)
    assert _pad(b.resolve(), "R1", 1).center.x == pytest.approx(20.0)


# ------------------------------------------------------------------ the placed pad's place

def test_a_pad_placed_at_the_end_of_an_edge_lies_outside_it_flush_with_the_side():
    plan = _shunt_ties()
    box = _pad(plan, "NT1", 1)
    shunt = _pad(plan, "RS", 1)
    assert box.top == pytest.approx(shunt.bottom - OVER, abs=1e-6)        # reaches 0.005 over the edge
    assert box.bottom == pytest.approx(shunt.bottom - OVER + 0.3, abs=1e-6)
    assert box.right == pytest.approx(shunt.right, abs=1e-6)              # flush with the pad's east side
    assert not _own(plan), plan.findings


def test_a_pad_placed_at_the_middle_of_an_edge_is_centred_on_it():
    b = _board([_shunt(), _tie("NT1", ("V_HI", "V_HI_SENSE"))])
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    b.place(Part("nt1"), at=Pin(1, PadRef(Part("rs"), 1, edge=Edge.SOUTH)), rotation=0)
    plan = b.resolve()
    assert _pad(plan, "NT1", 1).center.x == pytest.approx(30.0, abs=1e-6)


def test_the_through_x_and_y_form_says_the_same():
    b = _board([_shunt(), _tie("NT1", ("V_HI", "V_HI_SENSE"))])
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    tap = PadRef(Part("rs"), 1, edge=Edge.SOUTH, along=Along.END)
    b.place(Part("nt1"), at=Pin(1, X(tap), Y(tap)), rotation=0)
    plan = b.resolve()
    assert _pad(plan, "NT1", 1).right == pytest.approx(_pad(plan, "RS", 1).right, abs=1e-6)
    assert _pad(plan, "NT1", 1).top == pytest.approx(_pad(plan, "RS", 1).bottom - OVER, abs=1e-6)


def _bar_part():
    """A part whose pad 1 is 0.6 wide and 0.2 tall at rotation 0."""
    p = _tie("T1", ("V_HI", "V_HI_SENSE"), w=0.6, h=0.2, round_pads=False)
    return p


def test_the_size_across_the_edge_is_the_part_as_it_stands_turned():
    for rot, across in ((0, 0.2), (90, 0.6)):
        b = _board([_shunt(), _bar_part()])
        b.place(Part("rs"), at=Location(30, 30), rotation=0)
        b.place(Part("t1"), at=Pin(1, PadRef(Part("rs"), 1, edge=Edge.SOUTH)), rotation=rot)
        plan = b.resolve()
        box = _pad(plan, "T1", 1)
        assert box.top == pytest.approx(_pad(plan, "RS", 1).bottom - OVER, abs=1e-6), rot
        assert box.height == pytest.approx(across, abs=1e-6), rot


def test_a_turned_rotation_settles_before_the_size_is_taken():
    b = _board([_shunt(), _bar_part()])
    b.place(Part("rs"), at=Location(30, 30), rotation=90)
    b.place(Part("t1"), at=Pin(1, PadRef(Part("rs"), 1, edge=Edge.EAST)), rotation=Turned(Part("rs"), 90))
    plan = b.resolve()
    shunt, tie = _pad(plan, "RS", 1), _pad(plan, "T1", 1)
    assert tie.left == pytest.approx(shunt.right - OVER, abs=1e-6)       # a 180 turn: its 0.6 side lies across the edge
    assert tie.width == pytest.approx(0.6, abs=1e-6)


def test_two_ties_in_the_gap_are_placed_a_sliver_apart_and_judged_clear():
    plan = _shunt_ties()
    a, c = _pad(plan, "NT1", 1), _pad(plan, "NT2", 1)
    assert c.top - a.bottom == pytest.approx(0.76 - 0.6 + 2 * OVER, abs=1e-6)       # 0.17
    assert not _own(plan), plan.findings


@pytest.mark.parametrize("envelope", ["courtyard", "physical", "union"])
def test_the_shunt_with_its_ties_is_clean_in_every_envelope(envelope):
    plan = _shunt_ties(envelope)
    assert not _own(plan), plan.findings


# ------------------------------------------------------------------ a net tie standing out from a pad

def _standing_rider(rotation):
    """The shunt is searched (the board gives it a place) and a stock tie rides it: its pad 1 against the shunt's
    V_HI pad on the south edge, the rest of the tie turned `rotation`."""
    b = _board([_shunt(), _tie("NT1", ("V_HI", "V_HI_SENSE"))])
    b.place(Part("rs"))
    b.place(Part("nt1"), at=Pin(1, PadRef(Part("rs"), 1, edge=Edge.SOUTH, along=Along.MID)), rotation=rotation)
    return b.resolve()


def test_a_datum_part_is_placed_with_a_net_tie_riding_it_that_stands_out_from_its_pad():
    """The tie's bar is 0.145 mm from the pad it stands on, which the tie's pad 1 joins: KiCad's DRC gives the bar
    no clearance to the nets of the tie's pads, so the part's search does not refuse every place for it."""
    plan = _standing_rider(270)
    assert not [f for f in plan.findings if "rider" in f or "no place" in f or "cannot be laid out" in f], plan.findings
    pad1, pad2 = _pad(plan, "NT1", 1), _pad(plan, "NT1", 2)
    shunt = _pad(plan, "RS", 1)
    assert pad2.center.y > pad1.center.y                                                   # pad 2 lies further out
    assert pad1.top == pytest.approx(shunt.bottom - OVER, abs=1e-6)


def test_a_riding_net_tie_turned_to_lie_across_the_pad_of_another_net_is_still_refused():
    """Its pad 2 (net V_HI_SENSE) then lies over copper of V_HI wherever the shunt stands."""
    plan = _standing_rider(0)
    assert [f for f in plan.findings if "cannot be laid out with its riders" in f], plan.findings


# ------------------------------------------------------------------ refusals

def test_an_end_on_a_round_target_pad_is_refused_naming_the_pad():
    r1 = footprint("R1", 20, 20, w=4, h=2, inst="r1", nets=("A", "B"))
    disc = circle_polygon(Location(18.6, 20.0), 0.5, 32)
    r1 = dataclasses.replace(r1, pads=(dataclasses.replace(r1.pads[0], outlines=(disc,), box=Box.of_points(disc)),
                                       r1.pads[1]))
    b = _board([r1, _tie("NT1", ("A", "B"))])
    b.place(Part("r1"), at=Location(20, 20), rotation=0)
    b.place(Part("nt1"), at=Pin(1, PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END)), rotation=0)
    with pytest.raises(ValueError, match="R1"):
        b.resolve()


def test_an_edge_point_is_still_refused_for_a_via():
    b = _board([_shunt()])
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    b.via(Net("V_HI"), PadRef(Part("rs"), 1, edge=Edge.EAST))
    with pytest.raises(ValueError, match="edge="):
        b.resolve()


# ------------------------------------------------------------------ a net tie that draws nothing

def _third(ref, nets, cx, cy, w=2.0, h=2.0):
    """A third part: a drawn body (fab) w x h about (cx, cy), a pad on `nets[0]` at its west end."""
    p = footprint(ref, cx, cy, w=w, h=h, nets=nets, inst=ref.lower(), fab=(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    return p


def _cover(ref, left, drawn=True, pad_at=1.0):
    """A third part east of the shunt: its body (and courtyard) 2.0 wide from x `left`, y 29.4 to 30.1,
    its one pad (net X) `pad_at` from its west side."""
    box = Box(left, 29.4, left + 2.0, 30.1)
    p = pad(ref, ref.lower(), 1, "X", left + pad_at, 29.75, 0.5, 0.5)
    poly = ((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom))
    return Footprint(ref, ref.lower(), None, ref, Location(left + pad_at, 29.75), 0.0, Face.FRONT, box, box, box, (p,),
                     fab=((Face.FRONT, poly),) if drawn else ())


def _with_cover(envelope, cover, at):
    b = _board([_shunt(), _tie("NT1", ("V_HI", "V_HI_SENSE")), cover], envelope)
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    b.place(Part("nt1"), at=Pin(1, PadRef(Part("rs"), 1, edge=Edge.SOUTH, along=Along.END)), rotation=0)
    b.place(Part(cover.inst), at=Location(*at), rotation=0)
    return b.resolve()


@pytest.mark.parametrize("drawn", [True, False])
@pytest.mark.parametrize("envelope", ["courtyard", "physical", "union"])
def test_another_parts_body_and_courtyard_may_stand_over_a_tie(envelope, drawn):
    """CV's body (or, drawing nothing, its claimed courtyard) covers the tie's pad 2 by 0.1 mm."""
    plan = _with_cover(envelope, _cover("CV", 31.0, drawn), (32.0, 29.75))
    assert not _own(plan), plan.findings


@pytest.mark.parametrize("envelope", ["courtyard", "physical", "union"])
def test_another_parts_other_net_pad_near_a_tie_is_a_conflict(envelope):
    """CV's pad (net X) 0.1 mm from the tie's pad 2 (V_HI_SENSE): inside the 0.16 clearance."""
    plan = _with_cover(envelope, _cover("CV", 31.0, drawn=False, pad_at=0.45), (31.45, 29.75))
    assert [f for f in plan.findings if "V_HI_SENSE copper" in f], plan.findings


@pytest.mark.parametrize("native", [True, False])
def test_a_pad_of_the_ties_net_standing_on_its_pad_is_judged_clear_native_or_not(native, monkeypatch):
    """KiCad's net-tie exclusion is Python's: where native flags a pad of the tie's net on the tie's bar
    inside its pad, the check goes to Python and finds none."""
    from placemat import geometry
    if not native:
        monkeypatch.setattr(geometry, "_native", None)
    probe = _part("P", [pad("P", "p", 1, "V_HI_SENSE", 31.0, 29.765, 0.2, 0.2)], 31.0, 29.765, fab=False)
    probe = dataclasses.replace(probe, body_box=probe.pads[0].box, courtyard_box=probe.pads[0].box)
    b = _board([_shunt(), _tie("NT1", ("V_HI", "V_HI_SENSE")), probe])
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    b.place(Part("nt1"), at=Pin(1, PadRef(Part("rs"), 1, edge=Edge.SOUTH, along=Along.END)), rotation=0)
    b.place(Part("p"), at=Location(31.0, 29.765), rotation=0)
    plan = b.resolve()
    assert not [f for f in plan.findings if "P " in f or "p (" in f], plan.findings


def test_a_tie_claims_no_courtyard_and_no_body_in_any_envelope():
    from placemat.occupancy import _fp_shapes
    tie = _tie("NT1", ("A", "B"))
    for env in ("courtyard", "physical", "union"):
        kinds = {s.kind for s in _fp_shapes(tie, env, 0.98)}
        assert kinds == {"pad", "copper"}, (env, kinds)


def test_a_tie_that_draws_a_courtyard_is_still_claimed_by_it():
    from placemat.occupancy import _fp_shapes
    tie = _tie("NT1", ("A", "B"), courtyard=True)
    assert "courtyard" in {s.kind for s in _fp_shapes(tie, "courtyard", 0.98)}
    # and it keeps another part's courtyard out
    cover = footprint("CV", 20.25, 20, w=1.0, h=1.0, nets=("X", "Y"), inst="cv", excess=0.0)
    b = _board([tie, cover])
    b.place(Part("nt1"), at=Location(20.25, 20), rotation=0)
    b.place(Part("cv"), at=Location(20.25, 20.2), rotation=0)
    plan = b.resolve()
    assert [f for f in plan.findings if "courtyard" in f], plan.findings


def test_a_tie_that_draws_silk_is_not_copper_only():
    from placemat.occupancy import _fp_shapes
    tie = dataclasses.replace(_tie("NT1", ("A", "B")), silk=((Face.FRONT, rect(20.25, 19.5, 1.0, 0.1)),))
    assert "courtyard" in {s.kind for s in _fp_shapes(tie, "courtyard", 0.98)}


# ------------------------------------------------------------------ KiCad's DRC

def test_the_shunt_with_its_two_ties_passes_kicads_drc(tmp_path):
    """The written board: the shunt and two ties in its gap; KiCad finds no clearance, courtyard or
    unconnected item."""
    import json
    import subprocess
    pcbnew = pytest.importorskip("pcbnew")
    plan = _shunt_ties()
    assert not _own(plan), plan.findings
    board = pcbnew.CreateEmptyBoard()
    board.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(0.16))
    v = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    nets = {}
    for name in ("V_HI", "V_LO", "V_HI_SENSE", "V_LO_SENSE"):
        nets[name] = pcbnew.NETINFO_ITEM(board, name)
        board.Add(nets[name])

    def front(pad_):
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        pad_.SetLayerSet(ls)
        pad_.SetAttribute(pcbnew.PAD_ATTRIB_SMD)

    def part(ref, pads, tie=False):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        board.Add(fp)
        first = pads[0]
        fp.SetPosition(v(first[2], first[3]))
        made = []
        for number, net, x, y, w, h, round_ in pads:
            p = pcbnew.PAD(fp)
            p.SetNumber(str(number))
            p.SetShape(pcbnew.PAD_SHAPE_CIRCLE if round_ else pcbnew.PAD_SHAPE_RECT)
            front(p)
            p.SetSize(v(w, h))
            p.SetPosition(v(x, y))
            fp.Add(p)
            p.SetNet(nets[net])
            made.append(p)
        return fp, made

    for ref, pads in (("RS", ((1, "V_HI", 30, 28.835, 1.2, 1.57, False), (2, "V_LO", 30, 31.165, 1.2, 1.57, False))),):
        part(ref, pads)
    for ref, nets_ in (("NT1", ("V_HI", "V_HI_SENSE")), ("NT2", ("V_LO", "V_LO_SENSE"))):
        p1, p2 = _pad(plan, ref, 1).center, _pad(plan, ref, 2).center
        fp, made = part(ref, ((1, nets_[0], p1.x, p1.y, 0.3, 0.3, True), (2, nets_[1], p2.x, p2.y, 0.3, 0.3, True)),
                        tie=True)
        bar = pcbnew.PCB_SHAPE(board)
        bar.SetShape(pcbnew.SHAPE_T_SEGMENT)
        bar.SetStart(v(p1.x, p1.y))
        bar.SetEnd(v(p2.x, p2.y))
        bar.SetWidth(pcbnew.FromMM(0.3))
        bar.SetLayer(pcbnew.F_Cu)
        fp.Add(bar)
        fp.AddNetTiePadGroup("1, 2")
    pcb = tmp_path / "shunt.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    data = json.loads(report.read_text())
    bad = [x for x in data.get("violations", []) if x.get("type") in ("clearance", "courtyards_overlap", "shorting_items",
                                                                       "copper_edge_clearance", "hole_clearance")]
    assert not bad, bad
    assert not data.get("unconnected_items"), data.get("unconnected_items")


def test_a_pin_at_a_pitch_from_another_pad_by_a_polar_about_it():
    """Pin(key, Polar(radius, bearing, about=pad)): the pad a mechanical
    pitch from another pad along a bearing (90 is east), said as one point."""
    from placemat.layout import Board
    from placemat.values import Location, PadRef, Part, Pin, Polar
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("J1", 10, 10, w=2, h=1, inst="j1", nets=("A", "B")),
           footprint("J2", 20, 20, w=2, h=1, inst="j2", nets=("C", "D"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("j1"), at=Location(20, 20), rotation=0)
    b.place(Part("j2"), at=Pin(1, Polar(2.7, 90, about=PadRef(Part("j1"), 1))), rotation=0)
    plan = b.resolve()
    p1, p2 = plan.occupancy.pad_location("J1", "1"), plan.occupancy.pad_location("J2", "1")
    assert (round(p2.x - p1.x, 6), round(p2.y - p1.y, 6)) == (2.7, 0.0)
