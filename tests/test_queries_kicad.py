"""The occupancy queries against pcbnew: the rules they need, read off a real
board, and a spot the search chose that KiCad's DRC accepts."""
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad]


@needs_breakout
def test_the_board_hole_rules_are_read(breakout_pcb):
    import pcbnew
    from placemat.kicad.read import read_board
    ds = pcbnew.LoadBoard(str(breakout_pcb)).GetDesignSettings()
    g = read_board(breakout_pcb)
    assert abs(g.hole_to_hole - pcbnew.ToMM(ds.m_HoleToHoleMin)) < 1e-6
    assert abs(g.hole_clearance - pcbnew.ToMM(ds.m_HoleClearance)) < 1e-6


def test_a_via_reads_its_drill(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    b = pcbnew.CreateEmptyBoard()
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(10), pcbnew.FromMM(10)))
    v.SetWidth(pcbnew.FromMM(0.6))
    v.SetDrill(pcbnew.FromMM(0.3))
    b.Add(v)
    p = tmp_path / "v.kicad_pcb"
    b.Save(str(p))
    (via,) = [c for c in read_board(p).copper if c.kind == "via"]
    assert abs(via.drill_mm - 0.3) < 1e-6


@needs_breakout
def test_via_near_returns_a_spot_kicads_drc_accepts(breakout_pcb, tmp_path):
    """The search's answer is only worth having if KiCad agrees with it."""
    import json
    import shutil
    import pcbnew
    from placemat.cli import main
    from placemat.kicad.drc import run_drc
    from placemat.kicad.read import read_board
    pcb = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, pcb)
    shutil.copy(breakout_pcb.with_suffix(".kicad_pro"), tmp_path / "layout.kicad_pro")
    g = read_board(pcb)
    fp = next(f for f in g.footprints if f.pads and any(p.net == "GND" for p in f.pads))
    pad = next(p for p in fp.pads if p.net == "GND")
    import io, contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["occupancy", str(pcb), "--via-near", "%s.%s" % (fp.inst, pad.number), "--json"]) == 0
    spot = json.loads(out.getvalue())["spot"]
    before = run_drc(pcb, tmp_path / "before.json").real
    b = pcbnew.LoadBoard(str(pcb))
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(spot["at"][0]), pcbnew.FromMM(spot["at"][1])))
    v.SetWidth(pcbnew.FromMM(g.netclasses["GND"].via_diameter))
    v.SetDrill(pcbnew.FromMM(g.netclasses["GND"].via_drill))
    v.SetNet(b.FindNet("GND"))
    b.Add(v)
    b.Save(str(pcb))
    after = run_drc(pcb, tmp_path / "after.json").real
    assert after == before, "the via the search chose broke a rule: %s -> %s" % (before, after)


@needs_breakout
def test_at_names_what_is_under_a_point(breakout_pcb, capsys):
    from placemat.cli import main
    from placemat.kicad.read import read_board
    g = read_board(breakout_pcb)
    pad = next(p for fp in g.footprints for p in fp.pads if p.net)
    c = pad.box.center
    assert main(["occupancy", str(breakout_pcb), "--at", "%.3f,%.3f" % (c.x, c.y)]) == 0
    assert pad.net in capsys.readouterr().out


@needs_breakout
def test_via_near_an_smd_pad_lands_beside_it_and_drc_accepts(breakout_pcb, tmp_path):
    """The common case: an SMD pad, whose own centre passes every rule."""
    import contextlib
    import io
    import json
    import shutil
    import pcbnew
    from placemat.cli import main
    from placemat.kicad.drc import run_drc
    from placemat.kicad.read import read_board
    pcb = tmp_path / "layout.kicad_pcb"
    shutil.copy(breakout_pcb, pcb)
    shutil.copy(breakout_pcb.with_suffix(".kicad_pro"), tmp_path / "layout.kicad_pro")
    g = read_board(pcb)
    fp, pad = next((f, p) for f in g.footprints for p in f.pads if p.net and not p.through)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["occupancy", str(pcb), "--via-near", "%s.%s" % (fp.inst, pad.number), "--json"]) == 0
    doc = json.loads(out.getvalue())
    x, y = doc["spot"]["at"]
    assert doc["spot"]["distance"] > 0          # beside the pad, not in it
    before = run_drc(pcb, tmp_path / "before.json").real
    b = pcbnew.LoadBoard(str(pcb))
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    v.SetWidth(pcbnew.FromMM(doc["size"]))
    v.SetDrill(pcbnew.FromMM(doc["drill"]))
    v.SetNet(b.FindNet(pad.net))
    b.Add(v)
    b.Save(str(pcb))
    assert run_drc(pcb, tmp_path / "after.json").real == before
