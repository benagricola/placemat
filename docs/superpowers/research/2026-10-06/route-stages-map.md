# Route stages map (placemat main, read-only)

Paths: P = /home/ben/work/placemat/src/placemat ; K = /home/ben/work/KRT-upstream

## 1. Stage pipeline (P/kicad/route.py, `_route_board` 1006-1283)

Order: setup -> pairs -> islands -> classes -> main -> postprocess (guards removed, fill, dangling cleanup, DRC, report).
Resume/digest machinery: P/kicad/route_state.py (STAGES = pairs, islands, classes, main; line 17).

Setup (1042-1105): copies board to work/in.kicad_pcb (+ .kicad_pro/.kicad_dru), `lock_copper` (1054; locks every track, via, copper PCB_SHAPE, def 372),
drc_before (1066), `guard_footprint_copper` (1069), `guard_partial_pours` (1070, rule-area guards over partial inner pours of excluded nets),
excluded = exclude_nets | islands (1063); counted = excluded - islands (1064; nets the closure leaves out).
Base digest (1075): board/.kro/.dru file digests, sorted exclude_nets, islands items, layers, quick, iterations, probe, router version, placemat version,
all `route_*` settings except router_dir (json of cfg). Each stage digest chains: d_pairs -> d_islands -> d_classes -> d_main (1110,1137,1182,1204).
`state.result(stage, digest)` returns saved result (route_state.py 79-82); on miss `state.drop_from(stage)` deletes that stage and later stages' files (FILES map line 20-23) and reruns.
`state.record(stage, digest, result)` after finish. Whole stages only; nothing inside the main pass is kept. `--no-resume` -> RouteState wipes work dir (route_state.py 52-53).
`resumed` list on the report names stages taken. Resume check also needs the stage's board file to exist (1112, 1140, 1185); main needs router_out.kicad_pcb (1207).

### pairs (route_pairs 636-719)
- Nets: `pairs.board_pair_list(geometry.netclasses)` (1093): diff pairs from net classes (diff_pair_width/gap in the .zen). No selection setting.
- Router: separate script py_router/route_diff.py (667), `pair_command` (521-539): `--nets <aliases> --layers L --escalation off --keep-input-copper --turn-cost`, optional `--diff-pair-gap`, `--track-width` (route_diff_pair_gap/width settings), `--max-iterations`, `--max-probe-iterations`, `--net-clearances`, + `[route] pair_router_args`.
  Nets renamed to base_P/base_N aliases in a copy (pair_aliases) because the router pairs by suffix; renamed back after (rename_nets 600).
- Layers: `[route] pair_layers` table (resolve_pair_layers 542, pair_layer_groups 571): one router call per distinct layer list, each on the previous call's output.
- Keep fixed: after each call `lock_copper(out)` (707) and again on final pairs.kicad_pcb (718). Copper written into the board, locked.
- Records: state "pairs" {board, pairs (Pairs.to_dict), seconds}. route.json: `pairs` (coupled/partial/failed/single_ended/routed_nets), `pair_layers`, `pair_layers_refused`. Logs pairs.log, pairs_N.log. The pair router writes no summary json.

### islands (route_islands 909-953)
- Nets: `[route] islands` (array of strings "NET", "NET=WIDTH", "NET=WIDTH@F,In2,B") + `route --islands`; parse in P/settings.py `_island_entry` 654-695, `parse_islands` 696, `parse_island_layers` 701. CLI merge cli.py 727-733 (bare NET keeps width and layers from setting). `islands_on_board` (740) drops names the board lacks -> `islands_missing`.
- Router: one call per island net, sorted (919): `router_command(..., nets=[net], widths={net: w})` (880-906) -> `--nets NET --layers <own layers or route layers> --escalation off --keep-input-copper --turn-cost [--power-nets NET --power-nets-widths W] [--no-smoothing] [--max-iterations] [--max-probe-iterations] [--net-clearances] <router_args> --json-out islandsN_summary.json`.
  Per-net layers = the `--layers` given for that call; the router appends other board layers with forbidden cost, so vias still span them (comment 927-931). Neck-down is the router's default (no placemat flag; user may put `--no-power-tap-neckdown`, `--neckdown-length` in router_args).
  Width: only via --power-nets/--power-nets-widths for that single net. Clearance: map from net_halos/class clearances (--net-clearances).
  Before each call: other islands' partial pours guarded; `pours_as_zones(net)` (782) turns the net's filled copper graphics into zones so the router sees them as joining pads (KRT credits zones); `pours_back` (834) restores after.
- Keep fixed: `lock_copper(out)` (945); next call reads that board. Final islands.kicad_pcb with island pour guards dropped (952).
- Main-pass: island nets are in `excluded` (1063); main pass never reroutes them.
- Records: state "islands" {board, breaches, pours, seconds}. route.json: `islands` {net: [apart before, apart after]} (1254, from drc_before/after open_nets), `islands_missing`, `island_layers`, `widths` records (board_widths, stage "islands").

### classes (class_stages 967-980, route_class_stages 983-1003)
- Nets: `routed_later` (1178) = nets with >=2 pads not excluded/pair-routed; of those, nets whose clearance in the clearance map (net_halos.merged/class_clearances from net classes, + halos) is above the Default's (`routing_clearance` 956). Grouped per distinct clearance, widest first. Not user selectable; derived from net classes (+ `[route] net_halos`). Reason: router spaces a whole call at the max clearance among its nets (KRT set_net_clearances).
- Router: one call per clearance, `router_command(nets=nets)` with no widths; same flags; `--json-out classesN_summary.json`; class widths come from the .kicad_pro netclasses/.kicad_dru via the router's own auto-read (KRT route.py 1176-1230).
- Keep fixed: `lock_copper(out)` (1001), copper in the board.
- Records: state "classes" {board, seconds}. route.json `class_stages` [{clearance_mm, nets: {net: [open items before the whole route, after the whole route]}}] (1257; NOT per stage, both numbers are board-wide from drc_before/drc_after).

### main (1204-1230)
- Nets: `--nets * !EXCL...` (router_command 891) where excluded = exclude_nets | islands | pairs.routed_nets | staged class nets (1214). `*` + `!name` patterns, KRT net_queries.py 20-50.
- Router: `script` = route_one_round.py (quick, final_reconcile=False; P/kicad/route_one_round.py, execs KRT route.py with one keyword) or KRT py_router/route.py (full). Flags as above, no `--power-nets`; `--json-out router_summary.json`; log router.log, raw_out router_out.kicad_pcb.
  Per-net widths: from net classes via the router's auto-read, not from placemat.
- Keep fixed: n/a (last stage). `--keep-input-copper` keeps earlier stages' (locked) copper from router cleanup.
- Records: state "main" {board, seconds}. Digest d_main includes excluded|pairs.routed_nets|staged (1204).

### postprocess (1231-1283)
raw_out -> routed.kicad_pcb; `remove_guards` (356), `fill_zones` (391), `remove_dangling_router_copper` (route_cleanup.py), drc_after, `score()` (60) -> closure/closure_clean, `router_breaches` (1295), widths, `route.json` written at 1282 (`RouteReport.as_dict` 210-225).

### route.json fields (RouteReport 73-138, as_dict 210)
valid, closure, closure_clean, open_before, open_after, open_nets, shorted, violations, excluded (= counted), layers, seconds, router_version, drc_after, routed_pcb, log, quick, invalid_reason, keepout_breaches, pairs, plane_layers, pours_kept, islands, islands_missing, island_layers, class_stages, resumed, record, widths, pair_layers(+_refused), net_halos(+_missing, _trapped), dangling_removed.
Per-stage open counts exist only for islands (before/after) and class stages (board-wide before/after). Main and pairs have no own before/after.
Events/record: P/route_progress.py (rev.begin/end/resumed per stage name "pairs","islands","classes","main").

## 2. Settings `[route]` (P/settings.py)
Fields: route_router_dir 365, route_quick 367, route_max_iterations 369, route_plane_share 371, route_turn_cost 374, route_smoothing 375,
route_router_args 377 (tuple of strings), route_pair_router_args 379, route_pair_layers 381 (dict "table", subtable `[route.pair_layers]`), route_net_halos 383 (subtable `[route.net_halos]`),
route_islands 385 (tuple of strings), route_diff_pair_gap/width 387-389, route_adopt_tolerance 391.
- No `[route] exclude` setting. Excludes are CLI only: `route --exclude` (cli.py 81), `run --route-exclude` (cli.py 32), plus plane nets always added (cli.py 724-740, runner.py 752 `plan.plane_nets`, explore.py 743 `p.plane_nets`).
- Plane nets: placemat decides, not a setting. `plane_nets_of(pcb)` (route.py 228: nets with a board-level zone or filled copper polygon, not inside a group) for `placemat route`; `plan.plane_nets` (layout.py 757: nets with Pour/Zone ops) for run --route and explore. `route_plane_share` (default 0.9) only sets when a pour counts as "whole" for guarding (guard_partial_pours 308).
- Class stage: no setting at all; derived (see above). Only net_halos and netclass clearances feed it.
- router_args refusal list `_ROUTER_OWNED` settings.py 721-723: --nets --layers --escalation --keep-input-copper --turn-cost --smoothing --no-smoothing --power-nets --power-nets-widths --max-iterations --max-probe-iterations --json-out --net-clearances. Validation 828-836.
  `--clearance`, `--track-width`, `--neckdown-*`, `--no-power-tap-neckdown`, `--via-size`, `--layer-costs` are NOT owned, so user can pass them but they apply to every pass.
- TOML parsing: `_flatten` (settings.py 916-946): a section's value that is a dict is accepted only if "section.key" is in `_SUBTABLES` (609: check.limits, drc.severities, facts.boards, route.pair_layers, route.net_halos), else SettingsError. A TOML list falls to `out[name]=value`; `_coerce` (949) turns a list into a tuple when the field is declared `tuple`. `_validate` (801-870) checks "tuple" -> must be list; per-setting extra checks by name (router_args strings 828, pair_layers 837, net_halos 845, islands 849).
- Arrays of tables: no existing setting takes one (all tuple settings hold strings/numbers: lines 287-293, 333-335, 377-385, 409). Mechanically a `[[route.phase]]` would hit `_flatten` with a list of dicts: not a dict, so it takes the list path, becomes a tuple of dicts with NO per-item validation, but needs a new field `route_phases: tuple`, a name-keyed validator in `_validate`, and an addition to the "key must be two words" convention (`split_key` 600: section = text before first underscore, so `route_phases` -> `[route] phases`; an `[[route.phases]]` header yields data["route"]["phases"] = list of dicts). `Settings.json()` (line ~880-890 region, `sorted(v.items()) if dict else list(v) if tuple`) will emit it as list of dicts: fine for digest (route.py 1078 digests all route_* keys). Per-script override `[scripts."x.py".route]` reuses `_flatten` (996-1010) so would work the same.

## 3. --exclude / --adopt / --partial
- `route --exclude NET...` (cli.py 81, validated `_net_names` 706) -> `route_board(exclude_nets=set(args.exclude) | planes)` (740). Excluded nets are `--nets !NET` in main pass and dropped from the closure count (`counted`, 1064/1067). Also in base digest (1076). `run --route-exclude` (cli.py 32, 599) -> runner.route_exclude -> runner.py 752 `set(plan.plane_nets) | set(route_exclude)`; explore uses same (explore.py 743).
- `--adopt NET...` / `--adopt-all` (cli.py 95-97, mutually exclusive; script required, not a .kicad_pcb: 711) -> after route, `_adopt` (cli.py 776-824) -> `routes.adoptable` (routes.py 518) picks nets whose router copper is closed (not in report.open_nets, not in report.shorted, added copper exists); stores copper relative to pads in `<script stem>.routes.json` (routes.py `entries_from` 268, `keep` 561; coordinates as pad refs or offsets from nearest pad in part frame). Replayed each run while the parts it joins keep their relative placement; dropped with a reason when one moves (`resolve` 349, `without_kept` 483). By default (no `--no-lock`) the placed items the kept nets join are locked in the lock file (`_lock_where_it_stands`, cli.py 503).
  Adopted routes go into the placement run as copper (they are not "declared tracks" in script) and so end up in the board written for the next route.
- `--partial` (cli.py 98): only with --adopt/--adopt-all (708). In `adoptable`, a net still open keeps each island of the router's new copper that joins two pads or a pad and a plane (`islands()` routes.py 160); stored with entry.partial = True; a net can have several entries. (Separate `lock --current --partial` at cli.py 336 is a different flag: drop items that would not land.)
- Nothing in these passes per-connection selection into the router: --partial is a post-hoc filter on router output.

## 4. Carriers / current paths (P/checks.py)
- `carriers_of(geometry)` (1682-1697): {net: {ref: amps}} from `Pm.I` facts (`facts()`; `fact.current_a` for the whole part, or `fact.currents` per-net map `Pm.I: vin:3A fb:1mA`, FactSet lines 68-69). Granularity is the PART (ref), not the pad: max over the part's pads on the net.
- `current_paths` (1739-1790): per net, if one carrier -> "not judged"; else `_pairs(geometry, net, on, ...)` (1524) which enumerates every two carriers `(a, b)` for a<b over sorted refs (1556-1557), the widest copper route from any pad of a to any pad of b at the lesser of the two currents; returns judged tuples (width, need, amps, from, to, fill, neck point, length, basis, layer shares), `unmeasured` (pad/via-only routes) and `apart` (no copper joins yet). The Verdict reports only the WORST route per net (facts from/to/amps).
- Pad granularity exists: `_pairs(..., by_pad=True)` takes carriers {"ref.number": amps}, each pad its own end (used by `pour_current` 1713 via by_pad). `carriers_of` itself does not yield pad keys; a caller would build the by_pad dict from fact.currents + the part's pads. So pad-to-pad carrier pairs per net: yes via `_pairs(by_pad=True)` (returns every pair in `judged`/`apart`, not only the worst), but today nothing calls it with pads except pour_current. Mechanism: pairs = all combinations of carriers; an unjoined pair appears in `apart`.
- Callers of carriers_of elsewhere: route_widths.stated_currents (route_widths.py 233: max amps per net, for findings).

## 5. Width judging (P/kicad/route_widths.py)
- Router requested widths exist only for island nets given a width (`--power-nets-widths`). Everything else uses netclass widths, never judged against current in the route.
- Two sources of records, merged in `_route_board` 1261-1270:
  a) `board_widths(routed_geometry, islands, rise_c, copper_oz, neck_allowance(router_args))` (route_widths.py 138-): judged on the routed board, for island nets with a width: any track narrower than the asked width on any layer counts, except the router's pad neck-down (`_neck_lengths` 86, within `--neckdown-length` + taper, default 2.5+0.5 mm, KRT defaults mirrored at 76-77; `--no-power-tap-neckdown` -> 0). Record keys: net, stage "islands", requested_mm, delivered_min_mm, length_under_mm, length_mm, share, declared, max_a, bottleneck_mm/layer, amps None, necks_mm, neck_limit_mm, layers [{layer, need_mm, by "asked", under_mm, min_mm}]. `by` field has "current" reserved but nothing sets it.
  b) `read_widths(work, islands, len(stages))` (route_widths.py 60-): every stage's router summary JSON (islandsN/classesN/router_summary.json): `power_widths` (only present with `--power-nets-widths` and final_reconcile, so NOT in quick route) and `design_rules.narrowed[]`; kept only for nets not judged on the board.
- `findings_of(records, stated)` (route_widths.py 215-): Finding C.ROUTE_WIDTH, critical if `declared` (script gave a width) or if `max_a` < stated current (`stated_currents`, from Pm.I, per net, max over parts); else warning. Findings emitted in cli.py 755-757 / runner.py 776-783; `has_findings` (route.py 140).
- Current-vs-width judgment for the net as a whole is left to `check current-path` (checks.py) on the routed board; the route-time check does not run it.

## 6. Closure and summary computation
- `run_drc(pcb_in, drc_before.json)` / `run_drc(pcb_out, drc_after.json)` -> `.open_nets` {net: open items} (unconnected items by net). Before: excludes `counted` (excluded minus islands) (1067). After: same filter (1241). `score(open0, open1, violated_nets)` (route.py 60-69): closure = 1 - sum(open1)/sum(open0) (1.0 when none); closure_clean counts a net with DRC violations in `shorted` as still at its before count. Violated nets come from drc_after violations by net (`_violations_by_net`).
- Per stage: islands {net: (before, after)} from the same board-wide open_nets (1254); class_stages nets {net: [open0, after]} (1257). No per-stage DRC is run; there is one DRC before and one after the whole route.
- Summary line: `RouteReport.summary` (157-208) built from the fields.

## 7. explore --route-best (P/explore.py)
- Setting `explore_route_best` (settings.py 315); `route_best` arg (explore.py 911, 952); a routing worker process `_route_work` (explore.py ~690-745): per seed writes the variant board (`router.write` -> `_write_variant`), optional pin remap, then `router.route(pcb, d/"route", exclude_nets=set(p.plane_nets)|set(routing.exclude), quick=True, resume=routing.resume)` (743) = `VariantRouter.route` (228) = `route_board(pcb, work, exclude_nets, quick, resume)` with NO islands/layers args, so `[route]` settings drive everything (islands, pairs, class stages). Entry gets `closure_clean, closure, open_before, open_after, valid` straight from the RouteReport (745-746), or `error`.
- Best taken by `_taken` (explore.py 1047-1053): max closure_clean, ties by better run score, then seed. Messages 1390-1398.
- So any new phase design changes explore routing time and closure; closure_clean must stay a single board-wide number from RouteReport.

## 8. Declared copper reserving room during placement (P/layout.py)
- `board.track(net, points, layer=, width=, ...)` layout.py 5718 (width: `_width(name, width)`; lane start takes the lane's width). Declared copper is a `CopperIntent` in `self._copper` (key "track N" / "via N" / "pair" / "pour" / "plane" / "finger"). Setting `place_copper_room` (settings.py 118, default true) and `place_copper_room_tolerance`, `place_firm_passes`.
- Mechanism: `_ROOM_KINDS = ("track","pair","via")`, `_ROOM_KINDS_AFTER` adds "pour" (layout.py 2757-2758). `_dry_rooms` (2838) plans each declaration's ops via `c.plan(ctx)` without committing and turns Track/Via/Pour ops into `Shape`s owner "room <key>". After each searched item lands, `_rooms_after` (2902) plans the declared copper whose ends are all placed and `occ.set_rooms(occ.rooms + shapes)` (occupancy.py 998): provisional obstacles the search keeps clear of (`occ.rooms_apply = True`, layout.py 8066). `_redo_check` (2783) with `_squeezers` (2874) re-runs passes (firm passes, `_resolve` ~7590-7620) so Beside parts back off to the box standoff where room copper would meet another declaration's copper or a placed pad; `FIXED_ROOM_UNSETTLED` finding if the plans move more than tolerance across passes. At the end `occ.set_rooms([])`, real copper planned (8062).
- A track is therefore reserved by width and path when ALL of its end parts are placed; before that, nothing. A routed-later phase (a net not declared) reserves nothing: the room-keeping works only for declared copper. A declared track's width is what is reserved; routed phase widths would need a separate mechanism.
- "power legs" (user term) are declared `board.track` per the 2026-10-06 trial doc at /home/ben/work/placemat/.tmp/cell-turn/fairing/electronics/docs/decisions/layout/core-routed-power-legs-trial-2026-10-06.md (islands trial: routed at one width per net, 2.6x under-rated In2 runs; closure 87.4% declared vs 87.7% islands with neck-down).
- Written declared copper lands in the board the route copies; `lock_copper` locks it so the router keeps it (route.py 1054).

## 9. KRT per-call capabilities (K/py_router/route.py, K/docs/power-nets.md)
Args (route.py 6958-7330):
- Net selection: `--nets` (globs, `!NAME` excludes, `\!` escapes active-low names; net_queries.py 20-50; sheet-path-aware match 55+), positional patterns, `--component REF...` (all nets of those parts), `--group/--group-by/--group-scope`. No pad or connection selection.
- Widths: `--track-width` (global default; default from Default netclass), per-net: auto-read from sibling .kicad_pro netclasses and .kicad_dru (`design_rules.DesignRules`, route.py 1176-1230; per-net per-layer widths possible when a .kicad_dru rule has layer-scoped track_width opt -> `net_layer_widths`), `--power-nets PAT... --power-nets-widths W...` (fnmatch patterns, first match wins, raised to at least --track-width, route.py 1650-1668; docs/power-nets.md). One width per net unless the .kicad_dru gives per-layer widths. `--impedance` derives per layer.
- Neck-down: automatic retry at layer default width for failed power-net edges; `--neckdown-length` (default 2.5), `--neckdown-taper-length` (default 0.5), `--no-power-tap-neckdown` (route.py 7098, 7115-7118). Global flags, not per-net.
- Clearance: `--clearance`, `--net-clearances JSON` {net: mm} (cross-class floor; the router spaces a call at the max among nets routed), `--hole-to-hole-clearance`, `--board-edge-clearance`, `--same-net-pad-clearance`.
- Layers: `--layers` and `--layer-costs` (one per layer; negative = forbidden: no track but vias may span; route.py 7292, 1285-1312) are per CALL, not per net. Per-net layers = one call per net (placemat's islands do this).
- Existing copper: `--keep-input-copper` (read-only input copper), `--rip-existing-nets PAT` (committed tracks are otherwise never ripped), `--force-reroute` (needs explicit --nets), `--undo`, `--preview`.
- Pad-to-pad subset: NOT supported. KRT groups a net's pads by existing copper connectivity (connectivity.py ~500, find_connected_groups; Case 4 1520-1545) and connects the groups (multipoint MST, tap edges); it always tries to close the whole net. A way to restrict: pre-lay copper that joins the unwanted pads (they then form one group), or give the net's zone (island trick: `pours_as_zones`), or route in a copy where the pads of interest are on a renamed net (as route_pairs renames, route.py 600). Placemat has no mechanism for a connection subset today.
- Other per-call: `--ordering`, `--direction`, `--bus*`, `--max-iterations`, `--max-probe-iterations`, `--escalation`, `--turn-cost`, `--smoothing/--no-smoothing`, `--json-out` (summary with power_widths only when power nets given and final reconciliation on; the quick route skips it), `--length-match-group`, `--swappable-nets`.
