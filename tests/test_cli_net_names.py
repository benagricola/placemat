import pytest

from placemat.cli import main


@pytest.mark.parametrize("argv", [
    ["route", "board.kicad_pcb", "--exclude", "A B C"],
    ["run", "layout.py", "--route", "--route-exclude", "A B"],
])
def test_a_net_name_holding_spaces_is_refused_as_several_names_in_one_argument(argv, capsys):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert "one argument" in str(e.value) and "A B" in str(e.value)
