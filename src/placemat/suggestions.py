"""Suggestions: changes to a layout script that may clear a finding.

A suggestion is a structured script edit (`Edit`) with its wording, made where the finding
is raised, from the facts the site measured. Every surface reads the same records and
applies them through one function, `apply_suggestion`.

The records and their JSON come first, then binding to a script (`bind`), applying and
undoing (`apply_suggestion`, `undo_last`), and last the case builders: one function per
finding case, from the facts its raising site measured to the suggestions."""
from __future__ import annotations

import difflib
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path


class SuggestionError(Exception):
    """A suggestion that cannot be shown, applied or undone; the message says why."""


@dataclass(frozen=True)
class Target:
    """The declaration an edit changes: what kind of call (`place`, `link`, `keepout`, `label`, `track`, ...),
    its key (the item, keepout name, track key, or `A.1>B.3` for a link), and, once bound to a script, the file and
    line it was declared on, how many declarations share that file, line and kind (a loop or helper: more than
    one), and the file's digest at the plan."""
    kind: str
    key: str
    file: str = ""
    line: int = 0
    shared: int = 1
    digest: str = ""

    def to_json(self) -> dict:
        out = {"kind": self.kind, "key": self.key}
        if self.file:
            out.update(file=self.file, line=self.line, shared=self.shared, digest=self.digest)
        return out

    @staticmethod
    def from_json(d: dict) -> "Target":
        return Target(d["kind"], d["key"], d.get("file", ""), d.get("line", 0), d.get("shared", 1), d.get("digest", ""))


@dataclass(frozen=True)
class Edit:
    """What to write. `op` is one of script_edit.OPS; `target` the declaration it changes (None for `toml_set` and
    `set_constant`, whose `file` names the file); `args` the op's arguments; `value` an intent expression (never
    source); `refs` binds each item an expression names to its own declaration, so the script's spelling of it is
    found."""
    op: str
    target: Target | None = None
    args: dict = field(default_factory=dict)
    value: object = None
    refs: dict = field(default_factory=dict)
    file: str = ""

    def to_json(self) -> dict:
        out = {"op": self.op, "args": self.args}
        if self.target is not None:
            out["target"] = self.target.to_json()
        if self.value is not None:
            out["value"] = self.value
        if self.refs:
            out["refs"] = {k: t.to_json() for k, t in self.refs.items()}
        if self.file:
            out["file"] = self.file
        return out

    @staticmethod
    def from_json(d: dict) -> "Edit":
        return Edit(d["op"], Target.from_json(d["target"]) if d.get("target") else None, d.get("args", {}),
                    d.get("value"), {k: Target.from_json(t) for k, t in d.get("refs", {}).items()}, d.get("file", ""))


def _const_of(value):
    return value.get("const") if isinstance(value, dict) and isinstance(value.get("const"), dict) else None


@dataclass(frozen=True)
class Suggestion:
    text: str
    edit: Edit
    rank: int = 1
    lever: str = ""                 # suggestions of one lever are variants; the cap per lever is a setting
    id: str = ""                    # "s3a": finding 3, suggestion a; given by bind
    digests: dict = field(default_factory=dict)     # {file: digest} of each file the edit writes, at the plan

    def to_json(self) -> dict:
        out = {"id": self.id, "text": self.text, "rank": self.rank, "lever": self.lever, "edit": self.edit.to_json()}
        if self.digests:
            out["digests"] = dict(self.digests)
        return out

    @staticmethod
    def from_json(d: dict) -> "Suggestion":
        return Suggestion(d["text"], Edit.from_json(d["edit"]), d.get("rank", 1), d.get("lever", ""), d.get("id", ""),
                          dict(d.get("digests", {})))


def to_json(suggestions) -> list:
    return [s.to_json() for s in suggestions]


def from_json(items) -> list:
    return [Suggestion.from_json(d) for d in items or ()]


# ------------------------------------------------------------------ errors
class UnknownSuggestion(SuggestionError, KeyError):
    """No suggestion has this id in the plan's suggestions."""

    def __str__(self):
        return Exception.__str__(self)


class StaleSuggestion(SuggestionError):
    """A file the suggestion was made from has changed since the plan: nothing is written. `files` names them."""

    def __init__(self, files):
        self.files = list(files)
        super().__init__("%s changed since the plan was made: resolve again for suggestions that fit it"
                         % ", ".join(self.files))


class EditRefused(SuggestionError):
    """The edit would not do what it says, or could not be checked, or may not be written. `reason` says why."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class NothingToUndo(SuggestionError):
    pass


class UndoRefused(SuggestionError):
    """The file is not as the apply left it, so putting it back would undo someone else's change as well."""


# ------------------------------------------------------------------ the cases
CASES: dict = {}
"""{case id: builder}: a builder takes the facts the raising site measured and returns the suggestions, best first,
each a `Pick`. The id is `kind.case`, as a finding's `case` says."""


@dataclass(frozen=True)
class Pick:
    """What a builder offers before the engine has bound it: the wording, the edit and the lever it belongs to."""
    text: str
    edit: Edit
    lever: str = ""


def case(name):
    def register(fn):
        CASES[name] = fn
        return fn
    return register


def suggest(case_id: str, facts: dict, settings=None) -> list:
    """The suggestions for a finding of this case from the facts its site measured, unbound, ranked 1..n in the order
    the builder gave them, at most `[studio] suggestions_per_lever` to a lever. A case with no builder, or facts the
    builder finds nothing to offer for, gives none."""
    builder = CASES.get(case_id)
    if builder is None:
        return []
    from .settings import Settings
    settings = settings or Settings()
    cap = settings.studio_suggestions_per_lever
    seen: dict = {}
    out = []
    for pick in builder(facts, settings) or ():
        n = seen.get(pick.lever, 0)
        if pick.lever and n >= cap:
            continue
        seen[pick.lever] = n + 1
        out.append(Suggestion(pick.text, pick.edit, len(out) + 1, pick.lever))
    return out


# ------------------------------------------------------------------ binding to a script
def _letters(n: int) -> str:
    out, n = "", n + 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(97 + r) + out
    return out


class _Binder:
    """Gives a finding's suggestions the file, the line and the digest of the declarations they edit, as the board
    recorded them, and drops one whose edit cannot be made on the script as it stands."""

    def __init__(self, board):
        self.board = board
        self.script = getattr(board, "script_file", "")

    def target(self, t: Target):
        sites = self.board.sites_of(t.kind, t.key)
        if len(sites) != 1:
            return None
        site = sites[0]
        digest = self.board.file_digest(site.file)
        if not digest:
            return None
        return Target(t.kind, t.key, site.file, site.line, self.board.shared_by(site), digest)

    def settings_file(self):
        """(the placemat.toml nearest the script, the script's path relative to it) or None."""
        from .settings import _files
        if not self.script:
            return None
        found = _files(Path(self.script).parent)
        if not found:
            return None
        toml = found[-1]
        try:
            rel = Path(self.script).resolve().relative_to(toml.parent.resolve()).as_posix()
        except ValueError:
            return None
        return str(toml), rel

    def constants_file(self, scope: str, call_file: str) -> str:
        """Where a named constant goes: a cell's own in the file of the call; a board-wide one in the module the
        board's scripts share where the board's script has one, else in the board's script."""
        if scope == "board" and self.script and call_file == self.script:
            from . import script_edit
            return script_edit.shared_module(self.script) or call_file
        return call_file

    def bind(self, s: Suggestion) -> list:
        edit = s.edit
        refs = {}
        for k, t in edit.refs.items():
            bound = self.target(t)
            if bound is None:
                return []
            refs[k] = bound
        target = None
        if edit.target is not None:
            target = self.target(edit.target)
            if target is None:
                return []
        file, args = edit.file, dict(edit.args)
        if edit.op == "toml_set":
            found = self.settings_file()
            if found is None:
                return []
            file = found[0]
            args["table"] = ["scripts", found[1], args.pop("section")]
        home = target.file if target else file
        value = _bind_consts(edit.value, lambda c: self.constants_file(c.get("scope", "cell"), home))
        bound = Edit(edit.op, target, args, value, refs, file)
        out = []
        for variant in self.variants(s, bound):
            made = self.check(*variant)
            if made is not None:
                out.append(made)
        return out

    def variants(self, s: Suggestion, edit: Edit) -> list:
        """The suggestion as it stands; or, where the keyword it sets already reads a constant of the script's,
        two: change that constant, or give this one use a constant of its own."""
        from . import script_edit
        const = _const_of(edit.value)
        if edit.op != "set_kwarg" or const is None or edit.target is None:
            return [(s, edit)]
        try:
            existing = script_edit.keyword_constant(self.board._source_text(edit.target.file), edit.target,
                                                    edit.args["name"])
        except (script_edit.EditRefused, OSError):
            existing = None
        if existing is None:
            return [(s, edit)]
        change = Edit("set_constant", None, {"name": existing, "existing": True, "comment": const.get("comment", "")},
                      const["value"], {}, edit.target.file)
        return [(replace(s, text="%s, by changing %s (every use of it changes)" % (s.text, existing)), change),
                (replace(s, text="%s, with a constant of its own" % s.text), edit)]

    def check(self, s: Suggestion, edit: Edit):
        """The suggestion with its edit bound and its digests, if the edit can be made on the script as it stands."""
        from . import script_edit
        try:
            changed = script_edit.apply_all(edit, self.board._source_text)
        except (script_edit.EditRefused, OSError, UnicodeDecodeError, KeyError):
            return None
        digests = {}
        for path, (before, _) in changed.items():
            now = script_edit.digest(before)
            seen = self.board._file_digests.get(path)
            if seen and seen != now:
                return None             # the file was edited while the resolve ran: its lines are not these
            digests[path] = now
        return replace(s, edit=edit, digests=digests)


def _bind_consts(value, file_of):
    if isinstance(value, dict):
        if isinstance(value.get("const"), dict):
            c = dict(value["const"])
            c["file"] = file_of(c)
            return dict(value, const=c)
        return {k: _bind_consts(v, file_of) for k, v in value.items()}
    if isinstance(value, list):
        return [_bind_consts(v, file_of) for v in value]
    return value


def bind(findings, board) -> None:
    """Bind the suggestions of every finding that has unbound ones. Ids are `s<finding number><letter>`, the number
    being the finding's place in `findings` from 1. Each suggestion gets its edit's file, line and digest from where
    the board recorded the declaration, and is dropped when its edit cannot be made on the script as it stands or
    would change a call that declares several items. Called at the end of a resolve, and again for findings added
    after it."""
    binder = _Binder(board)
    for n, f in enumerate(findings, 1):
        if f.case and f.facts and not f.suggestions and not getattr(f, "_built", False):
            f.suggestions = tuple(suggest(f.case, f.facts, board.settings))
            f._built = True
        pending = [s for s in f.suggestions if not s.id]
        if not pending:
            continue
        kept = [b for s in pending for b in binder.bind(s)]
        f.suggestions = tuple(replace(s, rank=i + 1, id="s%d%s" % (n, _letters(i))) for i, s in enumerate(kept))


def flatten(findings) -> list:
    """Every bound suggestion of these findings, in finding order."""
    return [s for f in findings for s in f.suggestions if s.id]


# ------------------------------------------------------------------ applying
@dataclass
class FileChange:
    file: str
    before: str
    after: str

    @property
    def diff(self) -> str:
        return "".join(difflib.unified_diff(self.before.splitlines(keepends=True), self.after.splitlines(keepends=True),
                                            "a/" + self.file, "b/" + self.file))

    def _ops(self):
        a, b = self.before.splitlines(), self.after.splitlines()
        return [op for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]

    @property
    def old_lines(self) -> list:
        """The 1-based lines of `before` the edit changed or removed."""
        return [n for tag, i1, i2, j1, j2 in self._ops() if tag in ("replace", "delete") for n in range(i1 + 1, i2 + 1)]

    @property
    def new_lines(self) -> list:
        """The 1-based lines of `after` the edit wrote."""
        return [n for tag, i1, i2, j1, j2 in self._ops() if tag in ("replace", "insert") for n in range(j1 + 1, j2 + 1)]


@dataclass
class Applied:
    """What an apply (or a dry run, or an undo) did: each file's text before and after."""
    id: str
    text: str
    files: dict
    dry_run: bool = False

    def diff(self) -> str:
        return "".join(c.diff for c in self.files.values())


def find(suggestions, id: str) -> Suggestion:
    for s in suggestions:
        if s.id == id:
            return s
    raise UnknownSuggestion("no suggestion %s in this plan" % id)


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _write_atomic(path: str, text: str) -> None:
    """The file's new text, written to a temporary file beside it and moved over it, keeping its mode."""
    p = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        if p.exists():
            os.chmod(tmp, p.stat().st_mode & 0o7777)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _inside(root, path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def apply_suggestion(suggestions, id: str, dry_run: bool = False, *, root=None, log=None, now=None) -> Applied:
    """Apply the suggestion `id` of `suggestions` to the files it edits, or, with `dry_run`, work out what that would
    write and write nothing. Every file the edit writes must be as the plan saw it (its digest): if one has changed
    nothing is written (StaleSuggestion). The files are written atomically; the apply is appended to `log`
    (`.placemat/applied.jsonl`), and may be undone by `undo_last`. A write needs `root` (only files under it are
    written) and `log`. Errors are SuggestionErrors: UnknownSuggestion, StaleSuggestion, EditRefused."""
    from . import script_edit
    s = find(suggestions, id)
    if not dry_run and (root is None or log is None):
        raise ValueError("applying a suggestion needs the project root it may write under and the log to record it in")
    stale = []
    for path, want in s.digests.items():
        try:
            if script_edit.digest(_read(path)) != want:
                stale.append(path)
        except OSError:
            stale.append(path)
    if stale:
        raise StaleSuggestion(stale)
    try:
        changed = script_edit.apply_all(s.edit, _read)
    except script_edit.StaleEdit as e:
        raise StaleSuggestion(e.files) from None
    except script_edit.EditRefused as e:
        raise EditRefused(e.reason) from None
    except OSError as e:
        raise EditRefused("cannot read %s" % (e.filename or e)) from None
    files = {p: FileChange(p, before, after) for p, (before, after) in changed.items()}
    result = Applied(s.id, s.text, files, dry_run)
    if dry_run:
        return result
    outside = [p for p in files if not _inside(root, p)]
    if outside:
        raise EditRefused("%s is outside the project, which a suggestion does not write" % ", ".join(outside))
    _write_all(files)
    _append(log, {"op": "apply", "id": s.id, "text": s.text, "at": _stamp(now),
                  "files": [{"file": p, "before": c.before, "after": c.after} for p, c in files.items()]})
    return result


def _write_all(files: dict) -> None:
    done = []
    try:
        for p, c in files.items():
            _write_atomic(p, c.after)
            done.append(p)
    except BaseException:
        for p in done:                  # a later file failed: the earlier ones go back
            try:
                _write_atomic(p, files[p].before)
            except OSError:
                pass
        raise


def _stamp(now) -> str:
    return (now if now is not None else time.strftime("%Y-%m-%dT%H:%M:%S%z"))


def _append(log, entry: dict) -> None:
    path = Path(log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def applied_entries(log) -> list:
    """The applied log as [{"seq", "id", "text", "at", "files", "undone"}], oldest first: what the studio's history
    lists as applied from a suggestion."""
    path = Path(log)
    if not path.exists():
        return []
    entries, undone = [], set()
    for seq, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        e["seq"] = seq
        if e.get("op") == "undo":
            undone.add(e.get("of"))
        else:
            entries.append(e)
    for e in entries:
        e["undone"] = e["seq"] in undone
    return entries


def undo_last(log, *, root=None, dry_run: bool = False, now=None) -> Applied:
    """Put back what the last apply that has not been undone changed, if each file is still as that apply wrote it
    (nothing else has touched it since); otherwise refuse (UndoRefused) and write nothing. The undo is logged, so
    undoing again reverts the apply before it."""
    pending = [e for e in applied_entries(log) if not e["undone"]]
    if not pending:
        raise NothingToUndo("nothing applied is left to undo")
    e = pending[-1]
    moved = []
    for f in e["files"]:
        try:
            if _read(f["file"]) != f["after"]:
                moved.append(f["file"])
        except OSError:
            moved.append(f["file"])
    if moved:
        raise UndoRefused("%s changed since %s was applied, so it is not put back: undo would take someone else's "
                          "change with it" % (", ".join(moved), e["id"]))
    files = {f["file"]: FileChange(f["file"], f["after"], f["before"]) for f in e["files"]}
    result = Applied(e["id"], e["text"], files, dry_run)
    if dry_run:
        return result
    if root is not None:
        outside = [p for p in files if not _inside(root, p)]
        if outside:
            raise EditRefused("%s is outside the project, which a suggestion does not write" % ", ".join(outside))
    _write_all(files)
    _append(log, {"op": "undo", "of": e["seq"], "id": e["id"], "text": e["text"], "at": _stamp(now),
                  "files": [{"file": p, "before": c.before, "after": c.after} for p, c in files.items()]})
    return result


# ------------------------------------------------------------------ builders: helpers
def _name(*parts) -> str:
    """A constant's name from an item and a keyword: `C4_LINK_LIMIT_MM`."""
    import re
    return "_".join(p for p in (re.sub(r"[^A-Za-z0-9]+", "_", str(x)).strip("_").upper() for x in parts) if p)


def _item(key):
    return {"item": key}


def _enum(text):
    return {"enum": text}


def _form(name, *args, **kwargs):
    return {"form": name, "args": list(args), "kwargs": kwargs}


def _const(name, value, comment, scope="cell"):
    return {"const": {"name": name, "value": value, "comment": comment, "scope": scope}}


def _refs_of(value, out=None):
    """The items an intent expression names, each bound to its own `place` declaration."""
    out = {} if out is None else out
    if isinstance(value, dict):
        if "item" in value:
            out[value["item"]] = Target("place", value["item"])
        for v in value.values():
            _refs_of(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _refs_of(v, out)
    return out


def _set(kind, key, name, value, text, lever="") -> Pick:
    edit = Edit("set_kwarg", Target(kind, key), {"name": name}, value, _refs_of(value))
    return Pick(text, edit, lever)


def _unset(kind, key, name, text, lever="") -> Pick:
    return Pick(text, Edit("remove_kwarg", Target(kind, key), {"name": name}), lever)


def _add_to(kind, key, arg, element, text, lever="", create=True) -> Pick:
    edit = Edit("edit_list", Target(kind, key), {"arg": arg, "action": "add", "create": create}, element,
                _refs_of(element))
    return Pick(text, edit, lever)


def _setting(section, key, value, text, comment, lever="") -> Pick:
    edit = Edit("toml_set", None, {"section": section, "key": key, "comment": comment}, value)
    return Pick(text, edit, lever)


def _beside(neighbour, side):
    return _form("Beside", _item(neighbour), _enum("Edge.%s" % side))


def _said(measure: str, what: str) -> str:
    return "Measured by a run's finding: %s" % what if measure else what


def _mm(x) -> str:
    return "%.2f" % x


def _side_word(side: str) -> str:
    return side.lower()


# ------------------------------------------------------------------ builders: link_over
_WEIGHTS = (("FREE", 0), ("DEFAULT", 1), ("PREFER", 2), ("SHORT", 8))


@case("link_over")
def link_over(f, settings):
    a, b = f["a"], f["b"]
    out = []
    for side in f.get("free_sides", ()):
        out.append(_set("place", a["key"], "at", _beside(b["key"], side),
                        "Place %s beside %s, on its %s side" % (a["key"], b["key"], _side_word(side)), "beside"))
    nxt = next(((n, v) for n, v in _WEIGHTS if v > f.get("weight", 1)), None)
    if nxt is not None:
        out.append(_set("link", f["link"], "weight", _enum("LinkWeight.%s" % nxt[0]),
                        "Pull %s pad %s to %s pad %s harder" % (a["key"], a["pad"], b["key"], b["pad"]), "weight"))
    if f.get("a_searched", True) and f.get("a_priority") != "high":
        out.append(_set("place", a["key"], "priority", _enum("Priority.HIGH"),
                        "Place %s before the parts that crowd it" % a["key"], "priority"))
    limit = math.ceil(f["achieved"] * 100 - 1e-9) / 100
    out.append(_set("link", f["link"], "limit_mm",
                    _const(_name(a["key"], "link", "limit", "mm"), limit,
                           "Measured by a run's finding (link_over): %s pad %s to %s pad %s was %s mm, over its %s mm limit."
                           % (a["key"], a["pad"], b["key"], b["pad"], _mm(f["achieved"]), _mm(f["limit"]))),
                    "Raise the limit to %s mm" % _mm(limit), "limit"))
    return out


# ------------------------------------------------------------------ builders: label
def _label_picks(f, settings):
    out = []
    ref = f["key"].split(" ", 2)[1]
    for side in f.get("sides", ()):
        out.append(_set("label", f["key"], "side", _enum("Edge.%s" % side),
                        "Move the label of %s to its %s side" % (ref, _side_word(side)), "side"))
    size = f.get("size")
    if size:
        smaller = round(size / settings.studio_suggest_factor, 2)
        out.append(_set("label", f["key"], "size",
                        _const(_name(ref, "label", "size", "mm"), smaller,
                               "A run's finding (%s) said the label of %s was in the way: %s mm is the label size %s "
                               "mm divided by studio.suggest_factor." % (f["case"], ref, _mm(smaller), _mm(size))),
                        "Make the label of %s smaller" % ref, "size"))
    return out


@case("label.sits_on")
def label_sits_on(f, settings):
    return _label_picks(dict(f, case="label.sits_on"), settings)


@case("label.no_spot")
def label_no_spot(f, settings):
    return _label_picks(dict(f, case="label.no_spot"), settings)


@case("label.not_drawn")
def label_not_drawn(f, settings):
    return []


# ------------------------------------------------------------------ builders: copper
@case("copper.keepout")
def copper_keepout(f, settings):
    name, net, word = f["keepout"], f["net"], f["word"]
    out = []
    if not f.get("bars"):
        out.append(_add_to("keepout", name, "allow", {"str": net}, "Let net %s into keepout `%s`" % (net, name), "allow"))
    layer = f.get("layer")
    left = [l for l in f.get("keepout_layers", ()) if l != layer]
    if layer and word != "via" and left:
        out.append(_set("keepout", name, "layers", {"list": [_enum("CopperLayer.%s" % l) for l in left]},
                        "Keep keepout `%s` off the %s layer" % (name, f.get("layer_word", layer)), "layers"))
    kept = [e for e in f.get("excludes", ()) if e != f.get("excluded")]
    if kept and len(kept) < len(f.get("excludes", ())):
        out.append(_set("keepout", name, "excludes", {"tuple": [{"str": e} for e in kept]},
                        "Let keepout `%s` forbid %s only" % (name, " and ".join(kept)), "excludes"))
    return out


@case("copper.cross")
def copper_cross(f, settings):
    me, other = f["yielder_net"], f["other_net"]
    out = []
    if f.get("yielder") and not f.get("arc"):
        out.append(_set("track", f["yielder"], "bridge", True, "Let the %s track pass under %s" % (me, other), "bridge"))
    if f.get("yielder") and f.get("other_bridge") and not f.get("fixed") and f.get("yielder_priority") != "high":
        out.append(_set("track", f["yielder"], "priority", _enum("Priority.HIGH"),
                        "Let %s yield to %s" % (other, me), "priority"))
    return out
