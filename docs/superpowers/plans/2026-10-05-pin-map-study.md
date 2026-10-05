# Pin Map Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a part whose capture gives it a `Pm.PinPool`, placemat measures how many weighted ratsnest crossings a better assignment of nets to its pins would save, at its present rotation and at each turn in `pins.rotations`, and says so in a `pins.remap` notice whose advice suggestion carries the map and the turn; an explore reports the same study of its best variants beside their scores. Nothing is written to the board or the capture.

**Architecture:** The study's hot path is a native core: `native/src/pinmap.rs` (crossing counts against a 2 mm grid of the other airwires, the weighted score with per-net and per-pair memos so a move recounts only the nets it touches, and the move/swap/group-move annealing search with its seeds and clock) over `native/src/pinmap_geom.rs` (exit points, the way round the courtyard box, bends, poses), exposed as `placemat_native.pinmap_search`. It takes the study as plain arrays (parts, pins, nets with their fixed anchors and end slots, the other airwires in nm, movables with their allowed pins, groups with their windows, pose combinations) and returns the best map per pose with its tallies and airwires. `pinmap_core` builds those arrays and is the one entry point, picking the native core when `geometry.native_status()` has the module in use and else its Python twin (`pinmap_geom.py`, `pinmap_twin.py`), which gives the same answers bit for bit. Around it, in Python: `pinmap_rules` (the annotations), `pinmap_input` (the studied parts, their nets and the other airwires from the pads alone, `ratsnest.board_nets(pads, copper=())`), and `pinmap` (findings, facts, the digest cache), called once at the end of a resolve, by the explore on its best variants, and by `placemat apply <id> --search`. The finding renders in `finding_text`, its suggestion is a new `how: "advice"` kind with an `advice` record and no edit, and the studio draws the airwires before and after from the finding's facts.

**Tech Stack:** Python 3.12; Rust in `native/` (pyo3 0.29, built by `uv pip install -e ".[native]"`, used only when its version is placemat's: `geometry.native_status()`); pcbnew (KiCad 10.0.6 in the checkout's venv: `NETCLASS.GetTuningProfile`); pytest with xdist; node for the studio page tests.

**Spec:** `docs/superpowers/specs/2026-10-05-pin-map-study-design.md` (approved 2026-10-05; binding). Read it with this plan.

## Global Constraints

- The spec's settings, each with a default and a line in api.md's generated settings table: `pins.exit_mm`, `pins.follow_series`, `pins.pair_weight`, `pins.impedance_weight`, `pins.length_weight`, `pins.bend_weight`, `pins.rotations` (default 0, 90, 180, 270), `pins.seeds`, `pins.budget_ms` (provisional 400 until Task 6 sets it, with `pins.anneal_moves` and `pins.seeds`, from the bench), `pins.faces`, `pins.gain_min`, `pins.explore_top`. Tunables the plan adds because a number must not be a literal: `pins.anneal_moves`, `pins.anneal_start`, `pins.anneal_end`, `pins.joint_combinations` (the spec's cap on a joint study's rotation combinations) and `pins.probe_budget_ms` (the probe's longer budget). A crossing with a plane's or a free net's airwire weighs the existing `score.crossing_plane`.
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
- The native core is the primary path; the Python twin is the fallback where the native module is not in use, and both give the same maps and tallies on the same arrays (Task 7's tests). Native code follows the module's existing patterns: logic in `native/src/<name>.rs`, a thin `#[pyfunction]` in `lib.rs`, CPython's arithmetic copied where Python's answer must be met (`exact::hypot`, `clean9`, plain sums, CPython's `radians`/`degrees`), Rust unit tests with `nice cargo test --release`, and no new clippy warning in the pin map files.
- `SCRATCH=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad` is exported in the shell that runs the plan.

## Review Focus

Inputs the spec implies and no task's own feature tests reach, most likely to bite first. Each has its test in the task named.

1. A net on two pins of the studied part (two pins tied, a power net written into the pool): it stays, its pins are offered to no other net, and it never appears in a map. Tests: Task 2 (`test_a_net_on_two_pins_of_the_pool_stays_where_it_is`), Task 9 (`test_a_net_on_two_pins_of_the_part_stays_and_is_not_in_the_map`).
2. Annotations that name pins by name on a board whose pin names were not read (the part's symbol is not among the generator inputs): one `setup.pins` per entry saying the names were not read, not one per name of a range; pad numbers still read. Test: Task 2 (`test_names_on_a_part_whose_pin_names_were_not_read_are_one_problem_per_entry_and_numbers_still_read`).
3. `pins.rotations` written loosely (360, -90, a turn twice, 0 left out): the present pose is studied first and each turn once. Test: Task 5 (`test_the_present_pose_comes_first_and_each_turn_is_studied_once_however_the_turns_are_written`).
4. A part standing off-axis (45 degrees) or with its pins under its body (a BGA): it is studied without error, each pin leaving by the box side it is nearest, and the poses are named from where it stands. Test: Task 9 (`test_a_part_at_45_degrees_with_its_pins_under_its_body_is_studied_and_its_poses_named_from_where_it_stands`).
5. A target pad under the studied part's body (a part on the other face beneath it): its airwire goes straight from the exit point, not round the body. Tests: Task 4 (the Rust `a_target_in_sight_is_straight_and_one_behind_goes_round_the_shorter_way`, its third case) and Task 7 (`test_a_target_inside_the_body_is_reached_straight`).

## File Structure

New, one responsibility each:

- `src/placemat/pinmap_rules.py` - pure: the five annotations read into `PinRules` (pad numbers, pool order kept), `Problem` records for what is left out, and `part_pins` -> `PartPins` (what moves, where it may go, what is held, group windows).
- `src/placemat/pinmap_input.py` - the study's input as data: `PlacedPad`, `PlacedPart`, `Pin`, `StudiedPart`, `StudyNet`, `Wire`, `StudyInput`; `build` (pads alone, series parts followed, crossing classes, each pin's `outward` normal) and `placed_from_geometry`.
- `native/src/pinmap_geom.rs` - the airwire model in Rust: `Pose`, `Exit`, `exit_of`, `through`, `round_body`, `route`, `length`, `bend`.
- `native/src/pinmap.rs` - the native core: background grid, segment crossings, `Scorer` with its memos, `Tally`, `hungarian`, first map, the proposer, `anneal`, `search`; SplitMix64 and the clock.
- `src/placemat/pinmap_core.py` - the core's arrays (`Problem`, `problem_of`), poses, parameters, the one entry point (`search`: native or twin), `study_group`, and from Task 8 `linked_groups` and `study`.
- `src/placemat/pinmap_geom.py`, `src/placemat/pinmap_twin.py` - the Python twin of the two Rust files, line for line.
- `src/placemat/pinmap.py` - the edge to placemat: facts, digest and cache, `study_findings`, `geometry_findings`, `placed_from_plan`, `plan_findings`, `study_line`, `plan_summary`, `longer_advice`.
- `tests/pinmap_boards.py` - synthetic placed boards for the study's tests.
- `fixtures/pinmap/reference.json`, `fixtures/pinmap_bench.py` - the reference board (its annotations live only here) and the bench.

Modified:

- `settings.py` (the `[pins]` section), `reuse.py` (`pins_` settings change no placement).
- `board_geometry.py` (`NetClass.tuning_profile`), `kicad/read.py` (read it).
- `native/src/lib.rs` (`mod pinmap_geom;`, `mod pinmap;`, `pinmap_search`).
- `findings.py` (kind `pins`, causes `pins.remap`, `setup.pins`), `finding_text.py` (their sentences, `pose_text`, subjects), `suggestions.py` (`advice` on `Pick` and `Suggestion`, `how: "advice"`, the builder, binding and apply).
- `occupancy.py` (`courtyard_box`), `layout.py` (`Plan.pin_study`, `Board.pin_study`, `Board.pin_study_cache`, `_report_pin_maps`), `runner.py` (the cache path, the record and the console line), `explore.py` (`BoardFactory`, `_pin_maps`, `pin_map_lines`), `previewer.py` (the console line), `cli.py` (`_pin_search`).
- `studio_page.html` (the advice suggestion's Try, its map and the airwires).
- Docs: `skills/placemat/references/capture.md`, `api.md`, `migration.md`, `skills/placemat/SKILL.md`.
- Tests touched: `tests/test_finding_kinds.py`, `tests/test_suggestion_cases.py`, `tests/test_studio_page.py`, `tests/slow_tests.txt`.

Task order: 1 settings; 2 constraints; 3 the input; 4 the airwire model in Rust; 5 the native core and the entry point; 6 bench the native core and set the defaults (or stop); 7 the Python twin and its agreement with the native core; 8 joint study; 9 finding and suggestion; 10 run and preview; 11 explore; 12 longer study; 13 studio; 14 docs.

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

### Task 3: The study's input from the pads alone

What the core (Task 5) is fed, as data. A laid board is scored as unrouted - its nets are built from the pads alone, `board_nets(pads, copper=())` - so a routed net keeps its airwire (the score's half of that test is in Task 5). Series parts are followed; each net gets its crossing class, a controlled impedance read from the net class's KiCad 10 tuning profile; each pin its outward normal. This stays Python: it runs once per study, not in the search.

**Files:**
- Modify: `src/placemat/board_geometry.py` (`NetClass`)
- Modify: `src/placemat/kicad/read.py` (`_netclasses`)
- Create: `src/placemat/pinmap_input.py`
- Create: `tests/pinmap_boards.py`
- Test: `tests/test_pinmap_input.py`, `tests/test_pinmap_netclass.py`
- Modify: `tests/slow_tests.txt`

**Interfaces:**
- Consumes: `ratsnest.board_nets(pads, copper=())` (pads as `(ref, number, net, layers, outlines, box, anchor)`), `ratsnest.mst(net, anchors, joined)`, `ratsnest.Anchor`; Task 2's `read_rules`, `part_pins`, `natural`; `Settings` (Task 1) in the test helpers.
- Produces:
  - `NetClass.tuning_profile: str = ""`.
  - `PlacedPad(ref, number, net, layers, outlines, box, anchor, no_connect=False)`, `PlacedPart(ref, courtyard, rotation, face, may_flip=False, fields={})`.
  - `Pin(number, name, x, y, nx, ny)`, `StudiedPart(ref, cx, cy, hw, hh, rotation, face, may_flip, pins, slots)` with `.pin(number)`, `StudyNet(net, kind, fixed, joined, ends, via="", far="")`, `Wire(net, kind, a, b)`, `StudyInput(parts, nets, background, names)` with `.part(ref)`.
  - `KINDS = ("plain", "impedance", "pair", "plane")`, `net_kind(net, quiet, partners, netclasses) -> str`, `outward(x, y, hw, hh) -> (nx, ny)` (the side of the courtyard box a pin is nearest; ties go east, south, west, north).
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
from placemat.pinmap_input import build, net_kind, outward, placed_from_geometry
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


def test_a_pin_faces_the_side_of_the_box_it_is_nearest_ties_going_east_south_west_north():
    assert outward(1.7, 0.2, 2.0, 2.0) == (1.0, 0.0)
    assert outward(0.2, 1.7, 2.0, 2.0) == (0.0, 1.0)
    assert outward(-1.7, 0.0, 2.0, 2.0) == (-1.0, 0.0)
    assert outward(0.0, -1.7, 2.0, 2.0) == (0.0, -1.0)
    assert outward(1.7, 1.7, 2.0, 2.0) == (1.0, 0.0)                  # a corner pin: east before south
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


_SIDES = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))     # east, south, west, north: the order a tie is broken in


def outward(x: float, y: float, hw: float, hh: float) -> tuple:
    """The outward normal of the box side nearest a pin at (x, y) in the part's frame, the box being (-hw, -hh) to (hw, hh);
    ties go east, south, west, north."""
    gaps = (hw - x, hh - y, x + hw, y + hh)
    return _SIDES[min(range(4), key=lambda k: (gaps[k], k))]


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
Expected: PASS (6 and 1 tests).

- [ ] **Step 7: Commit**

```bash
git add src/placemat/board_geometry.py src/placemat/kicad/read.py src/placemat/pinmap_input.py tests/pinmap_boards.py tests/test_pinmap_input.py tests/test_pinmap_netclass.py tests/slow_tests.txt
git commit -m "Pin map study: its input from the pads alone, series parts followed, a net class's tuning profile read"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 4: The airwire model, in Rust

**Decision: the airwire model goes into the native core.** Where the time goes, measured while planning on the reference board (Task 6's fixture; a QFN-56 with 23 movable nets) with the whole study in Python: 1.3 s for 4 poses of 4 seeds of 200 moves, of which the crossing counts (background and net against net) took about 70%, the minimum spanning trees and the bookkeeping most of the rest, and the airwire geometry (exit points, the way round the body, bends) about 4%. With the counts moved to Rust, every move that puts a net on a pin it has not stood on asks the geometry for that net's new airwires inside the search's inner loop; left in Python, each of those thousands of questions would be a call from Rust back into Python, costing more than the geometry itself. So the model is written in Rust here, for the core (Task 5), and its Python twin comes with the core's twin (Task 7). The pin's outward normal is input, not search: it stays in Python (`pinmap_input.outward`, Task 3).

**Files:**
- Create: `native/src/pinmap_geom.rs`
- Modify: `native/src/lib.rs` (`mod pinmap_geom;`)
- Test: the Rust unit tests in `native/src/pinmap_geom.rs`

**Interfaces:**
- Consumes: `crate::exact::{clean9, hypot}` (CPython's `round(v, 9)` as `geometry._clean` takes it, and CPython's `math.hypot`, bit for bit).
- Produces (Rust, `pub`): `Pose { cx, cy, turn, flip }` with `Pose::new`, `vector`, `to_board`, `to_local`; `Exit { at, local, normal, side, pose, hw, hh, margin }`; `exit_of(pose, x, y, normal, hw, hh, margin) -> Exit`; `through(p, q, hw, hh) -> bool`; `length(&[(f64, f64)]) -> f64`; `round_body(&Exit, target) -> Vec<(f64, f64)>`; `End::{Exit, Point}`; `route(&End, &End) -> Vec<(f64, f64)>`; `bend(normal, at, target) -> f64`.

Exactness rules, which the Python twin (Task 7) follows the other way round so the two agree to the last bit: positions go through `clean9` where `geometry._clean` rounds; distances use `exact::hypot`; a turn in radians is `x * (pi / 180)` (CPython's `radians`) and an angle in degrees `(180 / pi) * x` (CPython's `degrees`); sums are plain `+=` in order (never `sum()`, which CPython compensates).

- [ ] **Step 1: Write the module with its tests failing**

Create `native/src/pinmap_geom.rs` with only its test module (the tests at the end of the file below, from `#[cfg(test)]` on), and in `native/src/lib.rs` add `mod pinmap_geom;` to the module list between `mod judge;` and `mod pockets;`.

Run: `cd native && nice cargo test --release --lib pinmap_geom; cd ..`
Expected: FAIL to compile: `cannot find function exit_of in this scope` and the like.

- [ ] **Step 2: The model**

Replace `native/src/pinmap_geom.rs` with:

```rust
//! The pin map study's airwire model (`placemat.pinmap_geom`, its Python twin), for the native core (pinmap.rs), which
//! asks it for every net a move puts on a pin it has not stood on before.
//!
//! A studied part's body is its courtyard's box. A pin's airwire leaves along the pin's outward normal - the side of the
//! box it is nearest - to its exit point, `margin` past the box, then takes the shorter way round the box grown by
//! `margin` to its target, corner to corner, until the target is in sight. A target inside the body's box is reached
//! straight. The bend at a pin is the angle between its outward normal and the bearing from its exit point to its
//! target. A `Pose` turns the part's own frame (the board's, moved to the courtyard box's centre) about that centre,
//! counter-clockwise on screen with y down, mirrored left to right first for the other face.
//!
//! Every value is Python's: `clean9` is `geometry._clean`, `hypot` CPython's, angles go through CPython's `radians`
//! (`x * (pi / 180)`) and `degrees` (`(180 / pi) * x`), and sums are plain, in order.

use crate::exact::{clean9, hypot};

const EPS: f64 = 1e-9;
const SIDES: [(f64, f64); 4] = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]; // east, south, west, north
const DEG_TO_RAD: f64 = std::f64::consts::PI / 180.0; // CPython's degToRad
const RAD_TO_DEG: f64 = 180.0 / std::f64::consts::PI; // and its radToDeg

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pose {
    pub cx: f64,
    pub cy: f64,
    pub turn: f64,
    pub flip: bool,
}

impl Pose {
    pub fn new(cx: f64, cy: f64, turn: f64, flip: bool) -> Pose {
        Pose { cx, cy, turn, flip }
    }

    fn cs(&self) -> (f64, f64) {
        let r = self.turn * DEG_TO_RAD;
        (r.cos(), r.sin())
    }

    /// A direction in the part's own frame, in the board's.
    pub fn vector(&self, x: f64, y: f64) -> (f64, f64) {
        let x = if self.flip { -x } else { x };
        let (c, s) = self.cs();
        (clean9(c * x + s * y), clean9(-s * x + c * y))
    }

    pub fn to_board(self, x: f64, y: f64) -> (f64, f64) {
        let (vx, vy) = self.vector(x, y);
        (clean9(self.cx + vx), clean9(self.cy + vy))
    }

    pub fn to_local(self, x: f64, y: f64) -> (f64, f64) {
        let (dx, dy) = (x - self.cx, y - self.cy);
        let (c, s) = self.cs();
        let lx = c * dx - s * dy;
        let ly = s * dx + c * dy;
        (if self.flip { -lx } else { lx }, ly)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Exit {
    pub at: (f64, f64),
    pub local: (f64, f64),
    pub normal: (f64, f64),
    pub side: usize,
    pub pose: Pose,
    pub hw: f64,
    pub hh: f64,
    pub margin: f64,
}

/// The exit of a pin at (x, y) in the part's frame with outward `normal` (its frame), at `pose`.
pub fn exit_of(pose: Pose, x: f64, y: f64, normal: (f64, f64), hw: f64, hh: f64, margin: f64) -> Exit {
    let side = SIDES.iter().position(|s| *s == normal).unwrap_or(0);
    let local = [(hw + margin, y), (x, hh + margin), (-hw - margin, y), (x, -hh - margin)][side];
    Exit { at: pose.to_board(local.0, local.1), local, normal: pose.vector(normal.0, normal.1), side, pose, hw, hh, margin }
}

/// Whether segment p-q passes through the inside of the box (-hw, -hh)-(hw, hh).
pub fn through(p: (f64, f64), q: (f64, f64), hw: f64, hh: f64) -> bool {
    let (x0, y0) = p;
    let (dx, dy) = (q.0 - x0, q.1 - y0);
    let (mut t0, mut t1) = (0.0f64, 1.0f64);
    for (pp, qq) in [(-dx, x0 + hw), (dx, hw - x0), (-dy, y0 + hh), (dy, hh - y0)] {
        if pp.abs() < 1e-15 {
            if qq <= EPS {
                return false;
            }
            continue;
        }
        let r = qq / pp;
        if pp < 0.0 {
            if r > t0 {
                t0 = r;
            }
        } else if r < t1 {
            t1 = r;
        }
        if t1 - t0 <= EPS {
            return false;
        }
    }
    let mx = x0 + dx * (t0 + t1) / 2.0;
    let my = y0 + dy * (t0 + t1) / 2.0;
    -hw + EPS < mx && mx < hw - EPS && -hh + EPS < my && my < hh - EPS
}

/// A path's length, segment by segment in order.
pub fn length(points: &[(f64, f64)]) -> f64 {
    let mut total = 0.0;
    for w in points.windows(2) {
        total += hypot(w[1].0 - w[0].0, w[1].1 - w[0].1);
    }
    total
}

/// The way from exit `e` to `target` (board frame) round e's body: [e.at, corners..., target].
pub fn round_body(e: &Exit, target: (f64, f64)) -> Vec<(f64, f64)> {
    let t = e.pose.to_local(target.0, target.1);
    let (hw, hh) = (e.hw, e.hh);
    if (-hw < t.0 && t.0 < hw && -hh < t.1 && t.1 < hh) || !through(e.local, t, hw, hh) {
        return vec![e.at, target];
    }
    let (w, h) = (hw + e.margin, hh + e.margin);
    let corners = [(w, -h), (w, h), (-w, h), (-w, -h)]; // north-east, south-east, south-west, north-west
    let after = [1usize, 2, 3, 0];
    let mut best: Option<(f64, Vec<(f64, f64)>)> = None;
    for step in [1i64, -1] {
        let mut k = if step == 1 { after[e.side] } else { (after[e.side] + 3) % 4 };
        let mut local = vec![e.local];
        for _ in 0..4 {
            let c = corners[k];
            local.push(c);
            if !through(c, t, hw, hh) {
                break;
            }
            k = ((k as i64 + step + 4) % 4) as usize;
        }
        local.push(t);
        let n = length(&local);
        let better = match &best {
            None => true,
            Some((b, _)) => n < *b - EPS,
        };
        if better {
            best = Some((n, local));
        }
    }
    let local = best.map(|b| b.1).unwrap_or_default();
    let mut pts = vec![e.at];
    for c in &local[1..local.len() - 1] {
        pts.push(e.pose.to_board(c.0, c.1));
    }
    pts.push(target);
    pts
}

/// One end of an airwire: a studied pin's exit, or a point.
#[derive(Clone, Copy, Debug)]
pub enum End {
    Exit(Exit),
    Point((f64, f64)),
}

impl End {
    fn at(&self) -> (f64, f64) {
        match self {
            End::Exit(e) => e.at,
            End::Point(p) => *p,
        }
    }
}

/// An airwire's path from `a` to `b`: round the body of each end that is an exit, the second end's from the last turn
/// the first one's path makes.
pub fn route(a: &End, b: &End) -> Vec<(f64, f64)> {
    let (pa, pb) = (a.at(), b.at());
    let mut pts = match a {
        End::Exit(e) => round_body(e, pb),
        End::Point(_) => vec![pa, pb],
    };
    if let End::Exit(e) = b {
        let back = round_body(e, pts[pts.len() - 2]);
        pts.pop();
        pts.extend(back.iter().rev().skip(1));
    }
    pts
}

/// Degrees between a pin's outward `normal` and the bearing from its exit point `at` to `target`.
pub fn bend(normal: (f64, f64), at: (f64, f64), target: (f64, f64)) -> f64 {
    let (dx, dy) = (target.0 - at.0, target.1 - at.1);
    let d = hypot(dx, dy);
    if d <= EPS {
        return 0.0;
    }
    let cos = ((normal.0 * dx + normal.1 * dy) / d).clamp(-1.0, 1.0);
    RAD_TO_DEG * cos.acos()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn east(pose: Pose, y: f64) -> Exit {
        exit_of(pose, 2.0, y, (1.0, 0.0), 2.0, 2.0, 0.5)
    }

    #[test]
    fn a_target_in_sight_is_straight_and_one_behind_goes_round_the_shorter_way() {
        let e = east(Pose::new(10.0, 10.0, 0.0, false), 0.5);
        assert_eq!(e.at, (12.5, 10.5));
        assert_eq!(route(&End::Exit(e), &End::Point((20.0, 10.5))), vec![(12.5, 10.5), (20.0, 10.5)]);
        assert_eq!(route(&End::Exit(e), &End::Point((0.0, 10.0))), vec![(12.5, 10.5), (12.5, 12.5), (7.5, 12.5), (0.0, 10.0)]);
        assert_eq!(route(&End::Exit(e), &End::Point((9.0, 10.0))), vec![(12.5, 10.5), (9.0, 10.0)]);
    }

    #[test]
    fn a_quarter_turn_takes_an_east_pin_north_and_a_flip_takes_it_west() {
        let e = east(Pose::new(10.0, 10.0, 90.0, false), 0.5);
        assert_eq!((e.at, e.normal), ((10.5, 7.5), (0.0, -1.0)));
        let e = east(Pose::new(10.0, 10.0, 0.0, true), 0.5);
        assert_eq!((e.at, e.normal), ((7.5, 10.5), (-1.0, 0.0)));
    }

    #[test]
    fn the_bend_is_the_angle_from_the_normal_to_the_target() {
        assert_eq!(bend((1.0, 0.0), (12.5, 10.5), (20.0, 10.5)), 0.0);
        assert!((bend((1.0, 0.0), (12.5, 10.0), (0.0, 10.0)) - 180.0).abs() < 1e-9);
        assert!((bend((1.0, 0.0), (12.5, 10.0), (20.0, 2.5)) - 45.0).abs() < 1e-9);
    }
}
```

- [ ] **Step 3: Run the tests to watch them pass**

Run: `cd native && nice cargo test --release --lib pinmap_geom; cd ..`
Expected: PASS (3 tests). (`dead_code` warnings until Task 5 uses the module are expected; nothing is exported to Python yet.)

- [ ] **Step 4: Commit**

```bash
git add native/src/pinmap_geom.rs native/src/lib.rs
git commit -m "Native: the pin map study's airwire model, round the body, with its bend"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 5: The native core - crossing counts, the score, the annealing search

**Files:**
- Create: `native/src/pinmap.rs`
- Modify: `native/src/lib.rs` (`mod pinmap;`, the `pinmap_search` pyfunction, its registration)
- Create: `src/placemat/pinmap_core.py` (the arrays, the poses, the one entry point, `study_group`)
- Test: the Rust unit tests in `native/src/pinmap.rs`; `tests/test_pinmap_core.py`

**Interfaces:**
- Consumes: Task 4's `pinmap_geom.rs`; `crate::ratsnest::{mst, cross_nm, nm}` (KiCad's tree with its tie order, the proper-crossing test and nanometre rounding, already ported); `crate::exact::hypot`; Task 3's `StudyInput` (`parts` with `slots`, `nets`, `background`); Task 2's `natural`; settings `pins_*` and `score_crossing_plane`; `geometry._native` (set only when `native_status()` finds the module's version is placemat's).
- Produces:
  - `placemat_native.pinmap_search(parts, pins, nets, fixed, joined, ends, wires, movable, groups, group_parts, combos, weights, params)` where `weights = (pair, impedance, plane, length, bend)` and `params = (margin, seeds, moves, t0, t1, budget_ms, step_ms, seed_key)`; it returns `(present, present_paths, results, budget_out, first_map, problems)`: `present` the tallies `(total, against, among, weighted, length, bend)`, `present_paths` `[(net, [path, ...])]` for the group's nets, `results` `[(combo, tallies, assignment, paths)]` (an assignment is a pin index per end slot per net), `problems` `[(part, net)]` no matching placed.
  - `pinmap_core.Problem(parts, pins, nets, fixed, joined, ends, wires, movable, groups, margin)`; `KIND_CODES`; `problem_of(inp, margin) -> Problem`; `poses_of(part, settings) -> list[(turn, flip)]`; `seed_key(refs) -> int`; `params_of(settings, refs, step_ms=0.0, budget_ms=None) -> dict`; `native_core()`; `search(pb, group_parts, combos, params, native=True) -> tuple` (the one entry point; until Task 7 it refuses to run without the native module); `Breakdown(total, against, among, weighted, length_mm, bend_deg)` with `.to_json()`; `PoseResult(poses, breakdown, assign, paths)`; `GroupResult(refs, present, present_assign, present_paths, results, searched, of, budget_out, first_map, problems)`; `study_group(inp, refs, settings, step_ms=0.0, budget_ms=None, native=True, pb=None) -> GroupResult`.

The arrays (all plain lists, as pyo3 takes them): `parts` (ref, cx, cy, hw, hh); `pins` per part (number, x, y, nx, ny) in natural pad order, x and y in the part's own frame; `nets` (name, kind code 0 plain, 1 pair, 2 impedance, 3 plane); per net `fixed` anchors (x, y, ref, number), `joined` index pairs of them and `ends` (part, pin) one per end slot; `wires` (kind, ax, ay, bx, by) in nm; `movable` (net, slot, allowed pins, group or -1); `groups` (part, member movables or -1, windows of pins); `group_parts` the parts searched; `combos` the pose combinations, each [(part, turn, flip)], the present one first, capped by Python at `pins.joint_combinations`.

The algorithm (the Python twin, Task 7, is the same line for line):

- Score of an assignment: per net in index order its background crossings (weighted, counted) and its airwires' length and bend; then per pair of nets (a < b) their crossings. `total = weighted + length_weight * length + bend_weight * bend`. A net's airwires: `ratsnest::mst` over its fixed anchors then its ends at their exit points (as (x, y, ref, number)); each tree edge routed with `pinmap_geom::route`; each studied end's bend the smallest over its tree edges; length and bend summed in order. Memoised per (net, pins), per (net, net, pins, pins); a move's price is `Tally::delta` over the nets it touches.
- Background: the other airwires on a 2 mm grid (`CELL_NM = 2_000_000`), a plane's left out when `score.crossing_plane` is 0; a segment's candidates taken in wire order.
- First map, per part of the group: each group placed on the cheapest window (summed distance from each member's exit point to its nearest fixed anchor, ties by window order) that still leaves the other movables a matching; then the other movables by `hungarian`, ties to the lower pin. A part no matching places keeps its pins and gives `(part, net)`.
- Search, per seed: SplitMix64 seeded `seed_key ^ (combo << 32) ^ seed`; `moves` steps; at step k the temperature is `t0 * (t1 / t0) ** (k / max(moves - 1, 1))`; a unit (a single movable, or a group with windows) is drawn; a single moves to a free allowed pin or swaps with an ungrouped movable that may take its pin; a group moves to another window, the ungrouped movables standing there taking the pins it left, in pin order; a change is taken when it gains more than 1e-12 or when a draw falls below `exp(-d / temperature)`; the best is kept when it beats the best by 1e-9.
- Clock: asked between poses and every 32 steps; `step_ms > 0` makes it a counted clock (each question adds `step_ms`), for tests and for the twins to agree on where a study stops.

- [ ] **Step 1: Write the Rust tests first and watch them fail to build**

Create `native/src/pinmap.rs` holding only the test module at the end of the file below (from `#[cfg(test)]` on), and in `native/src/lib.rs` add `mod pinmap;` between `mod judge;` and `mod pinmap_geom;`.

Run: `cd native && nice cargo test --release --lib pinmap::; cd ..`
Expected: FAIL to compile: `cannot find type Problem`, `cannot find function hungarian`.

- [ ] **Step 2: The core**

Replace `native/src/pinmap.rs` with:

```rust
//! The pin map study's core (`placemat.pinmap_core`; its Python twin is `placemat.pinmap_twin`, which this mirrors line
//! for line so the two give the same answers). It takes a study as plain arrays and, for the parts of one group and each
//! combination of their poses, returns the best assignment of the movable nets to pins with its tallies.
//!
//! - Score: weighted crossings of the studied nets' airwires against the board's other airwires (on a 2 mm grid) and
//!   among themselves, plus `length` times their length in mm, plus `bend` times their summed bend in degrees. A net's
//!   airwires are the minimum spanning tree of its pads (`ratsnest::mst`), each studied pin at its exit point and each
//!   airwire to one taken round the body (pinmap_geom.rs).
//! - Incremental: a net's airwires, its crossings with the background and with each other net are kept per placing of
//!   its ends, so a move recounts only the nets it touches.
//! - Search: a first map (each group on the cheapest run of pins that leaves the rest a matching, then a minimum-cost
//!   matching), then per seed `moves` moves, swaps and group moves under annealing from `t0` down to `t1`, the clock
//!   checked every 32 moves and between poses. The random stream is SplitMix64, the twin's.

use crate::exact::hypot;
use crate::pinmap_geom::{bend, exit_of, length, route, End, Exit, Pose};
use crate::ratsnest::{cross_nm, mst, nm};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::rc::Rc;
use std::time::Instant;

pub const CELL_NM: i64 = 2_000_000; // pinmap_twin.CELL_NM
const PAIR: u8 = 1;
const IMPEDANCE: u8 = 2;
const PLANE: u8 = 3;

/// (ax, ay, bx, by, minx, miny, maxx, maxy) in whole nanometres.
pub type Seg = [i64; 8];
/// (total, against, among, weighted, length, bend).
pub type Tallies = (f64, i64, i64, f64, f64, f64);
pub type Paths = Vec<(usize, Vec<Vec<(f64, f64)>>)>;

/// A part (ref, cx, cy, hw, hh), or a pin (number, x, y, nx, ny).
pub type Row = (String, f64, f64, f64, f64);

/// A study as `pinmap_core.Problem` holds it.
pub struct Problem {
    pub parts: Vec<Row>,
    pub pins: Vec<Vec<Row>>,
    pub nets: Vec<(String, u8)>,
    pub fixed: Vec<Vec<(f64, f64, String, String)>>,
    pub joined: Vec<Vec<(usize, usize)>>,
    pub ends: Vec<Vec<(usize, usize)>>,
    pub wires: Vec<(u8, i64, i64, i64, i64)>,
    pub movable: Vec<(usize, usize, Vec<usize>, i64)>,
    pub groups: Vec<(usize, Vec<i64>, Vec<Vec<usize>>)>,
    pub margin: f64,
}

/// (pair, impedance, plane, length, bend) weights and the search's own figures.
pub struct Params {
    pub w: [f64; 5],
    pub seeds: u32,
    pub moves: u32,
    pub t0: f64,
    pub t1: f64,
    pub budget_ms: f64,
    pub step_ms: f64,
    pub seed_key: u64,
}

pub struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    pub fn new(seed: u64) -> SplitMix64 {
        SplitMix64 { state: seed }
    }

    pub fn next(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }

    fn unit(&mut self) -> f64 {
        (self.next() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }
}

pub fn stream_seed(seed_key: u64, combo: usize, seed: usize) -> u64 {
    seed_key ^ ((combo as u64) << 32) ^ (seed as u64)
}

struct Clock {
    budget: f64,
    step: f64,
    elapsed: f64,
    start: Instant,
}

impl Clock {
    fn out(&mut self) -> bool {
        if self.step > 0.0 {
            self.elapsed += self.step;
        } else {
            self.elapsed = self.start.elapsed().as_secs_f64() * 1000.0;
        }
        self.elapsed >= self.budget
    }
}

fn one(w: &[f64; 5], k: u8) -> f64 {
    match k {
        PAIR => w[0],
        IMPEDANCE => w[1],
        _ => 1.0,
    }
}

/// What a crossing of classes `a` and `b` counts.
pub fn crossing(w: &[f64; 5], a: u8, b: u8) -> f64 {
    if a == PLANE || b == PLANE {
        return w[2];
    }
    let (x, y) = (one(w, a), one(w, b));
    if x >= y { x } else { y }
}

fn segments(paths: &[Vec<(f64, f64)>]) -> Vec<Seg> {
    let mut out = Vec::new();
    for path in paths {
        for p in path.windows(2) {
            let (ax, ay, bx, by) = (nm(p[0].0), nm(p[0].1), nm(p[1].0), nm(p[1].1));
            out.push([ax, ay, bx, by, ax.min(bx), ay.min(by), ax.max(bx), ay.max(by)]);
        }
    }
    out
}

fn cells(s: &Seg) -> Vec<(i64, i64)> {
    let mut out = Vec::new();
    for cx in s[4].div_euclid(CELL_NM)..=s[6].div_euclid(CELL_NM) {
        for cy in s[5].div_euclid(CELL_NM)..=s[7].div_euclid(CELL_NM) {
            out.push((cx, cy));
        }
    }
    out
}

struct Background {
    w: [f64; 5],
    kinds: Vec<u8>,
    segs: Vec<Seg>,
    grid: HashMap<(i64, i64), Vec<usize>>,
}

impl Background {
    fn new(wires: &[(u8, i64, i64, i64, i64)], w: [f64; 5]) -> Background {
        let kept: Vec<&(u8, i64, i64, i64, i64)> = wires.iter().filter(|x| !(x.0 == PLANE && w[2] <= 0.0)).collect();
        let segs: Vec<Seg> = kept.iter().map(|x| [x.1, x.2, x.3, x.4, x.1.min(x.3), x.2.min(x.4), x.1.max(x.3), x.2.max(x.4)]).collect();
        let mut grid: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
        for (k, s) in segs.iter().enumerate() {
            for c in cells(s) {
                grid.entry(c).or_default().push(k);
            }
        }
        Background { w, kinds: kept.iter().map(|x| x.0).collect(), segs, grid }
    }

    fn cross(&self, kind: u8, segs: &[Seg]) -> (f64, i64) {
        let (mut total, mut count) = (0.0, 0i64);
        for s in segs {
            let mut near: BTreeSet<usize> = BTreeSet::new();
            for c in cells(s) {
                if let Some(v) = self.grid.get(&c) {
                    near.extend(v.iter().copied());
                }
            }
            for k in near {
                let t = &self.segs[k];
                if t[6] < s[4] || s[6] < t[4] || t[7] < s[5] || s[7] < t[5] {
                    continue;
                }
                if cross_nm(s[0], s[1], s[2], s[3], t[0], t[1], t[2], t[3]) {
                    total += crossing(&self.w, kind, self.kinds[k]);
                    count += 1;
                }
            }
        }
        (total, count)
    }
}

pub fn segments_crossing(a: &[Seg], b: &[Seg]) -> i64 {
    let mut n = 0;
    for s in a {
        for t in b {
            if s[6] < t[4] || t[6] < s[4] || s[7] < t[5] || t[7] < s[5] {
                continue;
            }
            if cross_nm(s[0], s[1], s[2], s[3], t[0], t[1], t[2], t[3]) {
                n += 1;
            }
        }
    }
    n
}

struct NetWires {
    paths: Vec<Vec<(f64, f64)>>,
    length: f64,
    bend: f64,
    segs: Vec<Seg>,
    bbox: [i64; 4],
}

type Pins = Vec<usize>;

struct Scorer<'a> {
    pb: &'a Problem,
    poses: Vec<Pose>,
    w: [f64; 5],
    bg: &'a Background,
    exits: HashMap<(usize, usize), Exit>,
    wires: HashMap<(usize, Pins), Rc<NetWires>>,
    single: HashMap<(usize, Pins), (f64, f64, i64)>,
    pair: HashMap<(usize, Pins, usize, Pins), (f64, i64)>,
}

impl<'a> Scorer<'a> {
    fn new(pb: &'a Problem, poses: Vec<Pose>, w: [f64; 5], bg: &'a Background) -> Scorer<'a> {
        Scorer { pb, poses, w, bg, exits: HashMap::new(), wires: HashMap::new(), single: HashMap::new(), pair: HashMap::new() }
    }

    fn exit(&mut self, part: usize, pin: usize) -> Exit {
        if let Some(e) = self.exits.get(&(part, pin)) {
            return *e;
        }
        let (_, _, _, hw, hh) = self.pb.parts[part];
        let (_, x, y, nx, ny) = self.pb.pins[part][pin];
        let e = exit_of(self.poses[part], x, y, (nx, ny), hw, hh, self.pb.margin);
        self.exits.insert((part, pin), e);
        e
    }

    fn wires(&mut self, net: usize, pins: &Pins) -> Rc<NetWires> {
        if let Some(hit) = self.wires.get(&(net, pins.clone())) {
            return hit.clone();
        }
        let pb = self.pb;
        let fixed = &pb.fixed[net];
        let mut anchors: Vec<(f64, f64, String, String)> = fixed.clone();
        let mut exits = Vec::new();
        for (slot, &pin) in pins.iter().enumerate() {
            let part = pb.ends[net][slot].0;
            let e = self.exit(part, pin);
            exits.push(e);
            anchors.push((e.at.0, e.at.1, pb.parts[part].0.clone(), pb.pins[part][pin].0.clone()));
        }
        let first = fixed.len();
        let end_of = |i: usize| if i >= first { End::Exit(exits[i - first]) } else { End::Point((anchors[i].0, anchors[i].1)) };
        let mut paths = Vec::new();
        let mut bends: BTreeMap<usize, f64> = BTreeMap::new();
        for (i, j) in mst(&anchors, &pb.joined[net]) {
            paths.push(route(&end_of(i), &end_of(j)));
            for (me, other) in [(i, j), (j, i)] {
                if me >= first {
                    let e = exits[me - first];
                    let d = bend(e.normal, e.at, (anchors[other].0, anchors[other].1));
                    let v = bends.entry(me).or_insert(d);
                    if d < *v {
                        *v = d;
                    }
                }
            }
        }
        let mut ln = 0.0;
        for p in &paths {
            ln += length(p);
        }
        let mut bd = 0.0;
        for v in bends.values() {
            bd += *v;
        }
        let segs = segments(&paths);
        let bbox = if segs.is_empty() {
            [0, 0, 0, 0]
        } else {
            [segs.iter().map(|s| s[4]).min().unwrap(), segs.iter().map(|s| s[5]).min().unwrap(),
             segs.iter().map(|s| s[6]).max().unwrap(), segs.iter().map(|s| s[7]).max().unwrap()]
        };
        let hit = Rc::new(NetWires { paths, length: ln, bend: bd, segs, bbox });
        self.wires.insert((net, pins.clone()), hit.clone());
        hit
    }

    fn single(&mut self, net: usize, pins: &Pins) -> (f64, f64, i64) {
        if let Some(hit) = self.single.get(&(net, pins.clone())) {
            return *hit;
        }
        let nw = self.wires(net, pins);
        let (weighted, count) = self.bg.cross(self.pb.nets[net].1, &nw.segs);
        let hit = (weighted + self.w[3] * nw.length + self.w[4] * nw.bend, weighted, count);
        self.single.insert((net, pins.clone()), hit);
        hit
    }

    fn pair(&mut self, a: usize, ea: &Pins, b: usize, eb: &Pins) -> (f64, i64) {
        let (a, ea, b, eb) = if b < a { (b, eb, a, ea) } else { (a, ea, b, eb) };
        let key = (a, ea.clone(), b, eb.clone());
        if let Some(hit) = self.pair.get(&key) {
            return *hit;
        }
        let (wa, wb) = (self.wires(a, ea), self.wires(b, eb));
        let (ba, bb) = (wa.bbox, wb.bbox);
        let hit = if ba[2] < bb[0] || bb[2] < ba[0] || ba[3] < bb[1] || bb[3] < ba[1] {
            (0.0, 0)
        } else {
            let n = segments_crossing(&wa.segs, &wb.segs);
            (n as f64 * crossing(&self.w, self.pb.nets[a].1, self.pb.nets[b].1), n)
        };
        self.pair.insert(key, hit);
        hit
    }

    fn total(&mut self, assign: &[Pins]) -> Tallies {
        let (mut weighted, mut against, mut among, mut ln, mut bd) = (0.0, 0i64, 0i64, 0.0, 0.0);
        for (n, pins) in assign.iter().enumerate() {
            let (_, w, c) = self.single(n, pins);
            let nw = self.wires(n, pins);
            weighted += w;
            against += c;
            ln += nw.length;
            bd += nw.bend;
        }
        for a in 0..assign.len() {
            for b in a + 1..assign.len() {
                let (w, c) = self.pair(a, &assign[a], b, &assign[b]);
                weighted += w;
                among += c;
            }
        }
        (weighted + self.w[3] * ln + self.w[4] * bd, against, among, weighted, ln, bd)
    }

    fn paths(&mut self, group_parts: &[usize], assign: &[Pins]) -> Paths {
        let mut out = Vec::new();
        for (n, pins) in assign.iter().enumerate() {
            if (0..pins.len()).any(|k| group_parts.contains(&self.pb.ends[n][k].0)) {
                out.push((n, self.wires(n, pins).paths.clone()));
            }
        }
        out
    }
}

struct Tally {
    assign: Vec<Pins>,
    value: f64,
}

impl Tally {
    fn new(sc: &mut Scorer, assign: &[Pins]) -> Tally {
        let value = sc.total(assign).0;
        Tally { assign: assign.to_vec(), value }
    }

    fn delta(&self, sc: &mut Scorer, changes: &BTreeMap<usize, Pins>) -> f64 {
        let now = &self.assign;
        let moved: Vec<usize> = changes.keys().copied().collect();
        let mut d = 0.0;
        for &n in &moved {
            d += sc.single(n, &changes[&n]).0 - sc.single(n, &now[n]).0;
        }
        for &n in &moved {
            for m in 0..now.len() {
                if changes.contains_key(&m) {
                    continue;
                }
                d += sc.pair(n, &changes[&n], m, &now[m]).0 - sc.pair(n, &now[n], m, &now[m]).0;
            }
        }
        for (i, &n) in moved.iter().enumerate() {
            for &m in &moved[i + 1..] {
                d += sc.pair(n, &changes[&n], m, &changes[&m]).0 - sc.pair(n, &now[n], m, &now[m]).0;
            }
        }
        d
    }

    fn apply(&mut self, changes: &BTreeMap<usize, Pins>, d: f64) {
        for (n, pins) in changes {
            self.assign[*n] = pins.clone();
        }
        self.value += d;
    }
}

/// `pinmap_twin.hungarian`: each row's column, or None when every assignment meets an infinite cost.
pub fn hungarian(cost: &[Vec<f64>]) -> Option<Vec<usize>> {
    let n = cost.len();
    if n == 0 {
        return Some(Vec::new());
    }
    let m = cost[0].len();
    let a: Vec<Vec<f64>> = cost.iter().map(|row| row.iter().map(|&c| if c < 1e12 { c } else { 1e12 }).collect()).collect();
    let (mut u, mut v) = (vec![0.0f64; n + 1], vec![0.0f64; m + 1]);
    let (mut p, mut way) = (vec![0usize; m + 1], vec![0usize; m + 1]);
    for i in 1..=n {
        p[0] = i;
        let mut j0 = 0usize;
        let mut minv = vec![f64::INFINITY; m + 1];
        let mut used = vec![false; m + 1];
        loop {
            used[j0] = true;
            let (i0, mut delta, mut j1) = (p[j0], f64::INFINITY, 0usize);
            for j in 1..=m {
                if !used[j] {
                    let cur = a[i0 - 1][j - 1] - u[i0] - v[j];
                    if cur < minv[j] {
                        minv[j] = cur;
                        way[j] = j0;
                    }
                    if minv[j] < delta {
                        delta = minv[j];
                        j1 = j;
                    }
                }
            }
            for j in 0..=m {
                if used[j] {
                    u[p[j]] += delta;
                    v[j] -= delta;
                } else {
                    minv[j] -= delta;
                }
            }
            j0 = j1;
            if p[j0] == 0 {
                break;
            }
        }
        loop {
            let j1 = way[j0];
            p[j0] = p[j1];
            j0 = j1;
            if j0 == 0 {
                break;
            }
        }
    }
    let mut out = vec![0usize; n];
    for j in 1..=m {
        if p[j] != 0 {
            out[p[j] - 1] = j - 1;
        }
    }
    for i in 0..n {
        if cost[i][out[i]] == f64::INFINITY {
            return None;
        }
    }
    Some(out)
}

fn with(assign: &[Pins], net: usize, slot: usize, pin: usize) -> Pins {
    let mut pins = assign[net].clone();
    pins[slot] = pin;
    pins
}

fn part_of(pb: &Problem, mv: usize) -> usize {
    pb.ends[pb.movable[mv].0][pb.movable[mv].1].0
}

fn target_cost(sc: &mut Scorer, mv: usize, pin: usize, assign: &[Pins]) -> f64 {
    let pb = sc.pb;
    let (net, slot) = (pb.movable[mv].0, pb.movable[mv].1);
    let e = sc.exit(part_of(pb, mv), pin);
    let mut pts: Vec<(f64, f64)> = pb.fixed[net].iter().map(|a| (a.0, a.1)).collect();
    if pts.is_empty() {
        for (k, &q) in assign[net].iter().enumerate() {
            if k != slot {
                pts.push(sc.exit(pb.ends[net][k].0, q).at);
            }
        }
    }
    let mut best: Option<f64> = None;
    for (x, y) in pts {
        let d = hypot(e.at.0 - x, e.at.1 - y);
        if best.is_none() || d < best.unwrap() {
            best = Some(d);
        }
    }
    best.unwrap_or(0.0)
}

fn matching(sc: &mut Scorer, singles: &[usize], used: &BTreeSet<usize>, assign: &[Pins]) -> (Vec<usize>, Option<Vec<usize>>) {
    let pb = sc.pb;
    let pins: Vec<usize> = singles.iter().flat_map(|&k| pb.movable[k].2.iter().copied()).collect::<BTreeSet<usize>>()
        .difference(used).copied().collect();
    if pins.len() < singles.len() {
        return (pins, None);
    }
    let mut cost = Vec::new();
    for &k in singles {
        let mut row = Vec::new();
        for &q in &pins {
            row.push(if pb.movable[k].2.contains(&q) { target_cost(sc, k, q, assign) } else { f64::INFINITY });
        }
        cost.push(row);
    }
    let got = hungarian(&cost);
    (pins, got)
}

fn first_map(sc: &mut Scorer, group_parts: &[usize], start: &[Pins]) -> (Vec<Pins>, Vec<(usize, usize)>) {
    let pb = sc.pb;
    let mut assign = start.to_vec();
    let mut problems = Vec::new();
    for &part in group_parts {
        let singles: Vec<usize> = (0..pb.movable.len()).filter(|&k| part_of(pb, k) == part && pb.movable[k].3 < 0).collect();
        let mut used: BTreeSet<usize> = BTreeSet::new();
        let mut changes: BTreeMap<usize, usize> = BTreeMap::new();
        for (gpart, members, windows) in &pb.groups {
            if *gpart != part {
                continue;
            }
            let mut ranked: Vec<(f64, usize)> = Vec::new();
            for (wi, win) in windows.iter().enumerate() {
                if win.iter().any(|q| used.contains(q)) {
                    continue;
                }
                let mut c = 0.0;
                for (m, &q) in members.iter().zip(win.iter()) {
                    if *m >= 0 {
                        c += target_cost(sc, *m as usize, q, &assign);
                    }
                }
                ranked.push((c, wi));
            }
            ranked.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap().then(a.1.cmp(&b.1)));
            let mut chosen: Option<&Vec<usize>> = None;
            for (_, wi) in &ranked {
                let mut trial = used.clone();
                trial.extend(windows[*wi].iter().copied());
                if matching(sc, &singles, &trial, &assign).1.is_some() {
                    chosen = Some(&windows[*wi]);
                    break;
                }
            }
            match chosen {
                None => {
                    for m in members.iter().filter(|m| **m >= 0) {
                        let mv = &pb.movable[*m as usize];
                        used.insert(assign[mv.0][mv.1]);
                    }
                }
                Some(win) => {
                    used.extend(win.iter().copied());
                    for (m, &q) in members.iter().zip(win.iter()) {
                        if *m >= 0 {
                            changes.insert(*m as usize, q);
                        }
                    }
                }
            }
        }
        if !singles.is_empty() {
            let (pins, got) = matching(sc, &singles, &used, &assign);
            match got {
                None => {
                    let bad = singles.iter().copied().find(|&k| !pins.iter().any(|q| pb.movable[k].2.contains(q))).unwrap_or(singles[0]);
                    problems.push((part, pb.movable[bad].0));
                    continue;
                }
                Some(got) => {
                    for (k, j) in singles.iter().zip(got.iter()) {
                        changes.insert(*k, pins[*j]);
                    }
                }
            }
        }
        for (k, q) in changes {
            let (net, slot) = (pb.movable[k].0, pb.movable[k].1);
            assign[net] = with(&assign, net, slot, q);
        }
    }
    (assign, problems)
}

struct State {
    pin: Vec<usize>,
    who: HashMap<(usize, usize), usize>,
}

impl State {
    fn new(pb: &Problem, assign: &[Pins]) -> State {
        let pin: Vec<usize> = pb.movable.iter().map(|mv| assign[mv.0][mv.1]).collect();
        let mut who = HashMap::new();
        for (k, &q) in pin.iter().enumerate() {
            who.insert((part_of(pb, k), q), k);
        }
        State { pin, who }
    }

    fn commit(&mut self, pb: &Problem, changes: &BTreeMap<usize, usize>) {
        for &k in changes.keys() {
            let key = (part_of(pb, k), self.pin[k]);
            if self.who.get(&key) == Some(&k) {
                self.who.remove(&key);
            }
        }
        for (&k, &q) in changes {
            self.pin[k] = q;
            self.who.insert((part_of(pb, k), q), k);
        }
    }
}

#[derive(Clone, Copy)]
enum Unit {
    Movable(usize),
    Group(usize),
}

fn units(pb: &Problem, group_parts: &[usize]) -> Vec<Unit> {
    let mut out = Vec::new();
    for &part in group_parts {
        for k in 0..pb.movable.len() {
            if pb.movable[k].3 < 0 && part_of(pb, k) == part {
                out.push(Unit::Movable(k));
            }
        }
        for (g, gr) in pb.groups.iter().enumerate() {
            if gr.0 == part && !gr.2.is_empty() {
                out.push(Unit::Group(g));
            }
        }
    }
    out
}

fn propose(rng: &mut SplitMix64, st: &State, pb: &Problem, units: &[Unit]) -> Option<BTreeMap<usize, usize>> {
    if units.is_empty() {
        return None;
    }
    match units[rng.below(units.len())] {
        Unit::Movable(i) => {
            let mv = &pb.movable[i];
            let part = part_of(pb, i);
            let here = st.pin[i];
            let choices: Vec<usize> = mv.2.iter().copied().filter(|&q| q != here).collect();
            if choices.is_empty() {
                return None;
            }
            let to = choices[rng.below(choices.len())];
            let mut out = BTreeMap::new();
            match st.who.get(&(part, to)) {
                None => {
                    out.insert(i, to);
                    Some(out)
                }
                Some(&other) => {
                    if pb.movable[other].3 < 0 && pb.movable[other].2.contains(&here) {
                        out.insert(i, to);
                        out.insert(other, here);
                        Some(out)
                    } else {
                        None
                    }
                }
            }
        }
        Unit::Group(g) => {
            let (gpart, members, windows) = &pb.groups[g];
            let now: Vec<usize> = members.iter().filter(|m| **m >= 0).map(|m| st.pin[*m as usize]).collect();
            let wins: Vec<&Vec<usize>> = windows.iter()
                .filter(|w| members.iter().zip(w.iter()).filter(|(m, _)| **m >= 0).map(|(_, q)| *q).collect::<Vec<usize>>() != now)
                .collect();
            if wins.is_empty() {
                return None;
            }
            let win = wins[rng.below(wins.len())];
            let mut changes = BTreeMap::new();
            for (m, &q) in members.iter().zip(win.iter()) {
                if *m >= 0 {
                    changes.insert(*m as usize, q);
                }
            }
            let left: Vec<usize> = now.iter().copied().collect::<BTreeSet<usize>>()
                .difference(&win.iter().copied().collect()).copied().collect();
            let mut sorted_win = win.clone();
            sorted_win.sort_unstable();
            let taken: Vec<usize> = sorted_win.into_iter()
                .filter(|q| match st.who.get(&(*gpart, *q)) {
                    Some(&o) => !members.contains(&(o as i64)),
                    None => false,
                })
                .collect();
            if taken.len() > left.len() {
                return None;
            }
            for (q, r) in taken.iter().zip(left.iter()) {
                let other = st.who[&(*gpart, *q)];
                if pb.movable[other].3 >= 0 || !pb.movable[other].2.contains(r) {
                    return None;
                }
                changes.insert(other, *r);
            }
            Some(changes)
        }
    }
}

fn anneal(sc: &mut Scorer, group_parts: &[usize], start: &[Pins], pr: &Params, combo: usize, clock: &mut Clock) -> (Vec<Pins>, f64, bool) {
    let pb = sc.pb;
    let mut best = start.to_vec();
    let mut best_v = sc.total(start).0;
    let units = units(pb, group_parts);
    let n = pr.moves.max(1) as usize;
    for s in 0..pr.seeds.max(1) as usize {
        let mut rng = SplitMix64::new(stream_seed(pr.seed_key, combo, s));
        let mut tally = Tally::new(sc, start);
        let mut st = State::new(pb, start);
        for k in 0..n {
            if k % 32 == 0 && clock.out() {
                return (best, best_v, true);
            }
            let temp = if pr.t0 > 0.0 && pr.t1 > 0.0 {
                pr.t0 * (pr.t1 / pr.t0).powf(k as f64 / (n.saturating_sub(1).max(1)) as f64)
            } else {
                0.0
            };
            let got = match propose(&mut rng, &st, pb, &units) {
                Some(g) => g,
                None => continue,
            };
            let mut changes: BTreeMap<usize, Pins> = BTreeMap::new();
            for (&m, &q) in &got {
                let (net, slot) = (pb.movable[m].0, pb.movable[m].1);
                changes.insert(net, with(&tally.assign, net, slot, q));
            }
            let d = tally.delta(sc, &changes);
            if d < -1e-12 || (temp > 0.0 && rng.unit() < (-d / temp).exp()) {
                tally.apply(&changes, d);
                st.commit(pb, &got);
                if tally.value < best_v - 1e-9 {
                    best = tally.assign.clone();
                    best_v = tally.value;
                }
            }
        }
    }
    (best, best_v, false)
}

pub type SearchResult = (Tallies, Paths, Vec<(usize, Tallies, Vec<Pins>, Paths)>, bool, bool, Vec<(usize, usize)>);

/// `pinmap_twin.search`: (present tallies, present paths, [(combo, tallies, assignment, paths)], budget_out, first_map,
/// [(part, net)] no matching placed).
pub fn search(pb: &Problem, group_parts: &[usize], combos: &[Vec<(usize, f64, bool)>], pr: &Params) -> SearchResult {
    let bg = Background::new(&pb.wires, pr.w);
    let mut clock = Clock { budget: pr.budget_ms, step: pr.step_ms, elapsed: 0.0, start: Instant::now() };
    let present: Vec<Pins> = pb.ends.iter().map(|e| e.iter().map(|x| x.1).collect()).collect();
    let present_poses: Vec<Pose> = pb.parts.iter().map(|p| Pose::new(p.1, p.2, 0.0, false)).collect();
    let mut sc0 = Scorer::new(pb, present_poses.clone(), pr.w, &bg);
    let base = sc0.total(&present);
    let base_paths = sc0.paths(group_parts, &present);
    let (mut results, mut out, mut first, mut problems) = (Vec::new(), false, true, Vec::new());
    for (k, combo) in combos.iter().enumerate() {
        if clock.out() {
            out = true;
            if k == 0 {
                first = false;
            }
            break;
        }
        let mut poses = present_poses.clone();
        for &(part, turn, flip) in combo {
            poses[part] = Pose::new(pb.parts[part].1, pb.parts[part].2, turn, flip);
        }
        let mut fresh;
        let sc: &mut Scorer = if k == 0 {
            &mut sc0
        } else {
            fresh = Scorer::new(pb, poses, pr.w, &bg);
            &mut fresh
        };
        let (start, said) = first_map(sc, group_parts, &present);
        for p in &said {
            if !problems.contains(p) {
                problems.push(*p);
            }
        }
        if !said.is_empty() && k == 0 {
            return (base, base_paths, Vec::new(), false, true, problems);
        }
        let (best, _, ran_out) = anneal(sc, group_parts, &start, pr, k, &mut clock);
        let t = sc.total(&best);
        let paths = sc.paths(group_parts, &best);
        results.push((k, t, best, paths));
        if ran_out {
            out = true;
            break;
        }
    }
    (base, base_paths, results, out, first, problems)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitmix_is_the_published_stream() {
        let mut r = SplitMix64::new(1234567);
        assert_eq!(r.next(), 6457827717110365317);
        assert_eq!(r.next(), 3203168211198807973);
    }

    #[test]
    fn the_matching_is_the_cheapest_and_refuses_what_cannot_be_matched() {
        assert_eq!(hungarian(&[vec![4.0, 1.0, 3.0], vec![2.0, 0.0, 5.0], vec![3.0, 2.0, 2.0]]), Some(vec![1, 0, 2]));
        assert_eq!(hungarian(&[vec![1.0, f64::INFINITY], vec![2.0, f64::INFINITY]]), None);
    }

    fn reversed_four() -> Problem {
        // U1 with A-D on its east side north to south; their test points due east in the opposite order
        let pins = (0..4).map(|i| ((i + 1).to_string(), 1.7, -1.5 + i as f64, 1.0, 0.0)).collect();
        let fixed = (0..4).map(|i| vec![(20.0, 11.5 - i as f64, format!("TP{}", 4 - i), "1".to_string())]).collect();
        Problem {
            parts: vec![("U1".into(), 10.0, 10.0, 2.25, 2.25)], pins: vec![pins],
            nets: vec![("A".into(), 0), ("B".into(), 0), ("C".into(), 0), ("D".into(), 0)], fixed,
            joined: vec![vec![]; 4], ends: (0..4).map(|i| vec![(0, i)]).collect(), wires: vec![],
            movable: (0..4).map(|i| (i, 0, vec![0, 1, 2, 3], -1)).collect(), groups: vec![], margin: 0.5,
        }
    }

    #[test]
    fn four_nets_in_reverse_order_are_uncrossed() {
        let pb = reversed_four();
        let pr = Params { w: [5.0, 3.0, 0.0, 0.25, 0.005], seeds: 3, moves: 400, t0: 1.0, t1: 0.02, budget_ms: 60000.0,
                          step_ms: 0.0, seed_key: 7 };
        let (base, _, results, out, first, problems) = search(&pb, &[0], &[vec![(0, 0.0, false)]], &pr);
        assert_eq!((base.2, out, first, problems.len()), (6, false, true, 0));
        assert_eq!(results[0].1 .2, 0);
        assert_eq!(results[0].2, vec![vec![3], vec![2], vec![1], vec![0]]);
    }
}
```

Run: `cd native && nice cargo test --release --lib pinmap; cd ..`
Expected: PASS (6 tests: 3 of the core, 3 of the geometry).

- [ ] **Step 3: Expose it to Python**

In `native/src/lib.rs`, before the line `/// The occupancy's placed ratsnest, mirrored for \`leaf_costs\``, add:

```rust
/// The pin map study's core (native/src/pinmap.rs): one group's study from plain arrays, as
/// `placemat.pinmap_twin.search` gives it (`placemat.pinmap_core.search` picks one or the other).
#[pyfunction]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn pinmap_search(
    parts: Vec<pinmap::Row>,
    pins: Vec<Vec<pinmap::Row>>,
    nets: Vec<(String, u8)>,
    fixed: Vec<Vec<(f64, f64, String, String)>>,
    joined: Vec<Vec<(usize, usize)>>,
    ends: Vec<Vec<(usize, usize)>>,
    wires: Vec<(u8, i64, i64, i64, i64)>,
    movable: Vec<(usize, usize, Vec<usize>, i64)>,
    groups: Vec<(usize, Vec<i64>, Vec<Vec<usize>>)>,
    group_parts: Vec<usize>,
    combos: Vec<Vec<(usize, f64, bool)>>,
    weights: (f64, f64, f64, f64, f64),
    params: (f64, u32, u32, f64, f64, f64, f64, u64),
) -> pinmap::SearchResult {
    let (pair, impedance, plane, length, bend) = weights;
    let (margin, seeds, moves, t0, t1, budget_ms, step_ms, seed_key) = params;
    let pb = pinmap::Problem { parts, pins, nets, fixed, joined, ends, wires, movable, groups, margin };
    let pr = pinmap::Params { w: [pair, impedance, plane, length, bend], seeds, moves, t0, t1, budget_ms, step_ms, seed_key };
    pinmap::search(&pb, &group_parts, &combos, &pr)
}

```

(pyo3 takes a tuple of at most 12 items as one argument: hence two.) After `    m.add_class::<NativeRatsnest>()?;` add:

```rust
    m.add_function(wrap_pyfunction!(pinmap_search, m)?)?;
```

Run: `cd native && nice cargo clippy --release 2>&1 | grep -A3 "src/pinmap"; cd ..`
Expected: nothing (no new warning in the pin map files).

- [ ] **Step 4: Write the Python side's failing tests**

Create `tests/test_pinmap_core.py`:

```python
"""The pin map study's core, through its one entry point (pinmap_core.study_group): the score of the present map, a
first map by minimum-cost matching, then moves, swaps and group moves under the constraints, per pose; deterministic;
stopped by its clock with the best found. Each test runs on every core in CORES: the native one (skipped when the
native module is not in use) and, from the Python twin's task on, the twin."""
import pytest

from placemat.pinmap_core import native_core, poses_of, problem_of, study_group
from placemat.pinmap_input import build, placed_from_geometry
from tests.fixtures import board_geometry, footprint, track
from tests.pinmap_boards import input_of, point_pad, quad, quad_footprint, reversed_four, settings

CORES = ["native"]


@pytest.fixture(params=CORES)
def native(request):
    if request.param == "native" and native_core() is None:
        pytest.skip("the native module is not in use")
    return request.param == "native"


def run(inp, native, s=None, refs=("U1",), step_ms=0.0, budget_ms=None):
    return study_group(inp, refs, s or settings(), step_ms=step_ms, budget_ms=budget_ms, native=native)


def best(g):
    return min(g.results, key=lambda r: r.breakdown.total)


def pin(result, net, ref="U1"):
    return dict(result.assign[net])[ref]


def test_four_nets_in_reverse_order_cross_six_times_and_are_uncrossed_at_the_present_rotation(native):
    inp, _ = input_of(*reversed_four())
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    r = g.results[0]
    assert (g.present.among, g.present.against, g.present.weighted) == (6, 0, 6.0)
    assert r.breakdown.among == 0 and [pin(r, n) for n in "ABCD"] == ["4", "3", "2", "1"]
    s = settings()
    assert r.breakdown.total == pytest.approx(s.pins_length_weight * r.breakdown.length_mm
                                              + s.pins_bend_weight * r.breakdown.bend_deg)


def test_each_constraint_holds_fixed_allow_deny_and_a_group_kept_whole_and_in_order(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D", "E", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinFixed": "1", "Pm.PinAllow": "B:2,3", "Pm.PinDeny": "C:3",
                     "Pm.PinGroup": "bus:4-5"})
    for i, net in enumerate(["A", "B", "C", "D", "E"]):
        pads += point_pad("T%d" % i, net, 20, 12.5 - i)                 # every target in reverse order
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    r = g.results[0]
    assert pin(r, "A") == "1" and pin(r, "B") in ("2", "3") and pin(r, "C") != "3"
    d, e = int(pin(r, "D")), int(pin(r, "E"))
    assert e == d + 1                                                   # the group moved whole, in its order
    assert r.breakdown.total < g.present.total


def test_a_net_whose_target_is_behind_the_part_is_moved_to_the_side_that_faces_it(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""], "W": ["", ""]}, {"Pm.PinPool": "1-4"})
    pads += point_pad("T1", "A", 0, 10)
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    assert pin(g.results[0], "A") in ("3", "4")
    assert g.present.length_mm > g.results[0].breakdown.length_mm + 4.0     # the way round the body is gone
    (before,) = g.present_paths["A"]
    assert len(before) == 4                                             # exit, two corners, target


def test_a_net_of_several_pads_is_scored_on_its_tree_with_the_studied_pin_at_its_exit(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("T1", "A", 20, 9.5) + point_pad("T2", "A", 30, 9.5)
    inp, _ = input_of(pads, {"U1": u1})
    g = run(inp, native, settings(pins_rotations=(0.0,)))
    assert sorted(tuple(sorted(p)) for p in g.present_paths["A"]) == [((12.75, 9.5), (20.0, 9.5)), ((20.0, 9.5), (30.0, 9.5))]
    assert g.present.length_mm == pytest.approx(17.25) and g.present.bend_deg == 0.0


def test_a_diagonal_turn_wins_on_the_bend_when_it_is_listed_and_is_not_reported_when_it_is_not(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("T1", "A", 22, -2)
    inp, _ = input_of(pads, {"U1": u1})
    eighths = run(inp, native, settings(pins_rotations=tuple(range(0, 360, 45))))
    b = best(eighths)
    assert b.poses == (("U1", 45.0, False),) and b.breakdown.bend_deg < 5.0
    quarters = run(inp, native)
    assert {p[1] for r in quarters.results for p in r.poses} == {0.0, 90.0, 180.0, 270.0}


def test_the_other_face_is_studied_only_when_asked_and_the_part_may_stand_there(native):
    pads, u1 = quad("U1", 10, 10, {"E": ["A", ""]}, {"Pm.PinPool": "1-2"}, may_flip=True)
    pads += point_pad("T1", "A", 22, 10)
    inp, _ = input_of(pads, {"U1": u1})
    assert poses_of(inp.parts[0], settings()) == [(0.0, False), (90.0, False), (180.0, False), (270.0, False)]
    assert (90.0, True) in poses_of(inp.parts[0], settings(pins_faces=True))
    g = run(inp, native, settings(pins_faces=True))
    assert g.of == 8 and any(p[2] for r in g.results for p in r.poses)


def test_the_present_pose_comes_first_and_each_turn_is_studied_once_however_the_turns_are_written():
    inp, _ = input_of(*reversed_four())
    assert poses_of(inp.parts[0], settings(pins_rotations=(360, -90, 90.0, 90))) == [(0.0, False), (270.0, False), (90.0, False)]


def test_the_same_board_gives_the_same_maps_and_totals(native):
    inp, _ = input_of(*reversed_four())
    a, b = run(inp, native), run(inp, native)
    assert [(r.poses, r.breakdown, r.assign) for r in a.results] == [(r.poses, r.breakdown, r.assign) for r in b.results]


def test_a_clock_out_before_the_first_map_says_so_and_one_out_later_keeps_the_best_found(native):
    inp, _ = input_of(*reversed_four())
    s = settings(pins_anneal_moves=500, pins_seeds=4)                   # 64 questions a pose: more than the budget
    g = run(inp, native, s, step_ms=1.0, budget_ms=0.5)                 # out at the first question
    assert (g.first_map, g.budget_out, g.results) == (False, True, ())
    g = run(inp, native, s, step_ms=1.0, budget_ms=40)                  # out after 40 questions
    assert g.first_map and g.budget_out and 1 <= len(g.results) < 4 and g.searched == len(g.results) and g.of == 4


def test_a_routed_board_scores_as_the_same_board_without_its_copper(native):
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"}),
           footprint("R1", 20, 10.5, w=2, h=1, inst="r1", nets=("A", "N1")),
           footprint("R2", 20, 9.5, w=2, h=1, inst="r2", nets=("B", "N2"))]
    a1, r1 = fps[0].pads[0].airwire_end, fps[1].pads[0].airwire_end
    routed = board_geometry(fps, copper=[track("A", a1.x, a1.y, r1.x, r1.y)], width=40, height=40)
    bare = board_geometry(fps, width=40, height=40)
    present = []
    for g in (routed, bare):
        inp, _ = build(*placed_from_geometry(g), {}, frozenset(), {}, g.netclasses)
        present.append(run(inp, native, settings(pins_rotations=(0.0,))).present)
    assert present[0] == present[1] and present[0].among == 1           # A still has its airwire, and it crosses B's


def test_the_core_takes_the_study_as_plain_arrays():
    inp, _ = input_of(*reversed_four({"Pm.PinPool": "1-4", "Pm.PinGroup": "ab:1-2"}))
    pb = problem_of(inp, 0.5)
    assert pb.parts == [("U1", 10.0, 10.0, 2.25, 2.25)] and [p[0] for p in pb.pins[0]] == ["1", "2", "3", "4"]
    assert pb.nets == [("A", 0), ("B", 0), ("C", 0), ("D", 0)] and pb.ends == [[(0, 0)], [(0, 1)], [(0, 2)], [(0, 3)]]
    assert pb.movable == [(0, 0, [0, 1, 2, 3], 0), (1, 0, [0, 1, 2, 3], 0), (2, 0, [0, 1, 2, 3], -1), (3, 0, [0, 1, 2, 3], -1)]
    assert pb.groups == [(0, [0, 1], [[0, 1], [1, 2], [2, 3]])]
    assert pb.fixed[0] == [(20.0, 11.5, "TP4", "1")] and pb.wires == []
```

- [ ] **Step 5: Build the module and watch the tests fail**

Run: `uv pip install -e ".[native]"` (it builds the module from this checkout, so its version is placemat's and `geometry.native_status()` takes it), then `.venv/bin/python -c "from placemat.geometry import native_status; print(native_status().facts())"`.
Expected: `in_use: True`.

Run: `.venv/bin/python -m pytest tests/test_pinmap_core.py -q -n 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap_core'`.

- [ ] **Step 6: The entry point**

Create `src/placemat/pinmap_core.py`:

```python
"""The pin map study's core, as one entry point: a study as plain arrays (`Problem`), searched by the native core
(native/src/pinmap.rs, `placemat_native.pinmap_search`) when the native module is in use, else by its Python twin
(pinmap_twin.py), which gives the same answers. Around it: the arrays from a StudyInput, the poses a part is studied at,
and the core's answer turned back into names (`study_group`)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools

from . import geometry as _geometry
from .pinmap_rules import natural
from .ratsnest import _nm

KIND_CODES = {"plain": 0, "pair": 1, "impedance": 2, "plane": 3}


@dataclass(frozen=True)
class Problem:
    """A study as the core takes it. `parts` (ref, cx, cy, hw, hh) and `pins` per part (number, x, y, nx, ny) in
    natural pad order; `nets` (name, kind code), and per net its `fixed` anchors (x, y, ref, number), `joined` pairs of
    them and its `ends` (part, pin) as they stand, one per end slot; `wires` the other airwires (kind code, ax, ay, bx,
    by) in nm; `movable` (net, slot, allowed pins, group or -1); `groups` (part, member movables or -1, windows of
    pins); `margin` the exit distance."""
    parts: list
    pins: list
    nets: list
    fixed: list
    joined: list
    ends: list
    wires: list
    movable: list
    groups: list
    margin: float


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


@dataclass(frozen=True)
class PoseResult:
    """The best found at one pose of each part of a group: `poses` ((ref, turn, flip), ...), its score, `assign`
    {net: ends ((ref, pad number), ...)} for every studied net, and `paths` {net: [path, ...]} of the group's nets."""
    poses: tuple
    breakdown: Breakdown
    assign: dict
    paths: dict


@dataclass(frozen=True)
class GroupResult:
    refs: tuple
    present: Breakdown
    present_assign: dict
    present_paths: dict
    results: tuple
    searched: int
    of: int
    budget_out: bool
    first_map: bool
    problems: tuple = ()        # (ref, net) a matching could not place


def problem_of(inp, margin: float) -> Problem:
    """The arrays of a StudyInput (pinmap_input)."""
    parts = [(p.ref, p.cx, p.cy, p.hw, p.hh) for p in inp.parts]
    part_at = {p.ref: i for i, p in enumerate(inp.parts)}
    pins, pin_at = [], []
    for p in inp.parts:
        ordered = sorted(p.pins, key=lambda q: natural(q.number))
        pins.append([(q.number, q.x, q.y, q.nx, q.ny) for q in ordered])
        pin_at.append({q.number: k for k, q in enumerate(ordered)})
    nets = [(n.net, KIND_CODES[n.kind]) for n in inp.nets]
    net_at = {n.net: i for i, n in enumerate(inp.nets)}
    fixed = [[(a.x, a.y, a.ref, a.number) for a in n.fixed] for n in inp.nets]
    joined = [list(n.joined) for n in inp.nets]
    ends = [[(part_at[r], pin_at[part_at[r]][num]) for r, num in n.ends] for n in inp.nets]
    wires = [(KIND_CODES[w.kind], _nm(w.a[0]), _nm(w.a[1]), _nm(w.b[0]), _nm(w.b[1])) for w in inp.background]
    movable, groups, mv_at = [], [], {}
    for pi, p in enumerate(inp.parts):
        slots = p.slots
        group_of = {n: g for g, (_, gnets) in enumerate(slots.groups) for n in gnets if n}
        first_group = len(groups)
        for net in slots.movable:
            ni = net_at[net]
            slot = next(k for k, (r, _) in enumerate(ends[ni]) if r == pi)
            mv_at[(pi, net)] = len(movable)
            movable.append((ni, slot, [pin_at[pi][q] for q in slots.allowed[net]],
                            first_group + group_of[net] if net in group_of else -1))
        for name, gnets in slots.groups:
            groups.append((pi, [mv_at[(pi, n)] if n else -1 for n in gnets],
                           [[pin_at[pi][q] for q in w] for w in slots.windows.get(name, ())]))
    return Problem(parts, pins, nets, fixed, joined, ends, wires, movable, groups, margin)


def poses_of(part, settings) -> list:
    """The (turn, flip) a part is studied at: its present pose first, each of `pins.rotations` as a turn from where it
    stands (mod 360, each once), then the same on the other face when `pins.faces` is true and the part may stand
    there."""
    turns = [0.0]
    for t in settings.pins_rotations:
        t = float(t) % 360.0
        if t not in turns:
            turns.append(t)
    out = [(t, False) for t in turns]
    if settings.pins_faces and part.may_flip:
        out += [(t, True) for t in turns]
    return out


def seed_key(refs) -> int:
    """The study's random streams' key: from the parts' refs, so a board gives the same map every time."""
    return int.from_bytes(hashlib.sha256(",".join(refs).encode()).digest()[:8], "little")


def params_of(settings, refs, step_ms: float = 0.0, budget_ms: float | None = None) -> dict:
    return {"weights": (settings.pins_pair_weight, settings.pins_impedance_weight, settings.score_crossing_plane,
                        settings.pins_length_weight, settings.pins_bend_weight),
            "seeds": int(settings.pins_seeds), "moves": int(settings.pins_anneal_moves),
            "t0": float(settings.pins_anneal_start), "t1": float(settings.pins_anneal_end),
            "budget_ms": float(settings.pins_budget_ms * len(refs) if budget_ms is None else budget_ms),
            "step_ms": float(step_ms), "seed_key": seed_key(refs)}


def native_core():
    """The native core when the native module is in use and has it, else None."""
    native = _geometry._native
    return native if native is not None and hasattr(native, "pinmap_search") else None


def search(pb: Problem, group_parts: list, combos: list, params: dict, native=True) -> tuple:
    """The one entry point: (present breakdown, present paths, [(combo, breakdown, assignment, paths)], budget_out,
    first_map, [(part, net)]), from the native core when it is in use (and `native`), else the Python twin."""
    core = native_core() if native else None
    if core is None:
        raise RuntimeError("the pin map study's core is the native module's until its Python twin is in: build it with "
                           "`uv pip install -e \".[native]\"`")
    w = params["weights"]
    return core.pinmap_search(
        pb.parts, pb.pins, pb.nets, pb.fixed, pb.joined, pb.ends, pb.wires,
        [(n, s, list(a), g) for n, s, a, g in pb.movable], [(p, list(m), [list(x) for x in ws]) for p, m, ws in pb.groups],
        list(group_parts), [[(p, float(t), bool(f)) for p, t, f in c] for c in combos],
        tuple(w), (pb.margin, params["seeds"], params["moves"], params["t0"], params["t1"], params["budget_ms"],
                   params["step_ms"], params["seed_key"]))


def _breakdown(t) -> Breakdown:
    return Breakdown(t[0], int(t[1]), int(t[2]), t[3], t[4], t[5])


def study_group(inp, refs: tuple, settings, step_ms: float = 0.0, budget_ms: float | None = None, native=True,
                pb: Problem | None = None) -> GroupResult:
    """The study of one group of parts: every combination of their poses (the present first, at most
    `pins.joint_combinations`), each from its first map through the local search, in the core."""
    pb = pb or problem_of(inp, settings.pins_exit_mm)
    part_at = {p.ref: i for i, p in enumerate(inp.parts)}
    group_parts = [part_at[r] for r in refs]
    lists = [[(part_at[r], t, f) for t, f in poses_of(inp.part(r), settings)] for r in refs]
    combos = [list(c) for c in itertools.islice(itertools.product(*lists), max(int(settings.pins_joint_combinations), 1))]
    total = 1
    for l in lists:
        total *= len(l)
    base, base_paths, results, out, first, problems = search(pb, group_parts, combos, params_of(settings, refs, step_ms,
                                                                                                  budget_ms), native)

    def assign_of(pins) -> dict:
        return {pb.nets[n][0]: tuple((pb.parts[pb.ends[n][k][0]][0], pb.pins[pb.ends[n][k][0]][q][0])
                                     for k, q in enumerate(qs)) for n, qs in enumerate(pins)}

    def paths_of(ps) -> dict:
        return {pb.nets[n][0]: [[tuple(p) for p in path] for path in paths] for n, paths in ps}
    present = [[q for _, q in pb.ends[n]] for n in range(len(pb.nets))]
    rows = tuple(PoseResult(tuple((pb.parts[p][0], t, f) for p, t, f in combos[k]), _breakdown(b), assign_of(pins),
                            paths_of(ps)) for k, b, pins, ps in results)
    return GroupResult(tuple(refs), _breakdown(base), assign_of(present), paths_of(base_paths), rows, len(rows), total,
                       bool(out), bool(first), tuple((pb.parts[p][0], pb.nets[n][0]) for p, n in problems))
```

- [ ] **Step 7: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_core.py tests/test_pinmap_input.py tests/test_pinmap_rules.py tests/test_native_import.py tests/test_native_status.py -q -n 2`
Expected: PASS (11 core tests on the native core; none skipped).

- [ ] **Step 8: Commit**

```bash
git add native/src/pinmap.rs native/src/lib.rs src/placemat/pinmap_core.py tests/test_pinmap_core.py
git commit -m "Native: the pin map study's core - crossing counts, the score and the annealing search from plain arrays"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 6: Bench the native core on the reference board, and set the defaults or stop

**Files:**
- Create: `fixtures/pinmap/reference.json` (the reference case: a laid fixture board, its plane nets, and its MCU's pin annotations - which live only here)
- Create: `fixtures/pinmap_bench.py`
- Test: `tests/test_pinmap_real.py`
- Modify (if the rule says set): `src/placemat/settings.py` (the defaults of `pins_anneal_moves`, `pins_seeds`, `pins_budget_ms`), `tests/test_pinmap_settings.py`, `skills/placemat/references/api.md` (the generated settings table), `tests/slow_tests.txt`

**Interfaces:**
- Consumes: Task 5's `pinmap_core.problem_of`, `study_group`, `native_core`; Task 3's `build`, `placed_from_geometry`; `kicad.read.read_board`; `pairs.board_pairs`.
- Produces: `fixtures/pinmap_bench.py` with `annotated(geometry, parts)`, `cases()`, `board_of(case)`, `input_of(case)`, `run_case(case, settings, repeat) -> dict`, `main(argv)`; the measurements in `$SCRATCH/pinmap-bench.txt`; the shipped defaults (or a stop).

The reference board is a laid board among the existing fixtures (the path in `reference.json`) whose 56-pin MCU carries 23 signal nets on its general-purpose pins and five unconnected pins, with nets routed already (so the "scored as unrouted" path is exercised). The annotations were chosen from the pads' nets as read while planning: pool pads 6-19, 21-24, 27, 38-45, 47-48; pad 8 (a strap) fixed; one net allowed only on pads 6-15; the two-wire bus pair a group; the ground and the 3.3 V net are its plane nets.

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
read as its file has it, its parts given the fixture's pin annotations (no capture carries them), and the study's core
run on each annotated part, `--repeat` times. Prints, per case, the median seconds per studied part against
`pins.budget_ms`, whether the native core ran, whether the clock ran out, and the present and best totals; with
`--long`, the best a long search finds too, the mark the default search effort is judged against.

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


def input_of(case):
    """The case's board read and annotated, as the study's input."""
    from placemat.pairs import board_pairs
    from placemat.pinmap_input import build, placed_from_geometry
    g = board_of(case)
    inp, _ = build(*placed_from_geometry(g), g.pin_names, frozenset(case["quiet"]), board_pairs(g.netclasses),
                   g.netclasses)
    return inp


def run_case(case, settings, repeat: int) -> dict:
    """The study of each of the case's annotated parts, `repeat` times: the median seconds a part, and the last run's
    present and best totals, the best pose and whether the clock ran out."""
    from placemat.pinmap_core import native_core, problem_of, study_group
    inp = input_of(case)
    pb = problem_of(inp, settings.pins_exit_mm)
    times, out = [], {}
    for _ in range(repeat):
        t0 = time.perf_counter()
        groups = [study_group(inp, (ref,), settings, pb=pb) for ref in sorted(case["parts"])]
        times.append((time.perf_counter() - t0) / len(groups))
        g = groups[0]
        best = min(g.results, key=lambda r: r.breakdown.total) if g.results else None
        out = {"present": round(g.present.total, 3), "best": round(best.breakdown.total, 3) if best else None,
               "pose": [t for _, t, _ in best.poses] if best else None, "budget_out": g.budget_out,
               "native": native_core() is not None}
    return dict(out, seconds_per_part=round(statistics.median(times), 3))


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
        line = "%s: %.3f s a part (budget %d ms, native %s), present %s, best %s at %s, clock ran out: %s" % (
            case["name"], got["seconds_per_part"], settings.pins_budget_ms, got["native"], got.get("present"),
            got.get("best"), got.get("pose"), got.get("budget_out"))
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
best map beats the present one inside `pins.budget_ms`, and no board item moves."""
import hashlib
import importlib.util
from pathlib import Path

from placemat.settings import Settings
from tests.conftest import needs_kicad

BENCH = Path(__file__).resolve().parents[1] / "fixtures" / "pinmap_bench.py"


def bench():
    spec = importlib.util.spec_from_file_location("pinmap_bench", BENCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_kicad
def test_on_a_real_board_the_best_map_beats_the_present_one_inside_its_budget_and_nothing_moves():
    from placemat.kicad.read import read_board
    from placemat.pinmap_core import study
    b = bench()
    case = b.cases()[0]
    pcb = b.HERE / case["board"]
    digest = hashlib.sha256(pcb.read_bytes()).hexdigest()
    inp = b.input_of(case)
    (g,) = study(inp, Settings())
    best = min(g.results, key=lambda r: r.breakdown.total)
    assert best.breakdown.total < g.present.total and g.budget_out is False and g.searched == g.of
    assert hashlib.sha256(pcb.read_bytes()).hexdigest() == digest
    where = lambda geometry: [(fp.ref, fp.location, fp.rotation, fp.face) for fp in geometry.footprints]
    assert where(read_board(pcb)) == where(b.board_of(case))
```

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_pinmap_real.py -q`
Expected: FAIL on `g.budget_out is False`: the provisional effort (500 moves, 4 seeds, four poses) takes longer than the provisional 400 ms.

- [ ] **Step 3: Measure the native core against a long search**

Run each line, one at a time, appending to `$SCRATCH/pinmap-bench.txt`:

```bash
L=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock
flock $L .venv/bin/python fixtures/pinmap_bench.py --repeat 1 --long --set pins_budget_ms=600000 | tee -a $SCRATCH/pinmap-bench.txt
for m s in 100 1 100 2 200 2 500 2 500 4; do
  flock $L .venv/bin/python fixtures/pinmap_bench.py --repeat 3 --set pins_budget_ms=600000 --set pins_anneal_moves=$m --set pins_seeds=$s \
    | sed "s/^/moves $m seeds $s: /" | tee -a $SCRATCH/pinmap-bench.txt
done
```

(The `for m s in` pairs loop is zsh's, the user's shell. Every line must say `native True`; if one says `native False`, the module is not in use - rebuild it as in Task 5 Step 5 - and measure again.)

Expected, as measured while planning (native core, this machine; yours will differ a little): present total 1437.9; long search (4000 moves, 4 seeds) best 1247.2; and

| moves, seeds | seconds a part | best total |
|---|---|---|
| 100, 1 | 0.12 | 1271.9 |
| 100, 2 | 0.21 | 1271.9 |
| 200, 2 | 0.32 | 1270.1 |
| 500, 2 | 0.52 | 1262.1 |
| 500, 4 | 0.69 | 1252.5 |

(For comparison, the same search in Python took 0.45 s at 100, 1 and 1.14 s at 200, 2: the native core is about four to five times faster, with the same maps.)

- [ ] **Step 4: Decide**

From `$SCRATCH/pinmap-bench.txt`:

1. The effort `(M, N)` is the cheapest (moves, seeds) whose best total is within 2% of the long search's best (at or under 1.02 times it).
2. The budget `B` is that effort's seconds a part times 1.5, in milliseconds, rounded up to a multiple of 50 (headroom for a machine slower than this one).
3. The core meets the budget when `B` is at most 500 ms (the spec aims it at a few hundred ms).

Write the decision as the last line of `$SCRATCH/pinmap-bench.txt`: `decision: set moves <M> seeds <N> budget <B>` or `decision: stop`.

With the planning numbers: within 2% means at or under 1272.1, so `(100, 1)` at 0.12 s; `B = 200`; it meets the budget: set.

**If the decision is `stop`:** do not change the settings and do not go on to Task 7. Commit only `fixtures/pinmap/reference.json` and `fixtures/pinmap_bench.py`, with Step 7's message, and report the table, the long search's best and the cheapest effort's seconds a part to the user, saying the native core does not meet a few hundred ms within 2% of a long search on the reference board.

- [ ] **Step 5: Set the defaults**

In `src/placemat/settings.py`, replace the first argument of `S(...)` in `pins_anneal_moves: int = S(500, "count", ...)` with `M`, in `pins_seeds: int = S(4, "count", ...)` with `N`, and in `pins_budget_ms: int = S(400, "ms", ...)` with `B`; nothing else in those lines changes. With the planning numbers the three lines start:

```python
    pins_seeds: int = S(1, "count",
    pins_anneal_moves: int = S(100, "count",
    pins_budget_ms: int = S(200, "ms",
```

In `tests/test_pinmap_settings.py`, in `test_every_pins_setting_has_its_default`, change the expected `pins_seeds`, `pins_anneal_moves` and `pins_budget_ms` to `N`, `M` and `B` (with the planning numbers: `((0.0, 90.0, 180.0, 270.0), 1, 100, 1.0, 0.02)` and `(200, 64, False, 0.05, 3, 5000)`).

Regenerate the api.md table with Task 1's Step 4 command.

Add to `tests/slow_tests.txt`:

```
tests/test_pinmap_real.py::test_on_a_real_board_the_best_map_beats_the_present_one_inside_its_budget_and_nothing_moves
```

- [ ] **Step 6: Run the tests to watch them pass**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_pinmap_real.py -q` and `.venv/bin/python -m pytest tests/test_pinmap_settings.py tests/test_settings_docs.py tests/test_pinmap_core.py -q -n 2`
Expected: PASS. (The core tests that time a clock give their own effort, so a smaller default does not change them.) If the real-board test fails on `budget_out`, this machine was busier than when it was measured: measure the chosen effort again (Step 3, that line only) and recompute `B`; do not raise `B` past what a measurement supports.

- [ ] **Step 7: Commit**

```bash
git add fixtures/pinmap/reference.json fixtures/pinmap_bench.py tests/test_pinmap_real.py src/placemat/settings.py tests/test_pinmap_settings.py skills/placemat/references/api.md tests/slow_tests.txt
{ echo "Bench: the pin map study's native core on the reference board, and its defaults"; echo; grep -E "^(mcu|moves|decision)" $SCRATCH/pinmap-bench.txt; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 7: The Python twin of the native core

The study must run where the native module is not in use (`geometry.native_status()` says why: not installed, a version mismatch, `PLACEMAT_NATIVE=0`), as every native path in placemat does. The twin is the same algorithm on the same arrays, written so the two agree to the last bit: plain sums in order, CPython's `math.hypot` (which `exact::hypot` copies), `math.radians` and `math.degrees`, the same SplitMix64 stream, the same counted clock. Its tests follow the project's "native X is the Python X" tests (`tests/test_native_mst.py`): the same inputs through both, compared exactly.

**Files:**
- Create: `src/placemat/pinmap_geom.py` (the airwire model's twin)
- Create: `src/placemat/pinmap_twin.py` (the core's twin)
- Modify: `src/placemat/pinmap_core.py` (`search` falls back to the twin)
- Modify: `tests/test_pinmap_core.py` (`CORES` gains "python")
- Test: `tests/test_pinmap_geom.py`, `tests/test_pinmap_twin.py`, `tests/test_native_pinmap.py`

**Interfaces:**
- Consumes: Task 5's `Problem`, `search`, `params_of`, `poses_of`, `problem_of`, `native_core`; `ratsnest.mst`, `ratsnest._cross_nm`, `ratsnest._nm`, `ratsnest.Anchor`.
- Produces: `pinmap_geom.Pose`, `Exit`, `exit_of`, `through`, `round_body`, `route`, `length`, `bend` (Python, the Rust model's twin); `pinmap_twin.SplitMix64`, `stream_seed`, `Clock(budget_ms, step_ms=0.0)`, `crossing(w, a, b)`, `segments(paths)`, `Background`, `segments_crossing`, `Scorer`, `Tally`, `hungarian`, `first_map`, `anneal`, `search(pb, group_parts, combos, params)` (returns what `placemat_native.pinmap_search` returns); `pinmap_core.search(..., native=False)` and any call without the native module go to the twin.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_geom.py`:

```python
"""The pin map study's airwire model: a pin leaves along its outward normal to a point past the courtyard, then goes the
shorter way round the courtyard's box to its target; the bend is the angle between the normal and the bearing to the
target; a pose turns the part about its centre, and mirrors it for the other face."""
import pytest

from placemat.pinmap_geom import Pose, bend, exit_of, route, through

HW = HH = 2.0           # a 4 mm square body


def east_exit(pose=Pose(10, 10), y=0.5):
    return exit_of("U1", pose, 2.0, y, (1.0, 0.0), HW, HH, 0.5)


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

Create `tests/test_pinmap_twin.py`:

```python
"""The Python twin of the pin map study's core, its own parts: the random stream, the crossing weights, the background
grid, the matching, the incremental tally (a move priced as the whole total would price it) and the counted clock."""
import random

import pytest

from placemat.pinmap_core import Problem, problem_of
from placemat.pinmap_geom import Pose
from placemat.pinmap_twin import Background, Clock, Scorer, SplitMix64, Tally, crossing, hungarian, segments
from tests.pinmap_boards import input_of, point_pad, quad, settings

W = (5.0, 3.0, 0.25, 0.25, 0.005)           # pair, impedance, plane, length, bend


def test_the_random_stream_is_splitmix64():
    r = SplitMix64(1234567)
    assert (r.next(), r.next()) == (6457827717110365317, 3203168211198807973)
    assert 0 <= r.unit() < 1 and 0 <= r.below(7) < 7


def test_a_crossing_counts_one_more_for_a_pair_or_a_controlled_impedance_and_the_plane_weight_for_a_plane():
    assert crossing(W, 0, 0) == 1.0
    assert crossing(W, 0, 1) == 5.0 and crossing(W, 2, 0) == 3.0 and crossing(W, 1, 2) == 5.0
    assert crossing(W, 3, 1) == 0.25


def test_the_background_counts_the_wires_a_path_crosses_and_drops_a_weightless_plane():
    nm = lambda v: int(round(v * 1e6))
    wires = [(0, nm(5), 0, nm(5), nm(10)), (1, nm(7), 0, nm(7), nm(10)), (3, nm(8), 0, nm(8), nm(10))]
    segs = segments([((0.0, 5.0), (10.0, 5.0))])
    assert Background(wires, (5.0, 3.0, 0.0, 0.0, 0.0)).cross(0, segs) == (6.0, 2)
    assert Background(wires, (5.0, 3.0, 0.5, 0.0, 0.0)).cross(0, segs) == (6.5, 3)


def test_the_matching_is_the_cheapest_and_refuses_what_cannot_be_matched():
    inf = float("inf")
    assert hungarian([[4, 1, 3], [2, 0, 5], [3, 2, 2]]) == [1, 0, 2]
    assert hungarian([[1, 2, 3], [1, 2, 3]]) == [0, 1]
    assert hungarian([[1, inf], [2, inf]]) is None
    assert hungarian([]) == []


def test_a_move_is_priced_by_recounting_the_nets_it_touches_as_the_whole_total_would():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C"], "S": ["D", "E", ""], "W": ["F", "", ""]}, {"Pm.PinPool": "1-9"})
    rng = random.Random(1)
    for i, net in enumerate("ABCDEF"):
        pads += point_pad("T%d" % i, net, rng.uniform(0, 25), rng.uniform(0, 25))
    pads += point_pad("Q1", "X", 0, 0) + point_pad("Q2", "X", 25, 25)
    pb = problem_of(input_of(pads, {"U1": u1})[0], 0.5)
    sc = Scorer(pb, [Pose(10.0, 10.0)], W, Background(pb.wires, W))
    tally = Tally(sc, [tuple(q for _, q in e) for e in pb.ends])
    for _ in range(40):
        a, b = rng.sample(range(len(pb.nets)), 2)
        change = {a: tally.assign[b], b: tally.assign[a]} if rng.random() < 0.5 else {a: (rng.randrange(9),)}
        d = tally.delta(change)
        after = list(tally.assign)
        for n, pins in change.items():
            after[n] = pins
        assert d == pytest.approx(sc.total(after)[0] - sc.total(tally.assign)[0], abs=1e-9)
        tally.apply(change, d)
    assert tally.value == pytest.approx(sc.total(tally.assign)[0], abs=1e-6)


def test_a_counted_clock_runs_out_after_its_budget_in_steps():
    c = Clock(3.0, step_ms=1.0)
    assert [c.out() for _ in range(4)] == [False, False, True, True]
    assert isinstance(Problem([], [], [], [], [], [], [], [], [], 0.5), Problem)
```

Create `tests/test_native_pinmap.py`:

```python
"""The native pin map core is the Python twin: on the same arrays, seeds and counted clock, the same present score, the
same best map per pose with the same tallies to the last bit, the same airwires, the same clock outcome."""
import itertools
import json
import random

import pytest

from placemat.pinmap_core import native_core, params_of, poses_of, problem_of, search
from tests.pinmap_boards import input_of, point_pad, quad, reversed_four, settings

pytestmark = pytest.mark.skipif(native_core() is None, reason="the native module is not in use or predates the pin map core")


def both(inp, refs, s, step_ms=0.0):
    pb = problem_of(inp, s.pins_exit_mm)
    at = {p.ref: i for i, p in enumerate(inp.parts)}
    lists = [[(at[r], t, f) for t, f in poses_of(inp.part(r), s)] for r in refs]
    combos = [list(c) for c in itertools.islice(itertools.product(*lists), s.pins_joint_combinations)]
    pr = params_of(s, refs, step_ms)
    norm = lambda x: json.loads(json.dumps(x))
    return (norm(search(pb, [at[r] for r in refs], combos, pr, native=True)),
            norm(search(pb, [at[r] for r in refs], combos, pr, native=False)))


def constrained():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D", "E", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinFixed": "1", "Pm.PinAllow": "B:2,3", "Pm.PinDeny": "C:3",
                     "Pm.PinGroup": "bus:4-5"})
    for i, net in enumerate("ABCDE"):
        pads += point_pad("T%d" % i, net, 20, 12.5 - i)
    return input_of(pads, {"U1": u1})[0]


def joint():
    p1, a = quad("U1", 10, 10, {"W": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"})
    p2, b = quad("U2", 20, 10, {"E": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"})
    return input_of(p1 + p2, {"U1": a, "U2": b})[0]


@pytest.mark.parametrize("case, refs", [("four", ("U1",)), ("constrained", ("U1",)), ("joint", ("U1", "U2"))])
@pytest.mark.parametrize("turns", [(0.0, 90.0, 180.0, 270.0), tuple(range(0, 360, 45))])
def test_the_native_core_is_the_twin_on_fixed_cases(case, refs, turns):
    inp = {"four": lambda: input_of(*reversed_four())[0], "constrained": constrained, "joint": joint}[case]()
    native, python = both(inp, refs, settings(pins_rotations=turns, pins_faces=True))
    assert native == python


def test_the_native_core_is_the_twin_when_the_clock_runs_out():
    native, python = both(input_of(*reversed_four())[0], ("U1",), settings(pins_budget_ms=40, pins_anneal_moves=500, pins_seeds=4),
                          step_ms=1.0)
    assert native == python and native[3] is True


@pytest.mark.parametrize("seed", range(12))
def test_the_native_core_is_the_twin_on_random_boards(seed):
    rng = random.Random(seed)
    nets = ["N%d" % i for i in range(rng.randint(3, 9))]
    sides = {s: [] for s in "ESWN"}
    for net in nets + [""] * rng.randint(0, 4):
        sides[rng.choice("ESWN")].append(net)
    pads, u1 = quad("U1", 15, 15, sides, {"Pm.PinPool": "1-%d" % (len(nets) + sum(1 for v in sides.values() for n in v if not n))},
                    body=rng.choice((4.0, 6.0)))
    for i, net in enumerate(nets):
        for k in range(rng.randint(1, 3)):
            pads += point_pad("T%d_%d" % (i, k), net, round(rng.uniform(0, 30), 2), round(rng.uniform(0, 30), 2))
    for k in range(rng.randint(0, 6)):
        pads += point_pad("Q%da" % k, "X%d" % k, round(rng.uniform(0, 30), 2), round(rng.uniform(0, 30), 2))
        pads += point_pad("Q%db" % k, "X%d" % k, round(rng.uniform(0, 30), 2), round(rng.uniform(0, 30), 2))
    inp, _ = input_of(pads, {"U1": u1})
    native, python = both(inp, ("U1",), settings(pins_anneal_moves=150, pins_seeds=2))
    assert native == python
```

In `tests/test_pinmap_core.py`, replace `CORES = ["native"]` with `CORES = ["native", "python"]`.

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_geom.py tests/test_pinmap_twin.py tests/test_native_pinmap.py tests/test_pinmap_core.py -q -n 2`
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap_geom'` (and `pinmap_twin`), and every `[python]` core test with the RuntimeError Task 5's `search` raises without its twin.

- [ ] **Step 3: The airwire model's twin**

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
    """The path's length, summed segment by segment in order (a plain sum: the native twin adds the same way)."""
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total


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

- [ ] **Step 4: The core's twin**

Create `src/placemat/pinmap_twin.py`:

```python
"""The pin map study's core in Python: the twin of the native core (native/src/pinmap.rs), used when the native module is
not in use. Same algorithm, same arrays, same answers: every float is added in the same order, the random stream is the
same SplitMix64, `math.hypot` is CPython's (which the native side copies bit for bit), and the angles go through
`math.radians` and `math.degrees` as CPython defines them.

It takes a study as plain arrays (pinmap_core.Problem) and, for the parts of one group and each combination of their
poses, returns the best assignment of the movable nets to pins with its tallies:

- score: weighted crossings of the studied nets' airwires against the board's other airwires (a 2 mm grid of them)
  and among themselves, plus `length` times their length in mm, plus `bend` times their summed bend in degrees. A
  net's airwires are the minimum spanning tree of its pads (ratsnest.mst), each studied pin at its exit point and
  each airwire to one taken round the body (pinmap_geom.route);
- incremental: a net's airwires, its crossings with the background and its crossings with each other net are kept per
  placing of its ends, so a move recounts only the nets it touches;
- search: a first map (each group on the cheapest run of pins that leaves the rest a matching, then a minimum-cost
  matching), then per seed `moves` moves, swaps and group moves under annealing from `t0` down to `t1`, checking the
  clock every 32 moves and between poses."""
from __future__ import annotations

import math

from .pinmap_geom import Pose, bend, exit_of, length, route
from .ratsnest import Anchor, _cross_nm, _nm, mst

_INF = float("inf")
CELL_NM = 2_000_000          # the background's grid, 2 mm, in whole nanometres
PLAIN, PAIR, IMPEDANCE, PLANE = 0, 1, 2, 3
_MASK = (1 << 64) - 1


class SplitMix64:
    """The random stream both twins draw from (Steele, Lea and Flood's SplitMix64)."""

    def __init__(self, seed: int):
        self.state = seed & _MASK

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & _MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n

    def unit(self) -> float:
        return (self.next() >> 11) * (1.0 / (1 << 53))


def stream_seed(seed_key: int, combo: int, seed: int) -> int:
    return (seed_key ^ (combo << 32) ^ seed) & _MASK


class Clock:
    """A budget in milliseconds. With `step_ms` above 0 it is a counted clock: each question advances it by that much
    (a test's, and the same in both twins); otherwise it reads the time."""

    def __init__(self, budget_ms: float, step_ms: float = 0.0):
        import time
        self.budget, self.step, self.elapsed = budget_ms, step_ms, 0.0
        self.start = time.perf_counter()

    def out(self) -> bool:
        import time
        if self.step > 0:
            self.elapsed += self.step
        else:
            self.elapsed = (time.perf_counter() - self.start) * 1000.0
        return self.elapsed >= self.budget


def crossing(w, a: int, b: int) -> float:
    """What a crossing of classes `a` and `b` counts: `w` (pair, impedance, plane, length, bend)."""
    if a == PLANE or b == PLANE:
        return w[2]
    x = w[0] if a == PAIR else w[1] if a == IMPEDANCE else 1.0
    y = w[0] if b == PAIR else w[1] if b == IMPEDANCE else 1.0
    return x if x >= y else y


def segments(paths) -> list:
    """Each path's segments in whole nanometres with their boxes: (ax, ay, bx, by, minx, miny, maxx, maxy)."""
    out = []
    for path in paths:
        for p, q in zip(path, path[1:]):
            ax, ay, bx, by = _nm(p[0]), _nm(p[1]), _nm(q[0]), _nm(q[1])
            out.append((ax, ay, bx, by, min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
    return out


def _box4(s):
    return (min(s[0], s[2]), min(s[1], s[3]), max(s[0], s[2]), max(s[1], s[3]))


class Background:
    """The board's other airwires, (kind, ax, ay, bx, by) in nm, on a 2 mm grid; a plane's are left out when they weigh
    nothing."""

    def __init__(self, wires, w):
        self.w = w
        self.wires = [x for x in wires if not (x[0] == PLANE and w[2] <= 0)]
        self.boxes = [_box4(x[1:]) for x in self.wires]
        self.grid: dict = {}
        for k, b in enumerate(self.boxes):
            for cx in range(b[0] // CELL_NM, b[2] // CELL_NM + 1):
                for cy in range(b[1] // CELL_NM, b[3] // CELL_NM + 1):
                    self.grid.setdefault((cx, cy), []).append(k)

    def cross(self, kind: int, segs) -> tuple:
        total, count = 0.0, 0
        for s in segs:
            near = set()
            for cx in range(s[4] // CELL_NM, s[6] // CELL_NM + 1):
                for cy in range(s[5] // CELL_NM, s[7] // CELL_NM + 1):
                    near.update(self.grid.get((cx, cy), ()))
            for k in sorted(near):
                t = self.boxes[k]
                if t[2] < s[4] or s[6] < t[0] or t[3] < s[5] or s[7] < t[1]:
                    continue
                x = self.wires[k]
                if _cross_nm(s[0], s[1], s[2], s[3], x[1], x[2], x[3], x[4]):
                    total += crossing(self.w, kind, x[0])
                    count += 1
        return total, count


def segments_crossing(a, b) -> int:
    n = 0
    for s in a:
        for t in b:
            if s[6] < t[4] or t[6] < s[4] or s[7] < t[5] or t[7] < s[5]:
                continue
            if _cross_nm(s[0], s[1], s[2], s[3], t[0], t[1], t[2], t[3]):
                n += 1
    return n


class Scorer:
    """Scores assignments at one set of poses. An assignment is a list, per net, of a tuple of pin indexes, one per end
    slot (the part of slot k is `ends[net][k][0]`)."""

    def __init__(self, pb, poses: list, w, bg: Background):
        self.pb, self.poses, self.w, self.bg = pb, poses, w, bg
        self._exits: dict = {}
        self._wires: dict = {}
        self._single: dict = {}
        self._pair: dict = {}

    def exit(self, part: int, pin: int):
        k = (part, pin)
        e = self._exits.get(k)
        if e is None:
            ref, _, _, hw, hh = self.pb.parts[part]
            _, x, y, nx, ny = self.pb.pins[part][pin]
            e = exit_of(ref, self.poses[part], x, y, (nx, ny), hw, hh, self.pb.margin)
            self._exits[k] = e
        return e

    def wires(self, net: int, pins: tuple):
        k = (net, pins)
        hit = self._wires.get(k)
        if hit is not None:
            return hit
        pb = self.pb
        fixed = pb.fixed[net]
        anchors = [Anchor(r, num, x, y) for x, y, r, num in fixed]
        exits = []
        for slot, pin in enumerate(pins):
            part = pb.ends[net][slot][0]
            e = self.exit(part, pin)
            exits.append(e)
            anchors.append(Anchor(pb.parts[part][0], pb.pins[part][pin][0], e.at[0], e.at[1]))
        index = {id(a): i for i, a in enumerate(anchors)}
        first = len(fixed)
        paths, bends = [], {}
        for edge in mst(pb.nets[net][0], anchors, pb.joined[net]):
            i, j = index[id(edge.a)], index[id(edge.b)]
            a = exits[i - first] if i >= first else (anchors[i].x, anchors[i].y)
            b = exits[j - first] if j >= first else (anchors[j].x, anchors[j].y)
            paths.append(route(a, b))
            for me, other in ((i, j), (j, i)):
                if me >= first:
                    e = exits[me - first]
                    d = bend(e.normal, e.at, (anchors[other].x, anchors[other].y))
                    bends[me] = min(bends.get(me, d), d)
        ln = 0.0
        for p in paths:
            ln += length(p)
        bd = 0.0
        for me in sorted(bends):
            bd += bends[me]
        segs = segments(paths)
        box = (min(s[4] for s in segs), min(s[5] for s in segs), max(s[6] for s in segs), max(s[7] for s in segs)) \
            if segs else (0, 0, 0, 0)
        hit = (paths, ln, bd, segs, box)
        self._wires[k] = hit
        return hit

    def single(self, net: int, pins: tuple) -> tuple:
        k = (net, pins)
        hit = self._single.get(k)
        if hit is None:
            _, ln, bd, segs, _ = self.wires(net, pins)
            weighted, count = self.bg.cross(self.pb.nets[net][1], segs)
            hit = (weighted + self.w[3] * ln + self.w[4] * bd, weighted, count)
            self._single[k] = hit
        return hit

    def pair(self, a: int, ea: tuple, b: int, eb: tuple) -> tuple:
        if b < a:
            a, ea, b, eb = b, eb, a, ea
        k = (a, ea, b, eb)
        hit = self._pair.get(k)
        if hit is None:
            wa, wb = self.wires(a, ea), self.wires(b, eb)
            ba, bb = wa[4], wb[4]
            if ba[2] < bb[0] or bb[2] < ba[0] or ba[3] < bb[1] or bb[3] < ba[1]:
                hit = (0.0, 0)
            else:
                n = segments_crossing(wa[3], wb[3])
                hit = (n * crossing(self.w, self.pb.nets[a][1], self.pb.nets[b][1]), n)
            self._pair[k] = hit
        return hit

    def total(self, assign: list) -> tuple:
        """(total, against, among, weighted, length, bend)."""
        weighted, against, among, ln, bd = 0.0, 0, 0, 0.0, 0.0
        for n, pins in enumerate(assign):
            _, w, c = self.single(n, pins)
            _, l, b, _, _ = self.wires(n, pins)
            weighted += w
            against += c
            ln += l
            bd += b
        for a in range(len(assign)):
            for b in range(a + 1, len(assign)):
                w, c = self.pair(a, assign[a], b, assign[b])
                weighted += w
                among += c
        return (weighted + self.w[3] * ln + self.w[4] * bd, against, among, weighted, ln, bd)


class Tally:
    def __init__(self, scorer: Scorer, assign: list):
        self.s, self.assign = scorer, list(assign)
        self.value = scorer.total(self.assign)[0]

    def delta(self, changes: dict) -> float:
        s, now = self.s, self.assign
        moved = sorted(changes)
        d = 0.0
        for n in moved:
            d += s.single(n, changes[n])[0] - s.single(n, now[n])[0]
        for n in moved:
            for m in range(len(now)):
                if m in changes:
                    continue
                d += s.pair(n, changes[n], m, now[m])[0] - s.pair(n, now[n], m, now[m])[0]
        for i, n in enumerate(moved):
            for m in moved[i + 1:]:
                d += s.pair(n, changes[n], m, changes[m])[0] - s.pair(n, now[n], m, now[m])[0]
        return d

    def apply(self, changes: dict, d: float) -> None:
        for n, pins in changes.items():
            self.assign[n] = pins
        self.value += d


def hungarian(cost) -> list | None:
    """The minimum-cost assignment of every row to a different column (rows <= columns), or None when every assignment
    meets an infinite cost. Kuhn-Munkres with potentials; ties go to the lower column."""
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    a = [[c if c < 1e12 else 1e12 for c in row] for row in cost]
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
    for i in range(n):
        if cost[i][out[i]] == _INF:
            return None
    return out


def _with(assign: list, net: int, slot: int, pin: int) -> tuple:
    pins = list(assign[net])
    pins[slot] = pin
    return tuple(pins)


def _target_cost(sc: Scorer, mv, pin: int, assign: list) -> float:
    """How far `pin`'s exit point is from what the movable `mv` (net, slot, allowed, group) heads for: its nearest
    anchor on another part, else the exit points of its other ends."""
    pb = sc.pb
    net, slot = mv[0], mv[1]
    part = pb.ends[net][slot][0]
    e = sc.exit(part, pin)
    pts = [(x, y) for x, y, _, _ in pb.fixed[net]]
    if not pts:
        pts = [sc.exit(pb.ends[net][k][0], q).at for k, q in enumerate(assign[net]) if k != slot]
    best = None
    for x, y in pts:
        d = math.hypot(e.at[0] - x, e.at[1] - y)
        if best is None or d < best:
            best = d
    return 0.0 if best is None else best


def first_map(sc: Scorer, group_parts, assign: list) -> tuple:
    """(assignment, [(part, net)] that no matching places)."""
    pb = sc.pb
    assign = list(assign)
    problems = []
    for part in group_parts:
        mvs = [k for k, mv in enumerate(pb.movable) if pb.ends[mv[0]][mv[1]][0] == part]
        singles = [k for k in mvs if pb.movable[k][3] < 0]
        cost_of = lambda k, pin: _target_cost(sc, pb.movable[k], pin, assign) if pin in pb.movable[k][2] else _INF

        def matching(used):
            pins = sorted({q for k in singles for q in pb.movable[k][2]} - used)
            if len(pins) < len(singles):
                return pins, None
            return pins, hungarian([[cost_of(k, q) for q in pins] for k in singles])
        used, changes = set(), {}
        for g, (gpart, members, windows) in enumerate(pb.groups):
            if gpart != part:
                continue
            ranked = []
            for wi, win in enumerate(windows):
                if used & set(win):
                    continue
                c = 0.0
                for m, q in zip(members, win):
                    if m >= 0:
                        c += _target_cost(sc, pb.movable[m], q, assign)
                ranked.append((c, wi))
            ranked.sort()
            chosen = None
            for _, wi in ranked:
                if matching(used | set(windows[wi]))[1] is not None:
                    chosen = windows[wi]
                    break
            if chosen is None:
                used |= {assign[pb.movable[m][0]][pb.movable[m][1]] for m in members if m >= 0}
                continue
            used |= set(chosen)
            for m, q in zip(members, chosen):
                if m >= 0:
                    changes[m] = q
        if singles:
            pins, got = matching(used)
            if got is None:
                bad = next((k for k in singles if not any(q in pb.movable[k][2] for q in pins)), singles[0])
                problems.append((part, pb.movable[bad][0]))
                continue
            for k, j in zip(singles, got):
                changes[k] = pins[j]
        for k in sorted(changes):
            net, slot = pb.movable[k][0], pb.movable[k][1]
            assign[net] = _with(assign, net, slot, changes[k])
    return assign, problems


class _State:
    """Which pin each movable stands on, and which movable each pin of each part holds."""

    def __init__(self, pb, assign):
        self.pb = pb
        self.pin = [assign[mv[0]][mv[1]] for mv in pb.movable]
        self.who = {}
        for k, mv in enumerate(pb.movable):
            self.who[(pb.ends[mv[0]][mv[1]][0], self.pin[k])] = k

    def commit(self, changes: dict) -> None:
        pb = self.pb
        for k in changes:
            part = pb.ends[pb.movable[k][0]][pb.movable[k][1]][0]
            if self.who.get((part, self.pin[k])) == k:
                del self.who[(part, self.pin[k])]
        for k, q in changes.items():
            self.pin[k] = q
            self.who[(pb.ends[pb.movable[k][0]][pb.movable[k][1]][0], q)] = k


def _units(pb, group_parts) -> list:
    out = []
    for part in group_parts:
        out += [("m", k) for k, mv in enumerate(pb.movable) if mv[3] < 0 and pb.ends[mv[0]][mv[1]][0] == part]
        out += [("g", g) for g, gr in enumerate(pb.groups) if gr[0] == part and gr[2]]
    return out


def _propose(rng: SplitMix64, st: _State, pb, units) -> dict | None:
    """A random legal change, {movable: new pin}, or None."""
    if not units:
        return None
    what, i = units[rng.below(len(units))]
    if what == "m":
        mv = pb.movable[i]
        part = pb.ends[mv[0]][mv[1]][0]
        here = st.pin[i]
        choices = [q for q in mv[2] if q != here]
        if not choices:
            return None
        to = choices[rng.below(len(choices))]
        other = st.who.get((part, to))
        if other is None:
            return {i: to}
        if pb.movable[other][3] < 0 and here in pb.movable[other][2]:
            return {i: to, other: here}
        return None
    gpart, members, windows = pb.groups[i]
    now = tuple(st.pin[m] for m in members if m >= 0)
    wins = [w for w in windows if tuple(q for m, q in zip(members, w) if m >= 0) != now]
    if not wins:
        return None
    win = wins[rng.below(len(wins))]
    changes = {m: q for m, q in zip(members, win) if m >= 0}
    left = sorted(set(now) - set(win))
    taken = [q for q in sorted(win) if st.who.get((gpart, q)) is not None and st.who[(gpart, q)] not in members]
    if len(taken) > len(left):
        return None
    for q, r in zip(taken, left):
        other = st.who[(gpart, q)]
        if pb.movable[other][3] >= 0 or r not in pb.movable[other][2]:
            return None
        changes[other] = r
    return changes


def anneal(sc: Scorer, group_parts, start: list, params, combo: int, clock: Clock) -> tuple:
    """(best assignment, its total, whether the clock ran out) from `start`, over the seeds."""
    pb = sc.pb
    seeds, moves, t0, t1, seed_key = params["seeds"], params["moves"], params["t0"], params["t1"], params["seed_key"]
    best, best_v = list(start), sc.total(start)[0]
    units = _units(pb, group_parts)
    n = max(moves, 1)
    for s in range(max(seeds, 1)):
        rng = SplitMix64(stream_seed(seed_key, combo, s))
        tally, st = Tally(sc, start), _State(pb, start)
        for k in range(n):
            if k % 32 == 0 and clock.out():
                return best, best_v, True
            temp = t0 * (t1 / t0) ** (k / max(n - 1, 1)) if t0 > 0 and t1 > 0 else 0.0
            got = _propose(rng, st, pb, units)
            if got is None:
                continue
            changes = {}
            for m in sorted(got):
                net, slot = pb.movable[m][0], pb.movable[m][1]
                changes[net] = _with(tally.assign, net, slot, got[m])
            d = tally.delta(changes)
            if d < -1e-12 or (temp > 0 and rng.unit() < math.exp(-d / temp)):
                tally.apply(changes, d)
                st.commit(got)
                if tally.value < best_v - 1e-9:
                    best, best_v = list(tally.assign), tally.value
    return best, best_v, False


def _paths(sc: Scorer, group_parts, assign: list) -> list:
    out = []
    for n, pins in enumerate(assign):
        if any(sc.pb.ends[n][k][0] in group_parts for k in range(len(pins))):
            out.append((n, [list(p) for p in sc.wires(n, pins)[0]]))
    return out


def search(pb, group_parts, combos, params) -> tuple:
    """The study of one group, as the native core's `pinmap_search` returns it: (present breakdown, present paths,
    [(combo, breakdown, assignment, paths)], budget_out, first_map, [(part, net)])."""
    w = params["weights"]
    bg = Background(pb.wires, w)
    clock = Clock(params["budget_ms"], params["step_ms"])
    present = [tuple(q for _, q in pb.ends[n]) for n in range(len(pb.nets))]
    present_poses = [Pose(p[1], p[2]) for p in pb.parts]
    sc0 = Scorer(pb, present_poses, w, bg)
    base = sc0.total(present)
    base_paths = _paths(sc0, group_parts, present)
    results, out, first, problems = [], False, True, []
    for k, combo in enumerate(combos):
        if clock.out():
            out = True
            if k == 0:
                first = False
            break
        poses = list(present_poses)
        for part, turn, flip in combo:
            poses[part] = Pose(pb.parts[part][1], pb.parts[part][2], turn, flip)
        sc = sc0 if k == 0 else Scorer(pb, poses, w, bg)
        start, said = first_map(sc, group_parts, present)
        for p in said:
            if p not in problems:
                problems.append(p)
        if said and k == 0:
            return base, base_paths, [], False, True, problems
        best, _, ran_out = anneal(sc, group_parts, start, params, k, clock)
        results.append((k, sc.total(best), [list(x) for x in best], _paths(sc, group_parts, best)))
        if ran_out:
            out = True
            break
    return base, base_paths, results, out, first, problems
```

In `src/placemat/pinmap_core.py`, in `search`, replace:

```python
    core = native_core() if native else None
    if core is None:
        raise RuntimeError("the pin map study's core is the native module's until its Python twin is in: build it with "
                           "`uv pip install -e \".[native]\"`")
```

with:

```python
    core = native_core() if native else None
    if core is None:
        from . import pinmap_twin
        return pinmap_twin.search(pb, group_parts, combos, params)
```

- [ ] **Step 5: Run the tests to watch them pass, with the module and without it**

Run: `.venv/bin/python -m pytest tests/test_pinmap_geom.py tests/test_pinmap_twin.py tests/test_native_pinmap.py tests/test_pinmap_core.py -q -n 2`
Expected: PASS: 7, 6, 19 and 22 tests (`test_native_pinmap` compares 12 random boards, six fixed cases at quarter and eighth turns with both faces, and a study the counted clock stops; while planning every one agreed exactly).

Run: `PLACEMAT_NATIVE=0 .venv/bin/python -m pytest tests/test_pinmap_core.py tests/test_native_pinmap.py -q -n 2`
Expected: PASS, the `[native]` cases and `test_native_pinmap` skipped: the study runs on the twin alone.

- [ ] **Step 6: Commit**

```bash
git add src/placemat/pinmap_geom.py src/placemat/pinmap_twin.py src/placemat/pinmap_core.py tests/test_pinmap_geom.py tests/test_pinmap_twin.py tests/test_native_pinmap.py tests/test_pinmap_core.py
git commit -m "Pin map study: the Python twin of the native core, the same answers on the same arrays"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 8: Joint study of linked parts

**Files:**
- Modify: `src/placemat/pinmap_core.py` (append `linked_groups`, `study`)
- Test: `tests/test_pinmap_joint.py`

**Interfaces:**
- Consumes: Task 5's `study_group`, `problem_of`; the core takes a group of parts and their pose combinations already (Task 5).
- Produces: `pinmap_core.linked_groups(inp) -> list[tuple[str, ...]]` (parts joined by a net that may move on both, sorted); `pinmap_core.study(inp, settings, step_ms=0.0, native=True) -> list[GroupResult]` (one per group, the arrays built once).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_joint.py`:

```python
"""Parts whose movable nets connect to each other's are studied together: their poses searched in combination (at most
`pins.joint_combinations`), both ends of a shared net free."""
import pytest

from placemat.pinmap_core import linked_groups, native_core, study, study_group
from tests.pinmap_boards import input_of, point_pad, quad, settings

CORES = ["native", "python"]


@pytest.fixture(params=CORES)
def native(request):
    if request.param == "native" and native_core() is None:
        pytest.skip("the native module is not in use")
    return request.param == "native"


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


def test_a_joint_study_beats_studying_each_part_alone(native):
    inp = facing_away()
    s = settings(pins_length_weight=0.1)
    best = lambda g: min(r.breakdown.total for r in g.results)
    joint = study_group(inp, ("U1", "U2"), s, native=native)
    alone = [study_group(inp, (r,), s, native=native) for r in ("U1", "U2")]
    assert best(joint) < min(best(g) for g in alone)
    win = min(joint.results, key=lambda r: r.breakdown.total)
    assert win.poses == (("U1", 180.0, False), ("U2", 180.0, False))
    assert [g.refs for g in study(inp, s, native=native)] == [("U1", "U2")]


def test_a_joint_study_searches_at_most_the_combinations_it_is_allowed(native):
    g = study_group(facing_away(), ("U1", "U2"), settings(pins_joint_combinations=5), native=native)
    assert (g.searched, g.of) == (5, 16)
    assert g.results[0].poses == (("U1", 0.0, False), ("U2", 0.0, False))
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/bin/python -m pytest tests/test_pinmap_joint.py -q -n 2`
Expected: FAIL with `ImportError: cannot import name 'linked_groups' from 'placemat.pinmap_core'`.

- [ ] **Step 3: Append the grouping and the study of every group**

Append to `src/placemat/pinmap_core.py`:

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


def study(inp, settings, step_ms: float = 0.0, native=True) -> list:
    """Every group's study (GroupResult), the arrays built once for all of them."""
    pb = problem_of(inp, settings.pins_exit_mm)
    return [study_group(inp, refs, settings, step_ms=step_ms, native=native, pb=pb) for refs in linked_groups(inp)]
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_joint.py tests/test_pinmap_core.py -q -n 2`
Expected: PASS (5 joint cases on both cores; the joint case is two parts 10 mm apart with three shared nets each on the side facing away: alone, each turn still leaves the other's body to go round; together both turn 180 degrees).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/pinmap_core.py tests/test_pinmap_joint.py
git commit -m "Pin map study: parts whose movable nets meet are studied together, their poses in combination"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 9: The finding and the suggestion - `pins.remap`, `setup.pins`, advice, facts, cache

**Files:**
- Modify: `src/placemat/findings.py` (kind `PINS`, causes `SETUP_PINS`, `PINS_REMAP`, `SEVERITY`)
- Modify: `src/placemat/finding_text.py` (renderers, `pose_text`, `subject`)
- Modify: `src/placemat/suggestions.py` (`Suggestion.advice`, `Pick.advice`, `suggest`, `_Binder.bind`, `apply_suggestion`, `pin_advice`, `pin_advice_text`, the `pins.remap` builder)
- Create: `src/placemat/pinmap.py`
- Modify: `skills/placemat/references/api.md` (the suggestions case table: the `pins.remap` row)
- Modify: `tests/test_finding_kinds.py`, `tests/test_suggestion_cases.py`
- Test: `tests/test_pinmap_finding.py`

**Interfaces:**
- Consumes: Tasks 2-8 (`build`, `placed_from_geometry`, `pinmap_core.study` and its `GroupResult` (`present`, `present_assign`, `present_paths`, `results` of `PoseResult(poses, breakdown, assign, paths)`, `searched`, `of`, `budget_out`, `first_map`, `problems` as (ref, net)), `Problem`, `natural`); `reuse.canonical`, `reuse.finding_to_json`, `reuse.finding_from_json`; `checkpoint.write_atomic`; `finding_text.schemas_digest`; `pairs.board_pairs`.
- Produces:
  - `FindingKind.PINS = "pins"` (severity notice); `FindingCause.SETUP_PINS = "setup.pins"`, `FindingCause.PINS_REMAP = "pins.remap"`.
  - `finding_text.pose_text(turns: list) -> str`.
  - `Suggestion.advice: dict | None`, `Pick.advice: dict | None`, `how == "advice"`; `suggestions.pin_advice(facts, i) -> dict`, `suggestions.pin_advice_text(advice) -> str`.
  - `pinmap.CACHE_VERSION`, `has_pools(footprints) -> bool`, `copper_nets(geometry, plan=None) -> frozenset`, `group_facts(inp, g, copper, settings) -> dict | None`, `digest(inp, problems, copper, settings) -> str`, `study_findings(pads, parts, names, quiet, partners, netclasses, settings, copper=frozenset(), cache=None, step_ms=0.0) -> (list[Finding], dict)`, `geometry_findings(geometry, settings, quiet=frozenset(), either=frozenset(), cache=None, step_ms=0.0) -> (list[Finding], dict)` (`step_ms` above 0 gives the core a counted clock, for a test).
  - The `pins.remap` facts (all JSON): `ref`, `refs`, `at`, `present` (a `Breakdown.to_json()`), `rotations` (per pose searched, the present one first: the breakdown's fields plus `turns` [{`ref`, `turn_deg`, `rotation_deg`, `face`, `flip`}], `map` [{`ref`, `net`, `from`: {`pin`, `name`}, `to`: {`pin`, `name`}}], `routed` (the moved nets with copper now), `paths` [{`net`, `path`: [[x, y], ...]}]), `best` (index), `routed`, `before` (paths at the present map), `held` [{`ref`, `net`, `pin`, `name`, `why`}], `searched`, `of`, `budget_out`, `first_map`, `budget_ms`.
  - The `setup.pins` facts: `Problem.facts()` - `ref`, `key`, `entry`, `code`, `name`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pinmap_finding.py`:

```python
"""The pin map study's finding: a `pins.remap` notice when a map saves `pins.gain_min` of the present total, its facts
as data and its sentence rendered from them; a `setup.pins` warning for an entry the study ran without; the suggestion
that carries the map and the turn and writes nothing; and a study reused when what it reads has not changed."""
import json

import pytest

from placemat import suggestions as sg
from placemat.findings import FindingCause as C, FindingKind
from placemat.pinmap import study_findings
from tests.pinmap_boards import complete, point_pad, quad, reversed_four, settings


def study(pads, parts, s=None, copper=frozenset(), cache=None, step_ms=0.0):
    return study_findings(pads, complete(pads, parts), {}, frozenset(), {}, {}, s or settings(), copper, cache, step_ms)


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
    found, _ = study(*reversed_four(), settings(pins_budget_ms=50), step_ms=100.0)        # out at the first question
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

Append to `tests/test_pinmap_real.py` (the reference board studied twice through the cache; the spec's "a repeated run reuses its result"):

```python
@needs_kicad
def test_a_second_study_of_the_real_board_is_reused(tmp_path):
    from placemat.findings import FindingCause as C
    from placemat.pinmap import geometry_findings
    b = bench()
    case = b.cases()[0]
    g = b.board_of(case)
    cache = tmp_path / "pinmap.json"
    first, r1 = geometry_findings(g, Settings(), frozenset(case["quiet"]), cache=cache)
    again, r2 = geometry_findings(g, Settings(), frozenset(case["quiet"]), cache=cache)
    assert any(f.cause is C.PINS_REMAP for f in first)
    assert (r1["reused"], r2["reused"]) == (False, True) and [str(f) for f in again] == [str(f) for f in first]
```

and add its id to `tests/slow_tests.txt`:

```
tests/test_pinmap_real.py::test_a_second_study_of_the_real_board_is_reused
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
Expected: FAIL with `ModuleNotFoundError: No module named 'placemat.pinmap'`, the kinds set lacking `pins`, and `AttributeError: PINS_REMAP`. (The real-board reuse test fails the same way: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_pinmap_real.py -q --full`.)

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

For each part whose capture gives it a `Pm.PinPool` (pinmap_rules), the study (pinmap_core: the native core, or its
Python twin) finds how many weighted
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

from .pinmap_core import study
from .pinmap_input import build, placed_from_geometry
from .pinmap_rules import Problem, natural

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


def _paths(paths: dict) -> list:
    return [{"net": net, "path": _rounded(p)} for net in sorted(paths) for p in paths[net]]


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


def group_facts(inp, g, copper, settings) -> dict | None:
    """The facts of a group's `pins.remap` finding, or None when no pose saves `pins.gain_min` of the present total
    (a study that ran out before a first map always has one, saying so)."""
    refs = g.refs
    lead = inp.part(refs[0])
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
        moved = _map(inp, refs, g.present_assign, r.assign)
        rows.append(dict(r.breakdown.to_json(), turns=_turns(inp, r.poses), map=moved,
                         routed=sorted({m["net"] for m in moved} & copper), paths=_paths(r.paths)))
    return dict(base, rotations=rows, best=best, routed=rows[best]["routed"], before=_paths(g.present_paths))


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
                   step_ms: float = 0.0) -> tuple:
    """(findings, record) of the study of a placed board: `setup.pins` for each problem, `pins.remap` for each group
    with a map worth having. `cache`, a path, holds the last study's digest and findings: a match is reused. `record` is
    what a run keeps: {"seconds", "reused", "groups", "parts"}, empty when nothing was studied. `step_ms` above 0 makes
    the core's clock a counted one (a test's)."""
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
        results = study(inp, settings, step_ms)
        groups = len(results)
        for g in results:
            found += [Finding(C.SETUP_PINS, Problem(ref, "", "", "no_legal_map", net).facts()) for ref, net in g.problems]
            facts = group_facts(inp, g, copper, settings)
            if facts is not None:
                found.append(Finding(C.PINS_REMAP, facts))
    if cache is not None:
        _keep(cache, d, found)
    return found, {"seconds": round(time.perf_counter() - t0, 3), "reused": False, "groups": groups, "parts": n_parts}


def geometry_findings(geometry, settings, quiet=frozenset(), either=frozenset(), cache=None, step_ms: float = 0.0) -> tuple:
    """`study_findings` of a board where its file has its parts (a laid board read from disk, a bench case)."""
    if not has_pools(geometry.footprints):
        return [], {}
    from .pairs import board_pairs
    pads, parts = placed_from_geometry(geometry, either)
    return study_findings(pads, parts, geometry.pin_names, quiet, board_pairs(geometry.netclasses), geometry.netclasses,
                          settings, copper_nets(geometry), cache, step_ms)
```

- [ ] **Step 7: Run the tests to watch them pass**

Run: `.venv/bin/python -m pytest tests/test_pinmap_finding.py tests/test_finding_kinds.py tests/test_suggestion_cases.py tests/test_no_sentence_parsing.py tests/test_apply_suggestion.py tests/test_finding_severity.py -q -n 2`
Expected: PASS (`test_no_sentence_parsing` checks the new causes have renderers and versions; `test_suggestion_cases` that the api.md table names `pins.remap`). Then `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_pinmap_real.py -q --full`: PASS (2 tests).

- [ ] **Step 8: Commit**

```bash
git add src/placemat/findings.py src/placemat/finding_text.py src/placemat/suggestions.py src/placemat/pinmap.py skills/placemat/references/api.md tests/test_pinmap_finding.py tests/test_pinmap_real.py tests/slow_tests.txt tests/test_finding_kinds.py tests/test_suggestion_cases.py
git commit -m "Pin map study: a pins.remap notice with its map as facts, an advice suggestion that writes nothing, setup.pins for what it runs without"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

### Task 10: Wiring into run and preview - once, at the end of a resolve, with digest reuse

**Files:**
- Modify: `src/placemat/occupancy.py` (`Occupancy.courtyard_box`)
- Modify: `src/placemat/layout.py` (`Plan.pin_study`; `Board.pin_study`, `Board.pin_study_cache`; `Board._report_pin_maps`; the call in `_resolve_once`)
- Modify: `src/placemat/pinmap.py` (import; append `study_line`, `placed_from_plan`, `plan_findings`)
- Modify: `src/placemat/runner.py` (`scripted_board` sets the cache path; `_run` records and says the study)
- Modify: `src/placemat/explore.py` (`BoardFactory.__call__`)
- Modify: `src/placemat/previewer.py` (`_resolved` says the study)
- Test: `tests/test_pinmap_wiring.py`

**Interfaces:**
- Consumes: Task 9's `study_findings`, `copper_nets`, `has_pools`; `Occupancy.pad_anchor`, `Occupancy._transform`, `Occupancy.items`, `Occupancy.pending`; `Board._placements()`, `Board._plane_nets()`, `Board._free_nets`; `pairs.board_pairs`; `context._overlay`.
- Produces: `Occupancy.courtyard_box(ref) -> Box`; `Plan.pin_study: dict` ({"seconds", "reused", "groups", "parts"}, `{}` when nothing was studied); `Board.pin_study: bool = True`; `Board.pin_study_cache: Path | None = None`; `pinmap.placed_from_plan(board, plan) -> (pads, parts)`, `pinmap.plan_findings(board, plan) -> list[Finding]`, `pinmap.study_line(record) -> str`; `run.json` `metrics.pin_study`; the console line `pins  <study_line>` in run and preview.

The hook sits after `_report_splits` and before `suggestions.bind` in `_resolve_once`, so the study's findings get their suggestion ids with the rest, are in the plan the studio is sent (`channel.reporter(...).plan`), and are in the reuse-free part of the plan (they are not step findings, so no replay record carries them). It runs when `self._explore is None` (a variant with a seed is never studied there) and `self.pin_study` (an explore's own boards, made by `BoardFactory`, say False: Task 11 studies the best of them). A try of a suggestion (`context._overlay` set) studies without keeping a record, as a try writes nothing.

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

### Task 11: The explore hook - the best variants studied, reported beside their scores

**Files:**
- Modify: `src/placemat/pinmap.py` (append `plan_summary`)
- Modify: `src/placemat/explore.py` (`search`'s two finishing branches, `_pin_maps`, `pin_map_lines`, `_report_lines`)
- Test: `tests/test_pinmap_explore.py`

**Interfaces:**
- Consumes: Task 10's `placed_from_plan`, `has_pools`; Task 8's `pinmap_core.linked_groups`; Task 5's `study_group`, `problem_of`; Task 9's `_turns`, `_map`; `finding_text.pose_text`; `explore.Explore`, `explore._context_of`, `ExploreResult.results` (rows `(seed, score, measures)`, best first).
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
    from .pinmap_core import linked_groups, problem_of, study_group
    settings = settings or board.settings
    pads, parts = placed_from_plan(board, plan)
    quiet = frozenset(board._plane_nets()) | frozenset(board._free_nets)
    inp, _ = build(pads, parts, board.geometry.pin_names, quiet, board_pairs(board.geometry.netclasses),
                   board.geometry.netclasses, settings.pins_follow_series)
    if inp is None:
        return []
    pb = problem_of(inp, settings.pins_exit_mm)
    out = []
    for group in linked_groups(inp):
        if refs and not set(group) & set(refs):
            continue
        g = study_group(inp, group, settings, pb=pb)
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

### Task 12: A longer study from `placemat apply <id> --search`

The spec's "the probe can run the study with a larger budget": the command a probe already is. `placemat apply <id> --search` on a `pins` advice suggestion resolves the board as the last run placed it, studies the suggestion's parts with `pins.probe_budget_ms` a part, and keeps a better map as `<id>.1` beside the plan's suggestions (`suggestions.add_found`), where `placemat apply` and the studio find it - as advice, which `apply` refuses to write.

**Files:**
- Modify: `src/placemat/pinmap.py` (append `longer_advice`)
- Modify: `src/placemat/cli.py` (`_search` dispatch; `_pin_search`)
- Test: `tests/test_pinmap_probe.py`

**Interfaces:**
- Consumes: Task 11's `plan_summary`; Task 9's `suggestions.pin_advice_text`, `Suggestion(advice=...)`; `previewer.resolve_like_last_run(script) -> (board, plan, src, run_id)`; `suggestions.add_found`, `suggestions.recall`, `suggestions.keep`; `settings.load`.
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

### Task 13: Studio - the map and the airwires before and after

The page already has what it needs: the plan JSON carries each finding's `facts` (with `before` and each pose's `paths`) and its suggestions' JSON (with `advice`), and `/suggest/show`, `/try` and `/apply` refuse an advice suggestion through `apply_suggestion` (Task 9). This task is the page alone: an advice suggestion is a third kind in `SG_KINDS` whose one button, Try, draws the airwires and lists the map, and writes and resolves nothing.

**Files:**
- Modify: `src/placemat/studio_page.html` (CSS, `S.pinmap`, `SG_KINDS.advice`, `sgKind`, `sgRow`, `sgAct`, `pinMapOf`, `pinMapSVG`, `pinMapHTML`, `drawPinMap`, `render`)
- Test: `tests/test_studio_page.py` (append)

**Interfaces:**
- Consumes: the finding JSON `{cause: "pins.remap", facts: {before, rotations: [{paths, map, ...}]}, suggestions: [{id, how: "advice", lever: "pins", advice: {rotation, turns, map, ...}}]}` (Task 9); the page's `plan()`, `esc`, `num`, `B.svg`, `schedule`, `render`.
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

### Task 14: Docs - capture.md, api.md, the skill, migration

**Files:**
- Modify: `skills/placemat/references/capture.md` (the annotation table; a section "Pin pools")
- Modify: `skills/placemat/references/api.md` (the findings table; a section "## The pin map study"; a sentence in "Exploring a placement")
- Modify: `skills/placemat/SKILL.md` (one bullet in "Pin assignments are a layout lever")
- Modify: `skills/placemat/references/migration.md` (a "### New" entry under "## Unreleased")

**Interfaces:**
- Consumes: the behaviour of Tasks 1-13 as built; the settings table is already generated (Tasks 1 and 6), the suggestions case row is in (Task 9).
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
searches of `pins.anneal_moves` moves and swaps under annealing. The score and
the search run in the native module when it is in use, else in its Python
twin, which gives the same maps (`setup.native` says when it is not). Parts whose
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

In `skills/placemat/references/migration.md`, add this bullet at the end of the `### New` list under `## Unreleased` (at HEAD when this plan was written, that list exists and holds the net halos entry; if it does not, create `## Unreleased` above the newest `## To ...` and `### New` above any `### Fixed` in it):

```markdown
- **The pin map study.** A part whose capture annotates its general-purpose pins (`Pm.PinPool`, with `Pm.PinFixed`,
  `Pm.PinAllow`, `Pm.PinDeny` and `Pm.PinGroup`; capture.md, "Pin pools") is studied at the end of every run and
  preview: placemat looks for an assignment of its nets to those pins, at its present rotation and at each turn in
  `[pins] rotations`, that saves weighted ratsnest crossings, airwire and turning, and says so in a `pins.remap` notice
  whose suggestion carries the map and the turn. Nothing is written: the map is a capture change and the turn a layout
  one. An annotation entry naming a pin or a net the part lacks is a `setup.pins` warning. An explore reports the study
  of its best variants beside their scores; `placemat apply <id> --search` studies again with a longer budget. Settings:
  `[pins]`. The study runs in the native module when it is in use (`uv pip install -e ".[native]"` after updating), else
  in Python, with the same results. Nothing in a layout script changes; the first run after updating replays no steps
  (the findings' schemas changed).
```

- [ ] **Step 5: Check the docs**

Run: `.venv/bin/python -m pytest tests/test_settings_docs.py tests/test_suggestion_cases.py -q -n 2`
Expected: PASS.

Run: `grep -nP "[\x{2013}\x{2014}\x{2192}\x{2018}\x{2019}\x{201C}\x{201D}\x{2026}]" skills/placemat/SKILL.md skills/placemat/references/capture.md skills/placemat/references/api.md skills/placemat/references/migration.md src/placemat/pinmap*.py native/src/pinmap*.rs`
Expected: no line the change added (ASCII only).

- [ ] **Step 6: Commit**

```bash
git add skills/placemat/SKILL.md skills/placemat/references/capture.md skills/placemat/references/api.md skills/placemat/references/migration.md
git commit -m "Docs: the pin map study, its annotations, finding and settings"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

- [ ] **Step 7: The whole suite**

Run: `.venv/bin/python -m pytest -n 2 -q 2>&1 | tail -5`, then `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest -n 2 -q --full tests/test_pinmap_real.py tests/test_pinmap_netclass.py`, and `PLACEMAT_NATIVE=0 .venv/bin/python -m pytest -n 2 -q tests/test_pinmap_*.py` (the study on its Python twin)
Expected: no failures.

---

## Self-Review

Done while writing; recorded here for the reviewer.

**Spec coverage.** Constraints (pool, fixed, allow, deny, group; number, name, range; `setup.pins` for a pin or net the part lacks; no legal map): Tasks 2, 5 (`no_legal_map` from the matching), 9. Scored as unrouted: Task 3 (`board_nets(pads, copper=())`), Task 5 (the routed-board score test). Airwires round the body: Task 4 (Rust), Task 7 (Python twin). Multi-pad nets on the tree, series parts: Tasks 3 and 5. Weights (pair, impedance, plane): Tasks 3 and 5. Bends: Tasks 4, 5 (the diagonal test). Total: Task 5. The search (matching seed, moves and swaps, groups whole, annealing, seeds, determinism, ties by pin number, rotations, faces): Task 5, twinned in Task 7. Joint study and its cap: Tasks 5 and 8. Speed (budget per part, incremental counts on a grid, the native module, once after placement, digest reuse): Tasks 5, 6, 9, 10. The finding, its facts (moved nets with copper now included) and its sentence: Task 9. The suggestion (lever `pins`, map and rotation, `try` previews nothing): Tasks 9 and 13. Studio before/after drawing: Task 13. The probe with a larger budget: Task 12. Explore: Task 11. Errors (no pool, no legal map, budget too short): Tasks 2, 5, 9. Testing list: known optimal map, each constraint, group whole and in order, body obstacle, bends with and without 45, determinism (Task 5, both cores from Task 7); joint beats one at a time (Task 8); speed on the reference board (Task 6) and reuse (Task 9); routed board (Task 5); real fixture board beats the present map and nothing moves (Task 6). Native and Python agree on fixed seeds: Task 7. Settings with defaults and table lines: Tasks 1, 6. Docs: Task 14.

**Placeholders.** The only values not fixed in this plan are the three defaults Task 6 takes from the bench (`pins_anneal_moves`, `pins_seeds`, `pins_budget_ms`), as the spec asks ("default set by the bench"); the measurement, the rule, the planning-time numbers and the edit are spelled out, and the stop branch says what to report.

**Type consistency.** Names checked across tasks: `Problem.facts()` (rules), `PinRules`, `PartPins.present/movable/allowed/free/groups/windows/held`, `read_rules`, `part_pins`, `natural`; `PlacedPad`, `PlacedPart`, `StudyInput.part`, `StudyNet`, `Wire`, `build`, `placed_from_geometry`, `net_kind`, `outward`; Rust `pinmap_geom::{Pose, Exit, exit_of, through, length, round_body, End, route, bend}` and `pinmap::{Row, Problem, Params, SplitMix64, stream_seed, crossing, segments_crossing, hungarian, Tallies, Paths, SearchResult, search}`; `placemat_native.pinmap_search(parts, pins, nets, fixed, joined, ends, wires, movable, groups, group_parts, combos, weights, params)`; `pinmap_core.Problem` (the arrays), `KIND_CODES`, `problem_of`, `poses_of`, `seed_key`, `params_of`, `native_core`, `search`, `Breakdown`, `PoseResult(poses, breakdown, assign, paths)`, `GroupResult(refs, present, present_assign, present_paths, results, searched, of, budget_out, first_map, problems)`, `study_group`, `linked_groups`, `study`; `pinmap_geom.py` and `pinmap_twin.py` mirroring the Rust names; `pinmap.has_pools/copper_nets/group_facts/digest/study_findings/geometry_findings/study_line/placed_from_plan/plan_findings/plan_summary/longer_advice`; `suggestions.pin_advice/pin_advice_text`; `finding_text.pose_text`; `Board.pin_study/pin_study_cache`, `Plan.pin_study`, `Occupancy.courtyard_box`; `explore._pin_maps/pin_map_lines`; `cli._pin_search`.

**Run while planning.** On a copy of the tree with the native module built into a scratch venv: the Rust tests (6), every pin map test on both cores (124 with the touched suites), the 19 native-against-twin comparisons agreeing exactly (one first disagreement, in the last bit of a bend, came from taking degrees as `x / (pi / 180)`; CPython's is `(180 / pi) * x`, which the Rust now uses), the reference board's maps the same on both cores, and the real-board test failing on its budget at the provisional defaults and passing at the bench's. Every find/replace anchor in the plan was checked to occur once in the current HEAD.

**Review Focus.** Each of the five lines has its test in the task named there.
