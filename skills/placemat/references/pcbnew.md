# pcbnew itself

Below placemat: the KiCad API's own behaviour. You need this when changing
placemat, or when something it does is surprising and the cause is underneath
it. Writing a layout script needs `references/api.md` instead.

KiCad 10 API unless noted.

## KiCad 10 API gotchas

- `SHAPE_POLY_SET.BooleanAdd(b)` / `.Simplify()` take NO mode argument (no
  `PM_FAST`).
- `PAD.GetPos0()` is gone - use `GetFPRelativePosition()`.
- Text bounding: use `GetBoundingBox()`; `GetTextBox()` needs a settings arg.
- `PCB_SHAPE.SetNetCode()` exists - a gr_poly can carry a net. Use it.
- `SetOrientationDegrees(90)` sends a footprint's local +x pad UP (-Y); 270
  sends it DOWN.
- `PAD.GetSize()` is in the pad's LOCAL frame - a pad rotated inside its
  footprint has its long axis swapped in world space. For world extents
  (clearance/gap measurements) always use `GetBoundingBox()`.
- Removing items: collect `list(b.GetTracks())` AND the drawings list BEFORE the
  first `b.Remove()` - the SWIG drawings proxy can break after removals.
  "memory leak ... no destructor" warnings on removal are harmless.
- Net format: KiCad 10 pads are `(net "NAME")` name-only; the KiCad-9 net-code
  table is gone and KiCad 10 rejects it.
- `PCB_GROUP.Move()`/`.Rotate()` themselves can also become unreliable deep in
  a long script session. Treat the whole PCB_GROUP transform API
  as untrusted: move/rotate MEMBER footprints individually and compute boxes
  as member unions.
- `PCB_GROUP.GetBoundingBox()` goes STALE immediately after `.Rotate()` in the
  same session: it returns a box that does not reflect the new member
  positions, and stays wrong across repeated same-session queries (it is not
  a one-off timing fluke). Verified by hand-computing each member footprint's
  true rotated bbox from its actual pos/rotation (matches reality, and
  survives save/reload) and finding it disagreed with the group-level call
  until a save+reload round-trip forced a recompute. Symptom: board-level
  stacking/spacing code that reads `group.GetBoundingBox()` right after
  rotating produces systematically wrong sizes and gaps that only show up
  once you inspect the saved file, not in the same session. Fix: compute a
  group's box yourself as the union of its member footprints' own
  `GetBoundingBox()`, and pivot `.Rotate()` on that computed centre too -
  never trust `PCB_GROUP.GetBoundingBox()` in the same session a rotation
  happened to that group.


## 3D models and renders

- 3D models: `pcbnew.FP_3DMODEL()` (KiCad 10 name), `m.m_Filename = path`,
  `fp.Models().push_back(m)`. A render-only dummy footprint works:
  `fp = pcbnew.FOOTPRINT(board)`, SetReference, SetPosition, attach the model,
  `board.Add(fp)`, mark it excluded from BOM and position files.
- Stackup colours are not exposed through the Python bindings; edit the
  `(stackup ...)` block in the board file directly.
- Renders: `kicad-cli pcb render --side top --background opaque --quality high
  -o layout.png board.kicad_pcb`; isometric with `--rotate "-60,0,45" --zoom
  0.9`; `--side bottom` whenever both faces carry parts.
- Vias and through-hole pads are holes through the whole board: on a
  two-sided population, collision-check them against both faces' content
  systematically, not per DRC hit.
