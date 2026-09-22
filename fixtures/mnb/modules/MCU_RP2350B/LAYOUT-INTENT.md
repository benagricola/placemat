# the MCU cell layout intent

RP2350B node-MCU cell (QFN-80), root `modules/MCU_RP2350B/`

The spec `Brains_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: RP2350 datasheet + hardware design guide + N17 core idiom.

Not a switcher: a digital MCU cell. Layout imperatives: QSPI signal integrity
(short direct runs), crystal parasitic capacitance (short XIN/XOUT), USB
differential routing. Because DVDD is external (below), the RP2350
datasheet's "most critical part of an RP2350 PCB layout" (the switching
regulator hot loop) does not apply to this module at all.

**Pinout (QFN-80, cross-checked against RP2350 datasheet Tables 1427-1432
and the fetched symbol):** four sides of 20. LEFT (1-20): GPIO4-20 + IOVDD at
5,15 + DVDD at 10. BOTTOM (21-40): GPIO21-32 + IOVDD at 24,29 + XIN 30 /
XOUT 31 + DVDD 32 + SWCLK 33 / SWDIO 34 / RUN 35. RIGHT (41-60): GPIO33-47
(ADC) + IOVDD at 41,50,60 + DVDD 51 + ADC_AVDD 59. TOP (61-80): VREG cluster
61-65 (VREG_AVDD/PGND/LX/VIN/FB) + USB_DM 66 / USB_DP 67 + USB_OTP_VDD 68 /
QSPI_IOVDD 69 (adjacent, one shared cap) + QSPI bus 70-75 + IOVDD 76 +
GPIO0-3. EP (81) = GND.

**LOCKED DEVIATION (do not "fix" this by adding an inductor):** DVDD is
external. RP2350 datasheet Section 6.3.7 / Figure 21 ("External core supply
with on-chip regulator disabled") applies verbatim: VREG_VIN + VREG_AVDD tied
to one 3.3 V node with ONE 4.7 uF cap (no RC filter), VREG_FB straight to
GND, VREG_LX unconnected (no inductor in this BOM), VREG_PGND to GND, each
DVDD pin its own 100 nF. Section 6.3.8's hot-loop, inductor-orientation,
VREG_LX cut-out and single-point-return rules do not apply: pins 61/64 and
62/65 are quiet decoupling and GND ties.

**Decoupling (Fig 6/7 "100 nF per power pin" plus two named exceptions):**
one 100 nF at every physical IOVDD pin (5,15,24,29,41,50,60,76; each its own
cap despite the shared net name) in line with that pin; one 100 nF shared by
the adjacent USB_OTP_VDD(68)/QSPI_IOVDD(69) pair; one 100 nF on ADC_AVDD(59);
one 4.7 uF (0603: no 0402 4.7 uF at JLC-Basic, and the node carries no
switching current) on the VREG_VIN/VREG_AVDD pair; three 100 nF on DVDD
(10,32,51). The instance names are a per-pin contract: the script ALLOCATES
each instance to the position that serves its own pin and prints the serve
audit every run (hand rounds place by position, so names drift; the audit is
what re-proves the map).

**The escape and decoupling architecture (binding):**
1. Every supply pin's cap sits point-blank on the pin's own axis (about
   1.06 mm supply-pad-to-pin on the west mid-face pins, 1.2-2.2 mm
   elsewhere; adjacent supply pairs 50/51 and 59/60 get mirrored flanking
   pairs). Serve map as generated: median 1.41 mm, worst 3.73 (QSPI_IOVDD 69,
   fed from the flash's own VCC pad), one cap per supply pin, all 16 covered.
2. Rails are silent on F.Cu: every cap carries via-in-pad on BOTH pads (the
   rail arrives by via into the supply pad, ground leaves by via from the
   gnd pad); the serve trace to the pin is the only top copper a cap owns.
3. Under-package relief columns at +/-2.350 from the package centre on one
   0.800 mm lattice anchored at y = -0.200 (the DVDD10 pin axis, the west
   face's own mirror line): signals whose face position would force fan
   detours dive through vias in the ring between the EP and the pad row and
   continue on B.Cu. West column 9 vias, east 7 (the count asymmetry is
   pin-forced; the ROW alignment must hold where both exist), EP quincunx
   exactly (0,0), (+/-1, +/-1). The mirror rule is X only: both columns share
   one |x| about the IC centre; row sets and ownership are free. A column's
   south capacity is three rows at 2.350 (row +4.6 is dead: no x between two
   0.4-pitch pads clears a 0.6 via), and no signal can slip past a column via
   into the pocket south of the pad row (0.650 mm annulus against 0.800
   needed). gpio24 (pin 25) therefore leaves like any other south pin, on
   F.Cu through the cap gate that the crystal block's 0.300 mm south slide
   opens (0.2000 to IOVDD24's served pad, on the class floor).
4. Cap bodies orient parallel to the local lane flow: 45-tilted in the
   diagonal field around the crystal diamond (south), vertical in the N/E
   column strips, horizontal on-axis on the west face.
5. Y-axis symmetry: relief columns, mirrored cap pairs and the EP quincunx
   are aligned and mirror-symmetric about the package Y axis; the same
   preference applies to every electrically equivalent choice.
6. The west fan: a 0402 pad is 0.31 half-height, so a lane needs 0.61 mm off
   a cap axis and the +/-0.4 neighbours of a cap pin are impossible at any
   track width; those six (gpio7/8/11/12/15/16, three mirror pairs about the
   DVDD10 axis) dive into the west column and the other lanes run dead
   straight out of their own pads, a full 0.8 mm off the nearest cap axis.
   Every fan group runs at one 0.4 mm lane pitch (0.5657 along a 45),
   anchored on a cap serve's own diagonal, all spacings derived (a 0.01 mm
   hand grid spaces a 45 bundle at 0.560 where D45 is 0.565685, 0.004 under
   the floor: derive, never copy rounding).
7. No edge stubs and no frontier lines. Every signal ends at its pad or, for
   the relief set, at its relief via; the far-layer lane from the via onward
   and every F.Cu continuation (the face fans, the ADC columns, the SW
   bundle) are the board's. The exit sides are still the cell's contract:
   QSPI_SS on the west face (off the far-row wrap), the SWD/RUN service trio
   east of the south relief column (so a board sites SwdHeader and
   McuButtons together), USB_P/USB_N at the 27R terminators' board-side
   pads north-east.

**Clusters:** crystal diamond + damping R + 45-tilted load caps south-centre;
flash + vertical cap columns north; the LDO island east mid-height pointing
OUT-cap-first at the chip; the 3V3 power-present LED (D1, KT-0603G + R1)
standing in the north-east pocket between the north cap columns and the USB
terminators (LED above resistor on one axis, cathode north to its drop), so
the north-west shoulder is empty and the flash and its wrap alone set the
north extent. The LDO's IN/EN/GND are plane pads and OUT is
the V1V1 strap (via-in-pad at the source, tactic 13), so the island has no
routing constraint and fills otherwise-dead area; its input cap sits in the
north pocket (its pads and the IN pin are all plane pads; the cap the LDO's
stability depends on, the output cap, is adjacent to the OUT pad).

**V1V1 is a board-strap contract.** All five V1V1 pads (the LDO's OUT cap and
the three DVDD caps plus the LDO OUT) tap by via-in-pad and the fragment
carries no V1V1 distribution; every board that instantiates the MCU cell MUST join
those drops (3 `unconnected` V1V1 items in the fragment DRC are that
contract).

**North cluster.** Every north load has its own cap and its own leg (no
pooling through the flash's VCC pad). The caps stand in vertical columns EAST
of the flash, beside the forced QSPI escape bundle, never across it: a
fine-pitch part's lanes are forced onto their pad columns (0.5 mm pitch
leaves 0.22 mm between pads), so a cap in the escape corridor costs package
movement while a cap beside it costs nothing. The flash sits at
(+0.300, -8.700) MCU-relative (`FLASH_DX`/`FLASH_DY`), with the QSPI landing
columns, the ground pad-4 walk and the EP drop all read off the part. Neither
flash pad can hold a via-in-pad (EP 0.30 mm tall, pad 4 0.28 mm wide): pad 4
walks onto the EP and the EP drops one via.

**QSPI flash (W25Q16JVUXIQ, USON-8 2x3 mm, 0.5 mm pitch; the N17-proven
part, firmware-proven for this RRF port):** "wired directly using short
connections" (hardware design guide Ch 3.1), hard against the QSPI cluster
(pins 70-75, TOP). No length matching (SPI). The near row (SD0/SCLK/SD3) is
order-matched to pins 72/71/70, each a straight drop + one 45 at its own
depth; the far row (SS/SD1/SD2) wraps west in three lanes north of the flash
and descends on columns that sit exactly on their MCU target's x, so no
far-row net re-enters the flash-to-MCU gap. The BOOTSEL 1k series R lives
with its button in `modules/McuButtons`, so what leaves this cell on the west
face is the live QSPI_SS node; the board keeps that run short.

**Crystal (ABM8-272-T3, the Pico's part), datasheet Ch 4/Fig 10:** keep the
layout short (parasitic PCB capacitance stacks with the 15 pF load caps;
target 10 pF total). Tight against XIN(30)/XOUT(31). The damping resistor
(R7, 1k) sits between the crystal's terminal 3 and the MCU's XOUT pin; the
load cap for that side (C18) lands on the CRYSTAL side of R7, not the MCU
side (Fig 10 order). C18 sits on the XIN wrap column west of the crystal.

**USB (datasheet Ch 5.1):** RP2350 needs 27R series termination on
USB_DP/USB_DM (R5/R6 close to pins 66/67). Nets are USB_P/USB_N so KiCad's
diff-pair matcher engages; the 90R target is a board NetClass number. The pair
is matched, not merely routed: parallel at the pair gap (0.45, which keeps
0.25 between the two 0.2 tracks, above the 0.20 class floor) on its
horizontals and its 45s (x+y differing by exactly gap x sqrt 2), USB_MCU_N's
annulus via 0.5 past a 0.4 gap as the length-match knob. The terminators
cannot sit on the 0.8 lattice (0402 pads 0.64 tall, 0.16 gap), so the pair
opens to 1.2 mm before two equal 45s into them; they stand just north of the
LDO island and the pair ends at their board-side pads.

**Envelope:** body union about 21.8 x 22.9 mm (the north 1.165 mm of copper
beyond the outermost part is the flash's far-row wrap, structural). Bounds
MCU-relative W -7.29 / E +14.52 / N -10.54 / S +12.36.

**Clearance floor 0.20 mm, part-forced.** P0.40 with 0.20 x 0.665 pads =
0.200 mm pad-to-pad by construction (80 pairs), so 0.25 is impossible at the
part and the escape-lane pairs inherit it. No the MCU cell net lands on an HV class.
The floor is derived from the boards that stamp the cell; this arithmetic is why it cannot be tighter.

**DRC allowances, per net:** `via_dangling` on gnd/v3v3 (plane drops) and
V1V1 (the strap contract); `silk_over_copper` 2 (Y1 and D1 library
self-clips); `invalid_outline`.

**Ported from the N17:** flash hard against the QSPI bank with its near
column facing the MCU; QSPI on one layer at 0.2 mm with no vias; the far-row
group wrapping the flash body; the 1V1 island strapped by the board. NOT
ported: its 0201 passives, via-in-pad everywhere and the 6-layer escape tier
(this ecosystem's floor is 0402 with plain 0.6/0.3 vias).

**Split cells:** the USB-C port , BOOT/RUN buttons + status LED
 and the SWD header  are board-placed cells, not
the MCU cell internals; the MCU cell exposes QSPI_SS, RUN, SWCLK, SWDIO as OPTIONAL io
(unconnected they rest on the chip's internal pulls). the MCU cell keeps its own
3V3 power-present LED: it indicates this cell's rail, not an MCU state.

---
