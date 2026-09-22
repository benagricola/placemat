# ProtectionCell layout intent

freewheel + drain TVS for a low-side-switched 24 V output

The spec `ProtectionCell_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: overview "shared protection cell"; standard pad pooling.

Not a datasheet-layout module: two discrete diodes with no vendor layout
section; standard pad-pooling practice (skill tactics 1/2/8/10).

**TVS part: SMBJ33CA** (the ecosystem's one bidirectional SMB TVS across
every clamp position, one feeder fee instead of two; the FET's body diode
owns negative-going clamping on this node, so the bidirectional half is inert
here, not wrong).

**Placement:** both parts rot 180 so their `v_out` pads face each other; D2
(TVS) west, D1 (freewheel, SS510B) east at 7.33 mm centre spacing, which
holds about 0.3 mm pad-to-pad at the pooled node for two SMB-class pads
(2.59 + 1.025 + 0.30 + 1.025 + 2.39). D1 is placed at `grid=0.01` so the
spacing lands exactly. `v_supply` (D1's outward pad) and `gnd` (D2's
outward pad) each get a plane-drop via-in-pad.

**Copper:** `v_out` is one filled polygon (this node carries the coil's real
recirculation current) shaped as a T: a bridge grown to swallow both pads'
full bounding boxes plus a south neck (tactic 10) carrying `v_out` off the
cell toward the FET drain it protects. `v_out` is also a plane node: via-in-pad
on each diode's `v_out` pad (each device enters the plane at its own pad
instead of travelling the pour to a shared exit) plus one drop in the pool's
south face on the pads' mid-line; the 4.5 mm-wide south face stays so a board
may take `v_out` on the component layer instead. No hand traces exist in this
script: with two parts and one shared node there is nothing to route.

**Output-active indicator:** D3 (KT-0603Y) + R1 (7.5k 0603) directly across
`v_supply -> v_out`: lights whenever the low-side switch pulls `v_out` down
(about 21.8 V across R, 2.9 mA, about 63 mW in a 0603); dark when the FET is
off. Pure observation. A north-side branch clear of the pooled bridge and
both diode bodies (checked against real courtyard and silk extents); R1 near
D1's `v_supply` pad, D3 north of the bridge with its K pad dropping 0.2 mm
INTO the bridge polygon's copper (not just touching its edge).

**Envelope:** 14.41 x 6.15 mm parts, 14.41 x 6.88 mm with copper. Accepted
courtyard grazes: R1/D1 and R2/D1 at 0.100 mm. Known cosmetic: D3's own
pin-1 marker self-clip. `module_clearance`: no different-net pair within
0.25 mm.

---
