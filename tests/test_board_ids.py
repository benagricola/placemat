"""A board whose file names no id for some items (an older KiCad format) gets ids from pcbnew's generator as it
loads. The route's working copies, and the reference set's prepared boards, are loaded with the generator seeded
from the file (write.load_board), so the same input gives the same ids in every run."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

SRC = str(Path(__file__).resolve().parents[1] / "src")
UUID = re.compile(r'^\s*\(uuid "[^"]*"\)\n', re.M)


def _board_without_ids(path):
    """Two footprints with a pad each, a track and a via, saved and then stripped of every uuid."""
    import pcbnew
    from pcbnew import FromMM as mm, VECTOR2I as V
    b = pcbnew.CreateEmptyBoard()
    net = pcbnew.NETINFO_ITEM(b, "A")
    b.Add(net)
    for ref, x in (("R1", 10), ("R2", 20)):
        fp = pcbnew.FOOTPRINT(b)
        fp.SetReference(ref)
        fp.SetPosition(V(mm(x), mm(10)))
        pad = pcbnew.PAD(fp)
        pad.SetNumber("1")
        pad.SetSize(V(mm(1), mm(1)))
        pad.SetPosition(V(mm(x), mm(10)))
        pad.SetLayerSet(pad.SMDMask())
        pad.SetNet(net)
        fp.Add(pad)
        b.Add(fp)
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(V(mm(10), mm(10)))
    t.SetEnd(V(mm(15), mm(10)))
    t.SetWidth(mm(0.25))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(net)
    b.Add(t)
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(V(mm(15), mm(10)))
    v.SetWidth(mm(0.45))
    v.SetDrill(mm(0.2))
    v.SetNet(net)
    b.Add(v)
    b.Save(str(path))
    path.write_text(UUID.sub("", path.read_text()))
    return path


def _in_a_new_process(code, *args):
    subprocess.run([sys.executable, "-c", code, *map(str, args)], check=True, capture_output=True,
                   env=dict(os.environ, PYTHONPATH=SRC))


def test_a_routes_working_copy_gets_the_same_ids_in_every_run(tmp_path):
    board = _board_without_ids(tmp_path / "given.kicad_pcb")
    assert "(uuid" not in board.read_text()
    copies = []
    for i in (1, 2):
        copy = tmp_path / ("in%d.kicad_pcb" % i)
        copy.write_bytes(board.read_bytes())
        _in_a_new_process("import sys; from placemat.kicad.route import lock_copper; lock_copper(sys.argv[1])", copy)
        copies.append(copy.read_text())
    assert "(uuid" in copies[0]
    assert copies[0] == copies[1]


def test_load_board_seeds_from_the_file_so_another_board_draws_other_ids(tmp_path):
    from placemat.kicad.write import file_seed, load_board
    one = _board_without_ids(tmp_path / "one.kicad_pcb")
    two = tmp_path / "two.kicad_pcb"
    two.write_text(one.read_text().replace("(at 15 10)", "(at 16 10)"))
    ids = [sorted(t.m_Uuid.AsString() for t in load_board(p).GetTracks()) for p in (one, one, two)]
    assert ids[0] == ids[1]
    assert not set(ids[0]) & set(ids[2])
    assert file_seed(b"x") == file_seed(b"x") != file_seed(b"y")
