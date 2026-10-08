"""Complete UUID/type coverage for native DRC copper pair resolution."""
from collections import Counter
import json
from uuid import UUID
from .manufacturing_clearance_report import Unproved


def canonical_uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
            raise Unproved('uuid_domain')
    except (ValueError, AttributeError) as error:
        raise Unproved('uuid_domain') from error
    return value


def raw_domain(path, read_forms, check_current):
    check_current()
    root = read_forms(path, lambda reason: (_ for _ in ()).throw(Unproved(reason)))
    rows = []
    numeric_names = {}
    for node in root:
        if isinstance(node,list) and node and node[0]=='net' and len(node)==3:
            code=node[1]
            if code in numeric_names:
                raise Unproved('raw_net_domain')
            numeric_names[code]=json.loads(node[2]) if node[2].startswith('"') else node[2]

    def net(node):
        entries=[row for row in node if isinstance(row,list) and row and row[0]=='net']
        if not entries:
            return ''
        if len(entries)!=1 or len(entries[0]) not in {2,3}:
            raise Unproved('raw_net_domain')
        row=entries[0]
        token=row[-1]
        if not isinstance(token,str):
            raise Unproved('raw_net_domain')
        if token.startswith('"'):
            return json.loads(token)
        if len(row)==3:
            return token
        if token=='0':
            return ''
        if token not in numeric_names:
            raise Unproved('raw_net_domain')
        return numeric_names[token]

    def uid(node):
        found = [row for row in node if isinstance(row, list) and row and row[0] == 'uuid']
        if len(found) != 1 or len(found[0]) != 2:
            raise Unproved('uuid_domain')
        token = found[0][1]
        if not isinstance(token,str):
            raise Unproved('uuid_domain')
        value = json.loads(token) if token.startswith('"') else token
        return canonical_uuid(value)

    def visit(node):
        check_current()
        if not isinstance(node, list) or not node:
            return
        if node[0] == 'footprint':
            if any(isinstance(row, list) and row and row[0] == 'net_tie_pad_groups' for row in node):
                raise Unproved('net_tie_unproved')
            for child in node:
                visit(child)
        elif node[0] in {'pad', 'segment', 'arc', 'via', 'zone'}:
            kind = 'track' if node[0] == 'segment' else node[0]
            rows.append({'uuid': uid(node), 'kind': kind, 'net':net(node)})
        elif node[0].startswith(('gr_', 'fp_')) or node[0] in {'property', 'dimension', 'target'}:
            for child in node:
                if isinstance(child, list) and child and child[0] in {'layer', 'layers'}:
                    if any((json.loads(token) if token.startswith('"') else token).endswith('.Cu')
                           for token in child[1:]):
                        raise Unproved('copper_graphic_unproved')

    for node in root:
        visit(node)
    if len({row['uuid'] for row in rows}) != len(rows):
        raise Unproved('uuid_domain')
    check_current()
    return sorted(rows,key=lambda row:row['uuid'])


def raw_layer_domain(path, read_forms, enabled, check_current):
    """Independent copper participation of supported literal item forms."""
    if (type(enabled) is not list or not enabled or len(set(enabled)) != len(enabled)
            or any(type(name) is not str or not name.endswith('.Cu') for name in enabled)):
        raise Unproved('layer_domain')
    root = read_forms(path, lambda reason: (_ for _ in ()).throw(Unproved(reason)))
    result = {}

    def text(token):
        if type(token) is not str:
            raise Unproved('layer_domain')
        return json.loads(token) if token.startswith('"') else token

    def visit(node):
        check_current()
        if type(node) is not list or not node:
            return
        if node[0] == 'footprint':
            for child in node:
                visit(child)
            return
        if node[0] not in {'pad', 'segment', 'arc', 'via', 'zone'}:
            return
        uuids = [row for row in node if type(row) is list and row and row[0] == 'uuid']
        fields = [row for row in node if type(row) is list and row and row[0] in {'layer', 'layers'}]
        if len(uuids) != 1 or len(uuids[0]) != 2 or len(fields) != 1:
            raise Unproved('raw_layer_domain')
        uid = canonical_uuid(text(uuids[0][1]))
        names = [text(value) for value in fields[0][1:]]
        if len(set(names)) != len(names):
            raise Unproved('raw_layer_domain')
        if node[0] == 'via':
            if len(names) != 2 or any(name not in enabled for name in names):
                raise Unproved('raw_layer_domain')
            first, last = [enabled.index(name) for name in names]
            if first >= last:
                raise Unproved('raw_layer_domain')
            copper = enabled[first:last + 1]
        else:
            copper = []
            for name in names:
                if name == '*.Cu':
                    copper.extend(enabled)
                elif name == 'F&B.Cu':
                    if 'F.Cu' not in enabled or 'B.Cu' not in enabled:
                        raise Unproved('raw_layer_domain')
                    copper.extend(['F.Cu', 'B.Cu'])
                elif name.endswith('.Cu'):
                    if name not in enabled:
                        raise Unproved('disabled_copper_layer')
                    copper.append(name)
            copper = [name for name in enabled if name in copper]
        if not copper or uid in result:
            raise Unproved('raw_layer_domain')
        result[uid] = copper

    for node in root:
        visit(node)
    check_current()
    return result


def collect(board, api, raw, check_current):
    check_current()
    stack = list(board.GetEnabledLayers().CuStack())
    if not stack or len(set(stack)) != len(stack) or any(type(layer) is not int or not api.IsCopperLayer(layer) for layer in stack):
        raise Unproved('layer_domain')
    physical_names = {layer: api.LayerName(layer) for layer in stack}
    if len(set(physical_names.values())) != len(stack):
        raise Unproved('layer_domain')
    rows = []

    def add(item, kind):
        check_current()
        layers = [physical_names[layer] for layer in stack if item.IsOnLayer(layer)]
        if not layers:
            raise Unproved('noncopper_item_unproved')
        net = item.GetNetname()
        if not isinstance(net, str):
            raise Unproved('net_domain')
        rows.append({'uuid': canonical_uuid(item.m_Uuid.AsString()),
                     'kind': kind, 'net': net, 'layers': layers})

    kinds = {api.PCB_TRACE_T: 'track', api.PCB_ARC_T: 'arc', api.PCB_VIA_T: 'via'}
    for item in board.GetTracks():
        kind = kinds.get(item.Type())
        if kind is None:
            raise Unproved('track_type_unproved')
        add(item, kind)
    for footprint in board.GetFootprints():
        if footprint.IsNetTie():
            raise Unproved('net_tie_unproved')
        for pad in footprint.Pads():
            add(pad, 'pad')
        for zone in footprint.Zones():
            if zone.GetIsRuleArea():
                raise Unproved('rule_area_unproved')
            add(zone, 'zone')
    for zone in board.Zones():
        if zone.GetIsRuleArea():
            raise Unproved('rule_area_unproved')
        add(zone, 'zone')
    native_ids = Counter((row['uuid'], row['kind'],row['net']) for row in rows)
    raw_ids = Counter((row['uuid'], row['kind'],row['net']) for row in raw)
    if native_ids != raw_ids or any(count != 1 for count in native_ids.values()):
        raise Unproved('raw_native_domain_changed')
    check_current()
    return sorted(rows,key=lambda row:row['uuid'])
