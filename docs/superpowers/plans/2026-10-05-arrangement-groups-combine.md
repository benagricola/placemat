# Arrangement Groups That Combine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A module's units, declared with `board.unit`, take part in its arrangements with options of their own, combined with every other item and unit in one product; the run reports an option no combination can use, and the author may exclude combinations.

**Architecture:** The pure layer (`arrangements.py`) turns items with options and `board.unit` declarations (kept as the internal `Group` record) into `Unit`s, walks their product in declaration order, skips combinations in which two units move one part, and leaves out the excluded ones, keeping every 0.99.15 id. The board (`layout.py`) gains `board.unit(name, *members)`, `board.alternative(unit, option, *alts)` and `board.exclude(*choices)`, orders the units by where the script declared them, and checks the declarations where the script finishes. The module run (`arrangement_run.py`) records the excluded combinations in `run.json` and raises `arrangement.option_dead` for an option refused in every combination that holds it.

**Tech Stack:** Python 3.12, pcbnew (KiCad 10.0.6 in the checkout's venv), pytest with xdist, node for the studio page tests.

**Spec:** docs/superpowers/specs/2026-10-05-arrangement-groups-combine-design.md (approved 2026-10-05), which amends docs/superpowers/specs/2026-10-04-module-member-variants-design.md (released in 0.99.15).

## Global Constraints

- Required properties: every 0.99.15 id keeps its meaning (a positional `board.arrangement`'s id is its name, an item's option is `item.option`, a combination of items is their pairs in place() order joined by `+`); a module with no units enumerates exactly as before, in the same order; the combinations of a `board.arrangement` (a one-option unit) with the items it does not move are added. `board.group(name, items, why="")` is the KiCad group on the written board and is not changed.
- Decisions this plan takes where the spec is silent or contradicts itself are listed in "Spec gaps and resolutions" at the end; each is confirmed by the user before the task that carries it. The one that changes behaviour most: a `board.arrangement` may still share members with items and other `board.arrangement`s (0.99.15 allowed it), the two units never combining.
- Findings carry structured facts; sentences are rendered only in `finding_text.py` (findings and the console rows of the arrangement record). A function returns records, never a sentence another function parses.
- Tunables are settings with documented defaults, never literals. This change adds no setting; it changes the docs of `place.arrangement_options_max` and `place.arrangements_max` and the default of `place.arrangements_max` (8 to 16, since a unit multiplies the count), and `api.md`'s settings table is regenerated (`PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m placemat settings --markdown`, pasted between the markers).
- ASCII only in code, comments, tests, docs and commit messages: no em or en dashes, no unicode arrows (`->`), straight quotes, `...`.
- Generic wording: code, docs, skill and commit messages never name a project, board, module, part number or net that uses placemat. Fixture folders and their part names may appear in test code only.
- Commit messages carry no reference to Claude, Anthropic or a session and no Co-Authored-By line. After every commit run `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`; it must print nothing.
- Tests run as `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest <tests> -n 2 -p no:cacheprovider -q` from the repository (or worktree) root. Never run `uv run` or `uv sync`.
- Real-board and real-module runs (every test that calls `tests/real_modules.run`, the `--full` suite, the gate's comparison) run one at a time under `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock <command>`. Copies made for a run are removed afterwards.
- CPU light: bench `--jobs 2` at most; never `pkill`, `killall` or a grep-kill; stop only PIDs this session started.
- Bench: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2 | tee /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/bench.out`, every case `same`, the tally lines (`grep -E "^(default|solve|physical):|^seconds:"`) in the commit message of the gate.
- Slow tests (over 2 s) are listed in `tests/slow_tests.txt` in the commit that adds them.

## Review Focus

1. A 0.99.15 module whose `board.arrangement`s share parts with each other or with an item's own alternative (`mirrored` and `rotated` over one pair; a `board.arrangement` over a part that also has `turned`). Expected: it runs without an error, every id it had is still made, and no combination lays two options over one part. Tests: Task 1 `test_units_that_move_one_part_never_combine`, Task 2 `test_a_0_99_15_module_whose_arrangements_share_parts_runs_and_keeps_its_ids`.
2. A KiCad group in a module or board script, `board.group("kept", [Part(...), ...])`, beside `board.unit`. Expected: `board.group` is unchanged, still written as a KiCad group and not refused on a board script, and a KiCad group passed to `board.alternative` fails loudly saying a unit is declared with `board.unit`. Tests: Task 2 `test_board_group_still_writes_a_kicad_group_and_takes_no_option`, `test_a_board_script_may_still_write_a_kicad_group`.
3. A module with many items with options (a large product) and an exclusion over two of them. Expected: the count is exact and immediate; the run does not walk the whole product to count it. Test: Task 1 `test_counting_does_not_walk_the_whole_product`.
4. An exclusion that can never hold: two options of one unit, two units that never combine, or a combination id written as one choice. Expected: an error with the declaration's line and the module's choices, not a silent no-op. Test: Task 2 `test_a_bad_exclusion_is_an_error_with_its_line`.
5. A combination refused where its options are each offered elsewhere; an option whose only other combination is a duplicate; an option whose refused combinations are partly excluded. Expected: no `option_dead` in the first two; in the third, the excluded combination is not counted. Tests: Task 3 `test_a_refused_combination_whose_options_stand_elsewhere_is_no_dead_option`, `test_a_duplicate_is_not_a_refusal_and_an_excluded_combination_does_not_count`.

## File Structure

Modified (what changes in each):

- `src/placemat/arrangements.py` - `GroupOption`, `Group` (members, alternatives, `positional`, `unit_options`, `moves`), `Exclusion`, `Choice`, `Unit`; `units`, `combinations`, `tally`; `enumerate_specs` over units with exclusions; `known_id` and `all_ids` over units. `count`, `picks` and `spec_id` go (replaced; nothing else imports them).
- `src/placemat/layout.py` - `board.unit`, `alternative` on a unit, `exclude`, `_member_key`, `_unit_holding`, `_refuse_taken_unit`, `_unit_order`, `arrangement_units`, `_check_units` in `finish_declarations`, `refuse_board_alternatives` over the new forms, `_SITED` entries.
- `src/placemat/arrangement_run.py` - `Prepared.units` and `.excluded`, `excluded_entries`, `option_dead_findings`, `finish` wiring, `lines` excluded state, `extent_findings` over unit members.
- `src/placemat/runner.py` - the board refusal runs before the declaration checks.
- `src/placemat/findings.py`, `src/placemat/finding_text.py` - `arrangement.option_dead`; `arrangement.limit` gains `excluded` (facts version 2); the excluded console row; the subject of `option_dead`.
- `src/placemat/settings.py` - the two limit settings' docs.
- `src/placemat/studio.py`, `src/placemat/studio_page.html` - an excluded combination in a run's arrangement list.
- `skills/placemat/SKILL.md`, `skills/placemat/references/api.md`, `skills/placemat/references/migration.md`, `docs/superpowers/skill-checks/arrangements.md`, `fixtures/skill_check.py` (docstring), the spec (build notes).

Tests: new `tests/test_arrangement_units.py` (Task 1), `tests/test_arrangement_unit_declarations.py` (Task 2), `tests/test_arrangement_combine_run.py` (Task 3); edits to `tests/test_arrangement_declarations.py`, `tests/test_finding_text.py`, `tests/test_arrangement_studio.py`, `tests/test_arrangement_run.py`, `tests/slow_tests.txt`.

Existing tests whose expectations change, and why (each edit is in the task that causes it): `test_arrangement_declarations.py` `test_the_arrangements_are_the_default_the_product_and_the_groups_in_declaration_order` (a `board.arrangement` is now a unit of the product: its place in the order and its `choices` change, its id does not), `test_exactly_the_limit_is_accepted_and_one_over_is_not` (a `board.arrangement` now counts as a unit; the facts gain `excluded`), `test_all_ids_are_the_enumerated_ids_up_to_the_cap` (the order), `test_a_group_names_the_members_it_moves_and_the_ids_are_formed_as_specified` (the order); `test_finding_text.py` the two `ARRANGEMENT_LIMIT` samples (the new fact and tail).

---

### Task 1: Units, combinations and exclusions as pure data

**Files:**
- Modify: `src/placemat/arrangements.py:1-11` (docstring, `import math`), `:45-52` (`Group`), `:55-67` (`Spec` docstring), `:73-77` (`Enumeration`), `:109-173` (`spec_id`, `count`, `picks`, `enumerate_specs`, `known_id`, `all_ids` replaced)
- Test: `tests/test_arrangement_units.py` (new)
- Modify: `tests/test_arrangement_declarations.py:24-42` and `:65-70` (pure tests), `:139-152` (the order of a board's ids)

**Interfaces:**
- Consumes: `Option`, `DEFAULT`, `DEFAULT_SPEC` (unchanged).
- Produces (all in `placemat.arrangements`):
  - `@dataclass(frozen=True) GroupOption(group: str, name: str, options: tuple[Option, ...], why: str = "", file: str = "", line: int = 0)`
  - `@dataclass(frozen=True) Group(name: str, options: tuple[Option, ...] = (), why: str = "", file: str = "", line: int = 0, members: tuple[str, ...] = (), alternatives: tuple[GroupOption, ...] = ())` the record of a unit `board.unit` declares, named `Group` internally only; property `positional -> bool` (no `members`: the 0.99.15 `board.arrangement` form), `unit_options() -> tuple[GroupOption, ...]`, `moves() -> frozenset[str]`
  - `@dataclass(frozen=True) Exclusion(choices: tuple[str, ...], why: str = "", file: str = "", line: int = 0)`
  - `@dataclass(frozen=True) Choice(unit: str, option: str, id: str, overrides: tuple)`; `@dataclass(frozen=True) Unit(name: str, choices: tuple[Choice, ...], moves: frozenset, positional: bool = False, why: str = "")`
  - `Spec(id, pairs, overrides, group="", why="")` unchanged in shape; `pairs` are `(unit, option)`, a `board.arrangement`'s option named as the unit, so `choices` is `{name: name}` for it.
  - `Enumeration(specs, over, declared, excluded: tuple = ())`, `excluded` holding `(Spec, Exclusion)` pairs in product order.
  - `units(order, options: dict, groups) -> list[Unit]`; `combinations(us) -> Iterator[tuple[Choice, ...]]`; `tally(us, exclusions=()) -> tuple[int, int]` (kept, excluded); `enumerate_specs(order, options, groups, max_options, max_arrangements, exclusions=()) -> Enumeration`; `known_id(ident, order, options, groups) -> bool`; `all_ids(order, options, groups, cap=64) -> list[str]`. `order` lists item keys and unit names; a unit it does not name follows it, in the order given.
  - `arrangement.limit` facts gain `"excluded": int`; `"options"` is keyed by unit (items and `board.unit`s).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_units.py
"""Units: a module's items with options and its units combine in one product, in the order declared; a 0.99.15 board.arrangement is a unit
with one option that keeps its id; units that move one part never combine; exclusions leave combinations out."""
import time

from placemat import arrangements as A


def opt(item, name, **kw):
    return A.Option(item, name, tuple(kw.items()))


def unit(name, members, *options):
    """A unit as board.unit declares it: `options` are (option name, [Option, ...]) pairs."""
    return A.Group(name, members=tuple(members),
                   alternatives=tuple(A.GroupOption(name, n, tuple(os)) for n, os in options))


PAIR = unit("pair", ["c1", "r1"], ("flat", [opt("c1", "flat", rotation=0), opt("r1", "flat", rotation=0)]),
             ("upright", [opt("c1", "upright", rotation=90), opt("r1", "upright", rotation=90)]))
CAPS = unit("caps", ["c2", "c3"], ("upright", [opt("c2", "upright", rotation=90)]))
R_FAR = {"r_far": [opt("r_far", "turned", rotation=90)]}
ARGS = (["pair", "caps", "r_far"], R_FAR, [PAIR, CAPS])


def ids(e):
    return [s.id for s in e.specs]


def test_two_units_and_an_item_combine_in_product_order_the_first_declared_changing_slowest():
    e = A.enumerate_specs(*ARGS, 4, 100)
    assert ids(e) == [
        "default", "r_far.turned", "caps.upright", "caps.upright+r_far.turned",
        "pair.flat", "pair.flat+r_far.turned", "pair.flat+caps.upright", "pair.flat+caps.upright+r_far.turned",
        "pair.upright", "pair.upright+r_far.turned", "pair.upright+caps.upright", "pair.upright+caps.upright+r_far.turned"]
    assert e.declared == 12 and e.over is None and e.excluded == ()
    last = e.specs[-1]
    assert last.choices == {"pair": "upright", "caps": "upright", "r_far": "turned"}
    assert [k for k, _ in last.overrides] == ["c1", "r1", "c2", "r_far"] and last.group == ""


def test_a_one_option_unit_keeps_its_0_99_15_id_and_combines_with_the_items():
    caps_upright = A.Group("caps_upright", (opt("c2", "caps_upright", rotation=90), opt("c3", "caps_upright", rotation=90)),
                           why="both capacitors stand")
    pull = {"r_pull": [opt("r_pull", "upright", rotation=90)]}
    e = A.enumerate_specs(["caps_upright", "r_pull"], pull, [caps_upright], 4, 100)
    assert ids(e) == ["default", "r_pull.upright", "caps_upright", "caps_upright+r_pull.upright"]
    alone = e.specs[2]
    assert alone.choices == {"caps_upright": "caps_upright"} and alone.group == "caps_upright" and alone.why == "both capacitors stand"
    assert [k for k, _ in alone.overrides] == ["c2", "c3"]
    assert e.specs[3].group == "" and e.specs[3].choices == {"caps_upright": "caps_upright", "r_pull": "upright"}


def test_units_that_move_one_part_never_combine():
    """Review focus 1: two 0.99.15 board.arrangements over one pair, and one over a part with an option of its own."""
    mirrored = A.Group("mirrored", (opt("q1", "mirrored", rotation=180), opt("q2", "mirrored", rotation=180)))
    rotated = A.Group("rotated", (opt("q1", "rotated", rotation=90),))
    q2 = {"q2": [opt("q2", "turned", rotation=90)]}
    args = (["q2", "mirrored", "rotated"], q2, [mirrored, rotated])
    e = A.enumerate_specs(*args, 4, 100)
    assert ids(e) == ["default", "rotated", "mirrored", "q2.turned", "q2.turned+rotated"]
    assert e.declared == 5
    assert A.known_id("q2.turned+rotated", *args)
    for bad in ("mirrored+rotated", "q2.turned+mirrored"):
        assert not A.known_id(bad, *args), bad


def test_an_exclusion_leaves_out_every_combination_holding_all_its_choices():
    rule = A.Exclusion(("pair.upright", "caps.upright"), "both stand in the one column")
    e = A.enumerate_specs(*ARGS, 4, 100, exclusions=(rule,))
    gone = ["pair.upright+caps.upright", "pair.upright+caps.upright+r_far.turned"]
    assert [s.id for s, _ in e.excluded] == gone and all(r is rule for _, r in e.excluded)
    assert not set(gone) & set(ids(e)) and e.declared == 10 and len(e.specs) == 10


def test_the_limit_counts_after_exclusions():
    rule = A.Exclusion(("pair.upright", "caps.upright"))
    assert A.enumerate_specs(*ARGS, 4, 10, exclusions=(rule,)).over is None
    over = A.enumerate_specs(*ARGS, 4, 9, exclusions=(rule,))
    assert ids(over) == ["default"] and over.excluded == ()
    assert over.over == {"variant": "arrangements", "arrangements": 10, "max_arrangements": 9,
                         "options": {"pair": 3, "caps": 2, "r_far": 2}, "max_options": 4, "excluded": 2}


def test_a_units_default_counts_as_one_of_its_options():
    wide = unit("wide", ["a"], *[(n, [opt("a", n, rotation=r)]) for n, r in (("w", 90), ("x", 180), ("y", 270), ("z", 45))])
    e = A.enumerate_specs(["wide"], {}, [wide], 4, 100)
    assert e.over["variant"] == "options" and e.over["options"] == {"wide": 5} and ids(e) == ["default"]


def test_counting_does_not_walk_the_whole_product():
    """Review focus 3: 14 items of 3 options each make 4^14 combinations; an exclusion over two of them is counted over those two."""
    items = {"p%02d" % n: [opt("p%02d" % n, o, rotation=r) for o, r in (("a", 90), ("b", 180), ("c", 270))] for n in range(14)}
    t0 = time.monotonic()
    kept, excluded = A.tally(A.units(sorted(items), items, []), (A.Exclusion(("p00.a", "p01.b")),))
    assert (kept, excluded) == (4 ** 14 - 4 ** 12, 4 ** 12)
    assert time.monotonic() - t0 < 1.0


def test_known_ids_and_all_ids_follow_the_product():
    assert A.all_ids(*ARGS) == ids(A.enumerate_specs(*ARGS, 4, 100))
    assert A.all_ids(*ARGS, cap=3) == ["default", "r_far.turned", "caps.upright"]
    for ok in ("default", "pair.flat", "caps.upright+r_far.turned", "pair.upright+caps.upright+r_far.turned"):
        assert A.known_id(ok, *ARGS), ok
    for bad in ("pair", "pair.sideways", "caps.upright+pair.flat", "pair.flat+pair.upright", "c1.flat", ""):
        assert not A.known_id(bad, *ARGS), bad
```

Edit `tests/test_arrangement_declarations.py`. Replace the test at lines 24-33 with:

```python
def test_the_arrangements_are_the_default_then_the_product_with_a_board_arrangement_as_one_more_unit():
    """A 0.99.15 board.arrangement keeps its id; it moves c_in and r_pull, which have options of their own, so it combines with neither."""
    options = {"c_in": [opt("c_in", "east")], "r_pull": [opt("r_pull", "turned"), opt("r_pull", "back")]}
    group = A.Group("mirrored", (opt("c_in", "mirrored"), opt("r_pull", "mirrored")))
    e = A.enumerate_specs(["c_in", "r_pull"], options, [group], 4, 20)
    assert [s.id for s in e.specs] == ["default", "mirrored", "r_pull.turned", "r_pull.back", "c_in.east",
                                       "c_in.east+r_pull.turned", "c_in.east+r_pull.back"]
    assert e.over is None and e.declared == 7
    both = e.specs[5]
    assert both.choices == {"c_in": "east", "r_pull": "turned"} and [k for k, _ in both.overrides] == ["c_in", "r_pull"]
    assert e.specs[1].choices == {"mirrored": "mirrored"} and e.specs[1].group == "mirrored" and e.specs[0].choices == {}
```

In `test_exactly_the_limit_is_accepted_and_one_over_is_not` (lines 36-42) replace the last assertion with:

```python
    assert over.over == {"variant": "arrangements", "arrangements": 12, "max_arrangements": 8,       # g moves a: 8 + 4 with b and c
                         "options": {"a": 2, "b": 2, "c": 2, "g": 2}, "max_options": 4, "excluded": 0}
```

In `test_all_ids_are_the_enumerated_ids_up_to_the_cap` (line 70) replace the cap assertion with:

```python
    assert A.all_ids(*args, cap=3) == ["default", "mirrored", "r_pull.turned"]
```

In `test_a_group_names_the_members_it_moves_and_the_ids_are_formed_as_specified` (line 146, a 0.99.15 test kept under its name) replace the ids assertion with:

```python
    assert ids == ["default", "mirrored", "r_pull.turned", "c_in.east", "c_in.east+r_pull.turned"]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_units.py tests/test_arrangement_declarations.py -n 2 -p no:cacheprovider -q`
Expected: FAIL (`AttributeError: module 'placemat.arrangements' has no attribute 'GroupOption'`, and the edited declaration tests on the order).

- [ ] **Step 3: Implement**

`arrangements.py` top: add `import math` after `import itertools`, and make the module docstring:

```python
"""A module's alternative arrangements as declarations: the options an item may take, the units, the exclusions, the ids and the
limits.

Pure: no Board, no KiCad. `Board.alternative`, `Board.unit`, `Board.arrangement` and `Board.exclude` (layout.py) validate against
the board and build the records here; `enumerate_specs` turns them into the arrangements a module run lays out, the default first."""
```

Replace `Group` (lines 45-52) with:

```python
@dataclass(frozen=True)
class GroupOption:
    """One option of a unit, `board.alternative(unit, name, Alt(...), ...)`: an Option for each member it moves, named as the
    option; the members it does not name keep their place()."""
    group: str
    name: str
    options: tuple              # (Option, ...)
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Group:
    """The record of a unit: members that move as one unit of a module's arrangements. (Named Group in code; every name a script
    or a message shows says unit.) `board.unit(name, *members)` declares one with its `members`, and `board.alternative(unit, ...)`
    adds each of its `alternatives`. `board.arrangement(name, *alts)`, the 0.99.15 form, is a unit with one option named as the
    unit, its members' options in `options`: its id is the unit's name alone."""
    name: str
    options: tuple = ()         # the 0.99.15 form: (Option, ...), one per member its one option moves
    why: str = ""
    file: str = ""
    line: int = 0
    members: tuple = ()         # board.unit: the members' item keys
    alternatives: tuple = ()    # board.unit: (GroupOption, ...), in declaration order

    @property
    def positional(self) -> bool:
        """The 0.99.15 form (board.arrangement)."""
        return not self.members

    def unit_options(self) -> tuple:
        """Its options as GroupOption: the 0.99.15 form's one, named as the unit, or board.unit's."""
        if self.positional:
            return (GroupOption(self.name, self.name, self.options, self.why, self.file, self.line),)
        return self.alternatives

    def moves(self) -> frozenset:
        """The item keys its options move."""
        return frozenset(o.item for go in self.unit_options() for o in go.options)


@dataclass(frozen=True)
class Exclusion:
    """`board.exclude(*choices)`: every combination holding all of `choices` (`item.option`, `unit.option`, or a 0.99.15 board.arrangement's
    name) is not laid out."""
    choices: tuple
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Choice:
    """One choice a unit offers: its unit's and option's names, its id in a combination, and the options it lays over members'
    places."""
    unit: str
    option: str
    id: str
    overrides: tuple            # ((item key, Option), ...)


@dataclass(frozen=True)
class Unit:
    """An item with options, or a unit: it contributes its default and each choice to the product."""
    name: str
    choices: tuple              # (Choice, ...)
    moves: frozenset            # the item keys its choices move: two units that share one never combine
    positional: bool = False    # a board.arrangement: alone, its arrangement keeps the unit's name and why
    why: str = ""
```

`Spec`'s docstring and field comments (lines 56-63):

```python
    """One arrangement a module run lays out: its id, its choices as (unit, option) pairs (a board.arrangement's option is named as
    the unit), and the options to lay over the items' places, in unit order."""
    id: str
    pairs: tuple
    overrides: tuple            # ((item key, Option), ...)
    group: str = ""             # a board.arrangement laid alone: its name
    why: str = ""
```

`Enumeration` (lines 73-77):

```python
@dataclass(frozen=True)
class Enumeration:
    specs: tuple                # the default first, then the combinations in product order, less the excluded
    over: dict | None           # the facts of arrangement.limit when a limit is passed; the specs are then the default alone
    declared: int               # how many arrangements the declarations make after exclusions, the default included
    excluded: tuple = ()        # ((Spec, Exclusion), ...): the combinations an exclusion leaves out, in product order
```

Replace lines 109-173 (`spec_id` through `all_ids`) with:

```python
def units(order, options: dict, groups) -> list:
    """The units in `order` (item keys and unit names, the first declared first), then each declared unit `order` does not name, in the
    order given: an item with options, or a declared unit, each as a Unit of its choices."""
    by_name = {g.name: g for g in groups}
    out = []
    for name in list(order) + [g.name for g in groups if g.name not in order]:
        g = by_name.get(name)
        if g is not None:
            choices = tuple(Choice(g.name, go.name, g.name if g.positional else "%s.%s" % (g.name, go.name),
                                   tuple((o.item, o) for o in go.options)) for go in g.unit_options())
            out.append(Unit(g.name, choices, g.moves(), g.positional, g.why if g.positional else ""))
        elif options.get(name):
            out.append(Unit(name, tuple(Choice(name, o.name, "%s.%s" % (name, o.name), ((name, o),)) for o in options[name]),
                            frozenset((name,))))
    return out


def combinations(us):
    """Every combination of the units' choices in `itertools.product` order over `us` (the first unit changing slowest), each a
    tuple of the Choices taken, the empty one (the default) first. Two units that move one item never combine: a combination
    holding both is not one."""
    for picked in itertools.product(*[(None,) + u.choices for u in us]):
        taken = [(u, c) for u, c in zip(us, picked) if c is not None]
        moved = [k for u, _ in taken for k in u.moves]
        if len(moved) == len(set(moved)):
            yield tuple(c for _, c in taken)


def _excluded_by(combo, exclusions):
    """The first exclusion all of whose choices `combo` holds, or None."""
    ids = {c.id for c in combo}
    return next((e for e in exclusions if set(e.choices) <= ids), None)


def tally(us, exclusions=()) -> tuple:
    """(kept, excluded): how many combinations the units make, the default included, less those an exclusion leaves out; and how
    many the exclusions leave out. Only the units an exclusion names, or that move an item another unit moves, are walked; each of
    their combinations stands for the product of the other units' sizes."""
    named = {i for e in exclusions for i in e.choices}
    walked = [u for u in us if any(c.id in named for c in u.choices) or any(v is not u and u.moves & v.moves for v in us)]
    walked_names = {u.name for u in walked}
    free = math.prod(1 + len(u.choices) for u in us if u.name not in walked_names)
    kept = excluded = 0
    for combo in combinations(walked):
        if _excluded_by(combo, exclusions) is None:
            kept += free
        else:
            excluded += free
    return kept, excluded


def _spec(combo, positional: dict) -> Spec:
    pairs = tuple((c.unit, c.option) for c in combo)
    overrides = tuple(o for c in combo for o in c.overrides)
    ident = "+".join(c.id for c in combo)
    if len(combo) == 1 and combo[0].unit in positional:          # a board.arrangement alone: its name and why, as in 0.99.15
        return Spec(ident, pairs, overrides, combo[0].unit, positional[combo[0].unit])
    return Spec(ident, pairs, overrides)


def enumerate_specs(order, options: dict, groups, max_options: int, max_arrangements: int, exclusions=()) -> Enumeration:
    """The arrangements of a module: the default, then every combination of the units' choices (each unit contributes its default
    and each choice; `combinations` order), less those an exclusion leaves out, which are returned apart. Over either limit (a
    unit's options, its default counted; the arrangements after exclusions) nothing is partly accepted: the default alone, and
    the facts of the finding."""
    us = units(order, options, groups)
    sizes = {u.name: 1 + len(u.choices) for u in us}
    declared, excluded = tally(us, exclusions)
    wide = any(n > max_options for n in sizes.values())
    if wide or declared > max_arrangements:
        facts = {"variant": "options" if wide else "arrangements", "arrangements": declared,
                 "max_arrangements": max_arrangements, "options": sizes, "max_options": max_options, "excluded": excluded}
        return Enumeration((DEFAULT_SPEC,), facts, declared)
    positional = {u.name: u.why for u in us if u.positional}
    specs, left_out = [DEFAULT_SPEC], []
    for combo in combinations(us):
        if not combo:
            continue
        spec, rule = _spec(combo, positional), _excluded_by(combo, exclusions)
        if rule is None:
            specs.append(spec)
        else:
            left_out.append((spec, rule))
    return Enumeration(tuple(specs), None, declared, tuple(left_out))


def known_id(ident: str, order, options: dict, groups) -> bool:
    """Whether `ident` is an id this module's declarations make, as written, without enumerating the product (a module over its
    limit still says which ids it meant): `default`, or choice ids in unit order joined by `+`, no two moving one item."""
    if ident == DEFAULT:
        return True
    where = {c.id: (n, u) for n, u in enumerate(units(order, options, groups)) for c in u.choices}
    last, moved = -1, frozenset()
    for piece in ident.split("+"):              # the id as the script wrote it: text to check, not a record
        got = where.get(piece)
        if got is None or got[0] <= last or moved & got[1].moves:
            return False
        last, moved = got[0], moved | got[1].moves
    return True


def all_ids(order, options: dict, groups, cap: int = 64) -> list:
    """The ids the declarations make, for a message: the default, then the combinations in product order, at most `cap`."""
    out = [DEFAULT]
    for combo in combinations(units(order, options, groups)):
        if combo:
            out.append("+".join(c.id for c in combo))
        if len(out) >= cap:
            break
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_units.py tests/test_arrangement_declarations.py tests/test_arrangement_only.py tests/test_arrangement_extent.py tests/test_arrangement_resolve.py -n 2 -p no:cacheprovider -q`
Expected: PASS. The last three are 0.99.15 tests of ids, `only=` and the resolve; they pass unchanged (the `board` they use passes item keys as `order`, and its unit follows them).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/arrangements.py tests/test_arrangement_units.py tests/test_arrangement_declarations.py
git commit -m "Arrangements: a module's units combine in one product, with options of their own, and exclusions leave combinations out"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 2: `board.unit`, a unit's options, `board.exclude`, and the checks where the script finishes

**Files:**
- Modify: `src/placemat/layout.py:42` (imports), `:1039-1043` (`Board.__init__` fields), `:3399-3419` (`_checked_option` split into `_member_key`), `:3421-3432` (`alternative`), `:3434-3455` (`arrangement`, and `unit` new beside it), `:3464-3475` (`arrangement_enumeration`), `:3481-3505` (`finish_declarations`), `:3507-3520` (`refuse_board_alternatives`), `:10717-10740` (`_SITED`); `board.group` (`:7519-7543`) is not touched
- Modify: `src/placemat/arrangement_run.py:116-117` (`extent_findings`: the members a unit moves)
- Modify: `src/placemat/runner.py:371-372` (refuse a board's alternatives before checking the declarations)
- Test: `tests/test_arrangement_unit_declarations.py` (new); `tests/test_arrangement_declarations.py:226-227` (one more declaration in the board-script test)

**Interfaces:**
- Consumes: from Task 1 `Group` (the unit record), `GroupOption`, `Exclusion`, `units`, `enumerate_specs(..., exclusions)`, `known_id`, `all_ids`.
- Produces:
  - `Board.unit(name: str, *members, why: str = "") -> arrangements.Group`: parts one by one, each a part the script placed with `place()`. `Board.group(name, items, why="")` is unchanged and returns a `DeclaredGroup`.
  - `Board.alternative(item, name: str, *alts, **keywords)`: on a part -> `Option` (unchanged); on a `Group` from `board.unit` -> `GroupOption`.
  - `Board.exclude(*choices: str, why: str = "") -> Exclusion`.
  - `Board._unit_order() -> list[str]`; `Board.arrangement_units() -> list[Unit]`; `Board._unit_holding(key: str) -> Group | None`; `Board._exclusions: list[Exclusion]`; `Board._group_after: dict[str, int]`.
  - `Board.finish_declarations()` raises `ValueError("<file>:<line>: ...")` for a unit with no option, a unit named as an item with options, and a bad exclusion.
  - `arrangement_enumeration()` passes `_unit_order()` and the exclusions; its `Enumeration.excluded` holds the excluded combinations.
  - Sites: `sites_of("alternative", "pair.upright")`, `sites_of("unit", "pair")`, `sites_of("exclude", "pair.upright+caps_upright")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_unit_declarations.py
"""board.unit and its options, board.exclude, the units' order, and the checks made where the script finishes declaring."""
import dataclasses

import pytest

from placemat import Alt, arrangement_run as run
from placemat.arrangements import Group, GroupOption
from placemat.layout import Board, DeclaredGroup
from placemat.settings import Settings
from placemat.values import Beside, CopperLayer, Edge, Location, Net, PadRef, Part
from tests.arrangement_support import module, parts
from tests.fixtures import board_geometry

HERE = "test_arrangement_unit_declarations.py:"


def paired(settings=None):
    b = module(settings)
    return b, b.unit("pair", Part("c_in"), Part("r_pull"), why="the pair moves as one")


def declared():
    """r_pull with its own option; a unit of c_in with two options; a board.arrangement that moves r_pull too."""
    b = module(dataclasses.replace(Settings(), place_arrangements_max=20))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    cap = b.unit("cap", Part("c_in"), why="the bypass may stand north or south of u1")
    b.alternative(cap, "north", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    b.alternative(cap, "south", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.SOUTH)))
    b.arrangement("lifted", Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.NORTH)), why="the pull-up north")
    return b


def test_board_group_still_writes_a_kicad_group_and_takes_no_option():
    """Review focus 2: board.group is unchanged; the unit is board.unit."""
    b = module()
    kept = b.group("kept", [Part("c_in"), Part("r_pull")], why="moved as one by hand")
    assert isinstance(kept, DeclaredGroup) and "kept" in b._groups and b._arr_groups == []
    pair = b.unit("pair", Part("c_in"), Part("r_pull"), why="the pair moves as one")
    assert isinstance(pair, Group) and pair.members == ("c_in", "r_pull") and "pair" not in b._groups
    assert len(b.sites_of("unit", "pair")) == 1
    with pytest.raises(TypeError) as e:
        b.alternative(kept, "up", Alt(Part("c_in"), rotation=90))
    assert "board.unit" in str(e.value)
    with pytest.raises(TypeError) as e:
        b.unit("listed", [Part("c_in"), Part("r_pull")])
    assert "one by one" in str(e.value)


def test_a_units_option_lays_its_members_and_leaves_the_rest():
    b, pair = paired()
    up = b.alternative(pair, "up", Alt(Part("c_in"), rotation=90), why="the bypass stands")
    assert isinstance(up, GroupOption) and up.group == "pair" and up.why == "the bypass stands"
    assert [(o.item, o.name) for o in up.options] == [("c_in", "up")]
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default", "pair.up"]
    assert b.arrangement_enumeration().specs[1].choices == {"pair": "up"}
    assert len(b.sites_of("alternative", "pair.up")) == 1


@pytest.mark.parametrize("call, error", [
    (lambda b, g: b.alternative(g, "up", rotation=90), TypeError),                                         # place keywords
    (lambda b, g: b.alternative(g, "up", Alt(Part("u1"), rotation=90)), ValueError),                       # not a member
    (lambda b, g: b.alternative(g, "up", Alt(Part("c_in"), rotation=90), Alt(Part("c_in"), rotation=180)), ValueError),  # twice
    (lambda b, g: b.alternative(g, "up", Part("c_in")), TypeError),                                        # not an Alt
    (lambda b, g: b.alternative(g, "up"), ValueError),                                                     # names no member
    (lambda b, g: b.alternative(g, "Up", Alt(Part("c_in"), rotation=90)), ValueError),                     # not a name
    (lambda b, g: b.alternative(Part("u1"), "up", Alt(Part("u1"), rotation=90)), TypeError),               # an Alt on an item
    (lambda b, g: b.alternative(b.arrangement("m", Alt(Part("u1"), rotation=90)), "x", Alt(Part("u1"), rotation=180)), TypeError),
])
def test_a_bad_unit_option_is_refused_where_it_is_written(call, error):
    b, pair = paired()
    with pytest.raises(error):
        call(b, pair)


def test_a_unit_option_name_is_unique_within_the_unit_and_a_unit_name_is_taken_once():
    b, pair = paired()
    b.alternative(pair, "up", Alt(Part("c_in"), rotation=90))
    with pytest.raises(ValueError):
        b.alternative(pair, "up", Alt(Part("r_pull"), rotation=90))
    with pytest.raises(ValueError):
        b.unit("pair", Part("u1"))
    with pytest.raises(ValueError):
        b.arrangement("pair", Alt(Part("u1"), rotation=90))


def test_a_member_is_in_one_unit_and_has_no_alternative_of_its_own():
    b, pair = paired()
    with pytest.raises(ValueError) as e:
        b.unit("other", Part("c_in"))
    assert "'pair'" in str(e.value) and str(e.value).count(HERE) == 2
    with pytest.raises(ValueError) as e:
        b.alternative(Part("r_pull"), "turned", rotation=180)
    assert "'pair'" in str(e.value) and str(e.value).count(HERE) == 2
    with pytest.raises(ValueError) as e:
        b.arrangement("lifted", Alt(Part("c_in"), rotation=90))
    assert "'pair'" in str(e.value) and str(e.value).count(HERE) == 2
    first = module()
    first.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    with pytest.raises(ValueError) as e:
        first.unit("pair", Part("c_in"))
    assert "'east'" in str(e.value) and str(e.value).count(HERE) == 2
    later = module()
    later.arrangement("lifted", Alt(Part("c_in"), rotation=90))
    with pytest.raises(ValueError) as e:
        later.unit("pair", Part("c_in"))
    assert "'lifted'" in str(e.value) and str(e.value).count(HERE) == 2


def test_a_0_99_15_module_whose_arrangements_share_parts_runs_and_keeps_its_ids():
    """Review focus 1: two board.arrangements over one pair, and one over a part with its own alternative."""
    b = module()
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.arrangement("mirrored", Alt(Part("c_in"), rotation=180), Alt(Part("r_pull"), rotation=180))
    b.arrangement("rotated", Alt(Part("c_in"), rotation=90), Alt(Part("r_pull"), rotation=90))
    b.finish_declarations()
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default", "rotated", "mirrored", "c_in.east"]


def test_a_one_option_unit_combines_with_the_items_it_does_not_move():
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("flip", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)), why="the bypass north")
    specs = b.arrangement_enumeration().specs
    assert [s.id for s in specs] == ["default", "flip", "r_pull.turned", "r_pull.turned+flip"]
    assert specs[1].group == "flip" and specs[1].why == "the bypass north"
    assert specs[3].choices == {"r_pull": "turned", "flip": "flip"}
    b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=CopperLayer.F, only=("r_pull.turned+flip",))
    b.finish_declarations()                                     # a combination id the new product makes is known to only=


@pytest.mark.parametrize("only", [("flip+r_pull.turned",), ("r_pull.turned+lifted",)])
def test_only_refuses_an_id_in_the_wrong_order_or_of_units_that_never_combine(only):
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("flip", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    b.arrangement("lifted", Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.NORTH)))
    b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=CopperLayer.F, only=only)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and "only=" in str(e.value)


def test_units_take_their_place_in_the_order_the_script_declared_them():
    b = Board(board_geometry(parts(), width=60, height=40), edge_margin=1.0, settings=Settings())
    b.place(Part("u1"), at=Location(20, 15))
    b.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST))
    pair = b.unit("pair", Part("c_in"))
    b.alternative(pair, "north", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    b.place(Part("r_pull"), at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.alternative(Part("u1"), "turned", rotation=180)          # declared last, but u1's place() came first: the first unit
    assert b._unit_order() == ["u1", "pair", "r_pull"]
    assert [s.id for s in b.arrangement_enumeration().specs] == [
        "default", "r_pull.turned", "pair.north", "pair.north+r_pull.turned", "u1.turned", "u1.turned+r_pull.turned",
        "u1.turned+pair.north", "u1.turned+pair.north+r_pull.turned"]


def test_a_module_of_items_alone_keeps_its_order():
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default", "r_pull.turned", "c_in.east", "c_in.east+r_pull.turned"]


def test_declared_units_make_their_product():
    b = declared()
    b.finish_declarations()
    assert b._unit_order() == ["r_pull", "cap", "lifted"]
    assert [s.id for s in b.arrangement_enumeration().specs] == [
        "default", "lifted", "cap.north", "cap.north+lifted", "cap.south", "cap.south+lifted", "r_pull.turned",
        "r_pull.turned+cap.north", "r_pull.turned+cap.south"]


def test_an_exclusion_leaves_out_its_combinations_and_keeps_its_why():
    b = declared()
    rule = b.exclude("cap.north", "lifted", why="both stand north of u1")
    b.finish_declarations()
    e = b.arrangement_enumeration()
    assert [(s.id, r) for s, r in e.excluded] == [("cap.north+lifted", rule)] and rule.why == "both stand north of u1"
    assert "cap.north+lifted" not in [s.id for s in e.specs] and e.declared == 8
    assert len(b.sites_of("exclude", "cap.north+lifted")) == 1
    with pytest.raises(TypeError):
        b.exclude("cap.north", 3)


@pytest.mark.parametrize("choices, words", [
    (("cap.north",), "two or more"),
    (("cap.north", "cap.south"), "one at a time"),
    (("cap.north", "nope.x"), "not a choice"),
    (("cap.north+r_pull.turned", "cap.south"), "not a choice"),     # a combination id is not one choice
    (("r_pull.turned", "lifted"), "never combine"),
])
def test_a_bad_exclusion_is_an_error_with_its_line(choices, words):
    """Review focus 4."""
    b = declared()
    b.exclude(*choices)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and words in str(e.value)
    if words == "not a choice":
        assert "cap.north" in str(e.value) and "lifted" in str(e.value)        # the module's choices are listed


def test_a_unit_with_no_option_and_a_unit_named_as_an_item_are_errors_where_the_script_finishes():
    b, _ = paired()
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and "'pair'" in str(e.value) and "no option" in str(e.value)
    c = module()
    c.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    g = c.unit("c_in", Part("r_pull"))
    c.alternative(g, "up", Alt(Part("r_pull"), rotation=90))
    with pytest.raises(ValueError) as e:
        c.finish_declarations()
    assert HERE in str(e.value) and "'c_in'" in str(e.value)


def test_a_member_moved_only_by_a_units_option_gets_no_extent_notice():
    b, pair = paired()
    b.alternative(pair, "north", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    extent = [{"item": "c_in", "sides": ["west"], "protrudes_mm": 0.4}, {"item": "r_pull", "sides": ["east"], "protrudes_mm": 0.1}]
    assert [f.facts["item"] for f in run.extent_findings(b, extent, 2.0)] == ["r_pull"]


def _scripted(tmp_path, declaration, draw=""):
    from placemat.project import FabProfile
    from placemat.runner import scripted_board
    from tests.test_arrangement_declarations import _BOARD_SCRIPT
    path = tmp_path / "layout.py"
    path.write_text(_BOARD_SCRIPT.format(draw=draw, declaration=declaration))
    return scripted_board(path, None, Settings(), FabProfile(), True, geometry=board_geometry(parts(), width=60, height=40))


def test_a_board_script_may_still_write_a_kicad_group(tmp_path):
    """Review focus 2."""
    b = _scripted(tmp_path, 'board.group("kept", [Part("c_in")])')          # unchanged by this plan
    assert "kept" in b._groups and b._arr_groups == []


def test_a_board_script_with_a_unit_fails_saying_it_is_a_modules_before_any_other_check(tmp_path):
    from placemat.runner import RunFailure
    with pytest.raises(RunFailure) as e:
        _scripted(tmp_path, 'board.unit("pair", Part("c_in"))')            # no option either: the board's error comes first
    said = str(e.value.details.get("error", "")) + str(e.value)
    assert "module" in said and ":5:" in said and "no option" not in said, said
```

In `tests/test_arrangement_declarations.py`, the parametrize of `test_a_board_script_that_declares_alternatives_fails_saying_they_are_a_modules` (lines 226-227) gains a third declaration, on one line so its line is 5:

```python
@pytest.mark.parametrize("declaration", ['board.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))',
                                         'board.arrangement("east", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.EAST)))',
                                         'pair = board.unit("pair", Part("c_in")); '
                                         'board.alternative(pair, "east", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.EAST)))'])
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_unit_declarations.py tests/test_arrangement_declarations.py -n 2 -p no:cacheprovider -q`
Expected: FAIL (`Board` has no `unit` or `exclude`).

- [ ] **Step 3: Implement**

`layout.py:42`:

```python
from .arrangements import (DEFAULT_SPEC, Alt, Enumeration, Exclusion, Group, GroupOption, Option, Spec, check_keywords, check_name,
                           enumerate_specs, merged_call, units)
```

`Board.__init__`, line 1040 becomes the first line below and two fields follow it:

```python
        self._arr_groups: list = []         # Group (a unit): board.unit() and board.arrangement(), in declaration order
        self._group_after: dict = {}        # unit name -> how many place() calls the script had made when it declared the unit
        self._exclusions: list = []         # Exclusion: board.exclude(), in declaration order
```

Replace `_checked_option` (lines 3399-3419) with:

```python
    def _member_key(self, item, grouped: bool = False) -> str:
        """The key of a part the script has placed with its own place(), which an option or a unit may move. A row's or ring's
        member is one only in a unit (`grouped`)."""
        geom, key, kind = self._item(item)
        call = self._place_calls.get(key)
        if call is None:
            raise ValueError("%s: an alternative or a unit moves a part the script has placed with place(), and the script has "
                             "not placed it; a block's member has none of its own" % key)
        if kind != "part":
            raise TypeError("%s: an alternative is for a part of a module; a %s's arrangements are the ones its own module "
                            "offers (arrangements= on its place())" % (key, kind))
        if not grouped and (key in self._row_members or call[3]):
            raise ValueError("%s is a member of a %s: an arrangement of a row is a unit (board.unit)"
                             % (key, "row" if key in self._row_members else call[3]))
        if "+" in key:
            raise ValueError("%s: an item key with a + cannot be named in an arrangement id" % key)
        return key

    def _checked_option(self, item, name: str, keywords: dict, *, grouped: bool = False) -> Option:
        site = _script_site()
        key = self._member_key(item, grouped)
        check_name("option", name)
        check_keywords(key, keywords)
        self._refuse_coordinates(key, keywords.get("at"))
        option = Option(key, name, tuple((k, v) for k, v in keywords.items() if k != "why"), keywords.get("why", ""), *site)
        self._intent_option(option)         # built now: a bad keyword or a bad relation is refused where it is written
        return option
```

Replace `alternative` and `arrangement` (lines 3421-3455) with:

```python
    def alternative(self, item, name: str, *alts, **keywords):
        """Another way a part, or a unit, may stand.

        On a part the script has placed: an option on its `place()`, which stays its default. `keywords` are those of `place()`
        that change where an item goes (`at=`, `rotation=`, `rotations=`, `face=`, `radius=`, `step=`) and `why=`; every other
        keyword and each one not given is the item's own. An option that gives `rotation=` replaces the item's `rotations=` and
        `Turned`, and one that gives `rotations=` replaces its `rotation=`. Returns the Option.

        On a unit board.unit declared: one option of the unit, `Alt(member, **keywords)` for each member it moves (each at
        most once; a member it does not name keeps its place()), and `why=`. Returns the GroupOption.

        The module run lays out every arrangement and offers the ones that pass its own DRC and checks; the board's search
        chooses among them."""
        if isinstance(item, DeclaredGroup):
            raise TypeError("group %r is a KiCad group on the written board and takes no option; a set of parts that moves as one "
                            "unit of a module's arrangements is declared with board.unit(%r, Part(...), ...)" % (item.name, item.name))
        if isinstance(item, Group):
            return self._unit_alternative(item, name, alts, keywords)
        if alts:
            raise TypeError("%s: an item's alternative takes place() keywords, not %r: Alt(...) is for a unit's option "
                            "(board.unit)" % (self._item(item)[1], alts[0]))
        option = self._checked_option(item, name, keywords)
        held = self._unit_holding(option.item)
        if held is not None:
            raise ValueError("%s:%d: %s is a member of unit %r (%s:%d): a member moves with its unit, so the option is the "
                             "unit's: board.alternative(%s, %r, Alt(...))" % (option.file, option.line, option.item, held.name,
                                                                                 held.file, held.line, held.name, name))
        if any(o.name == name for o in self._options.get(option.item, ())):
            raise ValueError("%s already has an option %r" % (option.item, name))
        self._options.setdefault(option.item, []).append(option)
        self._arrangement_enum = None
        return option

    def _unit_alternative(self, group: Group, name: str, alts, keywords: dict) -> GroupOption:
        g = next((x for x in self._arr_groups if x.name == group.name), None)
        if g is None or g.positional:
            raise TypeError("board.alternative(%r, ...): %s; a unit whose options are declared one by one is board.unit's"
                            % (group.name, "board.arrangement declares a unit with its one option" if g is not None
                               else "this board declares no unit of that name"))
        extra = sorted(set(keywords) - {"why"})
        if extra:
            raise TypeError("unit %r: a unit's alternative takes Alt(member, **keywords) for each member it moves, not %s"
                            % (g.name, ", ".join(extra)))
        check_name("option", name)
        if any(o.name == name for o in g.alternatives):
            raise ValueError("unit %r already has an option %r" % (g.name, name))
        if not alts:
            raise ValueError("unit %r: option %r names no member: give Alt(member, **keywords) for each member it moves"
                             % (g.name, name))
        seen, options = set(), []
        for a in alts:
            if not isinstance(a, Alt):
                raise TypeError("unit %r: option %r takes Alt(member, **keywords), not %r" % (g.name, name, a))
            key = self._item(a.item)[1]
            if key not in g.members:
                raise ValueError("unit %r: option %r names %s, which is not a member of the unit (its members: %s)"
                                 % (g.name, name, key, ", ".join(g.members)))
            if key in seen:
                raise ValueError("unit %r: option %r names %s twice" % (g.name, name, key))
            seen.add(key)
            options.append(self._checked_option(a.item, name, a.keywords, grouped=True))
        option = GroupOption(g.name, name, tuple(options), keywords.get("why", ""), *_script_site())
        self._arr_groups[self._arr_groups.index(g)] = dataclasses.replace(g, alternatives=g.alternatives + (option,))
        self._arrangement_enum = None
        return option

    def arrangement(self, name: str, *alts, why: str = "") -> Group:
        """A unit of the members `alts` name, with one option: `Alt(item, **keywords)` for each (the keywords of `alternative`).
        The 0.99.15 form: its id is its name, and the members it does not name keep their `place()`. It combines with every other
        item and unit except one that moves a part it moves. To give a unit more than one option, declare it with
        board.unit."""
        check_name("arrangement", name)
        self._refuse_taken_unit(name)
        if not alts:
            raise ValueError("arrangement %r names no member: give Alt(item, **keywords) for each one it moves" % name)
        file, line = _script_site()
        seen, options = set(), []
        for a in alts:
            if not isinstance(a, Alt):
                raise TypeError("arrangement %r takes Alt(item, **keywords), not %r" % (name, a))
            o = self._checked_option(a.item, name, a.keywords, grouped=True)
            if o.item in seen:
                raise ValueError("arrangement %r names %s twice" % (name, o.item))
            held = self._unit_holding(o.item)
            if held is not None:
                raise ValueError("%s:%d: arrangement %r names %s, which unit %r (%s:%d) moves: a member is in one unit"
                                 % (file, line, name, o.item, held.name, held.file, held.line))
            seen.add(o.item)
            options.append(o)
        group = Group(name, tuple(options), why, file, line)
        self._arr_groups.append(group)
        self._group_after[name] = len(self._intents)
        self._arrangement_enum = None
        return group

    def unit(self, name: str, *members, why: str = "") -> Group:
        """A set of a module's parts that moves as one unit of its arrangements: `board.unit(name, Part, Part, ..., why="")`, the
        parts given one by one, each a part the script has placed with `place()`. Its default is each member's own place();
        `board.alternative(unit, option, Alt(...), ...)` adds each option, and it combines with every other item and unit. A
        member is in one unit only and has no alternative of its own. Returns the unit (the arrangements.Group record).
        (`board.group(name, [parts])` is the KiCad group on the written board and is a different call.)"""
        file, line = _script_site()
        check_name("unit", name)
        self._refuse_taken_unit(name)
        if not members:
            raise ValueError("unit %r names no member: give the parts that move together" % name)
        if any(isinstance(m, (list, tuple, set, frozenset)) for m in members):
            raise TypeError("unit %r takes its parts one by one, board.unit(%r, Part(...), ...), not in a list; a KiCad group on "
                            "the written board is board.group" % (name, name))
        keys = []
        for m in members:
            key = self._member_key(m, grouped=True)
            if key in keys:
                raise ValueError("unit %r names %s twice" % (name, key))
            other = next((g for g in self._arr_groups if key in g.members or key in g.moves()), None)
            if other is not None:
                raise ValueError("%s:%d: unit %r names %s, which %s %r (%s:%d) already moves: a member is in one unit"
                                 % (file, line, name, key, "unit" if other.members else "arrangement", other.name,
                                    other.file, other.line))
            own = self._options.get(key)
            if own:
                raise ValueError("%s:%d: unit %r names %s, which has its own alternative %r (%s:%d): a member moves with its "
                                 "unit, so give the unit that option" % (file, line, name, key, own[0].name, own[0].file,
                                                                          own[0].line))
            keys.append(key)
        group = Group(name, (), why, file, line, members=tuple(keys))
        self._arr_groups.append(group)
        self._group_after[name] = len(self._intents)
        self._arrangement_enum = None
        return group

    def _refuse_taken_unit(self, name: str) -> None:
        taken = next((g for g in self._arr_groups if g.name == name), None)
        if taken is not None:
            raise ValueError("a unit or arrangement %r is already declared (%s:%d)" % (name, taken.file, taken.line))

    def _unit_holding(self, key: str):
        """The unit board.unit declared with `key` as a member, or None."""
        return next((g for g in self._arr_groups if key in g.members), None)

    def exclude(self, *choices, why: str = "") -> Exclusion:
        """Every combination that holds all of `choices` is not laid out. A choice is `item.option`, `unit.option`, or a
        board.arrangement's name; two or more, checked where the script finishes declaring. For combinations the author knows
        cannot stand together, so the run does not prove them, and to bring a module under `place.arrangements_max` without
        dropping an option."""
        for c in choices:
            if not isinstance(c, str):
                raise TypeError("board.exclude takes choices as text ('item.option', 'unit.option' or a unit's name), "
                                "not %r" % (c,))
        rule = Exclusion(tuple(choices), why, *_script_site())
        self._exclusions.append(rule)
        self._arrangement_enum = None
        return rule

    def _unit_order(self) -> list:
        """Item keys with options and unit names, in the order the script first declared them: an item at its place(), a unit at
        its board.unit or board.arrangement call. With no unit: the items in place() order, as before units combined."""
        keyed = [((i.index, 1, 0), i.key) for i in self._intents if i.key in self._options]
        keyed += [((self._group_after[g.name], 0, n), g.name) for n, g in enumerate(self._arr_groups)]
        return [k for _, k in sorted(keyed)]

    def arrangement_units(self) -> list:
        """The units of this module's arrangements, in the order the script declared them (arrangements.units)."""
        return units(self._unit_order(), self._options, self._arr_groups)
```

`arrangement_enumeration` (lines 3470-3474): replace the `else` branch with:

```python
            else:
                self._arrangement_enum = enumerate_specs(self._unit_order(), self._options, self._arr_groups,
                                                         self.settings.place_arrangement_options_max,
                                                         self.settings.place_arrangements_max, tuple(self._exclusions))
```

`finish_declarations` (line 3488): the line `order = [i.key for i in sorted(...) if i.key in self._options]` becomes the two lines

```python
        self._check_units()
        order = self._unit_order()
```

and add after `finish_declarations`:

```python
    def _check_units(self) -> None:
        """What the declarations make only once they are all in: a unit with no option, a unit named as an item with options,
        and each exclusion. Each an error of the script with its declaration's line."""
        for g in self._arr_groups:
            if not g.positional and not g.alternatives:
                raise ValueError("%s:%d: unit %r has no option: give it one with board.alternative(%s, name, Alt(...), ...), "
                                 "or drop the unit" % (g.file, g.line, g.name, g.name))
            if g.name in self._options:
                raise ValueError("%s:%d: unit %r has the name of an item with options of its own, so their ids would be one: "
                                 "name the unit for what it is" % (g.file, g.line, g.name))
        choice = {c.id: u for u in self.arrangement_units() for c in u.choices}
        for e in self._exclusions:
            where = "%s:%d: board.exclude(%s)" % (e.file, e.line, ", ".join(repr(c) for c in e.choices))
            if len(e.choices) < 2:
                raise ValueError("%s: an exclusion names two or more choices that cannot stand together; to drop one option, "
                                 "delete its declaration" % where)
            unknown = [c for c in e.choices if c not in choice]
            if unknown:
                raise ValueError("%s: %s is not a choice of this module; its choices: %s"
                                 % (where, ", ".join(unknown), ", ".join(choice) or "none"))
            for i, a in enumerate(e.choices):
                for b in e.choices[i + 1:]:
                    u, v = choice[a], choice[b]
                    if u.name == v.name:
                        raise ValueError("%s: %s and %s are both options of %s, which takes one at a time, so no arrangement "
                                         "holds both" % (where, a, b, u.name))
                    if u.moves & v.moves:
                        raise ValueError("%s: %s and %s both move %s, so they never combine and there is nothing to exclude"
                                         % (where, a, b, ", ".join(sorted(u.moves & v.moves))))
```

`refuse_board_alternatives` (lines 3513-3514): the `sites` list becomes

```python
        sites = [(o.file, o.line, "board.alternative") for opts in self._options.values() for o in opts] + \
            [(g.file, g.line, "board.unit" if g.members else "board.arrangement") for g in self._arr_groups] + \
            [(go.file, go.line, "board.alternative") for g in self._arr_groups for go in g.alternatives] + \
            [(e.file, e.line, "board.exclude") for e in self._exclusions]
```

`_SITED` (lines 10738-10739) becomes:

```python
    "alternative": lambda b, out, a, k: ["%s.%s" % (out.group if isinstance(out, GroupOption) else out.item, out.name)],
    "arrangement": lambda b, out, a, k: [out.name],
    "unit": lambda b, out, a, k: [out.name],
    "exclude": lambda b, out, a, k: ["+".join(out.choices)],
```

`arrangement_run.py:117`:

```python
    moved = set(board._options) | {k for g in board._arr_groups for k in g.moves()}
```

`runner.py:371-372`: swap the two calls, so a board script that declares a unit with no option is told first that units are a module's:

```python
        board.refuse_board_alternatives()               # an alternative on a board that is not a module
        board.finish_declarations()                     # an only= naming no arrangement is the script's error
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_unit_declarations.py tests/test_arrangement_units.py tests/test_arrangement_declarations.py tests/test_arrangement_only.py tests/test_arrangement_extent.py tests/test_arrangement_resolve.py tests/test_builder_golden.py -n 2 -p no:cacheprovider -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py src/placemat/arrangement_run.py src/placemat/runner.py tests/test_arrangement_unit_declarations.py tests/test_arrangement_declarations.py
git commit -m "Arrangements: board.unit with options, board.exclude, and units ordered as the script declares them"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 3: The run records excluded combinations and dead options; the limit counts exclusions

**Files:**
- Modify: `src/placemat/findings.py:125` (new cause after `ARRANGEMENT_EXTENT_FIXED`)
- Modify: `src/placemat/finding_text.py:791-800` (`arrangement_row_text`), `:803-810` (`_arrangement_limit`), after `:847-849` (`_arrangement_option_dead`), `:875-891` (`subject`), `:957` (`FACTS_V`)
- Modify: `src/placemat/arrangement_run.py:19-24` (`Prepared`), `:48-51` (`begin`), `:375` (`finish`: before the default's copy), `:383-394` (`lines`), new functions after `verdict_refusals` (`:164-165`)
- Test: `tests/test_arrangement_combine_run.py` (new); `tests/test_finding_text.py:167-174` (samples); `tests/test_arrangement_resolve.py:247-249` (the record it builds now also has a dead option)

**Interfaces:**
- Consumes: Task 1 `Unit`, `Choice`, `Enumeration.excluded`; Task 2 `Board.arrangement_units()`, `Board.unit`, `Board.alternative(unit, ...)`, `Board.exclude`.
- Produces:
  - `FindingCause.ARRANGEMENT_OPTION_DEAD` (`arrangement.option_dead`, warning) with facts `{"unit": str, "option": str, "choice": str, "refused": [id, ...], "reasons": {id: [refusal record, ...]}}`; `finding_text.subject` gives `choice`.
  - `arrangement.limit` facts `{"variant", "arrangements", "max_arrangements", "options", "max_options", "excluded": int}`, facts version 2.
  - `arrangement_run.Prepared(board, saved, specs, rows=[], units=[], excluded=())`.
  - `arrangement_run.excluded_entries(excluded) -> list[dict]`: `{"id", "choices", "offered": False, "excluded": {"why": str, "by": [str]}}`.
  - `arrangement_run.option_dead_findings(units, record) -> list[Finding]`.
  - `arrangement_run.lines(record)` rows gain `{"id", "state": "excluded", "why", "by"}`; `finding_text.arrangement_row_text` renders it.
  - `run.json`'s `arrangements` gains the excluded entries after the laid-out ones.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_combine_run.py
"""The module run over combined units: a combination of two options that cannot stand together is refused alone; an option
refused in every combination that holds it is `arrangement.option_dead`; an excluded combination is recorded, not laid out; the
limit counts after exclusions."""
import dataclasses

from placemat import Alt, arrangement_run as run
from placemat.finding_text import arrangement_row_text, subject
from placemat.findings import Finding, FindingCause as C
from placemat.settings import Settings
from placemat.values import Beside, Edge, Part
from tests.arrangement_support import module

FIXED = {"form": "finding", "cause": "fixed.part", "item": "r_pull"}
UNPLACED = {"form": "unplaced", "item": "r_pull"}


def colliding(settings=None):
    """Two units of one part each whose `upright` stands the part north of u1, turned: each alone fits, the two together take
    one spot and collide. (Without the turn, Beside would stand the second part further out.)"""
    b = module(settings)
    b.keep_going = True                 # a collision is a finding, not the end of the resolve
    cap = b.unit("cap", Part("c_in"), why="the bypass may stand upright north of u1")
    b.alternative(cap, "upright", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH), rotation=90))
    pull = b.unit("pull", Part("r_pull"), why="the pull-up may stand upright north of u1")
    b.alternative(pull, "upright", Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.NORTH), rotation=90))
    return b


def entry(ident, choices, offered, **more):
    return dict({"id": ident, "choices": choices, "offered": offered}, **more)


DEFAULT = entry("default", {}, True)


def test_two_options_that_cannot_stand_together_refuse_only_their_combination():
    prepared = run.begin(colliding())
    assert [s.id for s in prepared.specs] == ["default", "pull.upright", "cap.upright", "cap.upright+pull.upright"]
    default = run.resolve_spec(prepared, prepared.specs[0])
    refusals = {s.id: run.plan_refusals(run.resolve_spec(prepared, s), default) for s in prepared.specs}
    assert refusals["default"] == [] and refusals["pull.upright"] == [] and refusals["cap.upright"] == []
    assert refusals["cap.upright+pull.upright"]


def test_a_refused_combination_whose_options_stand_elsewhere_is_no_dead_option():
    """Review focus 5."""
    units = colliding().arrangement_units()
    record = [DEFAULT, entry("pull.upright", {"pull": "upright"}, True), entry("cap.upright", {"cap": "upright"}, True),
              entry("cap.upright+pull.upright", {"cap": "upright", "pull": "upright"}, False, refused=[FIXED])]
    assert run.option_dead_findings(units, record) == []


def test_an_option_refused_in_every_combination_that_holds_it_is_dead_with_its_refusals():
    units = colliding().arrangement_units()
    record = [DEFAULT, entry("pull.upright", {"pull": "upright"}, False, refused=[UNPLACED]), entry("cap.upright", {"cap": "upright"}, True),
              entry("cap.upright+pull.upright", {"cap": "upright", "pull": "upright"}, False, refused=[FIXED])]
    (f,) = run.option_dead_findings(units, record)
    assert f.cause is C.ARRANGEMENT_OPTION_DEAD and f.severity == "warning"
    assert f.facts == {"unit": "pull", "option": "upright", "choice": "pull.upright", "refused": ["pull.upright", "cap.upright+pull.upright"],
                       "reasons": {"pull.upright": [UNPLACED], "cap.upright+pull.upright": [FIXED]}}
    assert subject(f.cause, f.facts) == "pull.upright"


def test_a_duplicate_is_not_a_refusal_and_an_excluded_combination_does_not_count():
    """Review focus 5."""
    units = colliding().arrangement_units()
    duplicate = [DEFAULT, entry("pull.upright", {"pull": "upright"}, False, duplicate_of="default"),
                 entry("cap.upright", {"cap": "upright"}, True),
                 entry("cap.upright+pull.upright", {"cap": "upright", "pull": "upright"}, False, refused=[FIXED])]
    assert run.option_dead_findings(units, duplicate) == []
    excluded = [DEFAULT, entry("pull.upright", {"pull": "upright"}, False, refused=[UNPLACED]), entry("cap.upright", {"cap": "upright"}, True),
                entry("cap.upright+pull.upright", {"cap": "upright", "pull": "upright"}, False, excluded={"why": "", "by": []})]
    (f,) = run.option_dead_findings(units, excluded)
    assert f.facts["refused"] == ["pull.upright"] and list(f.facts["reasons"]) == ["pull.upright"]


def test_an_excluded_combination_is_recorded_with_its_why_and_not_laid_out():
    b = colliding()
    b.exclude("cap.upright", "pull.upright", why="both stand north of u1")
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default", "pull.upright", "cap.upright"]
    assert [u.name for u in prepared.units] == ["cap", "pull"]
    gone = run.excluded_entries(prepared.excluded)
    assert gone == [{"id": "cap.upright+pull.upright", "choices": {"cap": "upright", "pull": "upright"}, "offered": False,
                     "excluded": {"why": "both stand north of u1", "by": ["cap.upright", "pull.upright"]}}]
    rows = run.lines([DEFAULT] + gone)
    assert rows[1] == {"id": "cap.upright+pull.upright", "state": "excluded", "why": "both stand north of u1",
                       "by": ["cap.upright", "pull.upright"]}
    assert arrangement_row_text(rows[1]) == "cap.upright+pull.upright: excluded, not laid out: both stand north of u1"
    assert arrangement_row_text(dict(rows[1], why="")) == "cap.upright+pull.upright: excluded, not laid out"


def test_the_limit_is_counted_after_exclusions_and_its_finding_says_how_to_come_under_it():
    tight = dataclasses.replace(Settings(), place_arrangements_max=3)
    facts = colliding(tight).arrangement_limit()
    assert facts == {"variant": "arrangements", "arrangements": 4, "max_arrangements": 3, "options": {"cap": 2, "pull": 2},
                     "max_options": 4, "excluded": 0}
    assert str(Finding(C.ARRANGEMENT_LIMIT, facts)) == (
        "this module declares 4 arrangements, over the 3 place.arrangements_max allows, so only the default is laid out; "
        "leave out the combinations that do not matter with board.exclude")
    b = colliding(tight)
    b.exclude("cap.upright", "pull.upright")
    assert b.arrangement_limit() is None and len(b.arrangement_specs()) == 3
```

In `tests/test_finding_text.py` replace the two `ARRANGEMENT_LIMIT` samples (lines 167-174) with:

```python
    (C.ARRANGEMENT_LIMIT, {"variant": "arrangements", "arrangements": 12, "max_arrangements": 8,
                           "options": {"c_in": 3, "r_pull": 2, "pair": 2}, "max_options": 4, "excluded": 0},
     "this module declares 12 arrangements, over the 8 place.arrangements_max allows, so only the default is laid out; "
     "leave out the combinations that do not matter with board.exclude"),
    (C.ARRANGEMENT_LIMIT, {"variant": "arrangements", "arrangements": 10, "max_arrangements": 8,
                           "options": {"c_in": 3, "r_pull": 2, "pair": 2}, "max_options": 4, "excluded": 2},
     "this module declares 10 arrangements once its exclusions leave out 2, over the 8 place.arrangements_max allows, so only "
     "the default is laid out; leave out the combinations that do not matter with board.exclude"),
    (C.ARRANGEMENT_LIMIT, {"variant": "options", "arrangements": 6, "max_arrangements": 8,
                           "options": {"c_in": 5}, "max_options": 4, "excluded": 0},
     "c_in has 5 options, over the 4 place.arrangement_options_max allows, so only the default is laid out; drop one"),
    (C.ARRANGEMENT_OPTION_DEAD, {"unit": "pair", "option": "upright", "choice": "pair.upright",
                                 "refused": ["pair.upright", "pair.upright+r_far.turned"],
                                 "reasons": {"pair.upright": [{"form": "drc", "bucket": "clearance", "count": 2}],
                                             "pair.upright+r_far.turned": [{"form": "unplaced", "item": "r_far"}]}},
     "pair.upright is refused in every arrangement that holds it, so the board is never offered it: pair.upright for DRC "
     "clearance x2; pair.upright+r_far.turned for r_far is not placed; fix it or drop it"),
```

In `tests/test_arrangement_resolve.py`, `test_a_note_the_setting_leaves_no_room_for_refuses_its_arrangement_with_a_finding` hands
`finish` one arrangement, `r_pull.turned`, which its note refuses; that option is then refused in every arrangement the record
holds, so `finish` also raises `arrangement.option_dead`. Replace lines 247-249 with:

```python
    f, dead = out.findings
    assert f.cause == "arrangement.refused" and f.facts["id"] == "r_pull.turned" and f.severity == "warning"
    assert "place.arrangement_note_chars" in str(f)
    assert dead.cause == "arrangement.option_dead" and dead.facts["refused"] == ["r_pull.turned"]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_combine_run.py tests/test_finding_text.py -n 2 -p no:cacheprovider -q`
Expected: FAIL (`AttributeError: ARRANGEMENT_OPTION_DEAD`, `module 'placemat.arrangement_run' has no attribute 'option_dead_findings'`).

- [ ] **Step 3: Implement**

`findings.py`, after line 125:

```python
    ARRANGEMENT_OPTION_DEAD = (FindingKind.ARRANGEMENT, "arrangement.option_dead")
```

`finding_text.py`: `arrangement_row_text` (line 791) gains, as its first branch after `state = row["state"]`:

```python
    if state == "excluded":
        return "%s: excluded, not laid out%s" % (row["id"], ": " + row["why"] if row["why"] else "")
```

Replace `_arrangement_limit` (lines 803-810) with:

```python
@renders(C.ARRANGEMENT_LIMIT, "variant", "arrangements", "max_arrangements", "options", "max_options", "excluded")
def _arrangement_limit(f):
    if f["variant"] == "options":
        unit, n = max(f["options"].items(), key=lambda kv: (kv[1], kv[0]))
        return "%s has %d options, over the %d place.arrangement_options_max allows, so only the default is laid out; drop one" % (
            unit, n, f["max_options"])
    after = " once its exclusions leave out %d" % f["excluded"] if f["excluded"] else ""
    return ("this module declares %d arrangements%s, over the %d place.arrangements_max allows, so only the default is laid out; "
            "leave out the combinations that do not matter with board.exclude" % (f["arrangements"], after, f["max_arrangements"]))
```

After `_arrangement_extent_fixed` (line 849):

```python
@renders(C.ARRANGEMENT_OPTION_DEAD, "unit", "option", "choice", "refused", "reasons")
def _arrangement_option_dead(f):
    each = "; ".join("%s for %s" % (i, ", ".join(refusal_record_text(r) for r in f["reasons"][i])) for i in f["refused"])
    return "%s is refused in every arrangement that holds it, so the board is never offered it: %s; fix it or drop it" % (
        f["choice"], each)
```

`subject` (line 885), before `for k in _SUBJECT_KEYS:`:

```python
    if cause is C.ARRANGEMENT_OPTION_DEAD:
        return facts["choice"]
```

After line 957:

```python
FACTS_V[C.ARRANGEMENT_LIMIT] = 2        # excluded: how many combinations the module's exclusions leave out
```

`arrangement_run.py`: `Prepared` (lines 19-24) becomes

```python
@dataclass
class Prepared:
    board: object
    saved: tuple                # Board._snapshot() once the declarations are finished, before any arrangement is laid
    specs: tuple                # arrangements.Spec, the default first
    rows: list = field(default_factory=list)    # _row_state then
    units: list = field(default_factory=list)   # arrangements.Unit, in the order declared
    excluded: tuple = ()        # (Spec, Exclusion): the combinations an exclusion leaves out
```

`begin` (lines 48-51):

```python
def begin(board) -> Prepared:
    """The board as its script left it, checked and snapshotted, with the arrangements its declarations make and the ones its
    exclusions leave out."""
    board.finish_declarations()
    return Prepared(board, board._snapshot(), board.arrangement_specs(), _row_state(board), board.arrangement_units(),
                    board.arrangement_enumeration().excluded)
```

After `verdict_refusals` (line 165):

```python
def excluded_entries(excluded) -> list:
    """The record's entries of the combinations an exclusion leaves out, in product order: not laid out, so no folder, metrics or
    extent; `excluded` holds the exclusion's why and its choices."""
    return [{"id": spec.id, "choices": spec.choices, "offered": False, "excluded": {"why": rule.why, "by": list(rule.choices)}}
            for spec, rule in excluded]


def option_dead_findings(units, record) -> list:
    """`arrangement.option_dead` for each unit's choice that every laid-out combination holding it was refused in (an excluded
    combination is not counted; a duplicate is not a refusal), with each one's refusals."""
    out = []
    for u in units:
        for c in u.choices:
            held = [e for e in record if e["choices"].get(c.unit) == c.option and not e.get("excluded")]
            if held and all(e.get("refused") for e in held):
                out.append(Finding(C.ARRANGEMENT_OPTION_DEAD,
                                   {"unit": c.unit, "option": c.option, "choice": c.id, "refused": [e["id"] for e in held],
                                    "reasons": {e["id"]: e["refused"] for e in held}}, "warning"))
    return out
```

`finish`, before `d = _dir(run_dir, "default")` (line 375):

```python
    record += excluded_entries(prepared.excluded)
    findings += option_dead_findings(prepared.units, record)
```

`lines` (lines 383-394): the loop's first branch becomes

```python
        if a.get("excluded"):
            out.append({"id": a["id"], "state": "excluded", "why": a["excluded"]["why"], "by": a["excluded"]["by"]})
        elif a.get("duplicate_of"):
```

and its docstring names the `excluded` state (with `why` and `by`).

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_combine_run.py tests/test_finding_text.py tests/test_no_sentence_parsing.py tests/test_suggestion_cases.py tests/test_finding_kinds.py tests/test_arrangement_proof.py tests/test_arrangement_unit_declarations.py tests/test_arrangement_resolve.py -n 2 -p no:cacheprovider -q`
Expected: PASS (`test_every_cause_has_a_sample` included).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/findings.py src/placemat/finding_text.py src/placemat/arrangement_run.py tests/test_arrangement_combine_run.py tests/test_finding_text.py tests/test_arrangement_resolve.py
git commit -m "Arrangements: an option refused in every combination is arrangement.option_dead; run.json lists the excluded combinations"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 4: The studio shows an excluded combination

**Files:**
- Modify: `src/placemat/studio.py:1480-1481` (run summary)
- Modify: `src/placemat/studio_page.html:4066-4068` (run detail)
- Test: `tests/test_arrangement_studio.py` (append)

**Interfaces:**
- Consumes: Task 3's record entry `{"excluded": {"why", "by"}}`.
- Produces: the run summary's arrangement row `{"id", "offered", "refused": int, "duplicate_of"?, "excluded"?: True}`; the page's run detail writes `<span class="chip notice">id</span> excluded`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_arrangement_studio.py`:

```python
@needs_node
def test_the_run_detail_says_a_combination_was_excluded(tmp_path):
    out = _in_page(tmp_path, r"""
o.html = runDetail({drc: {}, severities: {}, timing: {}, verdicts: [], failure: null,
  arrangements: [{id: "default", offered: true, refused: 0},
                 {id: "pair.upright+caps_upright", offered: false, refused: 0, excluded: true}]});
""")
    h = out["html"]
    assert '<span class="chip notice">pair.upright+caps_upright</span> excluded' in h      # by design: a notice, never red or grey
    assert "chip bad" not in h and "refused 0" not in h


def test_a_run_summary_marks_an_excluded_combination(tmp_path):
    from placemat.report import RunRecord
    from placemat.studio import Studio
    rec = RunRecord(run_id="r1", board="b", status="ok")
    rec.arrangements = [{"id": "default", "choices": {}, "offered": True},
                        {"id": "pair.upright+caps_upright", "choices": {"pair": "upright", "caps_upright": "caps_upright"},
                         "offered": False, "excluded": {"why": "both stand", "by": ["pair.upright", "caps_upright"]}}]
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    rec.save(run / "run.json")
    s = Studio.__new__(Studio)
    s._run_cache, s.cfg = {}, None
    s.runs_dir = lambda: tmp_path / "runs"
    assert s.run_summary(run / "run.json")["arrangements"] == [
        {"id": "default", "offered": True, "refused": 0},
        {"id": "pair.upright+caps_upright", "offered": False, "refused": 0, "excluded": True}]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_studio.py -n 2 -p no:cacheprovider -q`
Expected: FAIL (the summary has no `excluded`; the page says `refused 0`).

- [ ] **Step 3: Implement**

`studio.py:1480-1481`:

```python
               "arrangements": [{"id": a["id"], "offered": a["offered"], "refused": len(a.get("refused") or ()),
                                 **({"duplicate_of": a["duplicate_of"]} if a.get("duplicate_of") else {}),
                                 **({"excluded": True} if a.get("excluded") else {})} for a in (rec.arrangements or [])],
```

`studio_page.html:4066-4068`:

```js
  // a module run's arrangements: offered, refused by its proof (a warning), laid out as another one, or excluded by the script
  const arrs = (r.arrangements || []).map(a => "<div>" + pill(a.id, a.duplicate_of || a.excluded ? "notice" : a.offered ? "good" : "warn") + " " +
    esc(a.duplicate_of ? "same as " + a.duplicate_of : a.excluded ? "excluded" : a.offered ? "offered" : "refused " + a.refused) + "</div>").join("");
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_studio.py tests/test_studio_page.py -n 2 -p no:cacheprovider -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/studio.py src/placemat/studio_page.html tests/test_arrangement_studio.py
git commit -m "Studio: a run's arrangement list shows an excluded combination as a notice"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 5: A real module written for 0.99.15 keeps its ids and places, and an exclusion runs end to end

**Files:**
- Test: `tests/test_arrangement_run.py` (append); `tests/slow_tests.txt` (two node ids, after the file's other `tests/test_arrangement_run.py` lines)

**Interfaces:**
- Consumes: the whole of Tasks 1-3 through `tests/real_modules.run` (the module run as `placemat run` does it); `with_alternatives` and `ALTERNATIVES` already in the file.
- Produces: nothing new; the end-to-end check of the required properties.

- [ ] **Step 1: Write the tests**

Append to `tests/test_arrangement_run.py`:

```python
MARK = "frame_planes(FILLET, supply=None)"

# The 0.99.15 form of ALTERNATIVES: r_rt's move as a one-option unit (board.arrangement), c_vcc's turn as an item's option.
GROUPED = '''
from placemat import Alt
board.alternative(Part("c_vcc"), "turned", rotation=LYING)
board.arrangement("rt_apart", Alt(Part("r_rt"), at=Beside(Part("buck"), Edge.SOUTH, gap=0.6, align=("RT_5V", pin(RT_PIN)))),
                  why="RT's resistor a little further south")
'''


def with_grouped(text: str) -> str:
    return text.replace(MARK, GROUPED + MARK, 1)


def _member_poses(pcb) -> dict:
    from placemat.kicad.read import read_board
    return {fp.inst: (round(fp.location.x, 4), round(fp.location.y, 4), round(fp.rotation % 360.0, 3), fp.face)
            for fp in read_board(pcb).footprints}


def test_a_module_written_for_0_99_15_keeps_its_ids_and_places_and_gains_the_combination(tmp_path):
    """A board.arrangement laid alone lays as the same move made an item's option does, so the arrangement form and the item
    form of one module agree arrangement by arrangement; its 0.99.15 ids are made, and its combination with the item is added."""
    items, _, _ = real_modules.run(tmp_path / "items", "usb5v", edit=with_alternatives)
    grouped, _, _ = real_modules.run(tmp_path / "grouped", "usb5v", edit=with_grouped)
    rec = json.loads((grouped.run_dir / "run.json").read_text())
    assert [a["id"] for a in rec["arrangements"]] == ["default", "rt_apart", "c_vcc.turned", "c_vcc.turned+rt_apart"]
    assert rec["arrangements"][1]["choices"] == {"rt_apart": "rt_apart"}
    same = {"default": "default", "rt_apart": "r_rt.apart", "c_vcc.turned": "c_vcc.turned",
            "c_vcc.turned+rt_apart": "c_vcc.turned+r_rt.apart"}
    for mine, theirs in same.items():
        assert _member_poses(grouped.run_dir / "arrangements" / mine / "layout.kicad_pcb") == \
            _member_poses(items.run_dir / "arrangements" / theirs / "layout.kicad_pcb"), mine
    assert [a["id"] for a in rec["arrangements"] if a["offered"]] == ["default", "rt_apart"]
    dead = [f["facts"] for f in rec["finding_details"] if f["cause"] == "arrangement.option_dead"]
    assert [(d["choice"], d["refused"]) for d in dead] == [("c_vcc.turned", ["c_vcc.turned", "c_vcc.turned+rt_apart"])]


def test_an_exclusion_is_not_laid_out_and_the_record_says_why(tmp_path):
    rule = '\nboard.exclude("c_vcc.turned", "rt_apart", why="the turned capacitor and the moved resistor are not wanted together")\n'
    result, _, _ = real_modules.run(tmp_path, "usb5v", edit=lambda t: with_grouped(t).replace(MARK, rule + MARK, 1))
    rec = json.loads((result.run_dir / "run.json").read_text())
    assert [a["id"] for a in rec["arrangements"] if not a.get("excluded")] == ["default", "rt_apart", "c_vcc.turned"]
    (gone,) = [a for a in rec["arrangements"] if a.get("excluded")]
    assert gone == {"id": "c_vcc.turned+rt_apart", "choices": {"c_vcc": "turned", "rt_apart": "rt_apart"}, "offered": False,
                    "excluded": {"why": "the turned capacitor and the moved resistor are not wanted together",
                                 "by": ["c_vcc.turned", "rt_apart"]}}
    assert not (result.run_dir / "arrangements" / "c_vcc.turned+rt_apart").exists()
    dead = [f["facts"] for f in rec["finding_details"] if f["cause"] == "arrangement.option_dead"]
    assert [(d["choice"], d["refused"]) for d in dead] == [("c_vcc.turned", ["c_vcc.turned"])]   # the excluded one is not counted
```

Add to `tests/slow_tests.txt`, after the last `tests/test_arrangement_run.py::` line:

```
tests/test_arrangement_run.py::test_a_module_written_for_0_99_15_keeps_its_ids_and_places_and_gains_the_combination
tests/test_arrangement_run.py::test_an_exclusion_is_not_laid_out_and_the_record_says_why
```

- [ ] **Step 2: Run them, under the lock, one at a time with nothing else real running**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock env PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest "tests/test_arrangement_run.py::test_a_module_written_for_0_99_15_keeps_its_ids_and_places_and_gains_the_combination" "tests/test_arrangement_run.py::test_an_exclusion_is_not_laid_out_and_the_record_says_why" --full -n 2 -p no:cacheprovider -q`
Expected: PASS. These are written after Tasks 1-3, so they pass on first run; a failure is a fault in those tasks, not in the test: find it before going on. If `c_vcc.turned+rt_apart` is offered (the item form's `c_vcc.turned+r_rt.apart` was refused when this plan was written), say so to the user rather than editing the expected ids.

- [ ] **Step 3: The module's other run tests, unchanged**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock env PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_run.py tests/test_arrangement_real_module.py --full -n 2 -p no:cacheprovider -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_arrangement_run.py tests/slow_tests.txt
git commit -m "Test: a module written for 0.99.15 keeps its arrangements and gains the combination; an exclusion on a real module"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 6: Skill, api.md and the migration entry

**Files:**
- Modify: `src/placemat/settings.py:130-133` (the two limits' docs, and the default of `place.arrangements_max`, 8 to 16) and `skills/placemat/references/api.md` settings table (regenerated)
- Modify: `skills/placemat/SKILL.md:728-795` ("Arrangements")
- Modify: `skills/placemat/references/api.md:1023-1101` (declarations, ids, limits), `:1109-1119` (after the proof's refusal paragraph), `:1129-1160` (the record), `:1777-1799` ("Groups on the written board"), `:4395-4397` (severities)
- Modify: `skills/placemat/references/migration.md:8-17` ("## Unreleased")
- Modify: `docs/superpowers/skill-checks/arrangements.md:50-52`, `fixtures/skill_check.py:3` (what the transcript is read for)
- Test: `tests/test_arrangement_declarations.py` (append); `tests/test_arrangement_settings.py:11` (the default is 16)

**Interfaces:**
- Consumes: the forms, ids, facts and record of Tasks 1-4, as built.
- Produces: documentation only.

- [ ] **Step 1: Write the failing test**

In `tests/test_arrangement_settings.py` line 11, `assert s.place_arrangements_max == 8` becomes `assert s.place_arrangements_max == 16`
(the next test sets `arrangements_max = 5` itself and is unchanged).

Append to `tests/test_arrangement_declarations.py`:

```python
def test_the_skill_and_api_document_units_exclusions_and_dead_options():
    section = API.split("**Arrangements.**", 1)[1].split("**How a searched item finds its place.**")[0]
    for word in ("board.unit(", "board.alternative(unit", "board.exclude(", "arrangement.option_dead", '"excluded"',
                 "unit.option", "never combine", "(default 16)"):
        assert word in section, word
    for word in ("arrangement.option_dead", "board.exclude", "board.unit", "needs no action"):
        assert word in SKILL, word
    unreleased = (_SKILLS / "references/migration.md").read_text().split("## Unreleased", 1)[1].split("\n## To ", 1)[0]
    for word in ("board.unit", "board.exclude", "arrangement.option_dead", "re-run", "keeps its id", "place.arrangements_max", "16"):
        assert word in unreleased, word
    assert unreleased.count("### Changed") == 1 and unreleased.count("### New") == 1
    assert "A bypass capacitor's alternative is a turn at its pin" in unreleased       # the entry already there is kept
    assert all(ord(c) < 128 for c in SKILL + API + unreleased), "ASCII only"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_declarations.py -n 2 -p no:cacheprovider -q`
Expected: FAIL on `board.unit(`.

- [ ] **Step 3: Write the docs**

`settings.py:130-133`, the two docs:

```python
    place_arrangement_options_max: int = S(4, "count",
        "the most options one item or unit of a module may have, its default included; a module that declares more is not partly accepted: its run lays out the default only and says so")
    place_arrangements_max: int = S(16, "count",
        "the most arrangements a module may have, the default included: every combination of its items' and units' options, less those board.exclude leaves out")
```

Then regenerate the table (the `place.arrangements_max` row now shows `16`): `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m placemat settings --markdown > /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/settings.md` and paste it between `<!-- settings-table:begin -->` and `<!-- settings-table:end -->` in `api.md`.

`api.md`, "Arrangements." (lines 1032-1095). Replace the code block and the bullets from `- \`board.alternative(item, name, **keywords)\`` through the Limits paragraph (ending `` `place.arrangements = false` lays out the default only without a finding.``) with:

````markdown
```python
board.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST), why="bypass at VIN")
board.alternative(Part("r_pull"), "turned", rotation=180)

pair = board.unit("pair", Part("c1"), Part("r1"), why="the filter pair moves as one")
board.alternative(pair, "flat",
                  Alt(Part("c1"), rotation=0),
                  Alt(Part("r1"), at=Beside(Part("c1"), Edge.EAST)))
board.alternative(pair, "upright",
                  Alt(Part("c1"), rotation=90),
                  Alt(Part("r1"), at=Beside(Part("c1"), Edge.NORTH)))

board.arrangement("mirrored",
                  Alt(Part("q1"), at=Beside(Part("u1"), Edge.EAST), rotation=180),
                  Alt(Part("q2"), at=Beside(Part("u1"), Edge.WEST)),
                  why="gate toward the east tab")

board.exclude("pair.upright", "mirrored", why="both stand in the one column")
```

- `board.alternative(item, name, **keywords)` adds an option to the
  item's `place()`, which stays its default option. An option takes the
  keywords of `place()` that say where an item goes (`at=`, `rotation=`,
  `rotations=`, `face=`, `radius=`, `step=`) and `why=`; every keyword
  it does not give is the item's own, so `rotation=180` alone keeps the
  `at=`. The item is a part the script has placed with `place()`: a part
  of a row, ring or block, and a cell, are refused. A searched item may
  have options too, as each arrangement is a full resolve.
- `board.unit(name, *members, why="")` declares a unit: parts the
  script has placed with `place()` that move as one. Its default is
  each member's own `place()`. `board.alternative(unit, name, *alts,
  why="")` adds one option to it, one call per option: an `Alt(member,
  **keywords)` (the keywords of `alternative`) for each member it moves,
  each at most once; a member it does not name keeps its `place()`. A
  unit's alternative takes `Alt`s and no place keywords; an item's takes
  keywords and no `Alt`s. Option names are unique within the unit. A
  unit with no option is an error where the script finishes declaring.
  Declare a unit's options when its members only make sense moving
  together; otherwise each member's own `alternative` gives more
  combinations for the same declarations.
- `board.arrangement(name, *alts, why="")` is a unit of the `Alt`s'
  members with one option, named as the unit: the form 0.99.15 had. Its
  id is its name.
- A part is in one unit only, and a member of a `board.unit` has no
  `alternative` of its own: a second unit naming it, an item's
  alternative on a unit's member, and a unit naming a part that has one
  are errors at the second call, each naming both declarations. A
  `board.arrangement` may name a part that has its own alternative, or
  that another `board.arrangement` names, as in 0.99.15: two units that
  move one part never combine.
- `board.exclude(*choices, why="")`: no combination holding all of
  `choices` is laid out. A choice is `item.option`, `unit.option`, or a
  `board.arrangement`'s name. Use it for combinations that cannot stand
  together, so the run does not prove them, and to bring a module under
  `place.arrangements_max` without dropping an option. Fewer than two
  choices, a choice the module does not declare, two options of one item
  or unit, and two choices that never combine are errors where the
  script finishes declaring, with the declaration's line.
- The units of a module are its items with options and its
  `board.unit`s, in the order the script declares them: an item at its
  `place()`, a unit at its `board.unit` or `board.arrangement`. Its
  arrangements are the
  default, then every combination of the units (each contributing its
  default and each option) in `itertools.product` order with the first
  unit changing slowest, less the excluded ones. A module with no unit
  has its items' combinations in `place()` order, as before.
- An arrangement's id is `default`, or its units' choices in unit order
  joined by `+`: `item.option`, `unit.option`, or a `board.arrangement`'s
  name (`pair.upright+r_pull.turned`, `mirrored+r_pull.turned`). Option
  and unit names are lower-case words, digits and `_`; `default` is
  refused, and a unit may not have the name of an item with options. The
  id is what the lock, findings, step notes, the studio and the board's
  `arrangements=` use. `choices` is the same as data, `{unit: option}`,
  with a `board.arrangement` as `{name: name}`.
- Two arrangements that lay out the same places and copper are one: the
  later is dropped with an `arrangement.duplicate` notice naming both.
````

and the Limits paragraph:

```markdown
Limits: `place.arrangement_options_max` (default 4) options per item or
unit, its default included, and `place.arrangements_max` (default 16)
arrangements per module, the default included, counted after
exclusions. A module over either is not partly accepted: the run lays
out the default only and raises `arrangement.limit` (facts: the counts,
both limits, and `excluded`, how many combinations the exclusions left
out). `place.arrangements = false` lays out the default only without a
finding.
```

(The `only=` paragraph between them is unchanged.)

After the paragraph that begins `Warnings, notices and measures are recorded, not refused.` and ends `` a chunk is not offered (`note_chars`). `` (lines 1109-1119), add:

```markdown
A combination is refused where two options cannot stand together; it
needs no action when each option is offered in some other combination.
An option refused in every combination that holds it, excluded ones not
counted, raises `arrangement.option_dead` (warning). Its facts are
`unit`, `option`, `choice` (the option as an id names it), `refused`
(the ids) and `reasons` (each id's refusals, as `arrangement.refused`
gives them). The board is never offered such an option: fix it or drop
it.
```

The `run.json` example (lines 1133-1141): the second entry's `"choices": {"group": "mirrored"}` becomes `"choices": {"mirrored": "mirrored"}`, and a third entry follows it:

```json
  {"id": "pair.upright+mirrored", "choices": {"pair": "upright", "mirrored": "mirrored"}, "offered": false,
   "excluded": {"why": "both stand in the one column", "by": ["pair.upright", "mirrored"]}}
```

and after the bullet on duplicates add:

```markdown
- A combination an exclusion leaves out has `offered` false and
  `excluded`, the exclusion's `why` and its choices (`by`), and no
  `dir`, `metrics` or `extent`: it is not laid out. These entries come
  after the laid-out ones, and `placemat run` prints each as excluded.
```

"Groups on the written board" (lines 1789-1799): the paragraph ends with one more sentence: `A module's parts that move as one unit of its arrangements are declared with \`board.unit\` (see "Arrangements"), not here.`

Severities (line 4395): the warning row becomes

```markdown
| `arrangement` (`arrangement.limit`, `arrangement.refused`, `arrangement.option_dead`, `arrangement.stale`) | warning | a module's alternatives over the limits, refused by the module's proof, an option refused in every combination, or ignored on the stamping board |
```

`SKILL.md`, "Arrangements":

- the bypass bullet's last sentence (lines 732-733), `A turn that fits only when a neighbour moves is a named group with that neighbour;`, becomes `A turn that fits only when a neighbour moves is a unit (\`board.unit\`) of the two, whose option turns one and moves the other;`
- lines 739-746 become:

```markdown
- the last run's `arrangement.extent_fixed` notices are all answered by one
  of the two, and no option is dead (`arrangement.option_dead`).

Only a part placed with its own `place()` takes an alternative. A row's
or ring's members move together through a unit (`board.unit`), not by
`alternative`, and a block's members take none. Place a member whose side
is free with `place()` beside its partner, so it can have one.
```

- the "Within the caps", "Names" and "Reading the report" bullets (lines 773-788) become:

```markdown
- **Within the caps.** `place.arrangement_options_max` options per item
  or unit and `place.arrangements_max` arrangements per module, every
  combination counted. Prefer a few alternatives on the members that
  matter. Declare a unit's options (`board.unit`) when its members
  only make sense moving together; otherwise each member's own
  `alternative` gives more combinations for the same declarations.
  Leave out with `board.exclude` a combination you can see is bad,
  rather than letting the run refuse it: each refused combination costs
  a full proof. Use `only=` for copper that exists in some arrangements.
- **Names.** An option is named for what it does (`east`, `turned`,
  `back`, `upright`), a unit for what it is (`pair`, `mirrored`), never
  `alt1`: ids (`pair.upright+r_pull.turned`) appear in the board
  script's `arrangements=`, in the lock, in step notes and in the
  studio.
- **Reading the report.** After the module run read `run.json`'s
  `arrangements` and the `arrangement.refused`,
  `arrangement.option_dead` and `arrangement.limit` findings. A refused
  combination is expected where two options cannot stand together, and
  needs no action when each option is offered in some other
  combination; exclude it when you can see why. An
  `arrangement.option_dead` names an option refused in every
  combination that holds it: read its refusals, then fix the option (a
  `gap=`, a different anchor, `only=` for a track that cannot exist
  there) or drop it. A module is not finished with a dead option.
```

`migration.md`, "## Unreleased": add to the existing "### Changed", after the bypass entry:

```markdown
- **A module's units combine with its other items and units.** `board.arrangement(name, Alt(...), ...)` is now a unit
  with one option. It keeps its id, its name, so a lock, an `arrangements=` or an `only=` written under 0.99.15 names the
  same arrangement; a module run now also lays it out combined with every item and unit that moves none of its parts
  (`mirrored+r_pull.turned`). The arrangements are listed in product order, so a unit declared after the items comes
  early in the list, and a board breaks a tie between two of them in that order. A unit counts toward
  `place.arrangements_max` as an item with one option does, and the default of `place.arrangements_max` is now 16,
  up from 8, since a unit multiplies the count where a `board.arrangement` added one; a project that sets its own
  value keeps it, and a module over the limit lays out the default only (`arrangement.limit`), which `board.exclude`
  brings it back under. `choices` of a
  `board.arrangement` is `{name: name}` where it was `{"group": name}`. A part in a `board.unit` may not have its own
  `board.alternative`. An option refused in every arrangement that holds it now also raises `arrangement.option_dead`. A
  board needs no change; a module offers the new combinations once it is run again (a re-run writes them into its
  fragment).
```

and after it a new section:

```markdown
### New

- **Units with options, and exclusions.** `board.unit(name, Part(...), Part(...), why=)` declares parts that move as one
  unit, and `board.alternative(unit, option, Alt(...), ...)` gives it each option (`unit.option`).
  `board.exclude(choice, choice, ..., why=)` leaves out every combination holding all the choices; `run.json`'s
  `arrangements` lists each with its `why`. `arrangement.option_dead` (warning) names an option refused in every
  combination that holds it.
```

`docs/superpowers/skill-checks/arrangements.md:50-52` become:

```markdown
- it read the run's arrangement report (`arrangements` in `run.json`, and the `arrangement.refused`,
  `arrangement.option_dead` and `arrangement.limit` findings), refused combinations included;
- for each dead option it fixed the option or dropped it, and did not finish with one dead;
```

and `fixtures/skill_check.py:3`'s phrase `and fixed or dropped an alternative the run refused)` becomes `and fixed or dropped an option the run found dead)`.

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_arrangement_declarations.py tests/test_arrangement_settings.py tests/test_settings_docs.py tests/test_skill_check.py tests/test_settings_wiring.py -n 2 -p no:cacheprovider -q`
Expected: PASS (the 0.99.15 doc tests in the file included).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/settings.py skills/placemat/SKILL.md skills/placemat/references/api.md skills/placemat/references/migration.md docs/superpowers/skill-checks/arrangements.md fixtures/skill_check.py tests/test_arrangement_declarations.py tests/test_arrangement_settings.py
git commit -m "Docs: units with options, exclusions and dead options in the skill, api.md and the migration entry; arrangements_max defaults to 16"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```
Expected: the grep prints nothing.

---

### Task 7: Final gate

**Files:**
- Modify: `docs/superpowers/specs/2026-10-05-arrangement-groups-combine-design.md` (a "## Build notes" section at the end)
- Create (scratch only, not committed): `/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/arrangements_0_99_15.py`

**Interfaces:**
- Consumes: everything above.
- Produces: the bench tally, the suite result and the comparison with 0.99.15, in the build notes and the commit.

- [ ] **Step 1: Bench**

Run: `PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python fixtures/bench.py --jobs 2 | tee /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/bench.out`
Expected: every case `same` on every config (the corpus runs no module script, so no unit or exclusion is in it). Any `better` or `worse` is a regression: find it with `git bisect` over this plan's commits before going on.

- [ ] **Step 2: The full suite, once, alone**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock env PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest tests --full -n 2 -p no:cacheprovider -q 2>&1 | tee /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/suite.out | tail -15`
Expected: PASS. A test the run names as over 2 s and not in `tests/slow_tests.txt` is added to it (`tests/update_slow_tests.py`).

- [ ] **Step 3: The real module against 0.99.15**

Write the scratch script:

```python
# /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/arrangements_0_99_15.py
"""Lays out the usb5v fixture module with a declaration written for 0.99.15 (one board.arrangement, one item alternative) under
whichever placemat and tests are first on sys.path, and prints each arrangement's id, whether it was offered and its members'
places, as JSON. Argument: a folder to stage the run in."""
import json
import sys
from pathlib import Path

from placemat.kicad.read import read_board
from tests import real_modules

GROUPED = '''
from placemat import Alt
board.alternative(Part("c_vcc"), "turned", rotation=LYING)
board.arrangement("rt_apart", Alt(Part("r_rt"), at=Beside(Part("buck"), Edge.SOUTH, gap=0.6, align=("RT_5V", pin(RT_PIN)))),
                  why="RT's resistor a little further south")
'''
MARK = "frame_planes(FILLET, supply=None)"

result, _, _ = real_modules.run(Path(sys.argv[1]), "usb5v", edit=lambda t: t.replace(MARK, GROUPED + MARK, 1))
rec = json.loads((result.run_dir / "run.json").read_text())
got = {}
for a in rec["arrangements"]:
    pcb = result.run_dir / "arrangements" / a["id"] / "layout.kicad_pcb"
    got[a["id"]] = {"offered": a["offered"],
                    "places": {fp.inst: [round(fp.location.x, 4), round(fp.location.y, 4), round(fp.rotation % 360.0, 3), str(fp.face)]
                               for fp in read_board(pcb).footprints} if pcb.exists() else None}
print(json.dumps(got, sort_keys=True))
```

Then run this as one shell script from the checkout the plan runs in (`src/` is unchanged between the `v0.99.15` tag and the commit this plan starts from, so the tag's run is 0.99.15's behaviour):

```bash
TOP=$(git rev-parse --show-toplevel)
S=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad
PY=/home/ben/work/placemat/.venv/bin/python
git worktree add "$S/v0.99.15" v0.99.15
(cd "$S/v0.99.15" && flock "$S/realboard.lock" env PYTHONPATH=src:. "$PY" "$S/arrangements_0_99_15.py" "$S/run-old" | tail -1 > "$S/old.json")
(cd "$TOP" && flock "$S/realboard.lock" env PYTHONPATH=src:. "$PY" "$S/arrangements_0_99_15.py" "$S/run-new" | tail -1 > "$S/new.json")
"$PY" - "$S" <<'EOF'
import json, sys
d = sys.argv[1] + "/"
old, new = json.load(open(d + "old.json")), json.load(open(d + "new.json"))
print("0.99.15:", sorted(old), "now:", sorted(new))
for ident in old:
    assert new.get(ident) == old[ident], ident
print("added:", sorted(set(new) - set(old)))
EOF
git worktree remove "$S/v0.99.15"
rm -rf "$S/run-old" "$S/run-new"
```

Expected: `0.99.15: ['c_vcc.turned', 'default', 'rt_apart']`, every one of them the same (offered and places) now, and `added: ['c_vcc.turned+rt_apart']`.

- [ ] **Step 4: Build notes and the gate's commit**

Append to the spec:

```markdown
## Build notes

Built <date>. The bench (`fixtures/bench.py --jobs 2`) is the same in every case on every config. The full suite (`--full`)
passed. The usb5v fixture module with a 0.99.15 declaration (one `board.arrangement`, one item alternative) makes, under
0.99.15 and now, `default`, `c_vcc.turned` and `rt_apart` with the same places and the same offered state; now it also
makes `c_vcc.turned+rt_apart`.
```

with the date and any number that differs from the expected results filled in from Steps 1-3. Then:

```bash
git add docs/superpowers/specs/2026-10-05-arrangement-groups-combine-design.md
{ echo "Spec: build notes for arrangement units that combine"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
git log --format=%B main..HEAD | grep -iE "claude|anthropic|session|co-authored"
```
Expected: both greps print nothing (the second only when the work is on a branch). `git status --short` shows nothing of this plan's left uncommitted.

- [ ] **Step 5: Release**

Follow the release procedure (suite, skill docs current, release with the migration and whats-new entries and the gaps file pruned, notify the sessions that use placemat, then the bench). The migration entry is written in Task 6; the release notes are the release's own step.

---

## Spec gaps and resolutions

Resolved by the user's decisions of 2026-10-05: gaps 1 and 8 by the user's own choice, gaps 2-7 and 9 as the plan recommended. Gaps 10-12 were not part of those decisions and stay for the user to confirm before the task that carries them.

1. **Resolved: `board.unit` was chosen.** `board.group(name, items, why="")` already writes a KiCad group on the board (`layout.py:7519-7543`, `api.md:1789`), and the spec's `board.group(name, *members, why="")` took the same name. The new form is `board.unit(name, *members, why="")`; `board.group` is unchanged and there is no dispatch on its arguments. A KiCad group passed to `board.alternative` is a `TypeError` saying a unit is declared with `board.unit`; parts given to `board.unit` in a list are a `TypeError` saying to give them one by one. The record type stays `Group` inside `arrangements.py` only; every name a script, a message or a document shows says unit (Task 2).
2. Resolved as recommended. **A 0.99.15 `board.arrangement` that shares parts.** The spec says a member may not be in a unit and have its own alternative, and lists that under "Changed"; it also says a 0.99.15 module runs unchanged with every id kept. 0.99.15 accepted a `board.arrangement` naming a part with its own alternative, and two `board.arrangement`s naming one part, and its tests do both (`test_arrangement_declarations.py:139-152`, `test_arrangement_only.py:10-14`). The plan applies the rule to `board.unit` and keeps 0.99.15's freedom for `board.arrangement`: two units that move one part never combine (Tasks 1 and 2). The strict reading would make those modules errors.
3. Resolved as recommended. **"An exclusion that leaves out every combination holding some option" cannot happen.** An exclusion needs two or more choices, and each option's own arrangement (it alone, everything else at its default) holds one choice, so no exclusion covers it. The plan drops that check and adds two that can occur: two options of one unit, and two choices that never combine (they move one part). Each is an error at the end of declaring (Task 2).
4. Resolved as recommended. **Where an item is "first declared".** The spec orders units by where the script first declares them. For an item the plan takes its `place()`, which is what keeps a module with no unit in its 0.99.15 order (the alternative call's position would reorder some). A unit stands where its `board.unit` or `board.arrangement` call is among the `place()` calls. A 0.99.15 module with `board.arrangement`s therefore lists them earlier than before (a unit declared after the items changes fastest); a board breaks ties in that order, so a re-run module may tie-break differently. The migration entry says so.
5. Resolved as recommended. **`choices` of a one-option unit.** The spec's `{unit: unit}` is read as `{name: name}`: the literal key `"group"` of 0.99.15 cannot hold two units in one combination. This changes 0.99.15's `{"group": name}` in `run.json` and in the fragment's notes. Nothing reads it back (`board_geometry.py:128`, `choices` is `compare=False` and unused); api.md and the migration entry say so.
6. Resolved as recommended. **A duplicate and `option_dead`.** A combination dropped as a duplicate is neither offered nor refused. The plan counts it as not refused, so an option whose only other combination is a duplicate is not dead (Task 3).
7. Resolved as recommended. **Where `run.json` puts the excluded ids.** The spec says the `arrangements` record "gains `excluded`". The plan adds one entry per excluded combination after the laid-out ones, with `offered: false` and `excluded: {"why", "by"}`, and no `dir` or `metrics`; the console and the studio show it as excluded (Tasks 3 and 4).
8. **Resolved: `place.arrangements_max` defaults to 16.** A `board.arrangement` added one arrangement in 0.99.15; as a unit it multiplies the count. The default goes from 8 to 16 (`settings.py`, Task 6), the settings table is regenerated, `tests/test_arrangement_settings.py` asserts 16, and the migration entry's "Changed" says so. A project that sets its own value keeps it; a module over the limit still lays out its default only, and the author excludes combinations or raises the setting.
9. Resolved as recommended. **`arrangement.limit`'s facts and text.** The facts gain `excluded` (facts version 2). The text's tail, which told the author to name a group (0.99.15 wording), now says to exclude combinations (arrangements variant) or to drop an option (options variant), since a unit no longer reduces the count.
10. **A unit named as an item with options** would make their ids one (`c_in.east` for both); the spec does not say. The plan makes it an error where the script finishes declaring.
11. **The order of a board script's errors.** `runner.py:371-372` checks the declarations before refusing a board's alternatives; with units, a board script declaring a unit with no option would be told about the option first. The plan swaps the two calls (Task 2).
12. **The real-module check against 0.99.15** uses the `v0.99.15` tag in a scratch worktree; `src/` is unchanged between the tag and this plan's starting commit, so the tag's run is the 0.99.15 behaviour (Task 7).
