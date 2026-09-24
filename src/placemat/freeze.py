"""freeze: lock entries moved into the script. An item's place() call gets
the arguments that put it where the lock does; the edit is made by the
positions `ast` gives the call and its arguments, so every other byte of
the script - comments, blank lines, the layout of other calls - is left as
it was, and the result is accepted only when the edited script resolves to
the locked placements."""
from __future__ import annotations

import ast


class FreezeError(Exception):
    """A call freeze cannot edit for the item, with the line to see."""


_ENCLOSING = (ast.For, ast.AsyncFor, ast.While, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
              ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _offsets(source: str):
    """(line, UTF-8 byte column) -> character offset into `source`."""
    lines = source.splitlines(keepends=True)
    starts, total = [], 0
    for line in lines:
        starts.append(total)
        total += len(line)

    def at(lineno: int, col: int) -> int:
        text = lines[lineno - 1]
        return starts[lineno - 1] + len(text.encode()[:col].decode(errors="replace"))
    return at, lines


def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _place_call(tree, line: int):
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.lineno == line
             and isinstance(n.func, ast.Attribute) and n.func.attr == "place"]
    if not calls:
        raise FreezeError("line %d: no place() call starts there" % line)
    if len(calls) > 1:
        raise FreezeError("line %d: more than one place() call starts there" % line)
    return calls[0]


def edit_call(source: str, line: int, set_kwargs: dict, remove=()) -> str:
    """`source` with the place() call starting on `line` given each keyword
    in `set_kwargs` (its value text replaced if present, added if not) and
    the keywords in `remove` dropped. A call inside a loop, a function or a
    comprehension declares more than one item and is refused, as is one
    passing * or ** arguments."""
    tree = ast.parse(source)
    call = _place_call(tree, line)
    parents = _parents(tree)
    node = call
    while node in parents:
        node = parents[node]
        if isinstance(node, _ENCLOSING):
            raise FreezeError("line %d: the call is inside a %s, so it declares more than this item; move this "
                              "item's declaration out of it by hand" % (line, type(node).__name__.lower()))
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        raise FreezeError("line %d: the call passes * or ** arguments, which freeze cannot see into" % line)
    at, lines = _offsets(source)

    def span(n):
        return at(n.lineno, n.col_offset), at(n.end_lineno, n.end_col_offset)
    edits = []
    everything = sorted(list(call.args) + list(call.keywords), key=lambda n: (n.lineno, n.col_offset))
    present = {k.arg for k in call.keywords}
    for k in call.keywords:
        if k.arg in set_kwargs:
            s, e = span(k.value)
            edits.append((s, e, set_kwargs[k.arg]))
        elif k.arg in remove:
            i = everything.index(k)
            if i + 1 < len(everything):
                s, e = span(k)[0], span(everything[i + 1])[0]
            elif i > 0:
                s, e = span(everything[i - 1])[1], span(k)[1]
            else:
                s, e = span(k)
            edits.append((s, e, ""))
    missing = [(name, text) for name, text in set_kwargs.items() if name not in present]
    if missing:
        kept = [n for n in everything if not (isinstance(n, ast.keyword) and n.arg in remove)]
        if kept:
            last = kept[-1]
            end = span(last)[1]
            if last.lineno != call.lineno or last.end_lineno != call.lineno:
                row = lines[last.lineno - 1]
                indent = row[:len(row) - len(row.lstrip())]
                text = "".join(",\n%s%s=%s" % (indent, name, value) for name, value in missing)
            else:
                text = "".join(", %s=%s" % (name, value) for name, value in missing)
        else:
            end = at(call.func.end_lineno, call.func.end_col_offset) + 1        # just inside the "("
            text = ", ".join("%s=%s" % (name, value) for name, value in missing)
        edits.append((end, end, text))
    out = source
    for s, e, text in sorted(edits, key=lambda x: x[0], reverse=True):
        out = out[:s] + text + out[e:]
    ast.parse(out)
    return out


def ensure_imports(source: str, names) -> str:
    """`source` with each of `names` imported from placemat: added to the
    first `from placemat import ...` it has, else on a new line after the
    last import at the top."""
    tree = ast.parse(source)
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    froms = [n for n in top if isinstance(n, ast.ImportFrom) and n.module == "placemat" and not n.level]
    have = {a.asname or a.name for n in froms for a in n.names}
    missing = [n for n in names if n not in have]
    if not missing:
        return source
    at, lines = _offsets(source)
    if froms:
        last = froms[0].names[-1]
        end = at(last.end_lineno, last.end_col_offset)
        return source[:end] + "".join(", " + n for n in missing) + source[end:]
    after = top[-1].end_lineno if top else (tree.body[0].end_lineno if tree.body and isinstance(tree.body[0], ast.Expr)
                                              and isinstance(tree.body[0].value, ast.Constant) else 0)
    pos = sum(len(l) for l in lines[:after])
    return source[:pos] + "from placemat import %s\n" % ", ".join(missing) + source[pos:]


# ------------------------------------------------------------ the command
def frozen_args(board, key, turn, fixed: bool) -> dict:
    """The keyword arguments that put an item where its turn did: at its
    anchor pad's point plus the offset in board directions, searched with no
    room to move (the same tier and turn of the order), or `fixed` a firm
    Location, which goes down before everything searched."""
    p = turn["placement"]
    rotation = "%g" % round(p.rotation, 6)
    if turn.get("anchor") is None:
        where = "Location(%s, %s)" % (_n(p.location.x), _n(p.location.y))
        return {"at": where if fixed else "Near(%s, radius=0)" % where, "rotation": rotation}
    ref, number = turn["anchor"]
    fp = board.geometry.footprint(ref)
    a = turn["anchor_at"]
    dx, dy = p.location.x - a.x, p.location.y - a.y
    if number.isdigit():
        pad = "PadRef(Part(%r), %s)" % (fp.inst, number)
    else:
        nets = [q.net for q in fp.pads if q.number == number and q.net]
        if not nets or sum(1 for q in fp.pads if q.net == nets[0]) != 1:
            raise FreezeError("%s: its anchor %s pad %s has no number or net to name it by" % (key, ref, number))
        pad = "PadRef(Part(%r), %r)" % (fp.inst, nets[0])
    if fixed:
        return {"at": "Location(X(%s, %s), Y(%s, %s))" % (pad, _n(dx), pad, _n(dy)), "rotation": rotation}
    return {"at": "Near(%s.offset(%s, %s), radius=0)" % (pad, _n(dx), _n(dy)), "rotation": rotation}


def _n(v: float) -> str:
    s = "%.6f" % round(v, 6)
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def freeze(script, keys, fixed: bool = False) -> dict:
    """Move lock entries (`keys`, or all when None) into the script. Returns
    {frozen, refused, differences}: the script and the lock are written only
    when every placement of the frozen script equals the locked run's."""
    import os
    import tempfile
    from pathlib import Path
    from . import lock as _lock
    from . import settings as settings_mod
    from .explore import BoardFactory
    from .project import fab_profile, find_board
    from .runner import cached_generation, scripted_board
    script = Path(script).resolve()
    path = _lock.path_for(script)
    entries = _lock.read(path)
    chosen = [e for e in entries if keys is None or e.key in keys]
    unknown = sorted(set(keys or ()) - {e.key for e in entries})
    if unknown:
        raise FreezeError("no lock entry for %s (the lock has %s)" % (", ".join(unknown),
                          ", ".join(e.key for e in entries) or "none"))
    report = {"frozen": [], "refused": [], "differences": []}
    if not chosen:
        return report
    src = find_board(script)
    cfg = settings_mod.load(src.board_dir)
    generated = cached_generation(src) / src.pcb.name
    with settings_mod.bind(cfg):
        fab = fab_profile(src.board_dir)
        board = scripted_board(script, src, cfg, fab, keep_going=True, pcb=generated if generated.exists() else None)
        locked = board.resolve(lock=entries)
        intents = {i.key: i for i in board._placements()}
        text = script.read_text()
        edits = []
        for e in chosen:
            i, turn = intents.get(e.key), locked.turns.get(e.key)
            try:
                if i is None or turn is None:
                    raise FreezeError("%s: not placed by the locked run" % e.key)
                if fixed and turn.get("anchor") is not None:
                    owner = next((o for o in intents.values() if any(fp.ref == turn["anchor"][0]
                                  for fp in _members(o.item))), None)
                    if owner is None or not owner.freedom.decided:
                        raise FreezeError("%s: --fixed refers to its anchor %s, which is searched: only a fixed or "
                                          "edge item may be referred to" % (e.key, turn["anchor"][0]))
                edits.append((i.line, e.key, frozen_args(board, e.key, turn, fixed)))
            except FreezeError as err:
                report["refused"].append(str(err))
        for line, key, args in sorted(edits, key=lambda x: -x[0]):
            try:
                text = edit_call(text, line, args, remove=("rotations",))
                report["frozen"].append(key)
            except FreezeError as err:
                report["refused"].append("%s: %s" % (key, err))
        if not report["frozen"]:
            return report
        text = ensure_imports(text, ["Near", "PadRef", "Part"] + (["Location", "X", "Y"] if fixed else ["Location"]))
        remaining = [e for e in entries if e.key not in report["frozen"]]
        fd, tmp = tempfile.mkstemp(suffix=".py", prefix="." + script.stem + ".freeze.", dir=str(script.parent))
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
            trial = BoardFactory(Path(tmp), src, cfg, fab, True, board.geometry)().resolve(lock=remaining)
        finally:
            os.unlink(tmp)
        want = {s.item: s.placement for s in locked.steps if s.placement is not None}
        got = {s.item: s.placement for s in trial.steps if s.placement is not None}
        for k in sorted(set(want) | set(got)):
            if want.get(k) != got.get(k):
                report["differences"].append("%s: %s -> %s" % (k, want.get(k), got.get(k)))
        if report["differences"]:
            report["frozen"] = []
            return report
    script.write_text(text)
    _lock.write(path, remaining)
    return report


def _members(item):
    from .board_geometry import members_of
    return members_of(item)
