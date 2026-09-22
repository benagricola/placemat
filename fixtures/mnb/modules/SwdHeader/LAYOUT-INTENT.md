# SwdHeader layout intent

1x4 2.54 mm SWD debug header, root `modules/SwdHeader/`

The spec `SwdHeader_layout.py` implements and the fragment in `layout/` must satisfy. Rules that apply to every module are in `modules/README.md`; how layout is done is the `pcb-layout` skill. History lives in git.

Spec source: hardware design guide Ch 5.4/Fig 8 debug pinout + the optionality rule.

**The rule this cell encodes is OPTIONALITY, not enclosure demand:** a part a
board may legitimately choose NOT to fit cannot live inside a functional
cell, because baking it in charges every consumer its pads AND its mating
volume. Clearance is not the test; board-level choice is. A cell owns a part
only if every consumer of that cell must fit the part.

**Contents: the header, nothing else.** No series damping on SWCLK/SWDIO:
the hardware design guide (RP-008280 Ch 5.4 / Fig 8) runs both debug lines
straight from pin to header, and the RP2350 supplies the idle pulls
internally (SWDIO up, SWCLK down; datasheet 3.5.5).

**io():** `swdio`, `swclk` (from the MCU cell's matching optional io; dedicated
pins 34/33, not GPIOs), `v3v3` (probe VTref only), `gnd`. **Pinout:** p1 =
the rectangular KEYED pad = GND, p2 = SWCLK, p3 = SWDIO, p4 = 3V3. nRESET
absent: RP2350 SWD needs no reset line and McuButtons carries the RESET
button.

**Access face: VERTICAL (+Z), not an edge.** A male vertical pin header mates
top-down, so a board reserves plug volume above it (the pin row grown to the
housing outline, 10.4 x 4.7 mm for a 4-way 2.54 shell, extruded about
14 mm), not a board edge. Inside that shadow: no other part, nothing taller
than the header's own 2.5 mm insulator, no exposed copper. NORTH is the
service/label face (the knockout band is north of the pin row, outside the
housing shadow, so it stays readable with a plug seated). A right-angle
variant would make north a true mating face, and the 0.5 mm-proud edge rule
would apply.

**Copper: none.** GND and 3V3 need no vias (a THT pad is a hole through every
layer, so it is its own plane landing), and SWCLK/SWDIO end at their pads.

**Silk: KNOCKOUT, own band north.** Per-pin labels `GND / CLK / IO / 3V3`,
each centred on its pad column, plus an `SWD` title row above. 0.80 mm text
is a FLOOR (KiCad's `text_height` rule fires below it); at 0.80 mm the four
fields abut at the 2.54 mm pitch and read as one band. Short forms are
forced by the pitch.

**Envelope:** header body 10.0 x 2.35 mm; 10.4 x 6.65 mm with the silk band,
which runs 2.4-5.5 mm north of the pin row. Consumers: Flyweight (fitted).
The Middleweight does not instantiate it (sealed backpack; SWD lands on pads
there).

---
