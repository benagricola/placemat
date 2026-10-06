# Organic vs clean core layout (fairing main 6ac7021b), 2026-10-06

Both scripts placed all 40 items. Neither explore (1200 s, --jobs 2, --route-best) found a variant better than its plain
placement. Kept routes were set aside in both.

| | organic 4ac0f1c4 | clean eec33ba8 | clean + HIGH on 4 leg cells 814d2296 |
|---|---|---|---|
| power legs drawn | 4 of 4 | 0 of 4 | 2 of 4 (VBIKE, VBUS) |
| airwires | 110, 1315.5 mm | 113, 1146.9 mm | 111, 1201.7 mm |
| crossings | 285 | 228 | 358 |
| congestion | 5.58 /cm2 | 4.46 /cm2 | 7.01 /cm2 |
| quick-route closure | 89.1% (12 open) | 91.1% (10 open) | 89.2% (12 open) |
| current-path fails, routed | VSHUNT 0.5 A tap | USB_HV, VBUS, VSHUNT at 0.127 mm; GND | VSHUNT; GND |
| resolve | 10.8 s (lock holds 22) | 31.1 s | 28.6 s |

Constraints: organic has about 10 waypoints tied to its positions, 17 steered cells, 13 LOW priorities, 7 free nets and
4 estimated link limits. Clean has none of these; every link limit has a worked number.

Conclusion: the organic constraints do not limit signal routing (clean is 2 points better, with 20% fewer crossings), but
the organic hand placement of the power cells and its leg waypoints meet a requirement the unaided search does not: no
declared leg could be drawn once its ends were placed, because smaller cells stood between them. That points to a
missing stage that places the power blocks and legs first, not to missing stated reasons. 5 variants per tree.

Found on the way: organic Core_layout.py:245 and fresh 62db3efd :242 write Circle(COIN_NO_PARTS_RADIUS), but Circle
takes a diameter, so the coin keep-out is r 3.35, not r 6.7.

Full detail, registers and run ids: in the experiment agent's hand-back (this session's transcript), and logs in exp/logs.
