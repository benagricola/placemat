# Display SPI routes on the core board: why they fail

Research only. Nothing in placemat, KRT or the board was changed. Experiments ran on scratch copies of
run af51c83d's router input (`route/islands.kicad_pcb`) under the realboard lock, one route at a time,
with the router command placemat used (KRT c98d38eb, same flags).

Paths: board runs `~/Documents/Hardware/fairing-instrument-stagger/electronics/boards/core/.placemat/runs/`,
KRT `~/work/KRT-upstream/py_router/`, placemat `/home/ben/work/placemat/src/placemat/`. Scratch work:
`.../scratchpad/rb/`.

## Summary

Three things stop the display lines, in this order of weight:

1. **A 0.2 mm clearance floor on every net in the main pass.** KRT prices every foreign obstacle at
   `max(floor, its class)`, and the floor is the largest class clearance among the nets routed in that
   call. placemat routes the 50 ohm nets (RF_50, ble.ANT24_FEED; class 0.2 mm) in the same call as
   everything else, so every Default net routes at 0.2 mm instead of 0.127 mm. This is what the
   "terminal copper ... grazes foreign copper ... only a narrower track clears it" refusals are: the
   check demands 0.2 + 0.0635 = 0.2635 mm from a terminal leg's centreline to foreign copper.
2. **The display pin order is reversed between the MCU and the connector.** Straight airwires of the
   group cross six times. With the floor fixed, the display lines that still fail are walled at their
   lane ends by a sibling display line that was routed first and had to cross them.
3. **The USB pair's escape** (pins 25/26, routed in the pairs step, KiCad-locked) dives to B.Cu within
   0.7 mm of the edge, right in front of DISP_DC's and DISP_CS's lane ends. Locked copper is never
   rippable.

The nets the board lead named (SCL_PWR, GNSS_PPS, SDA) cross or bound the corridor, but in af51c83d none
of the display failures is blocked by them. The corridor has plenty of room between the ends (cut
counts below).

## 1. The router's clearance floor (the "grazes" refusals)

### What the router does

- `routing_config.py:473-485` `set_net_clearances`: `net_clearance_floor = max([clearance] + [class
  clearance of every ROUTED net in the map])`.
- `routing_config.py:459-471` `obstacle_clearance(net_id)` = `max(floor, net_clearances.get(net_id,
  clearance))`. Every obstacle stamper and the base map read it (docstring, and
  `docs/api-routing-config.md:441-462`).
- `route.py:2362` calls `set_net_clearances(net_clearances, base_map_exclusions)`, i.e. over the nets
  this call routes.
- The terminal graze check: `single_ended_routing.py:931-1019` `_neck_terminal_grazes`. `own =
  config.obstacle_clearance(net_id)` (`:968`), `own_l` = the per-layer rule if any (`:986`), and a terminal
  segment is a graze when `d - own_l < width/2` (`:998`). Under `--escalation off` `may_narrow()` is
  False (`fab_tiers.py:180-182`), so the graze joins `hard` (`:1013-1015`) and the route is refused; the
  message is `_hard_text` (`:918-928`).

So the applied threshold is `d >= own_l + w/2` = 0.2 + 0.0635 = **0.2635 mm**, not 0.1905. Every
reported value (0.170, 0.212, 0.214, 0.219, 0.220, 0.238, 0.251) is under it.

### Where the 0.2 comes from

af51c83d's `route/net_clearances.json` (written by placemat because the board has a net halo,
`kicad/net_halos.py`): RF_50 0.2, ble.ANT24_FEED 0.2, gnss.ANT_FEED 0.2, gnss.ant_rf.ANT_TRACE 0.2,
USB_D_N/P 0.1524, USB_CC1/2 0.127, logicsupply.SW_3V3 2.0 (the halo). The main pass excludes
SW_3V3 and the USB pair, but routes RF_50 (router.log:329, `[35/73] Routing RF_50`) and
ble.ANT24_FEED (router.log:468). Floor = 0.2.

Without the halo placemat would not write the map, and the router builds the same class map itself
(`route.py:7757-7768`, `list_nets.net_clearance_map_by_id`), so the floor would still be 0.2. The halo is
not the cause; neither is a zone fill, a pad local clearance (none on U16, U5, R4-R7) or a .kicad_dru
rule (no layer rule touches these nets).

### Measured

A hook around `_neck_terminal_grazes` (scratch `rb/graze/hook.py`, wraps the module function and execs
`route.py`, nothing in KRT edited) on the af51c83d board, routing only the four display nets:

| Call | Floor printed (`own`) | Grazes | Display result |
|---|---|---|---|
| DISP_DC, RST, MOSI, SCK alone | 0.127 | none | DC, RST routed; MOSI, SCK walled by DC's and RST's routes |
| the same plus RF_50, ble.ANT24_FEED | **0.2** | RST d=0.219, SCK 0.212, MOSI 0.170, DC 0.191/0.216 | all four refused |

The foreign copper at each terminal is the neighbouring pin's escape lane on F.Cu (the board lead's
table agrees). Example line: `GRAZE DISP_SCK graze seg (28.596,42.976)->(28.600,43.000) w=0.127
d=0.212 own=0.2 own_l=0.2` (`rb/graze/log_rf.txt`).

The floor applies to the whole A* search too, not only to terminals: every Default net in the main pass
keeps 0.2 mm from everything. In af51c83d's main pass the log has 133 "grazes foreign copper" refusals;
with the floor at 0.127 (below) it has 8.

### Is it upstream behaviour?

Yes, documented: `docs/api-routing-config.md:459-462` - the floor is computed "over the routed nets only,
so a foreign class cannot inflate the floor". The consequence is that a caller who routes a 0.2 mm class
in the same call as Default nets gets 0.2 mm everywhere. Upstream's own design keeps a class out of the
floor by not routing it in that call, which is what placemat already does for the USB pair (pairs
stage) and the islands.

### Placemat's side

- `--escalation off` is placemat's choice and fixed: `kicad/route.py:499` (pairs) and `:758` (main
  pass), since routing was introduced (commit e89ea390). `settings.py:659` `_ROUTER_OWNED` refuses it in
  `router_args`. Turning escalation on would let the router narrow terminal legs to the fab floor
  (0.0889 mm) - it would hide this, not fix it.
- `--clearance-ceiling 0.127` would cap the 50 ohm class at 0.127, so the RF nets would route under
  their own class's rule. Not a fix either.
- The fix that follows upstream's model: a stage per clearance class. Route the nets of any class
  whose clearance is above Default's (here RF_50, ble.ANT24_FEED, gnss.ANT_FEED,
  gnss.ant_rf.ANT_TRACE) in their own call first, as the pairs and islands are, then the main pass
  without them. Their copper is then foreign and is still priced at their class clearance
  (`obstacle_clearance` maxes with the obstacle's own class), so KiCad's pairwise rule holds.

### Scratch result

`rb/split.sh`: RF stage (the four 0.2 mm nets) then the main pass excluding them, otherwise the same
command.

| Run | Open pad pairs (router) | Open nets |
|---|---|---|
| af51c83d as placemat ran it, reproduced on scratch | 10 of 181 | DISP_DC, DISP_MOSI, DISP_RST, GNSS_TX, LD2, PD_IRQ, SCL, SDA, SDA_PWR, USB_WET |
| class stage first (split) | 8 of 181 (RF stage 8/8, main 165/173) | DISP_MOSI, DISP_RST, GNSS_RX, LD2, PD_IRQ, SCL, SCL_PWR, SDA |

These are the router's pad-pair counts, not placemat's closure figure (placemat's 89.3% for af51c83d
is 11 open of 103 after its cleanup). I did not run placemat's pipeline on the split.

With the floor at 0.127, DISP_MOSI and DISP_RST no longer fail on a graze. They fail at their lane ends
because DISP_DC's and DISP_SCK's routes cross in front of them (`rb/split/log_split.txt:417-430`,
`:524-536`: "Top blockers: 1. DISP_DC: 12 cells near src", "1. DISP_SCK: 12 cells near src"). That is
the pin order, section 2.

## 2. The display pin order

MCU pins (af51c83d, U16 at 45 degrees, NE edge, from NW to SE): 27 DISP_CS, 26 USB_D_P, 25 USB_D_N,
24 DISP_DC, 23 DISP_MOSI, 22 DISP_SCK, 21 DISP_RST, 20 V3V3, 19 GNSS_PPS, ... 15 DISP_TE.
Heading north, west to east: CS, (USB), DC, MOSI, SCK, RST, PPS, ..., TE.

Connector U5 contacts, west to east: 3 CS_P, 4 RST, 5 SCK_P, 6 MOSI_P, 7 DC_P, 8 TE. Terminations
(af51c83d) west to east: R4 CS, R7 SCK, R6 MOSI, R5 DC.

DC, MOSI, SCK, RST are in reverse order at the two ends. Straight airwires (pin to pad, and through
the terminations) cross six times: DC/MOSI, DC/SCK, MOSI/SCK on the MCU side, RST against SCK_P,
MOSI_P, DC_P on the connector side (computed from the pad positions). TE and GNSS_PPS need no
crossing with the group.

- The MCU module's `Pm.PinGroup` is `display:21-24, 27` (`modules/mcu/Mcu.zen:172`), so the order within
  21-24 is free. The mirror (21 DC, 22 MOSI, 23 SCK, 24 RST) gives zero crossings among the
  group's airwires. RST then runs between the CS and SCK chains and must pass the termination row
  between R4 and R7 (the 0.3 mm gap the board lead found), so it needs a via pair under the row or a
  lane left for it there (the board lead's fix).
- placemat flags only crossings within `score.escape_depth` of a part (`ratsnest.py:309-327`
  `crossed_pair_list`); af51c83d reported RST against MOSI_P and SCK_P at U5 but not the MCU-side
  reversal, which crosses mid-span.
- The pin map decision (`docs/decisions/schematics/mcu-gpio-map-2026-10-04.md`) took the map the pin
  study found at the 45-degree turn (run ef82b21c). In that study's 45-degree pose the exits of pins
  21-24 and 27 lie in a different order along the edge than on the board (study: pin 27's exit
  south-east of pin 21's; board: pin 27 north-west of pin 24). I did not find why; worth checking that the
  study's pose matches the turn the board applies, since the map it chose is the worst order for the
  board as built.

Measured (`rb/mirror`, pins 21-24 swapped on the scratch board, nets and stubs both):

| Run | Open pad pairs | Display open |
|---|---|---|
| mirror, one call (floor 0.2) | 10 of 181 | DISP_RST, DISP_SCK (graze refusals at the same pins as before: they follow the pin, not the net) |
| mirror with the class stage (`rb/msplit`) | 6 of 181 (RF 8/8, main 167/173) | DISP_DC, DISP_SCK (others open: GNSS_PPS, LD2, PD_IRQ, SCL_PWR) |

## 3. The MCU's lane ends

`modules/mcu/Mcu_layout.py:198-208`: pins 21-27 escape straight out, then turn 45 degrees north-east a
lane long (`run=LANE`); on the board (cell at 45 degrees) the lanes run due north. placemat lays turned
lanes one step apart across their direction (`lanes.py:389-412` `_staggered`, step `lanes.py:347-357` =
half each width + clearance = 0.254 mm), then rounds each corner outward to 1 nm (`lanes.py:475-480`).

Lane x on the board: DC 28.066392, MOSI 28.320393, SCK 28.595763, RST 28.878606. DC to MOSI is
0.254001 centre to centre, 0.190501 from one centreline to the next lane's edge: legal by 1 nm against
0.1905. MOSI-SCK and SCK-RST are 0.275 and 0.283. I did not reproduce the board lead's 0.190 (0.0005
short) on af51c83d's board; on run 861247ff it may differ.

The router's terminal leg snaps the lane end to its 0.1 mm grid: MOSI's end (28.320, 42.685) gets a
leg to (28.300, 42.700), 0.02 mm toward DC, d = 0.170. That is a graze at any floor (0.170 < 0.1905).
So at 0.254 pitch a lane end is only enterable along the lane's own line. A lane pitch of at least
track + clearance + half a grid step (0.254 + 0.05 = 0.304 mm), or lane ends on the router's grid,
would leave room for the snap. Keeping the turned lanes at their natural spacing (0.4 x cos 45 =
0.283 mm) is not enough for a 0.05 snap.

## 4. Ordering, and why the lines are "not allowed to rip"

Order in af51c83d (router.log:43-69): MPS (KRT's default, `route.py:7011`), 4 rounds; the display nets
are all in round 1, with SCL at #28, SDA #36, the four _P lines #27-31, DISP_CS #41, DC #42, MOSI #43,
SCK #44, RST #52, GNSS_PPS in round 2 (#66). "Direct-first" (#472) moved IMU_INT1, SCL_PWR, SDA_PWR to the
front.

Ripping (`route.py:2255-2330`, `protected_nets.py:297-305, 409-434`):
- in the main pass, nets routed in that same pass are rippable (the log rips SCL, USB_HV, DISP_CS_P,
  DISP_SCK_P for DISP_CS, router.log:373-425);
- copper from an earlier step (pairs: USB_D_P/N; islands) is "pre-existing", and a net with any
  KiCad-locked segment is never rippable, with no override. placemat's escape lanes are locked, so
  every GPIO net with a lane is "locked" - USB_D_P/N, SCL, SDA, every DISP net;
- the final reconciliation sub-run (router.log:2237) treats everything from the main pass as
  pre-existing, so it can rip none of those nets. That is where most of the "not allowed to rip" hints
  come from.

DISP_CS and DISP_DC: their lane ends sit inside the USB pair's loop and vias (USB_D_P via near (28.6,
41.7), USB_D_N near (28.0, 41.9)): "forward cell (270, 422): 6/8 neighbors blocked ... USB_D_P(1 track,
1 pad), GND, USB_D_N, SPICS1" (router.log:366-368). That copper is from the pairs step and locked.

The board lead's runs agree that order alone does not fix it: `--ordering inside_out` (58eff333)
put the display nets at #14-28 and they still failed on the same graze refusals (its router.log:247-258).

## 5. Room in the corridor

Free 0.127 mm tracks at 0.254 pitch across x 20-32 on af51c83d's router input (pads, vias, pre-existing
copper, no-track rule areas, the In2 AGND fill), against tracks routed across the same cut:

| Cut | F.Cu free / used | In2.Cu free / used | B.Cu free / used |
|---|---|---|---|
| y = 30 | 33 / 6 | 25 / 4 | 29 / 4 |
| y = 34 | 40 / 7 | 18 / 3 | 21 / 0 |
| y = 38 | 41 / 6 | 38 / 7 | 17 / 2 |

The middle of the corridor has room for both sets on any layer. The constraint is at the two ends:
the MCU's NE edge (lane ends at 0.254-0.283 pitch, the USB pair's vias, SCL on In2 under the edge at y
~42) and the termination row / connector (B.Cu there is the GNSS module's keepout and pads).

## 6. What the router offers for groups of nets

- `--ordering bus` (`route.py:7011-7016`, `single_ended_loop.py:457-580`): detected bus groups route
  first, members middle-out, the rest by MPS. Ordering only.
- `--bus`: the same detection, plus a planned corridor per group (`bus_corridor.py:78-185`) and
  attraction of each member to that corridor or to its routed neighbour (`bus_detection.py:280-422`).
- Detection (`bus_detection.py:37-142`): a clique of nets whose sources (or targets) are all within
  `--bus-detection-radius` (default 5 mm, `routing_defaults.py:189`), sub-clustered by the other end, then
  the geometric filter (`bus_detection.py:316-376`): at least 3 members, displacement within a cos 0.9
  cone and a length ratio of 1.5, run at least 5 mm, no power or pair nets. `--bus-min-nets` is the
  clique minimum (default 2) before that filter.
- `--group BLOCK` / `--group-by` (`route.py:6970-6995`) scope a run to one placement block's nets
  (`--component` for N parts). They choose WHICH nets route, not their order. Not a grouping feature
  for routing order.
- placemat passes none of these itself (`kicad/route.py:758-771`); only through `[route] router_args`.

On af51c83d's board (run of `detect_bus_groups` + `filter_bus_groups_geometric` on the 73 main-pass nets):

| Radius, min nets | Groups after the filter |
|---|---|
| 5.0, 2 (default) | DISP_CS, DC, MOSI, SCK, RST, GNSS_PPS, GNSS_RX, GNSS_TX, DISP_TE (one group of 9); LED_STATUS, VBUS_DISCH, RING_INT; MCU_EN, SCL, SDA |
| 2.0, 2 | DISP_CS, DC, MOSI, SCK; GNSS_PPS, RX, TX, DISP_TE |
| 3.0, 3 | DISP_CS, DC, MOSI, SCK; GNSS_PPS, RX, DISP_TE |

Bus members are ordered by source position (`bus_detection.py:204-242`) and each is attracted to its
neighbour in that order. With the display pins reversed between the two ends, "neighbour at the
source" is not "neighbour at the target", so attraction pulls members into the crossings. The
corridor planner probes one representative at widened clearances (`bus_corridor.py:104-145`); in the
earlier runs that used `--bus` (fairing-instrument core runs 9376252e and d37478df, router.log:123-160
and 130-178) the probe's first cell was boxed 8/8 by the neighbouring lanes at every rung ("forward
stuck (1 < 5000)"), so the groups fell back to neighbour attraction. That is the "stuck at its first
step". I did not find run 3db3d24e on disk; this is from those two runs. Under the 0.2 mm floor a
widened probe has even less room at 0.254-pitch lane ends.

The _P lines (terminations to connector) are not detected as a bus at any of these settings.

Measured with the class stage and `--ordering bus` (`rb/bsplit`; detection found the 9-net display+GNSS group, LED_STATUS/VBUS_DISCH/RING_INT and MCU_EN/SCL/SDA): 8 of 181 open, the same count as the class stage alone; display open DISP_DC, DISP_MOSI, DISP_SCK_P.

## 6b. Run bf70ecbc (straight east fans) and 861247ff

Both still route the 0.2 mm nets in the main pass (bf70ecbc router.log: `[35/73] Routing RF_50`,
`[46/73] Routing ble.ANT24_FEED`; 861247ff: `[37/73]`, `[47/73]`), so both run at the 0.2 floor:
127 and 138 "grazes foreign copper" refusals. Straightening the fans removed the lane-pitch part but
not the floor: GNSS_PPS in bf70ecbc is refused at d = 0.194 (router.log:659), legal at 0.127, under
0.2635. DISP_DC in bf70ecbc is boxed at its pad by DISP_MOSI's lane, USB_D_N's track and pad (pairs-step
copper, locked) and a GND pad (router.log:431-439); DISP_RST by DISP_SCK's route and V3V3 at the MCU and
DISP_SCK_P's pad at the connector (router.log:517-522) - the pin-order crossings.

## 7. Should placemat have flagged the termination gap earlier?

Run f929b54b (row centred): DISP_RST's contact 4 lies between R4 (CS_P) and R7 (SCK_P), whose pads
leave 0.3 mm, under 0.381 for a track and two clearances.

- `escape_walled` / `escape_closed` (`escapes.py:364-393`, `path_out` `escapes.py:675-750`): a path search
  in a window `place.escape_depth` (1.5 mm) round each pad. The termination row is 6 mm from the
  contact, so the contact's escape is open.
- `escape_crossed` (`layout.py:5402-5410`, `ratsnest.py:309-327`): crossings within the escape depth of
  a part. In f929b54b RST's straight airwire passes through the gap and crosses nothing, so nothing
  fires. (In af51c83d it did fire: "U5 pins 4/5: U16 DISP_RST crosses R7 DISP_SCK_P", "U5 pins 4/6 ...
  R6 DISP_MOSI_P".)
- `escape_lane` covers only declared lanes (`board.escape`); `copper.not_drawn` only declared copper.
- No pinch or corridor check exists for pads (`pinch` appears only in pourfit.py).

So there is a gap: nothing judges whether a net's way between its pads is closed by a pair of other
nets' pads standing closer than a track and two clearances. A check that fits placemat's existing
pieces: for each airwire, the other-net pads on the same layer whose gap the straight airwire passes
through; flag when the gap is under track + 2 clearances on every layer the net can use there. It
would also catch the reverse case a router sees as a funnel. The mid-span reversal in section 2 is a
second gap: the run score counts those crossings, but no finding names them.

## Recommendations, ranked

1. **placemat: route classes above Default in their own stage before the main pass** (a stage like the
   pairs and islands; nets whose class clearance exceeds the Default class). This follows KRT's
   documented floor model rather than working round it. Measured on af51c83d: 10 -> 8 open pad pairs;
   graze refusals in the main pass 133 -> 8. It affects every board with a 50 ohm or other wider class.
   The same applies to any net halo entered into the map: SW_3V3 is already excluded from the main pass
   here, but a halo net routed in the main pass would set a 2.0 mm floor.
2. **Board: mirror the display pins within the group** (21 DC, 22 MOSI, 23 SCK, 24 RST, 27 CS) and keep
   the board lead's lane for RST past the terminations. Measured with the class stage: 6 open pad pairs of 181 (against 8 with the class stage alone, 10 as run); DISP_DC and DISP_SCK still open.
   This is the board's own `Pm.PinGroup` freedom, no new form.
3. **placemat: lane pitch at a turn.** Lay turned lanes at least half a router grid step wider than track
   + clearance, or end them on the router's grid, so the router's terminal leg can leave them. Today they
   sit at exactly 0.254 mm and only a collinear leg is legal.
4. **placemat: a pinch check on airwires** (section 7), and a finding for a pin group whose order is
   reversed between its two ends.
5. **Router group features.** `--ordering bus` is the upstream form of "a group routes first"; with the
   default radius it groups the display and GNSS lines together, which is what they physically are. It
   orders only. Measured with the class stage and `--ordering bus` (`rb/bsplit`; detection found the 9-net display+GNSS group, LED_STATUS/VBUS_DISCH/RING_INT and MCU_EN/SCL/SDA): 8 of 181 open, the same count as the class stage alone; display open DISP_DC, DISP_MOSI, DISP_SCK_P._SHORT. `--bus` (attraction and planned corridors) works against
   a reversed pin order and its corridor probe cannot leave 0.254-pitch lane ends, so I would not use it
   here until 2 and 3 are done. A placemat-declared net group mapped to the router would need a way to
   name a group on the router's command line; KRT has none (its groups are detected, and `--group` only
   scopes a run). I would not add a placemat form for this until 1-3 are in and the display group is
   measured again.
