# IdealDiodeInput layout intent

LM5050-1 ORing controller + external N-FET (48 V)

The spec `IdealDiodeInput_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: AN-2087 + hand pass (see the divergence below).

Not a switcher: an ideal-diode ORing controller whose external N-FET
replaces an ORing diode. Layout imperative = minimise pass-path parasitic
inductance: on reverse-current turn-off (about 25 ns) that inductance dumps
energy as a negative spike on IN and a positive spike on OUT.

**Pinout (LM5050MK-1, 6-pin):** 1 VS, 2 GND, 3 OFF, 4 IN, 5 GATE, 6 OUT.
IN(4)/GATE(5)/OUT(6) on one side: face them toward the FET, short.

**Rules (datasheet SNVS629C Applications + AN-2087 layout reference):**
- IN/OUT are the Vds sense across the FET. AN-2087 Kelvins both to the FET
  source/drain pads. As built the two pins differ on purpose: OUT(6) is
  Kelvin'd (its own trace climbs the U1/D1 channel and 45s into the FET's
  drain EP, so the high side of the Vds sense reads the FET pad, not a plane
  potential reached through a via); IN(4) stays plane-referenced, 45ing onto
  a dedicated vin via beside the FET (the vin injection point is what the
  source pour sits at). The VS bias tap hangs off the OUT pin as a separate
  south lane (OUT -> R1.1 -> 100R -> VS), so the sense trace carries no bias
  current.
- GATE(5) to the FET gate, short.
- VS(1) = bias: above 5 V tie VS to OUT; the EVAL uses a 100R series +
  0.1 uF RC to OUT for spike immunity. Keep it.
- Transient protection (the real layout content): IN clamp diode to GND
  (negative spike) + OUT TVS and local bypass (positive spike), both right
  at the pins; keep the IN-FET-OUT high-current loop tight.
- OFF(3): internal 5 uA pull-down, open or to GND. GND(2): single quiet tie.
- Placement (AN-2087 Figs 6-7): IC immediately adjacent to the FET (Q1 = the
  centre pass element); high-current path = wide top-layer pour, VIN on the
  source side, VOUT on the drain side; R1(100R)+C3(0.1 uF) hard against the
  IC; C1(1 uF)+IN clamp diode at the VIN terminal; C2(22 uF)+OUT TVS at the
  VOUT terminal.

**As built.** Q1 west (drain/EP north = vout, source/gate south = vin); U1
east of the gate corner; d_gnd (D1) horizontal in the mid channel; d_in (D2)
along the south edge in the vin lobe; the VS RC stacked vertically east of U1
with wide copper (0.4/0.6 mm; the class width is a floor); the bus TVS rides
the vout tongue. GND_FLOAT lives entirely on F.Cu (a pour joining d_gnd/d_in
plus one 45 diagonal to the IC's ground pads); it is the cell's own floating
reference, a different net from the board ground, and may pour. Vias-in-pad
on the GND_FLOAT diode pads and both VS RC pads carry no in-module back
copper: documented landing points for an optional board-level strap
(`via_dangling` in module DRC). C2's gnd pad carries its plane drop (a bypass
cap whose return never reaches the plane is not bypassing anything). The vout
pour's 0.2 mm stroke is paid for in the vertices (south edge lands at 104.48,
still swallowing the FET EP at 104.46, 0.500 mm to the vin pour).

**HV clearance floor 0.25 mm.** Both pass-path nets land on the boards'
HV_BUS class (`vin_raw` -> VCTRL_IN, `vout` -> V48_CTRL). Tightest survivor:
the Kelvin 45 passes D1's gnd pad at 0.250; do not push that route
north-east.

**Design flag, not settled: 48 V re-rating.** The LM5050-1EVAL clamps are
60 V parts (D1 60 V Schottky, D2 SMBJ60A TVS), chosen for its at-most-50 V
input. At 48 V nominal with the 56-58 V regen/chopper window those are
marginal to inadequate. Re-rate the IN clamp diode and the OUT TVS above the
worst-case bus (at least about 63 V standoff, coordinated with the FET VDS).
Ask before pinning the clamp parts.

Datasheet SNVS629C; AN-2087 (SNVA458A) Figs 5-8; EVAL LM5050MK-1EVAL.

---
