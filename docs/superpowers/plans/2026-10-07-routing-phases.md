# Routing Phases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace placemat's four fixed route stages with named routing phases stated in `placemat.toml`, backed by a KRT
fork that routes given pad pairs (`--connections`) and stated buses (`--bus-nets`), and a Zener fork that exports each
net's type, fields, interfaces and differential pairs in `nets.layout.json`.

**Architecture:** Three repositories change, in this order (D1): the Zener fork gains a `clearance` field and the
`nets.layout.json` sidecar (stage 1); the KRT fork gains the board floors, `--connections` and `--bus-nets`; placemat
gains the phase form, a sidecar reader, phase selection, a phase engine that replaces `_route_board`'s stages (one chain
of kept results, a DRC per phase), a run whose route fails or is stopped keeping its placed board (Task 14), per-phase reports,
`route --phase/--only` and `explore --route-rank`; then Zener stage 2 (interfaces, `DiffPair`), the placemat selectors
that need it, and the circuit-capture rules. The reference set's skill gaps are fixed in both skills (Task 24); the
last placemat task removes the step's removal-ledger rows; the release follows. 26 tasks.

**Tech Stack:** Python 3.12 (placemat, KRT), pcbnew and kicad-cli (KiCad 10), Rust 1.98 (Zener fork `pcb`, Starlark),
pytest with xdist, KRT's standalone test scripts (`tests/run_all.py`), cargo test with insta.

**Spec:** `docs/superpowers/specs/2026-10-06-routing-phases-design.md`. Also read
`docs/superpowers/specs/2026-10-06-roadmap-0.100.md` ("Removal ledger", "Keeping dead code out", "Attribution"),
`docs/superpowers/research/2026-10-07/krt-connections-design.md` and
`docs/superpowers/research/2026-10-07/zener-stage2-trace.md`. Every file:line cited below was read at placemat
175358af, KRT c98d38eb, pcb d2b9f749, except Tasks 14 and 24, read at placemat 55f9005b and circuit-capture bdcca59.

## Global Constraints

- Worktrees and paths (the shell does not keep variables; spell them out or prefix each command):
  - placemat: `WT=/home/ben/work/placemat/.claude/worktrees/routing-phases`, branch `step1-routing-phases` off `main`.
    Copy `src/placemat/_version.py` in from the main checkout. Run Python as
    `PYTHONPATH=$WT/src /home/ben/work/placemat/.venv/bin/python` (or imports resolve to main).
  - KRT: `KW=/home/ben/work/KRT-phases`, a worktree of ~/work/KRT-upstream on branch `placemat/connections` off
    `placemat/upstream-2026-10`. `.venv` is a symlink to `/home/ben/work/KRT-upstream/.venv`; build
    `rust_router/grid_router.so` there with `python3 build_router.py`. Point placemat at it with `KRT_DIR=$KW`.
  - Zener: `ZW=/home/ben/work/pcb-phases`, a worktree of ~/work/pcb on branch `feat/nets-layout-json` off
    `feat/netclass-nets-field-0.4.52`. Build with `CARGO_TARGET_DIR=$ZW/target` (never the main checkout's target:
    `~/.local/bin/pcb` is `~/work/pcb/target/release/pcbc`). A run that should use the fork puts `$ZW/bin` first on
    PATH, where `$ZW/bin/pcb` is a symlink to `$ZW/target/release/pcbc` (stdlib discovery follows `/proc/self/exe`
    to `$ZW/lib/std`, pcb-zen-core/src/stdlib.rs:70-84).
- ~/work/KRT-upstream and ~/work/pcb are live for every session. Do not move their checkouts or rebuild their binaries
  before the Release task (D22).
- Forks: KRT pushes go to remote `fork` only; Zener pushes go to remote `origin` (benagricola/pcb) only. Never push to
  KRT `origin` (drandyhaas) or Zener `upstream` (diodeinc); never open issues or PRs anywhere. The Zener AGENTS.md rule
  "rebase onto origin/main before pushing" does not apply: the fork's branches sit on v0.4.52, not on origin/main.
- Shared machine: pytest `-n 2` at most; `fixtures/bench.py --jobs 2` at most; real-board and reference runs one at a
  time under `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock`;
  KRT `tests/run_all.py -j 2`; cargo with `-j 2`. Kill only PIDs you started. Agents hand back after the default
  suite (`pytest -n 2 -p no:cacheprovider`), not `--full`, except in the Release task.
- Disk is about 96% full (77 GB free on 2026-10-07). Before a cargo build or a reference run, check `df -h ~`; below
  20 GB free, stop and ask the user. Never delete files to make room.
- Plain ASCII in everything written: no em or en dashes, no unicode arrows, straight quotes.
- Commits and PR bodies carry no reference to Claude or Anthropic (no Co-Authored-By, no Claude-Session, no session
  URL). After every commit run `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`; it must
  print nothing.
- Charter: structured data inside, text at the edge (records and enums cross functions, sockets and JSON; sentences
  are made only in console, `watch`, the studio); tunables are settings with documented defaults; project-agnostic
  wording (no project, board, part or net of a project in code, tests, docs or commit messages; reference-set boards
  are fixtures and may be named in fixtures and gate tallies); defer to upstream with file:line, and mark every
  deliberate divergence in a code comment.
- `CLAUDE.md`: take board items off with `board.Delete(item)` (after `group.RemoveItem` if grouped), never
  `board.Remove`.
- Values verbatim from the spec:
  - the no-phases refusal: `route: no routing phases in placemat.toml; \`placemat settings --example\` writes a placemat.toml with the default phases`
  - the sidecar is `nets.layout.json`, versioned `"version": 1`, keyed by net name;
  - selectors: `nets`, `net_classes`, `pairs = true`, `buses`, `connections`, `current_paths = true`, `interfaces`,
    `net_types`; other keys `name`, `width` (a number in mm or `"current"`), `layers`, `neckdown` (default true),
    `router_args`; `clearance` is not a key.
- Release: 0.100.0 after this step merges (handover "Release line").

## Decisions (to confirm)

Each is applied in the plan as written; the alternative is what changes if the user picks it. D3, D8 and the approval
of Task 23 were confirmed by the user on 2026-10-07; the rest are unchanged.

- D1 Order: Zener stage 1 and the KRT fork first, then the placemat engine, Zener stage 2 last. Alt: Zener stage 2 before the engine.
- D2 `--connections` JSON ends are `{net, from: {ref, pad}, to: {ref, pad}, widths: {layer: mm}}`; the spec is amended in Task 5. Alt: the spec's "REF.PAD" strings.
- D3 A task joined by copper narrower than its asked width on any layer is `joined_narrow` and routed; at or above width it is `joined_before`. Confirmed 2026-10-07, with this fallback: if KRT cannot route such a task within the planned size (Task 5 step 3), the task is reported `joined_narrow` with its narrowest width, counted joined and not routed, and the phase's width judgement (Task 15) raises `route.width` on it.
- D4 Same-net pads of an end's footprint that are not task ends are obstacles (moved to the private net). Alt: put them in the view so the call joins them too.
- D5 Different widths on one net: one router call per distinct width map, widest first. Alt: one call and KRT's `deferred` loop alone.
- D6 KRT floors: clearance floored at the board's `min_clearance`; every neck floored at the board's `min_track_width`; both documented fork divergences. Alt: leave KRT as upstream and record the errors.
- D7 An interface instance is selected by its module-level variable name (`DISP`), an io() instance by `<module path>.<io name>`; `name=` is not used; an unbound instance has no record. Alt: also record `name=` instances.
- D8 The Zener fork's four commits on `feat/netclass-nets-field-0.4.52` are pushed to `origin` (benagricola/pcb, never `upstream`) before work starts. Confirmed 2026-10-07; Task 1 pushes without stopping.
- D9 The KRT fork is not rebased onto upstream (110 commits behind) in step 1. Alt: rebase first, re-baselining test (a).
- D10 `nets.layout.json` carries `generator` (name, version, git sha) and `netlist.sha256`; placemat refuses a sidecar whose digest does not match `default.net` beside it. Alt: compare file times.
- D11 The sidecar lists what it exports (`"exports": ["types", "fields"]`, stage 2 adds `"interfaces"`); a physical field is `{"value": number, "unit": ...}`, lengths in mm. Alt: unit-suffixed keys.
- D12 The netlist digest is sha256 of the `default.net` bytes written in the same run. Alt: a digest of nets and pads computed from the board.
- D13 `width = "current"` on a net-level selector routes each selected net's carrier pairs as tasks; a selected net with under two carriers refuses the phase, naming it. Alt: route the whole net at its largest stated current.
- D14 `current_paths`: per carrier pair (A, B) on a net, tasks span every pad of A and of B on that net (`|A| + |B| - 1` tasks) at the lesser current. Alt: one task per pair, first pad of each.
- D15 A phase that selects a net the board serves by a pour routes it alone, the pour handed to the router as a zone (today's island mechanism); the rest phase never takes pour nets. Alt: refuse pour nets in phases.
- D16 A phase's closure is judged on a DRC of the board after the phase (one kicad-cli DRC per phase) and KiCad's pad connectivity for tasks. Alt: KRT's own `joined` and one DRC at the end.
- D17 Width judgement for a phase is made on the routed board, on the copper each router call of the phase added, against that call's asked width per layer, with the neck allowance unless `neckdown = false`. Alt: KRT's per-task narrowest width.
- D18 Test (a) boards have no capture: `route_ref.py` writes the board's default phases (no pair or interface phase), so usb-c's USB class and pic_programmer's POWER class route single-ended; the manifest's `islands` becomes `phases`. Alt: a pair selector by net names for boards without a capture.
- D19 `pairs.board_pairs` (net-class pairs) stays for placement scoring (score.py, pinmap.py, occupancy.py) in step 1; only route selection moves to `DiffPair`. Alt: move placement to `DiffPair` now (changes test (b) inside a routing step).
- D20 From Task 13 a route refuses `[route] islands`, `pair_layers` and `net_halos`; Task 25 deletes the fields and moves the refusal to settings load. Alt: delete them in Task 13.
- D21 The live router and pcb move only in the Release task; gate runs use `KRT_DIR=$KW` and `PATH=$ZW/bin:$PATH`. Alt: move them when each fork task lands.
- D22 `net_halos*` report keys and the `setup.net_halo` finding become `net_clearances*` and `setup.net_clearance`. Alt: keep the old names.
- D23 `--route-rank` is a `run` flag with no setting. Alt: also an `[explore] route_rank` setting.
- D24 Without a board, `settings --example` writes one rest phase `signals`. Alt: no phase block.
- D25 Zener tests assert the JSON and Starlark values directly; no new insta snapshots (AGENTS.md: snapshot changes need the user's approval). Alt: snapshot every layout fixture's sidecar.
- D26 `--only`: an earlier phase "has no copper" when no net it selects has a track on the input board. Alt: by the kept chain's records.
- D27 A selector that names a net, class, part, instance, type or layer the board lacks, or a glob that matches nothing, refuses the route naming it. Alt: a warning finding and an empty phase.
- D28 The spec's real-board check (the power legs as a `current_paths` phase) runs on a scratch copy under the lock in the Release task; numbers go to the user, not into commits. Alt: skip it.
- Task 23, the circuit-capture skill change its charter puts under "ask first", is approved. Confirmed 2026-10-07.

Decided by the user on 2026-10-07, beyond the list above:
- `capture:` stays a basis prefix of a reference script's `why=` (a fact read from the capture's own annotations); the
  roadmap's rules and fixtures/reference/README.md say so, as lint.py does.
- A route that fails after a good placement keeps the placed, unrouted board in the layout folder and says so; other
  failures still restore the folder (Task 14).
- The skill gaps the reference set recorded are fixed in step 1 (Task 24). Its furniture rule wording ("on a board
  with no enclosure, leave it searched") is confirmed as written.
- A stop during the route stage keeps the placed board too, says so, records the run as `stopped`, and a rerun
  resumes the route (Task 14).

## Review Focus

- A board generated by the upstream pcb (no sidecar) with phases that use `pairs`, `interfaces` or `net_types`: the
  route is refused naming the generator, and phases with other selectors still route. Test in Task 10.
- A selector that matches nothing on this board (a renamed net, a class with no nets, a glob typo): refused naming it,
  never a phase that silently routes nothing (D27). Test in Task 10.
- A route stopped in the middle of phase 3, then run again: phases 1-2 are reused, phase 3 routes again from its input.
  Test in Task 13.
- Net names a router reads specially: an active-low `!RST`, a sheet path `/sheet/NET`, a name with `*`: a `nets`
  selector and the `--connections` file name them exactly (KRT `\!` escape, net_queries.py:20-50). Test in Task 11.
- `layers` naming a layer the board lacks (`In2.Cu` on a 2-layer board): refused naming the board's layers. Test in
  Task 10.

---

## File Structure

Zener fork (`$ZW`):
- Modify `lib/std/interfaces.zen`: `clearance` on `Net`, `Power`, `Ground`, `Analog`, `Pwm`, `Gpio`.
- Modify `crates/pcb-zen-core/src/lang/net.rs:92-98`: `clearance` among the optional builtin fields.
- Modify `crates/pcb-zen-core/tests/common/mod.rs:80-84`: the test preamble's `Net` gains `clearance`.
- Create `crates/pcb-layout/build.rs`: the git sha as `PCB_LAYOUT_GIT`.
- Create `crates/pcb-layout/src/nets_layout.rs`: builds the sidecar document from a `Schematic`.
- Modify `crates/pcb-layout/src/lib.rs`: path, write, result field.
- Stage 2: `crates/pcb-zen-core/src/lang/{interface.rs,module.rs,context.rs}`, `crates/pcb-zen-core/src/convert.rs`,
  `crates/pcb-sch/src/lib.rs`.
- Tests: `crates/pcb-zen-core/tests/net_clearance.rs`, `crates/pcb-zen-core/tests/interfaces_record.rs`,
  `crates/pcb-layout/tests/nets_layout.rs`.

KRT fork (`$KW`):
- Modify `py_router/route.py`, `py_router/list_nets.py`, `py_router/diff_pair_routing.py`,
  `py_router/pcb_modification.py`, `py_router/route_diff.py` (floors).
- Create `py_router/connections.py` (`--connections`).
- Modify `py_router/single_ended_loop.py`, `py_router/bus_detection.py`, `py_router/routing_config.py` (`--bus-nets`).
- Tests: `tests/test_board_floors.py`, `tests/test_connections_unit.py`, `tests/test_connections_route.py`,
  `tests/test_bus_nets.py`; `tests/gui_parity/test_manifest_plan_parity.py` (`ROUTE_CLI_ONLY`).
- Docs: `docs/connections.md`, `docs/fork-divergences.md`.

placemat (`$WT`):
- Create `src/placemat/route_phase.py`: the `[[route.phase]]` form, its validation and the default phases.
- Create `src/placemat/capture_nets.py`: reads `nets.layout.json`.
- Create `src/placemat/kicad/phase_select.py`: what a phase routes on a board, and at what width.
- Create `src/placemat/kicad/phase_run.py`: the router calls of one phase and the phase's own judgement.
- Modify `src/placemat/kicad/route.py`: `_route_board` runs phases; `router_command` gains connections, buses,
  neck-down and phase flags; the stage code goes in Task 25.
- Modify `src/placemat/kicad/route_state.py`: the kept-result chain over phase names.
- Modify `src/placemat/kicad/route_widths.py`: per-layer asks, judged on a call's added copper.
- Rename `src/placemat/kicad/net_halos.py` to `src/placemat/kicad/net_clearance.py` (Task 16).
- Modify `src/placemat/settings.py`, `src/placemat/cli.py`, `src/placemat/runner.py` (also a route failure keeps the
  placed board, Task 14), `src/placemat/explore.py`, `src/placemat/route_progress.py`, `src/placemat/channel.py`,
  `src/placemat/detach.py`, `src/placemat/findings.py`.
- Modify `src/placemat/checks.py` (`carriers_of`: `Pm.I` by a net's last part, Task 24), `BACKLOG.md`, and the
  reference boards' `NOTES.md` (Task 24).
- Modify `fixtures/reference/route_ref.py`, `fixtures/reference/manifest.json`, `fixtures/reference/README.md`,
  the reference boards' `placemat.toml`, `fixtures/fairing/*/placemat.toml`; create `fixtures/mnb/placemat.toml`.
- Create `tests/surface/{cli.txt,settings.txt,removed.txt}`, `tools/release/vulture_allow.py`,
  `tests/test_route_failure_layout.py`.
- Docs: `skills/placemat/SKILL.md`, `skills/placemat/references/{api.md,capture.md,migration.md}`.

circuit-capture (`/home/ben/work/circuit-capture`): `skills/circuit-capture/SKILL.md`, `.claude-plugin/plugin.json`
(Task 23: 0.1.7; Task 24: 0.1.8).

---

## Task 1: Preparation and the Zener fork's pending commits

**Files:** none changed in any repository; worktrees created.

**Interfaces:**
- Consumes: nothing.
- Produces: `$WT`, `$KW`, `$ZW` as in Global Constraints; `origin/feat/netclass-nets-field-0.4.52` holding d2b9f749.

- [ ] **Step 1: Check the Zener fork's remotes**

The user approved the push on 2026-10-07 (D8): the four local commits (199fb5e7, e2cdbac6, 6357045a, d2b9f749 on
feat/netclass-nets-field-0.4.52) go to `origin` (benagricola/pcb), never to `upstream` (diodeinc).

```bash
git -C /home/ben/work/pcb remote get-url origin    # expect github.com:benagricola/pcb or github.com/benagricola/pcb
git -C /home/ben/work/pcb status --short           # expect nothing
```

If `origin` is not benagricola/pcb, stop and tell the user what it is; push nothing.

- [ ] **Step 2: Push the existing branch**

```bash
git -C /home/ben/work/pcb push origin feat/netclass-nets-field-0.4.52
git -C /home/ben/work/pcb branch -r --contains d2b9f749   # expect origin/feat/netclass-nets-field-0.4.52
```

- [ ] **Step 3: Create the three worktrees**

```bash
df -h ~ | tail -1                                   # stop and ask below 20 GB free
git -C /home/ben/work/placemat worktree add .claude/worktrees/routing-phases -b step1-routing-phases main
cp /home/ben/work/placemat/src/placemat/_version.py /home/ben/work/placemat/.claude/worktrees/routing-phases/src/placemat/_version.py
git -C /home/ben/work/KRT-upstream worktree add /home/ben/work/KRT-phases -b placemat/connections placemat/upstream-2026-10
ln -s /home/ben/work/KRT-upstream/.venv /home/ben/work/KRT-phases/.venv
cd /home/ben/work/KRT-phases && .venv/bin/python build_router.py
git -C /home/ben/work/pcb worktree add /home/ben/work/pcb-phases -b feat/nets-layout-json feat/netclass-nets-field-0.4.52
mkdir -p /home/ben/work/pcb-phases/bin && ln -s /home/ben/work/pcb-phases/target/release/pcbc /home/ben/work/pcb-phases/bin/pcb
```

- [ ] **Step 4: Confirm the baselines the step is measured against**

```bash
git -C /home/ben/work/KRT-phases log -1 --format=%H     # c98d38eb4fab1581bd3dde31ae5153ce25446e1a
python3 -c "import json;d=json.load(open('/home/ben/work/placemat/fixtures/reference/results.json'));print({b:{w:r['closure_clean'] for w,r in e.items()} for b,e in d['a'].items()})"
```

Expected: the closures in "Gates" of Task 26 (chainlinkDriver 1.0, usb-c 1.0, pic_programmer 1.0, lora-v3 1.0,
esp-rust 1.0, ir-probe 0.8861, spimux 0.8649, watchy 0.8582 at class widths).

---

## Task 2: Zener: `clearance` on the stdlib net types

**Files:**
- Modify: `$ZW/lib/std/interfaces.zen:1-26`
- Modify: `$ZW/crates/pcb-zen-core/src/lang/net.rs:92-98`
- Modify: `$ZW/crates/pcb-zen-core/tests/common/mod.rs:80-84`
- Create: `$ZW/crates/pcb-zen-core/tests/net_clearance.rs`; register it in `$ZW/crates/pcb-zen-core/tests/integration.rs`
- Modify: `$ZW/CHANGELOG.md`, `$ZW/docs/pages/spec.mdx`

**Interfaces:**
- Consumes: nothing.
- Produces: every stdlib net type takes `clearance=Length(...)`, unset reads `None` and is not stored as a property;
  set, it is the net property `clearance` holding a `PhysicalValue` string (`"2mm"`, `"500um"`), which Task 3 writes
  as a number in mm.

- [ ] **Step 1: Write the failing test**

`$ZW/crates/pcb-zen-core/tests/net_clearance.rs`:

```rust
use crate::common;

fn eval_to_schematic(source: &str) -> pcb_sch::Schematic {
    let mut files = common::stdlib_test_files();
    files.insert("test.zen".to_string(), source.to_string());
    let result = common::eval_zen_raw(files, "test.zen");
    assert!(result.is_success(), "eval failed: {:?}", result.diagnostics);
    result.output.expect("output").to_schematic_with_diagnostics().output.expect("schematic")
}

#[test]
#[cfg(not(target_os = "windows"))]
fn a_net_types_clearance_is_a_property_when_set_and_none_when_not() {
    let sch = eval_to_schematic(r#"
load("interfaces.zen", "Net", "Power", "Ground", "Gpio")
load("units.zen", "Length")

HV = Power("HV", clearance=Length("2mm"))
SIG = Net("SIG")
GND = Ground("GND", clearance=Length("0.5mm"))
IO = Gpio("IO", clearance=Length("0.3mm"))

check(SIG.clearance == None, "an unset clearance reads None")
check(HV.clearance != None, "a set clearance reads back")
"#);
    let hv = &sch.nets["HV"];
    assert!(hv.properties.keys().any(|k| k.to_string() == "clearance"), "{:?}", hv.properties);
    let sig = &sch.nets["SIG"];
    assert!(!sig.properties.keys().any(|k| k.to_string() == "clearance"), "an unset clearance is not stored");
    assert!(sch.nets["IO"].properties.keys().any(|k| k.to_string() == "clearance"));
    assert!(sch.nets["GND"].properties.keys().any(|k| k.to_string() == "clearance"));
}

#[test]
#[cfg(not(target_os = "windows"))]
fn clearance_none_clears_an_inherited_one() {
    let sch = eval_to_schematic(r#"
load("interfaces.zen", "Power")
load("units.zen", "Length")
A = Power("A", clearance=Length("2mm"))
B = Power(A, clearance=None)
check(B.clearance == None, "clearance=None clears it")
"#);
    assert!(sch.nets.len() >= 1);
}
```

Add `mod net_clearance;` to `tests/integration.rs` after `mod net;`.

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/pcb-phases && CARGO_TARGET_DIR=$PWD/target cargo test -j 2 -p pcb-zen-core --test integration net_clearance`
Expected: FAIL, Gpio/Power take no `clearance` field.

- [ ] **Step 3: Add the field**

`lib/std/interfaces.zen`:

```python
load("units.zen", "Voltage", "Impedance", "Length")

Net = builtin.net_type(
    "Net",
    symbol=Symbol,
    voltage=field(Voltage | None, default=None),
    impedance=field(Impedance | None, default=None),
    clearance=field(Length | None, default=None),
)

Power = builtin.net_type(
    "Power",
    symbol=field(Symbol, default=Symbol("kicad-symbols/power.kicad_symdir/VCC.kicad_sym")),
    voltage=field(Voltage | None, default=None),
    clearance=field(Length | None, default=None),
)

Ground = builtin.net_type(
    "Ground",
    symbol=field(Symbol, default=Symbol("kicad-symbols/power.kicad_symdir/GND.kicad_sym")),
    voltage=field(Voltage, default=Voltage("0V")),
    clearance=field(Length | None, default=None),
)

NotConnected = builtin.not_connected

Analog = builtin.net_type("Analog", clearance=field(Length | None, default=None))
Pwm = builtin.net_type("Pwm", clearance=field(Length | None, default=None))
Gpio = builtin.net_type("Gpio", clearance=field(Length | None, default=None))
```

Check `lib/std/units.zen:6` exports `Length` under that name before relying on it.

`crates/pcb-zen-core/src/lang/net.rs:92-98`:

```rust
fn builtin_optional_net_fields(type_name: &str) -> &'static [&'static str] {
    match type_name {
        "Net" => &["voltage", "impedance", "clearance"],
        "Power" => &["voltage", "clearance"],
        "Ground" | "Analog" | "Pwm" | "Gpio" => &["clearance"],
        _ => &[],
    }
}
```

`tests/common/mod.rs` `ZEN_TEST_PREAMBLE`: add `Length = builtin.Length` and `clearance=field(Length | None, default=None)`
to its `Net`, matching production (its comment says it must).

- [ ] **Step 4: Run the test and the neighbours**

Run: `cd /home/ben/work/pcb-phases && CARGO_TARGET_DIR=$PWD/target cargo test -j 2 -p pcb-zen-core --test integration net`
Expected: PASS, and no snapshot changes. If insta reports a changed snapshot, stop and show the user the diff (AGENTS.md).

- [ ] **Step 5: Docs and commit**

`CHANGELOG.md` under Unreleased: "- The stdlib net types take `clearance=Length(...)`, a net's electrical clearance; unset reads `None`."
`docs/pages/spec.mdx`: add `clearance` to the table of the stdlib net types' fields.

```bash
cd /home/ben/work/pcb-phases && git add lib/std/interfaces.zen crates/pcb-zen-core CHANGELOG.md docs/pages/spec.mdx
git commit -m "stdlib: a clearance field on the net types"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"     # prints nothing
```

---

## Task 3: Zener: `nets.layout.json`, stage 1

**Files:**
- Create: `$ZW/crates/pcb-layout/build.rs`
- Create: `$ZW/crates/pcb-layout/src/nets_layout.rs`
- Modify: `$ZW/crates/pcb-layout/src/lib.rs:44-53, 92-100, 641-650, 705-707, 794-803, 899-912`
- Modify: `$ZW/crates/pcb-layout/Cargo.toml` (deps `sha2`, `hex` from the workspace)
- Create: `$ZW/crates/pcb-layout/tests/nets_layout.rs`; register in `$ZW/crates/pcb-layout/tests/integration.rs`
- Modify: `$ZW/CHANGELOG.md`, `$ZW/crates/pcb-layout/README.md`

**Interfaces:**
- Consumes: Task 2's `clearance` property.
- Produces: `layout/<board>/nets.layout.json` written beside `default.net` on every `pcb layout` that is not `--check`:

```json
{
  "version": 1,
  "generator": {"name": "benagricola/pcb", "version": "0.4.52", "git": "0123456789ab"},
  "netlist": {"file": "default.net", "sha256": "<hex of the default.net bytes>"},
  "exports": ["types", "fields"],
  "nets": {
    "HV": {"type": "Power", "fields": {"voltage": {"value": 48.0, "unit": "V"}, "clearance": {"value": 2.0, "unit": "mm"}}},
    "SIG": {"type": "Net", "fields": {}}
  }
}
```

  Keys are `Schematic.nets` keys (the board's net names). A physical field is `{value, unit}`: a length in mm, any
  other in its SI unit as `PhysicalUnitDims` prints it. Symbol bookkeeping properties (`symbol_*`, `__*`) are left out.
  `LayoutResult.nets_file: PathBuf`.

- [ ] **Step 1: Write the failing test**

`$ZW/crates/pcb-layout/tests/nets_layout.rs`:

```rust
use pcb_layout::nets_layout::nets_layout_json;
use pcb_sch::{AttributeValue, Net, Schematic};
use std::collections::HashMap;

fn net(name: &str, kind: &str, props: &[(&str, &str)]) -> Net {
    let mut n = Net::default_for_test(name, kind);
    for (k, v) in props {
        n.properties.insert((*k).into(), AttributeValue::String((*v).to_string()));
    }
    n
}

#[test]
fn the_sidecar_holds_each_nets_type_and_fields_in_fixed_units() {
    let mut sch = Schematic::default();
    sch.nets.insert("HV".into(), net("HV", "Power", &[("voltage", "48V"), ("clearance", "2mm"), ("symbol_name", "VCC")]));
    sch.nets.insert("TAP".into(), net("TAP", "Gpio", &[("clearance", "500um")]));
    sch.nets.insert("SIG".into(), net("SIG", "Net", &[]));
    let doc: serde_json::Value = serde_json::from_str(&nets_layout_json(&sch, "(export (version D))\n")).unwrap();
    assert_eq!(doc["version"], 1);
    assert_eq!(doc["generator"]["name"], "benagricola/pcb");
    assert_eq!(doc["exports"], serde_json::json!(["types", "fields"]));
    assert_eq!(doc["netlist"]["file"], "default.net");
    assert_eq!(doc["netlist"]["sha256"].as_str().unwrap().len(), 64);
    assert_eq!(doc["nets"]["HV"]["type"], "Power");
    assert_eq!(doc["nets"]["HV"]["fields"]["clearance"], serde_json::json!({"value": 2.0, "unit": "mm"}));
    assert_eq!(doc["nets"]["HV"]["fields"]["voltage"]["value"], 48.0);
    assert_eq!(doc["nets"]["TAP"]["fields"]["clearance"]["value"], 0.5);
    assert!(doc["nets"]["HV"]["fields"].get("symbol_name").is_none());
    assert_eq!(doc["nets"]["SIG"]["fields"], serde_json::json!({}));
}
```

If `Net` has no test constructor, build it with a struct literal of its fields (crates/pcb-sch/src/lib.rs:548-555)
in the test instead of `default_for_test`; do not add API for the test's sake. Add a `layout_generation` case in
`tests/layout_generation.rs`'s macro only as an assertion that `result.nets_file` exists (no snapshot, D25).

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/pcb-phases && CARGO_TARGET_DIR=$PWD/target cargo test -j 2 -p pcb-layout --test integration nets_layout`
Expected: FAIL, no module `nets_layout`.

- [ ] **Step 3: Implement**

`crates/pcb-layout/build.rs`:

```rust
use std::process::Command;

fn main() {
    let sha = Command::new("git").args(["rev-parse", "--short=12", "HEAD"]).output().ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_else(|| "unknown".to_string());
    println!("cargo:rustc-env=PCB_LAYOUT_GIT={sha}");
    println!("cargo:rerun-if-changed=../../.git/HEAD");
    println!("cargo:rerun-if-changed=../../.git/refs/heads");
}
```

`crates/pcb-layout/src/nets_layout.rs`:

```rust
//! `nets.layout.json`: each net's type and fields, beside the netlist, for a layout tool to select nets by what the
//! capture says they are. Keyed by the board's net names (`Schematic.nets` keys, which `to_kicad_netlist` writes).
use pcb_sch::physical::{PhysicalUnitDims, PhysicalValue};
use pcb_sch::{AttributeValue, Schematic};
use rust_decimal::prelude::ToPrimitive;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::str::FromStr;

pub const FILE: &str = "nets.layout.json";

fn field_value(v: &AttributeValue) -> Option<Value> {
    match v {
        AttributeValue::String(s) => match PhysicalValue::from_str(s) {
            Ok(p) if p.unit == PhysicalUnitDims::LENGTH => {
                Some(json!({"value": p.nominal.to_f64()? * 1000.0, "unit": "mm"}))
            }
            Ok(p) => Some(json!({"value": p.nominal.to_f64()?, "unit": p.unit.to_string()})),
            Err(_) => Some(Value::String(s.clone())),
        },
        AttributeValue::Number(n) => Some(json!(n)),
        AttributeValue::Boolean(b) => Some(json!(b)),
        _ => None,
    }
}

pub fn nets_layout_json(schematic: &Schematic, netlist: &str) -> String {
    let mut nets = BTreeMap::new();
    for (name, net) in &schematic.nets {
        let mut fields = Map::new();
        let mut keys: Vec<_> = net.properties.keys().collect();
        keys.sort_by_key(|k| k.to_string());
        for key in keys {
            let k = key.to_string();
            if k.starts_with("symbol") || k.starts_with("__") {
                continue;
            }
            if let Some(v) = field_value(&net.properties[key]) {
                fields.insert(k, v);
            }
        }
        nets.insert(name.clone(), json!({"type": net.kind, "fields": fields}));
    }
    let doc = json!({
        "version": 1,
        "generator": {"name": "benagricola/pcb", "version": env!("CARGO_PKG_VERSION"), "git": env!("PCB_LAYOUT_GIT")},
        "netlist": {"file": "default.net", "sha256": hex::encode(Sha256::digest(netlist.as_bytes()))},
        "exports": ["types", "fields"],
        "nets": nets,
    });
    serde_json::to_string_pretty(&doc).expect("a JSON value serialises") + "\n"
}
```

Check the module paths of `PhysicalValue`/`PhysicalUnitDims` (`crates/pcb-sch/src/physical.rs:71`, `:446`) and
`PhysicalUnitDims::LENGTH` (used at physical.rs:457); adjust the `use` lines to where pcb-sch exports them.

`lib.rs`: `pub mod nets_layout;`; `LayoutPaths` gains `pub nets: PathBuf` (= `layout_dir.join(nets_layout::FILE)` in
`get_layout_paths_for_pcb`, lib.rs:899-912); `LayoutResult` gains `pub nets_file: PathBuf`, filled at lib.rs:641-650
(`--check`: the path, nothing written) and lib.rs:794-803. After the netlist write at lib.rs:705-707:

```rust
    fs::write(&paths.nets, nets_layout::nets_layout_json(schematic, &netlist_content))
        .with_context(|| format!("Failed to write nets layout: {}", paths.nets.display()))?;
```

Cargo.toml: `sha2 = { workspace = true }`, `hex = { workspace = true }` (workspace Cargo.toml:70, :153).

- [ ] **Step 4: Run the tests**

Run: `cd /home/ben/work/pcb-phases && CARGO_TARGET_DIR=$PWD/target cargo test -j 2 -p pcb-layout --test integration`
Expected: PASS; the layout tests need KiCad's pcbnew (installed). No snapshot changes.

- [ ] **Step 5: Build the release binary and check a real generation**

```bash
df -h ~ | tail -1
cd /home/ben/work/pcb-phases && CARGO_TARGET_DIR=$PWD/target cargo build -j 2 --release -p pcbc
cp -r /home/ben/work/placemat/fixtures/reference/boards/pic_programmer /tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/zs1
cd /tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/zs1 && PATH=/home/ben/work/pcb-phases/bin:$PATH pcb layout --no-open pic_programmer.zen
python3 -c "import json,glob;d=json.load(open(glob.glob('layout/*/nets.layout.json')[0]));print(d['generator'],d['exports'],len(d['nets']))"
```

Expected: the generator names the fork and the git sha of HEAD; the net count equals the `(net` count in
`layout/*/default.net`.

- [ ] **Step 6: Docs, commit, push**

CHANGELOG: "- `pcb layout` writes `nets.layout.json` beside the netlist: each net's type and fields." README of
pcb-layout: the file's keys, as in Interfaces above.

```bash
cd /home/ben/work/pcb-phases && git add crates/pcb-layout CHANGELOG.md
git commit -m "layout: nets.layout.json, each net's type and fields beside the netlist"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
git push origin feat/nets-layout-json
```

---

## Task 4: KRT: the board's floors on clearance and necks

**Files:**
- Modify: `$KW/py_router/route.py:7393-7399` (base clearance), `:7744-7770` (the per-net map)
- Modify: `$KW/py_router/route_diff.py:2253` region (the same two sites in the pair router's main)
- Modify: `$KW/py_router/diff_pair_routing.py:1253-1255`
- Modify: `$KW/py_router/pcb_modification.py:3969-3973, 4200` and its callers (`cleanup_pipeline.py:319`, `pcb_modification.py:6992`)
- Create: `$KW/tests/test_board_floors.py`
- Create: `$KW/docs/fork-divergences.md`

**Interfaces:**
- Consumes: `list_nets.board_constraint(pcb_path, 'min_clearance')` (list_nets.py:273-289),
  `GridRouteConfig.track_floor(net_id, layer, fab_value)` (routing_config.py:408-412).
- Produces: a board whose classes sit below `min_clearance` is routed at `min_clearance`; no neck goes below the
  board's `min_track_width`.

- [ ] **Step 1: Write the failing test**

`$KW/tests/test_board_floors.py`, a standalone script in the suite's style (test_1033_power_width_disclosure.py):

```python
#!/usr/bin/env python3
"""Fork divergence (docs/fork-divergences.md): the board's own minimums floor what the router routes at.

  * the base clearance and every per-net clearance are at least the board's min_clearance, which KiCad grades by
    (design_rules.py:24 states KiCad's rule; upstream declines it, list_nets.py:91-94);
  * a pair partner neck and a pruned graze neck no lower than the net's track floor, as the single-ended terminal
    neck does (single_ended_routing.py:960-962).

    python3 tests/test_board_floors.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, HERE)

fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _project(path, default_clearance, min_clearance, min_track):
    doc = {"board": {"design_settings": {"rules": {"min_clearance": min_clearance, "min_track_width": min_track}}},
           "net_settings": {"classes": [{"name": "Default", "clearance": default_clearance, "track_width": 0.2,
                                         "via_diameter": 0.6, "via_drill": 0.3}]}}
    with open(path, 'w') as f:
        json.dump(doc, f)


def t_floored_clearance():
    from route import resolve_floored_clearances
    with tempfile.TemporaryDirectory() as tmp:
        pcb = os.path.join(tmp, 'b.kicad_pcb')
        open(pcb, 'w').write('(kicad_pcb (version 20241229) (generator "t"))\n')
        _project(os.path.join(tmp, 'b.kicad_pro'), 0.125, 0.15, 0.125)
        base, by_id = resolve_floored_clearances(pcb, 0.125, {1: 0.125, 2: 0.2})
        check('base clearance floored at min_clearance', abs(base - 0.15) < 1e-9, base)
        check('a class under the minimum is raised to it', abs(by_id[1] - 0.15) < 1e-9, by_id)
        check('a class over the minimum keeps its own', abs(by_id[2] - 0.2) < 1e-9, by_id)
        _project(os.path.join(tmp, 'b.kicad_pro'), 0.125, 0.0, 0.125)
        base, _ = resolve_floored_clearances(pcb, 0.125, {})
        check('a board with no minimum is left at its class', abs(base - 0.125) < 1e-9, base)


def t_pair_neck_floor():
    from synth import make_seg
    from diff_pair_routing import _neck_pair_partner_grazes

    class Cfg:
        net_clearances = {}
        clearance = 0.2
        def track_floor(self, net_id, layer, fab_value):
            return max(fab_value, 0.25)
        def obstacle_clearance(self, net_id):
            return 0.2

    class Info:
        copper_layers = ['F.Cu', 'B.Cu']

    class Pcb:
        board_info = Info()
    p = [make_seg(0, 0, 10, 0, width=0.4, net_id=1)]
    n = [make_seg(0, 0.45, 10, 0.45, width=0.4, net_id=2)]
    _neck_pair_partner_grazes(p, n, Cfg(), Pcb())
    check('a pair neck stays at or above the board track floor',
          min(s.width for s in p + n) >= 0.25 - 1e-9, [s.width for s in p + n])


if __name__ == '__main__':
    t_floored_clearance()
    t_pair_neck_floor()
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
```

If `_neck_pair_partner_grazes` reads attributes of `config` or `pcb_data` the stubs lack, read
diff_pair_routing.py:1230-1320 and give the stubs exactly those attributes; the assertion stays.

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/KRT-phases && .venv/bin/python tests/test_board_floors.py`
Expected: FAIL, `resolve_floored_clearances` does not exist; the pair neck goes under 0.25.

- [ ] **Step 3: Implement**

In `py_router/route.py`, near the clearance resolution, add and use:

```python
def resolve_floored_clearances(input_file, clearance, net_clearances_by_id):
    """FORK DIVERGENCE (docs/fork-divergences.md): the base clearance and each per-net clearance floored at the
    board's min_clearance. KiCad grades every clearance as max(rule, min_clearance) (design_rules.py:24); upstream
    declines min_clearance as an edit floor (list_nets.py:91-94, :729-736), so a board whose Default class sits below
    it is routed under the minimum KiCad then grades by. placemat writes the project KiCad grades by, so the fork
    applies the floor."""
    from list_nets import board_constraint
    floor = board_constraint(input_file, 'min_clearance') or 0.0
    base = max(clearance, floor)
    by_id = {nid: max(float(c), floor) for nid, c in (net_clearances_by_id or {}).items()}
    return base, by_id
```

Call it after `args.clearance` is settled (route.py:7393-7399 and the ceiling lines after them):
`args.clearance, _ = resolve_floored_clearances(args.input_file, args.clearance, {})`, and after
`_net_clearances_map` is built in both branches (route.py:7744-7770):
`_, _net_clearances_map = resolve_floored_clearances(args.input_file, args.clearance, _net_clearances_map)` when
the map is not None. Do the same at the pair router's matching sites (route_diff.py from :2253), importing the
function from route.py or moving it to list_nets.py if route_diff.py cannot import route.py without side effects.

`diff_pair_routing.py:1253-1255`: replace `floor = _fab_track_floor(pcb_data)` by a per-segment floor inside the loop:

```python
    fab = _fab_track_floor(pcb_data)
    # FORK DIVERGENCE (docs/fork-divergences.md): the neck floors at the net's own track floor, the board's
    # min_track_width included, as the single-ended terminal neck does (single_ended_routing.py:960-962). Upstream
    # floors at the bare fab tier (0.0889 mm on 4+ layers), below the board's minimum that KiCad grades.
    def floor_of(seg):
        return config.track_floor(seg.net_id, seg.layer, fab) if hasattr(config, 'track_floor') else fab
```

and use `floor_of(seg)` where `floor` was compared (diff_pair_routing.py:1292-1294).

`pcb_modification.py`: `prune_grazing_segments(..., net_clearances=None, floor_of=None)`; at :4200
`floor = floor_of(s.net_id, s.layer) if floor_of else _fab_track_floor(pcb_data)` with the same divergence comment.
Read the two callers (cleanup_pipeline.py:300-330, pcb_modification.py:6980-6995): where a `GridRouteConfig` is in
scope pass `floor_of=lambda nid, layer: config.track_floor(nid, layer, _fab_track_floor(pcb_data))`; where none is,
thread it from the caller's caller and say so in the commit message.

`docs/fork-divergences.md`: one section per divergence: what upstream does (file:line), what the fork does, why
(placemat writes the project KiCad grades by), and the test that pins it.

- [ ] **Step 4: Run the test and the neighbours**

```bash
cd /home/ben/work/KRT-phases && .venv/bin/python tests/test_board_floors.py
python3 tests/run_all.py -j 2 clearance neck graze diff_pair floor
```

Expected: PASS. A neighbour that pinned a sub-minimum clearance or neck now fails: read it; if it pins upstream's
behaviour on a board whose minimum is above the class, update its expectation in the same commit and name it in the
message.

- [ ] **Step 5: Commit and push**

```bash
cd /home/ben/work/KRT-phases && git add py_router tests/test_board_floors.py docs/fork-divergences.md
git commit -m "Fork: clearance floored at the board's min_clearance; pair and graze necks at the board's track floor"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
git push fork placemat/connections
```

---

## Task 5: KRT: `--connections`, routing given pad pairs of a net

**Files:**
- Create: `$KW/py_router/connections.py`
- Modify: `$KW/py_router/route.py` (flag next to `--bus` at :7139; `batch_route` parameter at :764; the split right
  after the canonicalisation at :1119-1120; widths installed after :1545; summary hooks at :6662-6681 and
  `_write_summary_min_file` :482-513; net selection in main near :7506-7535)
- Modify: `$KW/py_router/net_queries.py:261-330` (`pin_pair_path_length` gains `return_path=False`)
- Modify: `$KW/tests/gui_parity/test_manifest_plan_parity.py:735` (`ROUTE_CLI_ONLY`), `$KW/krt_capabilities.py`
  (nothing if flags are read from `--help`; check `FLAG_SCRIPTS` at :105)
- Create: `$KW/tests/test_connections_unit.py`, `$KW/tests/test_connections_route.py`, `$KW/docs/connections.md`
- Modify (placemat, in `$WT`): `docs/superpowers/specs/2026-10-06-routing-phases-design.md`, section "Routing only
  some connections of a net (KRT fork)" (D2)

**Interfaces:**
- Consumes: Task 4's floors.
- Produces: `route.py IN OUT --connections FILE [--json-out SUMMARY]`. FILE is a JSON list, each
  `{"net": str, "from": {"ref": str, "pad": str}, "to": {"ref": str, "pad": str}, "widths": {"F.Cu": 0.5, ...}}`;
  `widths` names every layer the call routes on. `--connections` refuses `--nets` and `--power-nets` alongside.
  The summary gains `"connections"`: one record per task in file order:
  `{"net", "from": {"ref", "pad"}, "to": {"ref", "pad"}, "status": "routed"|"failed"|"joined_before"|"joined_narrow"|"deferred"|"refused", "reason": str|null, "joined": bool, "length_mm": float|null, "min_width_mm": {layer: mm}}`.
  `joined_narrow`: joined before the call by copper narrower than `widths` on some layer; routed (D3), its record
  `joined` is judged after. `deferred`: another group of the same net was routed in this call; route it again.
  `refused` carries `reason` in `unknown_ref`, `unknown_pad`, `pad_not_on_net`, `layer_not_routed`,
  `width_under_board_minimum`. `route.py --capabilities` lists `--connections`.

- [ ] **Step 1: Write the failing unit test**

`$KW/tests/test_connections_unit.py` (fast, in memory, the suite's script style as in Task 4):

```python
#!/usr/bin/env python3
"""--connections: load, refusals, the width-aware joined judgement, grouping, and the net split (placemat fork)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, HERE)

from synth import make_pad, make_pcb, make_seg  # noqa: E402
from kicad_parser import Net  # noqa: E402

fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def board():
    """Net 1 "PWR": J1.1 at (0,0), U1.1 at (10,0), U1.2 at (10,1) (a sibling pad), C1.1 at (5,8). Net 2 "SIG": R1.1."""
    pads = {1: [make_pad(1, 0, 0, ref='J1', num='1', net_name='PWR'),
                make_pad(1, 10, 0, ref='U1', num='1', net_name='PWR'),
                make_pad(1, 10, 1, ref='U1', num='2', net_name='PWR'),
                make_pad(1, 5, 8, ref='C1', num='1', net_name='PWR')],
            2: [make_pad(2, 20, 0, ref='R1', num='1', net_name='SIG')]}
    return make_pcb(nets={1: Net(1, 'PWR'), 2: Net(2, 'SIG')}, pads_by_net=pads)


def task(frm, to, widths=None, net='PWR'):
    return {"net": net, "from": {"ref": frm[0], "pad": frm[1]}, "to": {"ref": to[0], "pad": to[1]},
            "widths": widths or {"F.Cu": 0.5, "B.Cu": 0.5}}


def t_refusals():
    from connections import resolve
    pcb = board()
    layers = ['F.Cu', 'B.Cu']
    got = resolve([task(('J9', '1'), ('U1', '1')), task(('J1', '7'), ('U1', '1')), task(('R1', '1'), ('U1', '1')),
                   task(('J1', '1'), ('U1', '1'), {"F.Cu": 0.5, "In1.Cu": 0.5}),
                   task(('J1', '1'), ('U1', '1'), {"F.Cu": 0.05, "B.Cu": 0.05})], pcb, layers, min_track=0.1)
    check('an unknown ref is refused', got[0].reason == 'unknown_ref', got[0])
    check('an unknown pad is refused', got[1].reason == 'unknown_pad', got[1])
    check('a pad on another net is refused', got[2].reason == 'pad_not_on_net', got[2])
    check('a width layer the call does not route is refused', got[3].reason == 'layer_not_routed', got[3])
    check('a width under the board minimum is refused', got[4].reason == 'width_under_board_minimum', got[4])


def t_joined():
    from connections import resolve, judge_joined
    pcb = board()
    pcb.segments.append(make_seg(0, 0, 10, 0, width=0.2, net_id=1))     # J1.1-U1.1 joined at 0.2 on F.Cu
    tasks = resolve([task(('J1', '1'), ('U1', '1')), task(('J1', '1'), ('U1', '1'), {"F.Cu": 0.2, "B.Cu": 0.2}),
                     task(('J1', '1'), ('C1', '1'))], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    check('joined by narrower copper is joined_narrow', tasks[0].status == 'joined_narrow', tasks[0])
    check('joined at its width is joined_before', tasks[1].status == 'joined_before', tasks[1])
    check('an open task stays open', tasks[2].status is None, tasks[2])


def t_grouping():
    from connections import resolve, judge_joined, choose_groups
    pcb = board()
    tasks = resolve([task(('J1', '1'), ('U1', '1')), task(('C1', '1'), ('U1', '2')),
                     task(('U1', '1'), ('C1', '1'), {"F.Cu": 0.3, "B.Cu": 0.3})], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    routed = choose_groups(tasks)
    check('the first group in file order is routed', tasks[0] in routed[1], routed)
    check('a second, disjoint group of the net is deferred', tasks[1].status == 'deferred', tasks[1])
    check('a task with another width map on the net is deferred', tasks[2].status == 'deferred', tasks[2])


def t_split():
    from connections import resolve, judge_joined, choose_groups, split_nets
    pcb = board()
    pcb.segments.append(make_seg(5, 8, 5, 5, width=0.2, net_id=1))       # a stub on C1.1, not a task end
    tasks = resolve([task(('J1', '1'), ('U1', '1'))], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    private = split_nets(pcb, choose_groups(tasks))
    pid = private[1]
    on_net = {(p.component_ref, p.pad_number) for p in pcb.pads_by_net[1]}
    moved = {(p.component_ref, p.pad_number) for p in pcb.pads_by_net[pid]}
    check('the task ends stay on the net', on_net == {('J1', '1'), ('U1', '1')}, on_net)
    check('the sibling pad and the other pad move to the private net (D4)', moved == {('U1', '2'), ('C1', '1')}, moved)
    check('copper joined to no end moves with them', all(s.net_id == pid for s in pcb.segments), pcb.segments)
    check('the private net is not named like a board net', pcb.nets[pid].name.startswith('__connections_private'),
          pcb.nets[pid].name)


if __name__ == '__main__':
    t_refusals()
    t_joined()
    t_grouping()
    t_split()
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/KRT-phases && .venv/bin/python tests/test_connections_unit.py`
Expected: FAIL, no module `connections`.

- [ ] **Step 3: Check that D3 fits before building it**

D3 routes a task whose ends are joined by narrow copper. KRT treats a net whose pads share a component as routed
(routing_common.py:505-640, `filter_already_routed`), so the narrow joining copper must leave the net's view without
becoming an obstacle that touches the end pads. Find where obstacle stamping skips the copper of the net being routed
(grep `obstacle` builders in py_router for the net-id test that skips own-net copper). If one net-id set decides it,
the plan below adds a second private net, the "passable" one, to that set.

If no such single place exists, do not stop: take the fallback the user confirmed on 2026-10-07 (D3), and say in the
task's report that it was taken and why (the obstacle builders that test own-net copper, by file:line). Under the
fallback:
- `judge_joined` still sets `joined_narrow`, with `min_width_mm` the narrowest width per layer of the joining path;
- a `joined_narrow` task is not routed: `choose_groups` and `split_nets` take only open tasks (`t.status is None`), and
  the passable private net in step 4 is not built;
- its record has `"joined": true` and `"status": "joined_narrow"`, so placemat counts it joined, and one more key,
  `"path"`: the joining path's segments, each `{"layer": str, "start": [x, y], "end": [x, y], "width": mm}` in the
  board's mm, from `judge_joined`'s `path` (`[{"layer": s.layer, "start": [s.start_x, s.start_y], "end": [s.end_x,
  s.end_y], "width": s.width} for s in path]`); every other record has `"path": null`;
- `docs/connections.md` says a `joined_narrow` task is reported, not routed;
- the third case of step 6 expects `joined_narrow`, `joined` true, `min_width_mm` 0.2 on the stub's layer, a `path`
  of the stub's segments and no new copper between A and B.
placemat's phase width judgement then judges that path against the task's widths and raises `route.width` on it
(Task 15, `narrow_join_widths`).

- [ ] **Step 4: Implement `connections.py`**

```python
"""--connections: route only given pad pairs of a net, at a width per layer (placemat fork, docs/connections.md).

KRT closes whole nets (connectivity.py find_connected_groups); every pass works per net id. For a call with
--connections each named net is restricted to the pads of its tasks and the copper joined to them: the net's other pads
and copper move, for this call only, to a private net that is an obstacle (D4: a same-net sibling pad of an end's
footprint is one too), and copper joining a task's ends narrower than asked moves to a passable private net (D3). The
writer copies the input text and appends only new copper by name (output_writer.py:26, :387-452), so the private ids
never reach the file."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

STATUSES = ('routed', 'failed', 'joined_before', 'joined_narrow', 'deferred', 'refused')
_UNDER = 1e-3            # KRT's own width tolerance (routing_common.py power_width_report)


class ConnectionsError(ValueError):
    """A connections file that cannot be read at all: `code` and `facts`."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, facts
        super().__init__(f'--connections: {code} {json.dumps(facts, sort_keys=True)}')


@dataclass
class Task:
    index: int
    net: str
    start: dict          # {"ref", "pad"}
    end: dict
    widths: Dict[str, float]
    net_id: Optional[int] = None
    start_pads: list = field(default_factory=list)
    end_pads: list = field(default_factory=list)
    status: Optional[str] = None
    reason: Optional[str] = None
    joined: bool = False
    length_mm: Optional[float] = None
    min_width_mm: Dict[str, float] = field(default_factory=dict)

    def record(self) -> dict:
        return {"net": self.net, "from": self.start, "to": self.end, "status": self.status, "reason": self.reason,
                "joined": self.joined, "length_mm": self.length_mm, "min_width_mm": self.min_width_mm}


def read_file(path) -> list:
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    if not isinstance(doc, list):
        raise ConnectionsError('not_a_list', path=str(path))
    for i, t in enumerate(doc):
        ok = (isinstance(t, dict) and isinstance(t.get('net'), str) and isinstance(t.get('widths'), dict)
              and all(isinstance(t.get(k), dict) and isinstance(t[k].get('ref'), str) and isinstance(t[k].get('pad'), str)
                      for k in ('from', 'to')))
        if not ok:
            raise ConnectionsError('bad_task', index=i)
    return doc


def resolve(raw: list, pcb_data, routing_layers, min_track: float) -> List[Task]:
    """Each task with its net id and the pads of each end (every pad of that footprint with that number on the net:
    a number may repeat, kicad_parser.py:219-240), or refused with a reason."""
    by_name = {n.name: nid for nid, n in pcb_data.nets.items()}
    all_pads = [p for ps in pcb_data.pads_by_net.values() for p in ps]
    refs = {p.component_ref for p in all_pads} | set(getattr(pcb_data, 'footprints', {}) or {})
    out = []
    for i, t in enumerate(raw):
        task = Task(i, t['net'], dict(t['from']), dict(t['to']), {k: float(v) for k, v in t['widths'].items()})
        out.append(task)
        nid = by_name.get(task.net)
        task.net_id = nid
        for end, into in ((task.start, task.start_pads), (task.end, task.end_pads)):
            if end['ref'] not in refs:
                task.status, task.reason = 'refused', 'unknown_ref'
                break
            numbered = [p for p in all_pads if p.component_ref == end['ref'] and p.pad_number == end['pad']]
            if not numbered:
                task.status, task.reason = 'refused', 'unknown_pad'
                break
            on_net = [p for p in numbered if p.net_id == nid]
            if not on_net:
                task.status, task.reason = 'refused', 'pad_not_on_net'
                break
            into.extend(on_net)
        if task.status:
            continue
        if any(layer not in routing_layers for layer in task.widths):
            task.status, task.reason = 'refused', 'layer_not_routed'
        elif any(w < min_track - _UNDER for w in task.widths.values()):
            task.status, task.reason = 'refused', 'width_under_board_minimum'
    return out


def _components(pcb_data, net_id):
    from check_connected import check_net_connectivity
    segs = [s for s in pcb_data.segments if s.net_id == net_id]
    vias = [v for v in pcb_data.vias if v.net_id == net_id]
    zones = [z for z in pcb_data.zones if z.net_id == net_id]
    result = check_net_connectivity(net_id, segs, vias, pcb_data.pads_by_net.get(net_id, []), zones, pcb_data=pcb_data)
    return result['pad_components']


def _pad_key(pad):
    """The key check_net_connectivity's `pad_components` uses for a pad (read check_connected.py where it fills
    pad_components and use exactly that key)."""
    return (round(pad.global_x, 4), round(pad.global_y, 4))


def judge_joined(pcb_data, tasks: List[Task]) -> None:
    """A task whose two ends share a copper component before the call is `joined_before` when the joining path is at
    least its width on every layer, else `joined_narrow` (D3, routed)."""
    from net_queries import pin_pair_path_length
    comps = {}
    for t in tasks:
        if t.status:
            continue
        comps.setdefault(t.net_id, _components(pcb_data, t.net_id))
        c = comps[t.net_id]
        a = {c.get(_pad_key(p)) for p in t.start_pads} - {None}
        b = {c.get(_pad_key(p)) for p in t.end_pads} - {None}
        if not (a & b):
            continue
        length, path = pin_pair_path_length(pcb_data, t.net_id, t.start_pads[0], t.end_pads[0], return_path=True)
        narrow = {}
        for s in path or ():
            narrow[s.layer] = min(narrow.get(s.layer, s.width), s.width)
        t.length_mm, t.min_width_mm = length, narrow
        under = any(w < t.widths.get(layer, 0.0) - _UNDER for layer, w in narrow.items())
        t.status = 'joined_narrow' if under else 'joined_before'


def choose_groups(tasks: List[Task]) -> Dict[int, List[Task]]:
    """Per net, the first group (tasks joined through shared ends, union-find) in file order whose tasks share one
    widths map; every other open task of that net is `deferred`. KRT holds one width map and one connected terminal
    set per net per call (routing_config.py:602-640)."""
    chosen: Dict[int, List[Task]] = {}
    for nid in dict.fromkeys(t.net_id for t in tasks if t.status in (None, 'joined_narrow')):
        mine = [t for t in tasks if t.net_id == nid and t.status in (None, 'joined_narrow')]
        first = mine[0]
        group, ends = [first], {_end_key(first.start), _end_key(first.end)}
        grew = True
        while grew:
            grew = False
            for t in mine:
                if t in group or t.widths != first.widths:
                    continue
                if {_end_key(t.start), _end_key(t.end)} & ends:
                    group.append(t)
                    ends |= {_end_key(t.start), _end_key(t.end)}
                    grew = True
        for t in mine:
            if t not in group:
                t.status = 'deferred'
        chosen[nid] = group
    return chosen


def _end_key(end):
    return (end['ref'], end['pad'])


def split_nets(pcb_data, chosen: Dict[int, List[Task]]) -> Dict[int, int]:
    """Move, for each chosen net, every pad and copper item that is not a task end and not joined to one into a
    private obstacle net; returns {net id: private id}. The private net gets the net's class clearance (the caller
    sets net_clearances) and is protected from rip-up (the caller adds it to the protected set)."""
    private = {}
    next_id = max(pcb_data.nets) + 1
    for nid, group in chosen.items():
        ends = {id(p) for t in group for p in t.start_pads + t.end_pads}
        comps = _components(pcb_data, nid)
        keep = {comps.get(_pad_key(p)) for t in group for p in t.start_pads + t.end_pads} - {None}
        pid = next_id
        next_id += 1
        from kicad_parser import Net
        pcb_data.nets[pid] = Net(pid, '__connections_private_%d' % nid)
        stay, moved = [], []
        for p in pcb_data.pads_by_net.get(nid, []):
            (stay if id(p) in ends else moved).append(p)
        for p in moved:
            p.net_id = pid
        pcb_data.pads_by_net[nid], pcb_data.pads_by_net[pid] = stay, moved
        kept_items = _items_in_components(pcb_data, nid, keep)
        for item in list(pcb_data.segments) + list(pcb_data.vias) + list(pcb_data.zones):
            if item.net_id == nid and id(item) not in kept_items:
                item.net_id = pid
        private[nid] = pid
    return private
```

`_items_in_components(pcb_data, nid, keep)` returns the ids of the segments, vias and zones of `nid` in the kept
components: call `check_net_connectivity(..., return_graph=True)` and read the graph's item-to-component map (read
check_connected.py's `return_graph` branch for the exact keys). For a `joined_narrow` task, after `split_nets` move
the joining path's segments narrower than the task's widths into a second private net registered as passable (the set
step 3 found); its ends stay on the net. Fill the report after the call by re-parsing the written board
(`parse_kicad_pcb(output_file)`), running `judge_joined`'s measurement on each task (`joined`, `length_mm`,
`min_width_mm`) and setting `routed`/`failed` for the tasks that were routed.

`net_queries.pin_pair_path_length(..., return_path=False)`: with `return_path=True` return `(length, [segments on the
shortest path])`, `(None, [])` when not joined; keep the default return unchanged for its callers.

- [ ] **Step 5: Wire it into route.py**

- argparse, next to `--bus` (route.py:7139):
  `parser.add_argument("--connections", metavar="FILE", help="route only these pad pairs, each at its width per layer (placemat fork, docs/connections.md)")`.
- main, before net selection (route.py:7506-7535): with `args.connections`, refuse `--nets` and `--power-nets`
  given alongside (`parser.error`), `raw = connections.read_file(args.connections)`, set `net_names` to the distinct
  task nets, and pass `connections=raw` to the one `batch_route(...)` call, before `collect_stats=args.stats)`
  (placemat's quick wrapper patches that call by text anchors, P/kicad/route_one_round.py:29-35; do not add a second
  call or move the anchors).
- `batch_route(..., connections=None)`: forward it in `_reconcile_kwargs` (route.py:984-993). Right after
  `canonicalize_pcb_data_order(pcb_data)` (route.py:1119-1120): `tasks = resolve(...)`, `judge_joined`,
  `chosen = choose_groups(tasks)`, `private = split_nets(pcb_data, chosen)`; give each private id its net's class
  clearance in the `net_clearances` map (route.py:1122-1146, :1626) and add it to the protected set
  (protected_nets.py:297-336). After route.py:1545: `config.net_layer_widths[nid] = dict(group[0].widths)` for each
  chosen net and make sure `power_net_widths` does not name it (routing_config.py:623-625).
- Summary: `_merged['connections'] = [t.record() for t in tasks]` just before `write_summary_file`
  (route.py:6662-6681), gated on `json_out`; the same key in `_write_summary_min_file` (route.py:482-513) for the
  early return when every task was joined.
- `ROUTE_CLI_ONLY['--connections'] = "placemat's per-connection routing; the GUI has no connection list"`.

- [ ] **Step 6: Write the integration test**

`$KW/tests/test_connections_route.py`: a board written as text (the model is test_1033's `_board`, :280-325) with
net PWR on pads A (U1.1), B (U2.1), C (U3.1), F.Cu and B.Cu, Default 0.15 clearance, 0.2 width. Run
`route.py IN OUT --connections C.json --layers F.Cu B.Cu --json-out S.json` with A-B at `{"F.Cu": 0.5, "B.Cu": 0.3}`,
then check:

```python
    rec = doc['connections'][0]
    check('the task is routed and joined', rec['status'] == 'routed' and rec['joined'], rec)
    check('new copper on F.Cu is at its asked width', all(abs(s.width - 0.5) < 1e-3 for s in new if s.layer == 'F.Cu'))
    check('new copper on B.Cu is at its asked width', all(abs(s.width - 0.3) < 1e-3 for s in new if s.layer == 'B.Cu'))
    check('C gets no new copper', not any(_touches(s, C) for s in new))
    check('the private net name is in neither output file',
          '__connections_private' not in open(OUT).read() and '__connections_private' not in open(OUT_PRO).read())
```

A second run on OUT with the same file reports `joined_before`. A third, from a board with a 0.2 mm stub A-B
already laid, reports `joined_narrow` then `routed` with `min_width_mm` at least 0.3 on B.Cu. One more case calls
`batch_route(..., final_reconcile=False, connections=raw, json_out=...)` in process and checks the key is written.

- [ ] **Step 7: Run both tests and the neighbours**

```bash
cd /home/ben/work/KRT-phases && .venv/bin/python tests/test_connections_unit.py && .venv/bin/python tests/test_connections_route.py
.venv/bin/python tests/test_route_flag_plan_coverage.py
python3 tests/run_all.py -j 2 connections summary reconcile
```

Expected: PASS.

- [ ] **Step 8: Docs, the spec amendment, commits, push**

`docs/connections.md`: the file format, the statuses and reasons, D3 and D4 as decided, and that whole-net summary
keys still describe whole nets (a connections call's reader takes `connections`).

```bash
cd /home/ben/work/KRT-phases && git add py_router tests docs/connections.md
git commit -m "Fork: --connections routes given pad pairs of a net at a width per layer"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
git push fork placemat/connections
```

In `$WT`, amend the spec's `--connections` bullet to the structured form of Interfaces above (D2), naming the KRT
commit:

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases && git add docs/superpowers/specs/2026-10-06-routing-phases-design.md
git commit -m "Spec: --connections ends are structured {ref, pad}, as the KRT fork implements them"
```

---

## Task 6: KRT: `--bus-nets`, a stated bus

**Files:**
- Modify: `$KW/py_router/route.py` (flag; `config.stated_buses`), `$KW/py_router/routing_config.py` (one field),
  `$KW/py_router/single_ended_loop.py:463-481`, `$KW/py_router/bus_detection.py` (a builder for a stated group)
- Create: `$KW/tests/test_bus_nets.py`
- Modify: `$KW/tests/gui_parity/test_manifest_plan_parity.py` (`ROUTE_CLI_ONLY`), `$KW/docs/connections.md`

**Interfaces:**
- Consumes: nothing new.
- Produces: `--bus-nets NET [NET ...]`, repeatable (one group per use), implies `--bus`. Stated groups skip
  detection and the geometric filter; corridor planning and demotion stay. Summary key `bus_groups`:
  `[{"name": str, "nets": [str], "origin": "stated"|"detected", "demoted": bool}]`.

- [ ] **Step 1: Write the failing test**

`$KW/tests/test_bus_nets.py`: a two-net bus (detection drops groups under 3 members in the geometric filter,
bus_detection.py:316-376) on a written board, routed with `--bus-nets SDA SCL --json-out S.json`:

```python
    groups = doc.get('bus_groups') or []
    check('the stated pair is one bus group', any(g['origin'] == 'stated' and sorted(g['nets']) == ['SCL', 'SDA']
                                                  for g in groups), groups)
    check('without the flag detection finds none', not (doc_plain.get('bus_groups') or []), doc_plain.get('bus_groups'))
```

And in memory: `config.stated_buses = [[sda_id, scl_id]]` gives one `BusGroup` from `stated_bus_groups(pcb_data,
config)` with `net_ids` ordered by `_order_nets_by_position` (bus_detection.py:204).

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/KRT-phases && .venv/bin/python tests/test_bus_nets.py`
Expected: FAIL, unknown flag `--bus-nets`.

- [ ] **Step 3: Implement**

- route.py: `parser.add_argument("--bus-nets", nargs="+", action="append", metavar="NET", help="route these nets as one bus, as given (placemat fork); repeatable, one group per use; implies --bus")`;
  after parsing, `if args.bus_nets: args.bus = True`; resolve names to ids where `bus_enabled` is set and store
  `config.stated_buses: List[List[int]]` (new `GridRouteConfig` field, default empty list).
- bus_detection.py: `stated_bus_groups(pcb_data, config) -> List[BusGroup]`: for each stated list, the ids present in
  the call, ordered by `_order_nets_by_position`, endpoints from `get_net_routing_endpoints` (connectivity.py:1912),
  named `stated_%d`.
- single_ended_loop.py:466-481: run detection and the filter only over nets not in a stated group; prepend the
  stated groups; record each group's origin; when `plan_bus_corridors` demotes a group, mark it.
- route.py summary: `_merged['bus_groups'] = [...]` beside `connections`, gated on `json_out`.
- `ROUTE_CLI_ONLY['--bus-nets'] = "placemat's stated bus; the GUI detects buses"`.

- [ ] **Step 4: Run the tests**

```bash
cd /home/ben/work/KRT-phases && .venv/bin/python tests/test_bus_nets.py && .venv/bin/python tests/test_route_flag_plan_coverage.py
python3 tests/run_all.py -j 2 bus
```

Expected: PASS.

- [ ] **Step 5: Commit and push**

```bash
cd /home/ben/work/KRT-phases && git add py_router tests docs/connections.md
git commit -m "Fork: --bus-nets routes a stated group of nets as one bus; bus_groups in the summary"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
git push fork placemat/connections
```

---

## Task 7: placemat: surface tests and the unused-code check

**Files:**
- Create: `$WT/tests/test_cli_surface.py`, `$WT/tests/surface/cli.txt`
- Create: `$WT/tests/test_settings_surface.py`, `$WT/tests/surface/settings.txt`
- Create: `$WT/tests/test_docs_removed.py`, `$WT/tests/surface/removed.txt`
- Create: `$WT/tests/test_unused_code.py`, `$WT/tools/release/vulture_allow.py`
- Modify: `$WT/pyproject.toml:20` (dev deps), `$WT/.github/workflows/release.yml` (vulture and the native dead-code build)

**Interfaces:**
- Consumes: `placemat.cli.parser()`, `placemat.settings.Settings.keys()`, `split_key`.
- Produces: `tests/surface/cli.txt` (one `command` or `command --option` per line), `tests/surface/settings.txt`
  (one `section.key` per line), `tests/surface/removed.txt` (one literal per line that no reference doc may contain;
  `#` lines are comments). Every later task that adds or removes an option or setting edits these files on purpose.

- [ ] **Step 1: Write the tests**

`tests/test_cli_surface.py`:

```python
"""Every command and long option `placemat --help` exposes is listed in tests/surface/cli.txt: a removed one must be
gone from both, a new one added to the list on purpose (roadmap, "Keeping dead code out")."""
import argparse
from pathlib import Path

from placemat.cli import parser

LIST = Path(__file__).with_name("surface") / "cli.txt"


def surface() -> list:
    root = parser()
    sub = next(a for a in root._actions if isinstance(a, argparse._SubParsersAction))
    out = set()
    for name, sp in sub.choices.items():
        out.add(name)
        for action in sp._actions:
            out |= {"%s %s" % (name, o) for o in action.option_strings if o.startswith("--") and o != "--help"}
    return sorted(out)


def test_the_cli_surface_is_the_listed_one():
    listed = [l.strip() for l in LIST.read_text().splitlines() if l.strip() and not l.startswith("#")]
    got = surface()
    assert sorted(listed) == got, "added: %s; gone: %s" % (sorted(set(got) - set(listed)), sorted(set(listed) - set(got)))
```

`tests/test_settings_surface.py`:

```python
"""Every `[section] key` the settings accept is listed in tests/surface/settings.txt, and the api.md table is generated
from the same fields (test_settings_docs)."""
from pathlib import Path

from placemat.settings import Settings, split_key

LIST = Path(__file__).with_name("surface") / "settings.txt"


def test_the_settings_surface_is_the_listed_one():
    listed = [l.strip() for l in LIST.read_text().splitlines() if l.strip() and not l.startswith("#")]
    got = sorted("%s.%s" % split_key(k) for k in Settings.keys())
    assert sorted(listed) == got, "added: %s; gone: %s" % (sorted(set(got) - set(listed)), sorted(set(listed) - set(got)))
```

`tests/test_docs_removed.py`:

```python
"""No reference doc names a removed command, option or setting outside the migration notes."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "skills/placemat/SKILL.md", ROOT / "skills/placemat/references/api.md",
        ROOT / "skills/placemat/references/capture.md", ROOT / "README.md"]
REMOVED = [l.strip() for l in (Path(__file__).with_name("surface") / "removed.txt").read_text().splitlines()
           if l.strip() and not l.startswith("#")]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_reference_doc_names_a_removed_form(doc):
    text = doc.read_text()
    named = [r for r in REMOVED if r in text]
    assert not named, "%s names removed forms: %s (only migration.md may)" % (doc.name, named)
```

`tests/test_unused_code.py`:

```python
"""vulture finds no unused code in the package beyond tools/release/vulture_allow.py, each entry there with a reason."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_no_unused_code():
    pytest.importorskip("vulture")
    r = subprocess.run([sys.executable, "-m", "vulture", "src/placemat", "tools/release/vulture_allow.py",
                        "--min-confidence", "80"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.stdout.strip() == "", r.stdout
```

- [ ] **Step 2: Generate the lists and install vulture**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -c "
import tests.test_cli_surface as t; print('\n'.join(t.surface()))" > tests/surface/cli.txt
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -c "
from placemat.settings import Settings, split_key; print('\n'.join(sorted('%s.%s' % split_key(k) for k in Settings.keys())))" > tests/surface/settings.txt
printf '# Removed forms: no reference doc but migration.md may name these (one literal per line).\n' > tests/surface/removed.txt
uv pip install --python /home/ben/work/placemat/.venv/bin/python "vulture>=2.11"
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m vulture src/placemat --min-confidence 80 | tee /tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/vulture0.txt | wc -l
```

The vulture install adds a dev tool to the main checkout's venv, which other sessions share; it changes nothing they
import. If vulture reports more than 40 findings, stop and give the user the count and the first 20 before working
through them. Otherwise fix each (delete the dead code) or add it to `tools/release/vulture_allow.py` with a comment
giving the reason (an entry point called by name, a pcbnew callback, a dataclass field read through `asdict`):

```python
"""Names vulture reports that are used, each with the reason vulture cannot see it."""
# from placemat.cli import cmd_route   # called by name from the command table in cli.main
```

- [ ] **Step 3: Run the four tests**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_cli_surface.py tests/test_settings_surface.py tests/test_docs_removed.py tests/test_unused_code.py -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 4: CI and dev dependency**

`pyproject.toml`: `dev = ["pytest>=8", "pytest-xdist>=3", "vulture>=2.11"]`. In `.github/workflows/release.yml` after the
pure-Python suite: `.venv/bin/python -m vulture src/placemat tools/release/vulture_allow.py --min-confidence 80`; after
the native install: `RUSTFLAGS="-D dead_code" cargo build --manifest-path native/Cargo.toml`.

- [ ] **Step 5: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add tests/test_cli_surface.py tests/test_settings_surface.py tests/test_docs_removed.py tests/test_unused_code.py tests/surface tools/release/vulture_allow.py pyproject.toml .github/workflows/release.yml src
git commit -m "Surface tests for the CLI and settings, a docs test for removed forms, and an unused-code check"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 8: placemat: the phase form in placemat.toml

**Files:**
- Create: `$WT/src/placemat/route_phase.py`
- Modify: `$WT/src/placemat/settings.py` (a `route_phase` field after `route_islands` at :393; `_validate` at :794;
  `_ROUTER_OWNED` at :729 gains `--connections`, `--bus-nets`)
- Create: `$WT/tests/test_route_phase_form.py`
- Modify: `$WT/tests/surface/settings.txt` (`route.phase`)

**Interfaces:**
- Consumes: nothing.
- Produces:

```python
# src/placemat/route_phase.py
SELECTORS: tuple            # ("nets", "net_classes", "pairs", "buses", "connections", "current_paths", "interfaces", "net_types")
CAPTURE_SELECTORS: frozenset  # {"pairs", "interfaces", "net_types"}: need nets.layout.json
REST = "rest"               # the selector of a phase with none
CURRENT = "current"
class PhaseError(ValueError): code: str; facts: dict
def phase_error_text(code: str, facts: dict) -> str
@dataclass(frozen=True) class End: part: str; pad: str
@dataclass(frozen=True) class Connection: start: End; end: End
@dataclass(frozen=True) class Phase:
    name: str; selector: str; nets: tuple = (); net_classes: tuple = (); buses: tuple = (); connections: tuple = ()
    interfaces: tuple = (); net_types: tuple = (); width: float | str | None = None; layers: tuple | None = None
    neckdown: bool = True; router_args: tuple = ()
    def key(self) -> dict          # canonical JSON value, for digests
    def record(self) -> dict       # {"name", "selector", "width", "layers", "neckdown"} for reports
def parse_phases(raw) -> tuple[Phase, ...]     # raises PhaseError
def phases_of(cfg) -> tuple[Phase, ...]        # parse_phases(cfg.route_phase)
```

  `Settings.route_phase: tuple` holds the raw tables (tuple of dicts) as TOML gives them, so `Settings.json()` and
  the route digest see exactly what the project wrote.

- [ ] **Step 1: Write the failing test**

`tests/test_route_phase_form.py`:

```python
"""The `[[route.phase]]` form: each selector, the refusals, and the setting as it loads."""
import pytest

from placemat.route_phase import Connection, End, Phase, PhaseError, parse_phases
from placemat.settings import SettingsError, load


def test_each_selector_parses_to_its_phase():
    got = parse_phases([
        {"name": "legs", "current_paths": True, "width": "current", "layers": ["F", "B"], "neckdown": False},
        {"name": "leg", "width": 1.2, "connections": [{"from": {"part": "j1", "pad": "2"}, "to": {"part": "q1", "pad": "VB"}}]},
        {"name": "dp", "pairs": True},
        {"name": "bus", "interfaces": ["Spi", "DISP"], "layers": ["F.Cu"]},
        {"name": "pwr", "net_types": ["Power"], "width": "current"},
        {"name": "rf", "net_classes": ["50Ohm SE"]},
        {"name": "taps", "nets": ["VB*", "!VBX"], "width": 0.3},
        {"name": "grp", "buses": [["D0", "D1"], ["A*"]]},
        {"name": "signals"},
    ])
    assert [p.selector for p in got] == ["current_paths", "connections", "pairs", "interfaces", "net_types",
                                         "net_classes", "nets", "buses", "rest"]
    assert got[0].layers == ("F.Cu", "B.Cu") and got[0].neckdown is False and got[0].width == "current"
    assert got[1].connections == (Connection(End("j1", "2"), End("q1", "VB")),) and got[1].width == 1.2
    assert got[7].buses == (("D0", "D1"), ("A*",))
    assert got[8] == Phase("signals", "rest")


@pytest.mark.parametrize("raw, code", [
    ([{"nets": ["A"]}], "no_name"),
    ([{"name": "a b"}], "bad_name"),
    ([{"name": "x"}, {"name": "x"}], "duplicate_name"),
    ([{"name": "x", "nets": ["A"], "pairs": True}], "two_selectors"),
    ([{"name": "x", "clearance": 0.3}], "clearance_key"),
    ([{"name": "x", "colour": 1}], "unknown_key"),
    ([{"name": "x", "pairs": False}], "flag_true"),
    ([{"name": "x", "width": -1}], "bad_width"),
    ([{"name": "x", "width": "wide"}], "bad_width"),
    ([{"name": "x", "layers": ["Top"]}], "bad_layers"),
    ([{"name": "x", "neckdown": "no"}], "bad_neckdown"),
    ([{"name": "x", "router_args": ["--nets", "A"]}], "router_owned"),
    ([{"name": "x", "router_args": ["--no-power-tap-neckdown"]}], "router_owned"),
    ([{"name": "x", "connections": [{"from": {"part": "j1"}, "to": {"part": "q1", "pad": "1"}}]}], "bad_connection"),
    ([{"name": "x", "nets": []}], "bad_list"),
    ([{"name": "x", "buses": [["A"], "B"]}], "bad_buses"),
])
def test_a_phase_that_cannot_be_obeyed_is_refused_by_code(raw, code):
    with pytest.raises(PhaseError) as e:
        parse_phases(raw)
    assert e.value.code == code and e.value.facts


def test_the_setting_loads_from_arrays_of_tables(tmp_path):
    (tmp_path / "placemat.toml").write_text(
        '[[route.phase]]\nname = "leg"\nwidth = "current"\n[[route.phase.connections]]\n'
        'from = { part = "j1", pad = "2" }\nto = { part = "q1", pad = "VB" }\n\n[[route.phase]]\nname = "signals"\n')
    cfg = load(tmp_path)
    assert [t["name"] for t in cfg.route_phase] == ["leg", "signals"]


def test_a_bad_phase_fails_the_settings_load_naming_the_file(tmp_path):
    (tmp_path / "placemat.toml").write_text('[[route.phase]]\nname = "x"\nnets = ["A"]\npairs = true\n')
    with pytest.raises(SettingsError, match=r"placemat.toml: route.phase 'x': .*one selector"):
        load(tmp_path)


@pytest.mark.parametrize("flag", ["--connections", "--bus-nets"])
def test_the_new_router_flags_are_placemats_own(tmp_path, flag):
    (tmp_path / "placemat.toml").write_text('[route]\nrouter_args = ["%s", "x"]\n' % flag)
    with pytest.raises(SettingsError, match="is set by placemat itself"):
        load(tmp_path)
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_phase_form.py -p no:cacheprovider`
Expected: FAIL, no module `placemat.route_phase`.

- [ ] **Step 3: Implement `route_phase.py`**

```python
"""The routing phases a project states in placemat.toml: `[[route.phase]]` tables, each a named set of connections the
route takes up in the order given, at its own width, on its own layers, with its own router flags. Parsed here into
`Phase` records; what a phase selects on a board is kicad/phase_select.py's, and the engine that runs them is
kicad/route.py's `_route_board`."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re

SELECTORS = ("nets", "net_classes", "pairs", "buses", "connections", "current_paths", "interfaces", "net_types")
CAPTURE_SELECTORS = frozenset(("pairs", "interfaces", "net_types"))
REST = "rest"
CURRENT = "current"
_KEYS = SELECTORS + ("name", "width", "layers", "neckdown", "router_args")
_FLAGS = ("pairs", "current_paths")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_LAYER = re.compile(r"^(F|B|In([1-9]|[12][0-9]|30))\.Cu$")
PHASE_OWNED = {"--no-power-tap-neckdown": "neckdown = false"}

_TEXT = {
    "not_a_table": "route.phase %(index)d: each phase is a table, [[route.phase]]",
    "no_name": "route.phase %(index)d: a phase needs a name",
    "bad_name": "route.phase %(name)r: a name is letters, digits, '-', '_' and '.', starting with a letter or digit",
    "duplicate_name": "route.phase %(name)r: two phases have this name",
    "unknown_key": "route.phase %(name)r: %(key)s is not a phase key; a phase takes %(keys)s",
    "clearance_key": "route.phase %(name)r: clearance is not a phase key: a net keeps its net class's clearance, raised "
                     "by the clearance field of its net type in the capture",
    "two_selectors": "route.phase %(name)r: %(selectors)s: a phase has at most one selector",
    "flag_true": "route.phase %(name)r: %(key)s takes true; leave it out to not select by it",
    "bad_list": "route.phase %(name)r: %(key)s is a list of one or more names, not %(value)r",
    "bad_buses": "route.phase %(name)r: buses is a list of buses, each a list of net names or globs, not %(value)r",
    "bad_connection": "route.phase %(name)r: connection %(index)d: from and to are each {part = \"...\", pad = \"...\"}",
    "bad_width": "route.phase %(name)r: width is a number in mm above 0 or \"current\", not %(value)r",
    "bad_layers": "route.phase %(name)r: layers: %(value)r is not a copper layer (F, In1 to In30, B, or their .Cu names)",
    "bad_neckdown": "route.phase %(name)r: neckdown is true or false, not %(value)r",
    "bad_router_args": "route.phase %(name)r: router_args is a list of strings, not %(value)r",
    "router_owned": "route.phase %(name)r: router_args: %(flag)s is set by placemat itself (%(by)s)",
}


def phase_error_text(code: str, facts: dict) -> str:
    """A PhaseError as a sentence: the edge's rendering of its code and facts."""
    return _TEXT[code] % facts


class PhaseError(ValueError):
    """A phase that cannot be obeyed: `code` (a key of _TEXT, or one phase_select adds) and its `facts`."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, dict(facts)
        super().__init__(phase_error_text(code, self.facts) if code in _TEXT else "%s %r" % (code, self.facts))


@dataclass(frozen=True)
class End:
    part: str           # the part's instance path, or its reference
    pad: str            # a pad number, or the name of a net the part has a pad on (its first, as a PadRef takes it)


@dataclass(frozen=True)
class Connection:
    start: End
    end: End


@dataclass(frozen=True)
class Phase:
    name: str
    selector: str                       # one of SELECTORS, or REST
    nets: tuple = ()
    net_classes: tuple = ()
    buses: tuple = ()
    connections: tuple = ()
    interfaces: tuple = ()
    net_types: tuple = ()
    width: float | str | None = None    # mm on every layer, CURRENT, or None: the net classes'
    layers: tuple | None = None         # None: every layer the route uses
    neckdown: bool = True
    router_args: tuple = ()

    def key(self) -> dict:
        return asdict(self)

    def record(self) -> dict:
        return {"name": self.name, "selector": self.selector, "width": self.width,
                "layers": list(self.layers) if self.layers else None, "neckdown": self.neckdown}


def _layer(name: str, phase: str) -> str:
    full = name if name.endswith(".Cu") else (name.upper() + ".Cu" if name.upper() in ("F", "B")
                                              else "In%s.Cu" % name[2:] if name[:2].lower() == "in" else name)
    if not _LAYER.match(full):
        raise PhaseError("bad_layers", name=phase, value=name)
    return full


def _names(t: dict, key: str, name: str) -> tuple:
    v = t[key]
    if not (isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)):
        raise PhaseError("bad_list", name=name, key=key, value=v)
    return tuple(v)


def _end(raw, name: str, index: int) -> End:
    if not (isinstance(raw, dict) and isinstance(raw.get("part"), str) and isinstance(raw.get("pad"), (str, int))
            and not isinstance(raw.get("pad"), bool) and set(raw) == {"part", "pad"}):
        raise PhaseError("bad_connection", name=name, index=index)
    return End(raw["part"], str(raw["pad"]))


def _one(t, index: int, seen: set) -> Phase:
    from .settings import _ROUTER_OWNED
    if not isinstance(t, dict):
        raise PhaseError("not_a_table", index=index)
    name = t.get("name")
    if not name:
        raise PhaseError("no_name", index=index)
    if not (isinstance(name, str) and _NAME.match(name)):
        raise PhaseError("bad_name", name=name)
    if name in seen:
        raise PhaseError("duplicate_name", name=name)
    seen.add(name)
    if "clearance" in t:
        raise PhaseError("clearance_key", name=name)
    for key in t:
        if key not in _KEYS:
            raise PhaseError("unknown_key", name=name, key=key, keys=", ".join(_KEYS))
    chosen = [k for k in SELECTORS if k in t]
    if len(chosen) > 1:
        raise PhaseError("two_selectors", name=name, selectors=", ".join(chosen))
    selector = chosen[0] if chosen else REST
    kw = {}
    if selector in _FLAGS and t[selector] is not True:
        raise PhaseError("flag_true", name=name, key=selector)
    if selector in ("nets", "net_classes", "interfaces", "net_types"):
        kw[selector] = _names(t, selector, name)
    if selector == "buses":
        v = t["buses"]
        if not (isinstance(v, list) and v and all(isinstance(b, list) and b and all(isinstance(x, str) and x for x in b)
                                                  for b in v)):
            raise PhaseError("bad_buses", name=name, value=v)
        kw["buses"] = tuple(tuple(b) for b in v)
    if selector == "connections":
        v = t["connections"]
        if not (isinstance(v, list) and v):
            raise PhaseError("bad_connection", name=name, index=0)
        kw["connections"] = tuple(Connection(_end(c.get("from") if isinstance(c, dict) else None, name, i),
                                             _end(c.get("to") if isinstance(c, dict) else None, name, i))
                                  for i, c in enumerate(v))
    width = t.get("width")
    if width is not None and not (width == CURRENT or (isinstance(width, (int, float)) and not isinstance(width, bool)
                                                         and width > 0)):
        raise PhaseError("bad_width", name=name, value=width)
    layers = t.get("layers")
    if layers is not None:
        if not (isinstance(layers, list) and layers and all(isinstance(x, str) for x in layers)):
            raise PhaseError("bad_layers", name=name, value=layers)
        layers = tuple(dict.fromkeys(_layer(x, name) for x in layers))
    neckdown = t.get("neckdown", True)
    if not isinstance(neckdown, bool):
        raise PhaseError("bad_neckdown", name=name, value=neckdown)
    args = t.get("router_args", [])
    if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
        raise PhaseError("bad_router_args", name=name, value=args)
    for a in args:
        flag = a.split("=", 1)[0]
        if flag in PHASE_OWNED:
            raise PhaseError("router_owned", name=name, flag=flag, by=PHASE_OWNED[flag])
        if flag.startswith("--") and any(o.startswith(flag) and len(flag) > 2 for o in _ROUTER_OWNED):
            raise PhaseError("router_owned", name=name, flag=flag, by="the phase's selector, layers and width")
    return Phase(name, selector, width=float(width) if isinstance(width, (int, float)) else width, layers=layers,
                 neckdown=neckdown, router_args=tuple(args), **kw)


def parse_phases(raw) -> tuple:
    seen: set = set()
    return tuple(_one(t, i, seen) for i, t in enumerate(raw or ()))


def phases_of(cfg) -> tuple:
    return parse_phases(cfg.route_phase)
```

- [ ] **Step 4: Wire the setting**

`settings.py`, after `route_islands` (:393):

```python
    route_phase: tuple = S((), "list",
        "the routing phases, in order: `[[route.phase]]` tables, each a `name`, at most one selector (`nets`, `net_classes`, "
        "`pairs = true`, `buses`, `connections`, `current_paths = true`, `interfaces`, `net_types`; none takes every "
        "connection still open), and `width` (mm or \"current\"), `layers`, `neckdown`, `router_args`. A route needs at "
        "least one; `placemat settings --example` writes the default phases for a board (api.md \"Routing phases\")")
```

`_validate`, beside the `route_islands` branch:

```python
    if name == "route_phase":
        from .route_phase import PhaseError, parse_phases
        try:
            parse_phases(value)
        except PhaseError as e:
            raise SettingsError("%s: %s" % (path, e)) from None
```

`_ROUTER_OWNED` gains `"--connections"` and `"--bus-nets"`. Add `route.phase` to `tests/surface/settings.txt`.

- [ ] **Step 5: Run the tests**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_phase_form.py tests/test_settings.py tests/test_settings_docs.py tests/test_settings_surface.py tests/test_net_halos.py -n 2 -p no:cacheprovider`
Expected: PASS after regenerating the api.md settings table (`placemat settings --markdown`, pasted between the
markers, as test_settings_docs says).

- [ ] **Step 6: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add src/placemat/route_phase.py src/placemat/settings.py tests/test_route_phase_form.py tests/surface/settings.txt skills/placemat/references/api.md
git commit -m "Routing phases: the [[route.phase]] form and its validation"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 9: placemat: reading `nets.layout.json`

**Files:**
- Create: `$WT/src/placemat/capture_nets.py`
- Create: `$WT/tests/test_capture_nets.py`

**Interfaces:**
- Consumes: the sidecar format of Task 3 (stage 1) and Task 21 (stage 2: `"interfaces"` in `exports`, per-net
  `interfaces`, top-level `interfaces` and `pairs`).
- Produces:

```python
SIDECAR = "nets.layout.json"
@dataclass(frozen=True) class Membership: instance: str; type: str; member: str
@dataclass(frozen=True) class NetRecord: name: str; type: str; fields: dict; interfaces: tuple = ()
    clearance_mm: float | None   # property: fields["clearance"]["value"] when its unit is "mm"
@dataclass(frozen=True) class Instance: path: str; type: str; members: dict   # member path -> net name
@dataclass(frozen=True) class Capture:
    path: str; digest: str; generator: dict; exports: frozenset; nets: dict; instances: dict; pairs: tuple
    def clearances(self) -> dict          # {net: mm} for nets with a clearance field
    def nets_of_types(self, types) -> list
class CaptureError(ValueError): code: str; facts: dict   # codes: unreadable, version, no_netlist, stale
def read_capture(path) -> Capture
def capture_beside(pcb) -> Capture | None   # the sidecar beside a board, None when there is none
```

- [ ] **Step 1: Write the failing test**

`tests/test_capture_nets.py`:

```python
"""nets.layout.json, the capture's facts about each net, written by the Zener fork beside the netlist."""
import hashlib
import json

import pytest

from placemat.capture_nets import CaptureError, capture_beside, read_capture

NETLIST = "(export (version D))\n"


def write(folder, doc=None, netlist=NETLIST, **over):
    (folder / "default.net").write_text(netlist)
    base = {"version": 1, "generator": {"name": "benagricola/pcb", "version": "0.4.52", "git": "abc"},
            "netlist": {"file": "default.net", "sha256": hashlib.sha256(NETLIST.encode()).hexdigest()},
            "exports": ["types", "fields"],
            "nets": {"HV": {"type": "Power", "fields": {"clearance": {"value": 2.0, "unit": "mm"},
                                                        "voltage": {"value": 48.0, "unit": "V"}}},
                     "SIG": {"type": "Net", "fields": {}}}}
    base.update(over)
    (folder / "nets.layout.json").write_text(json.dumps(doc if doc is not None else base))
    return folder / "nets.layout.json"


def test_a_sidecar_gives_each_nets_type_fields_and_clearance(tmp_path):
    cap = read_capture(write(tmp_path))
    assert cap.nets["HV"].type == "Power" and cap.nets["HV"].clearance_mm == 2.0
    assert cap.nets["SIG"].clearance_mm is None
    assert cap.clearances() == {"HV": 2.0}
    assert cap.exports == frozenset({"types", "fields"}) and cap.generator["name"] == "benagricola/pcb"
    assert cap.nets_of_types(["Power"]) == ["HV"]


def test_a_sidecar_from_another_generation_is_refused(tmp_path):
    path = write(tmp_path)
    (tmp_path / "default.net").write_text("(export (version D) (other))\n")
    with pytest.raises(CaptureError) as e:
        read_capture(path)
    assert e.value.code == "stale" and e.value.facts["file"] == "default.net"


@pytest.mark.parametrize("doc, code", [({"version": 2}, "version"), ("not json", "unreadable")])
def test_an_unknown_or_unreadable_sidecar_is_refused(tmp_path, doc, code):
    write(tmp_path)
    (tmp_path / "nets.layout.json").write_text(doc if isinstance(doc, str) else json.dumps(doc))
    with pytest.raises(CaptureError) as e:
        read_capture(tmp_path / "nets.layout.json")
    assert e.value.code == code


def test_no_sidecar_beside_a_board_is_none(tmp_path):
    (tmp_path / "layout.kicad_pcb").write_text("")
    assert capture_beside(tmp_path / "layout.kicad_pcb") is None
    write(tmp_path)
    assert capture_beside(tmp_path / "layout.kicad_pcb").nets["HV"].type == "Power"


def test_stage_two_instances_and_pairs(tmp_path):
    cap = read_capture(write(tmp_path, exports=["types", "fields", "interfaces"],
                             interfaces={"USB": {"type": "Usb2", "members": {"D.P": "USB_D_P", "D.N": "USB_D_N"}},
                                         "USB.D": {"type": "DiffPair", "members": {"P": "USB_D_P", "N": "USB_D_N"}}},
                             pairs=[{"instance": "USB.D", "p": "USB_D_P", "n": "USB_D_N"}]))
    assert cap.instances["USB.D"].type == "DiffPair" and cap.pairs == (("USB.D", "USB_D_P", "USB_D_N"),)
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_capture_nets.py -p no:cacheprovider`
Expected: FAIL, no module `placemat.capture_nets`.

- [ ] **Step 3: Implement**

```python
"""nets.layout.json: what the capture says about each net, written beside the netlist by the Zener fork's `pcb layout`
(benagricola/pcb, crates/pcb-layout/src/nets_layout.rs): its type and fields, and from the fork's stage 2 the interface
instances it belongs to and the differential pairs. Read here as records; a phase selects by them
(kicad/phase_select.py) and the route takes each net's `clearance` field (kicad/net_clearance.py).

The file names the netlist it was written with and that file's sha256. A sidecar whose digest does not match the
netlist beside it was left by another generation (a stale file from an earlier toolchain) and is refused."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

SIDECAR = "nets.layout.json"
VERSION = 1


class CaptureError(ValueError):
    """A sidecar placemat cannot use: `code` (unreadable, version, no_netlist, stale) and `facts`."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, dict(facts)
        super().__init__("%s: %s %s" % (SIDECAR, code, json.dumps(self.facts, sort_keys=True)))


@dataclass(frozen=True)
class Membership:
    instance: str
    type: str
    member: str


@dataclass(frozen=True)
class NetRecord:
    name: str
    type: str
    fields: dict
    interfaces: tuple = ()

    @property
    def clearance_mm(self) -> float | None:
        f = self.fields.get("clearance")
        return float(f["value"]) if isinstance(f, dict) and f.get("unit") == "mm" else None


@dataclass(frozen=True)
class Instance:
    path: str
    type: str
    members: dict


@dataclass(frozen=True)
class Capture:
    path: str
    digest: str
    generator: dict
    exports: frozenset
    nets: dict
    instances: dict
    pairs: tuple

    def clearances(self) -> dict:
        return {n: r.clearance_mm for n, r in sorted(self.nets.items()) if r.clearance_mm is not None}

    def nets_of_types(self, types) -> list:
        wanted = set(types)
        return sorted(n for n, r in self.nets.items() if r.type in wanted)


def read_capture(path) -> Capture:
    path = Path(path)
    raw = path.read_bytes()
    try:
        doc = json.loads(raw)
    except ValueError:
        raise CaptureError("unreadable", path=str(path)) from None
    if not isinstance(doc, dict) or doc.get("version") != VERSION:
        raise CaptureError("version", path=str(path), version=doc.get("version") if isinstance(doc, dict) else None,
                           reads=VERSION)
    netlist = path.parent / doc["netlist"]["file"]
    if not netlist.is_file():
        raise CaptureError("no_netlist", path=str(path), file=doc["netlist"]["file"])
    if hashlib.sha256(netlist.read_bytes()).hexdigest() != doc["netlist"]["sha256"]:
        raise CaptureError("stale", path=str(path), file=doc["netlist"]["file"], generator=doc.get("generator"))
    nets = {name: NetRecord(name, r["type"], dict(r.get("fields") or {}),
                            tuple(Membership(m["instance"], m["type"], m["member"]) for m in r.get("interfaces") or ()))
            for name, r in doc["nets"].items()}
    instances = {p: Instance(p, r["type"], dict(r["members"])) for p, r in (doc.get("interfaces") or {}).items()}
    pairs = tuple((p["instance"], p["p"], p["n"]) for p in doc.get("pairs") or ())
    return Capture(str(path), hashlib.sha256(raw).hexdigest(), dict(doc.get("generator") or {}),
                   frozenset(doc.get("exports") or ()), nets, instances, pairs)


def capture_beside(pcb) -> Capture | None:
    path = Path(pcb).with_name(SIDECAR)
    return read_capture(path) if path.is_file() else None
```

- [ ] **Step 4: Run the test**

Run: same as step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add src/placemat/capture_nets.py tests/test_capture_nets.py
git commit -m "Routing phases: read the capture's nets.layout.json, refusing one from another generation"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 10: placemat: what a phase selects, and at what width

**Files:**
- Create: `$WT/src/placemat/kicad/phase_select.py`
- Create: `$WT/tests/test_phase_select.py`

**Interfaces:**
- Consumes: `route_phase.Phase`, `PhaseError`, `CAPTURE_SELECTORS`, `CURRENT`, `REST` (Task 8);
  `capture_nets.Capture` (Task 9); `checks.carriers_of(geometry)` (checks.py:1682), `checks.ipc2221_width_mm`,
  `checks._layer_oz`, `checks._layer_k` (checks.py:813-840); `BoardGeometry.footprint`, `.pad`, `.netclasses`,
  `.layers`, `.copper_mm`, `.min_track_width`.
- Produces:

```python
@dataclass(frozen=True) class Task:
    net: str; start: tuple; end: tuple          # (ref, pad number)
    widths: tuple                               # ((layer name, mm), ...) in the phase's layer order
    amps: float | None = None
    def record(self) -> dict                    # {"net", "from": {"ref", "pad"}, "to": {...}, "widths": {layer: mm}, "amps"}
@dataclass(frozen=True) class Selection:
    phase: str; selector: str
    nets: tuple = ()        # whole nets
    tasks: tuple = ()       # Task
    pairs: tuple = ()       # ((p, n), ...)
    buses: tuple = ()       # ((net, ...), ...)
    pour_nets: tuple = ()   # selected nets served by a pour, routed one at a time (D15)
    width: float | None = None   # a numeric width for whole nets
    layers: tuple = ()      # the layers its tracks may use
    rest: bool = False      # every open net not excluded
def select(phase, geometry, capture, *, open_nets: set, excluded: set, pour_nets: set, route_layers: list,
           rise_c: float, copper_oz: float) -> Selection          # raises PhaseError
def net_matches(name: str, pattern: str) -> bool
def layer_widths(amps: float, layers, geometry, rise_c: float, copper_oz: float) -> tuple
def current_tasks(geometry, nets, layers, rise_c, copper_oz) -> tuple[tuple, list]   # (tasks, nets with < 2 carriers)
```

  New PhaseError codes (texts added to `route_phase._TEXT`): `needs_capture` (facts name, selector, generator),
  `not_on_board` (name, kind: net|class|part|pad|type|instance, value), `layer_missing` (name, layers, board_layers),
  `no_current` (name, nets or connections), `ends_on_two_nets` (name, index, nets).

- [ ] **Step 1: Write the failing test**

`tests/test_phase_select.py`:

```python
"""What a phase selects on a board (kicad/phase_select.py)."""
from dataclasses import replace

import pytest

from placemat.board_geometry import NetClass
from placemat.kicad.phase_select import current_tasks, layer_widths, net_matches, select
from placemat.route_phase import PhaseError, parse_phases
from tests.fixtures import board_geometry, footprint

LAYERS = ["F.Cu", "B.Cu"]


def board():
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"), fields={"Pm.I": "4A"})
    q1 = footprint("Q1", 20, 10, nets=("VB", "VOUT"), fields={"Pm.I": "4A"})
    u1 = footprint("U1", 30, 20, nets=("VB", "SDA"), fields={"Pm.I": "1mA"})
    r1 = footprint("R1", 30, 30, nets=("SDA", "SCL"))
    r2 = footprint("R2", 35, 30, nets=("SCL", "!RST"))
    g = board_geometry([j1, q1, u1, r1, r2])
    classes = dict(g.netclasses)
    classes["VOUT"] = NetClass("Wide", 0.4, 0.3, 0.6, 0.3)
    return replace(g, netclasses=classes)


def one(raw, capture=None, **kw):
    g = board()
    args = dict(open_nets=set(g.nets), excluded=set(), pour_nets=set(), route_layers=LAYERS, rise_c=10.0, copper_oz=1.0)
    args.update(kw)
    return select(parse_phases([raw])[0], g, capture, **args)


def test_nets_by_name_and_glob_with_an_exclusion():
    s = one({"name": "p", "nets": ["S*", "!SCL"], "width": 0.3})
    assert s.nets == ("SDA",) and s.width == 0.3 and s.layers == ("F.Cu", "B.Cu")


def test_an_active_low_net_is_named_with_its_escape():
    assert net_matches("!RST", "\\!RST") and not net_matches("RST", "\\!RST")
    assert one({"name": "p", "nets": ["\\!RST"]}).nets == ("!RST",)


def test_a_class_selects_its_nets():
    assert one({"name": "p", "net_classes": ["Wide"]}).nets == ("VOUT",)


def test_only_open_nets_are_selected():
    assert one({"name": "p", "nets": ["S*"]}, open_nets={"SCL"}).nets == ("SCL",)


def test_the_rest_takes_every_open_net_not_excluded_nor_a_pour():
    s = one({"name": "signals"}, excluded={"GND"}, pour_nets={"VB"})
    assert s.rest and "GND" not in s.nets and "VB" not in s.nets and "SDA" in s.nets


def test_a_named_pour_net_is_routed_as_one():
    s = one({"name": "p", "nets": ["VB"]}, pour_nets={"VB"})
    assert s.pour_nets == ("VB",) and s.nets == ()


def test_buses_keep_their_groups():
    assert one({"name": "p", "buses": [["SDA", "SCL"]]}).buses == (("SDA", "SCL"),)


def test_a_connection_resolves_by_pad_number_or_net():
    s = one({"name": "p", "width": 1.0, "connections": [{"from": {"part": "j1", "pad": "1"}, "to": {"part": "Q1", "pad": "VB"}}]})
    (t,) = s.tasks
    assert (t.net, t.start, t.end) == ("VB", ("J1", "1"), ("Q1", "1")) and dict(t.widths) == {"F.Cu": 1.0, "B.Cu": 1.0}


def test_current_paths_size_each_pair_at_the_lesser_current_per_layer():
    s = one({"name": "p", "current_paths": True, "width": "current"})
    by_pair = {(t.start[0], t.end[0]): t for t in s.tasks}
    assert by_pair[("J1", "Q1")].amps == 4.0 and by_pair[("J1", "U1")].amps == pytest.approx(0.001)
    assert dict(by_pair[("J1", "Q1")].widths)["F.Cu"] > dict(by_pair[("J1", "U1")].widths)["F.Cu"]


def test_an_inner_layer_needs_more_width_for_the_same_current():
    g = board()
    outer = dict(layer_widths(4.0, ["F.Cu"], g, 10.0, 1.0))["F.Cu"]
    inner = dict(layer_widths(4.0, ["In1.Cu"], g, 10.0, 1.0))["In1.Cu"]
    assert inner > outer


def test_a_width_is_never_under_the_boards_minimum():
    g = replace(board(), min_track_width=0.2)
    assert dict(layer_widths(0.001, ["F.Cu"], g, 10.0, 1.0))["F.Cu"] == 0.2


def test_current_width_on_a_net_with_one_carrier_is_refused_naming_it():
    with pytest.raises(PhaseError) as e:
        one({"name": "p", "nets": ["SDA"], "width": "current"})
    assert e.value.code == "no_current" and e.value.facts["nets"] == ["SDA"]


@pytest.mark.parametrize("selector", [{"pairs": True}, {"interfaces": ["Spi"]}, {"net_types": ["Power"]}])
def test_capture_selectors_without_a_sidecar_are_refused(selector):
    with pytest.raises(PhaseError) as e:
        one(dict({"name": "p"}, **selector))
    assert e.value.code == "needs_capture"


@pytest.mark.parametrize("raw, kind", [
    ({"name": "p", "nets": ["NOPE"]}, "net"), ({"name": "p", "nets": ["Z*"]}, "net"),
    ({"name": "p", "net_classes": ["Gone"]}, "class"),
    ({"name": "p", "connections": [{"from": {"part": "X9", "pad": "1"}, "to": {"part": "Q1", "pad": "1"}}]}, "part"),
])
def test_a_selector_that_names_nothing_on_the_board_is_refused(raw, kind):
    with pytest.raises(PhaseError) as e:
        one(raw)
    assert e.value.code == "not_on_board" and e.value.facts["kind"] == kind


def test_layers_the_board_lacks_are_refused_naming_its_layers():
    with pytest.raises(PhaseError) as e:
        one({"name": "p", "nets": ["SDA"], "layers": ["In2"]})
    assert e.value.code == "layer_missing" and e.value.facts["board_layers"] == ["F.Cu", "B.Cu"]


def test_current_tasks_span_every_pad_of_both_parts():
    two = footprint("Q2", 20, 10, nets=("VB", "VB"), fields={"Pm.I": "4A"})
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"), fields={"Pm.I": "4A"})
    tasks, missing = current_tasks(board_geometry([j1, two]), ["VB"], LAYERS, 10.0, 1.0)
    assert {(t.start, t.end) for t in tasks} == {(("J1", "1"), ("Q2", "1")), (("J1", "1"), ("Q2", "2"))} and not missing
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_phase_select.py -p no:cacheprovider`
Expected: FAIL, no module `placemat.kicad.phase_select`.

- [ ] **Step 3: Implement**

```python
"""What one routing phase routes on a board (route_phase.Phase -> Selection): whole nets, pad-to-pad tasks, differential
pairs and buses, the layers its tracks may use, and the width each is asked at. Pure: the board is a BoardGeometry, the
capture a capture_nets.Capture or None. The router calls are kicad/phase_run.py's."""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch

from ..route_phase import CAPTURE_SELECTORS, CURRENT, REST, PhaseError


@dataclass(frozen=True)
class Task:
    net: str
    start: tuple
    end: tuple
    widths: tuple
    amps: float | None = None

    def record(self) -> dict:
        return {"net": self.net, "from": {"ref": self.start[0], "pad": self.start[1]},
                "to": {"ref": self.end[0], "pad": self.end[1]}, "widths": dict(self.widths), "amps": self.amps}


@dataclass(frozen=True)
class Selection:
    phase: str
    selector: str
    nets: tuple = ()
    tasks: tuple = ()
    pairs: tuple = ()
    buses: tuple = ()
    pour_nets: tuple = ()
    width: float | None = None
    layers: tuple = ()
    rest: bool = False


def net_matches(name: str, pattern: str) -> bool:
    """KRT's own reading of a net pattern (net_queries.py:20-50): an fnmatch glob; a leading `\\!` names a net whose
    name starts with '!'; a pattern with no '/' also matches the last part of a sheet path."""
    if pattern.startswith("\\!"):
        pattern = pattern[1:]
    if fnmatch.fnmatchcase(name, pattern):
        return True
    return "/" not in pattern and "/" in name and fnmatch.fnmatchcase(name.rsplit("/", 1)[-1], pattern)


def _expand(phase, patterns, nets) -> list:
    keep, drop = [], []
    for p in patterns:
        (drop if p.startswith("!") else keep).append(p[1:] if p.startswith("!") else p)
    out = set()
    for p in keep:
        hit = {n for n in nets if net_matches(n, p)}
        if not hit:
            raise PhaseError("not_on_board", name=phase.name, kind="net", value=p)
        out |= hit
    for p in drop:
        out -= {n for n in out if net_matches(n, p)}
    return sorted(out)


def layer_widths(amps: float, layers, geometry, rise_c: float, copper_oz: float) -> tuple:
    """The width `amps` needs on each layer by IPC-2221 at `rise_c`, the inner constant on an inner layer and each
    layer's own copper weight (checks._need_mm's sizing), never under the board's minimum track width."""
    from ..checks import _layer_k, _layer_oz, ipc2221_width_mm
    from ..values import CopperLayer
    out = []
    for name in layers:
        layer = CopperLayer.of(name)
        w = ipc2221_width_mm(amps, rise_c, _layer_oz(layer, geometry.copper_mm, copper_oz), _layer_k(layer))
        out.append((name, round(max(w, geometry.min_track_width or 0.0), 4)))
    return tuple(out)


def _pads_on(geometry, ref, net) -> list:
    return sorted({p.number for p in geometry.footprint(ref).pads if p.net == net}, key=lambda n: (len(n), n))


def current_tasks(geometry, nets, layers, rise_c, copper_oz) -> tuple:
    """Per net, each pair of the parts that carry current on it (`Pm.I`, checks.carriers_of), at the lesser current:
    tasks from the first pad of each to every pad of the other, so every pad of both parts on the net is joined (D14).
    Returns (tasks, the nets with fewer than two carriers)."""
    from ..checks import carriers_of
    carriers = carriers_of(geometry)
    tasks, missing = [], []
    for net in sorted(nets):
        on = carriers.get(net, {})
        if len(on) < 2:
            missing.append(net)
            continue
        refs = sorted(on)
        for i, a in enumerate(refs):
            for b in refs[i + 1:]:
                amps = min(on[a], on[b])
                widths = layer_widths(amps, layers, geometry, rise_c, copper_oz)
                pa, pb = _pads_on(geometry, a, net), _pads_on(geometry, b, net)
                tasks.append(Task(net, (a, pa[0]), (b, pb[0]), widths, amps))
                tasks += [Task(net, (a, x), (b, pb[0]), widths, amps) for x in pa[1:]]
                tasks += [Task(net, (a, pa[0]), (b, y), widths, amps) for y in pb[1:]]
    return tuple(tasks), missing


def _end(phase, geometry, end, index):
    try:
        fp = geometry.footprint(end.part)
    except KeyError:
        raise PhaseError("not_on_board", name=phase.name, kind="part", value=end.part) from None
    key = int(end.pad) if end.pad.isdigit() else end.pad
    try:
        pad = fp.pad(key)
    except KeyError:
        raise PhaseError("not_on_board", name=phase.name, kind="pad", value="%s %s" % (end.part, end.pad)) from None
    return fp.ref, pad.number, pad.net


def _class_widths(geometry, net, layers) -> tuple:
    nc = geometry.netclasses.get(net)
    return tuple((l, nc.track_width if nc else geometry.min_track_width or 0.2) for l in layers)


def select(phase, geometry, capture, *, open_nets, excluded, pour_nets, route_layers, rise_c, copper_oz) -> Selection:
    board_layers = [l.value for l in geometry.layers]
    layers = tuple(phase.layers or route_layers)
    missing = [l for l in layers if l not in board_layers]
    if missing:
        raise PhaseError("layer_missing", name=phase.name, layers=missing, board_layers=board_layers)
    if phase.selector in CAPTURE_SELECTORS:
        need = "types" if phase.selector == "net_types" else "interfaces"
        if capture is None or need not in capture.exports:
            raise PhaseError("needs_capture", name=phase.name, selector=phase.selector,
                             generator=capture.generator if capture is not None else None)
    numeric = phase.width if isinstance(phase.width, float) else None
    pads = {}
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.net:
                pads[p.net] = pads.get(p.net, 0) + 1
    routable = {n for n, k in pads.items() if k >= 2}
    base = dict(phase=phase.name, selector=phase.selector, layers=layers)

    def whole(names):
        names = [n for n in names if n in open_nets and n not in excluded]
        if phase.width == CURRENT:
            tasks, short = current_tasks(geometry, names, layers, rise_c, copper_oz)
            if short:
                raise PhaseError("no_current", name=phase.name, nets=short)
            return Selection(tasks=tasks, **base)
        return Selection(nets=tuple(n for n in names if n not in pour_nets),
                         pour_nets=tuple(n for n in names if n in pour_nets), width=numeric, **base)

    if phase.selector == REST:
        nets = sorted(n for n in routable if n in open_nets and n not in excluded and n not in pour_nets)
        return Selection(nets=tuple(nets), rest=True, width=numeric, **base)
    if phase.selector == "nets":
        return whole(_expand(phase, phase.nets, geometry.nets))
    if phase.selector == "net_classes":
        names = []
        for cls in phase.net_classes:
            hit = sorted(n for n, nc in geometry.netclasses.items() if nc.name == cls)
            if not hit:
                raise PhaseError("not_on_board", name=phase.name, kind="class", value=cls)
            names += hit
        return whole(sorted(set(names)))
    if phase.selector == "net_types":
        names = capture.nets_of_types(phase.net_types)
        for t in phase.net_types:
            if not capture.nets_of_types([t]):
                raise PhaseError("not_on_board", name=phase.name, kind="type", value=t)
        return whole([n for n in names if n in routable])
    if phase.selector == "buses":
        buses = tuple(tuple(n for n in _expand(phase, bus, geometry.nets) if n in open_nets and n not in excluded)
                      for bus in phase.buses)
        return Selection(buses=tuple(b for b in buses if b), width=numeric, **base)
    if phase.selector == "current_paths":
        from ..checks import carriers_of
        nets = sorted(n for n, on in carriers_of(geometry).items() if len(on) >= 2 and n not in excluded)
        tasks, _ = current_tasks(geometry, nets, layers, rise_c, copper_oz)
        return Selection(tasks=tasks, **base)
    if phase.selector == "connections":
        from ..checks import carriers_of
        carriers = carriers_of(geometry) if phase.width == CURRENT else {}
        tasks, short = [], []
        for i, c in enumerate(phase.connections):
            a_ref, a_pad, a_net = _end(phase, geometry, c.start, i)
            b_ref, b_pad, b_net = _end(phase, geometry, c.end, i)
            if a_net != b_net:
                raise PhaseError("ends_on_two_nets", name=phase.name, index=i, nets=[a_net, b_net])
            if phase.width == CURRENT:
                on = carriers.get(a_net, {})
                if a_ref not in on or b_ref not in on:
                    short.append({"net": a_net, "from": a_ref, "to": b_ref})
                    continue
                amps = min(on[a_ref], on[b_ref])
                widths = layer_widths(amps, layers, geometry, rise_c, copper_oz)
            else:
                amps = None
                widths = tuple((l, numeric) for l in layers) if numeric else _class_widths(geometry, a_net, layers)
            tasks.append(Task(a_net, (a_ref, a_pad), (b_ref, b_pad), widths, amps))
        if short:
            raise PhaseError("no_current", name=phase.name, connections=short)
        return Selection(tasks=tuple(tasks), **base)
    raise PhaseError("needs_capture", name=phase.name, selector=phase.selector, generator=None)   # pairs, interfaces: Task 22
```

Add to `route_phase._TEXT`:

```python
    "needs_capture": "route.phase %(name)r: %(selector)s needs the capture's nets.layout.json with what it selects by; "
                     "this board's generator (%(generator)s) does not export it: generate the board with the Zener fork",
    "not_on_board": "route.phase %(name)r: no %(kind)s %(value)r on this board",
    "layer_missing": "route.phase %(name)r: the board has no %(layers)s (its copper layers: %(board_layers)s)",
    "no_current": "route.phase %(name)r: width = \"current\" needs a stated current (Pm.I) at both ends; none for %(what)s",
    "ends_on_two_nets": "route.phase %(name)r: connection %(index)d joins two nets, %(nets)s",
```

and make `phase_error_text` fill `what` from `nets` or `connections` (`", ".join(...)`) so the facts stay lists.

- [ ] **Step 4: Run the test**

Run: same as step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add src/placemat/kicad/phase_select.py src/placemat/route_phase.py tests/test_phase_select.py
git commit -m "Routing phases: what each selector takes on a board, and the width per layer it is asked at"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 11: placemat: the router calls of a phase

**Files:**
- Modify: `$WT/src/placemat/kicad/route.py:921-947` (`router_command`), `:1008-1021` (`class_stages` renamed
  `clearance_groups`)
- Create: `$WT/src/placemat/kicad/phase_run.py` (the command planning part; the run is Task 13)
- Create: `$WT/tests/test_phase_commands.py`

**Interfaces:**
- Consumes: `phase_select.Selection`, `Task` (Task 10).
- Produces:

```python
# kicad/route.py
def router_command(python, script, pcb_in, pcb_out, excluded, layers, summary, iterations=None, probe=None,
                   quick=False, nets=None, widths=None, clearances=None, connections=None, bus_nets=None,
                   neckdown=True, extra_args=()) -> list
def clearance_groups(clearances: dict, base: float, nets) -> list          # the old class_stages, same behaviour
REQUIRES = ("route.py:--connections", "route.py:--bus-nets")
def router_capable(rpy, router_dir) -> list        # the REQUIRES the router lacks, from krt_capabilities.py --require
# kicad/phase_run.py
@dataclass(frozen=True) class Call:
    kind: str           # "pairs" | "pour" | "bus" | "nets" | "tasks" | "rest"
    nets: tuple = ()    # the nets it routes; for "rest" the ones it may route
    excluded: tuple = ()   # for "rest": the nets its `*` leaves out
    tasks: tuple = ()   # Task, for "tasks"
    width: float | None = None
    clearance: float | None = None
def plan_calls(sel, clearance_map: dict, base: float, excluded: set) -> list[Call]
def write_connections(tasks, path) -> Path
```

  Order of `plan_calls`: pairs; pour nets one call each (sorted); buses one call each; tasks grouped by
  (clearance, widths) widest clearance first, then widest width first (D5); whole nets per clearance group widest
  first; for a rest selection, the wide-clearance groups by name, then one `*` call excluding them and `excluded`.

- [ ] **Step 1: Write the failing test**

`tests/test_phase_commands.py`:

```python
"""The router calls a phase makes (kicad/phase_run.plan_calls) and their command lines (kicad/route.router_command)."""
import json

from placemat.kicad.phase_run import Call, plan_calls, write_connections
from placemat.kicad.phase_select import Selection, Task
from placemat.kicad.route import clearance_groups, router_command
from placemat.settings import Settings, bind

W5 = (("F.Cu", 0.5), ("B.Cu", 0.5))
W3 = (("F.Cu", 0.3), ("B.Cu", 0.3))


def test_tasks_split_by_clearance_then_width_widest_first():
    tasks = (Task("VB", ("J1", "1"), ("Q1", "1"), W3, 1.0), Task("VB", ("J1", "1"), ("U1", "1"), W5, 4.0),
             Task("HV", ("J2", "1"), ("Q2", "1"), W3, 1.0))
    calls = plan_calls(Selection("p", "connections", tasks=tasks, layers=("F.Cu", "B.Cu")), {"HV": 2.0}, 0.15, set())
    assert [(c.kind, c.clearance, [t.net for t in c.tasks]) for c in calls] == [
        ("tasks", 2.0, ["HV"]), ("tasks", 0.15, ["VB"]), ("tasks", 0.15, ["VB"])]
    assert dict(calls[1].tasks[0].widths)["F.Cu"] == 0.5


def test_the_rest_routes_wide_clearances_by_name_then_everything_else():
    calls = plan_calls(Selection("signals", "rest", nets=("A", "RF", "B"), rest=True), {"RF": 0.2}, 0.15, {"GND"})
    assert [(c.kind, c.nets) for c in calls[:1]] == [("nets", ("RF",))]
    assert calls[1].kind == "rest" and set(calls[1].excluded) == {"GND", "RF"}


def test_pairs_pours_and_buses_each_route_in_their_own_calls():
    sel = Selection("p", "nets", nets=("S",), pour_nets=("VB", "GND"), layers=("F.Cu",))
    assert [c.kind for c in plan_calls(sel, {}, 0.15, set())] == ["pour", "pour", "nets"]
    sel = Selection("b", "buses", buses=(("D0", "D1"), ("A0", "A1")))
    assert [c.nets for c in plan_calls(sel, {}, 0.15, set())] == [("D0", "D1"), ("A0", "A1")]


def test_the_connections_file_is_structured(tmp_path):
    p = write_connections((Task("!RST", ("U1", "3"), ("J1", "1"), W5, None),), tmp_path / "c.json")
    assert json.loads(p.read_text()) == [{"net": "!RST", "from": {"ref": "U1", "pad": "3"}, "to": {"ref": "J1", "pad": "1"},
                                          "widths": {"F.Cu": 0.5, "B.Cu": 0.5}}]


def test_a_call_with_connections_names_no_nets_and_carries_the_phase_flags(tmp_path):
    with bind(Settings(route_router_args=("--via-cost", "50"))):
        cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json",
                             connections=tmp_path / "c.json", neckdown=False, extra_args=("--bus-detection-radius", "3"))
    assert "--nets" not in cmd and cmd[cmd.index("--connections") + 1] == str(tmp_path / "c.json")
    assert "--no-power-tap-neckdown" in cmd
    assert cmd.index("--via-cost") < cmd.index("--bus-detection-radius") < cmd.index("--json-out")


def test_a_bus_call_states_its_nets_and_an_active_low_net_is_escaped(tmp_path):
    with bind(Settings()):
        cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json",
                             nets=["!RST", "D1"], bus_nets=["!RST", "D1"])
    i = cmd.index("--bus-nets")
    assert cmd[i + 1:i + 3] == ["\\!RST", "D1"] and cmd[cmd.index("--nets") + 1] == "\\!RST"


def test_clearance_groups_are_the_class_stages_rule():
    assert clearance_groups({"RF": 0.2, "W": 0.3, "EQ": 0.127}, 0.127, {"RF", "W", "EQ", "S"}) == [(0.3, ["W"]), (0.2, ["RF"])]
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_phase_commands.py -p no:cacheprovider`
Expected: FAIL, no module `placemat.kicad.phase_run`.

- [ ] **Step 3: Implement**

`route.py`, replacing `router_command` (:921-947):

```python
def _net_arg(name: str) -> str:
    """A net name as KRT's --nets reads it: a leading '!' is an exclusion there, so a net named '!RST' is written
    '\\!RST' (net_queries.py:20-50)."""
    return "\\" + name if name.startswith("!") else name


def router_command(python, script, pcb_in, pcb_out, excluded, layers, summary,
                   iterations: int | None = None, probe: int | None = None, quick: bool = False,
                   nets=None, widths=None, clearances: Path | None = None, connections: Path | None = None,
                   bus_nets=None, neckdown: bool = True, extra_args=()) -> list:
    """The router's command line. `nets` routes those alone rather than every net but the excluded; `connections`
    (a file, phase_run.write_connections) routes given pad pairs instead and names no nets; `bus_nets` routes `nets`
    as one stated bus (`--bus-nets`); `widths` ({net: mm}) sets whole nets' widths over the netclass's;
    `neckdown` False turns the router's pad neck-down off for this call; `extra_args` are a phase's own router flags,
    after `[route] router_args`. `clearances` is the per-net clearance map placemat wrote (net_clearance.py)."""
    if connections is not None:
        chosen = []
    elif nets is not None:
        chosen = ["--nets"] + [_net_arg(n) for n in sorted(nets)]
    else:
        chosen = ["--nets", "*"] + ["!" + n for n in sorted(excluded)]
    cmd = _launch(python, script) + [str(pcb_in), str(pcb_out)] + chosen + \
          ["--layers"] + list(layers) + ["--escalation", "off"] + \
          ["--keep-input-copper"] + _tuning()      # the script's copper is its intent: no cleanup pass removes it
    if connections is not None:
        cmd += ["--connections", str(connections)]
    if bus_nets:
        cmd += ["--bus-nets"] + [_net_arg(n) for n in bus_nets]
    if widths:
        named = sorted(widths)
        cmd += ["--power-nets"] + [_net_arg(n) for n in named] + ["--power-nets-widths"] + ["%g" % widths[n] for n in named]
    if not neckdown:
        cmd.append("--no-power-tap-neckdown")
    if not active_settings().route_smoothing:
        cmd.append("--no-smoothing")
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    if probe is not None:
        cmd += ["--max-probe-iterations", str(probe)]
    if clearances is not None:
        cmd += ["--net-clearances", str(clearances)]
    return cmd + list(active_settings().route_router_args) + list(extra_args) + ["--json-out", str(summary)]
```

Check `main_pass_nets`' '!NET' handling (route.py:892-918) still describes what a `*` call matches; the exclusion
form keeps the '!' unescaped there, as today. Rename `class_stages` to `clearance_groups` (body unchanged) and its
two callers. Add:

```python
REQUIRES = ("route.py:--connections", "route.py:--bus-nets")


def router_capable(rpy, router_dir) -> list:
    """The REQUIRES this router lacks (KRT krt_capabilities.py --require, which exits non-zero listing them): a router
    older than the fork's phase work is refused by name rather than failing in a call."""
    r = subprocess.run([str(rpy), str(Path(router_dir) / "krt_capabilities.py"), "--require", *REQUIRES],
                       capture_output=True, text=True, cwd=str(router_dir), timeout=60)
    return [] if r.returncode == 0 else [x for x in REQUIRES if x.split(":", 1)[1] in r.stdout + r.stderr]
```

`phase_run.py`:

```python
"""One routing phase's router calls, in order, each on the board the one before it left with its copper locked, and the
phase's own judgement (closure and widths, Task 13/14). The calls are planned here from a Selection
(kicad/phase_select.py); a phase holding nets of several clearances routes one call per clearance, widest first,
because KRT spaces a whole call at the largest clearance among its nets (routing_config.py:473-485)."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .route import clearance_groups


@dataclass(frozen=True)
class Call:
    kind: str
    nets: tuple = ()
    excluded: tuple = ()
    tasks: tuple = ()
    width: float | None = None
    clearance: float | None = None


def write_connections(tasks, path) -> Path:
    path = Path(path)
    path.write_text(json.dumps([{"net": t.net, "from": {"ref": t.start[0], "pad": t.start[1]},
                                 "to": {"ref": t.end[0], "pad": t.end[1]}, "widths": dict(t.widths)} for t in tasks],
                               indent=1) + "\n")
    return path


def plan_calls(sel, clearance_map: dict, base: float, excluded: set) -> list:
    calls = []
    if sel.pairs:
        calls.append(Call("pairs", tuple(n for pair in sel.pairs for n in pair)))
    calls += [Call("pour", (n,), width=sel.width) for n in sorted(sel.pour_nets)]
    calls += [Call("bus", tuple(b), width=sel.width) for b in sel.buses]
    if sel.tasks:
        def clr(t):
            return max(base, clearance_map.get(t.net, base))
        keys = sorted({(clr(t), t.widths) for t in sel.tasks}, key=lambda k: (-k[0], -max(w for _, w in k[1])))
        calls += [Call("tasks", tasks=tuple(t for t in sel.tasks if (clr(t), t.widths) == k), clearance=k[0]) for k in keys]
    if sel.nets:
        groups = clearance_groups(clearance_map, base, sel.nets)
        wide = {n for _, ns in groups for n in ns}
        calls += [Call("nets", tuple(ns), width=sel.width, clearance=c) for c, ns in groups]
        rest = tuple(n for n in sel.nets if n not in wide)
        if sel.rest:
            calls.append(Call("rest", rest, excluded=tuple(sorted(set(excluded) | wide)), width=sel.width, clearance=base))
        elif rest:
            calls.append(Call("nets", rest, width=sel.width, clearance=base))
    return calls
```

- [ ] **Step 4: Run the tests**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_phase_commands.py tests/test_route_command.py tests/test_route_class_stages.py -n 2 -p no:cacheprovider`
Expected: PASS (test_route_class_stages imports the renamed function: update its import).

- [ ] **Step 5: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add src/placemat/kicad/route.py src/placemat/kicad/phase_run.py tests/test_phase_commands.py tests/test_route_class_stages.py
git commit -m "Routing phases: the router calls a phase makes, with --connections, --bus-nets and its own flags"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 12: placemat: the kept-result chain over phases

**Files:**
- Modify: `$WT/src/placemat/kicad/route_state.py` (whole file)
- Modify: `$WT/tests/test_route_resume.py:49-91` (the state-file tests)

**Interfaces:**
- Consumes: nothing.
- Produces:

```python
VERSION = 2
FINAL = ("router*", "routed*", "drc_after.json", "route.json", "route_record.json", "route_summary.json")
class RouteState:
    def __init__(self, work, resume: bool = True)
    def set_order(self, names: list) -> None     # the phases of this route, in order; a saved phase not among them,
                                                 # or out of its place, is dropped with every one after it
    def result(self, name: str, digest_: str)    # the saved result, or None
    def record(self, name: str, digest_: str, result: dict) -> None
    def drop_from(self, name: str) -> None       # forget name and every later phase, and delete their files p<i>_* and FINAL
    finished: list                               # names in order
def files_of(index: int) -> tuple                # ("p%d_*" % index,)
def digest(*parts) -> str; def file_digest(path) -> str     # unchanged
```

- [ ] **Step 1: Rewrite the state-file tests to fail**

Replace `tests/test_route_resume.py:49-91` with:

```python
def test_a_finished_phase_is_found_by_its_digest_and_only_by_it(tmp_path):
    s = RouteState(tmp_path)
    s.set_order(["legs", "signals"])
    s.record("legs", "d1", {"board": "p0_0.kicad_pcb", "seconds": 2.0})
    again = RouteState(tmp_path)
    again.set_order(["legs", "signals"])
    assert again.result("legs", "d1") == {"board": "p0_0.kicad_pcb", "seconds": 2.0}
    assert again.result("legs", "other") is None and again.result("signals", "d1") is None


def test_dropping_a_phase_drops_it_its_files_and_every_phase_after_it(tmp_path):
    s = RouteState(tmp_path)
    s.set_order(["a", "b", "c"])
    for i, name in enumerate("abc"):
        (tmp_path / ("p%d_0.kicad_pcb" % i)).write_text("x")
        s.record(name, "d" + name, {})
    (tmp_path / "routed.kicad_pcb").write_text("x")
    s.drop_from("b")
    assert s.finished == ["a"] and (tmp_path / "p0_0.kicad_pcb").exists()
    assert not (tmp_path / "p1_0.kicad_pcb").exists() and not (tmp_path / "p2_0.kicad_pcb").exists()
    assert not (tmp_path / "routed.kicad_pcb").exists()


def test_a_reordered_or_renamed_phase_list_keeps_only_the_common_head(tmp_path):
    s = RouteState(tmp_path)
    s.set_order(["a", "b", "c"])
    for name in "abc":
        s.record(name, "d", {})
    again = RouteState(tmp_path)
    again.set_order(["a", "c", "b"])
    assert again.finished == ["a"]


def test_a_state_file_of_the_old_stages_is_no_state(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"version": 1, "stages": {"pairs": {"digest": "d", "result": {}}}}))
    s = RouteState(tmp_path)
    s.set_order(["pairs"])
    assert s.finished == []


def test_without_resume_everything_is_dropped(tmp_path):
    (tmp_path / "p0_0.kicad_pcb").write_text("x")
    RouteState(tmp_path, resume=False)
    assert not (tmp_path / "p0_0.kicad_pcb").exists()
```

Delete `test_the_pairs_outcome_survives_the_state_file` here (Task 25 deletes `Pairs.to_dict` with the stage code if
nothing else uses it). The rig tests below it (`rig`, :93 on) are rewritten in Task 13.

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_resume.py -k "phase or state_file or without_resume" -p no:cacheprovider`
Expected: FAIL, `RouteState` has no `set_order`.

- [ ] **Step 3: Implement**

```python
"""What a route keeps in its work folder so a stop or a failure costs only the phase in hand: `state.json` names each
finished routing phase with the digest of everything its result depends on, chained from the phase before it (the
board and its rules, the capture, the route's settings, the earlier phases' keys, the phase's own definition, the
router's and placemat's versions). A rerun whose digest for a phase matches takes that phase's saved result instead of
routing it again; the first phase that does not match drops itself, its files and every later phase's, and routes.

Phase i's files are `p<i>_*`; what the end of the route makes (FINAL) goes with any dropped phase. Only whole phases
are kept: inside a router call nothing is."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

VERSION = 2
FINAL = ("router*", "routed*", "drc_after.json", "route.json", "route_record.json", "route_summary.json")


def digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def file_digest(path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def files_of(index: int) -> tuple:
    return ("p%d_*" % index,)


class RouteState:
    def __init__(self, work, resume: bool = True):
        self.work = Path(work)
        self.order: list = []
        self.phases: dict = {}
        self._saved_order: list = []
        if not resume:
            shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir(parents=True, exist_ok=True)
        if resume:
            self._load()

    @property
    def path(self) -> Path:
        return self.work / "state.json"

    @property
    def finished(self) -> list:
        return [n for n in self.order if n in self.phases]

    def _load(self) -> None:
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(doc, dict) and doc.get("version") == VERSION and isinstance(doc.get("phases"), dict):
            self._saved_order = [n for n in doc.get("order", []) if isinstance(n, str)]
            self.phases = {k: v for k, v in doc["phases"].items() if isinstance(v, dict)}

    def set_order(self, names) -> None:
        self.order = list(names)
        head = 0
        while head < min(len(self.order), len(self._saved_order)) and self.order[head] == self._saved_order[head]:
            head += 1
        keep = set(self.order[:head])
        for name in list(self.phases):
            if name not in keep:
                self.phases.pop(name)
        self._delete_from(head)
        self._saved_order = list(self.order)
        self._save()

    def _save(self) -> None:
        tmp = self.path.with_name("state.json.tmp")
        tmp.write_text(json.dumps({"version": VERSION, "order": self.order, "phases": self.phases}, indent=1) + "\n")
        os.replace(tmp, self.path)

    def result(self, name: str, digest_: str):
        saved = self.phases.get(name)
        return saved["result"] if saved is not None and saved.get("digest") == digest_ else None

    def record(self, name: str, digest_: str, result: dict) -> None:
        self.phases[name] = {"digest": digest_, "result": result}
        self._save()

    def _delete_from(self, index: int) -> None:
        last = len(self._saved_order) + len(self.order)       # every index either phase list used
        patterns = [p for i in range(index, max(index, last)) for p in files_of(i)] + list(FINAL)
        for pattern in patterns:
            for p in self.work.glob(pattern):
                try:
                    p.unlink() if p.is_file() else shutil.rmtree(p)
                except OSError:
                    pass

    def drop_from(self, name: str) -> None:
        index = self.order.index(name)
        for later in self.order[index:]:
            self.phases.pop(later, None)
        self._delete_from(index)
        self._save()
```

- [ ] **Step 4: Run them**

Run: same as step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add src/placemat/kicad/route_state.py tests/test_route_resume.py
git commit -m "Routing phases: the route's kept results chain over the project's phases"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 13: placemat: the phase engine

**Files:**
- Modify: `$WT/src/placemat/kicad/route.py:1047-1330` (`_route_board`), `:82-235` (`RouteReport`: `phases`,
  `phases_without_copper`), `:648-731` (`route_pairs` takes a file `stem`), new `route_pour_net` beside
  `route_islands` (:950-994), new `RouteRefused`
- Modify: `$WT/src/placemat/kicad/phase_run.py` (`PhaseContext`, `PhaseOutcome`, `run_phase`, `joined_ends`,
  `phase_record`)
- Modify: `$WT/src/placemat/route_progress.py:19, 88-130` (no fixed `STAGES`; a pair call's aliases renamed in any phase)
- Modify: `$WT/src/placemat/cli.py:703-760` (`cmd_route`: `pour_nets`, refusals), `$WT/src/placemat/runner.py:743-760`,
  `$WT/src/placemat/explore.py:206-231, 703-745, 912-956` (`Routing.capture`, `pour_nets`)
- Create: `$WT/tests/test_route_phases.py`
- Modify (migrate to phases, Interfaces below): `tests/test_route_resume.py` (rig tests from :93),
  `tests/test_route_events.py`, `tests/test_route_class_stages.py` (rig tests deleted; the `clearance_groups` unit
  test stays), `tests/test_route_islands.py` (route-driven tests become pour-net phase tests; parsing tests stay for
  Task 25), `tests/test_pair_layers.py` (route-driven tests deleted), `tests/test_route_pairs.py` (route-driven tests
  deleted; Task 22 adds capture-based ones), `tests/test_net_halos.py` (rig tests replaced by one refusal test; Task 16
  adds capture-based ones), `tests/test_route_footprint_copper.py`, `tests/test_route_breakout.py`,
  `tests/test_route_pours.py`, `tests/test_explore_route.py`
- Create: `$WT/tests/phase_helpers.py`
- Docs: `skills/placemat/references/api.md` (a "Routing phases" section replacing the stage description at
  :4009-4050), `skills/placemat/SKILL.md` (routing points to phases), `skills/placemat/references/migration.md`
  ("## Unreleased": a breaking "Changed" entry: a route needs `[[route.phase]]`, with the default block)

**Interfaces:**
- Consumes: Tasks 8-12.
- Produces:

```python
# kicad/route.py
class RouteRefused(ValueError): code: str; facts: dict      # codes: no_phases, legacy_setting, unknown_phase, capture, router_old
def refused_text(code: str, facts: dict) -> str
def route_board(pcb, work, exclude_nets=(), layers=None, router_dir_override=None, quick=False, iterations=None,
                probe=None, timeout=None, resume=True, board_info=None, on_setup=None, phases=None, upto=None,
                only=False, pour_nets=(), capture_path=None) -> RouteReport
    # phases: a tuple of route_phase.Phase, None: the bound settings'; upto: route up to and including this phase;
    # only: with upto, route just that phase on the board as given; pour_nets: nets the board serves by a pour;
    # capture_path: the sidecar, None: beside `pcb`
RouteReport.phases: list[dict]       # phase_record per phase, in order
RouteReport.phases_without_copper: list[str]   # with only: earlier phases none of whose nets has a track on the board (D26)
# kicad/phase_run.py
@dataclass class PhaseContext: rpy; script; router_dir; work; layers; iterations; probe; quick; timeout; env; cfg;
    geometry; clearance_map: dict; base_clearance: float; clearances_file; excluded: set; pour_nets: set; events
@dataclass class PhaseOutcome: board: Path; record: dict; open_nets: dict
def run_phase(ctx, index: int, phase, sel, board: Path, open_before: dict) -> PhaseOutcome
def joined_ends(pcb_path, tasks) -> list[bool]      # KiCad's connectivity: both ends' pads in one connected set
def phase_record(phase, index, sel, open_before, open_after, violated, joined, seconds, calls, pairs=None,
                 connections=(), bus_groups=()) -> dict
    # {"name", "index", "selector", "width", "layers", "neckdown", "asked", "joined", "open", "closure_clean",
    #  "seconds", "reused", "calls", "pairs", "connections", "bus_groups", "widths"}
    # net-level phases: asked/joined count open items (score() over the phase's nets, a net with a real DRC violation
    # counting as still open); task phases: asked/joined count tasks, `open` lists each open task's {net, from, to}.
# tests/phase_helpers.py
SIGNALS = ({"name": "signals"},)                  # the rest phase alone: what the fixed stages' main pass did
def phases(*raw) -> tuple                          # parse_phases(raw or SIGNALS)
```

- [ ] **Step 1: Write the failing engine test**

`tests/phase_helpers.py`:

```python
"""Phases for tests that route: the rest phase alone, which routes what the old main pass did."""
from placemat.route_phase import parse_phases

SIGNALS = ({"name": "signals"},)


def phases(*raw):
    return parse_phases(raw or SIGNALS)
```

`tests/test_route_phases.py`:

```python
"""The phase engine (kicad/route.py _route_board): phases route in order, each on the board the one before left with
its copper locked; a phase's kept result is reused while its key and every earlier key hold; a route with no phases,
or with a setting the phases replaced, is refused. The router is a stand-in that copies its board and logs its call."""
import json
import sys
import textwrap

import pytest

from placemat.kicad import phase_run
from placemat.kicad.route import RouteRefused, RouterFailed, route_board
from placemat.settings import Settings, bind
from tests.conftest import needs_kicad
from tests.phase_helpers import phases
from tests.test_net_halos import _two_part_board

FAKE = textwrap.dedent('''
    import json, os, shutil, sys
    a = sys.argv[1:]
    with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
        f.write(json.dumps(a) + "\\n")
    fail = os.environ.get("FAKE_ROUTER_FAIL")
    if fail and fail in a:
        sys.exit(3)
    shutil.copy(a[0], a[1])
    if "--json-out" in a:
        doc = {}
        if "--connections" in a:
            tasks = json.load(open(a[a.index("--connections") + 1]))
            doc["connections"] = [dict(t, status="routed", reason=None, joined=True, length_mm=1.0,
                                       min_width_mm=t["widths"]) for t in tasks]
        open(a[a.index("--json-out") + 1], "w").write(json.dumps(doc))
''')
CLASSES = 'def net_clearance_map_by_id(pcb_path, nets, design_rules=None):\n    return {}\n'


@pytest.fixture
def rig(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = tmp_path / "krt"
    (krt / ".venv/bin").mkdir(parents=True)
    (krt / ".venv/bin/python").symlink_to(sys.executable)
    (krt / "py_router").mkdir()
    (krt / "py_router/route.py").write_text(FAKE)
    (krt / "py_router/list_nets.py").write_text(CLASSES)
    (krt / "krt_capabilities.py").write_text("import sys\nsys.exit(0)\n")
    (krt / "VERSION").write_text("fake-1\n")
    monkeypatch.setenv("FAKE_ROUTER_LOG", str(tmp_path / "calls"))

    class Rig:
        pcb = _two_part_board(tmp_path)            # FB and VIN open between U1 and J1
        work = tmp_path / "route"

        def calls(self):
            log = tmp_path / "calls"
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

        def route(self, *raw, **kw):
            with bind(Settings()):
                return route_board(self.pcb, self.work, router_dir_override=str(krt), layers=["F.Cu", "B.Cu"],
                                   phases=phases(*raw), **kw)
    return Rig()


def _nets(call):
    if "--nets" not in call:
        return []
    i = call.index("--nets")
    return call[i + 1:call.index("--layers")]


LEG = {"name": "vin", "nets": ["VIN"], "width": 0.5}
FB = {"name": "fb", "nets": ["FB"]}


@needs_kicad
def test_phases_route_in_order_each_on_the_board_the_one_before_left(rig):
    report = rig.route(LEG, FB, {"name": "signals"})
    calls = rig.calls()
    assert [_nets(c) for c in calls[:2]] == [["VIN"], ["FB"]]
    assert calls[0][calls[0].index("--power-nets-widths") + 1] == "0.5"
    assert calls[1][0] == calls[0][1]
    assert [p["name"] for p in report.phases] == ["vin", "fb", "signals"]
    assert set(report.phases[0]) >= {"asked", "joined", "open", "closure_clean", "seconds", "reused", "calls"}


@needs_kicad
def test_each_calls_copper_is_locked_before_the_next_reads_it(rig, monkeypatch):
    locked = []
    real = phase_run.lock_copper
    monkeypatch.setattr(phase_run, "lock_copper", lambda p: (locked.append(str(p)), real(p))[1])
    rig.route(LEG, FB)
    calls = rig.calls()
    assert locked[:2] == [calls[0][1], calls[1][1]]


@needs_kicad
def test_an_edit_to_a_later_phase_reroutes_it_and_after_and_reuses_the_ones_before(rig):
    rig.route(LEG, FB, {"name": "signals"})
    n = len(rig.calls())
    report = rig.route(LEG, dict(FB, width=0.3), {"name": "signals"})
    later = rig.calls()[n:]
    assert [p["reused"] for p in report.phases] == [True, False, False]
    assert _nets(later[0]) == ["FB"]


@needs_kicad
def test_a_route_stopped_in_a_phase_resumes_from_that_phase(rig, monkeypatch):
    monkeypatch.setenv("FAKE_ROUTER_FAIL", "FB")
    with pytest.raises(RouterFailed):
        rig.route(LEG, FB)
    monkeypatch.delenv("FAKE_ROUTER_FAIL")
    n = len(rig.calls())
    report = rig.route(LEG, FB)
    assert [p["reused"] for p in report.phases] == [True, False] and _nets(rig.calls()[n]) == ["FB"]


@needs_kicad
def test_a_connections_phase_writes_its_tasks_and_reads_their_outcome(rig):
    report = rig.route({"name": "leg", "width": 0.4, "connections": [{"from": {"part": "U1", "pad": "3"},
                                                                    "to": {"part": "J1", "pad": "2"}}]})
    call = rig.calls()[0]
    tasks = json.loads(open(call[call.index("--connections") + 1]).read())
    assert tasks == [{"net": "VIN", "from": {"ref": "U1", "pad": "3"}, "to": {"ref": "J1", "pad": "2"},
                      "widths": {"F.Cu": 0.4, "B.Cu": 0.4}}]
    assert report.phases[0]["connections"][0]["status"] == "routed" and report.phases[0]["asked"] == 1


@needs_kicad
def test_upto_routes_the_phases_up_to_the_one_named(rig):
    report = rig.route(LEG, FB, {"name": "signals"}, upto="fb")
    assert [p["name"] for p in report.phases] == ["vin", "fb"] and len(rig.calls()) == 2


@needs_kicad
def test_upto_routes_a_stale_earlier_phase_first(rig):
    rig.route(LEG, FB, upto="fb")
    n = len(rig.calls())
    report = rig.route(dict(LEG, width=0.6), FB, upto="fb")
    assert [p["reused"] for p in report.phases] == [False, False] and [_nets(c) for c in rig.calls()[n:]] == [["VIN"], ["FB"]]


@needs_kicad
def test_only_routes_just_that_phase_and_names_earlier_ones_with_no_copper(rig):
    report = rig.route(LEG, FB, {"name": "signals"}, upto="fb", only=True)
    assert [p["name"] for p in report.phases] == ["fb"] and [_nets(c) for c in rig.calls()] == [["FB"]]
    assert report.phases_without_copper == ["vin"]


def test_a_route_with_no_phases_is_refused_with_the_specs_words(tmp_path):
    with bind(Settings()):
        with pytest.raises(RouteRefused) as e:
            route_board(tmp_path / "x.kicad_pcb", tmp_path / "w", phases=())
    assert str(e.value) == ("route: no routing phases in placemat.toml; `placemat settings --example` writes a "
                            "placemat.toml with the default phases")


@pytest.mark.parametrize("setting, value", [("route_islands", ("VB=0.5",)), ("route_pair_layers", {"A/B": ["F.Cu"]}),
                                            ("route_net_halos", {"SW": 2.0})])
def test_a_setting_the_phases_replaced_is_refused(tmp_path, setting, value):
    with bind(Settings(**{setting: value})):
        with pytest.raises(RouteRefused) as e:
            route_board(tmp_path / "x.kicad_pcb", tmp_path / "w", phases=phases())
    assert e.value.code == "legacy_setting" and e.value.facts["setting"] == setting.split("_", 1)[1]
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_phases.py -p no:cacheprovider`
Expected: FAIL, `RouteRefused` is not defined.

- [ ] **Step 3: Implement `run_phase` in phase_run.py**

```python
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from .. import route_progress
from .drc import run_drc
from .route import (RouterFailed, _copy_project, _violations_by_net, fill_zones, lock_copper, main_pass_nets,
                    remove_guards, route_pairs, route_pour_net, router_command, score)


@dataclass
class PhaseContext:
    rpy: Path
    script: str
    router_dir: str
    work: Path
    layers: list
    iterations: int | None
    probe: int | None
    quick: bool
    timeout: int
    env: dict
    cfg: object
    geometry: object
    clearance_map: dict
    base_clearance: float
    clearances_file: Path | None
    excluded: set
    pour_nets: set
    events: object


@dataclass
class PhaseOutcome:
    board: Path
    record: dict
    open_nets: dict
    summaries: list = field(default_factory=list)     # (phase name, call index, summary path)
    calls: list = field(default_factory=list)         # (Call, board in, board out)


def _run(cmd, log: Path, ctx, what: str) -> None:
    with open(log, "w") as f:
        f.write("$ %s\n\n" % " ".join(str(c) for c in cmd))
        f.flush()
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(ctx.router_dir), env=ctx.env,
                            timeout=ctx.timeout, pass_fds=route_progress.pass_fds()).returncode
    return rc


def _failed(rc, log, what):
    tail = "\n".join(Path(log).read_text(errors="replace").splitlines()[-8:])
    raise RouterFailed("the router exited %s routing %s" % (rc, what), rc, log, tail)


def joined_ends(pcb_path, tasks) -> list:
    """Whether each task's two ends are joined on the board, by KiCad's own connectivity (BuildConnectivity, the same
    test route_cleanup.pad_groups makes): an end is every pad of that footprint with that number."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb_path))
    board.BuildConnectivity()
    cn = board.GetConnectivity()
    pads = {}
    for p in board.GetPads():
        pads.setdefault((p.GetParentFootprint().GetReference(), p.GetNumber()), []).append(p)
    out = []
    for t in tasks:
        ends_b = {p.m_Uuid.AsString() for p in pads.get(tuple(t.end), ())}
        joined = False
        for a in pads.get(tuple(t.start), ()):
            reach = {i.m_Uuid.AsString() for i in cn.GetConnectedItems(a) if i.GetClass() == "PAD"}
            if reach & ends_b:
                joined = True
                break
        out.append(joined)
    return out


def phase_record(phase, index, sel, open_before, open_after, violated, joined, seconds, calls, pairs=None,
                 connections=(), bus_groups=()) -> dict:
    rec = dict(phase.record(), index=index, seconds=round(seconds, 1), reused=False, calls=calls, pairs=pairs,
               connections=list(connections), bus_groups=list(bus_groups), widths=[])
    if sel.tasks:
        ok = [j and t.net not in violated for t, j in zip(sel.tasks, joined)]
        rec.update(asked=len(sel.tasks), joined=sum(ok),
                   open=[{k: v for k, v in t.record().items() if k in ("net", "from", "to")}
                         for t, good in zip(sel.tasks, ok) if not good],
                   closure_clean=round(sum(ok) / len(sel.tasks), 4) if sel.tasks else 1.0)
        return rec
    nets = set(sel.nets) | set(sel.pour_nets) | {n for b in sel.buses for n in b} | {n for p in sel.pairs for n in p}
    before = {n: open_before[n] for n in nets if open_before.get(n)}
    after = {n: open_after.get(n, 0) for n in before}
    sc = score(before, after, set(violated) & set(before))
    asked = sum(before.values())
    still = sum(before[n] if n in sc.shorted else after[n] for n in before)
    rec.update(asked=asked, joined=asked - still, closure_clean=round(sc.closure_clean, 4),
               open=[{"net": n, "items": before[n] if n in sc.shorted else after[n]} for n in sorted(before)
                     if n in sc.shorted or after[n]])
    return rec


def run_phase(ctx, index, phase, sel, board, open_before) -> PhaseOutcome:
    t0 = time.time()
    calls = plan_calls(sel, ctx.clearance_map, ctx.base_clearance, ctx.excluded | ctx.pour_nets)
    layers = list(sel.layers)
    out = PhaseOutcome(board, {}, {})
    pairs, connections, bus_groups = None, [], []
    for k, call in enumerate(calls):
        stem = "p%d_%d" % (index, k)
        nxt = ctx.work / (stem + ".kicad_pcb")
        summary = ctx.work / (stem + "_summary.json")
        common = dict(iterations=ctx.iterations, probe=ctx.probe, quick=ctx.quick, clearances=ctx.clearances_file,
                      neckdown=phase.neckdown, extra_args=phase.router_args)
        if call.kind == "pairs":
            got, pairs_out = route_pairs(ctx.rpy, ctx.router_dir, board, ctx.work, list(sel.pairs), layers, ctx.cfg,
                                         ctx.iterations, ctx.probe, ctx.timeout, ctx.env, events=ctx.events, stem=stem)
            pairs = pairs_out.as_dict()
            if got != board:
                shutil.copy(got, nxt)
                _copy_project(got, nxt)
            else:
                shutil.copy(board, nxt)
                _copy_project(board, nxt)
        elif call.kind == "pour":
            route_pour_net(ctx, board, nxt, call.nets[0], call.width, layers, stem, set(sel.pour_nets) | ctx.pour_nets)
        elif call.kind == "tasks":
            pending, j, src = list(call.tasks), 0, board
            while pending:
                cfile = write_connections(pending, ctx.work / ("%s_%d_connections.json" % (stem, j)))
                part = ctx.work / ("%s_%d.kicad_pcb" % (stem, j))
                psum = ctx.work / ("%s_%d_summary.json" % (stem, j))
                cmd = router_command(ctx.rpy, ctx.script, src, part, set(), layers, psum, connections=cfile, **common)
                log = ctx.work / ("%s_%d.log" % (stem, j))
                rc = _run(cmd, log, ctx, "phase %s" % phase.name)
                if rc != 0 or not part.exists():
                    _failed(rc, log, "phase %s" % phase.name)
                _copy_project(src, part)
                lock_copper(str(part))
                out.summaries.append((phase.name, k, psum))
                recs = json.loads(psum.read_text()).get("connections") or []
                deferred = [t for t, r in zip(pending, recs) if r.get("status") == "deferred"]
                connections += [r for r in recs if r.get("status") != "deferred"]
                if len(deferred) == len(pending):     # nothing moved: KRT deferred every task, report them as such
                    connections += [r for r in recs if r.get("status") == "deferred"]
                    break
                pending, src, j = deferred, part, j + 1
            shutil.copy(src, nxt)
            _copy_project(src, nxt)
        else:
            if call.kind == "rest":
                if not main_pass_nets(ctx.geometry.nets, set(call.excluded)):
                    shutil.copy(board, nxt)
                    _copy_project(board, nxt)
                    out.calls.append((call, board, nxt))
                    board = nxt
                    continue
                cmd = router_command(ctx.rpy, ctx.script, board, nxt, set(call.excluded), layers, summary, **common)
            else:
                widths = {n: call.width for n in call.nets} if call.width else None
                cmd = router_command(ctx.rpy, ctx.script, board, nxt, set(), layers, summary, nets=list(call.nets),
                                     widths=widths, bus_nets=list(call.nets) if call.kind == "bus" else None, **common)
            log = ctx.work / (stem + ".log")
            rc = _run(cmd, log, ctx, "phase %s" % phase.name)
            if rc != 0 or not nxt.exists():
                _failed(rc, log, "phase %s" % phase.name)
            _copy_project(board, nxt)
            out.summaries.append((phase.name, k, summary))
            if call.kind == "bus":
                bus_groups += json.loads(summary.read_text()).get("bus_groups") or []
        lock_copper(str(nxt))
        out.calls.append((call, board, nxt))
        board = nxt
    if not calls:                                   # a phase that selected nothing open: its board is its input
        shutil.copy(board, ctx.work / ("p%d_0.kicad_pcb" % index))
        _copy_project(board, ctx.work / ("p%d_0.kicad_pcb" % index))
        board = ctx.work / ("p%d_0.kicad_pcb" % index)
    judged = ctx.work / ("p%d_drc.kicad_pcb" % index)
    shutil.copy(board, judged)
    _copy_project(board, judged)
    remove_guards(str(judged))
    fill_zones(str(judged))
    drc = run_drc(judged, ctx.work / ("p%d_drc.json" % index), refill_zones=False)
    violated = set(_violations_by_net(json.loads((ctx.work / ("p%d_drc.json" % index)).read_text())))
    joined = joined_ends(judged, sel.tasks) if sel.tasks else []
    out.board, out.open_nets = board, dict(drc.open_nets)
    out.record = phase_record(phase, index, sel, open_before, out.open_nets, violated, joined, time.time() - t0,
                              len(calls), pairs, connections, bus_groups)
    return out
```

(`json`, `Path`, `plan_calls`, `write_connections` are already in the module from Task 11.)

- [ ] **Step 4: Implement the engine in route.py**

`RouteRefused`:

```python
_REFUSED = {
    "no_phases": "route: no routing phases in placemat.toml; `placemat settings --example` writes a placemat.toml with "
                 "the default phases",
    "legacy_setting": "route: [route] %(setting)s is replaced by routing phases: %(instead)s",
    "unknown_phase": "route: no phase %(phase)r; the phases are %(phases)s",
    "capture": "route: %(path)s: %(code)s %(facts)s",
    "router_old": "route: the router at %(router)s lacks %(missing)s: route with the placemat fork of KiCadRoutingTools",
}
_INSTEAD = {"islands": "a phase with `nets` and `width`",
            "pair_layers": "a phase with `pairs = true` and `layers`",
            "net_halos": "the clearance field of the net's type in the capture"}


def refused_text(code: str, facts: dict) -> str:
    return _REFUSED[code] % facts


class RouteRefused(ValueError):
    """A route placemat will not start: `code` (a key of _REFUSED) and its `facts`; refused_text renders it."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, dict(facts)
        super().__init__(refused_text(code, self.facts))
```

`route_pairs(..., stem: str = "pairs")`: every `work / "pairs..."` name becomes `work / (stem + "...")`
(`pairs_in`, the output, logs `<stem>.log` and `<stem>_<i>.log`, the project copies). Its `pair_layers` and
`halos` parameters stay until Tasks 16 and 25.

`route_pour_net(ctx, board, out, net, width, layers, stem, pours)`: the body of one iteration of `route_islands`
(route.py:961-989) with `inp = work/(stem+"_in.kicad_pcb")`, the other pour nets' partial pours guarded
(`guard_partial_pours(str(inp), pours - {net}, layers, ctx.cfg.route_plane_share)`), `pours_as_zones`, the router call
`router_command(..., nets=[net], widths={net: width} if width else None, neckdown=..., extra_args=...)`, `pours_back`,
then `drop_pour_guards(str(out), pours)` and `guard_partial_pours(str(out), {net}, layers, share)` so later calls are
judged against its pour, as the islands stage did (route.py:1199). Keep the comment at route.py:968-971 about layers.

`_route_board` from :1047 becomes (setup lines that do not change are kept as they are and marked `...`; write them
out from the current function):

```python
def _route_board(pcb, work, exclude_nets=(), layers=None, router_dir_override: str | None = None,
                quick: bool = False, iterations: int | None = None, probe: int | None = None,
                timeout: int | None = None, resume: bool = True, board_info: dict | None = None,
                on_setup=None, phases=None, upto: str | None = None, only: bool = False, pour_nets=(),
                capture_path=None) -> RouteReport:
    """Route a copy of `pcb` through the project's routing phases (route_phase.py), in order, each phase on the board
    the one before it left, its copper locked. Each phase's result is kept in `work` (route_state.py) under a digest
    chained from the phases before it: a rerun reuses a phase while its key and every earlier one hold."""
    from ..settings import active
    from ..route_phase import phases_of
    from ..capture_nets import CaptureError, capture_beside, read_capture
    from .route_state import RouteState, digest, file_digest
    from .phase_run import PhaseContext, run_phase
    from .phase_select import select
    cfg = active()
    phases = phases_of(cfg) if phases is None else tuple(phases)
    if not phases:
        raise RouteRefused("no_phases")
    for key in ("route_islands", "route_pair_layers", "route_net_halos"):
        if getattr(cfg, key):
            name = key.split("_", 1)[1]
            raise RouteRefused("legacy_setting", setting=name, instead=_INSTEAD[name])
    names = [p.name for p in phases]
    if upto is not None and upto not in names:
        raise RouteRefused("unknown_phase", phase=upto, phases=", ".join(names))
    run_list = [phases[names.index(upto)]] if only else list(phases[:names.index(upto) + 1] if upto else phases)
    router_dir_path = router_dir_override or router_dir(cfg)
    ...  # timeout, iterations, paths, rpy/route_py check, RouteState, events, pcb_in copy, lock_copper, layers: as before
    missing = router_capable(rpy, router_dir_path)
    if missing:
        raise RouteRefused("router_old", router=router_dir_path, missing=", ".join(missing))
    try:
        capture = read_capture(capture_path) if capture_path else capture_beside(pcb)
    except CaptureError as e:
        raise RouteRefused("capture", path=str(capture_path or pcb), code=e.code, facts=e.facts) from None
    geometry = read_board(str(pcb_in))
    excluded, pours = set(exclude_nets), set(pour_nets)
    # every phase is checked before anything routes; the pour nets some phase names are routed (D15)
    every = set(geometry.nets)
    chosen_pours = set()
    for p in phases:
        chosen_pours |= set(select(p, geometry, capture, open_nets=every, excluded=excluded, pour_nets=pours,
                                   route_layers=layers, rise_c=cfg.check_rise_c, copper_oz=COPPER_OZ).pour_nets)
    counted = excluded | (pours - chosen_pours)
    before = run_drc(pcb_in, work / "drc_before.json")
    open0 = {n: v for n, v in before.open_nets.items() if n not in counted}
    valid = not before.real
    guard_footprint_copper(str(pcb_in))
    kept_pours = guard_partial_pours(str(pcb_in), pours - chosen_pours, layers, cfg.route_plane_share)
    clearance_map = net_halos.merged(net_halos.class_clearances(rpy, router_dir_path, pcb_in, geometry.nets, env), {},
                                     net_halos.ceiling(cfg.route_router_args, env))
    base_clearance = routing_clearance(geometry.default_clearance, cfg.route_router_args, env)
    from .. import __version__
    settings_part = {k: v for k, v in sorted(json.loads(cfg.json()).items())
                     if k.startswith("route_") and k not in ("route_router_dir", "route_phase")}
    base = digest(file_digest(pcb), file_digest(pcb.with_suffix(".kicad_pro")), file_digest(pcb.with_suffix(".kicad_dru")),
                  capture.digest if capture else "", sorted(excluded), sorted(pours), layers, quick, iterations, probe,
                  router_version(router_dir_path), __version__, settings_part)
    state.set_order(["only:" + run_list[0].name] if only else [p.name for p in run_list])
    ctx = PhaseContext(rpy, script, router_dir_path, work, layers, iterations, probe, quick, timeout, env, cfg,
                       geometry, clearance_map, base_clearance, None, excluded, pours, rev)
    board, prev, records, summaries, spent = pcb_in, base, [], [], 0.0
    open_now = dict(before.open_nets)
    for i, phase in enumerate(run_list):
        key = digest(prev, phase.key()) if not only else digest(base, "only", phase.key())
        label = state.order[i]
        saved = state.result(label, key)
        if saved is not None and (work / saved["board"]).exists():
            board, open_now = work / saved["board"], dict(saved["open_nets"])
            records.append(dict(saved["record"], reused=True))
            summaries += [tuple(s) for s in saved["summaries"]]
            spent += saved["record"]["seconds"]
            rev.resumed(phase.name, saved["record"]["seconds"])
            prev = key
            continue
        state.drop_from(label)
        sel = select(phase, geometry, capture, open_nets={n for n, v in open_now.items() if v}, excluded=excluded,
                     pour_nets=pours, route_layers=layers, rise_c=cfg.check_rise_c, copper_oz=COPPER_OZ)
        rev.begin(phase.name, nets=len(sel.nets) + len(sel.tasks) + len(sel.pour_nets))
        done = False
        try:
            outcome = run_phase(ctx_for(ctx, rev, phase.name), i, phase, sel, board, open_now)
            done = True
        finally:
            rev.end(phase.name, complete=done)
        board, open_now = outcome.board, outcome.open_nets
        records.append(outcome.record)
        summaries += [(n, k, str(s)) for n, k, s in outcome.summaries]
        spent += outcome.record["seconds"]
        state.record(label, key, {"board": board.name, "record": outcome.record, "open_nets": open_now,
                                  "summaries": [(n, k, str(s)) for n, k, s in outcome.summaries]})
        prev = key
    shutil.copy(board, raw_out)
    ...  # postprocess as before from :1278 (routed copy, remove_guards, fill_zones, dangling cleanup, drc_after,
         # score over open0/open1 with `counted`, breaches against kept pour guards), then:
    report.phases = records
    if only:
        report.phases_without_copper = without_copper(phases[:names.index(upto)], geometry, capture, excluded, pours,
                                                      layers, cfg)
```

`ctx_for(ctx, rev, name)` returns `dataclasses.replace(ctx, env=dict(ctx.env, **rev.env(name)))`.
`COPPER_OZ` is `checks.COPPER_OZ`. `without_copper` (D26): for each earlier phase, the nets its selection names
(`select(..., open_nets=every, ...)`: nets, pour nets, bus and pair nets, task nets) and whether any of them has a
track in `geometry.copper`; the names of those with none.

Delete from `_route_board` the pairs, islands, classes and main blocks (:1130-1277). The functions they called
(`route_islands`, `route_class_stages`, `resolve_pair_layers`, `pair_layer_groups`, `islands_on_board`,
`island_layers_on_board`) stay defined until Task 25 deletes them; nothing calls them now.

`route_progress.py`: drop `STAGES`; in `_forward` and `end`, rename by `self.names` whenever it is non-empty (the
pair router's aliases, set by `route_pairs` for its call and cleared after it) instead of testing `stage == "pairs"`.

- [ ] **Step 5: Callers**

- `cli.cmd_route` (cli.py:703-760): `route_board(pcb, work, exclude_nets=set(args.exclude), pour_nets=planes, ...)`
  with no `islands`; a non-empty `--islands` prints `refused_text("legacy_setting", setting="islands", instead=...)`
  and returns 2; catch `RouteRefused` and `PhaseError` around `route_board`: say `str(e)` at level fail, return 2.
- `runner.py:754`: `exclude_nets=set(route_exclude), pour_nets=set(plan.plane_nets)`; `RouteRefused`/`PhaseError` ->
  `RunFailure("route", "Routing refused", {"code": e.code, "facts": e.facts, "error": str(e)})`.
- `explore.py`: `Routing` gains `capture: Path | None = None` (the sidecar beside the run's board, set by the runner
  from `src.pcb`'s folder); `VariantRouter.route(pcb, work, exclude_nets=(), pour_nets=(), quick=True, resume=True,
  capture_path=None)`; `_route_work` passes `exclude_nets=set(routing.exclude), pour_nets=set(p.plane_nets),
  capture_path=routing.capture`.

- [ ] **Step 6: Migrate the tests that route**

For each file in "Files", a test that called `route_board` without phases now passes `phases=phases()` (the rest phase
alone) or the phases it means: an islands test becomes `phases({"name": "pour", "nets": [NET], "width": W},
{"name": "signals"})` with `pour_nets={NET}`; a class-stage rig test is deleted (its rule is
`test_the_rest_routes_wide_clearances_by_name_then_everything_else` in Task 11); a pair or halo rig test is deleted
here and its replacement is written in Task 22 or 16; `FAKE` routers that branch on `"*" in nets` treat a call with
`--connections` or explicit `--nets` as a phase call. Each deleted test is named in the commit message.

- [ ] **Step 7: Run the tests**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_phases.py -p no:cacheprovider
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -n 2 -p no:cacheprovider
```

Expected: PASS. The default suite leaves out the slow real-router tests; run the slow ones that route
(`grep -E "route|explore" tests/slow_tests.txt`) by name with `KRT_DIR=/home/ben/work/KRT-phases`, `-n 2`, under the
realboard lock, and migrate any that fail for the same reasons.

- [ ] **Step 8: Docs**

api.md "Routing phases" (replacing the stage description at :4009-4050 and the `[route] islands`/`pair_layers`/
`net_halos` paragraphs at :3848-3949 with a pointer to it): the form with the spec's example, each selector, width,
layers, neckdown, router_args, what a phase selects ("only connections still open"), clearance groups, pour nets
(D15), the kept-result chain, the per-phase record keys, the refusals with their codes. SKILL.md: routing is stated
as phases; power legs and buses are phases, declared copper only for fixed geometry. migration.md "## Unreleased":

```markdown
### Changed

- **A route needs routing phases.** `placemat route`, `run --route` and explore's `--route-best` route the project's
  `[[route.phase]]` tables in order and refuse a project with none. Start from the default phases
  (`placemat settings <board> --example`), or write the one phase that routes what the old fixed stages' main pass did:

      [[route.phase]]
      name = "signals"

  `[route] islands`, `[route] pair_layers` and `[route] net_halos` are refused; see "Removed" for what replaces each.
```

- [ ] **Step 9: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A src tests skills
git commit -m "Routing phases: the engine routes the project's phases in order, each kept and reused by its chained key"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 14: placemat: a route that fails or is stopped keeps the placed board

The user decided on 2026-10-07: when a run's placement succeeded and its route then fails, the layout folder keeps the
placed, unrouted board and the run's output says so; every other failure still puts the folder back as the last run
left it. A second decision the same day: a stop (Ctrl-C or a signal) during the route stage keeps the placed board
too, says so, records the run as `stopped`, and a rerun resumes the route; a stop in any other stage still puts the
folder back. Today every `RunFailure` without an `item` restores the folder from `before` (runner.py:815-823 at
55f9005b), so a route failure throws away a good placement. This is the user's standing rule for long commands: a
failed command keeps its work, and a rerun continues from it. The route's own work already carries over:
`keep_route` (runner.py:293-312) moves `route/` into a rerun of the same run id, and Task 13's kept-result chain
reuses each phase whose key holds.

**Files:**
- Modify: `$WT/src/placemat/runner.py` (the `except RunFailure` branch of `_run`, runner.py:815-831 at 55f9005b, and
  the `except stop.Stopped` branch, runner.py:832-841; after Task 13 both are a few lines lower)
- Create: `$WT/tests/test_route_failure_layout.py`
- Docs: `skills/placemat/references/api.md` ("**Stopping.**", api.md:4566-4577, and a paragraph after it),
  `skills/placemat/SKILL.md` (the long-commands bullet, SKILL.md:546-549: "the layout folder is as it was"),
  `skills/placemat/references/migration.md` ("## Unreleased", "### Changed")

**Interfaces:**
- Consumes: Task 13's `RouteRefused(code, **facts)` and the runner's mapping of `RouterFailed`, `RouteRefused` and
  any other route exception to `RunFailure("route", ...)`.
- Produces: `run.json`'s `failure.layout`, one of `"placed_unrouted"` (a route failure: the layout folder holds the
  placed board), `"restored"` (the folder was put back from `before`), `"as_written"` (a critical item's failure, or a
  first run with no earlier folder: the folder is as the run left it). A stopped run's `failure` (`kind: "stopped"`)
  carries the same `layout`: `placed_unrouted` for a stop during the route stage, else `restored` or `as_written`.
  Read by nothing in placemat yet; the studio and `watch` may show it later.

- [ ] **Step 1: Write the failing tests**

`tests/test_route_failure_layout.py`:

```python
"""A route that fails after a good placement keeps the placed, unrouted board in the layout folder, says so, and
keeps the route's work for the rerun; a failure before the board is written puts the folder back as the last run
left it."""
import shutil
from pathlib import Path

import pytest

from placemat.project import find_board


@pytest.fixture
def staged(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    from placemat import runner
    from placemat.console import configure, console as sink
    from tests import real_modules as rm
    script = rm.stage(tmp_path, "usb5v")
    src = find_board(script)
    src.layout_dir.mkdir(parents=True, exist_ok=True)
    (src.layout_dir / "earlier.txt").write_text("the folder as the last run left it\n")

    def cached(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(runner.cached_generation(src), src.layout_dir)
        return False
    monkeypatch.setattr(runner, "generate", cached)
    said = []
    real = sink.say
    monkeypatch.setattr(sink, "say", lambda stage, message="", **kw: (said.append((stage, message)),
                                                                       real(stage, message, **kw))[1])

    class Staged:
        pass
    s = Staged()
    s.src, s.said = src, said

    def run():
        try:
            return runner.run(script, render=False, quiet=True, route=True)
        finally:
            configure(quiet=False)
    s.run = run
    return s


def _failing(monkeypatch, exc, seen):
    """route_board stood in for: it records the board it was given and whether its work folder held an earlier
    route's work, leaves work of its own, and raises `exc`."""
    import placemat.kicad.route as route_mod

    def route(pcb, work, *a, **kw):
        seen.append({"placed": Path(pcb).read_bytes(), "kept_before": (Path(work) / "kept.txt").exists()})
        Path(work).mkdir(parents=True, exist_ok=True)
        (Path(work) / "kept.txt").write_text("a phase this route finished\n")
        raise exc
    monkeypatch.setattr(route_mod, "route_board", route)


def _router_failed():
    from placemat.kicad.route import RouterFailed
    return RouterFailed("the router exited 3 routing phase signals", 3, "router.log", "tail")


def _refused():
    from placemat.kicad.route import RouteRefused
    return RouteRefused("no_phases")


@pytest.mark.parametrize("exc", [_router_failed, _refused])
def test_a_failed_route_keeps_the_placed_board_and_says_so(staged, monkeypatch, exc):
    seen = []
    _failing(monkeypatch, exc(), seen)
    result = staged.run()
    assert result.status == "failed" and result.record.failure["kind"] == "route"
    assert result.record.failure["layout"] == "placed_unrouted"
    assert staged.src.pcb.read_bytes() == seen[0]["placed"]
    assert not (staged.src.layout_dir / "earlier.txt").exists()
    assert any(stage == "fail" and "holds the placed board, unrouted" in text for stage, text in staged.said)


def test_a_rerun_after_a_failed_route_finds_its_work(staged, monkeypatch):
    seen = []
    _failing(monkeypatch, _router_failed(), seen)
    staged.run()
    staged.run()
    assert [s["kept_before"] for s in seen] == [False, True]


def test_a_failure_before_the_board_is_written_still_restores_the_folder(staged, monkeypatch):
    from placemat import runner

    def broken(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        src.layout_dir.mkdir(parents=True)
        raise runner.RunFailure("generation", "Schematic generation failed", {"exit_code": 1})
    monkeypatch.setattr(runner, "generate", broken)
    result = staged.run()
    assert result.status == "failed" and result.record.failure["layout"] == "restored"
    assert (staged.src.layout_dir / "earlier.txt").exists()


def _record(src):
    import json
    runs = [p for p in (src.board_dir / ".placemat" / "runs").glob("*/run.json") if not p.parent.name.startswith(".")]
    return json.loads(max(runs, key=lambda p: p.stat().st_mtime).read_text())


def test_a_stop_during_the_route_keeps_the_placed_board_and_the_rerun_resumes(staged, monkeypatch):
    import signal
    from placemat import stop
    seen = []
    _failing(monkeypatch, stop.Stopped(signal.SIGTERM), seen)
    with pytest.raises(stop.Stopped):
        staged.run()
    rec = _record(staged.src)
    assert rec["status"] == "stopped" and rec["failure"]["stage"] == "route"
    assert rec["failure"]["layout"] == "placed_unrouted"
    assert staged.src.pcb.read_bytes() == seen[0]["placed"]
    assert not (staged.src.layout_dir / "earlier.txt").exists()
    assert any("holds the placed board, unrouted" in text for _, text in staged.said)
    with pytest.raises(stop.Stopped):
        staged.run()
    assert [s["kept_before"] for s in seen] == [False, True]


def test_a_stop_before_the_route_still_restores_the_folder(staged, monkeypatch):
    import signal
    from placemat import runner, stop

    def stopped(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        src.layout_dir.mkdir(parents=True)
        raise stop.Stopped(signal.SIGTERM)
    monkeypatch.setattr(runner, "generate", stopped)
    with pytest.raises(stop.Stopped):
        staged.run()
    assert (staged.src.layout_dir / "earlier.txt").exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_failure_layout.py -p no:cacheprovider`
Expected: FAIL: the route tests find `earlier.txt` put back and no `layout` in `failure`; the restore test fails on
`failure["layout"]` (KeyError); the route-stop test finds `earlier.txt` put back and no `layout`. The rerun test and
the stop-before-the-route test pass already (keep_route, the restore); they stay as guards on the rule.

- [ ] **Step 3: Implement**

In runner.py, beside `_KICAD_LOCKS`:

```python
# What a failed run's last lines say of the layout folder, by `failure.layout` ("as_written" says nothing)
_LAYOUT_SAID = {
    "placed_unrouted": "the layout folder holds the placed board, unrouted; run the same command again to route it: "
                       "the route's work is kept in %(route)s",
    "restored": "the layout folder is as the last run left it",
}
```

The `except RunFailure` branch, from `kept = run_dir / "before"` to the restore's `say`, becomes:

```python
        kept = run_dir / "before"
        if e.kind == "route":
            # the placement finished and the board is written: keep it, unrouted, with the route's work in
            # run_dir/route for the rerun (a failed long command keeps its work)
            layout = "placed_unrouted"
        elif kept.exists() and "item" not in e.details:     # a critical item's failure writes the board as it stood
            shutil.rmtree(src.layout_dir, ignore_errors=True)
            shutil.copytree(kept, src.layout_dir, ignore=_KICAD_LOCKS)
            layout = "restored"
        else:
            layout = "as_written"
        rec.failure["layout"] = layout
        if layout in _LAYOUT_SAID:
            say("fail", _LAYOUT_SAID[layout] % {"route": run_dir / "route"})
```

The `except stop.Stopped` branch, from `kept = run_dir / "before"` to its restore, becomes (the runner's own `stage`
says where the stop landed; `s.stage` may name something inside the route):

```python
        kept = run_dir / "before"
        if stage == "route":
            # the placement finished and the board is written: keep it, unrouted, with the route's work in
            # run_dir/route for the rerun (a stopped long command keeps its work)
            layout = "placed_unrouted"
        elif kept.exists():                # whatever the stop left half written: the folder as the last run left it
            shutil.rmtree(src.layout_dir, ignore_errors=True)
            shutil.copytree(kept, src.layout_dir, ignore=_KICAD_LOCKS)
            layout = "restored"
        else:
            layout = "as_written"
        rec.failure["layout"] = layout
        if layout == "placed_unrouted":
            say("stop", _LAYOUT_SAID[layout] % {"route": run_dir / "route"})
```

The stop's own final line (`stop.say`, after the record is saved) is unchanged.

- [ ] **Step 4: Run the tests and the neighbours**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_failure_layout.py tests/test_route_nothing_to_route.py tests/test_present.py -n 2 -p no:cacheprovider
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -n 2 -p no:cacheprovider
```

Expected: PASS.

- [ ] **Step 5: Docs**

api.md, a paragraph after "**Stopping.**":

```markdown
**A failed run.** A run that fails records `status: "failed"` and `failure: {kind, message, ..., layout}`. `layout`
says what the layout folder holds: `placed_unrouted` when the route failed or was refused after the placement was
written (the folder keeps the placed board, and the run's last lines say so; run the same command again to route it,
and the route takes the phases the failed one finished), `restored` when the folder was put back as the last run left
it (a failure before the board was written), `as_written` when a critical item's failure wrote the board as it stood.
A stopped run's `failure` carries the same `layout`.
```

In "**Stopping.**", "the layout folder is as the last run left it" becomes "the layout folder is as the last run left
it, except after a stop during the route: it then keeps the placed, unrouted board, says so, and a rerun resumes the
route". SKILL.md's long-commands bullet: "the layout folder is as it was" becomes "the layout folder is as it was (a
stop during the route keeps the placed board, unrouted, and a rerun resumes the route)".

migration.md "## Unreleased", under "### Changed" (Task 13 made the heading):

```markdown
- **A route that fails keeps the placed board.** When `run --route` places the board and the route then fails or is
  refused, the layout folder keeps the placed, unrouted board instead of going back to the last run's, and the run
  says so; `run.json`'s `failure.layout` is `placed_unrouted`. Run the same command again to route it: the route
  takes the phases the failed one finished. A failure before the board is written still puts the folder back
  (`failure.layout` `restored`). Scripts need no change.
- **A route that is stopped keeps the placed board.** A stop (Ctrl-C, SIGTERM, SIGHUP, `--max-time`) during the route
  of `run --route` keeps the placed, unrouted board in the layout folder instead of going back to the last run's, and
  the run says so; the run is recorded as `stopped`, with `failure.layout` `placed_unrouted`. Run the same command
  again to resume the route from the phases it finished. A stop in any other stage still puts the folder back.
  Scripts need no change.
```

- [ ] **Step 6: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add src/placemat/runner.py tests/test_route_failure_layout.py skills/placemat/SKILL.md skills/placemat/references/api.md skills/placemat/references/migration.md
git commit -m "Run: a route that fails or is stopped after a good placement keeps the placed, unrouted board and says so"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 15: placemat: width judgement per phase

**Files:**
- Modify: `$WT/src/placemat/kicad/route_widths.py:65-84` (`read_widths`), `:155-212` (`board_widths`), `:215-218`
  (`judged_on_board` deleted)
- Modify: `$WT/src/placemat/kicad/phase_run.py` (judge each width call after the phase), `$WT/src/placemat/kicad/route.py`
  (the report's `widths` from the phases)
- Create: `$WT/tests/test_phase_widths.py`
- Modify: `$WT/tests/test_route_widths.py`, `$WT/tests/test_route_widths_board.py` (callers of the old signatures)

**Interfaces:**
- Consumes: `PhaseOutcome.calls` ((Call, board in, board out)), `board_geometry.added_copper(given, routed)`.
- Produces:

```python
def board_widths(geometry, asks: dict, stage: str, rise_c=None, copper_oz=None, neck_mm=..., only=None,
                 by: str = "asked") -> list
    # asks: {net: {CopperLayer: mm}}; only: the CopperItems to judge (a call's added copper), None: every track of the net
    # each record as today plus "stage" = the phase name and per layer {"layer", "need_mm", "by", "under_mm", "min_mm"}
def read_widths(summaries: list, judged: set) -> list      # summaries: [(phase name, call index, path)]
def phase_widths(phase, calls, cfg) -> list                  # in phase_run.py: board_widths over each call with a width
def narrow_join_widths(phase, sel, connections, routed_pcb, cfg) -> list
    # in phase_run.py: D3's fallback (Task 5 step 3) only; the joining path of each `joined_narrow` record that carries
    # a `path`, judged against its task's asked widths
```

  `by` is `"current"` for a task call whose tasks carry `amps`, else `"asked"`. A phase with `neckdown = false` is
  judged with `neck_mm = 0`. Every phase record is `declared: true`, so its finding is critical (spec: "a critical
  `route.width` finding naming the phase").

- [ ] **Step 1: Write the failing test**

`tests/test_phase_widths.py`:

```python
"""A phase with a width is judged on the routed board, on the copper each of its calls added, per layer."""
from placemat.kicad.route_widths import board_widths, findings_of
from placemat.values import CopperLayer
from tests.fixtures import board_geometry, footprint, track

F, B = CopperLayer.F, CopperLayer.B


def test_added_copper_under_its_asked_width_is_recorded_per_layer_naming_the_phase():
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"))
    q1 = footprint("Q1", 25, 10, nets=("VB", "OUT"))
    narrow = track("VB", 8, 10, 20, 10, w=0.3)
    tap = track("VB", 8, 12, 20, 12, w=0.2)                 # an earlier phase's tap: not this call's copper
    g = board_geometry([j1, q1], copper=[narrow, tap])
    (r,) = board_widths(g, {"VB": {F: 1.0, B: 1.0}}, "legs", only=[narrow], neck_mm=0.0)
    assert r["stage"] == "legs" and r["layers"][0]["layer"] == "F.Cu" and r["layers"][0]["need_mm"] == 1.0
    assert r["length_under_mm"] == 12.0
    (f,) = findings_of([r])
    assert f.severity == "critical" and f.facts["stage"] == "legs"


def test_copper_at_its_width_is_not_recorded():
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"))
    wide = track("VB", 8, 10, 20, 10, w=1.0)
    assert board_widths(board_geometry([j1], copper=[wide]), {"VB": {F: 1.0}}, "legs", only=[wide]) == []


def test_a_task_left_joined_narrow_is_judged_on_its_joining_path(monkeypatch):
    """D3's fallback: KRT reports a task joined by narrower copper and does not route it; the phase judges the
    path the record names, and only that path, against the task's widths."""
    from types import SimpleNamespace as N
    from placemat.kicad import phase_run
    from placemat.route_phase import parse_phases
    from placemat.settings import Settings
    j1 = footprint("J1", 5, 10, nets=("VB", "GND"))
    q1 = footprint("Q1", 25, 10, nets=("VB", "OUT"))
    stub = track("VB", 8, 10, 20, 10, w=0.2)
    sense = track("VB", 8, 14, 20, 14, w=0.15)               # the same net, not on the path: not judged
    g = board_geometry([j1, q1], copper=[stub, sense])
    monkeypatch.setattr("placemat.kicad.read.read_board", lambda path: g)
    (phase,) = parse_phases(({"name": "legs", "width": 1.0, "connections": [
        {"from": {"part": "J1", "pad": "1"}, "to": {"part": "Q1", "pad": "1"}}]},))
    task = N(net="VB", start=("J1", "1"), end=("Q1", "1"), widths=(("F.Cu", 1.0),), amps=None)
    rec = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "Q1", "pad": "1"}, "status": "joined_narrow",
           "joined": True, "min_width_mm": {"F.Cu": 0.2},
           "path": [{"layer": "F.Cu", "start": [8, 10], "end": [20, 10], "width": 0.2}]}
    (r,) = phase_run.narrow_join_widths(phase, N(tasks=(task,)), [rec], "routed.kicad_pcb", Settings())
    assert r["stage"] == "legs" and r["net"] == "VB" and r["length_under_mm"] == 12.0
    assert phase_run.narrow_join_widths(phase, N(tasks=(task,)), [dict(rec, path=None)], "x", Settings()) == []
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_phase_widths.py -p no:cacheprovider`
Expected: FAIL, `board_widths` takes `islands`, and `phase_run` has no `narrow_join_widths`.

- [ ] **Step 3: Implement**

`board_widths(geometry, asks, stage, rise_c=None, copper_oz=None, neck_mm=KRT_NECKDOWN_LENGTH_MM + KRT_NECKDOWN_TAPER_MM, only=None, by="asked")`:
the body of today's (:155-212) with `need = {layer: asks[net][layer]}` per track layer (a track on a layer the ask
does not name is not judged), `tracks` filtered to `only` when given (by identity: `[c for c in only if c.net == net
and c.kind == "track"]`), `"stage": stage`, `"requested_mm": max(asks[net].values())`, `"declared": True`, and
`by` in each layer row. Delete `judged_on_board`.

`read_widths(summaries, judged)`: for each `(stage, _, path)`, `stage_widths(stage, _read(path))`, keeping the records
whose net is not in `judged` (the router's own `power_widths`/`design_rules.narrowed` for nets no board judgement
covered).

`phase_run.phase_widths(phase, calls, cfg)`:

```python
def phase_widths(phase, calls, cfg) -> list:
    """The width judgement of one phase (D17): for each call that asked a width, the copper it added (its board out
    against its board in) judged against what it asked, per layer."""
    from ..board_geometry import added_copper
    from ..values import CopperLayer
    from .read import read_board
    from .route_widths import board_widths, neck_allowance
    neck = neck_allowance(tuple(cfg.route_router_args) + tuple(phase.router_args)) if phase.neckdown else 0.0
    out = []
    for call, before, after in calls:
        if call.kind == "tasks":
            asks = {t.net: {CopperLayer.of(l): w for l, w in t.widths} for t in call.tasks}
            by = "current" if any(t.amps is not None for t in call.tasks) else "asked"
        elif call.width:
            asks = {n: {CopperLayer.of(l): call.width for l in phase.layers or ()} or None for n in call.nets}
            by = "asked"
        else:
            continue
        given, routed = read_board(str(before)), read_board(str(after))
        new = added_copper(given.copper, routed.copper)
        asks = {n: a or {l: call.width for l in routed.layers} for n, a in asks.items()}
        out += board_widths(routed, asks, phase.name, cfg.check_rise_c, None, neck, only=new, by=by)
    return out
```

`phase_run.narrow_join_widths` (D3's fallback, Task 5 step 3; a record without `path` returns nothing, so this is
inert when KRT routes `joined_narrow` tasks):

```python
def narrow_join_widths(phase, sel, connections, routed_pcb, cfg) -> list:
    """A task KRT reported `joined_narrow` and left unrouted (D3's fallback): the joining path its record names is
    judged against the task's asked widths, so the phase raises route.width on it. The path is matched to the routed
    board's tracks of the net by layer and both ends (to the micrometre)."""
    from ..values import CopperLayer
    from .read import read_board
    from .route_widths import board_widths, neck_allowance
    narrow = [r for r in connections if r.get("status") == "joined_narrow" and r.get("path")]
    if not narrow:
        return []
    tasks = {(t.net, tuple(t.start), tuple(t.end)): t for t in sel.tasks}
    routed = read_board(str(routed_pcb))
    neck = neck_allowance(tuple(cfg.route_router_args) + tuple(phase.router_args)) if phase.neckdown else 0.0
    out = []
    for r in narrow:
        t = tasks.get((r["net"], (r["from"]["ref"], r["from"]["pad"]), (r["to"]["ref"], r["to"]["pad"])))
        if t is None:
            continue
        path = {(CopperLayer.of(s["layer"]), _ends(s["start"], s["end"])) for s in r["path"]}
        only = [c for c in routed.copper if c.kind == "track" and c.net == t.net and len(c.anchors) == 2
                and any((layer, _ends(*c.anchors)) in path for layer in c.layers)]
        asks = {t.net: {CopperLayer.of(layer): w for layer, w in t.widths}}
        out += board_widths(routed, asks, phase.name, cfg.check_rise_c, None, neck, only=only,
                            by="current" if t.amps is not None else "asked")
    return out


def _ends(a, b) -> frozenset:
    return frozenset((round(p[0], 3), round(p[1], 3)) for p in (a, b))
```

`run_phase` sets `out.record["widths"] = phase_widths(phase, out.calls, ctx.cfg) + narrow_join_widths(phase, sel,
connections, board, ctx.cfg)` after the phase DRC.
`_route_board` sets `report.widths = [w for p in records for w in p["widths"]] + read_widths(summaries, judged)`
where `judged` is the nets of those records, and sends `route_width` events as today (route.py:1323-1325).

- [ ] **Step 4: Run the tests**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_phase_widths.py tests/test_route_widths.py tests/test_route_widths_board.py tests/test_route_phases.py -n 2 -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A src tests
git commit -m "Routing phases: a phase's widths judged on the copper each call added, per layer, its finding naming the phase"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 16: placemat: net clearance from the capture

**Files:**
- Rename: `$WT/src/placemat/kicad/net_halos.py` -> `$WT/src/placemat/kicad/net_clearance.py` (`git mv`)
- Modify: `$WT/src/placemat/kicad/route.py` (the map from the capture; report keys), `$WT/src/placemat/findings.py`
  (`SETUP_NET_HALO` -> `SETUP_NET_CLEARANCE`, `"setup.net_clearance"`), `$WT/src/placemat/finding_text.py` (its text)
- Modify: `$WT/tests/test_net_halos.py` -> `$WT/tests/test_net_clearance.py` (`git mv`, rewritten)
- Modify: every importer of `net_halos` (`grep -rn net_halos src tests`)

**Interfaces:**
- Consumes: `Capture.clearances()` (Task 9).
- Produces: `net_clearance.write_map(rpy, router_dir, pcb, names, clearances: dict, path, ceiling, env) -> Path`,
  `net_clearance.trapped(geometry, clearances, judged=None) -> list`, `net_clearance.findings(trapped) -> list`
  (`setup.net_clearance`), `merged`, `class_clearances`, `ceiling` unchanged. `RouteReport.net_clearances: dict`,
  `net_clearance_trapped: list`, `net_clearance_facts: list` (D22). With a capture that states clearances, every router
  call of every phase gets `--net-clearances` with each net at the larger of its class clearance and its `clearance`
  field, and `clearance_groups` uses the same map.

- [ ] **Step 1: Rewrite the tests to fail**

`tests/test_net_clearance.py` keeps the pure tests of `merged`, `ceiling`, `trapped` (renaming `halos` to
`clearances`) and the router-args refusal of `--net-clearances`, deletes the `[route] net_halos` setting tests
(Task 25 removes the setting; the route refuses it since Task 13), and adds:

```python
@needs_kicad
def test_a_captures_clearance_reaches_every_phase_call_and_the_groups(rig, tmp_path):
    side = rig.pcb.with_name("nets.layout.json")
    write_sidecar(rig.pcb.parent, {"SW": {"type": "Power", "fields": {"clearance": {"value": 2.0, "unit": "mm"}}},
                                   "FB": {"type": "Net", "fields": {}}, "VIN": {"type": "Power", "fields": {}}})
    report = rig.route({"name": "fb", "nets": ["FB"]}, {"name": "signals"})
    calls = rig.calls()
    assert all("--net-clearances" in c for c in calls)
    m = json.loads(open(calls[0][calls[0].index("--net-clearances") + 1]).read())
    assert m["SW"] == 2.0 and report.net_clearances == {"SW": 2.0}
    assert side.exists()


@needs_kicad
def test_a_pad_trapped_inside_a_nets_clearance_is_a_setup_finding(rig):
    write_sidecar(rig.pcb.parent, {"SW": {"type": "Power", "fields": {"clearance": {"value": 2.0, "unit": "mm"}}}})
    said = []
    rig.route({"name": "signals"}, on_setup=said.extend)
    assert said and said[0].cause.value == "setup.net_clearance"
```

`write_sidecar(folder, nets, **over)` writes `default.net` and a sidecar with that file's sha256: stage 1
(`exports` types and fields) unless `over` sets `exports`, `interfaces` or `pairs`. Move the `write` helper of
tests/test_capture_nets.py into tests/phase_helpers.py as this function and use it from both. The `rig` is the one in
tests/test_route_phases.py (import it, or move it to phase_helpers.py as a fixture factory).

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_net_clearance.py -p no:cacheprovider`
Expected: FAIL, no module `net_clearance`.

- [ ] **Step 3: Implement**

`git mv` the module; rename `halos` parameters and docstrings to clearances ("a net's own clearance, from the
capture"); delete `on_board` (a sidecar is keyed by the board's own names and its digest is checked). In
`_route_board`, after reading the capture:

```python
    stated = {n: c for n, c in (capture.clearances() if capture else {}).items() if n in geometry.nets}
    trapped = net_clearance.trapped(geometry, stated, judged={n for n in open0 if open0[n]}) if stated else []
    clearance_findings = net_clearance.findings(trapped)
    if clearance_findings and on_setup is not None:
        on_setup(clearance_findings)
    ceiling = net_clearance.ceiling(cfg.route_router_args, env)
    clearances_file = net_clearance.write_map(rpy, router_dir_path, pcb_in, geometry.nets, stated,
                                              work / net_clearance.MAP_NAME, ceiling, env) if stated else None
    clearance_map = (json.loads(clearances_file.read_text()) if clearances_file else
                     net_clearance.merged(net_clearance.class_clearances(rpy, router_dir_path, pcb_in, geometry.nets, env),
                                          {}, ceiling))
```

and pass `clearances_file` in `PhaseContext`; the pairs call passes the stated clearances to `route_pairs` as its
`halos` argument (renamed `clearances` in Task 25). `FindingCause.SETUP_NET_CLEARANCE = "setup.net_clearance"` and its
text in finding_text.py name the net, its clearance and the trapped pad, as the halo finding did.

- [ ] **Step 4: Run the tests**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -n 2 -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Docs and commit**

api.md: the clearance paragraph says a net's clearance is its `clearance` field in the capture (circuit-capture's
"Where a fact lives"); the finding table row (api.md:5055) becomes `setup.net_clearance`. migration.md "## Unreleased"
"Changed": the finding's new name.

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A src tests skills
git commit -m "Routing phases: a net's clearance comes from the capture's clearance field"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 17: placemat: fixtures and the reference set on phases

**Files:**
- Modify: `$WT/fixtures/reference/route_ref.py:184-216` (`_route`, `run_a`), `$WT/fixtures/reference/fetch.py`
  (`Board.islands` -> `Board.phases`), `$WT/fixtures/reference/manifest.json` (`islands` -> `phases`),
  `$WT/fixtures/reference/README.md` (manifest keys; the pic_programmer line)
- Modify: `$WT/fixtures/reference/boards/pic_programmer/placemat.toml`, `$WT/fixtures/reference/boards/usb-c-power-adapter/placemat.toml`
- Modify: `$WT/fixtures/fairing/{keep_out,mcu_fan,via_clearance,usb_cells}/placemat.toml`
- Create: `$WT/fixtures/mnb/placemat.toml`
- Modify: `$WT/tests/test_reference_route.py:86-104, 204`, `$WT/tests/test_reference_place.py`

**Interfaces:**
- Consumes: `route_phase.parse_phases` (Task 8), `kicad.read.read_board`.
- Produces: `route_phase.default_phases` and `phases_toml` (used again by Task 19):

```python
def default_phases(*, pairs: bool, interface_types: list, wide_classes: list, currents: bool) -> list[dict]
    # in order: "diff-pairs" (pairs = true) if pairs; "buses" (interfaces = [...]) if interface_types;
    # "wide-clearance" (net_classes = [...]) if wide_classes; "current" (current_paths = true, width = "current")
    # if currents; "signals" (rest) always
def phases_toml(phases: list[dict], notes: dict | None = None) -> str     # [[route.phase]] blocks, each with a comment
```

- Also produces: route_ref.py writes, for each test (a) board, a placemat.toml holding the manifest's `phases` first, then
  the board's default phases (no capture, D18: no pair or interface phase), and for the human-width run
  `[route] router_args = ["--track-width", W]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_reference_route.py`, the board is built with `phases=({"name": "vcc", "nets": ["VCC"]},)` in place of
`islands=("VCC",)`, `_route`'s stand-in takes `(pcb, work, toml)`, and:

```python
    assert '[[route.phase]]\nname = "vcc"\nnets = ["VCC"]' in seen["toml"]
    assert seen["toml"].index('name = "vcc"') < seen["toml"].index('name = "signals"')
    assert "--track-width" in seen["toml"]
```

A unit test of `default_phases` in `tests/test_route_phase_form.py`:

```python
def test_the_default_phases_reproduce_the_old_stages_in_order():
    from placemat.route_phase import default_phases, parse_phases, phases_toml
    got = default_phases(pairs=True, interface_types=["Spi"], wide_classes=["RF"], currents=True)
    assert [p["name"] for p in got] == ["diff-pairs", "buses", "wide-clearance", "current", "signals"]
    import tomllib
    assert parse_phases(tomllib.loads(phases_toml(got))["route"]["phase"])[-1].selector == "rest"
    assert [p["name"] for p in default_phases(pairs=False, interface_types=[], wide_classes=[], currents=False)] == ["signals"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_reference_route.py tests/test_route_phase_form.py -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

`route_phase.py`:

```python
def default_phases(*, pairs: bool, interface_types: list, wide_classes: list, currents: bool) -> list:
    out = []
    if pairs:
        out.append({"name": "diff-pairs", "pairs": True})
    if interface_types:
        out.append({"name": "buses", "interfaces": sorted(interface_types)})
    if wide_classes:
        out.append({"name": "wide-clearance", "net_classes": sorted(wide_classes)})
    if currents:
        out.append({"name": "current", "current_paths": True, "width": "current"})
    out.append({"name": "signals"})
    return out


_NOTES = {"diff-pairs": "the capture's DiffPair instances, routed as pairs",
          "buses": "each interface instance of these types routed together as one bus",
          "wide-clearance": "the net classes whose clearance is above the Default's",
          "current": "each pair of parts that carry current (Pm.I), at the width the lesser current needs",
          "signals": "every connection still open, at the net classes' widths"}


def phases_toml(phases: list, notes: dict | None = None) -> str:
    import json
    notes = dict(_NOTES, **(notes or {}))
    blocks = []
    for p in phases:
        lines = ["# " + notes[p["name"]]] if p["name"] in notes else []
        lines.append("[[route.phase]]")
        lines += ["%s = %s" % (k, json.dumps(v)) for k, v in p.items()]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
```

(`json.dumps` of `true` and lists is valid TOML for these values: strings, numbers, booleans, lists of strings.
Connections tables are not in the defaults.)

route_ref.py: `_route(pcb, work, toml)` always writes the toml; `run_a` builds it:

```python
def phases_for(board: fetch.Board, pcb: pathlib.Path) -> str:
    """The board's routing phases: the manifest's own first, then its defaults (the board has no capture, so no pair or
    interface phase; D18 of the routing-phases plan)."""
    from placemat.kicad.read import read_board
    from placemat.route_phase import default_phases, phases_toml
    g = read_board(str(pcb))
    default = {nc.clearance for n, nc in g.netclasses.items() if nc.name == "Default"}
    base = min(default) if default else g.default_clearance
    wide = sorted({nc.name for nc in g.netclasses.values() if nc.clearance > base + 1e-9})
    return phases_toml(list(board.phases) + default_phases(pairs=False, interface_types=[], wide_classes=wide,
                                                           currents=False))
```

and `toml = phases_for(board, work / prepare.TEST) + ("" if track_mm is None else '\n[route]\nrouter_args = ["--track-width", "%s"]\n' % track_mm)`.
Remove the `--islands` argument from `_route`. manifest.json: every `"islands": [...]` becomes `"phases": [...]`;
pic_programmer's is `[{"name": "vcc", "nets": ["VCC"]}]` (its pour does not reach its pads). fetch.Board reads
`phases` (a tuple of dicts). README: the manifest key row and the pic_programmer line.

The two reference boards' placemat.toml: append `phases_toml(default_phases(...))` for what each capture has (both:
currents true; pairs per their captures, false until Task 22 regenerates them with the fork), keeping their comment
that every setting is at its default and adding "Routing: the default phases (`placemat settings --example`)".

`fixtures/fairing/{keep_out,mcu_fan,via_clearance}/placemat.toml`: the `islands = [...]` line becomes

```toml
[[route.phase]]
name = "pour-taps"                 # the sink switch's 0.5 A
nets = ["VSHUNT"]
width = 0.3

[[route.phase]]
name = "pour-nets"                 # the pour nets' pads their pours do not reach
nets = ["VBIKE", "GND", "V3V3"]

[[route.phase]]
name = "signals"
```

(placed after the other sections: an array of tables cannot precede a `[route]` table in TOML; if the file has
other `[route]` keys, put them before the phase blocks). `usb_cells` and the new `fixtures/mnb/placemat.toml` hold
only `name = "signals"` with a comment that the family's modules route every open connection at the class widths.

- [ ] **Step 4: Run the tests and one real board**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_reference_route.py tests/test_reference_place.py tests/test_route_phase_form.py -n 2 -p no:cacheprovider
df -h ~ | tail -1
flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock env KRT_DIR=/home/ben/work/KRT-phases PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/reference/route_ref.py pic_programmer --changing placemat krt
```

Expected: the tests PASS; pic_programmer routes through phases `vcc`, `wide-clearance`, `signals` and its line
compares with the recorded entry (do not `--update` here; the gate run is Task 26).

- [ ] **Step 5: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A fixtures tests src
git commit -m "Reference set and fixtures route by phases: the manifest's islands become phases, the boards' defaults written"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 18: placemat: `route --phase/--only`, and what a route reports per phase

**Files:**
- Modify: `$WT/src/placemat/cli.py:79-102` (route parser), `:703-770` (`cmd_route`), `$WT/src/placemat/kicad/route.py`
  (`RouteReport.summary`, `as_dict`, new `phase_lines`), `$WT/src/placemat/route_progress.py:172-188`
  (`write_record`: the report's `phases`), `$WT/src/placemat/channel.py:615-616` (`route_stage` text),
  `$WT/src/placemat/detach.py:231-249, 285-300` (`run_facts` and `summary_lines`), `$WT/src/placemat/runner.py`
  (the run's route lines), `$WT/src/placemat/studio_page.html:3223` (the stage pill names the phase and its place)
- Create: `$WT/tests/test_route_phase_cli.py`
- Modify: `$WT/tests/surface/cli.txt` (`route --phase`, `route --only`)

**Interfaces:**
- Consumes: `RouteReport.phases`, `phases_without_copper` (Task 13).
- Produces:

```python
def phase_lines(phases: list, without_copper: list = ()) -> list[str]
    # one line per phase record: "phase NAME (SELECTOR): J of A joined clean (P%), T s[, reused][; open: ...]"
    # then "earlier phases with no copper on this board: ..." when without_copper
```

  `route_stage` events gain `"phase": index` and `"of": count`; `channel` renders "route phase 2 of 5, power-legs";
  the studio pill shows the same fields. `route_record.json`'s `report` keeps `phases`; `route_summary.json` gains
  `"phases": [{"name", "asked", "joined", "closure_clean", "reused"}]`. `watch --summary` of a run prints
  `phase_lines` under the route's line.

- [ ] **Step 1: Write the failing test**

`tests/test_route_phase_cli.py`:

```python
"""route --phase NAME routes up to and including NAME; --only routes just it on the board as it is; each phase is
said with its closure."""
from placemat.cli import parser
from placemat.kicad.route import phase_lines


def test_the_route_command_takes_phase_and_only():
    a = parser().parse_args(["route", "b.kicad_pcb", "--phase", "legs", "--only"])
    assert a.phase == "legs" and a.only is True


def test_only_without_a_phase_is_refused(capsys):
    from placemat.cli import main
    assert main(["route", "b.kicad_pcb", "--only"]) == 2
    assert "--only routes the phase --phase names" in capsys.readouterr().out


def test_each_phase_is_one_line_with_its_closure_and_what_is_open():
    lines = phase_lines([
        {"name": "legs", "selector": "current_paths", "asked": 4, "joined": 3, "closure_clean": 0.75, "seconds": 12.0,
         "reused": False, "open": [{"net": "VB", "from": {"ref": "J1", "pad": "2"}, "to": {"ref": "Q1", "pad": "1"}}]},
        {"name": "signals", "selector": "rest", "asked": 40, "joined": 40, "closure_clean": 1.0, "seconds": 80.0,
         "reused": True, "open": []}], ["legs"])
    assert lines[0] == "phase legs (current_paths): 3 of 4 joined clean (75.0%), 12 s; open: VB J1.2-Q1.1"
    assert lines[1] == "phase signals (rest): 40 of 40 joined clean (100.0%), 80 s, reused"
    assert lines[2] == "earlier phases with no copper on this board: legs"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_phase_cli.py -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

Parser: `rt.add_argument("--phase", metavar="NAME", help="route the phases up to and including NAME: earlier phases whose kept result still matches are reused, the others routed first")`,
`rt.add_argument("--only", action="store_true", help="with --phase: route just that phase against the copper the board has now, and name the earlier phases that have no copper on it")`.
`cmd_route`: `--only` without `--phase` says "--only routes the phase --phase names: give --phase NAME" and returns 2;
passes `upto=args.phase, only=args.only`; prints `phase_lines(report.phases, report.phases_without_copper)` after the
summary line. `--no-resume`'s help says "route every phase again".

```python
def phase_lines(phases: list, without_copper=()) -> list:
    out = []
    for p in phases:
        line = "phase %s (%s): %d of %d joined clean (%.1f%%), %.0f s%s" % (
            p["name"], p["selector"], p["joined"], p["asked"], 100 * p["closure_clean"], p["seconds"],
            ", reused" if p.get("reused") else "")
        opened = ["%s %s.%s-%s.%s" % (o["net"], o["from"]["ref"], o["from"]["pad"], o["to"]["ref"], o["to"]["pad"])
                  if "from" in o else "%s %d" % (o["net"], o["items"]) for o in p.get("open") or ()]
        if opened:
            line += "; open: " + ", ".join(opened)
        out.append(line)
    if without_copper:
        out.append("earlier phases with no copper on this board: " + ", ".join(without_copper))
    return out
```

`RouteReport.summary` drops the pairs/islands/class-stage segments' use (their fields stay empty until Task 25
deletes them) and adds `"  phases: " + ", ".join("%s %.0f%%" % (p["name"], 100 * p["closure_clean"]) for p in self.phases)`.
`as_dict` gains `"phases"` and `"phases_without_copper"`. `RouteEvents.begin(stage, nets=None, phase=None, of=None)`
puts `phase`/`of` on the `route_stage` event; `_route_board` passes `i + 1, len(run_list)`. channel.py:615:
`"route phase %d of %d, %s%s" % (ev["phase"], ev["of"], ev["stage"], " (taken from an earlier route)" ...)` when
`phase` is present. detach.py `run_facts` keeps `m["route"]["phases"]` and `summary_lines` adds `phase_lines`.
runner.py says `phase_lines` after the route summary. studio_page.html:3223 keeps `R.phase`/`R.of` from the event and
the pill reads "phase 2/5 power-legs".

- [ ] **Step 4: Run the tests**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_route_phase_cli.py tests/test_cli_surface.py tests/test_channel.py tests/test_studio_page.py tests/test_route_events.py -n 2 -p no:cacheprovider`
Expected: PASS after adding the two options to tests/surface/cli.txt.

- [ ] **Step 5: Docs and commit**

api.md: `placemat route` synopsis (:3373) with `--phase NAME [--only]`, the per-phase lines and record keys.
migration.md "## Unreleased" "New": `route --phase NAME`, `--only`, the per-phase report.

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A src tests skills
git commit -m "Routing phases: route --phase and --only, and each phase's closure in the report, watch and the studio"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 19: placemat: the default phases in `settings --example`

**Files:**
- Modify: `$WT/src/placemat/settings.py:1062-1091` (`example_toml(phases_block=None)`), `$WT/src/placemat/cli.py:339-346, 426-432`
- Modify: `$WT/tests/test_settings_docs.py:37-52`
- Create: `$WT/tests/test_settings_example_phases.py`

**Interfaces:**
- Consumes: `default_phases`, `phases_toml` (Task 17); `capture_beside` (Task 9); `checks.carriers_of`.
- Produces: `example_toml(phases_block: str | None = None) -> str`: every setting as today, `route.phase` left out of
  the `[route]` key list, and the phase block at the end of the file (D24: without a board, `signals` alone).
  `placemat settings <script|board dir|layout.kicad_pcb> --example` writes the board's defaults:
  `cli.board_default_phases(pcb) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_settings_example_phases.py`:

```python
"""`placemat settings --example` writes the default routing phases: for a board, from what it has."""
import tomllib

from placemat.cli import board_default_phases
from placemat.settings import example_toml, load
from tests.conftest import needs_kicad
from tests.phase_helpers import board_with_power_and_rf, write_sidecar


def test_without_a_board_the_example_has_the_rest_phase(tmp_path):
    text = example_toml()
    assert [p["name"] for p in tomllib.loads(text)["route"]["phase"]] == ["signals"]
    (tmp_path / "placemat.toml").write_text(text)
    assert [p["name"] for p in load(tmp_path).route_phase] == ["signals"]


@needs_kicad
def test_a_board_with_currents_a_wide_class_and_a_capture_gets_their_phases(tmp_path):
    pcb = board_with_power_and_rf(tmp_path)          # J1/Q1 Pm.I 4A on VB; RF in a 0.3 mm class
    write_sidecar(pcb.parent, {"VB": {"type": "Power", "fields": {}}}, exports=["types", "fields", "interfaces"],
                  interfaces={"S": {"type": "Spi", "members": {"CLK": "S_CLK", "MOSI": "S_MOSI"}}}, pairs=[])
    names = [p["name"] for p in board_default_phases(pcb)]
    assert names == ["buses", "wide-clearance", "current", "signals"]
```

`board_with_power_and_rf(tmp_path)` writes a board as text in the style of `tests/test_net_halos._two_part_board`
(a `layout.kicad_pcb` in a folder of its own, its `.kicad_pro` from that file's `_project`) with `Pm.I` fields on J1
and Q1 (net VB between them) and a class "RF" at 0.3 mm for net RF; put it in tests/phase_helpers.py.

In `tests/test_settings_docs.py`, `test_the_example_toml_is_valid_complete_and_loads_to_the_defaults` compares
`load(tmp_path)` with `replace(Settings(), route_phase=({"name": "signals"},))` and skips `route_phase` in the
every-key regex check (its form is the `[[route.phase]]` block).

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_settings_example_phases.py tests/test_settings_docs.py -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

`example_toml(phases_block=None)`: skip `route_phase` in the per-section loop; append
`"# " + "-" * 76`, `"# route.phase: the routing phases, in order (api.md \"Routing phases\")"`, then
`phases_block or phases_toml(default_phases(pairs=False, interface_types=[], wide_classes=[], currents=False))`.

```python
def board_default_phases(pcb) -> list:
    """The default phases for a board (spec "No phases"): its differential pairs and its interface types when the
    capture exports them, its net classes above the Default's clearance, current paths when any part states a current,
    then the rest."""
    from .capture_nets import capture_beside
    from .checks import carriers_of
    from .kicad.read import read_board
    from .route_phase import default_phases
    g = read_board(str(pcb))
    cap = capture_beside(pcb)
    interfaces = "interfaces" in cap.exports if cap else False
    default = [nc.clearance for nc in g.netclasses.values() if nc.name == "Default"]
    base = min(default) if default else g.default_clearance
    return default_phases(pairs=bool(interfaces and cap.pairs),
                          interface_types=sorted({i.type for i in cap.instances.values() if i.type != "DiffPair"})
                          if interfaces else [],
                          wide_classes=sorted({nc.name for nc in g.netclasses.values() if nc.clearance > base + 1e-9}),
                          currents=any(len(on) >= 2 for on in carriers_of(g).values()))
```

`cmd_settings`: with `--example` and a `where` that resolves to a board (a script or directory: `find_board(p).pcb`
when it exists; a `.kicad_pcb` path as given), `example_toml(phases_toml(board_default_phases(pcb)))`; else
`example_toml()`.

- [ ] **Step 4: Run the tests**

Run: same as step 2, then `-n 2` over `tests/test_settings*.py`. Expected: PASS.

- [ ] **Step 5: Docs and commit**

api.md "Routing phases": the default phases and where they come from. SKILL.md: "start from `placemat settings
<board> --example`".

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A src tests skills
git commit -m "Routing phases: settings --example writes a board's default phases"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 20: placemat: `run --route-rank`

**Files:**
- Modify: `$WT/src/placemat/cli.py:59-64` (a `--route-rank` option after `--route-best`), `_explore_options`
- Modify: `$WT/src/placemat/explore.py:206-213` (`Routing.rank`), `:745` (entry `phases`), `:1047-1053` (`_taken`),
  `:1389-1400` (`route_line`)
- Modify: `$WT/src/placemat/detach.py:271` (route entry keys), `$WT/tests/surface/cli.txt`
- Create: `$WT/tests/test_explore_route_rank.py`

**Interfaces:**
- Consumes: `RouteReport.phases`.
- Produces: `run --route-rank PHASE[,PHASE...]` (with `--route-best`); each routed variant's entry gains
  `"phases": {name: closure_clean}`; `_taken(routes, scores, rank=())` orders by each ranked phase's clean closure,
  in order, then the board-wide clean closure, then the run score, then the seed. A rank naming no phase of the
  project is refused before the explore starts.

- [ ] **Step 1: Write the failing test**

`tests/test_explore_route_rank.py`:

```python
"""explore --route-rank orders the routed variants by named phases' clean closure, then as before."""
import pytest

from placemat.explore import _taken


def routes():
    return [{"seed": 1, "closure_clean": 0.95, "score": 10.0, "error": None, "phases": {"legs": 0.5, "signals": 0.97}},
            {"seed": 2, "closure_clean": 0.90, "score": 12.0, "error": None, "phases": {"legs": 1.0, "signals": 0.9}},
            {"seed": 3, "closure_clean": 0.90, "score": 11.0, "error": None, "phases": {"legs": 1.0, "signals": 0.9}}]


def test_without_a_rank_the_board_wide_closure_decides():
    assert _taken(routes(), {}) == 1


def test_a_ranked_phase_comes_first_then_the_score():
    assert _taken(routes(), {}, rank=("legs",)) == 3


def test_a_rank_naming_no_phase_is_refused(tmp_path):
    from placemat.cli import _route_rank
    with pytest.raises(SystemExit):
        _route_rank("legs,bogus", ("legs", "signals"))
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_explore_route_rank.py -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def _taken(routes: list, scores: dict, rank=()):
    closed = [r for r in routes if not r.get("error")]
    if not closed:
        return None
    return min(closed, key=lambda r: tuple(-(r.get("phases") or {}).get(name, 0.0) for name in rank)
               + (-r["closure_clean"], scores.get(r["seed"], r["score"]), r["seed"]))["seed"]
```

(keep whatever `_taken` does today for an empty `closed`; read :1047-1053 and keep that line.) `_route_work`'s entry:
`entry["phases"] = {p["name"]: p["closure_clean"] for p in r.phases}`. `Routing.rank: tuple = ()`, passed from
`run --route-rank` through the runner; `_taken(result.routes, ..., rank=routing.rank)`. `route_line` appends
`"; " + ", ".join("%s %.1f%%" % (n, 100 * c) for n, c in r["phases"].items())` when present. cli:

```python
def _route_rank(text: str, names) -> tuple:
    wanted = tuple(x.strip() for x in text.split(",") if x.strip())
    bad = [w for w in wanted if w not in names]
    if bad:
        raise SystemExit("--route-rank: no phase %s; the phases are %s" % (", ".join(bad), ", ".join(names)))
    return wanted
```

called in `_explore_options` with the bound settings' phase names; `--route-rank` without `--route-best` (flag or
setting) is refused there too.

- [ ] **Step 4: Run the tests**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_explore_route_rank.py tests/test_explore_route.py tests/test_cli_surface.py -n 2 -p no:cacheprovider`
Expected: PASS after adding `run --route-rank` to tests/surface/cli.txt.

- [ ] **Step 5: Docs and commit**

api.md explore section: `--route-rank`. migration.md "## Unreleased" "New": rank variants by a phase.

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A src tests skills
git commit -m "Routing phases: explore ranks routed variants by named phases' clean closure"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 21: Zener: interface membership and `DiffPair`, stage 2

**Files:**
- Modify: `$ZW/crates/pcb-zen-core/src/lang/module.rs:68-73, 461-463, 585` (a `bound_interfaces` registry)
- Modify: `$ZW/crates/pcb-zen-core/src/lang/context.rs:327-331` (a pass-through)
- Modify: `$ZW/crates/pcb-zen-core/src/lang/interface.rs:678-710, 714-729` (record at the binding)
- Modify: `$ZW/crates/pcb-zen-core/src/convert.rs:234-319, 1174-1222` (instances into the schematic)
- Modify: `$ZW/crates/pcb-sch/src/lib.rs:753-776` (`InterfaceInstance`, `Schematic.interfaces`)
- Modify: `$ZW/crates/pcb-layout/src/nets_layout.rs` (`interfaces`, `pairs`, `exports`)
- Create: `$ZW/crates/pcb-zen-core/tests/interfaces_record.rs`; register in `tests/integration.rs`
- Modify: `$ZW/crates/pcb-layout/tests/nets_layout.rs`, `$ZW/CHANGELOG.md`, `$ZW/docs/pages/spec.mdx`

**Interfaces:**
- Consumes: Task 3's sidecar.
- Produces: `pcb_sch::InterfaceInstance { path: String, type_name: String, members: BTreeMap<String, String> }`
  (member path such as `"CLK.P"` -> final net name) and `Schematic.interfaces: Vec<InterfaceInstance>` (serde default,
  skipped when empty). Paths (D7): a module-level binding `DISP = Spi()` in the root is `DISP`, in module `display`
  it is `display.DISP`; an io() parameter `SPI` of module `display` is `display.SPI`; a nested interface is its own
  entry (`CAM.CLK`, type `DiffPair`, members `P`, `N`) and also dotted members of its parent (`CLK.P`). An instance
  bound to no module-level name and passed to no io() has no entry. The sidecar's `exports` gains `"interfaces"`;
  each net gains `"interfaces": [{"instance", "type", "member"}]`; top level gains
  `"interfaces": {path: {"type", "members"}}` and `"pairs": [{"instance", "p", "n"}]` for every `DiffPair` entry.

- [ ] **Step 1: Write the failing test**

`crates/pcb-zen-core/tests/interfaces_record.rs` (the model is name_inference.rs:118-147 and not_connected.rs:5-15):

```rust
use crate::common;

fn schematic(files: &[(&str, &str)]) -> pcb_sch::Schematic {
    let mut all = common::stdlib_test_files();
    for (k, v) in files {
        all.insert((*k).to_string(), (*v).to_string());
    }
    let result = common::eval_zen_raw(all, "test.zen");
    assert!(result.is_success(), "eval failed: {:?}", result.diagnostics);
    result.output.unwrap().to_schematic_with_diagnostics().output.unwrap()
}

fn find<'a>(s: &'a pcb_sch::Schematic, path: &str) -> &'a pcb_sch::InterfaceInstance {
    s.interfaces.iter().find(|i| i.path == path).unwrap_or_else(|| panic!("no {path} in {:?}", s.interfaces))
}

#[test]
#[cfg(not(target_os = "windows"))]
fn an_inferred_root_instance_is_recorded_by_its_variable_name() {
    let s = schematic(&[("test.zen", r#"
load("interfaces.zen", "Spi")
DISP = Spi()
"#)]);
    let disp = find(&s, "DISP");
    assert_eq!(disp.type_name, "Spi");
    assert_eq!(disp.members.get("CLK").map(String::as_str), Some("DISP_CLK"));
}

#[test]
#[cfg(not(target_os = "windows"))]
fn a_named_instance_is_recorded_by_its_variable_not_its_name() {
    let s = schematic(&[("test.zen", r#"
load("interfaces.zen", "Spi")
X = Spi(name="BUS")
"#)]);
    let x = find(&s, "X");
    assert_eq!(x.members.get("CLK").map(String::as_str), Some("BUS_CLK"));
}

#[test]
#[cfg(not(target_os = "windows"))]
fn a_nested_diff_pair_is_an_entry_of_its_own() {
    let s = schematic(&[("test.zen", r#"
load("interfaces.zen", "Csi")
CAM = Csi()
"#)]);
    let clk = find(&s, "CAM.CLK");
    assert_eq!(clk.type_name, "DiffPair");
    assert!(clk.members.contains_key("P") && clk.members.contains_key("N"));
    assert!(find(&s, "CAM").members.contains_key("CLK.P"));
}

#[test]
#[cfg(not(target_os = "windows"))]
fn an_instance_passed_to_a_module_is_also_its_io_path_and_an_alias_is_one_record() {
    let s = schematic(&[
        ("display.zen", r#"
load("interfaces.zen", "Spi")
SPI = io(Spi)
"#),
        ("test.zen", r#"
load("interfaces.zen", "Spi")
Display = Module("display.zen")
DISP = Spi()
BUS = DISP
Display(name="display", SPI=DISP)
"#),
    ]);
    assert_eq!(find(&s, "display.SPI").members.get("CLK"), find(&s, "DISP").members.get("CLK"));
    assert!(s.interfaces.iter().all(|i| i.path != "BUS"), "an alias of a recorded instance is not a second record");
}
```

In `crates/pcb-layout/tests/nets_layout.rs` add a case: a `Schematic` with `interfaces = [Spi DISP, DiffPair USB.D]`
gives `exports` with `"interfaces"`, `doc["pairs"] == [{"instance": "USB.D", "p": "USB_D_P", "n": "USB_D_N"}]` and
`doc["nets"]["DISP_CLK"]["interfaces"] == [{"instance": "DISP", "type": "Spi", "member": "CLK"}]`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd /home/ben/work/pcb-phases && CARGO_TARGET_DIR=$PWD/target cargo test -j 2 -p pcb-zen-core --test integration interfaces_record`
Expected: FAIL, `Schematic` has no field `interfaces`.

- [ ] **Step 3: Implement (the design of research/2026-10-07/zener-stage2-trace.md, "Proposed design")**

1. module.rs, next to `IntroducedNet` (:68-73):

```rust
#[derive(Clone, Debug, Trace, Allocative, Freeze)]
pub struct BoundInterface {
    pub name: String,
    pub type_name: String,
    pub members: Vec<(String, NetId)>,      // member path ("CLK", "CLK.P") -> net id
    pub nested: Vec<(String, String)>,      // nested path ("CLK") -> its type ("DiffPair")
}
```

   `ModuleValueGen` gains `bound_interfaces: Vec<BoundInterface>` beside `introduced_nets` (:463), initialised at the
   one constructor site (:585), with an accessor; `record_interface(&mut self, b: BoundInterface)` skips a record
   whose `type_name` and `members` equal one already held (an alias such as `BUS = DISP`).
2. context.rs: `pub(crate) fn record_interface(&self, b: BoundInterface)` borrowing the module mutably, as
   `infer_net_name` does (:327-331).
3. interface.rs `export_as` (:678): before the early return, walk `self.fields` (a helper shared with `Display`,
   :714-729, for the type name: `InterfaceTypeData.name` of the factory), collecting `(path, net id)` for nets and
   `(path, type)` for nested interfaces, recursing with dotted paths; call `context.record_interface` with
   `name: variable_name.to_string()`. The early return for `instance_root_name` stays after it (net naming unchanged).
4. convert.rs, after the nets are built (:278-319): for each module in the tree, its `bound_interfaces` and its
   non-config signature parameters whose `actual_value` is an interface (the walk `propagate_from_value` does,
   :1194-1222), each prefixed with the module path (`instance_ref.instance_path.join(".")`, :616; empty for the
   root), net ids mapped to final net names through `net_info` (an id with no net is dropped: an io() template net,
   interface.rs:83-111), nested interfaces emitted as entries of their own, deduplicated by (path), sorted by path,
   into `Schematic.interfaces`.
5. pcb-sch lib.rs (:753-776):

```rust
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterfaceInstance {
    pub path: String,
    pub type_name: String,
    pub members: BTreeMap<String, String>,
}
    // in Schematic:
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub interfaces: Vec<InterfaceInstance>,
```

6. nets_layout.rs: `exports` = `["types", "fields", "interfaces"]`; invert `schematic.interfaces` into each net's
   `interfaces` list (sorted by instance, member); top-level `interfaces` and `pairs` (instances of type `DiffPair`,
   `p` = members["P"], `n` = members["N"]).

Snapshot files that hold schematic JSON (crates/pcbc/tests/snapshots/release__publish_with_file.snap,
netlist__netlist_not_connected_open_intent.snap) change only if their capture binds an interface; if any snapshot
changes, stop and show the user the diff (AGENTS.md).

- [ ] **Step 4: Run the tests**

```bash
cd /home/ben/work/pcb-phases && CARGO_TARGET_DIR=$PWD/target cargo test -j 2 -p pcb-zen-core --test integration
CARGO_TARGET_DIR=$PWD/target cargo test -j 2 -p pcb-sch && CARGO_TARGET_DIR=$PWD/target cargo test -j 2 -p pcb-layout --test integration
df -h ~ | tail -1
CARGO_TARGET_DIR=$PWD/target cargo build -j 2 --release -p pcbc
```

Expected: PASS; the release binary builds.

- [ ] **Step 5: Docs, commit, push**

CHANGELOG: "- `nets.layout.json` names each net's interface instances and lists the differential pairs." spec.mdx:
an interface bound to a module-level name or an io() is exported by that name.

```bash
cd /home/ben/work/pcb-phases && git add crates CHANGELOG.md docs/pages/spec.mdx
git commit -m "layout: nets.layout.json carries interface instances and differential pairs"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
git push origin feat/nets-layout-json
```

---

## Task 22: placemat: pairs and interfaces from the capture

**Files:**
- Modify: `$WT/src/placemat/kicad/phase_select.py` (the `pairs` and `interfaces` selectors)
- Modify: `$WT/src/placemat/kicad/phase_run.py` (the pairs call reads `sel.pairs`)
- Modify: `$WT/fixtures/reference/boards/*/placemat.toml` (pair and bus phases where the regenerated capture has them)
- Create: `$WT/tests/test_phase_capture_selectors.py`
- Modify: `$WT/tests/test_route_pairs.py` (the route-driven pair tests, now from a sidecar)

**Interfaces:**
- Consumes: `Capture.instances`, `Capture.pairs` (Task 9), the stage-2 sidecar (Task 21).
- Produces: `pairs = true` selects each `DiffPair` instance's (P, N) whose nets are open, as `Selection.pairs`
  ((p, n) with P first); `interfaces = [...]` selects every instance whose type is named, or whose path is named
  (D7), each one bus of its member nets that are open and routable (nets with two pads or more); an instance of
  type `DiffPair` named by `interfaces` is a pair, not a bus. A path or type with no instance refuses the phase
  (`not_on_board`, kind `instance` or `type`).

- [ ] **Step 1: Write the failing test**

`tests/test_phase_capture_selectors.py`:

```python
"""pairs = true and interfaces select what the capture's nets.layout.json says (Zener fork stage 2)."""
import pytest

from placemat.capture_nets import read_capture
from placemat.kicad.phase_select import select
from placemat.route_phase import PhaseError, parse_phases
from tests.fixtures import board_geometry, footprint
from tests.phase_helpers import write_sidecar


def board():
    return board_geometry([footprint("U1", 5, 5, nets=("USB_D_P", "USB_D_N")), footprint("J1", 20, 5, nets=("USB_D_P", "USB_D_N")),
                           footprint("U2", 5, 20, nets=("DISP_CLK", "DISP_MOSI")), footprint("J2", 20, 20, nets=("DISP_CLK", "DISP_MOSI"))])


def capture(tmp_path):
    write_sidecar(tmp_path, {n: {"type": "Net", "fields": {}} for n in ("USB_D_P", "USB_D_N", "DISP_CLK", "DISP_MOSI")},
                  exports=["types", "fields", "interfaces"],
                  interfaces={"DISP": {"type": "Spi", "members": {"CLK": "DISP_CLK", "MOSI": "DISP_MOSI"}},
                              "USB.D": {"type": "DiffPair", "members": {"P": "USB_D_P", "N": "USB_D_N"}}},
                  pairs=[{"instance": "USB.D", "p": "USB_D_P", "n": "USB_D_N"}])
    return read_capture(tmp_path / "nets.layout.json")


def one(raw, cap):
    g = board()
    return select(parse_phases([raw])[0], g, cap, open_nets=set(g.nets), excluded=set(), pour_nets=set(),
                  route_layers=["F.Cu", "B.Cu"], rise_c=10.0, copper_oz=1.0)


def test_pairs_are_the_diffpair_instances(tmp_path):
    assert one({"name": "dp", "pairs": True}, capture(tmp_path)).pairs == (("USB_D_P", "USB_D_N"),)


def test_an_interface_type_selects_each_instance_as_a_bus(tmp_path):
    assert one({"name": "b", "interfaces": ["Spi"]}, capture(tmp_path)).buses == (("DISP_CLK", "DISP_MOSI"),)


def test_an_instance_is_selected_by_its_path(tmp_path):
    assert one({"name": "b", "interfaces": ["DISP"]}, capture(tmp_path)).buses == (("DISP_CLK", "DISP_MOSI"),)


def test_an_unknown_instance_is_refused(tmp_path):
    with pytest.raises(PhaseError) as e:
        one({"name": "b", "interfaces": ["CAM"]}, capture(tmp_path))
    assert e.value.code == "not_on_board" and e.value.facts["value"] == "CAM"


def test_a_stage_one_sidecar_refuses_interfaces(tmp_path):
    write_sidecar(tmp_path, {"DISP_CLK": {"type": "Net", "fields": {}}})
    with pytest.raises(PhaseError) as e:
        one({"name": "b", "interfaces": ["Spi"]}, read_capture(tmp_path / "nets.layout.json"))
    assert e.value.code == "needs_capture"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_phase_capture_selectors.py -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `select`, replacing the final `raise` for pairs and interfaces:

```python
    if phase.selector == "pairs":
        pairs = tuple((p, n) for _, p, n in capture.pairs
                      if (p in open_nets or n in open_nets) and p not in excluded and n not in excluded)
        return Selection(pairs=pairs, **base)
    if phase.selector == "interfaces":
        chosen = []
        for want in phase.interfaces:
            hit = [i for i in capture.instances.values() if i.path == want or i.type == want]
            if not hit:
                raise PhaseError("not_on_board", name=phase.name, kind="interface", value=want)
            chosen += [i for i in hit if i not in chosen]
        pairs, buses = [], []
        for inst in chosen:
            if inst.type == "DiffPair":
                pairs.append((inst.members["P"], inst.members["N"]))
                continue
            nets = tuple(sorted({n for n in inst.members.values() if n in routable and n in open_nets
                                 and n not in excluded}))
            if nets:
                buses.append(nets)
        return Selection(pairs=tuple(pairs), buses=tuple(buses), width=numeric, **base)
```

`phase_run.run_phase`'s pairs call passes `list(sel.pairs)`; `route_pairs` keeps renaming them to suffix aliases for
the pair router (route.py:678-686). The pair call's clearances are the capture's (Task 16).

`tests/test_route_pairs.py`: the route-driven tests deleted in Task 13 come back with a sidecar beside the board and a
`{"name": "dp", "pairs": True}` phase, checking that the pair router is called with the aliases and the outcome is in
`report.phases[0]["pairs"]`.

Regenerate the two reference boards' captures with the fork (`PATH=/home/ben/work/pcb-phases/bin:$PATH pcb layout`
in a scratch copy) and, where the capture binds a `DiffPair` or an interface, add the `diff-pairs`/`buses` phases to
its placemat.toml from `board_default_phases`.

- [ ] **Step 4: Run the tests**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_phase_capture_selectors.py tests/test_route_pairs.py tests/test_phase_select.py -n 2 -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: A generated board end to end**

```bash
df -h ~ | tail -1
flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock env PATH=/home/ben/work/pcb-phases/bin:$PATH KRT_DIR=/home/ben/work/KRT-phases PYTHONPATH=/home/ben/work/placemat/.claude/worktrees/routing-phases/src /home/ben/work/placemat/.venv/bin/python fixtures/reference/place_ref.py --modules mnb/UsbC --changing placemat krt pcb
```

Expected: the module generates a `nets.layout.json` with its USB pair, routes through `diff-pairs` then `signals`,
and its line reports the result (no `--update`).

- [ ] **Step 6: Docs and commit**

api.md: `pairs = true` and `interfaces` read the capture; an instance's path (D7). capture.md: a placemat phase can
select by the capture's interfaces, `DiffPair` instances and net types, which the Zener fork exports.

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A src tests fixtures skills
git commit -m "Routing phases: pairs and interfaces selected from the capture's DiffPair and interface instances"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 23: circuit-capture skill: buses as interfaces, pairs as `DiffPair`, a net's clearance on the net

**Files:**
- Modify: `/home/ben/work/circuit-capture/skills/circuit-capture/SKILL.md:62-90, 138-150`
- Modify: `/home/ben/work/circuit-capture/.claude-plugin/plugin.json` (0.1.6 -> 0.1.7)

**Interfaces:**
- Consumes: the Zener fork's stdlib `clearance` field (Task 2) and its export (Tasks 3, 21).
- Produces: the skill's rules, per the ledger row: a bus is a stdlib interface and that alone reaches the board (no
  `NetClass` per bus); a differential pair is a `DiffPair` instance; a net's electrical clearance is its `clearance`
  field; net classes keep width, clearance and impedance only; "Where a fact lives" and "A net-level fact with no
  class does not reach the board" rewritten. The skill names no tool or project (its charter, "Ask first").

- [ ] **Step 1: Read the skill's charter**

Run: `sed -n 1,60p /home/ben/work/circuit-capture/CHARTER.md`. The change reverses a rule ("a NetClass per bus"),
which its charter puts under "ask first". The user decided it in the 0.100 roadmap's removal ledger and approved this
task on 2026-10-07, so it goes ahead without stopping; cite that approval in the commit message.

- [ ] **Step 2: Rewrite the sections**

"Where a fact lives" rows become:

```markdown
| A net's width and impedance; a class's clearance | `NetClass(nets=[patterns])` in the board's `BoardConfig` | the project's net classes |
| A net's own electrical clearance (a high-voltage or switch net) | `clearance=Length(...)` on its net type (`Power("HV", clearance=Length("2mm"))`) | the net's fields, exported beside the netlist |
| A bus (SPI, I2C, CAN) | a stdlib `interface()` instance bound to a name (`DISP = Spi()`) or passed to a module's `io()` | the instance and its members, exported beside the netlist |
| A differential pair | a `DiffPair` instance, alone or inside an interface (`Usb2`, `Csi`) | the pair's two nets, exported beside the netlist |
| A net's kind (`Power`, `Ground`, `Gpio`, a custom type) | its net type | the net's type, exported beside the netlist |
```

and the paragraph under it: "A net's type, its fields, its interface instances and its pairs reach the board in the
file the layout generation writes beside the netlist. A fact that is none of these and has no class does not reach
the board: state it on the parts that carry it."

"Net classes and interfaces" becomes:

```markdown
- Use the stdlib interfaces (`Spi`, `I2c`, `Can`, `Usb2`, ...) for every bus, bound to a module-level name or passed
  to a module's `io()`: that binding is how the layout finds the bus. An instance built inside a list or a function
  and never bound is not exported.
- A differential pair is a `DiffPair` instance. Its width, gap and impedance stay in a net class whose patterns
  match its two nets.
- A net that needs more clearance than its class for electrical reasons states it on the net:
  `clearance=Length(...)`. A clearance that must differ at one place (a fine-pitch pin on a wide-clearance net) is a
  rule the layout declares.
- Net classes hold width, clearance and impedance only; a class per bus is not needed.
```

Step 3 of the completion list: "Bind every bus and pair to an interface instance; give a high-voltage or switch net
its `clearance`." Note in the rules that `clearance=` needs the stdlib that has the field.

- [ ] **Step 3: Version, commit**

```bash
cd /home/ben/work/circuit-capture
sed -i 's/"version": "0.1.6"/"version": "0.1.7"/' .claude-plugin/plugin.json
git add skills/circuit-capture/SKILL.md .claude-plugin/plugin.json
git commit -m "Buses are interface instances, pairs are DiffPair, a net's clearance is on the net; net classes keep width, clearance and impedance" \
  -m "Reverses the rule of a NetClass per bus (charter: ask first). Approved by the user on 2026-10-07, as decided in the placemat 0.100 roadmap's removal ledger."
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 24: Skill gaps from the reference set

The reference boards' NOTES.md record 19 skill gaps under "Skill gaps" (roadmap, "Keeping them current": a gap is
fixed in the skill, not worked round in the script). Two are fixed already: `overhang=` (07e13341) and a firm
courtyard over a hole following the board's severity (04d3a2aa). Five are recorded on both boards. That leaves 12
gaps. Each goes to the skill it belongs to: placemat's (this repo) or circuit-capture's (its own repo and charter; a
Zener capture convention goes there). A gap that needs a new form or a code change is filed in placemat's BACKLOG.md,
not built here; a released form doing the wrong thing is a bug fix with a failing test first. No skill text names a
project, board, part or net of a project (placemat charter, "A project-agnostic tool"; circuit-capture charter,
principles 1 and 2: it also names no layout tool).

| Gap | NOTES.md | Goes to |
|---|---|---|
| A. An imported sheet becomes a rigid cell | pic_programmer 2, usb-c-power-adapter 2 | placemat capture.md "Cells for placement" and SKILL.md; circuit-capture "Modules for placement"; BACKLOG (a finding) |
| B. `Pm.I` matches a net's whole name only | pic_programmer 3 | bug fix in `checks.carriers_of`; capture.md |
| C. An imported class carries pair figures | pic_programmer 4, usb-c-power-adapter 3 | placemat capture.md "Net classes"; circuit-capture "Net classes and interfaces" |
| D. No form for swapping a multi-gate part's gates | pic_programmer 5 | BACKLOG (a new form) |
| E. An imported capture has no part numbers | pic_programmer 6, usb-c-power-adapter 4 | placemat api.md (`# placemat generate:` takes any `pcb layout` argument); circuit-capture "Writing the capture" |
| F. `Pm.I` at full load when no load is documented | pic_programmer 7 | placemat capture.md |
| G. The hot loop is described for a buck only | pic_programmer 8 | placemat capture.md |
| H. Furniture on a board with no enclosure | pic_programmer 9, usb-c-power-adapter 8 | placemat SKILL.md |
| I. Facts read from the board's own files still need the user | pic_programmer 10, usb-c-power-adapter 9 | BACKLOG (the user's call) |
| J. A current that pours carry, not tracks | usb-c-power-adapter 5 | circuit-capture "Net classes and interfaces"; placemat capture.md |
| K. Marking only the switch and the inductor misses a switch node | usb-c-power-adapter 6 | placemat capture.md |
| L. Which end of a run `along=` counts from | usb-c-power-adapter 7 | placemat api.md |

B is a bug, not a doc gap: capture.md says annotations name nets as the capture does, and `Pm.KeepOut`, `Pm.PinAllow`
and `Pm.PinDeny` match the last part of a net's path (`checks._net_named`, checks.py:478-484), but `carriers_of`
(checks.py:1682-1694) looks a per-net `Pm.I` up by the whole name, so a module's `Pm.I` is dropped without a word in a
board that stamps the module, and `current-path` does not judge it.

**Files:**
- Modify: `$WT/src/placemat/checks.py:1682-1694` (`carriers_of`)
- Modify: `$WT/tests/test_checks.py` (one test)
- Docs (placemat): `$WT/skills/placemat/SKILL.md`, `$WT/skills/placemat/references/capture.md`,
  `$WT/skills/placemat/references/api.md`, `$WT/skills/placemat/references/migration.md` ("## Unreleased", "### Fixed")
- Modify: `$WT/BACKLOG.md` ("## Open": three entries)
- Modify: `$WT/fixtures/reference/boards/pic_programmer/NOTES.md`, `$WT/fixtures/reference/boards/usb-c-power-adapter/NOTES.md`
  ("Skill gaps": where each went)
- Modify (circuit-capture): `/home/ben/work/circuit-capture/skills/circuit-capture/SKILL.md`,
  `/home/ben/work/circuit-capture/.claude-plugin/plugin.json` (0.1.7 -> 0.1.8)

**Interfaces:**
- Consumes: Task 23's circuit-capture "Net classes and interfaces" list; Task 13's api.md "Routing phases".
- Produces: `checks.carriers_of(geometry) -> {net: {ref: amps}}` unchanged in shape; a per-net `Pm.I` entry now
  names a net as `_net_named` does.

- [ ] **Step 1: Write the failing test for B**

Append to `tests/test_checks.py`:

```python
def test_a_per_net_current_names_its_net_by_the_last_part_of_the_path():
    """`Pm.I` names nets as `Pm.KeepOut` does (`_net_named`): a module's annotation reads in a parent that stamps it."""
    from placemat.checks import carriers_of
    u = footprint("U1", 2, 2, nets=("/sheet/VCC", "GND"), fields={"Pm.I": "vcc:0.5A"})
    c = footprint("C1", 6, 2, nets=("CELL.VCC", "GND"), fields={"Pm.I": "VCC:0.5A"})
    w = footprint("W1", 10, 2, nets=("XVCC", "GND"), fields={"Pm.I": "vcc:0.5A"})
    assert carriers_of(board_geometry([u, c, w])) == {"/sheet/VCC": {"U1": 0.5}, "CELL.VCC": {"C1": 0.5}}
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_checks.py::test_a_per_net_current_names_its_net_by_the_last_part_of_the_path -p no:cacheprovider`
Expected: FAIL, `carriers_of` returns `{}`.

- [ ] **Step 3: Fix `carriers_of`**

In checks.py `carriers_of`, the line `amps = fact.current_a if fact.currents is None else fact.currents.get(p.net.lower())`
becomes:

```python
            if fact.currents is None:
                amps = fact.current_a
            else:                                   # named as Pm.KeepOut names a net: the whole name or its last part
                amps = next((a for name, a in fact.currents.items() if _net_named(name, p.net)), None)
```

Run step 2's command and `PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_checks.py tests/test_current_path*.py -n 2 -p no:cacheprovider`.
Expected: PASS.

- [ ] **Step 4: placemat's skill**

capture.md, the annotations table:
- the `Pm.Loop` row's values become: "a loop's name: the parts that share one form one loop; `hot` by convention for
  the fast-current loop, which the converter's topology decides (a buck's input caps and switch; a boost's switch,
  output diode and output caps): take it from the datasheet's layout section" (G);
- the `Pm.I` row's values become: "amps at full load per net the part's pads carry: `vin:3A sw:3A`; a bare `3A` means
  every pad. A net is named as for `Pm.KeepOut`: the last part of its path matches" (B).

capture.md, after the paragraph that starts "Name the net `Pm.Sensitive` protects", a new paragraph (F):

```markdown
Where no document gives the full load, give the bound the circuit guarantees instead (a converter's switch current
limit, a fuse's or a connector's rating), and say in the comment beside it that the figure is a bound, not a load.
```

capture.md, "How the checks find their nets": the switch-node item becomes (K):

```markdown
- A switch node is a net on two or more parts whose every pad belongs to a
  `Pm.Aggressor` part: mark every part with a pad on the node - the switch
  and the inductor, and a bootstrap capacitor, a snubber or a ripple-injection
  part on it as well. One unmarked part on the node hides it.
```

and after "A net-level fact with no part to carry it does not reach the board: state a current on the parts that
carry it (`Pm.I`)." add (J):

```markdown
A current that pours or planes carry, rather than tracks, is stated the same way and needs no class width: the route
carries it by a phase with `width = "current"` or `current_paths = true`, or the script declares the pour
(`references/api.md`, "Routing phases").
```

capture.md, "Net classes", after "Default never makes pairs." add (C):

```markdown
A class brought in from another tool's project may carry pair figures on every class (KiCad stores them on each):
take `diff_pair_width` and `diff_pair_gap` off a class whose nets are not a pair, or placemat pairs its nets.
```

capture.md, "Annotating a capture", step 1: "the switch and its input caps (`Pm.Loop`), the switch and the inductor
(`Pm.Aggressor`)" becomes "the hot loop's parts as the datasheet's layout section names them for its topology
(`Pm.Loop`), every part with a pad on the switch node (`Pm.Aggressor`)" (G, K).

capture.md, "Cells for placement", after its first paragraph (A):

```markdown
A sheet the capture imported from another tool (`pcb import`) is a module like any other: `pcb layout` stamps it as a
group and placemat places it as one rigid cell, in the arrangement the generator gave it unless the module has a
layout script of its own. `placemat parts` lists it as `cell <name>`. Flatten such a sheet into its parent in the
capture when its parts must sit apart.
```

SKILL.md (H, A; the furniture wording confirmed by the user on 2026-10-07): "Furniture (test points, LEDs, buttons) is `OnEdge(edge)` alone and slides to the room left; `along=`
is a mechanical fact, never spacing." becomes "Furniture (test points, LEDs, buttons) is `OnEdge(edge)` alone where an
enclosure gives it an edge (a window, a cut-out), and slides to the room left; on a board with no enclosure, leave it
searched. `along=` is a mechanical fact, never spacing." The bullet "Cells are rigid on the board: ..." gains a last
sentence: "A sheet imported into the capture is a cell too (capture.md, \"Cells for placement\")."

api.md (E), "**Modules.**": after "the script's first line `# placemat generate: --config key=value` tells the
generator which." add "The line passes any `pcb layout` arguments: `# placemat generate: -S bom.unspecified` lets a
capture whose parts have no part numbers yet generate."

api.md (L), "**A run**": after "On a run, `along` is length from the run's start: a number in mm,
`Along.START/MID/END`, `Fraction(f)` of it, or a reference, which lands at the nearest place on the run." add "The start
is the end the board's path reaches first, walked in the order the outline was declared (for an outline read from a
board, the order its edges chain); `run.at(0)[0]` is that point." (outline.py:243-300: `Outline.runs` walks the
loop in path order and a run's points keep that order.)

migration.md "## Unreleased", under "### Fixed":

```markdown
- **`Pm.I` names a net by the last part of its path.** A per-net current (`Pm.I: vcc:0.5A`) matched only a net whose
  whole name was `VCC`, so on a board that stamps the module, where the net is `/sheet/VCC` or `CELL.VCC`, the part
  carried no current and `current-path` did not judge it. It now matches as `Pm.KeepOut`, `Pm.PinAllow` and
  `Pm.PinDeny` do. Captures need no change.
```

- [ ] **Step 5: BACKLOG.md**

Under "## Open", at the top (newest source first):

```markdown
- **Swapping the gates of a multi-gate part** (the reference set's skill gaps, 2026-10-07): a logic part's
  interchangeable gates (each a set of pins, such as A, Y and /OE) cannot be swapped by the pin map study.
  `Pm.PinPool` moves single nets, and a hard `Pm.PinGroup` moves a block to any run of consecutive pins in pool
  order; nothing restricts a block to the other gates' pin sets. A new form: not before 1.0 (consolidation phase).

- **Facts read from a board's own files still need the user** (the reference set's skill gaps, 2026-10-07):
  `placemat facts --confirm` asks the user to confirm layer roles, weights and fab minimums. Where every fact is
  read from the board's project files, the `facts` finding stays on every run and nothing lets a script's author
  confirm them. Whether such a fact needs the user's confirmation is the user's call.

- **A cell with no layout of its own is placed as generated, and nothing says so** (the reference set's skill gaps,
  2026-10-07): a sheet imported into the capture becomes a module, which placemat places as a rigid cell in the
  generator's arrangement; it shows only as `cell <name>` in `placemat parts`. A finding naming such a cell would
  tell the agent before it reads the placement.
```

- [ ] **Step 6: circuit-capture's skill**

Run `sed -n 1,60p /home/ben/work/circuit-capture/CHARTER.md`. These are rules sharpened within its principles
("decide alone": wording and sharpening; the patch bump), and none names a tool or a project. If one would reverse a
rule Task 23 left in place, stop and ask.

`skills/circuit-capture/SKILL.md`:
- "Net classes and interfaces" (as Task 23 left it) gains two bullets (C, J):

```markdown
- A class imported from another tool may carry pair figures (`diff_pair_width`, `diff_pair_gap`) on every class;
  keep them only on a class whose nets are a pair.
- The current a net carries is a fact of the parts that carry it ("Where a fact lives"). Give the net a class with a
  track width only where tracks will carry that current; a net that pours or planes carry needs no width class.
```

- "Modules for placement", after its first paragraph (A):

```markdown
A sheet imported from another tool (`pcb import`) becomes a module, and a module is laid out as one piece. Test
each imported sheet as a module (below), and flatten it into its parent when its parts must sit in different places.
```

- "Writing the capture", step 5 (E): after "`pcb build -D warnings` must pass." add "A capture imported without part
  numbers fails it on `bom.unspecified`: choose each part, with its component-choice record, before the capture is
  complete. Until then that one warning may be suppressed (`-S bom.unspecified`) where the suppression is stated with
  its reason."

```bash
cd /home/ben/work/circuit-capture
sed -i 's/"version": "0.1.7"/"version": "0.1.8"/' .claude-plugin/plugin.json
git add skills/circuit-capture/SKILL.md .claude-plugin/plugin.json
git commit -m "Imported captures: a sheet is a module, pair figures stay only on a pair's class, parts without numbers; a current that pours carry needs no width class"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
git log -1 --format=%h
```

- [ ] **Step 7: NOTES.md, where each gap went**

Append to each gap in "Skill gaps" one line, `Went to: ...`, naming the skill, file and section (and the BACKLOG
entry by its title); "circuit-capture <short hash>" is the hash step 6 printed; "this step's placemat commit" is
written as "placemat (step 1, skill gaps)". For the two already fixed: "Went to: placemat 07e13341 (`overhang=`)."
and "Went to: placemat 04d3a2aa (courtyard over a hole follows the board's severity)." For a gap recorded on both
boards, both get the same line. For example, pic_programmer 4:

```markdown
   Went to: placemat capture.md "Net classes" (placemat, step 1, skill gaps); circuit-capture SKILL.md "Net classes
   and interfaces" (circuit-capture <short hash>).
```

- [ ] **Step 8: Check and commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
grep -rniE "pic_programmer|usb-c-power-adapter|lt1373|74hc125|vcc_pic" skills/ /home/ben/work/circuit-capture/skills/   # expect nothing
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -n 2 -p no:cacheprovider
git add src/placemat/checks.py tests/test_checks.py skills BACKLOG.md fixtures/reference/boards/pic_programmer/NOTES.md fixtures/reference/boards/usb-c-power-adapter/NOTES.md
git commit -m "Skill gaps from the reference set: imported sheets and classes, Pm.I by a net's last part, hot loops and switch nodes by topology, furniture with no enclosure, a run's start"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

Expected: the grep prints nothing, the suite passes, the commit check prints nothing.

---

## Task 25: Remove

The removal-ledger rows step 1 owns (roadmap, "Removal ledger"):

| Row | Removed here |
|---|---|
| Fixed route stages (pairs, islands, classes, main) and their names | `route_islands`, `route_class_stages`, `islands_on_board`, `island_layers_on_board`, `resolve_pair_layers`, `pair_layer_groups`, `Pairs.to_dict`/`from_dict` if unused, the `RouteReport` fields `pairs`, `islands`, `islands_missing`, `island_layers`, `class_stages`, `pair_layers`, `pair_layers_refused` and their summary segments, `route_widths`' stage names, the stage words in docs, studio and `--no-resume` help |
| `[route] islands`, `[route] pair_layers`, `route --islands` | the settings fields, `_island_entry`, `parse_islands`, `parse_island_layers`, the `route.pair_layers` sub-table, their `_validate` branches, `FindingCause.SETUP_PAIR_LAYERS`, the `--islands` option |
| `[route] net_halos` | the field, the `route.net_halos` sub-table, its `_validate` branch, `route_pairs`' `halos` name (now `clearances`) |
| Pairs derived from net-class patterns (`pairs.board_pair_list` for selection) | `board_pair_list` (route selection only; `board_pairs` stays for placement scoring, D19) |
| circuit-capture skill: a `NetClass` per bus, pairs by `*_P`/`*_N` class patterns, net facts only through classes | done in Task 23; checked here |

**Files:**
- Modify: `$WT/src/placemat/kicad/route.py`, `$WT/src/placemat/settings.py`, `$WT/src/placemat/cli.py`,
  `$WT/src/placemat/pairs.py:197-211`, `$WT/src/placemat/kicad/route_widths.py`, `$WT/src/placemat/findings.py`,
  `$WT/src/placemat/finding_text.py`, `$WT/src/placemat/studio_page.html`, `$WT/src/placemat/channel.py`
- Delete tests of removed code: the parsing tests in `tests/test_route_islands.py` (the file goes if nothing is left),
  `tests/test_pair_layers.py`, the `board_pair_list` test in `tests/test_pairs.py`/`tests/test_pair_classes_read.py`
  if any
- Modify: `tests/surface/cli.txt`, `tests/surface/settings.txt`, `tests/surface/removed.txt`, `tools/release/vulture_allow.py`
- Create: `$WT/tests/test_removed_route_forms.py`
- Docs: `skills/placemat/SKILL.md`, `skills/placemat/references/api.md`, `skills/placemat/references/capture.md`,
  `skills/placemat/references/migration.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a `placemat.toml` with `[route] islands`, `pair_layers` (either form) or `net_halos` (either form) fails
  to load, naming what replaces it (`settings._REPLACED`); `placemat route ... --islands ...` exits 2 naming the
  phase form; nothing else names them outside migration.md.

- [ ] **Step 1: Write the failing test**

`tests/test_removed_route_forms.py`:

```python
"""The forms routing phases replaced are refused, each naming what replaces it."""
import pytest

from placemat.settings import SettingsError, load


@pytest.mark.parametrize("text, names", [
    ('[route]\nislands = ["VB=0.5"]\n', "a phase with `nets` and `width`"),
    ('[route]\npair_layers = {"A/B" = ["F.Cu"]}\n', "a phase with `pairs = true` and `layers`"),
    ('[route.pair_layers]\n"A/B" = ["F.Cu"]\n', "a phase with `pairs = true` and `layers`"),
    ('[route]\nnet_halos = {"SW" = 2.0}\n', "the clearance field of the net's type in the capture"),
    ('[route.net_halos]\nSW = 2.0\n', "the clearance field of the net's type in the capture"),
])
def test_a_removed_route_setting_is_refused_naming_its_replacement(tmp_path, text, names):
    (tmp_path / "placemat.toml").write_text(text)
    with pytest.raises(SettingsError, match="is retired; set " + __import__("re").escape(names)):
        load(tmp_path)


def test_route_islands_is_refused_naming_the_phase_form(capsys):
    from placemat.cli import main
    assert main(["route", "b.kicad_pcb", "--islands", "VB"]) == 2
    assert "[[route.phase]]" in capsys.readouterr().out


def test_no_stage_code_is_left():
    import placemat.kicad.route as r
    import placemat.pairs as p
    for name in ("route_islands", "route_class_stages", "islands_on_board", "island_layers_on_board",
                 "resolve_pair_layers", "pair_layer_groups"):
        assert not hasattr(r, name), name
    assert not hasattr(p, "board_pair_list")
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest tests/test_removed_route_forms.py -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Remove**

- settings.py: delete `route_islands`, `route_pair_layers`, `route_net_halos` and their branches in `_validate`;
  `_SUBTABLES` loses `route.pair_layers` and `route.net_halos`; `_REPLACED` gains
  `"route_islands": "a phase with \`nets\` and \`width\` ([[route.phase]], api.md \"Routing phases\")"`,
  `"route_pair_layers": "a phase with \`pairs = true\` and \`layers\` ..."`,
  `"route_net_halos": "the clearance field of the net's type in the capture ..."`; in `_flatten`'s dict branch test
  `join_key(full, "")` against `_REPLACED` before the sub-table test, so the table form is refused the same way.
  The `router_args` refusal text (:844) drops "islands, net_halos".
- route.py: delete the functions in the ledger table; `_route_board`'s legacy check goes (the settings refuse them
  now); `RouteReport` loses the fields named above and their `summary`/`as_dict` lines; `route_pairs(..., clearances=None)`
  replaces `halos`; delete `parse_islands` import (:749).
- cli.py: delete `--islands` from the route parser; in `main`, before parsing, a removed option is refused:

```python
_REMOVED_OPTIONS = {("route", "--islands"): "a routing phase with `nets` and `width` in placemat.toml "
                                            "([[route.phase]], api.md \"Routing phases\")"}


def _removed_option(argv) -> str | None:
    if not argv:
        return None
    for (command, option), instead in _REMOVED_OPTIONS.items():
        if argv[0] == command and any(a == option or a.startswith(option + "=") for a in argv[1:]):
            return "%s %s is retired; use %s" % (command, option, instead)
    return None
```

  `main` says it at level fail and returns 2.
- pairs.py: delete `board_pair_list`; the module docstring no longer says the route step routes class pairs.
- findings.py / finding_text.py: delete `SETUP_PAIR_LAYERS`; route_widths.py: no stage names in docstrings.
- studio_page.html, channel.py: no "islands"/"classes"/"main" stage words.
- tests/surface: `cli.txt` loses `route --islands`; `settings.txt` loses the three; `removed.txt` gains:

```text
--islands
[route] islands
route.islands
[route] pair_layers
route.pair_layers
pair_layers =
[route] net_halos
route.net_halos
net_halos =
setup.net_halo
setup.pair_layers
class stage
board_pair_list
```

- [ ] **Step 4: Check every row against the code**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
grep -rnE "route_islands|parse_islands|island_layers|pair_layers|net_halos|net_halo\b|class_stages|route_class_stages|board_pair_list|SETUP_PAIR_LAYERS|STAGES = " src tests skills fixtures tools --include=*.py --include=*.md --include=*.toml --include=*.json --include=*.html | grep -v "references/migration.md"
grep -rn "NetClass per bus\|_P./.*_N.*class\|net-level fact with no class" /home/ben/work/circuit-capture/skills
PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m vulture src/placemat tools/release/vulture_allow.py --min-confidence 80
```

Expected: the greps print nothing (any line is a leftover to remove, or a different meaning to read and justify in
the commit message); vulture prints nothing (fix what the removal left unused).

- [ ] **Step 5: Docs**

api.md, SKILL.md and capture.md name none of the removed forms (`tests/test_docs_removed.py`). migration.md
"## Unreleased":

```markdown
### Removed

- **`[route] islands` and `route --islands`.** An island is a routing phase:

      # before                                  # after
      [route]                                   [[route.phase]]
      islands = ["VB=0.5@F,B", "GND"]           name = "vb"
                                                nets = ["VB"]
                                                width = 0.5
                                                layers = ["F", "B"]

                                                [[route.phase]]
                                                name = "gnd"
                                                nets = ["GND"]

  A net its pour serves is routed alone with the pour handed to the router, as an island was.
- **`[route] pair_layers`.** A phase with `pairs = true` and `layers`; the pairs are the capture's `DiffPair`
  instances (regenerate the board with the Zener fork; a capture binds each pair as a `DiffPair`).
- **`[route] net_halos`.** The net's own `clearance` field in the capture: `Power("SW", clearance=Length("2mm"))`.
  The finding `setup.net_halo` is `setup.net_clearance`.
- **Differential pairs from net classes.** Routing takes pairs only from the capture's `DiffPair` instances; a net
  class still gives a pair's width, gap and impedance.
- **The fixed stages and their names** (`pairs`, `islands`, `classes`, `main`): `route.json` has `phases` in their
  place; the old keys `pairs`, `islands`, `islands_missing`, `island_layers`, `class_stages`, `pair_layers`,
  `pair_layers_refused`, `net_halos*` are gone.
```

- [ ] **Step 6: Run the suite**

Run: `cd /home/ben/work/placemat/.claude/worktrees/routing-phases && PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python -m pytest -n 2 -p no:cacheprovider`
Expected: PASS, including the surface, docs and unused-code tests.

- [ ] **Step 7: Commit**

```bash
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
git add -A src tests skills tools fixtures
git commit -m "Remove the fixed route stages, [route] islands, pair_layers and net_halos, route --islands, and class-pattern pairs for routing"
git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 26: Gate, merge and release 0.100.0

**Files:**
- Modify: `$WT/fixtures/reference/results.json` (by the runners' `--update`), `$WT/skills/placemat/references/migration.md`
  ("## Unreleased" -> "## To 0.100.0"), `$WT/.claude-plugin/plugin.json`, `$WT/.claude-plugin/marketplace.json`,
  `$WT/tests/slow_tests.txt`, `$WT/fixtures/bench.json` (if the bench moves)

**Interfaces:**
- Consumes: every task above; the KRT branch `placemat/connections`; the Zener branch `feat/nets-layout-json`.
- Produces: main at the merge of `step1-routing-phases`; tag v0.100.0; the live router and pcb on the fork commits.

### Gates

Baseline (results.json, placemat a3e7b36e, krt c98d38eb, pcbc 0.4.52), test (a) clean closure at class widths:
chainlinkDriver 1.0 (0 new DRC), usb-c-power-adapter 1.0 (0), pic_programmer 1.0 (2 track_width), lora-v3 1.0
(3 solder_mask_bridge), esp-rust-board 1.0 (1 starved_thermal), ir-irradiance-probe 0.8861 (2 clearance),
spimux 0.8649 (5 open), watchy 0.8582 (15 open). Test (b): pic_programmer 1.0, usb-c-power-adapter 0.952; modules
17/18 at 1.0. The step merges only if no board or module is worse. Expected to improve: ir-irradiance-probe's
clearance errors (D6 clearance floor) and pic_programmer's track_width errors (D6 neck floor; and D18, its POWER
class no longer routed as a pair).

- [ ] **Step 1: Run the gate on the branch**

```bash
df -h ~ | tail -1
cd /home/ben/work/placemat/.claude/worktrees/routing-phases
L=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock
flock $L env PATH=/home/ben/work/pcb-phases/bin:$PATH KRT_DIR=/home/ben/work/KRT-phases PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/reference/route_ref.py --changing placemat krt pcb | tee /tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/gate_a.txt
flock $L env PATH=/home/ben/work/pcb-phases/bin:$PATH KRT_DIR=/home/ben/work/KRT-phases PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/reference/place_ref.py --changing placemat krt pcb | tee /tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/gate_b.txt
flock $L env PATH=/home/ben/work/pcb-phases/bin:$PATH KRT_DIR=/home/ben/work/KRT-phases PYTHONPATH=$PWD/src /home/ben/work/placemat/.venv/bin/python fixtures/reference/place_ref.py --modules --changing placemat krt pcb | tee /tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/gate_m.txt
grep -c " worse" /tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/gate_*.txt
```

Run them one after the other (each takes the lock itself; `flock` here serialises against other sessions). A run
that stops keeps the boards it finished (`--update` is not passed yet; rerun only the boards missing).

- [ ] **Step 2: Decide**

If any line is `worse` (or `not comparable` with a worse value), stop: give the user each worse board's old and new
numbers and what changed, and wait. Never pass `--accept-worse` without the user's approval. Otherwise write down
what improved, board by board, for the merge and release commits.

- [ ] **Step 3: The real-board check (D28)**

Copy the board lead's current core board and script folder to a scratch directory (read only; nothing is written in
the project). Route it twice under the lock with `KRT_DIR=$KW` and the worktree's placemat: once as its script stands
(declared power-leg copper), once with the declared legs removed in the scratch copy and a
`{"name": "power-legs", "current_paths": true, "width": "current"}` phase first. Compare closure, the phase's closure
and `placemat check current-path` on each routed board. Give the user the numbers; they go in no commit (they name a
project).

- [ ] **Step 4: Merge into main**

```bash
cd /home/ben/work/placemat && git pull --ff-only
git merge --no-ff step1-routing-phases -m "Merge step 1: routing phases"
```

Resolve `skills/placemat/references/migration.md` with `tools/release/merge_unreleased.py` (both sides'
"## Unreleased"); then for every released section since the branch was cut, diff it against its tag
(`diff <(git show v0.99.N:skills/placemat/references/migration.md | sed -n '/^## To 0.99.N/,$p') <(sed -n '/^## To 0.99.N/,$p' skills/placemat/references/migration.md)`)
and restore any that moved with `tools/release/fix_migration.py v0.99.N ...`. Check "## Unreleased" is above the
newest released section. Commit the merge; run the commit-message check.

- [ ] **Step 5: Move the live router and pcb (D21)**

```bash
git -C /home/ben/work/KRT-upstream status --short          # nothing but .venv
git -C /home/ben/work/KRT-upstream merge --ff-only placemat/connections
git -C /home/ben/work/KRT-upstream push fork placemat/upstream-2026-10
git -C /home/ben/work/pcb status --short
git -C /home/ben/work/pcb merge --ff-only feat/nets-layout-json
df -h ~ | tail -1
cd /home/ben/work/pcb && cargo build -j 2 --release -p pcbc
git -C /home/ben/work/pcb push origin feat/netclass-nets-field-0.4.52
pcb --version && ls /home/ben/work/placemat/fixtures/reference/boards/pic_programmer
```

If `git status` shows another session's changes in either checkout, stop and ask. KRT's `rust_router` is unchanged by
this step; if `git diff c98d38eb -- rust_router` is not empty, rebuild `grid_router.so` there with
`python3 build_router.py`.

- [ ] **Step 6: The release suite, the runners with --update, the bench**

```bash
cd /home/ben/work/placemat
.venv/bin/python -m pytest --full -n 2 -p no:cacheprovider --junitxml=/tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/full.xml
.venv/bin/python tests/update_slow_tests.py /tmp/claude-1000/-home-ben-work-placemat/2bd7aed4-b7ad-44b9-b938-13be6bbfe8c8/scratchpad/full.xml
L=/tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock
flock $L .venv/bin/python fixtures/reference/route_ref.py --changing placemat krt pcb --update
flock $L .venv/bin/python fixtures/reference/place_ref.py --changing placemat krt pcb --update
flock $L .venv/bin/python fixtures/reference/place_ref.py --modules --changing placemat krt pcb --update
.venv/bin/python -m vulture src/placemat tools/release/vulture_allow.py --min-confidence 80
RUSTFLAGS="-D dead_code" cargo build --manifest-path native/Cargo.toml
```

Expected: the suite passes; the runners' lines match the gate's (a line now worse than the gate's is a stop, as in
step 2); vulture and the native build report nothing.

- [ ] **Step 7: Release**

- migration.md: "## Unreleased" becomes "## To 0.100.0", with the "Changed", "New", "Fixed" and "Removed" entries of Tasks 13-25
  and a "New" list of what an upgrading agent can use (phases, `current_paths` for power legs in place of declared
  copper, `--phase`, `--only`, `--route-rank`, capture-selected pairs, interfaces and net types, the `clearance` field),
  and the coordinate-to-intent example: a declared power-leg `board.track(...)` with points beside the phase that
  replaces it.
- plugin.json and marketplace.json version 0.100.0.
- The release commit message carries the reference tallies (each board's and module's line from step 6) and the
  improvements from step 2; tag `v0.100.0`, push main and the tag, `gh release create v0.100.0` with the migration
  section as notes; update the plugin as the release procedure does.
- The board sessions' gaps file (fairing-instrument/electronics/PLACEMAT_GAPS.md): remove each entry this release
  resolves, committed by explicit path only.

- [ ] **Step 8: Notify and bench**

Send fairing-instrument-pcb and fairing-instrument-electronics a notice: placemat 0.100.0; reload the placemat skill
and the circuit-capture skill (0.1.8); update only the env your session owns; a route now needs `[[route.phase]]`
(start from `placemat settings <board> --example`); `[route] islands`/`pair_layers`/`net_halos` are refused, with
what replaces each; regenerate boards with the updated `pcb` so `nets.layout.json` is written (pairs, interfaces and
net clearances come from it); declared power-leg copper can become a `current_paths` phase. Then
`.venv/bin/python fixtures/bench.py --jobs 2`; a timing regression is a point release after, never a hold.

- [ ] **Step 9: Check the commits**

```bash
for r in /home/ben/work/placemat /home/ben/work/KRT-upstream /home/ben/work/pcb /home/ben/work/circuit-capture; do
  git -C $r log -30 --format=%B | grep -iE "claude|anthropic|session|co-authored"; done
```

Expected: nothing printed.
