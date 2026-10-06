# Reference corpus, 2026-10-06 (summary; full detail in the session transcript)

Adopt 8: pic_programmer (KiCad demo, CC-BY-SA-4.0, 63 parts, 2L), usb-c-power-adapter (antmicro @4d3e9e289a29,
Apache-2.0, 122 parts, 4L), LoRa-V3 (Strooom @4de6979ace4a, MIT, 84, 2L), ir-irradiance-probe (antmicro @d4891186544d,
Apache-2.0, 57, 2L), esp-rust-board (esp-rs @efe1e8ad5c6d, CERN-OHL-P-2.0, 55, 2L), Watchy (sqfmi @5f147972aa21, MIT,
84, 4L), spimux (oxide @29e59e9c99ce, MPL-2.0, 22, 2L), chainlinkDriver (splitflap @87b17c531ca5, Apache-2.0, 65, 2L).
Optional: ESP-PROG (OLIMEX @8dfb3bb217bd, test a only).

Test (a), route the human placement with copper stripped, today:
- pic_programmer 100% with --islands VCC; spimux 86.5%; ESP-PROG 70% at class width (86.7% at the human's 0.254).
- Stripped boards already fail DRC (footprint shorts, starved thermals): pass = no copper error beyond that baseline.

Test (b) import: `pcb import` works for 2 of 9 (pic_programmer, usb-c-power-adapter); the rest fail parity (field
drift, auto net names), generation (mounting-pad / MP pins) or are KiCad 5 schematics. Import swaps footprints for
stdlib ones and drops hierarchical net-class patterns, so the reference for (b) is the regenerated board.

Bug: placemat route crashes on user-named copper layers (read.py:463 GetLayerName -> values.py:40).
Storage: manifest (SHA, sha256, SPDX, per-board facts) + fetch script into a git-ignored cache.
Evidence: corpus/src, import, route, drc and scripts.
