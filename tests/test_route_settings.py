"""placemat route reads the board's own settings: its placemat.toml's
[route] layers, not the defaults."""
from pathlib import Path


def test_the_route_command_routes_with_the_boards_own_settings(tmp_path, monkeypatch):
    from placemat import cli
    import placemat.kicad.route as route_mod
    from placemat.settings import active
    (tmp_path / "placemat.toml").write_text('[route]\nlayers = ["F.Cu", "B.Cu"]\n')
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    seen = {}

    class Report:
        valid, keepout_breaches, open_nets, routed_pcb = True, [], {}, pcb

        def summary(self):
            return "route: stand-in"

        def as_dict(self):
            return {}

    def stand_in(pcb, work, **kw):
        seen["layers"] = active().route_layers
        return Report()
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb)]) == 0
    assert tuple(seen["layers"]) == ("F.Cu", "B.Cu")
