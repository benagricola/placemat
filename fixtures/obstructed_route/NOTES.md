# Wide route blocked by an unrelated part

This 30 x 12 mm, two-layer board has two 3 A carriers, J1 and J2, on VB. U1 lies
between them and carries five unrelated single-pad nets across the board. Its
1.7 mm through-hole pads have 0.84 mm gaps; after the 0.2 mm clearance on each
side, a 0.44 mm track can fit. The current-derived width exceeds that opening
on both layers. End pads stop the wide route going around the wall.

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
