# placemat studio: the 3D view

Date: 2026-10-03
Status: design, for the user's review
Source: the user, 2026-10-03, on the "3D (phase 3)" section of `2026-10-02-studio-design.md`: 3D uses the parts' real
models, loaded live, not KiCad's GLB export after a run. Each model is loaded once, converted to a mesh, cached, and
placed at each resolve's position, turn and face, so 3D follows the live 2D view: "it means we can do really cool stuff
like actually show a board being built in real time". A part with no model is shown honestly, not faked.

Builds on `2026-10-02-studio-design.md` (the studio, its replay timeline, its live channel). Nothing here changes what
placemat places or routes.

## Problem

The studio shows a board in 2D from the plan's shapes. A 2D view cannot say whether a connector faces the right way,
whether a tall part stands next to a short one, whether a part on the back sits under something on the front, or what
the board will look like built. KiCad's 3D viewer answers those, but only for a written board, and a run writes the
board late. The user wants to watch parts arrive in 3D as the layout resolves, step by step, with the parts' real shapes.

## Decided with the user

- 3D uses the parts' real models, loaded by placemat, placed from the plan at every resolve. Not a GLB exported after a
  run.
- The replay timeline works in 3D: parts appear step by step, then copper, and later the whole build including routing.
- No box-only view. A part with no model is shown as what it is: no model. How is set out in "Parts without a model".

## What exists today

| Fact | Where |
| --- | --- |
| A footprint's model entries are read as `(file, offset xyz, rotation xyz, scale xyz)`. The entry's hide flag and opacity are dropped. | `kicad/read.py:413` (`_models`), `board_geometry.Footprint.models` |
| A model path that does not resolve from the project's folder is re-anchored when a board is written: its tail is looked for in the project folder and each folder above it, up to the workspace. | `models.py` (`reanchor`), `kicad/write.py:1020` (`_reanchor_models`) |
| A second resolver for `${KIPRJMOD}`, environment variables and `KICAD<n>_3DMODEL_DIR` (hard-coded to `/usr/share/kicad/3dmodels`), trying a `.step` beside a `.wrl`. | `describe.py:533` (`_model_path`) |
| A port of KiCad's model transform, used by `placemat measure --models`: scaled, turned by the x, y and z angles negated, in the order x then y then z, then offset. | `describe.py:563` (`_model_xy`) |
| A plan item's members carry shapes already moved to the placed spot, and the item's own `at`, `rotation`, `face`. They carry no per-member placement and no models. | `preview_json.py:77` (`item_json`) |
| The page draws one SVG from the plan JSON, shows the first k placement steps (`showSteps`), and keeps one replay position (`S.replay`) for the slider, the step list and play. | `studio_page.html:615-633`, `1229` |
| The studio serves a fixed set of GET routes behind a token and a host check, streams events over SSE, and keeps a warm worker process as a child. | `studio.py:1122` (`_handler`), `studio.py:101` (`WorkerProcess`) |
| A board's stackup is not wrapped by pcbnew's Python on the installed build; copper thickness is read from the file text. | `kicad/read.py:34-59` |
| `kicad-cli` is already a runtime requirement (DRC, render). | `kicad/drc.py`, `kicad/write.py:848` |

Model entries across the 45 fixture boards (1301 footprints): 1403 entries, of which 932 are `kicad-embed://` (the model
file lives inside the board file), 168 are absolute paths into a user's library folder and 303 are
`${KIPRJMOD}`-relative. 1358 are `.step`, 6 `.STEP`, 39 `.wrl`. 8 entries have a non-zero offset, 75 a rotation, 7 a
scale other than 1. No entry is hidden and no footprint has more than one model. These are fixtures, not a census, but
embedded models are the common case and must be first-class.

## Design

### Overview

Three parts, each its own process or module:

1. **Resolution** (in the resolve worker, per resolve): for each placed part, find its model entries, resolve each to a
   file or an embedded file, give it a content id, and compute its placement matrix. Output: extra fields in the plan
   JSON.
2. **Conversion** (a separate converter process): turn each model not yet in the cache into a mesh file in a content
   addressed cache. Output: mesh files and `model` events.
3. **The viewer** (the page): loads each mesh once, draws one instanced mesh per model and material, places instances
   from the matrices, and shows the steps up to the replay position.

The page's 2D and 3D renderers share one state (the plan, the selection, the replay position, the compare). 3D is a
second renderer of that state, not a second view with its own.

### Model sources and resolution

A model entry is text plus offset, rotation (degrees, x y z), scale. Resolution gives one of: a file, an embedded file,
or a reason it has none.

Order, first hit wins:

1. `kicad-embed://<name>`: the file embedded in the footprint (`(embedded_files (file (name ..) (type model) (data
   |<base64 of zstd>|) (checksum ..)))`). pcbnew's Python on this build does not expose the embedded files (the
   `GetEmbeddedFiles()` object has no readable members), so the converter gets them by duplicating the footprint into
   a scratch board, which keeps them (measured: a fixture footprint duplicated into a new board and exported renders
   its embedded model). No decoding is needed, so no zstd library is needed either. A board stores the data once per
   distinct file: in the 258-footprint fixture board 10 footprint blocks hold `(data` and 184 list only the name and
   checksum, and the footprints without data still export their model after a `Duplicate` into an empty board
   (measured, 8 of 8). So the footprint is duplicated whole, from the loaded board, never rebuilt from the file text.
2. An absolute path.
3. `${KIPRJMOD}` and `$(KIPRJMOD)`: the project's folder, after the same re-anchoring the write step applies
   (`models.reanchor`), so 3D finds what the written board will find.
4. Another `${NAME}`: the process environment, then KiCad's own variables (`kicad_common.json`, `environment.vars`,
   null on this machine), then for `KICAD<n>_3DMODEL_DIR` and `KISYS3DMOD` the first existing of: the folder
   `../share/kicad/3dmodels` beside the real path of `kicad-cli`, `/usr/share/kicad/3dmodels`,
   `/usr/local/share/kicad/3dmodels`, the macOS bundle's `SharedSupport/3dmodels`, the Windows install's
   `share/kicad/3dmodels`, then the folders in the setting `studio_3d_model_dirs`.
5. A relative path: the project's folder.
6. A `.wrl` or `.wrz` path: the `.step`, `.stp` or `.STEP` of the same name beside it, when there is one. KiCad's own
   export does the same (`--subst-models`: "Substitute STEP or IGS models with the
   same name in place of VRML models"), and `describe._model_path` already does.

These replace `describe._model_path`, which becomes a caller of the same function (one resolver, in `models.py`).
`pcbnew.ResolveUriByEnvVars` exists, but called from a bare script it crashed the interpreter (exit 139), so it is not
used. Where KiCad resolves a plain relative path other than from the project's folder (the footprint library's
folder, say) is not verified here: KiCad's source is not on this machine. Step 5 is what is known to work for the
fixtures; the implementation reads KiCad's resolver before adding more.

A model's **id** is its content digest: for a file, the first 32 hex characters of the SHA-256 of its bytes (7 MB: 13
ms, measured), remembered by (path, mtime, size) in the worker; for an embedded model, `e-` plus KiCad's own checksum
field of the embedded file, which was identical for the same model in two different boards and does not equal the MD5
of its data or of its compressed data (checked), so it is used as a name for the content and not recomputed. The
cache key adds the converter's version and KiCad's major version.

Per model entry the plan carries a **state**: `ok`, `none` (the footprint declares no model), `missing` (not found; the
text as written is kept), `vrml` (VRML with no STEP beside it; read in phase 2),
`failed` (conversion failed, including an embedded model that did not export; the message is kept), `hidden` (the entry's hide flag), `loading` (not converted yet). The
hide flag and opacity are added to the model tuple read by `_models` (two more fields; `describe.model_check` unpacks four
today and is updated with it).

### Conversion

#### What can convert

A STEP model needs a CAD kernel to become a mesh. Measured on this machine (Python 3.12 system interpreter with
pcbnew 10.0.6; KiCad 10.0.6 with its model library of 7251 `.step` files, 3.2 GB):

| Option | Installed here | Size | Notes |
| --- | --- | --- | --- |
| `kicad-cli pcb export glb` on a scratch board that holds the models | yes (a placemat requirement already) | none added | Colours, tessellation and units are KiCad's. Reads STEP only; a VRML-only model comes out empty unless `--subst-models` finds a STEP. Needs a board file per batch. |
| OCP (`cadquery-ocp-novtk`) | in another project's tool environment (Python 3.14 only); not importable from placemat's Python 3.12 | PyPI wheel for cp312: 66.8 MB Linux x86_64, 63-68 MB macOS, 47.7 MB Windows; 159 MB package plus 95 MB of bundled libraries unpacked (measured in the other environment) | Fast, tessellation under our control, per-face colours. Bindings licensed Apache-2.0 (PyPI metadata); the bundled OpenCASCADE libraries' licence is not checked here. Needs Python <3.15. |
| `cadquery-ocp` (with VTK) | in uv's cache, Python 3.12 builds | pulls `vtk` as a hard requirement; the import failed here for want of a VTK library | Not worth it over the `novtk` build. |
| System OpenCASCADE libraries | `libocct-*` 7.6.3 are installed (KiCad needs them) | already there | No Python binding installed; calling C++ through ctypes is out. |
| FreeCAD, `trimesh`, `assimp`, `gmsh`, `pythonocc` | none installed | | `trimesh` does not read STEP by itself; the others are larger than OCP. |

Timing, STEP to mesh. OCP, linear deflection 0.05 mm, angular 0.5 rad, colours read; "read" is STEP parse and
transfer, which dominates. Triangle counts do not change with 0.01 mm deflection (13480 against 13464 for the
100-pin QFP) because the faces are planes and cylinders.

| Model | STEP size | OCP read | OCP mesh | Triangles | kicad-cli GLB, one model (wall) |
| --- | --- | --- | --- | --- | --- |
| 0402 resistor | 41 KB | 0.09 s | 0.01 s | 276 | 0.66 s (export 0.18 s), 180 triangles, 18 KB |
| SOIC-8 | 125 KB | 0.20 s | 0.03 s | 1184 | 0.87 s (0.36 s), 1180 triangles, 105 KB |
| QFN-48 with pad | 539 KB | 0.47 s | 0.09 s | 3592 | |
| 1x20 pin header | 724 KB | 0.48 s | 0.06 s | 1444 | |
| USB-C plug | 767 KB | 0.53 s | 0.06 s | 3044 | |
| LQFP-100 | 1.3 MB | 1.83 s | 0.26 s | 13464 | 4.1 s (3.57 s), 13412 triangles, 1.16 MB |
| PQFP-256 | 3.4 MB | 4.42 s | 0.48 s | 34526 | |
| 2x8 header (user library) | 7.1 MB | 2.52 s | 0.31 s | 10648 | |
| TF card socket (user library) | 7.1 MB | 3.24 s | 0.29 s | 33329 | |

OCP's import took 0.9 to 2 s, and the process peaked at 427 MB resident over the ten models.

The models of one real fixture board (258 footprints, 247 model entries, 62 distinct file names; 20 of them are on this
machine by name, 197 of the entries): converted by OCP in 10.1 s in one process, by one `kicad-cli` batch (one scratch
board holding all 20, one export) in 13.1 s, giving 3.1 MB of GLB and 37k vertices. 105,604 triangles if every
instance is drawn (42,184 distinct). A batch of five models took 7.7 s against about 3.1 s of OCP time, so `kicad-cli`
is roughly 1.3 to 2.5 times slower than OCP and adds 0.3 s of start-up per invocation, which a batch pays once. In a
batch, KiCad names each footprint's node by its reference and each mesh by its model's file name, so a batch can be
split back into models.

VRML, parsed in Python with the standard library plus a regular expression (a prototype, not placemat code): 17.9 KB
file, 3 ms, 474 triangles; 57 KB, 9 ms; a 2.6 MB file, 0.19 s, 82,036 triangles; a 3.1 MB file, 0.26 s, 101,877
triangles. The unit is 0.1 inch (a 0402 model measures 0.394 by 0.201 raw and is 1.00 by 0.51 mm after the factor
2.54). VRML meshes are 2 to 6 times denser than the STEP model of the same part (82,036 against 13,464 triangles for a
48-pin QFP, from different libraries), so they need the decimation below.

#### Recommendation

**Convert with `kicad-cli` in a separate converter process. Add no Python dependency.** Reasons: KiCad is already
required, so the view adds nothing to install; the mesh, colours and units are KiCad's, which is what the user compares
against; the cost over OCP is speed, 1.3 to 2.5 times, paid once per model per machine because of the cache; and it
needs no kernel in placemat's own interpreter. The cost to weigh against: each batch writes a scratch board and starts
KiCad, and `kicad-cli` is a binary placemat does not control (flags changed between releases; KiCad 10.0.6 is what was
measured).

If `kicad-cli` is not found, the 3D tab says so in one line ("3D needs kicad-cli on the path, or set
`studio_3d_kicad_cli`") and the tab shows the board and the no-model plates with that message instead of waiting for meshes. The 2D view is unaffected.

If measured conversion speed turns out to matter (a first open of a board with a hundred distinct large models), OCP is
the optional accelerator: `placemat[model3d] = cadquery-ocp-novtk`, imported lazily in the converter only, used when
present, with the same output format. That is a later step, not part of this spec's phases.

The converter is its own process for three reasons: the studio server and the page stay responsive while a batch runs
(the longest batch measured was 13 s); a `kicad-cli` or pcbnew failure in it cannot take the resolve worker down (the
project instructions record that pcbnew's bindings have broken for the rest of a process after item removal; the
converter only ever adds items to scratch boards, using `Duplicate` and `Add`, never `Remove`); and its CPU use can be
bounded. It follows `WorkerProcess` (JSON lines on stdin and stdout, a `ready` event, killed by its handle when the
studio stops). Nothing is killed by name or pattern.

#### The batch

Input: a list of `{id, kind, file | (board, ref)}`. The converter:

1. Takes the ids not in the cache and not in the failure cache, in the order the plan placed them, in batches of
   `studio_3d_batch` (default 8), one batch at a time. The batch size is the progress granularity; a batch of one costs
   0.3 s more than its export.
2. Writes a scratch board with one footprint per model, each at a distinct spot, front, orientation 0, model entry
   offset 0, rotation 0, scale 1. A file model is a new `FP_3DMODEL` with the resolved absolute path; an embedded model
   is the real footprint duplicated, with its model entry reset to identity. The scratch board has the default
   stackup, 1.6 mm.
3. Runs `kicad-cli pcb export glb --force --no-board-body --user-origin 0x0mm`, with a timeout (`timeout_render` is
   the setting that exists for the render; this gets its own, `studio_3d_batch_timeout_s`).
4. Reads the GLB with `struct` and `json` (no numpy), one node per reference, and rewrites each model's vertices from
   KiCad's export frame into the **model frame**: x right, y up the footprint's page, z up out of the board, metres to
   millimetres, and the board's model plane (1.595 mm in the scratch board) subtracted from z. Measured: with the
   scratch board at identity the export has x = model x, export z = -model y, export y = model z + 1.595.
5. Writes one mesh file per id (below) to the cache, emits a `model` event per id, and records a failure per model that
   is missing from the output, with a retry of that one alone (a bad model must not fail its batch).
6. At start-up, a self-test: one known model on a front and a back footprint; the planes must be 1.595 and -0.085 mm
   and their difference 1.68 mm. When not, the converter refuses and says which KiCad it found. This catches a KiCad
   release that moves the plane, which would shift every part in z.

Decimation: a mesh over `studio_3d_model_tris` (default 30000) triangles is simplified by vertex clustering at
conversion, with the grid grown until it fits. The STEP models measured are under that (34,526 is the largest; the
cap is what VRML models and unknown future models need). It is applied once, so the cache holds the drawn mesh.

### The mesh file and the cache

**Location.** A user cache folder shared by all projects: `$XDG_CACHE_HOME/placemat/models`, else
`~/.cache/placemat/models`; `~/Library/Caches/placemat/models` on macOS; the local app-data folder on Windows;
overridable by `studio_3d_cache_dir`. The key is a content digest, so a part library's models are converted once for
every board that uses them, and the cache survives `.placemat/` being deleted. This is the first place placemat writes
outside a project; it is open question 3.

**File.** `<id>.pmm`: a small binary format of our own, not GLB, because the converter has to read GLB to split a
batch anyway and a custom reader in the page is about 40 lines against three.js's 118 KB GLTFLoader. Layout: an 8-byte
magic and version, a JSON header (the model's bounding box in the model frame, the number of triangles before and
after decimation, the converter version, and per material: its colour as sRGB, its opacity, vertex count, index
count), then per material positions as float32 x3, normals as float32 x3 and indices as uint32 (uint16 when under
65536 vertices). About 40 bytes per triangle: a 0402 is about 7 KB, a 100-pin QFP about 0.55 MB. Normals come from
KiCad's export (its mesh splits vertices at sharp edges).

**Failures.** `<id>.fail`: the message and the converter version. Not retried until the version changes or the user
presses Retry in the 3D legend.

**Invalidation.** The converter version is in the key and in the file name's prefix (`v1-<id>.pmm`); a new version
ignores old files and removes them at start-up. Nothing else invalidates an entry: a file model's id is its content.

**Bounds and cleanup.** `studio_3d_cache_mb` (default 512; about a thousand average models). Each use touches the file's
mtime. At start-up and after each batch, when the folder is over the bound the least recently used files are deleted until it
is 20% under. The converter never deletes a file it was told is in use by the current plan. Writes go to a temporary
name and are renamed, so a reader never sees half a file and two studios can share the folder.

### Placement

The goal is the same pose KiCad's 3D viewer gives, measured against `kicad-cli` and not assumed.

**Two steps, both exact.**

*Step A: the model on the footprint as the generator left it.* The part as read from the generated board has a
location, an orientation (`Footprint.rotation`) and a face (`Footprint.face`); its model entry has offset `o`, rotation
`r`, scale `s`. For a model-frame point `v`:

1. `p = Rz(-r_z) Ry(-r_y) Rx(-r_x) (s * v) + o`: scale, then turn about x, then y, then z by the angles negated, then
   offset. This is the order `describe._model_xy` already uses.
2. The footprint's page (y down): on the front `q = (p.x, -p.y)`; on the back `q = (p.x, p.y)`. Height above the
   part's own face: `p.z`.
3. Turn `q` by the orientation `theta`: `(q.x cos(theta) + q.y sin(theta), -q.x sin(theta) + q.y cos(theta))`, and
   add the footprint's location.
4. Height in the scene: front `plane_front + p.z`, back `plane_back - p.z`.

*Step B: the plan moves the part.* The plan's own transform (`occupancy._transform`: translate away from the reference
location, mirror about the vertical axis when the face changes, rotate, translate to the target) is what moves its pads
and courtyard. Models take the same transform in x and y, and when the face changes, the height flips about the board:
`z' = plane_front + plane_back - z`. So the model and the pads move together by construction; there is no second
orientation convention to keep in step with the write step's (`_place_footprint` sets `target.rotation + 180` after a
flip and `target.rotation` otherwise, which is why 3D does not recompute a KiCad orientation from a Placement).

The worker composes A and B per model entry into one 4x4 matrix from the model frame to the **scene frame**, and sends
that. The scene frame is glTF's and KiCad's export's: x = board x, y = up, z = board y (down), so a camera looking down
with up = -z shows the board as the 2D view does. The page applies the matrix and never reimplements the chain; the
chain exists once, in Python, where it is tested.

**Planes.** With a board of stackup thickness T, KiCad's export puts the front model plane at `T - 0.005` mm and the
back plane at `-0.085` mm (measured: T = 1.6 gives 1.595; T = 0.8 gives 0.795; the back is -0.085 for both and for the
six-layer fixture board; KiCad's own body in that export is T - 0.09 thick). The scene's board body is drawn from 0 to T. The constants are
named, with this citation, in one place. Whether KiCad's interactive 3D viewer uses the same planes as its exporter is
not verified (its source is not on this machine); the test below measures the exporter, and the implementer reads the
viewer's source before treating a 0.09 mm difference as settled.

**Verification, done for this spec.** KiCad 10.0.6, `kicad-cli pcb export glb`, vertex by vertex, in mm:

- A 1x20 pin header (asymmetric) on a one-footprint board, at (100, 80) with orientation 30, -50 and 0, with offsets,
  all three model rotations (including 30/20/70) and a scale of (2, 1, 0.5): front, four cases, maximum difference
  1.5e-8 mm.
- The same on the back, four cases (orientation 0, 30, 30 with offset and rotation, -50 with a general rotation): the
  back mapping above, maximum difference under 0.0001 mm in x and y (the alternative, mirroring x, is off by up to 48 mm), with the
  height a constant -0.085 mm below the formula's own zero, which is the back plane.
- Pad positions in pcbnew for a flipped footprint (three pads, orientation 0, 30, -50) equal the model chain's points
  for the same three library positions, so models and pads agree.
- Two real fixture boards, every footprint with one model that has a non-trivial model entry or is on the back, up to 14
  per board: 7 of 7 on the 7-footprint board (orientations 90, 180, -90, front), 14 of 14 on the 258-footprint
  six-layer board (back side, orientations 0, 90, 180, -90): every vertex within 1 um in x and y, height planes 1.595 and
  -0.085.

The fixture comparisons used the footprint's final KiCad pose, not placemat's plan, so what is not yet verified is
step B: that placemat's plan transform places the model where the written board does. That is the end-to-end test
below.

### The board

From the plan document:

- **Body.** The outline loops (`board.loops`) extruded from 0 to T, T from the stackup (the board file's thickness; the
  worker reads it once per resolve, as `read_outline` does). The outermost loop is the edge, the others are cutouts
  (the same rule `_cutout_loop` uses). Holes through the body: vias' drills (`copper` ops of type `via`), through pads'
  drills and mounting holes (item shapes `hole`, `npth`). three.js's `ExtrudeGeometry` takes holes in its shape, so the
  body is one shape with its holes; no boolean library.
- **Copper**, phase 2: each copper layer a thin slab at its stackup height with the layer's thickness from the board
  file's stackup (`read.stackup_copper_mm`): track ops as boxes (one `InstancedMesh` of a unit box, scaled and turned
  per track; arcs as short chords), vias as rings and drill, pours and planes as the plan's polygons, pads from the
  items' `pad` and `through` shapes. Copper that is not yet laid is not drawn. The pour polygons are the plan's
  fitted shapes, not KiCad's filled zones, as in the 2D view.
- **Silk and mask**, phase 2 and later: silk from the items' `silk` shapes as flat polygons just above the face. Mask
  is not in the plan document and is a later addition with the checked run's data.
- **Colour.** Body, copper, mask and silk colours come from the page's theme tokens (light and dark), not from the
  stackup.

### Parts without a model

A part whose model state is not `ok` is drawn from its **courtyard polygon** (the plan's `courtyard` shape, already in
the part's placed spot), extruded 0.1 mm off its face, faint, with a dashed outline in the 2D view's courtyard colour,
and flagged. It is not given a height: nothing in the plan says how tall the part is, and a guessed height is a fake
model. The state is shown as text on the plate and in the card ("no model declared", "model not found:
<path as written>", "VRML only, not read yet", "conversion failed: <message>", "loading").
`loading` plates pulse faintly and become the part when its mesh arrives. The legend counts parts by state, lists the
ones without a model, and has a toggle that dims every part with a model so the plates stand out. A part with a
courtyard missing too is a point marker with its reference.

### The viewer

**Library.** three.js, vendored, not loaded from a CDN: the studio is a local tool and is also opened on a phone over
the LAN (`allowed_hosts`), where a CDN may be unreachable; and the studio spec already requires vendored JavaScript to
be MIT with its licence beside it. Version 0.186.1 (npm metadata: MIT). Files: `three.module.min.js` (393 KB, 90 KB
gzipped), `three.core.min.js` (416 KB, 104 KB), `OrbitControls.js` (41 KB, 8 KB): about 850 KB in the package, under
`src/placemat/vendor/three/` with `LICENSE`, served at `/vendor/three/<file>`, token required. It is loaded with a
dynamic `import()` when the 3D tab is first opened, with an import map for the bare `three` specifier, so a user who
never opens 3D loads none of it. `GLTFLoader` (118 KB) is not needed. A CDN is the alternative if the repository size
matters more (open question 2).

**Scene.** One `WebGLRenderer` on a canvas that replaces the SVG in the board area (a 2D | 3D switch beside the face
selector; the legend, step list, cards and replay bar are shared). Scene frame as above. Lights: a hemisphere light and
one directional light, no shadows by default. Background, body, copper and plate colours are read from CSS variables
at theme change, so light and dark follow the page.

**Draw cost.** One `InstancedMesh` per (model, material): the fixture board above has 20 distinct models of about three
materials each, so about 60 draw calls for 197 parts, and 105,604 triangles in all. Tracks and vias are one instanced
mesh each. Instances of a model are ordered by the step that placed them, so the first k steps are a count, not a
rewrite. Budget settings: `studio_3d_model_tris` (30000 per model, above), and `studio_3d_max_tris` (default 4,000,000
drawn; past it the page shows the parts as plates and says so, rather than dropping frames). The frame rate has not been
measured: no browser was run for this spec. The implementation measures a mid-range laptop and a phone on the 258-part
board and records the numbers in the commit.

**Controls.** Orbit with one finger or the left button, pan with two fingers or the right button, zoom with the wheel or
a pinch (three.js `OrbitControls`; the board takes the gestures and the page does not scroll, as the 2D view does).
Double tap or a Fit button fits the board. Buttons: Top, Bottom, Iso; a double tap on a part selects it. Top and Bottom
look straight down and up with the 2D view's orientation (Bottom mirrored, as the 2D back is). A part's click selects it
(a ray against its instance's bounding box, then its triangles); selection, hover card, findings and the card are the
page's existing ones, driven by `S.sel`/`S.selRef`; a selected part gets an outline edge and the rest fade, as in 2D.
Findings that carry a place get a marker ring that keeps its screen size.

### Live and replay

**Plan data.** `plan_json` and the streamed `item` event (both come from `item_json`) gain, per member: `models`, a list
of `{id, state, name, matrix, opacity}` (the 16 numbers of the placement matrix, column-major, millimetres, rounded to
10 micrometres: about 250 bytes per model entry, 60 KB for the 258-part fixture); and the plan gains `stackup`
(`{thickness, copper: {layer: mm}}`) and `models`, the table of distinct ids with `{name, source, bytes, state,
message}`. All additive; `VERSION` goes to 2 and the page tolerates a plan without them. The matrix is computed in the
worker from the member's generator placement (`Footprint.location, rotation, face`), the item's plan transform (the
one `_drawn_at` already builds) and the stackup, and the id from the resolver.

**Following 2D.** The 3D renderer implements what the 2D one does: draw(plan), `showSteps(k)`, marks, fit. It registers
every object with its step number, as `indexBoard` does for the SVG groups (`byStep`), and `showSteps(k)` sets
visibility for the objects between the old and the new position, so dragging the slider, the step list and play work
unchanged and stay in step with the 2D view. A streamed `item` adds its parts as it arrives, the way 2D adds groups, so
a resolve is watched being built: parts appear as their steps settle. A part appears with a short drop-in and fade
(`studio_3d_appear_ms`, default 200; none while replaying unchanged steps, which the 2D view also draws without
animation, and none for a replay step jump, only for a play or a live arrival).

**Compare.** For a moved part the 3D view draws the part at its new place and a translucent ghost of the same model at
the old place from the earlier resolve's matrix, with a line between them; added and removed parts are marked as in 2D.
It reads the same `S.cmp.diff`.

**The live channel.** Another command's resolve (run, preview, explore, route), opened in the Runs view, reaches the page
as `item`/`board`/`plan` events whose items come from `item_json`, so its parts come with models and matrices with no
second implementation, and opening it in 3D shows that command's build. The studio resolves model ids for such items
itself from the paths in the event (the events carry the text and the matrix, not a trusted id), queues unconverted
ones for the converter, and answers with `model` events. An explore's variants (the focused items drawn again where a
variant put them) are drawn as ghosts, in phase 2, from their placements through the same function.

**Routing replay.** Copper steps already carry their ops (`step_extras`) and the page already indexes them by step
(`opStep`). When routing arrives as steps later (a `route` run's tracks and vias as copper steps), 3D draws them as
they arrive, in phase 2's copper layers, with no new data. The part to design then is how a long route is paced in the
replay bar, which is the 2D view's question too.

### Data and APIs

Structured data only; the page never parses a path or a sentence.

- `GET /3d/models`: the table of model ids to `{state, tris, bbox, colours, message}` (a catch-up, also sent in `hello`).
- `GET /3d/model/<id>.pmm`: the mesh file. The id is validated as 32 hex characters, optionally `e-` plus 32; nothing
  from the client is used as a path. `Cache-Control: immutable`, `ETag` the id, because the id is content.
- SSE: `model` events `{id, state, tris, message}` as conversions finish or fail, and `models` progress
  `{done, total, current}` for a batch.
- `GET /vendor/three/<file>`: the vendored library, from a fixed list.
- `POST /3d/retry` `{id}` (or all): clears the failure cache and requeues.

All behind the studio's existing token and host check. The converter reads files the plan names (model paths from the
board and the footprint library), which is what the resolve already reads; the client cannot name a path.

### Settings

All in `[studio]`, documented as data like the others (name, default, unit, one line): `studio_3d_kicad_cli` (path,
default found on PATH), `studio_3d_model_dirs` (extra model folders, `os.pathsep`-separated), `studio_3d_cache_dir`,
`studio_3d_cache_mb` (512), `studio_3d_batch` (8), `studio_3d_batch_timeout_s` (120), `studio_3d_model_tris` (30000),
`studio_3d_max_tris` (4000000), `studio_3d_appear_ms` (200), `studio_3d_plate_mm` (0.1). Each name is added to the
validation set that checks every setting name.

### Charter fit

It serves the purpose by showing the plan's result as it is made, and judges nothing: no placement, copper or check
changes. It is project-agnostic: models come from the footprints; nothing names a board, a part or a library. Its
tunables are settings. It adds no script form. KiCad is the reference for the transform and the mesh, and the
transform is measured against KiCad rather than assumed. A part without a model is not given invented geometry. It adds
no Python dependency and no network use. The one thing outside the project it writes is the model cache, which is the
user's own cache folder.

## Phases

1. **Placed models, live.** Resolution, the converter and the cache, the vendored viewer, the board body with outline,
   cutouts, drills and thickness, parts at their matrices, plates for parts without a model, the controls, selection
   and cards shared with 2D, light and dark, touch, the replay position, live arrival of parts, and the models
   legend (counts by state, retry). Useful alone: it answers "what does this board look like built" and shows the build
   live, with parts appearing step by step. The 2D view is unchanged without it.
2. **Copper and the rest of the build.** Tracks, vias, pours, pads and silk as copper layers appear in the replay;
   VRML models (parser, decimation); the compare ghost; findings markers; explore variants as ghosts; the
   `measure --models` checks (model off its pads, turned 90) on the part card.
3. **Routing replay and finish.** Route steps in the replay, solder mask from a checked run, the OCP accelerator if
   conversion speed asks for it, runs from finished records opened in 3D.

## Out of scope

- Editing by dragging a part in 3D (a coordinate; the charter forbids it, as for 2D).
- KiCad's GLB export after a run as a view (the user decided against it); no ray tracing, shadows by default, or
  physically based rendering.
- Height or collision rules from the models. The meshes make part heights known, which could feed a rule later; that is
  a new rule and is specced when asked for.
- Authoring or fixing models, STEP export, model search or download.
- Remote access beyond what the studio already allows.

## Testing

- **A generic known-transform model.** An L-shaped prism STEP file, 4 x 2 x 1 mm with a 2 x 1 mm notch, written once and
  checked in under the tests' data folder (under 10 KB; an asymmetric shape, so a mirror or a swapped axis shows). No
  fixture names a project, a part or a net.
- **Placement, pure.** The matrix for a part at a position, orientation, face and plan transform, with a model offset,
  rotation and scale, against hand-computed corner positions of the prism; front and back; a part the plan flips and
  one it does not; the stackup planes. No KiCad needed.
- **Placement against KiCad.** Gated on `kicad-cli` being present: build a board from a plan with the prism on both
  faces at several orientations and model offsets/rotations/scales, run `kicad-cli pcb export glb`, and compare every
  vertex of each part with the matrix applied to the cached mesh, to 1 um. Run on the written board of a plan, so step
  B (the plan's transform against what the write step writes) is covered. The probe that produced this spec's numbers
  is the starting point; it ran on `kicad-cli` 10.0.6.
- **Two fixture boards**, as measured above, as a test that skips when a fixture's models are not on the machine, since
  most fixture models are absolute paths into a user's library or embedded.
- **Resolution.** A temporary project tree: `${KIPRJMOD}` with and without re-anchoring (agreeing with
  `models.reanchor`), an environment variable, a KiCad variable default, an absolute path, a relative path, `.wrl` with
  and without a STEP beside it, an embedded model, a missing file, a hidden entry; each gives its
  state and id. A renamed file keeps its id.
- **Cache.** A write is atomic (a reader during a write sees the old state); the version prefix ignores and removes old
  files; the size bound removes least recently used files first and not ones in use; a failure is not retried until
  Retry or a new version; two processes share the folder.
- **Converter.** A batch with one bad model: the others convert, the bad one fails alone. `kicad-cli` absent: one
  message, no traceback. Timeout: the batch fails as a unit and is split. The self-test refuses on a wrong plane.
  Decimation: a mesh over the cap ends under it, with its bounding box kept to within one grid cell.
- **Plan document.** The additive fields appear, `VERSION` is 2, a plan from an older worker still draws, and the
  document stays deterministic for the same plan.
- **Page.** The visible set at step k as a pure function of the plan and k (the 2D function and the 3D one agree on the
  same plan); selection and card parity with 2D. The page has no browser tests today; the draw-call and triangle counts
  and a frame-rate figure on a laptop and a phone are measured by hand on the 258-part fixture board and put in the
  commit message.
- **Cost.** The extra resolve work (model resolution, hashing, matrices) is timed on the large fixture board against
  the same resolve before the change, and the figure reported in the commit; the converter runs one batch at a time, so
  it holds one core and a full test suite or bench is not run beside it.

## Open questions

1. **Dependency.** Convert with `kicad-cli` only, as recommended: no new Python dependency, 1.3 to 2.5 times slower than
   OCP and 0.3 s per batch, once per model per machine. Is that the right trade, with OCP (about 67 MB to download, 254
   MB installed, an optional extra) kept for later if conversion speed bothers you?
2. **three.js: vendored or CDN.** Vendored is about 850 KB in the repository (MIT, licence beside it) and works offline
   and on a phone over the LAN; a CDN costs nothing in the repository and needs the internet. Vendored is
   recommended. OK?
3. **Cache location.** A shared user cache (`~/.cache/placemat/models`, 512 MB bound) is the first place placemat writes
   outside a project, chosen so models are converted once for every board. The alternative is `<project>/.placemat/`,
   per project, converting again for each. OK to write to the user cache?
4. **Parts without a model.** A 0.1 mm courtyard plate, faint, flagged "no model" with its reason, and no invented
   height. Is a plate right, or do you want a visibly different treatment (outline only, hatching)?
5. **VRML-only models in phase 1.** In the fixtures 39 of 1403 entries are VRML and some have no STEP beside them. Phase
   1 marks them "VRML only, not read yet" and phase 2 reads them. Do you want them in phase 1?
6. **Where 3D sits.** A 2D | 3D switch that replaces the board area (one state, shared legend and replay bar), as
   specced, or a side-by-side split on wide screens showing both at the same replay position?
