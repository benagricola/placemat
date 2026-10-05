# Module Arrangements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A module declares alternative arrangements for named members or groups, its run proves each one on the module's own terms and writes it into the fragment, and the board's search (and firm cells) choose among them, recorded in the run, the lock and the freeze.

**Architecture:** Declarations (`board.alternative`, `board.arrangement`, `only=`) are collected by the module's script; the module run resolves the board once per arrangement from a snapshot of its declarations, proves each (resolve, DRC, checks) on a scratch board under `arrangements/<id>/`, and writes the default as today plus one `placemat arrangement <json>` text per offered arrangement on User.Comments. A stamping board reads the notes into `CellGeom.arrangements` (arranged geometry built from member deltas and the note's ops), carries the choice in `Placement.arrangement`, searches (arrangement, face) pairs and decided cells' arrangements, replays and locks the choice, and the writer arranges the stamped group before moving it.

**Tech Stack:** Python 3.12, pcbnew (KiCad 9; the checkout's venv has KiCad 10.0.6, which the writer already supports), the placemat_native Rust module (pyo3, untouched), pytest (+xdist), node page tests.

**Spec:** docs/superpowers/specs/2026-10-04-module-member-variants-design.md

## Global Constraints

- Decided by the user (2026-10-04): notes carry each member's default place and an order field; note JSON is percent-escaped as rule notes are; `place.extent_notice_mm` defaults to 1.0; a firm cell with no legal arrangement is placed in its default with a `fixed.part` finding listing every arrangement's refusals.

- Settings, all new, all under existing sections: `place.arrangements` (bool, default true: false lays the default only); `place.arrangement_options_max` (count, default 4, floor 1: options per item, its `place()` included); `place.arrangements_max` (count, default 8, floor 1: arrangements per module, default and groups included); `place.arrangement_note_chars` (count, default 4000, floor 1: characters per note text before it is split); `place.extent_notice_mm` (mm, default 1.0, at least 0: the protrusion above which a module with no alternatives gets `arrangement.extent_fixed`; the user chose 1.0); `score.arrangement` (mm, default 0, at least 0: what a non-default arrangement costs the board).
- A module that declares no alternatives and a board that stamps only such modules: the written `layout.kicad_pcb`, every placement, lock entry and reuse step are byte-identical to before; no note is written; `CellGeom.arrangements == ()`; a `Placement` serialises as `[x, y, rotation, face]` and gains a fifth element only when `arrangement` is not `""`; `run.json` omits `arrangements` when empty. (`reuse.VERSION` goes 4 -> 5 and the settings digest changes, so the first run after the release replays nothing: accepted by the spec.)
- Ids: option and group names are `[a-z0-9_]+`, `default` is reserved; a product id is `item.option` pairs joined by `+` in item order (`c_in.east+r_pull.turned`), a group's id is its name, the default's id is `default`.
- `only=` is a non-empty sequence of arrangement ids, matched as written, checked when the script finishes declaring and before any resolve (`ValueError` naming file:line and the ids the module has); it is a dataclass field of the copper declaration with `omit_default` so a declaration without it digests as before.
- Alternatives take `at=`, `rotation=`, `rotations=`, `face=`, `radius=`, `step=` (and `why=`) and inherit every other keyword from the item's `place()`; no coordinates (Charter: intent, not coordinates).
- Structured data inside, text at the edge: refusals, notes, findings facts, the arrangement record and the note's document are records; sentences are rendered only in `step_text.py`, `finding_text.py`, the console and the studio.
- Tunables are settings with documented defaults, never literals; scoring weights live in `Settings`; `api.md`'s settings table is generated (`.venv/bin/python -m placemat settings --markdown`, pasted between the markers).
- UI labels carry no bracketed explanations (use a tooltip or info icon); red only for errors.
- pcbnew: delete board items with `group.RemoveItem(item)` then `board.Delete(item)`, never `board.Remove` (CLAUDE.md). It is checked on the real board fixture, not only on synthetic boards.
- ASCII only in docs, code comments, commit messages and test text: no em or en dashes, no unicode arrows; plain hyphens and `->`.
- Commit messages carry no reference to Claude, Anthropic or a session and no Co-Authored-By line (the user's CLAUDE.md overrides the harness attribution reminder). After every commit run `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`: it must print nothing.
- Project-agnostic wording: code, tests, docs, skill and commit messages never name a project, board, module, part number or net that uses placemat; fixtures under `fixtures/` may be used by their folder name in test code only.
- A change that can move a placement runs `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out` and puts its tally lines in the commit message, with `fixtures/bench.json` committed when a number changed. The corpus declares no alternatives, so every case must be `same`. `SCRATCH=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad` is exported in the shell that runs the plan; a commit that carries a tally is made as `{ echo "<title>"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -`.
- CPU light: bench `--jobs 2` at most; real-board runs and full suites one at a time; the suite is `.venv/bin/python -m pytest -n 2`, the slow tests `--full`. Never `pkill`, `killall` or grep-kill: stop only PIDs this session started.
- Real-board runs and checks run under `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock <command>`; any copy of a board made for the run is removed afterwards.
- Long commands keep their work and resume; a stopped or failed run never exits silently (the module run resumes each arrangement from its own `reuse.partial.jsonl`).
- Defer to upstream: the clearance, DRC and via rules are KiCad's; nothing in this change adds a rule of placemat's own to the proof.

## Review Focus

Inputs the spec implies and no phase's own tests would reach, most likely first. Each has its test in the task named.

1. One module stamped twice on one board: each cell chooses and is written independently, and the note's net names map per cell (`stamped_net`). Expected: cell A in `c_in.east`, cell B in the default, each group intact and each pose where its own search judged it. Test: Task 2.5.
2. A note that cannot be read as written: a newer note version, a net the parent lacks, a member the cell lacks, a member offset that differs between members, a truncated numbered text. Expected: that cell's arrangements are ignored, `arrangement.stale` names the cell, the reason and the ids, and the board resolves with the default. Test: Task 2.1 (reasons) and Task 2.2 (round trip through KiCad).
3. A cell placed with a non-default arrangement and turned 90 or flipped to the back. Expected: the written members stand exactly where the search's committed geometry put them (arrange first, then `_move_cell` about the arranged box centre). Test: Task 2.5.
4. `arrangements=` on the wrong thing or with the switch off: on a part (`TypeError`), an id the cell does not offer, `place.arrangements = false` with a non-default id, `arrangements="default"`. Expected: a part refuses at the declaration; an unoffered id leaves the item unplaced with `arrangement.missing` naming the offered ids (a stop with `required=True`); with the switch off only `"default"` is offered; `"default"` always holds. Test: Task 2.4.
5. An option that gives `rotation=` where the item's `place()` has `rotations=`, a `Turned`, or a `Near` with its own radius. Expected: the option's rotation replaces the default's turn rules (`rotations=` cleared, `Turned` dropped), an option's `rotations=` clears `rotation=`, and an `at=` replaced option keeps the settings' radius and step. Test: Task 1.3.

## File Structure

New modules (each one responsibility):

- `src/placemat/arrangements.py` - pure declarations: `Alt`, `Option`, `Group`, `Spec`, `Enumeration`, name and keyword checks, option merging (`merged_call`), id formation, enumeration with the two limits, `known_id`. No Board, no KiCad.
- `src/placemat/arrangement_note.py` - pure codec of the fragment's note: `ARRANGEMENT_PREFIX`, ops/keepouts/poses to and from JSON, `base_digest`, `document`, `encode` (escaped, split by `place.arrangement_note_chars`), `read_notes` (join, parse, version check).
- `src/placemat/arranged_geometry.py` - pure: a parsed note document -> `Arrangement` for a stamped `CellGeom` (member poses by delta, the cell's copper from ops, rule areas, boxes) or the reason it is stale; `attach(cell, texts, nets, layers)` for the reader.
- `src/placemat/arrangement_run.py` - the module run's side: the prepared board and its specs, resolving the other arrangements from a snapshot, duplicates, the proof (scratch board, DRC, checks), the record, the extent, the findings, the notes' documents.
- `src/placemat/kicad/arrange.py` - pcbnew side: `write_notes` (fragment) and `arrange_cell` (stamping board).
- `tests/arrangement_support.py` - synthetic modules and cells (pure) and a pcbnew staging helper.

Modified (what changes in each):

- `settings.py` - the six settings and their floors. `findings.py`, `finding_text.py`, `step_text.py` - the `arrangement` finding kind and causes, the `arrangement` step note.
- `layout.py` - `place()` records its call and takes `arrangements=`; `alternative`, `arrangement`, `finish_declarations`, `lay_arrangement`; `only=` on the copper forms; the search over arrangements (`_settle`, `_scan_arrangements`), firm trial, `_Redo` carry, `_step`; `Placement` plumbing in `_recording_commits`, `_apply_commits`.
- `board_geometry.py` - `MemberPose`, `Arrangement`, the `CellGeom` fields and `arranged()`. `geometry.py` - `pose_transform`. `occupancy.py` - arranged cell geometry and commit. `placement.py` - `Placement.arrangement`.
- `reuse.py` (serialisation, `VERSION`, context digest), `lock.py`, `freeze.py`, `explore.py`, `score.py`, `report.py`, `runner.py`, `kicad/read.py`, `kicad/write.py`, `preview_json.py`, `studio.py`, `studio_page.html`, `__init__.py`.
- `skills/placemat/SKILL.md`, `skills/placemat/references/api.md`, `skills/placemat/references/migration.md`, the spec (build notes).
- `fixtures/bench.py` - `--arrangements`.

Test files (one per task unless noted): `tests/test_arrangement_settings.py`, `test_arrangement_declarations.py`, `test_arrangement_only.py`, `test_arrangement_resolve.py`, `test_arrangement_note.py`, `test_arrangement_extent.py`, `test_arrangement_proof.py`, `test_arrangement_run.py`, `test_arranged_geometry.py`, `test_arrangement_reading.py`, `test_arrangement_occupancy.py`, `test_arrangement_pin.py`, `test_arrangement_write.py`, `test_arrangement_search.py`, `test_arrangement_replay.py`, `test_arrangement_lock.py`, `test_arrangement_explore.py`, `test_arrangement_firm.py`, `test_arrangement_studio.py`, `test_arrangement_real_module.py`, `test_arrangement_bench.py`; edits to `test_finding_text.py`, `test_finding_kinds.py`, `test_step_text.py`.

Where the spec and the code differ, the plan follows the code and lists the difference in "Spec and code notes" at the end.

---

# Phase 1: declaration, module proof, the note

### Task 1.1: Settings, finding causes, the arrangement step note

**Files:**
- Modify: `src/placemat/settings.py:112-115` (after `place_step_budget`, add the five `place_*` fields), `:367-368` (after `score_back_face`, add `score_arrangement`), `:591-607` (`_ABOVE_ZERO` and `_AT_LEAST_ZERO`)
- Modify: `src/placemat/findings.py:14-34` (kind), `:53-113` (causes), `:127-153` (SEVERITY)
- Modify: `src/placemat/finding_text.py` (renderers, after the `time.step_limit` renderer near `:686-700`)
- Modify: `src/placemat/step_text.py:126-130` (after `back_face`: the `arrangement` note)
- Modify: `src/placemat/score.py:137-139` (`_MEASURED_APART`)
- Modify: `skills/placemat/references/api.md` (settings table markers around `:4122-4330`; the severities table `:3895-3916`)
- Test: `tests/test_arrangement_settings.py`; edit `tests/test_finding_text.py:20-140` (SAMPLES), `tests/test_finding_kinds.py:31`, `tests/test_step_text.py:29-54`

**Interfaces:**
- Consumes: `settings.S(default, unit, doc)`, `finding_text.renders(cause, *required)`, `step_text.renders(kind)`.
- Produces: `Settings.place_arrangements: bool`, `place_arrangement_options_max: int`, `place_arrangements_max: int`, `place_arrangement_note_chars: int`, `place_extent_notice_mm: float`, `score_arrangement: float`; `FindingKind.ARRANGEMENT`; `FindingCause.ARRANGEMENT_LIMIT | ARRANGEMENT_REFUSED | ARRANGEMENT_DUPLICATE | ARRANGEMENT_STALE | ARRANGEMENT_MISSING | ARRANGEMENT_EXTENT_FIXED` with these facts (all JSON values):
  - `arrangement.limit`: `{"variant": "options"|"arrangements", "arrangements": int, "max_arrangements": int, "options": {item: int}, "max_options": int}`
  - `arrangement.refused`: `{"id": str, "refused": [record]}` where a record is `{"form": "unplaced", "item": str}`, `{"form": "finding", "cause": str, "item": str}`, `{"form": "drc", "bucket": str, "count": int}`, `{"form": "unconnected", "count": int, "default": int}`, `{"form": "verdict", "check": str, "item": str}` or `{"form": "nested_cell", "item": str}`
  - `arrangement.duplicate`: `{"id": str, "same_as": str}`
  - `arrangement.stale`: `{"cell": str, "reason": "version"|"base"|"offset"|"member"|"net"|"text", "ids": [str]}`
  - `arrangement.missing`: `{"item": str, "asked": [str], "offered": [str], "source"?: "lock"}`
  - `arrangement.extent_fixed`: `{"item": str, "sides": [str], "protrudes_mm": float, "alternatives": bool}`
  - step note `{"kind": "arrangement", "id": str, "score"?: float, "cost"?: float, "default_score"?: float, "default_blame"?: [..], "tried": [{"id": str, "score": float|None, "legal": bool}]}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_settings.py
import pytest

from placemat import settings as S
from placemat.settings import Settings, SettingsError


def test_the_arrangement_settings_have_the_documented_defaults():
    s = Settings()
    assert s.place_arrangements is True
    assert s.place_arrangement_options_max == 4
    assert s.place_arrangements_max == 8
    assert s.place_arrangement_note_chars == 4000
    assert s.place_extent_notice_mm == 1.0
    assert s.score_arrangement == 0.0


def test_they_are_set_from_placemat_toml(tmp_path):
    (tmp_path / "placemat.toml").write_text(
        "[place]\narrangements = false\narrangement_options_max = 2\narrangements_max = 5\n"
        "arrangement_note_chars = 100\nextent_notice_mm = 0.5\n[score]\narrangement = 1.5\n")
    s = S.load(tmp_path)
    assert (s.place_arrangements, s.place_arrangement_options_max, s.place_arrangements_max) == (False, 2, 5)
    assert (s.place_arrangement_note_chars, s.place_extent_notice_mm, s.score_arrangement) == (100, 0.5, 1.5)


@pytest.mark.parametrize("text", [
    "[score]\narrangement = -0.1\n", "[place]\narrangements_max = 0\n", "[place]\narrangement_options_max = 0\n",
    "[place]\narrangement_note_chars = 0\n", "[place]\nextent_notice_mm = -1\n"])
def test_a_setting_that_cannot_work_is_refused(tmp_path, text):
    (tmp_path / "placemat.toml").write_text(text)
    with pytest.raises(SettingsError):
        S.load(tmp_path)
```

Append to `SAMPLES` in `tests/test_finding_text.py` (before the closing `]` of the list):

```python
    (C.ARRANGEMENT_LIMIT, {"variant": "arrangements", "arrangements": 12, "max_arrangements": 8,
                           "options": {"c_in": 3, "r_pull": 2}, "max_options": 4},
     "this module declares 12 arrangements, over the 8 place.arrangements_max allows, so only the default is laid out; "
     "name a group (board.arrangement) for each combination that matters"),
    (C.ARRANGEMENT_LIMIT, {"variant": "options", "arrangements": 6, "max_arrangements": 8,
                           "options": {"c_in": 5}, "max_options": 4},
     "c_in has 5 options, over the 4 place.arrangement_options_max allows, so only the default is laid out; "
     "name a group (board.arrangement) for each combination that matters"),
    (C.ARRANGEMENT_REFUSED, {"id": "mirrored", "refused": [{"form": "drc", "bucket": "clearance", "count": 2},
                                                           {"form": "verdict", "check": "hot-loop", "item": "c_in"}]},
     "arrangement mirrored is not offered: DRC clearance x2; hot-loop c_in failed"),
    (C.ARRANGEMENT_DUPLICATE, {"id": "c_in.same", "same_as": "default"},
     "arrangement c_in.same lays out exactly as default and is dropped"),
    (C.ARRANGEMENT_STALE, {"cell": "mod", "reason": "base", "ids": ["c_in.east"]},
     "mod: arrangement c_in.east is ignored: the cell's members are not where the module run left them"),
    (C.ARRANGEMENT_MISSING, {"item": "mod", "asked": ["c_in.west"], "offered": ["default", "c_in.east"]},
     "mod: arrangements= names c_in.west, which the module does not offer (it offers default, c_in.east)"),
    (C.ARRANGEMENT_EXTENT_FIXED, {"item": "c_bulk", "sides": ["east", "north"], "protrudes_mm": 1.8, "alternatives": True},
     "c_bulk sets the module's extent on the east and north sides (1.8 mm past the next part) and has no alternative"),
```

In `tests/test_finding_kinds.py:31` add `"arrangement"` to the expected `set(KINDS)`. In `tests/test_step_text.py:29-54` add to `sample`: `"arrangement": {"id": "c_in.east", "score": 41.2, "cost": 0.0, "default_score": 44.9, "tried": [{"id": "default", "score": 44.9, "legal": True}, {"id": "c_in.east", "score": 41.2, "legal": True}]},`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_settings.py tests/test_finding_text.py tests/test_finding_kinds.py tests/test_step_text.py -q`
Expected: FAIL (`AttributeError: ... place_arrangements`, `AttributeError: ARRANGEMENT_LIMIT`).

- [ ] **Step 3: Implement**

`settings.py`, after `place_step_budget` (line 115):

```python
    place_arrangements: bool = S(True, "bool",
        "whether a stamped cell's module arrangements (alternative layouts a module run proved) are searched; false lays every cell's default only, and a module run lays out its default only")
    place_arrangement_options_max: int = S(4, "count",
        "the most options one item of a module may have, its `place()` included; a module that declares more is not partly accepted: its run lays out the default only and says so")
    place_arrangements_max: int = S(8, "count",
        "the most arrangements a module may have, the default and the named groups included; the product of the items' options counts")
    place_arrangement_note_chars: int = S(4000, "count",
        "the characters one arrangement note text holds before it is split into numbered texts (a note rides on a User.Comments text of the fragment)")
    place_extent_notice_mm: float = S(1.0, "mm",
        "how far a part may stand past the next part on a side of a module that declares no alternatives before `arrangement.extent_fixed` notes it as setting the module's extent")
```
after `score_back_face` (line 367-368):

```python
    score_arrangement: float = S(0.0, "mm",
        "mm the search adds to a cell's non-default arrangement, so an equal score keeps the module's own layout; a project raises it to prefer the module's default by that much")
```
`_ABOVE_ZERO` (line 591 tuple): add `"place_arrangement_options_max", "place_arrangements_max", "place_arrangement_note_chars",`; `_AT_LEAST_ZERO` (line 607): add `"score_arrangement", "place_extent_notice_mm",`.

`findings.py`: in `FindingKind` add `ARRANGEMENT = "arrangement"     # a module's alternative arrangements: over the limits, refused by the module run, stale on the stamping board, asked for and not offered`; causes:

```python
    ARRANGEMENT_LIMIT = (FindingKind.ARRANGEMENT, "arrangement.limit")
    ARRANGEMENT_REFUSED = (FindingKind.ARRANGEMENT, "arrangement.refused")
    ARRANGEMENT_DUPLICATE = (FindingKind.ARRANGEMENT, "arrangement.duplicate")
    ARRANGEMENT_STALE = (FindingKind.ARRANGEMENT, "arrangement.stale")
    ARRANGEMENT_MISSING = (FindingKind.ARRANGEMENT, "arrangement.missing")
    ARRANGEMENT_EXTENT_FIXED = (FindingKind.ARRANGEMENT, "arrangement.extent_fixed")
```
and `FindingKind.ARRANGEMENT: "warning",` in `SEVERITY` (the duplicate and extent_fixed findings are made with `"notice"`).

`finding_text.py`:

```python
# ------------------------------------------------------------------ arrangements
def refusal_record_text(r: dict) -> str:
    """One reason an arrangement is not offered (arrangement_run.prove)."""
    form = r["form"]
    if form == "unplaced":
        return "%s is not placed" % r["item"]
    if form == "finding":
        return "%s (%s)" % (r["cause"], r["item"]) if r.get("item") else r["cause"]
    if form == "drc":
        return "DRC %s x%d" % (r["bucket"], r["count"])
    if form == "unconnected":
        return "%d unconnected, the default has %d" % (r["count"], r["default"])
    if form == "verdict":
        return "%s %s failed" % (r["check"], r["item"])
    if form == "nested_cell":
        return "%s, a cell inside the module, stands elsewhere than in the default" % r["item"]
    return form


@renders(C.ARRANGEMENT_LIMIT, "variant", "arrangements", "max_arrangements", "options", "max_options")
def _arrangement_limit(f):
    tail = "so only the default is laid out; name a group (board.arrangement) for each combination that matters"
    if f["variant"] == "options":
        item, n = max(f["options"].items(), key=lambda kv: (kv[1], kv[0]))
        return "%s has %d options, over the %d place.arrangement_options_max allows, %s" % (item, n, f["max_options"], tail)
    return "this module declares %d arrangements, over the %d place.arrangements_max allows, %s" % (
        f["arrangements"], f["max_arrangements"], tail)


@renders(C.ARRANGEMENT_REFUSED, "id", "refused")
def _arrangement_refused(f):
    return "arrangement %s is not offered: %s" % (f["id"], "; ".join(refusal_record_text(r) for r in f["refused"]))


@renders(C.ARRANGEMENT_DUPLICATE, "id", "same_as")
def _arrangement_duplicate(f):
    return "arrangement %s lays out exactly as %s and is dropped" % (f["id"], f["same_as"])


_STALE_WHY = {"version": "its note is of a version this placemat does not read",
              "base": "the cell's members are not where the module run left them",
              "offset": "the cell's members do not stand at one offset from the module run's places",
              "member": "the note names members the cell does not have, or the cell has members the note does not",
              "net": "the note names a net this board does not have",
              "text": "its note text is not whole or does not parse"}


@renders(C.ARRANGEMENT_STALE, "cell", "reason", "ids")
def _arrangement_stale(f):
    ids = ", ".join(f["ids"]) or "its arrangements"
    return "%s: arrangement %s is ignored: %s" % (f["cell"], ids, _STALE_WHY.get(f["reason"], f["reason"]))


@renders(C.ARRANGEMENT_MISSING, "item", "asked", "offered")
def _arrangement_missing(f):
    return "%s: arrangements= names %s, which the module does not offer (it offers %s)" % (
        f["item"], ", ".join(f["asked"]), ", ".join(f["offered"]) or "nothing")


@renders(C.ARRANGEMENT_EXTENT_FIXED, "item", "sides", "protrudes_mm", "alternatives")
def _arrangement_extent_fixed(f):
    return "%s sets the module's extent on the %s side%s (%.1f mm past the next part) and has no alternative" % (
        f["item"], " and ".join(f["sides"]), "s" if len(f["sides"]) > 1 else "", f["protrudes_mm"])
```
Check the sample sentence for the sides: for two sides the expected sample above reads "on the east and north sides"; the renderer gives "on the east and north side" + "s" = "sides" is built as `side%s`: "the east and north sides" - matches ("%s side%s" with "s" appended after "side").

`step_text.py` after `_back_face`:

```python
@renders("arrangement")
def _arrangement(n):
    if n.get("default_blame") is not None:
        return "arrangement %s: the default module has no legal spot (%s)" % (n["id"], finding_text.blame_text(n["default_blame"]))
    if n.get("score") is None:
        return "arrangement %s" % n["id"]
    return "arrangement %s: %.2f and %.2f for it against %.2f as the default module stands" % (
        n["id"], n["score"], n.get("cost", 0.0), n["default_score"])
```
`score.py:137`: `_MEASURED_APART = ("unplaced", "link_over", "pair_crossed", "arrangement")`.

api.md: run `.venv/bin/python -m placemat settings --markdown`, paste the output between the `<!-- settings-table:begin -->` and `<!-- settings-table:end -->` markers; add to the severities table (after the `time` rows, `:3913-3914`):

```
| `arrangement` (`arrangement.limit`, `arrangement.refused`, `arrangement.stale`, `arrangement.missing`) | warning | a module's alternatives over the limits, refused by the module's proof, ignored on the stamping board, or asked for and not offered |
| `arrangement` (`arrangement.duplicate`, `arrangement.extent_fixed`) | notice | an arrangement dropped for laying out as another; a part that sets the module's extent and has no alternative |
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_settings.py tests/test_finding_text.py tests/test_finding_kinds.py tests/test_finding_severity.py tests/test_step_text.py tests/test_settings_docs.py tests/test_suggestion_cases.py tests/test_no_sentence_parsing.py -q`
Expected: PASS. If `test_every_cause_has_a_sample` or a corpus test names a missing cause, add its sample.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/settings.py src/placemat/findings.py src/placemat/finding_text.py src/placemat/step_text.py src/placemat/score.py skills/placemat/references/api.md tests/test_arrangement_settings.py tests/test_finding_text.py tests/test_finding_kinds.py tests/test_step_text.py
git commit -m "Arrangements: settings, finding causes and the arrangement step note"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.2: Arrangement declarations as pure data

**Files:**
- Create: `src/placemat/arrangements.py`
- Test: `tests/test_arrangement_declarations.py` (this task's part; Task 1.3 appends)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (all in `placemat.arrangements`): `DEFAULT = "default"`; `class Alt(item, **keywords)` with `.item`, `.keywords: dict`; `@dataclass(frozen=True) Option(item: str, name: str, keywords: tuple, why: str = "", file: str = "", line: int = 0)`; `@dataclass(frozen=True) Group(name: str, options: tuple[Option, ...], why: str = "", file: str = "", line: int = 0)`; `@dataclass(frozen=True) Spec(id: str, pairs: tuple, overrides: tuple, group: str = "", why: str = "")` with property `choices -> dict`; `@dataclass(frozen=True) Enumeration(specs: tuple[Spec, ...], over: dict | None, declared: int)`; `DEFAULT_SPEC: Spec`; `check_name(what: str, name: str) -> None`; `check_keywords(who: str, keywords: dict) -> None`; `merged_call(at, raw: dict, option: Option) -> dict`; `spec_id(pairs) -> str`; `enumerate_specs(order, options, groups, max_options, max_arrangements) -> Enumeration`; `known_id(ident, order, options, groups) -> bool`; `all_ids(order, options, groups, cap=64) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_arrangement_declarations.py
import pytest

from placemat import arrangements as A


def opt(item, name, **kw):
    return A.Option(item, name, tuple(kw.items()))


def test_a_name_is_lower_case_words_digits_and_underscores():
    A.check_name("option", "east_2")
    for bad in ("East", "a-b", "a.b", "a+b", "", "default"):
        with pytest.raises(ValueError):
            A.check_name("option", bad)


def test_an_option_takes_the_place_keywords_that_say_where_and_why():
    A.check_keywords("c_in", {"at": 1, "rotation": 90, "rotations": (0, 90), "face": 1, "radius": 2, "step": 0.1, "why": "w"})
    with pytest.raises(TypeError) as e:
        A.check_keywords("c_in", {"required": True})
    assert "required" in str(e.value) and "rotation" in str(e.value)


def test_the_arrangements_are_the_default_the_product_and_the_groups_in_declaration_order():
    options = {"c_in": [opt("c_in", "east")], "r_pull": [opt("r_pull", "turned"), opt("r_pull", "back")]}
    group = A.Group("mirrored", (opt("c_in", "mirrored"), opt("r_pull", "mirrored")))
    e = A.enumerate_specs(["c_in", "r_pull"], options, [group], 4, 20)
    assert [s.id for s in e.specs] == ["default", "r_pull.turned", "r_pull.back", "c_in.east", "c_in.east+r_pull.turned",
                                       "c_in.east+r_pull.back", "mirrored"]
    assert e.over is None and e.declared == 7
    both = e.specs[4]
    assert both.choices == {"c_in": "east", "r_pull": "turned"} and [k for k, _ in both.overrides] == ["c_in", "r_pull"]
    assert e.specs[-1].choices == {"group": "mirrored"} and e.specs[0].choices == {}


def test_exactly_the_limit_is_accepted_and_one_over_is_not():
    options = {"a": [opt("a", "x")], "b": [opt("b", "x")], "c": [opt("c", "x")]}      # 2 * 2 * 2 = 8
    assert A.enumerate_specs(["a", "b", "c"], options, [], 4, 8).over is None
    over = A.enumerate_specs(["a", "b", "c"], options, [A.Group("g", (opt("a", "g"),))], 4, 8)
    assert [s.id for s in over.specs] == ["default"]
    assert over.over == {"variant": "arrangements", "arrangements": 9, "max_arrangements": 8,
                         "options": {"a": 2, "b": 2, "c": 2}, "max_options": 4}


def test_an_item_over_the_option_limit_is_the_options_variant():
    options = {"a": [opt("a", n) for n in "wxyz"]}      # 5 with its place()
    e = A.enumerate_specs(["a"], options, [], 4, 100)
    assert e.over["variant"] == "options" and e.over["options"] == {"a": 5} and len(e.specs) == 1


def test_an_id_is_known_as_written():
    options = {"c_in": [opt("c_in", "east")], "r.pull": [opt("r.pull", "turned")]}
    group = A.Group("mirrored", ())
    args = (["c_in", "r.pull"], options, [group])
    for ok in ("default", "mirrored", "c_in.east", "r.pull.turned", "c_in.east+r.pull.turned"):
        assert A.known_id(ok, *args), ok
    for bad in ("east", "c_in.west", "r.pull.turned+c_in.east", "c_in.east+c_in.east", "nope"):
        assert not A.known_id(bad, *args), bad


def test_the_default_arrangement_has_no_overrides():
    assert A.DEFAULT_SPEC.id == "default" and A.DEFAULT_SPEC.choices == {} and A.DEFAULT_SPEC.overrides == ()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'placemat.arrangements'`.

- [ ] **Step 3: Write the implementation**

```python
# src/placemat/arrangements.py
"""A module's alternative arrangements as declarations: the options an item may take, the named groups, the ids and the limits.

Pure: no Board, no KiCad. `Board.alternative` and `Board.arrangement` (layout.py) validate against the board and build the
records here; `enumerate_specs` turns them into the arrangements a module run lays out, the default first."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import re

DEFAULT = "default"
NAME = re.compile(r"[a-z0-9_]+\Z")
KEYWORDS = ("at", "rotation", "rotations", "face", "radius", "step")        # what an option may change in place()
ALLOWED = KEYWORDS + ("why",)


class Alt:
    """One member's option inside `board.arrangement(name, Alt(item, **keywords), ...)`: the keywords of `board.alternative`."""
    __slots__ = ("item", "keywords")

    def __init__(self, item, **keywords):
        self.item, self.keywords = item, keywords

    def __repr__(self) -> str:
        return "Alt(%r%s)" % (self.item, "".join(", %s=%r" % kv for kv in self.keywords.items()))

    def __eq__(self, other) -> bool:
        return isinstance(other, Alt) and (self.item, self.keywords) == (other.item, other.keywords)

    __hash__ = None


@dataclass(frozen=True)
class Option:
    """What an item does in one arrangement: the place() keywords it changes (in the order given, `why` apart)."""
    item: str                   # the item's key
    name: str                   # the option's name, or the group's for a group's member
    keywords: tuple             # ((keyword, value), ...)
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Group:
    """An arrangement the script names: one option per member it moves, the rest keep their place()."""
    name: str
    options: tuple              # (Option, ...)
    why: str = ""
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Spec:
    """One arrangement a module run lays out: its id, its choices as pairs ((item, option) or ("group", name)), and the options
    to lay over the items' places, in item order."""
    id: str
    pairs: tuple
    overrides: tuple            # ((item key, Option), ...)
    group: str = ""
    why: str = ""

    @property
    def choices(self) -> dict:
        return dict(self.pairs)


DEFAULT_SPEC = Spec(DEFAULT, (), ())


@dataclass(frozen=True)
class Enumeration:
    specs: tuple                # the default first, then the product, then the groups
    over: dict | None           # the facts of arrangement.limit when a limit is passed; the specs are then the default alone
    declared: int               # how many arrangements the declarations make, the default included


def check_name(what: str, name) -> None:
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError("%s name %r: lower-case words, digits and _ only" % (what, name))
    if name == DEFAULT:
        raise ValueError("%s name %r is the module's own layout and cannot be declared" % (what, name))


def check_keywords(who: str, keywords: dict) -> None:
    bad = sorted(set(keywords) - set(ALLOWED))
    if bad:
        raise TypeError("%s: an alternative changes where an item goes, so it takes %s, not %s; every other keyword is "
                        "the item's place() own" % (who, ", ".join(ALLOWED), ", ".join(bad)))


def merged_call(at, raw: dict, option: Option) -> dict:
    """The keywords of `place()` for an option laid over the item's own call: the call as the script made it (`at` and `raw`,
    the keywords as given), with the option's changes. A turn the option gives replaces the call's way of turning: a
    `rotation=` clears `rotations=` and a `rotations=` clears `rotation=` (a `Turned` too)."""
    call = dict(raw)
    call["at"] = at
    given = dict(option.keywords)
    if "rotation" in given and "rotations" not in given:
        call["rotations"] = ()
    if "rotations" in given and "rotation" not in given:
        call["rotation"] = None
    call.update(given)
    return call


def spec_id(pairs) -> str:
    return "+".join("%s.%s" % p for p in pairs)


def count(options: dict, groups) -> int:
    n = 1
    for opts in options.values():
        n *= 1 + len(opts)
    return n + len(groups)


def enumerate_specs(order, options: dict, groups, max_options: int, max_arrangements: int) -> Enumeration:
    """The arrangements of a module: the default, every combination of the items' options (each item contributes its options
    and its default; `itertools.product` order over `order`, the first declared item changing slowest), then each group in
    the order declared. Over either limit nothing is partly accepted: the default alone, and the facts of the finding."""
    order = [k for k in order if options.get(k)]
    sizes = {k: 1 + len(options[k]) for k in order}
    declared = count({k: options[k] for k in order}, groups)
    if any(n > max_options for n in sizes.values()) or declared > max_arrangements:
        facts = {"variant": "options" if any(n > max_options for n in sizes.values()) else "arrangements",
                 "arrangements": declared, "max_arrangements": max_arrangements, "options": sizes,
                 "max_options": max_options}
        return Enumeration((DEFAULT_SPEC,), facts, declared)
    specs = [DEFAULT_SPEC]
    for combo in itertools.product(*[[None] + list(options[k]) for k in order]):
        picked = [(k, o) for k, o in zip(order, combo) if o is not None]
        if picked:
            pairs = tuple((k, o.name) for k, o in picked)
            specs.append(Spec(spec_id(pairs), pairs, tuple(picked)))
    for g in groups:
        specs.append(Spec(g.name, (("group", g.name),), tuple((o.item, o) for o in g.options), g.name, g.why))
    return Enumeration(tuple(specs), None, declared)


def known_id(ident: str, order, options: dict, groups) -> bool:
    """Whether `ident` is an id this module's declarations make, as written, without enumerating the product (a module over
    its limit still says which ids it meant)."""
    if ident == DEFAULT or any(g.name == ident for g in groups):
        return True
    order = [k for k in order if options.get(k)]
    last = -1
    for part in ident.split("+"):
        item, dot, name = part.rpartition(".")      # an item key may hold dots; an option name never does
        if not dot or item not in order or order.index(item) <= last or name not in {o.name for o in options[item]}:
            return False
        last = order.index(item)
    return True


def all_ids(order, options: dict, groups, cap: int = 64) -> list:
    """The ids the declarations make, for a message: the default, then the product and the groups, at most `cap`."""
    out = [DEFAULT]
    for combo in itertools.product(*[[None] + list(options[k]) for k in order if options.get(k)]):
        picked = [(k, o.name) for k, o in zip([k for k in order if options.get(k)], combo) if o is not None]
        if picked:
            out.append(spec_id(picked))
        if len(out) >= cap:
            return out
    return out + [g.name for g in groups]
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/arrangements.py tests/test_arrangement_declarations.py
git commit -m "Arrangements: the declarations as pure data, ids, the limits and the enumeration"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.3: `board.alternative`, `board.arrangement` and the recorded `place()` call

**Files:**
- Create: `tests/arrangement_support.py`
- Modify: `src/placemat/layout.py` - imports at the top (`:1-60`); `Board.__init__` after `self._sites` (`:1007`); `place()` (`:2866-3185`: signature, the "already placed" check at `:2923`, the `_centres.append` at `:3046`, the final append at `:3183-3185`); `row()`/`ring()` (`:3314`, `:3503`) set `_compound`; new methods inserted before `_refuse_either` (`:3187`); `_SITED` (`:9600-9622`)
- Modify: `src/placemat/__init__.py:21-27` (export `Alt`)
- Test: `tests/test_arrangement_declarations.py` (append)

**Interfaces:**
- Consumes: `arrangements.Alt/Option/Group/check_name/check_keywords/merged_call/enumerate_specs` (Task 1.2), `Settings.place_arrangements/place_arrangement_options_max/place_arrangements_max` (Task 1.1).
- Produces: `Board.alternative(item, name: str, **keywords) -> Option`; `Board.arrangement(name: str, *alts: Alt, why: str = "") -> Group`; `Board._place_calls: dict[str, tuple]` (key -> `(item, at, raw_keywords)`); `Board._options: dict[str, list[Option]]`; `Board._arr_groups: list[Group]`; `Board._intent_option(option) -> PlaceIntent`; `Board.arrangement_enumeration() -> Enumeration` (cached, reset by a new declaration; `place.arrangements = false` or no declarations -> `Enumeration((DEFAULT_SPEC,), None, 1)`); `Board.arrangement_limit() -> dict | None`; `placemat.Alt`. `place()` gains the private keyword `_declare: bool = True`; with `False` it returns the `PlaceIntent` without appending it, recording a centre or checking "already placed".

- [ ] **Step 1: Write the failing tests**

```python
# tests/arrangement_support.py
"""Synthetic modules for the arrangement tests: a regulator-like part with a bypass west of it and a pull-up east. Pure: no KiCad
until `kicad_cell_board`."""
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Beside, Edge, Location, Part
from tests.fixtures import board_geometry, footprint


def parts():
    return [footprint("U1", 20, 15, w=6, h=4, nets=("VIN", "OUT"), inst="u1"),
            footprint("C1", 8, 15, w=3, h=1.6, nets=("VIN", "GND"), inst="c_in"),
            footprint("R1", 33, 25, w=3, h=1.6, nets=("OUT", "GND"), inst="r_pull"),
            footprint("R2", 45, 8, w=3, h=1.6, nets=("OUT", "GND"), inst="r_free")]


def module(settings=None) -> Board:
    """u1 on its place, c_in west of it and r_pull east: the module as its script says it (r_free is not placed)."""
    b = Board(board_geometry(parts(), width=60, height=40), edge_margin=1.0, settings=settings or Settings())
    b.place(Part("u1"), at=Location(20, 15), why="the regulator")
    b.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST), why="bypass at VIN")
    b.place(Part("r_pull"), at=Beside(Part("u1"), Edge.EAST), why="pull-up at OUT")
    return b
```

Append to `tests/test_arrangement_declarations.py`:

```python
from placemat import Alt
from placemat.values import Beside, Edge, Location, Near, Part, Turned
from tests.arrangement_support import module


def test_an_option_inherits_the_places_keywords_and_replaces_the_ones_it_gives():
    b = module()
    opt = b.alternative(Part("r_pull"), "turned", rotation=180)
    i = b._intent_option(opt)
    assert i.rotation == 180.0 and i.beside is not None and i.why == "pull-up at OUT" and i.key == "r_pull"
    east = b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST), why="bypass on the output side")
    j = b._intent_option(east)
    assert j.beside.side == Edge.EAST and j.rotation == 0.0 and east.why == "bypass on the output side"


def test_an_options_turn_replaces_the_places_way_of_turning_and_keeps_the_rest():
    """Review focus 5: rotation= over rotations= or a Turned, rotations= over rotation=, and at= over a Near keeps the radius."""
    b = module()
    b.place(Part("r_free"), at=Near(Location(40, 10), radius=4.0), rotations=(0, 90))
    turned = b._intent_option(b.alternative(Part("r_free"), "turned", rotation=180))
    assert turned.rotations == () and turned.rotation == 180.0 and turned.rotation_given and turned.near is not None
    assert turned.radius == 4.0
    spread = b._intent_option(b.alternative(Part("r_free"), "spread", rotations=(0, 180)))
    assert tuple(float(r) for r in spread.rotations) == (0.0, 180.0) and not spread.rotation_given
    beside = b._intent_option(b.alternative(Part("r_free"), "beside", at=Beside(Part("u1"), Edge.NORTH)))
    assert beside.beside is not None and beside.near is None and beside.radius == b.settings.place_radius
    assert tuple(beside.rotations) == (0.0, 90.0)           # the item's own rotations stay when the option gives no turn
    b2 = module()
    b2.place(Part("r_free"), at=Beside(Part("u1"), Edge.NORTH), rotation=Turned(Part("u1"), 90))
    flat = b2._intent_option(b2.alternative(Part("r_free"), "flat", rotation=0))
    assert flat.turned is None and flat.rotation == 0.0


@pytest.mark.parametrize("call, error", [
    (lambda b: b.alternative(Part("r_free"), "x", rotation=90), ValueError),            # no place() of its own
    (lambda b: b.alternative(Part("r_pull"), "x", required=True), TypeError),           # not a keyword an option may change
    (lambda b: b.alternative(Part("r_pull"), "East", rotation=90), ValueError),         # not a lower-case word
    (lambda b: b.alternative(Part("r_pull"), "default", rotation=90), ValueError),      # reserved
    (lambda b: b.alternative(Part("r_pull"), "x", at=Location(3, 4)), TypeError),        # a coordinate
    (lambda b: b.alternative(Part("r_pull"), "x", bogus=1), TypeError),
])
def test_a_bad_alternative_is_refused_where_it_is_written(call, error):
    b = module()
    with pytest.raises(error):
        call(b)


def test_a_duplicate_option_name_and_a_row_members_alternative_are_refused():
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    with pytest.raises(ValueError):
        b.alternative(Part("r_pull"), "turned", rotation=90)
    b.row([Part("r_free")], Edge.NORTH)
    with pytest.raises(ValueError) as e:
        b.alternative(Part("r_free"), "x", rotation=90)
    assert "group" in str(e.value)


def test_an_alternative_is_not_a_second_place_and_leaves_the_declarations_alone():
    b = module()
    before = [i.key for i in b._intents]
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    assert [i.key for i in b._intents] == before
    assert len(b.sites_of("place", "c_in")) == 1 and len(b.sites_of("alternative", "c_in.east")) == 1


def test_a_group_names_the_members_it_moves_and_the_ids_are_formed_as_specified():
    b = module()
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("mirrored", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.EAST), rotation=180),
                  Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.WEST)), why="mirrored")
    ids = [s.id for s in b.arrangement_enumeration().specs]
    assert ids == ["default", "r_pull.turned", "c_in.east", "c_in.east+r_pull.turned", "mirrored"]
    with pytest.raises(ValueError):
        b.arrangement("mirrored", Alt(Part("c_in"), rotation=90))                     # a second group of that name
    with pytest.raises(TypeError):
        b.arrangement("x", Part("c_in"))                                              # not an Alt
    with pytest.raises(ValueError):
        b.arrangement("y", Alt(Part("c_in"), rotation=90), Alt(Part("c_in"), rotation=180))   # a member twice


def test_the_limits_leave_the_default_alone_and_the_switch_does_too():
    import dataclasses
    from placemat.settings import Settings
    b = module(dataclasses.replace(Settings(), place_arrangements_max=2))
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)            # 2 * 2 = 4 > 2
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default"]
    assert b.arrangement_limit()["variant"] == "arrangements"
    off = module(dataclasses.replace(Settings(), place_arrangements=False))
    off.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    assert [s.id for s in off.arrangement_enumeration().specs] == ["default"] and off.arrangement_limit() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py -v`
Expected: FAIL (`ImportError: cannot import name 'Alt' from 'placemat'`).

- [ ] **Step 3: Implement**

`src/placemat/__init__.py`: add `from .arrangements import Alt` after the `.context` import and `"Alt"` first in `__all__`.

`layout.py` imports (near line 41): `from .arrangements import DEFAULT_SPEC, Alt, Enumeration, Group, Option, check_keywords, check_name, enumerate_specs, merged_call`.

`Board.__init__` after `self._sites: list = []` (line 1007):

```python
        self._place_calls: dict = {}        # item key -> (the item as given, `at=`, the other place() keywords as given): what an alternative lays over
        self._options: dict = {}            # item key -> [Option]: board.alternative(), in declaration order
        self._arr_groups: list = []         # Group: board.arrangement(), in declaration order
        self._compound: str = ""            # "row" or "ring" while one of them declares its members
        self._arrangement_enum = None       # arrangements.Enumeration, cached until a declaration changes it
        self._declarations_done = False
        self._only_sites: dict = {}         # copper index -> (file, line) of an `only=` (Task 1.4)
        self._copper_uses: dict = {}        # copper index -> the indexes of the copper intents it is drawn from or fitted round (Task 1.4)
```

`place()`: signature gains `_declare: bool = True` after `_row_of`. At the top of the body (before `radius = ...`, line 2918):

```python
        raw = {"rotation": rotation, "face": face, "radius": radius, "step": step, "rotations": rotations, "priority": priority,
               "required": required, "why": why, "drops": drops, "budget": budget}
```
Line 2923 `if any(i.key == key for i in self._intents): raise ...` becomes `if _declare and any(...)`. Line 3046 `self._centres.append((key, at))` becomes `if _declare: self._centres.append((key, at))`. Before the first `if isinstance(at, Pin)` the item's original `at` is `at`; keep it as `given_at = at` right after `raw`. The last lines (3183-3185):

```python
        if _declare:
            self._intents.append(intent)
            self._place_calls[key] = (item, given_at, raw, self._compound)
            self._arrangement_enum = None
        return intent
```
`row()` and `ring()`: wrap each body that calls `self.place(...)` for members in `self._compound = "row"` / `"ring"` with `try/finally` restoring `""` (the ring's call is at `:3549`; `row` records `_row_members` at `:3434`, which `alternative` also checks).

New methods (before `_refuse_either`, line 3187):

```python
    # ------------------------------------------------------------ arrangements
    @staticmethod
    def _refuse_coordinates(key: str, at) -> None:
        """An alternative is a relation, as the default is: no number as a coordinate."""
        def numeric(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool)
        if isinstance(at, Near):
            Board._refuse_coordinates(key, at.location)
            return
        bad = (isinstance(at, (Location, Centre)) and (numeric(at.x) or numeric(at.y))) or \
              (isinstance(at, tuple) and any(numeric(v) for v in at))
        if bad:
            raise TypeError("%s: an alternative is a relation (Beside, Pin, a turn), as the default is; %r names a coordinate"
                            % (key, at))

    def _checked_option(self, item, name: str, keywords: dict) -> Option:
        site = _script_site()
        geom, key, kind = self._item(item)
        call = self._place_calls.get(key)
        if call is None:
            raise ValueError("%s: board.alternative() adds an option to an item's place(), and the script has not placed it; "
                             "a row's, a ring's or a block's member has none of its own: name a group of them" % key)
        if kind != "part":
            raise TypeError("%s: an alternative is for a part of a module; a %s's arrangements are the ones its own module "
                            "offers (arrangements= on its place())" % (key, kind))
        if key in self._row_members or call[3]:
            raise ValueError("%s is a member of a %s: an arrangement of a row is a named group (board.arrangement)"
                             % (key, "row" if key in self._row_members else call[3]))
        if "+" in key:
            raise ValueError("%s: an item key with a + cannot be named in an arrangement id" % key)
        check_name("option", name)
        check_keywords(key, keywords)
        self._refuse_coordinates(key, keywords.get("at"))
        option = Option(key, name, tuple((k, v) for k, v in keywords.items() if k != "why"), keywords.get("why", ""), *site)
        self._intent_option(option)         # built now: a bad keyword or a bad relation is refused where it is written
        return option

    def alternative(self, item, name: str, **keywords) -> Option:
        """Another way an item the script has placed may stand: an option on that item's `place()`, which stays its default.
        `keywords` are those of `place()` that change where an item goes (`at=`, `rotation=`, `rotations=`, `face=`, `radius=`,
        `step=`) and `why=`; every other keyword and each one not given is the item's own. An option that gives `rotation=`
        replaces the item's `rotations=` and `Turned`, and one that gives `rotations=` replaces its `rotation=`. The module run
        lays out every arrangement and offers the ones that pass its own DRC and checks; the board's search chooses among them."""
        option = self._checked_option(item, name, keywords)
        if any(o.name == name for o in self._options.get(option.item, ())):
            raise ValueError("%s already has an option %r" % (option.item, name))
        self._options.setdefault(option.item, []).append(option)
        self._arrangement_enum = None
        return option

    def arrangement(self, name: str, *alts, why: str = "") -> Group:
        """One arrangement the script names, made of the options of the members it moves, `Alt(item, **keywords)` each (the
        keywords of `alternative`); the members not named keep their `place()`. For members whose alternatives only make sense
        together, and for a row or a pair that moves as a unit."""
        check_name("arrangement", name)
        if any(g.name == name for g in self._arr_groups):
            raise ValueError("arrangement %r is already declared" % name)
        if not alts:
            raise ValueError("arrangement %r names no member: give Alt(item, **keywords) for each one it moves" % name)
        seen, options = set(), []
        for a in alts:
            if not isinstance(a, Alt):
                raise TypeError("arrangement %r takes Alt(item, **keywords), not %r" % (name, a))
            o = self._checked_option(a.item, name, a.keywords)
            if o.item in seen:
                raise ValueError("arrangement %r names %s twice" % (name, o.item))
            seen.add(o.item)
            options.append(o)
        group = Group(name, tuple(options), why, *_script_site())
        self._arr_groups.append(group)
        self._arrangement_enum = None
        return group

    def _intent_option(self, option: Option) -> "PlaceIntent":
        """The PlaceIntent an option makes of its item: the item's own `place()` call with the option laid over it, built
        without being declared."""
        item, at, raw, _ = self._place_calls[option.item]
        call = merged_call(at, raw, option)
        return Board.place.__wrapped__(self, item, call.pop("at"), _declare=False, **call)

    def arrangement_enumeration(self) -> Enumeration:
        """The arrangements this module offers, the default first (`place.arrangements` false, or no declaration: the default
        alone). Over a limit: the default alone, with the facts of `arrangement.limit` (`arrangement_limit`)."""
        if self._arrangement_enum is None:
            if not self.settings.place_arrangements or not (self._options or self._arr_groups):
                self._arrangement_enum = Enumeration((DEFAULT_SPEC,), None, 1)
            else:
                order = [i.key for i in sorted(self._intents, key=lambda i: i.index) if i.key in self._options]
                self._arrangement_enum = enumerate_specs(order, self._options, self._arr_groups,
                                                         self.settings.place_arrangement_options_max,
                                                         self.settings.place_arrangements_max)
        return self._arrangement_enum

    def arrangement_limit(self) -> dict | None:
        """The facts of `arrangement.limit` when the declarations pass a limit, else None."""
        return self.arrangement_enumeration().over
```
`_SITED` additions: `"alternative": lambda b, out, a, k: ["%s.%s" % (out.item, out.name)],` and `"arrangement": lambda b, out, a, k: [out.name],`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py tests/test_builder_golden.py tests/test_at.py tests/test_beside.py -q`
Expected: PASS. The last two are the existing `place()` paths; they must be unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py src/placemat/__init__.py tests/arrangement_support.py tests/test_arrangement_declarations.py
git commit -m "Arrangements: board.alternative and board.arrangement over a recorded place() call"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.4: `only=` on the copper forms

**Files:**
- Modify: `src/placemat/layout.py` - `CopperIntent` (`:439-459`, add the field after `declared`); `_copper_intent` (`:4868-4879`); signatures and the `_copper_intent` call of each form: `track` (`:4970`, call `:5155`), `pair` (`:5176`, call `:5236`), `vias` (`:5238`, calls `:5324` and `:5358`), `via` (`:5394`, call `:5457`), `stitch` (`:5465`, call `:5579`), `pour` (`:5985`, call `:6125`), `plane` (`:6323`, call `:6371`), `finger` (`:6376`, call `:6406`); `Board.finish_declarations` new, after `arrangement_limit`
- Test: `tests/test_arrangement_only.py`

**Interfaces:**
- Consumes: `Board._only_sites`, `_copper_uses`, `_declarations_done` (Task 1.3), `arrangements.known_id/all_ids`.
- Produces: `CopperIntent.only: tuple` (ids, `()` = every arrangement; `omit_default`); `Board._only(only, form) -> tuple`; every copper form takes `only=None`; `Board.finish_declarations() -> None` (idempotent; raises `ValueError("<file>:<line>: <key>: only= names 'x', which is not an arrangement of this module; it has ...")`); `CopperIntent.applies_in(ident: str) -> bool` (empty `only` or the id in it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_only.py
import pytest

from placemat import reuse
from placemat.values import Beside, CopperLayer, Edge, Net, PadRef, Part
from tests.arrangement_support import module

F = CopperLayer.F


def declared(b):
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("mirrored", __import__("placemat").Alt(Part("c_in"), rotation=180))
    return b


def track(b, **kw):
    return b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=F, **kw)


def test_a_declaration_without_only_is_in_every_arrangement():
    b = declared(module())
    c = track(b)
    assert c.only == () and c.applies_in("default") and c.applies_in("c_in.east")


def test_only_names_the_arrangements_a_declaration_exists_in():
    b = declared(module())
    c = track(b, only=("mirrored", "c_in.east+r_pull.turned"))
    assert c.only == ("mirrored", "c_in.east+r_pull.turned")
    assert c.applies_in("mirrored") and not c.applies_in("default") and not c.applies_in("c_in.east")
    b.finish_declarations()


@pytest.mark.parametrize("only", [("nope",), ("east",), ("r_pull.turned+c_in.east",)])
def test_an_unknown_id_is_refused_with_the_line_and_the_ids_the_module_has(only):
    b = declared(module())
    track(b, only=only)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    text = str(e.value)
    assert "test_arrangement_only.py:" in text and "only=" in text and "c_in.east" in text and "mirrored" in text


def test_an_empty_only_and_a_bare_string_are_refused_where_written():
    b = declared(module())
    with pytest.raises(ValueError):
        track(b, only=())
    with pytest.raises(TypeError):
        track(b, only="default")
    with pytest.raises(TypeError):
        b.place(Part("r_free"), only=("default",))                    # a form that takes no only=


def test_default_names_the_default_arrangement():
    b = declared(module())
    track(b, only=("default",)).applies_in("default")
    b.finish_declarations()


def test_every_copper_form_takes_only():
    import inspect
    from placemat.layout import Board
    for form in ("track", "pair", "vias", "via", "stitch", "pour", "plane", "finger"):
        assert "only" in inspect.signature(getattr(Board, form)).parameters, form


def test_only_is_in_the_reuse_digest_only_when_given():
    b = declared(module())
    plain, narrowed = track(b), track(b, only=("mirrored",))
    assert "only=" not in reuse.canonical(plain) and "only=" in reuse.canonical(narrowed)


def test_a_pour_fitted_round_a_via_that_exists_in_fewer_arrangements_is_refused():
    b = declared(module())
    v = b.via(Net("VIN"), PadRef(Part("u1"), 1), only=("mirrored",))
    b.pour(Net("VIN"), [PadRef(Part("u1"), 1), v], layer=F, swallow_pads=True)           # in every arrangement, its via in one
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert "via" in str(e.value) and "only" in str(e.value)
```
(`b.via(Net, PadRef)` places a via at a pad; if `via` requires `size/drill` defaults they come from the board.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_only.py -v`
Expected: FAIL (`TypeError: track() got an unexpected keyword argument 'only'`).

- [ ] **Step 3: Implement**

`CopperIntent` (after `declared`):

```python
    only: tuple = field(default=(), metadata={"omit_default": True})    # the arrangement ids it exists in; () every one (arrangements.py)

    def applies_in(self, ident: str) -> bool:
        return not self.only or ident in self.only
```
`_copper_intent(self, key, net, priority, plan, refs, why, bridge=False, extra_owners=frozenset(), only=())`: pass `only=only` into the `CopperIntent(...)` constructor call (keyword) and, after `self._copper.append(ci)`, `if only: self._only_sites[ci.index] = _script_site()`.

```python
    def _only(self, only, form: str) -> tuple:
        """The arrangement ids a copper declaration exists in: a non-empty sequence of ids, or None for every arrangement."""
        if only is None:
            return ()
        if isinstance(only, str) or not hasattr(only, "__iter__"):
            raise TypeError("%s: only= is a sequence of arrangement ids, only=(%r,) for one; got %r" % (form, only, only))
        ids = tuple(only)
        if not ids:
            raise ValueError("%s: only= is empty, so the declaration would exist in no arrangement; leave it out for every one" % form)
        if not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise TypeError("%s: only= is a sequence of distinct arrangement ids, not %r" % (form, only))
        return ids
```
For each form: add `only=None` to the signature (before `why`) and pass `only=self._only(only, "<form>")` to its `_copper_intent` call(s) (`"track"`, `"pair"`, `"vias"` at both calls, `"via"`, `"stitch"`, `"pour"`, `"plane"`, `"finger"`). After the `track` intent is created (`:5155`) add `self._copper_uses[intent.index] = tuple(p.index for p in points if isinstance(p, CopperIntent))`; after the `pour` intent (`:6125`, where `intent.members = vias` is set) `self._copper_uses[intent.index] = tuple(v.index for v in vias)`.

`finish_declarations` (after `arrangement_limit`):

```python
    def finish_declarations(self) -> None:
        """Called once the script has declared everything and before any resolve: the checks that need every declaration in.
        An `only=` names arrangements of this module; copper fitted round or drawn from other copper exists wherever that does."""
        if self._declarations_done:
            return
        self._declarations_done = True
        from .arrangements import all_ids, known_id
        order = [i.key for i in sorted(self._intents, key=lambda i: i.index) if i.key in self._options]
        for c in self._copper:
            for ident in c.only:
                if not known_id(ident, order, self._options, self._arr_groups):
                    file, line = self._only_sites.get(c.index, ("", 0))
                    raise ValueError("%s:%d: %s: only= names %r, which is not an arrangement of this module; it has %s"
                                     % (file, line, c.key, ident, ", ".join(all_ids(order, self._options, self._arr_groups))))
        by_index = {c.index: c for c in self._copper}
        for c in self._copper:
            for idx in self._copper_uses.get(c.index, ()):
                m = by_index.get(idx)
                if m is not None and m.only and (not c.only or not set(c.only) <= set(m.only)):
                    file, line = self._only_sites.get(c.index, self._only_sites.get(idx, ("", 0)))
                    raise ValueError("%s:%d: %s is drawn from or fitted round %s, which exists only in %s: give it an only= "
                                     "inside that set" % (file, line, c.key, m.key, ", ".join(m.only)))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_only.py tests/test_copper.py tests/test_beside_copper.py tests/test_builder_golden.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_arrangement_only.py
git commit -m "Arrangements: only= on the copper forms, checked once the script has finished declaring"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.5: Resolving an arrangement from a snapshot

**Files:**
- Modify: `src/placemat/layout.py` - `resolve()` (`:6468-6480`) calls `finish_declarations()` and `lay_arrangement(DEFAULT_SPEC)`; `_resolve_once` after the `SETUP_RULE_NOTE` line (`:6572`) adds the limit finding; new methods after `finish_declarations`; line `:5462` slice
- Create: `src/placemat/arrangement_run.py` (first part: `Prepared`, `begin`, `resolve_spec`, `signature`)
- Test: `tests/test_arrangement_resolve.py`

**Interfaces:**
- Consumes: `Board._snapshot()/_restore()` (`layout.py:2597-2611`), `Board._resolve(progress, reuse, explore, lock, routes, on_step, on_begin, partial)` (`:6482`), `Spec`, `CopperIntent.applies_in` (Task 1.4).
- Produces: `Board.arrangement_specs() -> tuple[Spec, ...]` (`finish_declarations()`, then the enumeration's specs, the default first); `Board.lay_arrangement(spec) -> None` (puts the board's declarations as `spec` has them: each override's option laid over the item's `PlaceIntent` in place, `index`/`line`/`file` kept, and only the copper that exists in `spec.id`; call after `_restore`); `arrangement_run.Prepared(board, saved, specs)` (`saved` = `board._snapshot()` taken after `finish_declarations()`); `arrangement_run.begin(board) -> Prepared`; `arrangement_run.resolve_spec(prepared, spec, *, reuse=None, lock=(), routes=None, partial=None) -> Plan` (restores, lays, `board._resolve(...)`; the default spec is laid too); `arrangement_run.signature(plan) -> str` (digest of the placements and the copper ops: equal text means the same arrangement); `Board._laid: str` (id of the arrangement last laid, `"default"` initially).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_resolve.py
import dataclasses

from placemat import Alt, arrangement_run as run
from placemat.settings import Settings
from placemat.values import Beside, CopperLayer, Edge, Net, PadRef, Part
from tests.arrangement_support import module

F = CopperLayer.F


def board():
    b = module()
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    return b


def test_the_default_resolves_as_the_script_says_and_an_alternative_lays_its_option_over():
    b = board()
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default", "r_pull.turned", "c_in.east", "c_in.east+r_pull.turned"]
    default = run.resolve_spec(prepared, prepared.specs[0])
    east = run.resolve_spec(prepared, prepared.specs[2])
    u1 = default.placement("u1").location.x
    assert default.placement("c_in").location.x < u1 < east.placement("c_in").location.x
    again = run.resolve_spec(prepared, prepared.specs[0])
    assert again.placements == default.placements                      # the board was put back between resolves


def test_the_option_turns_one_member_and_leaves_the_rest():
    b = board()
    prepared = run.begin(b)
    default = run.resolve_spec(prepared, prepared.specs[0])
    turned = run.resolve_spec(prepared, prepared.specs[1])
    assert turned.placement("r_pull").rotation == 180.0 and default.placement("r_pull").rotation == 0.0
    assert turned.placement("c_in") == default.placement("c_in")


def test_copper_exists_only_in_the_arrangements_it_names():
    b = board()
    b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=F)
    b.track(Net("OUT"), [PadRef(Part("r_pull"), 1), PadRef(Part("u1"), 2)], layer=F, only=("r_pull.turned",))
    prepared = run.begin(b)
    default = run.resolve_spec(prepared, prepared.specs[0])
    turned = run.resolve_spec(prepared, prepared.specs[1])
    nets = lambda plan: sorted({op.net for op in plan.copper if hasattr(op, "net")})
    assert nets(default) == ["VIN"] and nets(turned) == ["OUT", "VIN"]


def test_two_arrangements_that_resolve_alike_have_one_signature():
    b = board()
    b.alternative(Part("c_in"), "same", at=Beside(Part("u1"), Edge.WEST))      # the default's own relation
    prepared = run.begin(b)
    plans = {s.id: run.resolve_spec(prepared, s) for s in prepared.specs}
    assert run.signature(plans["c_in.same"]) == run.signature(plans["default"])
    assert run.signature(plans["c_in.east"]) != run.signature(plans["default"])


def test_the_limit_finding_is_on_the_default_plan_and_the_resolve_is_the_default_alone():
    b = module(dataclasses.replace(Settings(), place_arrangements_max=2))
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default"]
    plan = run.resolve_spec(prepared, prepared.specs[0])
    (f,) = [f for f in plan.findings if f.cause == "arrangement.limit"]
    assert f.facts["arrangements"] == 4 and f.facts["max_arrangements"] == 2 and f.severity == "warning"


def test_a_board_that_declares_no_alternative_resolves_as_before():
    plain = module().resolve()
    prepared = run.begin(module())
    got = run.resolve_spec(prepared, prepared.specs[0])
    assert got.placements == plain.placements and [str(f) for f in got.findings] == [str(f) for f in plain.findings]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_resolve.py -v`
Expected: FAIL (`ImportError: cannot import name 'arrangement_run' from 'placemat'`).

- [ ] **Step 3: Implement**

`layout.py` `Board.lay_arrangement` (after `finish_declarations`):

```python
    _laid = DEFAULT_SPEC.id          # the arrangement the board's declarations are laid as

    def lay_arrangement(self, spec) -> None:
        """Put the board's declarations as arrangement `spec` has them: each option of `spec` laid over its item's PlaceIntent
        (the intent keeps its place in the declaration order and its line), and only the copper that exists in `spec`. Called on
        a board `_restore` has put back; the default is laid before any plain resolve."""
        for key, option in spec.overrides:
            old = next(i for i in self._intents if i.key == key)
            new = self._intent_option(option)
            new.index, new.line, new.file = old.index, old.line, old.file
            old.__dict__.clear()
            old.__dict__.update(new.__dict__)
        self._copper = [c for c in self._copper if c.applies_in(spec.id)]
        self._laid = spec.id
```
`resolve()` (line 6468) first lines: `self.finish_declarations(); self.lay_arrangement(DEFAULT_SPEC)` (only when `self._laid == DEFAULT_SPEC.id`: cheap filter, idempotent). `_resolve_once` after `plan.findings.extend(self._finding(C.SETUP_RULE_NOTE, ...` (line 6572) add:

```python
        limit = self.arrangement_limit()
        if limit is not None:
            plan.findings.append(self._finding(C.ARRANGEMENT_LIMIT, limit, "warning"))
```
Line 5462: `for c in self._copper[:intent.index] if ...` becomes `for c in self._copper if c.index < intent.index and ...` (`self._copper` can now hold fewer intents than its highest index).

```python
# src/placemat/arrangement_run.py
"""The module run's side of arrangements: the board prepared once its script has declared everything, each other arrangement
resolved from a snapshot of the declarations, the proof, the record, the extent and the fragment's notes (the later tasks of
Phase 1 add them to this module)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .arrangements import DEFAULT_SPEC, Spec


@dataclass
class Prepared:
    board: object
    saved: tuple                # Board._snapshot() before any arrangement is laid
    specs: tuple                # arrangements.Spec, the default first


def begin(board) -> Prepared:
    """The board as its script left it, snapshotted, with the arrangements its declarations make."""
    board.finish_declarations()
    return Prepared(board, board._snapshot(), board.arrangement_specs())


def resolve_spec(prepared: Prepared, spec: Spec, *, reuse=None, lock=(), routes=None, partial=None):
    """One arrangement's Plan: the declarations put back, `spec` laid over them, and the same resolve the default gets (not
    reported to a studio: the module run's own plan is the default's)."""
    board = prepared.board
    board._restore(prepared.saved)
    board.lay_arrangement(spec)
    return board._resolve(None, reuse, None, lock, routes, None, None, partial)


def signature(plan) -> str:
    """A digest of where the plan put every item and the copper it planned: two arrangements with one signature are one."""
    h = hashlib.sha256()
    for s in plan.steps:
        h.update(repr((s.item, s.kind, s.placement)).encode())
    for op in plan.copper:
        h.update(repr(op).encode())
    return h.hexdigest()[:16]
```
`Board.arrangement_specs()` added to layout.py: `self.finish_declarations(); return self.arrangement_enumeration().specs`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_resolve.py tests/test_arrangement_only.py tests/test_arrangement_declarations.py tests/test_copper_room.py tests/test_beside.py -q`
Expected: PASS. If `test_the_default_resolves...` shows the restored board differing, read what `_snapshot` (`layout.py:2597`) leaves out and extend `_restore` for it (the note `_laid` must survive: it is a class attribute default, set on the instance by `lay_arrangement`).

- [ ] **Step 5: Bench and commit**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`
Expected: every case `same`.

```bash
git add src/placemat/layout.py src/placemat/arrangement_run.py tests/test_arrangement_resolve.py
{ echo "Arrangements: resolve each arrangement from a snapshot of the declarations"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.6: The note codec

**Files:**
- Create: `src/placemat/arrangement_note.py`
- Test: `tests/test_arrangement_note.py`

**Interfaces:**
- Consumes: `copper.Track/Via/Pour/Zone/Text`, `layout.PlacedKeepout`, `placement.Placement`, `values.CopperLayer/Face/Location`.
- Produces: `ARRANGEMENT_PREFIX = "placemat arrangement "`; `VERSION = 1`; `pose_json(p: Placement) -> list` (`[x, y, rotation, face]`, rounded to 4 places); `pose_from_json(v) -> Placement`; `op_to_json(op) -> dict`; `op_from_json(d) -> op` (kinds `track`, `via`, `pour`, `zone`, `text`; floats rounded to 6 places); `keepout_to_json(k) -> dict`; `keepout_from_json(d) -> PlacedKeepout`; `base_digest(places) -> str` (places = `[(inst, Placement)]`, sorted by inst, 16 hex); `document(ident, choices, members, ops, keepouts) -> dict` where `members = [(inst, pose, default_pose)]` giving `{"v": 1, "id", "choices", "base", "members": [{"inst", "x", "y", "rotation", "face", "from": [x, y, rotation, face]}], "ops", "keepouts"}`; `encode(doc, chars: int) -> list[str]`; `read_notes(texts) -> tuple[list[dict], list[dict]]` (documents, problems `{"reason": "text"|"version", "ids": [str]}`); `class NoteError(Exception)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_note.py
import json

import pytest

from placemat import arrangement_note as N
from placemat.copper import Pour, Text, Track, Via, Zone
from placemat.layout import PlacedKeepout
from placemat.placement import Placement
from placemat.values import CopperLayer, Face, Location

F, B = CopperLayer.F, CopperLayer.B
OPS = [Track("VIN", F, 0.3, Location(1.0, 2.0), Location(3.5, 2.0)),
       Track("VIN", F, 0.3, Location(3.5, 2.0), Location(5.0, 4.0), mid=Location(4.5, 2.5)),
       Via("GND", Location(2.0, 3.0), 0.3, 0.6),
       Via("GND", Location(2.0, 5.0), 0.2, 0.45, layers=(F, CopperLayer.IN1)),
       Pour("SRC", F, ((0.0, 0.0), (4.0, 0.0), (4.0, 3.0)), 0.2, True),
       Zone("GND", CopperLayer.IN1, ((0.0, 0.0), (9.0, 0.0), (9.0, 9.0)), 0.2, 0.2, True, 0.25),
       Text("SW", Location(1.0, 1.0), Face.FRONT, 0.8, 0.15, 90.0, "left", "top", True, False, "", None, None)]


@pytest.mark.parametrize("op", OPS)
def test_an_op_round_trips_through_json(op):
    d = N.op_to_json(op)
    assert json.loads(json.dumps(d)) == d and N.op_from_json(d) == op


def test_a_keepout_round_trips_to_what_the_writer_needs():
    k = PlacedKeepout("ant", ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0)), Location(0, 0), 0.0, ("tracks", "vias"), (F,),
                      frozenset({"GND"}), frozenset({"U1"}), "an antenna", None, frozenset(), frozenset())
    back = N.keepout_from_json(json.loads(json.dumps(N.keepout_to_json(k))))
    assert (back.name, back.poly, back.excludes, back.layers, back.allow, back.why) == \
           (k.name, k.poly, k.excludes, k.layers, k.allow, k.why)


def test_the_base_digest_follows_the_default_places_and_nothing_else():
    a = [("c_in", Placement(Location(1, 2), 90.0, Face.FRONT)), ("u1", Placement(Location(5, 2), 0.0, Face.FRONT))]
    assert N.base_digest(a) == N.base_digest(list(reversed(a)))
    b = [(a[0][0], Placement(Location(1, 2.001), 90.0, Face.FRONT)), a[1]]
    assert N.base_digest(a) != N.base_digest(b)


def doc():
    return N.document("c_in.east", {"c_in": "east"},
                      [("c_in", Placement(Location(9.5, 3.0), 180.0, Face.FRONT), Placement(Location(2.5, 3.0), 0.0, Face.FRONT)),
                       ("u1", Placement(Location(6.0, 3.0), 0.0, Face.FRONT), Placement(Location(6.0, 3.0), 0.0, Face.FRONT))],
                      OPS, [])


def test_a_note_is_a_text_with_no_brace_dollar_quote_or_percent_a_kicad_text_reads_as_markup():
    (text,) = N.encode(doc(), 100000)
    assert text.startswith(N.ARRANGEMENT_PREFIX) and "\n" not in text
    assert not any(c in text for c in '{}$"\\')
    docs, problems = N.read_notes([text])
    assert problems == [] and docs == [doc()]


def test_a_net_name_with_markup_characters_survives():
    d = N.document("x.y", {"x": "y"}, [], [Via("/VIN{a}$%", Location(1, 1), 0.3, 0.6)], [])
    docs, _ = N.read_notes(N.encode(d, 100000))
    assert docs[0]["ops"][0]["net"] == "/VIN{a}$%"


def test_a_long_note_splits_into_numbered_texts_and_joins_again():
    texts = N.encode(doc(), 120)
    assert len(texts) > 2 and all(len(t) <= 120 + 60 for t in texts)
    docs, problems = N.read_notes(list(reversed(texts)))            # the order KiCad lists a group's items in is not the order written
    assert problems == [] and docs == [doc()]


def test_two_arrangements_split_into_texts_that_are_told_apart():
    other = N.document("c_in.west", {"c_in": "west"}, [], [], [])
    docs, problems = N.read_notes(N.encode(doc(), 120) + N.encode(other, 120))
    assert problems == [] and sorted(d["id"] for d in docs) == ["c_in.east", "c_in.west"]


def test_a_truncated_or_newer_note_is_a_problem_not_a_crash():
    texts = N.encode(doc(), 120)
    docs, problems = N.read_notes(texts[:-1])
    assert docs == [] and problems and problems[0]["reason"] == "text"
    newer = dict(doc(), v=2)
    docs, problems = N.read_notes(N.encode(newer, 100000))
    assert docs == [] and problems == [{"reason": "version", "ids": ["c_in.east"]}]
    docs, problems = N.read_notes([N.ARRANGEMENT_PREFIX + "not%20json"])
    assert docs == [] and problems[0]["reason"] == "text"


def test_notes_of_a_cell_with_none_read_as_nothing():
    assert N.read_notes([]) == ([], [])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_note.py -v`
Expected: FAIL (`ModuleNotFoundError: placemat.arrangement_note`).

- [ ] **Step 3: Implement**

```python
# src/placemat/arrangement_note.py
"""The fragment's arrangement notes: one User.Comments text (or several numbered ones) per offered non-default arrangement,
`placemat arrangement <escaped json>`, the transport the faces and the clearance rules already use (pcb layout stamps it with
the cell). The document holds the members' places in the fragment's frame, the module's own copper as ops (the codec for the
copper.py records the writer reads back), the rule areas, and the default places the stamping board measures its offset by.

Like a rule note, the json is percent-escaped: KiCad reads braces and `$` in a text as markup."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import quote, unquote

from .copper import Pour, Text, Track, Via, Zone
from .placement import Placement
from .values import CopperLayer, Face, Location

ARRANGEMENT_PREFIX = "placemat arrangement "
VERSION = 1
_SAFE = ",:[]._-"


class NoteError(Exception):
    pass


def _r(v: float, places: int = 6) -> float:
    return round(float(v), places)


def _pt(p) -> list:
    return [_r(p.x), _r(p.y)] if isinstance(p, Location) else [_r(p[0]), _r(p[1])]


def _loc(v) -> Location:
    return Location(float(v[0]), float(v[1]))


def pose_json(p: Placement) -> list:
    return [_r(p.location.x, 4), _r(p.location.y, 4), _r(p.rotation, 4), p.face.value]


def pose_from_json(v) -> Placement:
    return Placement(Location(float(v[0]), float(v[1])), float(v[2]), Face(v[3]))


def op_to_json(op) -> dict:
    if isinstance(op, Track):
        d = {"kind": "track", "net": op.net, "layer": op.layer.value, "width": _r(op.width), "start": _pt(op.start),
             "end": _pt(op.end)}
        if op.mid is not None:
            d["mid"] = _pt(op.mid)
        if op.chamfer_cut:
            d["chamfer_cut"] = True
        return d
    if isinstance(op, Via):
        d = {"kind": "via", "net": op.net, "at": _pt(op.at), "drill": _r(op.drill), "size": _r(op.size)}
        if op.layers:
            d["layers"] = [l.value for l in op.layers]
        return d
    if isinstance(op, Pour):
        return {"kind": "pour", "net": op.net, "layer": op.layer.value, "points": [_pt(p) for p in op.points],
                "stroke": _r(op.stroke), "fitted": op.fitted}
    if isinstance(op, Zone):
        return {"kind": "zone", "net": op.net, "layer": op.layer.value, "points": [_pt(p) for p in op.points],
                "clearance": _r(op.clearance), "min_thickness": _r(op.min_thickness), "solid_pads": op.solid_pads,
                "npth_clearance": _r(op.npth_clearance)}
    if isinstance(op, Text):
        return {"kind": "text", "text": op.text, "at": _pt(op.at), "face": op.face.value, "size": _r(op.size),
                "thickness": _r(op.thickness), "rotation": _r(op.rotation), "hjust": op.hjust, "vjust": op.vjust,
                "knockout": op.knockout, "mirrored": op.mirrored, "net": op.net, "layer": op.layer}
    raise NoteError("no note form for %s" % type(op).__name__)


def op_from_json(d: dict):
    kind = d["kind"]
    if kind == "track":
        return Track(d["net"], CopperLayer.of(d["layer"]), d["width"], _loc(d["start"]), _loc(d["end"]),
                     d.get("chamfer_cut", False), _loc(d["mid"]) if "mid" in d else None)
    if kind == "via":
        return Via(d["net"], _loc(d["at"]), d["drill"], d["size"], tuple(CopperLayer.of(x) for x in d.get("layers", ())))
    if kind == "pour":
        return Pour(d["net"], CopperLayer.of(d["layer"]), tuple((p[0], p[1]) for p in d["points"]), d["stroke"], d["fitted"])
    if kind == "zone":
        return Zone(d["net"], CopperLayer.of(d["layer"]), tuple((p[0], p[1]) for p in d["points"]), d["clearance"],
                    d["min_thickness"], d["solid_pads"], d["npth_clearance"])
    if kind == "text":
        return Text(d["text"], _loc(d["at"]), Face(d["face"]), d["size"], d["thickness"], d["rotation"], d["hjust"],
                    d["vjust"], d["knockout"], d["mirrored"], d["net"], None, d["layer"])
    raise NoteError("unknown op kind %r" % kind)


def keepout_to_json(k) -> dict:
    return {"name": k.name, "polygon": [_pt(p) for p in k.poly], "layers": None if k.layers is None else [l.value for l in k.layers],
            "excludes": list(k.excludes), "allow": sorted(k.allow), "why": k.why}


def keepout_from_json(d: dict):
    from .layout import PlacedKeepout
    layers = None if d["layers"] is None else tuple(CopperLayer.of(x) for x in d["layers"])
    return PlacedKeepout(d["name"], tuple((p[0], p[1]) for p in d["polygon"]), Location(0.0, 0.0), 0.0, tuple(d["excludes"]),
                         layers, frozenset(d["allow"]), frozenset(), d["why"], None, frozenset(), frozenset())


def base_digest(places) -> str:
    """The default places of the members, as a digest the notes of one cell share."""
    rows = [(inst, _r(p.location.x, 3), _r(p.location.y, 3), _r(p.rotation, 3) % 360.0, p.face.value)
            for inst, p in sorted(places, key=lambda t: t[0])]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]


def document(ident: str, choices: dict, members, ops, keepouts, order: int = 0) -> dict:
    """The note's document. `members` is [(inst, pose in this arrangement, pose in the default)], all in the fragment's frame;
    `order` is where the module run laid the arrangement (the stamping board scans in that order)."""
    return {"v": VERSION, "id": ident, "order": order, "choices": dict(choices), "base": base_digest([(i, d) for i, _, d in members]),
            "members": [{"inst": i, "x": _r(p.location.x, 4), "y": _r(p.location.y, 4), "rotation": _r(p.rotation, 4),
                         "face": p.face.value, "from": pose_json(d)} for i, p, d in members],
            "ops": [op_to_json(o) for o in ops], "keepouts": [keepout_to_json(k) for k in keepouts]}


def encode(doc: dict, chars: int) -> list:
    """The texts that carry `doc`: one, or numbered ones (`placemat arrangement 2/3 <key> <chunk>`) of `chars` characters of
    escaped json each."""
    body = quote(json.dumps(doc, separators=(",", ":"), sort_keys=True), safe=_SAFE)
    if len(body) <= chars:
        return [ARRANGEMENT_PREFIX + body]
    key = hashlib.sha256(body.encode()).hexdigest()[:8]
    chunks = [body[k:k + chars] for k in range(0, len(body), chars)]
    return ["%s%d/%d %s %s" % (ARRANGEMENT_PREFIX, n, len(chunks), key, c) for n, c in enumerate(chunks, 1)]


def _parse(body: str):
    try:
        return json.loads(unquote(body))
    except ValueError:
        return None


def read_notes(texts) -> tuple:
    """(documents, problems) of a cell's arrangement texts, in no order: numbered texts joined, each document parsed and its
    version checked. A problem is `{"reason": "text" | "version", "ids": [...]}` and its arrangement is not among the documents."""
    docs, problems, parts = [], [], {}
    for t in texts:
        if not t.startswith(ARRANGEMENT_PREFIX):
            continue
        rest = t[len(ARRANGEMENT_PREFIX):]
        head = rest.split(" ", 2)
        if len(head) == 3 and "/" in head[0] and head[0].replace("/", "").isdigit():
            n, of = (int(x) for x in head[0].split("/"))
            parts.setdefault((head[1], of), {})[n] = head[2]
        else:
            parts.setdefault(None, []).append(rest)
    whole = [(None, body) for body in parts.pop(None, [])]
    for (key, of), got in parts.items():
        if sorted(got) != list(range(1, of + 1)):
            problems.append({"reason": "text", "ids": []})
            continue
        whole.append((key, "".join(got[n] for n in range(1, of + 1))))
    for _, body in whole:
        d = _parse(body)
        if not isinstance(d, dict) or "id" not in d:
            problems.append({"reason": "text", "ids": []})
        elif d.get("v") != VERSION:
            problems.append({"reason": "version", "ids": [d["id"]]})
        else:
            docs.append(d)
    return docs, problems
```
The `from` field in each member entry is serialised as `pose_json` (a list); `document()` compares equal after a json round trip, so `read_notes` returns the same lists (the tests compare `docs == [doc()]`).

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_note.py -v`
Expected: PASS. (`Text(...)` positional order in `OPS` is `text, at, face, size, thickness, rotation, hjust, vjust, knockout, mirrored, net, side, layer`; keep the test's constructor in step with `copper.py:90-110` if the dataclass moves.)

- [ ] **Step 5: Commit**

```bash
git add src/placemat/arrangement_note.py tests/test_arrangement_note.py
git commit -m "Arrangements: the fragment note codec - ops, keepouts, poses, escaped and split text"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.7: The module's extent and the `arrangement.extent_fixed` notice

**Files:**
- Modify: `src/placemat/arrangement_run.py` (add `extent_from_boxes`, `extent_of`, `extent_findings`)
- Test: `tests/test_arrangement_extent.py`

**Interfaces:**
- Consumes: `Plan` (`plan.steps`, `plan._items`, `plan.occupancy.items`), `board_geometry.members_of`, `Board._options`, `Board._arr_groups`, `Settings.place_extent_notice_mm`, `finding_text` cause `arrangement.extent_fixed` (Task 1.1).
- Produces: `extent_from_boxes(boxes: dict[str, Box]) -> list[dict]` (`[{"item": inst, "sides": ["north", ...], "protrudes_mm": float}]`, most protruding first; a member reaches a side when its edge on that side is the module's outermost; `protrudes_mm` is the most any of its sides stands past the next member's edge on that side, 0.0 for a lone member); `extent_of(plan) -> list[dict]` (boxes: each placed member's claimed shapes, as `report.extent_of` takes them, keyed by `fp.inst`); `extent_findings(board, extent, threshold_mm) -> list[Finding]` (a notice per extent member with no option and not in a group when the module declares any alternative; when it declares none, only those protruding more than `threshold_mm`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_extent.py
from placemat import arrangement_run as run
from placemat.values import Beside, Box, Edge, Location, Near, Part
from tests.arrangement_support import module


def test_the_members_that_set_the_outline_are_listed_with_how_far_they_stand_past_the_next():
    boxes = {"a": Box(0.0, 0.0, 10.0, 4.0), "b": Box(2.0, 1.0, 6.0, 3.0), "c": Box(7.0, -1.8, 9.0, 3.0)}
    assert run.extent_from_boxes(boxes) == [
        {"item": "a", "sides": ["east", "south", "west"], "protrudes_mm": 2.0},      # west: a at 0, the next edge at 2
        {"item": "c", "sides": ["north"], "protrudes_mm": 1.8}]                       # north: c at -1.8, the next edge at 0


def test_a_lone_member_reaches_every_side_and_protrudes_nothing():
    (g,) = run.extent_from_boxes({"a": Box(0.0, 0.0, 2.0, 1.0)})
    assert g["sides"] == ["north", "east", "south", "west"] and g["protrudes_mm"] == 0.0


def test_a_module_that_declares_alternatives_notes_each_extent_member_with_none():
    b = module()
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    extent = [{"item": "c_in", "sides": ["west"], "protrudes_mm": 0.4}, {"item": "r_pull", "sides": ["east"], "protrudes_mm": 0.1}]
    found = run.extent_findings(b, extent, 2.0)
    assert [f.facts["item"] for f in found] == ["r_pull"] and found[0].severity == "notice"
    assert found[0].facts == {"item": "r_pull", "sides": ["east"], "protrudes_mm": 0.1, "alternatives": True}


def test_a_module_that_declares_none_notes_only_what_protrudes_past_the_setting():
    b = module()
    extent = [{"item": "c_in", "sides": ["west"], "protrudes_mm": 2.5}, {"item": "r_pull", "sides": ["east"], "protrudes_mm": 1.9}]
    found = run.extent_findings(b, extent, 2.0)
    assert [f.facts["item"] for f in found] == ["c_in"] and found[0].facts["alternatives"] is False


def test_the_extent_of_a_resolved_plan_names_instances():
    plan = module().resolve()
    got = run.extent_of(plan)
    assert {g["item"] for g in got} <= {"u1", "c_in", "r_pull"} and got and all(g["sides"] for g in got)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_extent.py -v`
Expected: FAIL (`AttributeError: module 'placemat.arrangement_run' has no attribute 'extent_from_boxes'`).

- [ ] **Step 3: Implement** (append to `arrangement_run.py`)

```python
from .findings import Finding, FindingCause as C
from .values import Box, Edge

_SIDE_EDGE = (("north", lambda b: b.top, min), ("east", lambda b: b.right, max),
              ("south", lambda b: b.bottom, max), ("west", lambda b: b.left, min))
_TOL = 1e-6


def extent_from_boxes(boxes: dict) -> list:
    """The members whose box reaches the outline round all of them on a side, with how far each stands past the next member's
    edge on that side (the most over its sides). Most protruding first, then by name."""
    out: dict = {}
    for side, edge, pick in _SIDE_EDGE:
        values = sorted(((edge(b), n) for n, b in boxes.items()), key=lambda t: (t[0] if pick is min else -t[0], t[1]))
        if not values:
            continue
        best = values[0][0]
        others = [w for w, _ in values if abs(w - best) > _TOL]
        gap = abs(best - others[0]) if others else 0.0
        for v, n in values:
            if abs(v - best) > _TOL:
                break
            sides_of, was = out.get(n, ([], 0.0))
            out[n] = (sides_of + [side], max(was, gap))
    order = [s for s, _, _ in _SIDE_EDGE]
    rows = [{"item": n, "sides": sorted(s, key=order.index), "protrudes_mm": round(g, 6)} for n, (s, g) in out.items()]
    return sorted(rows, key=lambda r: (-r["protrudes_mm"], r["item"]))


def extent_of(plan) -> list:
    """`extent_from_boxes` of a resolved plan's placed members, as the placer claims them (`report.extent_of`)."""
    from .board_geometry import members_of
    boxes = {}
    for step in plan.steps:
        if step.placement is None or step.kind not in ("part", "cell"):
            continue
        item = plan._items.get(step.item)
        for fp in members_of(item) if item is not None else ():
            g = plan.occupancy.items.get(fp.ref)
            claimed = [s.box for s in g.shapes if s.kind != "npth"] if g is not None else []
            if claimed:
                boxes[fp.inst] = Box.union(claimed)
    return extent_from_boxes(boxes)


def extent_findings(board, extent: list, threshold_mm: float) -> list:
    """`arrangement.extent_fixed` for each extent member with no alternative: on a module that declares any, every one; on one
    that declares none, those standing past the next member by more than `threshold_mm` (`place.extent_notice_mm`)."""
    declares = bool(board._options or board._arr_groups)
    moved = set(board._options) | {o.item for g in board._arr_groups for o in g.options}
    out = []
    for row in extent:
        if row["item"] in moved or (not declares and row["protrudes_mm"] <= threshold_mm):
            continue
        out.append(Finding(C.ARRANGEMENT_EXTENT_FIXED, dict(row, alternatives=declares), "notice"))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_extent.py -v`
Expected: PASS; if the first test's exact list disagrees, print `got` and replace the `or` with the real list.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/arrangement_run.py tests/test_arrangement_extent.py
git commit -m "Arrangements: the members that set a module's extent and the extent_fixed notice"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.8: Refusals - what keeps an arrangement from being offered

**Files:**
- Modify: `src/placemat/arrangement_run.py` (add the refusal builders and `Proof`)
- Test: `tests/test_arrangement_proof.py`

**Interfaces:**
- Consumes: `Plan`, `kicad.drc.DrcReport` (`.real`, `.unconnected`), `checks.Verdict` (`.ok`, `.accepted`, `.check`, `.subject`), `findings.Finding` severities.
- Produces: `@dataclass Proof(offered: bool, refused: list, metrics: dict)`; `plan_refusals(plan, default_plan) -> list` (`unplaced` for each declared item with no placement, `finding` for each critical finding, `nested_cell` for each cell or nested-cell member whose pose differs from the default's); `drc_refusals(report, default_unconnected: int) -> list` (`drc` per non-empty `real` bucket; one `unconnected` when `report.unconnected > default_unconnected`); `verdict_refusals(verdicts) -> list` (`verdict` per `ok is False` and not accepted).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_proof.py
import types

from placemat import arrangement_run as run
from placemat.checks import Verdict
from placemat.values import Beside, Edge, Part
from tests.arrangement_support import module


def report(real=None, unconnected=0):
    return types.SimpleNamespace(real=real or {}, unconnected=unconnected)


def test_a_clean_plan_has_no_refusal_and_a_critical_finding_or_an_unplaced_item_has_one():
    b = module()
    plan = b.resolve()
    assert run.plan_refusals(plan, plan) == []
    from placemat.findings import Finding, FindingCause as C
    plan.findings.append(Finding(C.FIXED_PART, {"item": "c_in", "freedom": "fixed", "why": {"code": "edge", "what": "body", "box": [0, 0, 1, 1], "verdict": "outside", "margin_mm": 0.0}}))
    got = run.plan_refusals(plan, plan)
    assert {"form": "finding", "cause": "fixed.part", "item": "c_in"} in got
    plan.steps[1].placement = None
    assert {"form": "unplaced", "item": plan.steps[1].item} in run.plan_refusals(plan, plan)


def test_a_cell_standing_elsewhere_than_in_the_default_is_refused_by_name():
    a, b = module().resolve(), module().resolve()
    p = b.steps[0].placement
    b.steps[0].placement = p.moved(1.0, 0.0)
    b.steps[0].kind = "cell"
    a.steps[0].kind = "cell"
    assert {"form": "nested_cell", "item": a.steps[0].item} in run.plan_refusals(b, a)


def test_drc_buckets_and_unconnected_are_refusals_only_beyond_the_default():
    assert run.drc_refusals(report({"clearance": 2, "track_width": 1}, 3), 3) == [
        {"form": "drc", "bucket": "clearance", "count": 2}, {"form": "drc", "bucket": "track_width", "count": 1}]
    assert run.drc_refusals(report({}, 4), 3) == [{"form": "unconnected", "count": 4, "default": 3}]
    assert run.drc_refusals(report({}, 3), 3) == []


def test_a_failed_verdict_is_a_refusal_unless_a_script_accepted_it():
    failed = Verdict("hot-loop", "c_in", 9.0, "mm2", 5.0, False)
    accepted = Verdict("hot-loop", "u1", 9.0, "mm2", 5.0, False, accepted="accepted (<= 10): why")
    unjudged = Verdict("heat", "u1", 1.0, "C", None, None)
    assert run.verdict_refusals([failed, accepted, unjudged]) == [{"form": "verdict", "check": "hot-loop", "item": "c_in"}]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_proof.py -v`
Expected: FAIL (`AttributeError: ... plan_refusals`).

- [ ] **Step 3: Implement** (append to `arrangement_run.py`)

```python
@dataclass
class Proof:
    offered: bool
    refused: list               # records (finding_text.refusal_record_text reads them)
    metrics: dict               # {"drc": int | None, "findings": {severity: n}, "measures": {...}}


def plan_refusals(plan, default_plan) -> list:
    """What the resolve itself says against an arrangement: an item with no place, a critical finding, and a cell standing
    elsewhere than in the default (a module's nested cells are placed once, by the default: an arrangement that needs one moved is
    not offered)."""
    from .board_geometry import members_of
    out = []
    for s in plan.steps:
        if s.kind in ("part", "cell", "block") and s.placement is None:
            out.append({"form": "unplaced", "item": s.item})
    for f in plan.findings:
        if f.severity == "critical":
            out.append({"form": "finding", "cause": f.cause.value, "item": finding_subject(f)})
    was = {s.item: s.placement for s in default_plan.steps if s.placement is not None}
    for s in plan.steps:
        if s.kind == "cell" and s.placement is not None and was.get(s.item) not in (None, s.placement):
            out.append({"form": "nested_cell", "item": s.item})
    return out


def finding_subject(f) -> str:
    from . import finding_text
    return finding_text.subject(f.cause, f.facts) or ""


def drc_refusals(report, default_unconnected: int) -> list:
    out = [{"form": "drc", "bucket": b, "count": n} for b, n in sorted(report.real.items())]
    if report.unconnected > default_unconnected:
        out.append({"form": "unconnected", "count": report.unconnected, "default": default_unconnected})
    return out


def verdict_refusals(verdicts) -> list:
    return [{"form": "verdict", "check": v.check, "item": v.subject} for v in verdicts if v.ok is False and not v.accepted]
```
(`finding_text.subject(cause, facts)` is the helper `layout.py:6760` already uses; it returns the item key a finding is about.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_proof.py -v`
Expected: PASS. If the `FIXED_PART` facts in the first test fail `finding_text` validation, copy the facts of the `FIXED_PART` sample in `tests/test_finding_text.py`.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/arrangement_run.py tests/test_arrangement_proof.py
git commit -m "Arrangements: the refusals that keep an arrangement from being offered"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.9: The module run - proof on a scratch board, the record, the fragment's notes, resume

**Files:**
- Create: `src/placemat/kicad/arrange.py` (first part: `write_notes`)
- Modify: `src/placemat/arrangement_run.py` (add `Resolved`, `read_previous`, `read_died`, `resolve_others`, `scratch_board`, `prove`, `members_doc`, `finish`, `Outcome`)
- Modify: `src/placemat/runner.py` - the import line `from . import checks, settings, stop` (`:17`) gains `arrangement_run`; `scripted_board` (`:340-372`, call `finish_declarations()` inside the try after `run_script`); `_run`: `previous_arr`/`died_arr` reads (`:388-455`), `begin` before the resolve (`:482`), `resolve_others` before `timecap.placement_done()` (`:513`), the extent notices after `fab_min_findings` (`:515`), `finish` after the checks stage (`:690`)
- Modify: `src/placemat/report.py:16-37` (`RunRecord.arrangements`, `save` omits it when empty)
- Modify: `tests/real_modules.py:51-72` (`run` takes `reuse: bool = False` and `fresh_folder: bool = True`; with `fresh_folder=False` it runs the script of the board an earlier call staged under `tmp_path`, so a second run sees the first run's folders)
- Modify: `src/placemat/kicad/write.py:974-1001` (`_is_note` and `_drop_stamped_notes` know the prefix); `:1004-1018` (`strip_stamped_notes`)
- Test: `tests/test_arrangement_run.py` (KiCad; slow, add to `tests/slow_tests.txt` after the first full run)

**Interfaces:**
- Consumes: Tasks 1.5-1.8; `runner.copy_board`, `kicad.write.apply_plan/finish_board`, `kicad.drc.run_drc`, `checks.judge/run_checks/kwargs_from`, `score.plan_measures`, `reuse.PartialLog/read/read_partial/better_of/write`, `arrangement_note.document/encode`, `Settings.place_arrangement_note_chars`.
- Produces:
  - `kicad.arrange.write_notes(pcb_path, texts: list[str]) -> list[str]` (replaces the fragment's arrangement texts, below the rule notes; saved only when `texts` is non-empty or the board had some)
  - `arrangement_run.read_previous(last_run_dir) -> dict[id, reuse record]`, `read_died(final_dir) -> dict[id, record]`
  - `Resolved(spec, plan | None, duplicate_of: str = "", seconds: float = 0.0)`
  - `resolve_others(prepared, default_plan, run_dir, previous, died, lock, routes, say) -> list[Resolved]` (each non-default spec in order; duplicates dropped with the plan kept for none; each arrangement's `reuse.partial.jsonl` and `reuse.json` under `run_dir/arrangements/<id>/`)
  - `scratch_board(generated_pcb, arr_dir) -> Path` (`arr_dir/layout.kicad_pcb` with `layout.kicad_pro` and `layout.kicad_dru` beside it, from the cached generation)
  - `prove(prepared, resolved, default_plan, *, generated, cfg, fab, arr_dir, default_unconnected, drc=True) -> Proof`
  - `finish(prepared, default_plan, resolved, *, src, cfg, fab, run_dir, default_report, board, drc) -> Outcome(record: list, findings: list, texts: list)`; `record` entries `{"id", "choices", "offered", "metrics", "dir", "extent", ["refused"], ["duplicate_of"]}`
  - `RunRecord.arrangements: list` (default `[]`, left out of `run.json` when empty)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_run.py
"""The module run with alternatives, on a real module of the fixtures (KiCad): each arrangement resolved, proven by DRC and the
checks on its own scratch board, recorded in run.json and written into the fragment as notes."""
import json
import shutil
from pathlib import Path

import pytest

from tests.conftest import needs_kicad
from tests import real_modules

pytestmark = needs_kicad

ALTERNATIVES = '''
board.alternative(Part("c_vcc"), "turned", rotation=LYING)
board.alternative(Part("r_rt"), "turned", rotation=LYING)
'''


def with_alternatives(text: str) -> str:
    marker = "frame_planes(FILLET, supply=None)"
    return text.replace(marker, ALTERNATIVES + marker, 1)


def test_a_module_with_alternatives_records_each_arrangement_and_writes_the_offered_ones_as_notes(tmp_path):
    result, drc, pcb = real_modules.run(tmp_path, "usb5v", edit=with_alternatives)
    rec = json.loads((result.run_dir / "run.json").read_text())
    ids = [a["id"] for a in rec["arrangements"]]
    assert ids == ["default", "r_rt.turned", "c_vcc.turned", "c_vcc.turned+r_rt.turned"]
    assert rec["arrangements"][0]["offered"] is True and rec["arrangements"][0]["dir"] == "arrangements/default"
    for a in rec["arrangements"][1:]:
        d = result.run_dir / a["dir"]
        assert (d / "layout.kicad_pcb").exists() and (d / "reuse.json").exists()
        if a["offered"]:
            arr_drc = json.loads((d / "drc.json").read_text())
            assert not [v for v in arr_drc.get("violations", []) if v.get("severity") == "error"] or a["refused"]
        else:
            assert a["refused"] and all("form" in r for r in a["refused"])
    offered = [a["id"] for a in rec["arrangements"][1:] if a["offered"]]
    assert offered, "adjust ALTERNATIVES to two members whose other turn passes this module's own DRC"
    import pcbnew
    from placemat.arrangement_note import ARRANGEMENT_PREFIX, read_notes
    board = pcbnew.LoadBoard(str(pcb))
    texts = [d.GetText() for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(ARRANGEMENT_PREFIX)]
    docs, problems = read_notes(texts)
    assert problems == [] and sorted(d["id"] for d in docs) == sorted(offered)
    print("note characters:", sorted(len(t) for t in texts))             # the size Phase 1 measures
    assert max(len(t) for t in texts) < 20000


def test_the_written_fragment_is_the_defaults_and_equal_to_a_run_with_no_alternatives(tmp_path):
    plain_result, _, plain_pcb = real_modules.run(tmp_path / "a", "usb5v")
    alt_result, _, alt_pcb = real_modules.run(tmp_path / "b", "usb5v", edit=with_alternatives)
    import pcbnew
    from placemat.arrangement_note import ARRANGEMENT_PREFIX
    def live(path):
        board = pcbnew.LoadBoard(str(path))
        return sorted((f.GetReference(), f.GetPosition().x, f.GetPosition().y, f.GetOrientationDegrees()) for f in board.GetFootprints()), \
            sorted((t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y) for t in board.GetTracks())
    assert live(plain_pcb) == live(alt_pcb)


def test_a_module_with_no_alternatives_writes_no_arrangement_record_or_directory(tmp_path):
    result, _, _ = real_modules.run(tmp_path, "usb5v")
    rec = json.loads((result.run_dir / "run.json").read_text())
    assert "arrangements" not in rec and not (result.run_dir / "arrangements").exists()


def test_a_refused_alternative_is_recorded_with_its_refusals_and_raises_arrangement_refused(tmp_path):
    bad = '\nboard.alternative(Part("c_vcc"), "wild", at=Beside(Part("buck"), Edge.EAST, align=pin(SW_PIN)))\n'
    result, _, pcb = real_modules.run(tmp_path, "usb5v", edit=lambda t: t.replace("frame_planes(FILLET, supply=None)", bad + "frame_planes(FILLET, supply=None)", 1))
    rec = json.loads((result.run_dir / "run.json").read_text())
    wild = next(a for a in rec["arrangements"] if a["id"] == "c_vcc.wild")
    assert wild["offered"] is False and wild["refused"]
    assert any(f["cause"] == "arrangement.refused" and f["facts"]["id"] == "c_vcc.wild" for f in rec["finding_details"])
    assert rec["arrangements"][0]["offered"] is True                    # the default is written either way


def test_a_stopped_run_resumes_each_arrangement_from_its_own_record(tmp_path, monkeypatch):
    from placemat import arrangement_run, stop
    real = arrangement_run.resolve_spec

    def stop_on_the_last(prepared, spec, **kw):
        if spec.id == prepared.specs[-1].id:
            raise stop.Stopped(15)                      # the run is stopped while it lays out the last arrangement
        return real(prepared, spec, **kw)
    monkeypatch.setattr(arrangement_run, "resolve_spec", stop_on_the_last)
    with pytest.raises(stop.Stopped):
        real_modules.run(tmp_path, "usb5v", edit=with_alternatives, reuse=True)
    monkeypatch.setattr(arrangement_run, "resolve_spec", real)
    runs = tmp_path / "board" / "modules" / "usb5v" / ".placemat" / "runs"
    (stopped,) = [p for p in runs.iterdir() if (p / "arrangements").is_dir()]
    assert (stopped / "arrangements" / "r_rt.turned" / "reuse.json").exists()
    again, _, _ = real_modules.run(tmp_path, "usb5v", edit=with_alternatives, reuse=True, fresh_folder=False)
    done = json.loads((again.run_dir / "arrangements" / "r_rt.turned" / "reuse.json").read_text())
    assert done["reused"] == len(done["steps"]) > 0          # the arrangement the stopped run finished is replayed, not laid again


Also add a pure-ish test for `write_notes` in `tests/test_arrangement_note.py`? It needs pcbnew: add to `tests/test_arrangement_run.py`:

```python
def test_write_notes_replaces_the_fragments_texts_and_leaves_a_board_with_none_alone(tmp_path):
    import pcbnew
    from placemat.kicad.arrange import write_notes
    from placemat.arrangement_note import ARRANGEMENT_PREFIX
    pcb = tmp_path / "layout.kicad_pcb"
    board = pcbnew.CreateEmptyBoard()
    board.Save(str(pcb))
    before = pcb.read_bytes()
    assert write_notes(pcb, []) == [] and pcb.read_bytes() == before
    write_notes(pcb, [ARRANGEMENT_PREFIX + "a", ARRANGEMENT_PREFIX + "b"])
    write_notes(pcb, [ARRANGEMENT_PREFIX + "c"])
    texts = [d.GetText() for d in pcbnew.LoadBoard(str(pcb)).GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    assert texts == [ARRANGEMENT_PREFIX + "c"]
```

- [ ] **Step 2: Run to verify failure**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_arrangement_run.py -x -q`
Expected: FAIL (`ImportError: cannot import name 'write_notes'`, then the run has no `arrangements`).

- [ ] **Step 3: Implement**

`tests/real_modules.py`, `run` (`:51`): signature `run(tmp_path, module, keep_out=None, overrides=None, keep_going=False, script=None, edit=None, reuse=False, fresh_folder=True)`; its first line becomes

```python
    if fresh_folder:
        script = stage(tmp_path, module, keep_out, script, edit)
    else:                                       # the board an earlier call staged: its script, its generation cache and its runs
        folder, name = OTHER[module] if module in OTHER else (FIXTURES, MODULES[module])
        script = tmp_path / "board" / "modules" / module / (name + "_layout.py")
```
and the call `runner.run(script, render=False, quiet=True, reuse=reuse, ...)` (it passed `reuse=False`).

`kicad/arrange.py`:

```python
"""pcbnew side of arrangements: the fragment's notes (`write_notes`) and, in Phase 2, the stamped cell's arrange step."""
from __future__ import annotations

from .quiet import import_pcbnew, quiet_stderr

pcbnew = import_pcbnew()

from ..arrangement_note import ARRANGEMENT_PREFIX
from ..rules import RULE_PREFIX
from .read import FACES_PREFIX
from .write import _delete_note, _unique_uuid, nm, save, seed_uuids

_NOTES = (FACES_PREFIX, RULE_PREFIX, ARRANGEMENT_PREFIX)


def write_notes(pcb_path, texts) -> list:
    """Put a fragment's arrangement notes into it (replacing any it has): User.Comments texts below everything the fragment draws and
    its other notes, which pcb layout stamps with the cell. A board with none and none to write is not touched. Returns the texts."""
    texts = list(texts)
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb_path))
        had = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(ARRANGEMENT_PREFIX)]
        if not texts and not had:
            return []
        for d in had:
            _delete_note(board, d)
        boxes = [fp.GetBoundingBox(True, True) for fp in board.GetFootprints()]
        boxes += [d.GetBoundingBox() for d in board.GetDrawings()
                  if not (isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(_NOTES))]
        boxes += [t.GetBoundingBox() for t in board.GetTracks()] + [z.GetBoundingBox() for z in board.Zones()]
        left = min(b.GetLeft() for b in boxes) if boxes else 0
        bottom = max(b.GetBottom() for b in boxes) if boxes else 0
        for i, text in enumerate(texts):
            t = pcbnew.PCB_TEXT(board)
            t.SetText(text)
            t.SetLayer(pcbnew.Cmts_User)
            t.SetTextSize(pcbnew.VECTOR2I(nm(0.5), nm(0.5)))
            t.SetTextThickness(nm(0.1))
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
            t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_TOP)
            t.SetPosition(pcbnew.VECTOR2I(left, bottom + nm(4.0 + 0.7 * i)))
            _unique_uuid(board, t)
            board.Add(t)
        seed_uuids()
        save(board, str(pcb_path))
    return texts
```
`write.py`: import `from ..arrangement_note import ARRANGEMENT_PREFIX`; `_is_note` (`:974`) startswith tuple gains `ARRANGEMENT_PREFIX`; `write_rule_notes` and `write_faces` box filters (`:1152`, `:1187`) gain it too.

`report.py` `RunRecord`: `arrangements: list = field(default_factory=list)   # the module run's arrangements: id, choices, offered, metrics, dir, extent, refusals (arrangement_run.finish)`; `save()`:

```python
        data = asdict(self)
        if not data["arrangements"]:
            del data["arrangements"]            # a module with no alternatives writes the record it always did
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
```
`runner.py`: in `scripted_board`'s try (`:362`) after `run_script(script, board)` add `board.finish_declarations()`. In `_run`: `previous_arr = {}` beside `previous_reuse, previous_id = None, None` (`:395`); inside the `try:` that reads `last` (`:398-402`) after `previous_id = last.run_id`: `previous_arr = arrangement_run.read_previous(Path(last.paths.get("run_dir", "")))`; after `died = ...` (`:446`): `died_arr = arrangement_run.read_died(final_dir) if reuse else {}`; just before `plan = board.resolve(` (`:482`): `declared = arrangement_run.begin(board)`; after the `except CriticalUnplaced` handler and before `timecap.placement_done()` (`:513`):

```python
        others = arrangement_run.resolve_others(declared, plan, run_dir, previous_arr, died_arr, lock_entries,
                                                routes_mod.read(routes_mod.path_for(script)), say)
```
after `plan.findings += fab_min_findings(...)` (`:515`): `plan.findings += arrangement_run.extent_findings(board, arrangement_run.extent_of(plan), cfg.place_extent_notice_mm)`; after `rec.timing_s["checks"] = ...` (`:690`):

```python
        if len(declared.specs) > 1 or board.arrangement_limit() is not None:
            t0 = time.time()
            stage = "arrangements"
            outcome = arrangement_run.finish(declared, plan, others, src=src, cfg=cfg, fab=fab, run_dir=run_dir,
                                             default_report=report if drc else None, board=board, drc=drc)
            rec.arrangements = outcome.record
            plan.findings.extend(outcome.findings)
            if outcome.texts:
                from .kicad.arrange import write_notes
                write_notes(src.pcb, outcome.texts)
                copy_board(src.pcb, run_dir)
            for line in arrangement_run.lines(outcome.record):
                say("arrangements", line)
            rec.timing_s["arrangements"] = round(time.time() - t0, 1)
```
(`report` exists only when `drc`; the expression above guards it.)

`arrangement_run.py` additions:

```python
import json
import shutil
import time
from pathlib import Path

from . import arrangement_note as note, checks, reuse as reuse_mod, score as score_mod
from .copper import Text
from .findings import Finding, FindingCause as C


@dataclass
class Resolved:
    spec: Spec
    plan: object | None
    duplicate_of: str = ""
    seconds: float = 0.0


@dataclass
class Outcome:
    record: list
    findings: list
    texts: list


def _dir(run_dir, ident) -> Path:
    return Path(run_dir) / "arrangements" / ident


def read_previous(last_run_dir) -> dict:
    out = {}
    for p in sorted((Path(last_run_dir) / "arrangements").glob("*/reuse.json")):
        try:
            out[p.parent.name] = reuse_mod.read(p)
        except (ValueError, OSError):
            pass
    return out


def read_died(final_dir) -> dict:
    """What a stopped or crashed run of these very inputs left of each arrangement (read before its folder is replaced): the record
    it finished, or the steps of its partial log, whichever replays more."""
    out = {}
    for d in sorted(p for p in (Path(final_dir) / "arrangements").glob("*") if p.is_dir()):
        try:
            done = reuse_mod.read(d / "reuse.json") if (d / "reuse.json").exists() else None
        except (ValueError, OSError):
            done = None
        got = reuse_mod.better_of(done, reuse_mod.read_partial(d / "reuse.partial.jsonl"))
        if got is not None:
            out[d.name] = got
    return out


def resolve_others(prepared, default_plan, run_dir, previous, died, lock, routes, say) -> list:
    """Each arrangement after the default, resolved from the snapshot, in declared order. One that lays out exactly as an earlier one
    is dropped (its plan is not kept) and named by `duplicate_of`. Each keeps its steps' record in its own folder, so a stopped run
    resumes it without laying finished arrangements again."""
    out, seen = [], {signature(default_plan): "default"}
    for spec in prepared.specs[1:]:
        d = _dir(run_dir, spec.id)
        d.mkdir(parents=True, exist_ok=True)
        before = previous.get(spec.id)
        if spec.id in died and reuse_mod.better_of(before, died[spec.id]) is died[spec.id]:
            before = died[spec.id]
        partial = reuse_mod.PartialLog(d / "reuse.partial.jsonl")
        t0 = time.monotonic()
        say("arrangement", "resolving %s" % spec.id)
        plan = resolve_spec(prepared, spec, reuse=before, lock=lock, routes=routes, partial=partial)
        plan.reuse["parts"] = default_plan.reuse.get("parts", {})
        reuse_mod.write(d / "reuse.json", plan.reuse)
        partial.remove()
        sig = signature(plan)
        if sig in seen:
            out.append(Resolved(spec, None, seen[sig], time.monotonic() - t0))
            continue
        seen[sig] = spec.id
        out.append(Resolved(spec, plan, "", time.monotonic() - t0))
    if out:                                      # the board as the script declared it: what the rest of the run reads (measures, sites)
        prepared.board._restore(prepared.saved)
        prepared.board.lay_arrangement(DEFAULT_SPEC)
    return out
```
```python
def scratch_board(generated_pcb, arr_dir) -> Path:
    """arr_dir/layout.kicad_pcb with its project and rules beside it, from the board `pcb layout` generated (the cached generation):
    the plan is written on it without touching the fragment the run writes."""
    generated_pcb, arr_dir = Path(generated_pcb), Path(arr_dir)
    arr_dir.mkdir(parents=True, exist_ok=True)
    for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru"):
        src = generated_pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, arr_dir / ("layout" + ext))
    return arr_dir / "layout.kicad_pcb"


def prove(prepared, resolved, default_plan, *, generated, cfg, fab, arr_dir, default_unconnected: int, drc: bool = True) -> Proof:
    """The judgement the default gets, on this arrangement's own board: its resolve places every member with no critical finding;
    the plan written to a scratch board passes KiCad's DRC (the `real` buckets empty, no more unconnected than the default); the
    design checks run on it (no failed verdict, `board.accept` applied). Warnings, notices and measures are recorded, not refused."""
    from .kicad.drc import run_drc
    from .kicad.read import read_board
    from .kicad.write import apply_plan, finish_board
    plan, board = resolved.plan, prepared.board
    refused = plan_refusals(plan, default_plan)
    metrics = {"drc": None, "findings": plan.findings.by_severity(), "measures": score_mod.plan_measures(board, plan)}
    if refused:
        return Proof(False, refused, metrics)
    pcb = scratch_board(generated, arr_dir)
    apply_plan(pcb, plan)
    finish_board(pcb, fab, refs_to_fab=getattr(board, "refs_on_fab", True))
    if drc:
        allow = {"keepout %s" % k.name: (set(k.owners), set(k.allow)) for k in plan.keepouts.values()}
        report = run_drc(pcb, Path(arr_dir) / "drc.json", allow=allow, frame_only=not plan.draw_outline)
        refused += drc_refusals(report, default_unconnected)
        metrics["drc"] = sum(report.real.values())
        metrics["measures"]["drc"] = metrics["drc"]
    verdicts, _ = checks.judge(checks.run_checks(read_board(pcb), **checks.kwargs_from(cfg)), plan.acceptances)
    refused += verdict_refusals(verdicts)
    return Proof(not refused, refused, metrics)


def members_doc(prepared, plan, default_plan, spec, texts_chars: int) -> list:
    """The note of an offered arrangement (arrangement_note.encode of its document): every loose member's place in the fragment's frame,
    the copper this arrangement planned (the faces text is the default's), and the rule areas it declares."""
    geometry = prepared.board.geometry
    members = []
    for fp in geometry.footprints:
        if fp.cell is None and fp.ref in plan.occupancy.items and fp.ref in default_plan.occupancy.items:
            members.append((fp.inst, plan.occupancy.items[fp.ref].reference, default_plan.occupancy.items[fp.ref].reference))
    ops = [op for op in plan.copper if not (isinstance(op, Text) and op.layer == "User.Comments")]
    doc = note.document(spec.id, spec.choices, members, ops, list(plan.keepouts.values()),
                        order=[s.id for s in prepared.specs].index(spec.id))
    return note.encode(doc, texts_chars)


def finish(prepared, default_plan, resolved, *, src, cfg, fab, run_dir, default_report, board, drc: bool = True) -> Outcome:
    """After the default's own DRC and checks: prove each other arrangement, build the record, the findings, and the texts that carry
    the offered ones. The default is copied into its own folder beside the others'."""
    from .runner import cached_generation
    generated = cached_generation(src) / src.pcb.name
    default_unconnected = default_report.unconnected if default_report is not None else 0
    record = [{"id": "default", "choices": {}, "offered": True, "dir": "arrangements/default",
               "metrics": {"drc": sum(default_report.real.values()) if default_report is not None else None,
                           "findings": default_plan.findings.by_severity(), "measures": score_mod.plan_measures(board, default_plan)},
               "extent": extent_of(default_plan)}]
    findings, texts = [], []
    for r in resolved:
        spec = r.spec
        entry = {"id": spec.id, "choices": spec.choices, "dir": "arrangements/" + spec.id}
        if r.plan is None:
            entry.update(offered=False, duplicate_of=r.duplicate_of, metrics=None)
            findings.append(Finding(C.ARRANGEMENT_DUPLICATE, {"id": spec.id, "same_as": r.duplicate_of}, "notice"))
            record.append(entry)
            continue
        proof = prove(prepared, r, default_plan, generated=generated, cfg=cfg, fab=fab, arr_dir=_dir(run_dir, spec.id),
                      default_unconnected=default_unconnected, drc=drc)
        entry.update(offered=proof.offered, metrics=proof.metrics, extent=extent_of(r.plan))
        if proof.offered:
            texts += members_doc(prepared, r.plan, default_plan, spec, cfg.place_arrangement_note_chars)
        else:
            entry["refused"] = proof.refused
            findings.append(Finding(C.ARRANGEMENT_REFUSED, {"id": spec.id, "refused": proof.refused}, "warning"))
        record.append(entry)
    d = _dir(run_dir, "default")
    d.mkdir(parents=True, exist_ok=True)
    for name in ("layout.kicad_pcb", "drc.json", "reuse.json"):
        if (Path(run_dir) / name).exists():
            shutil.copy(Path(run_dir) / name, d / name)
    return Outcome(record, findings, texts)


def lines(record: list) -> list:
    """What the console says of the arrangements (the one place a sentence is made of the record)."""
    from . import finding_text
    out = []
    for a in record:
        if a.get("duplicate_of"):
            out.append("%s: the same as %s, dropped" % (a["id"], a["duplicate_of"]))
        elif a["offered"]:
            out.append("%s: offered%s" % (a["id"], "" if a["id"] != "default" else " (written)"))
        else:
            out.append("%s: not offered: %s" % (a["id"], "; ".join(finding_text.refusal_record_text(r) for r in a["refused"])))
    return out
```
Keep `prove`'s `refs_to_fab` consistent with the runner (`getattr(board, "refs_on_fab", True)`).

- [ ] **Step 4: Run to verify pass**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_arrangement_run.py -x -q -s`
Expected: PASS and the note sizes printed. If no non-default arrangement proves, choose two other members of the module (a `Beside` part whose other turn leaves its pads on the same nets) until one does; the assertion message says so. Record the printed sizes in the spec's "Build notes" section (Step 5). Then `rm -rf` nothing: the test works in `tmp_path`.

Also run the existing run tests unchanged: `.venv/bin/python -m pytest tests/test_runner*.py tests/test_run_record*.py tests/test_keep_out_modules.py -q`.

- [ ] **Step 5: Measure, record and commit**

Append to the spec (`docs/superpowers/specs/2026-10-04-module-member-variants-design.md`) a section `## Build notes` with a line: `Phase 1: a fixture module with 2 declared options per item (4 arrangements) wrote notes of N, N and N characters; no split was needed at place.arrangement_note_chars = 4000.` (the measured numbers; if a note was over 4000 say it was split and into how many texts).

```bash
git add src/placemat/arrangement_run.py src/placemat/kicad/arrange.py src/placemat/runner.py src/placemat/report.py src/placemat/kicad/write.py tests/test_arrangement_run.py docs/superpowers/specs/2026-10-04-module-member-variants-design.md
git commit -m "Arrangements: the module run proves each arrangement and writes the offered ones into the fragment"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.10: Skill and api.md for declaring, proving and reading (Phase 1 half)

**Files:**
- Modify: `skills/placemat/SKILL.md` - new subsection "Arrangements" in "Shaping modules for the board" (`:657-687`), and the two bullets that name turning a bypass or moving a part (`:675-679`); `skills/placemat/references/api.md` - "Arrangements" subsection under "Placement" (after the Modules paragraph at `:980-1001`), the run record's `arrangements` field in "Report form and the files placemat writes" (`:4077-4120`), the findings table rows already added in Task 1.1
- Modify: `skills/placemat/references/migration.md` - entry under "## Unreleased" (`:9`)
- Test: `tests/test_describe.py` (existing docs checks), a new check in `tests/test_arrangement_declarations.py` that the skill names the forms

**Interfaces:** none (documentation). The skill states rules, names no project's parts and points to `api.md` for the forms.

- [ ] **Step 1: Write the failing test** (append to `tests/test_arrangement_declarations.py`)

```python
from pathlib import Path

SKILL = Path("skills/placemat/SKILL.md").read_text()
API = Path("skills/placemat/references/api.md").read_text()


def test_the_skill_and_api_document_the_forms_and_the_report():
    for word in ("board.alternative", "board.arrangement", "only=", "arrangement.refused", "arrangement.limit",
                 "arrangement.extent_fixed", "place.arrangement_options_max", "place.arrangements_max"):
        assert word in API, word
    assert "add it as an alternative first" in SKILL and "extent" in SKILL and "arrangement.refused" in SKILL
    assert all(ord(c) < 128 for c in SKILL + API), "ASCII only"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py::test_the_skill_and_api_document_the_forms_and_the_report -v`
Expected: FAIL (`AssertionError: board.alternative`). If the existing files already carry non-ASCII characters the last assertion fails for a reason outside this change: restrict it to the added text (`added = ...`) by checking the new subsections only.

- [ ] **Step 3: Write the docs**

`SKILL.md`, "Shaping modules for the board": change the two bullets to `Change the module's layout script by intent, in small steps: for a member whose side or turn is a free choice (a bypass capacitor on either side of its pin, a part on the other side of its IC, a part on the other face, a pair that could be mirrored), add it as an alternative first and let the board's search choose (see "Arrangements"); edit the module's default layout only when no arrangement that keeps the module's intent fits. Swap a row's order, fit the module's frame (board.rect(fit=True)) ...` and add the subsection:

```
### Arrangements

A module often has two layouts that serve its own reason equally well. Declare the other one as an alternative; the module run
proves it on the module's own terms and the board's search chooses. `api.md`, "Arrangements", has the forms, the ids, the limits
and the record.

- **Members that set the extent first.** The members that set a module's outline (a bulk capacitor, a connector, an inductor or a
  tall part standing proud on one side) are the ones that make a module hard to place in some orientations, so they are the first
  to consider: a turn, the other side of their partner, the other face, or a group that tucks them in. The run lists them
  (`arrangements[].extent` in `run.json`, and an `arrangement.extent_fixed` notice for each one with no alternative). Work through
  that list before adding alternatives elsewhere, and say in the run notes why any extent-setting member has none.
- **When to declare one.** While laying out a module, wherever a member's side or turn is a free choice the module's own rules
  allow. Ask of each placed member: "would the module be as correct with this on the other side or turned?" If yes, declare the
  other way. A member whose place is a fact (a polarised part read by assembly, a connector's mouth, a part held by its datasheet's
  figure) gets none.
- **Every alternative keeps the module's intent.** An alternative is a relation the module is equally happy with, not a
  compromise for a board that does not exist yet. The run proves it by the module's own links, limits, keepouts and checks, and one
  that fails is not offered. A shape that breaks the module's reason (a decoupling loop, a sense line, a thermal path) is not an
  alternative.
- **Within the caps.** `place.arrangement_options_max` options per item and `place.arrangements_max` arrangements per module, the
  product counted. Prefer a few alternatives on the members that matter, name a group for a combination that only works together
  instead of declaring each member's options, and use `only=` for copper that exists in some arrangements.
- **Names.** An option is named for what it does (`east`, `turned`, `back`), a group for what it is (`mirrored`), never `alt1`:
  ids appear in the board script's `arrangements=`, in the lock, in step notes and in the studio.
- **Reading the report.** After the module run read `run.json`'s `arrangements` and the `arrangement.refused` and
  `arrangement.limit` findings, refused ones included. For each refused alternative read the refusals, then fix it (a `gap=`, a
  different anchor, `only=` for a track that cannot exist there) or drop it. A module is not finished with a declared alternative
  that is refused.
```

`api.md`: after the Modules paragraph add `**Arrangements.**` with: the three forms with the spec's examples, the ids, `only=`, the limits and switch, the proof (three steps, what is recorded not refused), the record shape (the JSON from the spec), the fragment's notes (`placemat arrangement ...`, escaped, split by `place.arrangement_note_chars`), the findings. In "Report form and the files placemat writes" add the `run` row: ``| `run` (a module with alternatives) | `arrangements/<id>/` with `layout.kicad_pcb`, `drc.json`, `reuse.json` (and `reuse.partial.jsonl` while it runs) for each arrangement | the run's folder |`` and a line saying `run.json` gains `arrangements` for such a module. `migration.md` "Unreleased" gets:

```
### Added

- **A module declares alternative arrangements.** `board.alternative(item, name, ...)`, `board.arrangement(name, Alt(...), ...)` and `only=` on the copper forms; the module run proves each and writes the offered ones into the fragment, so a script that wants them runs its module again. The word is "arrangement": a `.zen`'s per-variant `Layout` and explore's variants are other things. A module that declares none is unchanged. New settings: `place.arrangements`, `place.arrangement_options_max`, `place.arrangements_max`, `place.arrangement_note_chars`, `place.extent_notice_mm`, `score.arrangement`.
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py tests/test_describe.py tests/test_queries.py tests/test_suggestion_cases.py tests/test_settings_docs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/placemat/SKILL.md skills/placemat/references/api.md skills/placemat/references/migration.md tests/test_arrangement_declarations.py
git commit -m "Arrangements: skill and api.md for declaring, proving and reading a module's alternatives"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 1.11: Phase 1 gate

**Files:** none changed unless a gate fails.

- [ ] **Step 1: Bench (modules without alternatives are identical)**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`
Expected: every module and config `same`. Any `better` or `worse` is a regression of this phase: find it with `git bisect` over the Phase 1 commits before going on.

- [ ] **Step 2: Byte-identical module run**

Run, once (real modules, one at a time): `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_arrangement_run.py::test_the_written_fragment_is_the_defaults_and_equal_to_a_run_with_no_alternatives tests/test_arrangement_run.py::test_a_module_with_no_alternatives_writes_no_arrangement_record_or_directory -q`
Expected: PASS. Then compare the bytes against `main`: in a scratch checkout of `main` (`git worktree add <scratchpad>/main-wt main`), run the same module with `real_modules.run` and compare `layout.kicad_pcb` with this branch's (`cmp`); expected identical. Remove the worktree afterwards (`git worktree remove`).

- [ ] **Step 3: Default suite**

Run: `.venv/bin/python -m pytest -n 2`
Expected: PASS (slow tests left out). Run `--full` once before the release only.

- [ ] **Step 4: Real-module fixture check**

Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_arrangement_run.py -q -s`
Expected: PASS, and the printed note sizes recorded in the spec's build notes (Task 1.9).

- [ ] **Step 5: Commit any fixes and tag the phase in the branch notes**

```bash
git status --short
```
Expected: nothing to commit. Phases 1 can ship alone: a module can declare and prove arrangements, and a board that does not yet read them is unaffected (the notes are dropped from its written board only from Task 2.5; until then an old reader leaves them in the group, so ship Phase 1 and 2 together or keep `_is_note` from Task 1.9, which already strips them).

---

# Phase 2: the board reads and writes arrangements

### Task 2.1: Arranged geometry from a note (pure)

**Files:**
- Modify: `src/placemat/geometry.py` (add `pose_transform` after `Transform`, `:82-130`), `src/placemat/occupancy.py:641-661` (`_transform` delegates to it)
- Modify: `src/placemat/board_geometry.py` - `CellGeom` (`:115-131`: new fields and methods), new records `MemberPose` and `Arrangement` before it
- Create: `src/placemat/arranged_geometry.py`
- Modify: `src/placemat/arrangement_note.py` (`document(..., order=0)` adds `"order"`; Task 1.6) and `arrangement_run.finish`/`members_doc` pass `order=index in prepared.specs`
- Test: `tests/test_arranged_geometry.py`; extend `tests/arrangement_support.py`

**Interfaces:**
- Consumes: `arrangement_note.read_notes/pose_from_json/op_from_json/base_digest`, `board_geometry.stamped_net/RuleArea/CopperItem`, `geometry.transform_box`.
- Produces:
  - `geometry.pose_transform(reference: Placement, placement: Placement) -> Transform` (exactly what `Occupancy._transform` computes; the latter now calls it)
  - `board_geometry.MemberPose(ref: str, inst: str, pose: Placement, default: Placement)` (frozen); `Arrangement(id: str, choices: dict, members: tuple[MemberPose, ...], ops: tuple, rule_areas: tuple, geom: CellGeom)` (frozen, `choices` and `ops` `compare=False`)
  - `CellGeom.arrangements: tuple = ()`, `.arrangement: str = ""`, `.poses: tuple = ()` ((ref, Placement) in the generated board's frame), `.own_copper: tuple | None = None` (an arranged cell's own `CopperItem`s), `.arrangement_problems: tuple = ()` (`{"reason", "ids"}`), all `compare=False`; `CellGeom.arranged(ident: str = "") -> CellGeom` (`""` and `"default"` give the cell itself; an unknown id `KeyError` naming the ids offered); `CellGeom.offered() -> tuple[str, ...]`
  - `arranged_geometry.build(cell, doc, nets, layers) -> tuple[Arrangement | None, dict | None]` (the problem is `{"reason": "version"|"base"|"offset"|"member"|"net", "ids": [id]}`); `arranged_geometry.attach(cell, texts, nets, layers) -> CellGeom` (the cell itself when it has no texts; arrangements ordered by the note's `order`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/arrangement_support.py`:

```python
import dataclasses

from placemat import arrangement_note as N
from placemat.arranged_geometry import attach
from placemat.copper import Track
from placemat.placement import Placement
from placemat.values import CopperLayer, Face


def stamped_geometry(offset=(30.0, 10.0), partner=None, obstacle=None):
    """A board holding cell `mod` stamped from a fragment whose c_in stood at (1.0, 3.0) and u1 at (6.0, 3.0), moved by `offset`, and
    a loose part. The fragment's nets are `VIN`, `GND` and `OUT`; the board names them `mod.VIN` and so on. `partner=(x, y)` adds a
    part `r8` on the cell's VIN net there (the pull a search follows); `obstacle=(x, y, w, h)` adds a part `obst` that fills that box."""
    ox, oy = offset
    fps = [footprint("C1", 1.0 + ox, 3.0 + oy, w=3, h=1.6, nets=("mod.VIN", "mod.GND"), cell="mod", inst="mod.c_in"),
           footprint("U1", 6.0 + ox, 3.0 + oy, w=6, h=4, nets=("mod.VIN", "mod.OUT"), cell="mod", inst="mod.u1"),
           footprint("R9", 5, 5, nets=("mod.OUT", "GND"))]
    if partner is not None:
        fps.append(footprint("R8", partner[0], partner[1], w=3, h=1.6, nets=("mod.VIN", "GND"), inst="r8"))
    if obstacle is not None:
        x, y, w, h = obstacle
        fps.append(footprint("R7", x, y, w=w, h=h, nets=("GND", "GND"), inst="obst"))
    return board_geometry(fps, cells=["mod"], extra_nets=("mod.GND", "GND"), width=80, height=60)


DEFAULT_C_IN = Placement(Location(1.0, 3.0), 0.0, Face.FRONT)
DEFAULT_U1 = Placement(Location(6.0, 3.0), 0.0, Face.FRONT)
OBSTACLE = (43.0, 32.5, 2.0, 1.0)         # filled in the default's u1 and free in c_in.east, for a firm cell with its box centre on (40, 30)


def east_doc(ident="c_in.east", order=1, ops=None, base_from=None):
    """The note of an arrangement that turns c_in half way round and stands it east of u1 (fragment frame)."""
    east = Placement(Location(11.0, 3.0), 180.0, Face.FRONT)
    ops = [Track("VIN", CopperLayer.F, 0.3, Location(9.0, 3.0), Location(10.1, 3.0))] if ops is None else ops
    return N.document(ident, {"c_in": "east"}, [("c_in", east, DEFAULT_C_IN), ("u1", DEFAULT_U1, DEFAULT_U1)], ops, [], order=order)


def with_arrangement(g=None, doc=None):
    """`stamped_geometry` whose cell `mod` carries the note `doc` read as the reader reads it."""
    g = g or stamped_geometry()
    texts = N.encode(doc or east_doc(), 4000)
    cell = attach(g.cells["mod"], texts, frozenset(g.nets), g.layers)
    return dataclasses.replace(g, cells={**g.cells, "mod": cell})
```
(imports: `from placemat.values import Location` at the top of the file.)

```python
# tests/test_arranged_geometry.py
import dataclasses

import pytest

from placemat import arrangement_note as N
from placemat.arranged_geometry import attach, build
from placemat.geometry import pose_transform
from placemat.placement import Placement
from placemat.values import Face, Location
from tests.arrangement_support import DEFAULT_C_IN, east_doc, stamped_geometry, with_arrangement

NETS = lambda g: frozenset(g.nets)


def test_the_pose_transform_is_the_one_the_occupancy_has_always_used():
    from placemat.occupancy import Occupancy, ItemGeometry
    ref = Placement(Location(3.0, 4.0), 90.0, Face.FRONT)
    g = ItemGeometry(frozenset(["a"]), ref, (), None, frozenset())
    for to in (Placement(Location(9.0, 1.0), 270.0, Face.FRONT), Placement(Location(9.0, 1.0), 10.0, Face.BACK)):
        a, b = Occupancy._transform(g, to), pose_transform(ref, to)
        assert (a.a, a.b, a.c, a.d, a.tx, a.ty) == (b.a, b.b, b.c, b.d, b.tx, b.ty)


def test_a_note_becomes_an_arrangement_of_the_stamped_cell_in_the_stamped_frame():
    g = stamped_geometry()
    arr, problem = build(g.cells["mod"], east_doc(), NETS(g), g.layers)
    assert problem is None and arr.id == "c_in.east" and arr.choices == {"c_in": "east"}
    c_in = next(m for m in arr.members if m.inst == "c_in")
    assert c_in.ref == "C1" and c_in.pose == Placement(Location(41.0, 13.0), 180.0, Face.FRONT)
    assert c_in.default == Placement(Location(31.0, 13.0), 0.0, Face.FRONT)
    geom = arr.geom
    assert geom.arrangement == "c_in.east" and dict(geom.poses)["C1"] == c_in.pose and geom.members == g.cells["mod"].members
    assert geom.box.center.x > g.cells["mod"].box.center.x                      # c_in moved east of u1
    (track,) = [c for c in geom.own_copper if c.kind == "track"]
    assert track.net == "mod.VIN" and track.owner == "mod" and abs(track.anchors[0][0] - 39.0) < 1e-6   # shifted into the stamped frame
    assert g.cells["mod"].arrangements == ()                                      # the default cell is untouched


def test_the_cell_offers_its_arrangements_in_the_modules_order_and_answers_arranged():
    g = with_arrangement()
    cell = g.cells["mod"]
    assert cell.offered() == ("c_in.east",) and cell.arranged("") is cell and cell.arranged("default") is cell
    assert cell.arranged("c_in.east").arrangement == "c_in.east"
    with pytest.raises(KeyError) as e:
        cell.arranged("nope")
    assert "c_in.east" in str(e.value)
    two = N.encode(east_doc("c_in.b", 2), 4000) + N.encode(east_doc("c_in.a", 1), 4000)
    both = attach(stamped_geometry().cells["mod"], two, NETS(stamped_geometry()), stamped_geometry().layers)
    assert both.offered() == ("c_in.a", "c_in.b")


def test_a_cell_with_no_note_is_returned_as_it_is():
    g = stamped_geometry()
    assert attach(g.cells["mod"], [], NETS(g), g.layers) is g.cells["mod"]


def stale(g, doc, cell=None):
    return build(cell or g.cells["mod"], doc, NETS(g), g.layers)


def test_a_note_that_cannot_stand_is_stale_with_its_reason():
    """Review focus 2."""
    g = stamped_geometry()
    assert stale(g, dict(east_doc(), v=2))[1] == {"reason": "version", "ids": ["c_in.east"]}
    assert stale(g, dict(east_doc(), base="0000"))[1]["reason"] == "base"
    moved = east_doc()
    moved["members"][1]["from"] = [6.5, 3.0, 0.0, "front"]
    moved["base"] = N.base_digest([(m["inst"], N.pose_from_json(m["from"])) for m in moved["members"]])
    assert stale(g, moved)[1]["reason"] == "offset"                                # u1 would stand at another offset than c_in
    gone = east_doc()
    gone["members"] = gone["members"][:1]
    assert stale(g, gone)[1]["reason"] == "member"                                  # the cell has u1, the note has not
    extra = east_doc()
    extra["members"].append(dict(extra["members"][0], inst="nowhere"))
    assert stale(g, extra)[1]["reason"] == "member"
    from placemat.copper import Via
    nonet = east_doc(ops=[Via("NOPE", Location(1, 1), 0.3, 0.6)])
    assert stale(g, nonet)[1]["reason"] == "net"


def test_attach_keeps_the_good_arrangements_and_records_the_stale_ones():
    g = stamped_geometry()
    texts = N.encode(east_doc("c_in.east", 1), 4000) + N.encode(dict(east_doc("c_in.old", 2), v=2), 4000) + \
        N.encode(east_doc("c_in.t", 3), 40)[:-1]                                    # one truncated numbered note
    cell = attach(g.cells["mod"], texts, NETS(g), g.layers)
    assert cell.offered() == ("c_in.east",)
    assert sorted(p["reason"] for p in cell.arrangement_problems) == ["text", "version"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arranged_geometry.py -v`
Expected: FAIL (`ModuleNotFoundError: placemat.arranged_geometry`).

- [ ] **Step 3: Implement**

`geometry.py` (after the `Transform` class; `from .placement import Placement` at the top, no cycle: placement imports only `values`):

```python
def pose_transform(reference: "Placement", placement: "Placement") -> Transform:
    """Where an item's shapes go when it moves from `reference` to `placement`: a flip to the back mirrors about the vertical
    axis and then turns by the rotation asked for (KiCad's own F key); adding the reference rotation rather than subtracting it
    is what cancels the generator's own rotation out of the answer."""
    t = Transform.translate(-reference.location.x, -reference.location.y)
    flip = placement.face != reference.face
    if flip:
        t = t.then(Transform.mirror_x(Location(0, 0)))
    turn = placement.rotation + reference.rotation if flip else placement.rotation - reference.rotation
    t = t.then(Transform.rotate(turn))
    return t.then(Transform.translate(placement.location.x, placement.location.y))
```
`occupancy.py` `_transform(geom, placement)` body becomes `return pose_transform(geom.reference, placement)` (keep its docstring; import `pose_transform` with the other `.geometry` imports).

`board_geometry.py` (before `CellGeom`; imports `from .placement import Placement`):

```python
@dataclass(frozen=True)
class MemberPose:
    """One member of a cell as an arrangement stands it: its place in the generated board's frame, and the place it was stamped at."""
    ref: str
    inst: str                   # the instance path within the module, as the note names it
    pose: "Placement"
    default: "Placement"


@dataclass(frozen=True)
class Arrangement:
    """One arrangement a module run proved, read from its note for the cell that was stamped: `geom` is the cell as it stands in it."""
    id: str
    choices: dict = field(compare=False)
    members: tuple              # MemberPose, one per member
    ops: tuple = field(compare=False)           # the module's copper for it, in this board's nets and frame (copper.Track, Via, ...)
    rule_areas: tuple = ()      # RuleArea, in this board's frame
    geom: "CellGeom" = None
```
`CellGeom` gains (after `rules`):

```python
    arrangements: tuple = field(default=(), compare=False)         # Arrangement of the module's other offered arrangements (arranged_geometry.attach)
    arrangement: str = ""                                          # "" the module's own layout; else the id this geometry stands for
    poses: tuple = field(default=(), compare=False)                # an arranged cell: ((ref, Placement), ...) of its members in the generated board's frame
    own_copper: tuple | None = field(default=None, compare=False)  # an arranged cell: its own CopperItems, in place of the board's for the cell
    arrangement_problems: tuple = field(default=(), compare=False)  # notes that could not stand: {"reason", "ids"} (arrangement.stale)

    def offered(self) -> tuple:
        return tuple(a.id for a in self.arrangements)

    def arranged(self, ident: str = "") -> "CellGeom":
        """The cell as arrangement `ident` stands it; the cell itself for "" and "default"."""
        if ident == self.arrangement or (not self.arrangement and ident == "default"):
            return self                                # the layout it already stands in ("" is the module's own)
        for a in self.arrangements:
            if a.id == ident:
                return a.geom
        raise KeyError("cell %s has no arrangement %r; it offers %s" % (self.name, ident, ", ".join(("default",) + self.offered())))
```
`arranged_geometry.py`:

```python
"""A module's arrangement note read for the board that stamped the cell: the members' places by delta from where the stamp put them, the
module's copper from its ops, and the CellGeom that stands for the arrangement. Pure: the reader (kicad/read.py) hands it the texts."""
from __future__ import annotations

import dataclasses

from . import arrangement_note as note
from .board_geometry import Arrangement, CellGeom, CopperItem, MemberPose, RuleArea, resolve_marker, stamped_net
from .copper import Pour, Text, Track, Via, Zone
from .geometry import pose_transform, transform_box
from .placement import Placement
from .values import Box, CopperLayer, Location

_TOL = 1e-3


def _problem(reason: str, ident: str = "") -> dict:
    return {"reason": reason, "ids": [ident] if ident else []}


def _member(cell: CellGeom, inst: str):
    """The stamped member the note's instance path names: `<cell>.<inst>`, else the one member whose path ends in `.<inst>`."""
    exact = [fp for fp in cell.members if fp.inst == "%s.%s" % (cell.name, inst)]
    if exact:
        return exact[0]
    ends = [fp for fp in cell.members if fp.inst.endswith("." + inst)]
    return ends[0] if len(ends) == 1 else None


def _shift(op, dx: float, dy: float, net: str):
    moved = lambda p: (p.x + dx, p.y + dy) if not isinstance(p, Location) else Location(p.x + dx, p.y + dy)
    if isinstance(op, Track):
        return dataclasses.replace(op, net=net, start=moved(op.start), end=moved(op.end),
                                   mid=None if op.mid is None else moved(op.mid))
    if isinstance(op, Via):
        return dataclasses.replace(op, net=net, at=moved(op.at))
    if isinstance(op, (Pour, Zone)):
        return dataclasses.replace(op, net=net, points=tuple(moved(p) for p in op.points))
    return dataclasses.replace(op, at=moved(op.at))                 # a text


def _copper_item(op, owner: str, layers):
    if isinstance(op, Track):
        return CopperItem("track", op.net, frozenset([op.layer]), (op.polygon,), op.box, owner, op.width, 0.0,
                          ((op.start.x, op.start.y), (op.end.x, op.end.y)), op.length)
    if isinstance(op, Via):
        every = frozenset(layers)
        return CopperItem("via", op.net, frozenset(op.layers) if op.layers else every, (op.polygon,), op.box, owner, op.size,
                          op.drill, ((op.at.x, op.at.y),))
    if isinstance(op, Pour):
        return CopperItem("poly", op.net, frozenset([op.layer]), (op.points,), op.box, owner, op.stroke, 0.0, (), 0.0,
                          (op.points,), True)
    if isinstance(op, Zone):
        return CopperItem("zone", op.net, frozenset([op.layer]), (op.points,), op.box, owner)
    return None


def build(cell: CellGeom, doc: dict, nets, layers):
    """(the Arrangement, None) for note `doc` on the stamped `cell`, or (None, the problem that keeps it from standing)."""
    ident = doc.get("id", "")
    if doc.get("v") != note.VERSION:
        return None, _problem("version", ident)
    stamped = {}
    for m in doc["members"]:
        fp = _member(cell, m["inst"])
        if fp is None:
            return None, _problem("member", ident)
        stamped[m["inst"]] = fp
    if {fp.ref for fp in stamped.values()} != {fp.ref for fp in cell.members} or len(stamped) != len(cell.members):
        return None, _problem("member", ident)
    offsets, poses = [], []
    for m in doc["members"]:
        fp, was = stamped[m["inst"]], note.pose_from_json(m["from"])
        turned = ((fp.rotation - was.rotation + 180.0) % 360.0) - 180.0
        if abs(turned) > _TOL or fp.face != was.face:
            return None, _problem("offset", ident)
        offsets.append((fp.location.x - was.location.x, fp.location.y - was.location.y))
    dx, dy = offsets[0]
    if any(abs(x - dx) > _TOL or abs(y - dy) > _TOL for x, y in offsets):
        return None, _problem("offset", ident)
    if note.base_digest([(m["inst"], note.pose_from_json(m["from"])) for m in doc["members"]]) != doc.get("base"):
        return None, _problem("base", ident)
    for m in doc["members"]:
        fp, a = stamped[m["inst"]], Placement(Location(m["x"], m["y"]), m["rotation"], note.Face(m["face"]))
        poses.append(MemberPose(fp.ref, m["inst"], Placement(Location(a.location.x + dx, a.location.y + dy), a.rotation, a.face),
                                Placement(fp.location, fp.rotation, fp.face)))
    ops, items = [], []
    for raw in doc["ops"]:
        op = note.op_from_json(raw)
        mapped = stamped_net(op.net, cell.name, nets) if op.net else ""
        if op.net and mapped is None:
            return None, _problem("net", ident)
        op = _shift(op, dx, dy, mapped)
        ops.append(op)
        item = _copper_item(op, cell.name, layers)
        if item is not None:
            items.append(item)
    areas = []
    for k in (note.keepout_from_json(d) for d in doc["keepouts"]):
        have, _ = resolve_marker("*" if k.layers is None else tuple(k.layers), layers)
        allow = frozenset(n for n in (stamped_net(a, cell.name, nets) for a in k.allow) if n is not None)
        areas.append(RuleArea(k.name, cell.name, tuple((x + dx, y + dy) for x, y in k.poly), have, frozenset(k.excludes),
                              (), (), allow))
    moved_boxes = lambda attr: [transform_box(getattr(p_fp, attr), pose_transform(mp.default, mp.pose))
                                for mp in poses for p_fp in (next(f for f in cell.members if f.ref == mp.ref),)]
    own = [c.box for c in items]
    geom = dataclasses.replace(
        cell, box=Box.union(moved_boxes("body_box") + own), phys_box=Box.union(moved_boxes("phys_box") + own),
        courtyard_box=Box.union(moved_boxes("courtyard_box") + own), copper_box=Box.union(own) if own else None,
        arrangements=(), arrangement=ident, poses=tuple((mp.ref, mp.pose) for mp in poses), own_copper=tuple(items),
        arrangement_problems=())
    return Arrangement(ident, doc.get("choices", {}), tuple(poses), tuple(ops), tuple(areas), geom), None


def attach(cell: CellGeom, texts, nets, layers) -> CellGeom:
    """`cell` with the arrangements its note texts carry (in the order the module run gave them), and the problems of those that
    could not stand; the cell itself when it has no text."""
    texts = list(texts)
    if not texts:
        return cell
    docs, problems = note.read_notes(texts)
    built = []
    for d in sorted(docs, key=lambda d: (d.get("order", 0), d["id"])):
        arr, problem = build(cell, d, nets, layers)
        if arr is None:
            problems.append(problem)
        else:
            built.append(arr)
    return dataclasses.replace(cell, arrangements=tuple(built), arrangement_problems=tuple(problems))
```
In `arrangement_note.py` (Task 1.6) make `document(ident, choices, members, ops, keepouts, order=0)` add `"order": order` to the dict, and export `Face` (the module imports it already: `from .values import CopperLayer, Face, Location`). In `arrangement_run.members_doc` pass `order=[s.id for s in prepared.specs].index(spec.id)`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arranged_geometry.py tests/test_arrangement_note.py tests/test_occupancy*.py tests/test_scan*.py tests/test_beside.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/geometry.py src/placemat/occupancy.py src/placemat/board_geometry.py src/placemat/arranged_geometry.py src/placemat/arrangement_note.py src/placemat/arrangement_run.py tests/arrangement_support.py tests/test_arranged_geometry.py
git commit -m "Arrangements: a note read into the arranged geometry of a stamped cell, with the reasons it can be stale"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 2.2: The reader attaches arrangements; stale ones are findings

**Files:**
- Modify: `src/placemat/kicad/read.py` - `board_geometry_of` (`:784-850`): collect each group's arrangement texts in the cell loop (`:806-826`), attach after `_netclasses` and the layers are known (`:829-831`)
- Modify: `src/placemat/layout.py` - `_resolve_once`, next to the limit finding added in Task 1.5 (after `:6572`): one `arrangement.stale` per cell and reason
- Modify: `tests/arrangement_support.py` (`kicad_cell_board`)
- Test: `tests/test_arrangement_reading.py` (KiCad)

**Interfaces:**
- Consumes: `arranged_geometry.attach`, `kicad.arrange.write_notes` (Task 1.9), `CellGeom.arrangement_problems`.
- Produces: `read_board(path).cells[name].arrangements` and `.arrangement_problems`; `Board._resolve_once` findings `arrangement.stale` (`{"cell", "reason", "ids"}`, severity warning); `tests.arrangement_support.kicad_cell_board(path, cells=(("mod", (30.0, 10.0)),), notes=None) -> Path` (a 2-layer board of the cells, each a group of `c_in` and `u1` stamped at the offset, each part's reference its instance path `<cell>.c_in`, the nets `<cell>.VIN`, `<cell>.GND`, `<cell>.OUT` and `GND`; `notes` is `{cell: [text, ...]}` added as User.Comments texts inside the group).

- [ ] **Step 1: Write the failing tests**

Add to `tests/arrangement_support.py`:

```python
def kicad_cell_board(path, cells=(("mod", (30.0, 10.0)),), notes=None):
    """A 2-layer board of stamped cells (pcbnew, no libraries): each a group of c_in and u1 at the module's places (2.5, 3.0) and (6.0, 3.0) moved
    by the cell's offset. A footprint has no Path field, so its instance is its reference, `<cell>.c_in`."""
    import pcbnew
    mm = pcbnew.FromMM
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(2)
    names = ["GND"] + ["%s.%s" % (c, n) for c, _ in cells for n in ("VIN", "GND", "OUT")]
    info = {}
    for n in names:
        info[n] = pcbnew.NETINFO_ITEM(board, n)
        board.Add(info[n])
    rect = getattr(pcbnew, "PAD_SHAPE_RECT", None) or pcbnew.PAD_SHAPE_RECTANGLE
    for cell, (ox, oy) in cells:
        group = pcbnew.PCB_GROUP(board)
        group.SetName(cell)
        board.Add(group)
        for inst, x, y, n1, n2 in (("c_in", 2.5, 3.0, "VIN", "GND"), ("u1", 6.0, 3.0, "VIN", "OUT")):
            fp = pcbnew.FOOTPRINT(board)
            fp.SetReference("%s.%s" % (cell, inst))
            board.Add(fp)
            fp.SetPosition(pcbnew.VECTOR2I(mm(x + ox), mm(y + oy)))
            for number, dx, net in (("1", -0.9, n1), ("2", 0.9, n2)):
                pad = pcbnew.PAD(fp)
                pad.SetNumber(number)
                pad.SetShape(rect)
                pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                pad.SetSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
                pad.SetLayerSet(pad.SMDMask())
                pad.SetNet(info["%s.%s" % (cell, net)])
                fp.Add(pad)
                pad.SetPosition(pcbnew.VECTOR2I(mm(x + ox + dx), mm(y + oy)))
            group.AddItem(fp)
        track = pcbnew.PCB_TRACK(board)                     # the cell's own stamped copper
        track.SetLayer(pcbnew.F_Cu)
        track.SetNet(info["%s.GND" % cell])
        track.SetWidth(mm(0.3))
        track.SetStart(pcbnew.VECTOR2I(mm(ox), mm(oy + 4.0)))
        track.SetEnd(pcbnew.VECTOR2I(mm(ox + 2.0), mm(oy + 4.0)))
        board.Add(track)
        group.AddItem(track)
        for text in (notes or {}).get(cell, ()):
            t = pcbnew.PCB_TEXT(board)
            t.SetText(text)
            t.SetLayer(pcbnew.Cmts_User)
            t.SetPosition(pcbnew.VECTOR2I(mm(ox), mm(oy + 20)))
            board.Add(t)
            group.AddItem(t)
    board.Save(str(path))
    return path
```

```python
# tests/test_arrangement_reading.py
import pytest

from placemat import arrangement_note as N
from placemat.kicad.read import read_board
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location
from tests.arrangement_support import east_doc, kicad_cell_board
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def test_a_cells_notes_are_read_into_its_arrangements(tmp_path):
    pcb = kicad_cell_board(tmp_path / "layout.kicad_pcb", notes={"mod": N.encode(east_doc(), 4000)})
    cell = read_board(pcb).cell("mod")
    assert cell.offered() == ("c_in.east",) and cell.arrangement_problems == ()
    arr = cell.arrangements[0]
    assert abs(arr.geom.box.center.x - cell.box.center.x) > 1.0
    assert {m.inst for m in arr.members} == {"c_in", "u1"}


def test_a_cell_with_no_note_reads_as_it_always_did(tmp_path):
    pcb = kicad_cell_board(tmp_path / "layout.kicad_pcb")
    cell = read_board(pcb).cell("mod")
    assert cell.arrangements == () and cell.arrangement_problems == ()


def test_a_note_that_cannot_stand_is_a_finding_and_the_cell_places_as_its_default(tmp_path):
    """Review focus 2: a newer note version and a truncated numbered note, through KiCad's save and load."""
    texts = N.encode(dict(east_doc(), v=2), 4000) + N.encode(east_doc("c_in.t"), 40)[:-1]
    pcb = kicad_cell_board(tmp_path / "layout.kicad_pcb", notes={"mod": texts})
    g = read_board(pcb)
    assert g.cell("mod").offered() == () and sorted(p["reason"] for p in g.cell("mod").arrangement_problems) == ["text", "version"]
    from placemat.values import Cell
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.place(Cell("mod"), at=Location(40.0, 30.0))
    plan = b.resolve()
    stale = [f for f in plan.findings if f.cause == "arrangement.stale"]
    assert sorted(f.facts["reason"] for f in stale) == ["text", "version"] and all(f.facts["cell"] == "mod" for f in stale)
    assert plan.placement("mod").arrangement == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_reading.py -v`
Expected: FAIL (`AttributeError: 'CellGeom' object has no attribute 'offered'` is not reachable until Task 2.1; with it, `offered() == ()` for the first test).

- [ ] **Step 3: Implement**

`read.py` `board_geometry_of`: import `from ..arrangement_note import ARRANGEMENT_PREFIX` and `from ..arranged_geometry import attach`. In the per-cell loop, after the `rules = ...` assignment (`:824`) add:

```python
        arrangement_texts[name] = [it.GetText() for it in items
                                   if isinstance(it, pcbnew.PCB_TEXT) and it.GetText().startswith(ARRANGEMENT_PREFIX)]
```
with `arrangement_texts = {}` before the loop (`:803`). Move the `layers = tuple(CopperLayer.of(...))` statement (`:832`) above `return BoardGeometry(...)`'s neighbours so it is computed before use, and after `classes, default_clr = _netclasses(board)`:

```python
    cells = {n: (attach(c, arrangement_texts[n], frozenset(classes), layers) if arrangement_texts.get(n) else c)
             for n, c in cells.items()}
```
`layout.py` `_resolve_once` (after the limit finding from Task 1.5):

```python
        for cname in sorted(self.geometry.cells):
            for p in self.geometry.cells[cname].arrangement_problems:
                plan.findings.append(self._finding(C.ARRANGEMENT_STALE, {"cell": cname, "reason": p["reason"], "ids": p["ids"]}, "warning"))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_reading.py tests/test_board_geometry_read.py tests/test_faces.py tests/test_stamped_rules.py -q`
Expected: PASS. If `kicad_cell_board` fails on a KiCad-10 API name (pad shape, `SMDMask`), fix the helper only; the reader is not at fault.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/kicad/read.py src/placemat/layout.py tests/arrangement_support.py tests/test_arrangement_reading.py
git commit -m "Arrangements: the reader attaches a cell's arrangements and a stale note is a finding"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 2.3: The occupancy builds arranged cells; a placement carries its arrangement

**Files:**
- Modify: `src/placemat/placement.py` (whole file, 17 lines)
- Modify: `src/placemat/occupancy.py` - `__init__` copper loop (`:498-516`: extract `_copper_shapes`), `_geometry` (`:590-604`), `placed_geometries` (`:1163-1189`), `commit` (`:1053-1060`); add `_member_geometries`, `_posed`, `_arranged_own`, `_arranged` (static)
- Modify: `src/placemat/reuse.py:141-151` (`placement_to_json`, `placement_from_json`)
- Test: `tests/test_arrangement_occupancy.py`

**Interfaces:**
- Consumes: `CellGeom.arranged/poses/own_copper` (Task 2.1), `geometry.pose_transform`.
- Produces: `Placement(location, rotation, face, arrangement: str = "")` (`moved` and `at` keep it); `reuse.placement_to_json(p)` -> `[x, y, rotation, face]` plus `arrangement` as a fifth element only when not `""`; `placement_from_json` reads both; `Occupancy._geometry(arranged_cell)` cached under `(name, arrangement)`; `Occupancy._member_geometries(item) -> dict[ref, ItemGeometry]`; `Occupancy._arranged_own(item) -> list[Shape]`; `Occupancy.commit(item, placement)` commits `item.arranged(placement.arrangement)` when the placement names one; `Occupancy.thin_arranged: callable | None` (Task 2.5 sets it) and `Occupancy.arranged_gone: dict[(cell, arrangement), list[(x, y)]]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_occupancy.py
import dataclasses

from placemat import reuse
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Face, Location
from tests.arrangement_support import stamped_geometry, with_arrangement, footprint, board_geometry


def pads(geom, owner=None):
    return sorted((s.net, round(s.box.center.x, 3), round(s.box.center.y, 3)) for s in geom.shapes
                  if s.kind == "pad" and (owner is None or s.owner == owner))


def test_a_placement_serialises_as_it_did_and_gains_an_element_only_for_an_arrangement():
    p = Placement(Location(1.0, 2.0), 90.0, Face.FRONT)
    assert reuse.placement_to_json(p) == [1.0, 2.0, 90.0, "front"]
    q = dataclasses.replace(p, arrangement="c_in.east")
    assert reuse.placement_to_json(q) == [1.0, 2.0, 90.0, "front", "c_in.east"]
    assert reuse.placement_from_json([1.0, 2.0, 90.0, "front"]) == p and reuse.placement_from_json(reuse.placement_to_json(q)) == q
    assert q.moved(1.0, 0.0).arrangement == "c_in.east" and q.at(Location(0, 0)).arrangement == "c_in.east"


def test_an_arranged_cells_geometry_is_its_members_moved_by_their_delta():
    g = with_arrangement()
    occ = Occupancy(g)
    cell = g.cells["mod"]
    default = occ._geometry(cell)
    arranged = occ._geometry(cell.arranged("c_in.east"))
    assert default is occ._geometry(cell) and arranged is occ._geometry(cell.arranged("c_in.east")) and arranged is not default
    assert [p[0] for p in sorted(pads(default, "C1"), key=lambda p: p[1])] == ["mod.VIN", "mod.GND"]
    assert [p[0] for p in sorted(pads(arranged, "C1"), key=lambda p: p[1])] == ["mod.GND", "mod.VIN"]      # turned half way round
    assert min(p[1] for p in pads(arranged, "C1")) > max(p[1] for p in pads(arranged, "U1"))                  # and east of u1
    assert pads(arranged, "U1") == pads(default, "U1")
    assert arranged.body.center.x > default.body.center.x


def test_it_equals_the_geometry_of_a_cell_stamped_from_a_fragment_whose_default_is_that_arrangement():
    g = with_arrangement()
    arranged = Occupancy(g)._geometry(g.cells["mod"].arranged("c_in.east"))
    fps = [footprint("C1", 41.0, 13.0, w=3, h=1.6, nets=("mod.GND", "mod.VIN"), cell="mod", inst="mod.c_in", rotation=180.0),
           footprint("U1", 36.0, 13.0, w=6, h=4, nets=("mod.VIN", "mod.OUT"), cell="mod", inst="mod.u1"),
           footprint("R9", 5, 5, nets=("mod.OUT", "GND"))]
    stamped = board_geometry(fps, cells=["mod"], extra_nets=("mod.GND", "GND"), width=80, height=60)
    direct = Occupancy(stamped)._geometry(stamped.cells["mod"])
    assert pads(arranged) == pads(direct)
    assert abs(arranged.body.left - direct.body.left) < 1e-3 and abs(arranged.body.right - direct.body.right) < 1e-3


def test_committing_an_arranged_cell_leaves_its_members_where_the_arrangement_puts_them():
    g = with_arrangement()
    occ = Occupancy(g)
    cell = g.cells["mod"]
    arr = cell.arranged("c_in.east")
    placement = Placement(Location(50.0, 20.0), 0.0, Face.FRONT, "c_in.east")
    occ.commit(cell, placement)                                 # the default item and a placement that names the arrangement
    moved = occ.items["C1"].reference
    base = occ._geometry(arr).reference                         # the cell's reference point is the arranged box centre
    assert moved.rotation == 180.0 and abs(moved.location.x - (50.0 + dict(arr.poses)["C1"].location.x - base.location.x)) < 1e-6
    assert occ.items["U1"].reference.rotation == 0.0


def test_the_default_cell_is_committed_as_before():
    g = stamped_geometry()
    a, b = Occupancy(g), Occupancy(g)
    cell = g.cells["mod"]
    a.commit(cell, Placement(Location(50.0, 20.0)))
    b.commit(cell, Placement(Location(50.0, 20.0), 0.0, Face.FRONT, ""))
    assert a.items["C1"].reference == b.items["C1"].reference
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_occupancy.py -v`
Expected: FAIL (`TypeError: Placement.__init__() takes from 2 to 4 positional arguments`).

- [ ] **Step 3: Implement**

`placement.py`:

```python
@dataclass(frozen=True, order=True)
class Placement:
    location: Location
    rotation: float = 0.0
    face: Face = Face.FRONT
    arrangement: str = ""           # a cell's arrangement ("" the module's own layout): which of the module's proven layouts stands here

    def moved(self, dx: float, dy: float) -> "Placement":
        return Placement(self.location.offset(dx, dy), self.rotation, self.face, self.arrangement)

    def at(self, location: Location) -> "Placement":
        return Placement(location, self.rotation, self.face, self.arrangement)
```
`reuse.py`:

```python
def placement_to_json(p):
    if p is None:
        return None
    out = [p.location.x, p.location.y, p.rotation, p.face.value]
    if p.arrangement:
        out.append(p.arrangement)           # a placement with no arrangement writes the bytes it wrote before
    return out


def placement_from_json(v):
    if v is None:
        return None
    return Placement(Location(v[0], v[1]), v[2], Face(v[3]), v[4] if len(v) > 4 else "")
```
`occupancy.py`: extract the loop at `:498-516` (everything from `carried = _cell_vias(...)` through the last `self.copper.append(...)` of the hole) into

```python
    def _copper_shapes(self, items, carried: dict) -> list:
        """The shapes of stamped copper `items` (a cell's own tracks, vias and polygons: pads travel with their footprint, a fill pulls
        back round whatever is placed), carried vias tagged from `carried` (`_cell_vias`)."""
        out = []
        for c in items:
            ... the existing body, `self.copper.append(X)` becoming `out.append(X)`, `geometry.layers` becoming `self.geometry.layers` ...
        return out
```
and `__init__` keeps `carried = _cell_vias(geometry, self.settings.place_via_route_distance > 0)` and `self.copper.extend(self._copper_shapes(geometry.copper, carried))`. Add:

```python
    thin_arranged = None                  # layout.py sets it: (arranged cell, its own shapes) -> (the shapes kept, [(x, y)] of the drops thinned)
    arranged_gone: dict = {}              # (cell, arrangement) -> where its drops= took vias out (filled when its geometry is built)

    @staticmethod
    def _arranged(item, placement):
        """`item`, or the arranged cell `placement` names."""
        if isinstance(item, CellGeom) and placement.arrangement and item.arrangement != placement.arrangement:
            return item.arranged(placement.arrangement)
        return item

    def _posed(self, geom: ItemGeometry, pose: Placement) -> ItemGeometry:
        """A member's geometry moved to `pose`: where an arrangement stands it."""
        t = self._transform(geom, pose)
        return ItemGeometry(geom.owners, pose, tuple(self._moved(geom, geom.shapes, pose)), transform_box(geom.body, t),
                            geom.nets, transform_box(geom.reach or geom.body, t))

    def _member_geometries(self, item) -> dict:
        """{ref: ItemGeometry} of a cell's members as the cell stands: as generated, or, an arranged cell, each moved to its arrangement's place."""
        poses = dict(item.poses)
        out = {}
        for fp in item.members:
            base = self.geometry_of(fp.ref)
            pose = poses.get(fp.ref)
            out[fp.ref] = base if pose is None or pose == base.reference else self._posed(base, pose)
        return out

    def _arranged_own(self, item) -> list:
        """An arranged cell's own copper as shapes, built as the board's own are, with its carried vias found among them."""
        import types
        items = item.own_copper or ()
        shapes = self._copper_shapes(items, _cell_vias(types.SimpleNamespace(copper=items, cells={item.name: item}),
                                                       self.settings.place_via_route_distance > 0))
        if self.thin_arranged is not None:
            shapes, gone = self.thin_arranged(item, shapes)
            self.arranged_gone = dict(self.arranged_gone, **{(item.name, item.arrangement): gone})
        return shapes
```
(`arranged_gone` is replaced rather than mutated: it is a class-level default.) `_geometry` CellGeom branch:

```python
        if isinstance(item, CellGeom):
            key = (item.name, item.arrangement) if item.arrangement else item.name
            if key in self._cells:
                return self._cells[key]
            if item.arrangement:
                self._cells[key] = self.cell_geometry(item, self._member_geometries(item), self._arranged_own(item))
                return self._cells[key]
            own = self._pristine_copper.get(item.name)
            if own is None:
                own = [c for c in self.copper if c.owner == item.name]
            self._cells[key] = self.cell_geometry(item, {fp.ref: self.geometry_of(fp.ref) for fp in item.members}, own)
            return self._cells[key]
```
`commit` first line: `item = self._arranged(item, placement)`; `placed_geometries`: before the member loop `members = self._member_geometries(item) if item.arrangement else None` and in the loop `m = members[fp.ref] if members is not None else self.items[fp.ref]`. The type annotation of `_cells` becomes `dict`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_occupancy.py tests/test_occupancy*.py tests/test_cell_*.py tests/test_scan*.py tests/test_vias_give_way.py tests/test_carried_via_grids.py -q`
Expected: PASS (the existing cell and carried-via tests prove the extraction changed nothing).

- [ ] **Step 5: Bench and commit**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out` (every case `same`).

```bash
git add src/placemat/placement.py src/placemat/reuse.py src/placemat/occupancy.py tests/test_arrangement_occupancy.py
{ echo "Arrangements: the occupancy builds an arranged cell from its members' deltas and Placement carries the arrangement"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 2.4: `arrangements=` lays a cell in an arrangement

**Files:**
- Modify: `src/placemat/layout.py` - `PlaceIntent` (`:274-322`, new field after `budget`), `place()` signature and body (`:2866-3185`; the validation near `:2923`), `_settle` (`:9122-9127`, the gate), `_step` (`:7120-7132`), `_firm_placement` callers unchanged; new `_offered`, `_arrangement_ids`, `_arranged`, `_gate`
- Modify: `src/placemat/runner.py:753-756` (`rec.placements` carries `arrangement` when not default)
- Test: `tests/test_arrangement_pin.py`

**Interfaces:**
- Consumes: Task 2.1-2.3 (`CellGeom.arranged`, `Placement.arrangement`), `findings` cause `arrangement.missing`.
- Produces: `PlaceIntent.arrangements: tuple` (`omit_default`); `place(..., arrangements=None)` (an id or a sequence of ids, a cell only; `TypeError` otherwise); `Board._offered(item) -> tuple[str, ...]` (`()` when `place.arrangements` is false); `Board._arrangement_ids(i) -> list[str]` (the arrangement ids a search of cell `i` tries, `""` standing for the default, in order: `arrangements=` as given, else the default then everything offered); `Board._arranged(i, ident) -> PlaceIntent` (the intent with its item arranged); `Board._gate(occ, i, plan) -> tuple[PlaceIntent, Step | None]` (a step when an asked id is not offered); `_step` stamps `placement.arrangement` from an arranged item; `run.json`'s `placements[cell]["arrangement"]` when not default.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_pin.py
import dataclasses

import pytest

from placemat.layout import Board, CriticalUnplaced
from placemat.settings import Settings
from placemat.values import Cell, Location, Part
from tests.arrangement_support import stamped_geometry, with_arrangement


def board(settings=None, g=None):
    return Board(g or with_arrangement(), edge_margin=0.0, keep_going=True, settings=settings or Settings())


def test_one_id_lays_that_arrangement_and_default_holds_the_modules_own_layout():
    b = board()
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.east")
    plan = b.resolve()
    p = plan.placement("mod")
    assert p.arrangement == "c_in.east"
    assert plan.occupancy.items["C1"].reference.rotation == 180.0 and abs(plan.box("mod").center.x - 40.0) < 1e-3
    held = board()
    held.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="default")
    plan2 = held.resolve()
    assert plan2.placement("mod").arrangement == "" and plan2.occupancy.items["C1"].reference.rotation == 0.0


def test_a_part_cannot_take_arrangements():
    b = board()
    with pytest.raises(TypeError):
        b.place(Part("R9"), at=Location(5, 5), arrangements="x")


def test_an_id_the_cell_does_not_offer_leaves_it_unplaced_with_the_ids_offered():
    b = board()
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.west")
    plan = b.resolve()
    assert plan.step("mod").placement is None
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.facts == {"item": "mod", "asked": ["c_in.west"], "offered": ["default", "c_in.east"]}


def test_missing_stops_the_run_with_required():
    b = Board(with_arrangement(), edge_margin=0.0)
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.west", required=True)
    with pytest.raises(CriticalUnplaced):
        b.resolve()


def test_the_switch_off_offers_the_default_only():
    off = dataclasses.replace(Settings(), place_arrangements=False)
    b = board(off)
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.east")
    plan = b.resolve()
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.facts["offered"] == ["default"]
    ok = board(off)
    ok.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="default")
    assert ok.resolve().placement("mod").arrangement == ""


def test_a_cell_declared_without_arrangements_places_as_it_did():
    plain = Board(stamped_geometry(), edge_margin=0.0, keep_going=True)
    plain.place(Cell("mod"), at=Location(40.0, 30.0))
    with_note = board()
    with_note.place(Cell("mod"), at=Location(40.0, 30.0))
    assert plain.resolve().placement("mod") == with_note.resolve().placement("mod")      # nothing pulls it: the default
```
(The last test pins the Phase 2 behaviour before the search exists; Task 3.2 keeps it true by the "unscored takes the default" rule.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_pin.py -v`
Expected: FAIL (`TypeError: place() got an unexpected keyword argument 'arrangements'`).

- [ ] **Step 3: Implement**

`PlaceIntent` (after `budget`): `arrangements: tuple = field(default=(), metadata={"omit_default": True})   # arrangements=: the arrangement ids a cell may take, in the order tried; () every one it offers`.

`place()`: signature gains `arrangements=None` (after `budget`; add it to `raw`'s keyword set only through the normal path, not `raw`). After the `drops` validation (`:2936`):

```python
        if arrangements is None:
            ids = ()
        elif isinstance(arrangements, str):
            ids = (arrangements,)
        else:
            ids = tuple(arrangements)
        if ids and (kind != "cell" or not all(isinstance(a, str) for a in ids)):
            raise TypeError("%s: arrangements= selects among a cell's arrangements, ids as text; a %s has none" % (key, kind))
```
and pass `arrangements=ids` in the `PlaceIntent(...)` call (`:3171-3182`). New methods (before `_scan_faces`, `:9298`):

```python
    def _offered(self, item) -> tuple:
        """The ids a cell offers besides its own layout; none while `place.arrangements` is false."""
        if not self.settings.place_arrangements or not isinstance(item, CellGeom):
            return ()
        return item.offered()

    def _arrangement_ids(self, i: PlaceIntent) -> list:
        """The arrangements a search of `i` tries, "" standing for the default: the ones `arrangements=` names in its order, else the
        default then everything the cell offers in the module's order. A part, a block and a cell that offers none have [""]."""
        if i.kind != "cell" or getattr(i.item, "arrangement", ""):
            return [""]                                 # a part, a block, or a cell already standing in one arrangement
        if i.arrangements:
            return ["" if a == "default" else a for a in i.arrangements]
        return [""] + list(self._offered(i.item))

    def _arranged(self, i: PlaceIntent, ident: str) -> PlaceIntent:
        """`i` with its cell standing as arrangement `ident` ("" the default)."""
        return i if not ident else dataclasses.replace(i, item=i.item.arranged(ident))

    def _gate(self, occ, i: PlaceIntent, plan: Plan) -> tuple:
        """(the intent to settle, None), or (i, the unplaced step) when `arrangements=` names an id the cell does not offer. A cell that
        is to take one arrangement is settled as that arrangement."""
        if i.kind != "cell" or getattr(i.item, "arrangement", ""):
            return i, None                              # a settle that runs again with the item already arranged
        ids = self._arrangement_ids(i)
        offered = ("default",) + self._offered(i.item)
        missing = [a for a in i.arrangements if a not in offered]
        if missing:
            plan.findings.append(self._finding(C.ARRANGEMENT_MISSING, {"item": i.key, "asked": list(i.arrangements),
                                                                       "offered": list(offered)}, "warning"))
            return i, self._step(i, None, 0.0, unplaced=[{"form": "arrangement_missing", "asked": list(i.arrangements),
                                                          "offered": list(offered)}])
        return (self._arranged(i, ids[0]) if len(ids) == 1 else i), None
```
`_settle` (after the block branch, `:9125`): 

```python
        i, gone = self._gate(occ, i, plan)
        if gone is not None:
            return gone
```
`_step` (`:7120`), before building the `Step`:

```python
        arranged = getattr(i.item, "arrangement", "")
        if placement is not None and arranged and placement.arrangement != arranged:
            placement = dataclasses.replace(placement, arrangement=arranged)
```
`step_text.py`: `unplaced_text` must read the new refusal form `arrangement_missing`: add to its reason renderer (`refusals`-style records: check `step_text.unplaced_text` at its definition and add `if r.get("form") == "arrangement_missing": return "arrangements= names %s; the cell offers %s" % (...)`).
`runner.py:753-756`: the placements dict gains `**({"arrangement": s.placement.arrangement} if s.placement.arrangement else {})`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_pin.py tests/test_cell_pin.py tests/test_at.py tests/test_step_text.py tests/test_row.py -q`
Expected: PASS.

- [ ] **Step 5: Bench and commit**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out` (every case `same`).

```bash
git add src/placemat/layout.py src/placemat/step_text.py src/placemat/runner.py tests/test_arrangement_pin.py
{ echo "Arrangements: arrangements= lays a cell in one proven arrangement, or says which it offers"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 2.5: The writer arranges a stamped cell before it moves it

**Files:**
- Modify: `src/placemat/kicad/arrange.py` (add `arrange_cell`)
- Modify: `src/placemat/kicad/write.py` - `apply_plan` (`:928-971`: the thinned pre-loop and the cell branch), `_draw_keepouts` (`:349-404`: extract the per-keepout zone into `rule_area(board, k, stack)`), `_drop_stamped_notes` (`:989-1001`; already knows the prefix from Task 1.9)
- Modify: `src/placemat/layout.py` - `_thin_drops` (`:1362-1405`: extract `_thin_cell_vias`), `_resolve_once` (set `occ.thin_arranged`; after a cell's commit in `place_one` record `plan.thinned` for an arranged cell, `:6838-6850`)
- Test: `tests/test_arrangement_write.py` (KiCad)

**Interfaces:**
- Consumes: `kicad_cell_board`, `Arrangement.members/ops/rule_areas`, `write._place_footprint/_move_cell/_thin_cell/_draw_track/_draw_via/_draw_pour/_draw_zone/_draw_text`, `Occupancy.arranged_gone`.
- Produces: `kicad.arrange.arrange_cell(board, group, cell: CellGeom, ident: str) -> CellGeom` (poses each member by the delta from the stamped place, deletes the group's own copper (tracks, vias, copper polygons, zones and rule areas, and drawn texts) with `group.RemoveItem(item)` then `board.Delete(item)`, draws the arrangement's ops and keepouts into the group, and returns `cell.arranged(ident)` for `_move_cell`); `write.rule_area(board, k, stack) -> ZONE`; `Board._thin_cell_vias(i, vias, planes) -> tuple[list, list]` ((points taken out, the step's per-field notes)); `plan.thinned[cell]` for an arranged cell holds the drops thinned from the arranged copper.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_write.py
import pytest

from placemat import arrangement_note as N
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import Cell, Face, Location
from tests.arrangement_support import east_doc, kicad_cell_board
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def staged(tmp_path, cells=(("mod", (30.0, 10.0)),)):
    texts = N.encode(east_doc(), 4000)
    return kicad_cell_board(tmp_path / "layout.kicad_pcb", cells, notes={c: texts for c, _ in cells})


def written(pcb, plan, cell):
    """Each member of `cell` as the board holds it, against where the search's committed geometry put it."""
    after = read_board(pcb)
    out = []
    for fp in after.cell(cell).members:
        ref = fp.ref
        want = plan.occupancy.items[ref].reference
        out.append((fp.inst, fp.location, want.location, fp.rotation % 360.0, want.rotation % 360.0, fp.face, want.face))
    return out


def assert_as_judged(rows):
    for inst, at, want, rot, wrot, face, wface in rows:
        assert abs(at.x - want.x) < 1e-3 and abs(at.y - want.y) < 1e-3, inst
        assert abs(((rot - wrot + 180.0) % 360.0) - 180.0) < 1e-3 and face == wface, inst


def place(pcb, **kw):
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    for cell, args in kw.items():
        b.place(Cell(cell), **args)
    return b


@pytest.mark.parametrize("rotation, face", [(0, Face.FRONT), (90, Face.FRONT), (0, Face.BACK), (270, Face.BACK)])
def test_an_arranged_cell_turned_or_flipped_is_written_where_the_search_judged_it(tmp_path, rotation, face):
    """Review focus 3."""
    pcb = staged(tmp_path)
    b = place(pcb, mod=dict(at=Location(40.0, 30.0), rotation=rotation, face=face, arrangements="c_in.east"))
    plan = b.resolve()
    apply_plan(pcb, plan)
    assert_as_judged(written(pcb, plan, "mod"))


def test_the_group_is_intact_after_the_arrangement_deletes_its_copper(tmp_path):
    """The bindings check CLAUDE.md asks for: delete from a group with RemoveItem then Delete, never Remove."""
    import pcbnew
    pcb = staged(tmp_path)
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east")).resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    group = next(g for g in board.Groups() if g.GetName() == "mod")
    items = list(group.GetItems())
    assert items and not any(type(i).__name__ == "SwigPyObject" for i in items)
    assert [i.GetPosition() for i in items if isinstance(i, pcbnew.FOOTPRINT)]
    assert [i.GetStart() for i in board.GetTracks()]


def test_the_arrangements_copper_replaces_the_stamped_copper_and_the_note_is_dropped(tmp_path):
    import pcbnew
    pcb = staged(tmp_path)
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east")).resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    assert [t.GetNetname() for t in board.GetTracks()] == ["mod.VIN"]
    assert not [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(N.ARRANGEMENT_PREFIX)]


def test_two_stamps_of_one_module_choose_and_are_written_independently(tmp_path):
    """Review focus 1: cell A in c_in.east, cell B in the default; nets map per cell."""
    pcb = staged(tmp_path, (("mod_a", (30.0, 10.0)), ("mod_b", (30.0, 40.0))))
    b = place(pcb, mod_a=dict(at=Location(20.0, 15.0), arrangements="c_in.east"),
              mod_b=dict(at=Location(60.0, 45.0), arrangements="default"))
    plan = b.resolve()
    assert plan.placement("mod_a").arrangement == "c_in.east" and plan.placement("mod_b").arrangement == ""
    apply_plan(pcb, plan)
    assert_as_judged(written(pcb, plan, "mod_a") + written(pcb, plan, "mod_b"))
    import pcbnew
    nets = sorted(t.GetNetname() for t in pcbnew.LoadBoard(str(pcb)).GetTracks())
    assert nets == ["mod_a.VIN", "mod_b.GND"]                  # A's copper is its arrangement's, in A's nets; B keeps the copper it was stamped with


def test_a_cell_placed_in_its_default_drops_its_notes_and_keeps_its_copper(tmp_path):
    import pcbnew
    pcb = staged(tmp_path)
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="default")).resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    assert not [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(N.ARRANGEMENT_PREFIX)]
    assert [t.GetNetname() for t in board.GetTracks()] == ["mod.GND"]                 # the stamped copper, which kicad_cell_board draws


def test_a_board_with_no_arranged_cell_is_written_as_before(tmp_path):
    pcb = staged(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    other = kicad_cell_board(plain / "layout.kicad_pcb", (("mod", (30.0, 10.0)),))
    for p in (pcb, other):
        apply_plan(p, place(p, mod=dict(at=Location(40.0, 30.0))).resolve())
    import pcbnew
    live = lambda p: sorted((f.GetReference(), f.GetPosition().x, f.GetPosition().y) for f in pcbnew.LoadBoard(str(p)).GetFootprints())
    assert live(pcb) == live(other)
```
(`kicad_cell_board` draws one stamped track in each cell's group: a `PCB_TRACK` of net `<cell>.GND` from `(0.0, 4.0)` to `(2.0, 4.0)` in the fragment's frame, so "the stamped copper replaced" is visible: with the arrangement the board holds only the note's `mod.VIN` track, in the default only this `mod.GND` one. Add it to the helper in Task 2.2 and expect `["mod.GND"]` in the default-cell test above.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_write.py -x -q`
Expected: FAIL (the arranged cell is written at default poses: `assert_as_judged` fails on `c_in`).

- [ ] **Step 3: Implement**

`write.py` extract from `_draw_keepouts` (the body of its `for k in plan.keepouts.values():`, `:384-403`):

```python
def rule_area(board, k, stack):
    """A KiCad rule area for keepout `k`: layers, the flags its excludes ask for, its outline and its zone name; added to the board."""
    z = pcbnew.ZONE(board)
    ... the existing statements from `z = pcbnew.ZONE(board)` through `board.Add(z)` ...
    return z
```
and the loop becomes `for k in plan.keepouts.values(): rule_area(board, k, stack)`.

`kicad/arrange.py` (append):

```python
from ..board_geometry import CellGeom
from ..placement import Placement
from ..copper import Pour, Text, Track, Via, Zone
from .write import (_draw_pour, _draw_text, _draw_track, _draw_via, _draw_zone, _kiid, _place_footprint, nm, rule_area)
from ..layout import PlacedKeepout
from ..values import CopperLayer


def _own_items(group) -> list:
    """What a stamped cell's group holds that is its module's own drawing: tracks and vias, copper polygons, zones (rule areas too) and
    drawn text. Footprints and nested groups are not."""
    out = []
    for it in group.GetItems():
        if isinstance(it, (pcbnew.PCB_TRACK, pcbnew.ZONE, pcbnew.PCB_TEXT)):
            out.append(it)
        elif isinstance(it, pcbnew.PCB_SHAPE) and it.GetLayerSet().CuStack():
            out.append(it)
    return out


def arrange_cell(board, group, cell: CellGeom, ident: str) -> CellGeom:
    """Put a stamped cell's group in arrangement `ident` before it is moved: each member to the arrangement's place, the module's own
    copper and rule areas replaced by the arrangement's. Items leave the group with RemoveItem and are deleted with board.Delete, never
    board.Remove (CLAUDE.md: Remove hands the item to its Python wrapper, and on a large board that has broken pcbnew's bindings)."""
    arranged = cell.arranged(ident)
    arr = next(a for a in cell.arrangements if a.id == ident)
    by_ref = {fp.GetReference(): fp for fp in group.GetItems() if isinstance(fp, pcbnew.FOOTPRINT)}
    for mp in arr.members:
        _place_footprint(by_ref[mp.ref], mp.default, mp.pose)
    gone = _own_items(group)                    # all found before any is deleted: a deleted item's wrapper is dead
    for it in gone:
        group.RemoveItem(it)
        board.Delete(it)
    before = {_kiid(x) for x in list(board.GetTracks()) + list(board.GetDrawings()) + list(board.Zones())}
    for op in arr.ops:
        if isinstance(op, Track):
            _draw_track(board, op)
        elif isinstance(op, Via):
            _draw_via(board, op)
        elif isinstance(op, Pour):
            _draw_pour(board, op)
        elif isinstance(op, Zone):
            _draw_zone(board, op)
        elif isinstance(op, Text):
            _draw_text(board, op)
    stack = tuple(CopperLayer.of(board.GetLayerName(l)) for l in board.GetEnabledLayers().CuStack())
    for ra in arr.rule_areas:
        k = PlacedKeepout(ra.name, ra.polygon, None, 0.0, tuple(sorted(ra.excludes)), tuple(sorted(ra.layers, key=lambda l: l.value)),
                          ra.allow, frozenset(), "", None, frozenset(), frozenset())
        rule_area(board, k, stack)
    for x in list(board.GetTracks()) + list(board.GetDrawings()) + list(board.Zones()):
        if _kiid(x) not in before:
            group.AddItem(x)
    return arranged
```
`apply_plan` (`:944-955`): the thinned pre-loop skips arranged cells and the cell branch arranges:

```python
    arranged = {s.item for s in plan.steps if s.placement is not None and s.placement.arrangement and s.kind == "cell"}
    for name, gone in sorted(plan.thinned.items()):
        if name not in arranged:
            _thin_cell(board, groups[name], gone)
    for step in plan.steps:
        ...
        elif isinstance(item, CellGeom):
            if step.placement.arrangement:
                from .arrange import arrange_cell
                item = arrange_cell(board, groups[item.name], item, step.placement.arrangement)
                if item.name in plan.thinned:
                    _thin_cell(board, groups[item.name], plan.thinned[item.name])
            _move_cell(board, item, step.placement, groups)
```
(`arrange.py` imports `write`, so `write` imports `arrange` lazily inside the function.)

`layout.py` `_thin_drops` (`:1362`): extract the inner computation (from `fields, gone, said = {}, [], []` to the `said.append(...)` loop end) into

```python
    def _thin_cell_vias(self, i, vias: list, planes: set) -> tuple:
        """(the (x, y) of each via of cell `i`'s plane fields that `drops=` takes out, the notes of what each field kept) of the cell's
        via shapes `vias`."""
        ... the existing body, `i.item.members` as before ...
        return gone, said
```
and `_thin_drops` calls it with `vias = [s for s in occ.copper if s.owner == cell and ...]`. In `_resolve_once` after `thinned = self._thin_drops(occ)` (`:6532`):

```python
        planes = {c.net for c in self._copper if c.key.split(" ")[0] == "plane"}

        def thin_arranged(cell, shapes):
            i = next((x for x in self._placements() if getattr(x, "item", None) is not None and getattr(x.item, "name", "") == cell.name), None)
            if i is None or getattr(i, "drops", Drops.ALL) is Drops.ALL:
                return shapes, []
            vias = [s for s in shapes if s.kind == "through" and s.net in planes]
            gone, _ = self._thin_cell_vias(i, vias, planes)
            def at(s):
                return any(abs(s.box.center.x - g.x) < 1e-6 and abs(s.box.center.y - g.y) < 1e-6 for g in gone)
            return [s for s in shapes if not (s.kind in ("through", "hole") and at(s))], [(g.x, g.y) for g in gone]
        occ.thin_arranged = thin_arranged
```
In `place_one` after `occ.commit(obj.item, step.placement)` for a cell (`:6840-6846`): `if obj.kind == "cell" and step.placement.arrangement: gone = occ.arranged_gone.get((obj.item.name, step.placement.arrangement)); if gone: plan.thinned[obj.item.name] = gone`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_write.py tests/test_write_roundtrip.py tests/test_cell_drops.py tests/test_written_groups.py tests/test_vias_give_way_kicad.py -q`
Expected: PASS (the `needs_breakout` ones skip when the ecosystem board is absent; run them where it is: `MNB_ECOSYSTEM=... `).

- [ ] **Step 5: Commit**

```bash
git add src/placemat/kicad/arrange.py src/placemat/kicad/write.py src/placemat/layout.py tests/test_arrangement_write.py tests/arrangement_support.py
git commit -m "Arrangements: the writer arranges a stamped cell, deleting its own copper from the group with Delete, before it moves it"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 2.6: Skill's board-side bullet and `arrangements=` in api.md

**Files:**
- Modify: `skills/placemat/SKILL.md` (the "Arrangements" subsection from Task 1.10: one bullet), `skills/placemat/references/api.md` ("Arrangements" under Placement: `arrangements=`, the ids, `arrangement.missing`, `arrangement.stale`, the settings `place.arrangements` and `score.arrangement`; the `placements[cell]["arrangement"]` field)
- Test: `tests/test_arrangement_declarations.py` (extend `test_the_skill_and_api_document_the_forms_and_the_report`)

- [ ] **Step 1: Write the failing test**

```python
def test_the_skill_names_the_board_side():
    assert "arrangements=" in SKILL and "does not edit a module's default" in SKILL
    assert "arrangements=" in API and "arrangement.missing" in API and "arrangement.stale" in API
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py::test_the_skill_names_the_board_side -v`
Expected: FAIL.

- [ ] **Step 3: Write the docs**

SKILL.md bullet (after "Reading the report"): `- **On the board side.** arrangements= on a cell's place() pins or restricts the arrangements the cell may take (one id pins it; several restrict the search, in order; "default" holds the module's own layout), and freeze writes it. The agent does not edit a module's default to hold a choice the lock can hold.` api.md: `arrangements=` paragraph with the three cases, the missing finding, and the stale finding with its reasons.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py tests/test_describe.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/placemat/SKILL.md skills/placemat/references/api.md tests/test_arrangement_declarations.py
git commit -m "Arrangements: arrangements= in the skill and api.md"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 2.7: Phase 2 gate

- [ ] **Step 1: Bench** - `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`; expected every case `same` (no corpus module has notes).
- [ ] **Step 2: Default suite** - `.venv/bin/python -m pytest -n 2`; expected PASS.
- [ ] **Step 3: Real-module fixture** - add the two helpers to `tests/arrangement_support.py`, then `tests/test_arrangement_real_module.py` (KiCad).

```python
def stamp_fragment_as_cell(fragment_pcb, out_pcb, cell, offset):
    """What `pcb layout` does with a module fragment: its parts, copper, rule areas and notes become one group `cell` on a board, the
    instance paths and nets prefixed by the cell's name, the group moved by `offset`. The project and rules files are copied beside it."""
    import pathlib
    import shutil
    import pcbnew
    fragment_pcb, out_pcb = pathlib.Path(fragment_pcb), pathlib.Path(out_pcb)
    board = pcbnew.LoadBoard(str(fragment_pcb))
    group = pcbnew.PCB_GROUP(board)
    group.SetName(cell)
    board.Add(group)
    for code in range(board.GetNetCount()):
        net = board.FindNet(code)
        if net is not None and net.GetNetname():
            net.SetNetname("%s.%s" % (cell, net.GetNetname()))
    for fp in list(board.GetFootprints()):
        try:
            path = fp.GetFieldText("Path")
        except KeyError:
            path = ""
        if path:
            fp.GetFieldByName("Path").SetText("%s.%s" % (cell, path))
        else:
            fp.SetReference("%s.%s" % (cell, fp.GetReference()))
        group.AddItem(fp)
    for item in list(board.GetTracks()) + list(board.GetDrawings()) + list(board.Zones()):
        group.AddItem(item)
    group.Move(pcbnew.VECTOR2I(pcbnew.FromMM(offset[0]), pcbnew.FromMM(offset[1])))
    board.Save(str(out_pcb))
    for ext in (".kicad_pro", ".kicad_dru"):
        if fragment_pcb.with_suffix(ext).exists():
            shutil.copy(fragment_pcb.with_suffix(ext), out_pcb.with_suffix(ext))
    return out_pcb


def synthetic_notes_for(pcb) -> dict:
    """Write a note into every cell of the board at `pcb` that has two or more members: the arrangement `turn` leaves every member where it
    is and turns the smallest one half way round about its own origin (the stamped frame is taken as the fragment's, offset 0). Returns
    {cell: "turn"} for the cells that got one."""
    import pcbnew
    from placemat import arrangement_note as N
    from placemat.kicad.read import read_board
    from placemat.placement import Placement
    from placemat.values import Face
    geometry = read_board(pcb)
    board = pcbnew.LoadBoard(str(pcb))
    groups = {g.GetName(): g for g in board.Groups()}
    done = {}
    for name, cell in sorted(geometry.cells.items()):
        prefix = name + "."
        members = [fp for fp in cell.members if fp.inst.startswith(prefix)]
        if len(cell.members) < 2 or len(members) != len(cell.members) or name not in groups:
            continue
        smallest = min(members, key=lambda fp: (fp.body_box.area, fp.inst))
        rows = []
        for fp in members:
            was = Placement(fp.location, fp.rotation, fp.face)
            now = Placement(fp.location, (fp.rotation + 180.0) % 360.0, fp.face) if fp is smallest else was
            rows.append((fp.inst[len(prefix):], now, was))
        doc = N.document("turn", {"turn": "half"}, rows, [], [], order=1)
        for text in N.encode(doc, 4000):
            t = pcbnew.PCB_TEXT(board)
            t.SetText(text)
            t.SetLayer(pcbnew.Cmts_User)
            board.Add(t)
            groups[name].AddItem(t)
        done[name] = "turn"
    board.Save(str(pcb))
    return done
```

```python
# tests/test_arrangement_real_module.py
"""A fixture module run with alternatives, stamped by a board, and written with one of its arrangements: the arrangement offered
passes the module's real DRC, the board run places the cell, and the module run and the board run agree on what was written."""
import json

from placemat import arrangement_note as N
from tests import real_modules
from tests.arrangement_support import stamp_fragment_as_cell
from tests.conftest import needs_kicad
from tests.test_arrangement_run import with_alternatives

pytestmark = needs_kicad


def poses(geometry, member_filter):
    return {fp.inst: (fp.location, fp.rotation % 360.0, fp.face) for fp in geometry.footprints if member_filter(fp)}


def test_an_offered_arrangement_is_what_the_board_writes(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    from placemat.layout import Board
    from placemat.values import Cell, Location
    result, drc, frag = real_modules.run(tmp_path / "module", "usb5v", edit=with_alternatives)
    rec = json.loads((result.run_dir / "run.json").read_text())
    offered = [a["id"] for a in rec["arrangements"][1:] if a["offered"]]
    assert offered
    arr = read_board(result.run_dir / "arrangements" / offered[0] / "layout.kicad_pcb")        # the module run's own board of it
    assert not [v for v in json.loads((result.run_dir / "arrangements" / offered[0] / "drc.json").read_text()).get("violations", [])
                if v.get("severity") == "error"]
    stamped = stamp_fragment_as_cell(frag, tmp_path / "stamped.kicad_pcb", "mod", (40.0, 20.0))
    g = read_board(stamped)
    assert g.cell("mod").offered() == tuple(offered) and g.cell("mod").arrangement_problems == ()
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=140, height=120)
    b.place(Cell("mod"), at=Location(70.0, 60.0), arrangements=offered[0])
    plan = b.resolve()
    assert plan.step("mod").placement is not None and plan.placement("mod").arrangement == offered[0]
    apply_plan(stamped, plan)
    after = poses(read_board(stamped), lambda fp: fp.cell == "mod")
    want = poses(arr, lambda fp: fp.cell is None)
    from placemat.kicad.drc import run_drc
    mine = next(a for a in rec["arrangements"] if a["id"] == offered[0])["metrics"]["drc"] or 0
    assert sum(run_drc(stamped, tmp_path / "stamped-drc.json", frame_only=True).real.values()) <= mine      # no worse than the module run's own
    assert {k.split(".", 1)[1] for k in after} == set(want)
    first = sorted(want)[0]
    here = after["mod." + first][0]
    for inst, (loc, rot, face) in want.items():                                     # the placement is a translation: relative places agree
        wloc, wrot, wface = after["mod." + inst]
        assert (rot, face) == (wrot, wface), inst
        assert abs((wloc.x - here.x) - (loc.x - want[first][0].x)) < 2e-3 and abs((wloc.y - here.y) - (loc.y - want[first][0].y)) < 2e-3, inst

```
Run (under the real-board lock): `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_arrangement_real_module.py -q`; expected PASS.

- [ ] **Step 4: Real-board check for the group deletion** - on the whole-board fixture (a six-layer board of cells and loose parts, `fixtures/fairing/core/generated/layout.kicad_pcb`), under the lock, with the copy removed afterwards:

```bash
SCRATCH=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad
flock $SCRATCH/realboard.lock .venv/bin/python - <<'EOF'
import pathlib, shutil, tempfile
import pcbnew
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import Cell
from tests.arrangement_support import synthetic_notes_for

work = pathlib.Path(tempfile.mkdtemp(dir="/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad"))
try:
    for f in pathlib.Path("fixtures/fairing/core/generated").iterdir():
        shutil.copy(f, work / f.name)
    pcb = work / "layout.kicad_pcb"
    cells = synthetic_notes_for(pcb)
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    for name in cells:
        b.place(Cell(name), arrangements=cells[name])
    apply_plan(pcb, b.resolve())
    board = pcbnew.LoadBoard(str(pcb))
    for grp in board.Groups():
        items = list(grp.GetItems())
        assert not any(type(i).__name__ == "SwigPyObject" for i in items), grp.GetName()
        [i.GetPosition() for i in items if hasattr(i, "GetPosition")]
    print("groups intact:", len(list(board.Groups())), "arranged cells:", len(cells))
finally:
    shutil.rmtree(work, ignore_errors=True)
EOF
```
Expected: prints `groups intact: N arranged cells: M` with M > 0 and no assertion error (the CLAUDE.md failure shows as `SwigPyObject` items or an `AttributeError` on `GetPosition`). The copy is removed by the `finally`. (The cells are placed searched here, so `arrangements=` pins each to `turn`; the board's own `edge_margin` and outline are not needed for the write check.)

- [ ] **Step 5: Commit** the test and the helpers:

```bash
git add tests/test_arrangement_real_module.py tests/arrangement_support.py
git commit -m "Arrangements: a fixture module's offered arrangement is stamped, placed and written, and the group deletion is checked on the whole-board fixture"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

# Phase 3: the search

### Task 3.1: Extract the scan of one standing of an item (no behaviour change)

**Files:**
- Modify: `src/placemat/layout.py` - `_settle` (`:9122-9296`): the block from `# riders refuse candidates after they are scored` (`:9198`) through the `self._scan_faces(...)` call (`:9229-9233`) moves into `_scan_one`; new `_Tried` dataclass next to `_Redo` (`:9850`)
- Test: none new (a pure extraction); the characterisation is the existing suites and the bench

**Interfaces:**
- Consumes: the locals of `_settle` at `:9198`: `i, occ, plan, placed, targets, push_sources, hint, band, bt, within, solved, wide_push, wide_tangent, look, clr`.
- Produces: `@dataclass _Tried(j: PlaceIntent, hint: Placement, radius: float, result: ScanResult | None, face_note: dict | None, ahead: object, score: object, hopeless: dict | None = None)`; `Board._scan_one(occ, j, plan, placed, *, targets, push_sources, hint, band, bt, within, reseed, wide_push, wide_tangent, look, clr, floor=None, cost=0.0) -> _Tried` (`floor`: the best total so far and `cost` what this standing adds, so the scorer prunes what cannot beat `floor - cost`; both unused until Task 3.2).

- [ ] **Step 1: Record the baseline**

Run: `.venv/bin/python -m pytest -n 2 tests/test_scan*.py tests/test_either_face.py tests/test_emitter_lookahead.py tests/test_riders*.py tests/test_bearing_search.py tests/test_step_budget.py tests/test_lock.py tests/test_explore_pick.py -q` and `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`
Expected: PASS and every bench case `same` (the baseline for this task).

- [ ] **Step 2: Move the block**

In `_settle`, replace `:9198-9233` with:

```python
        reseed = targets if i.near is None and solved is None else None
        tried = self._scan_one(occ, i, plan, placed, targets=targets, push_sources=push_sources, hint=hint, band=band, bt=bt,
                               within=within, reseed=reseed, wide_push=wide_push, wide_tangent=wide_tangent, look=look, clr=clr)
        if tried.hopeless:
            from . import suggest_facts
            plan.findings.append(self._finding(C.UNPLACED_POCKET, dict(suggest_facts.unplaced_pocket(self, occ, plan, i),
                                                                       **tried.hopeless)))
            return self._step(i, None, 0.0, unplaced=[{"form": "pocket", **tried.hopeless}])
        result, face_note, ahead, score, radius = tried.result, tried.face_note, tried.ahead, tried.score, tried.radius
```
and below it the unchanged code from `from . import timecap` (`:9234`). Add the method (before `_scan_faces`) with the moved statements, verbatim:

```python
    def _scan_one(self, occ, j, plan, placed, *, targets, push_sources, hint, band, bt, within, reseed, wide_push, wide_tangent,
                  look, clr, floor=None, cost: float = 0.0) -> "_Tried":
        """One standing of the item scanned (the item as its script says it): the riders', exposure and look-ahead tests, the lane
        pricer, the scorer, the radius, the pocket check, and the front-then-back scan."""
        # riders refuse candidates after they are scored: a refused one must not prune the rest
        accept = self._accept(j)
        exposed = self._exposure_accept(occ, j, push_sources)
        if exposed is not None:
            accept = exposed if accept is None else (lambda c, a=accept, b=exposed: a(c) or b(c))
        ahead = self._lookahead(occ, j, placed) if look else None
        if ahead is not None:
            accept = ahead if accept is None else (lambda c, a=accept, b=ahead: a(c) or b(c))
        lanes = self._lane_pricer(occ, plan, j)
        score = self._scorer(j.item, occ, targets, prune=self._pick(j) is None and accept is None,
                             pushes=push_sources, lanes=lanes) if targets or push_sources or lanes else None
        if score is not None and floor is not None and hasattr(score, "best"):
            score.best[0] = min(score.best[0], floor - cost)
        # A seeded item lands on the pads that pull it; it must be free to step at least its own size clear of them.
        body = occ._geometry(j.item).body
        if band is not None:
            radius = band[2] + hint.location.distance(band[0])      # every point of the band is within it
        elif j.near is not None:
            radius = j.radius
        elif wide_push or wide_tangent:
            # A push's own disc can swallow whatever a link or the global solve seeded, so the
            # widening applies whatever else set the hint - not only when a push seeded it too.
            radius = math.hypot(self._outline.width, self._outline.height)
        else:
            radius = max(j.radius, body.width, body.height)
        hopeless = None if bt is not None or band is not None else self._no_pocket_note(occ, j)
        if hopeless:
            return _Tried(j, hint, radius, None, None, ahead, score, hopeless)
        if self._on_begin is not None:
            self._phase(Stage.SCAN, face="either" if j.either else j.face.value,
                        hint=[round(hint.location.x, 3), round(hint.location.y, 3)], radius=round(radius, 2))
        result, face_note = self._scan_faces(occ, j, hint, radius, clr, score, accept, reseed=reseed, turns_at=bt, within=within,
                                             turns_on=lambda f: self._spot_turns(occ, j, placed, band, f))
        return _Tried(j, hint, radius, result, face_note, ahead, score)
```
and next to `_Redo`:

```python
@dataclass
class _Tried:
    """One standing of an item scanned (`Board._scan_one`)."""
    j: PlaceIntent
    hint: Placement
    radius: float
    result: ScanResult | None
    face_note: dict | None
    ahead: object
    score: object
    hopeless: dict | None = None
```

- [ ] **Step 3: Run to verify nothing moved**

Run the commands of Step 1 again.
Expected: the same PASS and every bench case `same`. A difference is a transcription slip in the moved block: diff it against `git show HEAD:src/placemat/layout.py`.

- [ ] **Step 4: Commit**

```bash
git add src/placemat/layout.py
{ echo "Extract the scan of one standing of an item from _settle"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 3.2: The search over (arrangement, face) pairs

**Files:**
- Modify: `src/placemat/layout.py` - `_settle` (use `_scan_arrangements`, `:9195-9296`); new `_scan_arrangements`, `_Scanned`; `__init__` (`_arr_unreached`); `_time_limited` (`:7108-7118`); `_arrangement_ids`/`_gate` (Task 2.4) skip an item that is already arranged
- Modify: `src/placemat/board_geometry.py` - `CellGeom.arranged` returns itself when `ident == self.arrangement`
- Modify: `src/placemat/finding_text.py` (`time.step_limit` renderer, `:686-691`, optional `arrangements` fact)
- Test: `tests/test_arrangement_search.py`

**Interfaces:**
- Consumes: `_scan_one`/`_Tried` (Task 3.1), `_arrangement_ids/_arranged` (Task 2.4), `Settings.score_arrangement`, `Settings.score_back_face`, `SearchBudget` (`placer.py:25`), `timecap.active().gave_up`.
- Produces: `@dataclass _Scanned(won: _Tried | None, tried: list, result: ScanResult, face_note: dict | None, note: dict | None, reasons: list)`; `Board._scan_arrangements(occ, i, plan, placed, ids, **kw) -> _Scanned` (the default and the front first; a non-default arrangement is taken only when `result.score + score.arrangement` is strictly below the best so far, or when nothing earlier has a legal spot; an unscored search takes the default when it has a legal spot and scans the others only when it has none; `kw` are `_scan_one`'s keywords but `j`); the step's `arrangement` note (`{"kind": "arrangement", "id", "score", "cost", "default_score", "tried": [...]}`, or `default_blame` when the default had no legal spot) whenever more than one arrangement was scanned or a non-default one was taken; `time.step_limit` facts gain `arrangements: [ids not reached]`.

- [ ] **Step 1: Write the failing tests**

`stamped_geometry(partner=, obstacle=)` and `OBSTACLE` are in `tests/arrangement_support.py` (Task 2.1): `partner=(x, y)` is a placed part on the cell's VIN net that pulls its VIN pads, `OBSTACLE` fills the default's `u1` and not the arrangement's `c_in` for a cell whose box centre is on (40, 30).

```python
# tests/test_arrangement_search.py
import dataclasses

import pytest

from placemat import arrangement_note as N
from placemat.arranged_geometry import attach
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Cell, Location, Near, Part
from tests.arrangement_support import OBSTACLE, east_doc, stamped_geometry, with_arrangement

NEAR = dict(radius=8.0, step=0.5)


def board(partner=None, settings=None, doc=None, obstacle=None, geometry=None):
    g = geometry or with_arrangement(stamped_geometry(partner=partner, obstacle=obstacle), doc)
    b = Board(g, edge_margin=0.0, keep_going=True, settings=settings or Settings())
    b.rect(width=80, height=60)
    if obstacle is not None:
        b.place(Part("obst"), at=Location(obstacle[0], obstacle[1]))
    if partner is not None:
        b.place(Part("r8"), at=Location(*partner))
    return b


def run(partner, settings=None, doc=None, **place):
    b = board(partner, settings, doc)
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), **place)
    return b.resolve()


def test_with_links_that_favour_the_east_side_the_cell_takes_the_arrangement():
    plan = run((60.0, 30.0))
    assert plan.placement("mod").arrangement == "c_in.east"
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert note["id"] == "c_in.east" and note["score"] < note["default_score"]
    assert [t["id"] for t in note["tried"]] == ["default", "c_in.east"] and all(t["legal"] for t in note["tried"])


def test_with_the_default_at_least_as_good_the_cell_stays_default():
    assert run((18.0, 30.0)).placement("mod").arrangement == ""             # the pull is west: the module's own layout has VIN west


def test_with_no_pulls_the_cell_takes_the_default_and_scans_nothing_else():
    plan = run(None)
    assert plan.placement("mod").arrangement == ""
    assert not [n for n in plan.step("mod").notes if n["kind"] == "arrangement"]       # one scan: nothing to tell


def test_the_cost_flips_a_close_call():
    big = dataclasses.replace(Settings(), score_arrangement=1000.0)
    assert run((60.0, 30.0), big).placement("mod").arrangement == ""


def test_a_tie_goes_to_the_arrangement_declared_first():
    g = stamped_geometry(partner=(60.0, 30.0))
    texts = N.encode(east_doc("c_in.b", 2), 4000) + N.encode(east_doc("c_in.a", 1), 4000)
    g = dataclasses.replace(g, cells={**g.cells, "mod": attach(g.cells["mod"], texts, frozenset(g.nets), g.layers)})
    b = board(partner=(60.0, 30.0), geometry=g)
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    assert b.resolve().placement("mod").arrangement == "c_in.a"             # two that score alike: the one the module declared first


def test_the_first_arrangement_with_a_legal_spot_is_taken_when_the_default_has_none():
    b = board(obstacle=OBSTACLE)
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), radius=0.0, step=0.5))
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east"
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert note["tried"][0] == {"id": "default", "score": None, "legal": False} and "default_blame" in note
    assert next(t for t in note["tried"] if t["id"] == "c_in.east")["legal"] is True


def test_a_pinned_arrangement_restricts_the_search_and_several_try_in_order():
    for ids, want in ((("default",), ""), (("c_in.east", "default"), "c_in.east"), (("default", "c_in.east"), "c_in.east")):
        assert run((60.0, 30.0), arrangements=ids).placement("mod").arrangement == want


def test_the_native_and_the_python_sweep_choose_the_same_arrangement(monkeypatch):
    from placemat import placer
    from placemat.geometry import native_status
    if not native_status().in_use:
        pytest.skip("the native module is not in use")
    a = run((60.0, 30.0)).placement("mod")
    monkeypatch.setattr(placer, "NATIVE_SWEEP", False)
    assert run((60.0, 30.0)).placement("mod") == a


def test_each_arrangement_has_its_own_scan_budget_and_a_cut_is_reported_if_any_scan_was_cut():
    tiny = dataclasses.replace(Settings(), place_step_budget=40)
    plan = run((60.0, 30.0), tiny)
    (f,) = [f for f in plan.findings if f.cause == "setup.step_budget"]
    assert f.facts["limit"] == 40 and f.facts["item"] == "mod"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_search.py -x -q`
Expected: FAIL (`assert plan.placement("mod").arrangement == "c_in.east"` gets `""`: the search only scans the default).

- [ ] **Step 3: Implement**

`board_geometry.CellGeom.arranged`: first line `if ident == self.arrangement or (not self.arrangement and ident == "default"): return self`. `_gate` (Task 2.4) first line after the kind test: `if getattr(i.item, "arrangement", ""): return i, None` and `_arrangement_ids`: `if i.kind != "cell" or getattr(i.item, "arrangement", ""): return [""]`.

`Board.__init__`: `self._arr_unreached: dict = {}       # item key -> the arrangements a step out of time did not reach`.

In `_settle`, replace the call added in Task 3.1 by:

```python
        ids = self._arrangement_ids(i)
        scanned = self._scan_arrangements(occ, i, plan, placed, ids, targets=targets, push_sources=push_sources, hint=hint,
                                          band=band, bt=bt, within=within, reseed=reseed, wide_push=wide_push,
                                          wide_tangent=wide_tangent, look=look, clr=clr)
        tried = scanned.tried[0]                        # the default's, for what follows a search that found nothing
        if tried.hopeless and scanned.won is None and all(t.hopeless for t in scanned.tried):
            from . import suggest_facts
            plan.findings.append(self._finding(C.UNPLACED_POCKET, dict(suggest_facts.unplaced_pocket(self, occ, plan, i),
                                                                       **tried.hopeless)))
            return self._step(i, None, 0.0, unplaced=[{"form": "pocket", **tried.hopeless}])
        result, face_note, ahead, score, radius = scanned.result, scanned.face_note, tried.ahead, tried.score, tried.radius
        won = scanned.won.j if scanned.won is not None else i
```
Later in `_settle`: every `self._step(i, ...)` of the success path (`:9283-9295`) becomes `self._step(won, ...)` and the notes get `scanned.note` appended after `face_note`:

```python
        notes = list(seeded)
        if face_note:
            notes.append(face_note)
        if scanned.note:
            notes.append(scanned.note)
```
and the failing `plan.findings.append(self._finding(C.UNPLACED_SEARCH, facts))` step's `unplaced=` list is `scanned.reasons` (below) instead of `[w.to_json() for w in result.reasons.values()]`.

```python
@dataclass
class _Scanned:
    """The scans of every arrangement of an item, and which stands: its Tried, the ScanResult and face note of the winner (all the
    arrangements' refusals merged when none has a legal spot), the arrangement note, and the refusals as records tagged with the
    arrangement they came from."""
    won: "_Tried | None"
    tried: list
    result: ScanResult
    face_note: dict | None
    note: dict | None
    reasons: list
```
```python
    def _scan_arrangements(self, occ, i, plan, placed, ids, **kw) -> "_Scanned":
        """Scan item `i` in each arrangement of `ids` ("" the default, first), each an ordinary scan of the arranged cell (its own
        geometry, sweeper, scorer, seed, lanes), the front before the back. A non-default arrangement costs `score.arrangement` more and
        is taken only when its best score plus that is strictly below the best so far, or when nothing earlier has a legal spot; the best
        so far, less the cost, is the next scorer's pruning floor. An unscored search (no links, pushes or lanes to price) takes the
        default when it has a legal spot and scans the others only when it has none. An explore variant draws from the candidates of
        every arrangement's scan together, each score with its cost. The step's budget is counted per scan; the step's time limit
        stops between scans."""
        from . import timecap
        clock = timecap.active()
        cost = self.settings.score_arrangement
        tried, best, any_cut = [], None, None
        for k, ident in enumerate(ids):
            if k and clock is not None and clock.gave_up:
                self._arr_unreached[i.key] = [a or "default" for a in ids[k:]]
                break
            j = self._arranged(i, ident)
            budget = occ.step_budget
            if k and budget is not None:
                any_cut = any_cut or budget.cut
                budget.judged = budget.lattice = budget.covered = 0
                budget.cut = False
            hint = kw["hint"]
            if k and kw["reseed"] is not None and kw["band"] is None and kw["bt"] is None \
                    and not (kw["wide_push"] or kw["wide_tangent"]):
                hint = self._seed_hint(j.item, occ, kw["targets"], i.rotation, i.face)      # laid from the arranged item's pads
            extra = cost if ident else 0.0
            t = self._scan_one(occ, j, plan, placed, **{**kw, "hint": hint}, floor=best[0] if best else None, cost=extra)
            tried.append((ident, t))
            r = t.result
            if r is None or r.chosen is None:
                continue
            if t.score is None and k == 0:
                best = (0.0, ident, t)                           # unscored: the default has a spot, nothing else is scanned
                break
            total = r.score + extra + (self.settings.score_back_face if r.chosen.face is Face.BACK and i.either else 0.0)
            if best is None or total < best[0]:
                best = (total, ident, t)
            if t.score is None:
                break
        if budget_cut := (occ.step_budget.cut if occ.step_budget is not None else False):
            any_cut = any_cut or budget_cut
        return self._chosen_scan(occ, i, tried, best, cost, any_cut)
```
The explore draw is added in Task 3.7. `_chosen_scan`:

```python
    def _chosen_scan(self, occ, i, tried, best, cost, any_cut) -> "_Scanned":
        from collections import Counter
        results = [(a, t.result) for a, t in tried if t.result is not None]
        reasons = [dict(w.to_json(), **({"arrangement": a} if a else {})) for a, r in results for w in r.reasons.values()]
        if best is None:
            merged = ScanResult(None, tried[0][1].hint, sum(r.tried for _, r in results),
                                sum((r.rejected for _, r in results), Counter()),
                                {k: v for _, r in reversed(results) for k, v in r.reasons.items()},
                                sum((r.blockers for _, r in results), Counter()),
                                cut=next((r.cut for _, r in results if r.cut), None))
            return _Scanned(None, [t for _, t in tried], merged, None, None, reasons)
        total, ident, won = best
        won.result.cut = won.result.cut or any_cut_facts(occ, any_cut, results)
        note = None
        if len(tried) > 1 or ident:
            rows = [{"id": a or "default", "score": None if t.result is None or t.result.chosen is None
                     else round(t.result.score + (cost if a else 0.0), 3),
                     "legal": t.result is not None and t.result.chosen is not None} for a, t in tried]
            default = tried[0][1].result
            if default is not None and default.chosen is not None:
                note = step_text.record("arrangement", id=ident or "default", score=round(won.result.score, 3),
                                        cost=cost if ident else 0.0, default_score=round(default.score, 3), tried=rows)
            else:
                note = step_text.record("arrangement", id=ident or "default",
                                        default_blame=blame.blame_of(default) if default is not None else None, tried=rows)
        return _Scanned(won, [t for _, t in tried], won.result, won.face_note, note, reasons)
```
with the module-level helper

```python
def any_cut_facts(occ, any_cut, results):
    """The measurement of the first scan that the step's budget cut, when any scan of the step was cut; else None."""
    return next((r.cut for _, r in results if r.cut), None) if any_cut else None
```

 `time.step_limit`: `_time_limited` (`:7108`) adds `unreached = self._arr_unreached.pop(step.item, [])` and `if unreached: facts["arrangements"] = unreached`; the renderer appends `"; arrangements not reached: " + ", ".join(...)` when the fact is present (`FACTS_V` for the cause is unchanged: an optional field).

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_search.py tests/test_arrangement_pin.py tests/test_scan*.py tests/test_either_face.py tests/test_step_budget.py tests/test_time*.py tests/test_finding_text.py -q`
Expected: PASS.

- [ ] **Step 5: Bench and commit**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`
Expected: every case `same`.

```bash
git add src/placemat/layout.py src/placemat/board_geometry.py src/placemat/finding_text.py tests/arrangement_support.py tests/test_arrangement_search.py
{ echo "Arrangements: the search scans (arrangement, face) pairs, the default and the front first"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 3.3: The forms with one freedom, and a point with turns, search arrangements

**Files:**
- Modify: `src/placemat/layout.py` - `_settle` dispatch (`:9141-9166`), new `_first_legal`; `_settle_turns_on_point` (`:9421-9470`)
- Test: `tests/test_arrangement_search.py` (append)

**Interfaces:**
- Consumes: `_arrangement_ids/_arranged/_gate`, `_firm_placement`, `_slide` (`:8112`), the scorer.
- Produces: `Board._first_legal(occ, i, plan, settle_one) -> Step` (for `OnEdge(edge)`, a line, a run, a rim, a ring or a spoke: the form is unscored, so the default is taken when it has a legal spot, else the first arrangement that has; findings of an arrangement that failed are dropped, the default's kept when none succeeds); `_settle_turns_on_point` lays each (arrangement, turn) at the point, keeps the legal ones, scores each with its arrangement's scorer, and takes the lowest `score + score.arrangement`, a tie to the earlier arrangement then the turn nearest `rotation=`.

- [ ] **Step 1: Write the failing tests** (append)

```python
from placemat.layout import Step
from placemat.placement import Placement
from placemat.values import Face


def settled_board():
    b = board(partner=None)
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    plan = b.resolve()
    return b, plan, next(x for x in b._placements() if x.key == "mod")


def fake(placements, plan=None):
    """A settle_one that places by the arrangement it is given, {"": placement or None, "c_in.east": ...}; one that does not place says why."""
    def settle_one(j):
        from placemat.findings import Finding, FindingCause as C
        p = placements[getattr(j.item, "arrangement", "")]
        if p is None and plan is not None:
            plan.findings.append(Finding(C.UNPLACED_SLIDE, {"item": "mod", "where": {"form": "edge", "edge": "south"},
                                                            "counts": [["edge", 1]], "riders": []}))
        return Step("mod", "cell", None, p)
    return settle_one


def test_a_slide_takes_the_default_when_it_fits_and_the_first_arrangement_that_does_when_it_does_not():
    b, plan, i = settled_board()
    here = Placement(Location(10.0, 10.0))
    taken = b._first_legal(plan.occupancy, i, plan, fake({"": here, "c_in.east": here}, plan))
    assert taken.placement == here and not [n for n in taken.notes if n["kind"] == "arrangement"]
    n = len(plan.findings)
    east = Placement(Location(20.0, 10.0), 0.0, Face.FRONT, "c_in.east")
    step = b._first_legal(plan.occupancy, i, plan, fake({"": None, "c_in.east": east}, plan))
    assert step.placement == east and len(plan.findings) == n                 # the failed default left no finding behind
    assert [t["id"] for t in next(x for x in step.notes if x["kind"] == "arrangement")["tried"]] == ["default", "c_in.east"]


def test_when_none_has_a_spot_the_defaults_findings_stand():
    b, plan, i = settled_board()
    n = len(plan.findings)
    step = b._first_legal(plan.occupancy, i, plan, fake({"": None, "c_in.east": None}, plan))
    assert step.placement is None and [f.cause for f in plan.findings[n:]] == ["unplaced.slide"]


def test_a_point_with_a_turn_to_search_scores_each_arrangement_at_the_point():
    b = board(partner=(60.0, 30.0))
    b.place(Cell("mod"), at=Location(45.0, 30.0), rotations=(0,))
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east" and abs(plan.box("mod").center.x - 45.0) < 1e-3
    west = board(partner=(18.0, 30.0))
    west.place(Cell("mod"), at=Location(45.0, 30.0), rotations=(0,))
    assert west.resolve().placement("mod").arrangement == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_search.py -k "slide or none_has_a_spot or point_with_a_turn" -q`
Expected: FAIL (`AttributeError: 'Board' object has no attribute '_first_legal'`, then the point test: `_settle_turns_on_point` lays the default only).

- [ ] **Step 3: Implement**

`_first_legal`:

```python
    def _first_legal(self, occ, i, plan, settle_one) -> Step:
        """A form that is not scored (a slide along an edge, a line, a run, a rim, a ring, a spoke) takes the default arrangement when it has
        a legal spot and scans the others, in declared order, only when it has none. What an arrangement that failed said is dropped when
        another stands; when none does the default's findings stand."""
        ids = self._arrangement_ids(i)
        if len(ids) == 1:
            return settle_one(self._arranged(i, ids[0]))
        n = len(plan.findings)
        first, first_findings, rows = None, [], []
        for ident in ids:
            step = settle_one(self._arranged(i, ident))
            rows.append({"id": ident or "default", "score": None, "legal": step.placement is not None})
            if step.placement is not None:
                if ident or len(rows) > 1:
                    step.notes = step.notes + (step_text.record("arrangement", id=ident or "default", tried=rows),)
                return step
            if first is None:
                first, first_findings = step, list(plan.findings[n:])
            del plan.findings[n:]
        plan.findings.extend(first_findings)
        first.notes = first.notes + (step_text.record("arrangement", id="default", tried=rows),)
        return first
```
`_settle` dispatch: replace the seven `return self._settle_along_*(...)` lines (`:9145-9165`) so each goes through `self._first_legal(occ, i, plan, lambda j: self._settle_along_run(occ, j, plan, clr))` etc. (the `_settle_turns_on_point` call stays as it is, `:9141`, and handles arrangements itself). `_settle_turns_on_point` (`:9421`): replace the head with

```python
        turns = sorted({float(r) % 360.0 for r in i.rotations})
        ids = self._arrangement_ids(i)
        laid, scored = {}, {}
        for k, ident in enumerate(ids):
            j = self._arranged(i, ident)
            for rot in turns:
                laid[(k, rot)] = (ident, j) + self._firm_placement(occ, plan, dataclasses.replace(j, rotation=rot))
        geoms = {k: occ._geometry(j.item) for k, (ident, j) in {(k, laid[(k, turns[0])][:2]) for k in range(len(ids))}}
```
and keep the loop body: for each `(k, rot), (ident, j, p, chose)` judge `occ.legal_giving_way(j.item, p, clr, others=others, by_corners=True)` with `others` computed once over the union region of every laid candidate (`occ.obstacles(geom, region)` for the first arrangement's geom is not enough: compute `others` per arrangement `k`), score with `score_k = self._scorer(j.item, occ, targets, prune=..., pushes=push_sources, lanes=self._lane_pricer(occ, plan, j))` built once per `k`, add `cost = self.settings.score_arrangement if ident else 0.0`, and collect `found.append((total, k, away, rot, p, chose, ident, j))`; `min(found, key=lambda f: f[:4])` (total, then arrangement order, then the turn nearest `rotation=`, then the angle) picks the winner; the `turned` note gets `arrangement=ident or None` and the step is `self._step(j, p, 0.0, notes)`. With one arrangement the key's second element is constant, so the choice is the existing one.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_search.py tests/test_bearing_search.py tests/test_edge*.py tests/test_row*.py tests/test_polar*.py tests/test_cutouts.py -q`
Expected: PASS.

- [ ] **Step 5: Bench and commit**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out` (every case `same`).

```bash
git add src/placemat/layout.py tests/test_arrangement_search.py
{ echo "Arrangements: slides take the first arrangement with a legal spot and a point with turns scores each arrangement"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 3.4: Riders, escape lanes, a push and a carried via are judged per arrangement; cleanup and the solve leave arranged cells alone

**Files:**
- Modify: none expected (a failing case here is a missing `j` where `i` was used in `_scan_one`); the audit is a test per interaction
- Test: `tests/test_arrangement_search.py` (append)

**Interfaces:** consumes `_scan_arrangements`; produces nothing new.

- [ ] **Step 1: Write the tests** (append; each is one case from the spec's Testing list)

```python
from placemat.values import Beside, Edge, PadRef


def test_a_rider_is_judged_against_the_arranged_cell_at_each_arrangements_scan():
    """A part placed Beside the cell rides it: it is judged with the cell at each candidate of each arrangement's scan."""
    b = board(partner=(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    b.place(Part("r9"), at=Beside(Cell("mod"), Edge.EAST))
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east" and plan.step("r9").placement is not None
    assert plan.box("r9").left >= plan.box("mod").right - 1e-6


def test_the_escape_lane_pricer_is_asked_of_each_arranged_item(monkeypatch):
    """Lanes reserved by a cell's own members come with the arranged copper: the pricer is built for the arranged item at each scan."""
    seen = []
    real = Board._lane_pricer

    def spy(self, occ, plan, i):
        seen.append(getattr(i.item, "arrangement", ""))
        return real(self, occ, plan, i)
    monkeypatch.setattr(Board, "_lane_pricer", spy)
    run((60.0, 30.0))
    assert {"", "c_in.east"} <= set(seen)


def test_a_push_is_measured_from_the_arranged_members_pad():
    b = board(partner=(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    push = b.push(PadRef(Part("mod.c_in"), 1), from_=Part("r8"), falloff=2, reference=(10.0, 1.0), limit=2.0)
    plan = b.resolve()
    pad = plan.occupancy.pad_location("C1", "1")
    assert push.achieved_mm is not None and abs(push.achieved_mm - pad.distance(Location(60.0, 30.0))) < 0.05


def test_cleanup_leaves_a_placed_cell_and_its_arrangement_alone():
    """Cleanup moves loose parts only (`_cleanup_movable` keeps cells out), so an arranged cell keeps its placement and its arrangement."""
    b = board(partner=(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    plan = b.resolve()
    assert "mod" not in b._cleanup_movable(plan) and plan.placement("mod").arrangement == "c_in.east"


def test_the_global_solve_reads_the_default_geometry_and_an_arranged_cell_still_resolves():
    solving = dataclasses.replace(Settings(), solve_enabled=True)
    assert run((60.0, 30.0), solving).placement("mod") is not None


def test_a_carried_via_of_an_arrangement_is_in_the_search_and_the_board():
    from placemat.copper import Via
    plan = run((60.0, 30.0), doc=east_doc(ops=[Via("VIN", Location(9.0, 3.0), 0.3, 0.6)]))
    assert plan.placement("mod").arrangement == "c_in.east"
    assert [s for s in plan.occupancy.copper if s.owner == "mod" and s.kind == "through"]
```

- [ ] **Step 2: Run to see what fails**

Run: `.venv/bin/python -m pytest tests/test_arrangement_search.py -q`
Expected: each failing case points at a place in `_settle`/`_scan_one` that still reads the default `i` after the arrangement loop: fix by using `j`.

- [ ] **Step 3: Fix** the places found (known candidates: `_push_notes(occ, plan, i, ...)` in `_settle`'s success path takes the winner `won`, not `i`; `plan.turns[obj.key] = dict(self._turn_of(occ, obj, step.placement, placed)...` in `place_one` needs no change because the placement carries the arrangement).

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_search.py tests/test_emitter*.py tests/test_annotated_push.py tests/test_cleanup*.py tests/test_solve*.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py tests/test_arrangement_search.py
git commit -m "Arrangements: riders, pushes and carried vias are judged per arrangement; cleanup and the solve leave arranged cells alone"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 3.5: Replay and reuse carry the arrangement

**Files:**
- Modify: `src/placemat/reuse.py` - `VERSION` (`:20`) 4 -> 5, `context_key` (`:100-118`: the arrangements digest, only when a cell has any)
- Modify: `src/placemat/layout.py` - `_recording_commits` (`:9473-9487`), `_apply_commits` (`:7186-7191`)
- Test: `tests/test_arrangement_replay.py`

**Interfaces:**
- Consumes: `Placement.arrangement` in `placement_to_json/from_json` (Task 2.3).
- Produces: `reuse.arrangements_digest(geometry) -> str` (`""` when no cell has an arrangement; else a digest of each cell's arrangement ids, member poses and ops); `commits` entries `[["cell", name], placement]` for a default cell and `[["cell", name, arrangement], placement]` otherwise; `reuse.VERSION == 5`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_replay.py
import json

from placemat import reuse
from placemat.layout import Board
from placemat.values import Cell, Location, Near, Part
from tests.arrangement_support import stamped_geometry, with_arrangement
from tests.test_arrangement_search import NEAR


def board(g):
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.reuse_extra = "t"
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    return b


def test_the_second_run_replays_an_arranged_step():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    first = board(g).resolve()
    record = json.loads(json.dumps(first.reuse))
    assert first.placement("mod").arrangement == "c_in.east"
    second = board(g).resolve(reuse=record)
    assert second.reuse["reused"] == len(second.reuse["steps"]) and second.placement("mod") == first.placement("mod")
    entry = next(s for s in record["steps"] if s.get("commits") and s["commits"][0][0][1] == "mod")
    assert entry["commits"][0][0] == ["cell", "mod", "c_in.east"] and entry["commits"][0][1][-1] == "c_in.east"


def test_a_default_commit_is_recorded_as_before_and_an_old_record_reads_as_the_default():
    g = with_arrangement(stamped_geometry(partner=(18.0, 30.0)))
    first = board(g).resolve()
    entry = next(s for s in first.reuse["steps"] if s.get("commits") and s["commits"][0][0][1] == "mod")
    assert entry["commits"][0][0] == ["cell", "mod"] and len(entry["commits"][0][1]) == 4
    assert reuse.placement_from_json([1.0, 2.0, 0.0, "front"]).arrangement == ""


def test_the_context_digest_follows_the_cells_arrangements_only_when_it_has_any():
    plain = stamped_geometry()
    assert reuse.arrangements_digest(plain) == ""
    one, other = with_arrangement(), with_arrangement(doc=__import__("tests.arrangement_support", fromlist=["east_doc"]).east_doc("c_in.east", 1, []))
    assert reuse.arrangements_digest(one) != "" and reuse.arrangements_digest(one) != reuse.arrangements_digest(other)
    assert board(plain).resolve().reuse["context"] == board(stamped_geometry()).resolve().reuse["context"]


def test_a_record_of_another_version_replays_nothing():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    record = json.loads(json.dumps(board(g).resolve().reuse))
    record["version"] = 4
    assert board(g).resolve(reuse=record).reuse["reused"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_replay.py -q`
Expected: FAIL (`AttributeError: module 'placemat.reuse' has no attribute 'arrangements_digest'`).

- [ ] **Step 3: Implement**

`reuse.py`: `VERSION = 5   # ... 5 carries a cell's arrangement in a placement and in a commit`; 

```python
def arrangements_digest(g) -> str:
    """What the stamped cells' arrangements say, for the context: empty when no cell has any, so a board whose cells carry none digests as before."""
    rows = [(name, [(a.id, [(m.ref, m.pose) for m in a.members], a.ops, a.rule_areas) for a in cell.arrangements])
            for name, cell in sorted(g.cells.items()) if cell.arrangements]
    return canonical(rows) if rows else ""
```
and in `context_key` after the escapes lines: `arr = arrangements_digest(board.geometry); if arr: parts.append(arr)` (and `placement_settings` already covers `place.arrangements`).

`_recording_commits` (`:9480-9483`):

```python
    def commit(item, placement):
        key = ("cell", item.name) if isinstance(item, CellGeom) else ("fp", item.ref)
        if isinstance(item, CellGeom) and placement.arrangement:
            key = key + (placement.arrangement,)        # the arrangement beside the cell: a default cell records as it always did
        commits.append([key, _reuse.placement_to_json(placement)])
        return real(item, placement)
```
`_apply_commits`:

```python
        for key, placement in commits:
            kind, name = key[0], key[1]
            item = self.geometry.cells[name] if kind == "cell" else self.geometry.footprint(name)
            occ.commit(item, _reuse.placement_from_json(placement))     # a placement that names an arrangement commits the arranged cell
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_replay.py tests/test_reuse*.py tests/test_replay*.py tests/test_partial*.py -q`
Expected: PASS.

- [ ] **Step 5: Bench and commit**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out` (every case `same`).

```bash
git add src/placemat/reuse.py src/placemat/layout.py tests/test_arrangement_replay.py
{ echo "Arrangements: replay and reuse carry a cell's arrangement (reuse version 5)"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 3.6: Lock and freeze hold the arrangement

**Files:**
- Modify: `src/placemat/lock.py` - `LockEntry` (`:20-32`), `read` (`:40-50`), `write` (`:52-56`), `declaration_digest` (`:79-105`), `entry_from_turn` (`:117-127`), `placement_of` (`:129-149`), `entries` (`:151-166`)
- Modify: `src/placemat/layout.py` - `_lock_spot` (`:8470-8485`), `_settle_locked` (`:8487-8509`)
- Modify: `src/placemat/freeze.py` - `frozen_args` (`:106-135`), `why_text` (`:86-92`)
- Test: `tests/test_arrangement_lock.py`

**Interfaces:**
- Consumes: `Placement.arrangement`, `CellGeom.arranged/offered`.
- Produces: `LockEntry.arrangement: str = ""` (left out of the file when empty, `FORMAT` stays 1); `lock.declaration_digest(board, intent, ordered=True, arrangement="")` (adds the arranged cell's member places to the hash only when `arrangement` is not the default); `lock.placement_of` returns the entry's arrangement in the placement; a locked cell is laid in its arrangement first; an entry whose arrangement the module no longer offers, or whose arranged places changed (a changed digest), is released with the lock's released-entry note and an `arrangement.missing` finding (`{"item", "asked": [id], "offered": [...], "source": "lock"}`); `freeze.frozen_args` returns `"arrangements": repr(id)` when the turn's placement has one; `why_text` adds `arrangement <id>`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_lock.py
import dataclasses
import json

from placemat import lock as L
from placemat.freeze import edit_call, frozen_args, why_text
from placemat.layout import Board
from placemat.placement import Placement
from placemat.values import Cell, Face, Location, Near, Part
from tests.arrangement_support import east_doc, stamped_geometry, with_arrangement
from tests.test_arrangement_search import NEAR


def board(g):
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    return b


def test_an_entry_with_an_arrangement_round_trips_and_a_default_entry_writes_the_bytes_it_wrote(tmp_path):
    e = L.LockEntry("mod", None, None, (1.0, 2.0), 0.0, "front", "abc", 0, "r", "run", 1.5, "c_in.east")
    d = L.LockEntry("mod", None, None, (1.0, 2.0), 0.0, "front", "abc")
    path = tmp_path / "x.lock.json"
    L.write(path, [e])
    assert L.read(path)[0].arrangement == "c_in.east"
    L.write(path, [d])
    assert "arrangement" not in path.read_text() and L.read(path)[0].arrangement == ""


def test_the_declaration_digest_of_a_default_entry_is_unchanged_and_an_arranged_one_differs():
    b = board(with_arrangement(stamped_geometry(partner=(60.0, 30.0))))
    i = next(x for x in b._placements() if x.key == "mod")
    assert L.declaration_digest(b, i) == L.declaration_digest(b, i, arrangement="")
    assert L.declaration_digest(b, i, arrangement="c_in.east") != L.declaration_digest(b, i)


def test_an_accepted_entry_holds_the_arrangement_and_places_it_again():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = board(g)
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east"
    entries = L.entries(b, plan, ["mod"])
    assert entries[0].arrangement == "c_in.east"
    again = board(g).resolve(lock=entries)
    assert again.placement("mod") == plan.placement("mod") and again.step("mod").lock == "held"


def test_an_entry_whose_arrangement_the_module_no_longer_offers_is_released_with_a_finding():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = board(g)
    entries = L.entries(b, b.resolve(), ["mod"])
    gone = board(stamped_geometry(partner=(60.0, 30.0)))
    plan = gone.resolve(lock=entries)
    assert plan.step("mod").lock == "released" and plan.placement("mod").arrangement == ""
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.facts["asked"] == ["c_in.east"] and f.facts["source"] == "lock"


def test_freeze_writes_the_arrangement_into_the_call():
    turn = {"placement": Placement(Location(10.0, 20.0), 0.0, Face.FRONT, "c_in.east"), "anchor": None}
    b = board(with_arrangement(stamped_geometry(partner=(60.0, 30.0))))
    args = frozen_args(b, "mod", turn, False, why="'w'")
    assert args["arrangements"] == "'c_in.east'" and args["at"].startswith("Near(")
    entry = L.LockEntry("mod", None, None, (1.0, 2.0), 0.0, "front", "abc", 0, "", "run1", 41.2, "c_in.east")
    assert "arrangement c_in.east" in why_text("w", entry, "2026-10-04")
    src = 'board.place(Cell("mod"), at=Near(Location(1, 2)), why="w")\n'
    out = edit_call(src, 1, args)
    assert "arrangements='c_in.east'" in out or 'arrangements="c_in.east"' in out
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_lock.py -q`
Expected: FAIL (`TypeError: LockEntry.__init__() takes ... positional arguments`).

- [ ] **Step 3: Implement**

`lock.py`: `LockEntry` gains `arrangement: str = ""   # the cell's arrangement when it was accepted; "" the module's own layout`; `read` passes `e.get("arrangement", "")` as the last argument; `write`:

```python
def _doc(e) -> dict:
    d = asdict(e)
    if not d["arrangement"]:
        del d["arrangement"]              # an entry with none is written as it always was
    return d
```
(`doc = {"format": FORMAT, "entries": [_doc(e) for e in entries]}`). `declaration_digest(board, intent, ordered=True, arrangement="")`: after computing `shape` add

```python
    extra = []
    if arrangement:
        a = intent.item.arranged(arrangement)
        extra = [_reuse.canonical(sorted((fp.inst, round(p.location.x, 4), round(p.location.y, 4), round(p.rotation, 4),
                                          p.face.value) for fp in a.members for p in (dict(a.poses).get(fp.ref),) if p is not None))]
```
and `_reuse._sha("lock", canonical(said), links..., canonical(shape), *extra)`: with no `extra` the call is `_sha("lock", said, links, shape)` as before, so existing entries hold. `entry_from_turn` passes `arrangement=p.arrangement` to both `LockEntry(...)` constructions; `placement_of` adds `entry.arrangement` as the fourth `Placement` argument in both returns; `entries(...)` calls `declaration_digest(board, intent, arrangement=turn["placement"].arrangement)` and keeps `arrangement` through the `LockEntry(**{**asdict(e), ...})` rebuild.

`layout._lock_spot` (`:8470`): after the digest test:

```python
        if entry.arrangement and entry.arrangement not in self._offered(i.item):
            plan.findings.append(self._finding(C.ARRANGEMENT_MISSING, {"item": i.key, "asked": [entry.arrangement],
                                                                       "offered": ["default"] + list(self._offered(i.item)),
                                                                       "source": "lock"}, "warning"))
            self._lock_notes[i.key] = step_text.record("lock_released", reason={"form": "arrangement_gone", "id": entry.arrangement})
            return None, None
```
with the digest comparison made `arrangement=entry.arrangement` for both digests, and `_settle_locked` (`:8487`) using `j = self._arranged(i, entry.arrangement)` for the two `scan(...)` calls and `self._step(j, ...)`. `step_text` lock_released renderer: add the `arrangement_gone` reason (`"the module no longer offers arrangement %s"`).

`freeze.py`: `frozen_args` renamed `_frozen_core` and a new

```python
def frozen_args(board, key, turn, fixed: bool, entry=None, why: str = "") -> dict:
    out = _frozen_core(board, key, turn, fixed, entry, why)
    arrangement = turn["placement"].arrangement
    if arrangement:
        out["arrangements"] = repr(arrangement)            # the call's own keyword: the arrangement the lock held
    return out
```
and `why_text`: `if entry.arrangement: stamp += "; arrangement %s" % entry.arrangement`. In `freeze()` the trial resolve's `ensure_imports` is unchanged (a string keyword needs none).

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_lock.py tests/test_lock*.py tests/test_freeze*.py tests/test_explore_accept.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/lock.py src/placemat/layout.py src/placemat/freeze.py src/placemat/step_text.py tests/test_arrangement_lock.py
git commit -m "Arrangements: the lock and freeze hold a cell's arrangement"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 3.7: Explore draws arrangements

**Files:**
- Modify: `src/placemat/layout.py` - `_scan_arrangements` (the pool for a pick, Task 3.2)
- Modify: `src/placemat/explore.py` - the `moves` block (`:636-647`) into `_move_of`, and the line at `:811-813` that words a move
- Test: `tests/test_arrangement_explore.py`

**Interfaces:**
- Consumes: `Board._pick(i)` (`layout.py:8511`), `explore.draw`, `explore.Explore(seed, focus)`.
- Produces: with a pick, `_scan_arrangements` scans each arrangement with `pick=None` collecting its sorted legal candidates `(score, distance, rotation, placement)`, pools them with each score plus its cost (a fifth element: the arrangement id), calls the pick on the pool and takes the arrangement the draw landed in; `explore._move_of(key, was, now) -> dict | None` (`{"key", "mm", "rotation": [was, now]}` plus `"arrangement": [was, now]` when they differ; None for no move).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_explore.py
import dataclasses

from placemat import explore as E
from placemat.explore import Explore
from placemat.layout import Board
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Cell, Face, Location, Near, Part
from tests.arrangement_support import stamped_geometry, with_arrangement
from tests.test_arrangement_search import NEAR


def seeded(seed, g):
    s = dataclasses.replace(Settings(), explore_spot_slack=5.0)
    b = Board(g, edge_margin=0.0, keep_going=True, settings=s)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    return b.resolve(explore=Explore(seed, frozenset({"mod"}))).placement("mod").arrangement


def test_a_variant_draws_among_the_arrangements_within_the_slack():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    seen = {seeded(seed, g) for seed in range(1, 25)}
    assert seen == {"", "c_in.east"}


def test_the_plain_placement_is_still_the_best():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    plain = Board(g, edge_margin=0.0, keep_going=True)
    plain.rect(width=80, height=60)
    plain.place(Part("r8"), at=Location(60.0, 30.0))
    plain.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    assert plain.resolve().placement("mod").arrangement == "c_in.east"


def test_a_move_reports_the_arrangement_change():
    was = Placement(Location(1.0, 1.0), 0.0, Face.FRONT, "")
    now = Placement(Location(1.0, 1.0), 0.0, Face.FRONT, "c_in.east")
    assert E._move_of("mod", was, now) == {"key": "mod", "mm": 0.0, "rotation": [0.0, 0.0], "arrangement": ["", "c_in.east"]}
    assert E._move_of("mod", was, was) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_explore.py -q`
Expected: FAIL (`AttributeError: module 'placemat.explore' has no attribute '_move_of'`; the seeded draw only ever sees the default).

- [ ] **Step 3: Implement**

`explore.py`: move the body at `:636-647` into

```python
def _move_of(key, was, now) -> dict | None:
    """One focused item's move between the plain placement and the variant's, as the report holds it."""
    if was is None or now is None:
        if was == now:
            return None
        return {"key": key, "mm": None, "rotation": [getattr(was, "rotation", None), getattr(now, "rotation", None)]}
    d = was.location.distance(now.location)
    if d <= 1e-6 and was.rotation == now.rotation and was.arrangement == now.arrangement:
        return None
    out = {"key": key, "mm": round(d, 3), "rotation": [was.rotation, now.rotation]}
    if was.arrangement != now.arrangement:
        out["arrangement"] = [was.arrangement, now.arrangement]
    return out
```
and the loop becomes `m = _move_of(key, current.placement(key), best.placement(key)); if m: report["moves"].append(m)`; the move wording (`:811-813`) appends `", arrangement %s -> %s"` from `m["arrangement"]` (shown as `default` for `""`).

`Board.__init__`: `self._collect_into = None`. `_pick` (`layout.py:8511`) gains, after it has decided the item is focused:

```python
        if self._collect_into is not None:
            return lambda cands: (self._collect_into.extend(cands), cands[0])[1]     # a scan reports its sorted candidates and keeps its best
```
`_scan_arrangements` (Task 3.2) takes the real draw before collection is switched on and pools the candidates of every arrangement's scan, each score with its cost. Replace its loop and tail with:

```python
        draw = self._pick(i)                        # the explore variant's draw for a focused item, else None
        tried, best, any_cut, pool = [], None, None, []
        for k, ident in enumerate(ids):
            if k and clock is not None and clock.gave_up:
                self._arr_unreached[i.key] = [a or "default" for a in ids[k:]]
                break
            j = self._arranged(i, ident)
            budget = occ.step_budget
            if k and budget is not None:
                any_cut = any_cut or budget.cut
                budget.judged = budget.lattice = budget.covered = 0
                budget.cut = False
            hint = kw["hint"]
            if k and kw["reseed"] is not None and kw["band"] is None and kw["bt"] is None \
                    and not (kw["wide_push"] or kw["wide_tangent"]):
                hint = self._seed_hint(j.item, occ, kw["targets"], i.rotation, i.face)
            extra = cost if ident else 0.0
            self._collect_into = [] if draw is not None else None
            try:
                t = self._scan_one(occ, j, plan, placed, **{**kw, "hint": hint}, floor=best[0] if best else None, cost=extra)
            finally:
                got, self._collect_into = self._collect_into, None
            for c in got or ():
                pool.append((c[0] + extra, c[1], c[2], c[3], ident, t))
            tried.append((ident, t))
            r = t.result
            if r is None or r.chosen is None:
                continue
            if t.score is None and k == 0:
                best = (0.0, ident, t)
                break
            total = r.score + extra + (self.settings.score_back_face if r.chosen.face is Face.BACK and i.either else 0.0)
            if best is None or total < best[0]:
                best = (total, ident, t)
            if t.score is None:
                break
        if draw is not None and pool:
            pool.sort(key=lambda c: c[:3])
            drawn = draw(pool)                      # explore.draw over (score, distance, rotation, placement, arrangement, scan)
            ident, t = drawn[4], drawn[5]
            t.result.chosen, t.result.score = drawn[3], drawn[0] - (cost if ident else 0.0)
            best = (drawn[0], ident, t)
        if budget_cut := (occ.step_budget.cut if occ.step_budget is not None else False):
            any_cut = any_cut or budget_cut
        return self._chosen_scan(occ, i, tried, best, cost, any_cut)
```
(`explore.draw` weighs by `c[0]` and rank only, so the extra elements ride along.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_explore.py tests/test_explore*.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/layout.py src/placemat/explore.py tests/test_arrangement_explore.py
git commit -m "Arrangements: explore draws among the arrangements within the slack and reports the change"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 3.8: Bench set for arrangements

**Files:**
- Modify: `fixtures/bench.py` - `main` (`:319-345`: `--arrangements`), new `bench_arrangements()` after `bench_checks` (`:236`)
- Modify: `tests/arrangement_support.py` (`synthetic_notes_for`, from Task 2.7)
- Test: `tests/test_arrangement_bench.py` (a smoke test that the function runs on a tiny board)

**Interfaces:**
- Consumes: `bench_board`'s construction (`:206-233`), `tests.real_modules.run`, `synthetic_notes_for(pcb) -> dict[cell, id]`.
- Produces: `bench.bench_arrangements() -> dict` with `module` (`{"seconds_1": s, "seconds_k": s, "k": n}`), `board` (`{"off_s", "on_s", "off_score", "on_score", "cells"}`), `firm` (`{"off_s", "on_s"}`), printed by `--arrangements`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_arrangement_bench.py
import importlib.util
import pathlib

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad
BENCH = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "bench.py"


def load():
    spec = importlib.util.spec_from_file_location("bench", BENCH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_arrangement_cases_are_in_the_bench():
    m = load()
    assert hasattr(m, "bench_arrangements") and "--arrangements" in BENCH.read_text()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_bench.py -q`
Expected: FAIL (`assert hasattr(m, "bench_arrangements")`).

- [ ] **Step 3: Implement** (in `bench.py`)

```python
def bench_arrangements() -> dict:
    """The cost of arrangements, in three cases the corpus cannot show (it declares none): a module run with k arrangements against one,
    the whole-board fixture resolved with synthetic arrangement notes in every cell with and without them, and the same board with
    every cell firm. Seconds and run score; budgets: a module run at most about k times the default's, a board's resolve at most 25
    percent longer than the same board without."""
    import shutil, tempfile
    sys.path.insert(0, str(ROOT.parent))
    from placemat import score
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.settings import Settings
    from placemat.values import Cell, Centre, Part
    from tests import real_modules
    from tests.arrangement_support import synthetic_notes_for
    from tests.test_arrangement_run import with_alternatives
    out = {}
    for label, edit in (("one", None), ("k", with_alternatives)):
        with tempfile.TemporaryDirectory() as d:
            t0 = time.perf_counter()
            result, _, _ = real_modules.run(pathlib.Path(d), "usb5v", edit=edit)
            out["module_%s_s" % label] = round(time.perf_counter() - t0, 1)
            out["module_k"] = max(out.get("module_k", 1), len(json.loads((result.run_dir / "run.json").read_text()).get("arrangements", [1])))
    work = pathlib.Path(tempfile.mkdtemp())
    try:
        for f in (BOARD_FIXTURE / "generated").iterdir():
            shutil.copy(f, work / f.name)
        cells = synthetic_notes_for(work / "layout.kicad_pcb")
        g = read_board(work / "layout.kicad_pcb")
        written = read_board(BOARD_FIXTURE / "layout" / "layout.kicad_pcb")

        def resolve(on: bool, firm: bool):
            import dataclasses
            b = Board(g, keep_going=True, settings=dataclasses.replace(Settings(), place_arrangements=on))
            b.outline(written.board_polygon[0], holes=written.board_polygon[1:])
            for name, cell in sorted(g.cells.items()):
                if cell.members:
                    c = cell.box.center
                    b.place(Cell(name), at=Centre(c.x, c.y, coordinates=True)) if firm else b.place(Cell(name))
            for fp in sorted(g.footprints, key=lambda f: f.inst):
                if fp.cell is None:
                    b.place(Part(fp.inst))
            t0 = time.perf_counter()
            plan = b.resolve()
            return time.perf_counter() - t0, score.total(score.plan_measures(b, plan), b.settings)
        for key, firm in (("board", False), ("firm", True)):
            off_s, off = resolve(False, firm)
            on_s, on = resolve(True, firm)
            out[key] = {"off_s": round(off_s, 1), "on_s": round(on_s, 1), "off_score": round(off, 1), "on_score": round(on, 1),
                        "cells": len(cells)}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out
```
and in `main`: `ap.add_argument("--arrangements", action="store_true", help="the cost of arrangements: a module run with k, the whole board and a board of firm cells with synthetic notes, timed with and without")`; `if a.arrangements: print(json.dumps(bench_arrangements(), indent=1)); return 0` before the `a.board or a.checks` branch. (`bench_board` is the existing function; this one does not replace it.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_bench.py -q` then, once, under the lock: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python fixtures/bench.py --arrangements`
Expected: the JSON prints; record it (Task 3.9).

- [ ] **Step 5: Commit**

```bash
git add fixtures/bench.py tests/arrangement_support.py tests/test_arrangement_bench.py
git commit -m "Arrangements: a bench set for the cost of arrangements (module run, whole board, firm cells)"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 3.9: Phase 3 gate

- [ ] **Step 1: Bench** - `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`; expected every case `same`.
- [ ] **Step 2: Timing against the budgets** - under the real-board lock: `.venv/bin/python fixtures/bench.py --arrangements`. Expected: `module_k_s` at most about `module_k` times `module_one_s`; `board.on_s` at most 1.25 times `board.off_s`; `firm.on_s` small beside `board.on_s`. Write the numbers under "Build notes" in the spec. If a budget is missed, the first measure is the coarse pass over every arrangement and the fine pass over the best `place.arrangement_refine` of them (a new setting, as a scored scan already does over spots): file it as a follow-up task in this plan and stop here; do not build it unmeasured.
- [ ] **Step 3: Default suite** - `.venv/bin/python -m pytest -n 2`; expected PASS.
- [ ] **Step 4: Real-module fixture** - `flock ... .venv/bin/python -m pytest tests/test_arrangement_real_module.py tests/test_arrangement_run.py -q`; expected PASS.
- [ ] **Step 5: Real-board check** - re-run the whole-board check of Task 2.7 Step 4 with the search on (no `arrangements=` pins: the search chooses), under the lock; expected: `groups intact` printed, every cell placed, copies removed.
- [ ] **Step 6: Commit the build notes** - `git add docs/superpowers/specs/2026-10-04-module-member-variants-design.md && git commit -m "Arrangements: build notes for phases 1 to 3 (note size, timings)"`.

---

# Phase 4: firm cells

### Task 4.1: A decided cell tries its arrangements at its spot

**Files:**
- Modify: `src/placemat/layout.py` - `_settle` decided branch (`:9128-9140`), new `_settle_firm_arranged` and `_firm_trials`; `suggest_facts.fixed_part` caller (`:9136-9137`)
- Modify: `src/placemat/finding_text.py` (the `fixed.part` renderer: optional `arrangements`)
- Test: `tests/test_arrangement_firm.py`

**Interfaces:**
- Consumes: `_arrangement_ids/_arranged/_gate` (Task 2.4), `_firm_placement`, `occ.legal_giving_way`, `_scorer`, `_lane_pricer`, `_targets`, `Settings.score_arrangement`.
- Produces: `@dataclass _Trial(ident: str, j: PlaceIntent, placement: Placement, chose: dict | None, why: Refusal | None, score: float | None)`; `Board._firm_trials(occ, plan, i, placed, clr, push_sources) -> list[_Trial]` (one per arrangement id, in order: the declaration laid for that arranged cell, judged for legality as a firm item is judged, each legal one scored once at that placement against what is placed); `Board._settle_firm_arranged(occ, i, plan, placed, clr, push_sources) -> Step` (the lowest `score + score.arrangement` wins, a tie keeps the earlier, so the default; none scored (no placed partner, push or lane) keeps the first legal; no legal arrangement is a firm collision as it is today: the default's placement and finding, `fixed.part` facts gaining `arrangements: [{"id", "why"}]` for the others); `fixed.part` step notes gain the same `arrangement` note as a searched step's.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_firm.py
import dataclasses

import pytest

from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Cell, Centre, Location, Near, Part
from tests.arrangement_support import OBSTACLE, east_doc, footprint, stamped_geometry, with_arrangement

AT = Location(40.0, 30.0)


def firm(partner=None, searched_partner=False, settings=None, ids=None, doc=None, obstacle=None):
    g = with_arrangement(stamped_geometry(partner=partner, obstacle=obstacle), doc)
    b = Board(g, edge_margin=0.0, keep_going=True, settings=settings or Settings())
    b.rect(width=80, height=60)
    if obstacle is not None:
        b.place(Part("obst"), at=Location(obstacle[0], obstacle[1]))
    if partner is not None:
        (b.place(Part("r8")) if searched_partner else b.place(Part("r8"), at=Location(*partner)))
    b.place(Cell("mod"), at=AT, **({"arrangements": ids} if ids else {}))
    return b.resolve()


def test_a_firm_cell_takes_the_arrangement_that_scores_lower_at_its_spot():
    plan = firm(partner=(60.0, 30.0))
    assert plan.placement("mod").arrangement == "c_in.east"
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert [(t["id"], t["legal"]) for t in note["tried"]] == [("default", True), ("c_in.east", True)]
    assert note["score"] < note["default_score"] and abs(plan.box("mod").center.x - 40.0) < 1e-3


def test_it_keeps_the_default_on_a_tie_and_when_its_partners_are_unplaced():
    assert firm(partner=None).placement("mod").arrangement == ""
    assert firm(partner=(60.0, 30.0), searched_partner=True).placement("mod").arrangement == ""
    assert firm(partner=(18.0, 30.0)).placement("mod").arrangement == ""
    big = dataclasses.replace(Settings(), score_arrangement=1000.0)
    assert firm(partner=(60.0, 30.0), settings=big).placement("mod").arrangement == ""


def test_the_only_legal_arrangement_is_taken_when_the_default_is_illegal_and_none_when_none_is():
    plan = firm(obstacle=OBSTACLE)
    assert plan.placement("mod").arrangement == "c_in.east"
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert note["tried"][0]["legal"] is False and "default_blame" in note
    held = firm(obstacle=OBSTACLE, ids=("default",))                      # pinned to the layout that collides: a firm collision as today
    (f,) = [f for f in held.findings if f.cause == "fixed.part"]
    assert f.facts["item"] == "mod" and held.placement("mod").arrangement == ""
    both = firm(obstacle=(40.0, 30.0, 12.0, 8.0))                          # a part over the whole cell: no arrangement is legal
    (g,) = [f for f in both.findings if f.cause == "fixed.part" and f.facts["item"] == "mod"]
    assert [a["id"] for a in g.facts["arrangements"]] == ["c_in.east"]    # the default's finding, the others' refusals under it


def test_arrangements_with_one_id_lays_that_one_and_several_limit_the_trial():
    assert firm(partner=(60.0, 30.0), ids="default").placement("mod").arrangement == ""
    assert firm(partner=(18.0, 30.0), ids="c_in.east").placement("mod").arrangement == "c_in.east"
    assert firm(partner=(60.0, 30.0), ids=("default", "c_in.east")).placement("mod").arrangement == "c_in.east"


def test_a_cell_that_offers_none_is_settled_exactly_as_before():
    plain = Board(stamped_geometry(partner=(60.0, 30.0)), edge_margin=0.0, keep_going=True)
    plain.rect(width=80, height=60)
    plain.place(Part("r8"), at=Location(60.0, 30.0))
    plain.place(Cell("mod"), at=AT)
    p = plain.resolve()
    assert p.placement("mod").arrangement == "" and not [n for n in p.step("mod").notes if n["kind"] == "arrangement"]


def test_a_part_placed_beside_the_cell_follows_the_arrangement_it_took():
    from placemat.values import Beside, Edge
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=AT)
    b.place(Part("r9"), at=Beside(Cell("mod"), Edge.EAST))
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east" and plan.box("r9").left >= plan.box("mod").right - 1e-6
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_firm.py -q`
Expected: FAIL (the cell stays default: `assert plan.placement("mod").arrangement == "c_in.east"`).

- [ ] **Step 3: Implement**

In `_settle`, the decided branch (`:9128`) becomes:

```python
        if i.freedom.decided:
            if i.kind == "cell" and len(self._arrangement_ids(i)) > 1:
                return self._settle_firm_arranged(occ, i, plan, placed, clr, push_sources)
            ... the existing body unchanged ...
```
```python
@dataclass
class _Trial:
    """One arrangement of a decided cell laid at its place: where, whether legal, and its score there."""
    ident: str
    j: PlaceIntent
    placement: Placement
    chose: dict | None
    why: object
    score: float | None
```
```python
    def _firm_trials(self, occ, plan, i, placed, clr, push_sources) -> list:
        """The decided cell laid in each arrangement it may take, in order: the declaration laid for the arranged cell (a point puts the
        arranged box's centre on it, a Beside stands the arranged cell against its reference, an edge puts its reach at the keep-in),
        each judged as a firm item is (courtyards, keepouts, the edge, carried vias allowed to give way) and each legal one scored once
        by the Scorer against what is placed now: links to placed pads, pushes, lanes. Partners not yet placed contribute nothing."""
        targets = self._targets(i.item, occ, placed)
        out = []
        for ident in self._arrangement_ids(i):
            j = self._arranged(i, ident)
            p, chose = self._firm_placement(occ, plan, j)
            why = occ.legal_giving_way(j.item, p, clr, past_edge=self._firm_past_edge(j), by_corners=True)[0]
            score = None
            if why is None:
                lanes = self._lane_pricer(occ, plan, j)
                if targets or push_sources or lanes:
                    score = self._scorer(j.item, occ, targets, prune=False, pushes=push_sources, lanes=lanes)(p)
            out.append(_Trial(ident, j, p, chose, why, score))
        return out

    def _settle_firm_arranged(self, occ, i, plan, placed, clr, push_sources) -> Step:
        cost = self.settings.score_arrangement
        trials = self._firm_trials(occ, plan, i, placed, clr, push_sources)
        legal = [t for t in trials if t.why is None]
        rows = [{"id": t.ident or "default", "legal": t.why is None,
                 "score": None if t.score is None else round(t.score + (cost if t.ident else 0.0), 3)} for t in trials]
        if not legal:                                       # a firm collision as it is today: the default's, with the others' refusals named
            from . import suggest_facts
            d = trials[0]
            facts = dict(suggest_facts.fixed_part(self, i), why=d.why.to_json(),
                         arrangements=[{"id": t.ident, "why": t.why.to_json()} for t in trials[1:]])
            plan.findings.append(self._finding(C.FIXED_PART, facts))
            self._labels_give_way(occ, plan, i.item, d.placement)
            return self._step(i, d.placement, 0.0, [x for x in (d.chose, step_text.record("refused", why=d.why.to_json())) if x]
                              + [step_text.record("arrangement", id="default", tried=rows)])
        best = legal[0]
        for t in legal[1:]:
            if t.score is not None and best.score is not None and t.score + (cost if t.ident else 0.0) < best.score + (cost if best.ident else 0.0):
                best = t
        self._arr_choice[i.key] = best.ident
        default = trials[0]
        if default.why is None and default.score is not None:
            note = step_text.record("arrangement", id=best.ident or "default", score=round(best.score, 3),
                                    cost=cost if best.ident else 0.0, default_score=round(default.score, 3), tried=rows)
        else:
            note = step_text.record("arrangement", id=best.ident or "default",
                                    default_blame=None if default.why is None else [default.why.to_json()], tried=rows)
        self._labels_give_way(occ, plan, best.j.item, best.placement)
        return self._step(best.j, best.placement, 0.0, [x for x in (best.chose, note) if x])
```
(`default_blame` here is the refusal record of the default's firm judgement; the searched step's is `blame.blame_of(result)`; `step_text._arrangement` renders either through `finding_text.blame_text`, which reads a list of blame entries: wrap the refusal as `[{"form": "kind", "count": 1, "label": ..., "owners": []}]` if `blame_text` rejects a bare refusal, or extend `_arrangement` to render a refusal record with `step_text._refusal`.) `Board.__init__`: `self._arr_choice: dict = {}`. The `fixed.part` renderer appends `"; other arrangements: " + "; ".join("%s: %s" % (a["id"], <refusal text>) ...)` when `arrangements` is present.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_firm.py tests/test_arrangement_search.py tests/test_at.py tests/test_beside*.py tests/test_cell_pin.py tests/test_row*.py tests/test_finding_text.py -q`
Expected: PASS.

- [ ] **Step 5: Bench and commit**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out` (every case `same`).

```bash
git add src/placemat/layout.py src/placemat/finding_text.py tests/test_arrangement_firm.py
{ echo "Arrangements: a decided cell tries its proven arrangements at its spot"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 4.2: The firm choice is carried between passes and must settle

**Files:**
- Modify: `src/placemat/layout.py` - `Board.__init__` (`_arr_prev`, `_arr_unsettled`), `_resolve` (`:6482-6500`), `_redo_check` (`:2613-2648`), `_resolve_once` firm-pass findings (`:6924-6927`), `_Redo` (`:9850-9855`)
- Modify: `src/placemat/finding_text.py` (`fixed.room_unsettled`: required fields `("passes",)`, `FACTS_V[C.FIXED_ROOM_UNSETTLED] = 2`, a variant with `item` and `arrangements`)
- Test: `tests/test_arrangement_firm.py` (append), `tests/test_finding_text.py` (one more sample)

**Interfaces:**
- Consumes: `_settle_firm_arranged` records `self._arr_choice[key] = ident` (Task 4.1).
- Produces: `_Redo(seed, swaps, notes, loose, arr=None)` with `.arr: dict` (the arrangement each firm cell took in the pass that stopped); `Board._arr_prev: dict` (what the pass before took); `Board._arr_unsettled: dict[key, [ids]]`; a pass is settled when its ops are where they were and every firm cell took the arrangement it took in the pass before; `fixed.room_unsettled` with facts `{"item", "arrangements": [ids that alternated], "passes"}` for a cell still changing at the last pass, which keeps that pass's choice.

- [ ] **Step 1: Write the failing tests** (append)

```python
class Alternating(Board):
    """A board whose firm cell scores the arrangements the other way round on each pass: a choice that never settles."""
    def _firm_trials(self, occ, plan, i, placed, clr, push_sources):
        trials = super()._firm_trials(occ, plan, i, placed, clr, push_sources)
        flip = (self._firm_pass_no or 99) % 2
        for t in trials:
            t.score = 10.0 if (t.ident == "") == bool(flip) else 1.0
        return trials


def declared_copper_board(cls, passes=None):
    from placemat.values import CopperLayer, Net, PadRef
    s = Settings() if passes is None else dataclasses.replace(Settings(), place_firm_passes=passes)
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = cls(g, edge_margin=0.0, keep_going=True, settings=s)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=AT)
    b.track(Net("mod.VIN"), [PadRef(Part("r8"), 1), PadRef(Part("mod.u1"), 1)], layer=CopperLayer.F)
    return b


def test_a_choice_that_holds_settles_and_is_carried():
    b = declared_copper_board(Board)
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east"
    assert not [f for f in plan.findings if f.cause == "fixed.room_unsettled"]
    assert b._arr_choice == {"mod": "c_in.east"}


def test_a_cell_whose_arrangement_alternates_keeps_the_last_pass_and_says_which_ids_alternated():
    b = declared_copper_board(Alternating, passes=4)
    plan = b.resolve()
    (f,) = [f for f in plan.findings if f.cause == "fixed.room_unsettled" and f.facts.get("item") == "mod"]
    assert sorted(f.facts["arrangements"]) == ["c_in.east", "default"] and f.facts["passes"] == 4
    assert plan.placement("mod").arrangement in ("", "c_in.east")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_firm.py -k "settles or alternates" -q`
Expected: FAIL (no `fixed.room_unsettled` for the alternating cell: the passes do not look at arrangements).

- [ ] **Step 3: Implement**

`_Redo.__init__(self, seed, swaps, notes, loose, arr=None)`: `self.arr = dict(arr or {})`. `Board.__init__`: `self._arr_prev: dict = {}`, `self._arr_unsettled: dict = {}`. `_resolve`: in the reset line (`:6491`) add `self._arr_prev, self._arr_unsettled = {}, {}`; in `except _Redo as r:` after `self._restore(saved)` add `self._arr_prev = r.arr`. `_resolve_once` start: `self._arr_choice = {}`. `_redo_check`:

```python
        changed = {k: [self._arr_prev[k], v] for k, v in self._arr_choice.items()
                   if k in self._arr_prev and self._arr_prev[k] != v}
```
placed at the top of the method. In the first branch (`not self._redo and fixed_copper is not None`, the last pass): after computing `_room_unsettled` add `self._arr_unsettled = {k: sorted({a or "default" for a in ab}) for k, ab in changed.items()}`. In the redo branch the condition `if relaxed or moved or (conflicted and not seed):` becomes `if relaxed or moved or changed or (conflicted and not seed):` and every `raise _Redo(...)` in the method passes `self._arr_choice` as the fifth argument. After the `_room_unsettled` loop in `_resolve_once` (`:6924-6927`):

```python
        for key, ids in sorted(self._arr_unsettled.items()):
            plan.findings.append(self._finding(C.FIXED_ROOM_UNSETTLED, {"item": key, "arrangements": ids,
                                                                        "passes": self.settings.place_firm_passes}))
```
`finding_text.py`: `@renders(C.FIXED_ROOM_UNSETTLED, "passes")` with

```python
def _fixed_room_unsettled(f):
    if "arrangements" in f:
        return ("%s: the arrangement it took still changed between the last two of %d passes over the firm items (%s), so what "
                "stands beside it was placed against its last pass's" % (f["item"], f["passes"], ", ".join(f["arrangements"])))
    ... the existing sentence ...
```
and `FACTS_V[C.FIXED_ROOM_UNSETTLED] = 2` after the renderers. Add to `SAMPLES` in `tests/test_finding_text.py`: `(C.FIXED_ROOM_UNSETTLED, {"item": "mod", "arrangements": ["c_in.east", "default"], "passes": 4}, "mod: the arrangement it took still changed between the last two of 4 passes over the firm items (c_in.east, default), so what stands beside it was placed against its last pass's")`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_firm.py tests/test_copper_room.py tests/test_beside*.py tests/test_finding_text.py tests/test_suggestion_cases.py -q`
Expected: PASS.

- [ ] **Step 5: Bench and commit**

Run: `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out` (every case `same`).

```bash
git add src/placemat/layout.py src/placemat/finding_text.py tests/test_arrangement_firm.py tests/test_finding_text.py
{ echo "Arrangements: the firm choice is carried between passes and must settle, or fixed.room_unsettled names the ids"; echo; echo "bench --jobs 2:"; grep -E "^(default|solve|physical):|^seconds:" $SCRATCH/bench.out; } | git commit -F -
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 4.3: Phase 4 gate

- [ ] **Step 1: Bench** - `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`; expected every case `same`.
- [ ] **Step 2: Firm-cell timing** - under the real-board lock `.venv/bin/python fixtures/bench.py --arrangements`; expected `firm.on_s` a small multiple of `firm.off_s` (the k legality judgments and scorings are small beside the scans); record in the spec's build notes.
- [ ] **Step 3: Default suite** - `.venv/bin/python -m pytest -n 2`; expected PASS.
- [ ] **Step 4: Real-module fixture** - append to `tests/test_arrangement_real_module.py` the same stamped fixture with the cell placed by `Location` (firm) and no `arrangements=`: the board run places the cell and records an arrangement the module offers (or the default) without error.

```python

def test_a_firm_cell_of_the_same_module_is_placed_and_records_its_arrangement(tmp_path):
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.values import Cell, Location
    result, _, frag = real_modules.run(tmp_path / "module", "usb5v", edit=with_alternatives)
    stamped = stamp_fragment_as_cell(frag, tmp_path / "stamped.kicad_pcb", "mod", (40.0, 20.0))
    b = Board(read_board(stamped), edge_margin=0.0, keep_going=True)
    b.rect(width=140, height=120)
    b.place(Cell("mod"), at=Location(70.0, 60.0))
    plan = b.resolve()
    assert plan.step("mod").placement is not None and plan.placement("mod").arrangement in ("",) + b.geometry.cells["mod"].offered()
```
Run: `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock .venv/bin/python -m pytest tests/test_arrangement_real_module.py -q`; expected PASS.
- [ ] **Step 5: Commit** the build notes (`docs/superpowers/specs/2026-10-04-module-member-variants-design.md`): `git commit -m "Arrangements: build notes for the firm-cell timing"`.

---

# Phase 5: studio and the rest of the docs

### Task 5.1: The studio shows the arrangement a cell took and the module run's list

**Files:**
- Modify: `src/placemat/preview_json.py` - `item_json` (`:85-110`: `"arrangement"` when not default)
- Modify: `src/placemat/studio.py` - `run_summary` (`:1372-1410`: `"arrangements"`), `run_doc` (`:1489-1498`: the placements' `arrangement`)
- Modify: `src/placemat/studio_page.html` - `noteParts` (`:2199`: `case "arrangement"`), `noteRows` (`:2315`), `stepSummary` (`:2491`), `runDetail` (`:3839`)
- Test: `tests/test_arrangement_studio.py` (node, through `tests/test_studio_page.py`'s `run_page` harness), `tests/test_preview_json.py` (one item)

**Interfaces:**
- Consumes: the step note `{"kind": "arrangement", ...}` (Task 3.2), `RunRecord.arrangements` (Task 1.9).
- Produces: `plan.json` items gain `"arrangement": str` only when not default; `run_summary(...)["arrangements"]` = `[{"id", "offered", "refused": int, "duplicate_of"?}]`; page: `noteParts` returns `o.arrangement = {id, score, cost, default_score, tried: [{id, score, legal}]}`; the step card shows an "arrangement" row (the id as a pill), a row per tried arrangement ("c_in.east 41.20 legal", "default none") and the step summary says the id; the run detail lists the arrangements with "offered" or "refused n". No parenthetical text in any label; red only for a refused arrangement.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arrangement_studio.py
import shutil

import pytest

from tests.test_studio_page import needs_node, run_page

NOTE = {"kind": "arrangement", "id": "c_in.east", "score": 41.2, "cost": 0.0, "default_score": 44.9,
        "tried": [{"id": "default", "score": 44.9, "legal": True}, {"id": "c_in.east", "score": 41.2, "legal": True}],
        "text": "arrangement c_in.east: 41.20 and 0.00 for it against 44.90 as the default module stands"}


@needs_node
def test_the_step_card_reads_the_arrangement_note(tmp_path):
    out = run_page(tmp_path, r"""
const np = noteParts([%s], null);
out.id = np.arrangement && np.arrangement.id;
out.tried = np.arrangement && np.arrangement.tried.map(t => t.id + ":" + t.legal);
out.rows = noteRows(np).map(r => r[0]);
out.summary = stepSummary({why: ""}, null, np);
out.html = noteRows(np).map(r => r.join(" ")).join("|");
""" % __import__("json").dumps(NOTE))
    assert out["id"] == "c_in.east" and out["tried"] == ["default:true", "c_in.east:true"]
    assert "arrangement" in out["rows"] and "c_in.east" in out["summary"]
    assert "(" not in "".join(r for r in out["rows"])               # no bracketed explanation in a label
    assert "41.2" in out["html"] and "44.9" in out["html"]


@needs_node
def test_a_note_with_no_arrangement_changes_nothing(tmp_path):
    out = run_page(tmp_path, r"""
const np = noteParts([{kind: "rank", rank: 1, of: 2, area_mm2: 3, area_ord: 1, pins: 4, pins_ord: 1}], null);
out.arr = np.arrangement || null;
out.rows = noteRows(np).map(r => r[0]);
""")
    assert out["arr"] is None and "arrangement" not in out["rows"]


@needs_node
def test_the_run_detail_lists_the_modules_arrangements(tmp_path):
    out = run_page(tmp_path, r"""
out.html = runDetail({drc: {}, severities: {}, timing: {}, verdicts: [], failure: null,
  arrangements: [{id: "default", offered: true, refused: 0}, {id: "mirrored", offered: false, refused: 2},
                 {id: "c_in.same", offered: false, refused: 0, duplicate_of: "default"}]});
""")
    h = out["html"]
    assert "Arrangements" in h and "mirrored" in h and "refused 2" in h and "same as default" in h and "default" in h
```

```python
# in tests/test_preview_json.py (or a new function in tests/test_arrangement_pin.py)
def test_an_item_placed_in_an_arrangement_says_so_and_a_default_item_does_not():
    from placemat import preview_json as P
    from placemat.layout import Board
    from placemat.values import Cell, Location
    from tests.arrangement_support import stamped_geometry, with_arrangement
    b = Board(with_arrangement(), edge_margin=0.0, keep_going=True)
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.east")
    plan = b.resolve()
    item = P.item_json(plan, plan.step("mod"))
    assert item["arrangement"] == "c_in.east"
    d = Board(stamped_geometry(), edge_margin=0.0, keep_going=True)
    d.place(Cell("mod"), at=Location(40.0, 30.0))
    assert "arrangement" not in P.item_json(d.resolve(), d.resolve().step("mod"))
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_studio.py -q`
Expected: FAIL (`out["id"]` is null: `noteParts` has no `arrangement` case).

- [ ] **Step 3: Implement**

`preview_json.item_json` (after `"face"` in the returned dict): `**({"arrangement": p.arrangement} if p is not None and p.arrangement else {}),`. `studio.run_summary` (the `out` dict): `"arrangements": [{"id": a["id"], "offered": a["offered"], "refused": len(a.get("refused", ())), **({"duplicate_of": a["duplicate_of"]} if a.get("duplicate_of") else {})} for a in (rec.arrangements or [])],`; `run_doc`'s `items` rows: `**({"arrangement": v["arrangement"]} if v.get("arrangement") else {})`.

`studio_page.html`: in `noteParts` (`:2199`), add `arrangement: null` to the initial object and

```js
      case "arrangement": o.arrangement = {id: n.id, score: n.score, cost: n.cost, default_score: n.default_score, tried: n.tried || []}; break;
```
`noteRows` (`:2315`) gains, after the rank rows:

```js
  ...(np.arrangement ? [["arrangement", pill(np.arrangement.id, "arr")], ...np.arrangement.tried.map(t => [t.id, esc(t.legal ? (t.score != null ? (+t.score).toFixed(2) + " legal" : "legal") : "no legal spot")])] : []),
```
`stepSummary` (`:2491`): `if (np.arrangement) bits.push("arrangement " + np.arrangement.id);`. `runDetail` (`:3839`): a section

```js
  const arrs = (r.arrangements || []).map(a => "<div>" + pill(a.id, a.offered ? "good" : "bad") + " " + esc(a.duplicate_of ? "same as " + a.duplicate_of : a.offered ? "offered" : "refused " + a.refused) + "</div>").join("");
```
inserted as `(arrs ? sect("Arrangements", '<div class="cl">' + arrs + "</div>") : "")` before the failing-checks section; the `pill` classes `arr`, `good` and `bad` exist in the page's CSS (`.chip.good`, `.chip.bad`); add `.pill.arr { }` only if the page has no neutral class (it has `net` and `face-*`): reuse `net`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_studio.py tests/test_studio_page.py tests/test_studio*.py tests/test_preview_json.py -q`
Expected: PASS (node installed); `test_the_script_parses` stays green.

- [ ] **Step 5: Commit**

```bash
git add src/placemat/preview_json.py src/placemat/studio.py src/placemat/studio_page.html tests/test_arrangement_studio.py tests/test_preview_json.py
git commit -m "Arrangements: the studio shows the arrangement a cell took, each one tried, and a module run's list"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 5.2: The rest of the docs and the release entry

**Files:**
- Modify: `skills/placemat/references/api.md` - "Arrangements" (the step note, `plan.json`'s `arrangement`, the lock's `arrangement` and `freeze`'s `arrangements=`, explore's `moves`, `fixed.room_unsettled`'s new facts, the `time.step_limit` fact); the Placement `place()` table of keywords (`arrangements=`)
- Modify: `skills/placemat/references/migration.md` - the "Unreleased" entry (Task 1.10) gains the board side: `arrangements=`, the search, the lock and freeze, a re-run is needed to write the notes, a board that stamps such a module searches arrangements by default so its placements can change, `arrangements="default"` holds the module's own layout, `reuse.VERSION` 5 and the first run replays nothing
- Modify: `BACKLOG.md` (file nothing unless the build left a follow-up: the coarse-pass refinement if the timing gate asked for it)
- Test: `tests/test_arrangement_declarations.py` (docs words), `tests/test_describe.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_arrangement_declarations.py`)

```python
def test_the_migration_entry_names_what_a_board_must_know():
    text = Path("skills/placemat/references/migration.md").read_text().split("## To 0.98.0")[0]
    for word in ("arrangements=", "arrangement", "re-run", "default", "place.arrangements"):
        assert word in text, word
    assert "arrangement" in API and "plan.json" in API.split("**Arrangements.**", 1)[1][:6000]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py::test_the_migration_entry_names_what_a_board_must_know -v`
Expected: FAIL (`AssertionError: re-run`).

- [ ] **Step 3: Write the docs** as listed in Files (plain nouns for headings; the forms and the ids are in `api.md`, the skill points there).

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_arrangement_declarations.py tests/test_describe.py tests/test_queries.py tests/test_settings_docs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/placemat/references/api.md skills/placemat/references/migration.md tests/test_arrangement_declarations.py BACKLOG.md
git commit -m "Arrangements: api.md and the migration entry for the board side"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 5.3: The skill check

**Files:**
- Create: `fixtures/skill_check.py` (stage a fixture module without its layout script, print the task, check the produced script)
- Create: `docs/superpowers/skill-checks/arrangements.md` (the protocol and the pass criteria) and the folder `docs/superpowers/skill-checks/transcripts/`
- Test: `tests/test_skill_check.py` (the checker on hand-written good and bad scripts; pure)

**Interfaces:**
- Consumes: `tests.real_modules.stage` (the staging of a fixture module), `placemat.arrangements` names.
- Produces: `fixtures/skill_check.py stage <module> <dir>` (copies the fixture module without its `_layout.py` and prints the task text); `skill_check.check(script_text: str, roles: dict) -> list[str]` (the machine-checkable criteria, each failure a plain sentence): an alternative on each role `bypass` and `pullup` part, none on a `polarised` part, an alternative or a stated reason (a `# extent:` comment line) for each `protruding` part, option and group names not matching `alt\d*`, and no more than `place.arrangement_options_max` options per item (read from `Settings`); `ROLES: dict` (per module: the part names of each role, filled in from `placemat parts` of the chosen fixture modules).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_check.py
import importlib.util
import pathlib

BENCH = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "skill_check.py"


def load():
    spec = importlib.util.spec_from_file_location("skill_check", BENCH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ROLES = {"bypass": ["c_hf1"], "pullup": ["r_pull"], "polarised": ["bulk_a"], "protruding": ["bulk_b"]}
GOOD = '''
board.place(Part("c_hf1"), at=Beside(Part("u1"), Edge.NORTH))
board.alternative(Part("c_hf1"), "south", at=Beside(Part("u1"), Edge.SOUTH))
board.place(Part("r_pull"), at=Beside(Part("u1"), Edge.EAST))
board.alternative(Part("r_pull"), "turned", rotation=180)
board.place(Part("bulk_b"), at=Beside(Part("u1"), Edge.EAST))
board.alternative(Part("bulk_b"), "tucked", rotation=90)
board.place(Part("bulk_a"), at=Beside(Part("u1"), Edge.WEST))
'''


def test_a_script_that_follows_the_skill_passes():
    assert load().check(GOOD, ROLES) == []


def test_each_departure_is_named():
    m = load()
    assert any("bypass" in f for f in m.check(GOOD.replace('board.alternative(Part("c_hf1"), "south", at=Beside(Part("u1"), Edge.SOUTH))\n', ""), ROLES))
    assert any("polarised" in f for f in m.check(GOOD + 'board.alternative(Part("bulk_a"), "flipped", rotation=180)\n', ROLES))
    assert any("name" in f for f in m.check(GOOD.replace('"south"', '"alt1"'), ROLES))
    assert any("extent" in f or "protruding" in f for f in m.check(GOOD.replace('board.alternative(Part("bulk_b"), "tucked", rotation=90)\n', ""), ROLES))
    ok = GOOD.replace('board.alternative(Part("bulk_b"), "tucked", rotation=90)\n', "# extent: bulk_b is a fact of its datasheet figure\n")
    assert m.check(ok, ROLES) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_skill_check.py -q`
Expected: FAIL (`FileNotFoundError: fixtures/skill_check.py`).

- [ ] **Step 3: Implement**

```python
# fixtures/skill_check.py
"""The skill check for arrangements: an agent given only the updated skill and a fixture module with no layout script lays it out; this
stages the module, prints the task, and checks what can be checked of the script it wrote. The rest (it ran the module, read the
arrangement report, and fixed or dropped an alternative the run refused) is read from the transcript against the list in
docs/superpowers/skill-checks/arrangements.md."""
from __future__ import annotations

import ast
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROLES: dict = {}        # module -> {"bypass": [...], "pullup": [...], "polarised": [...], "protruding": [...]}: part names, from `placemat parts`
TASK = ("Lay out the module in {dir} with placemat. Use the placemat skill only. Run it, read the run's report, and finish when the "
        "module is correct.")


def _calls(text: str):
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            out.append(node)
    return out


def _part(call) -> str:
    a = call.args[0] if call.args else None
    return a.args[0].value if isinstance(a, ast.Call) and a.args and isinstance(a.args[0], ast.Constant) else ""


def check(script_text: str, roles: dict) -> list:
    from placemat.settings import Settings
    cap = Settings().place_arrangement_options_max
    moved: dict = {}
    names = []
    for c in _calls(script_text):
        if c.func.attr == "alternative" and len(c.args) >= 2 and isinstance(c.args[1], ast.Constant):
            moved.setdefault(_part(c), []).append(c.args[1].value)
            names.append(c.args[1].value)
        elif c.func.attr == "arrangement" and c.args and isinstance(c.args[0], ast.Constant):
            names.append(c.args[0].value)
            for a in c.args[1:]:
                if isinstance(a, ast.Call) and getattr(a.func, "id", "") == "Alt":
                    moved.setdefault(_part(a), []).append(c.args[0].value)
    out = []
    for role, what in (("bypass", "a bypass"), ("pullup", "a pull-up")):
        for part in roles.get(role, ()):
            if part not in moved:
                out.append("%s (%s) has no alternative: %s whose side or turn is free gets one" % (part, role, what))
    for part in roles.get("polarised", ()):
        if part in moved:
            out.append("%s is polarised: its place is a fact and it gets no alternative" % part)
    for part in roles.get("protruding", ()):
        if part not in moved and not re.search(r"#\s*extent:.*\b%s\b" % re.escape(part), script_text):
            out.append("%s sets the module's extent (protruding): it needs an alternative or a '# extent:' line saying why it has none" % part)
    for n in names:
        if re.fullmatch(r"alt\d*", n):
            out.append("%r names nothing: an option is named for what it does" % n)
    for part, opts in moved.items():
        if 1 + len(opts) > cap:
            out.append("%s has %d options, over the %d the caps allow" % (part, 1 + len(opts), cap))
    return out


def stage(module: str, target: pathlib.Path) -> str:
    sys.path.insert(0, str(ROOT))
    from tests import real_modules
    script = real_modules.stage(target, module)
    script.unlink()                                     # the agent writes this one
    return TASK.format(dir=target / "board" / "modules" / module)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "stage":
        print(stage(sys.argv[2], pathlib.Path(sys.argv[3])))
    elif len(sys.argv) == 4 and sys.argv[1] == "check":
        problems = check(pathlib.Path(sys.argv[3]).read_text(), ROLES[sys.argv[2]])
        print("\n".join(problems) or "the script passes the machine-checkable criteria")
        sys.exit(1 if problems else 0)
    else:
        print("usage: skill_check.py stage MODULE DIR | check MODULE SCRIPT")
        sys.exit(2)
```
`docs/superpowers/skill-checks/arrangements.md`: the protocol (stage two fixture modules chosen for the roles: a bypass beside its IC, a pull-up, a polarised part, a member protruding past the rest; fill `ROLES` from `placemat parts` of each), the criteria list from the spec's Testing section, and "a failure is a change to the skill's wording, not to the check".

- [ ] **Step 4: Run to verify pass, then the check itself**

Run: `.venv/bin/python -m pytest tests/test_skill_check.py -q` (PASS). Then, for each of two fixture modules chosen from `fixtures/*/modules/` for the four roles: `.venv/bin/python fixtures/skill_check.py stage <module> <scratch dir>`, hand the printed task and only `skills/placemat/SKILL.md` and `references/` to a fresh agent (no other instructions), let it finish, run `.venv/bin/python fixtures/skill_check.py check <module> <its script>`, and read its transcript against the criteria (ran the module, read `run.json`'s `arrangements` and the refused findings, fixed or dropped a refused alternative). Save each transcript to `docs/superpowers/skill-checks/transcripts/<module>.md`. Expected: both pass; a failure changes the skill's wording (`SKILL.md`, "Arrangements"), and the check runs again.

- [ ] **Step 5: Commit**

```bash
git add fixtures/skill_check.py docs/superpowers/skill-checks tests/test_skill_check.py skills/placemat/SKILL.md
git commit -m "Arrangements: the skill check, its checker and the transcripts of two fixture modules"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

### Task 5.4: Final gate

- [ ] **Step 1: Bench** - `.venv/bin/python fixtures/bench.py --jobs 2 | tee $SCRATCH/bench.out`; expected every case `same`.
- [ ] **Step 2: The full suite, once, alone** - `.venv/bin/python -m pytest --full -n 2`; expected PASS. Add any test over 2 s to `tests/slow_tests.txt` with `tests/update_slow_tests.py`.
- [ ] **Step 3: Real board** - under the lock, run the whole-board check of Task 2.7 Step 4 once more, then `.venv/bin/python fixtures/bench.py --arrangements`; copies removed afterwards; numbers into the spec's build notes.
- [ ] **Step 4: Spec status** - in the spec header add `Built: <date>, see Build notes`; confirm `git status` is clean and `git log` has no commit message matching `claude|anthropic|session|co-authored`: `git log --format=%B main..HEAD | grep -iE "claude|anthropic|session|co-authored"` prints nothing.
- [ ] **Step 5: Release** - follow the release procedure (suite, skill docs current, release with migration and whats-new entries, notify the projects that use placemat, then the bench). This plan adds the migration entry; the release notes and any gaps file are the release's own step.


---

# Spec and code notes

Where the spec is silent, ambiguous or contradicted by the code, and what this plan does about it (each is a decision for the user to confirm before the task that carries it):

1. **The note's `base` cannot give the stamping offset.** The spec takes the offset between the fragment's frame and the generated board's "from the members' default places (the note's `base` against the stamped footprints)", but `base` is a digest. The plan's note carries each member's default place as `from` beside its arrangement place, and `base` stays as the digest of those (Task 1.6, Task 2.1). The note also carries `order` (the module run's order of arrangements) so the stamping board can scan in the declared order, which the spec requires and the texts' order on a KiCad group cannot give.
2. **The note's text is percent-escaped, not raw JSON.** The spec says `placemat arrangement <json>`; `rules.py:129-145` percent-escapes its note because KiCad reads braces and `$` in a text as markup, and `kicad/read.py` reads a note with `GetText()`. The plan escapes (Task 1.6). Phase 1's measurement (Task 1.9) says whether the size needs the split at 4000.
3. **`place.extent_notice_mm` has no default in the spec**; the user chose 1.0 mm (2026-10-04). Also "how far it stands past the next member on that side" is read as the distance between the outermost edge on a side and the next member's edge on that side, so the end part of a chain always protrudes by about its neighbour's width; the setting is what keeps that quiet on a module with no alternatives.
4. **Cleanup does not move cells.** The spec says cleanup moves and swaps keep an item's arrangement; `layout.py:7286-7315` (`_cleanup_movable`) takes parts and block satellites only, so there is nothing to keep. Task 3.4 pins that with a test.
5. **A decided cell with no legal arrangement.** The spec says both "a firm collision as it is today (the default's finding, the others' refusals under it)" and "the cell is unplaced". Today a firm item that is illegal is still placed, with a `fixed.part` finding (`layout.py:9128-9140`, `PlacementCollision` after the firm tier); the plan keeps that (Task 4.1).
6. **Links and the proof.** The skill text says an alternative is proven "by the module's own links, limits ..."; Decision 4 (and the proof's three steps) refuse only unplaced members, critical findings, failed verdicts and `real` DRC buckets. A link past its limit (`link_over`) is a warning, so the plan records it in the arrangement's measures and does not refuse (Task 1.8).
7. **`unconnected`.** The spec says an arrangement missing a join "fails `unconnected` as the default would", but `unconnected` is not among the `real` buckets (`settings.py` `DEFAULT_REAL_KINDS`) and the default's own count is a gate, not a refusal. The plan refuses an arrangement whose `unconnected` count is above the default's (Task 1.8).
8. **Nested cells.** An arrangement moves parts of the module. A module's own nested cells are placed once, by the default; an arrangement that places one elsewhere is refused (`nested_cell`), and the note carries the module's loose parts only (Task 1.8, Task 1.9).
9. **Option merging.** The spec says an option inherits what it does not give; it does not say what a `rotation=` does to the item's `rotations=` or a `Turned`. The plan lets a turn the option gives replace the default's way of turning (Task 1.3, Review Focus 5). The product's order (`itertools.product` over the items in declaration order) and the extra finding `arrangement.duplicate` for a dropped duplicate are also the plan's.
10. **`freeze`.** The spec names `script_edit.edit_keywords`; `freeze.py:40-62` (`edit_call`) wraps it and is where `arrangements=` is added (Task 3.6).
11. **Release notes and a gaps file.** The spec's Migration names both; the repository has no gaps file (BACKLOG.md says so) and the release notes are the `migration.md` "Unreleased" entry (Task 1.10, 5.2).
12. **The bench corpus.** `fixtures/bench.py` resolves each module's generated board with a bare `place()` per part and runs no module script, so the corpus trivially declares no alternatives. The new cases (`--arrangements`, Task 3.8) need notes written into a copy of a fixture board (`synthetic_notes_for`).
13. **KiCad.** The header says KiCad 9; `pcbnew.Version()` in this checkout's venv is 10.0.6. The pcbnew staging helpers in `tests/arrangement_support.py` use API names that differ between the two for pad shapes; Task 2.2 says where to adjust.
14. **"Byte-identical" and `run.json`.** The run id includes the settings digest, so new settings change run ids and `reuse.json`; "byte-identical" is the written `layout.kicad_pcb`, the placements, lock entries and reuse steps (Global Constraints). `run.json` omits `arrangements` when empty.
15. **Written against partial reading.** The search refactor (Tasks 3.1-3.3), the explore pool (3.7), the firm trial's `default_blame` shape (4.1), the studio script (5.1) and the pcbnew helpers are written against the code as read, with the lines named; a test that fails on a name or a line is the signal to read the cited function again, not to change the test's property.
