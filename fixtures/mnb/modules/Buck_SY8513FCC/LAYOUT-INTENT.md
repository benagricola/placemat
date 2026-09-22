# Buck_SY8513FCC layout intent

48 V to 5 V and 48 V to 24 V

The spec `Buck_SY8513FCC_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: async-buck hot loop + hand passes.

**Topology: ASYNCHRONOUS.** Datasheet: "High Efficiency, 100V Input, 3A
Asynchronous Step Down Regulator." Integrates the high-side FET only
(RDS(on) 150 mR, ILIM 3.8 A). The SS510 Schottky is the external rectifier
(cathode to LX(8), anode to GND); it closes the loop when the top FET is off.

**Pinout (SO8E, EP = GND/thermal):** 1 IN, 2 EN, 3 FS, 4 GND, 5 FB, 6 PG,
7 BS, 8 LX. Useful adjacencies: IN(1)/GND(4) same side (tight CIN); BS(7)
next to LX(8) (tight bootstrap cap). FS(3): RFS to GND sets fSW (200k about
500 kHz, 1M about 100 kHz).

No datasheet layout section, only a land pattern (Rev 0.1A p.5). The rules
are standard async-buck practice mapped to this pinout:

- Hot (high-di/dt) loop, minimum area, one layer: `CIN(+) -> IN(1) -> [top
  FET] -> LX(8) -> SS510 (cathode at LX, anode to GND) -> CIN(-)`. CIN and the
  SS510 MUST be adjacent, sharing tight ground copper between the SS510 anode
  and the CIN return; the SS510 cathode sits right on LX(8).
- Input cap: ceramic across IN(1)/GND(4), as close to the pins as possible;
  a 100 V 1210 MLCC on the 48 V bus.
- Bootstrap cap: BS(7) to LX(8), short (adjacent pins), out of the FB region.
- Switch node (LX): small island (dv/dt aggressor), just LX(8) + diode
  cathode + inductor pad. Thermal area goes on an inner/bottom pour via
  stitching vias, not by spreading the top LX plane.
- Feedback (FB pin 5): route FB and the R1/R2 divider away from LX, the
  SS510 and the inductor; keep the node small; Kelvin the divider return to
  GND(4) single-point; sense VOUT at the output cap. CFF across R1.
- Ground/thermal: EP = GND and the main heat path, via array from the EP into
  a ground plane. Star quiet grounds (FB, FS returns) into the EP, not the
  hot loop.
- Placement order: SS510 + CIN first (fix the hot loop), IC over its via
  field, inductor on the LX island, output caps, FB divider last in the
  quiet zone.

**As built.** Pours are single edges over pad groups (0.2 stroke on LX/vin);
the vin pour carries a finger covering the EN divider's vin pads; all three
input caps drop via-in-pad to the 48 V plane individually. The output-cap
pool keeps its notched outline at 0.05 stroke: the notches are functional
(they steer around the FB pad and C8's gnd pad/via between the vout pads);
do not "clean them up". The output bank (inductor + both 1210 bulk output
caps) is one rigid block with its pool polygon, its 5-via plane-drop array
and its in-pad stub; the cell is 13.29 x 19.53 mm (house placement box) at
73% part fill. The hot loop is untouched by any packing: the LX pour's north
half (U1.8 to the D1 cathode) is the high-di/dt copper; only its south lobe
follows the inductor. The FB tap sits on the injection point (via-in-pad on
L1's output pad, tactic 13), so the `vout` feed from the C8/FB pool to the
bank (8.7 mm of 0.4 mm trace) carries only C8's ripple and the divider's bias
current: a low-Z line spending length, tactic 11.

**HV clearance floor 0.25 mm.** `vin` lands on the boards' HV_BUS class on
the Featherweight, Flyweight and CNC Expansion, so the cell is spaced to
0.25, not the fragment's own 0.2 default: the EN north lane threads the
corridor between U1's gnd EP and the vin pour's VIN-pin finger at 0.250 to
gnd / 0.300 to vin, and the finger still swallows U1.1. Known tight
survivors on the declared 0.20 nets: BS cap C1.1 to the LX pour 0.200; C8's
gnd via to the vout pool 0.234. Accepted courtyard interleaves: L1/C6 and
L1/C7 at -0.090 mm (same-net inductor-beside-output-cap); D1/L1 tight at
0.039 mm courtyard gap (both on LX).

**Open (pour audit):** the vout pool's narrowest section is 0.16 mm at
(25.8, 22.1), under the class width. Widen the neck or split the pool.

Datasheet: SY8513FCC Rev 0.1A (LCSC C3034281), layout figure p.5. No EVM.

---
