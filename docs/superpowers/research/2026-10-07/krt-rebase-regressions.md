# KRT rebase regressions on test (a): esp-rust-board and watchy

Investigation of why test (a) got worse on esp-rust-board (class widths, new DRC 1 -> 2) and watchy (class widths,
clean closure 85.8% -> 61.2%) when the router fork moved from old base c98d38eb (upstream 770363bb + fork) to
placemat/upstream-2026-10b (upstream 364b4572 + fork, now 5a629cfa). No code was changed.

## Summary

- Both boards change at the same upstream commit, **8013c817** "Every obstacle builder prices a net with the same
  soft-cost sources" (2026-10-05), and within it at one of its five changes: a multipoint net whose Phase 1 main route
  is in but whose Phase 3 taps are pending now stays a stub-proximity source, so its unconnected tap pads repel the
  nets routed after it (`_stub_proximity_source_ids`, py_router/routing_context.py:137-163 at 364b4572).
- Restoring the old source set (one condition, routing_context.py:163) on the full rebased fork 5a629cfa brings both
  boards back (esp class DRC 1, watchy class 85.8%) and changes nothing else on test (a) for the worse (table below).
- The commit is a deliberate upstream change with a stated rationale and no cited corpus measurement. It is not a
  bug. Its effect here is a small change to one early route on each board, and the rest follows from routing
  sensitivity.
- watchy is not "worse on upstream alone". With deterministic uuids, upstream alone goes 53.0% -> 75.4% between the
  two bases. The fork on the old base was 85.8%, and the fork on the new base is 61.2%. The 61.2% is the router
  placing a close same-net +3V3 via pair and placemat's close-via merge refusing it, so both sides contribute.

## Method

- Worktree /home/ben/work/KRT-bisect (removed) of the KiCadRoutingTools repository. The determinism fix 5a629cfa was
  cherry-picked onto every point, so every measurement is one deterministic run. Two runs of the same tree gave
  identical numbers (fork on 411491b5, watchy, run twice).
- rust_router is identical between 770363bb and 364b4572 (`git diff --stat` empty), so one upstream build of
  grid_router served every upstream point. The fork's crate changes (6 files) are the same on both bases, so one fork
  build served every fork point.
- Measured with fixtures/reference/route_ref.py (placemat /home/ben/work/placemat/src, `--work` in the scratchpad,
  no `--update`). Both widths ran each time.
- Upstream bisected on its first-parent history (35 commits from 055fa9e1 to 364b4572).
- For watchy the fork commits were replayed onto each upstream point: the 21 fork commits as rebased
  (e4686b78..7469df17), then 02670ef3 and 5a629cfa. They applied without conflict at every point tested.

## Endpoints

All with the determinism fix.

| router | esp class | esp human | watchy class | watchy human |
|---|---|---|---|---|
| upstream 770363bb | DRC 1, vias 58 | DRC 0 | 53.0%, open 21, DRC 5 | 62.7%, open 6, DRC 5 |
| upstream 364b4572 | DRC 2, vias 56 | DRC 0 | 75.4%, open 25, DRC 5 | 91.0%, open 6, DRC 7 |
| old fork c98d38eb | DRC 1, vias 57 | DRC 1 | 85.8%, open 15, DRC 3 | 90.3%, open 5, DRC 7 |
| rebased fork 5a629cfa | DRC 2, vias 55 | DRC 1 | 61.2%, open 15, DRC 5 | 89.5%, open 6, DRC 7 |

The old-fork and rebased-fork rows match the step 0 and task 5a-det numbers.

## esp-rust-board class widths

### Bisect (upstream alone)

| point | commit | new DRC |
|---|---|---|
| 4 | 36aeb08b | 1 |
| 8 | 90b4bbbc | 1 |
| 12 | 65deb815 | 1 |
| 13 | 80683fde | 1 |
| 14 | 411491b5 | 1 |
| 15 | **8013c817** | 2 |
| 17 | 95f931ac | 2 |
| 35 | 364b4572 | 2 |

411491b5 changes only tests/run_all.py and test files, so 8013c817 is the first bad commit.

### The new violation

The added violation is `starved_thermal` GND at (146.93, 87.28): U2 pad 1 (GND, F.Cu, 0.475 x 0.25 mm, the corner
pad of the QFN's left row). The other starved thermal, at (151.28, 121.23), is present on both sides. Copper within
1 mm of the pad in routed.kicad_pcb:
- 411491b5: IO10_SDA leaves pad 14 (147.59, 87.12) upward and to the right on F.Cu, (147.6, 86.8) -> (148.0, 86.4).
  Nothing sits directly above pad 1.
- 8013c817 and 364b4572: IO10_SDA leaves pad 14 up and to the left and drops a 0.8 mm via at (147.1, 86.5), 0.80 mm
  from pad 1's centre (via edge about 0.26 mm above the pad edge), then runs on B.Cu under the IC. This via is the new
  copper beside the pad, and it most likely removes the room for the pad's upward spoke. I did not confirm that by
  deleting the via and re-running DRC.

### How the commit moves that route

Router log diff, 411491b5 vs 8013c817 (router.log, class run):
- Phase 1 routes come out the same until IO3 ([27/29]): 16 segments, 3 vias, 34.45 mm becomes 9 segments, 1 via,
  21.60 mm. IO7 and IO10_SDA's main routes then shift.
- In Phase 3, IO10_SDA's first tap (pad 1 -> U2 pad 14) is found in 81511 iterations against 295439 before. The
  #444 seam re-ask that rerouted the whole net before no longer fires. That tap is the route with the via above.

The change that does this: with 8013c817, each obstacle builder takes its stub-proximity sources from
`_stub_proximity_source_ids` (routing_context.py:137-163 at 364b4572). This adds multipoint nets whose taps are
pending (`config._pending_multipoint` less `config._multipoint_taps_done`, the latter added by 39dd0327) and
pre-existing nets ripped this run. Before, a multipoint net left the source list once its Phase 1 route was in.

To isolate it, I reverted each part of 8013c817 by itself on 8013c817 + the determinism fix:

| variant | esp class |
|---|---|
| 8013c817 | DRC 2, vias 55, 663 mm |
| own track-proximity entry not dropped (`drop = set(sibs)`, routing_context.py:88 at 8013c817) | DRC 2, vias 55, 663 mm (unchanged) |
| stub-proximity sources as before 8013c817 | DRC 1, vias 57, 687 mm |
| pending multipoint taps not sources, ripped pre-existing nets kept | DRC 1, vias 57, 687 mm |

The pending-taps part accounts for the difference. The router has no model of a pour net's thermal spokes (no
spoke or thermal-relief term in the obstacle builders; GND is excluded from routing by placemat's `!GND`), so
whether a signal via lands beside a plane pad comes down to where the search happens to go.

## watchy class widths

### Bisect (fork commits replayed onto upstream points)

| point | upstream commit | watchy class | watchy human |
|---|---|---|---|
| 8 | 90b4bbbc | 85.8%, open 15, DRC 3, vias 52 (identical to old fork) | 90.3% |
| 13 | 80683fde | 85.8%, open 15, DRC 3, vias 54 | 86.6% |
| 14 | 411491b5 | 85.8%, open 15, DRC 3, vias 54 | 86.6% |
| 15 | **8013c817** | 60.5%, open 16, DRC 5, vias 54 | 81.3% |
| 17 | 95f931ac | 60.5%, open 16, DRC 5 | 81.3% |
| 35 | 364b4572 (= 5a629cfa) | 61.2%, open 15, DRC 5 | 89.5% |

First bad commit for the class result: 8013c817, as for esp-rust-board. On 8013c817 with only the pending-taps
condition reverted: 86.6%, open 14, DRC 3.

### What lowers clean closure

Closure (connections made) is 88.81% on both the old and the rebased fork. Clean closure drops because more nets
carry violations (route.json `violations`):
- old fork: Net-(AE1-FEED) clearance/shorting_items, PREVGL hole_clearance (both also in the baseline set);
- rebased fork: those, plus **+3V3 hole_to_hole** at (73.5, 109.4) and **CS/DC hole_clearance** at (85.9, 97.9).

+3V3 has many pads, so marking it unclean costs most of the 24 points.

The +3V3 violation is a router output followed by a placemat cleanup decision:
- router_out.kicad_pcb has two F.Cu-In1.Cu +3V3 vias 0.161 mm apart: one on C20 pad 1 (73.645, 109.33) and one at
  (73.5, 109.4), with a stub on In1.Cu. They come from the +3V3 rescue ("Rescuing +3V3 (partial, 4 disconnected
  parts)" in router.log), late in a run where +3V3 never closes (3 U4 pads open on both bases). Upstream's own
  same-net via merge (`merge_close_same_net_vias`, py_router/pcb_modification.py:6755) runs only in the plane steps
  (route_planes.py:2189, repair_planes.py:3062), so signal routing can ship such a pair.
- placemat's `merge_close_vias` (src/placemat/kicad/route_cleanup.py:348-422) walks the router's vias in board order
  and drops a via onto the first earlier survivor. Here (73.5, 109.4) would merge onto (73.645, 109.33). The moved
  track then clashes with GND, so `clean_routed` (route_cleanup.py:496-511) refuses every merge on +3V3 and keeps
  both vias (`vias_kept_close` reason "clearance", other_net GND). It does not try the other direction. Task 5a-det
  showed the other direction is clean and gives 84.3%. Which via comes first depends on uuid order, which 5a629cfa
  fixed per board content, so 61.2% is now stable on this board but would flip with an unrelated content change.
- CS/DC hole_clearance is a separate router-output violation on the new route. It remains in the 84.3% outcome.

### How the commit moves the routes

Router log diff, fork on 411491b5 vs fork on 8013c817: the first different route is ADC's Phase 1 main route
([42/52], 26.32 mm -> 26.16 mm). ADC is routed while BTN1, BTN2 and the other multipoint nets routed before it have
pending taps, and those tap pads now repel it. From there Phase 3's blocked-cell counts and rip choices differ
(ADC becomes +3V3's top Phase 3 blocker, 154 cells), the open-net set changes (ADC closes, USB_DET opens), and the
+3V3 rescue ends with the via pair above.

### watchy human widths

The 90.3% -> 89.5% human-width change (open 5 -> 6, a different set) does not follow one commit. Across the fork
points it reads 90.3, 86.6, 86.6, 81.3, 81.3, 89.5, and the pending-taps revert leaves it at 89.5%. I did not bisect
it further.

## Effect of reverting the pending-taps condition on test (a)

Rebased fork 5a629cfa as is, against 5a629cfa with routing_context.py:163 changed to
`(n not in routed or n in ripped)`. Each row is one run of the whole set, deterministic.

| board | widths | 5a629cfa | with revert |
|---|---|---|---|
| pic_programmer | class / human | 98.8% open 1 DRC 2 / same | same / same |
| usb-c-power-adapter | class | pass, vias 21 | same |
| usb-c-power-adapter | human | pass, vias 27, 200 mm | pass, vias 31, 201 mm |
| lora-v3 | class / human | 100% DRC 3, vias 113 | same |
| ir-irradiance-probe | class / human | 88.6% DRC 2 / 96.2% DRC 1 | same |
| esp-rust-board | class | DRC 2, vias 55, 654 mm | **DRC 1**, vias 56, 677 mm |
| esp-rust-board | human | DRC 1 | same |
| watchy | class | 61.2%, DRC 5, vias 56 | **85.8%**, DRC 3, vias 54 |
| watchy | human | 89.5%, vias 57, 693 mm | 89.5%, vias 63, 720 mm |
| spimux | class / human | 86.5% open 5 DRC 1 | same |
| chainlinkDriver | class / human | pass | same |

## Classification

- Upstream 8013c817 is deliberate. Its message gives the reason for this part: "a multipoint net joins
  routed_net_ids after its Phase 1 route, and the builders exclude routed nets from stub proximity, so its
  still-pending tap pads lost their escape protection for the rest of Phase 1 and all of Phase 3". 39dd0327 ("Review
  fixes for the soft-cost commits") narrowed it to nets whose taps Phase 3 has not yet routed. Neither commit cites a
  corpus measurement, unlike the soft-cost settings dc6b61ad discusses. It reads as a consistency fix, not a tuned
  trade-off, and I found no evidence upstream measured its effect on completion or DRC.
- esp-rust-board: a side effect of that change on a router that does not protect thermal spokes of pour-net pads.
  Not a bug in the change. The missing spoke model is a gap upstream has on every board.
- watchy: the change moves one early route. The visible loss is mostly the router shipping a same-net via pair from
  a rescue (upstream merges such pairs only in its plane steps) plus placemat's merge refusing the pair instead of
  trying the clean direction. The router output and placemat's cleanup both play a part.

## Possible fixes

Not built.

1. placemat, route_cleanup.py:348-422 and 496-511: when a merge on a net clashes or parts the net, try the
   opposite survivor for that pair (merge the earlier via onto the later one) before refusing the net, or choose the
   survivor by geometry (the via on a pad, or the one whose moved tracks clear). This makes watchy's result
   independent of uuid order (84.3% with the CS/DC violation, against 61.2% now) and applies to any board where the
   router leaves such a pair. It diverges from KRT's first-wins rule (pcb_modification.py:6755), so it needs a
   divergence comment.
2. Fork divergence, routing_context.py:163 on placemat/upstream-2026-10b: drop the pending-multipoint sources and
   keep the ripped pre-existing ones. Measured above: restores both boards and changes nothing else on test (a) for
   the worse. Against it: it reverts a deliberate upstream consistency fix on the evidence of two boards whose
   outcomes hinge on one early route each, and the next upstream change to search costs may move them again. Under
   "defer to upstream" I would not take this without a wider measurement (the bench corpus), and would report the
   test (a) numbers to the fork's own notes rather than to upstream.
3. esp-rust-board's second starved thermal: nothing in the fork. A real fix is a router cost that keeps spoke
   corridors of plane-net pads free, which is new upstream-scale work. placemat could instead flag or repair starved
   thermals after the route, but that is a separate feature.

My recommendation: 1 in placemat, accept esp-rust-board's +1 DRC as routing noise from upstream, and leave 2 as an
option for the user with the table above.

## Evidence

Scratch runs (route dirs with router.log, router_out, routed, drc_after) are under
/tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/bisect/: `w-old`, `w-new`
(upstream endpoints), `w-p4`..`w-p17` (upstream bisect), `w-forkold`, `w-forknew`, `w-f8`..`w-f17` (fork bisect),
`w-ownrev`, `w-stubrev`, `w-pendrev`, `w-f15pend`, `w-fnewpend` (part reverts), `w-allbase`, `w-allpend` (full test (a)).
