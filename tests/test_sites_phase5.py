"""Sites for the outline (rect, disc, outline), a row and a block: a suggestion can bind to and edit them."""
from placemat import script_edit as se, suggestions as sg
from placemat.context import run_script
from placemat.suggestions import Edit, Target
from tests.suggest_support import IMPORTS, make_board, script

OUT = "from placemat import board, Cutout, Edge, Location, OnEdge, PadRef, Part, Slot\n"


def run(tmp_path, body, imports=OUT, **kw):
    path = script(tmp_path, body, imports=imports)
    board = make_board(**kw)
    board.script_file = str(path)
    run_script(path, board)
    return board, path


def test_a_rect_disc_and_outline_record_where_the_script_declared_them(tmp_path):
    board, path = run(tmp_path, "board.rect(60, 40)\n")
    (site,) = board.sites_of("rect", "board")
    assert site.file == str(path) and site.line == 3
    board, path = run(tmp_path, "board.disc(50)\n")
    assert len(board.sites_of("disc", "board")) == 1
    board, path = run(tmp_path, "board.outline([(0, 0), (60, 0), (60, 40), (0, 40)])\n")
    assert len(board.sites_of("outline", "board")) == 1


def test_a_row_is_keyed_by_its_first_member_and_a_block_by_its_anchor(tmp_path):
    body = ('board.rect(60, 60)\n'
            'board.row([Part("c1"), Part("c4")], Edge.NORTH)\n'
            'board.block(Part("u1"), [(Part("c1"), "VIN")])\n')
    board, path = run(tmp_path, body)
    assert [s.key for s in board.sites_of("row", "c1")] == ["c1"]
    assert len(board.sites_of("block", "u1")) == 1


def test_an_edit_to_the_rect_binds_and_changes_its_size_and_nothing_else(tmp_path):
    board, path = run(tmp_path, "board.rect(60, 40)  # the board\nboard.place(Part(\"c1\"), at=Location(10, 10))\n")
    binder = sg._Binder(board)
    edit = binder.bind_edit(Edit("set_arg", Target("rect", "board"), {"index": 0}, {"num": 80}))
    assert edit is not None and edit.target.line == 3
    out = se.apply_edits([edit], board._source_text)[str(path)][1]
    assert "board.rect(80, 40)  # the board" in out and out.count("\n") == path.read_text().count("\n")


def test_a_rect_given_by_keyword_takes_a_hole_added(tmp_path):
    board, path = run(tmp_path, "board.rect(width=60, height=40)\n")
    edit = Edit("edit_list", Target("rect", "board"), {"arg": "holes", "action": "add", "create": True},
                {"form": "Cutout", "args": [{"form": "Slot", "args": [{"num": 8}, {"num": 2}]}, {"str": "slot"}],
                 "kwargs": {"at": {"form": "Location", "args": [{"num": 30}, {"num": 20}]}}})
    bound = sg._Binder(board).bind_edit(edit)
    out = se.apply_edits([bound], board._source_text)[str(path)][1]
    assert 'holes=[Cutout(Slot(8, 2), "slot", at=Location(30, 20))]' in out


def test_two_outline_declarations_are_not_an_edit_target(tmp_path):
    board, path = run(tmp_path, "board.rect(60, 40)\nboard.rect(70, 50)\n")
    assert sg._Binder(board).target(Target("rect", "board")) is None


def test_a_member_of_a_row_is_taken_out_of_it(tmp_path):
    board, path = run(tmp_path, 'board.rect(60, 60)\nboard.row([Part("c1"), Part("c4")], Edge.NORTH)\n')
    edit = sg._Binder(board).bind_edit(Edit("edit_list", Target("row", "c1"), {"arg": 0, "action": "remove"},
                                            {"form": "Part", "args": [{"str": "c4"}]}))
    out = se.apply_edits([edit], board._source_text)[str(path)][1]
    assert 'board.row([Part("c1")], Edge.NORTH)' in out
