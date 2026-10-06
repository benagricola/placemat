# Reference Set (Step 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fixed set of human-placed and human-routed boards, and our own modules, that measures placemat. It records
today's results as the baseline every 0.100 step is held to.

**Architecture:** A committed manifest pins each open board to a commit, with sha256s, licence and per-board facts. A
fetch script fills a git-ignored cache. Two runners, `fixtures/reference/route_ref.py` (test a) and
`fixtures/reference/place_ref.py` (test b), write results to `fixtures/reference/results.json` and compare against the
committed baseline, as `fixtures/bench.py` does with `bench.json`. Reference captures and layout scripts for the two
test (b) open boards live under `fixtures/reference/boards/<name>/`. A lint checks them against the reference-script
rules.

**Tech Stack:** Python 3.12, KiCad 10 pcbnew and kicad-cli, the `pcb` toolchain from our fork (~/work/pcb), placemat's
CLI, KRT's `tests/stress/strip_copper_only.py`.

**Spec:** docs/superpowers/specs/2026-10-06-roadmap-0.100.md, sections "The reference set", "Starting small",
"Writing each board's capture and layout script", "The rules for a reference script" and "Keeping them current".
Evidence: /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/corpus/REPORT.md and
that folder (`inventory.jsonl`, `trees.txt`, `route/`, `import/`).

## Global Constraints

- Boards are never vendored into the repo. The manifest, the fetch script and our reference captures and scripts are
  committed. The fetched files go to a git-ignored cache (`~/.cache/placemat-reference/` by default,
  `PLACEMAT_REFERENCE_CACHE` overrides).
- Each fetched file is checked against its sha256 in the manifest. A mismatch is an error naming the file, never a
  warning.
- Test (a) passes at 100% clean closure, at the board's own net-class rules, with no copper DRC error beyond the
  stripped board's baseline. It also records closure at the human's track width.
- In test (b), only the parts a human layout engineer fixes for mechanical reasons are held at the human board's
  coordinates, and only in reference scripts (approved by the user for the reference set only). Everything else is
  intent with a `why=` naming its basis, or searched. No steering.
- Real-board runs go one at a time under `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock`
  (the runners take the lock themselves). Keep CPU light: no more than `--jobs 2`.
- Kill only your own PIDs.
- Plain ASCII in code, docs and commit messages: no em or en dashes, no unicode arrows.
- Every commit message passes `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`, which must
  print nothing.
- placemat docs and code stay project-agnostic: no fairing names in placemat's own docs. Open-source board names in the
  manifest and the reference folder are fine.
- Tests that run KiCad or the router on a real board are listed in tests/slow_tests.txt.

## Review Focus

1. **A KiCad 5 board** (chainlinkDriver, ESP-PROG) must be upgraded to the current format before stripping. The runner
   loads and saves it with pcbnew, which writes a `.kicad_pro` with its net classes, so the run does not fail on the old
   format. The test is in Task 2.
2. **A board whose stripped copy already fails DRC** (footprint shorts, starved thermals) must pass when routing adds
   nothing new. The baseline is compared by violation type and location, not by count alone. The test is in Task 3.
3. **No network, with the cache filled:** fetching reuses the cache when every sha256 matches, and says so. With no
   network and an empty cache, the error names the board and the URL. The test is in Task 1.
4. **Two results recorded with different router or pcb versions** must not be called better or worse when the change
   under test is placemat's. They are reported as not comparable, naming the component that differs. The test is in
   Task 3.
5. **A board with user-named copper layers** must be read by standard names (fixed in 0.99.34). The runner must not
   rename layers itself. The test is in Task 2, using a board with renamed layers.
6. **A reference script that writes a coordinate for a part the manifest does not list as fixed** must fail the lint,
   naming the part and the line. The test is in Task 5.

---

### Task 1: Manifest and fetch

**Files:**
- Create: `fixtures/reference/manifest.json`
- Create: `fixtures/reference/fetch.py`
- Create: `fixtures/reference/README.md`
- Modify: `.gitignore` (nothing, if the cache is outside the repo; add `fixtures/reference/.cache/` only if the
  implementer chooses an in-repo cache)
- Test: `tests/test_reference_fetch.py`

**Interfaces:**
- Produces:
  - `fetch.load_manifest(path=MANIFEST) -> list[Board]`, where `Board` is a frozen dataclass:
    - `name: str`, `repo: str` (`"github:owner/repo"` or `"gitlab:kicad/code/kicad"`), `commit: str`;
    - `files: dict[str, str]` (path in repo -> sha256), `board: str` (the `.kicad_pcb` path), `licence: str` (SPDX);
    - `tests: tuple[str, ...]` (`"a"` and/or `"b"`), `islands: tuple[str, ...]` (nets for `--islands`);
    - `fixed: tuple[str, ...]` (references held in test b), `human_track_mm: float | None`, `kicad5: bool`.
  - `fetch.cache_dir() -> pathlib.Path`.
  - `fetch.fetch(board: Board, cache: pathlib.Path | None = None, *, offline: bool = False) -> pathlib.Path`: returns
    the folder holding the board's files. It raises `FetchError(board, path, reason)` on a sha256 mismatch or an
    unreachable URL with no valid cache.
  - CLI: `python fixtures/reference/fetch.py [name ...] [--offline]`.

- [ ] **Step 1: Write the manifest.** One entry per board, from REPORT.md and trees.txt:

| name | repo @ commit | board path | licence | tests | kicad5 |
|---|---|---|---|---|---|
| pic_programmer | gitlab:kicad/code/kicad @ tag 10.0.6 | demos/pic_programmer/pic_programmer.kicad_pcb | CC-BY-SA-4.0 | a, b | false |
| usb-c-power-adapter | github:antmicro/usb-c-power-adapter @ 4d3e9e289a294f7953bf48dde6c96af8327a0611 | usb-c-power-adapter.kicad_pcb | Apache-2.0 | a, b | false |
| lora-v3 | github:Strooom/LoRa-V3-PCB @ 4de6979ace4af83affa25ec414403f30ce9f1a3f | LoRa-V3-PCB.kicad_pcb | MIT | a | false |
| ir-irradiance-probe | github:antmicro/infrared-irradiance-probe @ d4891186544986e55678eab5d64815dd76db3088 | ir-irradiance-probe.kicad_pcb | Apache-2.0 | a | false |
| esp-rust-board | github:esp-rs/esp-rust-board @ efe1e8ad5c6dbc23b4365fef35af27545bc1381d | hardware/esp-rust-board/esp-rust-board.kicad_pcb | CERN-OHL-P-2.0 | a | false |
| watchy | github:sqfmi/watchy-hardware @ 5f147972aa2148d4971f3c41fc3ce39ff8c48131 | Watchy.kicad_pcb | MIT | a | false |
| spimux | github:oxidecomputer/hw-spimux @ 29e59e9c99ced0a5a90a672e08f21081bf6502da | spimux.kicad_pcb | MPL-2.0 | a | false |
| chainlinkDriver | github:scottbez1/splitflap @ 87b17c531ca57b0bf10e86754e9d6b404b11a131 | electronics/chainlinkDriver/chainlinkDriver.kicad_pcb | Apache-2.0 | a | true |

For each board, check the exact paths of the `.kicad_pcb`, `.kicad_pro`, `.kicad_dru` (where present) and `.kicad_sch`
files at the commit with `git ls-tree -r <commit>` in a temporary clone. Record the sha256 of each. The board paths
above come from the scratch checkouts; a repo whose files sit in a subfolder gets the subfolder. pic_programmer's tag
must be resolved to its commit SHA, and that SHA is recorded.

`islands`: pic_programmer `["VCC"]` (its pour does not reach its pads, REPORT.md). The others start empty.
`human_track_mm`: from `inventory.jsonl`, the board's most-used track width (ESP-PROG 0.254, by the report's run).
`fixed`: left empty here; Tasks 6-7 fill it for the two test (b) boards.

- [ ] **Step 2: Write the failing tests.**

```python
# tests/test_reference_fetch.py
import hashlib, json, pathlib
import pytest
from fixtures.reference import fetch

def test_the_manifest_lists_eight_boards_each_pinned_with_a_licence():
    boards = fetch.load_manifest()
    assert len(boards) == 8 and len({b.name for b in boards}) == 8
    for b in boards:
        assert len(b.commit) == 40 and b.licence and b.board in b.files and set(b.tests) <= {"a", "b"}

def test_a_cached_file_whose_sha256_matches_is_used_without_the_network(tmp_path, monkeypatch):
    board = fetch.Board(name="tiny", repo="github:o/r", commit="0" * 40, files={"x.kicad_pcb": hashlib.sha256(b"pcb").hexdigest()},
                        board="x.kicad_pcb", licence="MIT", tests=("a",), islands=(), fixed=(), human_track_mm=None, kicad5=False)
    (tmp_path / "tiny").mkdir(); (tmp_path / "tiny" / "x.kicad_pcb").write_bytes(b"pcb")
    monkeypatch.setattr(fetch, "_download", lambda *a: pytest.fail("network used"))
    assert fetch.fetch(board, tmp_path, offline=True) == tmp_path / "tiny"

def test_a_sha256_mismatch_names_the_file(tmp_path):
    board = fetch.Board(name="tiny", repo="github:o/r", commit="0" * 40, files={"x.kicad_pcb": "f" * 64},
                        board="x.kicad_pcb", licence="MIT", tests=("a",), islands=(), fixed=(), human_track_mm=None, kicad5=False)
    (tmp_path / "tiny").mkdir(); (tmp_path / "tiny" / "x.kicad_pcb").write_bytes(b"pcb")
    with pytest.raises(fetch.FetchError, match="x.kicad_pcb"):
        fetch.fetch(board, tmp_path, offline=True)

def test_offline_with_an_empty_cache_names_the_board_and_url(tmp_path):
    board = fetch.load_manifest()[0]
    with pytest.raises(fetch.FetchError, match=board.name):
        fetch.fetch(board, tmp_path, offline=True)
```

- [ ] **Step 3:** Run `.venv/bin/python -m pytest -p no:cacheprovider tests/test_reference_fetch.py -v`. Expected: FAIL,
  because there is no module `fixtures.reference.fetch`. Add `fixtures/reference/__init__.py` if needed for the import.

- [ ] **Step 4: Implement `fetch.py`.**
  - Raw URLs: `https://raw.githubusercontent.com/<owner>/<repo>/<commit>/<path>` and
    `https://gitlab.com/kicad/code/kicad/-/raw/<commit>/<path>`.
  - Download with `urllib.request`, with a 60 s timeout.
  - Write to `<cache>/<name>/<path>` through a temporary file and a rename.
  - Check the sha256, then return.
  - `_download(url) -> bytes` is the only network call.
  - The CLI prints one line per board (fetched, cached, or the error) and exits 1 on any error.

- [ ] **Step 5:** Run the tests again. Expected: PASS. Then run `python fixtures/reference/fetch.py` once for real, and
  check that all eight boards land in the cache.

- [ ] **Step 6:** Write `fixtures/reference/README.md`. Cover:
  - what the set is;
  - the two tests;
  - how to fetch and run;
  - the rules for a reference script (copy the roadmap's "The rules for a reference script" section verbatim);
  - each board's licence and source.

- [ ] **Step 7:** Commit with the message "Reference set: manifest of eight human-routed open boards, and a fetch
  script with sha256 checks".

### Task 2: Prepare a board for test (a): upgrade, strip, baseline

**Files:**
- Create: `fixtures/reference/prepare.py`
- Test: `tests/test_reference_prepare.py`

**Interfaces:**
- Consumes: `fetch.Board`, `fetch.fetch`.
- Produces:
  - `prepare.prepare(board: Board, src: pathlib.Path, work: pathlib.Path) -> Prepared`. It copies the board, `.kicad_pro`
    and `.kicad_dru` into `work`. For `board.kicad5` it loads and saves with pcbnew. It writes `ref.kicad_pcb` (the human
    copper) and `test.kicad_pcb` (stripped by KRT's `tests/stress/strip_copper_only.py`, zone definitions kept). It runs
    `kicad-cli pcb drc` on `test.kicad_pcb` into `baseline-drc.json`.
  - `Prepared` is a frozen dataclass with `ref: Path`, `test: Path`, `baseline: list[Violation]`, `layers: int`,
    `human: HumanCopper`.
  - `Violation`: `(type: str, nets: tuple[str, ...], at_mm: tuple[float, float])`.
  - `HumanCopper`: `(vias: int, track_mm: float)`, measured on `ref.kicad_pcb` as scratchpad/corpus/metrics.py does.
  - `prepare.violations(drc_json: Path) -> list[Violation]`: errors only, leaving out silk, courtyard and library types
    (`silk_*`, `courtyards_overlap`, `lib_footprint_*`).

- [ ] **Step 1: Write the failing tests.**
  - Build a two-layer board with pcbnew in the test (two pads on one net, one track between them, one GND zone).
    Prepare it, and assert that `test.kicad_pcb` has no tracks and keeps the zone, and that `ref.kicad_pcb` keeps the
    track.
  - The same, with the copper layers renamed (`board.SetLayerName`): it still prepares, and `Prepared.layers == 2`.
  - Feed `violations()` a DRC json with one `clearance` error and one `silk_overlap` error, and assert only the clearance
    error is returned.
  - Mark all three tests slow.
- [ ] **Step 2:** Run them and watch them fail.
- [ ] **Step 3: Implement `prepare.py`.**
  - Call the KRT strip script with the router's python, `os.environ.get("KRT_DIR")` or `~/work/KRT-upstream`, as
    placemat's route does (`src/placemat/kicad/route.py` `router_dir`).
  - Run `kicad-cli` with `placemat.childenv.child_env()`.
- [ ] **Step 4:** Run the tests and watch them pass. Prepare chainlinkDriver for real, a KiCad 5 board, and check that its
  `.kicad_pro` holds the net classes `Default` and `save` (inventory.jsonl).
- [ ] **Step 5:** Add the three tests to tests/slow_tests.txt. Commit with the message "Reference set: prepare a board
  for routing - upgrade, strip, and the stripped board's DRC baseline".

### Task 3: Test (a) runner and results

**Files:**
- Create: `fixtures/reference/route_ref.py`
- Create: `fixtures/reference/results.json` (baseline, written in Task 4)
- Test: `tests/test_reference_route.py`

**Interfaces:**
- Consumes: `fetch.*`, `prepare.*`.
- Produces:
  - `route_ref.run_a(board, work, *, track_mm=None) -> AResult`. It runs
    `placemat route <work>/test.kicad_pcb --full --islands <board.islands>` under the realboard flock, plus
    `[route] router_args = ["--track-width", str(track_mm)]` in a `placemat.toml` written beside the board when
    `track_mm` is given. It reads `route.json`.
  - `AResult` is a frozen dataclass:
    - `board: str`, `widths: str` (`"class"` or `"human"`);
    - `closure_clean: float`, `open: int`, `open_nets: list[str]`;
    - `new_violations: list[Violation]`, `vias: int`, `track_mm: float`;
    - `human_vias: int`, `human_track_mm: float`;
    - `passed: bool` (`closure_clean == 1.0 and not new_violations`), `seconds: float`;
    - `versions: dict`: `{"placemat": <git commit of the placemat checkout>, "krt": <commit of the router checkout the
      route used>, "pcb": <pcb --version>}`.
  - `route_ref.comparable(old: dict, new: dict, changing: str) -> list[str]`: the components other than `changing`
    whose versions differ between two results' `versions`. A non-empty list means the two are not compared: the CLI
    prints "not comparable: <components> differ" instead of better or worse. `--changing placemat|krt|pcb` (default
    `placemat`) names the component under change.
  - `route_ref.new_violations(after: list[Violation], baseline: list[Violation], tol_mm=0.05) -> list[Violation]`: those
    `after` has that no baseline violation of the same type and nets matches within `tol_mm`.
  - CLI: `python fixtures/reference/route_ref.py [name ...] [--update]`. For each test (a) board, it runs class widths,
    then human widths where `human_track_mm` is set. It prints one line per run and compares with
    `results.json["a"]`:
    - a board that passed and now fails, or whose `closure_clean` fell, is "worse";
    - `--update` writes the file.

- [ ] **Step 1: Write the failing tests** with a stand-in for the route call. Monkeypatch
  `route_ref._route(pcb, work, islands, toml) -> dict` to return a `route.json`-shaped dict.

```python
from fixtures.reference import route_ref, prepare

V = prepare.Violation
def test_a_violation_already_in_the_baseline_is_not_new():
    base = [V("clearance", ("A", "B"), (10.0, 10.0))]
    after = [V("clearance", ("A", "B"), (10.02, 10.0)), V("short", ("A", "C"), (5.0, 5.0))]
    assert route_ref.new_violations(after, base) == [V("short", ("A", "C"), (5.0, 5.0))]

def test_passed_needs_full_clean_closure_and_nothing_new():
    r = route_ref.AResult(board="x", widths="class", closure_clean=1.0, open=0, open_nets=[], new_violations=[],
                          vias=3, track_mm=10.0, human_vias=2, human_track_mm=9.0, passed=True, seconds=1.0, placemat="0")
    assert r.passed
    assert not route_ref.judge(dict(closure_clean=0.98), [], r).passed
```

  Also add two tests:
  - one that compares the results against a recorded file, and marks a board "worse" when it passed before and fails
    now;
  - one where two results differ in their `krt` version while `--changing placemat`, which are reported as not
    comparable, naming `krt`.
- [ ] **Step 2:** Run and watch them fail.
- [ ] **Step 3: Implement.** `judge(route_json, new, template) -> AResult` builds the result. Results are records; the
  console line is made at the edge, in `main()`.
- [ ] **Step 4:** Run and watch them pass. Then run `python fixtures/reference/route_ref.py pic_programmer` for real.
  Expected: about 100% with `--islands VCC` and 2 `track_width` errors on GND stubs, as in REPORT.md. If it differs, say
  so in the report.
- [ ] **Step 5:** Commit with the message "Reference set: test (a) runner - route the human placement, judge clean
  closure and new DRC errors against the baseline".

### Task 4: Record test (a)'s baseline on all eight boards

**Files:**
- Modify: `fixtures/reference/results.json`

- [ ] **Step 1:** Run `python fixtures/reference/route_ref.py --update`. That is all eight boards, at class widths and at
  human widths where set, one at a time under the lock.
- [ ] **Step 2:** Check each result against REPORT.md's runs (pic_programmer, spimux, ESP-PROG at its two widths).
  - A board that fails to prepare or route because of placemat, not because of the board, is a placemat bug. Write it up
    in the task report with its command and error, and do not work round it in the runner.
  - A board that cannot route for a reason in the board itself goes into the manifest as `notes`, and is still recorded.
- [ ] **Step 3:** Commit `results.json`. The message gives the tally, one line per board:
  `name: class X% (n open, m new DRC) / human Y%`.

### Task 5: Reference-script lint

**Files:**
- Create: `fixtures/reference/lint.py`
- Test: `tests/test_reference_lint.py`

**Interfaces:**
- Consumes: `fetch.Board` (its `fixed`).
- Produces:
  - `lint.lint(script: Path, fixed: Iterable[str]) -> LintReport`. It reads the script with `ast`, never by running it.
  - `LintReport` holds:
    - `declarations: list[Decl]`, each `Decl(line, call, refs, basis, coordinate: bool)`;
    - `problems: list[Problem]`, each `Problem(line, rule, ref)`.
  - The rules:
    - `"coordinate"`: a `Location(...)`, a numeric `Centre`, or `at=` with numbers, on a part not in `fixed`;
    - `"no_why"`: a placement, link or copper call with no `why=`;
    - `"basis"`: a `why=` that does not start with one of `mechanical:`, `datasheet:`, `physics:` or `capture:`;
    - `"steering"`: `priority=`, `Near(`, or an order call with no basis that permits it.
  - CLI: `python fixtures/reference/lint.py <board name>` prints the declarations by basis and the problems, and exits 1
    on any problem.

- [ ] **Step 1: Write the failing tests** on small script strings written to `tmp_path`:

```python
from fixtures.reference import lint

def test_a_coordinate_on_a_part_not_listed_as_fixed_fails_with_its_line(tmp_path):
    s = tmp_path / "s.py"
    s.write_text('board.place(Part("j1"), at=Location(10, 20), why="mechanical: connector at the edge")\n'
                 'board.place(Part("r1"), at=Location(30, 20), why="mechanical: no")\n')
    r = lint.lint(s, fixed={"j1"})
    assert [(p.line, p.rule, p.ref) for p in r.problems] == [(2, "coordinate", "r1")]

def test_a_why_without_a_basis_is_flagged(tmp_path):
    s = tmp_path / "s.py"; s.write_text('board.place(Part("c1"), at=Beside(Part("u1"), 3), why="close to U1")\n')
    assert [p.rule for p in lint.lint(s, fixed=()).problems] == ["basis"]

def test_priority_is_steering(tmp_path):
    s = tmp_path / "s.py"; s.write_text('board.place(Part("u1"), priority=Priority.HIGH, why="datasheet: x")\n')
    assert "steering" in [p.rule for p in lint.lint(s, fixed=()).problems]
```

- [ ] **Step 2:** Run and watch them fail. **Step 3:** Implement. **Step 4:** Run and watch them pass.
- [ ] **Step 5:** Add the lint's rules and its basis prefixes to fixtures/reference/README.md. Commit with the message
  "Reference set: a lint for reference scripts - coordinates only on fixed parts, every declaration's basis, no
  steering".

### Task 6: pic_programmer's capture and reference script

This is authoring work, and it needs judgement. The implementer:
- loads both skills: placemat (skills/placemat/SKILL.md and its references), and circuit-capture
  (~/work/circuit-capture/skills/circuit-capture/SKILL.md);
- reads the human board in the cache.

**Files:**
- Create: `fixtures/reference/boards/pic_programmer/` holding:
  - the imported Zener capture (`pcb import` output);
  - `placemat.toml`;
  - `PicProgrammer_layout.py`;
  - `NOTES.md`: the datasheet sources used for each annotation, and each fixed part with its reason.
- Modify: `fixtures/reference/manifest.json`: pic_programmer's `fixed`.

- [ ] **Step 1: Import.** In a scratch copy, run `pcb import` on the cached project, then `pcb layout -S errors`.
  Record that placement and copper match the original, and that the two references are renamed (P2 -> J2,
  U5 -> `U?1`, REPORT.md). The reference for test (b) is the regenerated board.
- [ ] **Step 2: Annotate the capture** as circuit-capture's skill says a designer would:
  - `Pm.I` on the parts that carry current, from their datasheets;
  - roles, and sources and sensitivities where they apply.

  Each number cites its datasheet section in NOTES.md.
- [ ] **Step 3: Choose the fixed parts.** These are only what a layout engineer fixes for mechanical reasons, read from
  the human board: the DB9 connector, the sockets, power jacks, mounting holes, and edge parts. List them in the
  manifest's `fixed`, with each reason in NOTES.md.
- [ ] **Step 4: Write the layout script** following SKILL.md:
  - the outline from the human board's edge, as the board's outline form, not as coordinates of items;
  - the fixed parts at the human coordinates, with `why="mechanical: ..."`;
  - everything else by relation from the circuit, with a `why=` naming its basis, or left to the search;
  - no steering.

  Run `python fixtures/reference/lint.py pic_programmer` until it passes.
- [ ] **Step 5: Gaps.** Where either skill led you wrong, or a needed form was missing, write it in NOTES.md under
  "Skill gaps", with what you tried. Do not work round it in the script with a coordinate or steering.
- [ ] **Step 6:** Run `placemat run PicProgrammer_layout.py` once, to check it resolves, under the lock. Commit with the
  message "Reference set: pic_programmer's capture and minimal intent script".

### Task 7: usb-c-power-adapter's capture and reference script

Same as Task 6, for usb-c-power-adapter (4 layers, power and USB).

**Files:**
- Create: `fixtures/reference/boards/usb-c-power-adapter/`, with the same contents as Task 6.
- Modify: `fixtures/reference/manifest.json`: its `fixed`.

- [ ] **Step 1: Import and generate** as in Task 6, Step 1. Record the stdlib footprint swap: about 50 DRC errors
  (REPORT.md). The regenerated board is the reference.
- [ ] **Step 2: Annotate.** The current of every part in the power path, from the PD controller's and the DC-DC's
  datasheets. The USB pair as a `DiffPair` interface, and its net class.
- [ ] **Step 3: Fixed parts:** the USB-C receptacle, the output connector, mounting holes, and edge parts.
- [ ] **Step 4: Write the script,** and run the lint until it passes.
- [ ] **Step 5:** Record skill gaps in NOTES.md, as in Task 6.
- [ ] **Step 6:** Run it once, to check it resolves. Commit with the message "Reference set: usb-c-power-adapter's
  capture and minimal intent script".

### Task 8: Test (b) runner, open boards and our modules

**Files:**
- Create: `fixtures/reference/place_ref.py`
- Test: `tests/test_reference_place.py`

**Interfaces:**
- Consumes: `fetch`, `prepare`, `route_ref.new_violations`, `lint.lint`.
- Produces:
  - `place_ref.run_b(board, ref_dir, work) -> BResult`. It lints the reference script, refusing to run when the lint
    fails. It then runs `placemat run <script> --route --full`, under the lock, from a clean copy of
    `fixtures/reference/boards/<name>/` (with the cached project's footprints and libraries alongside).
  - `BResult` holds:
    - `board`, `closure_clean`, `open`, `new_violations`, `vias`, `track_mm`, `run_score`;
    - the regenerated reference's `ref_vias` and `ref_track_mm`;
    - the test (a) result of the same board for comparison (`a_closure_clean`);
    - `seconds` and `versions`, as in `AResult`.
    - Results are compared only through `route_ref.comparable`.
  - `place_ref.run_module(script: Path, work) -> MResult`. It runs a module fixture with `placemat run --route` and
    records `closure_clean`, `area_mm2` (the fitted frame's area from run.json's outline), `run_score` and `seconds`.
    Modules are those under fixtures/mnb/modules and fixtures/fairing/modules that have a layout script.
  - CLI: `python fixtures/reference/place_ref.py [name ...] [--modules] [--update]`. It compares with
    `results.json["b"]` and `["modules"]`:
    - for an open board, worse means a lower clean closure, or a lint failure;
    - for a module, worse means a lower clean closure, or, at equal closure, a larger area.

- [ ] **Step 1: Write the failing tests,** with stand-ins for the placemat run:
  - the lint refusing a script;
  - result comparison: a module with a larger area at equal closure is worse, and a module with lower closure is worse
    whatever its area.
- [ ] **Step 2:** Run and watch them fail. **Step 3:** Implement. **Step 4:** Run and watch them pass.
- [ ] **Step 5:** Commit with the message "Reference set: test (b) runner - place and route the reference scripts and
  our modules, judged against the human board and test (a)".

### Task 9: Record test (b)'s baseline

**Files:**
- Modify: `fixtures/reference/results.json`

- [ ] **Step 1:** Run `python fixtures/reference/place_ref.py --update` (the two open boards), then
  `python fixtures/reference/place_ref.py --modules --update`. Do it one at a time under the lock. The modules run
  takes a while.
- [ ] **Step 2:** Check that no result is a crash. A placemat failure is written up, as in Task 4.
- [ ] **Step 3:** Commit with a tally per board and per module: closure, and area for modules.
- [ ] **Step 4:** Add a short "Reference set" paragraph to `fixtures/reference/README.md`. It covers:
  - how a step uses the set: run both runners before release, and put the tally in the release commit;
  - the ratchet: no board or module may get worse without the user's approval.

  Commit.

## Self-review notes

- **Spec coverage:**
  - the manifest and fetch (Task 1);
  - test (a) on 8 boards, at class and human widths, with the baseline DRC (Tasks 2-4);
  - test (b) on 2 open boards plus our modules (Tasks 6-9);
  - the reference-script rules and the lint (Task 5);
  - both skills loaded, and skill gaps recorded (Tasks 6-7);
  - the baseline recorded (Tasks 4 and 9);
  - the ratchet documented (Task 9).
- **Not in step 0:** keeping the reference scripts migrated is each later step's job (roadmap "Keeping them current").
- **Names used across tasks:** `Board`, `fetch`, `Prepared`, `Violation`, `new_violations`, `AResult`, `BResult`,
  `MResult`, `lint`, `LintReport`.
