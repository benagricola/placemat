# Straighter routes: the router's turn cost

Date: 2026-09-29
Status: approved 2026-09-29
Source: a board's PLACEMAT_GAPS.md, 2026-09-29 "how jagged the kept routes
are": 3262 bends over 2279 mm on 71 kept nets; SDA 195 bends in 100 mm.
The user, 2026-09-29: "we're using it quite naively"

## The problem

a whole test board's SDA is 231 segments over 133 mm, joined almost entirely
by 45-degree kinks: a staircase along the line between its pads, where a
person would draw a straight run, one 45 and another straight run.

The router prices a straight grid step at 1000 and a direction change at
`turn_cost` x the turn's eighths / 2, with `turn_cost` 1000 by default
(KiCadRoutingTools `rust_router/src/router.rs:750-767`, `types.rs:18-20`).
A 45-degree kink therefore costs half a grid step, 0.05 mm of path. Every
path using only the two headings either side of the line to the target is
the same length, so the search, weighted toward that line (heuristic 1.9),
stair-steps along it for almost nothing. Placemat passes no turn cost.

The router's smoothing pass (issue #536, which placemat's quick route turns
off) does not remove it: SDA and SCL routed alone on a copy of the core came
out identical with and without it.

## Measured

A copy of a whole test board with every route stripped, routed whole as
placemat's quick route does (F.Cu, In2.Cu, B.Cu; pour nets excluded;
smoothing on in every row but the first):

| turn cost | closure | open | turns per 10 mm | copper | vias | seconds |
|---|---|---|---|---|---|---|
| 1000 (today, no smoothing) | 66.0% | 89 | 12.6 | 2093 mm | 224 | 1332 |
| 10000 | 66.4% | 88 | 6.7 | 1941 mm | 222 | 867 |
| 20000 | 66.8% | 88 | 5.8 | 1879 mm | 222 | 715 |
| 50000 | 64.9% | 92 | 5.6 | 1962 mm | 238 | 1463 |

At 20000 every measure is as good as today or better. Above it the router
starts trading turns for detours and vias. SDA and SCL routed alone came out
at 15.4 and 11.6 turns per 10 mm today, 8.9 and 7.0 at 20000.

## The change

1. **`[route] turn_cost`, 20000 by default**, passed as `--turn-cost` to
   every router pass: pairs, island nets, the main pass.
   - This diverges from the router's default of 1000 on purpose, on the
     measurements above, and says so where it is passed.
   - 1000 gives the router's own behaviour back.
2. **Smoothing on**, as the router defaults. Placemat stops passing
   `--no-smoothing` in a quick route. `[route] smoothing = false` passes it
   again.
3. **`[route] router_args = [...]`** is appended to every pass's command
   line, for the router's other tuning (`--direction-preference-cost`,
   `--heuristic-weight`, `--bus`, `--via-cost`, ...). A flag placemat sets
   itself (`--nets`, `--layers`, `--escalation`, `--keep-input-copper`,
   `--turn-cost`) is refused when the settings load, since the setting
   names it.
4. **Re-routing what is already kept**:
   - `placemat routes <script> --release-all` drops every kept entry, as
     `lock --release-all` does for the lock, so the next
     `route --adopt-all` lays them again at the new cost.
   - The release notes say that kept routes stay as they were until then.

## Verification

- The command line of each pass carries `--turn-cost 20000` by default, the
  setting's value when set, no `--no-smoothing` unless `smoothing = false`,
  and `router_args` at its end. A placemat-owned flag in `router_args` is a
  SettingsError. (No router run.)
- `routes --release-all` empties the routes file.
- A quick router run on the breakout: completes with no fewer closed items
  than at 1000 (needs the router).

## Not in scope

- Bus routing for multi-pad nets such as I2C: the router pairs bus nets by
  their first two endpoints (`py_router/bus_detection.py:61-63`), so SDA and
  SCL were not detected as a bus. That is the router's to change.
- A per-net shape report: `placemat nets` (backlog).
