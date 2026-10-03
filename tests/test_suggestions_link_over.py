"""link_over: a link longer than its limit gets suggestions that edit the script and clear the finding."""
from placemat import suggestions as sg
from tests.suggest_support import apply_and_resolve, resolve, suggestions_of

SCRIPT = '''board.place(Part("u1"), at=Location(30, 30))
board.place(Part("c1"), at=Near(Location(45, 45), radius=0.5))   # the cap
board.link(PadRef(Part("c1"), 1), PadRef(Part("u1"), 2), limit_mm=4.0)
board.place(Part("c4"), at=Location(10, 50))
board.place(Part("r1"), at=Location(10, 10))
board.place(Part("j1"), at=Location(50, 10))
'''


def over(plan):
    return [f for f in plan.findings if f.kind == "link_over"]


def test_a_link_over_its_limit_has_ranked_suggestions_bound_to_the_script(tmp_path):
    board, plan, path = resolve(tmp_path, SCRIPT)
    (f,) = over(plan)
    assert f.case == "link_over"
    got = f.suggestions
    assert got and [s.rank for s in got] == list(range(1, len(got) + 1))
    assert [s.id for s in got] == ["s%d%s" % (plan.findings.index(f) + 1, c) for c in "abcdefgh"[:len(got)]]
    texts = [s.text for s in got]
    assert any(t.startswith("Place c1 beside u1, on its") for t in texts)
    assert "Pull c1 pad 1 to u1 pad 2 harder" in texts
    assert "Place c1 before the parts that crowd it" in texts
    assert any(t.startswith("Raise the limit to ") for t in texts)
    for s in got:
        assert s.edit.target.file == str(path) and s.edit.target.line and s.edit.target.digest
        assert s.digests and str(path) in s.digests


def test_applying_a_suggestion_to_the_script_gives_a_script_that_resolves_without_the_finding(tmp_path):
    board, plan, path = resolve(tmp_path, SCRIPT)
    (f,) = over(plan)
    raise_limit = next(s for s in f.suggestions if s.text.startswith("Raise the limit"))
    shown = sg.apply_suggestion(suggestions_of(plan), raise_limit.id, dry_run=True)
    assert "limit_mm=C1_LINK_LIMIT_MM" in shown.files[str(path)].after
    assert "# Measured by a run's finding (link_over)" in shown.files[str(path)].after
    assert path.read_text() == shown.files[str(path)].before          # a dry run writes nothing
    board2, plan2 = apply_and_resolve(tmp_path, plan, raise_limit.id, path)
    assert not over(plan2)
    assert "C1_LINK_LIMIT_MM = " in path.read_text()


def test_weight_and_priority_suggestions_edit_the_declarations_they_name(tmp_path):
    board, plan, path = resolve(tmp_path, SCRIPT)
    (f,) = over(plan)
    by = {s.text: s for s in f.suggestions}
    weight = sg.apply_suggestion(suggestions_of(plan), by["Pull c1 pad 1 to u1 pad 2 harder"].id, dry_run=True)
    assert "limit_mm=4.0, weight=LinkWeight.PREFER" in weight.files[str(path)].after
    prio = sg.apply_suggestion(suggestions_of(plan), by["Place c1 before the parts that crowd it"].id, dry_run=True)
    assert 'board.place(Part("c1"), at=Near(Location(45, 45), radius=0.5), priority=Priority.HIGH)   # the cap' in prio.files[str(path)].after


def test_a_link_declared_in_a_loop_gets_no_suggestion_that_would_edit_it(tmp_path):
    script = '''board.place(Part("u1"), at=Location(30, 30))
board.place(Part("c1"), at=Location(45, 45))
for n in (1, 2):
    board.link(PadRef(Part("c1"), 1), PadRef(Part("u1"), 2), limit_mm=4.0)
board.place(Part("c4"), at=Location(10, 50))
'''
    board, plan, path = resolve(tmp_path, script)
    for f in over(plan):
        assert not [s for s in f.suggestions if s.edit.target.kind == "link"]


def test_a_finding_is_cleared_when_its_kind_case_and_item_are_gone_from_the_next_resolve(tmp_path):
    board, plan, path = resolve(tmp_path, SCRIPT)
    (f,) = over(plan)
    assert not sg.cleared(f, plan.findings)
    assert not sg.cleared(f.detail() | {"item": "link"}, [g.detail() | {"item": "link"} for g in plan.findings])
    raise_limit = next(s for s in f.suggestions if s.text.startswith("Raise the limit"))
    board2, plan2 = apply_and_resolve(tmp_path, plan, raise_limit.id, path)
    assert sg.cleared(f, plan2.findings)


def test_a_builder_or_a_measurement_that_fails_does_not_fail_the_resolve(tmp_path, monkeypatch):
    from placemat import suggest_facts

    def boom(*a, **k):
        raise RuntimeError("a measurement that cannot be taken")
    monkeypatch.setitem(sg.CASES, "link_over", boom)
    board, plan, path = resolve(tmp_path, SCRIPT)
    (f,) = over(plan)
    assert f.suggestions == () and f.startswith("link C1.1")
    monkeypatch.undo()
    monkeypatch.setattr(suggest_facts, "free_sides", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    (tmp_path / "again").mkdir()
    board, plan, path = resolve(tmp_path / "again", SCRIPT)
    (f,) = over(plan)
    assert not [s for s in f.suggestions if s.lever == "beside"] and f.suggestions
