# Layout critique scenarios

## Goal

Get the user's judgement of layouts into a form placemat can learn from. Small hypothetical layouts of common circuit
blocks are generated in many variants, most of them good apart from one deliberate defect. The user marks what is wrong
in each, or picks the better of two, in a hosted page. Each mark is stored as a record, tied to the variant and to the
known cause of its defect.

The marks feed three things:
- the weights of placemat's score (from A-or-B picks);
- new findings and fixtures (from rules the user states);
- a critic model trained to predict where the user would object.

## Sources

| Source | Where | What it gives |
|---|---|---|
| fairing instrument | ~/Documents/Hardware/fairing-instrument (copied, never edited) | zen designs, cells, routed boards |
| mnb ecosystem | ~/Documents/Hardware/mnb-ecosystem (151 boards, 204 zen) | zen designs and boards, some incomplete |
| MnB Ultralight family | ~/Documents/Hardware/MnB Ultralight, M&B Ultralight N17, N17 R2, MnB Featherweight | KiCad schematics and boards |
| open corpus | the BC250 harvest (501 boards, open licences) | KiCad boards with netlists |

These paths are given to the tool as arguments, not written into it. A design that is incomplete still gives blocks
wherever its netlist is whole around an IC.

## Blocks

A block is an anchor IC plus the parts that hang off its local nets: nets of the IC that reach at most a few other
parts, followed up to two hops. Ground and the board's wide rails are kept as nets but not followed. The parts and nets
come from the netlist. The footprints come from the source board, or from the KiCad libraries where the source has none.

The block's type is taken from the anchor and the parts around it. Rules match the part's value and footprint
keywords, and the shape of the circuit:

| Type | Recognised by |
|---|---|
| ldo | a 3-5 pin regulator, caps on its input and output |
| switcher | a regulator IC, an inductor on one of its pins, bulk caps (buck, boost, buck-boost) |
| mcu | an IC with many pins and several decoupling caps; a crystal or oscillator if present |
| can | a CAN transceiver, a termination resistor, a connector |
| usb | a USB connector, ESD parts, a pair to an IC |
| other | anything else, kept for later |

Each type has a short list of what makes it good. A block whose type can't be found is set aside, with the reason.

## Hypothetical board

Each block becomes a small board of its own:
- an outline sized from the block's courtyard area;
- 2 layers, or 4 layers for switcher and mcu blocks;
- a ground pour on the bottom, or on an inner layer when there is one;
- nets that leave the block end at port pads on the outline's edge, so the routes have somewhere to go.

## Variants

On the BC250, each block gets one good variant and many with defects, each defect cause recorded:
1. **Good:** placed from the type's template intents (decoupling `Near` its pin, inductor `Beside` the switch pin,
   crystal by the MCU's oscillator pins, termination at the connector), then routed with KRT.
2. **One defect:** the same, with one item from the type's defect list applied. Examples:
   - a cap far from its pin;
   - the switch-node loop made large;
   - the inductor on the wrong side;
   - the feedback trace run past the inductor;
   - the crystal far from the MCU;
   - the termination at the wrong end;
   - the pour split under the block;
   - thermal vias missing under an exposed pad.
3. **Perturbed:** small jitter or swaps, as in the failure-data generator.
4. **Runner-up:** placemat's own second and third choices from its search.

Each variant writes:
- a record: source, block, type, causes, score terms, route closure and DRC counts;
- its geometry as JSON: the outline, plus pads, tracks, vias and pours per layer, with each item's reference and net;
- a thumbnail.

A few thousand variants is an overnight run at the failure generator's rate. That rate is measured on larger boards,
so this estimate is not checked.

## Feedback page

A private hosted page, with its data in a shared store that the session reads directly.

- **Scenario batches:** the geometry JSON of each batch is uploaded to the page's asset store. A batch is about 50
  blocks, each with 3-6 variants.
- **View:** drawn in the browser from the geometry. Top, bottom and 3D views, one copper layer at a time or all of
  them, nets highlighted on hover. Reference designators are shown, colours follow studio's, and there are no greys.
- **Mark mode:** click a point or a part, choose a type, then add an optional note. The types:
  - *rule*: wrong anywhere;
  - *this layout*: wrong only here;
  - *routing*;
  - *good*: worth keeping as it is.
- **Compare mode:** two variants of one block side by side. Pick A, B or the same, with an optional note.
- **Progress:** how many variants are marked and compared in the batch.
- A mark is never sent as a sentence. It is a record: variant id, mode, point (x, y, layer), items, type, choice,
  note and time.

## Using the marks

- **A-or-B picks:** fit the score weights of placemat's settings, then compare against the current defaults. Changing a
  default is proposed to the user, as a release.
- **A rule mark that matches a variant's cause:** confirms that defect. placemat gains a finding or a fixture for it,
  which is a new form and so the user's call during consolidation.
- **A rule mark that matches no cause:** something placemat does not measure. It goes on a list for the user.
- **A routing mark:** a router case. It goes to the KRT fork with the variant as the repro.
- **After a few hundred marks:** a critic model is trained on them, the same kind of model as the routability one.

## Phases

1. Block extraction from all four sources, with a count per type. Templates and defects for ldo, switcher and mcu.
   200 variants. The page, with mark and compare modes. A first batch for the user.
2. The can and usb types, more defects, thousands of variants, runner-up variants.
3. Weight fitting from the picks. The critic model.

## Testing

- **Extraction:** small synthetic netlists with a known block. Each type is found.
- **Board build:** the outline holds the block, and each port is on the edge.
- **Defects:** each one changes what it says and nothing else, checked by measuring the affected item before and after.
- **Page:** a fixture batch renders, a mark round-trips through the store, and compare mode stores its choice.

## Out of scope

- No placemat forms, unless the user approves one from what the marks show.
- No edits to the source projects.
