# Riders, Inside, one land, explicit router pairs - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The four forms in the spec, each with its tests and docs.

**Architecture:** Three parts, each in its own worktree, since they touch
different code:
- **A:** riders, in the placement search: `place_ranked`, the
  searched-item scan and commit.
- **B:** `Inside` and `land=`, in the region and pad-reference resolution.
- **C:** explicit router pairs, in the routing copy, `pairs_of` and the
  score.

**Tech Stack:** Python, pcbnew (KiCad 9), pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-remaining-backlog-design.md` (approved 2026-09-29)

## Global Constraints

- TDD per behaviour: write the failing test, watch it fail, implement,
  watch it pass.
- Fixed sets are enums. Tunables are settings. Plain ASCII only.
- Generic wording in source, tests, docstrings, docs and commit messages:
  no real module, part, board or component-type names.
- New fields that feed reuse/lock digests carry `metadata={"omit_default":
  True}`. The digest parity tests pass unchanged.
- Docs:
  - update `skills/placemat/references/api.md`;
  - add your notes under a `## Unreleased` section at the very top of
    `skills/placemat/references/migration.md`, creating it if absent.
- Commits:
  - `git -c user.name="<owner name>" -c user.email="<owner email>" commit`;
  - no Claude/Anthropic/session/Co-Authored-By text;
  - `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`
    prints nothing.
- Tests:
  - targeted files only, via
    `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/<files>`,
    after `cp /home/ben/work/placemat/src/placemat/_version.py src/placemat/`;
  - never the full suite, the bench or the router itself;
  - a test that needs the router is stubbed at the command boundary.

## Review Focus

- A rider whose reference is searched with rotations: the rider turns with
  each candidate.
- A rider that fits no candidate: the reference's search fails with a
  finding naming the rider, and nothing is committed half-way.
- `Inside` on a part with pads on one side only: the other sides use the
  pads' outer extent.
- `land=` on a pad number with one land: identical to no `land=`.
- An explicit pair whose names already follow `_P`/`_N`: routed once, not
  twice.

---

### Task A1: Riders on a searched item

**Files:**
- `src/placemat/layout.py`: `place_ranked` (the "only FIXED and EDGE items
  may be referred to" refusal, about line 3460), the searched-item scan
  (`_settle`/`scan`), and the commit.
- `src/placemat/placer.py`: follow how `scan_block`/`layout_block` carry
  satellites as a rigid group.
- Test: `tests/test_riders.py` (new).

**Behaviour (spec item 1):**
- A firm placement (`Pin`, `Beside`, `row(of=)`) whose reference is a
  searched item becomes a rider of it.
- At each candidate the reference is tried at, every rider is placed where
  its relation gives for that candidate, and the candidate counts only
  when every rider is legal there. The legality test is the one block
  satellites get (`occ.legal`, and against the reference and the other
  riders).
- Riders commit with the reference, as block members do: a Step each,
  with the note "rides <key>".
- A rider of a rider chains.
- A rider that fits nowhere fails the reference with a finding naming the
  rider and its reason.
- A relation whose reference is a searched item that is not the rider's
  own reference (a `Beside` aligning to a third, searched part's pad) is
  still refused, with the same message.
- Cutouts and keepouts at a searched part's `PadRef` stay refused. They
  are regions settled in the fixed queue; say so in the docs.

- [ ] Tests:
  - a `Pin` rider lands at its offset from a searched part's pad, including
    under `rotations=(0, 90)`;
  - a `Beside` rider;
  - a rider that blocks every candidate makes a finding naming it;
  - a rider of a rider;
  - the third-part refusal still stands.
- [ ] Implement, run `tests/test_riders.py tests/test_freedom.py
  tests/test_order.py tests/test_blocks.py tests/test_beside.py
  tests/test_lock*.py tests/test_reuse*.py tests/test_enum_digest_parity.py`.
- [ ] Docs: api.md (the refusal paragraph under `Beside`/`Pin`, and a
  "Riders" paragraph), migration.md Unreleased.
- [ ] Commit "A firm placement on a searched item rides it".

### Task B1: Inside(Part)

**Files:**
- `src/placemat/values.py` (new `Inside`);
- `src/placemat/layout.py` (`keepout()` where `region_of` is set;
  `_item_envelope_shape` is the model);
- `src/placemat/__init__.py` export.
- Test: `tests/test_keepout_inside.py`.

**Behaviour (spec item 2):**
- `board.keepout(Inside(Part("u1"), margin=0.0), name, ...)`.
- The region is a box in the part's own frame at rotation 0, split by the
  body centre:
  - west edge: the largest `right` of the pads wholly west of centre;
  - east edge: the smallest `left` of those wholly east;
  - north and south: the same with `bottom`/`top`;
  - a side with no pads: the pads' outer extent on that axis.
- It is grown by `margin` (negative shrinks it), anchored so it moves,
  turns and mirrors with the part exactly as `keepout(Part)` does (reuse
  `region_of` settling).
- A part whose inner box is empty or negative is a ValueError naming it.

- [ ] Tests:
  - two columns (east/west pads only): box between the columns, the pads'
    north/south extent;
  - a four-side ring;
  - turned 90;
  - on the back;
  - a negative margin;
  - an empty box refused.
- [ ] Commit "A keepout inside a part's pad ring".

### Task B2: land= on PadRef

**Files:**
- `src/placemat/values.py` (`PadRef.land`, new `Land` enum with
  `LARGEST`);
- `src/placemat/layout.py` (`_pad_ref`, `_locate`'s PadRef branch,
  `_pad_shapes`);
- `src/placemat/occupancy.py` (`pad_location` may take a land).
- Test: `tests/test_pad_land.py`.

**Behaviour (spec item 3):**
- `PadRef(part, 1, land=Land.LARGEST)` or `land=2` (1-based, in the
  footprint's order for that number).
- The reference locates at that land's box centre.
- `_pad_shapes` returns that land only.
- `land=` on a number with one land is identical to none.
- A land index past the count is a ValueError naming the count.
- `land` carries `omit_default`.

- [ ] Tests:
  - a track ending on the largest land;
  - a via grid (`vias(net, PadRef(..., land=...))`) over one land;
  - `Past` over one land;
  - the index form;
  - the out-of-range refusal;
  - one-land identity;
  - digest parity.
- [ ] Commit "A pad reference may name one land of a pin".

### Task C1: Explicit router pairs

**Files:**
- `src/placemat/pairs.py` (`pairs_of` takes explicit pairs);
- `src/placemat/kicad/route.py` (`route_pairs` / the routing copy: rename
  before, restore after);
- `src/placemat/settings.py` (the doc of `route_diff_pairs`);
- `src/placemat/occupancy.py:723` and `src/placemat/score.py:127` (the
  `pairs_of` callers).
- Tests: `tests/test_explicit_pairs.py`.

**Behaviour (spec item 4):**
- A `route.diff_pairs` entry containing one `/` (`"NET_A/NET_B"`) names an
  explicit pair: the first net is P, the second N.
- `pairs_of(nets, patterns)` includes each explicit pair whose two nets are
  both present, alongside the suffix pairs.
- Before the pair router runs, the routing copy's two nets are renamed
  `PMPAIR<i>_P`/`PMPAIR<i>_N` (net names chosen not to collide with any
  board net). The pattern `PMPAIR<i>` is passed to the pair router, and
  after it the routed copy's nets are renamed back before any copper is
  read or merged.
- An explicit pair naming a net the board does not have is refused before
  routing, naming it.
- A pair already named `_P`/`_N` given explicitly is routed once.

- [ ] Tests:
  - `pairs_of` with an explicit pair;
  - the rename/restore on a synthetic pcbnew board (rename, save, reload,
    restore: net names and the tracks' nets back as they were);
  - the pattern passed to the pair command (stub the subprocess);
  - the unknown-name refusal;
  - the no-double-routing case.
- [ ] Commit "route.diff_pairs names a pair explicitly".

### Finish

The coordinator merges A, B and C, runs the full suite, releases, notifies
the sessions (reload the skill), then runs the bench.
