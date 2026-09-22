# ReversePolarityFet layout intent

Return-path N-FET reverse-polarity guard for node inputs: conducts both ways
once polarity is right, so regen flows back up the cable.

The spec `ReversePolarityFet_layout.py` implements and the fragment in
`layout/` must satisfy. Rules that apply to every module are in
`modules/README.md`; how layout is done is the `pcb-layout` skill. History
lives in git.

Spec source: skill tactics (no vendor layout section).

**Structure.** The FET's drain EP (north) IS the cable V- landing (gnd_in): the
board pours the connector's V- pins straight onto it and the cell draws
nothing on that net. The source row (south) is board GND, pooled into a gnd
bar that also takes the gate cap's and the zener's ground ends and the
TVS/input-cap returns, with plane-drop vias in the bar and in the big pads.
The gate network hangs east of the FET on the gate pad's own axis (one
straight serve from the pad centre): gate cap point-blank, zener next, bias
resistor above them fed from the v48 pool. The bus parts (TVS + input cap) sit
west; their v48 ends pool along the north and reach the resistor over the top
of the EP.

**Open item (pour audit):** the gnd bar is a 29.8 mm2 ground polygon. The
module rule is that a cell does not pour ground: the board's plane is the
ground and each ground pad takes a via. Reduce it to the pad pool the source
row and the returns actually need, with via-in-pad on each, and let the board
plane distribute.
