"""The route step's default layers: signal and mixed layers, F.Cu and B.Cu
always, from each layer's role in the board's stackup - not whether a
plane happens to fill it whole."""
from placemat.kicad.route import plane_note, resolved_layers


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
