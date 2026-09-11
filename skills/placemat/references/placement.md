# Placement tactics

What good placement IS, in terms of component ROLES rather than part numbers.
Read before placing anything - round step 5.

## Objective

Minimise same-net pad distance and current-loop area; enable the widest possible
copper (pours over traces for power); keep the module envelope tight. Alignment,
rotation and packing are tactics serving this - never goals in themselves.

State every rule in terms of component **roles** (bypass cap, switch node, FB
divider, series chain, diff pair, isolation barrier) and **topologies**
(sync/async buck, ORing pass, opto input, transceiver front end) - never part
numbers. Role knowledge transfers to parts you have not seen; part knowledge
does not.


## Placement tactics

1. **Block formation** - pick rotations from relative footprint sizes so
   same-net pads close into one rectangle a single pour can cover (e.g. flip a
   bulk cap whose height matches two neighbours' combined height).
2. **Pad pooling** - point shared-net pads at each other so several targets
   collapse into one routing destination.
2a. **A proximity constraint belongs to a CONNECTION, not to a part.** Every
   loose part is connected to something, so "does it have a net" is never the
   question - and classing the PART is still wrong, because what a part is FOR
   does not tell you which of its links has to be short. A filter's job is to
   filter; that says nothing about where it goes. What matters is that the link
   from its filtered side to the LOAD is short - the unfiltered side may run the
   length of the board. A regulator's output can travel if the decoupling sits
   at the load. A divider's tap-to-FB-pin link is the constrained one; its
   top-to-VOUT link may travel (tactic 11). One part, two links, different
   answers: a per-part class cannot express that, so record the LINKS.
   What a link records is a WEIGHT - what a millimetre on that connection is
   worth against every other connection competing for the same room. Three
   points on that scale are worth naming because they cover most cases, and a
   connection that sits between two of them takes the number in between:
 - **Short by function.** The link IS the behaviour, and lengthening it
     degrades or breaks the circuit: bypass cap to its served pin, filtered
     node to its load, FB tap to the FB pin, driver to gate, Kelvin tap to the
     shunt, crystal to its pins, snubber across the node it damps. These take
     adjacency first and do not yield it under pressure.
 - **Preference.** Shorter is tidier and routes better, nothing degrades: a
     series element in a DC or slow path, a pull-up on a slow line. The part
     may sit ANYWHERE along that path - halfway down a trace on the far side of
     the board is a legitimate answer - and these are what give way when room
     runs short.
 - **Decided elsewhere.** Mechanics fixes an endpoint and the net follows: an
     indicator behind a case window, a jumper a hand has to reach, a connector,
     a test point.
   The named three are 10, 1 and 0 on one scale, relative to a preference:
   a link at 3 is worth three ordinary ones per millimetre. Reach for a number
   when a connection genuinely sits between the names - a serve that should
   beat the ordinary pull without outbidding a hot loop - and for a named
   weight otherwise, because a name says WHY and a number does not.
   THE WEIGHTS ARE THE MODEL'S TO ASSIGN, not the owner's to supply. Every
   input to this is electrical and readable: which node is high-impedance,
   which loop switches fast, which capacitor is bypass and which is bulk, which
   end of a filter faces the load. So assign a weight to every link the circuit
   gives an answer for, as part of laying the board out, rather than waiting to
   be told which connections matter - an owner who has to hand you the whole
   table is doing the work the harness exists to do. What the owner does is
   ARGUE with it, which is why every link carries its reason: a number with no
   why cannot be challenged, only obeyed.
   Record these where the layout can USE them: the prose belongs in the
   module's layout-intent with the rest of the electrical input, and the
   machine-readable form belongs in the layout script that already resolves
   these parts by role - one call per link, endpoints given as pads, recorded
   against the footprint's instance path so a schematic edit cannot silently
   re-point it. A cell's links travel with its fragment, so the board that
   stamps the cell inherits what that cell needs. State the length the circuit
   actually needs where you know it, as a limit ON the link: a weight nobody
   can check is decoration, the pass then fails when placement misses it, and
   how short "short" has to be is a property of the circuit, not something a
   library can pick. The cost of not doing it does not look like its cause:
   an objective that minimises airwire UNIFORMLY spends the board's scarce
   adjacency on links that never needed it, and the links that did find it
   already gone - which reads as "the board is too full" when it is really
   "the room went to the wrong connections".
2b. **A part or a cell is placed by its NETS, not by a typed coordinate.** A hand
   hint is a guess at where there is ROOM; it carries nothing about where the
   part's net is, so a search seeded on it parks parts in free board far from
   everything they connect to - and the result reads as deliberate, because a
   human typed it. Seed the search at the point with the shortest total airwire
   over the part's own routed nets; keep the hint only as the fallback, and when
   a part does fall back, NAME IT - a silent fallback is indistinguishable from
   a decision, and the list of them is the most useful diagnostic the pass
   produces. Two corollaries decide whether the objective works at all:
   (a) exclude PLANE nets - a plane is reachable from anywhere by a via, so
   counting it prices every position about equally and drowns out the nets that
   must actually reach something; (b) count only parts already PLACED - an
   unplaced footprint sits wherever the netlist dropped it, so aiming at it aims
   at nothing. Measure the result as median distance from a pad to its nearest
   same-net pad, loose parts against parts inside a cell: the cell figure is
   what good looks like, and a gap between them is the work left.
2c. **Placement has an ORDER, and the order is a trap for a flattened cell.**
   Parts go down one at a time and each is seeded against what is already
   placed. A cell whose members mostly connect to EACH OTHER breaks on that:
   the first member down has no sibling to aim at, takes its fallback, and every
   later member is then seeded on that arbitrary spot - so the cell ends up
   strung across the board and each individual placement looks locally
   reasonable. Re-run the search for the fallback set once everything is placed,
   keeping a move only where the airwire improves.
   **But a cell that cannot gather is a cell whose SHAPE is wrong, not a board
   that is too full** - check the area before believing the second story. A
   long thin cell needs a long thin hole; the pockets between big cells are
   stubby, so a strip can fail to place on a board with a third of its face
   free. FLATTENING IS NOT THE ANSWER: it scatters the members, throws away the
   routing the cell carries, and looks like damage because it is. Reshape the
   cell to the holes that exist and stamp the new shape everywhere. Do this
   work on the TIGHTEST board that uses the cell - a shape that places there
   places anywhere, and a shape proven on a roomy board tells you nothing.
2d. **Placement cannot see copper the script draws later** - the escape fans,
   the rails, the planes, all of which are drawn after placement because they
   are anchored on where the parts landed. Hand hints hide this by keeping parts
   clear of that copper by accident; placing by net walks parts straight into
   it, because the fan and the part are both aimed at the same pins. Two
   answers, and the choice is about WHEN the copper's position is decided:
   copper whose position is known before placement gets RESERVED (a band, with
   the reason and with the nets it carries, so the rail's own bulk cap is still
   allowed to sit on the bar that feeds it); copper whose position depends on
   where the parts landed gets a REPAIR pass afterwards that re-runs the same
   legality test and moves only what actually broke. Neither is optional once
   placement is net-driven, and the failure mode is a short in DRC, not a
   warning. But reach for a third answer before either: MAKE THE COPPER
   VISIBLE. A repair pass is not free - run one after the plane drops and it
   strands the drops of whatever it moves, and carrying those vias along moves
   HOLES, which need a hole-to-hole clearance the pad test never checked. When
   a guard you have PROVED correct says a pose is illegal and the placer put a
   part there anyway, the input was wrong, not the logic: ask what the guard
   could see at the time. Copper the checks can see needs no pass at all.
3. **Identical parts in one role form a ROW, not a stagger** - same rotation,
   one line, at their courtyard pitch. Each pad column then becomes a single
   straight destination instead of a set of scattered ones, which is what
   removes the bridges: on a plane-fed cap row the ground pads sit outboard as
   a via fence and the supply pads inboard pooled by one pour; on a pull-up or
   terminator row the supply pads take plane vias on one line and the signal
   pads take their escape vias on the other, and no copper links the row at
   all. The pour pools locally; the plane distributes. A stagger is only worth
   its extra depth when the served pins themselves are staggered - check that
   before accepting one, because a stagger inherited from an earlier revision
   usually is not.
4. **Serve-pin alignment** - put a bypass cap's served pad exactly on the served
   pin's axis so the connection is one straight trace. Alignment beats grid:
   drop to a finer placement grid when the pin axis demands it.
4b. **A regulator is a BLOCK: the package and the caps that serve its pins place
   together, and the package's pose is what decides whether they can.** Place
   them as three independent searches and each finds its own clear spot -
   millimetres from the pin it decouples, which is not decoupling - and no
   amount of re-hinting the caps fixes it, because the fault is the package.
   So ask of the pose first: is there room IN FRONT OF THE PIN ROW for what
   serves it? A package turned so its pins face a board edge, a neighbouring
   cell or its own tab has nowhere for its capacitors and will scatter them
   every time. Turn the pin row toward the open board and let the thermal tab
   take the edge - a tab wants copper and has nothing to serve. Then derive
   each cap's position from the package's own pads or courtyard rather than
   writing it down: the offset from a part's centre to its pad depends on the
   package, so a literal is wrong the moment a value or a footprint changes.
   Where the band is too tight for every cap to sit exactly on its pin's axis,
   give up the alignment by a fraction and keep the LENGTH - a serve with a
   jog narrower than the pad is still a serve; one that is millimetres long is
   not.
5. **Two-column chain blocks** - a series chain (e.g. an FB divider) wants its
   chain pads in one column (one straight rail, entered by a 45 degrees from the pin)
   and its externally-fed pads in the other.
5b. **A cell's bounding box is not its footprint - cells INTERLEAVE.** The
   only things that may not collide are real courtyards and real copper;
   everything else inside a cell's rectangle is free board that a
   neighbour may occupy. One thin part or one stub can push a rectangle
   far out while leaving that whole flank empty, so packing by rectangles
   systematically over-reserves - on a dense two-sided board the
   "internal air" of a few rigid cells can exceed the entire area deficit
   you are trying to solve. Optimise each cell for MINIMAL OCCUPIED AREA
   with its electrical structure intact, not for a tight or square
   rectangle: a sprawling bbox with small occupied area beats a compact
   bbox that wastes its interior. Report cells as bbox + occupied-union +
   fill% + where the empty regions ARE, and pack on real geometry.
   Caveat that keeps this honest: space a cell genuinely NEEDS is
   occupied even when it looks empty - its own routing lanes, a hot loop
   foreign copper must not cross, a thermal region, an isolation gap.
   Declare those as keepouts WITH the reason; never claim territory by
   assumption.
5c. **A courtyard is not the part either.** It is a rectangle drawn round
   something that is not rectangular, so on a QFP/QFN it covers 1-2mm of
   empty board at each CORNER - no body, no pad, nothing. That space takes
   small passives, and putting them there costs nothing but a
   courtyards-overlap DRC entry. The real constraint is body + pads +
   clearance; measure against those. Package-class nuance: this is a
   corner effect on a body-in-the-middle package, so it does NOT license
   intrusion along a pad row, over a lead frame, under a part with a
   bottom termination, or into a courtyard that is genuinely oversized
   for a stated reason (a connector's mating volume, a hot part's
   thermal keepout, a creepage gap). Record each intrusion with what it
   clears, and expect the DRC entry as documented output rather than
   suppressing the rule.

6. **Envelope is a first-class objective** - after electricals work, pack:
   rotate whole banks, pull stragglers into vacated pockets, centre-align mixed
   footprints. Buying envelope with a little *quiet-net* length is the right
   trade. Hard constraints outrank packing: isolation/creepage gaps, diff-pair
   symmetry, connector mating interfaces (tactic 7).
   Two passes do most of the work, and both are mechanical enough to script:
   (a) **Close the satellite gap.** Once the electrical structure is fixed,
   every part outside the anchor slides along its serve axis toward the
   anchor until real geometry stops it - a courtyard it may not enter
   (5c), a foreign pad, a lane it must not dam. The stop is MEASURED and
   the script lands exactly on it (the cell class has a pack primitive
   that slides a part until its courtyard or its pads' clearance stops
   it); done by eye this overshoots by 0.03-0.10 and the overshoot only
   shows up in DRC. A round number in a pitch or an offset ("4.60",
   "-2.60") is the signature of a gap that was never closed, and so is an
   "air" constant between two courtyards: a courtyard already IS the
   assembly margin, so two courtyards stop one grid step short of
   touching and never further. A tenth of a millimetre of padding per
   part is a millimetre per cell and a centimetre per board.
   (b) **A part that only sets the envelope moves into interior air.**
   Ask of the part on each extreme edge: what would the cell measure
   without it? If it is the only thing out there, it belongs in a gap
   further in, and paying serve length for it is the right trade. The
   anchor may MOVE to open that gap - shifting a package to widen an
   interior slot from 0.65 to 1.25 to house a satellite is cheap when
   the alternative is that satellite hanging off the end with air all
   round it. Check the served-pin contract survives the move (a bypass
   that changes which supply pin it faces is a regression, and a
   rotation usually fixes it).
7. **Connectors place by their mating interface, not their pads.** Before
   placing any connector, answer: which way does the counterpart enter
   (side-entry cable/wire, vertical plug, edge-mount, panel/bulkhead)? What
   volume does mating need (cable bend radius, hand/latch room, tool access -
   a screw terminal is side-entry for the wire AND top-entry for the driver)?
   Does it require a board edge (side-entry field wiring and edge-mount parts
   do; vertical headers and test points don't)? Reserve that mating volume as
   a keepout, point every entry face outward at a serviceable edge, and place
   connectors FIRST - the enclosure and field wiring fix them; everything
   else packs around them. A connector facing into the board is a defect no
   matter how clean the routing.
