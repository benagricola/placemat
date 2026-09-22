# RelayDriver layout intent

ULN2003 Darlington low-side driver array with its COM (freewheel) bypass.

The spec `RelayDriver_layout.py` implements and the fragment in `layout/` must
satisfy. Rules that apply to every module are in `modules/README.md`; how
layout is done is the `pcb-layout` skill. History lives in git.

Spec source: skill tactics (no vendor layout section).

**Structure.** The SOIC-16 pinout already pools the pads: the seven logic
inputs are one row (MCU side) and the seven open-collector outputs the other
(coil side), each channel column-aligned through the IC, so rot 0 gives one
clean routing front per side. The COM bypass stands vertical hard against pin
9 with its COM pad centred on the pin's axis (0.05 grid) so the serve is one
straight wide shot, and nested inside the IC's height so the envelope grows
only by the cap's short side (about 12.1 x 7.5 mm). COM is a chamfered POUR,
not a track (freewheel current is inductive: copper by area), swallowing pin 9
and the cap's COM pad whole; both COM pads drop their own via to the supply
plane. Each coil output pad gets a small raw pour widening its landing from
0.6 to 0.9 mm, corners chamfered, tops flush with the pad tips. Inputs are
signal: pads only. gnd never routes: E (pin 8) and the cap's gnd pad are
plane-stitched via-in-pad. No tracks anywhere in the module. Polygons are raw
(`pad_margin_mm=None`): hand-final shapes with flush pad-tip edges; do not let
the auto-swallow regrow them.
