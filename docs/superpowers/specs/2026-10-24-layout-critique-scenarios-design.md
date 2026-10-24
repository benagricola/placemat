# Layout critique scenarios

## Goal

A large corpus of small hypothetical layouts of circuit blocks, in hundreds of thousands of variants, that the user can
judge. The user marks what is wrong in a layout, or picks the better of two, in a hosted page.

The corpus and the marks are training data for fast models:
- a critic that predicts where a layout is bad and why;
- later, a model that proposes good layouts.

placemat is slow, and a model is the fast replacement for judging a layout. So the corpus is made by a fast generator
of its own. placemat and its score are not used to make it.

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
- Whether and how placemat uses the critic is a later decision for the user.

## Phases

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
