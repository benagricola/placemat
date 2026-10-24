# Layout critique scenarios

## Goal

A large corpus of small hypothetical layouts of circuit blocks, in hundreds of thousands of variants, that the user can
judge. The user marks what is wrong in a layout, or picks the better of two, in a hosted page.

The corpus and the marks are training data for fast models:
- a critic that predicts where a layout is bad and why;
- later, a model that proposes good layouts.

placemat is slow, and a model is the fast replacement for judging a layout. So the corpus is made by a fast generator
of its own. placemat and its score are not used to make it.

## Decisions the models make

The data serves these questions, and each one needs a particular kind of label:

| Decision | Labels | Where they come from |
|---|---|---|
| Which of two layouts of a block is better | A-or-B picks, and orderings | Variants of one block. The generator orders them by rules broken, and the user picks between them |
| Where a layout is wrong, and why | A point or part, with a reason | The generator knows where each defect is and which rule it breaks. The user marks what the rules miss |
| What to move to fix it | A defect variant paired with its fix: which part, where to, at what rotation | The generator, since it knows the inverse of each defect it applies |

The first use is inside placemat's search, as a fast score for candidate placements. That sets three requirements:
- **Placement first:** the critic judges a placement before it is routed, from parts, pads, nets and airwires. Routed
  copper is shown to the user where it helps them judge, but the model must not need it.
- **Blocks in context:** a block on a board has neighbours, an edge, and nets that leave it in known directions. A
  variant includes some of that, such as foreign parts nearby, the board edge, and port directions. Then the critic
  can be run over each block of a whole board.
- **The same input as placemat:** the model reads what placemat holds at search time (footprints, pads, positions,
  rotations, nets), turned into the same raster channels as the training records or into a graph. Every variant
  writes that input as well as the geometry for the page.

## Scenario types

Each type is a template:
- its parts, as roles with sampled values and packages;
- its nets;
- what makes it good, written as checkable rules;
- the defects that break those rules.

| Group | Types |
|---|---|
| Power | ldo, buck, boost, buck-boost, inverting, li-ion charger, load switch, efuse / hot-swap, ideal diode / reverse polarity, battery protection, supercap / holdup, pmic multi-rail |
| Power stage | half bridge with gate driver, h-bridge, three-phase bridge, stepper driver with sense resistors, low-side mosfet switch, relay with flyback, current shunt with amplifier |
| Digital | mcu decoupling and crystal, mcu with external flash (qspi), fpga bank decoupling, sdram / lpddr pair, level shifter, i2c bus with pull-ups, spi bus fan-out, debug header (swd / jtag), reset and boot straps |
| Interfaces | usb-c device (cc, esd, pair), usb hub, can transceiver and termination, rs-485, ethernet phy with magnetics, ffc / display connector, sd card, hdmi / lvds pair group |
| Analog | op-amp filter stage, instrumentation amplifier, adc front end with reference, dac output, voltage reference, precision divider, thermistor / rtd input, audio codec, class-d amplifier |
| RF and clocks | antenna feed with matching network, rf module with keep-out, crystal oscillator, clock buffer, gnss front end |
| Sensors and misc | imu / magnetometer, hall sensor, led driver, addressable led chain, buzzer / haptic driver |
| Protection and isolation | tvs / esd on a connector, fuse and polyfuse, digital isolator with isolated dc-dc and creepage slot, optocoupler input |

That is about 60 types. The list is open, and more are added by writing a template.

## Sources

Templates are written from:
- datasheet reference layouts;
- common practice;
- blocks found in real designs.

The real designs are fairing-instrument, mnb-ecosystem, the MnB Ultralight family and the 501 open boards. All of them
are read from copies or given as arguments, and never edited.

Real designs give each template:
- realistic values and packages to sample from;
- extracted blocks for a smaller set of real variants, with the anchor IC and its local nets.

## Generator

The generator is fast and stand-alone, written in Rust beside placemat's native code or on its own. It needs no KiCad
and no placemat at run time.

1. **Sample:** a type, part values, packages from a footprint table built once from the KiCad libraries, the layer
   count, board room and port sides.
2. **Place:**
   - Good: the template's rules are met with randomised freedom (side, orientation, spacing, mirrored layouts) by a
     quick constructive placer.
   - Defect: one or two rules are broken on purpose, each one named.
   - Mess: random within the room, a small share for contrast.
3. **Route:** a quick grid router (A* on a fine grid, a few rip-up passes) with pours on the ground and power nets, and
   vias. A block has tens of nets, so this takes milliseconds to tenths of a second.
   - Its tracks are cruder than KRT's. A routing defect is recorded the same way as a placement defect, for example a
     long return path or a track through the switch-node area.
   - A sample of variants is also routed with KRT on the BC250, so the routing marks can be compared on realistic
     copper.
4. **Check:** clearance and connectivity on the grid. A variant that breaks the rules it should keep is dropped,
   with the count recorded.
5. **Write:**
   - geometry JSON: the outline, plus pads, tracks, vias and pours per layer, each with its reference, net and role;
   - a record: type, seed, sampled parameters, rules met and broken, route outcome;
   - rasters for model training, in the same channels as the training records.

The generator is deterministic for a seed, so a variant is its type, its seed and the generator version, and it can be
made again rather than stored. The target is 100k variants or more, in hours on the BC250's CPU. That rate is a guess
until the router is measured.

## Feedback page

A private hosted page, with its data in a shared store that the session reads directly.

- **Batches:** drawn from the corpus by a sampler that covers the types and mixes good, defect and mess variants.
  Compare pairs are two variants of one block. A batch's geometry goes in the page's asset store.
- **View:** drawn in the browser from the geometry. Top, bottom and 3D views, layers one at a time or together, the net
  under the pointer highlighted. Reference designators and roles are shown. Colours carry meaning, and there are no
  greys.
- **Mark mode:** click a point or a part, choose a type, then add an optional note. The types:
  - *rule*: wrong anywhere;
  - *this layout*: wrong only here;
  - *routing*;
  - *good*.
- **Compare mode:** A, B or the same, with an optional note.
- **Quick mode:** one variant at a time, good or bad, then the next. It is for volume.
- A mark is a record: variant id (type, seed, version), mode, point (x, y, layer), items, type, choice, note and time.

## Using the corpus and the marks

- **A critic model** trained on the generator's labels (rules broken, where) and the user's marks. It is fast enough
  to judge thousands of layouts a second on the BC250's GPU.
- **Rule marks** that match no template rule show something the templates miss. They become new rules, and the
  generator makes more of that defect.
- **Compare picks and quick marks** calibrate the critic toward the user's taste, beyond what the rules say.
- **Routing marks:** the ones on KRT-routed variants are router cases for the fork.
- **Placemat's search:** the critic is a candidate score term there. Its weight would be a setting, and turning it on
  is a decision for the user once the critic is shown to agree with them on real boards.

## Phases

0. **Pilot.** Read PCB Gym and PCBWorld for parts to reuse. Build a rough generator for ldo, buck and mcu decoupling
   blocks, placed in context: about 150 variants, with their fix pairs. The page has all three modes, and some
   variants repeat without warning. The user marks for about 30 minutes. The report covers:
   - how consistent the user's judgements are;
   - how well the rule labels agree with the user's marks;
   - which mode yields the most per minute;
   - what the user marks that the rules miss.
   A critic trained on the pilot's generator labels is then run on blocks cut from real boards, and compared with the
   user's marks there.
1. The generator core: sample, place, route, check, write. 10 types across power, digital and interfaces. A rate
   measured on the BC250. The page with all three modes. A first batch.
2. All types, a 100k corpus, a KRT-routed sample, blocks extracted from the real designs.
3. A critic trained on generator labels, then on the user's marks.

## Testing

- **Templates:** each sample meets its good rules, measured on the result.
- **Defects:** each one breaks the rule it names and no other.
- **Router:** a routed variant is connected, and passes the clearance check on the grid.
- **Determinism:** the same seed and version give the same bytes.
- **Page:** a fixture batch renders, and a mark round-trips through the store.

## Out of scope

- No placemat forms or settings change.
- No edits to the source projects.
