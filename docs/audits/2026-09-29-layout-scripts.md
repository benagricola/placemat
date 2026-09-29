# Coordinate placement in the fairing instrument's layout scripts

Read-only audit. Nothing was run and nothing in either repository was modified.

- Scripts: /home/ben/Documents/Hardware/fairing-instrument/electronics/boards (every `*_layout.py`, plus
  `core/fragment_frame.py`, `core/core_geometry.py`, `core/core_clusters.py`, `ring-test/ring_geometry.py`).
  `core/snapshots/regroup_clusters.py` is a pcbnew script, not a layout helper, and is left out.
- placemat: /home/ben/work/placemat at 8d8a9da (main). `api.md` below is
  `skills/placemat/references/api.md`; source paths are under `src/placemat/`.
- The scripts were being edited while I read them. `Core_layout.py` changed from 1074 to 1060 lines during
  the audit (it now stamps `usbconnector`, `light` and `ring` as cells). All line numbers below are from a
  snapshot taken at 2026-09-29 13:57 BST:
  `/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/snap/`.
  I compared every module file's snapshot with what I had read; only `Core_layout.py` differed, and I re-read
  its changed sections from the snapshot.

## Summary

- Across the 30 scripts I counted 401 INTENT and 477 COORDINATE declaration sites (placements and copper).
  16 of the COORDINATE sites are mechanical facts that api.md allows as coordinates (api.md:62, 76).
- In the 26 module fragments, 220 placement sites are COORDINATE. Apart from each fragment's anchor
  (`board.size(fit=True)` plus the main part at the origin, which api.md:236-238 asks for), about 16
  placement sites use an intent form. In practice every non-anchor part in a fragment is positioned by
  arithmetic, almost all of it through `fragment_frame.Content.beside()` or a local `put()`.
- The core board itself is mostly intent: 54 intent placement sites (searched cells, blocks, links, `Near`)
  against 28 coordinate ones. Its coordinate sites are mechanical facts, cells placed by where one member
  must land (7), parts pushed against the seal band (4), and keepouts over hand-built polygons (10).
- About 11 fragment placements already fit an existing form (block satellites on a pin's axis), and about 22
  copper points are numbers where a zero-offset reference or a via handle would do. Everything else needs a
  relation placemat does not have.
- Ranked missing relations: (1) beside another item's envelope, a gap off it and level with a pad, 129 sites;
  (2) pad-edge references and copper over a group of same-net pads, 99 sites; (3) rows, stacks and columns
  measured from a part rather than a board edge, 51 sites; (4) lanes a clearance off pad ends, vias or tracks,
  40 sites as the main relation and about 70 in all; (5) vias on a pad's axis, in rows, fields or stitching,
  27; (6) choosing which end of a leg takes the 45, 20 (about 32 in all). Smaller: keepouts from absolute or
  outline-derived regions (18), datasheet reference patterns (11), frames fitted in one axis (11), cells placed
  by a member (10), placement against a keepout's boundary (6), copper over a group's box (8).
- The project's own gap log already records the first, second, fourth and sixth of these
  (`electronics/PLACEMAT_GAPS.md:2807-2899` "pad edges and drawn envelopes as placement and copper references",
  and `:2753-2780` "a position that is a sum of an x and a y").

## How I counted

A site is one call in the source that declares a placement (`board.place`, `board.block` or `board.row`, a
keepout, a cutout, a label, a fanout, or a frame `board.size`) or copper (`track`, `via`, `vias`, `pour`,
`plane`, `finger`). A helper (`g.beside`, `put`, `pour_box`, `pads_pour`, `frame_planes`, `region`, `drops`,
`beside`) counts where it is called. A loop counts once, and the number of items it produces is noted as xN.
Links, rules, `faces`, `free_net` and groups are not counted; all of them are intent.

- INTENT: no `at=`, `Near(...)` as a hint, `OnEdge`, `row`, `ring`, `block`, `fanout`, labels, `FreeSpot`,
  `vias(pad)`, a via at a `PadRef`, a plane with no outline. Also the fragment anchor at `Location(0, 0)` on a
  fit frame, and `Pin`/`Centre` or track points built only from `X(ref)`, `Y(ref)` or `Mid` with zero offsets
  (api.md:216-223, 803-806).
- COORDINATE: any position that carries a computed or literal number. That covers `X(ref, d)` and `Y(ref, d)`
  with d != 0, `Location` or `Centre` with computed values, plain numbers (including `g.pad()` values in the
  frame), pour outlines built from pad or envelope boxes, and keepouts placed at computed points.
  - [mech]: a mechanical fact stated as a coordinate: the outline, the barrel's tab positions, the USB mouth,
    the coin. api.md:62 allows these. They are counted but not treated as defects.
  - [shape]: the place is an intent form, but the region's size is computed from pad or body boxes.
  - [Z]: a zero-offset reference form, or a via handle as a track end (api.md:881-884), would say the same
    thing today. These are trivial rewrites.
  - [B]: an existing block satellite (api.md:766-787) expresses it (see "Block semantics I checked").

Relation codes used in part 2 and ranked in part 3:
R1 beside an item's envelope with a gap, aligned to a pad or axis; R2 a row, stack or column relative to a part;
R3 a pad-edge reference, or copper over same-net pads; R4 a cell placed by a member's position; R5 a lane a
clearance off copper; R6 which end of a leg takes the 45, or a point on a 45; R7 a datasheet pattern in a datum
frame; R8 a frame fitted in one axis, or edges and label room on a fit frame; R9 against a keepout's boundary;
R10 an absolute or outline-derived keepout region; R11 vias on an axis, in rows, fields or stitching;
R12 a rotation stated as a pad's direction; R13 copper over a group of parts or a run between pads.

### What I checked in placemat

- Rows are refused on a fit frame: `row()` calls `_refuse_on_fit` for an `Edge` (layout.py:1679-1680, 654-656).
  `OnEdge` is refused the same way (layout.py:1559-1560), and so are `board.edge()` and `board.centre`
  (layout.py:1389, 1441).
- `Pin` places a part only. A cell is refused: "a Pin places a part by its pad; a cell has no pad of its own"
  (layout.py:1545-1547). A cell's `Location` is its box centre (layout.py:1641-1642).
- `X(ref, dx)` and `Y(ref, dy)` add a number to one reference's coordinate (values.py:423-436). A `Part` or
  `Cell` resolves to its placed body centre (layout.py:4233-4236). A pad resolves to its centre, plus
  `.offset()` or `.local()` (layout.py:4237-4245; values.py:385-394). No reference names a pad edge or an
  envelope side, and no reference adds to another (values.py:423-443; `_coord` at layout.py:4248-4260).
- A keepout requires `at=` (layout.py:1197). It has no edge handle; only a cutout has one (`CutoutHandle`,
  layout.py:331-345, 1262-1269).
- `pour` takes explicit points (layout.py:2484-2497). `swallow_pads` grows the outline by each same-net
  pad's box plus a fixed 0.12 mm when a corner of that pad lies inside it (kicad/write.py:384-399).
- A `finger` is a rectangle from centreline end to centreline end (copper.py:276-315). Its pours use the
  default 0.2 mm stroke (copper.py:109), so the drawn copper is 0.2 mm wider and 0.1 mm longer at each end
  than `width` (Ble_layout.py:70-73 compensates for this by hand).
- Tracks: a leg that is not octilinear is routed by `route_leg` (copper.py:456-472). Among the candidates
  that clear, it keeps the fewest turns, then the shortest, then a tie rule for where the 45 goes; for a
  pad-to-pad leg the tie puts the 45 at the first point (copper.py:467-468). A script cannot choose the end.
- In the physical envelope, which core/placemat.toml:4-5 sets, a row's gap is raised to at least the widest of
  the net clearance, the component spacing and the silk clearance (layout.py:793-806). So "a silk gap apart"
  is a row's default there.
- Labels in a stamped cell arrive as reservations on the parent board (kicad/read.py:421, occupancy.py:815-816).
- Planes with no outline on a fit frame are planned after the frame is fitted, inset from it
  (layout.py:2516-2518). On a sized frame they are inset from `width` x `height` (layout.py:2519-2521).

### Block semantics I checked (placer.py)

A satellite's pad on the named net lands on the anchor pin's outward normal (`_pin_normal`, placer.py:694).
The distance is `half_anchor + gap + half_sat` beyond the pin (placer.py:588-589), and the satellite's body
must lie outward of its pad (placer.py:600-603). Among the four rotations the block keeps the one with the most
body outward (key `(-outward, rot)`, placer.py:615). For a two-pad part that means lying along the normal, so a
satellite cannot be laid across the pin's axis. `gap` is a single value per block (BlockSpec, placer.py:504).
With `gap=None` each satellite takes the tightest gap, in 0.05 mm steps up to `place.block_gap_reach` 2.0 mm,
at which it clears the anchor and the satellites already laid (placer.py:581-583, 606-625). Only when nothing
on the axis clears does it slide along the pin row (placer.py:626-640). A block can be FIXED at a `Location`
or `Centre` (layout.py:3846-3850), but not placed by `Pin`.

## 1. Per-file counts

| script | INTENT | COORD | of which [mech] |
|---|---:|---:|---:|
| core/modules/statuspulls/StatusPulls_layout.py | 3 | 2 | 0 |
| core/modules/usbconnector/UsbConnector_layout.py | 4 | 4 | 0 |
| core/modules/debug/Debug_layout.py | 11 | 3 | 0 |
| core/modules/lightsensor/LightSensor_layout.py | 5 | 3 | 0 |
| core/modules/status/Status_layout.py | 15 | 5 | 0 |
| core/modules/haptics/Haptics_layout.py | 11 | 5 | 0 |
| core/modules/display/Display_layout.py | 7 | 5 | 0 |
| core/modules/environment/Environment_layout.py | 11 | 6 | 0 |
| core/modules/ringsensor/RingSensor_layout.py | 5 | 8 | 0 |
| core/modules/usbmoisture/UsbMoisture_layout.py | 17 | 13 | 0 |
| core/modules/inputpower/InputPower_layout.py | 11 | 11 | 1 |
| core/modules/gnssreceiver/GnssReceiver_layout.py | 8 | 8 | 0 |
| core/modules/backlight/Backlight_layout.py | 7 | 16 | 0 |
| core/modules/ble/Ble_layout.py | 3 | 13 | 0 |
| core/modules/monitoring/Monitoring_layout.py | 8 | 17 | 0 |
| core/modules/logicsupply/LogicSupply_layout.py | 11 | 14 | 0 |
| core/modules/sensors/Sensors_layout.py | 24 | 10 | 0 |
| core/modules/pdcontroller/PdController_layout.py | 11 | 21 | 0 |
| core/modules/usbpowerpath/UsbPowerPath_layout.py | 17 | 21 | 0 |
| core/modules/supervisor/Supervisor_layout.py | 10 | 31 | 0 |
| core/modules/usbpdsupport/UsbPdSupport_layout.py | 13 | 20 | 0 |
| core/modules/usb5v/Usb5v_layout.py | 15 | 43 | 0 |
| core/modules/protection/Protection_layout.py | 21 | 31 | 0 |
| core/modules/gnssantenna/GnssAntenna_layout.py | 4 | 12 | 0 |
| core/modules/usbconverter/UsbConverter_layout.py | 15 | 50 | 0 |
| core/modules/mcu/Mcu_layout.py | 29 | 43 | 0 |
| core/Core_layout.py | 75 | 37 | 5 |
| core/CoreCells_layout.py | 2 | 14 | 4 |
| coil-coupon/CoilCoupon_layout.py | 6 | 3 | 3 |
| ring-test/RingTest_layout.py | 22 | 8 | 3 |
| total | 401 | 477 | 16 |

Module fragments alone: 296 INTENT and 415 COORDINATE. Of the fragments' 220 COORDINATE placement sites, the
largest are Mcu 28, Usb5v 20, UsbConverter 18, Protection 17, Supervisor 14, UsbPowerPath 13 and
UsbMoisture 11.

## 2. Inventory: every COORDINATE site, its intent, and the form for it

"L<n>" is a line in that file's snapshot. INTENT sites are listed by line only.

### StatusPulls_layout.py
INTENT: 30, 32, 45.
- L35-36 (loop, x4) `Content.beside` at `PITCH` = envelope width + GAP. Intent: five upright pull-ups in one
  row, a silk gap apart, their V3V3 pads in line. No form: R2. `board.row` would space them at the physical
  envelope's gap by default, but it needs an `Edge` and is refused on a fit frame.
- L44 `pour_box` over the V3V3 pads, from `placed_size` and `g.pad`. Intent: one pour over the five V3V3
  pads. No form: R3.
- The rotation helper `up()` at L24-26 is R12.

### UsbConnector_layout.py
INTENT: 31, 33, 53-54 (x2), 56.
- L48 D+ track through `(x(DP), U_Y)`. `U_Y` is the row tips - clearance - via - clearance - half a track
  (L44-46). Intent: D+ rises past the D- vias and joins across the top. No form: R5. The x of each leg could be
  `X(PadRef)`; the y is the lane.
- L50 (x2) D- vias at `(x, VIA_Y)`. Intent: a via on each contact's axis, a clearance past the row's tips.
  No form: R11. `FreeSpot` finds the nearest legal spot (values.py:149-160), not a spot on the axis.
- L51 (x2) track from the pad to `(x, VIA_Y)` [Z]: end it on the via handle (api.md:881-884).
- L52 D- join on the inner layer between the two via points [Z]: via handles.
- The core now stamps this cell (Core_layout.py:330-335).

### Debug_layout.py
INTENT: 46, 58, 63, 66, 67, 68, 72-76 (5 vias).
- L47 `row(lights, gap=LIGHT_GAP)`. `LIGHT_GAP` = NAME_WIDTH + silk - the light's width (L41), and
  NAME_WIDTH is a measured 2.3 mm (L21). Intent: lights spaced by their names. No form: R8/R2. The labels
  could move into this fragment, since stamped labels become reservations (kicad/read.py:421), but a row does
  not space by its items' labels, and a firm item on a label reservation stops the run (api.md:941-942).
- L48 `row(pads, gap=PAD_GAP, behind=buttons, inboard=SILK + LABEL_ROOM)`, with LABEL_ROOM a measured 1.6
  (L23). Intent: the pad row behind the buttons and their names. No form: "behind a row and its labels" (R8).
- L54-57 `board.size(FRAME_WIDTH, FRAME_HEIGHT)` from the rows' lengths and depths, the label room and
  NAME_OVERHANG. api.md:232-235 allows a frame sized from its own rows; the label arithmetic is the coordinate
  part. A fit frame would include labels (api.md:35-38) but refuses rows. R8.

### LightSensor_layout.py
INTENT: 45, 47, 67, 94, 95.
- L61 `c_als` beside VDD (pad 1), dy = the sensor's envelope south + GAP. Intent: the 1 uF lying a silk gap
  south of the supply row, V3V3 on VDD's axis, ground under GND. No form: R1. A block would stand it upright
  along the axis, which is not this arrangement.
- L88 V3V3 pour from pad boxes (`box_of`, L74-77). Intent: VDD's pad down onto the wider V3V3 pad. Partly
  covered: `finger(from_=PadRef(als,1), to=PadRef(c_als,"V3V3"), width=<VDD pad width>)` joins the two pads,
  with the stroke and bridge caveats above. The widening onto the larger pad cannot be said. R3.
- L92 GND L-shaped pour from pad boxes. No form: R3.
- L37-43: rotation and asserts from pad directions (R12).

### Status_layout.py
INTENT: 48, 49, 69, 72, 73, 74, 77, 80, 81, 83, 92, 94, 96, 97, 99. L96 is a via at
`(X(pin SCL), Y(pin A0))` with zero offsets.
- L53 `c_expander` `Pin(X(pin21, -(pin half + CLEAR + pad half)), Y(pin21))`. Intent: VCC's bypass in line
  with its pin, V3V3 toward it, a clearance off the pin end. [B]: satellite `(c_expander, 21)` with
  `gap=CLEAR` is this formula exactly (placer.py:589).
- L55 `r_alert`: x from the chip's envelope left - GAP, y from the bypass's envelope + GAP. Intent: INT's
  pull-up upright under the bypass, a silk gap west of the chip. No form: R1.
- L60 `r_bb_fault`: x a lane east of pin 14, y a silk gap above the chip. Intent: FAULT's pull-up over its pin,
  clear of ALS_INT's escape. No form: R1 + R5 (keep a lane for a neighbour's escape).
- L63 `r_led_usb` `Pin(X(pin17), Y(pin13, chip envelope top - GAP - pad/2))`. Intent: upright over its pin, a
  silk gap off the chip. [B], probably: satellite `(r_led_usb, 17)` with `gap=None` takes the tightest legal
  gap, which in the physical envelope is set by the silk. Not run. One block has one gap, so putting L53 and
  L63 in one block means `gap=None`, and the capacitor gets the tightest legal spot rather than CLEAR.
- L90 A1-A2 track along the pin ends, `X(pin, -pin half + track/2)`. Intent: join the two straps at their
  ends. No form: R3 (a pad-edge reference).

### Haptics_layout.py
INTENT: 54, 56, 89, 101, 102, 103, 104-105 (x2), 106, 107, 108, 109.
- L75, L77: the pogo pins beside pin 8 at +-1.35 mm, a silk gap north of the driver's envelope. Intent: two
  pins 2.7 mm apart (the coin's tabs, [mech]), centred on pin 8, a silk gap north. No form: R1 (a pair centred
  on a pad's axis, a gap off another part's envelope).
- L83 `c_drv_vdd`, L86 `c_drv_reg`. Intent: upright beyond pin 1's end of the package, level with pin 10 or
  pin 1. No form: R1. Not a block: those pins' normals point across the rows, while these capacitors stand at
  the package's end.
- L100 (x2) OUT tracks through `(gx(pin), gy(pogo) + dx)`. Intent: rise straight from the pin, then one 45
  into the pogo pad. No form: R6. A two-point track would put the 45 at the pin end (copper.py:467-468).

### Display_layout.py
INTENT: 54, 56, 94, 104, 105-107 (x4), 108-110 (vias x4).
- L75-77 (x3) terminations over pins 3, 5 and 7, a silk gap above the connector's envelope. Intent: each
  33 ohm resistor upright over its contact, panel side toward it. [B]: satellites on pins 3, 5 and 7, on the
  axis, upright, at the tightest legal gap.
- L79 MOSI a row up. [B], probably: a fourth satellite `(r_term_mosi, 6)` listed last. Where it meets the
  laid satellites (placer.py:610), the gap loop steps outward along the axis (placer.py:621-625), which should
  give the second row within the 2.0 mm reach. Not run.
- L89 `c_panel_io` at the VLED pad's west edge - CLEAR, on `LANE_Y`. Intent: the 100 nF on the V3V3 lane,
  north-west of pin 1. No form: R5 + R1.
- L92 `c_panel_vcc`, a silk gap above the 100 nF. No form: R2 (a stack).
- L102 V3V3 track through `(gx(pin2), LANE_Y)`. Intent: V3V3 rises to a lane a clearance above the contacts'
  tips. No form: R5.

### Environment_layout.py
INTENT: 49, 51, 100, 106, 114, 115, 116, 119-121 (x6), 124, 127. L100 is a keepout at
`Centre(X(Part("sht40")), Y(Part("sht40")))`.
- L74 `c_bmp_vdd`. Intent: lying north of the top row, V3V3 over VDD, a silk gap off the mask. No form: R1
  (across the axis).
- L77 `c_bmp_vddio`. Intent: upright west, V3V3 level with VDDIO. No form: R1.
- L81 `sht40`. Intent: centred south of the pressure sensor, a via's room and a silk gap below. No form: R1,
  and the gap here is not the board's own gap.
- L85 `c_sht_vdd`. Intent: upright east of the SHT40, V3V3 level with VDD. No form: R1.
- L95 keepout `bmp581_under` at `Location(0, 0)`. [Z]: `at=Centre(X(Part("bmp581")), Y(Part("bmp581")))`,
  as L100 does.
- L135 SDA track through `_sda_turn_y`. Intent: down from SDI, one 45 into the SHT40's west column from
  outside the region between its columns. No form: R6.

### RingSensor_layout.py
INTENT: 72, 74, 155, 158, 159.
- L97 `c_vdd`. Intent: upright beyond the package's VDD end, V3V3 level with pin 7. No form: R1.
- L105 (x2) windings at `Location(ORIGIN)`. ORIGIN comes from the reader's input pads, `READER_SETBACK` and
  each terminal's turned offset (`turned()`, L50-57). Intent: the reader 2 mm inboard of the terminals,
  centred on its inputs. No form as written. Anchoring the windings' shared origin (the disc centre) at the
  frame origin [mech] and placing the reader from `Mid` of the terminals would leave only the setback as a
  number.
- L141 (x2) tanks at a `Location` computed by rotating pad offsets. Intent: each tank parallel to its
  terminal pair, inboard, a silk gap off the terminals. No form: R1 (beside a pad pair and parallel to it).
- L145 (x4) stubs ending at `t_xy`, the terminal's computed coordinate. [Z]: `PadRef(Part("l_ring<i>"), net)`.
- L153 (x4) leads through `(px, ty + |tx - px|)`. Intent: each input rises and turns once into its tank pad.
  No form: R6.
- L157 (x4) GND pins to `(gx(p), gy(EXPOSED))` given as numbers. [Z]: `(X(PadRef(ldc, p)), Y(PadRef(ldc, 13)))`.
- L166, L167 planes with outline = the group's box + VIA. Intent: planes over the reader and its bypass only,
  none under a winding. No form: R13. Keepouts that exclude fill over the windings are an alternative inside
  the API; Core does that at 283-291.

### UsbMoisture_layout.py
INTENT: 55, 57, 106, 129, 130, 134, 146, 149, 153-154, 156, 159, 162, 167, 168, 169, 170, 171.
- L58, L60 `r_up1`/`r_up2` at +-(PITCH - PMOS_SPACING)/2 from the LD pins, dy = pin half + CLEAR + track/2
  + pad/2. Intent: a pair symmetric about the LD pins, their pads on a lane a clearance above the row. No form:
  R2 + R5.
- L62, L63 `q_p1`/`q_p2`, L68, L69 `q_n1`/`q_n2`. Intent: each drain over its resistor's pad, a silk gap
  above. No form: R1.
- L64, L66 `r_down1`/`r_down2`. Intent: a silk gap west or east of the pull-up. No form: R1.
- L88 `r_excitation`. Intent: level with the PMOS row or a silk gap over the east NMOS, whichever is lower
  (L86-87). No form: R1, plus a choice between two relations.
- L97 `c_supply`. Intent: upright on VPWR's row, a clearance past the pin tips or a silk gap from the chip,
  whichever is further. No form: R1/R5.
- L100 `c_bias`. Intent: lying under VBIAS, a silk gap under the chip. No form: R1.
- L140 (x2) PMOS gates to `Y(pad, BUS_DY)`. Intent: EXCITE's bus a clearance above the PMOS source pads.
  No form: R5.
- L143 the west NMOS gate rises at `X(pad, G_RISE_DX)`. Intent: a lane east of its source's drop. No form: R5.

### InputPower_layout.py
INTENT: 63, 65, 131, 132, 134, 169, 170, 171, 172, 173, 174.
- L105 `j_gnd` 19.0 mm east of `j_vin`'s lead [mech]: the barrel sets the pitch. This is fine as a fact.
- L111 `tvs_in`. Intent: lying a silk gap east of the tab, VBIKE level with the north lead. No form: R1.
- L115, L116, L117 `below()` (L94-101). Intent: a capacitor column under the clamp, VBIKE west edges aligned,
  a silk gap apart. No form: R2.
- L124 `r_scl_pwr`. Intent: under the clamp and east of the capacitors, a silk gap from each. No form: R1.
- L127, L128 `below()` for the resistor column. No form: R2.
- L150 VBIKE pour from 12 pad edges (`edge()`, L80-91); L160 GND pour; L164 `pour_box` over the V3V3 pads.
  No form: R3.

### GnssReceiver_layout.py
INTENT: 96, 98, 162, 163, 164, 165-166 (x3 `vias`), 169-170 (x3, vias at `(X(Part gnss), Y(pin))`), 180.
- L123 `c_gnss_hf`, L125 `r_gnss_vio`. Intent: upright a silk gap off the receiver's west edge, level with
  pin 8 or pin 7. No form: R1 (across the axis).
- L131 `c_gnss_bulk`, L133 `fb_gnss`. Intent: on pin 6's or pin 8's axis, a silk gap west of the upright
  pair. No form: R1 (beside a pair's envelope).
- L153, L155-157 (x2), L158: `pour_box` strip and rows from pad halves. No form: R3.
- L176 keepout `gnss_under` [shape]: the place is `Centre(X(Part), Y(Part))`, and the size is the gap between
  the pad columns by the body height, read from boxes. No form for "the body less its pads" (R3).

### Backlight_layout.py
INTENT: 46, 48, 109, 178, 179, 180, 181.
- L77 `c_bl_hf` (a silk gap under the driver, VSHUNT under VIN), L85 `c_bl_boot` (upright a silk gap west,
  BOOT level with BOOT), L89 `l_bl` (a silk gap west of the boot cap, SW level with SW), L93 `c_bl_out`
  (under the coil's VLED end), L98 `r_bl_sense` (north, BL_LEDK over FB's bar), L101 `r_bl_dim` (upright east,
  BL_PWM level with DIM). No form: R1.
- L80 `c_bl_in`, a silk gap under the 100 nF. No form: R2.
- L147, L149, L152, L155, L161, L165, L168, L171, L174: nine pours from pad edges (`west`/`east`/`north`/`south`
  at L117-130, `narrower` at L133-141). Intent: each net is a pour over adjacent pads, as wide as the narrower
  pad. No form: R3.

### Ble_layout.py (TDK reference pattern)
INTENT: 181, 185-186, 188.
- L94 `ant24` at `Location(X0 + 4.40, EDGE_Y + 0.6 + DEPTH_SHIFT)`. Intent: TDK p7, 4.40 mm along the
  keep-out and 0.6 mm from the edge. No form: R7. The frame is sized (L152), so `OnEdge` is allowed, but it
  puts the reach at the keep-in (api.md:84-86, 180-184), not a centre at a datasheet depth.
- L122, L129, L137: the Mt, series and shunt positions, `Pin`s on `FEED_X`, stacked by envelope + GAP. No
  form: R7 + R2.
- L146 Ft `Pin(STUB_X, FT_Y)`. No form: R7.
- L152 `board.size(FRAME_W, FRAME_H)`: R8.
- L156 keepout at the computed box centre. Partly covered: api.md:466-471 anchors a datasheet `Path` on a
  pad, so TDK's keep-out could be given in TDK's coordinates and placed at an `ant24` pad.
- L165, L168, L172: fingers between `Location`s (the strip, the stub and the back strip). No form: R7.
- L175-176 (x3) back-strip vias at X0 + inset + distance along. No form: R7/R11.
- L179 feed track from `Location(FEED_X, ANT_Y)`. No form: R7/R3.
- L183 `pour_box` over pads 2, 3, 5 and 6 from pad boxes. No form: R3.

### Monitoring_layout.py
INTENT: 66, 68, 152, 186, 187, 188, 202-203, 204-205.
- L101 `c_adc`, L104 `c_pd_filter`. Intent: two upright capacitors a silk gap apart, symmetric about the
  middle of pins 7 and 8, a silk gap north of the package. No form: R2 (a pair centred on `Mid`) + R1.
- L107, L110 `r_pd_filter`, `r_pd_bias`. Intent: continuing the row, pads level. No form: R2.
- L118 `ntc_pd`. Intent: its NTC end centred on the two NTC_PD pads, a silk gap north of the row. No form: R1.
  The x alone is `X(Mid(...))`.
- L127 `c_buck_filter`. Intent: upright east of the package, ADC_BUCK level with pin 6 or a silk gap below
  row 1. No form: R1.
- L130, L133 row 2. No form: R2.
- L144 `ntc_buck`. No form: R1.
- L191, L192, L193, L194, L197, L198 `pads_pour` (L174-180). No form: R3.
- L212 (x2) track to a drop point `Y(pad, pad half + VIA/2)`, and L213 (x2) the via there. Intent: drop on
  the pin's axis, the via's ring against the pad's end. No form: R11/R3.

### LogicSupply_layout.py
INTENT: 55, 57, 135, 188, 191, 213-214, 215, 218-219, 220-221, 222, 223.
- L85 `c_3v3_hf`. Intent: upright a silk gap west of VIN and GND, VSHUNT level with VIN. No form: R1.
- L88 `c_3v3_in`, a silk gap west of the 100 nF. No form: R2.
- L97 `c_bst`. Intent: east of BST and SW, far enough for the SW pour's neck, BST a clearance under SS's lane
  (a max of two). No form: R1 + R5.
- L103 `l_3v3`. Intent: under the part and the boot cap, its west edge under the part's middle. No form: R1.
- L114 `c_3v3_out`. Intent: west of the coil's output end, dropped if the stack would reach the 10 uF. No
  form: R1/R2.
- L116 `c_3v3_out2`, over the first. No form: R2.
- L122 `r_fb_bottom`. Intent: north of FB, a silk gap above the row. Partly [B]: satellite
  `(r_fb_bottom, 8)` gives the axis and the tightest gap, but the script's row line is
  `min(chip north, c_bst top)` (L121), which a block does not do.
- L125 `r_fb_top`, L128 `c_ss`, a silk gap either side. No form: R2.
- L162 VSHUNT band, L174 GND, L186 SW, L199 FB, L211 V3V3: five pours from pad edges and clearances. No form: R3.

### Sensors_layout.py
INTENT: 84, 86, 159, 165, 181, 182, 200-203, 206, 207, 210-213, 214, 215, 219, 220, 221, 222, 223, 224.
- L118 `mag`. Intent: a silk gap north of the IMU, its SDA and SCL over the IMU's (centred between them).
  No form: R1. The x is `X(Mid(IMU SDA, IMU SCL))` less the magnetometer's own half pitch.
- L122 `c_mag`. Intent: lying north of it, ground over VSA. No form: R1.
- L129 `c_imu_vddio`, L131 `c_imu`. Intent: lying a silk gap south, V3V3 on pin 5's or pin 8's axis. No form:
  R1 (across the axis). Core_layout.py:620-624 still declares these two as block satellites.
- L136 `conv_temp`. Intent: a silk gap east of the magnetometer and north of the IMU. No form: R1, against two
  envelopes at once.
- L147 `c_temp`. Intent: a silk gap east of the IMU, low enough that one 45 from V+ lands on its pad. No form:
  R1 + R6.
- L190 GND pour over pins 6 and 7 with a neck to the capacitor's pad, and L197 `pour_box` over pins 1-3 plus
  a via's width. No form: R3.
- L198 via at `X(pin2, pad west - VIA/2)`. No form: R11.
- L218 V+ track through `(X(pad), _vp_south)`, the pad's south edge. No form: R3/R6.

### PdController_layout.py
INTENT: 54, 56, 165, 166, 185-186, 193, 194, 206, 214, 223, 225.
The north row's fan-out is built from lanes `LANE = TRACK + CLEAR` (L71-91).
- L98 `c_pp5v`. Intent: lying where the PP5V pour widens, its ground a clearance north of GPIO7's via. No
  form: R5.
- L104 `c_cc2`, on CC2's lane east of the row. No form: R5.
- L114 `c_cc1`. Intent: a 45 step north-east of pin 24, a silk gap south of CC2's capacitor. No form:
  R5 + R6 + R1.
- L122 `c_pd`. Intent: upright at the end of VIN_3V3's lane, west of GPIO6's via. No form: R5.
- L135 `c_pd_ldo3`. Intent: west of pins 1-2, the smallest of three offsets. No form: R1.
- L143 `c_pd_ldo15`. Intent: west of LDO_3V3's capacitor, a pin row up. No form: R1/R2.
- L160 PP5V pour, L172 VBUS pour. No form: R3/R5.
- L163-164 (x2) PP5V vias down the column at a pitch. No form: R11.
- L174-177 VBUS via field, 3 x 2. No form: R11. `board.vias` fills pads only (api.md:887-901).
- L181, L183, L191, L196, L198: tracks on computed lanes, and L195, L197 vias on them. No form: R5 (L183 is
  also R6).
- L203 LDO_3V3 pour from the capacitor's pad to the pin tips. No form: R3.
- L212 LDO_1V5 track through `X(_l15, _step)`. No form: R6.
- L218, L220-222 (x3): tracks to the exposed pad's edge. No form: R3.

### UsbPowerPath_layout.py
INTENT: 148, 149, 150, 181 (x2), 187-188, 197, 211, 213, 214, 217, 218, 236, 237, 238, 239, 241, 242.
- L86 (x2, `efuse_parts`) the output bypass: lying north, its output pad on the switch's centre line, a silk
  gap. L89 (x2) the ILM resistor: upright a silk gap east of ILM. No form: R1.
- L99 `c_source_in`, L109 `source_permit`, L120 `r_sink_ov_top`, L128 `sink_switch`, L132 `r_sink_en`,
  L136 `c_sink_slew`, L142 `c_sink_in`: each a silk gap beside a named part's envelope, on a pad's row or
  column. No form: R1.
- L102 `r_source_en`. Intent: in the west column over the input bypass's ground end, on the output bypass's
  row. No form: R1. Its x equals `X(PadRef(c_source_in, "GND"))`, which is expressible; its y aligns part
  origins (`same_row`, L75-77).
- L114 `r_source_permission`. Intent: east of the gate, its row a clearance and half a track under the gate's
  south pads. No form: R1 + R5.
- L106 `c_logic`, under the input bypass; L124 `r_sink_ov_bottom`, under its top. No form: R2.
- L176, L179, L185, L195 (each x2), L208, L222, L232. Intent: leave the land or pin straight, then one 45
  onto the pad (`step()`, L164-167). No form: R6.
- L250 SOURCE_EN, a via's room short of the input bypass's column. No form: R5 + R6.

### Supervisor_layout.py
INTENT: 67, 69, 178, 217, 218, 228, 245, 246, 258-259, 260.
All 14 placements are "just outside a band one escape track wide round the chip's pin sides, by the pin
served" (BAND, L43; WEST/NORTH/EAST/SOUTH, L99-102). `board.fanout(Part("mcu"), depth=BAND)` reserves that
band (api.md:160-170), but it fences searched placement only; fixed parts are checked as collisions. No form
exists for "outside the band, level with the pin".
- R1: L107 `c_sup`, L124 `ldo_aon` (centred under the chip), L128 `c_aon_out`, L130 `c_aon_in`, L141 `q_en`,
  L156 `c_vcore`, L161 `c_sense`, L175 `r_bsl`.
- R2: L112 `r_nrst`, L116 `c_nrst`, L146 `r_en_pull`, L150 `r_en_gate`, L165 `r_sense_bot`, L169 `r_sense_top`.
- L196, L198, L201, L213, L215, L220, L222: `pour_box` from pad edges (`edge()`, L185-189). No form: R3.
- L209 NRST lane and 45 off the west tips. No form: R5/R6.
- L226 via midway between the regulator's IN and OUT. [Z]: `(X(Mid(PadRef(ldo,1), PadRef(ldo,5))), Y(PadRef(ldo,5)))`.
  L227 and L229 are tracks to it, [Z] with the via handle.
- L233 PA3 into the gate, L236 the gate column, L241 the drain. No form: R6 (L236 also R5).
- L249 VBIKE lane off the east tips. No form: R5.
- L255 a via a clearance off the west tips on PA2's row, and L256 the track to it. No form: R11.

### UsbPdSupport_layout.py
INTENT: 98, 100, 178, 179, 194-195, 218, 255, 258, 259, 262, 263, 274-275, 277.
- L128 `esd_cc1`, L131 `esd_cc2`, L134 `esd_vbus`. Intent: the barrier row, each part's receptacle side on the
  outward (south) line, a silk gap apart. No form: R2. This is `row(..., line="outer")` (api.md:186-214),
  but measured from a part in a fit frame.
- L139 `q_sink`. Intent: S1 over the clamp's middle IN pin, a silk gap north. No form: R1.
- L146 `config`. Intent: over the CC diodes and the array, centred on their span. No form: R1 (centred over a
  group).
- L150 `c_config`. Intent: upright a silk gap west of the EEPROM, PD_LDO_3V3 level with VCC. No form: R1.
  Core_layout.py:752-753 declares it as a block satellite.
- L158, L159 I2C pull-ups. Intent: a silk gap apart, centred between SCL and SDA, a silk gap north. No form:
  R2 (a pair centred on `Mid`).
- L169 (x6) pull-up row along the north edge. No form: R2.
- L185 GND via between the two lines, and L191 V3V3 via north of pin 5 with a computed rise (L187-190). No
  form: R11. L192 track to it: [Z] with the via handle.
- L206, L208, L216, L243, L253, L267, L272: seven `pour_box`s from pad halves. L243 uses `exposed()`
  (L224-234), which re-reads the lands and turns them by hand. No form: R3.
- L256 #WC track to the exposed pad's north edge. No form: R3.

### Usb5v_layout.py
INTENT: 53, 55, 188, 294, 295, 310, 325, 327, 342-343, 344-345, 346-347, 348-349, 350-351, 352, 353.
- L85 `c_hf1`, L89 `c_hf2`. Intent: across VIN and PGND, a silk gap outside the regulator. No form: R1 (a
  two-pad part across two pins).
- L87 `c_in1`, L91 `c_in2`, outside their 100 nF with VIN ends aligned. No form: R2.
- L100 `coil`. Intent: east, its SW end a clearance from the PGND pads. Partly [B]: satellite
  `(coil, 10)` puts it on SW's axis at the tightest legal gap, which is set by whatever it meets first. That
  may be what COIL_X's `max()` computes (L98-99). Not run.
- L104, L106 `c_out1`/`c_out2`, L121 `c_boot` (over the `Mid` of CBOOT and RBOOT, a silk gap up),
  L133 `c_en_gate`, L137 `en_gate`, L161 `c_ff`, L177 `r_en_top`, L185 `r_rt`, L113 `bulk_a`. No form: R1.
- L115 `bulk_b`, L148 `r_fb_bottom`, L151, L154, L181. No form: R2.
- L142 `c_vcc`. Intent: VCC's 1 uF west of its pin, VCC end east, a silk gap off the regulator. [B],
  probably: satellite `(c_vcc, 2)` on the axis at the tightest legal gap.
- L226, L245, L252, L258, L275, L280, L288, L291, L296-301 (six `pads_pour`s), L338: pours from pad edges
  (`edge_at`/`edge`, L201-213; `pads_pour`, L216-222). No form: R3.
- L234 SW track up the lane between RBOOT and the north VIN pad, with a hand `assert` at L232. No form: R5.
- L304, L305 AGND track and via a clearance off the pin's end. No form: R11.
- L313 EN 45. No form: R6.
- L326 BIAS via in its west land, flush with the south edge. No form: R11/R3.
- L328, L332 output sense on In3. No form: R5 (L328 also R6).
- L364-367 PGND via rows, half a pitch off the coil's SW pad, as many as fit. No form: R11.

### Protection_layout.py
INTENT: 86, 88, 199, 246, 261, 262, 263, 264, 265, 298, 299, 300, 303, 316-317, 318-319, 351, 372, 373,
374, 375, 376.
- L114 `r_shunt`, upright over OUT a silk gap above the eFuse. OUT is on the east column, so this is not on a
  pin's axis. No form: R1.
- L117 `q_revpol`, L123 `revpol`, L127 `c_rev_cap`, L167 `isense`, L177 `r_ina_n`: each a silk gap beside a
  named part, level with a pad or centre line. No form: R1.
- L133 `c_vprot_in`. Intent: a clearance past IN's top pin end, a silk gap under the controller. No form:
  R1 + R5.
- L146 `r_div_top`. Intent: UVLO level with its pin, a lane west of the pin ends. No form: R5 + R1.
- L150, L154, L157, L181: the divider chain and the filter levels. No form: R2.
- L174 `r_ina_p`. Intent: over VIN+, clear of VIN-'s rise. No form: R1/R5.
- L140 `c_vprot`, L159 `r_ilim`, L161 `r_pgood`: each at pin half + CLEAR + pad half on its pin's row. [B]:
  one block anchored on `efuse`, with `gap=CLEAR` and these three as satellites, matches placer.py:589, and
  the block would stand at the frame origin.
- L188 `c_isense`. Intent: upright over VS+, a clearance over its tip. [B] on an `isense` anchor, but
  `isense` is itself placed from the shunt (L167), and a block cannot be `Pin`-placed, so the anchor's
  position stays R1.
- L238, L244, L254, L276, L293, L312 (x2), L355, L369: pours from pad edges. No form: R3.
- L289 OVP, a 45 through the middle of a gap between two pads. No form: R6 + R5.
- L296 DVDT 45. No form: R6.
- L336, L343: Kelvin taps along the shunt pads' inner edges, then lanes. No form: R3 + R5.
- L348 VIN+ branch, L366 INA_N. No form: R5/R6.

### GnssAntenna_layout.py
INTENT: 349, 351, 367, 370-371.
- L230 `ant` at `Location(CLEARANCE_LEFT + W/2, EDGE_Y + inset + depth/2)`. No form: R7 (a datasheet depth
  from the edge datum) + R8 (a frame width from the network's span).
- L246, L265, L279 keepouts at `Location(ANT_AT)`. [Z], probably:
  `at=Centre(X(Part("ant")), Y(Part("ant")))` with the same anchor. That equals ANT_AT only if the body is
  centred on the origin, which I did not check.
- L303 `r_ant_series`. Intent: on the feed's line, clear of the clearance by the class gap. No form: R1 + R9.
  Its y alone is `Y(PadRef(ant, "ANT_TRACE"))`.
- L318, L321 shunts, `Centre(X(Part series, +-across), ...)`. Intent: across the corridor at a pad, at the
  larger of the courtyard touch and the copper clearance. No form: R1.
- L342 `board.size(FRAME_W, FRAME_H)`: R8.
- L384-385, L388-389 stitching vias: at most 2 mm apart and 0.35 mm from the ground's edge, along two sides
  of the clearance. No form: R11 (stitching along a region's edge at a pitch).
- L395 split-contact via and L396 track from a point computed by sin/cos. The start may be expressible as the
  antenna's own pad (a `PadRef`) if that contact is a pad; I did not check the footprint. The via is R11.
- `gap_between` (L128) and `shunt_at` (L159) are defined but not called.

### UsbConverter_layout.py
INTENT: 122, 123, 333, 337, 351, 388, 402, 433, 434-436, 444, 450-451, 470-472, 474, 475, 480.
- L170 (x3 through `comb`, L174-176). Intent: three resistors stacked over the ISP sense lane, fed by parallel
  45s. No form: R5 + R2 + R6. L131-133 and PLACEMAT_GAPS.md:2753 describe the missing x + y sum.
- L189 `c_vcc_bb`, L191 `r_agnd`, L213 `c_comp`, L226 `c_boot2`, L235 `l_vbus`, L247 `c_vbus_in_a`,
  L261 `r_vbus_sense`, L267 `c_vbus_pd`, L399 `r_vbus_en`: each a silk gap beside a named part, level with
  a pad or centre. No form: R1.
- L200 `r_ilim_bb`: ILIM at the end of pin 17's 45. No form: R6 + R1.
- L208 `r_comp`: a clearance off the tips, a lane off pin 17's track or a silk gap from ILIM. No form: R5 + R1.
- L230 `c_boot1` and L249 `c_vbus_in_b`, a stack and "beside the first". No form: R2.
- L243 `q_buck`: its switch pad a gate-via lane from the inductor's terminal. No form: R1 + R5.
- L257 `c_vbus_out`: a Kelvin lane east of pin 11. No form: R5.
- L275 `r_fsw`: at the foot of FSW's lane, a silk gap under the output capacitor. No form: R5 + R1.
- L296, L299, L312, L319, L323 pours, L304 and L306 SW zones: outlines from pad refs and pad-edge offsets.
  No form: R3.
- L330 keepout `isp-sense` [shape]: at `PadRef(vbus_conv, 12)`, sized as the pad plus CLEAR. R3.
- L340, L342 BOOT1/SW1 through the pin's west edge. No form: R3.
- L354 DR1L lane, L390 VIN run, L417 ISP pair, L423 ISN, L427 FSW. No form: R5 (L423 also R3).
- L381, L382, L389, L397 (x3), L407, L453 vias at `PadRef.offset(...)` or in staggered rows under the pins
  (`south_via`, L373-379). No form: R11. L383, L398 (x3), L408 are the tracks to them (R11).
- L386, L387, L392, L403, L454: tracks whose ends are via positions. [Z] with the via handles.
- L437 MODE, L439 CDC, L442 ILIM: the comb's 45s. No form: R6.
- L462 AGND plane whose outline is pad refs +- VIA. No form: R13.

### Mcu_layout.py
INTENT placement sites: 80 (block, S3R8), 126 (fanout), 132, 334 (`Pin` from `X(pad)`/`Y(pad)` with zero
offsets), 441 (block), 455, 460, 465, 470, 475. INTENT copper: 116, 503, 504, 511, 516, 517, 522, 531, 532,
533, 534, 535, 559, 560, 561, 579, 599, 633-635, 636-638.
- L109 `mcu` block at `Centre(MCU_X, MCU_Y)`. Intent: against the east side with a fanout band's room, the
  flash north, a row for the series links between. No form: R8 + R1. `OnEdge` works on a sized frame, but
  here the frame is declared later (L477) and its height depends on the content.
- L204 `l_xtal`: its XTAL_P pad against the pin ends, its top edge on XTAL_N's lane clearance. No form:
  R5 + R3.
- L210 `xtal`: its silk a silk gap from the inductor, its north pads level with XTAL_P. No form: R1.
- L227 `c_xtal2`: a clearance above XTAL_N's run, over its corner. No form: R5.
- L234 `c_vdda_10n`, L271 `c_rf_post`, L274 `c_en`, L328 `l_rf_match`, L331 `c_rf_chip`, L364 `c_rf_pre_100n`,
  L372 `c_xtal1`. No form: R1. Several take a max of two relations (L270, L327); L271 and L274 are also R5.
- L237 `c_vdda_1u`, L277 `r_en`, L367 `c_rf_pre_1u`, L392 `r_strap45`, L406 `r_boot`, L409 `r_strap3`,
  L429 `c_vspi_100n`. No form: R2 (L409 also R5).
- L361 `l_rf_supply` (on the south edge, a clearance west of RF_50's way out), L375 `c_mcu_bulk` (against the
  west edge), L390 `r_strap46` (against the west edge, the minimum of three relations, L387-389), L395
  `r_uart_tx` (the north-west corner), L399 `r_led_status` (the north edge). No form: R8. `OnEdge` would say
  these on a frame whose width is fixed and whose height is fitted; placemat has no such frame.
- L418 `c_rtc`, L425 `c_cpu`, L427 `c_vspi_1u`: a fanout lane off the pin, across its axis. No form: R5.
- L450 `flash` block at `Centre(MCU_X, keep_in + FLASH_HEIGHT/2)`. No form: R8. Its x alone is
  `X(Part("mcu"))`.
- L477 `board.size(FRAME_WIDTH, FRAME_HEIGHT)`: the width is the core's room (L50) and the height comes from
  the content (L289-311). No form: R8.
- L487, L488, L489 planes over the frame inset by the keep-in. [Z]: `board.plane(net, layers, inset=board.keep_in)`
  with no outline on a sized frame (layout.py:2519-2521), as `fragment_frame.frame_planes()` does.
- L509 VDDA pins joined along their ends. No form: R3.
- L514, L524, L545, L556, L602 pours from pad halves. No form: R3.
- L564 RF_50 straight to `(X(pad), FRAME_HEIGHT)`: a point on the frame's edge (R8).
- L574, L577 XTAL_N run over the crystal, and L590 the XTAL_1 column. No form: R5 + R6.
- L594 and L624 (x2 through `south_strap`, L628-629): the straps' 45s. No form: R6.

### Core_layout.py (snapshot)
INTENT placement sites (54): 404, 431, 433, 512, 513, 520, 528, 546, 550, 552, 555, 559, 562, 575, 580,
620-624, 625-626, 627-629, 638, 640, 656, 679, 692-694, 702-706, 709, 714, 717-720, 721-726, 731, 734, 737,
738, 746-749, 752-753, 754-759. INTENT copper (21): 258, 259, 270; the `plane_drop` loop at 788;
`drops` at 861, 921, 956, 958, 983, 999, 1049, 1050, 1051; `beside` (FreeSpot) at 925, 1000-1003; tracks at
924, 966, 1057.
- L145 vent cutout at `rider(-9.5, -tab reach top + clearance + radius)`. Intent: north of the return tab,
  clear of its shoulder by the copper clearance. No form: R1 (beside a part's reach).
- L152 ear holes, L154 outline, L489 and L491 the input tabs at +-9.5 mm: [mech].
- L600 coin keepout at `rim(bearing, r)` [mech]. `Polar(radius, bearing, about=<disc centre>)` can state it
  (values.py:633-653; keepouts take `Polar`, api.md:474-475), though still as numbers.
- L157 (x4) ear keepouts, L201 (x4, through `region()` at L174-178) the seal band polygons, L203 (x2) the seal
  corner circles, L243 and L246 (x2 each) the height rings, L283, L286, L289 the ring plane gap and the
  winding sectors, L310 and L315 the outside regions. Each passes absolute points and sets `at=` to the
  polygon's own box centre so that it lands where it already is. No form: R10.
- L302 `Cell("ring")`: `Centre` from rotating a member offset (L296-305). No form: R4.
- L333 `Cell("usbconnector")`: `Centre` = the mouth point + (box centre - `j_usb` origin). No form: R4 on a
  [mech] point.
- L353 `Cell("light")`: ALS_X from reach arithmetic beside the receptacle (L345) and `south_of_rim`
  (L336-342). No form: R4 + R1 + R9.
- L386 `Cell("ble")`: through `_ble_rider_x`/`_ble_north_limit` (L363-385). No form: R4 + R9.
- L399 `gnss.gnss` at `rider(0, NORTH_SEALED + reach top)`. Intent: on the arm's axis against the seal band's
  inner edge. No form: R9.
- L401 `Cell("gnss.ant_rf")`: `Centre` from member offsets and a setback (L163-171). No form: R4 + R7.
- L423 `Cell("debug")` at `rider(0, DEBUG_CENTRE_Y)`. Intent: against the south seal crossing. No form: R9.
- L453 `Cell("display")`: `Centre` = FFC_XY [mech] + member offset. No form: R4.
- L466 `Cell("logic")` at `rider(0, MCU_CELL_Y)`. Intent: against the bench panel, FIXED_CLEAR north of it.
  No form: R1 (beside another cell).
- L504 keepout circle at `PadRef(j_vin, 2)` [shape]: the diameter comes from the lead box and a courtyard
  margin.
- L613 `Cell("haptics")`: `Centre` by mirroring and rotating the pins' midpoint offset (L607-615). No form: R4.
- L857 GNSS feed track to `Y(_rf_in, RF_VIA_Y)`, and L859 the via at the RF_IN pad's antenna end. No form:
  R11/R3.
- L863 `gnss.j_ufl` `Pin(1, X(_rf_in), Y(_rf_in, via + pad half))`. Intent: its signal pin against the via.
  No form: R1.
- L866 track from the via point. [Z] with the via handle.
- L883 RF_50 column west of the reset button's pad by a pad half + RF50_EXIT. No form: R5.
- L917 VBIKE, L951 VSHUNT, L980 PP5V, L996 VBUS and L1042 USB_HV: In2 zone outlines from pad refs, pad halves
  and literal offsets. VSHUNT has 1.0, 1.9, 3.5, 1.5 and 2.1 at L934-948; VBUS has 0.8, 1.0 and 0.9 at
  L989-993; USB_HV has 9.0, 7.5, 13.0 and 12.0 at L1040-1041, which L1037-1039 calls "placement-bound". No
  form: R13 (a power run between pads at a width). These literals stop matching when the searched cells move.
- `SOUTH_TIP` (L320) is computed and not used, and `bypass()` (L659) is not called.

### CoreCells_layout.py
INTENT: 114, 115.
- L60 vent (R1, repeated from Core). L66 ear holes, L68 outline, L108 (x2) windings at `rider(0,0)`, and L120
  `j_usb` at the mouth: [mech]. L71, L97, L99 and L105 keepouts over absolute polygons: R10. L139, L143 and
  L147 cells placed by a member: R4. L185 and L208 park cells and parts at computed `Location`s (a parking lot
  east of the board): no form for packing groups beside a board.
- The docstring (L15) says to keep this file in step with Core. It has drifted:
  - it places `Part("usbconnector.j_usb")` (L120), while Core now places `Cell("usbconnector")` (Core:333);
  - its windings are `Part("l_ring0")`/`Part("l_ring1")` (L93), while Core's are `ring.l_ring0`/`ring.l_ring1`
    (Core:190);
  - its CELLS (L50-54) do not list `usbconnector` or `light`.

  I did not check which of these names exist in the current netlist. The drift is a cost of encoding the same
  derived positions in two scripts.

### CoilCoupon_layout.py
INTENT: 22, 30, 31, 33, 35, 37. COORD [mech]: L27 coil, L28 and L29 probe pads, all fixed test-fixture
positions.

### RingTest_layout.py
INTENT: 136, 137, 146 (keepout at `Centre(X(Mid(pad1, pad20)), ...)`), 151, 153, 181, 183, 194, 197, 203,
206, 207, 212, 216, 227, 231, 235, 237, 239, 247-248, 249-251, 270-274.
- L111 outline [mech]: the south arm's length comes from the N17's reach + keep-in.
- L133 windings, L140 N17: [mech].
- L115, L118, L125, L130 through `region()`. No form: R10.
- L157 `j_lra` `Near(disc centre)` with radius = spacer radius - the header's half-diagonal. Intent: only
  inside the display spacer, where the case leaves 6.05 mm. Existing form: a parts keepout outside the spacer
  with `max_height=` (api.md:574-585; layout.py:1206-1210). That lets every part be searched and admits only
  the low ones, which is what the `Near` radius approximates. Core states the same relation with
  `allow=fitting(...)` from a heights JSON (Core:234-248) rather than `max_height`.

## 3. Recurring missing relations, ranked

Counts are my hand tally of part 2, one per call site under the relation named first. "In all" adds the sites
where the relation is named second.

1. R1, beside an item's envelope: a gap off another part's or cell's drawn envelope on one side (by default
   the board's own gap), aligned on the other axis to a pad, a pad's row or column, or a `Mid`. 129 sites.
   This is what `Content.beside` + `drawn_from_pad` and every `put()` compute. A variant places a two-pad part
   across two pins' axes (LightSensor:61, Usb5v:85). Examples: Backlight_layout.py:85 (upright a silk gap west
   of the driver, BOOT level with BOOT), UsbPowerPath_layout.py:128 (the sink switch a silk gap east of the
   divider column), Core_layout.py:466 (the MCU cell FIXED_CLEAR north of the bench panel).
2. R3, pad-edge references and copper over pads: a pad's west, east, north or south edge usable in
   `X`/`Y`/`Pin`/track and pour points, and a pour over a set of adjacent same-net pads or a neck as wide as a
   named pad. 99 sites, nearly all of them pours. Examples: Usb5v_layout.py:296-301 (`pads_pour`),
   InputPower_layout.py:150 (VBIKE over 12 pad edges), Status_layout.py:90 (a track along the pin ends).
3. R2, rows off a part: a row, stack or column measured from a part, pad or `Mid` rather than a board edge,
   including pairs symmetric about a line, and usable on a fit frame. 51 sites. `row()` has the spacing,
   alignment (`line=`) and `before`/`after` already, but it needs an `Edge` and is refused on fit frames.
   Examples: StatusPulls_layout.py:35 (five pull-ups), UsbPdSupport_layout.py:169 (six pull-ups),
   Monitoring_layout.py:101-110 (a row fanned about the middle of pins 7 and 8).
4. R5, lanes: a line held a clearance plus half a track off pad ends, a pad row, a via or another track, for
   a track leg, a via row or a part's column. 40 sites as the main relation, about 70 in all. Examples:
   PdController_layout.py:80-91 (LANE_30/31/32 and the tracks on them), UsbConnector_layout.py:44-52,
   Mcu_layout.py:418-427 (bypasses a fanout lane off their pins).
5. R11, vias beyond FreeSpot and vias(pad): on a pad's axis just past its end, in rows under a pin row, in a
   field inside a pour, or stitched along a region's edge at a pitch. 27 sites. Examples:
   UsbConverter_layout.py:373-408 (staggered via rows), PdController_layout.py:174-177 (the VBUS field),
   GnssAntenna_layout.py:384-389 (stitching).
6. R6, 45-degree legs: which end of a leg takes the 45 ("leave the pin straight, then 45 into the pad"),
   and points defined on a 45 from a pad or a corner. 20 sites, about 32 in all. `route_leg` already makes
   the 45 but chooses the end itself (copper.py:456-472). Examples: UsbPowerPath_layout.py:176-195,
   Haptics_layout.py:100, UsbConverter_layout.py:437-442.
7. R10, regions as keepouts: a keepout from an absolute path (there is no `at`-free form; layout.py:1197),
   or from shapes the core needs (an annular sector, a band inset from the outline, a region beyond a
   crossing). 18 sites. Examples: Core_layout.py:174-178 with 201 (the seal band), RingTest_layout.py:97-101,
   core_geometry.py:209-227 ("a keepout shaped like the board has to be given points").
8. R7, datasheet reference patterns: parts, copper and keepouts given in the datasheet's own frame from a
   datum edge, then placed as a unit. 11 sites in 2 files. api.md:466-471 covers a keepout shape anchored on a
   pad, not the parts or copper. Examples: Ble_layout.py:94-183, GnssAntenna_layout.py:183-263.
9. R8, frames: a frame fitted in one axis and fixed in the other, rows or `OnEdge` on a fit frame's declared
   edge, and label room. 11 sites. Examples: Mcu_layout.py:477 with 361-399, Debug_layout.py:54-57.
10. R4, a cell placed by a member: `Pin` (or a `Centre`) that puts a named member's origin or pad at a point,
    with the cell's rotation and face applied. 10 sites; Core added three during this audit. Examples:
    Core_layout.py:296-305 (ring, with a rotation matrix), 607-615 (haptics, mirrored and turned), 330-335
    (usbconnector).
11. R13, copper over a group: a plane or zone over a group of parts' box plus a margin, or a power run
    between pads at a width. 8 sites. Examples: RingSensor_layout.py:162-167, Core_layout.py:917-1048.
12. R9, against a region: an item pushed to a keepout's boundary (the seal band), as cutouts allow through
    `board.cutout(name).edge(side=)` (api.md:435-443). 6 sites. Examples: Core_layout.py:392-400,
    416-424, 336-347.

Not coordinates, but the same habit: R12, rotations computed from pad directions (`up`, `lying`, `facing`,
`turn_where`, `east_rotation`, `two_pad_rotation`, `drv_rotation`, `ldc_rotation`), in 14 files. Another 8
files hard-code rotations with a comment naming the pad direction.

## 4. Coordinate-only helpers and what would retire each

### fragment_frame.py
- `size` (L16-18): a box's width and height. Used for pad sizes; retired by R3.
- `turn` (L21-24): re-implements placemat's rotation of an offset. `PadRef.local()` (values.py:389-394) turns
  an offset with its part already; the relations below retire the rest.
- `pad_from_origin` (L27-32): a pad's centre from its part's origin at a turn. It asserts the part is
  generated unturned. It is used for rotations (R12) and for offsets (R1). Retired by R12 plus R1.
- `inner_layers` (L35-40): the inner layer a back-stamped cell draws on. This is layer bookkeeping, not a
  coordinate.
- `frame_planes` (L43-54): an intent wrapper around `board.plane` with no outline on a fit frame
  (layout.py:2516-2518). Keep it.
- `shifted` (L57-61): moves an `X`/`Y` by d, through `dataclasses.replace` on placemat's reference fields.
  With `pour`/`pour_box` (L64-76), it draws a rectilinear pour inset by the fillet and stroked at twice the
  fillet to round the corners. Retired by R3 (a pour over pads with a corner radius); `board.pour` already
  takes `stroke=`.
- `Content` (L79-135) keeps its own table of where each part's origin, rotation and body box will land,
  ahead of placemat, so later parts can be placed from computed numbers:
  - `pad` (L96-100);
  - `beside` (L102-113), which emits `Pin(pad, X(ref, dx), Y(ref, dy))`;
  - `box` (L115-119), which RingSensor uses for its plane outline;
  - `place` (L121-135), the anchor at `Location(0,0)` or offset from another Content.

  Retired by R1 and R2, by R13 for the group box, and by blocks where the relation is a pin's axis.
- `_first_pad` (L138-140): a helper for `Content.place`.
- `drawn_from_pad` (L143-154): the drawn envelope relative to one of the part's pads, through the private
  `placemat.envelope.drawn_envelope` (envelope.py:17-29). Retired by R1. The public question for a similar
  box is `board.envelope(item, rotation)` (api.md:26; layout.py:808-818), but I did not check that the two
  return the same box. `drawn_envelope` is also imported directly by Status_layout.py:15,
  UsbConverter_layout.py:37 and Mcu_layout.py:24.
- `placed_size` (L157-160): a pad's size as turned. Retired by R3.

### Module-local helpers
- `gx`/`gy` (13 fragments): a pad's centre as a frame number. Replaced by `X(PadRef)`/`Y(PadRef)` [Z] where
  the offset is zero, and by R1 elsewhere.
- `put(...)` (Environment:62, Backlight:63, Monitoring:79, LogicSupply:72, Sensors:97, Supervisor:83,
  UsbPdSupport:118, Protection:103): puts a pad at a frame point, stated as an offset from a placed pad.
  Retired by R1 and R2.
- `env`/`edges` (Backlight:51, LogicSupply:60, Monitoring:86, Sensors:103, UsbPdSupport:111,
  Supervisor:63, Protection:91), `edge`/`centre_line`/`same_row` (UsbPowerPath:64-77), `drawn_box`
  (UsbConverter:105-110): envelope sides as numbers. Retired by R1.
- Pad-edge helpers retired by R3:
  - `edge`/`edge_at` (InputPower:80-91, Monitoring:160-171, Usb5v:201-213, Supervisor:185-189);
  - `box_of` (LightSensor:74-77, Sensors:172-175);
  - `west`/`east`/`north`/`south` (Backlight:117-130, UsbConverter:81-94) and `narrower` (Backlight:133-141);
  - `half`/`placed_half` (GnssReceiver:67-70 and 109-112, UsbPdSupport:65-73, LogicSupply:148-150,
    Usb5v:66-68, Supervisor:89-91, UsbConverter:74-78);
  - `exposed` (UsbPdSupport:224-234).
- `pads_pour` (Monitoring:174-180, Usb5v:216-222): a pour over adjacent same-net pads. Retired by R3.
- `below` (InputPower:94-101): a column. Retired by R2.
- `step` (UsbPowerPath:164-167) and `south_strap` (Mcu:621-625): 45 legs. Retired by R6.
- `turned` (RingSensor:50-57): the windings' terminals as numbers. Replaced by `PadRef` by net [Z] plus R1.
- `ctl_pin`/`ctl_x`/`ctl_y`/`comb`/`south_via` (UsbConverter:141-171, 377-378): frame numbers re-anchored on
  pin 16, because `X(Part)` is the body centre and not the origin (PLACEMAT_GAPS.md:2753-2780). Retired by
  R5, R6 and R11.
- GnssAntenna `pad_offset`/`courtyard_half`/`pad_half`/`pad_to_courtyard`/`gap_between`/`shunt_across`/
  `shunt_at`/`shunt_beside`/`net_reach_below` (L56-166, L308-331): a hand model of the courtyard and copper
  gaps with a COURTYARD_TOUCH fudge (L125). Retired by R1. In the physical envelope the placer keeps those
  gaps itself; for rows that is layout.py:793-806.
- Mcu `land_gap`, `_row_bottom`, `reach_half_h`, `reach_w`, `pin_y`, `_body_dx` (L168-172, L295-297,
  L348-355, L319-320, L610-611): frame and row arithmetic. Retired by R8 and R1.
- Core `region` (L174-178): retired by R10. `south_of_rim` (L336-342): retired by R9.
  `_ble_rider_x`/`_ble_north_limit` (L369-377): retired by R4 + R9. `pad_half` (L819-822): retired by R3.
  `lane_arc` (L1019-1023): retired by R13, plus a run along the rim. `plane_drop`, `drops` and `beside`
  (L774-838) are intent (`FreeSpot`, `vias`).
- CoreCells `park` (L171-179) and RingTest `region` (L97-101): no form for the first; R10 for the second.

### core_geometry.py, ring_geometry.py, core_clusters.py
- `core_geometry.py` holds mechanical geometry in the study's rider frame: the outline, ears, seal band,
  sectors, and the rider/rim conversions (L87-105). As data it is legitimate. Its region builders exist only
  to hand keepouts absolute polygons: `board_outline_points` (L209-227), `sector` (L230-234), `annulus`
  (L237-240), `seal_band_regions` (L254-280) and `outside_regions` (L283-295). R10 would retire them,
  including a band inset from the outline. `rim()` for points is `Polar(about=)` (values.py:633-653).
- `ring_geometry.py`: coil sectors, the N17 clearance derivation and the test outline. Mechanical, plus R10
  (L82-105).
- `core_clusters.py`: data only (which parts belong to which module, and their faces). No coordinates.

## 5. Changes possible with the current API

- Blocks for bypasses on a pin's axis: Status:53 and 63, Display:75-79, Protection:140, 159 and 161 (one
  `efuse` block with `gap=CLEAR`), Protection:188 (the anchor still R1), Usb5v:142, and probably Usb5v:100.
- Zero-offset references and via handles as track ends: Environment:95, RingSensor:145 and 157,
  Supervisor:226-229, UsbConverter:386, 387, 392, 403 and 454, UsbConnector:51-52, UsbPdSupport:192,
  Core:866, and probably GnssAntenna:246, 265 and 279.
- `board.plane(..., inset=board.keep_in)` with no outline instead of `_content`: Mcu:487-489.
- `max_height=` keepouts for the case's height bands instead of `Near` radii or `allow=` lists:
  RingTest:157 and Core:243-248.
- `board.envelope()` instead of importing `placemat.envelope.drawn_envelope`, if the boxes match (not checked).
