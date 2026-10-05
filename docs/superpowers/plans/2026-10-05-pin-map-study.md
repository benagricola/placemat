# Pin Map Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a part whose capture gives it a `Pm.PinPool`, placemat measures how many weighted ratsnest crossings a better assignment of nets to its pins would save, at its present rotation and at each turn in `pins.rotations`, and says so in a `pins.remap` notice whose advice suggestion carries the map and the turn; an explore reports the same study of its best variants beside their scores. Nothing is written to the board or the capture.

**Architecture:** Five pure modules carry the study: `pinmap_rules` (the annotations, as pad numbers, and what may move), `pinmap_geom` (exit points, the way round the courtyard box, bends, poses), `pinmap_input` (the studied parts, their nets and the other airwires, from the pads alone through `ratsnest.board_nets(pads, copper=())`), `pinmap_score` (weighted crossings, length and bend, with a grid of the other airwires and memoised per-net costs so a move recounts only the nets it touches) and `pinmap_search` (a minimum-cost matching seed, then moves, swaps and group moves under annealing, per pose, for parts studied alone or together). `pinmap` turns a placed board into findings and facts, keeps the last study under a digest, and is called once at the end of a resolve (`Board._report_pin_maps`), by the explore on its best variants (`explore._pin_maps`) and by `placemat apply <id> --search`. The finding renders in `finding_text`, the suggestion is a new `how: "advice"` kind with an `advice` record and no edit, and the studio draws the airwires before and after from the finding's facts.

**Tech Stack:** Python 3.12, pcbnew (KiCad 10.0.6 in the checkout's venv: `NETCLASS.GetTuningProfile`), pytest with xdist, node for the studio page tests, and - only if the bench says so - the `placemat_native` Rust module (pyo3 0.29).

**Spec:** `docs/superpowers/specs/2026-10-05-pin-map-study-design.md` (approved 2026-10-05; binding). Read it with this plan.

## Global Constraints

- The spec's settings, each with a default and a line in api.md's generated settings table: `pins.exit_mm`, `pins.follow_series`, `pins.pair_weight`, `pins.impedance_weight`, `pins.length_weight`, `pins.bend_weight`, `pins.rotations` (default 0, 90, 180, 270), `pins.seeds`, `pins.budget_ms` (provisional 400 until Task 15 sets it from the bench), `pins.faces`, `pins.gain_min`, `pins.explore_top`. Tunables the plan adds because a number must not be a literal: `pins.anneal_moves`, `pins.anneal_start`, `pins.anneal_end`, `pins.joint_combinations` (the spec's cap on a joint study's rotation combinations) and `pins.probe_budget_ms` (the probe's longer budget). A crossing with a plane's or a free net's airwire weighs the existing `score.crossing_plane`.
- `pins.remap` is a notice (kind `pins`); `setup.pins` is a `setup` finding at that kind's warning. A part with no `Pm.PinPool` is not studied and gives no finding.
- Nothing writes the .zen. Nothing moves a board item. The study never runs inside the placement search: once per resolve at its end, never on an explore's variants except through `explore._pin_maps`.
- Scored as unrouted: the study's nets come from the pads alone, `board_nets(pads, copper=())`; tracks, vias and pours are ignored for connectivity, never torn up.
- Structured data inside, text only at the edge: `finding_text`, `step_text`, the console lines (runner, previewer, cli, explore's report lines) and the studio. Functions return records; nothing parses a sentence.
- Tunables are settings with defaults, never literals. Weights, budgets, distances and counts live in `Settings`.
- ASCII only in code comments, docs, test text and commit messages: plain hyphens, `->`, straight quotes.
- Generic wording: code, tests, docs, the skill and commit messages name no project, board, module or part number; fixture folders are named only as paths in test and bench code.
- Every test is written first and watched failing before the code that passes it.
- Keep CPU light: the suite as `.venv/bin/python -m pytest -n 2`, the bench `--jobs 2`, real-board runs and full suites one at a time, each real-board command under `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock <command>`. Never `pkill`, `killall` or grep-kill: stop only PIDs this session started.
- Commit messages contain no reference to Claude, Anthropic, a session or Co-Authored-By. After every commit run `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`; it must print nothing (amend if it does).
- UI: no label with a parenthetical explanation (a tooltip says more); red only for errors, yellow for warnings, no greys.
- pcbnew: delete board items with `board.Delete(item)` after `group.RemoveItem(item)`, never `board.Remove`. No task here writes through pcbnew.
- Defer to upstream: the ratsnest (`ratsnest.py`) is KiCad's `RN_NET` ported; the study builds on it unchanged. The airwire model round the body and the bend term are placemat's own, and are named so in their docstrings.
- The new finding causes change `finding_text.schemas_digest()`, so the first run after this release replays no steps (the reuse context holds the digest). That is expected; nothing else in the reuse record changes.
- `SCRATCH=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad` is exported in the shell that runs the plan.

## Review Focus

Inputs the spec implies and no task's own feature tests reach, most likely to bite first. Each has its test in the task named.

1. A net on two pins of the studied part (two pins tied, a power net written into the pool): it stays, its pins are offered to no other net, and it never appears in a map. Tests: Task 2 (`test_a_net_on_two_pins_of_the_pool_stays_where_it_is`), Task 8 (`test_a_net_on_two_pins_of_the_part_stays_and_is_not_in_the_map`).
2. Annotations that name pins by name on a board whose pin names were not read (the part's symbol is not among the generator inputs): one `setup.pins` per entry saying the names were not read, not one per name of a range; pad numbers still read. Test: Task 2 (`test_names_on_a_part_whose_pin_names_were_not_read_are_one_problem_per_entry_and_numbers_still_read`).
3. `pins.rotations` written loosely (360, -90, a turn twice, 0 left out): the present pose is studied first and each turn once. Test: Task 6 (`test_the_present_pose_comes_first_and_each_turn_is_studied_once_however_the_turns_are_written`).
4. A part standing off-axis (45 degrees) or with its pins under its body (a BGA): it is studied without error, each pin leaving by the box side it is nearest, and the poses are named from where it stands. Test: Task 8 (`test_a_part_at_45_degrees_with_its_pins_under_its_body_is_studied_and_its_poses_named_from_where_it_stands`).
5. A target pad under the studied part's body (a part on the other face beneath it): its airwire goes straight from the exit point, not round the body. Test: Task 3 (`test_a_target_inside_the_body_is_reached_straight`).

## File Structure

New, one responsibility each:

- `src/placemat/pinmap_rules.py` - pure: the five annotations read into `PinRules` (pad numbers, pool order kept), `Problem` records for what is left out, and `part_pins` -> `PartPins` (what moves, where it may go, what is held, group windows).
- `src/placemat/pinmap_geom.py` - pure geometry: `Pose`, `outward`, `Exit`/`exit_of`, `through`, `round_body`, `route`, `length`, `bend`.
- `src/placemat/pinmap_input.py` - the study's input as data: `PlacedPad`, `PlacedPart`, `Pin`, `StudiedPart`, `StudyNet`, `Wire`, `StudyInput`; `build` (pads alone, series parts followed, crossing classes) and `placed_from_geometry`.
- `src/placemat/pinmap_score.py` - `Weights`, `Breakdown`, `Background` (the other airwires on a 2 mm grid), `NetWires`, `Scorer` (memoised per net and per pair), `Tally` (incremental delta).
- `src/placemat/pinmap_search.py` - `Clock`, `poses_of`, `hungarian`, `first_map`, the move proposer, `anneal`, `study_group`, `linked_groups`, `study`; `PoseResult`, `GroupResult`.
- `src/placemat/pinmap.py` - the edge to placemat: facts, digest and cache, `study_findings`, `geometry_findings`, `placed_from_plan`, `plan_findings`, `study_line`, `plan_summary`, `longer_advice`.
- `tests/pinmap_boards.py` - synthetic placed boards for the study's tests.
- `fixtures/pinmap/reference.json`, `fixtures/pinmap_bench.py` - the reference boards (annotations live only here) and the speed bench.
- `native/src/pinmap.rs` - only if Task 14 runs: the crossing counts in Rust.

Modified:

- `settings.py` (the `[pins]` section), `reuse.py` (`pins_` settings change no placement).
- `board_geometry.py` (`NetClass.tuning_profile`), `kicad/read.py` (read it).
- `findings.py` (kind `pins`, causes `pins.remap`, `setup.pins`), `finding_text.py` (their sentences, `pose_text`, subjects), `suggestions.py` (`advice` on `Pick` and `Suggestion`, `how: "advice"`, the builder, binding and apply).
- `occupancy.py` (`courtyard_box`), `layout.py` (`Plan.pin_study`, `Board.pin_study`, `Board.pin_study_cache`, `_report_pin_maps`), `runner.py` (the cache path, the record and the console line), `explore.py` (`BoardFactory`, `_pin_maps`, `pin_map_lines`), `previewer.py` (the console line), `cli.py` (`_pin_search`).
- `studio_page.html` (the advice suggestion's Try, its map and the airwires).
- Docs: `skills/placemat/references/capture.md`, `api.md`, `migration.md`, `skills/placemat/SKILL.md`.
- Tests touched: `tests/test_finding_kinds.py`, `tests/test_suggestion_cases.py`, `tests/test_studio_page.py`, `tests/slow_tests.txt`.

Task order: 1 settings; 2-7 the pure study; 8 finding and suggestion; 9 run and preview; 10 explore; 11 probe; 12 studio; 13-15 bench, native (conditional), defaults; 16 docs.

---

### Task 1: The `[pins]` settings

**Files:**
- Modify: `src/placemat/settings.py` (the fields after `explore_checkpoint_max_variants`, `SECTIONS`, `_ABOVE_ZERO`, `_AT_LEAST_ZERO`, `_validate`)
- Modify: `src/placemat/reuse.py` (`_NOT_PLACEMENT`)
- Modify: `skills/placemat/references/api.md` (the generated settings table between its markers)
- Test: `tests/test_pinmap_settings.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Settings.pins_exit_mm: float`, `pins_follow_series: bool`, `pins_pair_weight: float`, `pins_impedance_weight: float`, `pins_length_weight: float`, `pins_bend_weight: float`, `pins_rotations: tuple`, `pins_seeds: int`, `pins_anneal_moves: int`, `pins_anneal_start: float`, `pins_anneal_end: float`, `pins_budget_ms: int`, `pins_joint_combinations: int`, `pins_faces: bool`, `pins_gain_min: float`, `pins_explore_top: int`, `pins_probe_budget_ms: int`; TOML section `[pins]`. Every later task reads these by name.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pinmap_settings.py`:

```python
"""The pin map study's settings: each with its default, a list of turns refused when an entry is not a number, and none
of them able to stop a placement replaying."""
import pytest

from placemat.reuse import placement_settings
from placemat.settings import Settings, SettingsError, load


def test_every_pins_setting_has_its_default():
    s = Settings()
    assert (s.pins_exit_mm, s.pins_follow_series, s.pins_pair_weight, s.pins_impedance_weight, s.pins_length_weight,
            s.pins_bend_weight) == (0.5, True, 5.0, 3.0, 0.25, 0.005)
    assert (s.pins_rotations, s.pins_seeds, s.pins_anneal_moves, s.pins_anneal_start, s.pins_anneal_end) == \
        ((0.0, 90.0, 180.0, 270.0), 4, 500, 1.0, 0.02)
    assert (s.pins_budget_ms, s.pins_joint_combinations, s.pins_faces, s.pins_gain_min, s.pins_explore_top,
            s.pins_probe_budget_ms) == (400, 64, False, 0.05, 3, 5000)


def test_the_turns_are_read_from_the_toml_and_an_entry_that_is_not_a_number_is_refused(tmp_path):
    (tmp_path / "placemat.toml").write_text("[pins]\nrotations = [0, 45, 90]\nbudget_ms = 250\n")
    s = load(tmp_path)
    assert s.pins_rotations == (0, 45, 90) and s.pins_budget_ms == 250
    (tmp_path / "placemat.toml").write_text('[pins]\nrotations = [0, "ninety"]\n')
    with pytest.raises(SettingsError, match="pins.rotations"):
        load(tmp_path)
    (tmp_path / "placemat.toml").write_text("[pins]\nbudget_ms = 0\n")
    with pytest.raises(SettingsError, match="pins.budget_ms"):
        load(tmp_path)


def test_a_pins_setting_changes_no_placement_so_a_replay_still_holds():
    assert "pins_budget_ms" not in placement_settings(Settings())
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_settings.py -q -n 2`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'pins_exit_mm'` (and `pins.rotations is not a setting placemat has` for the TOML test).

- [ ] **Step 3: Add the settings**

In `src/placemat/settings.py`, find:

```python
    explore_checkpoint_max_variants: int = S(100000, "count",
        "finished variants an explore's checkpoint records; past it a resume tries those again")
```

and add after it (before `drc_severities`):

```python
    pins_exit_mm: float = S(0.5, "mm",
        "the pin map study: how far past its part's courtyard a pin's airwire leaves (its exit point) before it may turn")
    pins_follow_series: bool = S(True, "bool",
        "the pin map study scores a net that reaches a pin through a two-pad series part (a termination resistor) on to the series part's far net, as one connection")
    pins_pair_weight: float = S(5.0, "weight",
        "the pin map study: what a crossing counts where either airwire is a differential pair's (any other counts 1)")
    pins_impedance_weight: float = S(3.0, "weight",
        "the pin map study: what a crossing counts where either airwire's net class names a tuning profile, a controlled impedance")
    pins_length_weight: float = S(0.25, "weight",
        "the pin map study: weighted crossings per mm of the studied nets' airwire (0.25: the run score's 4 mm a crossing)")
    pins_bend_weight: float = S(0.005, "weight",
        "the pin map study: weighted crossings per degree a studied net turns from its pin's outward normal toward its target")
    pins_rotations: tuple = S((0.0, 90.0, 180.0, 270.0), "degrees",
        "the turns from where a part stands that the pin map study tries besides its present one; add 45, 135, 225 and 315 for the diagonals")
    pins_seeds: int = S(4, "count",
        "local searches of the pin map study per pose, each with its own fixed random stream")
    pins_anneal_moves: int = S(500, "count",
        "moves each local search of the pin map study tries")
    pins_anneal_start: float = S(1.0, "weight",
        "the pin map study's annealing temperature at its first move, in weighted crossings: a move that costs this much is taken about one time in three (0: only moves that gain)")
    pins_anneal_end: float = S(0.02, "weight",
        "the pin map study's annealing temperature at its last move")
    pins_budget_ms: int = S(400, "ms",
        "the pin map study's time for each studied part: it stops there with the best map found and says so")
    pins_joint_combinations: int = S(64, "count",
        "the most pose combinations the pin map study searches for parts it studies together, their present poses first")
    pins_faces: bool = S(False, "bool",
        "the pin map study also turns a part on the other face where its declaration lets it stand there (`face=Face.EITHER`)")
    pins_gain_min: float = S(0.05, "share",
        "the share of the present total a better pin map must save for a `pins.remap` finding")
    pins_explore_top: int = S(3, "count",
        "the best variants of an explore, by run score, the pin map study runs on (0: none)")
    pins_probe_budget_ms: int = S(5000, "ms",
        "the pin map study's time for each part when `placemat apply <id> --search` studies a `pins.remap` suggestion again")
```

In `SECTIONS`, after the `"explore": ...` entry, add:

```python
    "pins": "the pin map study: what may move on a part with a `Pm.PinPool`, how a map is scored and searched, and when it is a finding",
```

At the end of `_ABOVE_ZERO`, find:

```python
    "route_plane_share", "route_adopt_tolerance", "place_courtyard_polygon_share", "write_keepout_line_width", "write_keepout_text_height"))
```

and replace it with:

```python
    "route_plane_share", "route_adopt_tolerance", "place_courtyard_polygon_share", "write_keepout_line_width", "write_keepout_text_height",
    "pins_seeds", "pins_anneal_moves", "pins_budget_ms", "pins_joint_combinations", "pins_probe_budget_ms"))
```

At the end of `_AT_LEAST_ZERO`, find:

```python
    "score_via_relay", "score_via_relay_moved", "score_via_relay_gap", "score_via_relay_pitch"))
```

and replace it with:

```python
    "score_via_relay", "score_via_relay_moved", "score_via_relay_gap", "score_via_relay_pitch",
    "pins_exit_mm", "pins_pair_weight", "pins_impedance_weight", "pins_length_weight", "pins_bend_weight", "pins_anneal_start",
    "pins_anneal_end", "pins_gain_min", "pins_explore_top"))
```

In `_validate`, find the line `    if name == "drc_severities":` and add before it:

```python
    if name == "pins_rotations":
        bad = [v for v in value if isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            raise SettingsError("%s: pins.rotations: every entry is a turn in degrees, not %r" % (path, bad[0]))
```

In `src/placemat/reuse.py`, replace:

```python
_NOT_PLACEMENT = ("preview_", "timeout_", "run_", "route_", "best_", "noise_", "check_", "drc_")
```

with:

```python
_NOT_PLACEMENT = ("preview_", "timeout_", "run_", "route_", "best_", "noise_", "check_", "drc_", "pins_")
```

- [ ] **Step 4: Regenerate api.md's settings table**

```bash
.venv/bin/python - <<'EOF'
import re
from pathlib import Path
from placemat.settings import docs_table
p = Path("skills/placemat/references/api.md")
t = p.read_text()
t = re.sub(r"(<!-- settings-table:begin -->\n).*?(\n<!-- settings-table:end -->)",
           lambda m: m.group(1) + docs_table() + m.group(2), t, flags=re.S)
p.write_text(t)
EOF
```

- [ ] **Step 5: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_settings.py tests/test_settings_docs.py tests/test_settings.py -q -n 2`
Expected: PASS (the docs test checks every setting has a unit and meaning, the section is in `SECTIONS`, the example TOML loads to the defaults and the api.md table is the generated one).

- [ ] **Step 6: Commit**

```bash
git add src/placemat/settings.py src/placemat/reuse.py skills/placemat/references/api.md tests/test_pinmap_settings.py
git commit -m "Settings: the [pins] section for the pin map study"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

Expected: the grep prints nothing.

---

### Task 2: Constraint parsing - the pin annotations and what may move

**Files:**
- Create: `src/placemat/pinmap_rules.py`
- Test: `tests/test_pinmap_rules.py`

**Interfaces:**
- Consumes: `checks._net_named(name, net)` (src/placemat/checks.py: a net named by its whole name or its last part after `.` or `/`, case-insensitively; the same rule `Pm.KeepOut` uses).
- Produces:
  - `Problem(ref, key, entry, code, name)` frozen; `.facts() -> dict` (the `setup.pins` facts). Codes: `no_pin`, `no_names`, `no_net`, `unreadable`, `not_in_pool`, `two_groups`, `no_legal_pin`, `no_legal_map` (the last made by Task 6).
  - `PinRules(ref, pool: tuple, fixed: frozenset, allow: dict, deny: dict, groups: tuple)`.
  - `natural(number: str) -> tuple` (pad number sort key), `fields_of(fields: dict) -> dict`.
  - `pin_numbers(numbers, names: dict, item: str) -> (list, list)`.
  - `read_rules(ref, fields: dict, pads: list[(number, net)], names: dict) -> (PinRules | None, [Problem])`.
  - `Held(net, pin, why)`; `PartPins(ref, present: dict, movable: tuple, allowed: dict, free: tuple, groups: tuple, windows: dict, held: tuple)`.
  - `part_pins(rules, pads: list[(number, net, no_connect)], connected, quiet) -> (PartPins | None, [Problem])`.

Notes for the implementer: annotations are read case-insensitively because KiCad title-cases a field name (`Pm.PinPool` is written `Pm.Pinpool`), as `exposure._fields` does. A citation stays in a `.zen` comment beside the annotation (capture.md: "a value is a plain string with its unit, with its source in a comment beside it"); `;` here separates entries. A range's missing names are reported one by one and the rest of the range stands; with no pin names read at all, an entry that names pins by name is one `no_names` problem. Groups move to runs of consecutive entries in the pool's written order.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_rules.py`:

```python
"""The pin map study's constraints: pins named by number, by name or by a range of either; allow, deny, fixed and
groups; an entry naming a pin or a net the part lacks left out as a problem; which nets may move."""
from placemat.pinmap_rules import PinRules, Problem, part_pins, pin_numbers, read_rules

PADS = [(str(n), "N%d" % n) for n in range(1, 9)] + [("9", ""), ("10", "logic.SDA")]
NAMES = {str(n): "GPIO%d" % (n - 1) for n in range(1, 11)}         # pad 1 is GPIO0 ... pad 10 is GPIO9


def test_a_pin_is_named_by_number_by_name_or_by_a_range_of_either():
    numbers = {n for n, _ in PADS}
    assert pin_numbers(numbers, NAMES, "3") == (["3"], [])
    assert pin_numbers(numbers, NAMES, "GPIO4") == (["5"], [])
    assert pin_numbers(numbers, NAMES, "gpio4") == (["5"], [])
    assert pin_numbers(numbers, NAMES, "3-5") == (["3", "4", "5"], [])
    assert pin_numbers(numbers, NAMES, "GPIO1-GPIO3") == (["2", "3", "4"], [])
    assert pin_numbers(numbers, NAMES, "GPIO3-GPIO1") == (["4", "3", "2"], [])
    assert pin_numbers(numbers, NAMES, "GPIO8-GPIO11") == (["9", "10"], ["GPIO10", "GPIO11"])
    assert pin_numbers(numbers, NAMES, "SPI_CS") == ([], ["SPI_CS"])


def test_the_annotations_are_read_whatever_case_kicad_gave_the_key():
    rules, problems = read_rules("U1", {"Pm.Pinpool": "1-6", "Pm.Pinfixed": "GPIO0"}, PADS, NAMES)
    assert rules.pool == ("1", "2", "3", "4", "5", "6") and rules.fixed == {"1"} and problems == []


def test_a_part_without_a_pool_is_not_studied():
    assert read_rules("U1", {"Pm.PinFixed": "1"}, PADS, NAMES) == (None, [])


def test_a_pin_the_part_does_not_have_is_a_problem_and_the_rest_of_the_entry_stands():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-3, GPIO42"}, PADS, NAMES)
    assert rules.pool == ("1", "2", "3")
    assert problems == [Problem("U1", "Pm.PinPool", "GPIO42", "no_pin", "GPIO42")]


def test_allow_and_deny_name_nets_as_the_capture_does_and_a_net_the_part_lacks_is_a_problem():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-10", "Pm.PinAllow": "SDA:GPIO1-GPIO3; N4:4",
                                        "Pm.PinDeny": "N5:1,2; NOPE:3"}, PADS, NAMES)
    assert rules.allow == {"logic.SDA": frozenset({"2", "3", "4"}), "N4": frozenset({"4"})}
    assert rules.deny == {"N5": frozenset({"1", "2"})}
    assert problems == [Problem("U1", "Pm.PinDeny", "NOPE:3", "no_net", "NOPE")]


def test_a_group_must_lie_in_the_pool_off_the_fixed_pins_and_in_one_group_only():
    rules, problems = read_rules("U1", {"Pm.PinPool": "1-8", "Pm.PinFixed": "8", "Pm.PinGroup":
                                        "bus:2-4; late:4,5; out:9; strap:7-8; bad entry"}, PADS, NAMES)
    assert rules.groups == (("bus", ("2", "3", "4")),)
    assert [(p.entry, p.code, p.name) for p in problems] == [
        ("late:4,5", "two_groups", "4"), ("out:9", "not_in_pool", "9"), ("strap:7-8", "not_in_pool", "8"),
        ("bad entry", "unreadable", "bad entry")]


def test_pins_with_no_net_or_a_net_that_reaches_nothing_are_free_and_fixed_or_outside_nets_stay():
    rules = PinRules("U1", ("1", "2", "3", "4", "5", "6"), frozenset({"2"}))
    pads = [("1", "A", False), ("2", "B", False), ("3", "LONE", False), ("4", "", False), ("5", "C", True),
            ("6", "D", False), ("7", "E", False), ("8", "GND", False)]
    slots, problems = part_pins(rules, pads, connected={"A", "B", "C", "D", "E", "GND"}, quiet={"GND"})
    assert problems == [] and slots.movable == ("A", "D")
    assert slots.free == ("3", "4", "5")
    assert [(h.net, h.pin, h.why) for h in slots.held] == [("B", "2", "fixed")]
    assert slots.allowed == {"A": ("1", "3", "4", "5", "6"), "D": ("1", "3", "4", "5", "6")}


def test_a_net_allowed_only_its_own_pin_is_held_and_one_allowed_none_stops_the_part():
    rules = PinRules("U1", ("1", "2", "3"), allow={"A": frozenset({"1"})}, deny={"B": frozenset({"1", "2", "3"})})
    slots, problems = part_pins(rules, [("1", "A", False), ("2", "B", False)], {"A", "B"}, set())
    assert slots is None and problems == [Problem("U1", "Pm.PinDeny", "", "no_legal_pin", "B")]
    rules = PinRules("U1", ("1", "2", "3"), allow={"A": frozenset({"1"})})
    slots, _ = part_pins(rules, [("1", "A", False), ("2", "B", False)], {"A", "B"}, set())
    assert slots.movable == ("B",) and [(h.net, h.why) for h in slots.held] == [("A", "allow")]


def test_a_group_moves_to_runs_of_consecutive_pool_pins_its_nets_may_take():
    rules = PinRules("U1", ("1", "2", "3", "4", "5", "6"), frozenset({"4"}), allow={"Y": frozenset({"2", "3", "6"})},
                     groups=(("pair", ("1", "2")),))
    pads = [("1", "X", False), ("2", "Y", False), ("3", "Z", False)]
    slots, _ = part_pins(rules, pads, {"X", "Y", "Z"}, set())
    assert slots.groups == (("pair", ("X", "Y")),)
    assert slots.windows["pair"] == (("1", "2"), ("2", "3"), ("5", "6"))


def test_names_on_a_part_whose_pin_names_were_not_read_are_one_problem_per_entry_and_numbers_still_read():
    rules, problems = read_rules("U1", {"Pm.PinPool": "GPIO0-GPIO47, 3-4"}, PADS, {})
    assert rules.pool == ("3", "4")
    assert problems == [Problem("U1", "Pm.PinPool", "GPIO0-GPIO47", "no_names", "GPIO0-GPIO47")]


def test_a_net_on_two_pins_of_the_pool_stays_where_it_is():
    rules = PinRules("U1", ("1", "2", "3", "4"))
    slots, _ = part_pins(rules, [("1", "TIED", False), ("2", "TIED", False), ("3", "A", False)], {"TIED", "A"}, set())
    assert slots.movable == ("A",) and slots.free == ("4",)
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_rules.py -q -n 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap_rules'`.

- [ ] **Step 3: Write the module**

Create `src/placemat/pinmap_rules.py`:

```python
"""The pin map study's constraints: which of a part's pins may carry which nets, read from its capture annotations.

`Pm.PinPool`, `Pm.PinFixed`, `Pm.PinAllow`, `Pm.PinDeny` and `Pm.PinGroup` on a part (capture.md, "Annotations"). A pin is
named by its pad number or by its pin name, as `PadRef` names it, and a range is `3-8` or `GPIO1-GPIO10`. An entry that
names a pin the part does not have, or a net it does not carry, is left out and returned as a `Problem`, which the study
reports as a `setup.pins` finding. Pure: it reads a part's fields, its pads' numbers and nets, and the board's pin names."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .checks import _net_named

SHOWN = {"pm.pinpool": "Pm.PinPool", "pm.pinfixed": "Pm.PinFixed", "pm.pinallow": "Pm.PinAllow",
         "pm.pindeny": "Pm.PinDeny", "pm.pingroup": "Pm.PinGroup"}
_TAIL = re.compile(r"^(.*?)(\d+)$")


@dataclass(frozen=True)
class Problem:
    """An annotation entry the study runs without, or a part it cannot study: the facts of a `setup.pins` finding. `key`
    is the annotation as capture.md spells it, `entry` the text that was left out, `name` the pin or net it names and
    `code` what is wrong: no_pin (the part has no such pin), no_names (a pin named by name, and no pin names were read
    for the part), no_net (no pin of the part carries the net), unreadable (the entry is not `name:pins`), not_in_pool
    (a group's pin outside the pool, or on a fixed pin), two_groups (a pin already in an earlier group), no_legal_pin (a
    net that no pin may take: the part is not studied), no_legal_map (no matching places every net: the part is not
    studied)."""
    ref: str
    key: str
    entry: str
    code: str
    name: str

    def facts(self) -> dict:
        return {"ref": self.ref, "key": self.key, "entry": self.entry, "code": self.code, "name": self.name}


@dataclass(frozen=True)
class PinRules:
    """One part's constraints, in pad numbers. `pool` keeps the order the annotation lists the pins in: a group moves to a
    run of consecutive entries of it. `allow` and `deny` are keyed by the net as the board names it."""
    ref: str
    pool: tuple
    fixed: frozenset = frozenset()
    allow: dict = None
    deny: dict = None
    groups: tuple = ()              # (name, (pad number, ...)) in the order written

    def __post_init__(self):
        object.__setattr__(self, "allow", dict(self.allow or {}))
        object.__setattr__(self, "deny", dict(self.deny or {}))


def natural(number: str) -> tuple:
    """A pad number's sort key: numeric ones in number order, then the rest (`A1`, `EP`) as text."""
    return (0, int(number), "") if number.isdigit() else (1, 0, number)


def fields_of(fields: dict) -> dict:
    """The part's pin annotations, keys lower-cased as KiCad title-cases them (`Pm.Pinpool`), blank ones left out."""
    return {k.lower(): v.strip() for k, v in fields.items() if k.lower() in SHOWN and v and v.strip()}


def _items(text: str) -> list:
    return [w for w in re.split(r"[,\s]+", text.strip()) if w]


def pin_numbers(numbers, names: dict, item: str) -> tuple:
    """(pad numbers, names not found) for one item of a pin list: a pad number, a pin name (every pad that carries it), or
    a range of either. `numbers` are the part's pad numbers, `names` {pad number: pin name}."""
    by_name: dict = {}
    for n, nm in names.items():
        by_name.setdefault(nm, []).append(n)
    lower = {}
    for nm, ns in by_name.items():
        lower.setdefault(nm.lower(), []).extend(ns)

    def one(word):
        if word in numbers:
            return [word]
        hit = by_name.get(word) or lower.get(word.lower())
        return sorted(set(hit), key=natural) if hit else None

    whole = one(item)
    if whole is not None:
        return whole, []
    lo, dash, hi = item.partition("-")
    a, b = (_TAIL.match(lo), _TAIL.match(hi)) if dash else (None, None)
    if a is None or b is None or a.group(1) != b.group(1):
        return [], [item]
    prefix, i, j = a.group(1), int(a.group(2)), int(b.group(2))
    step = 1 if j >= i else -1
    out, missing = [], []
    for k in range(i, j + step, step):
        word = "%s%d" % (prefix, k)
        got = one(word)
        if got is None:
            missing.append(word)
        else:
            out += [g for g in got if g not in out]
    return out, missing


def _pin_list(ref, key, text, numbers, names, problems) -> list:
    out = []
    for item in _items(text):
        got, missing = pin_numbers(numbers, names, item)
        if missing and not names and not all(m.isdigit() for m in missing):    # a name, and none to look in: one problem
            problems.append(Problem(ref, key, item, "no_names", item))
            continue
        problems += [Problem(ref, key, item, "no_pin", m) for m in missing]
        out += [g for g in got if g not in out]
    return out


def _entries(text: str) -> list:
    return [e.strip() for e in text.split(";") if e.strip()]


def read_rules(ref: str, fields: dict, pads, names: dict) -> tuple:
    """(PinRules or None, [Problem]) for one part: `fields` its footprint's fields, `pads` its (pad number, net) pairs,
    `names` {pad number: pin name}. None when the part has no `Pm.PinPool`: it is not studied."""
    f = fields_of(fields)
    if "pm.pinpool" not in f:
        return None, []
    numbers = {n for n, _ in pads}
    nets = sorted({net for _, net in pads if net})
    problems: list = []
    pool = _pin_list(ref, "Pm.PinPool", f["pm.pinpool"], numbers, names, problems)
    fixed = frozenset(_pin_list(ref, "Pm.PinFixed", f.get("pm.pinfixed", ""), numbers, names, problems))
    rules = {}
    for low in ("pm.pinallow", "pm.pindeny"):
        key, out = SHOWN[low], {}
        for entry in _entries(f.get(low, "")):
            name, colon, pins = entry.partition(":")
            if not colon or not name.strip() or not pins.strip():
                problems.append(Problem(ref, key, entry, "unreadable", entry))
                continue
            hit = [n for n in nets if _net_named(name.strip(), n)]
            if not hit:
                problems.append(Problem(ref, key, entry, "no_net", name.strip()))
                continue
            got = frozenset(_pin_list(ref, key, pins, numbers, names, problems))
            for n in hit:
                out[n] = out.get(n, frozenset()) | got
        rules[low] = out
    groups, taken = [], set()
    for entry in _entries(f.get("pm.pingroup", "")):
        name, colon, pins = entry.partition(":")
        if not colon or not name.strip() or not pins.strip():
            problems.append(Problem(ref, "Pm.PinGroup", entry, "unreadable", entry))
            continue
        got = _pin_list(ref, "Pm.PinGroup", pins, numbers, names, problems)
        outside = [p for p in got if p not in pool or p in fixed]
        twice = [p for p in got if p in taken]
        if outside or twice:
            problems.append(Problem(ref, "Pm.PinGroup", entry, "not_in_pool" if outside else "two_groups",
                                    (outside or twice)[0]))
            continue
        if got:
            taken |= set(got)
            groups.append((name.strip(), tuple(got)))
    return PinRules(ref, tuple(pool), fixed, rules["pm.pinallow"], rules["pm.pindeny"], tuple(groups)), problems


@dataclass(frozen=True)
class Held:
    """A net a constraint keeps on its pin: `why` is fixed (`Pm.PinFixed`) or allow (`Pm.PinAllow` and `Pm.PinDeny` leave
    it only the pin it is on)."""
    net: str
    pin: str
    why: str


@dataclass(frozen=True)
class PartPins:
    """What may move on one studied part. `present` is every studied net's pin now (movable or held); `movable` the nets
    the search may move, each to a pin of `allowed[net]` (pool order); `free` the pool pins no studied net stands on now;
    `groups` (name, nets in order, "" for a pin with none) move whole, to one of `windows[name]`, each a run of
    consecutive pool pins."""
    ref: str
    present: dict
    movable: tuple
    allowed: dict
    free: tuple
    groups: tuple
    windows: dict
    held: tuple


def part_pins(rules: PinRules, pads, connected, quiet) -> tuple:
    """(PartPins or None, [Problem]): `pads` the part's (pad number, net, no_connect), `connected` the nets with a pad
    elsewhere on the board, `quiet` the plane and free nets. A pool pin with no net, with a net that reaches nothing else
    (a single-pad net, KiCad's `unconnected-(...)`) or that the capture marks unconnected is free. A net on one pool pin
    that is not fixed moves. A net on two pins, a quiet net and a net outside the pool stay, and so do their pins; so
    does a net `Pm.PinAllow` or `Pm.PinDeny` leaves only its own pin. None, with a `no_legal_pin` problem, when a net
    has no pin it may take: the part is not studied."""
    pool = list(rules.pool)
    on: dict = {}
    for number, net, no_connect in pads:
        if net and net in connected and not no_connect:
            on.setdefault(net, []).append(number)
    movable, held, staying = [], [], set()
    for net in sorted(on):
        pins = on[net]
        if net in quiet or len(pins) != 1 or pins[0] not in pool:
            staying |= set(pins)
        elif pins[0] in rules.fixed:
            held.append(Held(net, pins[0], "fixed"))
            staying.add(pins[0])
        else:
            movable.append(net)
    present = {net: on[net][0] for net in movable}

    def legal(net, pins):
        return tuple(p for p in pins if (net not in rules.allow or p in rules.allow[net]) and p not in rules.deny.get(net, ()))
    open_pins = [p for p in pool if p not in rules.fixed and p not in staying]
    for net in list(movable):
        if (net in rules.allow or net in rules.deny) and legal(net, open_pins) == (present[net],):
            held.append(Held(net, present[net], "allow"))
            staying.add(present[net])
            movable.remove(net)
            del present[net]
    open_pins = [p for p in open_pins if p not in staying]
    allowed, problems = {}, []
    for net in movable:
        allowed[net] = legal(net, open_pins)
        if not allowed[net]:
            problems.append(Problem(rules.ref, "Pm.PinAllow" if net in rules.allow else "Pm.PinDeny", "", "no_legal_pin", net))
    if problems:
        return None, problems
    taken = set(present.values())
    free = tuple(p for p in open_pins if p not in taken)
    by_pin = {pin: net for net, pin in present.items()}
    groups, windows = [], {}
    for name, pins in rules.groups:
        nets = tuple(by_pin.get(p, "") for p in pins)
        wins = []
        for i in range(len(pool) - len(pins) + 1):
            win = tuple(pool[i:i + len(pins)])
            if all(p in open_pins for p in win) and all(not n or p in allowed[n] for n, p in zip(nets, win)):
                wins.append(win)
        groups.append((name, nets))
        windows[name] = tuple(wins)
    return PartPins(rules.ref, present, tuple(movable), allowed, free, tuple(groups), windows,
                    tuple(sorted(held, key=lambda h: natural(h.pin)))), []
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_rules.py -q -n 2`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pinmap_rules.py tests/test_pinmap_rules.py
git commit -m "Pin map study: the pin annotations read into pad numbers, and what may move"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 3: The airwire model - exit points, the way round the body, bends, poses

**Files:**
- Create: `src/placemat/pinmap_geom.py`
- Test: `tests/test_pinmap_geom.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure geometry; the turn convention is `geometry.Transform.rotate`'s: counter-clockwise on screen with y down, `x' = cos*x + sin*y`, `y' = -sin*x + cos*y`).
- Produces:
  - `Pose(cx, cy, turn=0.0, flip=False)` frozen; `.vector(x, y)`, `.to_board(x, y)`, `.to_local(x, y)` (all tuples).
  - `outward(x, y, hw, hh) -> (nx, ny)` one of `(1,0)`, `(0,1)`, `(-1,0)`, `(0,-1)`; ties go east, south, west, north.
  - `Exit(ref, at, local, normal, side, pose, hw, hh, margin)` frozen; `exit_of(ref, pose, x, y, normal, hw, hh, margin) -> Exit`.
  - `through(p, q, hw, hh) -> bool`, `round_body(e: Exit, target) -> list`, `route(a, b) -> tuple[tuple]` (each end an `Exit` or a point), `length(path) -> float`, `bend(normal, at, target) -> float` (degrees).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_geom.py`:

```python
"""The pin map study's airwire model: a pin leaves along its outward normal to a point past the courtyard, then goes the
shorter way round the courtyard's box to its target; the bend is the angle between the normal and the bearing to the
target; a pose turns the part about its centre, and mirrors it for the other face."""
import pytest

from placemat.pinmap_geom import Pose, bend, exit_of, outward, route, through

HW = HH = 2.0           # a 4 mm square body


def east_exit(pose=Pose(10, 10), y=0.5):
    return exit_of("U1", pose, 2.0, y, (1.0, 0.0), HW, HH, 0.5)


def test_a_pin_faces_the_side_of_the_box_it_is_nearest_ties_going_east_south_west_north():
    assert outward(1.7, 0.2, HW, HH) == (1.0, 0.0)
    assert outward(0.2, 1.7, HW, HH) == (0.0, 1.0)
    assert outward(-1.7, 0.0, HW, HH) == (-1.0, 0.0)
    assert outward(0.0, -1.7, HW, HH) == (0.0, -1.0)
    assert outward(1.7, 1.7, HW, HH) == (1.0, 0.0)                  # a corner pin: east before south


def test_the_exit_point_is_the_margin_past_the_box_on_the_pins_side():
    e = east_exit()
    assert e.at == (12.5, 10.5) and e.normal == (1.0, 0.0) and e.side == 0


def test_a_target_in_sight_is_reached_straight():
    assert route(east_exit(), (20.0, 10.5)) == ((12.5, 10.5), (20.0, 10.5))
    assert route(east_exit(), (10.0, 30.0)) == ((12.5, 10.5), (10.0, 30.0))


def test_a_target_behind_the_part_is_reached_round_its_body_the_shorter_way_and_never_through_it():
    path = route(east_exit(), (0.0, 10.0))
    assert path == ((12.5, 10.5), (12.5, 12.5), (7.5, 12.5), (0.0, 10.0))         # south of it: nearer the pin
    path = route(east_exit(y=-0.5), (0.0, 10.0))
    assert path == ((12.5, 9.5), (12.5, 7.5), (7.5, 7.5), (0.0, 10.0))           # north of it
    for p, q in zip(path, path[1:]):
        assert not through((p[0] - 10, p[1] - 10), (q[0] - 10, q[1] - 10), HW, HH)


def test_a_target_inside_the_body_is_reached_straight():
    assert route(east_exit(), (9.0, 10.0)) == ((12.5, 10.5), (9.0, 10.0))


def test_a_quarter_turn_takes_an_east_pin_north_and_the_other_face_takes_it_west():
    e = east_exit(Pose(10, 10, 90.0))
    assert e.at == pytest.approx((10.5, 7.5)) and e.normal == (0.0, -1.0)
    e = east_exit(Pose(10, 10, 0.0, True))
    assert e.at == pytest.approx((7.5, 10.5)) and e.normal == (-1.0, 0.0)


def test_an_airwire_between_two_studied_pins_goes_round_both_bodies():
    a = east_exit(Pose(10, 10))
    b = exit_of("U2", Pose(30, 10), 2.0, 0.5, (1.0, 0.0), HW, HH, 0.5)     # U2's pin faces away from U1
    path = route(a, b)
    assert path[0] == a.at and path[-1] == b.at
    assert (32.5, 12.5) in path                                        # round U2's south-east corner to its exit
    for p, q in zip(path, path[1:]):
        assert not through((p[0] - 30, p[1] - 10), (q[0] - 30, q[1] - 10), HW, HH)
        assert not through((p[0] - 10, p[1] - 10), (q[0] - 10, q[1] - 10), HW, HH)


def test_the_bend_is_the_angle_from_the_normal_to_the_target():
    assert bend((1.0, 0.0), (12.5, 10.5), (20.0, 10.5)) == 0.0
    assert bend((1.0, 0.0), (12.5, 10.5), (12.5, 20.0)) == pytest.approx(90.0)
    assert bend((1.0, 0.0), (12.5, 10.0), (0.0, 10.0)) == pytest.approx(180.0)
    assert bend((1.0, 0.0), (12.5, 10.0), (20.0, 2.5)) == pytest.approx(45.0)
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_geom.py -q -n 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap_geom'`.

- [ ] **Step 3: Write the module**

Create `src/placemat/pinmap_geom.py`:

```python
"""The pin map study's airwire model, as pure geometry (millimetres, y down, KiCad's turn: counter-clockwise on screen).

A studied part's body is its courtyard's box. A pin's airwire leaves along the pin's outward normal - the side of the box
it is nearest - to its exit point, `margin` past the box, then takes the shorter way round the box grown by `margin` to
its target, corner to corner, until the target is in sight. A target inside the body's box (a part under it, on the
other face) is reached straight. The bend at a pin is the angle between its outward normal and the bearing from its exit
point to its target: 0 facing it, 180 turning back.

The part's own frame is the board's moved to the courtyard box's centre, as the part stands; a `Pose` turns it about that
centre (and mirrors it left to right first, for the other face) to ask where the pads would be at another rotation."""
from __future__ import annotations

from dataclasses import dataclass
import math

_EPS = 1e-9
_SIDES = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))     # east, south, west, north: the order a tie is broken in


def _clean(v: float) -> float:
    r = round(v, 9)
    return 0.0 if r == 0 else r


@dataclass(frozen=True)
class Pose:
    """A studied part's body turned `turn` degrees about (cx, cy), mirrored left to right first when `flip`."""
    cx: float
    cy: float
    turn: float = 0.0
    flip: bool = False

    def _cs(self):
        r = math.radians(self.turn)
        return math.cos(r), math.sin(r)

    def vector(self, x: float, y: float) -> tuple:
        """A direction in the part's own frame, in the board's."""
        if self.flip:
            x = -x
        c, s = self._cs()
        return (_clean(c * x + s * y), _clean(-s * x + c * y))

    def to_board(self, x: float, y: float) -> tuple:
        vx, vy = self.vector(x, y)
        return (_clean(self.cx + vx), _clean(self.cy + vy))

    def to_local(self, x: float, y: float) -> tuple:
        dx, dy = x - self.cx, y - self.cy
        c, s = self._cs()
        lx, ly = c * dx - s * dy, s * dx + c * dy
        return (-lx if self.flip else lx, ly)


def outward(x: float, y: float, hw: float, hh: float) -> tuple:
    """The outward normal of the box side nearest a pin at (x, y) in the part's frame, the box being (-hw, -hh) to (hw, hh);
    ties go east, south, west, north."""
    gaps = (hw - x, hh - y, x + hw, y + hh)
    return _SIDES[min(range(4), key=lambda k: (gaps[k], k))]


@dataclass(frozen=True)
class Exit:
    """Where a studied pin's airwire leaves its part: `at` in the board's frame, `local` in the part's, `normal` (the
    board's frame) and `side` (0 east, 1 south, 2 west, 3 north) of the box it leaves by, and the body it goes round."""
    ref: str
    at: tuple
    local: tuple
    normal: tuple
    side: int
    pose: Pose
    hw: float
    hh: float
    margin: float


def exit_of(ref: str, pose: Pose, x: float, y: float, normal: tuple, hw: float, hh: float, margin: float) -> Exit:
    """The exit of a pin at (x, y) in the part's frame with outward `normal` (its frame), at `pose`."""
    side = _SIDES.index(normal)
    lx, ly = ((hw + margin, y), (x, hh + margin), (-hw - margin, y), (x, -hh - margin))[side]
    return Exit(ref, pose.to_board(lx, ly), (lx, ly), pose.vector(*normal), side, pose, hw, hh, margin)


def through(p: tuple, q: tuple, hw: float, hh: float) -> bool:
    """Whether segment p-q passes through the inside of the box (-hw, -hh)-(hw, hh); along its edge or touching a corner
    is not through."""
    x0, y0 = p
    dx, dy = q[0] - x0, q[1] - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 + hw), (dx, hw - x0), (-dy, y0 + hh), (dy, hh - y0)):
        if abs(pp) < 1e-15:
            if qq <= _EPS:
                return False
            continue
        r = qq / pp
        if pp < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t1 - t0 <= _EPS:
            return False
    mx, my = x0 + dx * (t0 + t1) / 2, y0 + dy * (t0 + t1) / 2
    return -hw + _EPS < mx < hw - _EPS and -hh + _EPS < my < hh - _EPS


def _length(points) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def round_body(e: Exit, target: tuple) -> list:
    """The way from exit `e` to `target` (board frame) round e's body: [e.at, corners..., target], board frame."""
    t = e.pose.to_local(*target)
    hw, hh = e.hw, e.hh
    if (-hw < t[0] < hw and -hh < t[1] < hh) or not through(e.local, t, hw, hh):
        return [e.at, target]
    w, h = hw + e.margin, hh + e.margin
    corners = ((w, -h), (w, h), (-w, h), (-w, -h))         # north-east, south-east, south-west, north-west
    after = {0: 1, 1: 2, 2: 3, 3: 0}                          # the corner reached first going clockwise from side k
    best = None
    for step in (1, -1):
        k = after[e.side] if step == 1 else (after[e.side] - 1) % 4
        local = [e.local]
        for _ in range(4):
            c = corners[k]
            local.append(c)
            if not through(c, t, hw, hh):
                break
            k = (k + step) % 4
        local.append(t)
        n = _length(local)
        if best is None or n < best[0] - _EPS:
            best = (n, local)
    pts = [e.at] + [e.pose.to_board(*c) for c in best[1][1:-1]] + [target]
    return pts


def route(a, b) -> tuple:
    """An airwire's path from `a` to `b`, each an Exit (a studied pin) or a point: round the body of each end that is
    an Exit, the second end's from the last turn the first one's path makes."""
    pa = a.at if isinstance(a, Exit) else a
    pb = b.at if isinstance(b, Exit) else b
    pts = round_body(a, pb) if isinstance(a, Exit) else [pa, pb]
    if isinstance(b, Exit):
        back = round_body(b, pts[-2])
        pts = pts[:-1] + list(reversed(back))[1:]
    return tuple(tuple(p) for p in pts)


def length(path) -> float:
    return _length(path)


def bend(normal: tuple, at: tuple, target: tuple) -> float:
    """Degrees between a pin's outward `normal` and the bearing from its exit point `at` to `target`."""
    dx, dy = target[0] - at[0], target[1] - at[1]
    d = math.hypot(dx, dy)
    if d <= _EPS:
        return 0.0
    cos = max(-1.0, min(1.0, (normal[0] * dx + normal[1] * dy) / d))
    return math.degrees(math.acos(cos))
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_geom.py -q -n 2`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pinmap_geom.py tests/test_pinmap_geom.py
git commit -m "Pin map study: an airwire leaves past the courtyard and goes round the body, with its bend"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 4: Scoring, part 1 - the study's input from the pads alone

The first half of the scoring: what the score is computed over. A laid board is scored as unrouted - its nets are built from the pads alone, `board_nets(pads, copper=())` - so a routed net keeps its airwire. Series parts are followed, and each net gets its crossing class, a controlled impedance read from the net class's KiCad 10 tuning profile.

**Files:**
- Modify: `src/placemat/board_geometry.py` (`NetClass`)
- Modify: `src/placemat/kicad/read.py` (`_netclasses`)
- Create: `src/placemat/pinmap_input.py`
- Create: `tests/pinmap_boards.py`
- Test: `tests/test_pinmap_input.py`, `tests/test_pinmap_netclass.py`
- Modify: `tests/slow_tests.txt`

**Interfaces:**
- Consumes: `ratsnest.board_nets(pads, copper=())` (pads as `(ref, number, net, layers, outlines, box, anchor)`), `ratsnest.mst(net, anchors, joined)`, `ratsnest.Anchor`; Task 2's `read_rules`, `part_pins`, `natural`; Task 3's `outward`; `Settings` (Task 1) in the test helpers.
- Produces:
  - `NetClass.tuning_profile: str = ""`.
  - `PlacedPad(ref, number, net, layers, outlines, box, anchor, no_connect=False)`, `PlacedPart(ref, courtyard, rotation, face, may_flip=False, fields={})`.
  - `Pin(number, name, x, y, nx, ny)`, `StudiedPart(ref, cx, cy, hw, hh, rotation, face, may_flip, pins, slots)` with `.pin(number)`, `StudyNet(net, kind, fixed, joined, ends, via="", far="")`, `Wire(net, kind, a, b)`, `StudyInput(parts, nets, background, names)` with `.part(ref)`.
  - `KINDS = ("plain", "impedance", "pair", "plane")`, `net_kind(net, quiet, partners, netclasses) -> str`.
  - `build(pads, parts: dict, names: dict, quiet, partners: dict, netclasses: dict, follow_series=True) -> (StudyInput | None, [Problem])`.
  - `placed_from_geometry(geometry, either=frozenset()) -> (pads, {ref: PlacedPart})`.
  - Test helpers in `tests/pinmap_boards.py`: `settings(**kw)`, `pad`, `quad`, `two_pad`, `point_pad`, `complete`, `input_of`, `reversed_four`, `quad_footprint`.

- [ ] **Step 1: Write the test helpers**

Create `tests/pinmap_boards.py`:

```python
"""Synthetic placed boards for the pin map study's tests: a square part with pins on its sides and the parts its nets run
to, as PlacedPads and PlacedParts (pinmap_input), so the study is tested without a resolve."""
from dataclasses import replace

from placemat.pinmap_input import PlacedPad, PlacedPart, build
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Location

SIDES = ("E", "S", "W", "N")


def settings(**kw):
    """The defaults, with a budget no test meets unless it says so."""
    base = dict(pins_budget_ms=60000)
    base.update(kw)
    return replace(Settings(), **base)


def pad(ref, number, net, x, y, size=0.6, layer=CopperLayer.F, no_connect=False) -> PlacedPad:
    o = ((x - size / 2, y - size / 2), (x + size / 2, y - size / 2), (x + size / 2, y + size / 2), (x - size / 2, y + size / 2))
    return PlacedPad(ref, str(number), net, frozenset([layer]), (o,), Box.of_points(o), Location(x, y), no_connect)


def quad(ref, cx, cy, sides: dict, fields=None, body=4.0, pitch=1.0, rotation=0.0, face="front", may_flip=False) -> tuple:
    """(pads, PlacedPart) of a part `body` mm square centred at (cx, cy), its courtyard 0.25 mm round it, with pins on
    its sides: `sides` {"E" | "S" | "W" | "N": [net, ...]}, each side's pins in order north to south (E, W) or west to
    east (N, S), numbered from 1 in the order E, S, W, N. A net of "" is a pin with none."""
    pads, n, h = [], 0, body / 2.0 - 0.3
    for side in SIDES:
        nets = sides.get(side, ())
        for i, net in enumerate(nets):
            off = -(len(nets) - 1) / 2.0 * pitch + i * pitch
            x, y = {"E": (cx + h, cy + off), "W": (cx - h, cy + off), "N": (cx + off, cy - h), "S": (cx + off, cy + h)}[side]
            n += 1
            pads.append(pad(ref, n, net, x, y))
    c = body / 2.0 + 0.25
    return pads, PlacedPart(ref, Box(cx - c, cy - c, cx + c, cy + c), rotation, face, may_flip, dict(fields or {}))


def two_pad(ref, net_a, net_b, x, y) -> list:
    """A passive centred at (x, y): pad 1 on `net_a` 0.5 mm west, pad 2 on `net_b` 0.5 mm east."""
    return [pad(ref, 1, net_a, x - 0.5, y), pad(ref, 2, net_b, x + 0.5, y)]


def point_pad(ref, net, x, y) -> list:
    return [pad(ref, 1, net, x, y)]


def complete(pads, parts) -> dict:
    """`parts` with every other part the pads name made up from its pads: a box 0.1 mm round them."""
    parts = dict(parts)
    for p in pads:
        if p.ref not in parts:
            b = Box.union([q.box for q in pads if q.ref == p.ref])
            parts[p.ref] = PlacedPart(p.ref, b.inflate(0.1), 0.0, "front")
    return parts


def input_of(pads, parts, quiet=frozenset(), partners=None, netclasses=None, names=None, follow=True) -> tuple:
    """`build` with every other placed part made up from its pads."""
    return build(pads, complete(pads, parts), names or {}, frozenset(quiet), partners or {}, netclasses or {}, follow)


def reversed_four(fields=None) -> tuple:
    """U1 with nets A-D on its east side, north to south, and four test points due east of it in the opposite order:
    every pair of airwires crosses (6 crossings) until A and D, B and C trade pins."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"} if fields is None else fields)
    for i, net in enumerate(["D", "C", "B", "A"]):
        pads += point_pad("TP%d" % (i + 1), net, 20, 8.5 + i)
    return pads, {"U1": u1}


def quad_footprint(ref, cx, cy, sides: dict, fields=None, inst=None):
    """`quad` as a generated board's Footprint, for a BoardGeometry (tests.fixtures.board_geometry) or a resolve."""
    from placemat.board_geometry import Footprint, PadGeom
    from placemat.values import Face
    inst = inst or ref.lower()
    pads, part = quad(ref, cx, cy, sides, fields)
    geoms = tuple(PadGeom(ref, inst, p.number, p.net, p.layers, p.outlines, p.box, False, anchor=p.anchor) for p in pads)
    body = part.courtyard.inflate(-0.25)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, part.courtyard, body, geoms,
                     fields=dict(fields or {}))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_pinmap_input.py`:

```python
"""What the pin map study reads: the studied parts and their nets from the pads alone (a routed net keeps its airwire),
a net followed through a series part, each net's crossing class, and the other airwires."""
import pytest

from placemat.board_geometry import NetClass
from placemat.pinmap_input import build, net_kind, placed_from_geometry
from placemat.ratsnest import board_nets
from tests.fixtures import board_geometry, footprint, track
from tests.pinmap_boards import input_of, point_pad, quad, quad_footprint, reversed_four, two_pad


def test_the_studied_nets_carry_their_ends_and_anchors_and_the_rest_are_the_background():
    pads, parts = reversed_four()
    pads += two_pad("R9", "X", "Y", 30, 30) + point_pad("TP9", "X", 35, 30)
    inp, problems = input_of(pads, parts)
    assert problems == [] and [p.ref for p in inp.parts] == ["U1"]
    a = next(n for n in inp.nets if n.net == "A")
    assert a.ends == (("U1", "1"),) and [(f.ref, f.number) for f in a.fixed] == [("TP4", "1")]
    assert {w.net for w in inp.background} == {"X"}
    assert inp.parts[0].slots.movable == ("A", "B", "C", "D")


def test_a_board_without_a_pool_has_nothing_to_study():
    pads, parts = reversed_four(fields={})
    assert input_of(pads, parts) == (None, [])


def test_a_routed_net_keeps_its_airwire_for_the_study_is_scored_from_the_pads_alone():
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"}),
           footprint("R1", 20, 9.5, w=2, h=1, inst="r1", nets=("A", "N1")),
           footprint("R2", 20, 10.5, w=2, h=1, inst="r2", nets=("B", "N2"))]
    a1 = fps[0].pads[0].airwire_end
    r1 = fps[1].pads[0].airwire_end
    routed = board_geometry(fps, copper=[track("A", a1.x, a1.y, r1.x, r1.y)], width=40, height=40)
    bare = board_geometry(fps, width=40, height=40)
    joined = board_nets([(c.owner, "", c.net, c.layers, c.outlines, c.box, c.box.center) for c in routed.copper
                         if c.kind == "pad"], [(c.kind, c.net, c.layers, c.outlines, c.box, c.anchors)
                                               for c in routed.copper if c.kind == "track"])
    assert joined["A"][1]                                      # with its copper, KiCad's ratsnest has no airwire for A
    got = [build(*placed_from_geometry(g)[:2], {}, frozenset(), {}, g.netclasses)[0] for g in (routed, bare)]
    assert got[0] == got[1]
    a = next(n for n in got[0].nets if n.net == "A")
    assert a.ends == (("U1", "1"),) and [(f.ref, f.number) for f in a.fixed] == [("R1", "1")]


def test_a_net_through_a_series_part_is_followed_to_the_far_net():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    parts = {"U1": u1}
    pads += two_pad("R1", "A", "A_FAR", 15, 9.5) + point_pad("J1", "A_FAR", 30, 9.5)
    pads += two_pad("R2", "B", "B_OPEN", 15, 10.5)                 # its far net goes nowhere else: not followed
    inp, _ = input_of(pads, parts)
    a, b = (next(n for n in inp.nets if n.net == x) for x in ("A", "B"))
    assert (a.via, a.far, [(f.ref, f.number) for f in a.fixed]) == ("R1", "A_FAR", [("J1", "1")])
    assert (b.via, b.far, [(f.ref, f.number) for f in b.fixed]) == ("", "", [("R2", "1")])
    assert "A_FAR" not in {w.net for w in inp.background}
    inp, _ = input_of(pads, parts, follow=False)
    assert next(n for n in inp.nets if n.net == "A").via == ""


def test_a_nets_crossing_class_is_plane_pair_impedance_or_plain():
    classes = {"Z": NetClass("SE50", 0.1, 0.1, 0.4, 0.2, tuning_profile="SE50"), "P": NetClass("Default", 0.1, 0.1, 0.4, 0.2)}
    assert net_kind("GND", {"GND"}, {}, classes) == "plane"
    assert net_kind("P", set(), {"P": "N"}, classes) == "pair"
    assert net_kind("Z", set(), {}, classes) == "impedance"
    assert net_kind("P", set(), {}, classes) == "plain"
```

Create `tests/test_pinmap_netclass.py`:

```python
"""A net class's tuning profile, KiCad 10's controlled impedance, is read with the class: the pin map study weighs a
crossing of such a net at `pins.impedance_weight`."""
import json
import shutil
from pathlib import Path

from tests.conftest import needs_kicad

GENERATED = Path(__file__).resolve().parents[1] / "fixtures" / "fairing" / "core" / "generated"


@needs_kicad
def test_a_class_that_names_a_tuning_profile_carries_it_to_its_nets(tmp_path):
    from placemat.kicad.read import read_board
    for f in GENERATED.glob("layout.kicad_p*"):
        shutil.copy(f, tmp_path / f.name)
    pro = tmp_path / "layout.kicad_pro"
    doc = json.loads(pro.read_text())
    for c in doc["net_settings"]["classes"]:
        if c["name"] == "50Ohm SE":
            c["tuning_profile"] = "SE50"
    pro.write_text(json.dumps(doc, indent=2))
    g = read_board(tmp_path / "layout.kicad_pcb")
    profiled = {n for n, nc in g.netclasses.items() if nc.tuning_profile}
    assert profiled and all(g.netclasses[n].tuning_profile == "SE50" for n in profiled)
    assert all("50Ohm SE" in g.netclasses[n].name for n in profiled)
```

Add this line to `tests/slow_tests.txt` (it reads a 2.6 MB board):

```
tests/test_pinmap_netclass.py::test_a_class_that_names_a_tuning_profile_carries_it_to_its_nets
```

- [ ] **Step 3: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_input.py -q -n 2` and `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_pinmap_netclass.py -q --full`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap_input'` and `AttributeError: 'NetClass' object has no attribute 'tuning_profile'`.

- [ ] **Step 4: Carry the net class's tuning profile**

In `src/placemat/board_geometry.py`, in `class NetClass`, find:

```python
    diff_pair_gap: float | None = None       # and its gap
```

and add after it:

```python
    tuning_profile: str = ""                 # the KiCad tuning profile the class names: a controlled impedance; "" for none
```

In `src/placemat/kicad/read.py`, in `_netclasses`, replace:

```python
        classes[name] = NetClass(",".join(parts) or "Default", mm(nc.GetTrackWidth()),
                                 mm(nc.GetClearance()), mm(nc.GetViaDiameter()), mm(nc.GetViaDrill()),
                                 (mm(nc.GetDiffPairWidth()) or None) if pair else None,
                                 (mm(nc.GetDiffPairGap()) or None) if pair else None)
```

with:

```python
        # KiCad 10 names a controlled impedance on a class as its tuning profile; an older pcbnew has none
        profile = str(nc.GetTuningProfile()) if hasattr(nc, "HasTuningProfile") and nc.HasTuningProfile() else ""
        classes[name] = NetClass(",".join(parts) or "Default", mm(nc.GetTrackWidth()),
                                 mm(nc.GetClearance()), mm(nc.GetViaDiameter()), mm(nc.GetViaDrill()),
                                 (mm(nc.GetDiffPairWidth()) or None) if pair else None,
                                 (mm(nc.GetDiffPairGap()) or None) if pair else None, profile)
```

(Checked while planning: on KiCad 10.0.6 the effective class `GetNetClassSlow()` of a net in a class with `"tuning_profile": "SE50"` in the `.kicad_pro` reports `HasTuningProfile() == True` and `GetTuningProfile() == "SE50"`.)

- [ ] **Step 5: Write the input module**

Create `src/placemat/pinmap_input.py`:

```python
"""What the pin map study reads from a placed board, as data: the studied parts and their pins, every net that touches
them, and the board's other airwires.

Scored as unrouted: the nets come from the pads alone (`ratsnest.board_nets(pads, copper=())`). A laid board's tracks,
vias and pours would join a routed net's pads into one cluster with no airwire left to move, so they are ignored for
connectivity - never torn up - and a first preview and a laid board are scored on the same terms. Pads that touch are
still one cluster, as KiCad has them.

A net that reaches a studied pin through a two-pad series part (a termination resistor) and nothing else is followed on
to the series part's far net, as one connection (`pins.follow_series`)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .ratsnest import Anchor, board_nets, mst
from .values import Box, Location

from .pinmap_geom import outward
from .pinmap_rules import natural, part_pins, read_rules

KINDS = ("plain", "impedance", "pair", "plane")      # a net's crossing class, weakest of the signal ones first


@dataclass(frozen=True)
class PlacedPad:
    """A pad where the placement put it: what `board_nets` takes, and whether the capture marks it unconnected."""
    ref: str
    number: str
    net: str
    layers: frozenset
    outlines: tuple
    box: Box
    anchor: Location
    no_connect: bool = False


@dataclass(frozen=True)
class PlacedPart:
    """A part where the placement put it: its courtyard's box, rotation and face, whether its declaration lets it stand
    on the other face (`face=Face.EITHER`), and its footprint's fields (the capture's `Pm.*`)."""
    ref: str
    courtyard: Box
    rotation: float
    face: str
    may_flip: bool = False
    fields: dict = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Pin:
    """A studied part's pad: its anchor in the part's own frame (the courtyard box's centre, as the part stands) and the
    outward normal of the box side it is nearest."""
    number: str
    name: str
    x: float
    y: float
    nx: float
    ny: float


@dataclass(frozen=True)
class StudiedPart:
    ref: str
    cx: float
    cy: float
    hw: float                   # half the courtyard box's width and height
    hh: float
    rotation: float
    face: str
    may_flip: bool
    pins: tuple                 # Pin, by pad number
    slots: object               # pinmap_rules.PartPins

    def pin(self, number: str) -> Pin:
        return next(p for p in self.pins if p.number == number)


@dataclass(frozen=True)
class StudyNet:
    """A net with a pad on a studied part. `fixed` are its anchors on other parts, `joined` index pairs of them that
    touch, `ends` its (ref, pad number) on studied parts as they stand. A followed net keeps its own name and carries the
    series part (`via`) and the net it is followed on to (`far`), whose anchors are its `fixed`."""
    net: str
    kind: str
    fixed: tuple
    joined: tuple
    ends: tuple
    via: str = ""
    far: str = ""


@dataclass(frozen=True)
class Wire:
    """One of the board's other airwires: a straight segment of `net`, crossing class `kind`."""
    net: str
    kind: str
    a: tuple
    b: tuple


@dataclass(frozen=True)
class StudyInput:
    parts: tuple                # StudiedPart, by ref
    nets: tuple                 # StudyNet, by net
    background: tuple           # Wire
    names: dict = field(default_factory=dict)      # ref -> {pad number: pin name}

    def part(self, ref: str) -> StudiedPart:
        return next(p for p in self.parts if p.ref == ref)


def net_kind(net: str, quiet, partners: dict, netclasses: dict) -> str:
    """A net's crossing class: plane (a plane's or a free net), pair (a differential pair's half), impedance (its net
    class names a tuning profile: a controlled impedance, as KiCad 10 declares one), else plain."""
    if net in quiet:
        return "plane"
    if net in partners:
        return "pair"
    nc = netclasses.get(net)
    if nc is not None and getattr(nc, "tuning_profile", ""):
        return "impedance"
    return "plain"


def _merged(pads) -> list:
    """One PlacedPad per (ref, pad number): a pad drawn as several lands is one pin to the study."""
    out: dict = {}
    for p in pads:
        k = (p.ref, p.number)
        was = out.get(k)
        if was is None:
            out[k] = p
        else:
            out[k] = PlacedPad(p.ref, p.number, was.net or p.net, was.layers | p.layers, was.outlines + p.outlines,
                               Box.union([was.box, p.box]), was.anchor, was.no_connect or p.no_connect)
    return [out[k] for k in sorted(out, key=lambda k: (k[0], natural(k[1])))]


def build(pads, parts: dict, names: dict, quiet, partners: dict, netclasses: dict, follow_series: bool = True) -> tuple:
    """(StudyInput or None, [Problem]): `pads` every placed pad (PlacedPad), `parts` {ref: PlacedPart} of the placed
    parts, `names` {ref: {pad number: pin name}}, `quiet` the plane and free nets, `partners` {net: its pair's other
    half}, `netclasses` {net: NetClass}. None when no part has a pool and a net that may move."""
    pads = _merged(pads)
    of_ref: dict = {}
    for p in pads:
        of_ref.setdefault(p.ref, []).append(p)
    problems, read = [], []
    for ref in sorted(parts):
        mine = of_ref.get(ref, [])
        rules, said = read_rules(ref, parts[ref].fields, [(p.number, p.net) for p in mine], names.get(ref, {}))
        problems += said
        if rules is not None:
            read.append((ref, rules))
    if not read:
        return None, problems
    by_net = board_nets([(p.ref, p.number, p.net, p.layers, p.outlines, p.box, p.anchor) for p in pads], copper=())
    connected = frozenset(n for n, (anchors, _) in by_net.items() if len({(a.ref, a.number) for a in anchors}) >= 2)
    studied = []
    for ref, rules in read:
        part, mine = parts[ref], of_ref.get(ref, [])
        slots, said = part_pins(rules, [(p.number, p.net, p.no_connect) for p in mine], connected, quiet)
        problems += said
        if slots is None or not slots.movable:
            continue
        c = part.courtyard.center
        hw, hh = part.courtyard.width / 2.0, part.courtyard.height / 2.0
        pins = []
        for p in mine:
            x, y = p.anchor.x - c.x, p.anchor.y - c.y
            nx, ny = outward(x, y, hw, hh)
            pins.append(Pin(p.number, names.get(ref, {}).get(p.number, ""), x, y, nx, ny))
        studied.append(StudiedPart(ref, c.x, c.y, hw, hh, part.rotation, part.face, part.may_flip, tuple(pins), slots))
    if not studied:
        return None, problems
    on = {s.ref for s in studied}
    kind = lambda n: net_kind(n, quiet, partners, netclasses)
    nets, used = [], set()
    for net in sorted(by_net):
        anchors, joined = by_net[net]
        if net in quiet or not any(a.ref in on for a in anchors):
            continue
        ends = tuple(sorted({(a.ref, a.number) for a in anchors if a.ref in on}, key=lambda e: (e[0], natural(e[1]))))
        keep = [i for i, a in enumerate(anchors) if a.ref not in on]
        fixed, via, far, k = _fixed(anchors, joined, keep), "", "", kind(net)
        followed = _follow(net, ends, fixed[0], of_ref, on, by_net, quiet) if follow_series else None
        if followed is not None:
            via, far, fixed = followed
            used.add(far)
            k = max(k, kind(far), key=KINDS.index)
        nets.append(StudyNet(net, k, fixed[0], fixed[1], ends, via, far))
    studied_nets = {n.net for n in nets}
    background = []
    for net in sorted(by_net):
        if net in studied_nets or net in used:
            continue
        anchors, joined = by_net[net]
        for e in mst(net, anchors, joined):
            background.append(Wire(net, kind(net), (e.a.x, e.a.y), (e.b.x, e.b.y)))
    return StudyInput(tuple(studied), tuple(nets), tuple(background),
                      {s.ref: dict(names.get(s.ref, {})) for s in studied}), problems


def _fixed(anchors, joined, keep) -> tuple:
    """(anchors, joined) of the anchors at `keep`, renumbered."""
    at = {i: k for k, i in enumerate(keep)}
    return (tuple(Anchor(anchors[i].ref, anchors[i].number, anchors[i].x, anchors[i].y) for i in keep),
            tuple((at[i], at[j]) for i, j in joined if i in at and j in at))


def _follow(net, ends, fixed, of_ref, on, by_net, quiet):
    """(series part, far net, (anchors, joined)) when `net` joins one studied pin to one pad of a two-pad part not studied,
    whose other pad is on a net that is not quiet, reaches no studied part, and has other pads: that net's anchors less
    the series part's own. None otherwise."""
    if len(ends) != 1 or len(fixed) != 1:
        return None
    via = fixed[0].ref
    pads = of_ref.get(via, [])
    if via in on or len(pads) != 2:
        return None
    other = next(p for p in pads if p.number != fixed[0].number)
    far = other.net
    if not far or far == net or far in quiet or far not in by_net:
        return None
    anchors, joined = by_net[far]
    if any(a.ref in on for a in anchors):
        return None
    keep = [i for i, a in enumerate(anchors) if a.ref != via]
    if not keep:
        return None
    return via, far, _fixed(anchors, joined, keep)


def placed_from_geometry(geometry, either=frozenset()) -> tuple:
    """(pads, {ref: PlacedPart}) of a board where its file has its parts (a laid board read from disk, a bench case).
    Its copper is not read: the study is scored as unrouted. `either` are the parts that may stand on the other face."""
    pads, parts = [], {}
    for fp in geometry.footprints:
        for p in fp.pads:
            pads.append(PlacedPad(fp.ref, p.number, p.net, frozenset(p.layers), tuple(p.outlines), p.box, p.airwire_end,
                                  p.no_connect))
        parts[fp.ref] = PlacedPart(fp.ref, fp.courtyard_box, fp.rotation, fp.face.value, fp.ref in either, dict(fp.fields))
    return pads, parts
```

- [ ] **Step 6: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_input.py -q -n 2` and `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_pinmap_netclass.py -q --full`
Expected: PASS (5 and 1 tests).

- [ ] **Step 7: Commit**

```bash
git add src/placemat/board_geometry.py src/placemat/kicad/read.py src/placemat/pinmap_input.py tests/pinmap_boards.py tests/test_pinmap_input.py tests/test_pinmap_netclass.py tests/slow_tests.txt
git commit -m "Pin map study: its input from the pads alone, series parts followed, a net class's tuning profile read"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 5: Scoring, part 2 - weighted crossings, length, bend and the incremental recount

**Files:**
- Create: `src/placemat/pinmap_score.py`
- Test: `tests/test_pinmap_score.py`

**Interfaces:**
- Consumes: `ratsnest.Anchor`, `ratsnest.mst`, `ratsnest._cross_nm(ax, ay, bx, by, cx, cy, dx, dy)` and `ratsnest._nm(v)` (KiCad's nanometre rounding and proper-crossing test); Task 3's `bend`, `exit_of`, `length`, `route`; Task 4's `StudyInput`, `StudyNet`, `Wire`; settings `pins_pair_weight`, `pins_impedance_weight`, `score_crossing_plane`, `pins_length_weight`, `pins_bend_weight`, `pins_exit_mm`.
- Produces:
  - `Weights(pair, impedance, plane, length, bend)` with `Weights.of(settings)` and `.crossing(kind_a, kind_b) -> float`.
  - `Breakdown(total, against, among, weighted, length_mm, bend_deg)` with `.to_json()`.
  - `CELL_NM = 2_000_000`; `_segments(paths) -> tuple` of `(ax, ay, bx, by, minx, miny, maxx, maxy)` in nm; `segments_crossing(a, b) -> int`.
  - `Background(wires, weights)` with `.cross(net, kind, segs) -> (weighted, count)`.
  - `NetWires(paths, length, bend, box, segs)`.
  - `Scorer(inp, poses: {ref: Pose}, weights, background, margin)` with `.exit(ref, number)`, `.wires(net, ends)`, `.single(net, ends) -> (cost, weighted, count)`, `.pair(a, ea, b, eb) -> (weighted, count)`, `.total(assign) -> Breakdown`. An assignment is `{net: ends}`, `ends` a tuple of `(ref, pad number)` sorted by ref then `natural(number)`.
  - `Tally(scorer, assign)` with `.value`, `.assign`, `.delta(changes) -> float`, `.apply(changes, d)`.

The routed-board test the spec adds is here (`test_a_routed_board_scores_as_the_same_board_without_its_copper`): a net joined by copper still gets its airwire, and the score equals the same board's with its copper removed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_score.py`:

```python
"""The pin map study's score: weighted crossings against the other airwires and among the studied nets, length and bend;
the background asked only near a path; a move's price recounting only the nets it touches; and a routed board scored as
the same board without its copper."""
import random

import pytest

from placemat.pinmap_geom import Pose
from placemat.pinmap_input import Wire, build, placed_from_geometry
from placemat.pinmap_score import Background, Scorer, Tally, Weights
from tests.fixtures import board_geometry, footprint, track
from tests.pinmap_boards import input_of, point_pad, quad, quad_footprint, reversed_four, settings


def scorer_of(inp, s=None, poses=None):
    s = s or settings()
    w = Weights.of(s)
    poses = poses or {p.ref: Pose(p.cx, p.cy) for p in inp.parts}
    return Scorer(inp, poses, w, Background(inp.background, w), s.pins_exit_mm)


def present(inp):
    return {n.net: n.ends for n in inp.nets}


def test_a_crossing_counts_one_more_for_a_pair_or_a_controlled_impedance_and_the_plane_weight_for_a_plane():
    w = Weights(pair=5.0, impedance=3.0, plane=0.25)
    assert w.crossing("plain", "plain") == 1.0
    assert w.crossing("plain", "pair") == 5.0 and w.crossing("impedance", "plain") == 3.0
    assert w.crossing("pair", "impedance") == 5.0
    assert w.crossing("plane", "pair") == 0.25


def test_the_background_counts_the_wires_a_path_crosses_and_not_its_own_net_or_a_weightless_plane():
    w = Weights(pair=5.0, plane=0.0)
    bg = Background([Wire("X", "plain", (5, 0), (5, 10)), Wire("P", "pair", (7, 0), (7, 10)),
                     Wire("A", "plain", (6, 0), (6, 10)), Wire("G", "plane", (8, 0), (8, 10))], w)
    from placemat.pinmap_score import _segments
    segs = _segments([((0.0, 5.0), (10.0, 5.0))])
    assert bg.cross("A", "plain", segs) == (6.0, 2)            # X at 1, P at 5; its own net and the plane not counted


def test_four_nets_in_reverse_order_cross_six_times_until_they_trade_pins():
    inp, _ = input_of(*reversed_four())
    s = scorer_of(inp)
    now = s.total(present(inp))
    assert (now.among, now.against) == (6, 0) and now.weighted == 6.0
    swapped = dict(present(inp), A=(("U1", "4"),), D=(("U1", "1"),), B=(("U1", "3"),), C=(("U1", "2"),))
    better = s.total(swapped)
    assert better.among == 0 and better.total < now.total
    w = Weights.of(settings())
    assert better.total == pytest.approx(w.length * better.length_mm + w.bend * better.bend_deg)


def test_a_move_is_priced_by_recounting_the_nets_it_touches_as_the_whole_total_would():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C"], "S": ["D", "E", ""], "W": ["F", "", ""]},
                    {"Pm.PinPool": "1-9"})
    rng = random.Random(1)
    for i, net in enumerate("ABCDEF"):
        pads += point_pad("T%d" % i, net, rng.uniform(0, 25), rng.uniform(0, 25))
    pads += point_pad("Q1", "X", 0, 0) + point_pad("Q2", "X", 25, 25)
    inp, _ = input_of(pads, {"U1": u1})
    s = scorer_of(inp)
    tally = Tally(s, present(inp))
    pins = [str(n) for n in range(1, 10)]
    for _ in range(40):
        a, b = rng.sample(sorted(tally.assign), 2)
        change = {a: tally.assign[b], b: tally.assign[a]} if rng.random() < 0.5 else {a: (("U1", rng.choice(pins)),)}
        d = tally.delta(change)
        after = dict(tally.assign, **change)
        assert d == pytest.approx(s.total(after).total - s.total(tally.assign).total, abs=1e-9)
        tally.apply(change, d)
    assert tally.value == pytest.approx(s.total(tally.assign).total, abs=1e-6)


def test_a_net_of_several_pads_is_scored_on_its_tree_with_the_studied_pin_at_its_exit():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("T1", "A", 20, 9.5) + point_pad("T2", "A", 30, 9.5)
    inp, _ = input_of(pads, {"U1": u1})
    nw = scorer_of(inp).wires("A", (("U1", "1"),))
    assert sorted(tuple(sorted(p)) for p in nw.paths) == [((12.75, 9.5), (20.0, 9.5)), ((20.0, 9.5), (30.0, 9.5))]
    assert nw.length == pytest.approx(17.25) and nw.bend == 0.0


def test_a_routed_board_scores_as_the_same_board_without_its_copper():
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"}),
           footprint("R1", 20, 10.5, w=2, h=1, inst="r1", nets=("A", "N1")),
           footprint("R2", 20, 9.5, w=2, h=1, inst="r2", nets=("B", "N2"))]
    a1, r1 = fps[0].pads[0].airwire_end, fps[1].pads[0].airwire_end
    routed = board_geometry(fps, copper=[track("A", a1.x, a1.y, r1.x, r1.y)], width=40, height=40)
    bare = board_geometry(fps, width=40, height=40)
    totals = []
    for g in (routed, bare):
        inp, _ = build(*placed_from_geometry(g), {}, frozenset(), {}, g.netclasses)
        totals.append(scorer_of(inp).total(present(inp)))
    assert totals[0] == totals[1] and totals[0].among == 1        # A still has its airwire, and it crosses B's
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_score.py -q -n 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap_score'`.

- [ ] **Step 3: Write the module**

Create `src/placemat/pinmap_score.py`:

```python
"""The pin map study's score of one assignment of nets to pins, at one pose of each studied part.

Total = weighted crossings of the studied nets' airwires against every other airwire, plus weighted crossings among the
studied nets, plus `pins.length_weight` times their airwire length in mm, plus `pins.bend_weight` times their summed bend
angles in degrees. A studied net's airwires are the minimum spanning tree of its pads (ratsnest.mst), each studied pin
taken at its exit point and each airwire to one taken round the body (pinmap_geom.route).

A crossing counts 1, `pins.pair_weight` where either airwire is a differential pair's, `pins.impedance_weight` where either
is in a controlled-impedance class (the larger where both apply), and `score.crossing_plane` where either is a plane's or
a free net's, as the run score weighs those.

Incremental: the other airwires are bucketed once on a 2 mm grid (`Background`), and a net's airwires, its crossings
with the background and its crossings with each other studied net are worked out once per placing of its ends and kept
(`Scorer`), so a move recounts only the nets it touches (`Tally`)."""
from __future__ import annotations

from dataclasses import dataclass

from .ratsnest import Anchor, _cross_nm, _nm, mst

from .pinmap_geom import bend, exit_of, length, route


@dataclass(frozen=True)
class Weights:
    pair: float = 1.0
    impedance: float = 1.0
    plane: float = 0.0
    length: float = 0.0
    bend: float = 0.0

    @staticmethod
    def of(settings) -> "Weights":
        return Weights(settings.pins_pair_weight, settings.pins_impedance_weight, settings.score_crossing_plane,
                       settings.pins_length_weight, settings.pins_bend_weight)

    def _one(self, kind: str) -> float:
        return self.pair if kind == "pair" else self.impedance if kind == "impedance" else 1.0

    def crossing(self, a: str, b: str) -> float:
        """What a crossing of an airwire of class `a` with one of class `b` counts."""
        if a == "plane" or b == "plane":
            return self.plane
        return max(self._one(a), self._one(b))


@dataclass(frozen=True)
class Breakdown:
    """A score and its parts: crossings against the other airwires and among the studied nets (counts), their weighted
    sum, the airwire length in mm and the summed bend in degrees."""
    total: float
    against: int
    among: int
    weighted: float
    length_mm: float
    bend_deg: float

    def to_json(self) -> dict:
        return {"total": round(self.total, 3), "against": self.against, "among": self.among,
                "weighted": round(self.weighted, 3), "length_mm": round(self.length_mm, 3), "bend_deg": round(self.bend_deg, 1)}


CELL_NM = 2_000_000      # ratsnest's grid (2 mm), in whole nanometres


def _cells_nm(s):
    """The grid cells a segment's box (whole nanometres) touches."""
    for cx in range(s[4] // CELL_NM, s[6] // CELL_NM + 1):
        for cy in range(s[5] // CELL_NM, s[7] // CELL_NM + 1):
            yield cx, cy


class Background:
    """The board's other airwires on a 2 mm grid. `cross(net, kind, segs)` is the weighted count and the count of their
    crossings with a net's segments (`_segments`), each segment's candidates taken in wire order; a plane's wire is left
    out when `score.crossing_plane` is 0, as it weighs nothing."""

    def __init__(self, wires, weights: Weights):
        self.weights = weights
        self.wires = [w for w in wires if not (w.kind == "plane" and weights.plane <= 0)]
        self.segs = _segments([(w.a, w.b) for w in self.wires])
        self.grid: dict = {}
        for k, s in enumerate(self.segs):
            for c in _cells_nm(s):
                self.grid.setdefault(c, []).append(k)

    def cross(self, net: str, kind: str, segs) -> tuple:
        total, count = 0.0, 0
        for s in segs:
            near = set()
            for c in _cells_nm(s):
                near.update(self.grid.get(c, ()))
            for k in sorted(near):
                t = self.segs[k]
                if t[6] < s[4] or s[6] < t[4] or t[7] < s[5] or s[7] < t[5]:
                    continue
                w = self.wires[k]
                if w.net != net and _cross_nm(s[0], s[1], s[2], s[3], t[0], t[1], t[2], t[3]):
                    total += self.weights.crossing(kind, w.kind)
                    count += 1
        return total, count


@dataclass(frozen=True)
class NetWires:
    """One studied net's airwires: their paths, length, summed bend over its studied ends, the box round them (nm),
    and their segments in whole nanometres, each with its own box, for the crossing tests."""
    paths: tuple
    length: float
    bend: float
    box: tuple
    segs: tuple


def _segments(paths) -> tuple:
    out = []
    for path in paths:
        for p, q in zip(path, path[1:]):
            ax, ay, bx, by = _nm(p[0]), _nm(p[1]), _nm(q[0]), _nm(q[1])
            out.append((ax, ay, bx, by, min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
    return tuple(out)


def _box(segs) -> tuple:
    if not segs:
        return (0, 0, 0, 0)
    return (min(s[4] for s in segs), min(s[5] for s in segs), max(s[6] for s in segs), max(s[7] for s in segs))


def segments_crossing(a, b) -> int:
    """How many times two nets' segments (`_segments`) cross."""
    n = 0
    for s in a:
        for t in b:
            if s[6] < t[4] or t[6] < s[4] or s[7] < t[5] or t[7] < s[5]:
                continue
            if _cross_nm(s[0], s[1], s[2], s[3], t[0], t[1], t[2], t[3]):
                n += 1
    return n


class Scorer:
    """Scores assignments at one set of poses: `poses` {ref: Pose} for every studied part (the parts not being turned at
    their present one). An assignment is {net: ends}, ends a tuple of (ref, pad number) sorted as StudyNet.ends is."""

    def __init__(self, inp, poses: dict, weights: Weights, background: Background, margin: float):
        self.inp, self.poses, self.w, self.bg, self.margin = inp, poses, weights, background, margin
        self.parts = {p.ref: p for p in inp.parts}
        self.nets = {n.net: n for n in inp.nets}
        self._exits: dict = {}
        self._wires: dict = {}
        self._single: dict = {}
        self._pair: dict = {}

    def exit(self, ref: str, number: str):
        k = (ref, number)
        e = self._exits.get(k)
        if e is None:
            part = self.parts[ref]
            pin = part.pin(number)
            e = exit_of(ref, self.poses[ref], pin.x, pin.y, (pin.nx, pin.ny), part.hw, part.hh, self.margin)
            self._exits[k] = e
        return e

    def wires(self, net: str, ends: tuple) -> NetWires:
        k = (net, ends)
        hit = self._wires.get(k)
        if hit is not None:
            return hit
        n = self.nets[net]
        anchors = list(n.fixed)
        exits = [self.exit(r, num) for r, num in ends]
        anchors += [Anchor(r, num, e.at[0], e.at[1]) for (r, num), e in zip(ends, exits)]
        index = {id(a): i for i, a in enumerate(anchors)}
        first = len(n.fixed)
        end_of = lambda i: exits[i - first] if i >= first else (anchors[i].x, anchors[i].y)
        paths, bends = [], {}
        for edge in mst(net, anchors, n.joined):
            i, j = index[id(edge.a)], index[id(edge.b)]
            a, b = end_of(i), end_of(j)
            paths.append(route(a, b))
            for me, other in ((i, j), (j, i)):
                if me >= first:
                    e = exits[me - first]
                    to = anchors[other]
                    d = bend(e.normal, e.at, (to.x, to.y))
                    bends[me] = min(bends.get(me, d), d)
        paths = tuple(paths)
        segs = _segments(paths)
        hit = NetWires(paths, sum(length(p) for p in paths), sum(bends[k] for k in sorted(bends)), _box(segs), segs)
        self._wires[k] = hit
        return hit

    def single(self, net: str, ends: tuple) -> tuple:
        """(cost, weighted, count) of one net alone: its crossings with the background, weighted and counted, plus its
        length and bend weighted."""
        k = (net, ends)
        hit = self._single.get(k)
        if hit is None:
            nw = self.wires(net, ends)
            kind = self.nets[net].kind
            weighted, count = self.bg.cross(net, kind, nw.segs)
            hit = (weighted + self.w.length * nw.length + self.w.bend * nw.bend, weighted, count)
            self._single[k] = hit
        return hit

    def pair(self, a: str, ea: tuple, b: str, eb: tuple) -> tuple:
        """(weighted, count) of the crossings between two studied nets' airwires."""
        if b < a:
            a, ea, b, eb = b, eb, a, ea
        k = (a, ea, b, eb)
        hit = self._pair.get(k)
        if hit is None:
            wa, wb = self.wires(a, ea), self.wires(b, eb)
            if wa.box[2] < wb.box[0] or wb.box[2] < wa.box[0] or wa.box[3] < wb.box[1] or wb.box[3] < wa.box[1]:
                hit = (0.0, 0)
            else:
                n = segments_crossing(wa.segs, wb.segs)
                hit = (n * self.w.crossing(self.nets[a].kind, self.nets[b].kind), n)
            self._pair[k] = hit
        return hit

    def total(self, assign: dict) -> Breakdown:
        names = sorted(assign)
        weighted, against, among, ln, bd = 0.0, 0, 0, 0.0, 0.0
        for n in names:
            _, w, c = self.single(n, assign[n])
            nw = self.wires(n, assign[n])
            weighted += w
            against += c
            ln += nw.length
            bd += nw.bend
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                w, c = self.pair(a, assign[a], b, assign[b])
                weighted += w
                among += c
        return Breakdown(weighted + self.w.length * ln + self.w.bend * bd, against, among, weighted, ln, bd)


class Tally:
    """An assignment being searched, and its total kept as moves are made: `delta` prices a change to some nets' ends
    by recounting only those nets, against the background and against every other net; `apply` makes it."""

    def __init__(self, scorer: Scorer, assign: dict):
        self.s = scorer
        self.assign = dict(assign)
        self.names = sorted(self.assign)
        self.value = scorer.total(self.assign).total

    def delta(self, changes: dict) -> float:
        s, now = self.s, self.assign
        moved = sorted(changes)
        d = 0.0
        for n in moved:
            d += s.single(n, changes[n])[0] - s.single(n, now[n])[0]
        for n in moved:
            for m in self.names:
                if m in changes:
                    continue
                d += s.pair(n, changes[n], m, now[m])[0] - s.pair(n, now[n], m, now[m])[0]
        for i, n in enumerate(moved):
            for m in moved[i + 1:]:
                d += s.pair(n, changes[n], m, changes[m])[0] - s.pair(n, now[n], m, now[m])[0]
        return d

    def apply(self, changes: dict, d: float) -> None:
        self.assign.update(changes)
        self.value += d
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_score.py tests/test_pinmap_input.py -q -n 2`
Expected: PASS (6 and 5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pinmap_score.py tests/test_pinmap_score.py
git commit -m "Pin map study: weighted crossings, length and bend, a move recounting only the nets it touches"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 6: The search - first map, local search, groups, poses, determinism, the clock

**Files:**
- Create: `src/placemat/pinmap_search.py`
- Test: `tests/test_pinmap_search.py`

**Interfaces:**
- Consumes: Task 2's `Problem`, `natural`, `PartPins` (via `StudiedPart.slots`); Task 3's `Pose`; Task 5's `Background`, `Breakdown`, `Scorer`, `Tally`, `Weights`; settings `pins_rotations`, `pins_faces`, `pins_seeds`, `pins_anneal_moves`, `pins_anneal_start`, `pins_anneal_end`, `pins_budget_ms`, `pins_joint_combinations`, `pins_exit_mm`.
- Produces:
  - `Clock(ms, now=time.perf_counter)` with `.out()`.
  - `PoseResult(poses: tuple[(ref, turn, flip)], breakdown, assign)`, `GroupResult(refs, present, present_assign, results, searched, of, budget_out, first_map, problems=())`.
  - `poses_of(part, settings) -> list[(turn, flip)]` (present first, each turn once, mod 360).
  - `hungarian(cost) -> list | None`.
  - `first_map(scorer, inp, refs, assign) -> (assign, [Problem])`.
  - `anneal(scorer, inp, refs, start, settings, seed_key, clock) -> (best, value, ran_out)`.
  - `study_group(inp, refs: tuple, settings, background, clock=None) -> GroupResult` (the clock defaults to `pins.budget_ms` times the group's parts; combinations capped at `pins.joint_combinations`, the present ones first).

Determinism: every random stream is `random.Random("<refs>|<pose>|<seed>")` (string seeds are hashed with SHA-512 by `random`, so they do not depend on `PYTHONHASHSEED`), sets are iterated sorted, and ties go to the lower pin. A clock that runs out stops between moves (checked every 32) or between poses; such a study keeps the best found and is not deterministic, which the facts say (`budget_out`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_search.py`:

```python
"""The pin map study's search: a first map by minimum-cost matching, then a local search of moves, swaps and group moves
under the constraints, per pose; deterministic; stopped by its clock with the best found."""
import itertools

import pytest

from placemat.pinmap_score import Background, Weights
from placemat.pinmap_search import Clock, hungarian, poses_of, study_group
from tests.pinmap_boards import input_of, point_pad, quad, reversed_four, settings


def run(inp, s=None, refs=("U1",), clock=None):
    s = s or settings()
    return study_group(inp, refs, s, Background(inp.background, Weights.of(s)), clock)


def best(g):
    return min(g.results, key=lambda r: r.breakdown.total)


def pin(result, net, ref="U1"):
    return dict(result.assign[net])[ref]


def test_the_matching_is_the_cheapest_and_refuses_what_cannot_be_matched():
    inf = float("inf")
    assert hungarian([[4, 1, 3], [2, 0, 5], [3, 2, 2]]) == [1, 0, 2]
    assert hungarian([[1, 2, 3], [1, 2, 3]]) == [0, 1]
    assert hungarian([[1, inf], [2, inf]]) is None
    assert hungarian([]) == []


def test_four_nets_in_reverse_order_are_uncrossed_at_the_present_rotation():
    inp, _ = input_of(*reversed_four())
    g = run(inp, settings(pins_rotations=(0.0,)))
    r = g.results[0]
    assert g.present.among == 6 and r.breakdown.among == 0
    assert [pin(r, n) for n in "ABCD"] == ["4", "3", "2", "1"]


def test_each_constraint_holds_fixed_allow_deny_and_a_group_kept_whole_and_in_order():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D", "E", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinFixed": "1", "Pm.PinAllow": "B:2,3", "Pm.PinDeny": "C:3",
                     "Pm.PinGroup": "bus:4-5"})
    for i, net in enumerate(["A", "B", "C", "D", "E"]):
        pads += point_pad("T%d" % i, net, 20, 12.5 - i)                 # every target in reverse order
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, settings(pins_rotations=(0.0,)))
    r = g.results[0]
    assert pin(r, "A") == "1" and pin(r, "B") in ("2", "3") and pin(r, "C") != "3"
    d, e = int(pin(r, "D")), int(pin(r, "E"))
    assert e == d + 1                                                   # the group moved whole, in its order
    assert r.breakdown.total < g.present.total


def test_a_net_whose_target_is_behind_the_part_is_moved_to_the_side_that_faces_it():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""], "W": ["", ""]}, {"Pm.PinPool": "1-4"})
    pads += point_pad("T1", "A", 0, 10)
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, settings(pins_rotations=(0.0,)))
    assert pin(g.results[0], "A") in ("3", "4")
    assert g.present.length_mm > g.results[0].breakdown.length_mm + 4.0   # the way round the body is gone


def test_a_diagonal_turn_wins_on_the_bend_when_it_is_listed_and_is_not_reported_when_it_is_not():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("T1", "A", 22, -2)
    inp, _ = input_of(pads, {"U1": u1})
    eighths = run(inp, settings(pins_rotations=tuple(range(0, 360, 45))))
    b = best(eighths)
    assert b.poses == (("U1", 45.0, False),) and b.breakdown.bend_deg < 5.0
    quarters = run(inp, settings())
    assert {p[1] for r in quarters.results for p in r.poses} == {0.0, 90.0, 180.0, 270.0}


def test_the_other_face_is_studied_only_when_asked_and_the_part_may_stand_there():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"}, may_flip=True)
    pads += point_pad("T1", "A", 22, 10)
    inp, _ = input_of(pads, {"U1": u1})
    assert poses_of(inp.parts[0], settings()) == [(0.0, False), (90.0, False), (180.0, False), (270.0, False)]
    assert (90.0, True) in poses_of(inp.parts[0], settings(pins_faces=True))
    g = run(inp, settings(pins_faces=True))
    assert g.of == 8 and any(p[2] for r in g.results for p in r.poses)


def test_the_same_board_gives_the_same_maps_and_totals():
    inp, _ = input_of(*reversed_four())
    a, b = run(inp), run(inp)
    assert [(r.poses, r.breakdown, r.assign) for r in a.results] == [(r.poses, r.breakdown, r.assign) for r in b.results]


def test_a_clock_out_before_the_first_map_says_so_and_one_out_later_keeps_the_best_found():
    inp, _ = input_of(*reversed_four())
    g = run(inp, clock=Clock(0, now=itertools.count().__next__))
    assert (g.first_map, g.budget_out, g.results) == (False, True, ())
    ticks = itertools.count()
    g = run(inp, clock=Clock(40_000, now=lambda: next(ticks)))           # the clock reads 0, 1, 2 ... seconds
    assert g.first_map and g.budget_out and 1 <= len(g.results) < 4 and g.searched == len(g.results) and g.of == 4


def test_the_present_pose_comes_first_and_each_turn_is_studied_once_however_the_turns_are_written():
    inp, _ = input_of(*reversed_four())
    assert poses_of(inp.parts[0], settings(pins_rotations=(360, -90, 90.0, 90))) == [(0.0, False), (270.0, False), (90.0, False)]
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_search.py -q -n 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap_search'`.

- [ ] **Step 3: Write the module**

Create `src/placemat/pinmap_search.py`:

```python
"""The pin map study's search: per studied part (or parts studied together), per pose - each rotation in
`pins.rotations`, and the other face when `pins.faces` is true and the part may stand there - the best assignment of its
movable nets to its pins.

1. A first map: each group placed whole on the run of pool pins nearest its nets' targets, then each other net on the
   free allowed pin whose exit point is nearest its target, as a minimum-cost matching (crossings ignored).
2. A local search from it: moves (a net to a free pin), swaps (two nets) and group moves (a group to another run, the
   nets standing there taking the pins it left), each priced by `pinmap_score.Tally`, under a short annealing schedule
   (`pins.anneal_moves` moves from `pins.anneal_start` down to `pins.anneal_end`), once per seed of `pins.seeds`.

Deterministic for a given board: the random streams are seeded from the parts, the pose and the seed number, and ties
go to the lower pin number. A clock (`pins.budget_ms` for each part of the group) stops the search between moves with the
best found; a study the clock stopped says so, and is deterministic only while the budget is not reached."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
import random
import time

from .pinmap_geom import Pose
from .pinmap_rules import Problem, natural
from .pinmap_score import Background, Breakdown, Scorer, Tally, Weights

_INF = float("inf")


class Clock:
    """A budget in milliseconds from now; `now` is replaceable for a test."""

    def __init__(self, ms: float, now=time.perf_counter):
        self.now = now
        self.end = now() + ms / 1000.0

    def out(self) -> bool:
        return self.now() >= self.end


@dataclass(frozen=True)
class PoseResult:
    """The best assignment found at one pose of each part of a group: `poses` ((ref, turn, flip), ...), its score, and
    `assign` {net: ends} for every studied net."""
    poses: tuple
    breakdown: Breakdown
    assign: dict


@dataclass(frozen=True)
class GroupResult:
    """One group's study: the present score, the best result per pose combination searched (the present poses first),
    how many combinations were searched of how many, whether the clock ran out, whether it ran out before a first map,
    and the problems found (a net no matching could place)."""
    refs: tuple
    present: Breakdown
    present_assign: dict
    results: tuple
    searched: int
    of: int
    budget_out: bool
    first_map: bool
    problems: tuple = ()


def poses_of(part, settings) -> list:
    """The (turn, flip) a part is studied at: its present pose first, each of `pins.rotations` as a turn from where it
    stands, then the same on the other face when `pins.faces` is true and the part may stand there."""
    turns = [0.0]
    for t in settings.pins_rotations:
        t = float(t) % 360.0
        if t not in turns:
            turns.append(t)
    out = [(t, False) for t in turns]
    if settings.pins_faces and part.may_flip:
        out += [(t, True) for t in turns]
    return out


def hungarian(cost) -> list:
    """The minimum-cost assignment of every row to a different column (rows <= columns), as each row's column, or None
    when no assignment avoids an infinite cost. Ties go to the lower column (Kuhn-Munkres with potentials)."""
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    big = 1e12
    a = [[min(c, big) for c in row] for row in cost]
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [_INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], _INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = a[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    if any(cost[i][out[i]] == _INF for i in range(n)):
        return None
    return out


class _State:
    """Which pin each movable net of each part of the group stands on, and which net each pin holds."""

    def __init__(self, inp, refs, assign):
        self.inp, self.refs = inp, refs
        self.pin = {r: {} for r in refs}
        self.who = {r: {} for r in refs}
        for net, ends in assign.items():
            for r, num in ends:
                if r in self.pin and net in inp.part(r).slots.movable:
                    self.pin[r][net] = num
                    self.who[r][num] = net

    def ends(self, assign, net, ref, number) -> tuple:
        """`net`'s ends with its end on `ref` moved to `number`."""
        return tuple(sorted(((r, number if r == ref else n) for r, n in assign[net]), key=lambda e: (e[0], natural(e[1]))))

    def move(self, ref, changes: dict, assign) -> dict:
        """{net: ends} for `changes` {net: new pin} on `ref`."""
        return {net: self.ends(assign, net, ref, pin) for net, pin in changes.items()}

    def commit(self, ref, changes: dict) -> None:
        for net, pin in changes.items():
            old = self.pin[ref].get(net)
            if old is not None and self.who[ref].get(old) == net:
                del self.who[ref][old]
        for net, pin in changes.items():
            self.pin[ref][net] = pin
            self.who[ref][pin] = net


def _group_of(slots, net):
    for name, nets in slots.groups:
        if net in nets:
            return name
    return None


def _target_cost(scorer, part, net, pin, assign) -> float:
    """How far `pin`'s exit point is from what `net` heads for: its nearest anchor on another part, else the other
    studied ends' exit points."""
    e = scorer.exit(part.ref, pin)
    n = scorer.nets[net]
    pts = [(a.x, a.y) for a in n.fixed] or [scorer.exit(r, num).at for r, num in assign[net] if r != part.ref]
    if not pts:
        return 0.0
    return min(math.hypot(e.at[0] - x, e.at[1] - y) for x, y in pts)


def first_map(scorer, inp, refs, assign) -> tuple:
    """(assignment, [Problem]): every movable net of the group's parts placed by the first map. Each group takes the
    cheapest run of pins that still leaves the other nets a matching; then the other nets are matched. A part whose nets
    no matching can place keeps its present pins and gives a `no_legal_map` problem naming a net it could not place."""
    assign = dict(assign)
    problems = []
    for ref in refs:
        part = inp.part(ref)
        slots = part.slots
        grouped = {n for _, nets in slots.groups for n in nets if n}
        singles = [n for n in slots.movable if n not in grouped]
        cost_of = lambda n, p: _target_cost(scorer, part, n, p, assign) if p in slots.allowed[n] else _INF

        def matching(used):
            pins = sorted({p for n in singles for p in slots.allowed[n]} - used, key=natural)
            if len(pins) < len(singles):
                return pins, None
            return pins, hungarian([[cost_of(n, p) for p in pins] for n in singles])
        used, changes = set(), {}
        for name, nets in slots.groups:
            wins = sorted(((sum(_target_cost(scorer, part, n, p, assign) for n, p in zip(nets, w) if n), k, w)
                           for k, w in enumerate(slots.windows.get(name, ())) if not used & set(w)))
            win = next((w for _, _, w in wins if matching(used | set(w))[1] is not None), None)
            if win is None:
                win = tuple(slots.present[n] for n in nets if n)
                used |= set(win)
                continue
            used |= set(win)
            changes.update({n: p for n, p in zip(nets, win) if n})
        if singles:
            pins, got = matching(used)
            if got is None:
                bad = next((n for n in singles if not any(p in slots.allowed[n] for p in pins)), singles[0])
                problems.append(Problem(ref, "", "", "no_legal_map", bad))
                continue
            changes.update({n: pins[j] for n, j in zip(singles, got)})
        for net, pin in changes.items():
            assign[net] = tuple(sorted(((r, pin if r == ref else num) for r, num in assign[net]),
                                       key=lambda e: (e[0], natural(e[1]))))
    return assign, problems


def _propose(rng, state, inp, refs, assign):
    """A random legal change, as (ref, {net: new pin}), or None."""
    units = []
    for ref in refs:
        slots = inp.part(ref).slots
        grouped = {n for _, nets in slots.groups for n in nets if n}
        units += [(ref, "net", n) for n in slots.movable if n not in grouped]
        units += [(ref, "group", name) for name, _ in slots.groups if slots.windows.get(name)]
    if not units:
        return None
    ref, what, name = units[rng.randrange(len(units))]
    slots = inp.part(ref).slots
    pin_of, who = state.pin[ref], state.who[ref]
    if what == "net":
        here = pin_of[name]
        choices = [p for p in slots.allowed[name] if p != here]
        if not choices:
            return None
        to = choices[rng.randrange(len(choices))]
        other = who.get(to)
        if other is None:
            return ref, {name: to}
        if _group_of(slots, other) is None and here in slots.allowed.get(other, ()):
            return ref, {name: to, other: here}
        return None
    nets = dict(slots.groups)[name]
    now = tuple(pin_of[n] for n in nets if n)
    wins = [w for w in slots.windows[name] if tuple(p for n, p in zip(nets, w) if n) != now]
    if not wins:
        return None
    win = wins[rng.randrange(len(wins))]
    changes = {n: p for n, p in zip(nets, win) if n}
    left = sorted(set(now) - set(win), key=natural)
    taken = [p for p in sorted(win, key=natural) if who.get(p) is not None and who[p] not in nets]
    if len(taken) > len(left):
        return None
    for p, q in zip(taken, left):
        other = who[p]
        if _group_of(slots, other) is not None or q not in slots.allowed.get(other, ()):
            return None
        changes[other] = q
    return ref, changes


def anneal(scorer, inp, refs, start: dict, settings, seed_key: str, clock) -> tuple:
    """(best assignment, its total, whether the clock ran out) from `start`, over `pins.seeds` seeds."""
    best, best_v, out = dict(start), scorer.total(start).total, False
    n = max(int(settings.pins_anneal_moves), 1)
    t0, t1 = settings.pins_anneal_start, settings.pins_anneal_end
    for s in range(max(int(settings.pins_seeds), 1)):
        rng = random.Random("%s|%d" % (seed_key, s))
        tally, state = Tally(scorer, start), _State(inp, refs, start)
        for k in range(n):
            if k % 32 == 0 and clock.out():
                return best, best_v, True
            temp = t0 * (t1 / t0) ** (k / max(n - 1, 1)) if t0 > 0 and t1 > 0 else 0.0
            got = _propose(rng, state, inp, refs, tally.assign)
            if got is None:
                continue
            ref, pins = got
            changes = state.move(ref, pins, tally.assign)
            d = tally.delta(changes)
            if d < -1e-12 or (temp > 0 and rng.random() < math.exp(-d / temp)):
                tally.apply(changes, d)
                state.commit(ref, pins)
                if tally.value < best_v - 1e-9:
                    best, best_v = dict(tally.assign), tally.value
    return best, best_v, out


def study_group(inp, refs: tuple, settings, background: Background, clock=None) -> GroupResult:
    """The study of one group of parts: every combination of their poses (the present first, at most
    `pins.joint_combinations`), each from its first map through the local search."""
    weights = Weights.of(settings)
    clock = clock or Clock(settings.pins_budget_ms * len(refs))
    present_poses = {p.ref: Pose(p.cx, p.cy) for p in inp.parts}
    present = {n.net: n.ends for n in inp.nets}
    scorer0 = Scorer(inp, present_poses, weights, background, settings.pins_exit_mm)
    base = scorer0.total(present)
    lists = [[(r, t, f) for t, f in poses_of(inp.part(r), settings)] for r in refs]
    combos = list(itertools.islice(itertools.product(*lists), max(int(settings.pins_joint_combinations), 1)))
    total = 1
    for l in lists:
        total *= len(l)
    results, problems, out, first = [], [], False, True
    for k, combo in enumerate(combos):
        if clock.out():
            out = True
            if k == 0:
                first = False
            break
        poses = dict(present_poses)
        for r, t, f in combo:
            p = inp.part(r)
            poses[r] = Pose(p.cx, p.cy, t, f)
        scorer = scorer0 if k == 0 else Scorer(inp, poses, weights, background, settings.pins_exit_mm)
        start, said = first_map(scorer, inp, refs, present)
        if said:
            problems += [p for p in said if p not in problems]
            if k == 0:
                return GroupResult(tuple(refs), base, present, (), 0, len(combos), False, True, tuple(problems))
        key = "%s|%s" % (",".join(refs), ";".join("%s:%g:%d" % c for c in combo))
        best, _, ran_out = anneal(scorer, inp, refs, start, settings, key, clock)
        results.append(PoseResult(tuple(combo), scorer.total(best), best))
        if ran_out:
            out = True
            break
    return GroupResult(tuple(refs), base, present, tuple(results), len(results), total, out, first, tuple(problems))
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_search.py -q -n 2`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pinmap_search.py tests/test_pinmap_search.py
git commit -m "Pin map study: a matching seed, then moves, swaps and group moves under annealing, per pose"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 7: Joint study of linked parts

**Files:**
- Modify: `src/placemat/pinmap_search.py` (append `linked_groups`, `study`)
- Test: `tests/test_pinmap_joint.py`

**Interfaces:**
- Consumes: Task 6's `study_group`, `Background`, `Weights`.
- Produces: `linked_groups(inp) -> list[tuple[str, ...]]` (parts joined by a net that may move on both, sorted); `study(inp, settings, clock_for=None, background=None) -> list[GroupResult]` (one per group; `clock_for(refs)` makes a test's clock).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_joint.py`:

```python
"""Parts whose movable nets connect to each other's are studied together: their poses searched in combination (at most
`pins.joint_combinations`), both ends of a shared net free."""
from placemat.pinmap_score import Background, Weights
from placemat.pinmap_search import linked_groups, study, study_group
from tests.pinmap_boards import input_of, point_pad, quad, settings


def facing_away():
    """U1 with nets A-C on its west side and U2, 10 mm east, with the same nets on its east side: each faces away from
    the other, so the nets go round both bodies until both parts turn."""
    p1, u1 = quad("U1", 10, 10, {"W": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"})
    p2, u2 = quad("U2", 20, 10, {"E": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"})
    return input_of(p1 + p2, {"U1": u1, "U2": u2})[0]


def test_parts_sharing_a_net_that_may_move_on_both_are_one_group_and_a_held_link_does_not_join_them():
    assert linked_groups(facing_away()) == [("U1", "U2")]
    p1, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2", "Pm.PinFixed": "1"})
    p2, u2 = quad("U2", 20, 10, {"W": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    inp, _ = input_of(p1 + p2 + point_pad("T1", "B", 30, 30), {"U1": u1, "U2": u2})
    assert linked_groups(inp) == [("U1", "U2")]                        # B may move on both
    p2, u2 = quad("U2", 20, 10, {"W": ["A", ""]}, {"Pm.PinPool": "1-2"})
    inp, _ = input_of(p1 + p2 + point_pad("T1", "B", 30, 30), {"U1": u1, "U2": u2})
    assert linked_groups(inp) == [("U1",), ("U2",)]                    # A is fixed on U1: only U2's end moves


def test_a_joint_study_beats_studying_each_part_alone():
    inp = facing_away()
    s = settings(pins_length_weight=0.1)
    bg = Background(inp.background, Weights.of(s))
    best = lambda g: min(r.breakdown.total for r in g.results)
    joint = study_group(inp, ("U1", "U2"), s, bg)
    alone = [study_group(inp, (r,), s, bg) for r in ("U1", "U2")]
    assert best(joint) < min(best(g) for g in alone)
    win = min(joint.results, key=lambda r: r.breakdown.total)
    assert win.poses == (("U1", 180.0, False), ("U2", 180.0, False))
    assert [g.refs for g in study(inp, s)] == [("U1", "U2")]


def test_a_joint_study_searches_at_most_the_combinations_it_is_allowed():
    inp = facing_away()
    g = study_group(inp, ("U1", "U2"), settings(pins_joint_combinations=5), Background(inp.background, Weights()))
    assert (g.searched, g.of) == (5, 16)
    assert g.results[0].poses == (("U1", 0.0, False), ("U2", 0.0, False))
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_joint.py -q -n 2`
Expected: FAIL with `ImportError: cannot import name 'linked_groups' from 'placemat.pinmap_search'`.

- [ ] **Step 3: Append the grouping and the study of every group**

Append to `src/placemat/pinmap_search.py`:

```python


def linked_groups(inp) -> list:
    """The studied parts in groups to study together: two parts are linked when a net may move on both (its two ends
    free), and a group is every part linked to another of it. Sorted, each group's refs sorted."""
    parent = {p.ref: p.ref for p in inp.parts}

    def find(r):
        while parent[r] != r:
            parent[r] = parent[parent[r]]
            r = parent[r]
        return r
    for n in inp.nets:
        refs = sorted({r for r, _ in n.ends if n.net in inp.part(r).slots.movable})
        for a, b in zip(refs, refs[1:]):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups: dict = {}
    for r in sorted(parent):
        groups.setdefault(find(r), []).append(r)
    return [tuple(g) for _, g in sorted(groups.items())]


def study(inp, settings, clock_for=None, background=None) -> list:
    """Every group's study (GroupResult), on one `background` (bucketed here when not given). `clock_for(refs)`, when
    given, makes each group's clock (a test's); else each has `pins.budget_ms` for each of its parts."""
    background = background or Background(inp.background, Weights.of(settings))
    out = []
    for refs in linked_groups(inp):
        clock = clock_for(refs) if clock_for is not None else None
        out.append(study_group(inp, refs, settings, background, clock))
    return out
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_joint.py tests/test_pinmap_search.py -q -n 2`
Expected: PASS (3 and 9 tests). The joint case: two parts 10 mm apart, each with three shared nets on the side facing away from the other; alone, each turn still leaves the other's body to go round; together both turn 180 degrees.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pinmap_search.py tests/test_pinmap_joint.py
git commit -m "Pin map study: parts whose movable nets meet are studied together, their poses in combination"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 8: The finding and the suggestion - `pins.remap`, `setup.pins`, advice, facts, cache

**Files:**
- Modify: `src/placemat/findings.py` (kind `PINS`, causes `SETUP_PINS`, `PINS_REMAP`, `SEVERITY`)
- Modify: `src/placemat/finding_text.py` (renderers, `pose_text`, `subject`)
- Modify: `src/placemat/suggestions.py` (`Suggestion.advice`, `Pick.advice`, `suggest`, `_Binder.bind`, `apply_suggestion`, `pin_advice`, `pin_advice_text`, the `pins.remap` builder)
- Create: `src/placemat/pinmap.py`
- Modify: `skills/placemat/references/api.md` (the suggestions case table: the `pins.remap` row)
- Modify: `tests/test_finding_kinds.py`, `tests/test_suggestion_cases.py`
- Test: `tests/test_pinmap_finding.py`

**Interfaces:**
- Consumes: Tasks 2-7 (`build`, `placed_from_geometry`, `Pose`, `Background`, `Scorer`, `Weights`, `study`, `natural`, `Clock`); `reuse.canonical`, `reuse.finding_to_json`, `reuse.finding_from_json`; `checkpoint.write_atomic`; `finding_text.schemas_digest`; `pairs.board_pairs`.
- Produces:
  - `FindingKind.PINS = "pins"` (severity notice); `FindingCause.SETUP_PINS = "setup.pins"`, `FindingCause.PINS_REMAP = "pins.remap"`.
  - `finding_text.pose_text(turns: list) -> str`.
  - `Suggestion.advice: dict | None`, `Pick.advice: dict | None`, `how == "advice"`; `suggestions.pin_advice(facts, i) -> dict`, `suggestions.pin_advice_text(advice) -> str`.
  - `pinmap.CACHE_VERSION`, `has_pools(footprints) -> bool`, `copper_nets(geometry, plan=None) -> frozenset`, `group_facts(inp, g, background, copper, settings) -> dict | None`, `digest(inp, problems, copper, settings) -> str`, `study_findings(pads, parts, names, quiet, partners, netclasses, settings, copper=frozenset(), cache=None, clock_for=None) -> (list[Finding], dict)`, `geometry_findings(geometry, settings, quiet=frozenset(), either=frozenset(), cache=None, clock_for=None) -> (list[Finding], dict)`.
  - The `pins.remap` facts (all JSON): `ref`, `refs`, `at`, `present` (a `Breakdown.to_json()`), `rotations` (per pose searched, the present one first: the breakdown's fields plus `turns` [{`ref`, `turn_deg`, `rotation_deg`, `face`, `flip`}], `map` [{`ref`, `net`, `from`: {`pin`, `name`}, `to`: {`pin`, `name`}}], `routed` (the moved nets with copper now), `paths` [{`net`, `path`: [[x, y], ...]}]), `best` (index), `routed`, `before` (paths at the present map), `held` [{`ref`, `net`, `pin`, `name`, `why`}], `searched`, `of`, `budget_out`, `first_map`, `budget_ms`.
  - The `setup.pins` facts: `Problem.facts()` - `ref`, `key`, `entry`, `code`, `name`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_finding.py`:

```python
"""The pin map study's finding: a `pins.remap` notice when a map saves `pins.gain_min` of the present total, its facts
as data and its sentence rendered from them; a `setup.pins` warning for an entry the study ran without; the suggestion
that carries the map and the turn and writes nothing; and a study reused when what it reads has not changed."""
import itertools
import json

import pytest

from placemat import suggestions as sg
from placemat.findings import FindingCause as C, FindingKind
from placemat.pinmap import study_findings
from placemat.pinmap_search import Clock
from tests.pinmap_boards import complete, point_pad, quad, reversed_four, settings


def study(pads, parts, s=None, copper=frozenset(), cache=None, clock_for=None):
    return study_findings(pads, complete(pads, parts), {}, frozenset(), {}, {}, s or settings(), copper, cache, clock_for)


def test_a_better_map_is_a_notice_with_its_facts_and_its_sentence():
    found, record = study(*reversed_four(), settings(pins_rotations=(0.0,)))
    (f,) = found
    assert f.cause is C.PINS_REMAP and f.kind is FindingKind.PINS and f.severity == "notice"
    assert f == "U1: a pin map with 6 fewer weighted crossings exists at its present rotation"
    facts = json.loads(json.dumps(f.facts))
    assert facts["present"]["among"] == 6 and facts["rotations"][0]["among"] == 0 and facts["best"] == 0
    assert [(m["net"], m["from"]["pin"], m["to"]["pin"]) for m in facts["rotations"][0]["map"]] == [
        ("A", "1", "4"), ("B", "2", "3"), ("C", "3", "2"), ("D", "4", "1")]
    assert {w["net"] for w in facts["before"]} == {"A", "B", "C", "D"} and facts["rotations"][0]["paths"]
    assert record == {"seconds": record["seconds"], "reused": False, "groups": 1, "parts": 1}


def facing_away():
    """U1 with A and B on its west side, north to south, and their targets east of it in the same order: turned half
    round, its pins face them, A and B crossing until they trade pins."""
    pads, u1 = quad("U1", 10, 10, {"W": ["A", "B", ""]}, {"Pm.PinPool": "1-3"})
    for i, net in enumerate(["A", "B"]):
        pads += point_pad("T%d" % i, net, 25, 9.5 + i)
    return pads, {"U1": u1}


def test_a_better_pose_is_named_with_what_it_saves_beside_the_present_one():
    (f,) = study(*facing_away())[0]
    assert f.startswith("U1: a pin map with ") and " exists at its present rotation; at 180 degrees, " in f
    assert f.facts["rotations"][f.facts["best"]]["turns"] == [
        {"ref": "U1", "turn_deg": 180.0, "rotation_deg": 180.0, "face": "front", "flip": False}]


def test_a_map_saving_less_than_the_gain_min_is_no_finding():
    found, _ = study(*reversed_four(), settings(pins_rotations=(0.0,), pins_gain_min=0.99))
    assert found == []


def test_an_entry_the_study_runs_without_is_a_setup_warning():
    found, _ = study(*reversed_four({"Pm.PinPool": "1-4, 9"}), settings(pins_rotations=(0.0,)))
    pins = [f for f in found if f.cause is C.SETUP_PINS]
    assert [str(f) for f in pins] == ["U1: Pm.PinPool names pin 9, which U1 does not have; the study runs without it"]
    assert pins[0].severity == "warning"


def test_the_moved_nets_with_copper_now_are_named():
    (f,) = study(*reversed_four(), settings(pins_rotations=(0.0,)), copper=frozenset({"A", "Z"}))[0]
    assert f.facts["routed"] == ["A"] and f.endswith("; 1 of the nets it moves have copper now: A")


def test_a_budget_too_short_for_a_first_map_says_so():
    found, _ = study(*reversed_four(), settings(pins_budget_ms=50),
                     clock_for=lambda refs: Clock(0, now=itertools.count().__next__))
    (f,) = found
    assert f == "U1: the pin map study ran out of its 50 ms before a first map; pins.budget_ms sets it"
    assert sg.suggest(f.cause, f.facts) == []


def test_the_suggestion_carries_the_map_and_the_turn_and_writes_nothing(tmp_path):
    (f,) = study(*facing_away())[0]
    best, present = sg.suggest(f.cause, f.facts)
    assert (best.lever, best.how, best.edits) == ("pins", "advice", ())
    assert best.text == "Move 2 nets of U1 to the pins in the map, a capture change, and turn U1 to 180 degrees"
    assert best.advice["turns"][0]["rotation_deg"] == 180.0
    assert [(m["net"], m["from"]["pin"], m["to"]["pin"]) for m in best.advice["map"]] == [("A", "1", "2"), ("B", "2", "1")]
    assert present.advice["rotation"] == 0 and "turn" not in present.text
    assert sg.Suggestion.from_json(best.to_json()) == best

    class _Board:
        script_file = ""
        settings = settings()
    f.suggestions = ()
    sg.bind([f], _Board())
    assert [s.id for s in f.suggestions] == ["s1a", "s1b"]
    with pytest.raises(sg.EditRefused, match="advice"):
        sg.apply_suggestion(f.suggestions, "s1a", root=tmp_path)


def test_a_second_study_of_the_same_board_is_reused_and_a_changed_setting_is_not(tmp_path):
    cache = tmp_path / "pinmap" / "layout.json"
    s = settings(pins_rotations=(0.0,))
    first, r1 = study(*reversed_four(), s, cache=cache)
    again, r2 = study(*reversed_four(), s, cache=cache)
    assert (r1["reused"], r2["reused"]) == (False, True) and [str(f) for f in again] == [str(f) for f in first]
    assert again[0].facts == first[0].facts
    _, r3 = study(*reversed_four(), settings(pins_rotations=(0.0,), pins_seeds=2), cache=cache)
    assert r3["reused"] is False


def test_a_net_on_two_pins_of_the_part_stays_and_is_not_in_the_map():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "TIED", "TIED", "B"]}, {"Pm.PinPool": "1-4"})
    pads += point_pad("T1", "B", 20, 8.5) + point_pad("T2", "A", 20, 11.5) + point_pad("T3", "TIED", 20, 10)
    (f,) = study(pads, {"U1": u1}, settings(pins_rotations=(0.0,)))[0]
    assert {m["net"] for r in f.facts["rotations"] for m in r["map"]} <= {"A", "B"}


def test_a_part_at_45_degrees_with_its_pins_under_its_body_is_studied_and_its_poses_named_from_where_it_stands():
    from placemat.pinmap_input import PlacedPart
    from placemat.values import Box
    from tests.pinmap_boards import pad
    pads = [pad("U1", n, net, 10 + dx, 10 + dy) for n, (net, dx, dy) in
            enumerate([("A", -1, -1), ("B", 1, -1), ("", -1, 1), ("", 1, 1)], 1)]
    pads += point_pad("T1", "A", 25, 9) + point_pad("T2", "B", 0, 9)
    u1 = PlacedPart("U1", Box(7, 7, 13, 13), 45.0, "front", False, {"Pm.PinPool": "1-4"})
    (f,) = study(pads, {"U1": u1})[0]
    assert [t["rotation_deg"] for r in f.facts["rotations"] for t in r["turns"]] == [45.0, 135.0, 225.0, 315.0]
    assert f.facts["rotations"][0]["total"] < f.facts["present"]["total"]
```

In `tests/test_finding_kinds.py`, in `test_a_finding_is_its_text_and_carries_its_kind`, replace:

```python
                          "needs", "split", "time", "keep_out"}
```

with:

```python
                          "needs", "split", "time", "keep_out", "pins"}
```

In `tests/test_suggestion_cases.py`, in `FACTS`, replace:

```python
    C.SETUP_NATIVE: {"reason": "version_mismatch", "placemat_version": "0.97.2", "native_version": "0.97.1", "detail": ""},
}
```

with:

```python
    C.SETUP_NATIVE: {"reason": "version_mismatch", "placemat_version": "0.97.2", "native_version": "0.97.1", "detail": ""},
    C.PINS_REMAP: {"ref": "U1", "refs": ["U1"], "best": 1, "present": {"total": 9.0},
                   "rotations": [{"total": 6.0, "weighted": 2.0, "turns": [{"ref": "U1", "turn_deg": 0.0, "rotation_deg": 0.0,
                                                                             "face": "front", "flip": False}],
                                  "map": [{"ref": "U1", "net": "A", "from": {"pin": "1", "name": ""}, "to": {"pin": "2", "name": ""}}]},
                                 {"total": 4.0, "weighted": 0.0, "turns": [{"ref": "U1", "turn_deg": 90.0, "rotation_deg": 90.0,
                                                                             "face": "front", "flip": False}], "map": []}]},
}
```

and in both `test_every_keyword_a_builder_sets_is_a_parameter_of_the_board_method_it_edits_and_every_enum_exists` and `test_a_number_a_builder_writes_into_a_call_is_a_named_constant`, after the line `for pick in builder(FACTS[case], ...) or ():` add:

```python
            if pick.how == "advice":                                # no edit: a change made outside the script
                continue
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_finding.py tests/test_finding_kinds.py tests/test_suggestion_cases.py -q -n 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap'`, the kinds set lacking `pins`, and `AttributeError: PINS_REMAP`.

- [ ] **Step 3: The kind and the causes**

In `src/placemat/findings.py`, after `    TIME = "time" ...` in `FindingKind`, add:

```python
    PINS = "pins"                       # a better assignment of nets to a part's pins (its Pm.PinPool) than the capture's, from the pin map study
```

After `    SETUP_PAIR_LAYERS = (FindingKind.SETUP, "setup.pair_layers")` add:

```python
    SETUP_PINS = (FindingKind.SETUP, "setup.pins")
```

After `    TIME_STEP_LIMIT = (FindingKind.TIME, "time.step_limit")` add:

```python
    PINS_REMAP = (FindingKind.PINS, "pins.remap")
```

In `SEVERITY`, replace:

```python
    FindingKind.TIME: "notice",
}
```

with:

```python
    FindingKind.TIME: "notice",
    FindingKind.PINS: "notice",
}
```

- [ ] **Step 4: The sentences, rendered from the facts**

In `src/placemat/finding_text.py`, before `@renders(C.SETUP_PAIR_LAYERS, "key", "variant", "layers", "missing", "board_layers")`, add:

```python
_PIN_PROBLEMS = {
    "no_pin": "%(key)s names pin %(name)s, which %(ref)s does not have; the study runs without it",
    "no_net": "%(key)s names net %(name)s, which no pin of %(ref)s carries; the study runs without %(entry)s",
    "no_names": "%(key)s names %(name)s by pin name, and no pin names were read for %(ref)s: its symbol is not among "
                "the board's libraries; the study runs without it",
    "unreadable": "%(key)s entry %(entry)s is not name:pins; the study runs without it",
    "not_in_pool": "%(key)s entry %(entry)s names pin %(name)s, which is not an unfixed pin of its Pm.PinPool; the study "
                   "runs without the group",
    "two_groups": "%(key)s entry %(entry)s names pin %(name)s, which an earlier group has; the study runs without it",
    "no_legal_pin": "net %(name)s has no pin of the pool left that %(key)s lets it take; %(ref)s is not studied",
    "no_legal_map": "no map gives every net a pin it may take: %(name)s has none left; %(ref)s is not studied",
}


@renders(C.SETUP_PINS, "ref", "key", "entry", "code", "name")
def _setup_pins(f):
    return "%s: %s" % (f["ref"], _PIN_PROBLEMS[f["code"]] % f)


def _crossings_fewer(present: dict, r: dict, short: bool) -> str:
    """What a pose's best map saves against the present one, in its plainest term: weighted crossings, else airwire,
    else turning."""
    dw = present["weighted"] - r["weighted"]
    if dw > 1e-9:
        return ("%g fewer" if short else "%g fewer weighted crossings") % round(dw, 1)
    dl = present["length_mm"] - r["length_mm"]
    if dl > 1e-9:
        return "%.1f mm less airwire" % dl
    return "%.0f degrees less turning at its pins" % (present["bend_deg"] - r["bend_deg"])


def pose_text(turns: list) -> str:
    """'90 degrees', '90 degrees on the back', or for parts studied together 'U1 at 90 degrees and U2 at 180 degrees'."""
    def one(t):
        return "%g degrees%s" % (t["rotation_deg"], " on the %s" % t["face"] if t["flip"] else "")
    if len(turns) == 1:
        return one(turns[0])
    return " and ".join("%s at %s" % (t["ref"], one(t)) for t in turns)


@renders(C.PINS_REMAP, "ref", "refs", "present", "rotations", "best", "first_map", "budget_out", "budget_ms", "searched",
         "of", "routed")
def _pins_remap(f):
    who = " and ".join(f["refs"])
    their = "its present rotation" if len(f["refs"]) == 1 else "their present rotations"
    if not f["first_map"]:
        return "%s: the pin map study ran out of its %g ms before a first map; pins.budget_ms sets it" % (who, f["budget_ms"])
    rs, p = f["rotations"], f["present"]
    here, best = rs[0], rs[f["best"]]
    if here["total"] < p["total"] - 1e-9:
        text = "%s: a pin map with %s exists at %s" % (who, _crossings_fewer(p, here, False), their)
    else:
        text = "%s: no better pin map at %s" % (who, their)
    if f["best"] != 0:
        text += "; at %s, %s" % (pose_text(best["turns"]), _crossings_fewer(p, best, here["total"] < p["total"] - 1e-9))
    if f["routed"]:
        text += "; %d of the nets it moves have copper now: %s" % (len(f["routed"]), ", ".join(f["routed"]))
    if f["budget_out"]:
        text += "; the study stopped at its %g ms after %d of %d poses" % (f["budget_ms"], f["searched"], f["of"])
    return text


```

In `subject`, before `    if cause is C.LINK_OVER:`, add:

```python
    if cause is C.SETUP_PINS:
        return "%s %s %s" % (facts["ref"], facts["key"], facts["name"])
    if cause is C.PINS_REMAP:
        return " ".join(facts["refs"])
```

- [ ] **Step 5: Advice suggestions, and the builder**

In `src/placemat/suggestions.py`:

Replace the end of `Suggestion`'s docstring:

```python
    have no value for it yet and `figure` says what is varied and over what; `probe.py` finds the value)."""
```

with:

```python
    have no value for it yet and `figure` says what is varied and over what; `probe.py` finds the value; "advice": a
    change made outside the script, which `advice` carries as data and nothing applies - a pin map is a capture
    change)."""
```

After `Suggestion`'s `figure` field (the two comment lines ending `derived from the finding's facts}`) add:

```python
    advice: dict | None = None      # an advice suggestion's change, as data: a pin map's {"refs", "rotation", "turns", "map", "total", "weighted"}
```

In `Suggestion.to_json`, before `        return out`, add:

```python
        if self.advice is not None:
            out["advice"] = self.advice
```

In `Suggestion.from_json`, replace:

```python
                          d.get("id", ""), dict(d.get("digests", {})), d.get("how", "instant"), d.get("figure"))
```

with:

```python
                          d.get("id", ""), dict(d.get("digests", {})), d.get("how", "instant"), d.get("figure"),
                          d.get("advice"))
```

In `Pick`, after its last field `    figure: dict | None = None` (the line with no comment after it), add `    advice: dict | None = None`.

In `suggest`, replace:

```python
        out.append(Suggestion(pick.text, pick.edits, len(out) + 1, pick.lever, how=pick.how, figure=pick.figure))
```

with:

```python
        out.append(Suggestion(pick.text, pick.edits, len(out) + 1, pick.lever, how=pick.how, figure=pick.figure,
                              advice=pick.advice))
```

In `_Binder.bind`, make the first lines:

```python
    def bind(self, s: Suggestion) -> list:
        if s.how == "advice":                   # no script edit: kept as it is, with nothing to digest
            return [s]
        edits = [self.bind_edit(e) for e in s.edits]
```

In `apply_suggestion`, after `    s = find(suggestions, id)` add:

```python
    if s.how == "advice":
        raise EditRefused("%s is advice for the capture and the layout, not a script edit: nothing to write. Make the "
                          "map it names in the .zen and the turn in the script, then run again" % s.id)
```

Before `@case(C.SETUP_CENTRE_FLAG_DEFAULT)` add:

```python
def pin_advice(f: dict, i: int) -> dict:
    """What a `pins.remap` suggestion carries for its pose `i`: the parts, the pose's index, its turns, its map and its
    totals."""
    r = f["rotations"][i]
    return {"refs": list(f["refs"]), "rotation": i, "turns": r["turns"], "map": r["map"], "total": r["total"],
            "weighted": r["weighted"]}


def pin_advice_text(advice: dict) -> str:
    """'Move 4 nets of U1 to the pins in the map, a capture change, and turn U1 to 90 degrees'."""
    from .finding_text import pose_text
    who = " and ".join(advice["refs"])
    n = len({(m["ref"], m["net"]) for m in advice["map"]})
    turned = [t for t in advice["turns"] if t["turn_deg"] or t["flip"]]
    turn = "turn %s to %s" % (" and ".join(t["ref"] for t in turned), pose_text(turned)) if len(turned) == 1 else \
        "turn %s" % pose_text(turned)
    if not n:
        return turn[0].upper() + turn[1:] + "; the pins stay as they are"
    text = "Move %d net%s of %s to the pins in the map, a capture change" % (n, "" if n == 1 else "s", who)
    return text + (", and %s" % turn if turned else "")


@case(C.PINS_REMAP)
def pins_remap(f, settings):
    """The best map, with the turn to declare when another pose wins; and then the best at the present pose, when that
    one saves anything. No edit: the map is made in the capture and the turn in the script, by the agent or the user."""
    if not f.get("rotations"):
        return []
    picks = [f["best"]]
    if f["best"] != 0 and f["rotations"][0]["total"] < f["present"]["total"] - 1e-9:
        picks.append(0)
    return [Pick(pin_advice_text(pin_advice(f, i)), (), "pins", "advice", advice=pin_advice(f, i)) for i in picks]


```

In `skills/placemat/references/api.md`, in the case table under "### Suggestions", after the `| \`vias.dropped\` | none |` row add:

```
| `pins.remap` | advice, not an edit (`how: "advice"`, lever `pins`): the best map with the turn to declare when another pose wins, then the best map at the present pose when that saves anything; `advice` carries `refs`, `rotation` (the index into the finding's `rotations`), `turns`, `map`, `total` and `weighted` |
```

- [ ] **Step 6: The study, end to end**

Create `src/placemat/pinmap.py`:

```python
"""The pin map study, end to end: from a placed board to its `pins.remap` and `setup.pins` findings.

For each part whose capture gives it a `Pm.PinPool` (pinmap_rules), the study (pinmap_search) finds how many weighted
ratsnest crossings a better assignment of its nets to its pins would save, at its present rotation and at each pose in
`pins.rotations`; when the best saves at least `pins.gain_min` of the present total it is a `pins.remap` notice, whose
facts carry every pose's best map and the airwires before and after (finding_text renders the sentence; the suggestion
builder offers the map and the rotation). Nothing is written to the board or the capture.

It runs once on the finished board of a run or a preview (Board._report_pin_maps), on the best variants of an explore
(explore._pin_maps), and with a longer budget from `placemat apply <id> --search`. What it reads is digested; a study
whose digest matches the last one kept (`Board.pin_study_cache`) reuses its findings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from .findings import Finding, FindingCause as C

from .pinmap_geom import Pose
from .pinmap_input import build, placed_from_geometry
from .pinmap_rules import natural
from .pinmap_score import Background, Scorer, Weights
from .pinmap_search import study

CACHE_VERSION = 1


def has_pools(footprints) -> bool:
    """Whether any part carries a `Pm.PinPool`: a board with none is not studied, and nothing is read for it."""
    return any(k.lower() == "pm.pinpool" and (v or "").strip() for fp in footprints for k, v in fp.fields.items())


def copper_nets(geometry, plan=None) -> frozenset:
    """The nets with copper on the board now: the generated board's tracks, vias and pours (a stamped cell's, an
    adopted route's), and the copper a plan lays."""
    nets = {c.net for c in geometry.copper if c.kind != "pad" and c.net}
    if plan is not None:
        nets |= {op.net for op in plan.copper if getattr(op, "net", "") and type(op).__name__ != "Text"}
    return frozenset(nets)


def _rounded(path) -> list:
    return [[round(x, 3), round(y, 3)] for x, y in path]


def _paths(scorer, refs, assign) -> list:
    out = []
    for net in sorted(assign):
        if any(r in refs for r, _ in assign[net]):
            out += [{"net": net, "path": _rounded(p)} for p in scorer.wires(net, assign[net]).paths]
    return out


def _turns(inp, poses) -> list:
    out = []
    for ref, turn, flip in poses:
        part = inp.part(ref)
        face = part.face if not flip else ("back" if part.face == "front" else "front")
        out.append({"ref": ref, "turn_deg": round(turn, 3), "rotation_deg": round((part.rotation + turn) % 360.0, 3),
                    "face": face, "flip": bool(flip)})
    return out


def _map(inp, refs, before: dict, after: dict) -> list:
    """Each studied end the assignment moves, on the group's parts: the net, the pin it leaves and the pin it takes."""
    out = []
    for net in sorted(after):
        old, new = set(before[net]), set(after[net])
        for ref, number in sorted(new - old):
            was = next((n for r, n in sorted(old - new) if r == ref), None)
            if ref in refs and was is not None:
                names = inp.names.get(ref, {})
                out.append({"ref": ref, "net": net, "from": {"pin": was, "name": names.get(was, "")},
                            "to": {"pin": number, "name": names.get(number, "")}})
    return sorted(out, key=lambda m: (m["ref"], natural(m["from"]["pin"]), m["net"]))


def group_facts(inp, g, background, copper, settings) -> dict | None:
    """The facts of a group's `pins.remap` finding, or None when no pose saves `pins.gain_min` of the present total
    (a study that ran out before a first map always has one, saying so)."""
    refs = g.refs
    lead = inp.part(refs[0])
    weights = Weights.of(settings)
    present_poses = {p.ref: Pose(p.cx, p.cy) for p in inp.parts}
    base = {"ref": refs[0], "refs": list(refs), "at": [round(lead.cx, 3), round(lead.cy, 3)],
            "present": g.present.to_json(), "searched": g.searched, "of": g.of, "budget_out": g.budget_out,
            "first_map": g.first_map, "budget_ms": settings.pins_budget_ms * len(refs),
            "held": [{"ref": r, "net": h.net, "pin": h.pin, "name": inp.names.get(r, {}).get(h.pin, ""), "why": h.why}
                     for r in refs for h in inp.part(r).slots.held]}
    if not g.first_map:
        return dict(base, rotations=[], best=0, routed=[], before=[])
    if not g.results:
        return None
    best = min(range(len(g.results)), key=lambda i: (g.results[i].breakdown.total, i))
    gain = g.present.total - g.results[best].breakdown.total
    if gain <= 1e-9 or gain < settings.pins_gain_min * g.present.total:
        return None
    rows = []
    for r in g.results:
        poses = dict(present_poses)
        for ref, turn, flip in r.poses:
            p = inp.part(ref)
            poses[ref] = Pose(p.cx, p.cy, turn, flip)
        scorer = Scorer(inp, poses, weights, background, settings.pins_exit_mm)
        moved = _map(inp, refs, g.present_assign, r.assign)
        rows.append(dict(r.breakdown.to_json(), turns=_turns(inp, r.poses), map=moved,
                         routed=sorted({m["net"] for m in moved} & copper), paths=_paths(scorer, refs, r.assign)))
    before = _paths(Scorer(inp, present_poses, weights, background, settings.pins_exit_mm), refs, g.present_assign)
    return dict(base, rotations=rows, best=best, routed=rows[best]["routed"], before=before)


def digest(inp, problems, copper, settings) -> str:
    """What a study's result depends on: the input, the problems, the nets with copper, the `[pins]` settings and the
    plane weight, the release and the findings' schemas."""
    from . import __version__, finding_text, reuse
    keys = {k: v for k, v in json.loads(settings.json()).items() if k.startswith("pins_") or k == "score_crossing_plane"}
    text = "\0".join([str(CACHE_VERSION), __version__, finding_text.schemas_digest(), reuse.canonical(inp),
                      reuse.canonical(list(problems)), ",".join(sorted(copper)), json.dumps(keys, sort_keys=True)])
    return hashlib.sha256(text.encode()).hexdigest()


def _cached(path, d: str):
    from . import reuse
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if doc.get("version") != CACHE_VERSION or doc.get("digest") != d:
        return None
    try:
        return [reuse.finding_from_json(v) for v in doc["findings"]]
    except (ValueError, KeyError, TypeError):
        return None


def _keep(path, d: str, findings) -> None:
    from . import reuse
    from .checkpoint import write_atomic
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps({"version": CACHE_VERSION, "digest": d,
                                   "findings": [reuse.finding_to_json(f) for f in findings]}, separators=(",", ":")))


def study_findings(pads, parts, names, quiet, partners, netclasses, settings, copper=frozenset(), cache=None,
                   clock_for=None) -> tuple:
    """(findings, record) of the study of a placed board: `setup.pins` for each problem, `pins.remap` for each group
    with a map worth having. `cache`, a path, holds the last study's digest and findings: a match is reused. `record` is
    what a run keeps: {"seconds", "reused", "groups", "parts"}, empty when nothing was studied."""
    t0 = time.perf_counter()
    inp, problems = build(pads, parts, names, quiet, partners, netclasses, settings.pins_follow_series)
    if inp is None and not problems:
        return [], {}
    d = digest(inp, problems, copper, settings)
    hit = _cached(cache, d) if cache is not None else None
    n_parts = len(inp.parts) if inp is not None else 0
    if hit is not None:
        return hit, {"seconds": round(time.perf_counter() - t0, 3), "reused": True, "groups": None, "parts": n_parts}
    found = [Finding(C.SETUP_PINS, p.facts()) for p in problems]
    groups = 0
    if inp is not None:
        background = Background(inp.background, Weights.of(settings))
        results = study(inp, settings, clock_for, background)
        groups = len(results)
        for g in results:
            found += [Finding(C.SETUP_PINS, p.facts()) for p in g.problems]
            facts = group_facts(inp, g, background, copper, settings)
            if facts is not None:
                found.append(Finding(C.PINS_REMAP, facts))
    if cache is not None:
        _keep(cache, d, found)
    return found, {"seconds": round(time.perf_counter() - t0, 3), "reused": False, "groups": groups, "parts": n_parts}


def geometry_findings(geometry, settings, quiet=frozenset(), either=frozenset(), cache=None, clock_for=None) -> tuple:
    """`study_findings` of a board where its file has its parts (a laid board read from disk, a bench case)."""
    if not has_pools(geometry.footprints):
        return [], {}
    from .pairs import board_pairs
    pads, parts = placed_from_geometry(geometry, either)
    return study_findings(pads, parts, geometry.pin_names, quiet, board_pairs(geometry.netclasses), geometry.netclasses,
                          settings, copper_nets(geometry), cache, clock_for)
```

- [ ] **Step 7: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_finding.py tests/test_finding_kinds.py tests/test_suggestion_cases.py tests/test_no_sentence_parsing.py tests/test_apply_suggestion.py tests/test_finding_severity.py -q -n 2`
Expected: PASS (`test_no_sentence_parsing` checks the new causes have renderers and versions; `test_suggestion_cases` that the api.md table names `pins.remap`).

- [ ] **Step 8: Commit**

```bash
git add src/placemat/findings.py src/placemat/finding_text.py src/placemat/suggestions.py src/placemat/pinmap.py skills/placemat/references/api.md tests/test_pinmap_finding.py tests/test_finding_kinds.py tests/test_suggestion_cases.py
git commit -m "Pin map study: a pins.remap notice with its map as facts, an advice suggestion that writes nothing, setup.pins for what it runs without"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 9: Wiring into run and preview - once, at the end of a resolve, with digest reuse

**Files:**
- Modify: `src/placemat/occupancy.py` (`Occupancy.courtyard_box`)
- Modify: `src/placemat/layout.py` (`Plan.pin_study`; `Board.pin_study`, `Board.pin_study_cache`; `Board._report_pin_maps`; the call in `_resolve_once`)
- Modify: `src/placemat/pinmap.py` (import; append `study_line`, `placed_from_plan`, `plan_findings`)
- Modify: `src/placemat/runner.py` (`scripted_board` sets the cache path; `_run` records and says the study)
- Modify: `src/placemat/explore.py` (`BoardFactory.__call__`)
- Modify: `src/placemat/previewer.py` (`_resolved` says the study)
- Test: `tests/test_pinmap_wiring.py`

**Interfaces:**
- Consumes: Task 8's `study_findings`, `copper_nets`, `has_pools`; `Occupancy.pad_anchor`, `Occupancy._transform`, `Occupancy.items`, `Occupancy.pending`; `Board._placements()`, `Board._plane_nets()`, `Board._free_nets`; `pairs.board_pairs`; `context._overlay`.
- Produces: `Occupancy.courtyard_box(ref) -> Box`; `Plan.pin_study: dict` ({"seconds", "reused", "groups", "parts"}, `{}` when nothing was studied); `Board.pin_study: bool = True`; `Board.pin_study_cache: Path | None = None`; `pinmap.placed_from_plan(board, plan) -> (pads, parts)`, `pinmap.plan_findings(board, plan) -> list[Finding]`, `pinmap.study_line(record) -> str`; `run.json` `metrics.pin_study`; the console line `pins  <study_line>` in run and preview.

The hook sits after `_report_splits` and before `suggestions.bind` in `_resolve_once`, so the study's findings get their suggestion ids with the rest, are in the plan the studio is sent (`channel.reporter(...).plan`), and are in the reuse-free part of the plan (they are not step findings, so no replay record carries them). It runs when `self._explore is None` (a variant with a seed is never studied there) and `self.pin_study` (an explore's own boards, made by `BoardFactory`, say False: Task 10 studies the best of them). A try of a suggestion (`context._overlay` set) studies without keeping a record, as a try writes nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_wiring.py`:

```python
"""The pin map study at the end of a resolve: once, on the finished board, its findings in the plan and its record on
it; not on an explore's variants or a board that says not to; reused when a resolve reads what the last one read; and it
moves nothing."""
from placemat.explore import Explore
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.pinmap import study_line
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint
from tests.pinmap_boards import quad_footprint, settings


def board(fields=None, **kw):
    """U1 with nets A-D on its east side, north to south, and four resistors east of it in the opposite order."""
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"} if fields is None else fields)]
    for i, net in enumerate(["D", "C", "B", "A"]):
        fps.append(footprint("R%d" % (i + 1), 25, 7 + 2 * i, w=2, h=1, inst="r%d" % (i + 1), nets=(net, "G%d" % i)))
    b = Board(board_geometry(fps, width=40, height=30), edge_margin=1.0, settings=settings(pins_rotations=(0.0,)), **kw)
    b.place(Part("u1"), at=Location(10, 10))
    for i in range(4):
        b.place(Part("r%d" % (i + 1)), at=Location(25, 7 + 2 * i))
    return b


def remaps(plan):
    return [f for f in plan.findings if f.cause is C.PINS_REMAP]


def test_a_resolve_ends_with_the_study_and_keeps_its_record():
    plan = board().resolve()
    (f,) = remaps(plan)
    assert f.startswith("U1: a pin map with 6 fewer weighted crossings exists at its present rotation")
    assert plan.pin_study["reused"] is False and plan.pin_study["parts"] == 1
    assert f.suggestions and f.suggestions[0].lever == "pins" and f.suggestions[0].id


def test_a_board_that_says_not_to_and_an_explore_variant_are_not_studied():
    b = board()
    b.pin_study = False
    assert remaps(b.resolve()) == []
    plan = board().resolve(explore=Explore(3, frozenset({"r1"})))
    assert remaps(plan) == [] and plan.pin_study == {}


def test_the_study_moves_nothing_the_placement_is_the_one_without_a_pool():
    with_pool, without = board().resolve(), board(fields={}).resolve()
    keys = ["u1", "r1", "r2", "r3", "r4"]
    assert [with_pool.placement(k) for k in keys] == [without.placement(k) for k in keys]
    assert remaps(without) == [] and without.pin_study == {}


def test_a_resolve_reading_what_the_last_one_read_reuses_its_study(tmp_path):
    first = board()
    first.pin_study_cache = tmp_path / "pinmap" / "layout.json"
    a = first.resolve()
    second = board()
    second.pin_study_cache = first.pin_study_cache
    b = second.resolve()
    assert (a.pin_study["reused"], b.pin_study["reused"]) == (False, True)
    assert [str(f) for f in remaps(a)] == [str(f) for f in remaps(b)]
    assert study_line(b.pin_study).startswith("1 part, the last study reused")


def _scripted(tmp_path, monkeypatch, overlay=None):
    from types import SimpleNamespace
    from placemat import context, runner
    script = tmp_path / "x_layout.py"
    script.write_text("")
    fab = SimpleNamespace(via_drill=0.3, via_size=0.6, courtyard_excess=0.1, component_spacing=None, via_tiers={}, path=None)
    monkeypatch.setattr(context, "_overlay", overlay)
    return runner.scripted_board(script, SimpleNamespace(board_dir=tmp_path), settings(), fab, False,
                                 geometry=board().geometry)


def test_a_run_keeps_the_study_beside_its_board_and_a_try_keeps_nothing(tmp_path, monkeypatch):
    assert _scripted(tmp_path, monkeypatch).pin_study_cache == tmp_path / ".placemat" / "pinmap" / "x_layout.json"
    tried = _scripted(tmp_path, monkeypatch, overlay={str((tmp_path / "x_layout.py").resolve()): ""})
    assert tried.pin_study_cache is None


def test_an_explore_worker_board_is_not_studied(monkeypatch):
    from placemat import explore, runner
    monkeypatch.setattr(runner, "scripted_board", lambda *a, **k: board())
    assert explore.BoardFactory(None, None, None, None, False, None)().pin_study is False
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_wiring.py -q -n 2`
Expected: FAIL with `ImportError: cannot import name 'study_line' from 'placemat.pinmap'`.

- [ ] **Step 3: Where a part's courtyard stands now**

In `src/placemat/occupancy.py`, before `    def carry(self, ref: str, shapes) -> None:`, add:

```python
    def courtyard_box(self, ref: str) -> Box:
        """The box round a part's courtyard where the part stands NOW: its courtyard box as read, moved and turned as the
        part has moved since (as `pad_anchor` moves a pad's anchor)."""
        fp = self.geometry.footprint(ref)
        read = ItemGeometry(frozenset([ref]), Placement(fp.location, fp.rotation, fp.face), (), fp.body_box,
                            frozenset())
        t = self._transform(read, self.items[ref].reference)
        b = fp.courtyard_box
        return Box.of_points([t.apply(p) for p in ((b.left, b.top), (b.right, b.top), (b.right, b.bottom), (b.left, b.bottom))])

```

- [ ] **Step 4: The hook at the end of a resolve**

In `src/placemat/layout.py`:

In `class Plan`, after the `given_way` field add:

```python
    pin_study: dict = field(default_factory=dict)                 # the pin map study's record (pinmap.study_findings): seconds, reused, groups, parts
```

In `Board.__init__`, after `        self.script_file = ""               # the layout script this board runs, set by the runner` add:

```python
        self.pin_study = True               # the pin map study runs at the end of a resolve; an explore's variant boards say False
        self.pin_study_cache = None         # where the last pin map study is kept (pinmap.py), set by the runner; None: not kept
```

In `_resolve_once`, replace:

```python
        self._report_splits(plan)
        self._place_labels(occ, plan, placed, progress, final=True)
```

with:

```python
        self._report_splits(plan)
        if self._explore is None and self.pin_study:
            self._report_pin_maps(plan)
        self._place_labels(occ, plan, placed, progress, final=True)
```

Before `    def _report_links(self, occ: Occupancy, plan: Plan, placed: set):` add:

```python
    def _report_pin_maps(self, plan: Plan) -> None:
        """The pin map study (pinmap.py) on the finished board: once per resolve, never inside the search. An explore's
        variants are studied by the explore (explore._pin_maps), on its best ones only."""
        from . import pinmap
        plan.findings.extend(pinmap.plan_findings(self, plan))

```

- [ ] **Step 5: The plan's board as the study reads it**

In `src/placemat/pinmap.py`, replace:

```python
from .pinmap_input import build, placed_from_geometry
```

with:

```python
from .pinmap_input import PlacedPad, PlacedPart, build, placed_from_geometry
```

and append:

```python


def study_line(record: dict) -> str:
    """What a run or a preview says of the study, from its record."""
    if record.get("reused"):
        return "%d part%s, the last study reused (%.2f s)" % (record["parts"], "" if record["parts"] == 1 else "s",
                                                                record["seconds"])
    return "%d part%s in %d group%s (%.2f s)" % (record["parts"], "" if record["parts"] == 1 else "s", record["groups"],
                                               "" if record["groups"] == 1 else "s", record["seconds"])


def placed_from_plan(board, plan) -> tuple:
    """(pads, {ref: PlacedPart}) of a resolved plan: every placed part where the placement put it (its pads at their
    airwire anchors, its courtyard's box), and whether its declaration lets it stand on the other face."""
    occ = plan.occupancy
    either = {i.item.ref for i in board._placements() if i.kind == "part" and getattr(i, "either", False)}
    pads, parts = [], {}
    for ref in sorted(occ.items):
        if ref in occ.pending or not occ.geometry.has_footprint(ref):
            continue
        fp = occ.geometry.footprint(ref)
        nc = {p.number for p in fp.pads if p.no_connect}
        for s in occ.items[ref].shapes:
            if s.kind in ("pad", "through") and s.owner == ref:
                pads.append(PlacedPad(ref, s.label, s.net, frozenset(s.layers), (tuple(s.poly),), s.box,
                                      occ.pad_anchor(ref, s.label), s.label in nc))
        g = occ.items[ref].reference
        parts[ref] = PlacedPart(ref, occ.courtyard_box(ref), g.rotation, g.face.value, ref in either, dict(fp.fields))
    return pads, parts


def plan_findings(board, plan) -> list:
    """The study of a resolved plan's board, its record kept on the plan (`plan.pin_study`): what the end of a resolve
    adds to its findings. A board whose parts carry no `Pm.PinPool` is not read."""
    if not has_pools(board.geometry.footprints):
        return []
    from .pairs import board_pairs
    pads, parts = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    found, record = study_findings(pads, parts, board.geometry.pin_names, quiet, board_pairs(board.geometry.netclasses),
                                   board.geometry.netclasses, board.settings, copper_nets(board.geometry, plan),
                                   board.pin_study_cache)
    plan.pin_study = record
    return found
```

- [ ] **Step 6: The runner keeps the study beside the board and says it; an explore's boards are not studied**

In `src/placemat/runner.py`, in `scripted_board`, replace:

```python
    from . import context as context_mod
    if context_mod._overlay:                            # a try of a suggestion: declarations' digests are of the text it ran
        board.source_reader = context_mod.read_source
```

with:

```python
    from . import context as context_mod
    if context_mod._overlay:                            # a try of a suggestion: declarations' digests are of the text it ran
        board.source_reader = context_mod.read_source
    else:                                               # a try writes nothing, the pin map study's record included
        board.pin_study_cache = Path(src.board_dir) / ".placemat" / "pinmap" / (Path(script).stem + ".json")
```

In `_run`, replace:

```python
        metrics["resolve_seconds"] = round(plan.seconds, 3)
```

with:

```python
        metrics["resolve_seconds"] = round(plan.seconds, 3)
        if plan.pin_study:
            from .pinmap import study_line
            metrics["pin_study"] = dict(plan.pin_study)
            say("pins", study_line(plan.pin_study))
```

In `src/placemat/explore.py`, replace `BoardFactory.__call__`:

```python
    def __call__(self):
        from .runner import scripted_board
        return scripted_board(self.script, self.src, self.cfg, self.fab, self.keep_going, geometry=self.geometry)
```

with:

```python
    def __call__(self):
        from .runner import scripted_board
        board = scripted_board(self.script, self.src, self.cfg, self.fab, self.keep_going, geometry=self.geometry)
        board.pin_study = False             # a variant is studied by the explore, on its best ones (`_pin_maps`)
        return board
```

In `src/placemat/previewer.py`, in `_resolved`, replace:

```python
        timecap.placement_done()                # the placement is in hand: the cap is lifted for the drawing
        held = explore_mod.lock_summary(plan)
```

with:

```python
        timecap.placement_done()                # the placement is in hand: the cap is lifted for the drawing
        if plan.pin_study and not quiet:
            from .pinmap import study_line
            console.say("pins", study_line(plan.pin_study))
        held = explore_mod.lock_summary(plan)
```

- [ ] **Step 7: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_wiring.py tests/test_pinmap_finding.py -q -n 2`
Expected: PASS (6 and 10 tests).

- [ ] **Step 8: The suite and the bench**

The hook runs at the end of every resolve; a board without a `Pm.PinPool` returns at `has_pools` before reading anything, so no placement and no score may change. Check that:

Run: `.venv/bin/python -m pytest -n 2 -q 2>&1 | tail -5`
Expected: no failures.

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`
Expected: every case `same` (no fixture module carries a pool).

- [ ] **Step 9: Commit**

```bash
git add src/placemat/occupancy.py src/placemat/layout.py src/placemat/pinmap.py src/placemat/runner.py src/placemat/explore.py src/placemat/previewer.py tests/test_pinmap_wiring.py
{ echo "Pin map study: once at the end of a run's or a preview's resolve, reused while what it reads is unchanged"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 10: The explore hook - the best variants studied, reported beside their scores

**Files:**
- Modify: `src/placemat/pinmap.py` (append `plan_summary`)
- Modify: `src/placemat/explore.py` (`search`'s two finishing branches, `_pin_maps`, `pin_map_lines`, `_report_lines`)
- Test: `tests/test_pinmap_explore.py`

**Interfaces:**
- Consumes: Task 9's `placed_from_plan`, `has_pools`; Task 7's `linked_groups`, `study_group`; Task 8's `_turns`, `_map`; `finding_text.pose_text`; `explore.Explore`, `explore._context_of`, `ExploreResult.results` (rows `(seed, score, measures)`, best first).
- Produces: `pinmap.plan_summary(board, plan, refs=None, settings=None) -> list[dict]` (per group: `refs`, `present`, `best` (breakdowns as JSON), `rotation` (the best pose's index), `turns`, `map`, `searched`, `of`, `budget_out`); `explore._pin_maps(make_board, entries, focus, result, have) -> list[dict]` (per variant: `seed`, `score`, `groups`); `report["pin_maps"]` in the explore report (`metrics.explore` in `run.json`); `explore.pin_map_lines(report) -> list[str]`, printed under the explore's line.

The variants stay ranked by run score; the study's numbers are reported beside the score and never added to it. Seed 0 is the plan `search` already resolved (`current`), the best seed the one it resolves for the moves (`best`); any other of the top `pins.explore_top` is resolved again here (a seed is deterministic). Nothing is resolved when no part carries a pool.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_explore.py`:

```python
"""At the end of an explore the pin map study runs on the best `pins.explore_top` variants: each variant's crossings
after remapping and its map are reported beside its run score, which they do not change."""
from types import SimpleNamespace

from placemat.explore import _pin_maps, _report_lines
from tests.test_pinmap_wiring import board

RESULT = SimpleNamespace(results=[(0, 10.0, {}), (2, 11.0, {}), (5, 12.5, {}), (7, 13.0, {})])


def test_the_best_variants_are_studied_in_the_explores_order_and_reported_beside_their_score():
    b = board()
    made = []

    def make():
        made.append(1)
        return board()
    maps = _pin_maps(make, [], frozenset({"r1"}), RESULT, {0: (b, b.resolve())})
    assert [(m["seed"], m["score"]) for m in maps] == [(0, 10.0), (2, 11.0), (5, 12.5)] and len(made) == 2
    (g,) = maps[0]["groups"]
    assert g["refs"] == ["U1"] and g["best"]["weighted"] < g["present"]["weighted"] and g["map"]
    report = {"tried": 4, "seconds": 1.0, "focus": ["r1"], "baseline": 10.0, "best": 10.0, "best_seed": 2,
              "moves": [], "accepted": False, "pin_maps": maps}
    lines = _report_lines(report)
    assert "  pin map, seed 2 at 11.0 mm: U1 6 -> 0 weighted crossings after remapping" in lines
    assert lines[0].endswith("score 10.0 -> 10.0 mm; 0 items would move")


def test_a_board_without_a_pool_resolves_no_variant_for_the_study():
    b = board(fields={})
    made = []
    assert _pin_maps(lambda: made.append(1), [], frozenset(), RESULT, {0: (b, b.resolve())}) == [] and made == []
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_explore.py -q -n 2`
Expected: FAIL with `ImportError: cannot import name '_pin_maps' from 'placemat.explore'`.

- [ ] **Step 3: A summary of the study of a plan, without findings**

Append to `src/placemat/pinmap.py`:

```python


def plan_summary(board, plan, refs=None, settings=None) -> list:
    """Each studied group's present score and its best, with the pose and the map, for an explore's report and a longer
    study: no findings, nothing kept. `refs` keeps the groups holding any of those parts; `settings` replaces the
    board's (a longer budget)."""
    if not has_pools(board.geometry.footprints):
        return []
    from .pairs import board_pairs
    from .pinmap_search import linked_groups, study_group
    settings = settings or board.settings
    pads, parts = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    inp, _ = build(pads, parts, board.geometry.pin_names, quiet, board_pairs(board.geometry.netclasses),
                   board.geometry.netclasses, settings.pins_follow_series)
    if inp is None:
        return []
    background = Background(inp.background, Weights.of(settings))
    out = []
    for group in linked_groups(inp):
        if refs and not set(group) & set(refs):
            continue
        g = study_group(inp, group, settings, background)
        if not g.results:
            continue
        i = min(range(len(g.results)), key=lambda k: (g.results[k].breakdown.total, k))
        r = g.results[i]
        out.append({"refs": list(g.refs), "present": g.present.to_json(), "best": r.breakdown.to_json(), "rotation": i,
                    "turns": _turns(inp, r.poses), "map": _map(inp, g.refs, g.present_assign, r.assign),
                    "searched": g.searched, "of": g.of, "budget_out": g.budget_out})
    return out
```

- [ ] **Step 4: The explore studies its best variants**

In `src/placemat/explore.py`, in `search`, replace:

```python
    if result.best_seed == 0:
        _write_record(script, result, report)
```

with:

```python
    if result.best_seed == 0:
        report["pin_maps"] = _pin_maps(make_board, entries, focus, result, {0: (base, current)})
        _write_record(script, result, report)
```

and replace:

```python
        if ck is not None:
            ck.best_path.unlink(missing_ok=True)         # taken: it would not match the lock now
    _write_record(script, result, report)
```

with:

```python
        if ck is not None:
            ck.best_path.unlink(missing_ok=True)         # taken: it would not match the lock now
    report["pin_maps"] = _pin_maps(make_board, entries, focus, result, {0: (base, current), result.best_seed: (board, best)})
    _write_record(script, result, report)
```

Before `def stopped_line(report) -> str:` add:

```python
def _pin_maps(make_board, entries, focus, result, have: dict) -> list:
    """The pin map study (pinmap.py) on the best `pins.explore_top` variants, in the explore's own order (by run score):
    each variant's weighted crossings after remapping and its map, reported beside its score and never folded into it.
    `have` holds plans already resolved, {seed: (board, plan)}; another variant is resolved again (a seed is
    deterministic). Nothing is resolved for a board whose parts carry no `Pm.PinPool`."""
    from . import pinmap
    first = have[0][0]
    top = first.settings.pins_explore_top
    if top <= 0 or not pinmap.has_pools(first.geometry.footprints):
        return []
    out = []
    with _context_of(make_board):
        for seed, total, _ in result.results[:top]:
            if seed in have:
                board, plan = have[seed]
            else:
                board = make_board()
                plan = board.resolve(explore=Explore(seed, frozenset(focus)), lock=entries)
            out.append({"seed": seed, "score": round(total, 1), "groups": pinmap.plan_summary(board, plan)})
    return out


```

In `_report_lines`, replace:

```python
    if report["accepted"]:
        lines.append("accepted: written to the lock")
```

with:

```python
    lines += pin_map_lines(report)
    if report["accepted"]:
        lines.append("accepted: written to the lock")
```

Before `def lock_summary(plan) -> str:` add:

```python
def pin_map_lines(report) -> list:
    """A line per studied group of each variant the pin map study ran on: its weighted crossings now and after
    remapping, and the pose that takes."""
    from .finding_text import pose_text
    out = []
    for v in report.get("pin_maps") or ():
        for g in v["groups"]:
            turned = [t for t in g["turns"] if t["turn_deg"] or t["flip"]]
            out.append("  pin map, seed %d at %.1f mm: %s %g -> %g weighted crossings after remapping%s" % (
                v["seed"], v["score"], " and ".join(g["refs"]), g["present"]["weighted"], g["best"]["weighted"],
                ", at " + pose_text(turned) if turned else ""))
    return out


```

- [ ] **Step 5: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_explore.py tests/test_explore_search.py tests/test_explore_resolve.py tests/test_explore_accept.py tests/test_explore_best.py -q -n 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/pinmap.py src/placemat/explore.py tests/test_pinmap_explore.py
git commit -m "Explore: the pin map study of the best variants, reported beside their scores"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 11: A longer study from `placemat apply <id> --search`

The spec's "the probe can run the study with a larger budget": the command a probe already is. `placemat apply <id> --search` on a `pins` advice suggestion resolves the board as the last run placed it, studies the suggestion's parts with `pins.probe_budget_ms` a part, and keeps a better map as `<id>.1` beside the plan's suggestions (`suggestions.add_found`), where `placemat apply` and the studio find it - as advice, which `apply` refuses to write.

**Files:**
- Modify: `src/placemat/pinmap.py` (append `longer_advice`)
- Modify: `src/placemat/cli.py` (`_search` dispatch; `_pin_search`)
- Test: `tests/test_pinmap_probe.py`

**Interfaces:**
- Consumes: Task 10's `plan_summary`; Task 8's `suggestions.pin_advice_text`, `Suggestion(advice=...)`; `previewer.resolve_like_last_run(script) -> (board, plan, src, run_id)`; `suggestions.add_found`, `suggestions.recall`, `suggestions.keep`; `settings.load`.
- Produces: `pinmap.longer_advice(board, plan, advice, budget_ms) -> (dict | None, dict | None)`; `cli._pin_search(args, board_dir, script, s) -> int`; the found suggestion `<id>.1` (`how: "advice"`, lever `pins`, text ending `, found by a longer study`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_probe.py`:

```python
"""`placemat apply <id> --search` on a pin map suggestion studies its parts again with `pins.probe_budget_ms` a part,
on the board as the last run placed it, and keeps a better map as `<id>.1`."""
from types import SimpleNamespace

from placemat import cli, previewer, settings as settings_mod, suggestions as sg
from placemat.findings import FindingCause as C
from placemat.pinmap import longer_advice
from tests.pinmap_boards import settings
from tests.test_pinmap_wiring import board


def advice_of(plan):
    f = next(f for f in plan.findings if f.cause is C.PINS_REMAP)
    return f.suggestions[0]


def test_a_longer_study_offers_a_map_only_when_it_beats_the_one_suggested():
    b = board()
    plan = b.resolve()
    s = advice_of(plan)
    assert longer_advice(b, plan, s.advice, 2000)[0] is None             # this board has nothing better to find
    worse = dict(s.advice, total=s.advice["total"] + 1.0)
    better, g = longer_advice(b, plan, worse, 2000)
    assert better["total"] == g["best"]["total"] < worse["total"] and better["map"] == s.advice["map"]


def test_the_search_keeps_a_better_map_as_the_next_id(tmp_path, monkeypatch, capsys):
    b = board()
    plan = b.resolve()
    s = advice_of(plan)
    s = sg.Suggestion(s.text, (), 1, "pins", "s1a", how="advice", advice=dict(s.advice, total=s.advice["total"] + 1.0))
    script = tmp_path / "x_layout.py"
    script.write_text("")
    sg.keep(tmp_path, script, "run 1", [s])
    monkeypatch.setattr(previewer, "resolve_like_last_run", lambda path: (b, plan, None, "1"))
    monkeypatch.setattr(settings_mod, "load", lambda *a, **k: settings(pins_probe_budget_ms=1000))
    assert cli._pin_search(SimpleNamespace(json=False), tmp_path, script, s) == 0
    kept = sg.recall(tmp_path, script)[str(script.resolve())]["suggestions"]
    found = next(x for x in kept if x.id == "s1a.1")
    assert found.how == "advice" and found.text.endswith(", found by a longer study")
    assert "s1a.1: " in capsys.readouterr().out
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_probe.py -q -n 2`
Expected: FAIL with `ImportError: cannot import name 'longer_advice' from 'placemat.pinmap'`.

- [ ] **Step 3: The longer study**

Append to `src/placemat/pinmap.py`:

```python


def longer_advice(board, plan, advice: dict, budget_ms: int) -> tuple:
    """(better advice or None, the group's summary or None): the advice's parts studied again with `budget_ms` for each
    part (`placemat apply <id> --search`). The advice is better when its total is below the one it was given with."""
    from dataclasses import replace
    s = replace(board.settings, pins_budget_ms=budget_ms)
    g = next((g for g in plan_summary(board, plan, refs=advice["refs"], settings=s)
              if set(g["refs"]) == set(advice["refs"])), None)
    if g is None or g["best"]["total"] >= advice["total"] - 1e-9:
        return None, g
    return {"refs": g["refs"], "rotation": g["rotation"], "turns": g["turns"], "map": g["map"],
            "total": g["best"]["total"], "weighted": g["best"]["weighted"]}, g
```

In `src/placemat/cli.py`, in `_search`, replace:

```python
    s = next(x for x in entry["suggestions"] if x.id == args.id)
    if s.how != "searched":
```

with:

```python
    s = next(x for x in entry["suggestions"] if x.id == args.id)
    if s.how == "advice" and s.lever == "pins":
        return _pin_search(args, board_dir, script, s)
    if s.how != "searched":
```

Before `def _report_applied(args, done, verb) -> int:` add:

```python
def _pin_search(args, board_dir, script, s) -> int:
    """`placemat apply <id> --search` on a pin map suggestion: its parts studied again, on the board as the last run placed
    it, with `pins.probe_budget_ms` for each part. A better map is kept as `<id>.1` beside the plan's suggestions."""
    from . import pinmap, suggestions as sg
    from .previewer import resolve_like_last_run
    from .settings import load
    cfg = load(board_dir, script=script)
    try:
        board, plan, _, _ = resolve_like_last_run(script)
    except ValueError as e:
        console.say("probe", str(e), level="fail")
        return 1
    better, g = pinmap.longer_advice(board, plan, s.advice, cfg.pins_probe_budget_ms)
    found = None if better is None else sg.Suggestion(sg.pin_advice_text(better) + ", found by a longer study", (), 1,
                                                      "pins", s.id + ".1", how="advice", advice=better)
    if found is not None:
        sg.add_found(board_dir, script, found)
    if args.json:
        console.data(json.dumps({"id": s.id, "study": g, "found": found.to_json() if found is not None else None}, indent=2))
        return 0 if g is not None else 1
    if g is None:
        console.say("probe", "%s: %s is no longer studied on this board" % (s.id, " and ".join(s.advice["refs"])), level="fail")
        return 1
    console.say("probe", "%s: %d of %d poses at %d ms a part: best total %.1f, the suggestion's %.1f" % (
        s.id, g["searched"], g["of"], cfg.pins_probe_budget_ms, g["best"]["total"], s.advice["total"]))
    console.say("probe", "%s: %s; it is advice for the capture, which placemat apply does not write" % (found.id, found.text)
                if found is not None else "no better map than %s's" % s.id)
    return 0


```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_probe.py tests/test_apply_suggestion.py -q -n 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pinmap.py src/placemat/cli.py tests/test_pinmap_probe.py
git commit -m "placemat apply --search studies a pin map suggestion's parts again with a longer budget"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 12: Studio - the map and the airwires before and after

The page already has what it needs: the plan JSON carries each finding's `facts` (with `before` and each pose's `paths`) and its suggestions' JSON (with `advice`), and `/suggest/show`, `/try` and `/apply` refuse an advice suggestion through `apply_suggestion` (Task 8). This task is the page alone: an advice suggestion is a third kind in `SG_KINDS` whose one button, Try, draws the airwires and lists the map, and writes and resolves nothing.

**Files:**
- Modify: `src/placemat/studio_page.html` (CSS, `S.pinmap`, `SG_KINDS.advice`, `sgKind`, `sgRow`, `sgAct`, `pinMapOf`, `pinMapSVG`, `pinMapHTML`, `drawPinMap`, `render`)
- Test: `tests/test_studio_page.py` (append)

**Interfaces:**
- Consumes: the finding JSON `{cause: "pins.remap", facts: {before, rotations: [{paths, map, ...}]}, suggestions: [{id, how: "advice", lever: "pins", advice: {rotation, turns, map, ...}}]}` (Task 8); the page's `plan()`, `esc`, `num`, `B.svg`, `schedule`, `render`.
- Produces: `S.pinmap: {sid} | null`; `pinMapSVG(f, s) -> string` (a `<g class="pinmap">` of `polyline.pm-before` and `polyline.pm-after`); `pinMapHTML(s) -> string`; `drawPinMap()`.

Colours: the before airwires dashed in `--k-violet`, the after ones solid in `--good`, in both themes through the stylesheet's tokens; no red, yellow or grey (none of them is an error or a warning).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_studio_page.py`:

```python


# ---------------------------------------------------------------- a pin map suggestion
PINMAP = r"""
const PM_ADVICE = {refs: ["U1"], rotation: 1, total: 2.5, weighted: 0,
  turns: [{ref: "U1", turn_deg: 90, rotation_deg: 90, face: "front", flip: false}],
  map: [{ref: "U1", net: "SDA", from: {pin: "12", name: "GPIO7"}, to: {pin: "14", name: "GPIO9"}}]};
const PM_FACTS = {ref: "U1", refs: ["U1"], best: 1, present: {total: 9}, routed: [],
  before: [{net: "SDA", path: [[1, 1], [5, 1]]}],
  rotations: [{paths: [{net: "SDA", path: [[1, 1], [4, 1]]}], map: []}, {paths: [{net: "SDA", path: [[2, 2], [5, 2], [5, 4]]}], map: PM_ADVICE.map}]};
const PM_FND = [{text: "U1: a pin map with 3 fewer weighted crossings exists at its present rotation", kind: "pins", severity: "notice", item: "",
  cause: "pins.remap", facts: PM_FACTS, at: [10, 10], refs: ["U1"], pads: [],
  suggestions: [{id: "s1a", text: "Move 1 net of U1 to the pins in the map, a capture change, and turn U1 to 90 degrees", rank: 1, lever: "pins", how: "advice", edits: [], advice: PM_ADVICE}]}];
"""


@needs_node
def test_a_pin_map_suggestion_offers_try_alone_and_its_try_lists_the_map_and_draws_the_airwires_before_and_after(tmp_path):
    out = run_more(tmp_path, SUGGEST + PINMAP + r"""
(async () => {
  full([item("a", 1)], [st("a")], {findings: PM_FND});
  const html = () => { ev("renderFindings()"); return els["#tab-findings"].innerHTML; };
  out.offered = html();
  await ev("sgAct")("pinmap", "s1a");
  out.open = html(); out.state = ev("S.pinmap");
  out.svg = ev("pinMapSVG(plan().findings[0], plan().findings[0].suggestions[0])");
  await ev("sgAct")("pinmap", "s1a");
  out.closed = html(); out.after = ev("S.pinmap");
  console.log(JSON.stringify(out));
})();
""")
    h = out["offered"]
    assert 'data-sg="pinmap" data-sid="s1a"' in h and 'data-sg="show" data-sid="s1a"' not in h and 'data-sg="apply" data-sid="s1a"' not in h
    assert "pmmap" not in h
    o = out["open"]
    assert out["state"] == {"sid": "s1a"} and "<b>SDA</b>" in o and "GPIO7, pin 12" in o and "GPIO9, pin 14" in o
    assert "turn U1 to 90 degrees" in o and "airwires now" in o and "airwires after" in o
    svg = out["svg"]
    assert svg.count('class="pm-before"') == 1 and svg.count('class="pm-after"') == 1 and 'points="2,2 5,2 5,4"' in svg
    assert out["after"] is None and "pmmap" not in out["closed"]
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/python -m pytest tests/test_studio_page.py -q -n 2 -k "pin_map or parses"`
Expected: FAIL on `'data-sg="pinmap" data-sid="s1a"' in h`: without its own kind an advice suggestion is drawn with Show, Try and Apply.

- [ ] **Step 3: The page**

In `src/placemat/studio_page.html`:

After the CSS line `.sgmore { cursor: pointer; color: var(--accent); font-size: 12px; }` add:

```css
.pmmap { margin: 3px 0 4px; padding: 6px 8px; background: var(--surface2); border: 1px solid var(--line); border-radius: 6px; font-weight: 400; }
.pmmap table { border-collapse: collapse; font-size: 12px; }
.pmmap td { padding: 0 8px 0 0; }
.pmkey { display: inline-block; width: 18px; height: 0; vertical-align: middle; margin: 0 4px 0 10px; }
.pmkey.before { border-top: 1.5px dashed var(--k-violet); }
.pmkey.after { border-top: 2px solid var(--good); }
.pinmap polyline { fill: none; }
.pinmap .pm-before { stroke: var(--k-violet); stroke-width: 0.15; stroke-dasharray: 0.6 0.4; }
.pinmap .pm-after { stroke: var(--good); stroke-width: 0.2; }
```

In `const S = {`, after the `  sg: {more: new Set(), ...},` line add:

```js
  pinmap: null,                // the pin map suggestion whose airwires are drawn: {sid}
```

In `render`, after `  if (has("board") || has("runs")) drawExplore();` add:

```js
  if (has("board") || has("findings")) drawPinMap();
```

In `SG_KINDS`, after the `search:` entry add the advice kind, and after the object the kind chooser:

```js
  advice: (b) => b("pinmap", "Try", "draw the airwires before and after this map and list it; nothing is resolved or written"),
};
const sgKind = s => s.how === "searched" ? "search" : s.how === "advice" ? "advice" : "instant";
```

(the `};` shown is the object's existing closing line: the new entry goes before it and `sgKind` after it.)

In `sgRow`, replace:

```js
    (SG_KINDS[s.how === "searched" ? "search" : "instant"])(b) + "</span></div>" + (s.how === "searched" ? sgProbeHTML(s) : "");
```

with:

```js
    SG_KINDS[sgKind(s)](b) + "</span></div>" + (s.how === "searched" ? sgProbeHTML(s) : "") + (S.pinmap && S.pinmap.sid === s.id ? pinMapHTML(s) : "");
```

In `sgAct`, before `  } else if (kind === "search") {` add:

```js
  } else if (kind === "pinmap") {
    S.pinmap = S.pinmap && S.pinmap.sid === sid ? null : {sid};
    drawPinMap(); schedule("findings", "card", "steps");
```

Before `function drawExplore() {` add:

```js
// ---- a pin map suggestion (lever pins, how "advice"): the map is a capture change, so there is no edit to show, try or apply.
// Its Try draws the finding's airwires before (the present map, dashed) and after (the map at the suggestion's pose) over the
// board, and lists the map under its row; pressed again it takes them away.
function pinMapOf(p, sid) {
  for (const f of (p && p.findings) || []) for (const s of f.suggestions || []) if (s.id === sid && s.advice) return {f, s};
  return null;
}
function pinMapSVG(f, s) {
  const r = (f.facts.rotations || [])[s.advice.rotation];
  if (!r) return "";
  const line = (cls, w) => '<polyline class="' + cls + '" data-net="' + esc(w.net) + '" points="' + w.path.map(q => num(q[0]) + "," + num(q[1])).join(" ") + '"/>';
  return '<g class="pinmap">' + (f.facts.before || []).map(w => line("pm-before", w)).join("") + (r.paths || []).map(w => line("pm-after", w)).join("") + "</g>";
}
function pinMapHTML(s) {
  const a = s.advice, pin = e => esc(e.name ? e.name + ", pin " + e.pin : "pin " + e.pin);
  const turned = (a.turns || []).filter(t => t.turn_deg || t.flip);
  const rows = (a.map || []).map(m => "<tr><td>" + esc(m.ref) + "</td><td><b>" + esc(m.net) + "</b></td><td>" + pin(m.from) + "</td><td>-&gt;</td><td>" + pin(m.to) + "</td></tr>").join("");
  return '<div class="pmmap">' + (rows ? "<table>" + rows + "</table>" : "<div>the pins stay as they are</div>") +
    turned.map(t => "<div>turn " + esc(t.ref) + " to " + esc(String(t.rotation_deg)) + " degrees" + (t.flip ? " on the " + esc(t.face) : "") + "</div>").join("") +
    '<div><span class="pmkey before"></span>airwires now<span class="pmkey after"></span>airwires after</div></div>';
}
function drawPinMap() {
  const svg = typeof B !== "undefined" && B.svg; if (!svg || !svg.querySelectorAll) return;
  for (const e of svg.querySelectorAll(".pinmap")) e.remove();
  const hit = S.pinmap && pinMapOf(plan(), S.pinmap.sid);
  if (!hit) return;
  const g = pinMapSVG(hit.f, hit.s);
  for (const panel of svg.querySelectorAll(".panel")) panel.insertAdjacentHTML("beforeend", g);
}
```

- [ ] **Step 4: Run the page tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_studio_page.py -q -n 2`
Expected: PASS (the new test, the script still parses, and the colour-scheme test still finds only stylesheet colours).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/studio_page.html tests/test_studio_page.py
git commit -m "Studio: a pin map suggestion's Try draws the airwires before and after and lists the map"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 13: Bench - a reference board with an MCU and a pool, measured against the budget

**Files:**
- Create: `fixtures/pinmap/reference.json` (the reference case: a laid fixture board, its plane nets, and its MCU's pin annotations - which live only here)
- Create: `fixtures/pinmap_bench.py`
- Test: `tests/test_pinmap_real.py` (written and watched failing here; committed by Task 15 once the defaults let it pass)

**Interfaces:**
- Consumes: Task 8's `pinmap.geometry_findings`; `kicad.read.read_board`; `Settings`.
- Produces: `fixtures/pinmap_bench.py` with `annotated(geometry, parts)`, `cases()`, `board_of(case)`, `best_of(found)`, `run_case(case, settings, repeat)`, `main(argv)`; the measurements in `$SCRATCH/pinmap-bench.txt` that Tasks 14 and 15 read.

The reference board is a laid board among the existing fixtures (the path in `reference.json`) whose 56-pin MCU carries 23 signal nets on its general-purpose pins and five unconnected pins, with nets routed already (so the study's "scored as unrouted" path is exercised). The annotations below were chosen from the pads' nets as read while planning: pool pads 6-19, 21-24, 27, 38-45, 47-48; pad 8 (a strap) fixed; one net allowed only on pads 6-15; the two-wire bus pair a group; the ground and the 3.3 V net are its plane nets.

- [ ] **Step 1: The reference case and the bench**

Create `fixtures/pinmap/reference.json`:

```json
{
  "about": "The pin map study's reference boards: each a laid board of these fixtures, the plane nets its layout declares, and the pin annotations its MCU is given here for the study. The annotations live only in this file: no capture carries them.",
  "cases": [
    {
      "name": "mcu-qfn56",
      "board": "fairing/core/layout/layout.kicad_pcb",
      "quiet": ["GND", "V3V3"],
      "parts": {
        "U21": {
          "Pm.PinPool": "6-19, 21-24, 27, 38-45, 47-48",
          "Pm.PinFixed": "8",
          "Pm.PinAllow": "INA_ALERT:6-15",
          "Pm.PinGroup": "i2c:13-14"
        }
      }
    }
  ]
}
```

Create `fixtures/pinmap_bench.py`:

```python
"""The pin map study's speed and result on the reference boards (fixtures/pinmap/reference.json): each case's laid board
read as its file has it, its parts given the fixture's pin annotations (no capture carries them), and the study run as
a run runs it, `--repeat` times. Prints, per case, the median seconds per studied part against `pins.budget_ms`, whether
the clock ran out, and the present and best totals; with `--long`, the best a long search finds too, the mark the
default search effort is judged against.

    flock <realboard lock> .venv/bin/python fixtures/pinmap_bench.py [--repeat N] [--long] [--set pins_key=value ...]

Real boards: run it alone, under the lock the other real-board runs take."""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REFERENCE = HERE / "pinmap" / "reference.json"


def annotated(geometry, parts: dict):
    """The board with the fixture's annotations added to its parts' fields."""
    fps = tuple(dataclasses.replace(fp, fields=dict(fp.fields, **parts[fp.ref])) if fp.ref in parts else fp
                for fp in geometry.footprints)
    return dataclasses.replace(geometry, footprints=fps)


def cases() -> list:
    return json.loads(REFERENCE.read_text())["cases"]


def board_of(case):
    from placemat.kicad.read import read_board
    return annotated(read_board(HERE / case["board"]), case["parts"])


def best_of(found) -> dict:
    """{"present", "best", "budget_out", "pose"} of the first `pins.remap` finding, or {} for none."""
    f = next((f for f in found if f.cause.value == "pins.remap"), None)
    if f is None:
        return {}
    r = f.facts["rotations"][f.facts["best"]] if f.facts["rotations"] else {}
    return {"present": f.facts["present"]["total"], "best": r.get("total"), "budget_out": f.facts["budget_out"],
            "pose": [t["rotation_deg"] for t in r.get("turns", ())]}


def run_case(case, settings, repeat: int) -> dict:
    from placemat.pinmap import geometry_findings
    g = board_of(case)
    times, out = [], {}
    for _ in range(repeat):
        t0 = time.perf_counter()
        found, record = geometry_findings(g, settings, frozenset(case["quiet"]))
        times.append(time.perf_counter() - t0)
        out = best_of(found)
    parts = max(record.get("parts") or 1, 1)
    return dict(out, seconds_per_part=round(statistics.median(times) / parts, 3))


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--long", action="store_true", help="also run a long search (4 seeds of 4000 moves, no clock)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="a setting, e.g. pins_anneal_moves=200")
    args = ap.parse_args(argv)
    from placemat.settings import Settings
    over = {k: _value(v) for k, v in (s.split("=", 1) for s in args.set)}
    if "pins_rotations" in over:
        over["pins_rotations"] = tuple(over["pins_rotations"])
    settings = dataclasses.replace(Settings(), **over)
    for case in cases():
        got = run_case(case, settings, args.repeat)
        line = "%s: %.3f s a part (budget %d ms), present %s, best %s at %s, clock ran out: %s" % (
            case["name"], got["seconds_per_part"], settings.pins_budget_ms, got.get("present"), got.get("best"),
            got.get("pose"), got.get("budget_out"))
        if args.long:
            long = dataclasses.replace(settings, pins_seeds=4, pins_anneal_moves=4000, pins_budget_ms=10 ** 7)
            line += "; long search best %s" % run_case(case, long, 1).get("best")
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the real-board test and watch it fail**

Create `tests/test_pinmap_real.py`:

```python
"""The pin map study on a real laid board with an MCU (fixtures/pinmap/reference.json, its annotations given there): the
best map beats the present one inside `pins.budget_ms`, a second study of the same board is reused, and no board item
moves."""
import hashlib
import importlib.util
from pathlib import Path

from placemat.findings import FindingCause as C
from placemat.settings import Settings
from tests.conftest import needs_kicad

BENCH = Path(__file__).resolve().parents[1] / "fixtures" / "pinmap_bench.py"


def bench():
    spec = importlib.util.spec_from_file_location("pinmap_bench", BENCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_kicad
def test_on_a_real_board_the_best_map_beats_the_present_one_inside_its_budget_is_reused_and_nothing_moves(tmp_path):
    from placemat.kicad.read import read_board
    from placemat.pinmap import geometry_findings
    b = bench()
    case = b.cases()[0]
    pcb = b.HERE / case["board"]
    digest = hashlib.sha256(pcb.read_bytes()).hexdigest()
    g = b.board_of(case)
    cache = tmp_path / "pinmap.json"
    found, record = geometry_findings(g, Settings(), frozenset(case["quiet"]), cache=cache)
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    assert f.facts["rotations"][f.facts["best"]]["total"] < f.facts["present"]["total"]
    assert f.facts["budget_out"] is False and record["reused"] is False
    again, record = geometry_findings(g, Settings(), frozenset(case["quiet"]), cache=cache)
    assert record["reused"] is True and [str(x) for x in again] == [str(x) for x in found]
    assert hashlib.sha256(pcb.read_bytes()).hexdigest() == digest
    where = lambda geometry: [(fp.ref, fp.location, fp.rotation, fp.face) for fp in geometry.footprints]
    assert where(read_board(pcb)) == where(g)
```

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_pinmap_real.py -q`
Expected: FAIL on `assert f.facts["budget_out"] is False`: at the provisional 400 ms the Python study stops before its four poses are searched. (The rest of the test - a better map, reuse, nothing moved - is checked once the budget fits.)

- [ ] **Step 3: Measure the search effort against a long search**

Run each line, one at a time, and append its output to `$SCRATCH/pinmap-bench.txt`:

```bash
L=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock
flock $L .venv/bin/python fixtures/pinmap_bench.py --repeat 1 --long --set pins_budget_ms=600000 | tee -a $SCRATCH/pinmap-bench.txt
for e in "100 1" "100 2" "200 2" "500 2" "500 4"; do set -- $e
  flock $L .venv/bin/python fixtures/pinmap_bench.py --repeat 3 --set pins_budget_ms=600000 --set pins_anneal_moves=$1 --set pins_seeds=$2 \
    | sed "s/^/moves $1 seeds $2: /" | tee -a $SCRATCH/pinmap-bench.txt
done
```

Expected (measured while planning, pure Python, this machine; your numbers will differ a little):

| moves, seeds | seconds a part | best total |
|---|---|---|
| 100, 1 | 0.42 | 1286.3 |
| 100, 2 | 0.64 | 1274.7 |
| 200, 2 | 0.99 | 1274.5 |
| 500, 4 | 2.24 | 1264.2 |
| long (4000, 4) | - | about 1248 |

(present total 1437.9; the best pose was the present rotation.)

- [ ] **Step 4: Decide**

From `$SCRATCH/pinmap-bench.txt`:

1. The effort is the cheapest (moves, seeds) whose best total is within 2% of the long search's best.
2. If that effort takes more than 0.5 s a part (the spec aims the budget at a few hundred ms), the Python search is over budget on the reference board: Task 14 (native) runs, then Step 3 is run again with the native module in use (`.venv/bin/python -c "from placemat.geometry import native_status; print(native_status().facts())"` shows `in_use: True`), appending to the same file, and 1 is applied to the new numbers.
3. If no effort within 2% takes 0.5 s a part or less even then, the effort is the one with the lowest best total among those that do.
4. Write the decision as two lines at the end of `$SCRATCH/pinmap-bench.txt`: `effort: moves <M> seeds <N>` and `native: yes|no`.

With the planning numbers, (500, 4) is the cheapest within 2% (1264.2 against 1248) at 2.24 s, so Task 14 runs; were the native module not to help, rule 3 would give (100, 1) at 0.42 s.

- [ ] **Step 5: Commit the reference case and the bench (the test waits for Task 15)**

```bash
git add fixtures/pinmap/reference.json fixtures/pinmap_bench.py
{ echo "Bench: the pin map study's reference board and its speed bench"; echo; grep -E "^(mcu|moves)" $SCRATCH/pinmap-bench.txt; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 14: The inner crossing update in the native module (only if Task 13 says so)

Run this task only when `$SCRATCH/pinmap-bench.txt` ends with `native: yes`. Otherwise skip to Task 15.

The two questions the search asks by the thousand move to Rust: what a net's segments cross among the background wires (`Background.cross`), and how many times two nets' segments cross (`segments_crossing`). The answers are the Python ones exactly: segments arrive in whole nanometres, `cross_nm` is `ratsnest._cross_nm`'s port already in `native/src/ratsnest.rs`, and each segment's candidates are taken in wire order so the weighted sums add up in the same order.

**Files:**
- Create: `native/src/pinmap.rs`
- Modify: `native/src/lib.rs` (`mod pinmap;`, `NativeWires`, `segments_crossing`, registration)
- Modify: `src/placemat/pinmap_score.py` (`Background` and `segments_crossing` use the native module when it has them)
- Test: the Rust unit test in `native/src/pinmap.rs`; `tests/test_native_pinmap.py`

**Interfaces:**
- Consumes: `crate::ratsnest::cross_nm` (pub); Task 5's `Background`, `segments_crossing`, `_segments`, `Weights`, `CELL_NM`.
- Produces: `placemat_native.NativeWires(wires: list[(net, kind)], segs: list[(ax, ay, bx, by)], weights: (pair, impedance, plane))` with `.cross(net, kind, segs) -> (float, int)`; `placemat_native.segments_crossing(a, b) -> int`; `Background.mirror` (None in pure Python).

- [ ] **Step 1: Write the Rust test first and watch it fail to build**

Create `native/src/pinmap.rs` with only its test module:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_wire_across_a_segment_counts_and_its_own_net_does_not() {
        let w = Wires::new(vec![("X".into(), "plain".into()), ("A".into(), "plain".into()), ("P".into(), "pair".into())],
                           vec![(5_000_000, 0, 5_000_000, 10_000_000), (6_000_000, 0, 6_000_000, 10_000_000),
                                (7_000_000, 0, 7_000_000, 10_000_000)], (5.0, 3.0, 0.0));
        assert_eq!(w.cross("A", "plain", &[(0, 5_000_000, 10_000_000, 5_000_000)]), (6.0, 2));
        assert_eq!(segments_crossing(&[(0, 0, 10, 10)], &[(0, 10, 10, 0), (20, 20, 30, 30)]), 1);
    }
}
```

In `native/src/lib.rs`, add `mod pinmap;` to the module list, between `mod judge;` and `mod pockets;`.

Run: `cd native && nice cargo test --release --lib pinmap; cd ..`
Expected: FAIL to compile: `cannot find struct, variant or union type Wires`.

- [ ] **Step 2: The counts in Rust**

Replace `native/src/pinmap.rs` with:

```rust
//! The pin map study's crossing counts (`placemat.pinmap_score`), for the two questions its search asks by the
//! thousand: what a studied net's segments cross among the board's other airwires (`Wires::cross`), and how many times
//! two studied nets' segments cross (`segments_crossing`). Segments arrive in whole nanometres, as Python rounds them,
//! and each segment's candidate wires are taken in wire order, so a weighted sum adds up as Python's does.

use crate::ratsnest::cross_nm;
use std::collections::HashMap;

pub const CELL_NM: i64 = 2_000_000; // pinmap_score.CELL_NM

/// A segment, its ends in whole nanometres.
pub type Seg = (i64, i64, i64, i64);

fn bounds(s: &Seg) -> (i64, i64, i64, i64) {
    (s.0.min(s.2), s.1.min(s.3), s.0.max(s.2), s.1.max(s.3))
}

/// Python's floor division of a coordinate by the cell.
fn cell(v: i64) -> i64 {
    v.div_euclid(CELL_NM)
}

/// pinmap_score.Weights' classes: plain 0, pair 1, impedance 2, plane 3.
pub fn kind_code(kind: &str) -> u8 {
    match kind {
        "pair" => 1,
        "impedance" => 2,
        "plane" => 3,
        _ => 0,
    }
}

pub struct Wires {
    nets: Vec<String>,
    kinds: Vec<u8>,
    segs: Vec<Seg>,
    boxes: Vec<(i64, i64, i64, i64)>,
    grid: HashMap<(i64, i64), Vec<usize>>,
    pair: f64,
    impedance: f64,
    plane: f64,
}

impl Wires {
    /// `wires` (net, crossing class) and `segs` one each, `weights` (pair, impedance, plane).
    pub fn new(wires: Vec<(String, String)>, segs: Vec<Seg>, weights: (f64, f64, f64)) -> Self {
        let mut grid: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
        let boxes: Vec<(i64, i64, i64, i64)> = segs.iter().map(bounds).collect();
        for (k, b) in boxes.iter().enumerate() {
            for cx in cell(b.0)..=cell(b.2) {
                for cy in cell(b.1)..=cell(b.3) {
                    grid.entry((cx, cy)).or_default().push(k);
                }
            }
        }
        Wires {
            nets: wires.iter().map(|(n, _)| n.clone()).collect(),
            kinds: wires.iter().map(|(_, k)| kind_code(k)).collect(),
            segs,
            boxes,
            grid,
            pair: weights.0,
            impedance: weights.1,
            plane: weights.2,
        }
    }

    fn one(&self, k: u8) -> f64 {
        match k {
            1 => self.pair,
            2 => self.impedance,
            _ => 1.0,
        }
    }

    /// `Weights.crossing`.
    fn crossing(&self, a: u8, b: u8) -> f64 {
        if a == 3 || b == 3 {
            return self.plane;
        }
        let (x, y) = (self.one(a), self.one(b));
        if x >= y { x } else { y }
    }

    /// `Background.cross`: (weighted count, count) of the wires of other nets that `segs` cross.
    pub fn cross(&self, net: &str, kind: &str, segs: &[Seg]) -> (f64, i64) {
        let k = kind_code(kind);
        let mut total = 0.0;
        let mut count = 0i64;
        for s in segs {
            let b = bounds(s);
            let mut near: Vec<usize> = Vec::new();
            for cx in cell(b.0)..=cell(b.2) {
                for cy in cell(b.1)..=cell(b.3) {
                    if let Some(v) = self.grid.get(&(cx, cy)) {
                        near.extend_from_slice(v);
                    }
                }
            }
            near.sort_unstable();
            near.dedup();
            for i in near {
                let t = self.boxes[i];
                if t.2 < b.0 || b.2 < t.0 || t.3 < b.1 || b.3 < t.1 || self.nets[i] == net {
                    continue;
                }
                let w = self.segs[i];
                if cross_nm(s.0, s.1, s.2, s.3, w.0, w.1, w.2, w.3) {
                    total += self.crossing(k, self.kinds[i]);
                    count += 1;
                }
            }
        }
        (total, count)
    }
}

/// `pinmap_score.segments_crossing`: how many times two nets' segments cross.
pub fn segments_crossing(a: &[Seg], b: &[Seg]) -> i64 {
    let mut n = 0i64;
    for s in a {
        let sb = bounds(s);
        for t in b {
            let tb = bounds(t);
            if sb.2 < tb.0 || tb.2 < sb.0 || sb.3 < tb.1 || tb.3 < sb.1 {
                continue;
            }
            if cross_nm(s.0, s.1, s.2, s.3, t.0, t.1, t.2, t.3) {
                n += 1;
            }
        }
    }
    n
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_wire_across_a_segment_counts_and_its_own_net_does_not() {
        let w = Wires::new(vec![("X".into(), "plain".into()), ("A".into(), "plain".into()), ("P".into(), "pair".into())],
                           vec![(5_000_000, 0, 5_000_000, 10_000_000), (6_000_000, 0, 6_000_000, 10_000_000),
                                (7_000_000, 0, 7_000_000, 10_000_000)], (5.0, 3.0, 0.0));
        assert_eq!(w.cross("A", "plain", &[(0, 5_000_000, 10_000_000, 5_000_000)]), (6.0, 2));
        assert_eq!(segments_crossing(&[(0, 0, 10, 10)], &[(0, 10, 10, 0), (20, 20, 30, 30)]), 1);
    }
}
```

Run: `cd native && nice cargo test --release --lib pinmap; cd ..`
Expected: PASS (1 test).

- [ ] **Step 3: Expose them to Python**

In `native/src/lib.rs`, before `/// The occupancy's placed ratsnest, mirrored for \`leaf_costs\``, add:

```rust
/// The pin map study's other airwires (native/src/pinmap.rs): what a studied net's segments cross.
#[pyclass]
struct NativeWires {
    inner: pinmap::Wires,
}

#[pymethods]
impl NativeWires {
    #[new]
    fn new(wires: Vec<(String, String)>, segs: Vec<pinmap::Seg>, weights: (f64, f64, f64)) -> Self {
        NativeWires { inner: pinmap::Wires::new(wires, segs, weights) }
    }

    /// (weighted count, count) of the crossings of `segs` (a net of crossing class `kind`) with the other nets' wires.
    fn cross(&self, net: &str, kind: &str, segs: Vec<pinmap::Seg>) -> (f64, i64) {
        self.inner.cross(net, kind, &segs)
    }
}

/// How many times two studied nets' segments cross (pinmap_score.segments_crossing).
#[pyfunction]
fn segments_crossing(a: Vec<pinmap::Seg>, b: Vec<pinmap::Seg>) -> i64 {
    pinmap::segments_crossing(&a, &b)
}

```

and after `    m.add_class::<NativeRatsnest>()?;` add:

```rust
    m.add_class::<NativeWires>()?;
    m.add_function(wrap_pyfunction!(segments_crossing, m)?)?;
```

- [ ] **Step 4: Write the parity test**

Create `tests/test_native_pinmap.py`:

```python
"""The native pin map crossing counts are pinmap_score's: the same counts and the same weighted sums, in wire order."""
import random

import pytest

native = pytest.importorskip("placemat_native")
if not hasattr(native, "NativeWires"):
    pytest.skip("the native module was built before the pin map study", allow_module_level=True)

from placemat import geometry  # noqa: E402
from placemat.pinmap_input import Wire  # noqa: E402
from placemat.pinmap_score import Background, Weights, _segments, segments_crossing  # noqa: E402


def _python(fn):
    was = geometry._native
    geometry._native = None
    try:
        return fn()
    finally:
        geometry._native = was


@pytest.mark.parametrize("seed", range(20))
def test_the_counts_are_the_pythons(seed):
    rng = random.Random(seed)
    kinds = ("plain", "pair", "impedance", "plane")
    pt = lambda: (round(rng.uniform(-5, 30), 3), round(rng.uniform(-5, 30), 3))
    wires = [Wire(rng.choice("ABCDE"), rng.choice(kinds), pt(), pt()) for _ in range(rng.randint(1, 80))]
    w = Weights(pair=5.0, impedance=3.0, plane=rng.choice((0.0, 0.5)))
    paths = [_segments([tuple(pt() for _ in range(rng.randint(2, 5)))]) for _ in range(10)]
    py, nat = _python(lambda: Background(wires, w)), Background(wires, w)
    assert py.mirror is None and nat.mirror is not None
    for segs in paths:
        net, kind = rng.choice("ABCDEX"), rng.choice(kinds)
        assert nat.cross(net, kind, segs) == py.cross(net, kind, segs)
    assert segments_crossing(paths[0], paths[1]) == _python(lambda: segments_crossing(paths[0], paths[1]))
```

- [ ] **Step 5: Build the module and watch the parity test fail**

Run: `uv pip install -e ".[native]"` then `.venv/bin/python -m pytest tests/test_native_pinmap.py -q -n 2`
Expected: FAIL with `AttributeError: 'Background' object has no attribute 'mirror'` (Python does not ask the native module yet).

- [ ] **Step 6: Python asks the native module**

In `src/placemat/pinmap_score.py`:

After `from dataclasses import dataclass` add:

```python

from . import geometry as _geometry
```

Replace `Background`'s docstring ending `out when \`score.crossing_plane\` is 0, as it weighs nothing."""` with:

```python
    out when `score.crossing_plane` is 0, as it weighs nothing. The native module answers it when it has `NativeWires`,
    the same way and in the same order."""
```

Replace:

```python
        self.segs = _segments([(w.a, w.b) for w in self.wires])
        self.grid: dict = {}
```

with:

```python
        self.segs = _segments([(w.a, w.b) for w in self.wires])
        native = _geometry._native
        self.mirror = None
        if native is not None and hasattr(native, "NativeWires"):
            self.mirror = native.NativeWires([(w.net, w.kind) for w in self.wires], [s[:4] for s in self.segs],
                                             (weights.pair, weights.impedance, weights.plane))
            return
        self.grid: dict = {}
```

Replace:

```python
    def cross(self, net: str, kind: str, segs) -> tuple:
        total, count = 0.0, 0
```

with:

```python
    def cross(self, net: str, kind: str, segs) -> tuple:
        if self.mirror is not None:
            return self.mirror.cross(net, kind, [s[:4] for s in segs])
        total, count = 0.0, 0
```

In `segments_crossing`, make the first lines after the docstring:

```python
    native = _geometry._native
    if native is not None and hasattr(native, "segments_crossing"):
        return native.segments_crossing([s[:4] for s in a], [s[:4] for s in b])
```

- [ ] **Step 7: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_native_pinmap.py tests/test_pinmap_score.py tests/test_pinmap_search.py tests/test_pinmap_joint.py tests/test_pinmap_finding.py -q -n 2` and `cd native && cargo clippy --release -- -D warnings; cd ..`
Expected: PASS, and clippy clean.

- [ ] **Step 8: Measure again, and keep the port only if it pays**

Run Task 13's Step 3 again (the same lines), appending to `$SCRATCH/pinmap-bench.txt` under a line `native:`.
If the seconds a part at the chosen effort did not fall, revert this task (`git checkout -- native src/placemat/pinmap_score.py && rm native/src/pinmap.rs tests/test_native_pinmap.py`) and note `native: no gain` in the file. Otherwise:

```bash
git add native/src/pinmap.rs native/src/lib.rs src/placemat/pinmap_score.py tests/test_native_pinmap.py
{ echo "Native: the pin map study's crossing counts"; echo; grep -E "^(mcu|moves|native)" $SCRATCH/pinmap-bench.txt | tail -8; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 15: The defaults from the bench

**Files:**
- Modify: `src/placemat/settings.py` (the defaults of `pins_anneal_moves`, `pins_seeds`, `pins_budget_ms`)
- Modify: `tests/test_pinmap_settings.py` (the defaults it asserts)
- Modify: `skills/placemat/references/api.md` (the generated settings table)
- Modify: `tests/slow_tests.txt`
- Test: `tests/test_pinmap_real.py` (from Task 13)

**Interfaces:**
- Consumes: `$SCRATCH/pinmap-bench.txt` (Task 13, and Task 14 if it ran): the effort line and the seconds a part at that effort with the module that will ship (native when Task 14 was kept).
- Produces: the shipped defaults.

- [ ] **Step 1: Set the effort and the budget**

From the last measurement of the chosen effort: `M` and `N` are its moves and seeds; `B` is its seconds a part times 1.5, in milliseconds, rounded up to a multiple of 50 (the 1.5 is headroom for a slower machine than this one; the budget must not cut the reference board short). For example, an effort measured at 0.30 s a part gives `B = 450`.

In `src/placemat/settings.py`, replace the first argument of `S(...)` in `pins_anneal_moves: int = S(500, "count", ...)` with `M`, in `pins_seeds: int = S(4, "count", ...)` with `N` and in `pins_budget_ms: int = S(400, "ms", ...)` with `B`; nothing else in those lines changes.

In `tests/test_pinmap_settings.py`, in `test_every_pins_setting_has_its_default`, change the expected `pins_seeds`, `pins_anneal_moves` and `pins_budget_ms` to the same three numbers.

Regenerate the api.md table with Task 1's Step 4 command.

- [ ] **Step 2: Run the real-board test to watch it pass**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_pinmap_real.py -q`
Expected: PASS: the best map beats the present one, the clock did not run out, the second study is reused, and the board file and every part's place are as read.

If it fails on `budget_out`, the budget is too tight for this machine's load: take the measurement again (Task 13 Step 3 for the chosen effort only) and recompute `B`. Do not raise the budget past what the measurement supports.

- [ ] **Step 3: The real-board test is a slow one**

Add to `tests/slow_tests.txt`:

```
tests/test_pinmap_real.py::test_on_a_real_board_the_best_map_beats_the_present_one_inside_its_budget_is_reused_and_nothing_moves
```

Run: `.venv/bin/python -m pytest tests/test_pinmap_settings.py tests/test_settings_docs.py -q -n 2`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/placemat/settings.py tests/test_pinmap_settings.py skills/placemat/references/api.md tests/slow_tests.txt tests/test_pinmap_real.py
{ echo "Pin map study: its search effort and budget from the bench"; echo; grep -E "^(effort|native)" $SCRATCH/pinmap-bench.txt; grep -E "^moves" $SCRATCH/pinmap-bench.txt | tail -5; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 16: Docs - capture.md, api.md, the skill, migration

**Files:**
- Modify: `skills/placemat/references/capture.md` (the annotation table; a section "Pin pools")
- Modify: `skills/placemat/references/api.md` (the findings table; a section "## The pin map study"; a sentence in "Exploring a placement")
- Modify: `skills/placemat/SKILL.md` (one bullet in "Pin assignments are a layout lever")
- Modify: `skills/placemat/references/migration.md` (a "### New" entry under "## Unreleased")

**Interfaces:**
- Consumes: the behaviour of Tasks 1-15 as built; the settings table is already generated (Tasks 1 and 15), the suggestions case row is in (Task 8).
- Produces: documentation only.

- [ ] **Step 1: capture.md - the annotations**

In `skills/placemat/references/capture.md`, after the table row that begins `| \`Pm.SensesAt\` |`, add:

```
| `Pm.PinPool` | the general-purpose pins, by pad number or by pin name, ranges as `3-8` or `GPIO1-GPIO10`: `GPIO0-GPIO21, GPIO33-GPIO48` | the pin map study |
| `Pm.PinFixed` | pins of the pool that keep their net (straps, a crystal, in-package flash): `GPIO0, GPIO3` | the pin map study |
| `Pm.PinAllow` | `NET:pins; NET:pins`: a net may stand only on these pins (an ADC input on the ADC pins) | the pin map study |
| `Pm.PinDeny` | `NET:pins; ...`: a net may not stand on these pins | the pin map study |
| `Pm.PinGroup` | `name:pins; ...`: pins that move as one block, keeping their order | the pin map study |
```

Before `## Sources and limits`, add:

```markdown
### Pin pools

A part whose pins are general purpose (an MCU's GPIOs) says which in its
capture, and placemat studies whether another assignment of its nets to those
pins would cross less on every run and preview (the pin map study; api.md).
Each annotation is a datasheet fact, cited in a comment beside it as the
other `Pm.*` keys are:

    annotations = {
        "Pm.PinPool": "GPIO0-GPIO21, GPIO33-GPIO48",   # datasheet, pin description table: general-purpose IO
        "Pm.PinFixed": "GPIO0, GPIO3, GPIO45, GPIO46",  # datasheet, strapping pins
        "Pm.PinAllow": "VSENSE:GPIO1-GPIO10",           # datasheet, ADC1 channels
        "Pm.PinGroup": "lcd:GPIO10-GPIO17",             # datasheet, parallel bus: consecutive pins in order
    },

- Pins are named by pad number or by pin name, as `PadRef` names them; a range
  is `3-8` or `GPIO1-GPIO10` (a common name and a number, either way round).
  Pin names need the part's symbol among the board's libraries; without it,
  name pins by number.
- `Pm.PinPool` lists the pins a net may move among; a part without one is not
  studied. A net on a pin outside the pool, or on a `Pm.PinFixed` pin, stays;
  so does a net on two pins and a plane's net. A pool pin with no net, or a net
  that reaches nothing else, is free.
- `Pm.PinAllow` and `Pm.PinDeny` name nets as the capture does; the last part
  of a net's path matches, as for `Pm.KeepOut`. Entries are separated by `;`.
- `Pm.PinGroup` pins move as one block to another run of consecutive pins of
  the pool, in the order the pool lists them, keeping their order.
- An entry that names a pin the part does not have, or a net it does not
  carry, is a `setup.pins` finding naming it, and the study runs without that
  entry. Constraints that leave a net no pin stop the part's study, with a
  `setup.pins` finding naming the net.

placemat never writes the map: it is a capture change, made here, with the
datasheet table that allows each move named in the comment beside it.
```

- [ ] **Step 2: api.md - the finding, the study, the explore line**

In `skills/placemat/references/api.md`:

In the findings table, replace the end of the `setup` warning row:

```
a `[route] pair_layers` entry that names no pair or a layer the board lacks: `setup.pair_layers`) | warning | the script is incomplete or wrong |
```

with:

```
a `[route] pair_layers` entry that names no pair or a layer the board lacks: `setup.pair_layers`, a pin annotation the pin map study runs without: `setup.pins`) | warning | the script is incomplete or wrong |
```

After the row `| \`needs\` | notice | ... |`, add:

```
| `pins` (`pins.remap`) | notice | the pin map study found an assignment of a part's nets to its pool pins that saves at least `pins.gain_min` of the present total; nothing is changed |
```

Before `## Findings and severities`, add:

```markdown
## The pin map study

For each part whose capture gives it a `Pm.PinPool` (capture.md, "Pin pools"),
placemat measures how much a better assignment of its movable nets to its pool
pins would save, at its present rotation and at each turn in `pins.rotations`
(and on the other face with `pins.faces` where its declaration allows
`Face.EITHER`). It runs once at the end of every run and preview, on the
finished board, never inside the placement search, and writes nothing.

**The score.** Built on placemat's ratsnest. The nets come from the pads alone:
a laid board's tracks, vias and pours are ignored, so a routed net keeps its
airwire and a first preview and a laid board are scored alike. A pin's airwire
leaves along its outward normal to a point `pins.exit_mm` past the courtyard's
box, then goes the shorter way round the box to its target; a net of several
pads is scored on its minimum spanning tree; a net through a two-pad series
part is followed to the far net (`pins.follow_series`). A crossing counts 1,
`pins.pair_weight` for a differential pair's airwire, `pins.impedance_weight`
for a net whose class names a KiCad tuning profile, `score.crossing_plane` for
a plane's or a free net's. The total is the weighted crossings against every
other airwire and among the studied nets, plus `pins.length_weight` times the
airwire length in mm, plus `pins.bend_weight` times the summed bend (the angle
between a pin's outward normal and the bearing to its target).

**The search.** Per pose, a first map by minimum-cost matching (each group of
`Pm.PinGroup` on the run of pins nearest its targets), then `pins.seeds` local
searches of `pins.anneal_moves` moves and swaps under annealing. Parts whose
movable nets meet are studied together, their poses in combination, at most
`pins.joint_combinations`. Seeds are fixed and ties go to the lower pin, so a
board gives the same map twice; a study stops at `pins.budget_ms` a part with
the best found and says so. What a study reads is digested and kept in
`.placemat/pinmap/<script>.json`; a run or a preview of an unchanged board
reuses it. `run.json`'s `metrics.pin_study` is `{seconds, reused, groups,
parts}` and run and preview print `pins  <parts>, ...`.

**The finding.** `pins.remap`, a notice, when the best pose saves at least
`pins.gain_min` of the present total: "U1: a pin map with 88 fewer weighted
crossings exists at its present rotation; at 90 degrees, 112 fewer". Facts:
`ref`, `refs`, `at`, `present` and per pose in `rotations` (the present pose
first) `total`, `against` and `among` (crossing counts), `weighted`,
`length_mm`, `bend_deg`, `turns` (`ref`, `turn_deg`, `rotation_deg`, `face`,
`flip`), `map` (`ref`, `net`, `from` and `to` as `{pin, name}`), `routed` (the
moved nets with copper on the board now: a remap means routing them again) and
`paths` (each studied airwire's points after the map); `best` (the index of
the best pose), `routed`, `before` (the airwires now), `held` (nets a
constraint keeps: `fixed`, or `allow` where `Pm.PinAllow` and `Pm.PinDeny`
leave one pin), `searched`, `of`, `budget_out`, `first_map` (false when the
budget ran out before a first map, which the sentence says) and `budget_ms`.

**The suggestion** is advice (`how: "advice"`, lever `pins`, no edit): the
best map with the turn to declare when another pose wins, and the best at the
present pose. `placemat apply <id>` refuses it: make the map in the `.zen` and
the turn in the script. In the studio its Try draws the airwires before
(dashed) and after (solid) and lists the map. `placemat apply <id> --search`
studies the suggestion's parts again on the board as the last run placed it
with `pins.probe_budget_ms` a part and keeps a better map as `<id>.1`.
```

In "## Exploring a placement", after the sentence ending `` `metrics.explore` records it.`` add:

```markdown
With pin pools on the board, the pin map study runs on the best `pins.explore_top`
variants, and a line per studied part gives each one's weighted crossings now
and after remapping (`pin map, seed 3 at 120.4 mm: U1 40 -> 22 weighted
crossings after remapping`; `metrics.explore.pin_maps`). The variants stay
ranked by run score: the study's numbers are beside the score, not in it.
```

- [ ] **Step 3: SKILL.md - one bullet**

In `skills/placemat/SKILL.md`, in "## Pin assignments are a layout lever", after the bullet that begins `- swap a group as a group`, add:

```markdown
- a part whose capture gives it a `Pm.PinPool` is studied on every run and
  preview: a `pins.remap` notice gives a map (and a turn) that saves
  crossings; take it as a candidate, checked against the datasheet as above
  (capture.md, "Pin pools").
```

- [ ] **Step 4: migration.md - the entry**

In `skills/placemat/references/migration.md`, under `## Unreleased` (create the section above the newest `## To ...` if it is not there), add a `### New` subsection above any `### Fixed`:

```markdown
### New

- **The pin map study.** A part whose capture annotates its general-purpose pins (`Pm.PinPool`, with `Pm.PinFixed`,
  `Pm.PinAllow`, `Pm.PinDeny` and `Pm.PinGroup`; capture.md, "Pin pools") is studied at the end of every run and
  preview: placemat looks for an assignment of its nets to those pins, at its present rotation and at each turn in
  `[pins] rotations`, that saves weighted ratsnest crossings, airwire and turning, and says so in a `pins.remap` notice
  whose suggestion carries the map and the turn. Nothing is written: the map is a capture change and the turn a layout
  one. An annotation entry naming a pin or a net the part lacks is a `setup.pins` warning. An explore reports the study
  of its best variants beside their scores; `placemat apply <id> --search` studies again with a longer budget. Settings:
  `[pins]`. Nothing in a layout script changes; the first run after updating replays no steps (the findings' schemas
  changed).
```

- [ ] **Step 5: Check the docs**

Run: `.venv/bin/python -m pytest tests/test_settings_docs.py tests/test_suggestion_cases.py -q -n 2`
Expected: PASS.

Run: `grep -nP "[\x{2013}\x{2014}\x{2192}\x{2018}\x{2019}\x{201C}\x{201D}\x{2026}]" skills/placemat/SKILL.md skills/placemat/references/capture.md skills/placemat/references/api.md skills/placemat/references/migration.md src/placemat/pinmap*.py`
Expected: no line the change added (ASCII only).

- [ ] **Step 6: Commit**

```bash
git add skills/placemat/SKILL.md skills/placemat/references/capture.md skills/placemat/references/api.md skills/placemat/references/migration.md
git commit -m "Docs: the pin map study, its annotations, finding and settings"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

- [ ] **Step 7: The whole suite**

Run: `.venv/bin/python -m pytest -n 2 -q 2>&1 | tail -5`, then `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest -n 2 -q --full tests/test_pinmap_real.py tests/test_pinmap_netclass.py`
Expected: no failures.

---

## Self-Review

Done while writing; recorded here for the reviewer.

**Spec coverage.** Constraints (pool, fixed, allow, deny, group; number, name, range; `setup.pins` for a pin or net the part lacks; no legal map): Task 2, Task 6 (`no_legal_map`), Task 8. Scored as unrouted: Task 4 (`board_nets(pads, copper=())`), Task 5 (the routed-board test). Airwires round the body: Task 3. Multi-pad nets on the tree: Task 5. Series parts: Task 4. Weights (pair, impedance, plane): Tasks 4-5. Bends: Tasks 3, 5, 6 (the diagonal test). Total: Task 5. The search (matching seed, moves and swaps, groups whole, annealing, seeds, determinism, ties by pin number, rotations, faces): Task 6. Joint study and its cap: Tasks 6-7. Speed (budget per part, once after placement, digest reuse, incremental counts, native if the bench says so): Tasks 5, 6, 9, 13-15. The finding, its facts (moved nets with copper now included) and its sentence: Task 8. The suggestion (lever `pins`, map and rotation, `try` previews nothing): Tasks 8 and 12. Studio before/after drawing: Task 12. The probe with a larger budget: Task 11. Explore: Task 10. Errors (no pool, no legal map, budget too short): Tasks 2, 6, 8. Testing list: known optimal map (Task 6), each constraint (Task 6), group whole and in order (Task 6), joint beats one at a time (Task 7), body obstacle (Task 6), bends with and without 45 (Task 6), determinism (Task 6), speed and reuse on the reference board (Tasks 13, 15), routed board (Task 5), real fixture board beats the present map and nothing moves (Tasks 13, 15). Settings with defaults and table lines: Tasks 1, 15. Docs: Task 16.

**Placeholders.** The only values not fixed in this plan are the three defaults Task 15 takes from the bench (`pins_anneal_moves`, `pins_seeds`, `pins_budget_ms`), as the spec asks ("default set by the bench"); the measurement, the rule and the edit are spelled out. Task 14 runs only on the bench's word.

**Type consistency.** Names checked across tasks: `Problem.facts()`, `PinRules`, `PartPins.present/movable/allowed/free/groups/windows/held`, `read_rules`, `part_pins`, `natural`; `Pose`, `Exit`, `exit_of`, `route`, `bend`, `outward`, `through`; `PlacedPad`, `PlacedPart`, `StudyInput.part`, `StudyNet.ends/fixed/joined/kind/via/far`, `Wire`, `build`, `placed_from_geometry`, `net_kind`; `Weights.of`, `Breakdown.to_json`, `Background.cross(net, kind, segs)`, `_segments`, `segments_crossing`, `Scorer.exit/wires/single/pair/total`, `Tally.delta/apply/value/assign`; `Clock`, `poses_of`, `hungarian`, `first_map`, `anneal`, `study_group`, `GroupResult.refs/present/present_assign/results/searched/of/budget_out/first_map/problems`, `PoseResult.poses/breakdown/assign`, `linked_groups`, `study`; `pinmap.has_pools/copper_nets/group_facts/digest/study_findings/geometry_findings/study_line/placed_from_plan/plan_findings/plan_summary/longer_advice`; `suggestions.pin_advice/pin_advice_text`; `finding_text.pose_text`; `Board.pin_study/pin_study_cache`, `Plan.pin_study`, `Occupancy.courtyard_box`; `explore._pin_maps/pin_map_lines`; `cli._pin_search`. The code in Tasks 2-12 was run while planning against a copy of the tree (all 66 of the study's tests and the touched suites passing; the real-board test failing on its budget as Task 13 expects).

**Review Focus.** Each of the five lines has its test in the task named there.
