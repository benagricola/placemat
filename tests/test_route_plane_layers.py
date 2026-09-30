"""The route step's default layers: signal and mixed layers, F.Cu and B.Cu
always, from each layer's role in the board's stackup - not whether a
plane happens to fill it whole. plane_layers/_plane_zones (coverage-based)
remain as their own tested utility, used elsewhere for pour-guarding."""
from placemat.kicad.route import plane_layers, plane_note, resolved_layers
from tests.conftest import needs_kicad


def _zone(layer, net, area, in_group=False):
    return {"layer": layer, "net": net, "in_group": in_group, "area": area}


def test_an_inner_plane_at_95_percent_is_dropped():
    zones = [_zone("In1.Cu", "GND", 95.0)]
    assert plane_layers(zones, 100.0, 0.9) == ["In1.Cu"]


def test_an_inner_plane_at_50_percent_is_kept():
    zones = [_zone("In1.Cu", "GND", 50.0)]
    assert plane_layers(zones, 100.0, 0.9) == []


def test_a_cells_zone_is_kept_however_large():
    zones = [_zone("In1.Cu", "GND", 99.0, in_group=True)]
    assert plane_layers(zones, 100.0, 0.9) == []


def test_f_cu_and_b_cu_are_never_dropped():
    zones = [_zone("F.Cu", "GND", 100.0), _zone("B.Cu", "GND", 100.0), _zone("In1.Cu", "GND", 95.0)]
    assert plane_layers(zones, 100.0, 0.9) == ["In1.Cu"]


def test_several_qualifying_layers_come_back_sorted():
    zones = [_zone("In4.Cu", "GND", 96.0), _zone("In1.Cu", "GND", 95.0), _zone("In2.Cu", "3V3", 60.0)]
    assert plane_layers(zones, 100.0, 0.9) == ["In1.Cu", "In4.Cu"]


def test_an_explicit_list_overrides_the_role_based_default():
    layer_types = {"In1.Cu": "power"}
    layers, dropped = resolved_layers(["F.Cu", "In1.Cu", "B.Cu"], ["F.Cu", "In1.Cu", "B.Cu"], layer_types)
    assert layers == ["F.Cu", "In1.Cu", "B.Cu"] and dropped == {}


def test_with_nothing_explicit_only_signal_and_mixed_layers_route():
    """F signal, In1 ground (power), In2 signal, In3 power, In4 ground
    (power), B signal: routes on F, In2 and B."""
    all_layers = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]
    layer_types = {"F.Cu": "signal", "In1.Cu": "power", "In2.Cu": "signal",
                   "In3.Cu": "power", "In4.Cu": "power", "B.Cu": "signal"}
    layers, dropped = resolved_layers(None, all_layers, layer_types)
    assert layers == ["F.Cu", "In2.Cu", "B.Cu"]
    assert dropped == {"In1.Cu": "power", "In3.Cu": "power", "In4.Cu": "power"}


def test_a_mixed_layer_routes_too():
    all_layers = ["F.Cu", "In1.Cu", "B.Cu"]
    layer_types = {"F.Cu": "signal", "In1.Cu": "mixed", "B.Cu": "signal"}
    layers, dropped = resolved_layers(None, all_layers, layer_types)
    assert layers == ["F.Cu", "In1.Cu", "B.Cu"] and dropped == {}


def test_f_and_b_route_whatever_their_role():
    all_layers = ["F.Cu", "In1.Cu", "B.Cu"]
    layer_types = {"F.Cu": "jumper", "In1.Cu": "power", "B.Cu": "jumper"}
    layers, dropped = resolved_layers(None, all_layers, layer_types)
    assert layers == ["F.Cu", "B.Cu"] and dropped == {"In1.Cu": "power"}


def test_a_layer_with_no_declared_role_defaults_to_signal():
    all_layers = ["F.Cu", "In1.Cu", "B.Cu"]
    layers, dropped = resolved_layers(None, all_layers, {})
    assert layers == all_layers and dropped == {}


def test_plane_note_names_the_layers_and_their_role():
    note = plane_note({"In1.Cu": "power", "In4.Cu": "power"})
    assert note == "route layers: In1.Cu, In4.Cu left out, role power; placemat route --layers to override"


def test_plane_note_is_singular_for_one_layer():
    note = plane_note({"In1.Cu": "power"})
    assert note == "route layers: In1.Cu left out, role power; placemat route --layers to override"


def test_plane_note_is_empty_with_nothing_dropped():
    assert plane_note({}) == ""


def _synthetic_plane_board(tmp_path):
    """A 40x40 mm, 4-layer board: F.Cu and In1.Cu both carry a GND zone over
    (almost) the whole outline, In2.Cu carries a half-board zone plus a
    near-whole one inside a cell's group. Off pcbnew's own reading, this
    should drop only In1.Cu: F.Cu is an outer layer, and In2.Cu's large zone
    does not count because it belongs to a cell."""
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(4)

    def vec(x, y):
        return pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6))

    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(vec(*a))
        s.SetEnd(vec(*c))
        b.Add(s)
    net = pcbnew.NETINFO_ITEM(b, "GND")
    b.Add(net)

    def zone(layer_id, pts, name=""):
        z = pcbnew.ZONE(b)
        z.SetIsRuleArea(False)
        z.SetLayer(layer_id)
        z.SetNetCode(net.GetNetCode())
        o = z.Outline()
        o.NewOutline()
        for x, y in pts:
            o.Append(int(x * 1e6), int(y * 1e6))
        if name:
            z.SetZoneName(name)
        b.Add(z)
        return z

    zone(pcbnew.F_Cu, [(0, 0), (40, 0), (40, 40), (0, 40)])
    zone(pcbnew.In1_Cu, [(0.5, 0.5), (39.5, 0.5), (39.5, 39.5), (0.5, 39.5)])
    zone(pcbnew.In2_Cu, [(0, 0), (20, 0), (20, 40), (0, 40)])
    grouped = zone(pcbnew.In2_Cu, [(0, 0), (39, 0), (39, 39), (0, 39)], "cell zone")
    g = pcbnew.PCB_GROUP(b)
    g.SetName("a_cell")
    b.Add(g)
    g.AddItem(grouped)

    path = tmp_path / "planes.kicad_pcb"
    b.Save(str(path))
    return path


@needs_kicad
def test_plane_zones_off_a_real_board_drop_only_the_inner_whole_plane(tmp_path):
    from placemat.kicad.route import _plane_zones
    pcb = _synthetic_plane_board(tmp_path)
    zones, board_area = _plane_zones(str(pcb))
    assert plane_layers(zones, board_area, 0.9) == ["In1.Cu"]
