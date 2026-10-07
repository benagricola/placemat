# pic_programmer: capture and reference script notes

The KiCad 10.0.6 demo `demos/pic_programmer` (CC-BY-SA-4.0), pinned in `../../manifest.json`. This folder holds its
Zener capture (from `pcb import`, with the changes below), `placemat.toml`, the reference script
`PicProgrammer_layout.py`, and these notes: the source of every annotation, the reason for every fixed part, and the
gaps found in the skills while writing them.

## Import

`pcb import pic_programmer.kicad_pro` (pcbc 0.4.52) then `pcb layout -S errors`, on a scratch copy of the cached
project. The regenerated board matches the original:
- all 63 footprints at the same position, rotation and face; footprint names differ only by `.` -> `_`;
- all 376 tracks and vias identical (start, end, width, layer, net); the one GND zone kept;
- every connected net has the same name on the same pads;
- the copper layers are read by their standard names (the original calls them `top_layer`/`bottom_layer`).

Two references are renamed: P2 -> J2 and U5 -> `U?1`. Their instance names stay `P2` and `U5`, and the script and the
manifest's `fixed` name them that way. The reference for test (b) is the regenerated board; since its placement and
copper equal the original's, the cached original gives the same vias and track length.

The 56 errors `-S errors` hides are all `bom.unspecified` (no part numbers in an imported capture).

## Changes to the imported capture

- **The pic_sockets sheet is flattened into `pic_programmer.zen`.** As a module, `pcb layout` stamps it as one KiCad
  group, which placemat places as one rigid cell, with the members where the generator packed them. The sheet holds
  the five target sockets and their two bypass capacitors: each socket is a mechanical point of its own, so the sheet
  is a drawing boundary, not a placement one (circuit-capture, "Modules for placement"). Names and nets are unchanged.
- **The POWER net class gets `nets=["GND", "VCC"]`**, the original project's `netclass_patterns`. The import kept
  the class and dropped the assignment, so a fresh generation put every net in Default.
- **POWER's `diff_pair_width`, `diff_pair_gap` and `diff_pair_via_gap` are removed.** The import writes KiCad's
  stored values into every class. placemat pairs the two nets of any non-Default class that sets both
  (`src/placemat/pairs.py:184`), so GND and VCC would have been a differential pair.
- **B.Cu's role is `mixed`:** it carries the GND plane and most tracks, as on the original board (its one GND zone
  is on B.Cu, and B.Cu holds 305 of its 370 track segments). F.Cu stays `signal`.
- **Part wrappers that carry annotations take `annotations`** (capture.md, "Annotations"): LT1373, 22uH, SCHOTTKY,
  22uF_25V, 1N4004, CONN_2, 7805, 1K__RV2X4, 5_1K, 6_2K, 62K, BC307.

## Datasheets

| Part | Document | Where |
|---|---|---|
| U4 LT1373 | Linear Technology LT1373, "250kHz Low Supply Current High Efficiency 1.5A Switching Regulator", rev B (1373fbs, LT/TP 0200) | copy read: https://nonprod.docs.rs-online.com/d4a4/0900766b81222b7f.pdf (analog.com refused the download) |
| U3 7805 | Texas Instruments LM340/LM7805, SNOSBT0L, revised September 2016 | https://www.ti.com/lit/ds/symlink/lm340.pdf |
| D1 1N4004 | Vishay 1N4001 thru 1N4007, document 88503, revision 29-Apr-2020 | https://www.vishay.com/docs/88503/1n4001.pdf |
| Q2, Q3 BC307 | Fairchild BC307/308/309, rev A2, August 2002 (as distributed by onsemi) | https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/2311301508_onsemi-BC307_C3201905.pdf |

The 7805 has no maker in the capture; TI's LM7805 is used as its datasheet. D10's part is not named ("SCHOTTKY", a
DO-35 footprint): its current is the LT1373's, not its own rating.

## Annotations

| Part | Annotation | Source |
|---|---|---|
| U4 | `Pm.Loop: hot` | LT1373 p10, Figure 3 and "Switch Node Considerations": the switch, the output diode and the output capacitor form the only path with nanosecond edges |
| D10 | `Pm.Loop: hot` | same |
| C3 | `Pm.Loop: hot` | same |
| U4 | `Pm.Aggressor: true` | LT1373 p5 (VSW pin: "large currents ... keep the traces short") and p10 (switch node: E-field radiation from the traces on the switch pin) |
| L1 | `Pm.Aggressor: true` | LT1373 p10, Figure 3: the inductor's end on the switch node |
| D10 | `Pm.Aggressor: true` | LT1373 p10: the diode's lead on the switch node |
| U4 | `Pm.I: Net-(D10-A):1.5A GND:1.5A` | LT1373 p5: VSW (pin 8) and GND (pin 7) carry the switch current; p3, ILIM, switch current limit, duty cycle 50%: min 1.5 A (typ 1.9, max 2.7) |
| L1 | `Pm.I: 1.5A` | LT1373 p8: in on-time the inductor current is the switch current; bounded by ILIM min 1.5 A, p3 |
| D10 | `Pm.I: 1.5A` | LT1373 p9, "Output Diode": the diode conducts the inductor current in switch-off time; ILIM, p3 |
| C3 | `Pm.I: 1.5A` | LT1373 p10, Figure 3: the output capacitor closes the circulating path; ILIM, p3 |
| RV1 | `Pm.Sensitive: Net-(U4-FB+)` | LT1373 p5, FB pin: the inverting input of the error amplifier; the divider tap is on RV1's wiper |
| R15 | `Pm.Sensitive: Net-(R15-Pad1)` | LT1373 p5, FB pin: the divider's low end, which feeds FB+ through RV1 |
| R16 | `Pm.Sensitive: Net-(R16-Pad1)` | the same, the divider's high end |
| R10 | `Pm.Sensitive: Net-(U4-Vc)` | LT1373 p5, VC pin: the error amplifier's output; p9: its output impedance is about 1 Mohm |
| U3 | `Pm.I: Net-(D1-K):1A VCC:1A` | TI SNOSBT0L 6.6 (p6), LM7805 electrical characteristics: specified for 5 mA <= IO <= 1 A. The GND pin carries only the quiescent current, so GND is left out (capture.md) |
| D1 | `Pm.I: 1A` | Vishay 88503 p1: IF(AV) 1.0 A, the bound of the input path it sits in |
| P1 | `Pm.I: 1A` | in series with D1: the same bound |
| Q2 | `Pm.I: VPP:0.1A Net-(Q2-C):0.1A` | BC307 rev A2, absolute maximum ratings: IC 100 mA |
| Q3 | `Pm.I: VCC:0.1A /pic_sockets/VCC_PIC:0.1A` | same |

Currents are bounds, not measured loads. Neither the demo nor any document gives the board's full load (the target
chip's IDD and IPP, the VPP load), so each path takes the rating of the part that limits it: the LT1373's switch
current limit for the boost converter's switch path, the 1N4004's rating for the input path, the LM7805's specified
output current for VCC, the BC307's collector rating for the target switches.

Left out:
- `Pm.Pd`, `Pm.TjMax`, `Pm.ThetaJb` on U3 and U4: dissipation needs the load current, which is not known. The
  datasheets give TO-220 RthJB 5.3 C/W (SNOSBT0L 6.4) and LT1373 N8 theta-JA 100 C/W, TJMAX 125 C (rev B p2).
- `Pm.Emits` on L1: LT1373 p8 warns that open-core (rod, barrel) inductors radiate, but gives no field figure; no
  part on the board is field-sensitive.
- `Pm.KeepOut`: the LT1373 gives no keep-out distance.
- C4 (value "0", on VC): no value, so no role.
- The LT1373's GND S rule (p5: keep the ground path to the divider and the VC network free of large ground
  currents): GND S, the divider, the VC network and the switch's GND are one net (GND), and no `Pm.*` key says that
  part of a net's return must stay apart from its load current. The capture could split a quiet ground joined by a
  net tie (SKILL.md's sense-line rule), but that is a change to the circuit, not an annotation.
- Pin pools: see "Skill gaps" (74HC125 gate swap).

## Fixed parts

Read from the human board. Each is held at the human board's origin and rotation (the script gives the numbers in
board coordinates, whose origin is the human board's top-left corner, (73.66, 40.64)).

| Part | What | Reason |
|---|---|---|
| J1 | DB9 socket, west edge | a connector: its shell stands 8.6 mm past the west edge where the serial cable plugs in |
| P1 | screw terminal, west edge | a connector: the power wires enter from the west edge ("+8/12V") |
| P101-P106 | M4 mounting holes | the standoff pattern: corners and the middle of the long edges |
| P3 | 40-pin ZIF socket | a socket the user handles: its lever stands 15.7 mm past the north edge |
| P2 | 28-pin DIP socket | a socket the user plugs a chip into, labelled "PIC 28 PINS" |
| U5 | 18-pin DIP socket | the same, "PIC 18 PINS" |
| U6 | 8-pin DIP socket | the same, "PIC 8 PINS" |
| U1 | 8-pin DIP socket | the same, for the I2C EEPROM ("I2C PROM") |

Not fixed, and why:
- D8, D9, D12 (the VPP, PWR and VCC indicator LEDs): the board has no enclosure, so no window fixes them; their
  labels go with them.
- RV1 (the VPP trimmer, "13V ADJUST"): adjusted with a screwdriver on the open board, nothing fixes its place.
- JP1 (solder jumper, on the back of the human board): no mechanical reason; searched on the front.
- U3 (the 7805, TO-220 tab down): no heatsink or case mounting; searched.

## Script

Every declaration's basis is printed by `python fixtures/reference/lint.py pic_programmer`. J1 and P3 stand past an edge, so
they are placed with `OnEdge(edge, along=, overhang=)`, whose numbers put their origins back on the human ones; the
other fixed parts are a `Location`, the six holes with `overhang=0.74` (their courtyards cross the edge by that much,
as on the human board). Beyond the fixed parts:
- the six `datasheet:` links of the LT1373 (switch path, switch node, VIN bypass) and the LM7805 (output capacitor);
- the GND plane on B.Cu (LT1373: a ground plane under the switcher; B.Cu as on the original);
- the original board's silk labels on the sockets, the power terminal, the LEDs and the trimmer;
- every other part placed bare (`capture:`), searched from its connections. These lines are needed: a part no
  declaration names is not searched but stays where `pcb layout` put it, with a `setup.undeclared` finding
  (`layout.py` `_report_undeclared`).

`placemat.toml` keeps every setting at its default; the default route needs no phase of its own for this board.

## Skill gaps

1. **A fixed part whose courtyard crosses the board edge could not be placed (placemat). Fixed by `overhang=` on a
   firm placement, commit 07e13341.** The six mounting holes sit 3.81 mm from the edges; their M4 courtyards cross the
   edge by 0.74 mm, as on the human board. `Location` was refused ("body box ... crosses the board edge"), and
   `OnEdge(edge, overhang=)` covers one edge only, where a corner hole crosses two. The holes now take
   `overhang=0.74` with a `mechanical:` why.
2. **Nothing says an imported sheet becomes a cell (placemat, circuit-capture).** The sockets sheet came out of
   `pcb import` as a module, which `pcb layout` stamps as a group and placemat places as one rigid cell. SKILL.md says
   cells are rigid, but neither skill says that an imported sheet, with no layout script of its own, becomes such a
   cell, and no finding says so: it showed only as `cell PIC_SOCKETS` in `placemat parts`. Fixed in the capture by
   flattening (above).
3. **`Pm.I` names nets exactly; capture.md does not say so.** capture.md says the last part of a net's path matches for
   `Pm.KeepOut`, `Pm.PinAllow` and `Pm.PinDeny`, and says only "give `Pm.I` per net". `checks.py` looks `Pm.I` up by
   the whole net name (`currents.get(p.net.lower())`), so `VCC_PIC` does not name `/pic_sockets/VCC_PIC`. Written as
   the full name.
4. **A two-net class from an import is a differential pair (placemat capture.md, circuit-capture).** capture.md:
   "a class other than Default that sets `diff_pair_width` and `diff_pair_gap` pairs its nets, exactly two outright".
   KiCad stores pair figures on every class and `pcb import` writes them into every `NetClass`, so POWER (GND, VCC)
   would pair. Neither skill warns that an imported class must lose them. Removed from POWER. Test (a) shows the
   effect on the original project: its manifest note records GND and VCC routed as a coupled pair.
5. **No form for swapping the gates of a multi-gate logic part (placemat pin pools).** U2's four 74HC125 buffers are
   interchangeable (each gate is A, Y and /OE). `Pm.PinPool` moves single nets, and a hard `Pm.PinGroup` moves a block
   to any run of consecutive pins in pool order, so it can shift a gate by one pin; nothing restricts a block to the
   other gates' pin sets. Left without a pin pool.
6. **Imported captures fail `pcb layout` on part numbers (placemat, circuit-capture).** An imported part has no MPN,
   so every part is a `bom.unspecified` error and placemat's generation stops. circuit-capture says `pcb build -D
   warnings` must pass; neither skill says what to do with a capture whose parts have no numbers. Used the script's
   `# placemat generate: -S bom.unspecified` line (api.md documents the line for `--config` only).
7. **`Pm.I` "at full load" when no load is documented (capture.md).** capture.md asks for amps at full load. For this
   board no document gives the load, and for the boost converter the guaranteed bound is the switch current limit,
   which is an overload figure. capture.md does not say whether to use a part's limiting rating; the rating was used
   and said so above.
8. **The hot loop is described for a buck only (capture.md).** "the switch and its input caps (`Pm.Loop`)" is a buck's
   loop; a boost's is the switch, the output diode and the output capacitor (LT1373 Figure 3). Annotated from the
   datasheet.
9. **Furniture on an open board (SKILL.md).** "Furniture (test points, LEDs, buttons) is `OnEdge(edge)` alone" assumes
   an enclosure edge. These indicator LEDs have no window and the human placed them mid-board; the skill gives no rule
   for a board with no case. Left searched.
10. **Facts need the user.** `placemat facts --confirm` asks the user to confirm layer roles, weights and fab
    minimums; here every fact is read from the human board's own files, but the rule leaves no way for a reference
    script's author to confirm them. Left unconfirmed (a `facts` finding on every run).
