"""placemat facts: prints the board's facts and, with --confirm, records
their digest in placemat.toml's [facts] confirmed."""
from tests.conftest import needs_kicad


def _board_and_script(tmp_path, fab_profile: bool = False):
    """A minimal board (an empty two-layer .kicad_pcb) and script beside a
    .zen that declares it, the way find_board expects."""
    import json
    import pcbnew
    (tmp_path / "widget.zen").write_text(
        'Board(\n    name = "Widget",\n    layout_path = "layout",\n)\n')
    layout = tmp_path / "layout"
    layout.mkdir()
    pcb = layout / "layout.kicad_pcb"
    board = pcbnew.CreateEmptyBoard()
    board.Save(str(pcb))
    script = tmp_path / "Widget_layout.py"
    script.write_text("")            # no board.plane() calls: nothing declared
    if fab_profile:
        (tmp_path / "fab-profile.json").write_text(json.dumps(
            {"via": {"blind": "yes"}, "min": {"track_mm": 0.09}}))
    return script


@needs_kicad
def test_facts_prints_and_says_unconfirmed(tmp_path, capsys):
    from placemat import cli
    script = _board_and_script(tmp_path)
    rc = cli.main(["facts", str(script)])
    out = capsys.readouterr().out
    assert "layer" in out and "via" in out and "rise" in out
    assert "unconfirmed: no confirmation record yet" in out
    assert rc == 1


@needs_kicad
def test_facts_confirm_writes_placemat_toml(tmp_path, capsys):
    from placemat import cli
    script = _board_and_script(tmp_path, fab_profile=True)
    rc = cli.main(["facts", str(script), "--confirm"])
    assert rc == 0
    toml = (tmp_path / "placemat.toml").read_text()
    assert "[facts]" in toml and "confirmed" in toml
    capsys.readouterr()
    rc2 = cli.main(["facts", str(script)])
    out2 = capsys.readouterr().out
    assert "confirmed" in out2 and "unconfirmed" not in out2.split("\n")[-2]
    assert rc2 == 0
