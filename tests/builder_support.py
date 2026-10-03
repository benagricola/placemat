"""Helpers for the board builder's tests: a layout script's text run on a small synthetic board, the golden files, the property
that no script the builder writes holds a coordinate."""
import ast
from pathlib import Path

from placemat.context import run_script
from placemat.preview_json import declared_sites, plan_json
from tests.suggest_support import make_board

GOLDEN = Path(__file__).with_name("builder_golden")

# the parts of the synthetic board every builder test uses (suggest_support.make_board's own)
PARTS = None


def golden(name: str) -> str:
    return (GOLDEN / name).read_text()


def run_text(tmp_path: Path, text: str, parts=None, name="layout.py", **kw):
    """(board, plan, doc, path) of the script `text` written to `tmp_path` and run on a synthetic board."""
    path = tmp_path / name
    path.write_text(text)
    board = make_board(parts, **kw)
    board.script_file = str(path)
    run_script(path, board)
    plan = board.resolve()
    return board, plan, plan_json(plan, declared_sites(board)), path


FORBIDDEN_CALLS = {"Location", "figure"}


def coordinates_in(text: str) -> list:
    """What in a script's text is a coordinate the builder must never write: a `Location`, a numeric `Centre` axis, a `coordinates`
    keyword, `.local()` or `.offset()`, `X` or `Y` with a second argument, `board.figure`, `Near(Location...)`. A number literal is
    allowed only inside a constant assignment (a name in capitals), as a pad's number, or as a quarter-turn `rotation=`."""
    tree = ast.parse(text)
    found = []
    consts = set()
    for st in tree.body:
        if isinstance(st, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in st.targets):
            consts |= {id(n) for n in ast.walk(st)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in FORBIDDEN_CALLS:
                found.append("%s at line %d" % (name, node.lineno))
            if name in ("X", "Y") and len(node.args) + len(node.keywords) > 1:
                found.append("%s with an offset at line %d" % (name, node.lineno))
            if name == "Centre" and any(isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) for a in node.args[:2]):
                found.append("a numeric Centre at line %d" % node.lineno)
            if name == "Turned":                           # a quarter turn with another part
                consts |= {id(a) for a in node.args if isinstance(a, ast.Constant)}
            if name in ("PadRef", "CellPadRef"):          # a pad is named by its number or its net: not a coordinate
                consts |= {id(a) for a in node.args if isinstance(a, ast.Constant)}
            if name in ("local", "offset"):
                found.append(".%s() at line %d" % (name, node.lineno))
            for k in node.keywords:
                if k.arg == "coordinates":
                    found.append("coordinates= at line %d" % node.lineno)
                if k.arg == "rotation" and isinstance(k.value, ast.Constant) and k.value.value in (0, 90, 180, 270):
                    consts |= {id(n) for n in ast.walk(k.value)}
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool) \
                and id(node) not in consts:
            found.append("the number %r at line %d, outside a constant" % (node.value, node.lineno))
    return found


def stage_project(tmp_path: Path, module: str = "usbcells", keep_script: bool = False):
    """A scratch copy of a fixture project (tests/real_modules) with its generation cached and recorded as current, so a
    generate restores it and `pcb layout` is not run. The module's own layout script is removed unless `keep_script`, so the
    `.zen` is a board with no layout. Returns (the .zen, the script a builder would write beside it, the board folder)."""
    import json

    from placemat import runner
    from tests import real_modules
    layout = real_modules.stage(tmp_path, module)
    src = runner.find_board(layout)
    inputs = runner.generator_inputs(src)
    runner._inputs_record(src).write_text(json.dumps(inputs, indent=1, sort_keys=True))
    if not keep_script:
        layout.unlink()
    return src.zen, src.board_dir / (src.name + "_layout.py"), src.board_dir


class Session:
    """A builder session on a synthetic board: the script's text, resolved after each action, and the context a request is
    answered in. `act` applies an offer's edits to the text in memory (the same `apply_edits` the studio's apply path calls)."""

    def __init__(self, tmp_path: Path, parts=None, shape=None, name="Demo", description="layout.", text=None, **board):
        from placemat import builder, script_edit
        from placemat.builder_worker import parts_record
        self.tmp, self.name, self.board_kw = Path(tmp_path), name, board
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.parts = parts
        self.data = parts_record(make_board(parts, **board).geometry)
        self.path = self.tmp / ("%s_layout.py" % name)
        self.text = text if text is not None else builder.new_script(name, description, shape or {"shape": "rect", "width": 60.0, "height": 40.0},
                                                                     str(self.path.resolve()))
        self.history = [self.text]
        self.script_edit = script_edit
        self.resolve()

    def resolve(self):
        from placemat.builder_intents import Ctx
        import os
        _board, self.plan, self.doc, self.path = run_text(self.tmp, self.text, self.parts, name=self.path.name, **self.board_kw)
        for item in self.doc["items"]:             # as the studio names a file: relative to the script's folder
            item["file"] = os.path.relpath(item["file"], self.path.parent) if item.get("file") else ""
        self.ctx = Ctx({self.path.name: self.text}, str(self.path), self.doc, self.data)
        return self.ctx

    def offers(self, subjects, target=None, **params):
        from placemat import builder_intents as bi
        return bi.menu(self.ctx, subjects, target, params)

    def offer(self, subjects, target, intent, **params):
        got = self.offers(subjects, target, **params)
        hit = [o for o in got if o.intent == intent]
        assert hit, "no %r among %s" % (intent, [o.intent for o in got])
        return hit[0]

    def apply(self, edits):
        changed = self.script_edit.apply_edits(edits, lambda p: self.text)
        before, after = changed[str(self.path.resolve())]
        assert before == self.text
        self.text = after
        self.history.append(after)
        self.resolve()
        return after

    def act(self, subjects, target, intent, **params):
        o = self.offer(subjects, target, intent, **params)
        assert not o.needs, "%s still needs %s" % (intent, o.needs)
        return self.apply(o.edits)

    def status(self, key):
        return self.ctx.rows[key]["status"]
