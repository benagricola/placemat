# KRT --connections and a stated bus: design research

Read-only research for step 1 of 0.100 (routing phases, spec
docs/superpowers/specs/2026-10-06-routing-phases-design.md). Nothing in KRT or placemat was changed.

Paths: K = ~/work/KRT-upstream at c98d38eb (branch `placemat/upstream-2026-10`); P = placemat src/placemat at
175358af. Line numbers are at those commits.

## Summary

- Proposed design: `--connections FILE` restricts each named net, for this call only, to the pads of its tasks and the
  copper already joined to them; the net's other pads and copper become a protected obstacle under a private net id.
  The rest of KRT then routes an ordinary net, and a `connections` key in `--json-out` reports each task measured on
  the written board.
- Size: about 330 lines of production code (one new module, about 60 lines in route.py), about 600 lines of tests in
  three files. The stated-bus flag is about 50 more lines and one test.
- Both floor bugs are still present at the fork's HEAD and at upstream main (04a2c68d). The clearance one is
  deliberate upstream policy, so the fix is a documented fork divergence.
- Three points make the spec's design harder than it says. Tasks of one net that need different widths cannot share
  a call. The REF.PAD string encoding breaks the structured-data rule. Detection never groups a two-net bus or a
  bus routed with `--power-nets-widths`, so the stated-bus flag is required, not optional.

## 1. KRT's task model today

### A net becomes tasks

- The unit of work is the net id. `--nets` patterns are expanded in main (K/py_router/route.py:7506-7535), resolved to
  `(name, id)` (route.py:1680, routing_common.py:241-276) and filtered by `filter_already_routed`
  (route.py:1808-1810, routing_common.py:505-640). That filter uses `check_net_connectivity` (check_connected.py:1010),
  which credits tracks, T-junctions, vias, zones and pads. A net under two pads is dropped (routing_common.py:581-583).
- Every remaining net is single-ended (route.py:2033) and is routed by `route_single_ended_nets`
  (single_ended_loop.py:407). For each net the loop checks `get_multipoint_net_pads` (single_ended_loop.py:727). With
  3 or more unconnected terminals the net goes to `route_multipoint_main` (single_ended_loop.py:740), which routes
  the first MST edge; the remaining edges are tapped later in Phase 3 (`run_phase3_tap_routing`, route.py:2761-2780).
  Otherwise the net goes to `route_net_with_obstacles` (single_ended_loop.py:746, single_ended_routing.py:1938).
- Terminals come from the net's existing copper. `_get_net_endpoints_ordered` (connectivity.py:1176) groups the net's
  segments with `find_connected_groups` (connectivity.py:406-475, called at :1206, :1388, :1538) and routes from the
  largest group to the smaller one or to the unconnected pads (connectivity.py:1207-1260). Multipoint terminals are
  grouped by `get_terminal_component_info` (connectivity.py:495-523), so copper that already joins pads is never
  re-tapped. Other callers of `find_connected_groups`: `_get_multipoint_net_pads_unordered` (:1646),
  `get_stub_endpoints` (:1759), `get_net_mst_segments` (:1881), `get_net_routing_endpoints` (:1929, :1966; bus
  detection and MPS ordering use it), and net_queries.py:1590 (`get_all_unrouted_net_ids`), :1890
  (`get_unit_routing_info`), :2110 (`_compute_mps_unit_layers`).
- So KRT always tries to close the whole net. No pad or connection selection exists, and every later pass works per
  net id: rip-up, reroute, Phase 3, the end-of-run reconciliation sub-run, the final re-grade (route.py:351-470) and
  the improvement gate (route.py:6770-6866).

### Per-net width

`GridRouteConfig.get_net_track_width(net_id, layer)` (routing_config.py:602-640) chooses the width, highest first:

1. `power_net_widths[net]` from `--power-nets/--power-nets-widths` (route.py:1659-1676), floored up to `track_width`
   (routing_config.py:623-625). One scalar per net.
2. `net_layer_widths[net][layer]`: per net and per layer (routing_config.py:261, :626-634). Filled from stored
   impedance declarations (route.py:1423-1480) and from layer-scoped `.kicad_dru` width opts, the latter only when
   neither `--track-width` nor `--impedance` was given (route.py:1536-1545). No CLI flag sets it directly.
3. `net_track_widths[net]`: the net class width, only when `--track-width` was omitted (route.py:1150-1240,
   :1652-1654).
4. Coplanar and impedance layer widths, then `track_width`.

The A* margins follow the same function per layer (`track_margins_for_net`, routing_config.py:565-572), and the
emitted segments take `get_net_track_width(net, layer)` per layer (single_ended_routing.py:5379-5546, width at the
start, middle and end runs). A per-layer width therefore needs only a `net_layer_widths` entry; no stamp change.

### Neck-down

- `_route_main_connection` (single_ended_routing.py:3149-3226) retries a failed wide route. "Wide" is judged on
  `config.layers[0]` only (:3182-3186): `power_wide` when the net's width exceeds the layer width, `imp_wide` for
  impedance nets. `--no-power-tap-neckdown` turns the retry off for the whole call (:3187, route.py:7098).
- A short edge (`SHORT_POWER_EDGE_MM`) steps down a uniform scalar ladder net_w/2, net_w/4, ... to the layer width
  (`_power_width_ladder`, :2554-2565; :3190-3203). A long trunk re-routes at the layer width and necks within
  `--neckdown-length` of the pads, widening back where the full width fits (`_apply_neckdown_widths`, :5782;
  `_assign_wide_route_widths`, :5599-5636).
- With per-layer widths the gate and the ladder read only the first routing layer's width, so the ladder is uniform
  across layers.

### Board floors

- Base clearance: when `--clearance` is omitted, main sets it to the Default class clearance (route.py:7393-7399)
  with no floor at the board's `min_clearance`. The class map is built with no floor either, both when auto-read
  (route.py:7758-7762, list_nets.py:530-575) and when given by `--net-clearances` (route.py:7748-7756, "used as-is").
  placemat always passes `--net-clearances` (P/kicad/route.py `router_command`, :921-947).
- This is deliberate upstream policy. list_nets.py:91-94, :117-119, :380-386 and :729-736 call `min_clearance` "an
  unreliable edit-floor" and decline it. But the tool's own resolver states KiCad's rule: clearance is
  `max(result, rules.min_clearance)` after the class (design_rules.py:24). The router applies that floor only to pad
  overrides (routing_config.py:414-424, design_rules.py:932-944, :1111-1137). A board whose Default class is below
  `min_clearance` is routed at the class and graded by KiCad at the minimum. Step 0 recorded this on a reference
  board: class 0.125, `min_clearance` 0.15, new clearance errors (P/../fixtures/reference/manifest.json:100).
  **Confirmed at c98d38eb.** Still present at upstream main 04a2c68d (route.py:7619 there, list_nets.py:736).
- Track width: power widths floor up to `track_width`; `net_layer_widths` values are not floored
  (routing_config.py:623-634). Rule floors are `config.track_floor` / `rule_floors` (routing_config.py:370-412),
  which raise the fab floor to the board's `min_track_width` unless the escalation policy is `fab`.
- Neck floors. The single-ended terminal neck uses `config.track_floor` (single_ended_routing.py:960-962, #530). The
  diff-pair partner neck `_neck_pair_partner_grazes` uses the bare `_fab_track_floor(pcb_data)`
  (diff_pair_routing.py:1253-1255, applied at :1292-1294). That is the fab tier's nominal floor (0.0889 mm on 4+
  layers, fab_tiers.py:411-415), not the board's `min_track_width`. A third site has the same bare floor:
  `prune_grazing_segments` necking routed segments (pcb_modification.py:4181, :4200). Step 0 saw two GND segments
  necked to 0.218 mm under a 0.25 mm board minimum in a pair route (manifest.json:38). The pair log shows KRT then
  lowering the output project's `min_track_width` 0.25 -> 0.218 ("FAB FLOOR RELAXED"). placemat overwrites that
  project with the input's (`_copy_project` after each call), so KiCad grades at 0.25. The log does not name the
  neck site; `_neck_pair_partner_grazes` is the likely one, and pcb_modification.py:4200 is the other candidate.
  **Confirmed present at c98d38eb** and at upstream main (diff_pair_routing.py:1271 there). Fix: use
  `config.track_floor(net_id, layer, _fab_track_floor(pcb_data))` at both sites, as single_ended_routing.py:960-962
  does. A pair that cannot then clear falls into the existing `hard` list and fails honestly (:1300-1320).

## 2. Design for --connections

### Where to inject

`batch_route` parses the board at route.py:1094 and canonicalises it at :1119-1120. Every in-process sub-run (the
reconciliation laps) re-enters `batch_route` with this call's parameters forwarded verbatim (`_reconcile_kwargs`,
route.py:984-993), parses the board it was given and so reapplies anything done at this point. A new parameter
`connections` (the parsed file) is applied right after :1120. The work goes in a new module, py_router/connections.py.

### Steps

1. **Load and resolve** (main, before net selection). Each task is `{net, from, to, widths}`. Resolve each end to the
   pads of that footprint with that pad number on that net (`Pad.component_ref`, `Pad.pad_number`,
   kicad_parser.py:219-240). Refuse, with the task named, an unknown ref or pad, a pad not on the net, a width layer
   that is not a board copper layer, a width below the board's `min_track_width`, a net also matched by
   `--power-nets`, and `--nets` given alongside. Then set `net_names` to the task nets. Without that override main
   falls back to `*` (route.py:7530).
2. **Judge "already joined"** on the input board: one `check_net_connectivity` per net with all its pads
   (check_connected.py:1010-1060, `pad_components`). A task whose two ends share a component is `joined_before` and
   is not routed.
3. **Group per net.** Union-find over the open tasks' end components. The first group in file order whose tasks
   share one widths map is routed. Other groups of that net get status `deferred`, for the caller's next call. This
   keeps one width map and one connected terminal set per net per call, which is all KRT's net-level model can hold.
4. **Split the net.** The view of net N is its pads and copper (segments, vias, zones) in the components that hold a
   routed task end. Every other pad and copper item of N moves to a private net id (max id + 1, named for logs only):
   `pad.net_id`, `pads_by_net`, `segments`, `vias` and `zones` are re-keyed, and the id gets N's class clearance in
   `net_clearances` (route.py:1122-1146, :1626). The private net is not in `--nets`, so the sweeps, stale-copper strip
   and dead-end passes leave it alone (they are scoped by `sweep_scope_ids`, route.py:1692-1702). Add it to the
   protected set so no rip escalation takes it (protected_nets.py:297-336; the auto-candidate rule route.py:2299-2335).
   The writer copies the input text verbatim and appends only new copper by name (output_writer.py:26, :387-452,
   route.py:111-130), so the private id never reaches the file.
5. **Widths.** `config.net_layer_widths[N] = widths`, installed after the class and rule widths (after
   route.py:1545) so it wins over them; `power_net_widths` must not also name N (it would win,
   routing_config.py:623-625). A layer missing from `widths` falls back to the class width; the loader should require
   every routing layer instead.
6. **Report.** In `--json-out`, a `connections` list, one record per task in file order: `net`, `from`, `to`,
   `status` (`routed`, `failed`, `joined_before`, `deferred`, `refused`), `joined` on the written board,
   `length_mm` and the narrowest width per layer along the joining copper. Length comes from `pin_pair_path_length`
   (net_queries.py:261-330), extended to return the path's segments; it does not traverse zones, so a task joined
   only through a pour reports a null length. `joined_before` tasks get the same measurement, so a narrow
   earlier join is visible. Set the key on `_merged` just before `write_summary_file` (route.py:6662-6681), as
   `via_in_pad` is, and in the early-return writer `_write_summary_min_file` (route.py:482-513, used when every task
   was already joined, :1858-1861). Gate it on `json_out` (outermost run), not on `final_reconcile`. The
   `power_widths` block is gated on `final_reconcile` (route.py:6524-6525), so placemat's quick route
   (`final_reconcile=False`) never gets it.

### Existing copper of the net

Copper joined to a task end is in the view and is a terminal: the route starts from it (connectivity.py:1207-1260,
"route FROM established copper TO the unconnected end", :1172). Copper of N joined to neither end is an obstacle
at N's class clearance for this call. KiCad needs no clearance between items of one net, so this is stricter than
necessary. It is the smallest safe rule; reusing that copper would need the terminal derivation changed at the
call sites listed in section 1.

### What --json-out keeps

The existing keys stay whole-net. The final re-grade reparses the written board (route.py:394-401) and will list N
under `failed_multipoint`/`open_single` because its other pads are untouched by design. For a `--connections` call
the reader takes `connections`, not those keys. The improvement gate compares disconnected-pad counts per whole net
(improvement_gate.py:195-238); a connections run only adds copper on N, so it cannot trip the gate.

### Size

| Part | Where | Lines |
|---|---|---|
| Load, resolve, refusals | connections.py | 90 |
| Joined judgement, grouping, deferral | connections.py | 50 |
| Net split and restore map | connections.py | 60 |
| Per-task report (path, length, widths) | connections.py, net_queries.py | 80 |
| Flag, `batch_route` parameter, split call, widths install, net selection, two summary hooks | route.py | 60 |
| Docs: docs/connections.md, README flag line | docs | 60 |
| Flag coverage entry | tests/gui_parity/test_manifest_plan_parity.py `ROUTE_CLI_ONLY` (:735) | 2 |

About 330 lines of code in 3 files plus docs. The new kwarg in main's `batch_route` call must sit before
`collect_stats=args.stats)`: placemat's quick wrapper patches that call by two text anchors and refuses to run if
either anchor is missing or appears twice (P/kicad/route_one_round.py:29-35). For the same reason a design that calls
`batch_route` in a loop from main would break the quick route.

### Tests

KRT's layout: `tests/test_*.py`, each a standalone script that exits 0, non-zero, or 77 for a self-skip
(tests/run_all.py:1-22, :52-57). A test that shells out is classified integration and skipped by `--fast`
(run_all.py:15-18, :38). New pytest-style tests are also collected (pytest.ini). Helpers: `tests/synth.py`
(`make_pcb`, `make_pad`, `make_seg` for in-memory boards; `board_text`, `footprint_text`, `write_board` for files)
and `tests/run_utils.py` (`check(argv, refuse=...)`, which tells a refusal from a crash, :139; `evidence`, :183). The
model for an end-to-end width test is tests/test_1033_power_width_disclosure.py, which writes a board as text
(:280-325) and runs route.py with `--json-out` (:331-350); it takes 10 s here.

1. `tests/test_connections_unit.py` (fast, in-memory): each refusal by its reason; the split puts the right pads and
   copper on each side, including a zone; `joined_before` judged through a via and through a zone; two groups on one
   net give one routed and one `deferred`; tasks with different widths on one net give `deferred`.
2. `tests/test_connections_route.py` (integration): a net with pads A, B, C on two layers. `--connections` A-B with
   `{F.Cu: 0.5, B.Cu: 0.3}` joins A and B, leaves C with no new copper near it, and lays new copper at the asked width
   on each layer. A pre-laid stub from A is used as the start. The record carries `routed`, `length_mm` and the
   narrowest width per layer. A second run asking A-B again reports `joined_before`. The private net name appears in
   neither the output `.kicad_pcb` nor the `.kicad_pro`. The `connections` key is written with
   `final_reconcile=False` (in-process `batch_route`). A run whose tasks are all joined writes the key through the
   early return.
3. The floor fixes: a board whose Default class is below `min_clearance` routes at the minimum; a pair that grazes
   necks no lower than the board's `min_track_width`.

### Suite

- `python3 tests/run_all.py` runs 761 test files, 258 of them integration (`--list` at c98d38eb). CLAUDE.md says
  about 40 minutes on one laptop for ~594 files (K/CLAUDE.md:319-325), so expect longer now; I did not run it. The
  default is 4 parallel jobs (run_all.py:13); use `-j 2`, or name terms (`run_all.py connections bus floor`) while
  developing. CLAUDE.md's Modal fan-out (:319-330) is upstream's cloud and is not for fork work.
- `tests/test_route_flag_plan_coverage.py` (fast) fails on any new route.py flag that is neither replayed through a
  GUI plan nor listed in `ROUTE_CLI_ONLY` with a reason.

## 3. Bus mode

- `--bus` (route.py:7139-7148) sets `bus_enabled`. Detection runs in `route_single_ended_nets` over the nets of the
  call (single_ended_loop.py:463-481):
  - `detect_bus_groups` (bus_detection.py:39-150) takes two representative endpoints per net
    (`get_net_routing_endpoints`, connectivity.py:1912). It finds the largest clique of sources or of targets within
    `--bus-detection-radius` (default 5 mm, routing_defaults.py:189), then splits the clique by the other end at twice
    the radius (bus_detection.py:95-120). Groups below `--bus-min-nets` (default 2) are dropped.
  - `filter_bus_groups_geometric` (bus_detection.py:316-376, on unless `KICAD_BUS_STRICT=0`) keeps a group only if
    at least 3 members (fixed `min_members=3`, independent of `--bus-min-nets`) run at least 5 mm, within a cos 0.9
    cone and a length ratio of 1.5. Members are skipped if they are in `power_net_widths` (:347-353) or have under 2
    pads.
  - `plan_bus_corridors` (bus_corridor.py:78-95) can demote a group whose corridor needs too many layer changes;
    demoted members route as plain nets (single_ended_loop.py:527-541).
- Consequences for the spec's "one call per bus, so detection groups just that bus": a two-net bus (an I2C pair) is
  never a bus; a bus shorter than 5 mm is never a bus; a bus phase whose width goes through `--power-nets-widths`
  loses every member to rule 4. The summary has no key naming the groups found, so placemat cannot tell from
  `--json-out` whether a call routed as a bus.
- Smallest stated-bus flag: `--bus-nets NET [NET ...]`, repeatable, one group per use, implying `--bus`. Where
  detection runs (single_ended_loop.py:466-481), build each stated group as a `BusGroup` directly. Members are the
  stated nets present in the call, ordered by `_order_nets_by_position` (bus_detection.py:204), with endpoints from
  `get_net_routing_endpoints`. Detection and the geometric filter are skipped for those nets. Corridor planning and
  its demotion stay, as upstream does. Add a `bus_groups` summary key: name, nets, `stated` or `detected`, demoted.
  About 50 lines in route.py, routing_config.py (one field), single_ended_loop.py and bus_detection.py, plus a
  `ROUTE_CLI_ONLY` entry. Test: a two-net group, which detection refuses, is routed as one group and named in
  `bus_groups`.

## 4. The fork's state

- Checkout: ~/work/KRT-upstream, branch `placemat/upstream-2026-10` at c98d38eb, up to date with
  `fork/placemat/upstream-2026-10`; working tree clean apart from the untracked `.venv/`. Remotes: `fork` =
  benagricola/KiCadRoutingTools, `origin` = drandyhaas/KiCadRoutingTools. VERSION 0.23.0.
- Distance: 22 commits on top of upstream 770363bb (2026-10-02). Upstream main is at 04a2c68d, 110 commits past that
  base; those commits change 609 lines over route.py, routing_config.py, single_ended_loop.py, diff_pair_routing.py and
  connectivity.py (`git diff --stat 770363bb 04a2c68d`), including pairwise-clearance work (#1131-#1137) and a pair
  coupling-gap floor (53bbeb7f). Neither floor bug is fixed there.
- Other worktrees of the same repo: KRT-dev, KRT-align, KRT-fan, KRT-escape, KRT-agent, KiCadRoutingTools (`git
  branch -vv`). KRT-dev's `.venv` is a symlink to KiCadRoutingTools/.venv and it has its own built
  `rust_router/grid_router.so`, which is gitignored (.gitignore:5) and must be built per worktree (build_router.py).
- placemat invocation: router dir = `[route] router_dir`, else `$KRT_DIR`, else ~/work/KRT-upstream
  (P/kicad/route.py:25-39). Interpreter `<router_dir>/.venv/bin/python` (Python 3.12.3), script
  `py_router/route.py`, or `kicad/route_one_round.py` for a quick route, which execs route.py with
  `final_reconcile=False`. Pairs run `py_router/route_diff.py`. Each call runs with cwd = router dir and env
  `KRT_DIR` (P/kicad/route.py:1078-1082, :1129, and the `subprocess.run` calls in each stage).
- ~/work/KRT-upstream is the router every placemat session uses live. Build the change in its own worktree on a
  branch off `placemat/upstream-2026-10`, point a test placemat at it with `KRT_DIR`, and move the
  `placemat/upstream-2026-10` checkout only when it is released.
- `route.py --capabilities` / `krt_capabilities.py --require route.py:--connections` lets placemat refuse an old
  router by name (krt_capabilities.py:1-25).

## 5. What the phases need beyond the spec

| Need | KRT today |
|---|---|
| Layers per phase | Yes, per call: `--layers`. Unlisted copper layers are appended at the forbidden cost, so vias still span them (route.py:1291-1310). |
| One width per net, all layers | Yes: `--power-nets-widths` (scalar). It also removes the net from bus detection (bus_detection.py:347). |
| Width per layer, whole net | No flag. Only via `.kicad_dru` layer opts (route.py:1536-1545). The connections file could accept a task-less entry `{net, widths}` meaning the whole net, about 10 more lines. |
| Width per connection | No; `--connections` adds it, one width map per net per call. |
| Neck-down off per phase | Yes, per call: `--no-power-tap-neckdown`; length and taper flags too (route.py:7098, :7115-7118). |
| Per-net outcome in JSON | Partly: `routed_single`, `failed_single`, `open_single`, `failed_multipoint` (route.py:4301-4330) are whole-net; per-net shipped width only for power nets and only with `final_reconcile` (route.py:6524-6631). |
| Per-task outcome | No; `--connections` adds the `connections` key. |
| Stated bus | No; see section 3. |
| Bus membership in JSON | No; `bus_groups` key in section 3. |
| Spacing at each net's own clearance | Yes, by one call per clearance, as placemat's class stage does (routing_config.py:473-485). |
| Board floor on clearance and neck width | No; the two bugs in section 1. |
| Phase closure | Not KRT's: the spec judges it by a DRC after the phase, so each phase adds one kicad-cli DRC run in placemat. |

## 6. Where the spec's design is wrong or harder than stated

1. **Different widths on one net need more than one call.** KRT holds one width map per net per call
   (routing_config.py:602-640). Under `width = "current"`, `current_paths` gives every pair of carriers on a net, at
   the lesser current of each pair. A net with two high-current carriers and one low-current tap therefore has a
   wide pair and two narrow pairs. The spec's single file per phase does not fit. With the `deferred` status above,
   placemat repeats the call until nothing is deferred. It orders tasks widest first, so the narrow taps join the
   wide copper rather than the reverse.
2. **"Already joined" ignores width.** A pair joined by narrow copper (an earlier tap, or a later phase run first) is
   skipped as joined, and the wide connection is never laid. The report gives such tasks their narrowest width, so the
   phase's width judgement (spec "What is reported") flags them. Phase order still decides the outcome. The spec
   should say that a wide phase runs before any phase that can join the same pads narrowly.
3. **The ends are strings to parse.** `from: "REF.PAD"` is a string another program splits. The user's rule (and the
   spec's own "Connections are structured tables, never strings") calls for `{"ref": "J3", "pad": "2"}`. Pad numbers
   may repeat within a footprint; resolve an end to every pad with that number.
4. **Sibling pads of the same footprint on the same net.** A MOSFET's drain pins or an IC's supply pins are separate
   pads of one net. Under the split they become obstacles beside the named pad, at N's class clearance. The other
   choice is to put them in the view, so the call also joins them to the end. This is a decision for the user. I
   would put them in the view: they carry the same current, and the extra copper is short.
5. **"May use the net's existing copper" holds only for copper joined to a task end.** Other copper of the net is an
   obstacle for that call (section 2). Reusing it means changing terminal derivation at about ten call sites.
6. **Whole-net keys will read as failures.** KRT's re-grade and failure lists stay whole-net, so a connections call
   reports its net as open. placemat must read `connections` for a connections call.
7. **Stated buses are needed in practice.** See section 3: two-net buses, short buses and width-set buses are never
   detected.
8. **The clearance fix contradicts upstream on purpose.** Upstream declines `min_clearance` as unreliable
   (list_nets.py:91-94, :729-736). The fork applies it because placemat writes the project and KiCad grades by it.
   The floor has to cover the base clearance (route.py:7393-7399) and the map placemat passes with
   `--net-clearances` (route.py:7748-7756), which is otherwise used as given. Document it in the code as a divergence
   from upstream, with the reason.
9. **The quick route constrains main.** The `--connections` work must stay inside `batch_route`, behind the one call
   in main that P/kicad/route_one_round.py:29-35 patches.
10. **Upstream drift.** The fork base is 110 commits behind upstream main and those commits touch the same files
    (section 4). Building on the fork branch as the spec says is right; a later rebase onto upstream will conflict in
    route.py and single_ended_loop.py.
11. **Pours as zones.** placemat's island stage turns a net's filled copper into zones so KRT credits them
    (P/kicad/route.py `pours_as_zones`). KRT's zone credit is its fill model, not KiCad's fill (routing_common.py:524-530,
    the #572 note), so a task KRT judges `joined_before` through a pour can still be open in placemat's DRC. The phase's
    DRC catches it; the task is not retried in that call.
