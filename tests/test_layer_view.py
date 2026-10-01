"""placemat layer: one copper layer of a board file, its zone fills, tracks,
vias and pads coloured by net with a legend, and each track that runs inside
another net's zone outline (KiCad refills round it, so DRC passes while the
pour is cut apart)."""
import pcbnew
import pytest

from placemat.layerview import layer_crossings, layer_svg, read_layer
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


def _board(tmp_path):
    b = pcbnew.CreateEmptyBoard()
    nets = {}
    for name in ("GND", "SIG"):
        n = pcbnew.NETINFO_ITEM(b, name)
        b.Add(n)
        nets[name] = n
    z = pcbnew.ZONE(b)
    z.SetLayer(pcbnew.F_Cu)
    z.SetNet(nets["GND"])
    o = z.Outline()
    o.NewOutline()
    for x, y in ((10, 10), (30, 10), (30, 30), (10, 30)):
        o.Append(_vec(x, y))
    b.Add(z)
    t = pcbnew.PCB_TRACK(b)
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(nets["SIG"])
    t.SetWidth(pcbnew.FromMM(0.2))
    t.SetStart(_vec(5, 20))
    t.SetEnd(_vec(35, 20))
    b.Add(t)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    path = tmp_path / "layer.kicad_pcb"
    b.Save(str(path))
    return path


def test_a_track_inside_another_nets_zone_outline_is_listed(tmp_path):
    items = read_layer(_board(tmp_path), "F.Cu")
    (c,) = layer_crossings(items)
    assert c["track_net"] == "SIG" and c["zone_net"] == "GND"
    assert c["start"] == pytest.approx([5.0, 20.0]) and c["end"] == pytest.approx([35.0, 20.0])


def test_the_svg_colours_each_net_and_carries_a_legend(tmp_path):
    items = read_layer(_board(tmp_path), "F.Cu")
    assert {z["net"] for z in items["zones"]} == {"GND"} and items["zones"][0]["fills"]
    text = layer_svg(items, "F.Cu")
    assert text.startswith("<svg") and "GND" in text and "SIG" in text
    assert 'class="fill"' in text and 'class="track"' in text


def _polygon_board(tmp_path):
    b = pcbnew.CreateEmptyBoard()
    for name, filled, x in (("GND", True, 10), ("SIG", False, 20)):
        n = pcbnew.NETINFO_ITEM(b, name)
        b.Add(n)
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_POLY)
        s.SetLayer(pcbnew.F_Cu)
        s.SetFilled(filled)
        s.SetWidth(pcbnew.FromMM(0.2))
        pts = pcbnew.VECTOR_VECTOR2I()
        for px, py in ((x, 10), (x + 5, 10), (x + 5, 15)):
            pts.append(_vec(px, py))
        s.SetPolyPoints(pts)
        s.SetNet(n)
        b.Add(s)
    path = tmp_path / "polys.kicad_pcb"
    b.Save(str(path))
    return path


def test_graphic_copper_polygons_are_drawn_filled_or_outlined_by_net(tmp_path):
    items = read_layer(_polygon_board(tmp_path), "F.Cu")
    assert {(p["net"], p["filled"]) for p in items["polygons"]} == {("GND", True), ("SIG", False)}
    text = layer_svg(items, "F.Cu")
    assert text.count('class="polygon filled"') == 1 and text.count('class="polygon outlined"') == 1
    assert "GND" in text and "SIG" in text


def test_the_summary_line_counts_polygons(tmp_path, capsys):
    from placemat.cli import main
    assert main(["layer", str(_polygon_board(tmp_path)), "F.Cu", "--out", str(tmp_path / "l.svg")]) == 0
    assert "2 polygon(s)" in capsys.readouterr().out


def test_layer_writes_by_default_under_the_views_folder_with_a_gitignore(tmp_path, capsys):
    from placemat.cli import main
    pcb = _polygon_board(tmp_path)
    assert main(["layer", str(pcb), "F.Cu"]) == 0
    svg = pcb.parent / ".placemat" / "views" / "layer" / "layer-F_Cu.svg"
    assert svg.exists() and str(svg) in capsys.readouterr().out
    assert (pcb.parent / ".placemat" / "views" / ".gitignore").read_text() == "*\n"
