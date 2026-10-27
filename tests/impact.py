"""Which slow tests a change reaches: `pytest --full --impact REF` runs the default suite and, of the slow tests, those
a change since REF reaches.

tests/impact_map.json holds, for each slow test, what it touched when it last ran recorded
(`PLACEMAT_IMPACT_RECORD=<dir> pytest --full`, then `python tests/update_impact_map.py <dir>`):

- `funcs`: the repository's functions it ran, as "path::qualified name" (sys.monitoring, each code object once; a
  module's own body is "path::<module>");
- `opened`: the repository's other files (not Python sources, which importing opens) it opened from Python or loaded
  into pcbnew;
- `spawns`: true when it started placemat in another process (a subprocess of this Python, or a fork), whose code
  the record cannot see: such a test runs on every change.

A slow test is run when a function it ran changed (its decorators, signature or body), when a changed file is one it
opened or shares a folder at least two levels deep with one (fixtures/<module>/...: a module's other files), or when
it has no entry. Some changes run every slow test, because the record cannot say which tests they reach: a path under
RUN_ALL, a deleted Python file of the repository, or one whose statements run on import changed (`reaches_only_code`:
a constant, a class attribute, a base). Such a change to a test file runs every slow test of that file.

What the record cannot see, and so a selection misses: a slow test that iterates over a whole registry is not reached
by an entry added to it (a new setting, a new renderer registered by its decorator), since it never ran the new code.
Tests that enumerate a registry belong in the default suite, which always runs."""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = Path(__file__).with_name("impact_map.json")
RECORD_ENV = "PLACEMAT_IMPACT_RECORD"
# Paths whose change reaches every slow test: the native module (its code is not recorded), the environment, and how
# the suite itself selects.
RUN_ALL = ("native/", "pyproject.toml", "uv.lock", "tests/impact.py")
_TOOL = sys.monitoring.PROFILER_ID if hasattr(sys, "monitoring") else None


# ------------------------------------------------------------------ recording

class Recorder:
    """What each test touches, kept for the session and written by `write`."""

    def __init__(self):
        self.entries: dict = {}
        self.current = None
        self._root = str(ROOT) + os.sep

    def start(self):
        mon = sys.monitoring
        mon.use_tool_id(_TOOL, "placemat-impact")
        mon.register_callback(_TOOL, mon.events.PY_START, self._started)
        mon.set_events(_TOOL, mon.events.PY_START)
        sys.addaudithook(self._audit)
        try:
            import pcbnew
        except ImportError:
            return
        for name in ("LoadBoard", "FootprintLoad", "FootprintEnumerate"):
            real = getattr(pcbnew, name, None)
            if real is not None:
                setattr(pcbnew, name, self._loading(real))

    def begin(self, nodeid: str):
        self.current = {"funcs": set(), "opened": set(), "spawns": False}
        sys.monitoring.restart_events()
        self.entries[nodeid] = self.current

    def end(self):
        self.current = None

    def _rel(self, path) -> str | None:
        try:
            p = os.path.abspath(os.fspath(path))
        except TypeError:
            return None
        return p[len(self._root):] if p.startswith(self._root) else None

    def _started(self, code, offset):
        if self.current is not None:
            rel = self._rel(code.co_filename)
            if rel is not None and rel.endswith(".py"):
                self.current["funcs"].add("%s::%s" % (rel, code.co_qualname))
        return sys.monitoring.DISABLE

    def _audit(self, event, args):
        cur = self.current
        if cur is None:
            return
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            rel = self._rel(args[0] if not isinstance(args[0], bytes) else os.fsdecode(args[0]))
            if rel is not None and not rel.endswith((".py", ".pyc")) and "__pycache__" not in rel:
                cur["opened"].add(rel)
        elif event == "os.fork":
            cur["spawns"] = True
        elif event == "subprocess.Popen" and len(args) > 1:
            argv = [os.fsdecode(a) if isinstance(a, bytes) else str(a) for a in (args[1] or [])]
            # this environment's Python (by its path: another venv's, the router's, links to the same binary) or
            # placemat's own command
            if argv and (os.path.abspath(argv[0]) == os.path.abspath(sys.executable) or "placemat" in argv[:3]):
                cur["spawns"] = True

    def _loading(self, real):
        def load(path, *a, **k):
            if self.current is not None:
                rel = self._rel(path)
                if rel is not None:
                    self.current["opened"].add(rel)
            return real(path, *a, **k)
        return load

    def write(self, out_dir: str, worker: str):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        doc = {k: {"funcs": sorted(v["funcs"]), "opened": sorted(v["opened"]), "spawns": v["spawns"]}
               for k, v in self.entries.items()}
        (Path(out_dir) / ("impact-%s-%d.json" % (worker, os.getpid()))).write_text(json.dumps(doc))


# ------------------------------------------------------------------ the map

def pack(entries: dict) -> dict:
    """The map as written: the functions once, in a table, and each test's as indices into it."""
    table = sorted({f for v in entries.values() for f in v["funcs"]})
    index = {f: k for k, f in enumerate(table)}
    return {"functions": table,
            "tests": {t: {"funcs": sorted(index[f] for f in v["funcs"]), "opened": sorted(v["opened"]),
                          "spawns": v["spawns"]} for t, v in sorted(entries.items())}}


def load_map() -> dict:
    """{test id: {"funcs": set, "opened": set, "spawns": bool}} from tests/impact_map.json; empty without it."""
    if not MAP.exists():
        return {}
    doc = json.loads(MAP.read_text())
    table = doc["functions"]
    return {t: {"funcs": {table[k] for k in v["funcs"]}, "opened": set(v["opened"]), "spawns": v["spawns"]}
            for t, v in doc["tests"].items()}


# ------------------------------------------------------------------ what changed

def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def changed_paths(ref: str) -> list:
    """The paths that differ between `ref` and the working tree, as (status, path)."""
    out = []
    for line in _git("diff", "--name-status", "--no-renames", ref).splitlines():
        status, _, path = line.partition("\t")
        out.append((status[:1], path))
    return out


def _old_source(ref: str, path: str) -> str | None:
    try:
        return _git("show", "%s:%s" % (ref, path))
    except subprocess.CalledProcessError:
        return None


def _spans(tree) -> list:
    """(first line, last line, qualified name) of every function, as code objects name them: `Class.method`,
    `outer.<locals>.inner`; from its first decorator to its last line."""
    out = []

    def walk(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                first = min([node.lineno] + [d.lineno for d in node.decorator_list])
                out.append((first, node.end_lineno, name))
                walk(node.body, name + ".<locals>.")
            elif isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + ".")
            else:
                for field in ("body", "orelse", "finalbody", "handlers"):      # if/try/with/for at the same level
                    inner = getattr(node, field, None)
                    if isinstance(inner, list):
                        walk(inner, prefix)
    walk(tree.body, "")
    return out


def _hunks(ref: str, path: str) -> tuple:
    """(lines of `ref`'s file, lines of the working tree's) the diff of `path` touches; a hunk that only adds or only
    deletes touches the lines either side of where it is on the side it leaves alone."""
    old, new = [], []
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", _git("diff", "-U0", ref, "--", path), re.M):
        for side, start, count in ((old, int(m.group(1)), int(m.group(2) or 1)),
                                   (new, int(m.group(3)), int(m.group(4) or 1))):
            side.extend(range(start, start + count) if count else (start, start + 1))
    return old, new


def changed_functions(ref: str, path: str) -> set:
    """"path::qualified name" of each function of `path` a line changed since `ref` falls in, on either side: the
    innermost holding it."""
    old_lines, new_lines = _hunks(ref, path)
    out = set()
    for source, lines in ((_old_source(ref, path), old_lines), ((ROOT / path).read_text(), new_lines)):
        if source is None:
            continue
        spans = _spans(ast.parse(source))
        for n in lines:
            holding = [s for s in spans if s[0] <= n <= s[1]]
            if holding:
                out.add("%s::%s" % (path, max(holding, key=lambda s: s[0])[2]))
    return out


def _statements(tree) -> dict:
    """The statements of a module that run when it is imported, outside its functions, each as (scope, names it binds,
    its dump) -> the statement: module level and class bodies (scope: the dotted class path, "" at module level). A function is only its
    name: what it does, its signature included, reaches only its callers, which the map follows by the code they run.
    A class is its name, bases, keywords and decorators, and its body's statements. An import is one entry per name.
    Docstrings are left out."""
    out = {}

    def walk(body, scope):
        for node in body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[(scope, frozenset([node.name]), "def")] = node
            elif isinstance(node, ast.ClassDef):
                head = ast.dump(ast.ClassDef(node.name, node.bases, node.keywords, [], node.decorator_list, []))
                out[(scope, frozenset([node.name]), head)] = node
                walk(node.body, scope + "." + node.name if scope else node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    one = type(node)(**{**{f: getattr(node, f) for f in node._fields}, "names": [alias]})
                    out[(scope, frozenset([name]), ast.dump(one))] = one
            else:
                out[(scope, frozenset(_binds(node)), ast.dump(node))] = node
    walk(tree.body, "")
    return out


def _strings(value):
    """(the container's form, its strings) of a literal list, tuple or set of strings, bare or passed whole to
    frozenset/set/tuple/list; None for any other value."""
    wrap = None
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and len(value.args) == 1 and not value.keywords \
            and value.func.id in ("frozenset", "set", "tuple", "list"):
        wrap, value = value.func.id, value.args[0]
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts):
        return (wrap, type(value).__name__), [e.value for e in value.elts]
    return None


def _grown_registry(old, new, added: set) -> bool:
    """Whether `new` is `old`, a registry, with only entries put in: a list of names (of settings, say) that gains only
    names the change adds, each string of `old` kept in order; or a dict literal with string keys that gains entries
    under new keys, every entry of `old` the same."""
    if type(old) is not type(new) or not isinstance(old, (ast.Assign, ast.AnnAssign)) or not old.value or not new.value:
        return False
    targets = (lambda n: ast.dump(ast.Module(n.targets if isinstance(n, ast.Assign) else [n.target], [])))
    if targets(old) != targets(new):
        return False
    if isinstance(old.value, ast.Dict) and isinstance(new.value, ast.Dict):
        entries = [{k.value: ast.dump(v) for k, v in zip(d.keys, d.values)} if all(
            isinstance(k, ast.Constant) and isinstance(k.value, str) for k in d.keys) else None
            for d in (old.value, new.value)]
        return None not in entries and all(entries[1].get(k) == v for k, v in entries[0].items())
    a, b = _strings(old.value), _strings(new.value)
    if a is None or b is None or a[0] != b[0]:
        return False
    kept = [x for x in b[1] if x in set(a[1])]
    return kept == a[1] and set(b[1]) - set(a[1]) <= added


def _binds(node) -> set:
    """The plain names an assignment binds at its own level; none for any other statement."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    names = {t.id for t in targets if isinstance(t, ast.Name)}
    return names if names and len(names) == len(targets) else set()


def reaches_only_code(ref: str, path: str) -> bool:
    """Whether the change to the Python file `path` since `ref` leaves what the module does on import as it was, but
    for names it adds or drops: every statement outside its functions is the same, moved or not, or binds only names
    the other side does not have (a new constant, function, class or import, whose only users are changed code; or
    one taken away with its users), or a list of names that gains only names the change adds (`_grown_registry`). A
    changed constant, class attribute or base, or a statement with no name, is not; nor is a file that does not
    parse."""
    try:
        new = _statements(ast.parse((ROOT / path).read_text()))
    except (OSError, SyntaxError):
        return False
    source = _old_source(ref, path)
    if source is None:
        return True                 # a new file: it runs only where changed code imports it
    try:
        old = _statements(ast.parse(source))
    except SyntaxError:
        return False
    names = {side: {(scope, n) for scope, binds, _ in stmts for n in binds} for side, stmts in (("old", old), ("new", new))}
    added = {n for _, n in names["new"] - names["old"]}
    gone_old = {k: old[k] for k in old.keys() - new.keys()}
    gone_new = {k: new[k] for k in new.keys() - old.keys()}
    for (scope, binds, _), node in gone_new.items():
        if binds and not {(scope, n) for n in binds} & names["old"]:
            continue                                    # a name the change adds
        twins = [o for (sc, bs, _), o in gone_old.items() if sc == scope and bs == binds]
        if not binds or len(twins) != 1 or not _grown_registry(twins[0], node, added):
            return False
    for (scope, binds, _), node in gone_old.items():
        if binds and not {(scope, n) for n in binds} & names["new"]:
            continue                                    # a name the change takes away
        if not any(sc == scope and bs == binds for sc, bs, _ in gone_new):
            return False
    return True


def _folders(path: str) -> list:
    """The folders holding `path` at least two levels deep: fixtures/a/b/c.pcb -> fixtures/a, fixtures/a/b."""
    parts = path.split("/")[:-1]
    return ["/".join(parts[:n]) for n in range(2, len(parts) + 1)]


def selected(ref: str, slow_ids, entries: dict) -> set | None:
    """The slow test ids a change since `ref` reaches, or None when it reaches them all."""
    pick: set = set()
    dirs_of = {k: {d for p in v["opened"] for d in _folders(p)} for k, v in entries.items()}
    for status, path in changed_paths(ref):
        if path.startswith(RUN_ALL):
            return None
        if path.endswith(".py"):
            if status == "D" or not reaches_only_code(ref, path):
                if not path.startswith("tests/test_") or status == "D":
                    return None
                pick |= {t for t in slow_ids if t.split("::", 1)[0] == path}
                continue
            funcs = changed_functions(ref, path)
            pick |= {t for t in slow_ids if t in entries and entries[t]["funcs"] & funcs}
            continue
        folders = set(_folders(path))
        pick |= {t for t in slow_ids if t in entries and (path in entries[t]["opened"] or folders & dirs_of[t])}
    pick |= {t for t in slow_ids if t not in entries or entries[t]["spawns"]}
    return pick
