# Vias that give way - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a carried via ways to give way instead of refusing a
placement:
- share it with a same-net via on the far face;
- move it slightly;
- drop it;
- thin a stamped field when placing the cell;
- give a via a layer span.

**Architecture:** Two parts, in their own worktrees.
- **A**, the give-way in the placement search (Tasks A1-A4). It touches the
  occupancy's legality for carried vias and the search's scoring and
  commit.
- **B**, the density on `place()` and the layer span (Tasks B1-B2). It
  touches how a cell's copper is taken at placement, via writing and
  reading, and via shapes.

**Tech Stack:** Python, pcbnew (KiCad 9/10), the optional Rust native
module, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-plane-drops-and-the-far-face-design.md` (approved 2026-09-30)

## Global Constraints

- TDD per behaviour: write the failing test, watch it fail, implement,
  watch it pass.
- Tunables are settings with defaults, each documented in api.md's settings
  table (test_settings_wiring checks this):
  - `place.via_share` 1.0;
  - `place.via_move` 0.5;
  - `place.drops_keep` 0.5;
  - `score.via_share` 1;
  - `score.via_move` 2;
  - `score.via_drop` 10;
  - `copper.microvia_drill` 0.1.
- Fixed sets are enums (`Drops.ALL/HALF/MIN`). Plain ASCII only.
- Generic wording in source, tests, docstrings, docs and commit messages.
- New fields that feed reuse/lock digests carry `metadata={"omit_default":
  True}`. The digest parity tests pass unchanged.
- The native module (Rust, `native/`) judges placement legality alongside
  Python. `tests/test_native_legal.py` and `tests/test_native_sweep.py`
  must keep passing:
  - the give-way either runs in Python after a native refusal of a carried
    via;
  - or changes both paths.
  - Do not let the two disagree.
- Docs:
  - api.md;
  - migration.md: a `## Unreleased` section at the top, created if absent.
- Commits:
  - `git -c user.name="<owner name>" -c user.email="<owner email>" commit`;
  - no Claude/Anthropic/session/Co-Authored-By text;
  - check with `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`,
    which prints nothing.
- Tests:
  - targeted files only, via
    `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/<files>`,
    after `cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/`;
  - never the full suite, the bench or a router.

## Review Focus

- A via that could both share and move: sharing wins (the cheaper score).
- A cell with no drops on a pad: `drops_keep` never removes that pad's last
  via.
- A shared drop's joining tail on the drop's own face, not the other
  via's face.
- Give-way on an item already placed, for a later far-face part: the owner
  keeps its keep share, and its lock digest is unchanged, since giving way
  is the plan's, not the declaration's.
- A micro via span written and read back: KiCad's via type, and its layers.

---

### Task A1: The carried vias of a candidate, and sharing

**Files:**
- `src/placemat/occupancy.py`: legality and commit for an item's carried
  via shapes;
- `src/placemat/layout.py`: `_carry_pad_vias`, the search's scoring hook,
  commit;
- `src/placemat/placer.py`;
- `src/placemat/settings.py`.
- Test: `tests/test_vias_give_way.py` (new).

- [ ] Map where an item's carried vias live:
  - a cell's fragment vias (`occupancy.copper` shapes owned by the cell,
    moved with it);
  - pad vias carried by `_carry_pad_vias`.

  Identify each via's tail: a track of the same owner and net ending at
  the via's centre.
- [ ] Tests:
  - A cell whose GND via meets another net's far-face pad, with a GND via
    of another item within 1.0 mm: the candidate is legal, the cell's via
    is removed, and a straight tail at the net's width joins its pad (or
    its old tail's pad end) to the other via.
  - The same at 1.5 mm is not shared, and the candidate is refused.
  - A joining tail that would cross another net's copper is not shared.
- [ ] Implement:
  - on refusal by a carried via, try share, then move (A2), then drop (A3);
  - record the give-way on the candidate;
  - apply it at commit: remove the via, add the tail as the owner's copper;
  - add `score.via_share` per shared via to the candidate's score.
- [ ] Commit "A carried via shares a same-net via on the far face".

### Task A2: Moving a via

- [ ] Tests:
  - a signal via 0.2 mm onto a far-face pad of another net moves to the
    nearest clear spot within `place.via_move` on a 0.05 mm grid, with its
    tail redrawn from its pad;
  - a via inside its pad moves only within that pad;
  - with no clear spot, the candidate is refused and the refusal names the
    via.
- [ ] Implement, with `score.via_move`.
- [ ] Commit "A carried via moves to clear a pad on either face".

### Task A3: Dropping a drop

- [ ] Tests:
  - a plane-net via (the net has a declared `plane()`) is removed when its
    pad keeps at least `place.drops_keep` of its drops (rounded up, never
    fewer than one);
  - at the minimum, the candidate is refused;
  - a signal via is never dropped;
  - `score.via_drop` applies.
- [ ] Commit "A plane drop is dropped while its pad keeps its share".

### Task A4: An item already placed gives way, and the report

- [ ] Tests:
  - A back part placed after a front cell: the front cell's via that meets
    it shares, moves or drops, with the same rules and the owner's keep
    share.
  - The run reports what gave way per owner, as a Step note and a
    `plan.findings` entry of kind "vias":
    "protect: 6 GND vias shared, 2 moved 0.25 mm, 1 dropped under U3".
- [ ] Commit "A placed item's vias give way to a later far-face part; the
  give-way is reported".

### Task B1: `drops=` on placing a cell

**Files:**
- `src/placemat/values.py` (`Drops` enum);
- `src/placemat/layout.py` (`place()`, the cell's copper taken at commit);
- `src/placemat/__init__.py`.
- Test: `tests/test_cell_drops.py`.

- [ ] Tests:
  - `Drops.HALF` on a stamped cell with a 3x3 exposed-pad field keeps 5
    (checkerboard);
  - `Drops.MIN` keeps `ceil(drops_keep * n)` per field, at least one;
  - `Drops.ALL` is unchanged;
  - a field is the drops inside one pad;
  - the fragment is untouched;
  - the written board carries the thinned field;
  - digest parity (`drops` with `omit_default`).
- [ ] Commit "A cell's via fields thinned when it is placed (Drops)".

### Task B2: A via's layer span

**Files:**
- `src/placemat/copper.py` (`Via.layers`);
- `src/placemat/layout.py` (`via()`, `vias()`, `stitch()` take `layers=`;
  `_shape_of`, `_op_layers`);
- `src/placemat/kicad/write.py` (`_draw_via`: via type and layer pair; the
  design settings allowing it);
- `src/placemat/kicad/read.py` (check a blind via's layers read back);
- `src/placemat/settings.py` (`copper.microvia_drill`).
- Test: `tests/test_via_span.py`.

- [ ] Tests:
  - `board.via(net, at, layers=(CopperLayer.B, CopperLayer.IN4))` is
    judged on B and In4 only: a far-face F pad of another net over it is no
    conflict, and a B pad is;
  - it is written as a micro via with that layer pair and read back with
    those layers;
  - a span of B to In2 is written as blind;
  - a span naming a layer the board lacks is refused;
  - the default is through, with digests unchanged.
- [ ] Commit "A via may span some layers: micro and blind vias".

### Finish

The coordinator merges A and B, runs the full suite, releases, notifies the
sessions (reload the skill), then runs the bench.
