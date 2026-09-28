# Routing the taps a pour does not reach

Date: 2026-09-28
Status: approved 2026-09-28
Source: the fairing board's session, 2026-09-28 (on 0.50.0): "several power
nets have small taps no pour can reach"

## The problem

`placemat route` and `run --route` leave every net with a board-level zone
or pour out of the route (0.50). On the fairing core, VSHUNT (In2 pours)
also feeds a load switch's output, a resistor behind a panel and a
converter's input track, and VBIKE (an In2 pour, 4.6 A) feeds a
supervisor's sense divider and enable pull-up. No pour reaches those pads.
Kept routes from earlier runs held the taps until a part moved; now nothing
routes them, and hand-drawn `board.track` legs break when a cell turns.

The router already treats a net's own zones as joining what they reach
(KiCadRoutingTools `py_router/connectivity.py:502` passes the net's zones to
its connectivity check), and routes each net at its netclass width read from
the board's `.kicad_pro` (`py_router/route.py:813`), with
`--power-nets-widths` as an override. Routing a pour net therefore routes
only its pads and islands the pours leave apart. What stops it is placemat
leaving the net out, and the 0.50 pour guard: a net routed for its taps
cannot have its own partial pours guarded (a rule area has no allow list),
yet those pours still need other nets kept out.

## The change

1. **`[route] islands = ["NET", ...]`** (a setting, empty by default) and
   **`placemat route --islands NET[=WIDTH] ...`** (adds to the setting):
   nets with pours whose unreached pads and islands the route joins.
   `run --route` reads the setting. `=WIDTH` (mm) overrides the netclass
   width for that net (the router's `--power-nets` / `--power-nets-widths`);
   without it the net's class width is used.
2. **Two passes.** The islands pass first: the router is given only the
   island nets, with every other excluded net's partial inner-layer pour
   guarded as in 0.50 (the island nets' own pours unguarded). Then the main
   pass, as today, with the island nets excluded and their pours guarded;
   the islands pass's tracks are locked copper in its input, as the
   differential pairs' are.
3. **The report** says, per island net, how many islands it joined and how
   many are still apart; the islands' routes are adoptable by
   `--adopt NET` like any other net's.

## Verification

- A four-layer breakout copy with a partial In2 pour of a net, one of that
  net's pads outside the pour, the net named in `--islands`: the routed copy
  has a track joining that pad to the pour's copper (a via into the pour or a
  track to a pad the pour reaches), no track of it between two pads the pour
  already joins, and no other net's track inside the pour.
- Setting and flag: the island net is routed (not excluded) in the islands
  pass and excluded in the main pass (stand-in router, as the settings test).
- `=WIDTH` reaches the router's command line.

## Not in scope

- A script-side declaration (`board.route_islands(...)`): the setting lives
  in the board's `placemat.toml`, where the route's other settings are.
