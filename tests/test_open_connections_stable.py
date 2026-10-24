"""A board's open connections are the same whichever ends KiCad's DRC names: KiCad says which nets are open and which
copper is joined, and each open net's islands are joined by their shortest links (kicad/airwires.py), each end the
island's pad nearest the link. Copper that joins no pad is no connection to make."""
import json

from placemat.kicad import phase_run
from tests.conftest import needs_kicad

U11, U12, J11 = ("00000000-0000-0000-0000-0000000000%s" % s for s in ("a1", "a2", "c1"))
TIE, STRAY = "00000000-0000-0000-0000-0000000000e1", "00000000-0000-0000-0000-0000000000e3"


def _board(tmp_path, j1=True):
    """VB: U1 pads 1 (x 110) and 2 (x 112) joined by a track, J1 pad 1 (x 130) on its own (unless not `j1`), and a
    stray VB track (x 135 to 138) that joins nothing."""
    pads = ('\t(footprint "t:p" (layer "F.Cu") (at 110 110)\n\t\t(property "Reference" "U1" (at 0 -2 0) (layer "F.SilkS"))\n'
            '\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "VB") (uuid "%s"))\n'
            '\t\t(pad "2" smd rect (at 2 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "VB") (uuid "%s"))\n\t)\n'
            '\t(footprint "t:p" (layer "F.Cu") (at 130 110)\n\t\t(property "Reference" "J1" (at 0 -2 0) (layer "F.SilkS"))\n'
            '\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "VB") (uuid "%s"))\n\t)\n'
            % (U11, U12, J11))
    if not j1:
        pads = pads[:pads.index('\t(footprint "t:p" (layer "F.Cu") (at 130 110)')]
    seg = '\t(segment (start %g 110) (end %g 110) (width 0.2) (layer "F.Cu") (net 1) (uuid "%s"))\n'
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n\t(net 0 "")\n\t(net 1 "VB")\n'
                   + pads + seg % (110, 112, TIE) + seg % (135, 138, STRAY)
                   + '\t(gr_rect (start 100 100) (end 140 120) (stroke (width 0.1) (type solid)) (fill no) '
                     '(layer "Edge.Cuts"))\n)\n')
    return pcb


def _open(tmp_path, *items, j1=True):
    pcb = _board(tmp_path, j1)
    drc = tmp_path / "drc.json"
    drc.write_text(json.dumps({"violations": [], "unconnected_items": [{"items": list(pair)} for pair in items]}))
    return phase_run.open_connections(pcb, drc)


def _at(uuid, x):
    return {"uuid": uuid, "pos": {"x": x, "y": 110}}


@needs_kicad
def test_the_same_board_gives_the_same_connection_whichever_pad_kicad_names(tmp_path):
    want = [{"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"}}]
    assert _open(tmp_path, (_at(U11, 110), _at(J11, 130))) == want
    assert _open(tmp_path, (_at(U12, 112), _at(J11, 130))) == want
    assert _open(tmp_path, (_at(TIE, 111), _at(J11, 130))) == want


@needs_kicad
def test_copper_that_joins_no_pad_is_no_connection(tmp_path):
    got = _open(tmp_path, (_at(U12, 112), _at(J11, 130)), (_at(STRAY, 136.5), _at(J11, 130)))
    assert got == [{"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"}}]


@needs_kicad
def test_a_net_kicad_calls_open_that_is_one_island_keeps_kicads_items(tmp_path):
    # VB is U1's two joined pads alone: placemat's connectivity finds nothing to join, so KiCad's report stands
    got = _open(tmp_path, (_at(U11, 110), _at(U12, 112)), j1=False)
    assert got == [{"net": "VB", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"}}]


@needs_kicad
def test_two_islands_with_pads_at_one_point_are_joined_pad_to_pad(tmp_path):
    # a front pad and a back pad of VB at one point, not joined: the link between their islands is between the two
    # pads, not from one of them to itself
    front, back = "00000000-0000-0000-0000-0000000000f1", "00000000-0000-0000-0000-0000000000b1"
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(3 "B.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n\t(net 0 "")\n\t(net 1 "VB")\n'
                   '\t(footprint "t:p" (layer "F.Cu") (at 110 110)\n\t\t(property "Reference" "J9" (at 0 -2 0) (layer "F.SilkS"))\n'
                   '\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "VB") (uuid "%s"))\n\t)\n'
                   '\t(footprint "t:q" (layer "B.Cu") (at 110 110)\n\t\t(property "Reference" "U8" (at 0 2 0) (layer "B.SilkS"))\n'
                   '\t\t(pad "11" smd rect (at 0 0) (size 1 1) (layers "B.Cu" "B.Mask") (net 1 "VB") (uuid "%s"))\n\t)\n'
                   '\t(gr_rect (start 100 100) (end 140 120) (stroke (width 0.1) (type solid)) (fill no) '
                   '(layer "Edge.Cuts"))\n)\n' % (front, back))
    drc = tmp_path / "drc.json"
    drc.write_text(json.dumps({"violations": [], "unconnected_items": [{"items": [
        {"uuid": back, "pos": {"x": 110, "y": 110}}, {"uuid": front, "pos": {"x": 110, "y": 110}}]}]}))
    assert phase_run.open_connections(pcb, drc) == [
        {"net": "VB", "from": {"ref": "J9", "pad": "1"}, "to": {"ref": "U8", "pad": "11"}}]
