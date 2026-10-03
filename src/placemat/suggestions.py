"""Suggestions: changes to a layout script that may clear a finding.

A suggestion is a structured script edit (`Edit`) with its wording, made where the
finding is raised, from the facts the site measured. Every surface reads the same
records and applies them through one function, `apply_suggestion`.

This module holds the records and their JSON; the case builders are further down."""
from __future__ import annotations

from dataclasses import dataclass, field, replace


class SuggestionError(Exception):
    """A suggestion that cannot be shown, applied or undone; the message says why."""


@dataclass(frozen=True)
class Target:
    """The declaration an edit changes: what kind of call (`place`, `link`, `keepout`, `label`, `track`, ...),
    its key (the item, keepout name, track net, or `A.1>B.3` for a link), and, once bound to a script, the file and
    line it was declared on, how many declarations share that file, line and kind (a loop or helper: more than one),
    and the file's digest at the plan."""
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
    """What to write. `op` is one of script_edit.OPS; `target` the declaration it changes (None for `toml_set`,
    whose `file` names the placemat.toml); `args` the op's arguments; `value` an intent expression (never source);
    `refs` binds each item an expression names to its own declaration, so the script's spelling of it is found."""
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

    def files(self) -> list:
        """The files this edit writes, in order: the script or settings file, then a constant's file."""
        out = [self.file] if self.file else ([self.target.file] if self.target is not None and self.target.file else [])
        const = _const_of(self.value)
        if const is not None and const.get("file") and const["file"] not in out:
            out.append(const["file"])
        return out


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
