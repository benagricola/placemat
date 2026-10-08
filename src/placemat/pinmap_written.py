"""Exact supported pin candidate emission, separate from routed certification.

Only a current, combined Finalists judgment can mint a proof. The writer never
moves or retags fixed copper, and publishes nothing until exact readback passes.
A written placement receipt is not a routed logical-contract comparison proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import weakref

from .pinmap_common import CandidateRefused, Finalists, _fixed_copper, _physical_pad

_RESERVED = frozenset(('canonical-source.kicad_pcb', 'placement-proof.json'))
_SEAL = object()
_MINTED = weakref.WeakValueDictionary()


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _context(board, plan, settings):
    from .score_virtual import digest
    occ = plan.occupancy
    return digest({'settings': settings.json(), 'geometry': repr(occ.geometry),
                   'items': repr(sorted(occ.items.items())), 'copper': repr(occ.copper),
                   'pending': sorted(occ.pending), 'areas': repr(occ._cell_rule_areas),
                   'links': repr(plan.links), 'pushes': repr(plan.pushes),
                   'placements': repr(board._placements()), 'escapes': repr(board._escapes)})


def _pads(occ):
    numbered = {fp.ref: {pad.number for pad in fp.pads} for fp in occ.geometry.footprints}
    return tuple(sorted(((shape.owner, shape.label, shape.net, shape.kind,
                          tuple(sorted(layer.value for layer in shape.layers)),
                          tuple(shape.poly), (shape.box.left, shape.box.top, shape.box.right, shape.box.bottom))
                         for item in occ.items.values() for shape in item.shapes
                         if _physical_pad(shape, numbered)), key=repr))


def _rules(geometry):
    keys = ('nets', 'netclasses', 'default_clearance', 'layers', 'edge_clearance',
            'hole_to_hole', 'hole_clearance', 'silk_clearance', 'min_track_width',
            'drc_epsilon', 'layer_types', 'copper_mm')
    return tuple((key, repr(getattr(geometry, key))) for key in keys)


def _poses(occ):
    from dataclasses import replace
    # Occupancy poses express a face flip relative to the geometry it read.
    # KiCad stores the mirror's extra half turn in the footprint orientation.
    return tuple((fp.ref, replace(occ.items[fp.ref].reference,
                  rotation=(occ.items[fp.ref].reference.rotation +
                            (180 if occ.items[fp.ref].reference.face != fp.face else 0)) % 360))
                 for fp in sorted(occ.geometry.footprints, key=lambda f: f.ref))


def _shapes(occ):
    from dataclasses import fields
    # Include analytic collision/hole/ownership roles, not only polygon boxes.
    return tuple(sorted(((ref, tuple((field.name, repr(getattr(shape, field.name)))
                                    for field in fields(shape)))
                         for ref, item in occ.items.items() for shape in item.shapes), key=repr))


def _semantics(geometry):
    names = ('ref', 'inst', 'cell', 'value', 'lib_id', 'dnp', 'bom_excluded',
             'board_only', 'net_tie_pads', 'net_tie_groups', 'models', 'courtyard_drawn')
    pad_names = ('number', 'through', 'drill_mm', 'mask_paste', 'custom', 'no_connect')
    return tuple((tuple((name, repr(getattr(fp, name))) for name in names),
                  tuple(sorted(tuple((name, repr(getattr(pad, name))) for name in pad_names)
                               for pad in fp.pads)))
                 for fp in sorted(geometry.footprints, key=lambda fp: fp.ref))


def _collision_shapes(occ):
    from .occupancy import _move_shapes

    def key(value):
        # The rectangle's optional corner-start index and a polygon's first
        # vertex/winding describe enumeration, not different collision copper.
        # Canonicalization retains every integer coordinate, without tolerance.
        if value[0] == 'r':
            return tuple(value[:5])
        if value[0] == 'p':
            points = tuple(value[1])
            if not points:
                return 'p', ()
            cycles = [points[i:] + points[:i] for i in range(len(points))]
            reverse = tuple(reversed(points))
            cycles += [reverse[i:] + reverse[:i] for i in range(len(reverse))]
            return 'p', min(cycles)
        return tuple(value)

    found = []
    for ref, item in occ.items.items():
        for shape in item.shapes:
            if shape.kind not in ('pad', 'through', 'copper') or not occ.geometry.has_footprint(shape.owner):
                continue
            move, effective = occ._read_of(shape, shape.poly)
            fp = occ.geometry.footprint(shape.owner)
            declared = any(fp.copper_shapes) if shape.kind == 'copper' else any(
                pad.kshapes for pad in fp.pads if pad.number == shape.label)
            if declared and not effective:
                raise CandidateRefused('proof_collision_transform_unavailable',
                                       'candidate collision geometry cannot be reconstructed', ref=ref)
            if effective:
                if move is None:
                    raise CandidateRefused('proof_collision_transform_unavailable',
                                           'candidate collision geometry cannot be reconstructed', ref=ref)
                found.append((ref, shape.kind, shape.label,
                              tuple(sorted((key(value) for value in _move_shapes(effective, move)), key=repr))))
    return tuple(sorted(found, key=repr))


@dataclass(frozen=True)
class RemapProof:
    """Immutable physical candidate manifest; constructors use mint()."""
    source: Path
    inputs: tuple
    context: str
    source_pads: tuple
    final_pads: tuple
    source_poses: tuple
    final_poses: tuple
    source_shapes: tuple
    final_shapes: tuple
    fixed_copper: tuple
    rules: tuple
    properties: tuple
    semantics: tuple
    source_collision: tuple
    final_collision: tuple
    candidate_record: str
    _seal: object

    def verify(self, board, plan, settings=None):
        if self._seal is not _SEAL or _MINTED.get(id(self)) is not self:
            raise CandidateRefused('proof_missing', 'pin candidate lacks a minted physical proof')
        if _context(board, plan, settings or board.settings) != self.context:
            raise CandidateRefused('proof_context_changed', 'pin candidate source intent or layout changed')
        for path, expected in self.inputs:
            actual = _hash(path) if Path(path).is_file() else None
            if actual != expected:
                raise CandidateRefused('proof_input_changed', 'pin candidate source artifact changed', path=path)


def mint(board, plan, inp, groups, source_pcb, *, settings=None, context_files=()):
    """Validate complete declared permutations and simultaneous poses before writing.

    Unknown electrical evidence remains in candidate_record; this function does
    not turn an unmeasured placement into a certified routing candidate.
    context_files must include the original capture/selection artifacts needed
    by a later fresh route. Their immutable bytes travel with the written board.
    """
    effective = settings or board.settings
    source = Path(source_pcb).resolve()
    paths = [source, source.with_suffix('.kicad_pro'), source.with_suffix('.kicad_dru')]
    paths.extend(Path(path).resolve() for path in context_files)
    if not source.is_file() or not source.with_suffix('.kicad_pro').is_file():
        raise CandidateRefused('proof_input_missing', 'pin candidate requires the original board and project')
    if any(not Path(path).is_file() for path in context_files):
        raise CandidateRefused('proof_capture_missing', 'pin candidate capture context is missing')
    reserved = sorted({Path(path).name for path in paths} & _RESERVED)
    if reserved:
        raise CandidateRefused('proof_sidecar_reserved', 'pin candidate input uses a generated bundle filename', names=reserved)
    if len({Path(path).name for path in paths}) != len(paths):
        raise CandidateRefused('proof_sidecar_collision', 'pin candidate context files have colliding names')
    original = plan.occupancy
    if original.pending or any(fp.ref not in original.items for fp in original.geometry.footprints):
        raise CandidateRefused('proof_source_incomplete', 'pin candidate requires a fully placed source')
    judge = Finalists(board, plan, effective)
    final = judge.evaluate(inp, tuple(groups))
    if final.refusals or final.occupancy is None:
        refusal = final.refusals[0] if final.refusals else {'code': 'proof_candidate_missing', 'message': 'no physical candidate', 'facts': {}}
        raise CandidateRefused(refusal['code'], refusal['message'], **refusal['facts'])
    candidate = final.occupancy
    if _fixed_copper(candidate) != _fixed_copper(original):
        raise CandidateRefused('proof_fixed_copper_changed', 'pin candidate changes fixed electrical geometry')
    if candidate._cell_rule_areas != original._cell_rule_areas:
        raise CandidateRefused('proof_rule_area_pose_unsupported', 'pin candidate writer cannot move original cell rule areas')
    properties = tuple((fp.ref, tuple(sorted(fp.fields.items()))) for fp in sorted(original.geometry.footprints, key=lambda f: f.ref))
    proof = RemapProof(source, tuple((str(path), _hash(path) if Path(path).is_file() else None) for path in paths),
                      _context(board, plan, effective), _pads(original), _pads(candidate),
                      _poses(original), _poses(candidate), _shapes(original), _shapes(candidate),
                      _fixed_copper(original), _rules(original.geometry), properties,
                      _semantics(original.geometry),
                      _collision_shapes(original), _collision_shapes(candidate),
                      json.dumps(final.record(), sort_keys=True, allow_nan=False), _SEAL)
    _MINTED[id(proof)] = proof
    return proof


def _protected_forms(path):
    """Canonical tokens of fixed board copper/graphics, including full zone definitions.

    KiCad may rewrite whitespace. Quoted strings and escaped quotes stay intact;
    tokens preserve every numeric/net/layer/property value without tolerances.
    """
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', Path(path).read_text())
    protected = {'segment', 'arc', 'via', 'zone', 'gr_line', 'gr_arc', 'gr_circle', 'gr_rect', 'gr_poly', 'gr_text'}
    depth, start, forms = 0, None, []
    for i, token in enumerate(tokens):
        if token == '(':
            depth += 1
            if depth == 2:
                start = i
        elif token == ')':
            if depth == 2 and start is not None and tokens[start + 1] in protected:
                forms.append(tuple(tokens[start:i + 1]))
            depth -= 1
            if depth < 0:
                raise CandidateRefused('proof_board_malformed', 'pin candidate board syntax is malformed')
    if depth:
        raise CandidateRefused('proof_board_malformed', 'pin candidate board syntax is incomplete')
    return tuple(sorted(forms))


def _read_occupancy(path, settings):
    from .kicad.read import read_board
    from .occupancy import Occupancy
    return Occupancy(read_board(path), settings=settings)


def _edit_candidate(proof, out, canonical):
    """The only pcbnew mutation boundary; both files are private artifacts."""
    from .kicad.quiet import import_pcbnew, quiet_stderr
    from .kicad.write import _place_footprint
    from .placement import Placement
    from .values import Face, Location
    pcbnew = import_pcbnew()
    with quiet_stderr():
        pcb = pcbnew.LoadBoard(str(proof.source))
    fps = list(pcb.GetFootprints())
    by_ref = {fp.GetReference(): fp for fp in fps}
    if len(by_ref) != len(fps) or set(by_ref) != {ref for ref, _ in proof.final_poses}:
        raise CandidateRefused('proof_source_references_changed', 'written source footprint identities differ from the proof')
    final_nets = {}
    for ref, number, net, *_ in proof.final_pads:
        key = ref, number
        if key in final_nets and final_nets[key] != net:
            raise CandidateRefused('proof_pad_net_ambiguous', 'candidate lands disagree on a pad net', ref=ref, pad=number)
        final_nets[key] = net
    if any(net and pcb.FindNet(net) is None for net in final_nets.values()):
        raise CandidateRefused('proof_net_missing', 'pin candidate net is absent from the original board')
    pcb.Save(str(canonical))
    for ref, target in proof.final_poses:
        fp = by_ref[ref]
        current = Placement(Location(pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)),
                            fp.GetOrientationDegrees(), Face.BACK if fp.IsFlipped() else Face.FRONT)
        from dataclasses import replace
        # Reuse the established writer's flip convention, supplying the
        # pose that yields the manifest's actual KiCad orientation.
        requested = replace(target, rotation=target.rotation - (180 if current.face != target.face else 0))
        _place_footprint(fp, current, requested)
        for pad in fp.Pads():
            net = final_nets.get((ref, pad.GetNumber()))
            if net is not None:
                pad.SetNet(pcb.FindNet(net)) if net else pad.SetNetCode(0)
    pcb.Save(str(out))


def write_proved(board, plan, proof, destination, *, settings=None):
    """Write a fresh private bundle, exact reread, then publish the directory.

    Output only receives proved pad nets and complete footprint poses. Fixed
    tracks/vias/zones and original project/rules/capture bytes are preserved.
    Unsupported KiCad geometry round trips refuse rather than weaken the proof.
    """
    effective = settings or board.settings
    if not isinstance(proof, RemapProof):
        raise CandidateRefused('proof_missing', 'pin candidate writer requires a minted physical proof')
    proof.verify(board, plan, effective)
    destination = Path(destination)
    if destination.exists():
        raise CandidateRefused('proof_destination_exists', 'pin candidate destination must be fresh')
    actual = _read_occupancy(proof.source, effective)
    if (_pads(actual) != proof.source_pads or _poses(actual) != proof.source_poses
            or _shapes(actual) != proof.source_shapes):
        raise CandidateRefused('proof_written_source_mismatch', 'written source pad geometry differs from evaluated source')
    if _fixed_copper(actual) != proof.fixed_copper or _rules(actual.geometry) != proof.rules:
        raise CandidateRefused('proof_written_source_rules_or_copper_changed',
                               'written source fixed copper or physical rules differ from evaluated source')
    if _semantics(actual.geometry) != proof.semantics:
        raise CandidateRefused('proof_source_semantics_changed',
                               'written source manufacturing or footprint identity differs from evaluated source')
    if _collision_shapes(actual) != proof.source_collision:
        raise CandidateRefused('proof_source_collision_changed',
                               'written source collision geometry differs from evaluated source')
    if tuple((fp.ref, tuple(sorted(fp.fields.items()))) for fp in sorted(actual.geometry.footprints, key=lambda f: f.ref)) != proof.properties:
        raise CandidateRefused('proof_source_properties_changed', 'written source intent properties differ from evaluated source')
    # Work is confined to a temporary bundle; a refused readback publishes nothing.
    with tempfile.TemporaryDirectory(prefix='placemat-remap-', dir=destination.parent) as temp:
        temp = Path(temp)
        for raw, expected in proof.inputs:
            if expected is not None:
                shutil.copy2(raw, temp / Path(raw).name)
        out = temp / proof.source.name
        # Canonical baseline includes the same KiCad serializer as the result.
        canonical = temp / 'canonical-source.kicad_pcb'
        _edit_candidate(proof, out, canonical)
        protected = _protected_forms(canonical)
        if _protected_forms(out) != protected:
            raise CandidateRefused('proof_fixed_board_items_changed', 'writing changed fixed copper or board graphics')
        reread = _read_occupancy(out, effective)
        if (_pads(reread) != proof.final_pads or _poses(reread) != proof.final_poses
                or _shapes(reread) != proof.final_shapes):
            raise CandidateRefused('proof_readback_geometry_changed', 'saved candidate differs from evaluated pad geometry')
        if _fixed_copper(reread) != proof.fixed_copper or _rules(reread.geometry) != proof.rules:
            raise CandidateRefused('proof_readback_rules_or_copper_changed',
                                   'saved candidate fixed copper or physical rules changed')
        if _semantics(reread.geometry) != proof.semantics:
            raise CandidateRefused('proof_readback_semantics_changed',
                                   'saved candidate changed manufacturing or footprint identity')
        if _collision_shapes(reread) != proof.final_collision:
            raise CandidateRefused('proof_readback_collision_changed',
                                   'saved candidate collision geometry differs from evaluated candidate')
        properties = tuple((fp.ref, tuple(sorted(fp.fields.items()))) for fp in sorted(reread.geometry.footprints, key=lambda f: f.ref))
        if properties != proof.properties:
            raise CandidateRefused('proof_readback_properties_changed', 'saved candidate changed original intent properties')
        for raw, expected in proof.inputs:
            if expected is not None and Path(raw) != proof.source and _hash(temp / Path(raw).name) != expected:
                raise CandidateRefused('proof_readback_sidecar_changed', 'saved candidate changed original project or capture bytes')
        proof.verify(board, plan, effective)
        canonical.unlink()
        receipt = {'schema': 1, 'scope': 'exact written placement; routed comparison unavailable',
                   'source_inputs': dict(proof.inputs), 'context': proof.context,
                   'candidate': json.loads(proof.candidate_record),
                   'outputs': {path.name: _hash(path) for path in temp.iterdir() if path.is_file()}}
        (temp / 'placement-proof.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
        temp.rename(destination)
    return destination / proof.source.name, receipt
