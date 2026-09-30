# A 45 off a corner, a zone fill's width, a link wait under priority - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three forms and behaviours in the spec.

**Architecture:** Three independent tasks, run in order in one worktree:
- **C1:** `Past` with a `Corner`, in values.py and layout.py (`_past_point`,
  the `Beside` pair align).
- **C2:** the zone fill's width, in checks.py (`_net_graph`, `_pairs`,
  `current_paths`).
- **C3:** the link wait's tier, in layout.py (`_link_waits`).

**Tech Stack:** Python, pcbnew, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-diagonal-lane-zone-width-link-priority-design.md` (approved 2026-09-30)

## Global Constraints

- TDD per behaviour: write the failing test, watch it fail, implement,
  watch it pass.
- Fixed sets are enums (`Corner.NE/NW/SE/SW`). Tunables are settings with
  defaults, each documented in api.md's settings table
  (`check.zone_step` 0.05). Plain ASCII only.
- Generic wording everywhere, commit messages included.
- New digest-feeding fields carry `metadata={"omit_default": True}`; the
  digest parity tests pass unchanged.
- Docs:
  - `skills/placemat/references/api.md`, with the intent index rows;
  - `skills/placemat/references/capture.md` for the check;
  - `skills/placemat/references/migration.md` under a `## Unreleased`
    section at the top.
- Commits:
  - `git -c user.name="Ben Agricola" -c user.email=ben+git@agrico.la commit`;
  - no Claude/Anthropic/session/Co-Authored-By text;
  - the grep check prints nothing.
- Tests:
  - targeted files only, via
    `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -q -p no:cacheprovider tests/<files>`,
    after copying `_version.py`;
  - never the full suite, the bench or a router.

## Review Focus

- `Past(items, Corner.X)` measured off the items' polygons, as the side
  form now is: a via's ring, not its circle.
- A zone lane whose route enters by a pad inside the fill, and one that
  enters by a track ending on the fill's edge.
- A zone fill with a hole where a via stands: the path goes round it.
- Link priority with three tiers: `HIGH` does not wait for `DEFAULT`, and
  `DEFAULT` does not wait for `LOW`.

---

### Task C1: `Past` with a corner

**Files:**
- `src/placemat/values.py`: new `Corner` enum; `Past.edge` accepts an
  `Edge` or a `Corner`; `across=` with a corner is refused.
- `src/placemat/layout.py`:
  - `_past_point`: a corner is the point on the outward diagonal of the
    items' box corner, off by the clearance by net pair plus
    width/2;
  - the Beside pair align with a corner: the own pad's facing corner
    stands the clearance off the 45 through the lane point;
  - `_round_away` for both axes.
- `src/placemat/__init__.py`: export `Corner`.
- Tests: `tests/test_past_corner.py`.

- [ ] Tests:
  - A track `[A, Past([pad], Corner.NE), B]` with A and B placed so a 45
    through the point is natural: the drawn 45 passes the pad's NE corner
    at clearance + width/2 (poly distance at least the clearance, within
    0.01 of it).
  - Each corner's point.
  - `across=` with a corner is refused.
  - A `Beside` pad off a 45.
  - A migration test: a comb of two resistors fed by parallel 45s, each a
    clearance off the next pad's corner, hand-computed (x + y constants)
    against the intent form, agreeing within 0.01 mm.
- [ ] Commit "Past takes a corner: a 45 held a clearance off it".

### Task C2: A zone fill's width

**Files:**
- `src/placemat/checks.py`;
- `src/placemat/settings.py` (`check_zone_step`);
- its wiring into `current_paths`' callers.
- Tests: `tests/test_current_path_zone_width.py`.

- [ ] Tests:
  - two carriers joined only by a 1.2 mm zone lane are judged at 1.2
    (within one step), with a neck point;
  - a fill with KiCad's slits (a hole slit to the outline) is not read as
    zero;
  - a fill neck narrower than the need fails, naming its point;
  - a lane round a hole (a via) keeps the width beside it;
  - a route through a fill and a narrower track is judged by the track.
- [ ] Implement:
  - rasterise the fill on its layer at `check.zone_step`;
  - take a distance transform (a two-pass chamfer or exact EDT; numpy is
    allowed if already a dependency, else pure Python over the fill's
    box);
  - run a maximin path search from the cells under the route's entry
    copper to the cells under its exit copper;
  - the width is twice the path's minimum distance;
  - plug it into `_pairs`, where a zone node now reports `math.inf`.
- [ ] Commit "check current-path measures a zone fill's width along the
  route".

### Task C3: A link wait under priority

**Files:** `src/placemat/layout.py` (`_link_waits`, the
"priority set aside" note).
- Tests: in `tests/test_order.py` (existing link-wait tests there).

- [ ] Tests:
  - a `HIGH` item linked to a `DEFAULT` one with more pull places in the
    `HIGH` tier (before an unlinked `DEFAULT` item) and its step has no
    "set aside" note;
  - two `DEFAULT` items still wait by pull, as before;
  - three tiers.
- [ ] Implement: in `_link_waits`, a slow item waits for its partner only
  when the partner's priority tier is the same as or higher than its own.
- [ ] Bench: this is a placement change. Run
  `/home/ben/work/placemat/.venv/bin/python fixtures/bench.py` once, at
  the end, and put its tally in the commit message.
- [ ] Commit "A link wait never outranks the waiting item's priority".

### Finish

The coordinator merges, runs the full suite, releases, notifies the
sessions (reload the skill), and runs the bench.
