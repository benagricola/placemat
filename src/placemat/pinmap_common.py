"""Detached physical pin finalists, judged against one original layout intent."""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace

from placemat import score
from placemat.values import Face, Location, PadRef, CellPadRef

_CACHE_KEYS = ('_placed_groups', '_placed_groups_owners', '_escapes', '_ratsnest',
               '_rn_anchors', '_congestion', '_congestion_pads')


def detached(occ):
    """Own mutable containers; source geometry records stay immutable."""
    out = copy.copy(occ)
    for key, value in vars(occ).items():
        if isinstance(value, dict):
            out.__dict__[key] = {k: list(v) if isinstance(v, list) else v for k, v in value.items()}
        elif isinstance(value, list):
            out.__dict__[key] = list(value)
        elif isinstance(value, set):
            out.__dict__[key] = set(value)
    for key in _CACHE_KEYS:
        out.__dict__.pop(key, None)
    out._native_obstacle_cache = {}
    out._pad_location_cache = {}
    out._cells = {}
    return out


def mapped_geometry(occ, assignment):
    """A physical pin identity maps every land of that pin together."""
    if len({fp.ref for fp in occ.geometry.footprints}) != len(occ.geometry.footprints):
        raise CandidateRefused('pin finalist source has ambiguous footprint references')
    footprints = tuple(replace(fp, pads=tuple(replace(pad, net=assignment.get((fp.ref, pad.number), pad.net))
                                               for pad in fp.pads)) for fp in occ.geometry.footprints)
    by_ref = {fp.ref: fp for fp in footprints}
    cells = {name: replace(cell, members=tuple(by_ref[fp.ref] for fp in cell.members))
             for name, cell in occ.geometry.cells.items()}
    geom = replace(occ.geometry, footprints=footprints, cells=cells, _by_ref={}, _by_inst={})
    out = detached(occ)
    out.geometry = geom
    def remap(item):
        shapes = tuple(replace(shape, net=assignment.get((shape.owner, shape.label), shape.net))
                       if shape.kind in ('pad', 'through') else shape for shape in item.shapes)
        return replace(item, shapes=shapes, nets=frozenset(shape.net for shape in shapes if shape.net))
    out.items = {ref: remap(item) for ref, item in occ.items.items()}
    out._pristine = {ref: remap(item) for ref, item in occ._pristine.items()}
    out._tie_nets = frozenset(p.net for fp in footprints if fp.net_tie_pads for p in fp.pads if p.net)
    # Fixed current copper, including carried-via metadata, retains its nets.
    return out


class CandidateRefused(ValueError):
    """A candidate does not preserve this exact declared intent context."""


def _net_at(geom, endpoint):
    ref, number = endpoint
    nets = {pad.net for fp in geom.footprints if fp.ref == ref for pad in fp.pads if pad.number == number}
    if len(nets) != 1:
        raise CandidateRefused("pin finalist endpoint is missing or has ambiguous pad nets")
    return next(iter(nets))


def _fixed_copper(occ):
    """Electrical copper, excluding movable area reservations and silk."""
    fixed = [('board', shape) for shape in occ.copper if shape.kind not in ('viaban', 'silk')]
    for ref, item in sorted(occ.items.items()):
        fixed.extend((ref, shape) for shape in item.shapes
                     if shape.kind == 'copper' or shape.carried or shape.given
                     or (shape.kind == 'through' and not shape.label))
    return tuple(fixed)


@dataclass(frozen=True)
class Evaluation:
    terms: dict
    validity: score.Validity
    total: float
    reasons: tuple = ()
    occupancy: object = field(default=None, repr=False, compare=False)

    @property
    def key(self):
        return self.validity.key(), self.total


@dataclass(frozen=True)
class Selection:
    baseline: Evaluation
    finalists: tuple[Evaluation, ...]
    best: int
    gain: float
    reason: str
    actionable: bool


class Finalists:
    """One baseline and full-board judgments; callers never sum group gains.

    This placement context cannot certify routed phase-contract equivalence.
    Every context is rebuilt from the current plan rather than cached findings.
    """
    def __init__(self, board, plan, settings=None):
        self.board, self.plan = board, plan
        self.settings = settings or board.settings

    def select(self, inp, group):
        """Rank this group's finalists, retaining the current board on ties.

        Electrical/read uncertainty withholds an executable recommendation.
        Each selection is independent; combined adoption needs another full
        evaluate call with every chosen map and pose together.
        """
        baseline = self.evaluate(inp)
        finals = tuple(self.evaluate(inp, ((group.refs, candidate),)) for candidate in group.results)
        if not finals:
            return Selection(baseline, (), 0, 0.0, 'no finalist', False)
        best = min(range(len(finals)), key=lambda index: finals[index].key)
        chosen = finals[best]
        gain = baseline.total - chosen.total if math.isfinite(baseline.total) and math.isfinite(chosen.total) else 0.0
        if baseline.reasons or chosen.reasons or chosen.validity.unmeasured:
            return Selection(baseline, finals, best, gain, 'unmeasured candidate', False)
        if chosen.validity.key() < baseline.validity.key():
            return Selection(baseline, finals, best, gain, 'validity repair', True)
        actionable = (chosen.validity.key() == baseline.validity.key()
                      and gain > 1e-9 and gain >= self.settings.pins_gain_min * baseline.total)
        return Selection(baseline, finals, best, gain,
                         'common objective gain' if actionable else 'no common improvement', actionable)

    def _assignment(self, inp, refs, assign, *, present=False):
        out = {}
        if not set(refs) <= {part.ref for part in inp.parts}:
            raise CandidateRefused('pin finalist names an unrelated studied part')
        original = {net.net: tuple(net.ends) for net in inp.nets}
        movable = {(ref, net) for ref in refs for net in inp.part(ref).slots.movable}
        for net, ends in assign.items():
            if net not in original:
                raise CandidateRefused('pin finalist introduces an unrelated logical net')
            kept = tuple(end for end in ends if (end[0], net) not in movable)
            expected = tuple(end for end in original[net] if (end[0], net) not in movable)
            if sorted(kept) != sorted(expected):
                raise CandidateRefused('pin finalist changes a held or unrelated logical terminal')
        for ref in refs:
            part = inp.part(ref)
            used = set()
            actual = {}
            for net in part.slots.movable:
                ends = [number for owner, number in assign.get(net, ()) if owner == ref]
                if len(ends) != 1:
                    raise CandidateRefused('pin finalist changes a logical terminal multiplicity')
                number = ends[0]
                if number in used or (not present and number not in part.slots.allowed[net]):
                    raise CandidateRefused('pin finalist is not a legal declared PinPool permutation')
                used.add(number)
                actual[net] = number
                pin = next(pin for pin in part.pins if pin.number == part.slots.present[net])
                out[pin.key(ref)] = ''
            for net, number in actual.items():
                pin = next(pin for pin in part.pins if pin.number == number)
                out[pin.key(ref)] = net
            if not present:
                for name, nets in part.slots.groups:
                    if not any(all(not net or actual.get(net) == number for net, number in zip(nets, window))
                               for window in part.slots.windows[name]):
                        raise CandidateRefused('pin finalist breaks a declared hard pin group')
        return out

    def _pose(self, occ, item, part, turn, flip):
        """Preserve the exact study pivot with the occupancy's own affine."""
        geom = occ._geometry(item)
        base = geom.reference
        rotation = (turn - base.rotation) if flip else base.rotation + turn
        face = (Face.BACK if base.face is Face.FRONT else Face.FRONT) if flip else base.face
        trial = replace(base, rotation=rotation, face=face)
        pivot = Location(part.cx, part.cy)
        moved = occ._transform(geom, trial).apply_location(pivot)
        return replace(trial, location=Location(trial.location.x + pivot.x - moved.x,
                                                trial.location.y + pivot.y - moved.y))

    def _links(self, board, occ, plan):
        links = []
        for link in self.plan.links:
            endpoints = []
            for old, selector in ((link.a, link.a_ref), (link.b, link.b_ref)):
                logical = ((isinstance(selector, PadRef) and isinstance(selector.key, str) and selector.pin is None)
                           or (isinstance(selector, CellPadRef) and selector.net is not None))
                endpoint = board._pad_ref(selector)[:2] if logical else old
                original = _net_at(self.plan.occupancy.geometry, old)
                current = _net_at(occ.geometry, endpoint)
                if current != original:
                    raise CandidateRefused('pin finalist changes an explicit fixed pad link obligation')
                endpoints.append(endpoint)
            links.append(replace(link, a=endpoints[0], b=endpoints[1]))
        plan.links = links

    def evaluate(self, inp, groups=(), *, present=False):
        """Return common terms and placement validity, or a precise refusal.

        groups is ((refs, PoseResult), ...); simultaneous physical poses must
        agree when two linked studies name the same cell.
        """
        from placemat.settings import bind
        with bind(self.settings):
            return self._evaluate(inp, groups, present=present)

    def _evaluate(self, inp, groups, *, present):
        try:
            # These settings determined the source's physical shapes or its
            # cached legality policy. Price and live escape settings may change,
            # but rebuilding an alternate placement envelope needs a new plan.
            frozen = ('place_envelope', 'place_conflict_reach', 'place_courtyard_touch',
                      'place_silk_margin', 'place_drc_epsilon', 'place_courtyard_polygon_share',
                      'place_via_route_distance', 'drc_severities')
            if any(getattr(self.settings, key) != getattr(self.plan.occupancy.settings, key)
                   for key in frozen):
                raise CandidateRefused('pin finalist requires a fresh plan for changed physical placement settings')
            assignments, poses = {}, {}
            for refs, group in groups:
                mapping = self._assignment(inp, refs, group.assign, present=present)
                for key, net in mapping.items():
                    if key in assignments and assignments[key] != net:
                        raise CandidateRefused('combined pin finalists disagree on a physical pad net')
                    assignments[key] = net
                for ref, turn, flip in group.poses:
                    if ref not in refs:
                        raise CandidateRefused('pin finalist changes an unrelated item pose')
                    part = inp.part(ref)
                    from placemat.pinmap_core import poses_of
                    if (turn, flip) not in poses_of(part, self.settings):
                        raise CandidateRefused('pin finalist pose is outside the declared study choices')
                    owner = part.cell or ref
                    proposal = (turn, flip)
                    if owner in poses and poses[owner][0] != proposal:
                        raise CandidateRefused('combined pin finalists require conflicting poses of one item')
                    poses[owner] = proposal, part
            for (ref, number), net in assignments.items():
                pads = [pad for fp in self.plan.occupancy.geometry.footprints if fp.ref == ref
                        for pad in fp.pads if pad.number == number]
                if not pads:
                    raise CandidateRefused('pin finalist names a missing physical pad')
                if any(pad.no_connect and net and net != pad.net for pad in pads):
                    raise CandidateRefused('pin finalist requires unsupported no-connect intent reassignment')
            occ = mapped_geometry(self.plan.occupancy, assignments)
            occ.settings = self.settings
            board = copy.copy(self.board)
            board.geometry, board.settings = occ.geometry, self.settings
            candidate_plan = copy.copy(self.plan)
            candidate_plan.geometry, candidate_plan.occupancy = occ.geometry, occ
            for owner, ((turn, flip), part) in poses.items():
                if turn % 360 == 0 and not flip:
                    continue
                item = occ.geometry.cells[owner] if part.cell else occ.geometry.footprint(owner)
                pose = self._pose(occ, item, part, turn, flip)
                intent = next((i for i in board._placements() if i.key == (part.cell or item.inst)), None)
                if intent is not None:
                    step = next((step for step in self.plan.steps if step.item == intent.key), None)
                    if board._turn_held_by(intent, step, intent.freedom.decided):
                        raise CandidateRefused('pin finalist changes a held placement turn')
                    base = occ._geometry(item).reference
                    dx, dy = pose.location.x - base.location.x, pose.location.y - base.location.y
                    if (intent.at is not None and (abs(dx) > 1e-9 or abs(dy) > 1e-9)) or (
                        intent.pinned_by == 'at' and ((intent.pin_x is not None and abs(dx) > 1e-9)
                                                     or (intent.pin_y is not None and abs(dy) > 1e-9))) or (
                        intent.pin is not None or intent.cell_pin is not None or any(v is not None for v in (
                            intent.edge, intent.run, intent.rim, intent.beside, intent.row_of))):
                        raise CandidateRefused('pin finalist pose requires changing a held placement anchor')
                own = occ._lift_owners(occ._geometry(item).owners)
                if own & occ.pending:
                    raise CandidateRefused('pin finalist has an unplaced or temporarily lifted member')
                occ.lift(own)
                from placemat.score_delta import Delta
                delta = Delta(board, occ, item, candidate_plan.links, plan=candidate_plan)
                occ, _, _ = delta._view(pose)
                if _fixed_copper(occ) != _fixed_copper(self.plan.occupancy):
                    raise CandidateRefused('pin finalist pose would move fixed current copper')
                candidate_plan.occupancy = occ
            self._links(board, occ, candidate_plan)
            terms = score.whole(board, occ, candidate_plan)
            from placemat.escapes import judging
            escaped = judging(occ).counts()
            measures = score.plan_measures(board, candidate_plan)
            findings = dict(measures['findings'])
            findings.update(escaped)
            # Recheck all physical pads/copper on their unchanged logical nets.
            clashes = set()
            for ref, item in occ.items.items():
                if ref in occ.pending:
                    continue
                for shape in item.shapes:
                    if shape.kind in ('pad', 'through') and shape.net:
                        clashes.update(str(fault) for fault in occ.copper_conflicts(shape, check=True))
            findings['copper'] = len(clashes)
            illegal = []
            for intent in board._placements():
                if intent.kind not in ('part', 'cell'):
                    continue
                item = occ.geometry.cells[intent.key] if intent.kind == 'cell' else occ.geometry.footprint(intent.item.ref)
                geom = occ._geometry(item)
                if geom.owners & occ.pending:
                    continue
                with occ.silk_as_drawn():
                    fault = occ.legal(item, geom.reference, board.clearance, decided=intent.freedom.decided,
                                      past_edge=board._firm_past_edge(intent) if intent.freedom.decided else False,
                                      overhang=intent.overhang, by_corners=intent.freedom.decided)
                if fault is not None:
                    illegal.append(intent.key)
            findings['fixed'] = len(illegal)
            measures['findings'] = findings
            # Label/setup and already accepted action costs are part of the
            # final run objective too. Fresh escape terms replace notices from
            # the original solve; the geometric terms above remain raw.
            residual = score.terms(measures, self.settings)
            for term in score.TERMS:
                if term not in terms:
                    terms[term] = residual[term]
            back_faces = int(measures.get('back_face') or 0)
            for owner, ((_, flip), part) in poses.items():
                if not flip:
                    continue
                key = part.cell or occ.geometry.footprint(owner).inst
                step = next((step for step in self.plan.steps if step.item == key), None)
                intent = next((intent for intent in board._placements() if intent.key == key), None)
                if step is not None and step.placement is not None and intent is not None and intent.either:
                    back_faces -= int(step.back_face and step.placement.face is Face.BACK)
                    back_faces += int(step.placement.face is Face.FRONT)
            terms['back_face'] = self.settings.score_back_face * back_faces
            selected = {ref for refs, _ in groups for ref in refs}
            pin_failures = sum(len(part.slots.breaks) for part in inp.parts if present or part.ref not in selected)
            validity = score.Validity.of(measures)
            validity = replace(validity, critical=validity.critical + pin_failures)
            from placemat import checks
            facts = checks.facts(self.plan.occupancy.geometry)
            required = tuple(sorted(ref for ref, fact in facts.items()
                                    if fact.current_a is not None or fact.currents is not None
                                    or fact.sensitive or fact.aggressor))
            if required:
                # Occupancy polygons are the placement oracle, not a lossless
                # electrical readback of track widths, arcs and filled pours.
                # A writer/read/check proof is required before these candidates
                # may claim the source's electrical success.
                validity = replace(validity, unmeasured=tuple(
                    f'final electrical geometry unavailable: {ref}' for ref in required))
            return Evaluation(terms, validity, math.fsum(terms.values()), occupancy=occ)
        except CandidateRefused as error:
            return Evaluation({}, score.Validity(unmeasured=(str(error),)), math.inf, (str(error),))
