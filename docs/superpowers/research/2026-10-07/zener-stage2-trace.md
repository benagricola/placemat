# Zener fork: nets.layout.json stages 1 and 2

Read-only trace of the Zener fork at ~/work/pcb, branch `feat/netclass-nets-field-0.4.52`, HEAD d2b9f749.
Paths are relative to ~/work/pcb unless absolute. Nothing was changed. The only thing run was the installed
`pcb` on a two-line scratch file, to see how a `Length` prints (see "Value formatting").

The prior survey (docs/superpowers/research/2026-10-06/zener-net-export.md) still holds at this HEAD. Its line
numbers are within one or two lines; corrected numbers are used below.

## Stage 1: type and fields

### Where the sidecar is written

- `process_layout` (crates/pcb-layout/src/lib.rs:661) writes `default.net` at lib.rs:705-707, then the JSON netlist
  for the Python sync at lib.rs:714-721, then runs the sync (lib.rs:762). The sidecar write belongs after
  lib.rs:707, from the same `&Schematic`.
- Paths come from `utils::get_layout_paths_for_pcb` (lib.rs:899-912) into `LayoutPaths` (lib.rs:92-100). Add
  `nets: layout_dir.join("nets.layout.json")` there, and a `nets_file` field on `LayoutResult` (lib.rs:44-53),
  filled at the two constructions (lib.rs:641-650 for `--check`, lib.rs:794-803 for a normal run).
- The `--check` path (`check_layout_sync`, lib.rs:600) writes no files and should not write the sidecar.
- Board net names are the `Schematic.nets` keys: `to_kicad_netlist` emits `(name ...)` from them
  (crates/pcb-sch/src/kicad_netlist.rs:89-92, :370-375), and the Python sync reads `data["nets"]` keys
  (crates/pcb-layout/src/scripts/update_layout_file.py:337). Keying the sidecar by the same key matches the board.

### What Net.kind and properties hold

- `pcb_sch::Net` (crates/pcb-sch/src/lib.rs:548-555): `kind: String`, `id`, `name`, `ports`,
  `properties: HashMap<Symbol, AttributeValue>`. `Schematic.nets` is keyed by the final name (lib.rs:756-758).
- `kind` is the net type name: `NetValue.type_name` (crates/pcb-zen-core/src/lang/net.rs:200), via
  `net_kind_name` (net.rs:428), set in `update_net` (crates/pcb-zen-core/src/convert.rs:664-669) and from the
  module registry (convert.rs:641-642). Open nets are "NotConnected". A custom `builtin.net_type("X")` gives "X".
- `properties` are the net type's fields, inserted at `NetTypeGen::instantiate` (net.rs:807-827), plus
  `symbol_name`, `symbol_path`, `__symbol_value` and a symbol format version for typed nets with a symbol
  (net.rs:829-852), plus `differential_impedance` pushed onto DiffPair P/N nets at conversion
  (convert.rs:1174-1222). They are copied to `NetInfo` at convert.rs:693-699 and onto `Net` at convert.rs:313-315.
- `AttributeValue` (crates/pcb-sch/src/lib.rs:475-482) has no physical variant. A `PhysicalValue` becomes
  `AttributeValue::String(physical.to_string())` (convert.rs:1238-1239).

### Value formatting

`Length("0.5mm")` prints as `500um`, `Length("2mm")` as `2mm`, `Voltage("48V")` as `48V` (checked with the
installed pcbc 0.4.52). A string field therefore carries an SI-prefixed display value. The sidecar should parse
these back with `PhysicalValue::from_str` (crates/pcb-sch/src/physical.rs:1084) and write numbers (clearance in
mm, voltage in V, impedance in ohm), so placemat does not parse unit strings. Symbol properties should be left out.

### The stdlib net types and where `clearance` goes

- The net types are in lib/std/interfaces.zen:3-26: `Net` (symbol, voltage, impedance), `Power` (symbol,
  voltage), `Ground` (symbol, voltage default 0V), and `Analog`, `Pwm`, `Gpio` with no fields.
- `clearance=field(Length | None, default=None)` goes on each type that should carry it, with `Length` loaded
  from units.zen (lib/std/units.zen:6). Line 1 of interfaces.zen loads only `Voltage` and `Impedance`.
- Rust also needs a change: `builtin_optional_net_fields` (crates/pcb-zen-core/src/lang/net.rs:92-98) lists, per
  type name, the fields whose unset value reads as `None` and is not stored (net.rs:104-110, :242-260, :812-826).
  Without an entry, `clearance=None` is stored as a property, and an unset clearance is not exposed as `None`
  the way `voltage` is (commit 02759196 made that change for voltage). Add "clearance" to Net and Power and a
  Ground entry, and to Analog/Pwm/Gpio if they get the field.
- The stdlib is not compiled in. `discover_source_from_exe` (crates/pcb-zen-core/src/stdlib.rs:70-84) finds
  `lib/std` next to the binary's ancestors, and `cache_index.rs:292-311` (crates/pcb-zen) copies it into each
  workspace's `.pcb/stdlib` whenever the contents differ. A change to lib/std/interfaces.zen therefore takes
  effect on the next run with no rebuild, and checking out another branch in ~/work/pcb changes the stdlib the
  installed `pcb` uses.

### Size

- crates/pcb-layout/src/lib.rs: path, result field, write call, and a `utils::nets_layout_json(&Schematic)`
  producing `{"version": 1, "nets": {name: {type, fields}}}` sorted (BTreeMap), with physical values parsed to
  numbers: about 50 lines.
- lib/std/interfaces.zen: 3-7 lines. crates/pcb-zen-core/src/lang/net.rs: 2-4 lines.
- Tests: a zen-core net test for `clearance` set, unset and cleared, in the style of the 02759196 tests
  (crates/pcb-zen-core/tests/net.rs, about 30 lines plus snapshots), and a sidecar snapshot in
  the `layout_test!` macro in crates/pcb-layout/tests/layout_generation.rs:38-104 (about 10
  lines; every existing layout fixture then gains one snapshot file).
- CHANGELOG.md entry and docs/pages/spec.mdx lines for the new field (AGENTS.md "Documentation").
- Total: about 60 lines of code, 40-60 of tests, 5-6 files. The 40-line figure in the spec covered only the Rust
  write.

## Stage 2: interface membership

### Where an instance is created

- `InterfaceFactory::invoke` (crates/pcb-zen-core/src/lang/interface.rs:544-585): `Spi(...)`. With `name=` the
  prefix is `InstancePrefix::from_root(name)` (interface.rs:42-48, `assignment_inferable: false`); without, it is
  `InstancePrefix::empty()` (interface.rs:34-39, `assignment_inferable: true`). It calls
  `create_interface_instance` (interface.rs:380-436).
- `create_interface_instance` builds each field through `create_field_value` (interface.rs:330-377): nets via
  `clone_net_template` or `instantiate_generated_net`, nested interfaces via `clone_interface_template`
  (interface.rs:211-326) or `instantiate_interface` (interface.rs:835-875), each with `prefix.child(field)`
  (interface.rs:60-66).
- io() parameters: `resolve_io` (crates/pcb-zen-core/src/lang/param_decl.rs:453-531) takes the parent's value
  from `request_input` (param_decl.rs:494-500) or builds a default with `InstancePrefix::from_root(name)`
  (param_decl.rs:624-630, crates/pcb-zen-core/src/lang/module.rs:1517-1525).

### What is recorded

- The instance: `InterfaceValueGen { fields, generated_fields, instance_root_name, factory }`
  (interface.rs:651-660). `instance_root_name` is `Some(prefix)` only when the prefix is not
  assignment-inferable (interface.rs:417). The type name is on the factory: `InterfaceTypeData.name`
  (interface.rs:451-460), set by the factory's `export_as` when `Spi = interface(...)` is bound (interface.rs:593-604)
  and read the same way `Display` does (interface.rs:714-729).
- Field-to-net: only implicit, as the field values themselves (each a `NetValue` with an id). Nets are registered
  in the module by id with a name and kind (crates/pcb-zen-core/src/lang/context.rs:310-322,
  module.rs:797-829). Nothing records the instance, its type or which field a net is.

### The inferred name

- Inference runs through Starlark's export hook. In the pinned starlark-rust fork (rev c3d776b, checkout under
  ~/.cargo/git/checkouts/starlark-rust-88e905e0a5e18279/c3d776b), an assignment to a module-level variable
  compiles to `InstrStoreModuleAndExport` (starlark/src/eval/bc/compiler/assign.rs:109-111), which calls
  `export_as_module_binding` (starlark/src/eval/runtime/evaluator.rs:713-726, from instr_impl.rs:257-268), which
  calls the value's `export_as(variable_name)`. Local variables inside a function compile to a plain move
  (assign.rs:103-104) and get no hook.
- `InterfaceValueGen::export_as` (interface.rs:678-710) returns at once if `instance_root_name` is set
  (interface.rs:683-685). Otherwise, for each generated field, it calls `infer_assignment_name("DISP_" + relative)`
  on a net (interface.rs:692-703) or recurses into a nested interface with the same variable name
  (interface.rs:704-705).
- `NetValue::infer_assignment_name` (net.rs:362-380) promotes the module registry entry from
  `PendingInference` to `Named` (module.rs:833-851, via context.rs:327-331) and caches the name in the net's
  `inferred_name` OnceLock (net.rs:378).
- So `DISP = Spi()` gets its name only on the nets. The instance's `instance_root_name` stays `None`: `export_as`
  takes `&self` and the field has no interior mutability. The name "DISP" exists only as the argument of that one
  `export_as` call and as a prefix of the member net names.
- io() goes through the same hook: `SPI = io(Spi)` returns a `DeferredParam` whose `export_as` resolves the
  parameter with the variable name and swaps in the result (param_decl.rs:163-176); `io("SPI", Spi)` resolves at
  once (param_decl.rs:540-542). Both end in `resolve_io` with the name.

### How an instance passed into a module gets its path

- The parent's instance (same net ids) arrives through `request_input(name)` (param_decl.rs:494) and is bound to
  the io name. The child module records it in its signature: `finish_resolution` stores `actual_value: value`
  (param_decl.rs:515-530), kept on `ModuleValueGen.signature` (module.rs:461, accessor :696) and frozen into the
  module tree.
- The converter already walks these: `propagate_diffpair_impedance` (convert.rs:1174-1222) iterates every
  module's non-config signature parameters and recurses through `FrozenInterfaceValue` fields. The module's path
  is `instance_ref.instance_path.join(".")` (convert.rs:616). So an io-bound instance is reachable at conversion
  as `<module path>.<io name>` with its frozen factory (type name) and member nets, with no new evaluation state.
- A net's flat name is set by the first module that names it; later scoped names become aliases
  (convert.rs:618-643). Membership kept by net id resolves to the canonical name.

### Where it is lost

`Schematic` is built only from the frozen module tree (convert.rs:234-272): per module its signature,
`introduced_nets`, components and moved directives. An instance bound to a module-level variable that is not
an io() parameter is referenced only by the Starlark module's globals. The module tree holds `FrozenModuleValue`s,
not the Starlark modules (crates/pcb-zen-core/src/lang/eval.rs:232-246 keeps `star_module` for the root output
only), so at conversion `DISP = Spi()` is gone apart from its net names. `serialize_interface`
(convert.rs:171-183) writes signature values with no type or instance name.

### Proposed design

Record at the binding, the way net names are inferred, and read io bindings from the signature that already
survives.

1. pcb-zen-core lang/module.rs: a plain-data registry on `ModuleValueGen`, next to `introduced_nets`
   (module.rs:463), e.g. `bound_interfaces: Vec<BoundInterface>` with
   `BoundInterface { name: String, type_name: String, members: Vec<(String, NetId)>, nested: Vec<(String, String)> }`
   (member path such as "CLK.P" -> net id; nested path "CLK" -> type "DiffPair"). Derive
   `Trace, Allocative, Freeze` as `IntroducedNet` does (module.rs:68-73); one constructor site (module.rs:585). A
   `record_interface` method skips a record whose type and member net ids match one already recorded (an alias
   such as `BUS = DISP`, or `io("SPI", Spi)` that is then also assigned). About 35 lines.
2. lang/context.rs: a pass-through like `infer_net_name` (context.rs:327-331). About 8 lines.
3. lang/interface.rs: in `InterfaceValueGen::export_as`, before the early return at :683, walk `self.fields`
   (nets by id, nested interfaces by factory type name) and call the context. Instance name:
   `instance_root_name` when set (it matches the net prefix), else `variable_name`. A shared walker and a
   type-name helper factored from `Display` (interface.rs:714-729). About 50 lines.
4. convert.rs: after nets are built (convert.rs:278-319), for each module in the tree take its
   `bound_interfaces` plus its non-config signature parameters whose `actual_value` is an interface (same walk as
   `propagate_from_value`), prefix the module path, map net ids to final net names, drop ids with no net (template
   nets unregistered by io(), interface.rs:83-111), dedupe, and fill a new `Schematic` field. Nested instances
   become their own entries ("CAM.CLK", "DiffPair", {P, N}) as well as dotted members of the parent
   ("CAM", "Csi", "CLK.P"). About 60 lines.
5. pcb-sch lib.rs: `InterfaceInstance { path, type_name, members: BTreeMap<String, String> }` and
   `Schematic.interfaces: Vec<InterfaceInstance>` with `#[serde(default, skip_serializing_if = "Vec::is_empty")]`
   (lib.rs:756-776). A top-level field avoids touching the six `pcb_sch::Net { .. }` literals
   (convert.rs:298, crates/pcb-zen-wasm/src/lib.rs:528, kicad_netlist.rs:1023 and :1064,
   crates/pcbc/src/import/generated_validate.rs:355, crates/pcb-kicad-sch/src/root_interface.rs:252). About 15
   lines. Two snapshot files contain schematic JSON (crates/pcbc/tests/snapshots/release__publish_with_file.snap,
   netlist__netlist_not_connected_open_intent.snap); they change only if their capture binds an interface.
6. pcb-layout lib.rs: invert `schematic.interfaces` into each net's `interfaces` list
   (`{instance, type, member}`) and write `pairs` from instances of type "DiffPair". About 30 lines on top of
   stage 1.
7. Tests in crates/pcb-zen-core/tests (name_inference.rs:118-147 is the model): inferred root, `name=` root,
   nested Csi with DiffPair members, an instance passed to a child module's io(), an io() template whose nets
   must not appear, an alias binding. About 100 lines plus snapshots.

Size: about 200 lines of code in 6 files (interface.rs, module.rs, context.rs, convert.rs, pcb-sch/src/lib.rs,
pcb-layout/src/lib.rs) and about 100 lines of tests. The spec's 120-180 is low by about a quarter.

What the design does not reach: an instance never bound to a module-level name and not passed to an io(), for
example one built in a list (`[Spi(name="S0"), ...]`), one kept in a function local, or one passed inline to a
component. Such instances get no record. The second option, recording at `create_interface_instance` when
`instance_root_name` is set, would add the `name=` cases at the cost of an instance id to dedupe against the
binding record (`InterfaceValueGen` has none today); leave it out of the first version.

## DiffPair

- `DiffPair = interface(P=Net(), N=Net(), impedance=field(Impedance | None, default=None))`
  (lib/std/interfaces.zen:28-32). Its members are two `Net` fields named `P` and `N`.
- It appears nested in Csi, DisplayPort, Dsi, Edp, Ethernet variants, Hdmi and Lvds
  (interfaces.zen:44-50, 127-149, 167-190, 261-266), as `CLK=DiffPair(impedance=Impedance(100))` templates, cloned
  per instance by `clone_interface_template` with the DiffPair factory kept (interface.rs:261-325).
- Stage 2 yields pairs only if nested interfaces are recorded with their own type (point 4 above). With that, a
  pair is any entry of type "DiffPair", top-level or nested, and its `P` and `N` members are the two nets. The type
  name is the name the factory was first bound to in the stdlib, so a renamed load
  (`load(..., DP="DiffPair")`) still reports "DiffPair".
- Today the converter finds DiffPairs only structurally (fields `impedance`, `P`, `N`) and only among io() values
  (convert.rs:1194-1203), to copy the impedance onto the nets as `differential_impedance`. That property alone
  marks the nets but not which two belong together, and only when the impedance is set.

## Build, install, test and branch state

- `pcb` on PATH: ~/.local/bin/pcb and ~/.local/bin/pcbc are symlinks to ~/work/pcb/target/release/pcbc (created
  Jul 20). The binary's mtime is Sep 13 21:37, two minutes after HEAD d2b9f749 (21:35), so it was most likely
  built from HEAD. `pcb --version` prints `pcbc 0.4.52` (workspace version, Cargo.toml:6), the same as upstream's
  release, so placemat cannot tell the fork from the version string.
- Build and install: `cargo build --release -p pcbc` in ~/work/pcb. The symlinks pick it up; no copy step.
  Toolchain is pinned to 1.98.0 (rust-toolchain.toml).
- Tests: AGENTS.md:5-7 says `cargo nextest run -p <crate>`; nextest is not installed here, so
  `cargo test -p pcb-zen-core --test integration`, `cargo test -p pcb-sch` and
  `cargo test -p pcb-layout --test integration` (crates/pcb-layout/Cargo.toml:11-13; the layout tests run the
  KiCad Python sync, so they need KiCad's pcbnew). Snapshots are insta; AGENTS.md:9 says changed snapshots are
  reported and accepted only with the user's approval.
- Branch state: working tree clean on `feat/netclass-nets-field-0.4.52`, which has no upstream. Its four fork
  commits on top of v0.4.52 (60f21e9f): 199fb5e7 (NetClass `nets`), e2cdbac6 (seeded KIIDs), 6357045a (footprint
  UUIDs by instance path), d2b9f749 (annotations dict). `git branch -r --contains` finds none of them on any remote.
  `origin` (benagricola/pcb) has `main` at v0.4.7 (788404f0) and `feat/netclass-nets-field` at an older cherry-pick
  (98fa1951). `upstream` is diodeinc/pcb, 18 commits past v0.4.52.
- Shipping: commit on this branch or a branch off it, push to `origin` as a new branch (not to `upstream`),
  then rebuild the release binary. AGENTS.md:15 asks for one
  CHANGELOG.md entry under Unreleased per user-visible change and spec.mdx updates for language changes.

## Problems with the spec as written

1. Instance coverage. "every instance of these Zener interface types" holds only for instances bound to a
   module-level name or an io() parameter (see "What the design does not reach"). The spec should say so.
2. Nested instances. The spec's per-net entry `{instance path, type, member}` needs nested interfaces as entries
   of their own (`CAM.CLK`, `DiffPair`, `P`) or `pairs = true` finds no pairs in Csi, Hdmi and the like. The
   parent's member name is then a dotted path (`CLK.P`).
3. Instance path when `name=` differs from the variable (`X = Spi(name="BUS")`). Net names use `BUS_*`; the
   design above reports `BUS`. The spec's `interfaces = ["DISP"]` example assumes the two agree.
4. Child module paths. An instance passed into a module appears twice: under the creator's name (`DISP`) and
   under the child's io path (`display.SPI`, module path joined with "."). That fits the spec's "a list, since a
   net can sit in several", but a selector by path must say which it matches.
5. `clearance` is more than a stdlib edit: net.rs:92-98 needs the field listed, and `Gpio`, `Analog` and `Pwm`
   have no fields today, so a clearance on a GPIO net needs the field added there too. A capture that sets
   `clearance=` will not evaluate on the upstream toolchain (unknown field), which ties those captures to the fork.
6. Values arrive as display strings with SI prefixes (`500um`); the sidecar should write numbers in fixed units.
7. Detection. The version string does not distinguish the fork. The spec's rule (no sidecar -> refuse
   `interfaces`/`net_types` phases) is the workable test; a stale `nets.layout.json` left by an earlier fork run
   in a layout directory later generated by another toolchain would pass it. Writing the generator's commit or a
   format marker into the file, or placemat checking the sidecar is newer than `default.net`, closes that.
8. The fork's current work is unpushed (four commits on no remote). Pushing the existing branch before starting is
   the first step of any plan.
