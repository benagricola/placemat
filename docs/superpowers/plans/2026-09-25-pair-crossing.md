# Pair Crossing Weighed at Placement: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** done (tasks 1-4, 345f1db 26d5666 c0229c2 a8a9601; pattern selection 82872f8); bench at each step in the commits.

**Goal:** a differential pair's P crossing its own N costs `score.pair_crossing` at placement, so the search and cleanup uncross it by a turn or a swap, and a crossed pair is reported.

**Architecture:** `placemat/pairs.py` ports the router's pair rule. Crossings (`ratsnest.crossings`, `Ratsnest`, native `Ratsnest`) take a pair map: a crossing between two partner nets weighs the pair factor (`score.pair_crossing / score.crossing`) instead of the lighter net weight. The occupancy's ratsnest and the run score pass the board's pairs; a finding reports each crossed pair.

**Tech Stack:** Python, the native Rust module (`native/src/ratsnest.rs`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-pair-crossing-design.md`

## Global Constraints

- Tunables are settings: `score.pair_crossing` (default 100, mm), validated at least zero.
- Generic wording in src, skill and migrations (no part or board names).
- Placement changes measured with `fixtures/bench.py`; tally and baseline in the commit.
- Native and Python ratsnests agree (the parity tests).
- Plain ASCII; commits carry no tool attribution.

---

### Task 1: The pair rule

**Files:** Create `src/placemat/pairs.py`; Test `tests/test_pairs.py`

**Interfaces:** Produces `pair_key(net) -> tuple | None` ((base, style) and polarity) and `pairs_of(nets) -> dict[str, str]` (each paired net -> its partner).

- [x] Failing tests from the router's own cases: `USB_P`/`USB_N`, `CLK+`/`CLK-` (not with `CLK_N`), `D0P`/`D0N`, `USB_DP`/`USB_DM`, `DQS0_t`/`DQS0_c`, `Net-(U12-USB_D+)`/`Net-(U12-USB_D-)`, a lone `_P` with no partner.
- [x] Port `net_queries.extract_diff_pair_base` (KiCadRoutingTools), cited in the docstring.
- [x] Commit.

### Task 2: Crossings weigh a pair's own crossing

**Files:** Modify `src/placemat/ratsnest.py`, `native/src/ratsnest.rs`, `native/src/lib.rs` (binding); Test `tests/test_ratsnest.py`, `tests/test_native_ratsnest.py`

**Interfaces:** `crossings(edges, weights=None, partners=None, pair_weight=1.0)`; `Ratsnest(weights, mirror, partners=None, pair_weight=1.0)`; native `NativeRatsnest.set_partners(pairs, pair_weight)`.

- [x] Failing tests: two crossing airwires of partner nets count `pair_weight`; of non-partners, the lighter weight as now; `leaf_costs` native and Python equal with partners set.
- [x] Implement in Python and Rust; rebuild the native module.
- [x] Commit.

### Task 3: The board passes its pairs

**Files:** Modify `src/placemat/settings.py` (`score_pair_crossing`), `src/placemat/occupancy.py` (the ratsnest), `src/placemat/score.py` (the run score); Test `tests/test_pair_crossing.py`

- [x] Failing tests on a board built in the test: two identical 0402s in series on a pair, placed crossed by hints: the score's crossings term carries the pair weight; with cleanup the two swap and the crossing is gone. A 6-pad part with a mirrored pinout, rotations (0, 180), the pair crossed at 0: the search places it at 180.
- [x] Implement.
- [x] Commit.

### Task 4: The finding

**Files:** Modify the findings pass (`checks.py` or where crossings are reported); Test `tests/test_pair_crossing.py`

- [x] Failing test: a crossed pair on decided parts gives one finding naming the pair and the two parts, with the swap/turn advice.
- [x] Implement; skill line; migration note for the next release.
- [x] Commit.

### Task 5: Measurement

- [x] `fixtures/bench.py` against the baseline; tally in the commit.
- [x] Full test suite.
