# Wide route blocked by an unrelated part

This 30 x 13 mm, two-layer board has two 3 A carriers, J1 and J2, on VB. U1 lies
between them and carries five unrelated single-pad nets across the board. Its
1.7 mm through-hole pads have 0.84 mm gaps; after the 0.2 mm clearance on each
side, a 0.44 mm track can fit. The current-derived width exceeds that opening
on both layers. End pads stop the wide route going around the wall. Their 0.57 mm edge gap
satisfies the unchanged 0.5 mm copper-edge minimum. A route needs its own
width plus 0.2 mm pad clearance and 0.5 mm edge clearance, so this edge gap
provides no bypass. The gaps between pads still admit the 0.2 mm signal route.

The `legs` phase asks J1.1 to J2.1 at the current-derived width and must fail,
with failure evidence naming U1. The `signals` phase then joins VB at the
0.2 mm class width. Final connectivity therefore exists, while the earlier
required-width obligation stays unfulfilled: final clean closure 0 and one
failed width. This distinguishes connectivity from meeting electrical intent.

Regenerate with `PYTHONPATH=src .venv/bin/python fixtures/obstructed_route/make.py`.
The generator assigns deterministic board-item UUIDs and saves using KiCad's
current format. Record and compare the actual router evidence with
`fixtures/reference/route_ref.py obstructed-route`; do not adjust the board to
hide a mismatch with the expected behavior.

The local reference protocol explicitly sets `KICAD_NET_RESCUE=0` for this
fixture's route subprocess and records that setting in the result's `protocol`.
It disables expensive fine-parameter rescue while retaining initial A* search
and its blocker evidence.

The original 30 x 12 mm fixture had an invalid 0.07 mm edge gap against the
0.5 mm project minimum. Its 1135.4-second default-rescue and 16.7-second
bounded runs produced useful routing diagnostics but had `valid=False` and
cannot be passing reference records. Reviewer-approved mechanical correction
increased only the board height to 13 mm and translated every component Y
from 6 to 6.5 mm; X, pitch, pads, current, widths and clearances are unchanged.
This fixes input legality without lowering any original manufacturing floor.

The bounded protocol does not prove geometric impossibility:
search exhaustion and a diagnosis of `unknown` remain truthful outcomes. Other
reference boards and the caller's environment retain their own rescue policy.
