# Zener net type and interface export (fork ~/work/pcb, branch feat/netclass-nets-field-0.4.52)

Paths relative to ~/work/pcb/crates. Read-only survey; nothing built or run.

## 1. Where it lives

Net type: kept after evaluation.
- Starlark `NetValue` has `type_name` (`pcb-zen-core/src/lang/net.rs:~200`, accessor `net_type_name` :423, `net_kind_name` :428 returns "NotConnected" for open nets) and `properties: SmallMap<String,V>` (:206, accessor :441).
- Net type fields (voltage, impedance, symbol) are inserted into `properties` at `NetTypeGen::instantiate` (net.rs:~800-835). Field defs: `lib/std/interfaces.zen:3-24` (Net, Power, Ground; Analog/Pwm/Gpio have no fields).
- `convert.rs` `update_net` (:~661-700) copies kind and properties into `NetInfo` (:28-37); `Net` objects built at :~275-315.
- IR: `pcb-sch/src/lib.rs:549` `Net { kind: String, id, name, ports, properties: HashMap<Symbol, AttributeValue> }`. `Schematic.nets` keyed by final name (:758).
- Custom `builtin.net_type("X")` gives kind "X" the same way. Voltage/impedance in properties are `AttributeValue` (PhysicalValue stringified).
- DiffPair impedance is pushed onto P/N nets as `differential_impedance` (convert.rs:1174-1222).

Interface membership: NOT kept in the Schematic.
- `InterfaceValueGen` (`lang/interface.rs:651`) holds fields, private `instance_root_name` (:656, set only when the prefix is not assignment-inferable, :417), and a factory whose `InterfaceTypeData.name` is the type name ("Spi") (:451, set by `export_as` :594-604).
- Nothing records "net id X is field F of interface instance I of type T". Net names are flattened to `<PREFIX>_<FIELD>` by `compute_net_name`/`InstancePrefix::child` (interface.rs:26-60, :347-370). `register_net` (context.rs:310, module.rs:797) takes only id/name/kind.
- The only surviving trace: a module instance's `signature` attribute (convert.rs:~590-610, `attrs::SIGNATURE`, JSON) carries each io() param's actual value, serialized by `serialize_interface` (convert.rs:171-183) as `{"Interface":{"fields":{...}}}` with nested `{"Net":{id,kind,name,properties}}`. It has no type name and no instance name, and covers only interfaces passed as module parameters.

## 2. pcb layout pipeline (pcb-layout/src/lib.rs)

- Paths: `default.net`, `snapshot.layout.json`, temp `netlist.json` (lib.rs:~897-910).
- default.net: `pcb_sch::kicad_netlist::to_kicad_netlist` (kicad_netlist.rs:~60-390), written at lib.rs:705. Per net it emits only `(net (code) (name) (node ...))` (kicad_netlist.rs:~370-385). No net property or class field is written.
- JSON netlist for Python: `utils::layout_json_netlist` (lib.rs:947) = full `Schematic::to_json()` plus `footprint_fpid`. This already contains every net's `kind` and `properties`. The parser (`update_layout_file.py:170-180, 195+`) reads `kind` and drops properties.
- Snapshot: `FinalizeBoard._export_layout_snapshot` (update_layout_file.py:816-859) emits footprints, groups, zones, tracks, vias. There is no net section at all.
- Netclass patterns: `build_netclass_assignments` (lib.rs:1094-1170) -> `kicad_project_patch.rs` -> .kicad_pro `net_settings.netclass_patterns`. Called at lib.rs:767-774.

## 3. Precedent

- 199fb5e7 (NetClass `nets` field), 6 files plus fixtures: `lib/std/board_config.zen` (+1 record field), `pcb-zen-core/src/lang/stackup.rs` (+3, serde `Option<Vec<String>>`), `pcb-layout/src/lib.rs` (+25, assignment loop), `kicad_project_patch.rs` (+1), tests. Path: Zener record -> serde struct on root board_config attribute -> Rust builds pattern map -> .kicad_pro. Python not involved.
- d2b9f749 (annotations): `lib/std/generics/Capacitor.zen` and `Resistor.zen`, +2 lines each. Merges an `annotations` dict into the component's `properties`, which become footprint fields. Pure .zen; no Rust change.
- Neither carries per-net data to the board.

## 4. Options

A. Net properties in default.net: KiCad netlist E-format nets have no `(property)` element (components do, nets do not). KiCad's importer would ignore or reject it, and the .net is also parsed elsewhere. Not recommended.
B. Fields in snapshot.layout.json: the snapshot is built from the pcbnew board in Python, regression-diffed, and `--only-snapshot` exists. Adding a `nets` list there mixes schematic facts into a layout snapshot and changes every fixture snap. Possible but noisy.
C. Sidecar `nets.layout.json` written by Rust beside default.net (recommended): the data is schematic-side, so write it from the `Schematic` in lib.rs next to the netlist write (:705). Add `nets_file` to `LayoutPaths` (:93) and the result struct (:48, :798).

Recommended C, two stages.
- Stage 1 (type and fields, ~40 lines, Rust only): in pcb-layout/src/lib.rs, serialize `schematic.nets` as `{name: {kind, properties}}` (properties via serde AttributeValue or flattened to strings), sorted, and write `nets.layout.json`. No zen-core change. About 40 lines plus one test/fixture.
- Stage 2 (interfaces, ~120-180 lines): needs new data in pcb-zen-core.
  - Record membership where interfaces are built: in `create_interface_instance` (interface.rs:380-425) when `should_register`, push `{instance_root_name, type_name, fields: {field_path -> net_id}}` into the module's registry (new field near `introduced_nets`, module.rs:463, or ContextValue).
  - Carry through `FrozenModuleValue`, convert.rs `NetInfo` (add `interfaces: Vec<{instance, type, member}>`), and `pcb_sch::Net` (new serde field, `skip_serializing_if` empty).
  - Then the sidecar picks it up and the JSON netlist carries it for free.
  - Fallback with no zen-core change: parse module `signature` attributes. This covers only interfaces passed to child modules and has no type or instance name, so it is not enough for `DISP = Spi(...)`.
  - Total: files touched interface.rs, module.rs, convert.rs, pcb-sch/lib.rs, pcb-layout/lib.rs, plus tests.

## 5. Hierarchy

- A net keeps one id across modules; when an interface is passed down, child modules see the same `NetValue`s, and `net_name_aliases` (convert.rs:53, 358, 618-640) maps the child's scoped name to the parent's canonical name. The canonical flat name in `Schematic.nets` is the name registered by the module that introduced the net, i.e. `<module_path>.<PREFIX>_<FIELD>` for non-root modules (convert.rs:~618-640), plain `DISP_CS` at root.
- Because membership would be keyed by net id (stage 2), it survives passing down; one net can then belong to several interface instances (the creator's and any re-wrapped one), so the schema needs a list per net, not a single parent.
- Instance name: `instance_root_name` is only set for explicitly named construction (`!assignment_inferable`). For `DISP = Spi(...)` inferred from assignment it is None at construction time; the name is inferred later, so stage 2 must resolve it from the net name prefix or the assignment hook. I did not trace where inference finishes; check this before estimating.
- Not verified by running anything; the pcbc binary at target/release/pcbc was not invoked.
