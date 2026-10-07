# usb-c-power-adapter: capture and reference script notes

Antmicro's USB-C Power Delivery Adapter (github.com/antmicro/usb-c-power-adapter at 4d3e9e28, Apache-2.0), pinned in
`../../manifest.json`. This folder holds its Zener capture (from `pcb import`, with the changes below),
`placemat.toml`, the reference script `usb-c-power-adapter_layout.py`, and these notes: the source of every
annotation, the reason for every fixed part, and the gaps found in the skills while writing them.

## Import

`pcb import usb-c-power-adapter.kicad_pro` (pcbc 0.4.52) then `pcb layout -S errors`, on a scratch copy of the cached
project. Compared with pcbnew against the original:
- all 124 footprints (122 parts and two logos) at the same position, rotation and face;
- all 829 tracks and vias identical in geometry, width and layer; every net maps one to one (66 renamed: the import
  prefixes each sheet's nets with its module, `USB_PD.VBUS`, `DC_DC_CONVERTERS.+12V`);
- the zones kept, on the same nets.

The import swaps every footprint: the 76 resistors and capacitors take the KiCad stdlib's
(`stdlib_kicad-footprints_Capacitor_SMD:C_0402_1005Metric`), the rest copies of the original's own library
(`antmicro-footprints:...`) under the part's component folder. The stdlib pads are larger than Antmicro's, so KiCad
DRC on the regenerated board gives 56 errors where the original gives 4: 22 clearance, 24 courtyards_overlap,
1 shorting_items, 1 more hole_clearance (a +3V3 via in R3's pad), 2 copper_edge_clearance, 1 padstack,
1 items_not_allowed; the original's 4 are J1's GND pads against its own NPTH pegs (hole_clearance), in both. The
reference for test (b) is the regenerated board.

The 30 errors `-S errors` hides are all `bom.unspecified`: the part wrappers the import writes carry no `part=`.

## Changes to the imported capture

- **The USB_PD and DC-DC Converters sheets are flattened into `usb-c-power-adapter.zen`.** As modules, `pcb layout`
  stamps each as one KiCad group, which placemat places as one rigid cell. Each sheet holds connectors that sit at
  their own mechanical points (J1 and J2 in USB_PD, J3 and J4 in DC-DC Converters), so the sheets are drawing
  boundaries, not placement ones (circuit-capture, "Modules for placement"). Instance names and nets are unchanged;
  net names lose the module prefix the import's generation added (`USB_PD.VBUS` is `VBUS`). They are the import's
  names, not quite the original's: a sheet path keeps the import's underscore (`/USB_PD/CC1`,
  `/DC-DC_Converters/12V_SS`, where the original has `/USB PD/CC1` and `/DC-DC Converters/12V_SS`). The import's `# pcb:sch` schematic positions are dropped with the modules.
- **The USB net class gets `nets=["/USB_PD/*"]`**, the original project's pattern `/USB.*`: the PD sheet's CC1, CC2,
  SDA, SCL, QWIIC_VCC, VBUS_EN and VBUS_DISCH. The import kept the class and dropped the pattern.
- **USB's `diff_pair_width`, `diff_pair_gap` and `diff_pair_via_gap` are removed.** KiCad stores pair figures on
  every class and the import writes them into every `NetClass`; this class is a sheet's control nets, not a pair.
  placemat pairs the nets of a non-Default class that sets both (capture.md, "Net classes").
- **U6's pins 1 and 10 are not connected.** The import joined them into one net (`unconnected-(U6-Pad1)`); on the
  original each is its own unconnected net (pin 1 is the unused IO1, pin 10 NC, TI SLVSD85B Pin Functions). As one
  net it was an airwire between two pins that carry nothing.
- **Layer roles are the original board's use:** In1.Cu `ground` (one GND zone over the whole board), F.Cu, In2.Cu and
  B.Cu `mixed` (tracks with power pours; In2 holds the +12V, +3V3 and VBUS pours).
- **Part wrappers that carry annotations take `annotations`** (capture.md, "Annotations"): USB4105-GF-A,
  SQS401EN-T1_BE3, 74279221100, SIC477ED-T1-GE3, ASPIAIG-Q8080-4R7M-T, 3413_0326_11, 1053131202, AP62301Z6-7,
  TFM252012ALMA3R3MTAA, SM04B-SRSS-TB_LF_SN.

## No USB pair

The board has no USB data pair: J1 is a USB 2.0 receptacle used for power only, its D+, D- and SBU pins are not
connected (the original's nets `unconnected-(J1-D_{A}+-PadA6)` and so on). The `USB` class is the PD sheet's
control nets. So the capture has no `DiffPair` interface and no pair class.

## Sources

| Part | Document | Where |
|---|---|---|
| the board | the project's README at the pinned commit: 12 V 55 W continuous, up to 75 W with active cooling; the PD profile (PDO3 20 V 4.5 A); the 5 V and 3.3 V converters up to 500 mA | https://github.com/antmicro/usb-c-power-adapter/blob/4d3e9e289a294f7953bf48dde6c96af8327a0611/README.md |
| U1 STUSB4500 | ST DS12499 rev 2, July 2018 | copy read: https://www.farnell.com/datasheets/2710898.pdf (st.com did not answer) |
| U2 SiC477 | Vishay SiC476/477/478/479, document 77113, S25-1437 rev I, 17-Nov-2025 | https://www.vishay.com/docs/77113/sic47x.pdf |
| U3, U4 AP62301 | Diodes AP62300/AP62301/AP62300T, DS41958 rev 2-2 | copy read: https://static.chipdip.ru/lib/362/DOC026362352.pdf (diodes.com links returned 404) |
| U5, U7, U8 TVS2200 | TI SLVSED5C, revised August 2023 | https://www.ti.com/lit/ds/symlink/tvs2200.pdf |
| U6 TPD4E02B04 | TI SLVSD85B, revised July 2016 | https://www.ti.com/lit/ds/symlink/tpd4e02b04.pdf |

## Annotations

The load is the board's own: its README gives the PD profile and the outputs. Each current is that load; the
datasheet figure beside it is the part's rating, which the load stays under.

| Part | Annotation | Source |
|---|---|---|
| J1 | `Pm.I: VBUS:4.5A GND:4.5A` | README: PDO3 20 V 4.5 A, the highest current the sink asks for; DS12499 3.3.1 p11: a sink PDO's current is 0.5 A to 5 A |
| Q1 | `Pm.I: VBUS:4.5A VCC:4.5A` | the same current: Q1 is the VBUS switch VBUS_EN_SNK drives (DS12499 2.2.10) |
| FB1 | `Pm.I: 4.5A` | the same current, in series on VCC to U2's VIN |
| U2 | `Pm.I: Net-(U2-V_{CIN}):4.5A Net-(L1-Pad1):6.25A GND:6.25A` | VIN: the PD input above. SW and PGND: README, 75 W at 12 V = 6.25 A; 77113 p1 and p23: SiC477 8 A continuous |
| L1 | `Pm.I: 6.25A` | the 12 V output current, as U2's SW |
| F1 | `Pm.I: 6.25A` | the same current, in series to J4 |
| J4 | `Pm.I: Net-(D5-C):6.25A GND:6.25A` | the same current |
| U3, U4 | `Pm.I: +12V:0.5A Net-(Ux-SW):0.5A GND:0.5A` | README: up to 500 mA; DS41958 p1: AP62301 3 A continuous. A buck's input current is below its output current, so 0.5 A bounds +12V too |
| L2, L3 | `Pm.I: 0.5A` | the converter's output current |
| J3 | `Pm.I: +5V:0.5A +3V3:0.5A` | the same currents |
| U2, C3, C4, C16 | `Pm.Loop: hot` | 77113 p20 step 1: the VIN ceramics between VIN and PGND, very close to the device |
| U3, C21 | `Pm.Loop: hot_5v` | DS41958 p20 Layout 2: the input capacitor across VIN and GND. C21 is U3's: the sheet draws it with U3 |
| U4, C22 | `Pm.Loop: hot_3v3` | the same, for U4 and C22 |
| U2, L1 | `Pm.Aggressor: true` | 77113 p2: SW (pins 12-14) is the power stage switch node; p20 step 3 |
| R15 | `Pm.Aggressor: true` | its pad 1 is on U2's switch node (the ripple injection network, not fitted) |
| U3, L2, U4, L3 | `Pm.Aggressor: true` | DS41958 p20 Layout 3: the inductor at SW, the switch node |
| C23, C24 | `Pm.Aggressor: true` | the BST capacitor's pad 1 is on the converter's switch node |
| R17, R18 | `Pm.Sensitive: Net-(U2-V_{FB})` | 77113 p21 step 6.3: feedback far from the VSWH node |
| R2, R41 | `Pm.Sensitive: Net-(U3-FB)` | DS41958 p20 Layout 5: the feedback components at FB |
| R1, R27 | `Pm.Sensitive: Net-(U4-FB)` | the same |

The 12 V current is the 75 W figure, the most the README says the board delivers (with active cooling); the
continuous figure without cooling is 55 W, 4.6 A.

Left out:
- `Pm.I` on the input bulk (C43, C44), the output capacitors, the TVS diodes (U5, D2, D5) and R12: they carry ripple
  or a sense current, not the load. FB2 (VCC to +12V) is not fitted.
- `Pm.Pd`, `Pm.TjMax`, `Pm.ThetaJa` on U2: 77113 p3 gives theta-JA 12 C/W and TJ 150 C (operating 125 C), and the
  README a 94 % efficiency, but not how the loss divides between U2 and L1; the README's own limit is a cooling one
  (55 W without, 75 W with a fan).
- `Pm.KeepOut`: neither the SiC47x nor the AP62301 gives a keep-out distance.
- `Pm.Emits` on L1: no field figure in either document.
- Pin pools: no part has interchangeable pins.

## Fixed parts

Read from the human board. Each is held at the human board's origin, rotation and face; the script gives the numbers
in board coordinates, whose origin is the outline's north-west corner, (81.530, 58.569).

| Part | What | Reason |
|---|---|---|
| J1 | USB-C receptacle, back | a connector: its mouth stands 1.4 mm past the north tongue's end, where the cable plugs in |
| J2 | Qwiic (JST SH 4-pin), front | a connector: on the north tongue, mouth north, for the cable that programs U1 |
| J3 | JST SH 4-pin, back | a connector: the 5 V and 3.3 V output, mouth to the east edge |
| J4 | Molex Nano-Fit 2-pin, front | a connector: the 12 V output, its mouth 2.9 mm past the south tongue's end |
| MP1 | 3.5 mm pad, 2.2 mm drill | the mounting hole |

Not fixed, and why:
- the LEDs D3, D4, D6..D9: no enclosure or window is documented; their labels go with them.
- the test points: no fixture is documented.
- U2 and L1: the datasheet asks for them, the VIN ceramics and the planes on the top layer, which the script says;
  where on the board is the search's.

## Script

Every declaration's basis is printed by `python fixtures/reference/lint.py usb-c-power-adapter`. Beyond the fixed
parts:
- the outline: the original's Edge.Cuts as `board.outline`, the west side taken as one line (the original's lower
  west segment is 0.004 mm further west than the upper one);
- J1 and J4 stand past an edge, so they are placed with `OnEdge(run, along=, overhang=)`, whose numbers put their
  origins back on the human ones; J2, J3 and MP1 are a `Location`;
- the `datasheet:` links of the SiC477 (VIN ceramics, VCIN, VDD, VDRV, the boot RC, the inductor), the AP62301s (input
  capacitor, inductor, feedback, output capacitor), the STUSB4500 (VREG decoupling) and the TVS parts (at their
  connector);
- U2, L1 and the VIN ceramics on the front; the VIN and SW planes on F.Cu as fitted pours; the GND plane on In1.
  The human board departs from two datasheet rules - AP62301 p20 Layout 6 (In1 and In2 both GND) and SiC47x p22 step
  7.2 (VIN and ground planes duplicated on the bottom layer): its In2 carries the +12V, +3V3 and VBUS pours and its
  B.Cu no VIN plane. The script follows the human board;
- the original board's silk labels on J2, J4 and the LEDs;
- every other part placed bare on either face (`mechanical:`: the original is assembled on both, 46 of its 124
  footprints on the back).

`placemat.toml` keeps every setting at its default.

## Skill gaps

1. **A fixed part whose courtyard covers another fixed part's NPTH on the other face cannot be placed (placemat).**
   Resolved. J1 (on the back) has two NPTH locating pegs; J2 (on the front, above it) has its courtyard over them, as
   on the human board, whose project sets `npth_inside_courtyard` to warning. placemat stopped the run: "Firm
   placements collide ... J1 (edge): J2 courtyard sits over a npth (J1)". Tried: J1 by `OnEdge(..., overhang=)` and
   J2 by `Location`, both at the human origins. The user decided that a firm courtyard over a hole follows the board's
   severity (placemat 04d3a2aa); `placemat.toml` carries the human board's severities, and the run places both.
2. **Imported sheets become rigid cells (placemat, circuit-capture).** As for pic_programmer: both sheets came out of
   `pcb import` as modules, which placemat places as rigid cells with the generator's arrangement. Neither skill says
   so. Fixed in the capture by flattening.
3. **An imported class carries pair figures (placemat capture.md, circuit-capture).** As for pic_programmer: the USB
   class came with `diff_pair_*`. It has seven nets with no pair suffix, so placemat would not have paired them, but
   neither skill warns that an imported class must lose them. Removed.
4. **Imported captures fail `pcb layout` on part numbers.** As for pic_programmer: 30 parts whose wrappers have no
   `part=`. Used the script's `# placemat generate: -S bom.unspecified` line.
5. **A high-current net's class against a board that carries its current in pours (circuit-capture).**
   circuit-capture: "A high-current net has its own class with the width it needs". At 10 C rise on 1 oz outer copper
   (IPC-2221), 4.5 A and 6.25 A need tracks about 2.4 mm and 3.8 mm wide, which a 22 mm board routes nowhere; the human
   carries them in pours and the In2 planes, under the Default class. placemat's route takes its widths from the
   classes (and `[route] islands`), not from `Pm.I`, so without a class the router draws these nets at 0.125 mm.
   Neither skill says how a capture states a current that pours, not tracks, are to carry. Left: `Pm.I` on the
   parts, no class; the current-path check judges what is drawn.
6. **"Mark the switch and the inductor" leaves the switch node unfound (capture.md).** A switch node is a net "whose
   every pad belongs to a `Pm.Aggressor` part", but capture.md says to mark the switch and the inductor. Here the
   bootstrap capacitors (C23, C24) and a ripple injection resistor (R15, not fitted) also have a pad on the node, so
   marking only the switch and the inductor finds no switch node. Marked them too.
7. **Which end of a run `along=` counts from (api.md).** "On a run, `along` is length from the run's start"; the start
   is wherever the outline's path enters the run, so the south tongue's run is measured from its east corner. Found
   by placing J4 and measuring.
8. **Indicators on an open board (SKILL.md).** As for pic_programmer: no rule for LEDs with no enclosure window. Left
   searched.
9. **Facts need the user.** As for pic_programmer: every fact here is read from the human board's files, but only the
   user can confirm them. Left unconfirmed (a `facts` finding on every run).
