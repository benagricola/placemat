# Rip and Reroute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan
> task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a router call of a phase leaves a connection open and the router names copper an earlier call laid as
blocking it, placemat removes that copper, reroutes the blocked connection, reroutes the removed connections at their
own phases' settings, and keeps the result only when nothing judged before is worse.

**Architecture:** One new module, `src/placemat/kicad/rip_reroute.py`, holds the pure parts (blocker evidence, victim
rules, the removed connections and their owners, the verdict, the record) and the board steps (copper keys, removing
copper, one attempt, the per-call driver). `phase_run.route_calls` calls the driver after every call but a pair call;
`route._route_board` builds the route's history (phases, selections, obligations, width answers, script copper, each
finished phase's board and records) and hands it to the phases through `PhaseContext`. The final re-judgement reads
the reroute records; the width rows and the console lines follow. No router change.

**Tech Stack:** Python 3.12, pcbnew and kicad-cli (KiCad 10), pytest with xdist, the reference runners
(`fixtures/reference/place_ref.py`).

**Spec:** `docs/superpowers/specs/2026-10-12-rip-reroute-design.md`. Also read
`.superpowers/sdd/2026-10-07-routing-phases/rip-reroute-research.md` (the code map), section 6 of
`gate-diagnosis.md` and `usbc-starvation-report.md` in the same folder, the routing-phases spec and plan
(`docs/superpowers/specs/2026-10-06-routing-phases-design.md`, `docs/superpowers/plans/2026-10-07-routing-phases.md`,
its "Decisions" and "Controller rulings"), `CHARTER.md`, `CLAUDE.md` and `~/.claude/CLAUDE.md`. Every file:line below
was read at placemat f8ae55c8 and KRT `placemat/connections` 96e0422f.

## Global Constraints

- Worktree: `/home/ben/work/placemat/.claude/worktrees/rip-reroute`, branch `step1b-rip-reroute`, cut from main
  f8ae55c8 (step 1 merged). Below, `$WT` stands for that path; the shell keeps no variables, so spell it out in each
  command. Copy `src/placemat/_version.py` in from the main checkout first (Task 1): without it the native module is
  not used and routes run about 4x slower.
- The test command, written below as `<TEST>`, is this literal prefix:
  `cd /home/ben/work/placemat/.claude/worktrees/rip-reroute && KRT_DIR=/home/ben/work/KRT-phases MNB_ECOSYSTEM=/home/ben/Documents/Hardware/mnb-ecosystem PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m pytest -p no:cacheprovider -q`
- Tests (the user, 2026-10-12): each task runs only the test files it names, with `--full` so its slow tests run. No
  whole suite, not even the fast one, before Task 17, which runs the full suite once (`<TEST> --full -n 2`).
- Shared machine: pytest `-n 2` at most. Real-board runs one at a time, under a private lock:
  `REALBOARD_LOCK=<your scratchpad>/realboard.lock`, the scratchpad under `/tmp/claude-1000/`; never flock the shared
  lock. Real-board work folders go under that scratchpad on /tmp, never on the home disk. Before a real-board run check
  `df -h /tmp ~`; below 20 GB free on either, stop and ask the user. Never delete files to make room. Kill only PIDs you
  started. Give the 1-minute load average with every timing.
- The router is not changed. KRT is `/home/ben/work/KRT-phases` (`placemat/connections`); record its commit with every
  real-board result. Never write in ~/work/KRT-upstream or another session's KRT worktree.
- `CLAUDE.md`: take board items off with `board.Delete(item)`, after `group.RemoveItem(item)` when grouped, never
  `board.Remove`.
- Charter: structured data inside, text at the edge (records cross functions and go into route.json; sentences are made
  only in `route.phase_lines`); tunables are settings with documented defaults; project-agnostic wording in src, tests,
  skill docs and commit messages (no project, board, part or net of a project; the reference boards may be named in
  this plan, the spec, fixtures and gate tallies). Defer to upstream with file:line, and mark every deliberate
  divergence in a code comment.
- Plain ASCII everywhere: no em or en dashes, no unicode arrows, straight quotes.
- Wording: say "call" and "phase"; a stamped instance on a board is a "cell".
- Commits carry no reference to Claude or Anthropic (no Co-Authored-By, no Claude-Session, no session URL). After every
  commit run `git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"`; it must print nothing. Do not
  push.
- Agents in the worktree commit only their own paths. Tasks that edit `kicad/route.py` or `kicad/phase_run.py` run one
  at a time.
- Release: this ships in 0.100.0 with step 2 (docs/superpowers/plan-0.100-index.md); no release here.

## Decisions

The user's, 2026-10-12 (binding):

- R1 Scope: any later router call may rip copper an earlier call laid, in the same phase or an earlier phase, when
  that copper blocks a connection the later call leaves open.
- R2 Design B: placemat does it, with no router change: (1) a call leaves a connection open and the router names
  earlier-call copper blocking it; (2) placemat removes that blocking copper (its connections: the obligations the
  earlier call joined with it); (3) placemat reroutes the blocked connection; (4) placemat reroutes the removed
  connections as `--connections` tasks, each at its own phase's width, layers and clearance; (5) the result is kept
  only if the blocked connection joins clean and every earlier connection is judged clean again (DRC plus
  judge_obligations, as S6 and recheck_final_phases do); otherwise the board is restored to what it was before the
  attempt.
- R3 Earlier calls keep their priority: their copper is moved, never dropped. Copper the script itself declares,
  which is never router copper, is never ripped.
- R4 Ships in 0.100.0 with step 2.

Controller rulings made while writing the spec (each: the ruling, its reason, its cost if wrong). The user approves or
reverses them with the spec:

- C1 Named nets come from `found_by == "preexisting"` entries and from `found_by == "static"` entries of
  `kind == "track"`, in task records' `evidence.blocked_by`, in the summary's `net_evidence`, and in the summary's
  `blockers` entries with `stage == "preexisting"`. Reason: pic_programmer's blocker is only in `blockers`; a static
  track entry is copper of another net the failed search's frontier met. Cost if wrong: attempts on nets that were
  only near the failed search.
- C2 An attempt's unit is one net's connections that one call left open; every connection of the unit must join
  clean. Reason: the router's evidence is per net (`scope: "net"`). Cost if wrong: a unit with two connections is
  restored when only one could join.
- C3 A victim loses all of its router copper; nets the failing call laid copper on, the blocked net, pour nets, pair
  nets and excluded nets are never victims. Reason: whole-net removal returns the net to its input state, whose open
  connections span it; the excluded kinds cannot be rerouted at their own settings as tasks. Cost if wrong: more
  copper moved than the blocker needed.
- C4 Joins no phase asks (an input-board open connection of a victim joined on the board, with no obligation of that
  pad pair) are rerouted at the settings of the first phase whose board joins them, at that phase's width answer.
  Reason: a rest call joins the leftover pads of a net an earlier `current_paths` phase named, and no obligation
  covers them. Cost if wrong: one `joined_pairs` pass per earlier phase board per attempt that has such joins.
- C5 A pad pair two phases ask is rerouted once, at the earliest asking phase's settings. Reason: R3, earlier keeps
  priority. Cost if wrong: a later phase's wider ask is not met by the reroute.
- C6 The keep test adds three checks to R2 (5): no net's open item count rises, no new real DRC error, and no track
  of the attempt off its owner's layers. An obligation is "worse" when its rank (clean 2, joined 1, open 0) falls.
  Reason: "nothing is lost" covers joins no obligation asks and pour splits; the layer check closes the
  phase_run.py:806-807 gap for this work's copper. Cost if wrong: attempts restored that a looser test would keep.
- C7 Limits: `[route] rip_attempts` (4) per call, 0 off; `[route] rip_max_nets` (3) victims per attempt; a victim set
  restored once is not tried again in the call; a router failure, refusal or timeout in an attempt ends the call's
  attempts. Reason: bounded time per call. Cost if wrong: blocked connections past the fourth left open.
- C8 A `pour` call's blocked unit is rerouted by `join_pour` again on the ripped board; pair calls start no attempt.
  Reason: a pour task belongs to the drops-then-tasks join (D31), and the pair router writes no per-connection
  evidence. Cost if wrong: a pair call blocked by earlier copper stays as today.
- C9 Attempts run straight after the failing call, before the phase's next call. Reason: later calls then route on the
  repaired board. Cost if wrong: none known.
- C10 The blocked unit is rerouted as `--connections` tasks even after a whole-net call. Reason: the attempt routes
  exactly the unit, at the widths phase i asks for it. Cost if wrong: a whole-net call's MST choice of pad pairs is not
  repeated.
- C11 Width rows of moved copper are dropped and the reroute's rows added under the owner phase's name. Reason: the
  `route.width` findings describe the final board. Cost if wrong: none known.
- C12 The studio's route view and the route record's replay are not changed in this plan.
- C13 With `--only`, the given board's copper is script copper; the phase's own earlier calls' copper can still move.
- C14 Prose-only names (the router's sentence about protected nets within 3 mm, KRT routing_diagnostics.py:509-545)
  are never read. If usb-c-power-adapter's blockers are only there, Task 18 reports it to the user.

## Review Focus

- A victim net that has script copper as well as router copper: only the router copper is removed (Task 5, Task 11).
- A victim whose joins belong to two phases, a `current_paths` task and the rest call's leftovers: each rerouted at its
  own owner's settings (Task 7, Task 11).
- A restored attempt: the phase's next call reads the failing call's output file unchanged (Task 11).
- After a kept attempt, the final re-judgement of an earlier phase reads the reroute record (Task 13).
- A reroute that splits a pour net: restored with `net_open_rose` (Task 8, pure).
- A named net with only script copper: not ripped, `no_router_copper` (Task 4, Task 11).
- usb-c-power-adapter: whether any structured field names its blockers (Task 18).

---

## File Structure

- Create `src/placemat/kicad/rip_reroute.py`: everything new.
- Modify `src/placemat/kicad/route.py`: `copper_key` and `copper_items` taken out of `routed_copper` (:1164-1184);
  `_route_board` builds the history (:1368-1470), reads the moved rows into `report.widths` (:1501); 
  `recheck_final_phases` supersedes outcomes with reroute records (:1230-1262); the kept-result digest to
  `phase-judgement-v10` (:1416); `phase_lines` renders `rip` (:1576-1625).
- Modify `src/placemat/kicad/phase_run.py`: `PhaseSettings` and `phase_settings` taken out of `route_calls`
  (:1080-1094); `PhaseContext.history`; `Routed.rip`; `phase_record(..., rip=None)`; the driver called after each call
  in `route_calls` (:1112-1154).
- Modify `src/placemat/settings.py`: `route_rip_attempts`, `route_rip_max_nets`.
- Tests: create `tests/rip_helpers.py` (the rip board and the stand-in router), `tests/test_rip_reroute.py` (pure),
  `tests/test_rip_reroute_board.py` (pcbnew, no router), `tests/test_rip_reroute_route.py` (engine); modify
  `tests/surface/settings.txt`, `tests/test_route_phases.py` (the digest name, if a test names it).
- Docs: `skills/placemat/references/api.md` ("Routing phases" and the generated settings table),
  `skills/placemat/references/migration.md` (Unreleased, New), the routing-phases spec and plan (D32).

---

## Task 1: Preparation and the baseline at a fixed placement

**Files:** none committed.

- [ ] **Step 1: Check the worktree.**

```bash
cd /home/ben/work/placemat/.claude/worktrees/rip-reroute && git status --short && git log -1 --oneline
cp /home/ben/work/placemat/src/placemat/_version.py /home/ben/work/placemat/.claude/worktrees/rip-reroute/src/placemat/_version.py
git -C /home/ben/work/KRT-phases log -1 --oneline
df -h /tmp ~
```

Expected: branch `step1b-rip-reroute`, head the spec and plan commit; `_version.py` stays untracked or unchanged in git
(it is ignored; if git lists it, do not commit it).

- [ ] **Step 2: The baseline runs.** With the code as merged (before any task here), run test (b) for the two boards
under the private lock, one at a time, work under your scratchpad, no `--update`:

```bash
cd /home/ben/work/placemat/.claude/worktrees/rip-reroute && uptime && REALBOARD_LOCK=<scratch>/realboard.lock KRT_DIR=/home/ben/work/KRT-phases PATH=/home/ben/work/pcb-phases/bin:$PATH PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python fixtures/reference/place_ref.py pic_programmer --work <scratch>/rip-base/pic && uptime
cd /home/ben/work/placemat/.claude/worktrees/rip-reroute && uptime && REALBOARD_LOCK=<scratch>/realboard.lock KRT_DIR=/home/ben/work/KRT-phases PATH=/home/ben/work/pcb-phases/bin:$PATH PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python fixtures/reference/place_ref.py usb-c-power-adapter --work <scratch>/rip-base/usbc && uptime
```

Keep each run's printed line (closure_clean, open, new DRC, vias, track, seconds, verdict against results.json) and
locate each run's `route/in.kicad_pcb` (the placed board the route was given) under the work folder: those two boards
are the fixed placements Task 18 routes again. Write the paths, the lines, the load and the KRT commit into the ledger
(`.superpowers/sdd/2026-10-12-rip-reroute/progress.md`, git-ignored, in the main checkout).

- [ ] **Step 3: The fixed-placement route at the base.** Route each fixed placement with the merged code, so Task 18
compares like with like. Copy the run's routed input with what a route reads beside it into a folder of its own:
`route/in.kicad_pcb` as `<scratch>/rip-base/<board>-fixed/layout.kicad_pcb`, with the same run's `.kicad_pro`,
`.kicad_dru`, `placemat.toml` and `nets.layout.json` beside it (as the usb-c investigation did,
usbc-starvation-report.md, "Evidence"). Then, for each board:

```bash
cd /home/ben/work/placemat/.claude/worktrees/rip-reroute && uptime && flock <scratch>/realboard.lock env KRT_DIR=/home/ben/work/KRT-phases PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m placemat route <scratch>/rip-base/<board>-fixed/layout.kicad_pcb --full --no-resume --out <scratch>/rip-base/<board>-fixed/work && uptime
```

Record from each `route.json`: `closure_clean`, `open_after`, each phase's `joined`/`asked` and
`final_closure_clean`, `widths_failed`, `drc_new`, `vias`, `track_mm`, `seconds`; and whether pic_programmer's
signals phase leaves VCC_PIC JP1.2-U6.1 open.

---

## Task 2: Settings `[route] rip_attempts` and `[route] rip_max_nets`

**Files:**
- Modify: `$WT/src/placemat/settings.py` (after `route_adopt_tolerance`, :395)
- Modify: `$WT/tests/surface/settings.txt`, `$WT/skills/placemat/references/api.md` (the generated table)
- Test: `$WT/tests/test_rip_reroute.py` (create)

**Interfaces:** Produces `Settings.route_rip_attempts: int = 4`, `Settings.route_rip_max_nets: int = 3`, read by
Tasks 10-12.

- [ ] **Step 1: Write the failing test** in `tests/test_rip_reroute.py`:

```python
"""Rip and reroute (kicad/rip_reroute.py): the pure parts."""
from placemat.settings import Settings


def test_rip_and_reroute_is_on_by_default_with_its_limits():
    s = Settings()
    assert (s.route_rip_attempts, s.route_rip_max_nets) == (4, 3)


def test_rip_attempts_zero_turns_it_off():
    assert Settings(route_rip_attempts=0).route_rip_attempts == 0
```

- [ ] **Step 2: Run it.** `<TEST> --full tests/test_rip_reroute.py` - expected FAIL (no such field).

- [ ] **Step 3: Add the settings** in `settings.py` after `route_adopt_tolerance`:

```python
    route_rip_attempts: int = S(4, "count",
        "attempts per router call to move an earlier call's copper that blocks a connection the call left open: the "
        "blocking nets' routed copper is taken off, the blocked connection routed, and the moved connections routed "
        "again at their own phase's widths, layers and clearance; kept only when no connection judged before is "
        "worse. 0 is off")
    route_rip_max_nets: int = S(3, "count",
        "the most nets one such attempt moves; a blocked connection whose router names more is not attempted")
```

Add `route.rip_attempts` and `route.rip_max_nets` to `tests/surface/settings.txt` in sorted place. Regenerate the
api.md settings table: `cd $WT && PYTHONPATH=src /home/ben/work/placemat/.venv/bin/python -m placemat settings --markdown`
and paste it between `<!-- settings-table:begin -->` and `<!-- settings-table:end -->`. If a settings validation set
lists count settings that must be non-negative, add both there (check `settings.py` for the set
`test_every_name_in_a_validation_set_is_a_real_setting` reads).

- [ ] **Step 4: Run.** `<TEST> --full tests/test_rip_reroute.py tests/test_settings_surface.py tests/test_settings_docs.py`
  - expected PASS.

- [ ] **Step 5: Commit.**

```bash
cd /home/ben/work/placemat/.claude/worktrees/rip-reroute && git add src/placemat/settings.py tests/surface/settings.txt skills/placemat/references/api.md tests/test_rip_reroute.py && git commit -m "Settings: [route] rip_attempts and rip_max_nets" && git log -1 --format=%B | grep -iE "claude|anthropic|session|co-authored"
```

---

## Task 3: Blocker evidence

**Files:**
- Create: `$WT/src/placemat/kicad/rip_reroute.py`
- Test: `$WT/tests/test_rip_reroute.py`

**Interfaces:** Produces

```python
TASK_CALLS = ("tasks", "bus_tasks", "pour")
NET_CALLS = ("nets", "rest", "bus")

@dataclass(frozen=True)
class Named:
    net: str
    found_by: str                  # "preexisting" | "static"
    def record(self) -> dict: ...  # {"net", "found_by"}

@dataclass(frozen=True)
class Blocked:
    net: str
    named: tuple                   # Named, router order, each net once
    connections: tuple = ()        # a task call's failed tasks {"net", "from", "to", "widths"}; () for a whole-net call

def blocked_of(kind: str, records=(), summary: dict | None = None) -> list   # [Blocked]
```

Consumed by Task 10.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_rip_reroute.py`):

```python
from placemat.kicad import rip_reroute as rr


def _ev(*blocked):
    return {"scope": "net", "search": None, "verdicts": [], "narrow": [], "diagnosis": "unknown",
            "blocked_by": list(blocked)}


def _pre(net):
    return {"found_by": "preexisting", "kind": "copper", "net": net}


def _rec(net, status, *blocked, a=("U1", "1"), b=("J1", "2")):
    return {"net": net, "from": {"ref": a[0], "pad": a[1]}, "to": {"ref": b[0], "pad": b[1]},
            "widths": {"F.Cu": 0.2}, "status": status, "evidence": _ev(*blocked) if blocked else None}


def test_a_task_call_blocks_each_net_with_a_failed_task_whose_router_names_other_copper():
    recs = [_rec("N", "failed", _pre("V"), {"found_by": "static", "kind": "track", "net": "W"},
                 {"found_by": "static", "kind": "pad", "net": "X", "ref": "U9"},
                 {"found_by": "frontier", "kind": "routed_copper", "net": "Y"}),
            _rec("N", "failed", _pre("V"), a=("U1", "3")),
            _rec("M", "routed"),
            _rec("K", "failed")]                      # no evidence: nothing named
    got = rr.blocked_of("tasks", recs)
    assert [(u.net, [n.record() for n in u.named], len(u.connections)) for u in got] == [
        ("N", [{"net": "V", "found_by": "preexisting"}, {"net": "W", "found_by": "static"}], 2)]
    assert got[0].connections[0] == {"net": "N", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "2"},
                                     "widths": {"F.Cu": 0.2}}


def test_a_whole_net_call_reads_net_evidence_and_the_preexisting_blockers():
    summary = {"net_evidence": {"N": _ev(), "M": _ev(_pre("W"))},
               "blockers": [{"net": "N", "stage": "preexisting", "blocked_by": [{"net": "V", "preexisting": True}]},
                            {"net": "M", "stage": "phase3", "blocked_by": [{"net": "Z"}]}]}
    got = rr.blocked_of("rest", summary=summary)
    assert [(u.net, [n.net for n in u.named], u.connections) for u in got] == [("N", ["V"], ()), ("M", ["W"], ())]


def test_a_pair_call_blocks_nothing():
    assert rr.blocked_of("pairs", [_rec("N", "failed", _pre("V"))], {"blockers": []}) == []
```

- [ ] **Step 2: Run.** `<TEST> --full tests/test_rip_reroute.py` - expected FAIL (no module).

- [ ] **Step 3: Implement** `rip_reroute.py`:

```python
"""Rip and reroute of earlier calls' copper (docs/superpowers/specs/2026-10-12-rip-reroute-design.md). After a router
call of a phase leaves a connection open and the router names another net's copper an earlier call laid as blocking
it, that net's router copper is taken off, the blocked connection routed, and the removed connections routed again at
their own phases' widths, layers and clearance; the result is kept only when nothing judged before is worse.
Everything returned here is a value or a record; route.phase_lines renders them."""
from __future__ import annotations

from dataclasses import dataclass, field

TASK_CALLS = ("tasks", "bus_tasks", "pour")
NET_CALLS = ("nets", "rest", "bus")


@dataclass(frozen=True)
class Named:
    net: str
    found_by: str

    def record(self) -> dict:
        return {"net": self.net, "found_by": self.found_by}


@dataclass(frozen=True)
class Blocked:
    net: str
    named: tuple
    connections: tuple = ()


def _named(blocked_by) -> list:
    """The nets an evidence record's `blocked_by` names as other copper (KRT docs/connections.md, "Failure evidence"):
    `preexisting` entries, and `static` entries of kind `track` (a net's tracks the failed search's frontier met).
    Pads and this call's own routed copper (`frontier`) are not earlier copper."""
    out = []
    for b in blocked_by or ():
        if b.get("net") and (b.get("found_by") == "preexisting"
                             or (b.get("found_by") == "static" and b.get("kind") == "track")):
            out.append(Named(b["net"], b["found_by"]))
    return out


def _once(named) -> tuple:
    seen, out = set(), []
    for n in named:
        if n.net not in seen:
            seen.add(n.net)
            out.append(n)
    return tuple(out)


def blocked_of(kind: str, records=(), summary: dict | None = None) -> list:
    """The blocked units of one call: for a task call (`tasks`, `bus_tasks`, a `pour` call's tasks) each net with a
    `failed` record, its failed tasks as the unit's connections; for a whole-net call each net in the summary's
    `net_evidence`, named from it and from the summary's `blockers` entries of stage `preexisting` (KRT
    route.py:4615-4625: the router's pre-existing blocker names, kept there when a reconcile pass replaced the net's
    evidence). A unit nothing names is left out; a pair call has none."""
    if kind in TASK_CALLS:
        units = {}
        for r in records:
            if r.get("status") != "failed":
                continue
            conns, named = units.setdefault(r["net"], ([], []))
            conns.append({k: r[k] for k in ("net", "from", "to", "widths")})
            named.extend(_named((r.get("evidence") or {}).get("blocked_by")))
        return [Blocked(n, _once(named), tuple(conns)) for n, (conns, named) in units.items() if named]
    if kind in NET_CALLS:
        summary = summary or {}
        evidence = summary.get("net_evidence") or {}
        pre = {}
        for b in summary.get("blockers") or ():
            if b.get("stage") == "preexisting":
                pre.setdefault(b.get("net"), []).extend(Named(x["net"], "preexisting")
                                                         for x in b.get("blocked_by") or () if x.get("net"))
        out = []
        for n in list(evidence) + [n for n in pre if n not in evidence]:
            named = _once(_named((evidence.get(n) or {}).get("blocked_by")) + pre.get(n, []))
            if named:
                out.append(Blocked(n, named))
        return out
    return []
```

- [ ] **Step 4: Run.** `<TEST> --full tests/test_rip_reroute.py` - expected PASS.

- [ ] **Step 5: Commit** `src/placemat/kicad/rip_reroute.py tests/test_rip_reroute.py`, message
"Rip and reroute: the blocked units a call leaves and the nets its router names", then the attribution grep.

---

## Task 4: Router copper and victims

**Files:**
- Modify: `$WT/src/placemat/kicad/route.py:1164-1184` (`routed_copper`: its key and item reader become
  `copper_key(pcbnew, item)` and `copper_items(path) -> set`, `routed_copper` uses them unchanged in result)
- Modify: `$WT/src/placemat/kicad/rip_reroute.py`
- Test: `$WT/tests/test_rip_reroute.py` (pure), `$WT/tests/test_rip_reroute_board.py` (create; pcbnew)

**Interfaces:** Produces

```python
# route.py
def copper_key(pcbnew, item) -> tuple       # (kind "segment" | "arc" | "via", net, layer id, ends rounded to 4 dp mm)
def copper_items(path) -> set               # copper_key of every track, arc and via on a board
# rip_reroute.py
def router_nets(board, script_keys) -> dict             # {net: items of router copper}
def laid_nets(before, after) -> set                     # nets with copper on `after` not on `before`
def victims_of(unit, *, router_nets, laid_by_call, pour_nets, pair_nets, excluded) -> tuple
    # (victims: tuple of net names, not_ripped: tuple of {"net", "reason"})
```

- [ ] **Step 1: Failing tests.** Pure, in `tests/test_rip_reroute.py`:

```python
def test_victims_are_named_nets_with_router_copper_laid_before_the_call():
    unit = rr.Blocked("N", tuple(rr.Named(n, "preexisting") for n in ("N", "S", "L", "P", "D", "X", "V")))
    victims, skipped = rr.victims_of(unit, router_nets={"L": 3, "P": 2, "D": 2, "X": 1, "V": 4}, laid_by_call={"L"},
                                     pour_nets={"P"}, pair_nets={"D"}, excluded={"X"})
    assert victims == ("V",)
    assert skipped == ({"net": "N", "reason": "own_net"}, {"net": "S", "reason": "no_router_copper"},
                       {"net": "L", "reason": "routed_by_call"}, {"net": "P", "reason": "pour_net"},
                       {"net": "D", "reason": "pair_net"}, {"net": "X", "reason": "excluded"})
```

pcbnew, in `tests/test_rip_reroute_board.py` (uses Task 9's `rip_board` only after Task 9; here build the board with
`tests.test_net_clearance._two_part_board`, whose SW track is script copper):

```python
"""Rip and reroute on real boards (pcbnew), no router."""
import shutil

import pytest

from placemat.kicad import rip_reroute as rr
from placemat.kicad.route import copper_items
from tests.conftest import needs_kicad
from tests.test_net_clearance import _two_part_board


def _add_track(pcb, net, a, b, width=0.2, layer="F.Cu"):
    text = pcb.read_text()
    nid = {"SW": 1, "FB": 2, "VIN": 3}[net]
    seg = '\t(segment (start %g %g) (end %g %g) (width %g) (layer "%s") (net %d))\n' % (*a, *b, width, layer, nid)
    pcb.write_text(text.replace("\t(gr_rect", seg + "\t(gr_rect", 1))


@needs_kicad
def test_router_copper_is_what_the_input_board_lacks(tmp_path):
    pytest.importorskip("pcbnew")
    given = _two_part_board(tmp_path)
    script = frozenset(copper_items(given))
    routed = tmp_path / "routed.kicad_pcb"
    shutil.copy(given, routed)
    _add_track(routed, "FB", (110, 110), (125, 110))
    assert rr.router_nets(routed, script) == {"FB": 1}
    assert rr.laid_nets(given, routed) == {"FB"}
```

- [ ] **Step 2: Run.** `<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_board.py` - expected FAIL.

- [ ] **Step 3: Implement.** In route.py, take the key out of `routed_copper` and keep its result:

```python
def copper_key(pcbnew, t) -> tuple:
    """A track, arc or via as the route's copper comparisons key it: kind, net, layer and ends (mm, 4 places)."""
    kind = "via" if t.Type() == pcbnew.PCB_VIA_T else "arc" if t.Type() == pcbnew.PCB_ARC_T else "segment"
    ends = tuple(round(pcbnew.ToMM(v), 4) for p in (t.GetStart(), t.GetEnd()) for v in (p.x, p.y))
    return (kind, t.GetNetname(), t.GetLayer(), ends)


def copper_items(path) -> set:
    """copper_key of every track, arc and via on the board at `path`."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(str(path))
    return {copper_key(pcbnew, t) for t in board.GetTracks()}
```

and `routed_copper` computes `new = copper_items(routed_pcb) - copper_items(given_pcb)` with the rest as it was. In
rip_reroute.py:

```python
def router_nets(board, script_keys) -> dict:
    """{net: count} of the router copper on `board`: its tracks, arcs and vias that are not script copper (the route's
    input board, `script_keys` = route.copper_items of it)."""
    from .route import copper_items
    out = {}
    for k in copper_items(board) - set(script_keys):
        out[k[1]] = out.get(k[1], 0) + 1
    return out


def laid_nets(before, after) -> set:
    """The nets a call laid copper on: copper on its output board `after` that its input board `before` has not."""
    from .route import copper_items
    return {k[1] for k in copper_items(after) - copper_items(before)}


def victims_of(unit, *, router_nets, laid_by_call, pour_nets, pair_nets, excluded) -> tuple:
    """The named nets an attempt may move, and the others with why not, in the router's order (spec "What triggers an
    attempt"): never the unit's own net, a net with no router copper (script copper only), a net the failing call laid
    copper on, a pour net, a pair net or an excluded net."""
    victims, skipped = [], []
    for n in unit.named:
        reason = ("own_net" if n.net == unit.net else
                  "no_router_copper" if not router_nets.get(n.net) else
                  "routed_by_call" if n.net in laid_by_call else
                  "pour_net" if n.net in pour_nets else
                  "pair_net" if n.net in pair_nets else
                  "excluded" if n.net in excluded else None)
        if reason:
            skipped.append({"net": n.net, "reason": reason})
        else:
            victims.append(n.net)
    return tuple(victims), tuple(skipped)
```

- [ ] **Step 4: Run.** `<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_board.py tests/test_route_phases.py`
  - expected PASS (test_route_phases covers `routed_copper`'s callers).

- [ ] **Step 5: Commit** "Rip and reroute: router copper by board difference, and which named nets may move", grep.

---

## Task 5: Removing a victim's router copper

**Files:**
- Modify: `$WT/src/placemat/kicad/rip_reroute.py`
- Test: `$WT/tests/test_rip_reroute_board.py`

**Interfaces:** Produces `remove_copper(src, dst, victims, script_keys) -> dict` ({"tracks", "arcs", "vias",
"track_mm"}), writing `dst` with the source's project files beside it. Consumed by Task 10.

- [ ] **Step 1: Failing test.**

```python
@needs_kicad
def test_removing_a_victim_takes_its_router_copper_and_leaves_script_copper_and_other_nets(tmp_path):
    pytest.importorskip("pcbnew")
    given = _two_part_board(tmp_path)
    _add_track(given, "FB", (110, 110), (112, 110))          # script copper on the victim
    script = frozenset(copper_items(given))
    routed = tmp_path / "routed.kicad_pcb"
    shutil.copy(given, routed)
    _add_track(routed, "FB", (112, 110), (125, 110))         # router copper on the victim
    _add_track(routed, "VIN", (113, 110), (113, 115))        # router copper on another net
    out = tmp_path / "ripped.kicad_pcb"
    got = rr.remove_copper(routed, out, {"FB"}, script)
    assert got == {"tracks": 1, "arcs": 0, "vias": 0, "track_mm": 13.0}
    left = {(k[1], k[3]) for k in copper_items(out)}
    assert ("FB", (110.0, 110.0, 112.0, 110.0)) in left and ("VIN", (113.0, 110.0, 113.0, 115.0)) in left
    assert not any(n == "FB" and e == (112.0, 110.0, 125.0, 110.0) for n, e in left)
    assert out.with_suffix(".kicad_pro").exists()
    assert copper_items(routed) - copper_items(out)        # the source board is not written
```

- [ ] **Step 2: Run** `<TEST> --full tests/test_rip_reroute_board.py` - expected FAIL.

- [ ] **Step 3: Implement.**

```python
def remove_copper(src, dst, victims, script_keys) -> dict:
    """`src` written to `dst` without the victims' router copper: every track, arc and via of a net in `victims` that
    is not script copper, taken off with board.Delete (CLAUDE.md: never board.Remove), after group.RemoveItem when it
    is grouped. `src` is left as it was. Returns what was taken off."""
    import shutil
    from .quiet import import_pcbnew, quiet_stderr
    from .route import _copy_project, _load_board, copper_key
    pcbnew = import_pcbnew()
    shutil.copy(src, dst)
    _copy_project(src, dst)
    with quiet_stderr():
        board = _load_board(str(dst))
    out, mm = {"tracks": 0, "arcs": 0, "vias": 0}, 0.0
    for t in list(board.GetTracks()):
        if t.GetNetname() not in victims:
            continue
        key = copper_key(pcbnew, t)
        if key in script_keys:
            continue
        out[{"segment": "tracks", "arc": "arcs", "via": "vias"}[key[0]]] += 1
        if key[0] != "via":
            mm += pcbnew.ToMM(t.GetLength())
        group = t.GetParentGroup()
        if group is not None:
            group.RemoveItem(t)
        board.Delete(t)
    with quiet_stderr():
        board.Save(str(dst))
    return dict(out, track_mm=round(mm, 3))
```

- [ ] **Step 4: Run** - expected PASS. **Step 5: Commit** "Rip and reroute: take a victim's router copper off a copy of
the board", grep.

---

## Task 6: A phase's settings as one record

**Files:**
- Modify: `$WT/src/placemat/kicad/phase_run.py:1073-1094` (`route_calls`)
- Test: `$WT/tests/test_rip_reroute.py`, and `$WT/tests/test_route_phases.py` as the regression

**Interfaces:** Produces

```python
@dataclass(frozen=True)
class PhaseSettings:
    clearance_map: dict
    base_clearance: float
    clearances_file: Path | None
    common: dict           # route_tasks / router_command keywords: iterations, probe, quick, clearances, neckdown, extra_args
    layers: tuple

def phase_settings(ctx, phase, sel, stem: str) -> PhaseSettings
```

`route_calls` uses it with `stem = "p%d" % index` (the file name `p<i>_net_clearances.json` is unchanged). Task 10
uses it for each owner with its own stem.

- [ ] **Step 1: Failing test** (pure; a stand-in context):

```python
def test_a_phases_settings_are_its_clearances_layers_and_flags(tmp_path, monkeypatch):
    import types
    from placemat.kicad import phase_run, net_clearance
    from placemat.route_phase import parse_phases
    from placemat.settings import Settings
    phase = parse_phases(({"name": "legs", "layers": ["F"], "neckdown": False, "router_args": ["--via-cost", "9"]},))[0]
    sel = types.SimpleNamespace(layers=("F.Cu",))
    ctx = types.SimpleNamespace(cfg=Settings(), class_clearances={"A": 0.3}, stated_clearances={"B": 0.5}, env={},
                                geometry=types.SimpleNamespace(default_clearance=0.2), work=tmp_path,
                                iterations=None, probe=None, quick=True)
    got = phase_run.phase_settings(ctx, phase, sel, "p0_1_rip0_v0")
    assert got.layers == ("F.Cu",) and got.clearance_map["A"] == 0.3 and got.clearance_map["B"] == 0.5
    assert got.clearances_file == tmp_path / "p0_1_rip0_v0_net_clearances.json" and got.clearances_file.exists()
    assert got.common["neckdown"] is False and got.common["extra_args"] == ("--via-cost", "9")
    assert got.common["clearances"] == got.clearances_file
```

- [ ] **Step 2: Run** `<TEST> --full tests/test_rip_reroute.py` - expected FAIL.

- [ ] **Step 3: Implement** in phase_run.py, moving `route_calls`' lines 1078-1094 into:

```python
@dataclass(frozen=True)
class PhaseSettings:
    clearance_map: dict
    base_clearance: float
    clearances_file: Path | None
    common: dict
    layers: tuple


def phase_settings(ctx, phase, sel, stem: str) -> PhaseSettings:
    """What one phase's calls are routed with: its clearance map (the net classes', the capture's stated clearances
    and the ceiling from `[route] router_args` plus its own, net_clearance.merged), written to `<stem>_net_clearances.json`
    when the capture states clearances; its base clearance (route.routing_clearance); its router keywords (neck-down,
    its own router flags); and its layers. route_calls uses it for the phase, rip and reroute for each owner phase."""
    from . import net_clearance
    from .route import routing_clearance
    args = tuple(ctx.cfg.route_router_args) + tuple(phase.router_args)
    phase_map = net_clearance.merged(ctx.class_clearances, ctx.stated_clearances, net_clearance.ceiling(args, ctx.env))
    phase_file = None
    if ctx.stated_clearances:
        phase_file = ctx.work / ("%s_net_clearances.json" % stem)
        phase_file.write_text(json.dumps(phase_map, sort_keys=True) + "\n")
    common = dict(iterations=ctx.iterations, probe=ctx.probe, quick=ctx.quick, clearances=phase_file,
                  neckdown=phase.neckdown, extra_args=tuple(phase.router_args))
    return PhaseSettings(phase_map, routing_clearance(ctx.geometry.default_clearance, args, ctx.env), phase_file,
                         common, tuple(sel.layers))
```

and in `route_calls`:

```python
    st = phase_settings(ctx, phase, sel, "p%d" % index)
    ctx = replace(ctx, clearance_map=st.clearance_map, clearances_file=st.clearances_file,
                  base_clearance=st.base_clearance)
    calls = plan_calls(sel, ctx.clearance_map, ctx.base_clearance, set(ctx.excluded) | set(ctx.pour_nets))
    layers = list(st.layers)
    ...
    common = st.common
```

- [ ] **Step 4: Run** `<TEST> --full tests/test_rip_reroute.py tests/test_route_phases.py tests/test_route_pour_phases.py`
  - expected PASS.

- [ ] **Step 5: Commit** "Phase calls: a phase's clearances, layers and flags as one record", grep.

---

## Task 7: The removed connections, their owners and their calls

**Files:**
- Modify: `$WT/src/placemat/kicad/rip_reroute.py`
- Test: `$WT/tests/test_rip_reroute.py`, `$WT/tests/test_rip_reroute_board.py`

**Interfaces:** Produces

```python
@dataclass(frozen=True)
class Move:
    owner: int             # the phase index whose settings it is rerouted at
    obligation: dict       # {"net", "from", "to", "widths"}
    asked: bool            # an obligation of `owner`; False: a join no phase asks (spec, "unasked")

def asked_moves(victims, asked, upto, joined) -> tuple        # ([Move], reason | None)
def unasked_pairs(victims, input_open, moves, joined_on_board) -> list   # input-open connections to move
def first_joined(pairs, boards) -> list                       # per pair: index of the first board joining it
def receipt_widths(receipt, phase_name, net) -> dict | None
def task_of(obligation, layers) -> Task
def owner_calls(sel, moves, settings) -> list                  # plan_calls on a Selection of the owner's tasks
```

- [ ] **Step 1: Failing tests** (pure):

```python
def _ob(net, a, b, widths=None):
    return {"net": net, "from": {"ref": a[0], "pad": a[1]}, "to": {"ref": b[0], "pad": b[1]},
            "widths": widths if widths is not None else {"F.Cu": 0.2, "B.Cu": 0.2}}


def test_the_asked_moves_are_the_victims_joined_obligations_owned_by_the_earliest_phase_asking():
    legs = [_ob("V", ("U1", "1"), ("J1", "1"), {"F.Cu": 1.2})]
    signals = [_ob("V", ("J1", "1"), ("U1", "1")), _ob("V", ("U1", "1"), ("C1", "1")), _ob("V", ("C2", "1"), ("U1", "1")),
               _ob("N", ("Q1", "1"), ("Q2", "1"))]
    moves, why = rr.asked_moves({"V"}, [legs, signals], 1, [[True], [True, True, False, False]])
    assert why is None
    assert [(m.owner, m.obligation["to"]["ref"], m.asked) for m in moves] == [(0, "J1", True), (1, "C1", True)]
    assert moves[0].obligation["widths"] == {"F.Cu": 1.2}


def test_an_obligation_that_cannot_be_a_task_stops_the_moves():
    assert rr.asked_moves({"V"}, [[_ob("V", ("U1", "1"), ("J1", "1"), {})]], 0, [[True]])[1] == "victim_width_unknown"
    loose = dict(_ob("V", ("U1", "1"), ("J1", "1")), to={"ref": None, "pad": None, "at": [1.0, 2.0]})
    assert rr.asked_moves({"V"}, [[loose]], 0, [[True]])[1] == "victim_end_not_pad"


def test_joins_no_phase_asks_are_moved_too():
    moves, _ = rr.asked_moves({"V"}, [[_ob("V", ("U1", "1"), ("J1", "1"))]], 0, [[True]])
    open0 = [_ob("V", ("J1", "1"), ("U1", "1")), _ob("V", ("U1", "1"), ("R1", "2")), _ob("V", ("R1", "1"), ("R2", "1")),
             _ob("W", ("A", "1"), ("B", "1"))]
    got = rr.unasked_pairs({"V"}, open0, moves, [True, True, False, True])
    assert [(o["from"]["ref"], o["to"]["ref"]) for o in got] == [("U1", "R1")]


def test_a_phases_width_answer_for_a_net():
    receipt = {"policies": [{"name": "signals", "kind": "nets",
                             "by_net": {"V": {"status": "known", "widths": {"F.Cu": 0.5, "B.Cu": 0.5}},
                                        "U": {"status": "unknown", "widths": None}}}]}
    assert rr.receipt_widths(receipt, "signals", "V") == {"F.Cu": 0.5, "B.Cu": 0.5}
    assert rr.receipt_widths(receipt, "signals", "U") is None and rr.receipt_widths(receipt, "legs", "V") is None


def test_an_owners_calls_carry_its_widths_layers_and_buses():
    from placemat.kicad.phase_run import PhaseSettings
    from placemat.kicad.phase_select import Selection
    sel = Selection("legs", "current_paths", buses=(("S", "T", "Q"),), layers=("F.Cu",))
    st = PhaseSettings({}, 0.2, None, {}, ("F.Cu",))
    moves = [rr.Move(0, _ob("V", ("U1", "1"), ("J1", "1"), {"F.Cu": 1.2}), True),
             rr.Move(0, _ob("S", ("U1", "4"), ("J1", "4"), {"F.Cu": 0.2}), True),
             rr.Move(0, _ob("T", ("U1", "5"), ("J1", "5"), {"F.Cu": 0.2}), True)]
    calls = rr.owner_calls(sel, moves, st)
    assert [(c.kind, c.nets, [t.widths for t in c.tasks]) for c in calls] == [
        ("bus_tasks", ("S", "T"), [(("F.Cu", 0.2),), (("F.Cu", 0.2),)]),
        ("tasks", (), [(("F.Cu", 1.2),)])]
```

pcbnew (`tests/test_rip_reroute_board.py`): `first_joined` on three copies of `_two_part_board` where FB is joined
by a track only on the second and third: `rr.first_joined([(("U1", "2"), ("J1", "1"))], [b0, b1, b2]) == [1]`, and
`[None]` when no board joins it.

- [ ] **Step 2: Run** `<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_board.py` - expected FAIL.

- [ ] **Step 3: Implement.**

```python
@dataclass(frozen=True)
class Move:
    owner: int
    obligation: dict
    asked: bool


def _end(e) -> tuple:
    return (e["ref"], e["pad"], e["fp"]) if e.get("fp") else (e["ref"], e["pad"])


def asked_moves(victims, asked, upto, joined) -> tuple:
    """The obligations of phases 0..upto on a victim net that are joined on the failing call's board (`joined[k]`,
    aligned with `asked[k]`), each pad pair once, owned by the earliest phase that asks it (spec "The removed
    connections"). (moves, None), or ([], reason) when one cannot be a task: `victim_end_not_pad`,
    `victim_width_unknown`. pour_served obligations are on pour nets, never victims."""
    from .phase_run import _pair_key
    out, seen = [], set()
    for k in range(upto + 1):
        for o, j in zip(asked[k], joined[k]):
            if o["net"] not in victims or not j or o.get("pour_served"):
                continue
            key = _pair_key(o)
            if key in seen:
                continue
            seen.add(key)
            if not (o["from"].get("ref") and o["to"].get("ref")):
                return [], "victim_end_not_pad"
            if not o.get("widths"):
                return [], "victim_width_unknown"
            out.append(Move(k, {f: o[f] for f in ("net", "from", "to", "widths")}, True))
    return out, None


def unasked_pairs(victims, input_open, moves, joined_on_board) -> list:
    """The route's input-board open connections (`input_open`) on a victim net that are joined on the failing call's
    board (`joined_on_board`, aligned) and whose pad pair no move has: joins a call made that no phase asks."""
    from .phase_run import _pair_key
    have = {_pair_key(m.obligation) for m in moves}
    return [o for o, j in zip(input_open, joined_on_board)
            if o["net"] in victims and j and o["from"].get("ref") and o["to"].get("ref") and _pair_key(o) not in have]


def first_joined(pairs, boards) -> list:
    """For each pad pair ((ref, pad[, fp]), (ref, pad[, fp])), the index of the first board in `boards` whose copper
    joins it (phase_run.joined_pairs), or None."""
    from .phase_run import joined_pairs
    out = [None] * len(pairs)
    for i, b in enumerate(boards):
        todo = [n for n, v in enumerate(out) if v is None]
        if not todo:
            break
        for n, j in zip(todo, joined_pairs(b, [pairs[n] for n in todo])):
            if j:
                out[n] = i
    return out


def receipt_widths(receipt, phase_name, net) -> dict | None:
    """The router's width per layer for `net` in phase `phase_name` (kicad/width_policy.py's receipt), None when it has
    none or two of its records disagree."""
    found = [r["by_net"][net] for r in receipt.get("policies") or () if r["name"] == phase_name and net in r["by_net"]]
    widths = [e["widths"] for e in found if e.get("status") == "known"]
    if not widths or len(widths) != len(found) or any(w != widths[0] for w in widths):
        return None
    return dict(widths[0])


def task_of(o, layers):
    """An obligation as a --connections task, its widths in the layer order of the owner phase."""
    from .phase_select import Task
    return Task(o["net"], _end(o["from"]), _end(o["to"]), tuple((l, o["widths"][l]) for l in layers))


def owner_calls(sel, moves, settings) -> list:
    """An owner phase's calls for its moved connections: plan_calls on a Selection of just those tasks at its layers,
    with its buses cut to the moved nets, so they group by (clearance, widths), widest clearance first, as its own task
    calls do (phase_run.plan_calls)."""
    from .phase_run import plan_calls
    from .phase_select import Selection
    tasks = tuple(task_of(m.obligation, settings.layers) for m in moves)
    nets = {t.net for t in tasks}
    buses = tuple(b for b in (tuple(n for n in bus if n in nets) for bus in sel.buses) if b)
    own = Selection(sel.phase, "rip", tasks=tasks, buses=buses, layers=settings.layers)
    return plan_calls(own, settings.clearance_map, settings.base_clearance, set())
```

`plan_calls`' `bus_tasks` branch names the bus's nets as given; with the bus cut to the moved nets it names only them.

- [ ] **Step 4: Run** - expected PASS. **Step 5: Commit** "Rip and reroute: the moved connections, their owner phases
and their calls", grep.

---

## Task 8: Standing and the verdict

**Files:**
- Modify: `$WT/src/placemat/kicad/rip_reroute.py`
- Test: `$WT/tests/test_rip_reroute.py`

**Interfaces:** Produces

```python
LEVEL = ("open", "joined", "clean")
KEEP_CHECKS = ("blocked_not_clean", "obligation_worse", "net_open_rose", "drc_new", "off_layer")
ROUTER_REASONS = ("router_failed", "router_refused", "router_timeout")

@dataclass
class Standing:
    board: Path            # the board judged (not the DRC copy)
    copy: Path             # its DRC copy: guards off, zones filled
    drc_json: Path
    open_nets: dict        # {net: open items}
    errors: list           # drc.real_errors of the DRC
    judged: list           # per phase 0..upto: judge_obligations
    outcomes: list         # per phase 0..upto: the record status per obligation, or None

def rank(j, outcome) -> int
@dataclass(frozen=True)
class Verdict:
    kept: bool
    reason: str | None
    worse: tuple = ()
    open_rose: dict = field(default_factory=dict)
    drc_new: int = 0
    off_layer: int = 0
def verdict(before, after, asked, names, blocked_clean, off_layer) -> Verdict
def standing(ctx, asked, phases, upto, board, stem, connections) -> Standing      # Task 10 calls it
def off_layer(given, routed, layers) -> int
```

- [ ] **Step 1: Failing tests** (pure: Standings built by hand):

```python
def _st(judged, outcomes=None, open_nets=None, errors=()):
    from pathlib import Path
    return rr.Standing(Path("b"), Path("c"), Path("d"), dict(open_nets or {}), list(errors), judged,
                       outcomes or [[None] * len(j) for j in judged])


J_CLEAN = {"joined": True, "violated": False, "under": {}}
J_UNDER = {"joined": True, "violated": False, "under": {"F.Cu": 0.1}}
J_OPEN = {"joined": False, "violated": False, "under": {}}
ASKED = [[_ob("V", ("U1", "1"), ("J1", "1"))], [_ob("N", ("Q1", "1"), ("Q2", "1")), _ob("M", ("R1", "1"), ("R2", "1"))]]


def test_an_attempt_that_loses_nothing_is_kept():
    v = rr.verdict(_st([[J_CLEAN], [J_OPEN, J_OPEN]]), _st([[J_CLEAN], [J_CLEAN, J_OPEN]]), ASKED, ["legs", "signals"],
                   [True], 0)
    assert (v.kept, v.reason, v.worse) == (True, None, ())


def test_the_first_failing_check_is_the_reason_and_every_finding_is_kept():
    before = _st([[J_CLEAN], [J_OPEN, J_UNDER]], open_nets={"N": 1, "GND": 0})
    after = _st([[J_UNDER], [J_CLEAN, J_OPEN]], open_nets={"N": 0, "GND": 2},
                errors=[{"type": "clearance", "nets": ["V", "N"], "items": []}])
    v = rr.verdict(before, after, ASKED, ["legs", "signals"], [False], 1)
    assert v.kept is False and v.reason == "blocked_not_clean"
    assert v.worse == ({"phase": "legs", "net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "1"},
                        "before": "clean", "after": "joined"},
                       {"phase": "signals", "net": "M", "from": {"ref": "R1", "pad": "1"}, "to": {"ref": "R2", "pad": "1"},
                        "before": "joined", "after": "open"})
    assert v.open_rose == {"GND": [0, 2]} and v.drc_new == 1 and v.off_layer == 1
    assert rr.verdict(before, after, ASKED, ["legs", "signals"], [True], 0).reason == "obligation_worse"


def test_a_joined_narrow_outcome_ranks_as_joined():
    assert rr.rank(J_CLEAN, "joined_narrow") == 1 and rr.rank(J_CLEAN, "routed") == 2 and rr.rank(J_OPEN, None) == 0
```

(The error record shape must be what `drc.real_errors` returns; read `drc.py:308-352` and build the test's error the
same way, so `drc.new_errors` matches it.)

- [ ] **Step 2: Run** - expected FAIL.

- [ ] **Step 3: Implement.**

```python
LEVEL = ("open", "joined", "clean")
KEEP_CHECKS = ("blocked_not_clean", "obligation_worse", "net_open_rose", "drc_new", "off_layer")
ROUTER_REASONS = ("router_failed", "router_refused", "router_timeout")


@dataclass
class Standing:
    board: Path
    copy: Path
    drc_json: Path
    open_nets: dict
    errors: list
    judged: list
    outcomes: list


def rank(j, outcome) -> int:
    """2 clean (phase_run.is_clean), 1 joined but not clean, 0 open."""
    from .phase_run import is_clean
    return 2 if is_clean(j, outcome) else 1 if j["joined"] else 0


@dataclass(frozen=True)
class Verdict:
    kept: bool
    reason: str | None
    worse: tuple = ()
    open_rose: dict = field(default_factory=dict)
    drc_new: int = 0
    off_layer: int = 0


def verdict(before, after, asked, names, blocked_clean, off_layer) -> Verdict:
    """Keep the candidate (`after`) over the failing call's board (`before`) only when every blocked connection is
    clean, no obligation of phases 0..i ranks lower, no net has more open items, the DRC has no new real error and no
    track lies off its owner's layers (spec, "The keep or restore test"). The reason is the first check that fails,
    in KEEP_CHECKS order; every finding is returned."""
    from .drc import new_errors
    worse = []
    for k, obs in enumerate(asked):
        for o, jb, ob, ja, oa in zip(obs, before.judged[k], before.outcomes[k], after.judged[k], after.outcomes[k]):
            rb, ra = rank(jb, ob), rank(ja, oa)
            if ra < rb:
                worse.append({"phase": names[k], "net": o["net"], "from": o["from"], "to": o["to"],
                              "before": LEVEL[rb], "after": LEVEL[ra]})
    rose = {n: [before.open_nets.get(n, 0), v] for n, v in sorted(after.open_nets.items())
            if v > before.open_nets.get(n, 0)}
    new = len(new_errors(after.errors, before.errors))
    failed = dict(zip(KEEP_CHECKS, (not (blocked_clean and all(blocked_clean)), bool(worse), bool(rose), new > 0,
                                    off_layer > 0)))
    reason = next((c for c in KEEP_CHECKS if failed[c]), None)
    return Verdict(reason is None, reason, tuple(worse), rose, new, off_layer)


def standing(ctx, asked, phases, upto, board, stem, connections) -> Standing:
    """A board as the keep test judges it: a DRC of a copy with guards off and zones filled (as phase_run.judge_phase),
    every obligation of phases 0..upto judged on it against its own phase's input DRC (phase_input_drc, ruling S15),
    and each obligation's outcome from `connections[k]`, that phase's records as they stand."""
    import json
    import shutil
    from .drc import real_errors, run_drc
    from .phase_run import judge_obligations, phase_input_drc, phase_neck, records_of
    from .route import _copy_project, fill_zones, remove_guards
    copy, drc_json = ctx.work / (stem + "_drc.kicad_pcb"), ctx.work / (stem + "_drc.json")
    shutil.copy(board, copy)
    _copy_project(board, copy)
    remove_guards(str(copy))
    fill_zones(str(copy))
    drc = run_drc(copy, drc_json, refill_zones=False)
    judged, outcomes = [], []
    for k in range(upto + 1):
        obs = asked[k]
        judged.append(judge_obligations(copy, obs, drc_json, phase_neck(ctx.cfg, phases[k]), drc.is_real_kind,
                                        phase_input_drc(ctx.work, k)))
        outcomes.append([r.get("status") if r else None for r in records_of(obs, connections[k])])
    return Standing(Path(board), copy, drc_json, dict(drc.open_nets),
                    real_errors(json.loads(drc_json.read_text()), drc.is_real_kind), judged, outcomes)


def off_layer(given, routed, layers) -> int:
    """Tracks (not vias) on `routed` that `given` lacks, on a layer outside `layers` (layer names)."""
    from ..board_geometry import added_copper
    from ..values import CopperLayer
    from .read import read_board
    allowed = {CopperLayer.of(l) for l in layers}
    new = added_copper(read_board(str(given)).copper, read_board(str(routed)).copper)
    return sum(1 for c in new if c.kind == "track" and not set(c.layers) <= allowed)
```

`from pathlib import Path` goes at the module top. Read `board_geometry.added_copper` and `CopperItem.layers` first and
match their types (layers are `CopperLayer`s; see phase_run.width_shortfall:806 for the same conversion).

- [ ] **Step 4: Run** - expected PASS. **Step 5: Commit** "Rip and reroute: the keep test", grep.

---

## Task 9: The rip board and a stand-in router that lays copper

**Files:**
- Create: `$WT/tests/rip_helpers.py`
- Test: `$WT/tests/test_rip_reroute_board.py`

**Interfaces:** Produces `rip_board(tmp_path, *, a_track=False) -> Path`, `TOY` (a stand-in `py_router/route.py`),
and a `toy_rig` fixture factory used by Tasks 10-15. The engine tests in Tasks 11-15 run on it.

The board: net A between P1.1 (105, 110) and P2.1 (125, 110), net B between Q1.1 (115, 104) and Q2.1 (115, 116); SMD
pads 0.6 mm on F.Cu; outline 100..135 x 100..125; Default class clearance 0.15, track 0.2. `a_track=True` adds A's
straight track as script copper. The stand-in router lays each connection on the call's first layer at its width:
straight, or else a detour `TOY_DETOUR` mm (default 8; "0": none) to either side; a path is blocked within clearance
0.15 of another net's track (it names that net) or pad. A `--connections` call writes one record per task; a
`--nets` call routes each named net (or `*` minus `!X`) with two pads and no track yet, at `--power-nets-widths` or
0.2, and for a failed net writes `net_evidence` with an empty `blocked_by` and the names in `blockers` (stage
`preexisting`), as pic_programmer's run recorded them.

With A laid straight first, B is blocked every way. With A taken off, B goes straight, and A's detour at y = 118
clears B (2 mm from Q2.1's centre).

- [ ] **Step 1: Write `tests/rip_helpers.py`:**

```python
"""A board and a stand-in router for rip and reroute: the stand-in lays copper (straight, or a detour to either side)
and names the nets of the tracks that block a connection, so a route can be blocked by an earlier call's copper."""
import json
import sys
import textwrap
from pathlib import Path

from tests.phase_helpers import fake_capabilities
from tests.test_net_clearance import _project

TOY = textwrap.dedent('''
    import json, math, os, sys
    import pcbnew
    a = sys.argv[1:]
    with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
        f.write(json.dumps(a) + "\\n")
    def opt(flag):
        return a[a.index(flag) + 1] if flag in a else None
    def opts(flag):
        if flag not in a:
            return []
        i, out = a.index(flag) + 1, []
        while i < len(a) and not a[i].startswith("--"):
            out.append(a[i]); i += 1
        return out
    board = pcbnew.LoadBoard(a[0])
    layers = opts("--layers")
    layer = board.GetLayerID(layers[0])
    mm, CLR = pcbnew.ToMM, 0.15
    def pads_of(net):
        return {(fp.GetReference(), p.GetNumber()): (mm(p.GetPosition().x), mm(p.GetPosition().y))
                for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname() == net}
    def d_ps(c, p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((c[0] - p[0]) * dx + (c[1] - p[1]) * dy) / L))
        return math.hypot(c[0] - p[0] - t * dx, c[1] - p[1] - t * dy)
    def d_ss(p, q, r, s):
        def cr(o, u, v):
            return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
        if (cr(r, s, p) > 0) != (cr(r, s, q) > 0) and (cr(p, q, r) > 0) != (cr(p, q, s) > 0):
            return 0.0
        return min(d_ps(p, r, s), d_ps(q, r, s), d_ps(r, p, q), d_ps(s, p, q))
    def hits(net, path, w):
        met, blocked = [], False
        for t in board.GetTracks():
            if t.GetNetname() == net or t.GetLayer() != layer or t.Type() == pcbnew.PCB_VIA_T:
                continue
            r, s = (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))
            if any(d_ss(p, q, r, s) < w / 2 + mm(t.GetWidth()) / 2 + CLR for p, q in zip(path, path[1:])):
                blocked = True
                if t.GetNetname() not in met:
                    met.append(t.GetNetname())
        for fp in board.GetFootprints():
            for pd in fp.Pads():
                c = (mm(pd.GetPosition().x), mm(pd.GetPosition().y))
                if pd.GetNetname() != net and any(d_ps(c, p, q) < w / 2 + 0.3 + CLR for p, q in zip(path, path[1:])):
                    blocked = True
        return blocked, met
    def lay(net, s, e, w):
        d = float(os.environ.get("TOY_DETOUR", "8"))
        L = math.hypot(e[0] - s[0], e[1] - s[1]) or 1.0
        n = (-(e[1] - s[1]) / L, (e[0] - s[0]) / L)
        paths = [[s, e]] + ([[s, (s[0] + n[0] * d * k, s[1] + n[1] * d * k), (e[0] + n[0] * d * k, e[1] + n[1] * d * k), e]
                             for k in (1, -1)] if d else [])
        met = []
        for path in paths:
            blocked, by = hits(net, path, w)
            met += [m for m in by if m not in met]
            if not blocked:
                for p, q in zip(path, path[1:]):
                    t = pcbnew.PCB_TRACK(board)
                    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(p[0]), pcbnew.FromMM(p[1])))
                    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(q[0]), pcbnew.FromMM(q[1])))
                    t.SetWidth(pcbnew.FromMM(w)); t.SetLayer(layer); t.SetNet(board.FindNet(net))
                    board.Add(t)
                return True, sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(path, path[1:])), []
        return False, 0.0, met
    def evidence(met):
        return {"scope": "net", "search": None, "verdicts": [], "narrow": [], "diagnosis": "unknown",
                "blocked_by": [{"found_by": "preexisting", "kind": "copper", "net": m, "ref": None, "pad": None,
                                "layer": None, "at": None, "cells": None, "seen_from": None,
                                "near_source_cells": None, "near_target_cells": None} for m in met]}
    doc = {}
    if "--connections" in a:
        recs = []
        for t in json.load(open(opt("--connections"))):
            ends = pads_of(t["net"])
            ok, length, met = lay(t["net"], ends[(t["from"]["ref"], t["from"]["pad"])],
                                  ends[(t["to"]["ref"], t["to"]["pad"])], max(t["widths"].values()))
            recs.append(dict(t, status="routed" if ok else "failed", reason=None, joined=ok, length_mm=length,
                             min_width_mm=dict(t["widths"]) if ok else {}, layers=layers, path=None,
                             evidence=None if ok else evidence(met)))
        doc["connections"] = recs
    else:
        pats = opts("--nets")
        names = sorted({p.GetNetname() for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname()})
        if pats and pats[0] == "*":
            nets = [n for n in names if "!" + n not in pats]
        else:
            nets = [n for n in names if n in pats]
        powered = dict(zip(opts("--power-nets"), map(float, opts("--power-nets-widths"))))
        doc["net_evidence"], doc["blockers"] = {}, []
        for net in nets:
            ends = sorted(pads_of(net).values())
            if len(ends) != 2 or any(t.GetNetname() == net for t in board.GetTracks()):
                continue
            ok, _, met = lay(net, ends[0], ends[1], powered.get(net, 0.2))
            if not ok:
                doc["net_evidence"][net] = evidence([])
                doc["blockers"].append({"net": net, "stage": "preexisting",
                                        "blocked_by": [{"net": m, "preexisting": True} for m in met]})
    board.Save(a[1])
    if "--json-out" in a:
        open(opt("--json-out"), "w").write(json.dumps(doc))
''')

CLASSES = 'def net_clearance_map_by_id(pcb_path, nets, design_rules=None):\n    return {}\n'


def _part(ref, x, y, net):
    return ('\t(footprint "t:p" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
            '(layer "F.SilkS"))\n\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu" "F.Mask") '
            '(net "%s"))\n\t)\n' % (x, y, ref, net))


def rip_board(tmp_path, *, a_track=False) -> Path:
    """Net A: P1.1 (105, 110) to P2.1 (125, 110); net B: Q1.1 (115, 104) to Q2.1 (115, 116)."""
    pcb = tmp_path / "board" / "layout.kicad_pcb"
    pcb.parent.mkdir()
    track = '\t(segment (start 105 110) (end 125 110) (width 0.2) (layer "F.Cu") (net 1))\n' if a_track else ""
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n'
                   '\t(net 1 "A")\n\t(net 2 "B")\n'
                   + _part("P1", 105, 110, "A") + _part("P2", 125, 110, "A")
                   + _part("Q1", 115, 104, "B") + _part("Q2", 115, 116, "B") + track
                   + '\t(gr_rect (start 100 100) (end 135 125) (stroke (width 0.1) (type solid)) (fill no) '
                     '(layer "Edge.Cuts"))\n)\n')
    _project(pcb, [{"name": "Default", "clearance": 0.15, "track_width": 0.2}])
    return pcb


def toy_router(tmp_path) -> Path:
    """A router checkout whose route.py is TOY (and whose plane repair is never called here)."""
    krt = tmp_path / "krt"
    (krt / ".venv/bin").mkdir(parents=True)
    (krt / ".venv/bin/python").symlink_to(sys.executable)
    (krt / "py_router").mkdir()
    (krt / "py_router/route.py").write_text(TOY)
    (krt / "py_router/repair_planes.py").write_text(TOY)
    (krt / "py_router/list_nets.py").write_text(CLASSES)
    fake_capabilities(krt)
    (krt / "VERSION").write_text("toy-1\n")
    return krt
```

Check `_project`'s signature in `tests/test_net_clearance.py` and the `.kicad_pcb` header against `_two_part_board`
(same version and layers); keep the same form.

- [ ] **Step 2: A test of the stand-in itself** in `tests/test_rip_reroute_board.py`: run `TOY` directly
(`subprocess.run([sys.executable, krt / "py_router/route.py", board, out, "--nets", "A", "--layers", "F.Cu",
"--json-out", summary])` with `FAKE_ROUTER_LOG` set) on `rip_board`: A is laid straight (one track, (105,110)-(125,110));
then on that output `--nets B` lays nothing and writes `blockers == [{"net": "B", "stage": "preexisting",
"blocked_by": [{"net": "A", "preexisting": True}]}]`; then a `--connections` file with A's task on a board holding only
B's straight track lays A's detour (three tracks, the middle one at y = 118).

- [ ] **Step 3: Run** `<TEST> --full tests/test_rip_reroute_board.py` - expected PASS. If DRC-free geometry is in
doubt, also run `kicad-cli pcb drc` on the detoured board and expect no clearance or short errors.

- [ ] **Step 4: Commit** "Tests: a board and a stand-in router for rip and reroute", grep.

---

## Task 10: The route's history and the driver's skeleton

**Files:**
- Modify: `$WT/src/placemat/kicad/rip_reroute.py` (`History`, `CallRip`, `gate`, `after_call` returning the board
  unchanged when nothing is attempted)
- Modify: `$WT/src/placemat/kicad/phase_run.py` (`PhaseContext.history`, `Routed.rip`, `phase_record(..., rip=None)`,
  `judge_phase` passes it, `route_calls` calls `after_call`)
- Modify: `$WT/src/placemat/kicad/route.py` (`_route_board`: the input board's open connections in a variable; the
  history built after `width_policy.apply` (:1393) and the guards (:1377); each phase's board and records added to it,
  routed or reused)
- Test: `$WT/tests/test_rip_reroute.py` (gate), `$WT/tests/test_rip_reroute_route.py` (create)

**Interfaces:** Produces

```python
@dataclass
class History:
    phases: tuple            # the phases routed (run_list)
    selections: tuple        # their Selections as picked before routing (layers, buses, pairs)
    asked: tuple             # each phase's obligations after width_policy.apply
    receipt: dict            # width_policy receipt
    script_keys: frozenset   # route.copper_items of the route's input board after its guards
    input_open: tuple        # open_connections of the route's input board
    boards: list = field(default_factory=list)        # each finished phase's board, in order
    connections: list = field(default_factory=list)   # each finished phase's records ("connections")
    moved: dict = field(default_factory=dict)         # {phase index: kept reroute records owned by it, in order}

    def finish(self, index, board, record) -> None    # adds a finished (routed or reused) phase

@dataclass
class CallRip:
    made: int = 0
    tried: set = field(default_factory=set)           # frozensets of victims restored in this call
    stopped: bool = False

def gate(victims, *, rip: CallRip, max_nets: int, attempts: int) -> str | None
    # the skip reason, or None: no_victim, too_many_victims, stopped, limit, tried (this order)

@dataclass
class AfterCall:
    board: Path              # the board the phase goes on from
    records: list            # router records that supersede phase i's connections
    calls: list              # (Call, board in, board out) of phase i's to add to out.calls
    trim: set                # nets of phase i whose earlier calls' width asks are dropped (moved copper)
    summaries: list          # summary paths of the attempts' router calls
    widths: list             # route.width rows of reroutes owned by earlier phases

def after_call(ctx, index, phase, sel, k, call, board_in, board_out, records, summary, connections, rip_record) -> AfterCall
```

`rip_record` is the phase's `{"attempts": [], "skipped": []}`, appended to in place.

- [ ] **Step 1: Failing tests.** Pure, `gate`:

```python
def test_the_gate_skips_in_order():
    r = rr.CallRip()
    assert rr.gate((), rip=r, max_nets=3, attempts=4) == "no_victim"
    assert rr.gate(("A", "B", "C", "D"), rip=r, max_nets=3, attempts=4) == "too_many_victims"
    assert rr.gate(("A",), rip=rr.CallRip(stopped=True), max_nets=3, attempts=4) == "stopped"
    assert rr.gate(("A",), rip=rr.CallRip(made=4), max_nets=3, attempts=4) == "limit"
    assert rr.gate(("A",), rip=rr.CallRip(tried={frozenset({"A"})}), max_nets=3, attempts=4) == "tried"
    assert rr.gate(("A",), rip=r, max_nets=3, attempts=4) is None
    assert rr.gate(("A",), rip=r, max_nets=3, attempts=0) == "limit"
```

Engine, `tests/test_rip_reroute_route.py`:

```python
"""Rip and reroute through a whole route: a stand-in router that lays copper (tests/rip_helpers.py), real pcbnew and
DRC."""
import json

import pytest

from placemat.kicad.route import route_board
from placemat.settings import Settings, bind
from tests.conftest import needs_kicad
from tests.phase_helpers import phases
from tests.rip_helpers import rip_board, toy_router


@pytest.fixture
def toy(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = toy_router(tmp_path)
    monkeypatch.setenv("FAKE_ROUTER_LOG", str(tmp_path / "calls"))

    class Toy:
        def calls(self):
            log = tmp_path / "calls"
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

        def route(self, *raw, pcb=None, settings=None, **kw):
            with bind(Settings(**(settings or {}))):
                return route_board(pcb or rip_board(tmp_path), tmp_path / "route", router_dir_override=str(krt),
                                   layers=["F.Cu", "B.Cu"], phases=phases(*raw), **kw)
    return Toy()


A = {"name": "a", "nets": ["A"]}
B = {"name": "b", "nets": ["B"]}


@needs_kicad
def test_every_phase_records_its_rip_and_rip_off_changes_nothing(toy):
    report = toy.route(A, B, settings={"route_rip_attempts": 0})
    assert [p["rip"] for p in report.phases] == [{"attempts": [], "skipped": []}] * 2
    assert [p["joined"] for p in report.phases] == [1, 0]
```

- [ ] **Step 2: Run** `<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_route.py` - expected FAIL.

- [ ] **Step 3: Implement.**
  - `History.finish(index, board, record)`: append `board` and `record.get("connections") or []`; for every kept
    attempt in `record["rip"]["attempts"]`, add each `rerouted` entry whose `index < index` (the argument) to
    `moved[entry["index"]]`, in order.
  - `PhaseContext` gains `history: object = None` (last field). `Routed` gains `rip: dict` (default
    `{"attempts": [], "skipped": []}`) in `record()` and `of()`. `phase_record(..., rip=None)` sets `rec["rip"] =
    dict(rip or {"attempts": [], "skipped": []})`; `judge_phase` passes `routed.rip`.
  - `route_calls`: `rip = {"attempts": [], "skipped": []}`, `extra_widths = []` and `trims = []`. After each call
    but `pairs`, with `recs` the call's records (`run.records` for tasks, bus_tasks and pour), `doc` its summary (read
    from `summary` when it exists, for nets, rest and bus) and `prev` the board the call was given:

```python
        if call.kind != "pairs" and ctx.history is not None:
            from . import rip_reroute
            got = rip_reroute.after_call(ctx, index, phase, sel, k, call, prev, nxt, recs, doc, connections, rip)
            if got.trim:
                trims.append((len(out.calls), set(got.trim)))     # the calls made so far laid the moved copper
            nxt = got.board
            connections = superseded(connections, got.records)
            out.calls += got.calls
            out.summaries += [(phase.name, k, s) for s in got.summaries]
            extra_widths += got.widths
```

    Before `phase_widths`, each call made before a kept attempt loses the moved nets from its asks:
    `out.calls = [(_without(c, set().union(*[n for at, n in trims if at > j])), a, b) for j, (c, a, b) in
    enumerate(out.calls)]`, with `_without(call, nets) = replace(call, nets=tuple(n for n in call.nets if n not in
    nets), tasks=tuple(t for t in call.tasks if t.net not in nets))`. Then
    `Routed(..., widths=phase_widths(...) + narrow_join_widths(...) + task_widths(...) + extra_widths, rip=rip)`.
  - `after_call` in this task: return `AfterCall(board_out, [], [], set(), [], [])` when
    `ctx.cfg.route_rip_attempts <= 0` or `blocked_of(...)` is empty; otherwise, for each unit, compute victims
    (Task 4) and the gate; record each skip as
    `{"call": k, "net": unit.net, "named": [n.record() for n in unit.named], "not_ripped": list(not_ripped), "reason": r}`.
    Attempts come in Task 11; until then a unit that passes the gate is skipped with reason `limit`. (Task 11 replaces
    that line.)
  - `_route_board`: `input_open = open_connections(pcb_in, work / "drc_before.json")` before `obligations_of` and
    passed to it; after `asked = width_policy.apply(...)` and the guards, `hist = rip_reroute.History(tuple(run_list),
    tuple(picked[p.name] for p in run_list), tuple(asked), width_receipt, frozenset(copper_items(pcb_in)),
    tuple(input_open))`, given to `PhaseContext(..., history=hist)`. In the loop, after a phase is reused
    (`records.append(dict(saved["record"], reused=True))`) and after one is routed and judged, call
    `hist.finish(i, board, record)`.
  - The kept-result digest: `"phase-judgement-v10"` (route.py:1416). Grep the tests for `phase-judgement-v9` and
    update any that name it.

- [ ] **Step 4: Run** `<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_route.py tests/test_route_phases.py tests/test_route_pour_phases.py tests/test_route_resume.py`
  - expected PASS.

- [ ] **Step 5: Commit** "Rip and reroute: the route's history and a record per phase", grep.

---

## Task 11: One attempt

**Files:**
- Modify: `$WT/src/placemat/kicad/rip_reroute.py` (`blocked_connections`, `plan_moves`, `attempt`; `after_call`
  makes attempts)
- Test: `$WT/tests/test_rip_reroute_route.py`

**Interfaces:** Produces

```python
def blocked_connections(unit, call, before, hist, index, phase) -> tuple    # ([{"net","from","to","widths"}], reason | None)
def plan_moves(victims, hist, index, before) -> tuple                        # ([Move], reason | None)
def reroute_blocked(ctx_i, call, unit, conns, ripped, settings, stem, phase_name) -> TaskRun
    # step 2: join_pour again for a pour call (its TaskRun with `board` = the join's output), else route_tasks
def attempt(ctx, index, phase, sel, k, a, call, unit, conns, victims, not_ripped, moves, before, connections) -> tuple
    # (record, after Standing | None, AfterCall parts)
```

The attempt (spec "The order of calls", "The keep or restore test"):

1. `stem = "p%d_%d_rip%d" % (index, k, a)`; `ripped = fresh_output(work / (stem + "_ripped.kicad_pcb"))`;
   `removed = remove_copper(before.board, ripped, set(victims), hist.script_keys)`.
2. The blocked unit at phase i's settings (`phase_settings(ctx, phase, sel, stem + "_b")`), by `reroute_blocked`: a
   `pour` call -> `pour_join.join_pour(ctx_i, ripped, ctx_i.work / (stem + "_b.kicad_pcb"), unit.net, call.width,
   layers_i, stem + "_b", phase_name, common_i)`, its TaskRun with `board` set to that output; any other ->
   `route_tasks(ctx_i, [task_of(c, layers_i) for c in conns], ripped, stem + "_b", layers_i, common_i, phase_name)`. `ctx_i = replace(ctx, clearance_map=..., clearances_file=..., base_clearance=...)` from the
   settings record. Each `TaskRun.calls` entry goes to phase i's calls.
3. For each owner in ascending order: `st = phase_settings(ctx, hist.phases[o], hist.selections[o], "%s_v%d" % (stem, o))`;
   for `j, c` in `enumerate(owner_calls(hist.selections[o], moves_of_o, st))`: `route_tasks(ctx_o, c.tasks, board,
   "%s_v%d_%d" % (stem, o, j), st.layers, st.common, hist.phases[o].name, bus_nets=c.nets if c.kind == "bus_tasks"
   else None)`; add `off_layer(board, run.board, st.layers)`; each record goes to `rerouted` as
   `dict(r, phase=hist.phases[o].name, index=o, asked=<the move's asked>)`; owner o == index: its calls go to phase
   i's calls; owner o < index: `phase_widths(hist.phases[o], calls_o, ctx.cfg)` rows go to the attempt's `widths`.
4. `connections_after`: for o < index, `superseded(superseded(hist.connections[o], hist.moved.get(o, [])),
   rerouted_o)`; for index, `superseded(connections, blocked_records + rerouted_index)`.
   `after = standing(ctx, hist.asked, hist.phases, index, board, stem + "_after", connections_after)`.
5. `blocked_clean`: `judge_obligations(after.copy, conns, after.drc_json, phase_neck(ctx.cfg, phase),
   is_real, phase_input_drc(ctx.work, index))` and `is_clean(j, status)` with each blocked task's record status
   (`records_of(conns, blocked_records)`). `v = verdict(before, after, hist.asked[:index + 1], names, blocked_clean,
   off)`.
6. A `RouterFailed`, `RouteRefused` or `subprocess.TimeoutExpired` in 2-3: no judgement; `kept` False, `reason`
   `router_failed` / `router_refused` / `router_timeout`, `router` = `{"code": e.code, "exit_code": e.exit_code,
   "log": str(e.log)}` (RouterFailed), `{"code": e.code, **e.facts}` (RouteRefused), `{"code": "timeout",
   "seconds": e.timeout}` (TimeoutExpired); the call's `CallRip.stopped` is set.
7. The record, exactly the spec's shape ("What is recorded"): `call`, `attempt`, `blocked` (conns), `named`,
   `victims`, `not_ripped`, `removed`, `rerouted`, `blocked_records`, `kept`, `reason`, `worse` (list),
   `open_rose`, `drc_new`, `off_layer`, `router`, `widths`, `seconds` (rounded to 0.1).

`before` for a call is `standing(ctx, hist.asked, hist.phases, index, board_out, "p%d_%d_rip" % (index, k),
connections_before)`, made once, when the first unit passes the gate; with `connections_before[o] =
superseded(hist.connections[o], hist.moved.get(o, []))` for o < index and `connections` for index. A kept attempt's
`after` becomes `before` for the call's next unit, and its board the call's output.

`blocked_connections`: a task unit's connections as given; they must be pads with widths (`blocked_end_not_pad`,
`blocked_width_unknown` otherwise). A whole-net unit's: `open_connections(before.copy, before.drc_json)` on
`unit.net`, each with phase i's obligation widths for the same pad pair (`_pair_key` match in `hist.asked[index]`)
else `receipt_widths(hist.receipt, phase.name, unit.net)`; none -> `blocked_width_unknown`; an end not a pad ->
`blocked_end_not_pad`; no open connection on the net any more -> `joined_since`. A task unit whose tasks are all
joined on the current board (`joined_pairs`) -> `joined_since`.

`plan_moves`: `asked_moves(victims, hist.asked, index, [[j["joined"] for j in before.judged[o]] for o in
range(index + 1)])`; then `unasked_pairs(victims, hist.input_open, moves, joined_pairs(before.board, <pairs of
hist.input_open>))`; their owners `first_joined(pairs, hist.boards[:index] + [before.board])` (a None owner is
`index`); each unasked pair's widths `receipt_widths(hist.receipt, hist.phases[o].name, net)`, None ->
`victim_width_unknown`. Returns the asked moves then the unasked ones.

- [ ] **Step 1: Failing engine tests** (append to `tests/test_rip_reroute_route.py`):

```python
from placemat.kicad.route import copper_items


@needs_kicad
def test_a_later_phase_moves_an_earlier_phases_copper_and_both_join_clean(toy):
    report = toy.route(A, B)
    a, b = report.phases
    assert [x["kept"] for x in b["rip"]["attempts"]] == [True]
    att = b["rip"]["attempts"][0]
    assert att["victims"] == ["A"] and att["named"] == [{"net": "A", "found_by": "preexisting"}]
    assert att["removed"] == {"tracks": 1, "arcs": 0, "vias": 0, "track_mm": 20.0}
    assert [(r["phase"], r["index"], r["net"], r["status"], r["asked"]) for r in att["rerouted"]] == [
        ("a", 0, "A", "routed", True)]
    assert b["joined"] == 1 and a["final_closure_clean"] == 1.0 and b["final_closure_clean"] == 1.0
    assert a["final_joined"] == 1
    assert ("segment", "A", 0, (105.0, 110.0, 125.0, 110.0)) not in copper_items(report.routed_pcb)


@needs_kicad
def test_an_attempt_that_would_lose_an_earlier_connection_is_restored(toy, monkeypatch, tmp_path):
    monkeypatch.setenv("TOY_DETOUR", "0")                  # A cannot go round B
    report = toy.route(A, B)
    att = report.phases[1]["rip"]["attempts"][0]
    assert (att["kept"], att["reason"]) == (False, "obligation_worse")
    assert att["worse"] == [{"phase": "a", "net": "A", "from": {"ref": "P1", "pad": "1"},
                             "to": {"ref": "P2", "pad": "1"}, "before": "clean", "after": "open"}]
    assert report.phases[0]["final_closure_clean"] == 1.0 and report.phases[1]["joined"] == 0
    work = tmp_path / "route"
    assert copper_items(work / "p1_0.kicad_pcb") == copper_items(work / "router_out.kicad_pcb")


@needs_kicad
def test_a_later_call_of_the_same_phase_moves_the_earlier_calls_copper(toy, monkeypatch):
    from placemat.kicad import net_clearance
    monkeypatch.setattr(net_clearance, "class_clearances", lambda *a, **kw: {"A": 0.3})
    report = toy.route({"name": "signals"})
    (p,) = report.phases
    nets = [c[c.index("--nets") + 1:c.index("--layers")] for c in toy.calls() if "--nets" in c]
    assert nets[:2] == [["A"], ["*", "!A"]]                   # A alone (its clearance), then the rest
    assert len(p["rip"]["attempts"]) == 1
    att = p["rip"]["attempts"][0]
    assert (att["call"], att["kept"], att["rerouted"][0]["phase"]) == (1, True, "signals")
    assert p["final_closure_clean"] == 1.0


@needs_kicad
def test_script_copper_is_never_moved(toy, tmp_path):
    report = toy.route(B, pcb=rip_board(tmp_path, a_track=True))
    rip = report.phases[0]["rip"]
    assert rip["attempts"] == []
    assert rip["skipped"] == [{"call": 0, "net": "B", "named": [{"net": "A", "found_by": "preexisting"}],
                               "not_ripped": [{"net": "A", "reason": "no_router_copper"}], "reason": "no_victim"}]


@needs_kicad
def test_a_moved_connection_keeps_its_own_phases_widths_layers_and_neckdown(toy):
    legs = {"name": "legs", "width": 0.5, "layers": ["F"], "neckdown": False,
            "connections": [{"from": {"part": "P1", "pad": "1"}, "to": {"part": "P2", "pad": "1"}}]}
    report = toy.route(legs, B)
    att = report.phases[1]["rip"]["attempts"][0]
    assert att["kept"] and att["rerouted"][0]["widths"] == {"F.Cu": 0.5}
    moved = [c for c in toy.calls() if "--connections" in c and "rip0_v0" in c[c.index("--connections") + 1]]
    assert moved and moved[0][moved[0].index("--layers") + 1:moved[0].index("--escalation")] == ["F.Cu"]
    assert "--no-power-tap-neckdown" in moved[0]
```

In the same-phase test A's class clearance (0.3) is above the base (0.15), so `clearance_groups` gives A a `nets` call
of its own before the rest call (phase_run.plan_calls), as pic_programmer's VCC.

- [ ] **Step 2: Run** `<TEST> --full tests/test_rip_reroute_route.py` - expected FAIL.

- [ ] **Step 3: Implement** `blocked_connections`, `plan_moves` and `attempt` as above, and in `after_call` replace
Task 10's placeholder: on a unit that passes the gate, build `before` if not yet built, then `blocked_connections`
and `plan_moves` (a reason from either is a skip with that reason), then `attempt`; `rip.made += 1`; append the
record; kept -> `board_out = after.board`, `before = after`, the router-nets map recomputed on the new board, the
unit's net added to the call's laid nets, its blocked records and phase-i reroutes added to `AfterCall.records`, its
phase-i calls to `AfterCall.calls`, victims owned by phase i to `trim`, the attempt's `widths` to `AfterCall.widths`,
and the attempt's summary paths to `AfterCall.summaries`; restored -> `rip.tried.add(frozenset(victims))`, and
`rip.stopped = True` when the reason is in `ROUTER_REASONS`. A unit after a kept attempt reads the new `before`.
- [ ] **Step 4: Run** `<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_board.py tests/test_rip_reroute_route.py tests/test_route_phases.py`
  - expected PASS.
- [ ] **Step 5: Commit** "Rip and reroute: an attempt, kept when nothing judged before is worse", grep.

---

## Task 12: Limits and stops

**Files:**
- Modify: `$WT/src/placemat/kicad/rip_reroute.py` (only if the tests show a gap)
- Test: `$WT/tests/test_rip_reroute_route.py`

- [ ] **Step 1: Failing tests.**

```python
@needs_kicad
def test_a_router_failure_in_an_attempt_restores_and_ends_the_calls_attempts(toy, monkeypatch):
    import placemat.kicad.rip_reroute as rr_mod
    from placemat.kicad.route import RouterFailed

    def broken(*a, **kw):
        raise RouterFailed("stand-in", 3, "/dev/null", "")
    monkeypatch.setattr(rr_mod, "route_tasks", broken)        # rip_reroute imports route_tasks at module level
    report = toy.route(A, B)
    att = report.phases[1]["rip"]["attempts"][0]
    assert (att["kept"], att["reason"], att["router"]["exit_code"]) == (False, "router_failed", 3)
    assert report.phases[1]["joined"] == 0 and report.phases[0]["final_closure_clean"] == 1.0


@needs_kicad
def test_the_net_limit_skips_a_unit_naming_too_many_nets(toy):
    report = toy.route(A, B, settings={"route_rip_max_nets": 0})
    assert report.phases[1]["rip"]["skipped"][0]["reason"] == "too_many_victims"
```

Imports: rip_reroute imports phase_run's names at its top (`from .phase_run import route_tasks, ...`), and
phase_run imports rip_reroute inside `route_calls`; route.py imports it inside functions. So tests can replace
`rip_reroute.route_tasks`. `reroute_blocked` (Task 15) calls `pour_join.join_pour` through the module
(`from . import pour_join`), so tests can replace that too.

- [ ] **Step 2: Run** - expected FAIL until the import and the stop are right. **Step 3:** fix. **Step 4: Run**
`<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_route.py` - PASS.
- [ ] **Step 5: Commit** "Rip and reroute: a failed router call ends a call's attempts", grep.

---

## Task 13: The final judgement and the width rows

**Files:**
- Modify: `$WT/src/placemat/kicad/rip_reroute.py` (`moved_records`, `moved_nets`)
- Modify: `$WT/src/placemat/kicad/route.py:1230-1262` (`recheck_final_phases`), `:1501` (`report.widths`)
- Test: `$WT/tests/test_rip_reroute.py`, `$WT/tests/test_rip_reroute_route.py`

**Interfaces:** Produces

```python
def moved_records(phases, k) -> list        # kept attempts' rerouted records with index == k, from phases after k, in order
def moved_nets(phases) -> set               # {(k, net)} of kept moves owned by an earlier phase k
```

- [ ] **Step 1: Failing tests.** Pure:

```python
def test_the_final_judgement_reads_an_earlier_phases_moved_records():
    moved = {"net": "V", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "1"}, "status": "routed",
             "phase": "legs", "index": 0, "asked": True}
    phases = [{"name": "legs", "rip": {"attempts": [], "skipped": []}},
              {"name": "signals", "rip": {"attempts": [{"kept": True, "rerouted": [moved]},
                                                       {"kept": False, "rerouted": [dict(moved, status="failed")]}],
                                          "skipped": []}}]
    assert rr.moved_records(phases, 0) == [moved] and rr.moved_records(phases, 1) == []
    assert rr.moved_nets(phases) == {(0, "V")}
```

The engine side is Task 11's kept test (`a["final_joined"] == 1` after the move).

- [ ] **Step 2: Run** - FAIL. **Step 3: Implement.** In `recheck_final_phases`:

```python
        from .phase_run import superseded
        from .rip_reroute import moved_records
        connections = superseded(rec.get("connections") or [], moved_records(report.phases, i))
```

and in `_route_board`:

```python
    from .rip_reroute import moved_nets
    gone = moved_nets(records)
    report.widths = [w for j, rec in enumerate(records) for w in rec.get("widths", [])
                     if (j, w.get("net")) not in gone or w.get("stage") != rec["name"]] + read_widths(summaries, judged_width_nets)
```

(The attempt's own rows are in the later phase's `widths` under the owner's stage name, so they stay.)

- [ ] **Step 4: Run** `<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_route.py tests/test_route_phases.py tests/test_phase_widths.py`
  - PASS.
- [ ] **Step 5: Commit** "Rip and reroute: the final judgement reads moved records; width rows follow the copper", grep.

---

## Task 14: The console lines

**Files:**
- Modify: `$WT/src/placemat/kicad/route.py:1576-1625` (`phase_lines`)
- Test: `$WT/tests/test_rip_reroute.py`

- [ ] **Step 1: Failing test** (pure):

```python
def test_the_phase_lines_say_what_was_moved_restored_and_not_tried():
    from placemat.kicad.route import phase_lines
    end = lambda r, p: {"ref": r, "pad": p}
    kept = {"call": 1, "attempt": 0, "kept": True, "reason": None, "victims": ["VCC"],
            "blocked": [{"net": "VCC_PIC", "from": end("JP1", "2"), "to": end("U6", "1")}],
            "rerouted": [{"net": "VCC", "phase": "legs", "index": 0}] * 6, "worse": []}
    lost = {"call": 1, "attempt": 1, "kept": False, "reason": "obligation_worse", "victims": ["V"],
            "blocked": [{"net": "N", "from": end("A", "1"), "to": end("B", "2")}], "rerouted": [],
            "worse": [{"phase": "legs", "net": "V", "from": end("C", "1"), "to": end("D", "2"),
                       "before": "clean", "after": "open"}]}
    skipped = [{"call": 1, "net": "M", "named": [], "not_ripped": [], "reason": "too_many_victims"},
               {"call": 1, "net": "Q", "named": [], "not_ripped": [], "reason": "no_victim"}]
    base = {"selector": "rest", "joined": 1, "asked": 2, "closure_clean": 0.5, "seconds": 3.0, "open": []}
    lines = phase_lines([dict(base, name="legs", rip={"attempts": [], "skipped": []}),
                         dict(base, name="signals", rip={"attempts": [kept, lost], "skipped": skipped})])
    assert lines[0].endswith("; moved by phase signals: VCC")
    assert "; moved earlier copper: VCC_PIC JP1.2-U6.1 joined after moving VCC (legs, 6 connections)" in lines[1]
    assert "; restored: N A.1-B.2 after moving V: V C.1-D.2 would be open" in lines[1]
    assert "; not moved for M: too many nets named" in lines[1] and "Q" not in lines[1].split("not moved")[-1]
```

`moved by` on phase 0's line comes from phase 1's kept attempt, whose records are owned by phase 0 (`index` 0).

- [ ] **Step 2: Run** - FAIL. **Step 3: Implement** in `phase_lines`, after the pour text of each line:

```python
_RESTORED = {"blocked_not_clean": "not joined clean", "net_open_rose": "%s left with more open items",
             "drc_new": "%d new DRC error(s)", "off_layer": "copper off its phase's layers",
             "router_failed": "the router failed", "router_refused": "the router refused a task",
             "router_timeout": "the router timed out"}
_NOT_MOVED = {"too_many_victims": "too many nets named", "limit": "attempt limit", "tried": "same nets restored before",
              "stopped": "an earlier attempt's router call failed", "victim_width_unknown": "a moved connection's width unknown",
              "victim_end_not_pad": "a moved connection's end is no pad", "blocked_width_unknown": "width unknown",
              "blocked_end_not_pad": "an end is no pad", "joined_since": "joined by an earlier attempt"}
```

Each kept attempt: `"; moved earlier copper: %s joined after moving %s (%s, %d connections)"` with the blocked
connections as `NET A.1-B.2` (`_phase_end`), the victims joined by ", ", the owner phases' names joined by ", " and
the count of `rerouted`. Each restored: `"; restored: %s after moving %s: %s"`, the why from `worse[0]` ("NET A-B would
be open" / "would no longer be clean" when `after == "joined"`), `open_rose`'s first net, `drc_new`, or `_RESTORED`.
Each skipped other than `no_victim`: `"; not moved for %s: %s"`. On a phase k's line, the nets moved by later kept
attempts with `index == k`: `"; moved by phase %s: %s"` per later phase. The words are the edge's own; nothing parses
them.

- [ ] **Step 4: Run** `<TEST> --full tests/test_rip_reroute.py tests/test_route_phase_cli.py tests/test_route_command.py`
  - PASS.
- [ ] **Step 5: Commit** "Rip and reroute: the phase lines say what moved", grep.

---

## Task 15: Pour calls and pair calls

**Files:**
- Modify: `$WT/src/placemat/kicad/rip_reroute.py` (only if the tests show a gap)
- Test: `$WT/tests/test_rip_reroute.py`

- [ ] **Step 1: Failing tests.**

```python
def test_a_pour_calls_blocked_net_is_joined_to_its_pour_again(monkeypatch, tmp_path):
    """Step 2 of an attempt after a pour call is join_pour on the ripped board, not a plain task call."""
    import types
    import placemat.kicad.pour_join as pj
    seen = []

    def join_pour(ctx, board, out, net, width, layers, stem, phase, common):
        seen.append((net, stem, width, tuple(layers)))
        return {"net": net}, types.SimpleNamespace(board=out, records=[], summaries=[], calls=[])

    def no_tasks(*a, **kw):
        raise AssertionError("route_tasks called for a pour call")
    monkeypatch.setattr(pj, "join_pour", join_pour)
    monkeypatch.setattr(rr, "route_tasks", no_tasks)
    call = types.SimpleNamespace(kind="pour", width=0.5, nets=("GND",))
    rr.reroute_blocked(types.SimpleNamespace(work=tmp_path), call, rr.Blocked("GND", ()), [],
                       tmp_path / "r.kicad_pcb", types.SimpleNamespace(layers=("F.Cu",), common={}), "p2_0_rip0",
                       "pours")
    assert seen == [("GND", "p2_0_rip0_b", 0.5, ("F.Cu",))]


def test_pair_nets_and_pour_nets_never_move():
    unit = rr.Blocked("N", (rr.Named("D_P", "preexisting"), rr.Named("GND", "static")))
    victims, skipped = rr.victims_of(unit, router_nets={"D_P": 4, "GND": 9}, laid_by_call=set(), pour_nets={"GND"},
                                     pair_nets={"D_P", "D_N"}, excluded=set())
    assert victims == () and [s["reason"] for s in skipped] == ["pair_net", "pour_net"]
```

  These pin `reroute_blocked`'s pour branch (Task 11) and the victim rules for pour and pair nets.

- [ ] **Step 2: Run** - expected PASS if Task 11 followed its interface; a failure here is a fault in Task 11's
`reroute_blocked` or in the import direction (Task 12). **Step 3:** fix any failure with the test first. **Step 4: Run**
`<TEST> --full tests/test_rip_reroute.py tests/test_rip_reroute_route.py tests/test_route_pour_phases.py tests/test_pour_join.py`
  - PASS.
- [ ] **Step 5: Commit** "Tests: rip and reroute after a pour call, and pour and pair nets never move", grep.

---

## Task 16: Docs

**Files:**
- Modify: `$WT/skills/placemat/references/api.md` ("Routing phases", after the clearance paragraph at :3986-3990)
- Modify: `$WT/skills/placemat/references/migration.md` (Unreleased, New)
- Modify: `$WT/docs/superpowers/specs/2026-10-06-routing-phases-design.md` ("Goal" :22-25, "Running" :227)
- Modify: `$WT/docs/superpowers/plans/2026-10-07-routing-phases.md` ("Decisions": D32 after D31)

Project-agnostic: no board, part or net of a project in api.md or migration.md.

- [ ] **Step 1: api.md**, a paragraph in "Routing phases":

```markdown
A call's copper is locked for the router in every later call. When a later call leaves a connection open and the
router names another net's routed copper as blocking it, placemat may move that copper: it takes the net's routed
copper off (never copper the script declares, a pour net's or a pair's), routes the blocked connection, then routes
the moved net's connections again as pad-to-pad tasks, each at the width, layers, clearance and router flags of the
phase that asked it. It keeps the result only when the blocked connection joins clean and no connection of the
phases so far is worse, no net has more open items and the DRC has no new error; otherwise the board is as the call
left it. `[route] rip_attempts` (4 per call; 0 is off) and `[route] rip_max_nets` (3) bound it. Each phase's record
in route.json lists its attempts (`rip`), and its line says what moved, what was restored and why.
```

- [ ] **Step 2: migration.md**, under Unreleased "New":

```markdown
- **Routing phases.** A later router call may move an earlier call's routed copper that blocks a connection it left
  open, routing the moved connections again at their own phase's widths, layers and clearance, and keeping the
  result only when nothing judged before is worse. On by default; `[route] rip_attempts = 0` turns it off. Nothing
  in a script changes.
```

- [ ] **Step 3: The routing-phases spec**: "Goal" gains, after "its copper is fixed for the phases after it": "for
the router; placemat may move it when it blocks a later call
(docs/superpowers/specs/2026-10-12-rip-reroute-design.md)". "Running", the lock bullet: "A call's copper is locked
(`lock_copper`) before the next call runs; rip and reroute may move it (the 2026-10-12 spec)."

- [ ] **Step 4: The routing-phases plan**, Decisions:

```markdown
- D32 A later router call may rip copper an earlier call laid, in the same phase or an earlier phase, when that copper
  blocks a connection it leaves open. placemat removes the copper, reroutes the blocked connection, then reroutes the
  removed connections as `--connections` tasks at their own phases' settings, and keeps the result only when nothing
  judged before is worse; no router change. Earlier calls' copper is moved, never dropped; script copper is never
  ripped. User, 2026-10-12. Spec docs/superpowers/specs/2026-10-12-rip-reroute-design.md, plan
  docs/superpowers/plans/2026-10-12-rip-reroute.md. Alt: the router rips named nets itself (the research's options A
  and C).
```

- [ ] **Step 5: Run** `<TEST> --full tests/test_settings_docs.py` (the api table still matches) - PASS.
- [ ] **Step 6: Commit** "Docs: rip and reroute in the skill reference, the migration notes and the routing-phases
documents", grep.

---

## Task 17: The full suite

**Files:** whatever the suite shows broken.

- [ ] **Step 1:** `df -h /tmp ~`, then `<TEST> --full -n 2` once. Record the counts and every failure in the ledger,
with the load average.
- [ ] **Step 2:** Sort failures: caused by this branch (fix each with a failing test first, then rerun only that
file), or known before the branch (test_version against the installed package; two test_studio_builder tests, as
listed in usbc-starvation-report.md). A failure that is neither goes to the user.
- [ ] **Step 3:** After fixes, rerun the files that failed, not the suite. Commit each fix on its own, grep.

---

## Task 18: pic_programmer (b) and usb-c-power-adapter (b) at a fixed placement

**Files:** none committed; results go to the user (D28's rule: a gate's numbers go to the user, results.json is not
updated without them).

- [ ] **Step 1:** `df -h /tmp ~`; KRT commit; `uptime`.
- [ ] **Step 2: The runners.** Run place_ref for each board at the branch head, as Task 1 step 2, into
`<scratch>/rip-head/<board>`, no `--update`. Keep each printed line and its verdict against results.json.
- [ ] **Step 3: The placement is the same.** Compare each head run's `route/in.kicad_pcb` with Task 1's: every
footprint's reference, position, rotation and side (`placemat.kicad.read.read_board(...).footprints`, compared to
1 um). Placement code is untouched by this branch, so they should match. If they differ, say so and use Step 4's
numbers as the like-for-like ones.
- [ ] **Step 4: The fixed placement.** Route Task 1's two fixed placements at the head, as Task 1 step 3, into
`<scratch>/rip-head/<board>-fixed`.
- [ ] **Step 5: Report** to the user, for each board, Task 1's numbers beside Step 2's and Step 4's:
  - the runner's line and verdict against results.json (closure_clean, open, new DRC, vias, track mm, seconds);
  - from route.json: each phase's `joined`/`asked` and `final_closure_clean`, `widths_failed`, `drc_new`;
  - each phase's `rip`: attempts kept and restored with reasons, victims, connections moved, skipped units with
    reasons, seconds spent in attempts;
  - pic_programmer: whether VCC_PIC JP1.2-U6.1 joins clean, and whether VCC's copper stays 0.8 mm on F.Cu/B.Cu
    (its obligations' `final_*`, and the board's VCC tracks);
  - usb-c-power-adapter: which open connections of the signals phase had blocker evidence naming other copper
    (`net_evidence`, `blockers`, task records) and which did not; for each that did not, whether the router named the
    net only in its prose (the log's "PROTECTED net(s) ... within 3mm" sentence), per C14;
  - the load average for every timing.
- [ ] **Step 6:** Write the same into the ledger. Nothing is committed and results.json is not updated in this task;
the user decides whether the new results are recorded.
