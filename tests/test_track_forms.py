import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as N

import pytest

from placemat.board_geometry import BoardGeometry, CopperItem, NetClass


def functions(filename, names, namespace):
    tree = ast.parse((Path(__file__).parents[1] / 'src/placemat' / filename).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, 'exec'), namespace)
    return namespace


def test_actual_reader_copper_kind_transport_keeps_tiny_arc_and_unknown():
    from placemat.values import Box, CopperLayer
    layer = CopperLayer.of('F.Cu')

    class Via:
        pass
    pcb = N(PCB_TRACE_T=1, PCB_ARC_T=2, PCB_VIA=Via, PAD_ATTRIB_NPTH=7)
    ns = {
        'CLEAR_ERR_NM': 5000, 'pcbnew': pcb, 'CopperItem': CopperItem, 'Box': Box,
        '_copper_layers': lambda b, s: frozenset([layer]),
        '_kiid': lambda o: str(o.Type()), 'mm': lambda v: v / 1_000_000,
        'copper_outlines': lambda o, l, e: (((0, 0), (1, 0), (1, 1)),),
    }
    functions('kicad/read.py', ('_track_form', '_copper'), ns)

    class Object:

        def __init__(self, kind):
            self.kind = kind

        def Type(self):
            return self.kind

        def GetLayerSet(self):
            return N(CuStack=lambda: [0])

        def GetNetname(self):
            return 'N'

        def GetWidth(self):
            return 200000

        def GetStart(self):
            return N(x=0, y=0)

        def GetEnd(self):
            return N(x=1000000, y=0)

        def GetLength(self):
            # A tiny arc can have the same rounded native length as its chord.
            return 1_000_000
    board = N(
        GetFootprints=lambda: [], GetTracks=lambda: [Object(1), Object(2), Object(99)],
        IsLayerEnabled=lambda l: True, GetDrawings=lambda: [], GetAreaCount=lambda: 0,
    )
    items = ns['_copper'](board, {})
    assert [c.track_form for c in items] == ['straight', 'arc', None]
    assert all((c.kind == 'track' and c.length_mm == 1 for c in items))


def test_legacy_copper_constructor_defaults_unknown():
    from placemat.values import Box
    item = CopperItem('track', 'N', frozenset(), (), Box.of_points(((0, 0), (1, 1))))
    assert item.track_form is None


def test_actual_arranged_track_mid_is_kind_evidence():
    import placemat.arranged_geometry as actual
    from placemat.copper import Track
    from placemat.values import Location, CopperLayer
    base = dict(net='N', layer=CopperLayer.of('F.Cu'), width=0.2,
                start=Location(0, 0), end=Location(1, 0))
    line = actual._copper_item(Track(**base), 'M', [])
    arc = actual._copper_item(Track(**base, mid=Location(0.5, 1e-06)), 'M', [])
    assert line.track_form == 'straight' and arc.track_form == 'arc'


def test_actual_loaded_binding_declares_trace_and_arc_native_types():
    binding = Path('/usr/lib/python3/dist-packages/pcbnew.py')
    if not binding.exists():
        pytest.skip('system KiCad binding unavailable')
    tree = ast.parse(binding.read_text())
    declarations = {
        node.targets[0].id: node.value.attr for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name) and node.value.value.id == '_pcbnew'
    }
    assert declarations['PCB_TRACE_T'] == 'PCB_TRACE_T'
    assert declarations['PCB_ARC_T'] == 'PCB_ARC_T'
    track = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PCB_TRACK'))
    constructor = next((n for n in track.body if isinstance(n, ast.FunctionDef) and n.name == '__init__'))
    assert isinstance(constructor.args.defaults[-1], ast.Name)
    assert constructor.args.defaults[-1].id == 'PCB_TRACE_T'


def test_geometry_fingerprint_retains_track_kind():
    custody = pytest.importorskip('placemat.kicad.final_custody')
    from placemat.values import Box, CopperLayer
    item = CopperItem(
        'track', 'N', frozenset([CopperLayer.of('F.Cu')]), (),
        Box.of_points(((0, 0), (1, 1))), anchors=((0, 0), (1, 1)),
        length_mm=1.414213, track_form='straight',
    )
    geometry = BoardGeometry(
        '/controlled/input.kicad_pcb', (), {}, (item,), (), frozenset({'N'}),
        {'N': NetClass('Default', 0.2, 0.2, 0.6, 0.3)}, 0.2, (),
    )
    arc = replace(geometry, copper=(replace(item, track_form='arc'),))
    assert custody.geometry_fingerprint(geometry) != custody.geometry_fingerprint(arc)
    readcopy = replace(geometry, path='/controlled/readcopy.kicad_pcb')
    assert custody.geometry_fingerprint(geometry) == custody.geometry_fingerprint(readcopy)
