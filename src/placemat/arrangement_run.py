"""The module run's side of arrangements: the board prepared once its script has declared everything, each arrangement
resolved from a snapshot of the declarations and proven on a scratch board of its own, the record of them all, and the notes
that carry the offered ones in the fragment."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import shutil
import time

from . import arrangement_note as note, checks, reuse as reuse_mod, score as score_mod
from .arrangements import Spec
from .copper import Text
from .layout import _RowSlot
from .findings import Finding, FindingCause as C


@dataclass
class Prepared:
    board: object
    saved: tuple                # Board._snapshot() once the declarations are finished, before any arrangement is laid
    specs: tuple                # arrangements.Spec, the default first
    rows: list = field(default_factory=list)    # _row_state then


def _row_state(board) -> list:
    """Each row whose start waits on what it is anchored to, with its fields: a resolve fixes the start on the Row itself (a
    PlaceIntent holds it through a _RowSlot), which `Board._snapshot` does not copy. Left begun, the next arrangement's rows
    would stand where the last resolve put them, and its reuse context would differ from a run that never began them."""
    rows, todo = {}, [i.along.row for i in board._intents if isinstance(getattr(i, "along", None), _RowSlot)]
    while todo:
        row = todo.pop()
        if id(row) in rows:
            continue
        rows[id(row)] = row
        if row.anchor is not None and row.anchor[0] in ("before", "after"):
            todo.append(row.anchor[1])
    return [(row, dict(row.__dict__)) for row in rows.values()]


def _put_rows(state) -> None:
    for row, fields in state:
        row.__dict__.clear()
        row.__dict__.update(fields)


def begin(board) -> Prepared:
    """The board as its script left it, checked and snapshotted, with the arrangements its declarations make."""
    board.finish_declarations()
    return Prepared(board, board._snapshot(), board.arrangement_specs(), _row_state(board))


def resolve_spec(prepared: Prepared, spec: Spec, *, reuse=None, lock=(), routes=None, partial=None):
    """One arrangement's Plan: the declarations put back, `spec` laid over them, and the resolve the default gets. Not
    reported to a studio: the module run's own plan is the default's. The board is left as it was found, the arrangement
    it was laid as included, whether the resolve returns or raises."""
    board = prepared.board
    found, found_rows = board._snapshot(), _row_state(board)
    try:
        board._restore(prepared.saved)
        _put_rows(prepared.rows)
        board.lay_arrangement(spec)
        return board._resolve(None, reuse, None, lock, routes, None, None, partial)
    finally:
        board._restore(found)
        _put_rows(found_rows)


def signature(plan) -> str:
    """A digest of where the plan put every item and the copper it planned: two arrangements with one signature are one."""
    h = hashlib.sha256()
    for s in plan.steps:
        h.update(repr((s.item, s.kind, s.placement)).encode())
    for op in plan.copper:
        h.update(repr(op).encode())
    return h.hexdigest()[:16]


_SIDE_EDGE = (("north", lambda b: b.top, min), ("east", lambda b: b.right, max),
              ("south", lambda b: b.bottom, max), ("west", lambda b: b.left, min))
_TOL = 1e-6


def extent_from_boxes(boxes: dict) -> list:
    """The members whose box reaches the outline round all of them on a side, with how far each stands past the next member's
    edge on that side (the most over its sides). Most protruding first, then by name."""
    out: dict = {}
    for side, edge, pick in _SIDE_EDGE:
        values = sorted(((edge(b), n) for n, b in boxes.items()), key=lambda t: (t[0] if pick is min else -t[0], t[1]))
        if not values:
            continue
        best = values[0][0]
        others = [w for w, _ in values if abs(w - best) > _TOL]
        gap = abs(best - others[0]) if others else 0.0
        for v, n in values:
            if abs(v - best) > _TOL:
                break
            sides_of, was = out.get(n, ([], 0.0))
            out[n] = (sides_of + [side], max(was, gap))
    order = [s for s, _, _ in _SIDE_EDGE]
    rows = [{"item": n, "sides": sorted(s, key=order.index), "protrudes_mm": round(g, 6)} for n, (s, g) in out.items()]
    return sorted(rows, key=lambda r: (-r["protrudes_mm"], r["item"]))


def extent_of(plan) -> list:
    """`extent_from_boxes` of a resolved plan's placed members, as the placer claims them (`report.claimed_boxes`)."""
    from .report import claimed_boxes
    return extent_from_boxes(claimed_boxes(plan))


def extent_findings(board, extent: list, threshold_mm: float) -> list:
    """`arrangement.extent_fixed` for each extent member with no alternative: on a module that declares any, every one; on one
    that declares none, those standing past the next member by more than `threshold_mm` (`place.extent_notice_mm`)."""
    declares = bool(board._options or board._arr_groups)
    moved = set(board._options) | {o.item for g in board._arr_groups for o in g.options}
    out = []
    for row in extent:
        if row["item"] in moved or (not declares and row["protrudes_mm"] <= threshold_mm):
            continue
        out.append(Finding(C.ARRANGEMENT_EXTENT_FIXED, dict(row, alternatives=declares), "notice"))
    return out


@dataclass
class Proof:
    offered: bool
    refused: list               # records (finding_text.refusal_record_text reads them)
    metrics: dict               # {"drc": int | None, "findings": {severity: n}, "measures": {...}}


def plan_refusals(plan, default_plan) -> list:
    """What the resolve itself says against an arrangement: an item with no place, a critical finding, and a cell standing
    elsewhere than in the default (a module's nested cells are placed once, by the default: an arrangement that needs one moved is
    not offered)."""
    from . import finding_text
    from .findings import FindingKind
    out = []
    for s in plan.steps:
        if s.kind in ("part", "cell", "block") and s.placement is None:
            out.append({"form": "unplaced", "item": s.item})
    unplaced = {r["item"] for r in out}
    for f in plan.findings:
        if f.severity == "critical":
            subject = finding_text.subject(f.cause, f.facts) or ""
            if f.cause.kind is FindingKind.UNPLACED and subject in unplaced:
                continue            # the unplaced record already says it
            out.append({"form": "finding", "cause": f.cause.value, "item": subject})
    was = {s.item: s.placement for s in default_plan.steps if s.placement is not None}
    for s in plan.steps:
        if s.kind == "cell" and s.placement is not None and was.get(s.item) not in (None, s.placement):
            out.append({"form": "nested_cell", "item": s.item})
    return out


def drc_refusals(report, default_unconnected: int) -> list:
    out = [{"form": "drc", "bucket": b, "count": n} for b, n in sorted(report.real.items())]
    if report.unconnected > default_unconnected:
        out.append({"form": "unconnected", "count": report.unconnected, "default": default_unconnected})
    return out


def verdict_refusals(verdicts) -> list:
    return [{"form": "verdict", "check": v.check, "item": v.subject} for v in verdicts if v.ok is False and not v.accepted]


@dataclass
class Resolved:
    spec: Spec
    plan: object | None         # None: a duplicate (`duplicate_of`) or a resolve that raised (`refused`)
    duplicate_of: str = ""
    seconds: float = 0.0
    refused: list = field(default_factory=list)     # refusal records of a resolve that raised (plan_refusals' forms)


@dataclass
class Outcome:
    record: list                # RunRecord.arrangements: one entry per arrangement, the default first
    findings: list
    texts: list                 # the note texts of the offered arrangements, for the fragment


def _dir(run_dir, ident) -> Path:
    return Path(run_dir) / "arrangements" / ident


def read_previous(last_run_dir) -> dict:
    """The reuse record each arrangement of an earlier run kept, by id."""
    out = {}
    for p in sorted((Path(last_run_dir) / "arrangements").glob("*/reuse.json")):
        try:
            out[p.parent.name] = reuse_mod.read(p)
        except (ValueError, OSError):
            pass
    return out


def read_died(final_dir) -> dict:
    """What a stopped or crashed run of these very inputs left of each arrangement (read before its folder is replaced): the record
    it finished, or the steps of its partial log, whichever replays more."""
    out = {}
    for d in sorted(p for p in (Path(final_dir) / "arrangements").glob("*") if p.is_dir()):
        try:
            done = reuse_mod.read(d / "reuse.json") if (d / "reuse.json").exists() else None
        except (ValueError, OSError):
            done = None
        got = reuse_mod.better_of(done, reuse_mod.read_partial(d / "reuse.partial.jsonl"))
        if got is not None:
            out[d.name] = got
    return out


def _raised_refusals(e) -> list:
    """The refusal records of a resolve or a proof that raised: a required item with no place, firm items that collide, an
    escape that cannot be laid out, or any other error (its type and message)."""
    from . import finding_text
    from .lanes import EscapeError
    from .layout import CriticalUnplaced, PlacementCollision
    if isinstance(e, CriticalUnplaced):
        return [{"form": "unplaced", "item": e.key}]
    if isinstance(e, PlacementCollision):
        return [{"form": "finding", "cause": f.cause.value, "item": finding_text.subject(f.cause, f.facts) or ""}
                for f in e.collisions]
    if isinstance(e, EscapeError):
        return [{"form": "escape", "escape": e.escape, "part": e.part}]
    return [{"form": "error", "type": type(e).__name__, "message": str(e)}]


def _keep_partial(d, partial, parts) -> None:
    """An arrangement whose resolve raised: the steps it completed become its record (reuse.json, as a finished one's), so the
    next run replays them as far as they hold, and no partial log is left as if it were still running."""
    got = reuse_mod.read_partial(d / "reuse.partial.jsonl")
    partial.remove()
    if got is not None:
        reuse_mod.write(d / "reuse.json", dict(got, reused=0, first_change=None, parts=parts))


def resolve_others(prepared, default_plan, run_dir, previous, died, lock, routes, on_begin) -> list:
    """Each arrangement after the default, resolved from the snapshot, in declared order (`on_begin` is called with its id
    first). One that lays out exactly as an earlier one is dropped (its plan is not kept) and named by `duplicate_of`; one whose
    resolve raises (a required item with no place, firm items that collide, an escape that cannot be laid out, any other error)
    is kept with its refusals, and the rest go on; a stop (stop.Stopped, a BaseException) ends the run, its partial log kept. Each keeps its steps' record in its own folder, so a stopped run resumes it without laying
    finished arrangements again. The board is left as the default's resolve left it."""
    out, seen = [], {signature(default_plan): "default"}
    for spec in prepared.specs[1:]:
        d = _dir(run_dir, spec.id)
        d.mkdir(parents=True, exist_ok=True)
        before = previous.get(spec.id)
        if spec.id in died and reuse_mod.better_of(before, died[spec.id]) is died[spec.id]:
            before = died[spec.id]
        partial = reuse_mod.PartialLog(d / "reuse.partial.jsonl")
        t0 = time.monotonic()
        on_begin(spec.id)
        try:
            plan = resolve_spec(prepared, spec, reuse=before, lock=lock, routes=routes, partial=partial)
        except Exception as e:
            _keep_partial(d, partial, default_plan.reuse.get("parts", {}))
            out.append(Resolved(spec, None, "", time.monotonic() - t0, _raised_refusals(e)))
            continue
        plan.reuse["parts"] = default_plan.reuse.get("parts", {})
        reuse_mod.write(d / "reuse.json", plan.reuse)
        partial.remove()
        sig = signature(plan)
        if sig in seen:
            out.append(Resolved(spec, None, seen[sig], time.monotonic() - t0))
            continue
        seen[sig] = spec.id
        out.append(Resolved(spec, plan, "", time.monotonic() - t0))
    return out


def scratch_board(generated_pcb, arr_dir) -> Path:
    """arr_dir/layout.kicad_pcb with its project and rules beside it, from the board `pcb layout` generated (the cached generation):
    the plan is written on it without touching the fragment the run writes."""
    generated_pcb, arr_dir = Path(generated_pcb), Path(arr_dir)
    arr_dir.mkdir(parents=True, exist_ok=True)
    for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru"):
        src = generated_pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, arr_dir / ("layout" + ext))
    return arr_dir / "layout.kicad_pcb"


def prove(prepared, resolved, default_plan, *, generated, cfg, fab, arr_dir, default_unconnected: int, drc: bool = True) -> Proof:
    """The judgement the default gets, on this arrangement's own board: its resolve places every member with no critical finding;
    the plan written to a scratch board passes KiCad's DRC (the `real` buckets empty, no more unconnected than the default); the
    design checks run on it (no failed verdict, `board.accept` applied). Warnings, notices and measures are recorded, not refused.
    The board is written whatever the resolve says, to be looked at; one the resolve refuses is not judged further."""
    from .kicad.drc import run_drc
    from .kicad.read import read_board
    from .kicad.write import apply_plan, finish_board
    plan, board = resolved.plan, prepared.board
    refused = plan_refusals(plan, default_plan)
    metrics = {"drc": None, "findings": plan.findings.by_severity(), "measures": score_mod.plan_measures(board, plan)}
    pcb = scratch_board(generated, arr_dir)
    apply_plan(pcb, plan)
    finish_board(pcb, fab, refs_to_fab=getattr(board, "refs_on_fab", True))
    if refused:
        return Proof(False, refused, metrics)
    if drc:
        allow = {"keepout %s" % k.name: (set(k.owners), set(k.allow)) for k in plan.keepouts.values()}
        report = run_drc(pcb, Path(arr_dir) / "drc.json", allow=allow, frame_only=not plan.draw_outline)
        refused += drc_refusals(report, default_unconnected)
        metrics["drc"] = sum(report.real.values())
        metrics["measures"]["drc"] = metrics["drc"]
    verdicts, _ = checks.judge(checks.run_checks(read_board(pcb), **checks.kwargs_from(cfg)), plan.acceptances)
    refused += verdict_refusals(verdicts)
    return Proof(not refused, refused, metrics)


def members_doc(prepared, plan, default_plan, spec, texts_chars: int) -> list:
    """The note texts of an offered arrangement: arrangement_note.encode of `members_document`. Raises
    arrangement_note.NoteError when `texts_chars` leaves no room for a chunk."""
    return note.encode(members_document(prepared, plan, default_plan, spec), texts_chars)


def members_document(prepared, plan, default_plan, spec) -> dict:
    """The note's document of an offered arrangement: every loose member's place in the fragment's frame, the copper this
    arrangement planned (the faces text is the default's), and the rule areas it declares."""
    geometry = prepared.board.geometry
    members = []
    for fp in geometry.footprints:
        if fp.cell is None and fp.ref in plan.occupancy.items and fp.ref in default_plan.occupancy.items:
            members.append((fp.inst, plan.occupancy.items[fp.ref].reference, default_plan.occupancy.items[fp.ref].reference))
    ops = [op for op in plan.copper if not (isinstance(op, Text) and op.layer == "User.Comments")]
    return note.document(spec.id, spec.choices, members, ops, list(plan.keepouts.values()),
                         order=[s.id for s in prepared.specs].index(spec.id))


def finish(prepared, default_plan, resolved, *, src, cfg, fab, run_dir, default_report, board, drc: bool = True,
           render: bool = False) -> Outcome:
    """After the default's own DRC and checks: prove each other arrangement, build the record, the findings, and the texts that carry
    the offered ones. A proof that raises refuses its arrangement (an `error` refusal) and the rest go on. With `render`, each
    proven arrangement's board is rendered in its folder, as the default's is. The default is copied into its own folder beside
    the others'."""
    from .runner import cached_generation
    generated = cached_generation(src) / src.pcb.name
    default_unconnected = default_report.unconnected if default_report is not None else 0
    default_drc = sum(default_report.real.values()) if default_report is not None else None
    measures = score_mod.plan_measures(board, default_plan)
    if default_drc is not None:
        measures["drc"] = default_drc
    record = [{"id": "default", "choices": {}, "offered": True, "dir": "arrangements/default",
               "metrics": {"drc": default_drc, "findings": default_plan.findings.by_severity(), "measures": measures},
               "extent": extent_of(default_plan)}]
    findings, texts = [], []
    for r in resolved:
        spec = r.spec
        entry = {"id": spec.id, "choices": spec.choices, "dir": "arrangements/" + spec.id}
        record.append(entry)
        if r.duplicate_of:
            entry.update(offered=False, duplicate_of=r.duplicate_of, metrics=None)
            findings.append(Finding(C.ARRANGEMENT_DUPLICATE, {"id": spec.id, "same_as": r.duplicate_of}, "notice"))
            continue
        if r.plan is None:                      # its resolve raised
            entry.update(offered=False, metrics=None, refused=r.refused)
            findings.append(Finding(C.ARRANGEMENT_REFUSED, {"id": spec.id, "refused": r.refused}, "warning"))
            continue
        arr_dir = _dir(run_dir, spec.id)
        try:
            proof = prove(prepared, r, default_plan, generated=generated, cfg=cfg, fab=fab, arr_dir=arr_dir,
                          default_unconnected=default_unconnected, drc=drc)
            if render:
                from .kicad.write import render_board
                render_board(arr_dir / "layout.kicad_pcb", arr_dir / "render.log", both_faces=getattr(board, "both_faces", False))
        except Exception as e:
            proof = Proof(False, _raised_refusals(e), None)
        entry.update(offered=proof.offered, metrics=proof.metrics, extent=extent_of(r.plan))
        refused = proof.refused
        if proof.offered:
            doc = members_document(prepared, r.plan, default_plan, spec)
            try:
                texts += note.encode(doc, cfg.place_arrangement_note_chars)
            except note.NoteError:
                refused = [{"form": "note_chars", "chars": cfg.place_arrangement_note_chars}]
                entry["offered"] = False
        if refused:
            entry["refused"] = refused
            findings.append(Finding(C.ARRANGEMENT_REFUSED, {"id": spec.id, "refused": refused}, "warning"))
    d = _dir(run_dir, "default")
    d.mkdir(parents=True, exist_ok=True)
    for name in ("layout.kicad_pcb", "layout.kicad_pro", "layout.kicad_dru", "drc.json", "reuse.json"):
        if (Path(run_dir) / name).exists():
            shutil.copy(Path(run_dir) / name, d / name)
    return Outcome(record, findings, texts)


def lines(record: list) -> list:
    """One row per arrangement of the record, for the console (finding_text.arrangement_row_text): its id and `state`, written (the
    default), offered, duplicate (with `same_as`) or refused (with `refused`)."""
    out = []
    for a in record:
        if a.get("duplicate_of"):
            out.append({"id": a["id"], "state": "duplicate", "same_as": a["duplicate_of"]})
        elif a["offered"]:
            out.append({"id": a["id"], "state": "written" if a["id"] == "default" else "offered"})
        else:
            out.append({"id": a["id"], "state": "refused", "refused": a.get("refused", [])})
    return out
