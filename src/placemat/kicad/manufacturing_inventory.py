"""Scratch complete annular inventory. Caller owns deadline/native process.

No writes, rules changes, Standing or retrospective adoption authority.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
from uuid import UUID
import re

from placemat.kicad.board_forms import read_forms


class InventoryUnavailable(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def raw_inventory(path):
    before = sha(path)
    def refuse(reason):
        raise InventoryUnavailable(reason)
    root = read_forms(path, refuse)
    vias = [node for node in root if isinstance(node, list) and node and node[0] == 'via']
    ids = []
    for node in vias:
        fields = [entry for entry in node if isinstance(entry, list) and entry and entry[0] == 'uuid']
        if len(fields) != 1 or len(fields[0]) != 2:
            raise InventoryUnavailable('raw_via_uuid_unproved')
        value = fields[0][1]
        if value.startswith('"'):
            try:value = json.loads(value)
            except (ValueError, TypeError):raise InventoryUnavailable('raw_via_uuid_unproved') from None
        try:parsed = UUID(value)
        except (ValueError, TypeError, AttributeError):raise InventoryUnavailable('raw_via_uuid_unproved') from None
        if str(parsed) != value or parsed.int == 0:raise InventoryUnavailable('raw_via_uuid_unproved')
        ids.append(value)
    if sha(path) != before:
        raise InventoryUnavailable('raw_source_changed')
    token_sha = hashlib.sha256(json.dumps(vias, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'pcb_sha256': before, 'via_tokens_sha256': token_sha, 'via_uuid_multiset': ids}


def collect(board, api, raw):
    """Enumerate every native track; exact raw/native via multiplicity required.

    api is actual pcbnew in the owned worker; controlled tests supply its narrow
    API surface. Native loading and file/runtime checks remain caller-owned.
    """
    layers = list(board.GetEnabledLayers().CuStack())
    if any(type(layer) is not int or not api.IsCopperLayer(layer) for layer in layers) or len(set(layers)) != len(layers):
        raise InventoryUnavailable('native_copper_layers_unproved')
    if 'physical_layer_ids' in raw and layers != raw['physical_layer_ids']:
        raise InventoryUnavailable('native_raw_layer_ids_mismatch')
    names = [api.LayerName(layer) for layer in layers]
    if (not layers or len(set(names)) != len(names) or names != raw['copper_layers']
            or type(board.GetCopperLayerCount()) is not int or len(layers) != board.GetCopperLayerCount()):
        raise InventoryUnavailable('native_copper_layers_unproved')
    rows = []
    for item in board.GetTracks():
        if not api.PCB_VIA.ClassOf(item):
            continue
        uid = item.m_Uuid.AsString()
        through = item.GetViaType() == api.VIATYPE_THROUGH
        if not item.HasValidLayerPair(board.GetCopperLayerCount()):
            raise InventoryUnavailable('native_via_span_invalid')
        if through and not all(item.IsOnLayer(layer) for layer in layers):
            raise InventoryUnavailable('native_through_span_incomplete')
        rows.append({'uuid': uid, 'kind': 'through' if through else 'unsupported',
                     'drill_iu': positive_iu(item.GetDrillValue()), 'layers': names,
                     'diameters_iu': [positive_iu(item.GetWidth(layer)) for layer in layers]})
    if Counter(row['uuid'] for row in rows) != Counter(raw['via_uuid_multiset']):
        raise InventoryUnavailable('raw_native_via_coverage')
    return {'copper_layers': names, 'via_tokens_sha256': raw['via_tokens_sha256'],
            'via_count': len(rows), 'vias': rows}


def positive_iu(value):
    if type(value) is not int or not 0 < value <= 2**31-1:
        raise InventoryUnavailable('native_dimension_unproved')
    return value


def raw_layer_record(path):
    root = read_forms(path, lambda reason: (_ for _ in ()).throw(InventoryUnavailable(reason)))
    sections = [n for n in root if isinstance(n, list) and n and n[0] == 'layers']
    if len(sections) != 1:raise InventoryUnavailable('raw_layers_unproved')
    names, ids = [], []
    for row in sections[0][1:]:
        if not isinstance(row, list) or len(row) < 3:raise InventoryUnavailable('raw_layers_unproved')
        try:
            layer_id = int(row[0])
            name = json.loads(row[1]) if row[1].startswith('"') else row[1]
        except (ValueError, TypeError):raise InventoryUnavailable('raw_layers_unproved') from None
        if row[2] == 'user':continue
        if row[2] not in ('signal', 'power', 'mixed'):raise InventoryUnavailable('raw_copper_type_unproved')
        if type(name) is not str or re.fullmatch(r'(?:F|B|In[1-9][0-9]*)\.Cu', name) is None:
            raise InventoryUnavailable('raw_copper_alias_unproved')
        names.append(name);ids.append(layer_id)
    if (len(names)<2 or names[0]!='F.Cu' or names[-1]!='B.Cu'
            or len(set(names))!=len(names) or len(set(ids))!=len(ids)
            or any(n!=f'In{i}.Cu' for i,n in enumerate(names[1:-1],1))):
        raise InventoryUnavailable('raw_layers_unproved')
    return {'names':names,'ids':ids}


def raw_layers(path):
    return raw_layer_record(path)['names']


def retained_original(factory):
    """Only actual private retained factory/grader custody supplies this record.

    Saved historical diagnostics cannot construct this object from JSON. They
    must use a separately labelled diagnostic request, never this authority seam.
    """
    from placemat.final_authority import RetainedAuthorityFactory
    from placemat.kicad.final_custody import require_original
    if type(factory) is not RetainedAuthorityFactory or not factory._bound:
        raise InventoryUnavailable('retained_original_unavailable')
    factory._verify()
    custody = require_original(factory._grader)
    path = factory._source.resolve()
    manifest = custody['read_manifest']
    expected = manifest.get(str(path))
    if expected is None or sha(path) != expected or factory._inputs[str(path)] != expected:
        raise InventoryUnavailable('original_source_changed')
    raw = raw_inventory(path)
    layers = raw_layers(path)
    files = {}
    for suffix in ('.kicad_pcb', '.kicad_pro', '.kicad_dru'):
        p = path.with_suffix(suffix)
        expected = factory._inputs.get(str(p), 'missing_binding')
        if expected == 'missing_binding' or manifest.get(str(p), 'missing_binding') != expected:
            raise InventoryUnavailable('original_companion_unbound')
        if expected is None:
            if p.exists() or p.is_symlink():raise InventoryUnavailable('original_absence_changed')
            files[suffix] = None
        else:
            if sha(p) != expected:raise InventoryUnavailable('original_companion_changed')
            files[suffix] = {'path': str(p), 'sha256': expected}
    factory._verify()
    after = require_original(factory._grader)
    if after != custody:raise InventoryUnavailable('original_custody_changed')
    return {'custody_sha256': custody['private_context_sha256'],
            'deadline_utc': custody['deadline_utc'],
            'original': {'files': files, 'via_tokens_sha256': raw['via_tokens_sha256'],
                         'via_uuid_multiset': raw['via_uuid_multiset'], 'copper_layers': layers},
            'comparison_authority': False}
