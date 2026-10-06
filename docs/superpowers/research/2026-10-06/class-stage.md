# The class stage on the core board (run f06f75cb)

Research only. Nothing in placemat, KRT or the board was changed. Experiments ran on scratch copies under the
realboard lock, one route at a time, with the router command placemat 0.99.23 uses (KRT c98d38eb, same flags),
then placemat 0.99.23's own post-processing (`remove_guards`, `fill_zones`, `remove_dangling_router_copper`,
`run_drc`; scratch `cs/post.py`). post.py on f06f75cb's own router output gives 11 open / 89.32%, the same as
its route.json.

Scratch: `.../scratchpad/cs/`. Copies of the run dirs are in `cs/f06_route` (f06f75cb/route) and `cs/xrf_route`
(the excluded-RF run). f06f75cb's run.json has since been overwritten by a running `placemat run --explore`
(pid 1880766, started 07:39), so its route/ may change; the copy was taken at 07:41, after route.json (07:36).

## Summary

- The class stage ran on f06f75cb and the main pass ran at 0.127. No graze refusal is in the 0.1905-0.2635 band.
- The 0.99.20 excluded-RF run and f06f75cb route **different placements**. 56 footprints differ, the MCU among
  them. The 0.99.20 run's input is identical to run 96ef6af4's.
- On the 0.99.20 placement, the class stage gives the same result as excluding RF: **7 open of 103, 93.2%**,
  with the same seven nets open, and RF_50 routed and counted. The excluded-RF run's 93.1% is 7 of 102,
  because RF_50 was left unrouted and uncounted.
- On f06f75cb's placement, routing with no RF copper at all gives 13 open, and routing the class stage after
  the main pass also gives 13 open. The stage as built (before the main pass) gives 11. The RF copper is not
  what blocks the open nets.
- Recommendation: leave the class stage where it is. The drop from 93.1% to 89.3% comes from the placement
  and from the pairs stage on that placement.

## 1. Did the class stage run?

Yes.

- route.json `class_stages`: one stage, `clearance_mm` 0.2, nets RF_50 [1 -> 0], ble.ANT24_FEED [0 -> 0],
  gnss.ANT_FEED [0 -> 0], gnss.ant_rf.ANT_TRACE [0 -> 0].
- classes0.log:1: `--nets RF_50 ble.ANT24_FEED gnss.ANT_FEED gnss.ant_rf.ANT_TRACE` on islands.kicad_pcb; :128-129 and
  :160-161 `Single-ended: 2/2 routed`, `Multi-point: 6/6` and `10/10 pads connected`.
- router.log:1 (main pass): the input is `classes0.kicad_pcb` and the nets are `* !GND !RF_50 !USB_D_N !USB_D_P !V3V3 !VBIKE
  !VBUS !VSHUNT !ble.ANT24_FEED !gnss.ANT_FEED !gnss.ant_rf.ANT_TRACE !logicsupply.SW_3V3`.
- The floor. KRT computes it as the max of `--clearance` and the class clearance of every net routed in the call
  (`routing_config.py:473-485`, called at `route.py:2362`), and prices each obstacle at `max(floor, own)`
  (`routing_config.py:459-471`). router.log:8 gives a base of 0.127. Every net in net_clearances.json above 0.127
  (RF x4 0.2, USB_D_P/N 0.1524, SW_3V3 2.0) is negated in the main pass, so the floor is 0.127. The router
  does not print the floor, so this is derived from the code and the net set, then checked against the refusals
  below.

Graze refusals ("terminal copper ... grazes foreign copper (centreline d mm ...)") by d. At a 0.127 floor the
check refuses d < 0.1905; at 0.2 it refuses d < 0.2635:

| Log | Lines | d < 0.1905 | 0.1905 <= d < 0.2635 |
|---|---|---|---|
| f06f75cb main pass (router.log) | 17 | 17 | 0 |
| f06f75cb class stage (classes0.log) | 0 | 0 | 0 |
| 0.99.20 excluded-RF run (router.log) | 7 | 7 | 0 |
| 96ef6af4, 0.99.20 with RF in the main pass | 131 | 9 | **122** |

The floor is fixed. 96ef6af4 shows what a 0.2 floor looks like on this board.

## 2. Are the same nets open?

No, and the placements differ (section 3), so the open lists are not like for like:

| Run | Open (placemat) | Nets |
|---|---|---|
| excluded-RF, 0.99.20 (`boards/.placemat/route`) | 7 / 102 (93.14%) | DISP_DC, DISP_SCK, GNSS_PPS, LD2, PD_IRQ, SCL_PWR, USB_D_P |
| f06f75cb, 0.99.23 | 11 / 103 (89.32%) | DISP_RST, DISP_SCK, EXCITE, GNSS_TX, LD1, RAIL_FAULT, SDA_PWR x2, USB_D_N, USB_D_P x2 |

- Three of f06f75cb's 11 are the USB pair (USB_D_N 1, USB_D_P 2). The pairs stage decides these, before the
  class stage, and the main pass excludes the pair. On this placement the pair router needed three leg failures
  and a rip before it succeeded (f06 pairs.log:261, :496, :654, :953). On the 0.99.20 placement it routed first time
  (pairs.log:260). Both report `Diff pairs: 1/1 routed`, but KiCad still counts the pads open.
- The main-pass failures in f06f75cb (router.log) and their blockers. None of them names an RF net:
  - DISP_CS, routed later: blocked by SDA_PWR, SCL_PWR and DISP_CS_P (:355-391).
  - DISP_SCK: SCL_PWR, SDA_PWR and DISP_DC_P (:431-465), "no rippable blockers" (:476).
  - DISP_RST: DISP_SCK_P, DISP_CS_P and LED_USB_K (:615-651).
  - RAIL_FAULT: PGOOD (:779-780).
  - GNSS_TX: GNSS_RX (:817-818).
  - EXCITE: three retries fail (:1017-1068).
  - LD1: ripped in the final reconciliation and not restored, "restore skipped (net 10) ... left ripped (#134)"
    (:2023), then "PARTIAL LD1: reroute failed" (:2029).
- Where the RF copper runs (classes0.kicad_pcb). RF_50 runs on F.Cu from L1.2 (27.78, 52.19) to C6.1/R3.1
  (24.6, 61.1), about 13 segments, all south of the MCU (y 52-61). ble.ANT24_FEED runs along y = 61.09 (x 18.7-22.8).
  gnss.ANT_FEED and ANT_TRACE are at the top edge (y 2-10). The open nets run from U16 (about 26, 46) north and
  west, to U5/R5-R7 (y 19-26), U10 (y 20), U39-U43 (x 10-14, y 38-45) and U27 (y 15). None of their corridors
  reaches y > 52 at x 24-30.

Measured on f06f75cb's own islands board (`cs/e1`): the main pass with the RF nets negated and **no RF copper
on the board** gives 13 open of 102 counted (87.3%: RAIL_FAULT 2, VBUS_DISCH 1, the rest as f06f75cb, RF_50
unrouted). The RF stage's copper being there did not cost a net. Without it, two more failed.

Determinism: rerunning f06f75cb's main pass from its classes0.kicad_pcb (`cs/e0`) reproduces 11 open, net
for net. The differences in this note are not run-to-run noise.

## 3. Is the placement identical?

No. The excluded-RF run is `~/Documents/Hardware/fairing-instrument/electronics/boards/.placemat/route/`
(2026-10-05 22:41-22:47; its router.log:1 negates the four RF nets with no class stage, and route.json `excluded`
lists them). Its in.kicad_pcb has every footprint at the same position as run 96ef6af4's in.kicad_pcb (0 differ;
96ef6af4 is the 0.99.20 run with RF in the main pass, 89.3% / 11). Against f06f75cb's in.kicad_pcb, 56
footprints differ (`cs/fpdiff.py`):

| Group | Shift (mm) | Parts |
|---|---|---|
| MCU cell and its passives | (-0.036, -0.118) | U16, U17, U19, C25-C39, C46-C48, L1-L3, R10-R22, TH1, TH2 |
| west sensor cluster | (+0.364, -0.118) | U4, U39-U43, R57-R61, C8, C76, C77 |
| B.Cu group | (-0.014, +0.155) | U25, U26, C58-C60 |
| C33 | (+0.082, -0.236) | |

I did not find placement 55e759bc on disk (no file under the board's .placemat names it). The comparison above
uses the router inputs the two runs actually routed.

### Like for like

On the 0.99.20 placement (the excluded-RF run's islands.kicad_pcb) I ran the class stage, then locked its copper
and ran the main pass, as 0.99.23 does (`cs/e2`):

| Run on the 0.99.20 placement | Open | Nets |
|---|---|---|
| RF in the main pass (96ef6af4) | 11 / 103 (89.32%) | DISP_RST, DISP_SCK, GNSS_RX, GNSS_TX, LD2, PD_IRQ, SCL, SDA, SDA_PWR, USB_D_P, USB_WET |
| RF excluded, not routed (board lead) | 7 / 102 (93.14%) | DISP_DC, DISP_SCK, GNSS_PPS, LD2, PD_IRQ, SCL_PWR, USB_D_P |
| **class stage first, then the main pass** | **7 / 103 (93.20%)** | DISP_DC, DISP_SCK, GNSS_PPS, LD2, PD_IRQ, SCL_PWR, USB_D_P |

The class stage routes all four RF nets (classes0.log `2/2 routed`, `6/6`, `10/10`) and leaves the main pass with
exactly the excluded-RF result. The main pass has 7 graze lines, all under 0.1905.

## 4. Recommendations, ranked

1. **Leave the class stage before the main pass.** Measured on both placements:

   | Placement | Class stage first (0.99.23) | No RF copper | Class stage after the main pass |
   |---|---|---|---|
   | 0.99.20 (96ef6af4) | 7 open, 93.2% | 7 open, RF unrouted | - |
   | f06f75cb | 11 open, 89.3% | 13 open, RF unrouted | 13 open, 87.4% (`cs/e1b`) |

   A late stage at 0.2 routes RF with floor 0.2 against all earlier copper, priced at max(0.2, its own class)
   (`routing_config.py:459-471`), which is KiCad's pairwise rule. On this board the late RF stage did route all
   four nets (e1b late.log:126-127, :158-159; the RF nets are short and sit at the board's ends), so it is
   legal. It does not help: the main pass then routes without the RF copper, and that run is 2 worse here. A
   late stage also risks leaving the antenna feeds open on a fuller board, and they are the nets least able to
   take a detour. I would not change the order.

2. **Do not make the RF stage's copper rippable.** KRT will not take it as a rip candidate even unlocked. In
   the main pass, a pre-existing net is a candidate only if it is not locked, not `!`-negated in `--nets`, small,
   and its class clearance is no higher than the call's floor (`route.py:2255-2335`; the floor guard is
   `:2326-2332`, so that "auto-candidates must not change routing on multi-class boards"). The RF nets fail
   all three: placemat locks them (`route_class_stages` -> `lock_copper`), negates them, and their class is
   0.2 > 0.127. To rip them, the RF nets would have to be in the main call, which brings the 0.2 floor back.
   Measured, ripping would have nothing to gain: with no RF copper on the board at all, the main pass did
   worse (13 vs 11).

3. **Read 0.99.23 against the 0.99.20 result on the same placement.** f06f75cb's 89.3% is that placement:
   the MCU cell moved 0.12 mm and the west cluster 0.36 mm. That made the pairs stage leave the USB pair with
   3 open pads instead of 1, and changed which display and I2C nets box each other in at the MCU's NE edge.
   On 96ef6af4's placement, 0.99.23's routing gives 93.2%. For the board lead: route the placement you want
   to compare (`placemat route` on that layout) instead of comparing two explore runs.

4. The remaining opens on f06f75cb are the patterns `route-boxed.md` describes: the display group at the MCU's
   NE edge, walled by its own siblings and the _P lines, and SDA_PWR/SCL_PWR. LD1 is a router reconciliation
   casualty (#134, router.log:2023-2029). None depends on the class stage.

## 5. Same-net vias 0.1 mm apart (hole_to_hole)

### What is on the board

f06f75cb drc_after.json: `hole_to_hole ... (board setup constraints min 0.3000 mm; actual 0.0000 mm)`, two
VSHUNT F.Cu-B.Cu vias at (19.0, 19.4) and (19.1, 19.4), drill 0.2, size 0.45. route.json lists VSHUNT under
`shorted`, so it counts against `closure_clean`: 0.8544 = 1 - (11 + VSHUNT's 4) / 103.

- **Origin.** The pair first appears in islands4.kicad_pcb (VSHUNT's island stage); islands4_in.kicad_pcb has
  neither via. Both come from that stage's final reconciliation sub-run (islands4.log:295 onwards): "Via-in-pad
  unblock: dropped 2 fab-floor via(s)" (:372), "STUB-SWAP RESCUE: VSHUNT stub F.Cu -> In2.Cu routed (8 segments,
  2 vias)" (:374) and "Adding 1 via(s) from stub layer swapping" (:422). After that, VSHUNT copper there is an
  In2.Cu chain (18.97, 19.37) -> (19.0, 19.4) -> (19.1, 19.4), with B.Cu at (19.1, 19.4) -> (19.2, 19.4) and
  (19.1, 19.4) -> (19.91, 20.10). The via at (19.0, 19.4) also touches the 0.3 mm B.Cu track
  (18.96, 19.15) -> (19.91, 20.10), 0.146 mm from its centreline.
- **INA_ALERT** (runs 05e7da77, 0.288 mm; 88e83df0, 0.135 mm): the same mechanism, also in a reconciliation
  sub-run. 88e83df0 router.log:2251 "Stub layer switch: INA_ALERT stub at (33.10,12.80) F.Cu -> In2.Cu" drills a
  through via 0.335 mm from INA_ALERT's via at (32.77, 12.85).
- **"restore skipped ... left ripped (#134)" is a different matter.** In f06f75cb it is about ripped nets
  whose saved copper would now short: ALS_INT (router.log:1781, re-routed at :1984), LD1 and DISP_MOSI (:2023-2024).
  No via is involved, and the VSHUNT pair was made in islands4, not the main pass.

### What KRT and KiCad do

- KRT's own rule is that a via keeps hole-to-hole even against its own net. `merge_close_same_net_vias`
  (`pcb_modification.py:6755-6880`) drops a new via within `(drill_a + drill_b)/2 + hole_to_hole` of a same-net
  via whose layer span covers it, and moves the attached segment ends onto the survivor. It runs only in the plane
  paths (`route_planes.py:2174`, `repair_planes.py:2997`). The stub-switch path has a narrower guard,
  `_reuse_nearby_same_net_via` (`stub_layer_switching.py:294-353`, #340), which checks only vias already in
  `pcb_data`. The rescue route's vias and the reconciliation sub-run's swaps get past it. This is a router gap.
  Per the router rule (local only), no upstream issue.
- KiCad's TRACKS_CLEANER (`kicadsrc/tracks_cleaner.cpp`) removes a via only when another via is at the **same
  position** with the same type and layer set (:400-430), or when it sits on a through-hole pad (:435-451). It
  skips locked items (:397). It would leave both pairs alone.
- KiCad's hole_to_hole test does not look at nets (`drc_test_provider_hole_to_hole.cpp:253-312`): two same-net
  holes 0.1 mm apart are a real error, and a fab will reject the drill file.

### Should placemat fix it after routing?

Yes, for the case where one via of the pair is redundant. That is a small extension of
`route_cleanup.remove_dangling_router_copper`, which already ports the cleaner and checks connectivity with
`pad_groups`:

- Scope: the router's vias (the cleanup's `mine`; it already takes the locked island copper). The rule:
  for each pair of same-net vias whose holes are closer than the board's hole-to-hole (KRT's test,
  `pcb_modification.py:6836`), with one span covering the other, delete the covered via when `pad_groups` for the
  net is unchanged. That is the same guard the dangling pass uses for `refused_nets`.
- Measured on f06f75cb's routed.kicad_pcb (`cs/vt.py`): `board.Delete` of the VSHUNT via at (19.0, 19.4) leaves
  VSHUNT one pad group, and DRC then reports no hole_to_hole, the same open nets and no new violation.
  `closure_clean` would go from 0.8544 to 0.8932.
- Where deleting a via would split the net (INA_ALERT 0.335 mm apart, probably), KRT's way is to move the
  segment ends onto the survivor. That moves copper by up to 0.3 mm, so it needs a clearance check, which makes it
  a reroute, not a cleanup. I would leave such a pair as it is and name it (a structured record on the cleanup,
  like `refused_nets`) instead of moving copper.
- This diverges from KiCad's cleaner, which only merges coincident vias. Name the divergence in the module
  docstring with the reason: KRT's own hole-to-hole rule, and KiCad's net-independent DRC.
