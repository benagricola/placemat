"""Exact, versioned final-check context for an owned JSON-only worker.

This transport is not authority. The retained parent binds its bytes and
independently verifies worker artifacts before minting comparison evidence.
Unknown objects refuse; no script, class name, pickle or callback is executed.
"""
from dataclasses import asdict, fields
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

from .pinmap_common import CandidateRefused


class ContextRefused(CandidateRefused):
    pass


def _refuse(message, **facts):
    raise ContextRefused('final_check_context_unsupported', message, **facts)


def _keys(record, expected):
    if not isinstance(record, dict) or set(record) != set(expected):
        _refuse('final-check context fields are missing or unknown')


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _refuse('final-check context has a nonfinite or nonnumeric coordinate')
    return value


def _point(value):
    from .values import Location
    if type(value) is Location:
        value = (value.x, value.y)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _refuse('final-check context point must have two coordinates')
    return tuple(_number(v) for v in value)


def _paths(paths):
    from .cutouts import Arc
    if not isinstance(paths, (list, tuple)):
        _refuse('final-check context paths must be a list')
    return [[{'arc': {'to': list(_point(v.to)), 'via': list(_point(v.via))}}
             if type(v) is Arc else {'point': list(_point(v))} for v in path]
            for path in paths]


def _read_paths(paths):
    from .cutouts import Arc
    if not isinstance(paths, list) or any(not isinstance(path, list) for path in paths):
        _refuse('final-check context paths must be lists')
    out = []
    for path in paths:
        points = []
        for entry in path:
            if not isinstance(entry, dict):
                _refuse('final-check path entry is not a record')
            if set(entry) == {'point'}:
                points.append(_point(entry['point']))
            elif set(entry) == {'arc'}:
                _keys(entry['arc'], ('to', 'via'))
                points.append(Arc(_point(entry['arc']['to']), _point(entry['arc']['via'])))
            else:
                _refuse('final-check path has an unsupported entry')
        out.append(tuple(points))
    return tuple(out)


def _shape(shape):
    from .cutouts import Cutouts
    from .outline import Outline
    from .values import Disc
    if shape is None:
        return {'kind': 'none'}
    if type(shape) is Outline:
        return {'kind': 'outline', 'paths': _paths(shape.paths),
                'loops': [[list(_point(v)) for v in loop] for loop in shape.loops]}
    if type(shape) is Cutouts:
        return {'kind': 'cutouts', 'paths': _paths(shape.paths),
                'loops': [[list(_point(v)) for v in loop] for loop in shape.loops]}
    if type(shape) is Disc:
        return {'kind': 'disc', 'centre': list(_point(shape.centre)),
                'diameter': _number(shape.diameter), 'hole': _number(shape.hole),
                'holes': _paths(shape.holes)}
    _refuse('final-check board shape type is unsupported', type=type(shape).__name__)


def _read_shape(record):
    from .cutouts import Cutouts
    from .outline import Outline
    from .values import Disc, Location
    if not isinstance(record, dict):
        _refuse('final-check board shape is not a record')
    kind = record.get('kind')
    if kind == 'none':
        _keys(record, ('kind',))
        return None
    if kind in ('outline', 'cutouts'):
        _keys(record, ('kind', 'paths', 'loops'))
        if not isinstance(record['loops'], list) or any(not isinstance(v, list) for v in record['loops']):
            _refuse('final-check board loops must be lists')
        loops = tuple(tuple(_point(p) for p in loop) for loop in record['loops'])
        paths = _read_paths(record['paths'])
        made = Outline.of(paths[0], paths[1:]) if kind == 'outline' and paths else Cutouts(paths)
        if kind == 'outline' and not paths:
            _refuse('final-check outline has no outer path')
        if made.loops != loops:
            _refuse('final-check declared and flattened board paths disagree')
        return made
    if kind == 'disc':
        _keys(record, ('kind', 'centre', 'diameter', 'hole', 'holes'))
        return Disc(Location(*_point(record['centre'])), _number(record['diameter']),
                    _number(record['hole']), _read_paths(record['holes']))
    _refuse('final-check board shape kind is unsupported', kind=kind)


def _named(record, cls):
    names = tuple(f.name for f in fields(cls))
    _keys(record, names)
    if cls.__name__ == 'Rule':
        if record['kind'] != 'clearance' or _number(record['min_mm']) < 0:
            _refuse('final-check rule kind or minimum is unsupported')
        for key in ('why', 'within', 'on', 'of'):
            if not isinstance(record[key], str) and not (key != 'why' and record[key] is None):
                _refuse('final-check rule subject is unsupported')
        between = record['between']
        if between is not None:
            if not isinstance(between, list) or len(between) != 2 or any(not isinstance(v, str) for v in between):
                _refuse('final-check rule pair is unsupported')
            record = {**record, 'between': tuple(between)}
    else:
        from .checks import SIDES
        if record['check'] not in SIDES or not isinstance(record['subject'], str) or not isinstance(record['why'], str):
            _refuse('final-check acceptance subject is unsupported')
        bounds = [record[k] for k in ('at_least', 'at_most') if record[k] is not None]
        if len(bounds) != 1:
            _refuse('final-check acceptance must have exactly one bound')
        if record[SIDES[record['check']]] is None:
            _refuse('final-check acceptance bound has the wrong direction')
        _number(bounds[0])
    return cls(**record)


def _plain(value):
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        _refuse('final-check context cannot be represented exactly as JSON', reason=str(error))


def encode(board, plan, measures, source_pcb):
    """Encode retained original facts; declared lane intent is not supported yet."""
    from .checks import Acceptance
    from .rules import Rule
    if board._escapes:
        _refuse('declared escape intent requires a supported exact worker transport')
    if any(type(rule) is not Rule for rule in board._rules) or any(type(a) is not Acceptance for a in plan.acceptances):
        _refuse('unknown rule or acceptance type cannot be transported')
    source = Path(source_pcb).resolve()
    inputs = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
              for path in (source, source.with_suffix('.kicad_pro'), source.with_suffix('.kicad_dru'))}
    if inputs[str(source)] is None or inputs[str(source.with_suffix('.kicad_pro'))] is None:
        _refuse('original final-check board/project is missing')
    settings = asdict(board.settings)
    settings.pop('sources', None)
    result = {'schema': 1, 'source': str(source), 'inputs': inputs, 'settings': settings,
              'rules': [asdict(rule) for rule in board._rules],
              'acceptances': [asdict(a) for a in plan.acceptances],
              'measures': measures, 'edge_margin': board.edge_margin,
              'component_spacing': board.component_spacing,
              'board_shape': _shape(plan.occupancy.board_shape),
              'board_cutouts': _shape(plan.occupancy.board_cutouts),
              'quiet': sorted(plan.occupancy.quiet_nets), 'planes': sorted(plan.occupancy.plane_nets),
              'pending': sorted(plan.occupancy.pending),
              'fields': {fp.ref: dict(fp.fields) for fp in plan.geometry.footprints}}
    return _plain(result)


def judge(record, pcb):
    """Worker-only reads and judgment. Its caller supplies the owned deadline."""
    from .checks import Acceptance
    from .final_board import judge as final_judge
    from .kicad.read import read_board
    from .layout import Board
    from .occupancy import Occupancy
    from .rules import Rule
    from .settings import Settings, SettingsError, _coerce, _validate, bind
    _keys(record, ('schema', 'source', 'inputs', 'settings', 'rules', 'acceptances', 'measures',
                   'edge_margin', 'component_spacing', 'board_shape', 'board_cutouts',
                   'quiet', 'planes', 'pending', 'fields'))
    if type(record['schema']) is not int or record['schema'] != 1:
        _refuse('unsupported final-check context schema')
    _plain(record)
    if not isinstance(record['source'], str) or not Path(record['source']).is_absolute():
        _refuse('final-check source must be an absolute path')
    if not isinstance(record['measures'], dict) or not isinstance(record['fields'], dict) or any(
            not isinstance(ref, str) or not isinstance(props, dict) or any(
                not isinstance(key, str) or not isinstance(value, str) for key, value in props.items())
            for ref, props in record['fields'].items()):
        _refuse('final-check measures or captured properties are malformed')
    def unchanged():
        if not isinstance(record['inputs'], dict):
            _refuse('final-check source identities are malformed')
        source = Path(record['source'])
        if set(record['inputs']) != {str(source), str(source.with_suffix('.kicad_pro')), str(source.with_suffix('.kicad_dru'))}:
            _refuse('final-check source identity scope is malformed')
        for path, expected in record['inputs'].items():
            optional = path == str(source.with_suffix('.kicad_dru'))
            if not (optional and expected is None) and (not isinstance(expected, str) or len(expected) != 64
                    or any(c not in '0123456789abcdef' for c in expected)):
                _refuse('final-check source digest is missing or malformed', path=path)
        for path, expected in record['inputs'].items():
            actual = hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None
            if actual != expected:
                _refuse('original final-check source changed', path=path)
    unchanged()
    values = record['settings']
    if not isinstance(values, dict) or set(values) != set(Settings.keys()) - {'sources'}:
        _refuse('final-check settings scope is incomplete or unknown')
    declared = {f.name: str(f.type) for f in fields(Settings)}
    for key, value in values.items():
        if value is None and 'None' in declared[key]:
            continue  # None is a real optional built-in value, not a CLI unset.
        try:
            _validate(key, value, 'retained final-check context')
        except SettingsError as error:
            _refuse('final-check setting is malformed', setting=key, reason=str(error))
    cfg = Settings(**{key: _coerce(key, value) for key, value in values.items()})
    with bind(cfg):
        geometry = read_board(record['source'])
        if {fp.ref: dict(fp.fields) for fp in geometry.footprints} != record['fields']:
            _refuse('original final-check footprint intent changed')
        board = Board(geometry, keep_going=True, settings=cfg)
        board.edge_margin = None if record['edge_margin'] is None else _number(record['edge_margin'])
        board.component_spacing = _number(record['component_spacing'])
        if not isinstance(record['rules'], list) or not isinstance(record['acceptances'], list):
            _refuse('final-check rules or acceptances are not lists')
        board._rules = [_named(rule, Rule) for rule in record['rules']]
        occ = Occupancy(geometry, board.edge_margin, settings=cfg, rules=board._rules,
                        component_spacing=board.component_spacing,
                        board_shape=_read_shape(record['board_shape']), board_cutouts=_read_shape(record['board_cutouts']))
        for key in ('quiet', 'planes', 'pending'):
            if not isinstance(record[key], list) or any(not isinstance(v, str) for v in record[key]) or len(set(record[key])) != len(record[key]):
                _refuse('final-check net/owner scope is malformed', scope=key)
        occ.quiet_nets, occ.plane_nets, occ.pending = set(record['quiet']), set(record['planes']), set(record['pending'])
        plan = SimpleNamespace(geometry=geometry, occupancy=occ, steps=[], findings=[],
                               acceptances=[_named(a, Acceptance) for a in record['acceptances']])
        result = final_judge(board, plan, pcb, record['measures'])
    unchanged()
    return result
