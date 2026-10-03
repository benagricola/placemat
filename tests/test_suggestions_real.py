"""A real fixture module, edited to meet each phase-1 case: its findings carry suggestions that name the module's own
parts and declarations, and applying one to the staged COPY of the script gives a script that resolves without the
finding. The fixture under fixtures/ is never written."""
import pytest

from placemat import suggestions as sg
from placemat.values import Location
from tests import real_modules as rm
from tests.suggest_support import rerun, suggestions_of

IMPORT = ("from placemat import board, Along, Bend, Beside, Between, CopperLayer, Edge, Facing, FreeSpot, Net, PadRef, "
          "Part, Past, Pin")
MODULE = "usb5v"


def layout_of(tmp_path):
    return tmp_path / "board" / "modules" / MODULE / "Usb5v_layout.py"


def cases(result, case):
    return [f for f in result.plan.findings if f.case == case]


def apply_first(tmp_path, result, finding, startswith):
    s = next(s for s in finding.suggestions if s.text.startswith(startswith))
    sg.apply_suggestion(suggestions_of(result.plan), s.id, root=tmp_path, log=tmp_path / "applied.jsonl")
    return s


def test_link_over_on_a_real_module(tmp_path):
    edit = lambda t: t + '\nboard.link(PadRef(Part("c_hf1"), "VSHUNT"), PadRef(Part("buck"), VIN_N), limit_mm=0.01)\n'
    result, drc, pcb = rm.run(tmp_path, MODULE, keep_going=True, edit=edit)
    (f,) = cases(result, "link_over")
    assert [s.text for s in f.suggestions][-1].startswith("Raise the limit to ")
    original = rm.FIXTURES.joinpath("modules", MODULE, "Usb5v_layout.py").read_text()
    apply_first(tmp_path, result, f, "Raise the limit")
    text = layout_of(tmp_path).read_text()
    assert "limit_mm=C_HF1_LINK_LIMIT_MM" in text and "C_HF1_LINK_LIMIT_MM = " in text
    assert text.count("\n") > original.count("\n")
    again = rerun(layout_of(tmp_path))
    assert not cases(again, "link_over")


def test_unplaced_search_on_a_real_module(tmp_path):
    edit = lambda t: t.replace(IMPORT, IMPORT + ", Near").replace(
        'board.place(Part("c_en_gate"), at=Beside(Part("c_boot"), Edge.WEST, align=("GND", pad("c_boot", "SW_5V"))),',
        'board.place(Part("c_en_gate"), at=Near(Part("c_hf1"), radius=0.3),', 1)
    result, drc, pcb = rm.run(tmp_path, MODULE, keep_going=True, edit=edit)
    (f,) = cases(result, "unplaced.search")
    assert f.startswith("c_en_gate:")
    texts = [s.text for s in f.suggestions]
    assert any(t.startswith("Place c_en_gate beside ") for t in texts), texts
    apply_first(tmp_path, result, f, "Place c_en_gate beside ")
    assert 'at=Beside(Part("' in layout_of(tmp_path).read_text()
    again = rerun(layout_of(tmp_path))
    assert not [g for g in cases(again, "unplaced.search") if g.startswith("c_en_gate:")]


def test_a_label_on_a_part_on_a_real_module(tmp_path):
    edit = lambda t: t + '\nboard.label(Part("c_hf1"), "IN", side=Edge.SOUTH, gap=0.3, reserve=False)\n'
    result, drc, pcb = rm.run(tmp_path, MODULE, keep_going=True, edit=edit)
    (f,) = cases(result, "label.sits_on")
    assert any(s.text.startswith("Move the label of c_hf1 to its ") for s in f.suggestions)
    s = apply_first(tmp_path, result, f, "Move the label of c_hf1")
    assert "side=Edge." in layout_of(tmp_path).read_text().rsplit("board.label", 1)[1]
    again = rerun(layout_of(tmp_path))
    assert again.status == "ok"
    assert [str(g) for g in cases(again, "label.sits_on") if g.startswith("label c_hf1 IN")] != [str(f)]


def test_tracks_that_cross_on_a_real_module(tmp_path):
    edit = lambda t: t.replace(IMPORT, IMPORT + ", Location") + (
        '\nboard.track(Net("GND"), [Location(-20, -20), Location(-20, -10)], layer=CopperLayer.F, why="a")\n'
        'board.track(Net("PP5V"), [Location(-25, -15), Location(-15, -15)], layer=CopperLayer.F, why="b")\n')
    result, drc, pcb = rm.run(tmp_path, MODULE, keep_going=True, edit=edit)
    (f,) = [f for f in cases(result, "copper.cross") if f.startswith("GND and PP5V cross")]
    assert [s.text for s in f.suggestions if s.lever == "bridge"] == ["Let the GND track pass under PP5V"]
    apply_first(tmp_path, result, f, "Let the GND track pass under PP5V")
    text = layout_of(tmp_path).read_text()
    assert 'Location(-20, -10)], layer=CopperLayer.F, why="a", bridge=True)' in text
    again = rerun(layout_of(tmp_path))
    assert not [g for g in cases(again, "copper.cross") if g.startswith("GND and PP5V cross")]


def test_copper_through_a_keepout_on_a_real_module(tmp_path):
    base, drc, pcb = rm.run(tmp_path / "base", MODULE, keep_going=True)
    from placemat.copper import Track
    track = next(op for op in base.plan.copper if isinstance(op, Track) and op.net.startswith("FB"))
    mid = Location(round((track.start.x + track.end.x) / 2, 2), round((track.start.y + track.end.y) / 2, 2))
    edit = lambda t: t.replace(IMPORT, IMPORT + ", Circle, Location") + (
        '\nboard.keepout(Circle(1.0), "k", at=Location(%s, %s), excludes=("tracks", "vias"), why="a keepout")\n' % (mid.x, mid.y))
    result, drc, pcb = rm.run(tmp_path / "edited", MODULE, keep_going=True, edit=edit)
    mine = [f for f in cases(result, "copper.keepout") if "keepout 'k'" in f and f.startswith("track %s " % track.net)]
    assert mine, [str(f) for f in cases(result, "copper.keepout")]
    f = mine[0]
    assert f.suggestions[0].text == "Let net %s into keepout `k`" % track.net
    apply_first(tmp_path / "edited", result, f, "Let net %s into keepout" % track.net)
    text = layout_of(tmp_path / "edited").read_text()
    assert 'allow=[Net("%s")]' % track.net in text
    again = rerun(layout_of(tmp_path / "edited"))
    assert not [g for g in cases(again, "copper.keepout") if "keepout 'k'" in g and g.startswith("track %s " % track.net)]


def test_a_decided_part_that_collides_on_a_real_module(tmp_path):
    edit = lambda t: t.replace(IMPORT, IMPORT + ", Location").replace(
        'board.place(Part("c_boot"), at=Beside(Part("buck"), Edge.NORTH, align=("BST_5V", pin(CBOOT_PIN))),',
        'board.place(Part("c_boot"), at=Location(20, 20),', 1).replace(
        'board.place(Part("c_vcc"), at=Beside(Part("buck"), Edge.WEST, align=pin(VCC_PIN)), rotation=LYING_FLIPPED,',
        'board.place(Part("c_vcc"), at=Location(20, 20), rotation=LYING_FLIPPED,', 1)
    result, drc, pcb = rm.run(tmp_path, MODULE, keep_going=True, edit=edit)
    (f,) = [f for f in cases(result, "fixed.part") if f.startswith("c_vcc ")]
    assert [s.text for s in f.suggestions] == ["Let c_vcc be searched"]       # the script imports no Face
    apply_first(tmp_path, result, f, "Let c_vcc be searched")
    text = layout_of(tmp_path).read_text()
    assert 'board.place(Part("c_vcc"), rotation=LYING_FLIPPED,' in text
    again = rerun(layout_of(tmp_path))
    assert not [g for g in cases(again, "fixed.part") if g.startswith("c_vcc ")]


def test_a_walled_pad_on_a_real_module_offers_a_fanout_and_a_lane(tmp_path):
    edit = lambda t: t.replace(IMPORT, IMPORT + ", Location").replace(
        'board.place(Part("c_boot"), at=Beside(Part("buck"), Edge.NORTH, align=("BST_5V", pin(CBOOT_PIN))),',
        'board.place(Part("c_boot"), at=Location(20, 20),', 1).replace(
        'board.place(Part("c_vcc"), at=Beside(Part("buck"), Edge.WEST, align=pin(VCC_PIN)), rotation=LYING_FLIPPED,',
        'board.place(Part("c_vcc"), at=Location(20, 20), rotation=LYING_FLIPPED,', 1)
    result, drc, pcb = rm.run(tmp_path, MODULE, keep_going=True, edit=edit)
    f = next(f for f in cases(result, "escape_walled") if f.startswith("C1 pin 1"))
    assert [s.text for s in f.suggestions] == ["Keep c_boot's south side clear", "Keep the lane of c_boot pin 1 clear"]
    s = next(s for s in f.suggestions if s.text.startswith("Keep the lane"))
    shown = sg.apply_suggestion(suggestions_of(result.plan), s.id, dry_run=True).files[str(layout_of(tmp_path))].after
    assert 'board.escape(Part("c_boot"), [1], why="keeps the way out of c_boot pin 1 clear (escape_walled)")\n' in shown
    fan = next(s for s in f.suggestions if s.lever == "fanout")
    shown = sg.apply_suggestion(suggestions_of(result.plan), fan.id, dry_run=True).files[str(layout_of(tmp_path))].after
    assert 'board.fanout(Part("c_boot"), sides=[Edge.SOUTH])\n' in shown


def test_the_fixture_itself_is_untouched():
    folder = rm.FIXTURES / "modules" / MODULE
    assert "board.link" not in (folder / "Usb5v_layout.py").read_text()
