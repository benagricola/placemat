"""The forms routing phases replaced are refused, each naming what replaces it."""
import pytest

from placemat.settings import SettingsError, load


@pytest.mark.parametrize("text, names", [
    ('[route]\nislands = ["VB=0.5"]\n', "a phase with `nets` and `width`"),
    ('[route]\npair_layers = {"A/B" = ["F.Cu"]}\n', "a phase with `pairs = true` and `layers`"),
    ('[route.pair_layers]\n"A/B" = ["F.Cu"]\n', "a phase with `pairs = true` and `layers`"),
    ('[route]\nnet_halos = {"SW" = 2.0}\n', "the clearance field of the net's type in the capture"),
    ('[route.net_halos]\nSW = 2.0\n', "the clearance field of the net's type in the capture"),
])
def test_a_removed_route_setting_is_refused_naming_its_replacement(tmp_path, text, names):
    (tmp_path / "placemat.toml").write_text(text)
    with pytest.raises(SettingsError, match="is retired; set " + __import__("re").escape(names)):
        load(tmp_path)


def test_route_islands_is_refused_naming_the_phase_form(capsys):
    from placemat.cli import main
    assert main(["route", "b.kicad_pcb", "--islands", "VB"]) == 2
    assert "[[route.phase]]" in capsys.readouterr().out


def test_no_stage_code_is_left():
    import placemat.kicad.route as r
    import placemat.pairs as p
    for name in ("route_islands", "route_class_stages", "islands_on_board", "island_layers_on_board",
                 "resolve_pair_layers", "pair_layer_groups"):
        assert not hasattr(r, name), name
    assert not hasattr(p, "board_pair_list")
