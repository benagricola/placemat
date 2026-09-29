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
