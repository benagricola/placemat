# CanFrontendNative layout intent

MCP2542 transceiver front end for a native-FDCAN host (transceiver, common-mode
choke, split termination, ESD, DNF SI caps, 2.00 mm CAN-TERM header).

The spec `CanFrontendNative_layout.py` implements and the fragment in `layout/`
must satisfy. Rules that apply to every module are in `modules/README.md`; how
layout is done is the `pcb-layout` skill. History lives in git.

Spec source: the N17 CAN front-end idiom, re-laid under the skill.

**Structure.** U1 (MCP2542) anchors with its digital side (TXD/RXD/VDD/GND)
toward the MCU and its CAN side toward the bus; chain order transceiver ->
choke -> split-termination bridge -> ESD at the bus edge. The bus rails are
dead straight and matched by construction: CAN_P and CAN_N run at the choke's
own pad pitch from the choke to a mirrored 45 convergence into the ESD pads.
Two placements make that possible: the term resistor on the CAN_N rail
stands across it with its TERM_MID pad on the TERM_MID rail (a 0603's
0.85 mm pad gap lets CAN_N thread straight through), and the term resistor
on CAN_P puts its CAN_P pad directly ON the rail (pad pooling: the rail
crosses the pad, no stub, no bow). Residual pair mismatch 0.02 mm (the choke
footprint's own pad asymmetry). The termination bridge is a two-column
block; TERM_MID joins the inner pads on one rail and runs into the term cap
on its axis; TERM_JLEG drops 45 to the header's pad 1. CAN_P turns 45 early
and enters the ESD pad on its axis; the header's CAN_N pad rides ONE 45 up
through the CAN_N rail's end into the ESD's CAN_N pad, so rail, header and
ESD meet on one line. All termination internals are single-ended series
bridges and carry the pair's width. The header tucks under the ESD's flank;
the fragment draws no F.Fab body for it, so the courtyard rect is what a
neighbour packs against. The TX pair leaves each transceiver pin along its
axis, turns once, and enters the choke pad along the pad's own axis.

**Supply caps** STAND side by side west of the transceiver on the midline,
1.0 mm apart, v5 pads south and gnd pads north, each pad its own plane via;
the 100 nF nearest the pin reaches the VDD pin on one 45, the 1 uF beside it
is plane-fed only. The VIO 100 nF lies E-W under its pin with its v3v3 pad
on the pin's axis. Every part is resolved from the fresh netlist by net set;
the two {v5, gnd} caps by instance path (never a refdes).

**Fine-pitch escape rules (any DFN fan-out):**
- A power rail through a fine-pitch pad corridor is necked to the netclass
  floor: the TDFN-8's 0.50 mm pitch leaves a 0.700 mm corridor between pins 2
  and 4, so a 0.20 mm rail measures exactly 0.250 to both; it widens back the
  moment it clears the pads.
- A 45 pinned at both ends (pad axis -> 45 -> a pad centre with dx = dy) can
  only be freed by moving a PART: the choke moved 0.03 mm east to open the TX
  doglegs to 0.250, and both doglegs moved equally so the pair stayed matched.
  Search placement and copper jointly.
- Two parallel 45s make a constant-width corridor: a drop via between them
  cannot be fixed by sliding it; move a corner onto its own pad instead.
- Tap a 2-pad part from the far side of the pad you are entering.

**DNF SI caps (CAN_P/CAN_N, 10 pF):** Microchip DS20005514C section 1.8 shows
no capacitor on CANH or CANL individually; the positions are carried as DNF
(`skip_bom=True`, KiCad `exclude_from_bom`), tapped mid-rail in the one stretch
with clear copper both sides. A DNF part still carves a full keepout.

**Copper contract:** the bus rails end at the ESD/header pads on the bus side;
TXD and RXD end at the transceiver's pads (no stubs); v5/v3v3/gnd are plane
drops. The transceiver's two gnd PINS carry no copper of their own: the EP
is via-in-pad and the board's ground fill on this face joins each gnd pin's
pad to it (EP-grounded package rule); in the cell's own DRC those pins read
as unconnected, accepted. Envelope about 21.6 x 6.3 mm. **Clearance floor 0.20** (every net
Default-class or CAN_DIFF); the cell is spaced at 0.25. Accepted courtyard
graze: C3/D1. Consumer: Featherweight `can`.
