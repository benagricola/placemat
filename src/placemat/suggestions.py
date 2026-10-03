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


def _edits_of(edits) -> tuple:
    return (edits,) if isinstance(edits, Edit) else tuple(edits)


@dataclass(frozen=True)
class Suggestion:
    """A change to the script, worded: `edits` are made together or not at all (one for most), `how` says how it was
    found ("instant": from the finding's facts alone)."""
    text: str
    edits: tuple
    rank: int = 1
    lever: str = ""                 # suggestions of one lever are variants; the cap per lever is a setting
    id: str = ""                    # "s3a": finding 3, suggestion a; given by bind
    digests: dict = field(default_factory=dict)     # {file: digest} of each file the edits write, at the plan
    how: str = "instant"

    def __post_init__(self):
        object.__setattr__(self, "edits", _edits_of(self.edits))

    def to_json(self) -> dict:
        out = {"id": self.id, "text": self.text, "rank": self.rank, "lever": self.lever,
               "edits": [e.to_json() for e in self.edits], "how": self.how}
        if self.digests:
            out["digests"] = dict(self.digests)
        return out

    @staticmethod
    def from_json(d: dict) -> "Suggestion":
        edits = d["edits"] if "edits" in d else [d["edit"]]          # a record from before suggestions had several
        return Suggestion(d["text"], tuple(Edit.from_json(e) for e in edits), d.get("rank", 1), d.get("lever", ""),
                          d.get("id", ""), dict(d.get("digests", {})), d.get("how", "instant"))


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


class NothingToRedo(SuggestionError):
    """The last thing in the log is not an undo: there is nothing undone to make again."""


class RedoRefused(SuggestionError):
    """A file is not as it was before the undone apply, so making that apply again would write over someone else's change."""


# ------------------------------------------------------------------ the cases
CASES: dict = {}
"""{FindingCause: builder}: a builder takes the facts the raising site measured and returns the suggestions, best first,
each a `Pick`."""


@dataclass(frozen=True)
class Pick:
    """What a builder offers before the engine has bound it: the wording, the edits and the lever it belongs to."""
    text: str
    edits: tuple
    lever: str = ""

    def __post_init__(self):
        object.__setattr__(self, "edits", _edits_of(self.edits))


def case(name):
    def register(fn):
        CASES[name] = fn
        return fn
    return register


def suggest(case_id, facts: dict, settings=None) -> list:
    """The suggestions for a finding of this cause from the facts its site measured, unbound, ranked 1..n in the order
    the builder gave them, at most `[studio] suggestions_per_lever` to a lever. A cause with no builder, or facts the
    builder finds nothing to offer for, gives none."""
    builder = CASES.get(case_id)
    if builder is None:
        return []
    from .settings import Settings
    settings = settings or Settings()
    cap = settings.studio_suggestions_per_lever
    seen: dict = {}
    out = []
    try:
        picks = list(builder(facts, settings) or ())
    except Exception:                   # a suggestion is best-effort: facts a builder cannot read give none
        picks = []
    for pick in picks:
        n = seen.get(pick.lever, 0)
        if pick.lever and n >= cap:
            continue
        seen[pick.lever] = n + 1
        out.append(Suggestion(pick.text, pick.edits, len(out) + 1, pick.lever))
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

    def bind_edit(self, edit: Edit):
        """The edit bound to the script's declarations, or None where one cannot be."""
        refs = {}
        for k, t in edit.refs.items():
            bound = self.target(t)
            if bound is None:
                return None
            refs[k] = bound
        target = None
        if edit.target is not None:
            target = self.target(edit.target)
            if target is None:
                return None
        file, args = edit.file, dict(edit.args)
        if edit.op == "toml_set":
            found = self.settings_file()
            if found is None:
                return None
            file = found[0]
            args["table"] = ["scripts", found[1], args.pop("section")]
        home = target.file if target else file
        value = _bind_consts(edit.value, lambda c: self.constants_file(c.get("scope", "cell"), home))
        return Edit(edit.op, target, args, value, refs, file)

    def bind(self, s: Suggestion) -> list:
        edits = [self.bind_edit(e) for e in s.edits]
        if any(e is None for e in edits):
            return []
        out = []
        for variant in self.variants(s, edits):
            made = self.check(*variant)
            if made is not None:
                out.append(made)
        return out

    def variants(self, s: Suggestion, edits: list) -> list:
        """The suggestion as it stands; or, where the one keyword it sets already reads a constant of the script's,
        two: change that constant, or give this one use a constant of its own."""
        from . import script_edit
        edit = edits[0]
        const = _const_of(edit.value)
        if len(edits) != 1 or edit.op != "set_kwarg" or const is None or edit.target is None or edit.args.get("into"):
            return [(s, edits)]
        try:
            existing = script_edit.keyword_constant(self.board._source_text(edit.target.file), edit.target,
                                                    edit.args["name"])
        except (script_edit.EditRefused, OSError):
            existing = None
        if existing is None:
            return [(s, edits)]
        change = Edit("set_constant", None, {"name": existing, "existing": True, "comment": const.get("comment", "")},
                      const["value"], {}, edit.target.file)
        return [(replace(s, text="%s, by changing %s (every use of it changes)" % (s.text, existing)), [change]),
                (replace(s, text="%s, with a constant of its own" % s.text), edits)]

    def check(self, s: Suggestion, edits: list):
        """The suggestion with its edits bound and its digests, if they can be made on the script as it stands."""
        from . import script_edit
        try:
            changed = script_edit.apply_edits(edits, self.board._source_text)
        except (script_edit.EditRefused, OSError, UnicodeDecodeError, KeyError):
            return None
        digests = {}
        for path, (before, _) in changed.items():
            now = script_edit.digest(before)
            seen = self.board._file_digests.get(path)
            if seen and seen != now:
                return None             # the file was edited while the resolve ran: its lines are not these
            digests[path] = now
        return replace(s, edits=tuple(edits), digests=digests)


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
        if f.cause and f.facts and not any(s.id for s in f.suggestions):
            f.suggestions = tuple(suggest(f.cause, f.facts, board.settings))
        pending = [s for s in f.suggestions if not s.id]
        if not pending:
            continue
        kept = []
        for s in pending:
            try:
                kept += binder.bind(s)
            except Exception:           # one that cannot be bound is left out; the resolve goes on
                continue
        f.suggestions = tuple(replace(s, rank=i + 1, id="s%d%s" % (n, _letters(i))) for i, s in enumerate(kept))


def flatten(findings) -> list:
    """Every bound suggestion of these findings, in finding order."""
    return [s for f in findings for s in f.suggestions if s.id]


# ------------------------------------------------------------------ applying
@dataclass
class FileChange:
    """One file's text before and after; None for a side where the file does not exist (a created file has no `before`,
    a removed one no `after`)."""
    file: str
    before: str | None
    after: str | None

    @property
    def diff(self) -> str:
        return "".join(difflib.unified_diff((self.before or "").splitlines(keepends=True),
                                            (self.after or "").splitlines(keepends=True),
                                            "a/" + self.file if self.before is not None else "/dev/null",
                                            "b/" + self.file if self.after is not None else "/dev/null"))

    def _ops(self):
        a, b = (self.before or "").splitlines(), (self.after or "").splitlines()
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
    p.parent.mkdir(parents=True, exist_ok=True)
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


def _read_or_none(path):
    try:
        return _read(path)
    except OSError:
        return None


def apply_suggestion(suggestions, id: str, dry_run: bool = False, *, root=None, log=None, now=None) -> Applied:
    """Apply the suggestion `id` of `suggestions` to the files it edits, or, with `dry_run`, work out what that would
    write and write nothing: `apply_edits` on its edits and digests. Errors are SuggestionErrors: UnknownSuggestion,
    StaleSuggestion, EditRefused."""
    s = find(suggestions, id)
    return apply_edits(s.edits, s.digests, dry_run, root=root, log=log, now=now, label=s.text, source="suggestion",
                       id=s.id)


def apply_edits(edits, digests=None, dry_run: bool = False, *, root=None, log=None, now=None, label: str = "",
                source: str = "", id: str = "edits") -> Applied:
    """Make `edits` together (one atomic write of every file, one entry in the log, one undo), or, with `dry_run`, work
    out what that would write and write nothing. Every file in `digests` ({path: digest of its text at the plan, "" for a
    file that is not there}) must be as the plan saw it: if one has changed nothing is written (StaleSuggestion). The
    files are written atomically; the apply is appended to `log` (`.placemat/applied.jsonl`) with `label` as its text and
    `source` (who asked), and may be undone by `undo_last`. A write needs `root` (only files under it are written) and
    `log`. A file the edits create has no `before`."""
    from . import script_edit
    if not dry_run and (root is None or log is None):
        raise ValueError("applying edits needs the project root they may write under and the log to record them in")
    stale = []
    for path, want in (digests or {}).items():
        now_text = _read_or_none(path)
        if (now_text is None) != (not want) or (now_text is not None and script_edit.digest(now_text) != want):
            stale.append(path)
    if stale:
        raise StaleSuggestion(stale)
    try:
        changed = script_edit.apply_edits(edits, _read)
    except script_edit.StaleEdit as e:
        raise StaleSuggestion(e.files) from None
    except script_edit.EditRefused as e:
        raise EditRefused(e.reason) from None
    except OSError as e:
        raise EditRefused("cannot read %s" % (e.filename or e)) from None
    files = {p: FileChange(p, before, after) for p, (before, after) in changed.items()}
    result = Applied(id, label, files, dry_run)
    if dry_run:
        return result
    outside = [p for p in files if not _inside(root, p)]
    if outside:
        raise EditRefused("%s is outside the project, which an edit does not write" % ", ".join(outside))
    _write_all(files)
    _append(log, _entry("apply", id, label, source, files, now))
    return result


def _entry(op: str, id, text, source, files: dict, now, **more) -> dict:
    out = {"op": op, "id": id, "text": text, "at": _stamp(now)}
    if source:
        out["source"] = source
    out.update(more)
    out["files"] = [{"file": p, "before": c.before, "after": c.after} for p, c in files.items()]
    return out


def _put(path: str, text) -> None:
    if text is None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    else:
        _write_atomic(path, text)


def _write_all(files: dict) -> None:
    done = []
    try:
        for p, c in files.items():
            _put(p, c.after)
            done.append(p)
    except BaseException:
        for p in done:                  # a later file failed: the earlier ones go back
            try:
                _put(p, files[p].before)
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


def _log_lines(log) -> list:
    """[(seq, entry)] of the log, oldest first; the line number is the seq, a line that is not JSON is skipped."""
    path = Path(log)
    if not path.exists():
        return []
    out = []
    for seq, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            out.append((seq, json.loads(line)))
        except ValueError:
            continue
    return out


def applied_entries(log) -> list:
    """The applied log as [{"seq", "op", "id", "text", "at", "source", "files", "undone"}], oldest first: what the
    studio's history lists. An entry is an apply, or a redo that made an undone apply again; "undone" says an undo took
    it back."""
    entries, undone = [], set()
    for seq, e in _log_lines(log):
        e["seq"] = seq
        if e.get("op") == "undo":
            undone.add(e.get("of"))
        else:
            entries.append(e)
    for e in entries:
        e["undone"] = e["seq"] in undone
    return entries


def _outside_root(root, files):
    if root is not None:
        outside = [p for p in files if not _inside(root, p)]
        if outside:
            raise EditRefused("%s is outside the project, which an edit does not write" % ", ".join(outside))


def undo_last(log, *, root=None, dry_run: bool = False, now=None) -> Applied:
    """Put back what the last apply that has not been undone changed (a created file is removed), if each file is still
    as that apply wrote it (nothing else has touched it since); otherwise refuse (UndoRefused) and write nothing. The
    undo is logged, so undoing again reverts the apply before it, and `redo_last` makes it again."""
    pending = [e for e in applied_entries(log) if not e["undone"]]
    if not pending:
        raise NothingToUndo("nothing applied is left to undo")
    e = pending[-1]
    moved = [f["file"] for f in e["files"] if _read_or_none(f["file"]) != f["after"]]
    if moved:
        raise UndoRefused("%s changed since %s was applied, so it is not put back: undo would take someone else's "
                          "change with it" % (", ".join(moved), e["id"]))
    files = {f["file"]: FileChange(f["file"], f["after"], f["before"]) for f in e["files"]}
    result = Applied(e["id"], e["text"], files, dry_run)
    if dry_run:
        return result
    _outside_root(root, files)
    _write_all(files)
    _append(log, _entry("undo", e["id"], e["text"], e.get("source", ""), files, now, of=e["seq"]))
    return result


def _redoable(log):
    """The entry the next redo makes again, or None: undone applies are a stack, an undo pushes the entry it took back, a
    redo pops it, and a new apply empties it."""
    stack, entries = [], {}
    for seq, e in _log_lines(log):
        op = e.get("op")
        if op == "undo":
            stack.append(e.get("of"))
        elif op == "redo":
            if stack:
                stack.pop()
            entries[seq] = e
        else:
            stack.clear()
            entries[seq] = e
    return entries.get(stack[-1]) if stack else None


def redo_last(log, *, root=None, dry_run: bool = False, now=None) -> Applied:
    """Make again the apply the last undo took back, if each file is as it was before that apply (a file it created is
    not there); otherwise refuse (RedoRefused) and write nothing. A run of undos is redone last first; a new apply drops
    what could be redone (NothingToRedo)."""
    e = _redoable(log)
    if e is None:
        raise NothingToRedo("nothing undone is left to redo")
    moved = [f["file"] for f in e["files"] if _read_or_none(f["file"]) != f["before"]]
    if moved:
        raise RedoRefused("%s changed since %s was undone, so it is not made again: that would write over someone else's "
                          "change" % (", ".join(moved), e["id"]))
    files = {f["file"]: FileChange(f["file"], f["before"], f["after"]) for f in e["files"]}
    result = Applied(e["id"], e["text"], files, dry_run)
    if dry_run:
        return result
    _outside_root(root, files)
    _write_all(files)
    _append(log, _entry("redo", e["id"], e["text"], e.get("source", ""), files, now))
    return result


# ------------------------------------------------------------------ builders: helpers
def _name(*parts) -> str:
    """A constant's name from an item and a keyword: `C4_LINK_LIMIT_MM`."""
    import re
    return "_".join(p for p in (re.sub(r"[^A-Za-z0-9]+", "_", str(x)).strip("_").upper() for x in parts) if p)


def _item(key):
    return {"item": key}


from .findings import FindingCause, FindingCause as C
from .values import Edge as _Edge    # noqa: E402
_EDGES = tuple(_Edge)


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
        if "pad" in value:
            out[value["pad"][0]] = Target("place", value["pad"][0])
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


def _mm(x) -> str:
    return "%.2f" % x


def _side_word(side: str) -> str:
    return side.lower()


# ------------------------------------------------------------------ builders: link_over
_WEIGHTS = (("FREE", 0), ("DEFAULT", 1), ("PREFER", 2), ("SHORT", 8))


@case(C.LINK_OVER)
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
    limit = math.ceil(f["achieved_mm"] * 100 - 1e-9) / 100
    out.append(_set("link", f["link"], "limit_mm",
                    _const(_name(a["key"], "link", "limit", "mm"), limit,
                           "Measured by a run's finding (link_over): %s pad %s to %s pad %s was %s mm, over its %s mm limit."
                           % (a["key"], a["pad"], b["key"], b["pad"], _mm(f["achieved_mm"]), _mm(f["limit_mm"]))),
                    "Raise the limit to %s mm" % _mm(limit), "limit"))
    return out


# ------------------------------------------------------------------ builders: label
def _label_picks(f, settings):
    out = []
    ref = f["item"]
    for side in f.get("sides", ()):
        out.append(_set("label", f["key"], "side", _enum("Edge.%s" % side),
                        "Move the label of %s to its %s side" % (ref, _side_word(side)), "side"))
    return out


@case(C.LABEL_SITS_ON)
def label_sits_on(f, settings):
    return _label_picks(f, settings)


@case(C.LABEL_NO_SPOT)
def label_no_spot(f, settings):
    return _label_picks(f, settings)


@case(C.LABEL_NOT_DRAWN)
def label_not_drawn(f, settings):
    return []


# ------------------------------------------------------------------ builders: copper
@case(C.COPPER_KEEPOUT)
def copper_keepout(f, settings):
    name, net, word = f["keepout"], f["net"], f["word"]
    out = []
    if not f.get("bars"):
        out.append(_add_to("keepout", name, "allow", _form("Net", {"str": net}),
                           "Let net %s into keepout `%s`" % (net, name), "allow"))
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


@case(C.COPPER_CROSS)
def copper_cross(f, settings):
    me, other = f["yielder_net"], f["other_net"]
    out = []
    if f.get("yielder") and not f.get("arc"):
        out.append(_set("track", f["yielder"], "bridge", True, "Let the %s track pass under %s" % (me, other), "bridge"))
    if f.get("yielder") and f.get("other_bridge") and not f.get("fixed") and f.get("yielder_priority") != "high":
        out.append(_set("track", f["yielder"], "priority", _enum("Priority.HIGH"),
                        "Let %s yield to %s" % (other, me), "priority"))
    return out


# ------------------------------------------------------------------ builders: unplaced
def _face_other(face: str) -> str:
    return "back" if face == "front" else "front"


def _insert_after(kind, key, value, text, lever="") -> Pick:
    return Pick(text, Edit("insert_statement", Target(kind, key), {}, value, _refs_of(value)), lever)


@case(C.UNPLACED_SEARCH)
def unplaced_search(f, settings):
    item = f["item"]
    out = []
    for nb, sides in f.get("free_sides", {}).items():
        for side in sides:
            out.append(_set("place", item, "at", _beside(nb, side),
                            "Place %s beside %s, on its %s side" % (item, nb, _side_word(side)), "beside"))
    if f.get("priority") != "high":
        out.append(_set("place", item, "priority", _enum("Priority.HIGH"),
                        "Place %s before the parts that crowd it" % item, "priority"))
    if f.get("face") in ("front", "back"):
        out.append(_set("place", item, "face", _enum("Face.EITHER"),
                        "Let %s take the %s face too" % (item, _face_other(f["face"])), "face"))
    if f.get("kind") == "part" and f.get("turns", 0) < 4:
        out.append(_set("place", item, "rotations", {"list": [{"num": n} for n in (0, 90, 180, 270)]},
                        "Let %s take all four turns" % item, "turns"))
    if f.get("kind") == "part" and f.get("turns", 0) < 8:
        out.append(_set("place", item, "rotations", _enum("Turns.ANY"),
                        "Let %s turn to any bearing" % item, "turns"))
    for r in f.get("reservations", ()):
        if "keepout" in r and not r.get("bars"):
            out.append(_add_to("keepout", r["keepout"], "allow", _item(item),
                               "Let %s into keepout `%s`" % (item, r["keepout"]), "reservation"))
        elif "label" in r:
            out.append(_set("label", r["label"], "reserve", False,
                            "Stop the label of %s reserving room" % r["item"], "reservation"))
    if f.get("drawn") and f.get("envelope") != "courtyard":
        out.append(_setting("place", "envelope", "courtyard", "Judge parts by their courtyards",
                            "A run's finding (unplaced.search): %s was refused by what parts draw round themselves; "
                            "courtyards are what the envelope reads." % item, "envelope"))
    return out


@case(C.UNPLACED_POCKET)
def unplaced_pocket(f, settings):
    item = f["item"]
    out = []
    for nb, sides in f.get("free_sides", {}).items():
        for side in sides:
            out.append(_set("place", item, "at", _beside(nb, side),
                            "Place %s beside %s, on its %s side" % (item, nb, _side_word(side)), "beside"))
    for link in f.get("links", ()):
        pads = [{"pad": [item, link["own"]]}, {"pad": [link["partner"], link["pad"]]}]
        out.append(_insert_after("place", item, _form("board.link", *pads),
                                 "Pull %s toward %s pad %s" % (item, link["partner"], link["pad"]), "link"))
    if f.get("face") in ("front", "back"):
        out.append(_set("place", item, "face", _enum("Face.EITHER"),
                        "Let %s take the %s face too" % (item, _face_other(f["face"])), "face"))
    return out


@case(C.UNPLACED_SLIDE)
def unplaced_slide(f, settings):
    item, here = f["item"], f.get("edge")
    return [_set("place", item, "at", _form("OnEdge", _enum("Edge.%s" % e.name)),
                 "Put %s on the %s edge" % (item, _side_word(e.name)), "edge")
            for e in _EDGES if here and e.name != here]


@case(C.UNPLACED_BLOCK)
def unplaced_block(f, settings):
    item = f["item"]
    out = [_set("place", item, "rotations", _enum("Turns.ANY"), "Let the block turn to any of its turns", "turns")]
    block, sat = f.get("block"), _block_satellite(f)
    if block and sat in block["satellites"]:
        out.append(_out_of_a_list("Place %s on its own, not as a satellite of %s" % (sat, block["anchor"]),
                                  Target("block", block["anchor"]), "satellites", block["satellites"].index(sat), sat, "satellite"))
    return out


@case(C.UNPLACED_BEARING)
def unplaced_bearing(f, settings):
    return []


@case(C.UNPLACED_RIDES)
def unplaced_rides(f, settings):
    return []


# ------------------------------------------------------------------ builders: fixed
def _block_satellite(f):
    """The satellite a block could not lay out, from the refusal a finding carries, or None."""
    turns = f.get("turns")
    whys = [f["why"]] if isinstance(f.get("why"), dict) else [t[1] for t in turns] if isinstance(turns, list) else []
    return next((w["sat"] for w in whys if w.get("code") in ("block_no_spot", "block_taken")), None)


def _out_of_a_list(text, list_target, arg, index, then_place, lever) -> Pick:
    """Take element `index` out of a list argument and put a bare `board.place(Part(...))` after the declaration: a
    row's member, a block's satellite, left to the search."""
    return Pick(text, (Edit("edit_list", list_target, {"arg": arg, "action": "remove", "indices": [index]}),
                       Edit("insert_statement", list_target, {}, _form("board.place", _form("Part", {"str": then_place})))),
                lever)


@case(C.FIXED_PART)
def fixed_part(f, settings):
    item = f["item"]
    out = []
    row = f.get("row")
    if row:
        out.append(_out_of_a_list("Take %s out of the row and let it be searched" % item, Target("row", row["first"]), "items",
                                  row["index"], item, "row"))
    block, sat = f.get("block"), _block_satellite(f)
    if block and sat in block["satellites"]:
        out.append(_out_of_a_list("Place %s on its own, not as a satellite of %s" % (sat, block["anchor"]),
                                  Target("block", block["anchor"]), "satellites", block["satellites"].index(sat), sat, "satellite"))
    out += [_unset("place", item, "at", "Let %s be searched" % item, "search")]
    if f.get("centre"):
        for free, axis, line in ((1, "y", "x"), (0, "x", "y")):
            out.append(Pick("Let %s slide along its %s line" % (item, line),
                            Edit("set_arg", Target("place", item), {"index": free, "into": [{"kw": "at"}]}, None), "slide"))
    if f.get("face") == "front":
        out.append(_set("place", item, "face", _enum("Face.BACK"), "Take %s on the back face" % item, "face"))
    elif f.get("face") == "back":
        out.append(_set("place", item, "face", _enum("Face.FRONT"), "Take %s on the front face" % item, "face"))
    return out


@case(C.FIXED_CUTOUT)
def fixed_cutout(f, settings):
    why = f.get("why") or {}
    if why.get("code") != "cutout_web":
        return []
    return _web_pick(f, why["gap_mm"], why["web_mm"], ("fixed.cutout", "%s would leave a %s mm web" % (f["name"], _mm(why["gap_mm"]))))


@case(C.FIXED_KEEPOUT)
def fixed_keepout(f, settings):
    return []


@case(C.FIXED_ROOM)
def fixed_room(f, settings):
    return []


@case(C.FIXED_ROOM_UNSETTLED)
def fixed_room_unsettled(f, settings):
    return []


# ------------------------------------------------------------------ builders: copper that does not draw as asked
def _fitting_radius(f, text):
    """The radius an arc that did not fit would fit at: a leg of L mm that its arcs take T mm of is fitted by an arc radius
    scaled by L / T (an arc takes radius * tan(turn / 2) of a leg, so the take is proportional to the radius). The leg and
    the take are what the arc misfit measured."""
    m = f.get("misfit") or {}
    if m.get("code") != "arc_leg" or not f.get("radius_mm"):
        return []
    take = sum(a["takes_mm"] for a in m["arcs"])
    if take <= 0:
        return []
    fit = math.floor(f["radius_mm"] * m["length_mm"] / take * 100 - 1e-9) / 100
    if not 0 < fit < f["radius_mm"]:
        return []
    net = f.get("net", "")
    return [_set("track", f["key"], "radius",
                 _const(_name(f["key"].split("#")[0].split(" ", 1)[-1], "radius", "mm"), fit,
                        "A run's finding (copper.not_drawn): the leg was %s mm and the arcs of radius %s mm took %s mm of "
                        "it; %s mm is the radius that fits it, derived as %s x %s / %s." % (
                            _mm(m["length_mm"]), _mm(f["radius_mm"]), _mm(take), _mm(fit), _mm(f["radius_mm"]),
                            _mm(m["length_mm"]), _mm(take))),
                 text % net, "radius")]


def _drop_waypoints(f, text):
    n = f.get("waypoints", 0)
    if n < 1:
        return []
    return [Pick(text, Edit("edit_list", Target("track", f["key"]),
                            {"arg": "points", "action": "remove", "indices": list(range(1, n + 1))}), "waypoints")]


@case(C.COPPER_MEETS)
def copper_meets(f, settings):
    net = f["net"]
    out = []
    if f.get("word") == "track" and f.get("key"):
        out += _drop_waypoints(f, "Draw the %s track pad to pad" % net)
        if f.get("layer") in ("F", "B"):
            other = "B" if f["layer"] == "F" else "F"
            out.append(_set("track", f["key"], "layer", _enum("CopperLayer.%s" % other),
                            "Put the %s track on the %s layer" % (net, "back" if other == "B" else "front"), "layer"))
    return out


@case(C.COPPER_NOT_DRAWN)
def copper_not_drawn(f, settings):
    net = f.get("net", "")
    out = []
    if f.get("variant") == "arc":
        out += _fitting_radius(f, "Use a smaller radius on the %s track")
    if f.get("variant") == "through":
        out += _drop_waypoints(f, "Draw the %s track pad to pad" % net)
        if f.get("layer") in ("F", "B"):
            other = "B" if f["layer"] == "F" else "F"
            out.append(_set("track", f["key"], "layer", _enum("CopperLayer.%s" % other),
                            "Put the %s track on the %s layer" % (net, "back" if other == "B" else "front"), "layer"))
    return out


@case(C.COPPER_CORNER)
def copper_corner(f, settings):
    return []


@case(C.SETUP_CENTRE_COORDINATES)
def setup_centre_coordinates(f, settings):
    """A coordinate placement turned toward intent: beside the neighbour it stands next to, on the side it is on. Never
    `coordinates=True`, never a number."""
    rel = f.get("relation")
    if not rel:
        return []
    item = f["item"]
    return [_set("place", item, "at", _beside(rel["item"], rel["side"]),
                 "Place %s beside %s, on its %s side" % (item, rel["item"], _side_word(rel["side"])), "beside")]


@case(C.SETUP_CENTRE_FLAG_DEFAULT)
def setup_centre_flag_default(f, settings):
    item = f["item"]
    return [Pick("Leave coordinates=False out of the Centre of %s" % item,
                 Edit("remove_kwarg", Target("place", item), {"name": "coordinates", "into": [{"kw": "at"}]}), "flag")]


@case(C.SETUP_FRAME_REACH)
def setup_frame_reach(f, settings):
    """The declared width or height of a fit frame, made the size that holds the item: the item's far reach, rounded up to
    the hundredth. Not offered where the item reaches the frame's origin side, which a size cannot fix."""
    if f["from_mm"] < f["frame_from_mm"] - 1e-6:
        return []
    need = math.ceil(f["to_mm"] * 100 - 1e-9) / 100
    which = f["axis"]
    return [_set("rect", "board", which,
                 _const(_name("board", which, "mm"), need,
                        "A run's finding (setup.frame_reach): %s reaches to %s mm, past the frame's declared %s of %s mm."
                        % (f["item"], _mm(f["to_mm"]), which, _mm(f["frame_to_mm"]))),
                 "Make the board's %s %s mm" % (which, _mm(need)), "frame")]


def _web_pick(f, gap, web, what):
    kind = f.get("outline_kind")
    if not kind:
        return []
    least = math.floor(gap * 100 + 1e-9) / 100
    if not 0 < least < web:
        return []
    return [_set(kind, "board", "web",
                 _const(_name("board", "web", "mm"), least,
                        "A run's finding (%s): %s; the web was %s mm, and %s mm is what the board has, to the hundredth."
                        % (what[0], what[1], _mm(web), _mm(least))),
                 "Lower the web minimum to %s mm" % _mm(least), "web")]


@case(C.SETUP_WEB)
def setup_web(f, settings):
    return _web_pick(f, f["gap_mm"], f["web_mm"], ("setup.web", "a web round %s was %s mm" % (
        "cutout %r" % f["cutout"] if f["cutout"] is not None else "an unnamed cutout", _mm(f["gap_mm"]))))


@case(C.COPPER_STITCH)
def copper_stitch(f, settings):
    return []


@case(C.COPPER_NOTE)
def copper_note(f, settings):
    if f.get("variant") != "waypoint":
        return []
    return _drop_waypoints(f, "Drop the waypoint%s" % ("" if f.get("waypoints") == 1 else "s"))


# ------------------------------------------------------------------ builders: escapes and pairs
def _clear_picks(f, case_id):
    part, pin = f["part"], f["pin"]
    out = []
    if f.get("side"):
        out.append(_insert_after("place", part,
                                 _form("board.fanout", _item(part), sides={"list": [_enum("Edge.%s" % f["side"])]}),
                                 "Keep %s's %s side clear" % (part, _side_word(f["side"])), "fanout"))
    number = {"num": int(pin)} if pin.isdigit() else {"str": pin}
    out.append(_insert_after("place", part,
                             _form("board.escape", _item(part), {"list": [number]},
                                   why={"str": "keeps the way out of %s pin %s clear (%s)" % (part, pin, case_id)}),
                             "Keep the lane of %s pin %s clear" % (part, pin), "escape"))
    return out


@case(C.ESCAPE_WALLED)
def escape_walled(f, settings):
    return _clear_picks(f, "escape_walled")


@case(C.ESCAPE_CLOSED)
def escape_closed(f, settings):
    return _clear_picks(f, "escape_closed")


@case(C.ESCAPE_CROSSED)
def escape_crossed(f, settings):
    return []


@case(C.ESCAPE_LANE)
def escape_lane(f, settings):
    return []


@case(C.PAIR_CROSSED)
def pair_crossed(f, settings):
    return []


# ------------------------------------------------------------------ builders: setup and vias
@case(C.SETUP_UNDECLARED)
def setup_undeclared(f, settings):
    if not f.get("anchor"):
        return []
    item = f["item"]
    return [_insert_after("place", f["anchor"], _form("board.place", _form("Part", {"str": item})),
                          "Place %s searched from its links" % item, "place")]


@case(C.SETUP_LANE_UNUSED)
def setup_lane_unused(f, settings):
    part, pin = f["part"], f["pin"]
    number = {"num": int(pin)} if str(pin).isdigit() else {"str": str(pin)}
    return [Pick("Take pin %s out of %s's escape" % (pin, part),
                 Edit("edit_list", Target("escape", part), {"arg": "pins", "action": "remove"}, number), "pins")]


@case(C.SETUP_ACCEPT)
def setup_accept(f, settings):
    return [Pick("Remove the accept for %s" % f["key"], Edit("remove_statement", Target("accept", f["key"])), "accept")]


@case(C.VIAS_DROPPED)
def vias_dropped(f, settings):
    return []


# ------------------------------------------------------------------ the plan's suggestions, kept for `placemat apply`
STORE = "suggestions.json"
LOG = "applied.jsonl"


def store_path(board_dir) -> Path:
    return Path(board_dir) / ".placemat" / STORE


def project_root(board_dir) -> Path:
    """The folder a suggestion may write under: the one holding the outermost placemat.toml above the board, else
    the board's own. Pass it as `root` to `apply_suggestion` and `undo_last`."""
    from .settings import _files
    found = _files(board_dir)
    return found[0].parent if found else Path(board_dir)


def log_path(board_dir) -> Path:
    """The applied log, shared by the command line and the studio: `<board>/.placemat/applied.jsonl`."""
    return Path(board_dir) / ".placemat" / LOG


def remember(board_dir, script, source: str, findings, now=None) -> None:
    """Keep the suggestions of the plan a `run` or a `preview` just made, per script, for `placemat apply` to find by
    id. `source` says which: "run 1a2b3c4d" or "preview"."""
    path = store_path(board_dir)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    scripts = doc.get("scripts", {})
    scripts[str(Path(script).resolve())] = {"source": source, "at": _stamp(now),
                                            "suggestions": to_json(flatten(findings))}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "scripts": scripts}, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def recall(board_dir, script=None) -> dict:
    """{script: {"source", "at", "suggestions": [Suggestion]}} for the scripts whose plans were kept, or just `script`."""
    try:
        doc = json.loads(store_path(board_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for name, entry in doc.get("scripts", {}).items():
        if script is not None and Path(name) != Path(script).resolve():
            continue
        out[name] = {"source": entry.get("source", ""), "at": entry.get("at", ""),
                     "suggestions": from_json(entry.get("suggestions", ()))}
    return out


# ------------------------------------------------------------------ did a try clear the finding
def finding_key(f) -> tuple:
    """What names a finding across two resolves: (kind, cause, subject). `f` is a Finding or its JSON (a plan's
    `findings[i]`, or a run record's `finding_details[i]`); the subject is what finding_text.subject says the facts are
    about: the item, the link, the label, the part and pin."""
    from . import finding_text
    if isinstance(f, dict):
        cause = FindingCause.parse(f.get("cause"))
        return (f.get("kind"), f.get("cause"), finding_text.subject(cause, f.get("facts") or {}) if cause else "")
    return (f.kind.value, f.cause.value, finding_text.subject(f.cause, f.facts))


def cleared(finding, after) -> bool:
    """Whether the finding is gone from `after` (the findings of a try, or of the resolve after an apply): the same
    (kind, cause, subject) is not among them."""
    return finding_key(finding) not in {finding_key(a) for a in after}
