# PermitReceiver layout intent

one channel of the dual-ANDed PERMIT (24 V opto)

The spec `PermitReceiver_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: overview S2/Tier 2 safety spec; reuses OptoSense's isolation-barrier geometry.

Not a datasheet-layout module: the spec source is the overview's Tier 2 /
`safety-design-reference.md` "Tier 2 detail" (the electrical and safety
rules), and the isolation-barrier geometry is inherited directly from
OptoSense (identical LTV-357T-C SOP-4 footprint, so the barrier maths is
proven, not re-derived): no copper between the LED-side pad edges and the
transistor-side pad edges under the opto body.

**What differs from OptoSense (both deliberate):**
- Bleed placement: OptoSense's 10k bleed sits on the OUTPUT side (across the
  phototransistor's pull-up). PermitReceiver's bleed spans the RAW FIELD PINS
  (perm_p/perm_n) per the safety spec's wording ("bleed pull-down across the
  opto input"), sized 0603 because it dissipates about 57.6 mW continuously
  at 24 V.
- Output polarity: OptoSense is collector-output (active-low). PermitReceiver
  needs active-high = energized at its io(), so it is wired emitter-output:
  COL ties directly to v3v3 (bias only), EM carries its own 10k pull-down to
  gnd and is "out".
- Bypass: a 2-pin THT header + shunt (XFCN PZ200V-11-02P) bridges v3v3 to
  out; fitting the shunt forces "out" high regardless of the opto state (the
  overview's "locally asserts the permit for bench use"), per channel.

**Indicator LED (D2, KT-0603R):** in series in the AN chain between D1's tap
(net `an`) and the opto's own AN pin (net `opto_an`). D1 (K=an, A=perm_n) is
therefore anti-parallel with [D2 + the opto's LED] in series and protects
both from a reverse-wired field pair. Series R: 24 V - LED Vf - 1.4 V (opto
Vf) across 2 x 2.2k 0603, about 4.6 mA, about 47 mW per resistor.

**Placement.** One band: R4/R3 (series-R chain) and D1 (reverse diode) west,
D2 then U1 (opto), the bypass header H1 on the COL/v3v3 row east of U1 with
pad 1 (v3v3) facing west toward U1.COL, R2 (output pull-down) under H1's pad
2 for a straight drop; R1 (field bleed) at the south edge with its pads
doubling as the field pair's entry point, so the bleed sits across the true
raw pins. Grid: parts whose target y is not a 0.1 mm multiple are placed at
`grid=0.01` (a 0.1 grid silently lands 20.73 at 20.70). LED spacing is set by
SILK, not pads: the KT-0603 footprint's silk envelope is about 3 mm wide on a
1.5 mm pad pitch, so verify LED spacing against the real silk box. Body
envelope 21.5 x 4.2 mm; the field nets end at R1's pads and `out`/`v3v3`
at their parts (no stubs).

**Known cosmetic DRC item:** `silk_over_copper` on D2's own pin-1 marker vs
its pad 1, inherent to the stock KT-0603 footprint (self-clip, not a
neighbour collision; KiCad clips silk over mask at fab).

**Clearance:** min copper gap 0.250 mm, 0 pairs under the 0.25 floor. All
eight parts resolve through `find_by_nets()` (the two multi-net parts with
`exact=True`, since {out, v3v3} is a subset of the opto's net set).

---
