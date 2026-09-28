# The load's route, between the parts that carry it

Date: 2026-09-28
Status: draft
Source: a board's layout work, 2026-09-28: "the check treats every pad and
track of a net as the load's path, so sense, boot and bias connections fail
it"

## The problem

`check current-path` judges each net a part's `Pm.I` puts current on by
the narrowest point of the load's widest route between the parts that
carry it (`checks._load_path`). On the board's modules most of its FAILs are
not the load:

| Net (module) | Reported | What it measured |
|---|---|---|
| SW2 (usbconverter) | narrowest track 0.16 | the track joining the controller's two SW2 pins; the 3.6 A runs in the SW2 zone, FET to coil |
| SW1 (usbconverter) | 0.16 | the boot capacitor's track |
| ISP (usbconverter) | 0.075 | the current-sense line from the controller's pin 12 |
| SW_5V (usb5v) | 0.56 | the boot capacitor to coil track; the switch current is in a zone lane |
| VBIKE, VPROT_IN (protection) | 0.04 | the ideal-diode controller's ANODE/CATHODE sense pins |
| VSHUNT (logicsupply) | 0.02 | an input pin's lead into its pour |

Four things in the check produce these:

1. **A zone is not part of the net's copper.** `_net_graph` takes tracks,
   vias and drawn pours but not zones (`kind == "zone"`), so where the
   current runs in a zone no route joins the carrying parts. The check then
   judges the narrowest track anywhere on the net, which is a pin lead, a
   boot track or a sense line.
2. **Every pair of carrying parts is judged at the net's largest current.**
   A controller with its own small `Pm.I` (1 mA), or one given the load's
   current, is a carrier on every net it has a pin on, and the thin route to
   its sense pin is judged as if the 3.6 A ran through it.
3. **The narrowest route to any of a carrier's pads decides**: a part's
   other pins on the net (a second switch pin, a sense pin) set the width
   though the current enters by its widest-joined pad.
4. **A part carries on a net whose current it gives as 0** (`Pm.I: sw:3A
   isp:0`): nothing lets a net's pin be named as not carrying.

## The change

1. **Zones are copper of the net's graph**: a zone's fill, on each layer, is
   a node whose width is its narrowest neck, as a drawn pour's is, and it
   joins what its fill touches.
2. **A pair of carrying parts is judged at the lesser of their two
   currents** on the net - what can flow between them - by the widest route
   from any pad of one to any pad of the other on the net. The net's verdict
   is its worst pair by width over need, naming both ends and the current it
   was judged at: "narrowest point of the load's widest route, U3.2 to
   L1.1, 3.6 A at 10 C rise on 1 oz".
3. **A part carries on a net only at a current above zero**: a per-net
   `Pm.I` that leaves a net out, or gives it 0, does not make the part a
   carrier there.
4. **No copper joining two carriers yet is not judged**: "no copper joins
   U3 and L1 on SW yet" (ok: not judged), in place of the narrowest track
   anywhere on the net.
5. **One carrier on a net**: its widest route to any other part's pad on the
   net, at its own current (as now).
6. **Docs**: `api.md`'s check paragraph, and the design skill's `Pm.I`
   entry: a controller that senses a load's net gives its own current there
   (or leaves the net out of a per-net `Pm.I`), so its sense pin is judged at
   what it draws, not at the load's current.

## Verification

- Pure tests (synthetic geometry):
  - a FET and a coil joined by a 3 mm zone lane, a 0.16 mm boot track from
    the FET's pin to a capacitor: judged by the zone lane, ok;
  - a controller (`Pm.I: 1mA`) whose two switch pins are joined by 0.16 mm,
    on a net whose FET and coil carry 3.6 A through a wide route: the load
    pair decides, and the controller pair is judged at 1 mA, ok;
  - a sense pin at 0.04 mm on a 3 A net whose controller gives the net 0:
    not a carrier;
  - two carriers with no copper between them: not judged, "no copper joins";
  - a pair whose widest route is narrow: FAIL, naming the pair and the
    current.
- The existing current-path tests pass, or change where they encoded the
  behaviours above (listed in the commit).

## Not in scope

- Currents split across parallel routes (the widest one is judged).
- Inner-layer IPC figures (the external-layer constant is used, as now).
