# CanFrontendDiscrete layout intent

MCP2518FD + MCP2542 CAN-FD front end, root `modules/CanFrontendDiscrete/`

The spec `CanFrontendDiscrete_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: N17 idiom + MCP2518FD datasheet section 1.3; DNF 10 pF caps as above.

Two ICs: MCP2542 (bare transceiver, same part and role as CanFrontendNative)
plus MCP2518FD (external CAN-FD controller, VDFN-14 with EPAD, SPI to the
host), bridged by a CAN-MODE jumper (see the module's `.zen` header for the
electrical why). The bus-side cell (transceiver + choke + split term + ESD)
follows CanFrontendNative's rules (standing supply caps west of the
transceiver, straight rails at the choke's pad pitch, term_ra's pad on the
CAN_P rail, term_rb across the CAN_N rail, the header under the ESD's flank)
with this cell's own positions: the two cells share the idiom, not the
numbers, and each is folded from its own hand round.

**MCP2518FD pinout (VDFN-14, DS20006027B Table 1-1):** Row A (1-7): TXCAN,
RXCAN, CLKO/SOF (NC), ~INT, OSC2, OSC1, VSS. Row B (8-14): ~INT1/GPIO1 (NC),
~INT0/GPIO0/XSTBY (NC), SCK, SDI, SDO, nCS, VDD. EPAD (15) = ground,
via-in-pad.

**Structure: two rows.** Row 1 (north), west to east: CAN-MODE header (H1),
crystal cell, controller U1. Row 2 (south): the bus cell. The header sits
against the transceiver it selects (a selector jumper belongs on the part it
selects: its always-populated column is a routing destination for the block
it switches, so the optional path takes the long run), giving XCVR_TXD
2.8 mm / XCVR_RXD 7.9 mm while the controller absorbs length on its quiet
SPI-side nets. Controller rotation 90 (CAN side east, host side west);
crystal hard against the controller with OSC2 approaching from one pad
corner and OSC1 from the opposite one, so the two traces never share a
corridor; X1 rot 270 so OSC1 lands on the SE pad, matching OSC1 being the
southern pin (the other rotation crosses the pair); the OSC2 load cap stands
west of the crystal with its OSC2 pad on the crystal's NW pad row, the OSC1
load cap lies under the OSC1 lane and drops straight onto it; the
controller's two VDD caps stack at its north-east corner with their v3v3
pads on the VDD pin's own axis. H1's rows carry TX north / RX south, one
family per row across all three columns (electrical, not cosmetic). The DNF
SI caps carve a full keepout: route around DNF copper exactly as if
populated. Every part is resolved from the fresh netlist by net set, the
same-net caps by instance path (never a refdes).

**Rotation rule (verify, do not assume):** for any footprint with pads on
two or more sides, verify a placement rotation with a round trip (place,
regenerate, query the real pad position with the script's `pad()` helper)
rather than hand-deriving the rotation matrix.

**B.Cu rule:** every B.Cu segment that originates at an SMD pad needs an
explicit via, no exceptions. A B.Cu track starting exactly on an F.Cu-only
pad's coordinates with no via throws no DRC error; the saved net table folds
that island into whichever other net's copper it ends up nearest.

**Congestion rule:** separate same-region nets by altitude (a lower or higher
y for a given net's traverse) or by layer before fighting for X; where two
placed parts fight for one gap, widen the envelope there (the `BUS_DX`
shift) rather than threading a needle.

**Copper contract:** the bus cell's rails as in CanFrontendNative (no
stubs); the controller's SPI, TX and RX nets end at their pads, INT at its
escape via west of the controller, mcu_can_rx/tx at the header's column 3
(the board draws from the pad or its via). Neither IC's gnd pins carry
copper of their own (EP-grounded package rule): the transceiver's EP has
its centre via, the controller's long EP a centre via and one near each
end (the south one beside its VSS pin), and the board's ground fill on this
face joins each gnd pin's pad to its EP; in the cell's own DRC those pins
read as unconnected, accepted. The seam
between the two rows is not free space on any layer: both rows' plane-drop
vias and the bus cell's ground stitches populate it, so a B.Cu corridor is
checked against every via of both rows and an F.Cu corridor against the
neighbour cell's tracks.

**Envelope:** about 22.0 x 11.5 mm. **Clearance floor 0.20 mm, part-forced:**
the CAN-MODE header is a 2.00 mm THT part with 1.4 mm pads (0.600 mm
inter-pad corridor, a floor-width lane 0.200 each side) and the crystal /
MCP2518 escape runs at the same 0.4 mm lane pitch; declared with its
arithmetic here; the floor itself is derived from the consuming boards. Accepted courtyard graze:
C7/D1. The pocket that must hold a via AND a track is a 1.4 mm budget
(0.2 + 0.6 + 0.2 + 0.2 + 0.2 at this fab): X1 stands off U1 purely to keep
the int_pin escape via and OSC2's climb in the same channel.

**CAN_P/CAN_N DNF SI caps (both CAN cells):** Microchip DS20005514C
section 1.8 (Figures 1-3 and 1-4) shows no capacitor on CANH or CANL
individually (only VDD/VIO bypass and the split-termination centre-tap cap),
so the N17's 10 pF/50 V 0402 positions are carried as DNF (`skip_bom=True`,
which sets KiCad's `exclude_from_bom`), tapped mid-rail in the one stretch of
the bus rail with clear copper both sides. Tap a 2-pad part from the far side
of the pad you are entering: dropping west of the CAN pad and 45-ing east into
its centre gives 0.58 mm to the gnd pad where the other side gives 0.24 at a
maximum. Same-net caps ({v5, gnd} twice, {v3v3, gnd} three times) are
resolved by instance path.

---
