"""The preview drawing: a plan to SVG, pure."""
import xml.etree.ElementTree as ET

import pytest

from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.preview import draw
from placemat.values import CopperLayer, Face, LinkWeight, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint

NS = "{http://www.w3.org/2000/svg}"


def _plan():
    """j1 fixed; k1 a wall so u1 has no room by j1 and takes a pocket; r1 on
    the back; big never fits; a limited link met and one broken; a track and
    a via."""
    fps = [footprint("J1", 3, 10, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("K1", 13, 10, w=16, h=17, inst="k1", nets=("K1A", "K1B")),
           footprint("U1", 50, 10, w=6, h=6, inst="u1", nets=("A", "B")),
           footprint("R1", 40, 15, w=2, h=1, inst="r1", nets=("B", "C"), face=Face.BACK),
           footprint("BIG", 30, 30, w=80, h=80, inst="big", nets=("D", "E"))]
    b = Board(board_geometry(fps, width=60, height=20), edge_margin=0.5, keep_going=True)
    b.place(Part("j1"), at=Location(3, 10))
    b.place(Part("k1"), at=Location(13, 10))
    b.place(Part("u1"))
    b.place(Part("r1"), face=Face.BACK)
    b.place(Part("big"))
    b.keepout(Circle(2.0), "clear", at=Location(30, 3), why="a clearance")
    b.link(PadRef(Part("u1"), 2), PadRef(Part("r1"), 1), weight=LinkWeight.SHORT, limit_mm=50.0)
    b.link(PadRef(Part("u1"), 1), PadRef(Part("j1"), 1), limit_mm=1.0)
    b.track(Net("A"), [PadRef(Part("j1"), 1), (6.0, 18.0)], layer=CopperLayer.F)
    b.via(Net("A"), (6.0, 18.0))
    return b.resolve()


def _svg(plan, **kw):
    return ET.fromstring(draw(plan, **kw))


def _cls(root, name):
    return [e for e in root.iter() if name in (e.get("class") or "").split()]


def test_each_face_is_a_panel_and_the_back_is_mirrored():
    root = _svg(_plan())
    front, back = _cls(root, "front"), _cls(root, "back")
    assert len(front) == 1 and len(back) == 1
    assert "scale(-1" in back[0].get("transform", "")


def test_pads_and_courtyards_are_drawn_on_their_face():
    plan = _plan()
    front, back = _cls(_svg(plan), "front")[0], _cls(_svg(plan), "back")[0]
    placed_front = sum(len(plan.geometry.footprint(r).pads) for r in ("J1", "K1", "U1"))
    assert len(_cls(front, "pad")) == placed_front
    assert len(_cls(back, "pad")) == len(plan.geometry.footprint("R1").pads)
    assert len(_cls(front, "courtyard")) == 3 and len(_cls(back, "courtyard")) == 1


def test_links_are_coloured_by_their_limit():
    root = _svg(_plan())
    assert len(_cls(root, "ok")) >= 1 and len(_cls(root, "over")) >= 1
    assert all("link" in (e.get("class") or "") for e in _cls(root, "over"))


def test_a_pocketed_part_is_marked_and_an_unplaced_one_listed():
    plan = _plan()
    assert "u1" in plan.pocketed
    root = _svg(plan)
    assert _cls(root, "pocketed")
    listed = " ".join("".join(e.itertext()) for e in _cls(root, "unplaced"))
    assert "big" in listed


def test_the_heat_map_and_the_worst_cell_can_be_left_out():
    plan = _plan()
    root = _svg(plan)
    assert _cls(root, "heat") and _cls(root, "worst")
    bare = _svg(plan, heat=False, links=False, copper=False)
    assert not _cls(bare, "heat") and not _cls(bare, "worst") and not _cls(bare, "link") and not _cls(bare, "copper")


def test_copper_and_keepouts_are_drawn():
    root = _svg(_plan())
    assert _cls(root, "track") and _cls(root, "via") and _cls(root, "keepout")


def test_the_same_plan_draws_the_same_bytes():
    plan = _plan()
    assert draw(plan) == draw(plan)
    assert draw(_plan()) == draw(_plan())


def test_one_face_alone():
    root = _svg(_plan(), faces=("back",))
    assert not _cls(root, "front") and len(_cls(root, "back")) == 1


def test_a_region_draws_that_part_of_each_face_clipped():
    from placemat.values import Box
    root = _svg(_plan(), region=Box(0, 0, 10, 20))
    whole = _svg(_plan())
    width = lambda r: float(r.get("viewBox").split()[2])
    assert width(root) < width(whole)
    assert len([e for e in root.iter() if e.tag.endswith("clipPath")]) == 2


def test_the_converter_command_is_built_from_the_setting():
    from placemat.previewer import converter_command
    assert converter_command("rsvg-convert --width {width} -o {png} {svg}", "/a b/p.svg", "/a b/p.png", 3200) == \
        ["rsvg-convert", "--width", "3200", "-o", "/a b/p.png", "/a b/p.svg"]


def test_a_missing_or_failing_converter_keeps_the_svg_and_says_why(tmp_path):
    from placemat.previewer import convert
    svg = tmp_path / "p.svg"
    svg.write_text("<svg/>")
    why = convert("no-such-converter-anywhere {svg} {png}", svg, tmp_path / "p.png", 100)
    assert "not installed" in why and svg.exists()
    why = convert("false {svg} {png}", svg, tmp_path / "p.png", 100)
    assert "failed" in why


def test_the_newest_reuse_record_is_the_one_replayed(tmp_path):
    import os
    from placemat import reuse
    from placemat.previewer import newest_record
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    reuse.write(a, {"context": "a"})
    reuse.write(b, {"context": "b"})
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    assert newest_record([(a, "run"), (b, "preview")]) == ({"context": "b"}, "preview")
    assert newest_record([(tmp_path / "none.json", "x")]) == (None, None)


@pytest.mark.skipif(__import__("shutil").which("rsvg-convert") is None, reason="rsvg-convert not installed")
def test_placemat_preview_on_a_fixture_module_writes_both_and_reuses_on_a_second_go(tmp_path):
    import pathlib, shutil, struct, subprocess, sys
    from tests.conftest import _has_pcbnew
    if not _has_pcbnew():
        pytest.skip("pcbnew not importable")
    root = pathlib.Path(__file__).resolve().parent.parent
    mod = tmp_path / "UsbC"
    shutil.copytree(root / "fixtures/mnb/modules/UsbC", mod)
    shutil.copytree(mod / "layout", mod / ".placemat/generated/UsbC")          # the generation, cached
    exe = [sys.executable, "-m", "placemat", "preview", str(mod / "UsbC_layout.py")]
    first = subprocess.run(exe, capture_output=True, text=True, timeout=600)
    assert first.returncode == 0, first.stdout + first.stderr
    png = mod / ".placemat/preview/preview.png"
    assert (mod / ".placemat/preview/preview.svg").exists() and png.exists()
    width = struct.unpack(">I", png.read_bytes()[16:20])[0]
    assert width > 1000
    assert not (mod / ".placemat/runs/latest.json").exists()
    second = subprocess.run(exe, capture_output=True, text=True, timeout=600)
    assert "reused  all" in second.stdout, second.stdout
