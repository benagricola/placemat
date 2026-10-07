import pytest

from fixtures.reference import lint


def _lint(tmp_path, source, fixed=()):
    s = tmp_path / "s.py"
    s.write_text(source)
    return lint.lint(s, fixed=fixed)


def _problems(tmp_path, source, fixed=()):
    return [(p.line, p.rule, p.ref) for p in _lint(tmp_path, source, fixed).problems]


def test_a_coordinate_on_a_part_not_listed_as_fixed_fails_with_its_line(tmp_path):
    s = tmp_path / "s.py"
    s.write_text('board.place(Part("j1"), at=Location(10, 20), why="mechanical: connector at the edge")\n'
                 'board.place(Part("r1"), at=Location(30, 20), why="mechanical: no")\n')
    r = lint.lint(s, fixed={"j1"})
    assert [(p.line, p.rule, p.ref) for p in r.problems] == [(2, "coordinate", "r1")]


def test_a_why_without_a_basis_is_flagged(tmp_path):
    s = tmp_path / "s.py"
    s.write_text('board.place(Part("c1"), at=Beside(Part("u1"), 3), why="close to U1")\n')
    assert [p.rule for p in lint.lint(s, fixed=()).problems] == ["basis"]


def test_priority_is_steering(tmp_path):
    s = tmp_path / "s.py"
    s.write_text('board.place(Part("u1"), priority=Priority.HIGH, why="datasheet: x")\n')
    assert "steering" in [p.rule for p in lint.lint(s, fixed=()).problems]


# The forms placemat's scripts really use (skills/placemat/references/api.md, "Placement").

def test_a_clean_script_has_no_problems_and_lists_declarations_by_basis(tmp_path):
    r = _lint(tmp_path,
              'board.place(Part("j1"), at=Location(10, 20), rotation=90, why="mechanical: edge connector")\n'
              'board.place(Part("c1"), at=Beside(Part("u1"), Edge.EAST, align=Along.MID), why="datasheet: bypass at VIN")\n'
              'board.place(Part("u1"), why="capture: the MCU")\n'
              'board.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), limit_mm=2.0, why="physics: 2 mm loop")\n',
              fixed={"J1"})
    assert r.problems == []
    assert [(d.line, d.call, d.refs, d.basis, d.coordinate) for d in r.declarations] == [
        (1, "place", ("j1",), "mechanical", True),
        (2, "place", ("c1",), "datasheet", False),
        (3, "place", ("u1",), "capture", False),
        (4, "link", (), "physics", False)]


def test_a_part_with_no_why_is_flagged(tmp_path):
    assert _problems(tmp_path, 'board.place(Part("u1"))\n') == [(1, "no_why", "u1")]


@pytest.mark.parametrize("call", [
    'board.link(PadRef(Part("c1"), 1), PadRef(Part("u1"), 2))',
    'board.track(Net("VIN"), [PadRef(Part("c1"), 1), PadRef(Part("u1"), 2)], layer=CopperLayer.F_CU)',
    'board.via(Net("GND"), at=PadRef(Part("c1"), 2))',
    'board.pour(Net("GND"), [PadRef(Part("c1"), 2)], layer=CopperLayer.B_CU)',
    'board.keepout(Part("ant"), "antenna")',
])
def test_a_link_or_copper_call_with_no_why_is_flagged(tmp_path, call):
    assert [p.rule for p in _lint(tmp_path, call + "\n").problems] == ["no_why"]


@pytest.mark.parametrize("at", [
    "Location(10, 20)", "Location(-3.5, None)", "Centre(30, 12, coordinates=True)", "Centre(30, None, coordinates=True)",
    "Pin(1, 4, 5)", "Pin(1, Location(4, 5))", "Centre(X(Part(\"u1\"), 3.4), Y(PadRef(Part(\"u1\"), 1)))",
    "OnEdge(Edge.WEST, along=12.5)", "OnEdge(Edge.WEST, along=Fraction(0.3))", "(10, 20)",
    "fig.point(1.2, 3.4)", "Pin(1, PadRef(Part(\"u1\"), 3).local(0.4, -1.2))",
])
def test_every_coordinate_form_is_flagged_on_a_part_not_listed_as_fixed(tmp_path, at):
    assert _problems(tmp_path, 'board.place(Part("r1"), at=%s, why="mechanical: x")\n' % at) == [(1, "coordinate", "r1")]


@pytest.mark.parametrize("at", [
    "Beside(Part(\"u1\"), Edge.EAST)", "Beside(Part(\"u1\"), Edge.EAST, gap=0.5, align=Along.MID)",
    "OnEdge(Edge.NORTH)", "OnEdge(Edge.WEST, along=Along.MID)", "Centre(X(Mid(PadRef(Part(\"u1\"), 1), PadRef(Part(\"u1\"), 2))), None)",
    "Centre(X(PadRef(Part(\"u1\"), 1)), Y(PadRef(Part(\"u1\"), 1)))", "Pin(1, PadRef(Part(\"u1\"), 3, edge=Edge.EAST))",
    "Polar(Fraction, None, about=centre)",
])
def test_intent_forms_are_not_coordinates(tmp_path, at):
    assert _problems(tmp_path, 'board.place(Part("r1"), at=%s, why="mechanical: x")\n' % at) == []


def test_a_coordinate_on_a_fixed_part_passes_whatever_its_form_and_the_case_of_the_reference(tmp_path):
    src = ('board.place(Part("J1"), at=Centre(30, 12, coordinates=True), why="mechanical: x")\n'
           'board.place(Part("h1"), at=Pin(1, 3, 4), why="mechanical: hole")\n')
    assert _problems(tmp_path, src, fixed=["j1", "H1"]) == []


def test_a_coordinate_reached_through_a_variable_is_followed(tmp_path):
    src = 'J1_AT = Location(10, 20)\nboard.place(Part("j1"), at=J1_AT, why="mechanical: x")\nboard.place(Part("r1"), at=J1_AT, why="mechanical: x")\n'
    assert _problems(tmp_path, src, fixed={"j1"}) == [(3, "coordinate", "r1")]


def test_a_row_names_each_part_and_flags_each_one_not_fixed(tmp_path):
    src = 'board.row([Part("d1"), Part("d2")], Edge.SOUTH, of=Part("u1"), start=Location(3, 4), why="mechanical: x")\n'
    assert _problems(tmp_path, src, fixed={"d1"}) == [(1, "coordinate", "d2")]


def test_a_cell_is_named_by_its_cell_name(tmp_path):
    assert _problems(tmp_path, 'board.place(Cell("mcu"), at=Location(1, 2), why="mechanical: x")\n') == [(1, "coordinate", "mcu")]


@pytest.mark.parametrize("why", ['"close to U1"', '""', '"Mechanical: x"', '" mechanical: x"', "reason"])
def test_a_why_that_does_not_start_with_a_basis_is_flagged(tmp_path, why):
    assert [p.rule for p in _lint(tmp_path, 'board.place(Part("c1"), why=%s)\n' % why).problems] == ["basis"]


@pytest.mark.parametrize("why", ['"mechanical: a"', '"datasheet: U1 p4 figure 2"', '"physics: x"', '"capture: Pm.Near"',
                                 '"datasheet: " + page', 'f"capture: {x}"', '("physics: a "\n "and b")'])
def test_each_basis_prefix_is_accepted(tmp_path, why):
    assert _problems(tmp_path, 'board.place(Part("c1"), why=%s)\n' % why) == []


@pytest.mark.parametrize("fragment", [
    'priority=Priority.LOW', 'priority=Priority.HIGH', 'at=Near(PadRef(Part("u1"), 1))',
    'at=Near(Location(1, 2), radius=3)', 'order=2'])
def test_steering_forms_are_flagged_even_with_a_basis(tmp_path, fragment):
    got = [p.rule for p in _lint(tmp_path, 'board.place(Part("c1"), %s, why="datasheet: x")\n' % fragment, fixed={"c1"}).problems]
    assert "steering" in got


def test_an_order_call_is_steering(tmp_path):
    assert [p.rule for p in _lint(tmp_path, 'board.order(Part("a"), Part("b"), why="datasheet: x")\n').problems] == ["steering"]


def test_priority_outside_a_declaration_is_steering(tmp_path):
    assert [p.rule for p in _lint(tmp_path, 'P = Priority.HIGH\n').problems] == ["steering"]


def test_a_script_that_does_not_parse_is_a_problem(tmp_path):
    assert [(p.line, p.rule) for p in _lint(tmp_path, 'x = 1\nboard.place(\n').problems] == [(2, "syntax")]


def test_the_script_is_read_not_run(tmp_path):
    marker = tmp_path / "ran"
    _lint(tmp_path, 'open(%r, "w")\nboard.place(Part("u1"), why="capture: x")\n' % str(marker))
    assert not marker.exists()


def test_a_missing_board_folder_is_a_clear_error(tmp_path):
    with pytest.raises(lint.LintError, match="no-such-board"):
        lint.find_script("no-such-board", boards_dir=tmp_path)


def test_the_script_of_a_board_is_found_in_its_folder(tmp_path):
    (tmp_path / "b1").mkdir()
    (tmp_path / "b1" / "b1_layout.py").write_text("")
    assert lint.find_script("b1", boards_dir=tmp_path) == tmp_path / "b1" / "b1_layout.py"


def test_a_folder_with_no_script_or_two_is_a_clear_error(tmp_path):
    (tmp_path / "b1").mkdir()
    with pytest.raises(lint.LintError, match="b1"):
        lint.find_script("b1", boards_dir=tmp_path)
    (tmp_path / "b1" / "a.py").write_text("")
    (tmp_path / "b1" / "b.py").write_text("")
    with pytest.raises(lint.LintError, match="b1"):
        lint.find_script("b1", boards_dir=tmp_path)


def test_main_exits_1_on_a_problem_and_0_when_clean(tmp_path, capsys):
    d = tmp_path / "b1"
    d.mkdir()
    (d / "b1_layout.py").write_text('board.place(Part("u1"), why="capture: x")\n')
    assert lint.main(["b1", "--boards-dir", str(tmp_path), "--fixed", ""]) == 0
    assert "capture" in capsys.readouterr().out
    (d / "b1_layout.py").write_text('board.place(Part("u1"), priority=Priority.HIGH, why="x")\n')
    assert lint.main(["b1", "--boards-dir", str(tmp_path), "--fixed", ""]) == 1
    out = capsys.readouterr().out
    assert "steering" in out and "basis" in out


def test_main_names_an_unknown_board_and_exits_1(capsys):
    assert lint.main(["no-such-board"]) == 1
    assert "no-such-board" in capsys.readouterr().out


def test_a_bare_call_named_like_an_order_call_does_not_crash(tmp_path):
    assert _problems(tmp_path, 'before(1)\nafter()\norder()\n') == []


def test_a_figure_needs_a_datasheet_basis(tmp_path):
    ok = 'fig = board.figure(at=Location(1, 2), why="datasheet: ant p3 fig 2")\n'
    assert _problems(tmp_path, ok) == []
    for why in ('"mechanical: x"', '"fig"', "reason"):
        assert [p[1] for p in _problems(tmp_path, 'fig = board.figure(at=Location(1, 2), why=%s)\n' % why)] == ["basis"]


@pytest.mark.parametrize("call", [
    'board.track(Net("A"), [Location(1, 2), PadRef(Part("u1"), 1)], layer=L, why="physics: x")',
    'board.via(Net("A"), at=Location(1, 2), why="physics: x")',
    'board.pour(Net("A"), [Location(1, 2), Location(3, 4)], layer=L, why="physics: x")',
    'board.push(Part("u2"), from_=Location(1, 2), falloff=3, reference=(1, 1), limit=1, why="physics: x")',
])
def test_a_coordinate_in_copper_or_a_push_is_a_problem_even_for_a_fixed_part(tmp_path, call):
    assert [(p.rule, p.ref) for p in _lint(tmp_path, call + "\n", fixed={"u2", "u1"}).problems] == [("coordinate", "")]
