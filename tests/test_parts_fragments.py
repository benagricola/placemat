"""placemat parts --fragments: the fragment each part was stamped from, read
from the generator's layout log beside the board; "-" for a part the
generator placed itself."""
from placemat.describe import fragment_sources, parts_lines
from tests.fixtures import board_geometry, footprint

LOG = """INFO: Authoritative fragments: ['light', 'radio.receiver']
INFO: OPLOG PLACE_FP_FRAGMENT path=light.u_als.Vendor_Als x=0 y=0 fragment_group=light
INFO: OPLOG PLACE_FP_FRAGMENT path=radio.receiver.u_rx.MAX x=0 y=0 fragment_group=radio.receiver
INFO: OPLOG PLACE_FP path=radio.c_rf.C x=1 y=2 w=3 h=4
"""


def test_each_part_names_the_fragment_it_was_stamped_from(tmp_path):
    log = tmp_path / "layout.log"
    log.write_text(LOG)
    src = fragment_sources(log)
    assert src == {"light.u_als": "light", "radio.receiver.u_rx": "radio.receiver", "radio.c_rf": "-"}


def test_parts_lines_add_the_fragment_column(tmp_path):
    fps = [footprint("U1", 5, 5, inst="light.u_als"), footprint("C1", 9, 5, inst="radio.c_rf"),
           footprint("R1", 13, 5, inst="loose.r1")]
    text = "\n".join(parts_lines(board_geometry(fps), fragments={"light.u_als": "light", "radio.c_rf": "-"}))
    rows = {l.split()[0]: l for l in text.splitlines()[1:-1]}
    assert rows["light.u_als"].rstrip().endswith("light")
    assert rows["radio.c_rf"].rstrip().endswith("-")
    assert rows["loose.r1"].rstrip().endswith("?")          # not in the log
