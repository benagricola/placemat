# A plated lead and a neighbour's courtyard under a drawn envelope

Date: 2026-09-28
Status: draft
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-26 "same-face terminal
lead versus capacitor courtyard"; confirmed on 0.49.2 (2026-09-28)

## The problem

Under the courtyard envelope placemat refuses a courtyard over another
part's plated lead ("courtyard sits over a through-hole lead"), as KiCad's
DRC does (`pth_inside_courtyard`). Under a drawn envelope (`physical`,
`union`) a part claims its pads, mask openings, silk and body instead of its
courtyard, so the rule is never applied: a capacitor whose body clears a
screw terminal's lead by 0.3 mm is placed with its courtyard over the lead,
and KiCad reports it. The board worked round it with a hand-sized parts-only
keepout, which then raised a courtyard `items_not_allowed` of its own.

Under a drawn envelope the courtyard is not a shape of the part: adding it
back would change every measure that unions a part's shapes (its reach, its
extent, its edge fit, its row spacing).

## The change

1. **Under a drawn envelope, each placed part's plated leads keep other
   parts' courtyards off them, and each placed part's courtyard keeps other
   parts' plated leads off it**, as KiCad's DRC judges the pair:
   - when a part (or a cell's member) with plated leads (`_is_lead`: a
     through pad that stands proud of the far face) is committed, each lead
     becomes a reservation judged against a candidate's courtyard (its drawn
     polygon where it has one, else its box), on both faces;
   - when any part is committed, its courtyard becomes a reservation judged
     against a candidate's plated leads.
   Its own leads and courtyard are its own (the owner is let in, as today).
2. **These reservations are held apart from the others**, judged in
   `_edge_or_reservation_conflict` against the candidate's courtyard or
   leads rather than its body, and checked only when they can apply (a
   candidate with leads for the courtyard ones; a board with leads for the
   lead ones), so a board without through-hole parts pays nothing.
3. **The native scan applies them too**: the native board takes both kinds
   with the shape they are judged against, so the sweep refuses the same
   spots (parity tests over both).
4. **A refusal names it**: "C16 courtyard over the plated lead of J1 pad 2".

## Verification

- Pure tests, physical envelope: a capacitor searched near a terminal whose
  body would clear the lead but whose courtyard would cover it lands clear;
  the reverse, a terminal searched near a placed capacitor; a part's own
  lead under its own courtyard is allowed; a board with no plated leads is
  unchanged. Courtyard envelope: unchanged.
- Native and Python agree on each (a parity test).
- Bench (physical and union configurations may change where a lead is near
  a courtyard; each change named in the commit).

## Not in scope

- An unplated hole (`npth_inside_courtyard`): the same pattern, if a board
  needs it.
