"""Phases for tests that route: the rest phase alone, which routes what the old main pass did; and the capability
listing a stand-in router gives so a route takes it for the placemat fork."""
import json

from placemat.route_phase import parse_phases

SIGNALS = ({"name": "signals"},)
CAPABILITIES = {"modules": {"route.py": True}, "flags": {"route.py": ["--connections", "--bus-nets"]}}


def phases(*raw):
    return parse_phases(raw or SIGNALS)


def fake_capabilities(krt) -> None:
    """A stand-in router checkout's krt_capabilities.py: it lists every flag a phase route needs (route.REQUIRES)."""
    (krt / "krt_capabilities.py").write_text("print(%r)\n" % json.dumps(CAPABILITIES))
    (krt / "py_router").mkdir(exist_ok=True)
    (krt / "py_router/nominal_width_policy.py").write_text(FAKE_WIDTH_POLICY)



def write_sidecar(folder, nets, **over):
    from tests.test_capture_nets import write
    return write(folder, nets=nets, **over)


def board_with_power_and_rf(tmp_path):
    from tests.test_net_clearance import _two_part_board, _project
    pcb = _two_part_board(tmp_path)
    text = pcb.read_text().replace('(property "Reference"', '(property "Pm.I" "4A") (property "Reference"')
    pcb.write_text(text)
    _project(pcb, [{"name": "Default", "clearance": 0.15, "track_width": 0.2},
                   {"name": "RF", "clearance": 0.3, "track_width": 0.2}], assignments={"VIN": ["RF"]})
    return pcb


# Explicit stand-in policy for fake routers: no production policy is imported.
# These boards use a 0.2mm Default; focused policy tests cover real class/rules.
FAKE_WIDTH_POLICY = r"""
import hashlib, json, pathlib, sys
packet = json.load(sys.stdin)
board = pathlib.Path(packet['board'])
root = pathlib.Path(__file__).resolve().parents[1]
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
policies = []
for request in packet['requests']:
    width = 0.2
    args = request['args']
    for i, arg in enumerate(args):
        if arg == '--track-width': width = float(args[i+1])
        elif arg.startswith('--track-width='): width = float(arg.split('=',1)[1])
    policies.append({'name': request['name'], 'kind': request['kind'], 'by_net': {
        net: {'status': 'known', 'widths': {layer: max(width, request.get('power', {}).get(net, 0))
             for layer in request['layers']}, 'reason': ''} for net in request['nets']}})
receipt = {'schema': 1, 'board': str(board), 'config_sha256': hashlib.sha256(
    json.dumps(packet['requests'], sort_keys=True).encode()).hexdigest(),
    'inputs': {str(p): sha(p) for p in (board, board.with_suffix('.kicad_pro'), board.with_suffix('.kicad_dru'))},
    'sources': {str(p.relative_to(root)): sha(p) for p in sorted(set(root.glob('*.py')) |
        set((root / 'py_router').rglob('*.py')))}, 'policies': policies}
print('PLACEMAT_WIDTH_POLICY ' + json.dumps(receipt))
"""
