"""`placemat drc` names each violation: its kind, severity, description and
the items it is between, each with where it is."""
from placemat.kicad.drc import violation_items
from tests.conftest import needs_breakout, needs_kicad


def test_each_counted_violation_is_listed_with_its_items_and_places():
    data = {"violations": [
        {"type": "clearance", "severity": "error", "description": "Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.1500 mm)",
         "items": [{"description": "Track [SDA] on F.Cu, length 3.0000 mm", "pos": {"x": 10.5, "y": 20.25}},
                   {"description": "Pad 3 [SCL] of U7 on F.Cu", "pos": {"x": 10.7, "y": 20.3}}]},
        {"type": "items_not_allowed", "severity": "error", "description": "Items not allowed (keepout area 'keepout antenna')",
         "items": [{"description": "Footprint U3", "pos": {"x": 1, "y": 2}}]},
    ]}
    items = violation_items(data, {"keepout antenna": ({"U3"}, set())})        # U3 is let in: not listed
    assert items == [{"kind": "clearance", "severity": "error",
                      "description": "Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.1500 mm)",
                      "items": [{"description": "Track [SDA] on F.Cu, length 3.0000 mm", "at": [10.5, 20.25]},
                                {"description": "Pad 3 [SCL] of U7 on F.Cu", "at": [10.7, 20.3]}]}]


def test_the_open_connections_are_listed_by_net():
    from placemat.kicad.drc import unconnected_items
    data = {"unconnected_items": [
        {"type": "unconnected_items", "description": "Missing connection between items",
         "items": [{"description": "Pad 1 [VBUS] of J1 on F.Cu", "pos": {"x": 5, "y": 6}},
                   {"description": "Pad 2 [VBUS] of C3 on F.Cu", "pos": {"x": 8, "y": 6}}]}]}
    assert unconnected_items(data) == [{"net": "VBUS", "items": [
        {"description": "Pad 1 [VBUS] of J1 on F.Cu", "at": [5, 6]},
        {"description": "Pad 2 [VBUS] of C3 on F.Cu", "at": [8, 6]}]}]


@needs_kicad
@needs_breakout
def test_the_drc_command_lists_the_items(breakout_pcb, tmp_path, capsys):
    import json
    import shutil
    from placemat import cli
    for ext in (".kicad_pcb", ".kicad_pro"):
        if breakout_pcb.with_suffix(ext).exists():
            shutil.copy(breakout_pcb.with_suffix(ext), tmp_path / ("layout" + ext))
    cli.main(["drc", str(tmp_path / "layout.kicad_pcb"), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert "violations" in data and "unconnected_items" in data
    assert all({"kind", "severity", "description", "items"} <= set(v) for v in data["violations"])
    assert sum(1 for v in data["violations"]) == sum(data["by_type"].values())
