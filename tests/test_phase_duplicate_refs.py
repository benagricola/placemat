"""Two footprints that share a reference: a connection's ends are told apart by the footprint's own identity (KiCad's
footprint uuid), so each is judged on its own copper."""
import json
from dataclasses import replace

from placemat.kicad import phase_run
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

A, B, J = "00000000-0000-0000-0000-00000000000a", "00000000-0000-0000-0000-00000000000b", \
    "00000000-0000-0000-0000-00000000000c"


def _board(tmp_path):
    """Two TP4s and J1, each with pad 1 on VB; a track joins the second TP4 to J1, the first is left open."""
    def part(ref, x, uuid, pad_uuid):
        return ('\t(footprint "t:p" (layer "F.Cu") (uuid "%s") (at %g 110)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "VB") '
                '(uuid "%s"))\n\t)\n' % (uuid, x, ref, pad_uuid))
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n\t(net 0 "")\n\t(net 1 "VB")\n'
                   + part("TP4", 110, A, A[:-2] + "1a") + part("TP4", 120, B, B[:-2] + "1b")
                   + part("J1", 130, J, J[:-2] + "1c")
                   + '\t(segment (start 120 110) (end 130 110) (width 0.4) (layer "F.Cu") (net 1))\n'
                   + '\t(gr_rect (start 100 100) (end 140 120) (stroke (width 0.1) (type solid)) (fill no) '
                     '(layer "Edge.Cuts"))\n)\n')
    return pcb


@needs_kicad
def test_each_footprint_of_a_shared_reference_is_judged_on_its_own_copper(tmp_path):
    pcb = _board(tmp_path)
    drc = tmp_path / "drc.json"
    drc.write_text(json.dumps({"violations": [], "unconnected_items": [
        {"items": [{"uuid": A[:-2] + "1a", "pos": {"x": 110, "y": 110}},
                   {"uuid": J[:-2] + "1c", "pos": {"x": 130, "y": 110}}]}]}))
    (open_one,) = phase_run.open_connections(pcb, drc)
    assert open_one["from"] == {"ref": "J1", "pad": "1"}
    assert open_one["to"] == {"ref": "TP4", "pad": "1", "fp": A}
    joined_one = dict(open_one, to={"ref": "TP4", "pad": "1", "fp": B})
    assert phase_run.joined_pairs(pcb, [(("J1", "1"), ("TP4", "1", A)), (("J1", "1"), ("TP4", "1", B))]) == \
        [False, True]
    obs = [dict(open_one, widths={"F.Cu": 0.4}), dict(joined_one, widths={"F.Cu": 0.4})]
    got = phase_run.judge_obligations(pcb, obs, drc, is_real=lambda _: True)
    assert [j["joined"] for j in got] == [False, True]
    assert got[1] == {"joined": True, "violated": False, "under": {}}


def test_a_joining_path_ends_at_the_footprint_its_end_names():
    from tests.test_route_widths_board import _track
    a = replace(footprint("TP4", 5.6 + 1.0, 10.0, nets=("V", "X")), uuid="fp-a")
    b = replace(footprint("TP4", 5.6 + 1.0, 20.0, nets=("V", "X")), uuid="fp-b")
    j = footprint("J1", 40.0 + 1.4, 10.0, nets=("V", "Y"))
    g = board_geometry([a, b, j], copper=[_track((5.2, 10), (40, 10), 0.5)], width=60, height=30)
    ob = {"net": "V", "from": {"ref": "TP4", "pad": "1", "fp": "fp-a"}, "to": {"ref": "J1", "pad": "1"}}
    assert phase_run.joining_spans(g, ob) is not None
    assert phase_run.joining_spans(g, dict(ob, **{"from": {"ref": "TP4", "pad": "1", "fp": "fp-b"}})) is None
