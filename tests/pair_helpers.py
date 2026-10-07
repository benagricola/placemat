import json
from pathlib import Path

NETS = ("A_P", "A_N", "B_P", "B_N")

def _router(tmp_path) -> Path:
    router = tmp_path / "router"
    (router / "py_router").mkdir(parents=True)
    (router / "py_router/route_diff.py").write_text("")
    return router


def _board(tmp_path) -> Path:
    """A four-layer board with two parts, each with a pad per net of two pairs and one for a single net (the main pass
    has a net to route), and a project giving each pair a pair class."""
    pads = list(zip(NETS + ("SIG",), (-1.2, -0.4, 1.2, 2.0, 4.0)))

    def part(ref, x, y):
        body = "".join('\t\t(pad "%d" smd rect (at %g 0) (size 0.4 1.2) (layers "F.Cu" "F.Mask") (net "%s"))\n'
                       % (i + 1, at, net) for i, (net, at) in enumerate(pads))
        return ('\t(footprint "t:conn" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n%s\t)\n' % (x, y, ref, body))
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)\n\t\t(2 "B.Cu" signal)\n'
                   '\t\t(25 "Edge.Cuts" user)\n\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n'
                   + "".join('\t(net %d "%s")\n' % (i + 1, n) for i, (n, _) in enumerate(pads))
                   + part("J1", 110, 108) + part("J2", 130, 120)
                   + '\t(gr_rect (start 100 100) (end 140 128) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n)\n')
    pro = {"meta": {"filename": "board.kicad_pro", "version": 3},
           "net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.15},
                                        {"name": "Fast", "clearance": 0.15, "track_width": 0.15,
                                         "diff_pair_gap": 0.2, "diff_pair_width": 0.2},
                                        {"name": "Slow", "clearance": 0.15, "track_width": 0.15,
                                         "diff_pair_gap": 0.2, "diff_pair_width": 0.2}],
                            "netclass_assignments": {"A_P": ["Fast"], "A_N": ["Fast"], "B_P": ["Slow"], "B_N": ["Slow"]}}}
    pcb.with_suffix(".kicad_pro").write_text(json.dumps(pro))
    return pcb


