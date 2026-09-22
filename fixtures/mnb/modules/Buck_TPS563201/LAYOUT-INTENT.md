# Buck_TPS563201 layout intent

5 V to 3.3 V (SOT-23-6 / DDC)

The spec `Buck_TPS563201_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: TI 10-rule layout section + hand passes.

**Topology: SYNCHRONOUS.** Both FETs internal; GND(1) = low-side FET source.
No external diode.

**Pinout (DDC):** 1 GND, 2 SW, 3 VIN, 4 VFB, 5 EN, 6 VBST. GND/SW/VIN on one
side, so CIN bridges VIN(3)/GND(1).

**Datasheet layout section, SLVSD90B section 7.4.1 (10 rules) + Fig 7-18 +
EVM SLVUAK7A:**
1. VIN and GND traces as wide as possible (impedance + heat).
2. Input and output caps as close to the device as possible.
3. Sufficient vias for input and output caps.
4. SW trace short and wide as practical (radiated emissions).
5. Do not allow switching current to flow under the device.
6. Separate VOUT path to the upper feedback resistor.
7. Kelvin the GND-pin connection for the feedback path.
8. VFB loop away from the switching trace; prefer a ground shield.
9. VFB node trace as small as possible.
10. GND trace between output cap and GND pin as wide as possible.

- Hot loop: `CIN -> VIN(3) -> [FETs] -> GND(1) -> CIN`; CIN across
  VIN(3)/GND(1), close, with vias (rules 2-3).
- SW copper (tension resolved by Fig 7-18): SW small on the device layer
  (rules 4-5); its thermal area is a pour on an inner/bottom layer reached
  by a via field, not an enlarged top island.
- Feedback: dedicated VOUT sense to the top divider; Kelvin FB return to
  GND(1); VFB node small, away from SW, ground-shielded (rules 6-9).
- Ground: single-point VFB-ground tie to GND(1); wide copper from the
  output-cap ground back to GND(1) (rule 10).
- Placement (Fig 7-18): IC centre; input cap hard against VIN/GND; boost cap
  VBST(6) to SW; FB resistors clustered at VFB(4) on the quiet side;
  inductor + output cap on the SW/VOUT side; SW vias down to the pour.

**As built (the module's layout intent, folded from a hand pass; every rule
kept at about 98 mm2):**
- Input caps in a ROW, not a pour-fed column: C3/C2 side by side r90, gnd
  pads outboard forming a via fence at the module edge, vin pads inboard
  pooled by one horizontal vin pour. Each cap is plane-fed by its own
  via-in-pad; the pour pools locally, the 5 V plane distributes.
- C4 (HF 100 nF) exactly x-aligned with VIN(3): the served pad sits on the
  served pin's axis, so the hot-loop connection is a straight 1.4 mm shot.
  The vin pour also absorbs the EN(5) tie via.
- FB divider = two-column block at VFB(4): chain pads (R2.2/R1.2) share one
  rail (straight through both), entered straight off the pin then one 45;
  the other column takes the vout-sense entry and R1's gnd via-in-pad. The
  divider keeps 0.85 mm courtyard-to-sense clearance from the west sense
  corridor.
- Plane injection at the source: a via-in-pad on the inductor's output pad
  injects vout into its plane where it is generated, and the FB sense taps
  that point (regulation point = injection point). VBST's run rides the boot
  cap pad's axis and ends on its centre.
- The vout sense taps the vout pour near L1 and hugs the module edge
  (about 14 mm) instead of a 24 mm perimeter detour; it runs about 3 mm
  parallel to VBST at 0.7 mm gap, acceptable because the sense line is low-Z
  off a stiff pour while the high-Z VFB node stays microscopic at the pin.
- SW pour chamfered and necked: 45 degree bevels, the neck to SW(2) at pad
  width (about 0.6 mm) to minimise radiating area, full width at L1/boot cap.
  C5/C6 pulled in so vout and gnd land via-in-pad.

**Clearance:** every net lands on Default-class board nets (floor 0.20);
the cell is spaced at 0.25 and stays there. The binding geometry is U1's
SOT-23-6 pitch: 0.95 mm pitch, 0.6 mm pads = a 0.350 mm pad-to-pad corridor,
so a pour may overhang its own pad by at most 0.100 mm total across the
corridor at 0.25; split that budget evenly so both pours keep positive pad
coverage. Every cut is a lip past a pad, downstream of the current path.
Tightest pair 0.253 mm (C4's gnd via-in-pad to the vin pour, set by C4's own
pad gap).

**Packing:** the two output caps are one row and are packed west as a pair
until real geometry stops them (the input-cap row's courtyard above the
upper one, measured by the cell class's pack primitive, one grid step short
of touching); the vout pour's finger vertices follow their pads. No "air"
constant sits between courtyards anywhere in this cell.

Datasheet SLVSD90B; EVM SLVUAK7A (Figs 5-1/5-2/5-3); WEBENCH CAD export
available.

---
