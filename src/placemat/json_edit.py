"""The JSON dialect of the splicing editor: values of `fab-profile.json` set as minimal splices of the file's own text.

A small scanner finds the span of every value (strings, numbers and literals through `json.JSONDecoder.raw_decode`, objects and
arrays by their brackets), a value is replaced where its key exists and a key is inserted where it does not, in the file's own
indentation, and the rest of the file stays byte for byte. `json.loads` before and after must differ only in what was asked.
A file that does not parse is refused."""
from __future__ import annotations

import json
import re

from .script_edit import EditRefused

_WS = " \t\r\n"
_DEC = json.JSONDecoder()


class _Member:
    def __init__(self, key, key_start, val_start, val_end, node):
        self.key, self.key_start, self.val_start, self.val_end, self.node = key, key_start, val_start, val_end, node


class _Obj:
    def __init__(self, open_, close, members):
        self.open, self.close, self.members = open_, close, members


def _skip(text, i):
    while i < len(text) and text[i] in _WS:
        i += 1
    return i


def _value(text, i):
    """(end offset, node): the value that starts at `i`; node is an `_Obj` for an object, else None."""
    c = text[i:i + 1]
    if c == "{":
        return _object(text, i)
    if c == "[":
        depth, j = 0, i
        while j < len(text):
            ch = text[j]
            if ch == '"':
                j = _DEC.raw_decode(text, j)[1]
                continue
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    return j + 1, None
            j += 1
        raise EditRefused("the JSON array at offset %d is not closed" % i)
    _, end = _DEC.raw_decode(text, i)
    return end, None


def _object(text, i):
    members, j = [], _skip(text, i + 1)
    if text[j:j + 1] == "}":
        return j + 1, _Obj(i, j, members)
    while True:
        j = _skip(text, j)
        key, kend = _DEC.raw_decode(text, j)
        if not isinstance(key, str):
            raise EditRefused("a JSON key at offset %d is not a string" % j)
        k = _skip(text, kend)
        if text[k:k + 1] != ":":
            raise EditRefused("no colon after the JSON key %r" % key)
        v = _skip(text, k + 1)
        end, node = _value(text, v)
        members.append(_Member(key, j, v, end, node))
        j = _skip(text, end)
        if text[j:j + 1] == ",":
            j += 1
            continue
        if text[j:j + 1] == "}":
            return j + 1, _Obj(i, j, members)
        raise EditRefused("the JSON object at offset %d is not closed" % i)


def _scan(text):
    try:
        json.loads(text)
    except ValueError as e:
        raise EditRefused("the file is not valid JSON: %s" % e)
    i = _skip(text, 0)
    if text[i:i + 1] != "{":
        raise EditRefused("the file's JSON is not an object")
    end, root = _object(text, i)
    return root


def _unit(text, root) -> str:
    """One level of the file's indentation: the first member's indent less the object's own, or two spaces."""
    if root.members:
        ls = text.rfind("\n", 0, root.members[0].key_start) + 1
        line = text[ls:root.members[0].key_start]
        if line.strip() == "" and line:
            return line
    return "  "


def _indent_of(text, off) -> str:
    ls = text.rfind("\n", 0, off) + 1
    return re.match(r"[ \t]*", text[ls:]).group(0)


def _dumps(value, unit: str, ind: str, nl: str) -> str:
    out = json.dumps(value, indent=unit if isinstance(value, (dict, list)) and value else None, ensure_ascii=False)
    return out.replace("\n", nl + ind) if nl or ind else out


def _set_path(text: str, path: list, value) -> str:
    root = _scan(text)
    nl = "\r\n" if "\r\n" in text else "\n"
    unit = _unit(text, root)
    node = root
    for depth, key in enumerate(path):
        member = next((m for m in node.members if m.key == key), None)
        last = depth == len(path) - 1
        if member is not None and sum(1 for m in node.members if m.key == key) > 1:
            raise EditRefused("the JSON key %r is given twice" % key)
        if member is None:
            return _insert(text, node, path[depth:], value, unit, nl)
        if last:
            ind = _indent_of(text, member.key_start)
            new = _dumps(value, unit, ind, nl)
            if text[member.val_start:member.val_end] == new:
                return text
            return text[:member.val_start] + new + text[member.val_end:]
        if member.node is None:
            raise EditRefused("the JSON value of %r is not an object, so %r cannot be set inside it" % (key, path[depth + 1]))
        node = member.node
    raise EditRefused("an empty path")


def _insert(text, node, path, value, unit, nl) -> str:
    """`text` with the key `path[0]` added to the object `node`, holding the rest of `path` nested down to `value`."""
    for key in reversed(path[1:]):
        value = {key: value}
    key = path[0]
    ind_open = _indent_of(text, node.open)
    if not node.members:
        inner = ind_open + unit
        member = "%s%s: %s" % (inner, json.dumps(key), _dumps(value, unit, inner, nl))
        return text[:node.open + 1] + nl + member + nl + ind_open + text[node.close:]
    last = node.members[-1]
    ind = _indent_of(text, last.key_start)
    own_line = text[text.rfind("\n", 0, last.key_start) + 1:last.key_start].strip() == ""
    member = "%s: %s" % (json.dumps(key), _dumps(value, unit, ind if own_line else "", nl))
    if own_line:
        return text[:last.val_end] + "," + nl + ind + member + text[last.val_end:]
    return text[:last.val_end] + ", " + member + text[last.val_end:]


def _apply(doc, path, value):
    for key in path[:-1]:
        doc = doc.setdefault(key, {})
    doc[path[-1]] = value


def set_values(text: str, sets) -> str:
    """`text` with each (path, value) of `sets` set: the key's value replaced where it exists, the key added where it does not
    (the objects on the way made). Everything else is the file's own bytes."""
    original = text
    _scan(text)
    want = json.loads(text)
    for path, value in sets:
        if not path or not all(isinstance(k, str) for k in path):
            raise EditRefused("a JSON path is a list of keys, not %r" % (path,))
        text = _set_path(text, list(path), value)
        _apply(want, list(path), value)
    try:
        got = json.loads(text)
    except ValueError as e:
        raise EditRefused("the edited file would not be valid JSON: %s" % e)
    if got != want:
        raise EditRefused("the edit would change more than the values asked for")
    return text if text != original else original


def read_value(text: str, path):
    """The value at `path` of the file, or None."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    for key in path:
        if not isinstance(doc, dict) or key not in doc:
            return None
        doc = doc[key]
    return doc
