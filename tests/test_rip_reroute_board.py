"""Rip and reroute on real boards (pcbnew), no router."""
import shutil

import pytest

from placemat.kicad import rip_reroute as rr
from placemat.kicad.route import copper_items
from tests.conftest import needs_kicad
from tests.test_net_clearance import _two_part_board


def _add_track(pcb, net, a, b, width=0.2, layer="F.Cu"):
    text = pcb.read_text()
    nid = {"SW": 1, "FB": 2, "VIN": 3}[net]
    seg = '\t(segment (start %g %g) (end %g %g) (width %g) (layer "%s") (net %d))\n' % (*a, *b, width, layer, nid)
    pcb.write_text(text.replace("\t(gr_rect", seg + "\t(gr_rect", 1))


@needs_kicad
def test_router_copper_is_what_the_input_board_lacks(tmp_path):
    pytest.importorskip("pcbnew")
    given = _two_part_board(tmp_path)
    script = frozenset(copper_items(given))
    routed = tmp_path / "routed.kicad_pcb"
    shutil.copy(given, routed)
    _add_track(routed, "FB", (110, 110), (125, 110))
    assert rr.router_nets(routed, script) == {"FB": 1}
    assert rr.laid_nets(given, routed) == {"FB"}
