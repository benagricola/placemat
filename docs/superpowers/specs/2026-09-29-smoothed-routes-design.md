# Routes kept smooth

Date: 2026-09-29
Status: draft
Source: PLACEMAT_GAPS.md (fairing), 2026-09-29 "how jagged the kept routes
are": 3262 bends over 2279 mm on 71 kept nets; SDA 195 bends in 100 mm,
mostly 0.02-0.6 mm segments

## The problem

A quick route (the default for `placemat route` and `run --route`) runs the
router with `--no-smoothing` (`kicad/route.py:585`). The router smooths by
default (KiCadRoutingTools `py_router/route.py:6329`, issue #536: it
collapses the grid search's staircase jogs into octolinear shortcuts), and
placemat turned it off on the ground that it "costs most of the run". Every
route kept by `route --adopt` from a quick route is that unsmoothed copper.

Measured on the breakout (2026-09-29, quick route, tracks stripped):

| | seconds | segments | under 0.6 mm | length | closure |
|---|---|---|---|---|---|
| no smoothing | 37.4 | 557 | 295 | 743 mm | 80.0% |
| smoothing | 42.0 | 375 | 172 | 722 mm | 80.0% |

Smoothing costs about an eighth more time, not most of the run.

## The change

1. **Every route smooths, as the router does by default.**
   - Placemat stops passing `--no-smoothing`.
   - `[route] smoothing = false` passes it again, for a measurement where the
     time matters more than the copper.
2. **A kept entry records whether its route was smoothed.**
   - Entries written from now on carry `"smoothed": true` (or `false` under
     the setting).
   - `placemat routes <script>` marks every entry not recorded as smoothed,
     entries kept before this release included.
   - `placemat routes <script> --release-unsmoothed` releases those, so the
     next `route --adopt` routes those nets again, smoothed.
3. **`[route] router_args = [...]`** is appended to every router pass's
   command line. It carries the router's own tuning (`--turn-cost`,
   `--direction-preference-cost`, `--bus`) without placemat naming each
   flag. A flag placemat itself sets (`--nets`, `--layers`, `--escalation`,
   `--keep-input-copper`) is refused when the settings load.

## Verification

- The router's command line has no `--no-smoothing` by default, and has it
  under `smoothing = false` (no router run).
- Entries adopted by `_adopt` carry `smoothed` from the report. An entry read
  from a file without the key counts as not smoothed. `--release-unsmoothed`
  releases exactly those (pure, with a written routes file).
- `router_args` appears on each pass's command line; a placemat-owned flag in
  it is a SettingsError.
- A quick router run on the breakout: fewer segments than the table's first
  row (needs the router).

## Not in scope

- A per-net shape report (bends per mm, length against span): that belongs
  to `placemat nets` (backlog).
