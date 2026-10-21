"""An open connection's end on copper that touches no pad itself, such as the outer leg of an escape lane past its
riser, is named by the pad the copper joins through the copper before it, as KiCad's connectivity joins them; only
copper that joins no pad at all is a loose end at its place."""
import json

from placemat.kicad import phase_run
from tests.conftest import needs_kicad

U1_PAD, J1_PAD = "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000c1"
RISER, LEG, STRAY = "00000000-0000-0000-0000-0000000000e1", "00000000-0000-0000-0000-0000000000e2", \
    "00000000-0000-0000-0000-0000000000e3"


def _board(tmp_path):
    """U1 pad 1 and J1 pad 1 on VB; a riser from U1's pad to (115, 110) and a leg on from there to (120, 110), and a
    stray track of VB that joins nothing. J1 is left open."""
    def part(ref, x, pad_uuid):
        return ('\t(footprint "t:p" (layer "F.Cu") (at %g 110)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (net 1 "VB") '
                '(uuid "%s"))\n\t)\n' % (x, ref, pad_uuid))

    def seg(a, b, uuid):
        return '\t(segment (start %g 110) (end %g 110) (width 0.2) (layer "F.Cu") (net 1) (uuid "%s"))\n' % (a, b, uuid)
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n\t(net 0 "")\n\t(net 1 "VB")\n'
                   + part("U1", 110, U1_PAD) + part("J1", 130, J1_PAD)
                   + seg(110, 115, RISER) + seg(115, 120, LEG) + seg(135, 138, STRAY)
                   + '\t(gr_rect (start 100 100) (end 140 120) (stroke (width 0.1) (type solid)) (fill no) '
                     '(layer "Edge.Cuts"))\n)\n')
    return pcb


def _open(tmp_path, a, b):
    pcb = _board(tmp_path)
    drc = tmp_path / "drc.json"
    drc.write_text(json.dumps({"violations": [], "unconnected_items": [{"items": [a, b]}]}))
    return phase_run.open_connections(pcb, drc)


@needs_kicad
def test_an_end_on_a_lanes_outer_leg_is_named_by_the_pad_its_riser_joins(tmp_path):
    (got,) = _open(tmp_path, {"uuid": LEG, "pos": {"x": 120, "y": 110}}, {"uuid": J1_PAD, "pos": {"x": 130, "y": 110}})
    assert (got["from"], got["to"]) == ({"ref": "J1", "pad": "1"}, {"ref": "U1", "pad": "1"})


@needs_kicad
def test_an_end_on_copper_that_joins_no_pad_is_loose_at_its_place(tmp_path):
    (got,) = _open(tmp_path, {"uuid": STRAY, "pos": {"x": 136.5, "y": 110}},
                   {"uuid": J1_PAD, "pos": {"x": 130, "y": 110}})
    assert got["to"] == {"ref": None, "pad": None, "at": [136.5, 110]}
