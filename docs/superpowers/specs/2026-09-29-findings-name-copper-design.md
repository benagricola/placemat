# Findings that name the copper they measured

Date: 2026-09-29
Status: approved 2026-09-29 (Ben: implement unless a decision is needed)
Source: a board's PLACEMAT_GAPS.md, 2026-09-28 "which copper a keep-out or
current-path check measured" and "the usb5v cell's copper by net, and where a
chamfer cut" (part 2)

## The problem

- **Keep-out check:** `check keep-out` (`checks.keep_out`) gives a distance
  and the list of sensitive nets. It doesn't say which two pieces of copper
  set the distance, or that both are pads of one part: a distance the
  footprint sets and no placement changes.
- **Current-path check:** `check current-path` gives a route's ends and its
  narrowest width. It doesn't give where the neck is or how long it is. A
  temperature-rise width is a long-track figure, and a short neck between
  large copper heats little.
- **Copper clearance finding:** it names two nets and a point, not the
  segment. When the leg is a chamfer's cut that came within clearance, it
  doesn't say so.

## The change

1. **The keep-out verdict names its two items and points.** For example:
   "SW_5V to FB_5V 1.27 mm: U3 pad 5 (SW) at (x, y) to U3 pad 9 (FB) at
   (x, y); both pads of U3, a distance its footprint sets". A track or via
   is named by net and ends. `--json` carries the same fields.
2. **A current-path verdict gives its neck** as a point and a length along
   the route: "narrowest 1.47 mm at (x, y), 0.9 mm long". The length is how
   far the route stays within 10% of the narrowest width, measured along the
   copper the widest route passes. Where the neck is a zone fill (not
   measured), it says so as now.
3. **A copper clearance finding names the segment** by its ends and layer.
   When that segment is a chamfer cut of a declared track, it says so: "the
   45 of its chamfer at (x, y); a smaller `chamfer=` there keeps clear".
4. **Docs**: api.md's check and finding paragraphs.

## Verification

- **Keep-out:** a synthetic board where a switch pad and a sense pad of one
  part set the keep-out: the verdict names both pads and says the footprint
  sets it. With a track instead, it names the track.
- **Current-path:** a synthetic route with a 2 mm long neck: the verdict's
  point lies on the neck, and its length is 2 mm within one grid step.
- **Chamfer:** a declared track whose chamfer cuts within clearance of a
  foreign pad: the finding names the chamfer segment and says to reduce
  `chamfer=`.
- The existing check and finding tests pass or change where they assert the
  old wording (listed in the commit).
