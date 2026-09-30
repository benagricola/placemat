"""A net class makes pairs only when it sets its own diff-pair width and
gap. KiCad reports its default pair figures on every class, so a class of
two nets that sets none (a pair of control lines at their own width) is
not a pair."""
from tests.conftest import needs_kicad


def _board(path):
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    for k, name in enumerate(("P_A", "P_B", "C_1", "C_2")):
        net = pcbnew.NETINFO_ITEM(b, name)
        b.Add(net)
        t = pcbnew.PCB_TRACK(b)                 # something on the net, so the board keeps it
        t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(2), pcbnew.FromMM(2 + k)))
        t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(4), pcbnew.FromMM(2 + k)))
        t.SetWidth(pcbnew.FromMM(0.2))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(net)
        b.Add(t)
    ns = b.GetDesignSettings().m_NetSettings
    pair = pcbnew.NETCLASS("Pair")
    pair.SetTrackWidth(pcbnew.FromMM(0.13))
    pair.SetDiffPairWidth(pcbnew.FromMM(0.13))
    pair.SetDiffPairGap(pcbnew.FromMM(0.15))
    plain = pcbnew.NETCLASS("Plain")
    plain.SetTrackWidth(pcbnew.FromMM(0.25))
    ns.SetNetclass("Pair", pair)
    ns.SetNetclass("Plain", plain)
    for net, cls in (("P_A", "Pair"), ("P_B", "Pair"), ("C_1", "Plain"), ("C_2", "Plain")):
        ns.SetNetclassPatternAssignment(net, cls)
    b.Save(str(path))
    # a class the capture gives no pair figures has them null in the project, as the generator writes it
    import json
    pro = path.with_suffix(".kicad_pro")
    doc = json.loads(pro.read_text())
    for c in doc["net_settings"]["classes"]:
        if c["name"] == "Plain":
            c["diff_pair_width"] = c["diff_pair_gap"] = None
    pro.write_text(json.dumps(doc, indent=2))


@needs_kicad
def test_only_a_class_that_sets_its_pair_figures_makes_a_pair(tmp_path):
    import shutil
    from placemat.kicad.read import read_board
    from placemat.pairs import board_pairs
    made, read = tmp_path / "made", tmp_path / "read"
    made.mkdir()
    _board(made / "layout.kicad_pcb")
    # read from a path pcbnew has not loaded: it keeps a project it saved in memory
    shutil.copytree(made, read)
    g = read_board(read / "layout.kicad_pcb")
    assert g.netclasses["C_1"].diff_pair_width is None and g.netclasses["C_1"].diff_pair_gap is None
    assert g.netclasses["P_A"].diff_pair_width is not None
    assert board_pairs(g.netclasses) == {"P_A": "P_B", "P_B": "P_A"}
