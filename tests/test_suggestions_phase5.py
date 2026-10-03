"""The levers phase 5 enables: the frame's size, the web, a row member or a satellite on its own, a Centre's free line."""
from placemat import suggestions as sg
from placemat.findings import FindingCause as C
from tests.fixtures import footprint
from tests.suggest_support import apply_and_resolve, resolve

IMPORTS = ("from placemat import (board, Axis, Centre, Cutout, Edge, Location, PadRef, Part, Slot, X, Y)\n")


def of(plan, cause):
    return [f for f in plan.findings if f.cause is cause]


def lever(f, name):
    return [s for s in f.suggestions if s.lever == name]


def test_a_part_past_a_fit_frames_declared_width_offers_the_width_that_holds_it(tmp_path):
    body = 'board.rect(width=30, fit=Axis.Y, draw=False)\nboard.place(Part("c1"), at=Location(40, 40))\n'
    board, plan, path = resolve(tmp_path, body, imports=IMPORTS)
    (f,) = of(plan, C.SETUP_FRAME_REACH)
    (s,) = lever(f, "frame")
    assert s.text == "Make the board's width 42.10 mm" and s.edits[0].target.kind == "rect"
    shown = sg.apply_suggestion([s], s.id, dry_run=True).files[str(path)].after
    assert "BOARD_WIDTH_MM = 42.1" in shown and "board.rect(width=BOARD_WIDTH_MM, fit=Axis.Y, draw=False)" in shown
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not of(plan2, C.SETUP_FRAME_REACH)


def test_a_web_under_the_minimum_offers_the_web_the_board_has(tmp_path):
    body = ('board.rect(60, 40, web=1.0, holes=[Cutout(Slot(8, 2), "slot", at=Location(30, 1.9))])\n'
            'board.place(Part("c1"), at=Location(40, 30))\n')
    board, plan, path = resolve(tmp_path, body, imports=IMPORTS)
    fs = of(plan, C.SETUP_WEB)
    assert fs, [str(f) for f in plan.findings]
    (s,) = lever(fs[0], "web")
    assert s.text.startswith("Lower the web minimum to ") and s.edits[0].target.kind == "rect"
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not of(plan2, C.SETUP_WEB)


ROW_PARTS = [footprint("C1", 20, 20, inst="c1", nets=("A", "B")), footprint("C4", 30, 20, inst="c4", nets=("A", "B")),
             footprint("R1", 40, 20, w=80, h=3, inst="r1", nets=("A", "B"))]


def test_a_row_member_that_does_not_fit_is_taken_out_of_the_row_and_left_to_the_search(tmp_path):
    body = 'board.row([Part("c1"), Part("c4"), Part("r1")], Edge.NORTH)\n'
    board, plan, path = resolve(tmp_path, body, parts=ROW_PARTS, imports=IMPORTS)
    (f,) = of(plan, C.FIXED_PART)
    (s,) = lever(f, "row")
    assert s.text == "Take r1 out of the row and let it be searched" and len(s.edits) == 2
    assert len(s.digests) == 1
    sg.apply_suggestion([s], s.id, root=tmp_path, log=tmp_path / "applied.jsonl")
    text = path.read_text()
    assert 'board.row([Part("c1"), Part("c4")], Edge.NORTH)' in text and text.rstrip().endswith('board.place(Part("r1"))')
    sg.undo_last(tmp_path / "applied.jsonl", root=tmp_path)
    assert 'board.row([Part("c1"), Part("c4"), Part("r1")], Edge.NORTH)' in path.read_text()


BLOCK_PARTS = [footprint("U1", 30, 30, w=6, h=3, inst="ldo", nets=("VIN", "VOUT")),
               footprint("C1", 60, 60, inst="ca", nets=("VIN", "GND")),
               footprint("C2", 60, 65, inst="cb", nets=("VIN", "GND"))]


def test_a_satellite_that_the_block_cannot_lay_out_is_taken_out_and_placed_on_its_own(tmp_path):
    body = ('blk = board.block(Part("ldo"), satellites=[(Part("ca"), "VIN"), (Part("cb"), "VIN")])\n'
            'board.place(blk, at=Location(30, 40))\n')
    board, plan, path = resolve(tmp_path, body, parts=BLOCK_PARTS, imports=IMPORTS)
    fs = [f for f in of(plan, C.UNPLACED_BLOCK)] + [f for f in of(plan, C.FIXED_PART)]
    row = [s for f in fs for s in lever(f, "satellite")]
    assert row, [(f.cause.value, str(f)) for f in plan.findings]
    s = row[0]
    assert s.text == "Place cb on its own, not as a satellite of ldo" and len(s.edits) == 2
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path, parts=BLOCK_PARTS)
    assert 'satellites=[(Part("ca"), "VIN")]' in path.read_text() and 'board.place(Part("cb"))' in path.read_text()


def test_an_item_pinned_on_both_axes_by_references_may_slide_along_either_line(tmp_path):
    parts = [footprint("C1", 20, 20, inst="c1", nets=("A", "B")), footprint("C4", 30, 20, inst="c4", nets=("A", "B"))]
    body = ('board.place(Part("c1"), at=Location(20, 20))\n'
            'board.place(Part("c4"), at=Centre(X(PadRef(Part("c1"), 1)), Y(PadRef(Part("c1"), 1))))\n')
    board, plan, path = resolve(tmp_path, body, parts=parts, imports=IMPORTS)
    (f,) = of(plan, C.FIXED_PART)
    slides = lever(f, "slide")
    assert [s.text for s in slides] == ["Let c4 slide along its x line", "Let c4 slide along its y line"]
    assert slides[0].edits[0].args["into"] == [{"kw": "at"}] and slides[0].edits[0].op == "set_arg"
    board2, plan2 = apply_and_resolve(tmp_path, plan, slides[0].id, path, parts=parts)
    assert not of(plan2, C.FIXED_PART) and plan2.placement("c4") is not None
    assert "Centre(X(PadRef(Part(\"c1\"), 1)), None)" in path.read_text()


def test_a_coordinate_centre_is_never_offered_a_slide(tmp_path):
    parts = [footprint("C1", 20, 20, inst="c1", nets=("A", "B")), footprint("C4", 30, 20, inst="c4", nets=("A", "B"))]
    body = ('board.place(Part("c1"), at=Location(20, 20))\n'
            'board.place(Part("c4"), at=Centre(20, 20, coordinates=True))\n')
    board, plan, path = resolve(tmp_path, body, parts=parts, imports=IMPORTS)
    (f,) = of(plan, C.FIXED_PART)
    assert not lever(f, "slide")
