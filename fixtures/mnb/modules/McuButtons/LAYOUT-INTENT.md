# McuButtons layout intent

MCU control cluster (BOOT + RUN + status LED), root `modules/McuButtons/`

The spec `McuButtons_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: hardware design guide Ch 5.4/Fig 8 (RP2350) + ST NRST/BOOT0 practice (STM32) + the enclosure-parts rule.

**The rule this cell encodes:** a part whose position is dictated by the
ENCLOSURE (finger access, edge proximity, a lid hole, a light pipe) must not
be trapped inside a functional module, or it dictates that module's board
position and through it the IC's. The converse holds: OptoSense keeps its
NPN/PNP selects and its series LED in-cell because those have no enclosure
demand.

**Contents (nothing else):** SW1 = BOOT + its 1k series R (R1) onto the flash
chip-select; SW2 = RUN/reset + its 1k pull-up (R3); C1 = the optional reset
RC cap (DNF by default); D1 = the MCU status LED (blue, KT-0603B) + its 180R
(R2). Controls and the indicator for the same IC live together. Electrical
source: hardware design guide RP-008280 Ch 5.4 / Fig 8 (BOOTSEL pulls
QSPI_SS low through 1k at reset; RESET pulls RUN low; RUN carries a 1k
pull-up above the internal weak one). LED sizing is the thin-3V3-headroom
case: blue Vf 2.6-3.1 V leaves about 0.2-0.7 V across R, sized against Vf
min at about 4 mA (175R -> 180R E24).

**io():** `boot_cs` (the live flash-CS / BOOT0 node; the series 1k is on
this side, so the board's run to the MCU cell's `QSPI_SS` is a real QSPI stub: keep
it short), `boot_com` (the BOOT switch's common rail), `run` (RP2350 RUN /
STM32 NRST), `status` (the GPIO, high-side drive), `v3v3` (reset pull-up
supply only), `gnd`. the MCU cell's matching `QSPI_SS`/`RUN` io are optional, so a
board without this cell still builds.

**One cell, both MCU families.** The only thing a boot/reset cluster changes
between families is which rail the BOOT switch closes onto, so that is what
is exposed: `boot_com` defaults to the cell's own `gnd` (RP2350 BOOTSEL pulls
the flash CS down); an STM32 board passes `boot_com = v3v3` (BOOT0 asserts
high). The RESET switch does not differ (RP2350 RUN and STM32 NRST are both
active-low, closed to ground, idle-high off an internal pull-up), so there is
no `run_com`. The idle-level pull that must survive the cell being unfitted
(BOOT0's pull-down) stays at the MCU. Configs: `boot_r_value`,
`run_pu_value` (STM32: `"10kohm"`), `fit_reset_cap`/`reset_cap_value`,
`led_r_value`. Optional part = DNF, never a conditional instantiation: C1 is
always placed and `skip_bom` keeps it off the BOM unless `fit_reset_cap`;
a config that adds or removes footprints would churn refdes and fork the
layout. An STM32-config instance re-nets SW1's C/D pads and their fence vias
to 3V3 automatically, geometry identical.

**Access face (binding on boards):** the cell's NORTH face (the two switch
courtyards' north edge) is the access edge, and the board edge sits about
0.5 mm PROUD of that face, never on it. The nearest copper is 0.45 mm inboard
of the access face, so a 0.5 mm-proud edge yields about 0.95 mm
copper-to-edge. Nothing in this cell is ever placed north of the access
face. (`switch_style = "side"` selects the side-actuated variant for a sealed
board with no lid holes.)

**Placement idioms:**
- One aligned row: BOOT, RUN and the STATUS LED sit on a single centre line
  parallel to the access edge, so an enclosure gets ONE drill line for two
  plungers and a light pipe. Alignment here is the enclosure interface.
- Button pitch 8.60 mm (3.5 mm body gap): the one-finger-at-a-time number.
- Buttons at rot 180 put the COMMON pads outboard (a via fence at the edge,
  tactic 3) and the signal row south, so every signal leaves toward the MCU
  and no net turns back at the edge. The fence is a plane hand-off either
  way (gnd, or the 3V3 plane for SW1 when `boot_com = v3v3`).
- LED at rot 270 so its cathode joins the same north gnd fence.
- The passives stand in ONE COLUMN in the 3.5 mm gap between the two
  switches, on their mid-axis: C1 (reset cap) at the top, R3 (RUN pull-up)
  under it, R1 (BOOT series) at the bottom with its BOOT_SW pad just above
  the switches' signal row. The gap the finger rule already pays for is the
  column's room, so the cell ends 0.6 mm below the switch pad row instead of
  4 mm below it; each passive joins its net with one 45 off the switch's own
  pad-pair bridge (R3's run pad reaches SW2's west pad on one 45, R1's
  BOOT_SW pad takes one 45 off SW1's bridge). R2 (LED series) lies E-W under
  the LED, its led_a pad north on one 45 into the anode.
- C1 (reset cap) filters the whole reset net rather than one pin, so it
  heads the column and its run pad runs straight down into R3's. If a
  board's MCU is far from the cluster, prefer ST's "cap at the NRST pin" and
  leave C1 DNF.
- Pad-pair bridges: A/B (and C/D) are one terminal inside the switch; the
  script draws the bridge in copper anyway so connectivity is explicit.
- Pickup vias: `run` carries a via on SW2's west signal pad as the board's
  far-layer pickup. The hand round also placed a via on SW1's east signal
  pad (BOOT_SW) and on the LED anode (STATUS_LED_A); both are cell-local
  nets and the vias are kept as placed.

**Silk: KNOCKOUT labels, own band.** BOOT / RUN / MCU (the status LED's
label), 0.9 mm text, knockout, each centred on its own control, in a band
3.6 mm south of the control line, never at the access edge where an outline
would trim them. `PCB_TEXT` +
`SetIsKnockout(True)`; keep the boxes clear of pads and signal copper.

**Envelope:** footprint union about 17.8 x 5.8 mm; max copper beyond the
access face 0.000 mm (0.45 inboard). The labels sit inside the parts' x
span. Fill is not the
objective for an enclosure-driven cluster: button pitch, edge offset and
label legibility are. `boot_cs`, `run` and `status` end at their parts (no
stubs). Consumers: Featherweight, Flyweight, Middleweight.

**DRC allowances:** `via_dangling` on gnd (4 switch commons, D1's cathode,
C1's return), one v3v3, and the three pickup vias; `silk_over_copper` 1
(D1's own pin-1 marker self-clip). Clearance as built 0.21 mm (three pairs
in the column at 0.20, the class floor).

---
