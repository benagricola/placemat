"""The reader carries what a part physically claims beyond its courtyard:
stroked silk, mask apertures and the fab body, per face."""
import json

import pytest

from tests.conftest import needs_kicad

MCU = "fixtures/fairing/modules/Mcu/layout/layout.kicad_pcb"


@pytest.fixture
def board(tmp_path):
    """The fixture board with a silk clearance and a mask expansion set, so
    both have something to show."""
    import pcbnew
    b = pcbnew.LoadBoard(MCU)
    ds = b.GetDesignSettings()
    ds.m_SilkClearance = pcbnew.FromMM(0.1)
    ds.m_SolderMaskExpansion = pcbnew.FromMM(0.05)
    out = tmp_path / "board.kicad_pcb"
    b.Save(str(out))
    return out


@needs_kicad
def test_the_silk_clearance_is_read(board):
    from placemat.kicad.read import read_board
    assert read_board(board).silk_clearance == pytest.approx(0.1)


@needs_kicad
def test_silk_is_the_stroked_graphics_and_no_field(board):
    import pcbnew
    from placemat.kicad.read import read_board
    g = read_board(board)
    pb = pcbnew.LoadBoard(str(board))
    checked = 0
    for kfp in pb.GetFootprints():
        graphics = [d for d in kfp.GraphicalItems() if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS)]
        if not graphics:
            continue
        fp = g.footprint(kfp.GetReference())
        from placemat.kicad.read import outlines_of
        assert len(fp.silk) == sum(len(outlines_of(d, d.GetLayer())) for d in graphics)   # graphics only: no field text
        assert any(f.IsVisible() is False or f.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) for f in kfp.GetFields())
        xs = [p[0] for _, poly in fp.silk for p in poly]
        bb = graphics[0].GetBoundingBox()
        assert max(xs) >= pcbnew.ToMM(bb.GetLeft()) - 1e-6          # the stroke is inside what KiCad says it covers
        from placemat.values import Face
        assert all(face in (Face.FRONT, Face.BACK) for face, _ in fp.silk)
        checked += 1
    assert checked > 5


@needs_kicad
def test_a_mask_aperture_is_the_pad_grown_by_its_expansion(board):
    from placemat.kicad.read import read_board
    g = read_board(board)
    fp = next(f for f in g.footprints if f.mask and not any(p.through for p in f.pads))
    pad = fp.pads[0]
    boxes = []
    for face, poly in fp.mask:
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        boxes.append((max(xs) - min(xs), max(ys) - min(ys)))
    assert any(abs(w - (pad.box.width + 0.1)) < 0.01 and abs(h - (pad.box.height + 0.1)) < 0.01 for w, h in boxes)
    assert len(fp.mask) == len(fp.pads)


@needs_kicad
def test_the_body_is_the_box_of_the_fab_graphics(board):
    import pcbnew
    from placemat.kicad.read import read_board
    g = read_board(board)
    pb = pcbnew.LoadBoard(str(board))
    kfp = next(f for f in pb.GetFootprints()
               if any(d.GetLayer() == pcbnew.F_Fab and not isinstance(d, pcbnew.PCB_TEXT) for d in f.GraphicalItems()))
    fp = g.footprint(kfp.GetReference())
    assert len(fp.fab) == 1
    face, poly = fp.fab[0]
    boxes = [d.GetBoundingBox() for d in kfp.GraphicalItems() if d.GetLayer() == pcbnew.F_Fab and not isinstance(d, pcbnew.PCB_TEXT)]
    assert min(p[0] for p in poly) == pytest.approx(min(pcbnew.ToMM(b.GetLeft()) for b in boxes))
    assert max(p[1] for p in poly) == pytest.approx(max(pcbnew.ToMM(b.GetBottom()) for b in boxes))


def test_the_component_spacing_defaults_to_twice_the_courtyard_excess(tmp_path):
    from placemat.project import fab_profile
    (tmp_path / "fab-profile.json").write_text(json.dumps({"courtyard": {"excess_mm": 0.15}}))
    assert fab_profile(tmp_path).component_spacing == pytest.approx(0.3)
    (tmp_path / "fab-profile.json").write_text(json.dumps({"courtyard": {"excess_mm": 0.15, "component_spacing_mm": 0.5}}))
    assert fab_profile(tmp_path).component_spacing == pytest.approx(0.5)
    from placemat.project import FabProfile
    assert FabProfile().component_spacing == pytest.approx(0.2)


@needs_kicad
def test_a_bare_footprint_reads_each_pads_mask_and_paste_layers():
    import glob
    from placemat.kicad.read import read_footprint
    path = sorted(glob.glob("fixtures/mnb/parts/*/*.kicad_mod"))[0]
    fp, _ = read_footprint(path)
    smd = [p for p in fp.pads if not p.through]
    assert smd and all("F.Mask" in p.mask_paste for p in smd)
