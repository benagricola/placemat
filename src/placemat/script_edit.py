"""Edits to a layout script and to placemat.toml, as pure functions of the file's text.

An `Edit` (suggestions.Edit) names a declaration (its target call) and an operation; `apply_all` gives the
edited text of every file it writes. The text is edited by splicing: `ast` gives each node's start and end (line
and UTF-8 column) and `tokenize` gives the commas, brackets and comments between them; an edit is a few
(start, end, text) replacements of those spans, so every byte outside them - comments, blank lines, the layout
of other calls - is the file's own. What is written inside the target follows the layout of what was there (see
`_Seq`). Two checks stand between an edit and the caller: the edited text must parse, and the `ast` of everything
outside the target must equal the original's. Either failing refuses the edit.

A value an edit writes is an intent expression (a dict), never source: forms and enums are written as the
script imports them, an item as the script spelled it where it declared it, and a measured number as a named
constant with a comment (`set_constant`).

Structure, for edits to come (an argument inside a nested call such as Beside(...), several edits to one
suggestion): `Src` turns positions into offsets, `_Seq` reads the arguments of any call or the elements of any
bracketed list and says what splices add, remove or replace one of them, and `_splice` applies a set of
splices that do not overlap. None of them knows which call is the target."""
from __future__ import annotations

import ast
import bisect
import functools
import hashlib
import io
import re
import tokenize
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

OPS = ("set_kwarg", "remove_kwarg", "set_arg", "edit_list", "insert_statement", "remove_statement", "set_constant",
       "toml_set", "ensure_import", "remove_constant", "move_statement", "create_file", "confirm_facts", "zen_stackup",
       "zen_netclasses", "json_set")


class EditRefused(Exception):
    """An edit that would not do what it says, or could not be checked. Nothing is written."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class StaleEdit(EditRefused):
    """A file whose text is not the one the plan was made from."""

    def __init__(self, files):
        self.files = list(files)
        super().__init__("%s changed since the plan was made" % ", ".join(self.files))


def digest(text: str) -> str:
    """What a file's text is called in a suggestion: a short hash of its bytes."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def undo(before: str, after: str, current: str) -> str:
    """The text an edit started from, if `current` is still the text it made."""
    if current != after:
        raise EditRefused("the file has changed since the edit was applied")
    return before


# ------------------------------------------------------------------ positions and splices
class Src:
    """A script's text and the positions in it. Offsets are character offsets into `text`."""

    def __init__(self, text: str):
        self.text = text
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]
        self._tokens = None

    def off(self, lineno: int, col: int) -> int:
        """The offset of an `ast` position: a 1-based line and a UTF-8 byte column."""
        start = self.starts[lineno - 1]
        end = self.starts[lineno] if lineno < len(self.starts) else len(self.text)
        line = self.text[start:end]
        return start + (col if line.isascii() else len(line.encode()[:col].decode(errors="replace")))

    def span(self, node) -> tuple:
        return self.off(node.lineno, node.col_offset), self.off(node.end_lineno, node.end_col_offset)

    def code(self, node) -> str:
        s, e = self.span(node)
        return self.text[s:e]

    def line_start(self, off: int) -> int:
        return self.text.rfind("\n", 0, off) + 1

    def line_end(self, off: int) -> int:
        """The offset where the line holding `off` stops, before its newline."""
        i = self.text.find("\n", off)
        if i < 0:
            return len(self.text)
        return i - 1 if i > 0 and self.text[i - 1] == "\r" else i

    def newline_at(self, off: int) -> str:
        return "\r\n" if self.text.startswith("\r\n", off) else "\n"

    def indent_of(self, off: int) -> str:
        """The white space that starts the line holding `off`."""
        s = self.line_start(off)
        m = re.match(r"[ \t]*", self.text[s:])
        return m.group(0)

    def tokens(self) -> list:
        """(type, string, start offset, end offset) of every token."""
        if self._tokens is None:
            out = []
            try:
                for t in tokenize.generate_tokens(io.StringIO(self.text).readline):
                    out.append((t.type, t.string, self._pos(t.start), self._pos(t.end)))
            except (tokenize.TokenError, SyntaxError) as e:
                raise EditRefused("the file cannot be read as tokens: %s" % e)
            self._tokens = out
            self._starts = [t[2] for t in out]
        return self._tokens

    def _pos(self, rc) -> int:
        row, col = rc
        return self.starts[row - 1] + col if row - 1 < len(self.starts) else len(self.text)

    def token_at(self, off: int) -> int:
        toks = self.tokens()
        i = bisect.bisect_left(self._starts, off)
        if i >= len(toks) or toks[i][2] != off:
            raise EditRefused("no token starts at offset %d" % off)
        return i


def _splice(text: str, splices) -> str:
    """`text` with each (start, end, new) replaced; they must not overlap."""
    out = sorted(splices, key=lambda x: (x[0], x[1]))
    for a, b in zip(out, out[1:]):
        if a[1] > b[0]:
            raise EditRefused("two changes to the same place")
    for s, e, new in reversed(out):
        text = text[:s] + new + text[e:]
    return text


# ------------------------------------------------------------------ a sequence: call arguments, list elements
@dataclass
class _Item:
    s: int                  # where the item's own text starts and stops (its parentheses included)
    e: int
    comma: tuple | None     # the comma after it
    note: tuple | None      # the comment on the same line, after the comma (or after the item where it has none)


class _Seq:
    """The arguments of a call, or the elements of a list or a tuple, read from the text between its brackets.
    Each method says what splices add, remove or replace an item; what an edit writes follows the layout there:

    - items on lines of their own (any item starts its line): a new one goes on a line of its own, after the
      last, at the indent of the last item that starts a line, with a trailing comma where the last has one;
    - items run along a line: a new one follows the last, after `, `.
    A comment on an item's line stays where it was or goes to the previous item's line, never lost."""

    def __init__(self, src: Src, ob: int, end: int | None = None, tuple_: bool = False):
        self.src, self.ob, self.tuple = src, ob, tuple_      # a tuple of one item keeps its comma
        toks = src.tokens()
        i = src.token_at(ob)
        if toks[i][0] != tokenize.OP or toks[i][1] not in "([{":
            raise EditRefused("not a bracket")
        depth, first, last, items = 0, None, None, []
        self.cb = None
        for k in range(i, len(toks)):
            typ, string, s, e = toks[k]
            if typ == tokenize.OP and string in "([{":
                depth += 1
                if depth == 1:
                    continue
            elif typ == tokenize.OP and string in ")]}":
                depth -= 1
                if depth == 0:
                    self.cb = s
                    if first is not None:
                        items.append(_Item(first, toks[last][3], None, self._note(last)))
                    break
            elif typ == tokenize.OP and string == "," and depth == 1:
                if first is not None:
                    items.append(_Item(first, toks[last][3], (s, e), self._note(k)))
                first = None
                continue
            elif typ in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE):
                continue
            if first is None:
                first = s
            last = k
        if self.cb is None or (end is not None and self.cb != end - 1):
            raise EditRefused("the brackets are not where the syntax puts them")
        self.items = items

    def _note(self, k):
        toks = self.src.tokens()
        nxt = toks[k + 1] if k + 1 < len(toks) else None
        return (nxt[2], nxt[3]) if nxt is not None and nxt[0] == tokenize.COMMENT else None

    # ---- layout
    def text_of(self, it) -> str:
        return self.src.text[it.s:it.e]

    def tail(self, it) -> int:
        return it.comma[1] if it.comma else it.e

    def first_on_line(self, it) -> bool:
        return self.src.text[self.src.line_start(it.s):it.s].strip() == ""

    def last_on_line(self, it) -> bool:
        t = self.tail(it)
        rest = self.src.text[t:self.src.line_end(t)].strip()
        return rest == "" or rest.startswith("#")

    def _tack(self, it, comment) -> tuple:
        """A splice putting `comment` at the end of the line `it` stands on."""
        at = it.note[1] if it.note else self.tail(it)
        return (at, at, "  " + comment)

    # ---- add
    def append(self, item: str, comment: str | None = None) -> list:
        src, items = self.src, self.items
        if not items:
            return [(self.ob + 1, self.ob + 1, item)]
        last = items[-1]
        trailing = last.comma is not None
        t = self.tail(last)
        ref = next((it for it in reversed(items) if self.first_on_line(it)), None)
        if ref is not None:
            indent, le = src.indent_of(ref.s), src.line_end(t)
            nl = src.newline_at(le)
            new = nl + indent + item + ("," if trailing else "") + ("  " + comment if comment else "")
            if self.cb < le:            # the closing bracket shares the last item's line
                if comment:             # a comment ends the line, so the bracket goes to a line of its own
                    new += nl + indent
                return [(t, t, ("" if trailing else ",") + new)]
            out = [] if trailing else [(last.e, last.e, ",")]
            return out + [(le, le, new)]
        if trailing:
            out = [(t, t, " " + item + ",")]
        else:
            out = [(last.e, last.e, ", " + item)]
        if comment:
            out.append(self._tack(last, comment))
        return out

    def insert(self, k: int, item: str, comment: str | None = None) -> list:
        """Splices putting `item` before item k (at the end when k is past the last)."""
        if k >= len(self.items):
            return self.append(item, comment)
        it = self.items[k]
        src = self.src
        if self.first_on_line(it):
            ls = src.line_start(it.s)
            return [(ls, ls, src.text[ls:it.s] + item + "," + ("  " + comment if comment else "") + src.newline_at(src.line_end(it.s)))]
        out = [(it.s, it.s, item + ", ")]
        if comment:
            le = src.line_end(it.s)
            out.append((le, le, "  " + comment))
        return out

    # ---- take away
    def remove(self, i: int, carry: bool = False) -> tuple:
        """(splices, comment): the splices that take item i out, and the comment that was on its line - left where
        it stood (on the previous item's line, or a line of its own), or with `carry` only returned, for the caller
        to put on the item where it goes."""
        src, items = self.src, self.items
        text = src.text
        n, it = len(items), items[i]
        t = self.tail(it)
        note = text[it.note[0]:it.note[1]] if it.note else None
        first, last = self.first_on_line(it), self.last_on_line(it)
        out = []
        if self.tuple and n == 2 and i == 0 and items[1].comma is None and not carry:
            out.append((items[1].e, items[1].e, ","))       # ("A", "B") without "A" is ("B",)
        prev = items[i - 1] if i > 0 else None
        keep = None if carry else note          # a comment that has to be put somewhere
        stop = it.note[1] if carry and it.note else t       # with `carry`, a comment that stays in place goes too

        def lines():
            """The whole lines the item stands on, as a splice."""
            ls, le = src.line_start(it.s), src.line_end(it.note[1] if it.note else t)
            return ls, le + len(src.newline_at(le))
        if n == 1:
            after = it.note[1] if it.note else t
            rest = text[self.ob + 1:it.s] + text[after:self.cb]
            if rest.strip() == "" and (keep is None):
                out.append((self.ob + 1, self.cb, ""))
            elif keep is not None:
                out.append((it.s, after, keep))
            elif first and last:
                out.append(lines())
            else:
                out.append((it.s, t, ""))
            return out, note
        if i < n - 1:
            nxt = items[i + 1]
            if first and last:
                ls, nl = lines()
                if keep is not None and prev is None:
                    out.append((ls, nl, src.indent_of(it.s) + keep + src.newline_at(src.line_end(it.s))))
                else:
                    out.append((ls, nl, ""))
                    if keep is not None:
                        out.append(self._tack(prev, keep))
            elif last:
                if it.note is None:                         # the next item moves up to the line it stood on
                    out.append((it.s, nxt.s, ""))
                else:
                    out.append((prev.comma[1] if prev is not None else it.s, stop, ""))
            else:
                out.append((it.s, nxt.s, ""))
            return out, note
        trailing = it.comma is not None or (self.tuple and n == 2 and not carry)
        if first and last:
            ls, nl = lines()
            out.append((ls, nl, ""))
        elif first:                             # the closing bracket shares its line
            at = prev.note[1] if prev.note else prev.comma[1]
            # after a comment the bracket cannot follow on the same line: it takes a line at the item's indent
            out.append((at, t, src.newline_at(src.line_end(it.s)) + src.indent_of(it.s) if prev.note else ""))
        else:
            out.append((prev.comma[1], stop, "") if trailing else (prev.e, stop, ""))
            return out, note
        if not trailing:
            out.append((prev.comma[0], prev.comma[1], ""))
        if keep is not None:
            out.append(self._tack(prev, keep))
        return out, note


def _call_seq(src: Src, call: ast.Call) -> _Seq:
    """The arguments of `call` (any call, nested ones too) as a sequence."""
    after = src.off(call.func.end_lineno, call.func.end_col_offset)
    toks = src.tokens()
    for k in range(bisect.bisect_left(src._starts, after), len(toks)):
        if toks[k][0] == tokenize.OP and toks[k][1] == "(":
            seq = _Seq(src, toks[k][2], src.off(call.end_lineno, call.end_col_offset))
            break
    else:
        raise EditRefused("the call's parenthesis is not where the syntax puts it")
    nodes = sorted(list(call.args) + list(call.keywords), key=lambda n: (n.lineno, n.col_offset))
    if len(nodes) != len(seq.items):
        raise EditRefused("the call's arguments cannot be told apart")
    seq.nodes = nodes
    return seq


def _list_seq(src: Src, node) -> _Seq:
    """The elements of a list, or of a tuple written with parentheses."""
    s, e = src.span(node)
    if isinstance(node, (ast.List, ast.Tuple)) and src.text[s] in "([":
        seq = _Seq(src, s, e, isinstance(node, ast.Tuple))
        if len(seq.items) == len(node.elts):
            seq.nodes = list(node.elts)
            return seq
    raise EditRefused("not a list or a tuple written with brackets")


def _value_node(arg):
    return arg.value if isinstance(arg, ast.keyword) else arg


# ------------------------------------------------------------------ names and values
@dataclass
class _Names:
    names: set
    star: bool
    modules: set            # names the placemat package is imported as

    def source(self, name: str):
        """How the script writes `name` (a name placemat exports), or None when it cannot."""
        if name in self.names or self.star:
            return name
        for m in sorted(self.modules):
            return "%s.%s" % (m, name)
        return None


class _Mod:
    """A parsed script: its text and positions, its tree, and the calls found in it."""

    def __init__(self, text: str):
        if re.search(r"\r(?!\n)", text):
            raise EditRefused("the file has a lone carriage return as a line end")
        try:
            self.tree = ast.parse(text)
        except (SyntaxError, ValueError) as e:
            raise EditRefused("the file does not parse: %s" % e)
        self.src = Src(text)
        self.text = text
        self._calls = {}

    def calls(self, method):
        if method not in self._calls:
            self._calls[method] = _find_calls(self, method)
        return self._calls[method]


@functools.lru_cache(maxsize=32)
def _parse(text) -> _Mod:
    """The text as a module. A text parsed once (every suggestion of a plan reads the same script) is not parsed
    again."""
    return _Mod(text)


class _ImportScan:
    def __init__(self, mod):
        self.names, self.star, self.modules, self.stems = set(), False, set(), {}
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.ImportFrom):
                text = node.module or ""
                self.stems.setdefault(text, []).append(node)
                for a in node.names:
                    if a.name == "*":
                        if text.split(".")[0] == "placemat":
                            self.star = True
                        continue
                    self.names.add(a.asname or a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    nm = a.asname or a.name.split(".")[0]
                    self.names.add(nm)
                    if a.name.split(".")[0] == "placemat":
                        self.modules.add(nm)
                    self.stems.setdefault(a.name, []).append(node)


def _names_of(mod) -> _Names:
    scan = _ImportScan(mod)
    return _Names(scan.names, scan.star, scan.modules)


def _bound_names(mod) -> set:
    """Every name the file uses or binds, attribute and keyword names included."""
    out = set()
    for n in ast.walk(mod.tree):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.keyword) and n.arg:
            out.add(n.arg)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.alias):
            out.update(n.name.split("."))
            if n.asname:
                out.add(n.asname)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
    return out


def _export(first: str, rest: list):
    """Refuse a form or enum that placemat does not export."""
    import placemat
    obj = getattr(placemat, first, None)
    if obj is None:
        raise EditRefused("%s is not something placemat exports" % first)
    for r in rest:
        if not hasattr(obj, r):
            raise EditRefused("%s has no %s" % (first, r))
        obj = getattr(obj, r)


@dataclass
class _Ctx:
    names: _Names
    spell: object           # callable(item key) -> source, or raises EditRefused
    bound: set              # every name the file binds
    consts: dict            # id of a {"const"} value -> its final name


def _render(v, ctx: _Ctx) -> str:
    """An intent expression as the source this script would write."""
    if v is None or v is True or v is False:
        return repr(v)
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        raise EditRefused("a value is an intent expression, not source: %r" % (v,))
    if "enum" in v:
        first, *rest = v["enum"].split(".")
        src = ctx.names.source(first)
        if src is None:
            raise EditRefused("%s is not imported by the script" % first)
        _export(first, rest)
        return ".".join([src] + rest)
    if "form" in v:
        parts = v["form"].split(".")
        if parts[0] == "board":
            src = "board" if "board" in ctx.names.names or ctx.names.star else None
            head = src
        else:
            head = ctx.names.source(parts[0])
            if head is not None:
                _export(parts[0], [])
        if head is None:
            raise EditRefused("%s is not imported by the script" % parts[0])
        args = [_render(a, ctx) for a in v.get("args", ())]
        args += ["%s=%s" % (k, _render(x, ctx)) for k, x in v.get("kwargs", {}).items()]
        return "%s(%s)" % (".".join([head] + parts[1:]), ", ".join(args))
    if "item" in v:
        return ctx.spell(v["item"])
    if "str" in v:
        return '"%s"' % v["str"].replace("\\", "\\\\").replace('"', '\\"')
    if "num" in v:
        return repr(v["num"])
    if "name" in v:
        if v["name"] not in ctx.bound:
            raise EditRefused("%s is not a name the script binds" % v["name"])
        return v["name"]
    if "const" in v:
        return ctx.consts[id(v)] if id(v) in ctx.consts else v["const"]["name"]
    if "div" in v:
        a, b = v["div"]
        return "%s / %s" % (_render(a, ctx), _render(b, ctx))
    if "pad" in v:
        owner, key = v["pad"]
        return "%s(%s, %s)" % (ctx.names.source("PadRef") or _need("PadRef"), ctx.spell(owner),
                               key if re.fullmatch(r"\d+", str(key)) else '"%s"' % key)
    if "list" in v:
        return "[%s]" % ", ".join(_render(a, ctx) for a in v["list"])
    if "tuple" in v:
        items = [_render(a, ctx) for a in v["tuple"]]
        return "(%s%s)" % (", ".join(items), "," if len(items) == 1 else "")
    raise EditRefused("cannot write %r" % (v,))


def _need(name):
    raise EditRefused("%s is not imported by the script" % name)




# ------------------------------------------------------------------ finding the target
@dataclass
class _Found:
    call: ast.Call
    line: int
    end: int
    scope: tuple
    in_loop: bool
    stmt: object            # the statement holding it, when it stands alone on its lines as a statement


_LOOPS = (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _stands_alone(src: Src, stmt) -> bool:
    """The statement starts its line and ends it (a `;` or a comment may follow)."""
    s, e = src.span(stmt)
    return (src.text[src.line_start(s):s].strip() == ""
            and re.fullmatch(r"\s*;?\s*(#.*)?", src.text[e:src.line_end(e)]) is not None)


def _find_calls(mod: _Mod, method: str) -> list:
    # a call that is a statement of its own, bare or assigned to a name (`blk = board.block(...)`)
    own = {id(n.value): n for n in ast.walk(mod.tree)
           if isinstance(n, ast.Expr) or (isinstance(n, ast.Assign) and len(n.targets) == 1
                                          and isinstance(n.targets[0], ast.Name))}
    found = []
    stack = [(mod.tree, (), 0)]
    while stack:
        node, scope, loops = stack.pop()
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == method:
            st = own.get(id(node))
            found.append(_Found(node, node.lineno, node.end_lineno, scope, loops > 0,
                                st if st is not None and _stands_alone(mod.src, st) else None))
        if isinstance(node, _SCOPES):
            scope = scope + (node.name,)
        if isinstance(node, _LOOPS):
            loops += 1
        stack.extend((c, scope, loops) for c in reversed(list(ast.iter_child_nodes(node))))
    return found


def _name_literal(call, index, keyword):
    """The string a call gives as its `index`th positional argument or `keyword=`, or None when it is not a literal."""
    pos = [a for a in call.args if not isinstance(a, ast.Starred)]
    node = None
    for k in call.keywords:
        if k.arg == keyword:
            node = k.value
    if node is None and len(pos) > index:
        node = pos[index]
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _locate(mod, target, want_stmt=False):
    """The one call of this target in `mod`: its method, its declared line, and (for a keepout, whose key is
    its name) the name it gives. Refused when there is none, or more than one, or it runs for several items."""
    if not target.line:
        raise EditRefused("the declaration of %s has no line: the script did not say where it was declared" % target.key)
    found = mod.calls(target.kind)
    hits = [f for f in found if f.line == target.line]
    if not hits:
        hits = [f for f in found if f.line <= target.line <= f.end]
    if target.kind == "keepout":
        hits = [f for f in hits if _name_literal(f.call, 1, "name") in (None, target.key)]
    if len(hits) != 1:
        raise EditRefused("%s at line %d: found %d calls of board.%s there, not one" % (
            target.key, target.line, len(hits), target.kind))
    hit = hits[0]
    if hit.in_loop:
        raise EditRefused("%s at line %d is declared in a loop: an edit there would change every item it declares"
                          % (target.key, target.line))
    if target.shared > 1:
        raise EditRefused("%s at line %d declares %d items (a loop or a helper): an edit there would change all of them"
                          % (target.key, target.line, target.shared))
    if want_stmt and hit.stmt is None:
        raise EditRefused("%s at line %d is not a statement of its own" % (target.key, target.line))
    return hit


def _check_expr(src: str):
    try:
        ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise EditRefused("%r does not parse: %s" % (src, e))


def _positional(call):
    return [a for a in call.args if not isinstance(a, ast.Starred)]


def _first_arg(call):
    """The call's first positional argument, else its item= or name= keyword's value."""
    pos = _positional(call)
    return pos[0] if pos else next((k.value for k in call.keywords if k.arg in ("item", "name")), None)


def _spell_for(texts_of, refs, home_file, home_scope):
    """A function: the source the script uses for an item, from the call that declared it."""
    def spell(key):
        ref = refs.get(key)
        if ref is None:
            raise EditRefused("%s is not an item this edit has a declaration for" % key)
        mod = _parse(texts_of(ref.file))
        hit = _locate(mod, ref)
        if ref.file != home_file or hit.scope != home_scope:
            raise EditRefused("%s is declared in another file or scope than the call being edited" % key)
        first = _first_arg(hit.call)
        if first is None:
            raise EditRefused("the declaration of %s has no first argument to spell it from" % key)
        return mod.src.code(first)
    return spell


def spelling(text: str, target) -> str:
    """How the script at `text` writes the item a call declares: its first argument, as written."""
    mod = _parse(text)
    hit = _locate(mod, target)
    positional = _positional(hit.call)
    if not positional:
        raise EditRefused("%s has no first argument" % target.key)
    return mod.src.code(positional[0])


# ------------------------------------------------------------------ the check
def _calls_at(tree, line, func_dump):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.lineno == line and ast.dump(n.func) == func_dump]


class _Mask(ast.NodeTransformer):
    def __init__(self, node):
        self.node = node

    def generic_visit(self, node):
        if node is self.node:
            return ast.Constant(value="<target>")
        return super().generic_visit(node)


def _masked_call_dump(text, line, func_dump, into=()):
    tree = ast.parse(text)
    hits = _calls_at(tree, line, func_dump)
    if not hits:
        raise EditRefused("the target call is not where the edit left it")
    node = _resolve_into(hits[0], into) if into else hits[0]
    return ast.dump(_Mask(node).visit(tree))


def _check_call_edit(before, after, hit_line, func_dump, into=()):
    """The edited text parses and everything outside the target call (or, with `into`, outside the inner call it names)
    is the tree it was."""
    try:
        ast.parse(after)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    try:
        same = _masked_call_dump(before, hit_line, func_dump, into) == _masked_call_dump(after, hit_line, func_dump, into)
    except EditRefused:
        raise EditRefused("the edit would change more than the %s" % ("inner call" if into else "target call"))
    if not same:
        raise EditRefused("the edit would change more than the %s" % ("inner call" if into else "target call"))


def _stmt_lists(tree):
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            seq = getattr(node, field, None)
            if isinstance(seq, list) and seq and isinstance(seq[0], ast.stmt):
                yield seq


def _dump_without(text, line):
    """The tree of `text` with the statement that starts at `line` left out."""
    tree = ast.parse(text)
    for seq in _stmt_lists(tree):
        for k, st in enumerate(seq):
            if st.lineno == line:
                del seq[k]
                return ast.dump(tree)
    raise EditRefused("the statement is not where the edit left it")


# ------------------------------------------------------------------ call edits
def _func_name(call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _step_into(node, step):
    """The node a step of `into` reaches from `node`: {"kw": name} or {"pos": index} an argument of a call,
    {"elem": index} an element of a list or tuple, {"find": "Name"} the one call of that name among a list's elements."""
    if "kw" in step or "pos" in step:
        if not isinstance(node, ast.Call):
            raise EditRefused("there is no call to take the argument %r of" % (step,))
        if "kw" in step:
            hit = [k.value for k in node.keywords if k.arg == step["kw"]]
            if not hit:
                raise EditRefused("the call has no %s=" % step["kw"])
            return hit[0]
        pos = _positional(node)
        if step["pos"] >= len(pos):
            raise EditRefused("the call has no positional argument %d" % step["pos"])
        return pos[step["pos"]]
    if not isinstance(node, (ast.List, ast.Tuple)):
        raise EditRefused("there is no list to take the element %r of" % (step,))
    if "elem" in step:
        if not 0 <= step["elem"] < len(node.elts):
            raise EditRefused("the list has no element %d" % step["elem"])
        return node.elts[step["elem"]]
    if "find" in step:
        hits = [e for e in node.elts if isinstance(e, ast.Call) and _func_name(e) == step["find"]]
        if len(hits) != 1:
            raise EditRefused("the list has %d calls of %s, not one" % (len(hits), step["find"]))
        return hits[0]
    raise EditRefused("unknown step %r" % (step,))


def _resolve_into(call, into):
    """The call that `into` (a path of steps) names inside `call`."""
    node = call
    for step in into:
        node = _step_into(node, step)
    if not isinstance(node, ast.Call):
        raise EditRefused("the place %r is not a call" % (list(into),))
    return node


def _call_of(text, target, into=()):
    """(the module, the target call's hit): with `into`, the hit's `call` is the inner call the path names."""
    mod = _parse(text)
    hit = _locate(mod, target)
    if into:
        hit = replace(hit, call=_resolve_into(hit.call, into))
    return mod, hit


def _into(edit):
    return tuple(edit.args.get("into", ()))


def _kind_of(edit, hit):
    """What the call being edited is called, for reading its parameters: the board method, or the inner call's name."""
    return _func_name(hit.call) if _into(edit) else edit.target.kind


@functools.lru_cache(maxsize=None)
def _positional_index(kind, name):
    """Where the board method `kind` takes its parameter `name` by position (0 for the first after self), or None
    where it is by keyword alone."""
    import inspect
    from .layout import Board
    fn = getattr(Board, kind, None)
    skip = 1
    if fn is None:                      # an inner call: a form the script imports from placemat (Beside, Past, Centre, ...)
        import placemat
        fn = getattr(placemat, kind, None) if kind[:1].isupper() else None
        skip = 0
        if fn is None:
            return None
    index = 0
    for p in list(inspect.signature(fn).parameters.values())[skip:]:
        if p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            return None
        if p.name == name:
            return index
        index += 1
    return None


def _given(call, kind, name):
    """The argument that gives parameter `name` of the call: `name=...`, or the argument in its position."""
    kw = next((k for k in call.keywords if k.arg == name), None)
    if kw is not None:
        return kw
    index = _positional_index(kind, name)
    if index is None:
        return None
    if any(isinstance(a, ast.Starred) for a in call.args):
        raise EditRefused("the call spreads *args, so %s may be given there" % name)
    positional = _positional(call)
    return positional[index] if index < len(positional) else None


def _has_star_kwargs(call):
    return any(k.arg is None for k in call.keywords)


def _finish_call(text, out, hit, into=(), outer_func=None):
    """The edited text, once it is checked: with `into`, `hit.call` is the inner call and `outer_func` the dump of the
    target call's function."""
    _check_call_edit(text, out, hit.line, outer_func if into else ast.dump(hit.call.func), into)
    return out


def _replace_value(mod, arg, src):
    """The splice that gives the argument `arg` (a keyword or a positional expression) the value `src`."""
    s, e = mod.src.span(_value_node(arg))
    return [(s, e, src)]


def _outer_func(text, edit):
    """The dump of the target call's function, for the check of a nested edit."""
    return ast.dump(_locate(_parse(text), edit.target).call.func)


def _set_kwarg(text, edit, ctx_for):
    into = _into(edit)
    mod, hit = _call_of(text, edit.target, into)
    name = edit.args["name"]
    src = _render(edit.value, ctx_for(mod, hit))
    _check_expr(src)
    call = hit.call
    outer = _outer_func(text, edit) if into else None
    arg = _given(call, _kind_of(edit, hit), name)
    if arg is not None:
        if _same(src, mod.src.code(_value_node(arg))):
            raise EditRefused("%s= is already %s" % (name, src))
        return _finish_call(text, _splice(text, _replace_value(mod, arg, src)), hit, into, outer)
    if _has_star_kwargs(call):
        raise EditRefused("the call takes **kwargs: %s= may already be given there" % name)
    return _finish_call(text, _splice(text, _call_seq(mod.src, call).append("%s=%s" % (name, src))), hit, into, outer)


def _remove_kwarg(text, edit, ctx_for):
    into = _into(edit)
    mod, hit = _call_of(text, edit.target, into)
    name = edit.args["name"]
    seq = _call_seq(mod.src, hit.call)
    arg = _given(hit.call, _kind_of(edit, hit), name)
    if arg is None:
        raise EditRefused("the call has no %s=" % name)
    k = next(i for i, n in enumerate(seq.nodes) if n is arg)
    if not isinstance(arg, ast.keyword) and any(
            not isinstance(n, (ast.keyword, ast.Starred)) for n in seq.nodes[k + 1:]):
        raise EditRefused("%s is given by position, and the arguments after it would move up" % name)
    return _finish_call(text, _splice(text, seq.remove(k)[0]), hit, into, _outer_func(text, edit) if into else None)


def _set_arg(text, edit, ctx_for):
    into = _into(edit)
    mod, hit = _call_of(text, edit.target, into)
    index = edit.args["index"]
    src = _render(edit.value, ctx_for(mod, hit))
    _check_expr(src)
    positional = _positional(hit.call)
    if index >= len(positional):
        raise EditRefused("the call has no positional argument %d" % index)
    return _finish_call(text, _splice(text, _replace_value(mod, positional[index], src)), hit, into,
                        _outer_func(text, edit) if into else None)


def _list_arg(call, which, kind):
    if isinstance(which, int):
        pos = _positional(call)
        return pos[which] if which < len(pos) else None
    return _given(call, kind, which)


def _same(src_a, src_b):
    try:
        return ast.dump(ast.parse(src_a, mode="eval")) == ast.dump(ast.parse(src_b, mode="eval"))
    except SyntaxError:
        return False


def _reseq(text, ob, tuple_=False):
    """The sequence that opens at `ob`, read again from the text an edit made (edits in it leave `ob` where it was)."""
    return _Seq(Src(text), ob, None, tuple_)


def _edit_list(text, edit, ctx_for):
    into = _into(edit)
    mod, hit = _call_of(text, edit.target, into)
    ctx = ctx_for(mod, hit)
    arg = _list_arg(hit.call, edit.args["arg"], _kind_of(edit, hit))
    if arg is None:
        if edit.args.get("create") and edit.args.get("action") == "add" and isinstance(edit.args["arg"], str):
            return _set_kwarg(text, replace(edit, op="set_kwarg", args={"name": edit.args["arg"], "into": list(into)},
                                            value={"list": [edit.value]}), ctx_for)
        raise EditRefused("the call has no %s" % (edit.args["arg"],))
    seq = _list_seq(mod.src, _value_node(arg))
    ob, tuple_ = seq.ob, seq.tuple
    sources = [seq.text_of(it) for it in seq.items]
    action = edit.args["action"]
    src = _render(edit.value, ctx) if edit.value is not None else None

    def index_of(spec):
        s = _render(spec, ctx)
        for i, have in enumerate(sources):
            if _same(have, s):
                return i
        raise EditRefused("%s is not in the list" % s)
    out = text
    if action == "add":
        if any(_same(src, have) for have in sources):
            raise EditRefused("%s is already in the list" % src)
        _check_expr(src)
        k = len(sources)
        if edit.args.get("before") is not None:
            k = index_of(edit.args["before"])
        elif edit.args.get("after") is not None:
            k = index_of(edit.args["after"]) + 1
        out = _splice(text, seq.insert(k, src))
    elif action == "remove" and edit.args.get("indices") is not None:
        for k in sorted(set(edit.args["indices"]), reverse=True):      # by position: a waypoint has no name to find it by
            seq = _reseq(out, ob, tuple_)
            if not 0 <= k < len(seq.items):
                raise EditRefused("the list has no element %d" % k)
            out = _splice(out, seq.remove(k)[0])
    elif action == "remove":
        out = _splice(text, seq.remove(index_of(edit.value))[0])
    elif action == "move":
        k = index_of(edit.value)
        if len(sources) > 1:
            item = sources[k]
            splices, comment = seq.remove(k, carry=True)
            out = _splice(text, splices)
            sources2 = sources[:k] + sources[k + 1:]
            dest = len(sources2)
            for key, shift in (("before", 0), ("after", 1)):
                spec = edit.args.get(key)
                if spec is not None:
                    s = _render(spec, ctx)
                    dest = next((i for i, have in enumerate(sources2) if _same(have, s)), None)
                    if dest is None:
                        raise EditRefused("%s is not in the list" % s)
                    dest += shift
            out = _splice(out, _reseq(out, ob, tuple_).insert(dest, item, comment))
    else:
        raise EditRefused("unknown list action %r" % (action,))
    return _finish_call(text, out, hit, into, _outer_func(text, edit) if into else None)


def _insert_statement(text, edit, ctx_for):
    mod, hit = _locate_stmt(text, edit.target)
    if not isinstance(edit.value, dict) or "form" not in edit.value:
        raise EditRefused("an inserted statement is a call")
    new = _render(edit.value, ctx_for(mod, hit))
    _check_expr(new)
    src = mod.src
    s, e = src.span(hit.stmt)
    le = src.line_end(e)
    nl = src.newline_at(le)
    line = src.indent_of(s) + new
    out = text + nl + line if le >= len(text) else _splice(text, [(le + len(nl), le + len(nl), line + nl)])
    try:
        ast.parse(out)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    if _dump_without(out, hit.stmt.end_lineno + 1) != ast.dump(ast.parse(text)):
        raise EditRefused("the edit would change more than the inserted statement")
    return out


def _locate_stmt(text, target):
    mod = _parse(text)
    return mod, _locate(mod, target, want_stmt=True)


def _tidy_start(text: str, a: int, b: int) -> int:
    """Where a removal of the lines `a`..`b` starts so that no blank line is left doubled or dangling: `a`, or the start of the
    blank line above it where the removed lines were alone between that blank line and another (or the end of the file)."""
    if a > 0:
        pa = text.rfind("\n", 0, a - 1) + 1
        rest = text[b:].split("\n", 1)[0]
        if text[pa:a].strip() == "" and (b >= len(text) or rest.strip() == ""):
            return pa
    return a


def _remove_statement(text, edit, ctx_for):
    """The statement's lines go; comments above it stay, for whatever follows, and so do blank lines, except one that would be left
    doubled: a statement alone between two blank lines (or one and the end of the file) takes the blank line above it."""
    mod, hit = _locate_stmt(text, edit.target)
    if isinstance(hit.stmt, ast.Assign):
        raise EditRefused("%s at line %d is assigned to a name the script may use: it is not removed" % (
            edit.target.key, edit.target.line))
    src = mod.src
    s, e = src.span(hit.stmt)
    le = src.line_end(e)
    a, b = src.line_start(s), le + (len(src.newline_at(le)) if le < len(text) else 0)
    out = _splice(text, [(_tidy_start(text, a, b), b, "")])
    try:
        ast.parse(out)
    except SyntaxError as err:
        raise EditRefused("the edited file would not parse: %s" % err)
    if _dump_without(text, hit.stmt.lineno) != ast.dump(ast.parse(out)):
        raise EditRefused("the edit would change more than the removed statement")
    return out


_CALL_OPS = {"set_kwarg": _set_kwarg, "remove_kwarg": _remove_kwarg, "set_arg": _set_arg, "edit_list": _edit_list,
             "insert_statement": _insert_statement, "remove_statement": _remove_statement}


# ------------------------------------------------------------------ keywords of one call, for freeze
def edit_keywords(text: str, line: int, method: str, set_values: dict, remove=()) -> str:
    """`text` with the keywords of the one `<x>.<method>(...)` call starting on `line` changed: each in
    `set_values` (name -> source of the value) has its value replaced where the call has it and is added at the
    end where it has not (in the layout `_Seq` gives), and each in `remove` is taken out. A call passing * or **
    arguments is refused. The edit is made on the call's own text, so the cost does not grow with the script."""
    mod = _parse(text)
    hits = [n for n in ast.walk(mod.tree) if isinstance(n, ast.Call) and n.lineno == line
            and isinstance(n.func, ast.Attribute) and n.func.attr == method]
    if len(hits) != 1:
        raise EditRefused("line %d: %d %s() calls start there" % (line, len(hits), method))
    call = hits[0]
    if any(isinstance(a, ast.Starred) for a in call.args) or _has_star_kwargs(call):
        raise EditRefused("the call passes * or ** arguments, which cannot be seen into")
    cs, ce = mod.src.span(call)
    sub = text[cs:ce]
    func_dump = ast.dump(call.func)

    def reread(t):
        m = _Mod(t)
        node = m.tree.body[0].value
        return m, node
    m, node = reread(sub)
    present = {k.arg for k in node.keywords}
    sub = _splice(sub, [(m.src.span(k.value)[0], m.src.span(k.value)[1], set_values[k.arg])
                        for k in node.keywords if k.arg in set_values])
    for name in remove:
        if name in set_values:
            continue
        m, node = reread(sub)
        seq = _call_seq(m.src, node)
        kw = next((k for k in node.keywords if k.arg == name), None)
        if kw is not None:
            sub = _splice(sub, seq.remove(next(i for i, n in enumerate(seq.nodes) if n is kw))[0])
    for name, value in set_values.items():
        if name not in present:
            m, node = reread(sub)
            sub = _splice(sub, _call_seq(m.src, node).append("%s=%s" % (name, value)))
    try:
        inner = ast.parse(sub).body
    except SyntaxError as e:
        raise EditRefused("the edited call would not parse: %s" % e)
    if len(inner) != 1 or not isinstance(inner[0], ast.Expr) or ast.dump(inner[0].value.func) != func_dump:
        raise EditRefused("the edit would change more than the call")
    return text[:cs] + sub + text[ce:]


# ------------------------------------------------------------------ constants
_UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _is_constant_line(stmt) -> bool:
    """A module-level assignment to upper-case names alone: a line of a constants block."""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return False
    t = stmt.targets[0]
    names = [t] if isinstance(t, ast.Name) else (list(t.elts) if isinstance(t, ast.Tuple) else [None])
    return all(isinstance(n, ast.Name) and (_UPPER.match(n.id) or n.id == "_") for n in names)


def _is_import(stmt) -> bool:
    return isinstance(stmt, (ast.Import, ast.ImportFrom))


def _is_docstring(stmt) -> bool:
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str))


def _only_imports(node) -> bool:
    containers = tuple(c for c in (ast.If, ast.Try, getattr(ast, "TryStar", None)) if c)
    inner = [n for n in ast.walk(node) if isinstance(n, ast.stmt) and not isinstance(n, containers)]
    return bool(inner) and all(_is_import(s) for s in inner)


def _block_end(mod):
    """(the index to add a constant at, whether the module has a constants block). The header is the docstring and
    the imports; the block is the run of plain assignments after it, and a constant goes after the last upper-case
    one of them (after the header where there is none)."""
    body = mod.tree.body
    i = 1 if body and _is_docstring(body[0]) else 0
    end = i
    while i < len(body) and (_is_import(body[i]) or (isinstance(body[i], (ast.If, ast.Try)) and _only_imports(body[i]))):
        i += 1
        end = i
    has = False
    while i < len(body):
        s = body[i]
        if _is_constant_line(s):
            end, has = i + 1, True
        elif not isinstance(s, ast.Assign):
            break
        i += 1
    return end, has


def _line_after(mod, idx):
    """(the offset of the line after top-level statement idx - 1, whether the file ends without a newline there);
    the start of the file for idx 0."""
    if idx == 0:
        return 0, False
    end_line = mod.tree.body[idx - 1].end_lineno
    starts = mod.src.starts
    return (starts[end_line], False) if end_line < len(starts) else (len(mod.text), True)


def _local_module_names(texts_of, home_file, mod):
    """Names bound at the top level of the modules this file imports that sit beside it."""
    out = set()
    base = Path(home_file).parent
    for stem in _ImportScan(mod).stems:
        path = base / (stem.split(".")[0] + ".py")
        try:
            other = _parse(texts_of(str(path)))
        except (EditRefused, OSError, KeyError):
            continue
        out |= _bound_names(other)
    return out


def _unique(name, taken):
    if name not in taken:
        return name
    n = 2
    while "%s_%d" % (name, n) in taken:
        n += 1
    return "%s_%d" % (name, n)


def _nl_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def _comment_block(comment, nl):
    return "".join("# %s%s" % (line, nl) for line in comment.splitlines())


def _constant_text(value):
    if isinstance(value, (list, tuple)) and value and all(
            isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)
            for p in value):
        return repr([tuple(p) for p in value])                  # a polygon's vertices: a list of (x, y) pairs
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EditRefused("a constant holds a number, a string or a list of (x, y) pairs, not %r" % (value,))
    return repr(value)


def _add_constant(text, name, value, comment):
    """`text` with `name = value` added at the end of its constants block (made, after the imports, where there
    is none), the comment on the lines above it."""
    mod = _parse(text)
    end, has = _block_end(mod)
    at, needs_nl = _line_after(mod, end)
    nl = _nl_of(text)
    block = ("" if has else nl) + _comment_block(comment, nl) + "%s = %s%s" % (name, _constant_text(value), nl)
    out = text + nl + block if needs_nl else _splice(text, [(at, at, block)])
    _check_constant(text, out, name, added=True)
    return out


def _constant_line(tree_text, name):
    return next((n.lineno for n in ast.parse(tree_text).body if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name), None)


def _check_constant(before, after, name, added):
    try:
        tree = ast.parse(after)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    line = _constant_line(after, name)
    if line is None:
        raise EditRefused("the constant is not where the edit left it")
    if added:
        if _dump_without(after, line) != ast.dump(ast.parse(before)):
            raise EditRefused("the edit would change more than the added constant")
    else:
        was = ast.parse(before)
        for t in (was, tree):
            for n in t.body:
                if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name:
                    n.value = ast.Constant(value="<value>")
        if ast.dump(was) != ast.dump(tree):
            raise EditRefused("the edit would change more than the constant")


def _assigns(stmt, name):
    return (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == name)


def _change_constant(text, name, value, comment, replace_comment=False):
    """The assignment of `name` given `value`, with the comment above it: written above the one that is there, or, with
    `replace_comment`, in place of the comment lines directly above the assignment (where the number came from has changed)."""
    mod = _parse(text)
    hits = [s for s in mod.tree.body if _assigns(s, name)]
    if len(hits) != 1:
        raise EditRefused("%s is assigned %d times in the file, not once" % (name, len(hits)))
    s = hits[0]
    vs, ve = mod.src.span(s.value)
    ls = mod.src.line_start(mod.src.span(s)[0])
    splices = [(vs, ve, _constant_text(value))]
    if replace_comment and comment:
        lines = text.splitlines(keepends=True)
        k = s.lineno - 1
        while k > 0 and lines[k - 1].lstrip().startswith("#"):
            k -= 1
        splices.append((mod.src.starts[k], ls, _comment_block(comment, _nl_of(text))))
    else:
        splices.append((ls, ls, _comment_block(comment, _nl_of(text))))
    out = _splice(text, splices)
    _check_constant(text, out, name, added=False)
    return out


def _import_name(text, stem, name):
    """`text` importing `name` from the module `stem`: added to its one-line `from stem import ...`, or a line of
    its own after its imports. A script that has `from stem import *` already has it."""
    mod = _parse(text)
    body = mod.tree.body
    last = None
    for k, s in enumerate(body):
        if not _is_import(s):
            continue
        last = k
        if isinstance(s, ast.ImportFrom) and s.module == stem and not s.level:
            if any(a.name in ("*", name) for a in s.names):
                return text
            a, b = mod.src.span(s)
            if s.lineno == s.end_lineno and "(" not in text[a:b]:
                at = mod.src.span(s.names[-1])[1]
                out = _splice(text, [(at, at, ", " + name)])
                _check_import(out)
                return out
    if last is None:
        last = 0 if body and _is_docstring(body[0]) else -1
    at, needs_nl = _line_after(mod, last + 1)
    nl = _nl_of(text)
    line = "from %s import %s%s" % (stem, name, nl)
    out = text + nl + line if needs_nl else _splice(text, [(at, at, line)])
    _check_import(out)
    return out


def _check_import(after):
    try:
        ast.parse(after)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)


# ------------------------------------------------------------------ toml
def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        import json
        return json.dumps(v)
    raise EditRefused("cannot write %r into a settings file" % (v,))


_HEADER = re.compile(r"^\s*\[(?!\[)(.+?)\]\s*(#.*)?$")


def _header_path(line):
    m = _HEADER.match(line)
    if not m:
        return None
    try:
        d = tomllib.loads("[%s]\n" % m.group(1))
    except tomllib.TOMLDecodeError:
        return None
    path = []
    while isinstance(d, dict) and len(d) == 1:
        (k, d), = d.items()
        path.append(k)
    return path


def toml_set(text: str, table, key: str, value, comment: str = "") -> str:
    """`key = value` in `[table]` of the settings file `text`, as a change of its own line, or a line added at the
    end of the table, or the table added at the end of the file. The rest of the file is as it was."""
    table = list(table)
    before = tomllib.loads(text) if text.strip() else {}
    lines = text.splitlines(keepends=True)
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    start = None
    for i, line in enumerate(lines):
        if _header_path(line) == table:
            start = i
            break
    tail = ("  # " + comment) if comment and any(re.search(r"(^|\s)#", l) for l in lines) else ""
    new_line = "%s = %s%s%s" % (key, _toml_value(value), tail, nl)
    if start is None:
        out = text
        if out and not out.endswith("\n"):
            out += nl
        if out.strip():
            out += nl
        out += "[%s]%s%s" % (".".join(k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else '"%s"' % k for k in table), nl, new_line)
    else:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if _HEADER.match(lines[j]) or re.match(r"^\s*\[\[", lines[j]):
                end = j
                break
        key_re = re.compile(r"^(\s*)(%s|\"%s\")\s*=\s*" % (re.escape(key), re.escape(key)))
        hit = next((j for j in range(start + 1, end) if key_re.match(lines[j])), None)
        if hit is not None:
            m = key_re.match(lines[hit])
            rest = lines[hit][m.end():]
            old_comment = re.search(r"\s+#.*$", rest.rstrip("\r\n"))
            keep = old_comment.group(0) if old_comment and not tail else tail
            lines[hit] = "%s%s = %s%s%s" % (m.group(1), key, _toml_value(value), keep, nl)
        else:
            at = start + 1
            for j in range(start + 1, end):
                body = lines[j].strip()
                if body and not body.startswith("#"):
                    at = j + 1
            if at > 0 and not lines[at - 1].endswith("\n"):
                lines[at - 1] += nl
            lines.insert(at, new_line)
        out = "".join(lines)
    after = tomllib.loads(out)
    want = _deep_set(before, table + [key], value)
    if after != want:
        raise EditRefused("the settings file would change more than %s" % key)
    return out


def _deep_set(d, path, value):
    import copy
    d = copy.deepcopy(d)
    cur = d
    for k in path[:-1]:
        cur = cur.setdefault(k, {})
    cur[path[-1]] = value
    return d


# ------------------------------------------------------------------ apply
def _read_default(path):
    return Path(path).read_text()


def _find_consts(value, out):
    if isinstance(value, dict):
        if isinstance(value.get("const"), dict):
            out.append(value)
        for v in value.values():
            _find_consts(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _find_consts(v, out)


# ------------------------------------------------------------------ imports
def _sort_key(name: str):
    return (name != "board", name)


def _ensure_import(text, names):
    """`text` importing `names` from placemat: each added to the one `from placemat import ...` statement in its place
    (`board` first, then in order), with the statement's own layout kept; or a statement of its own after the last import
    (after the docstring where there is none). A star import, or every name already imported, changes nothing."""
    mod = _parse(text)
    body = mod.tree.body
    stmt = next((s for s in body if isinstance(s, ast.ImportFrom) and s.module == "placemat" and not s.level), None)
    if stmt is None:
        last = max((k for k, s in enumerate(body) if _is_import(s)), default=None)
        if last is None:
            last = 0 if body and _is_docstring(body[0]) else -1
        at, needs_nl = _line_after(mod, last + 1)
        nl = _nl_of(text)
        line = "from placemat import %s%s" % (", ".join(sorted(names, key=_sort_key)), nl)
        out = text + nl + line if needs_nl else _splice(text, [(at, at, line)])
        _check_import(out)
        return out
    have = [a.name for a in stmt.names]
    if "*" in have or all(n in have for n in names):
        return text
    s, e = mod.src.span(stmt)
    if "#" in text[s:e]:
        raise EditRefused("the placemat import has a comment inside it; it is not rewritten")
    splices = []
    ahead = list(stmt.names)
    for name in sorted((n for n in names if n not in have), key=_sort_key):
        nxt = next((a for a in ahead if _sort_key(a.name) > _sort_key(name)), None)
        if nxt is not None:
            at = mod.src.off(nxt.lineno, nxt.col_offset)
            splices.append((at, at, name + ", "))
        else:
            last = ahead[-1]
            at = mod.src.off(last.end_lineno, last.end_col_offset)
            splices.append((at, at, ", " + name))
    out = _splice(text, splices)
    _check_import(out)
    return out


# ------------------------------------------------------------------ constants
def _remove_constant(text, name):
    """The assignment of `name` and the comment lines directly above it, when nothing in the file reads the name."""
    mod = _parse(text)
    hits = [s for s in mod.tree.body if _assigns(s, name)]
    if not hits:
        raise EditRefused("the file has no constant %s" % name)
    if len(hits) != 1:
        raise EditRefused("%s is assigned %d times in the file, not once" % (name, len(hits)))
    s = hits[0]
    for n in ast.walk(mod.tree):
        if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load):
            raise EditRefused("%s is not removed: line %d uses it" % (name, n.lineno))
    src = mod.src
    k = s.lineno - 1
    lines = text.splitlines(keepends=True)
    while k > 0 and lines[k - 1].lstrip().startswith("#"):
        k -= 1
    start = src.starts[k]
    le = src.line_end(src.span(s)[1])
    end = le + (len(src.newline_at(le)) if le < len(text) else 0)
    out = _splice(text, [(_tidy_start(text, start, end), end, "")])
    if _dump_without(text, s.lineno) != ast.dump(ast.parse(out)):
        raise EditRefused("the edit would change more than the removed constant")
    return out


# ------------------------------------------------------------------ statements by region
def _is_place(stmt) -> bool:
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "place")


def _is_group(stmt) -> bool:
    """A `board.row(...)` or `board.ring(...)` statement (bare or bound to a name): it says where its items go."""
    v = stmt.value if isinstance(stmt, (ast.Expr, ast.Assign)) else None
    return isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr in ("row", "ring")


def _place_at(stmt):
    """The value a `board.place(...)` statement gives for `at=` (a keyword or the second argument), or None."""
    call = stmt.value
    kw = next((k.value for k in call.keywords if k.arg == "at"), None)
    if kw is not None:
        return kw
    pos = _positional(call)
    return pos[1] if len(pos) > 1 else None


def _decided(stmt) -> bool:
    if _is_group(stmt):
        return True
    at = _place_at(stmt)
    return at is not None and not (isinstance(at, ast.Call) and _func_name(at) == "Near")


def _is_outline(stmt) -> bool:
    c = stmt.value if isinstance(stmt, (ast.Expr, ast.Assign)) else None
    return isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in ("rect", "disc", "outline")


def _header_end(mod) -> int:
    body = mod.tree.body
    i = 1 if body and _is_docstring(body[0]) else 0
    while i < len(body) and (_is_import(body[i]) or (isinstance(body[i], (ast.If, ast.Try)) and _only_imports(body[i]))):
        i += 1
    return i


def _region_after(mod, region):
    """(the index in the module body after which a statement of `region` goes, whether the region is new: a blank line
    then goes before the statement)."""
    body = mod.tree.body
    header = _header_end(mod)
    consts, has = _block_end(mod)
    outline = next((k for k, s in enumerate(body) if _is_outline(s)), None)
    out_end = None
    if outline is not None:
        out_end = outline + 1
        while out_end < len(body) and isinstance(body[out_end], ast.Assign) and isinstance(body[out_end].value, ast.Call) \
                and isinstance(body[out_end].value.func, ast.Attribute) and not _is_group(body[out_end]):
            out_end += 1
    base = out_end if out_end is not None else consts
    decided = [k for k, s in enumerate(body) if (_is_place(s) or _is_group(s)) and _decided(s)]
    searched = [k for k, s in enumerate(body) if _is_place(s) and not _decided(s)]
    if region == "header":
        return header, False
    if region == "constants":
        return consts, False
    if region == "outline":
        return base, outline is None and base > 0
    if region == "decided":
        return (decided[-1] + 1 if decided else base), not decided and base > 0
    if region == "searched":
        if searched:
            return searched[-1] + 1, False
        return (decided[-1] + 1 if decided else base), True
    raise EditRefused("unknown region %r" % (region,))


def _insert_region(text, edit, texts_of):
    mod = _parse(text)
    value = edit.value
    block = value.get("block") if isinstance(value, dict) else None
    forms = block if block is not None else [value]
    if not forms or not all(isinstance(f, dict) and "form" in f for f in forms):
        raise EditRefused("an inserted statement is a call")
    idx, new_region = _region_after(mod, edit.args["after"]["region"])
    ctx = _Ctx(_names_of(mod), _spell_for(texts_of, edit.refs, edit.file, ()), _bound_names(mod), {})
    lines, bound = [], set(ctx.bound)
    binds = [f.get("bind") for f in forms]
    if edit.args.get("bind"):
        if block is not None or len(forms) != 1:
            raise EditRefused("a block of statements is bound by name in each statement, not as a whole")
        binds = [edit.args["bind"]]
    for f, bind in zip(forms, binds):
        ctx.bound = set(bound)
        new = _render(f, ctx)
        _check_expr(new)
        if bind:
            if not bind.isidentifier() or bind in bound:
                raise EditRefused("%s is a name the script already binds, or not a name" % bind)
            new = "%s = %s" % (bind, new)
            bound.add(bind)
        lines.append(new)
    nl = _nl_of(text)
    note = edit.args.get("comment")
    head = _comment_block(note, nl) if note and new_region else ""
    at, needs_nl = _line_after(mod, idx)
    lead = nl if new_region and idx > 0 else ""
    body = nl.join(lines)
    out = text + nl + lead + head + body + nl if needs_nl else _splice(text, [(at, at, lead + head + body + nl)])
    try:
        tree = ast.parse(out)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    body_nodes = list(tree.body)
    del body_nodes[idx:idx + len(forms)]
    if ast.dump(ast.Module(body_nodes, [])) != ast.dump(ast.Module(mod.tree.body, [])):
        raise EditRefused("the edit would change more than the inserted statement")
    return out


def _unordered(tree):
    """`tree` with every statement list sorted, so two orders of the same statements compare equal."""
    for seq in reversed(list(_stmt_lists(tree))):
        seq.sort(key=ast.dump)
    return ast.dump(tree)


def _move_statement(text, edit):
    """The target statement's line moved before or after another statement of the same block, its trailing comment with
    it; comments on lines above it stay."""
    from .suggestions import Target
    mod, hit = _locate_stmt(text, edit.target)
    where = "after" if "after" in edit.args else "before"
    other = _locate(mod, Target.from_json(edit.args[where]), want_stmt=True)
    mine, theirs = hit.stmt, other.stmt
    if mine is theirs:
        raise EditRefused("a statement is not moved relative to itself")
    if not any(any(x is mine for x in seq) and any(x is theirs for x in seq) for seq in _stmt_lists(mod.tree)):
        raise EditRefused("the two statements are not in one block")
    src = mod.src
    nl = _nl_of(text)
    a = src.line_start(src.span(mine)[0])
    le = src.line_end(src.span(mine)[1])
    b = le + (len(src.newline_at(le)) if le < len(text) else 0)
    moved = text[a:le] + nl
    ts, te = src.span(theirs)
    if where == "before":
        c = src.line_start(ts)
    else:
        tle = src.line_end(te)
        c = tle + (len(src.newline_at(tle)) if tle < len(text) else 0)
        if tle >= len(text):
            c, moved = tle, nl + text[a:le]
    if a <= c <= b:
        raise EditRefused("the statement is already there")
    if b >= len(text) and a > 0 and c < a:
        # the last line has no newline: it keeps none
        moved = text[a:le] + nl
        b = le
    out = _splice(text, [(a, b, ""), (c, c, moved)])
    try:
        ok = _unordered(ast.parse(text)) == _unordered(ast.parse(out))
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    if not ok:
        raise EditRefused("the edit would change more than the order")
    return out


# ------------------------------------------------------------------ reading an intent back
INTENT_FORMS = frozenset(("Beside", "OnEdge", "Centre", "Near", "Mid", "X", "Y", "Between", "Past", "SideOf", "Fraction",
                          "Polar", "OnRim", "OnBore", "Turned", "Facing", "Parallel", "Corner", "Land", "Row", "Part", "Cell",
                          "PadRef", "CellPadRef", "board.edge", "board.edges"))


class _ByHand(Exception):
    """A declaration outside the closed vocabulary: shown as written, not as an intent."""


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id] + parts[::-1])
    raise _ByHand()


def _intent_of(node):
    if isinstance(node, ast.Constant):
        if node.value is None or isinstance(node.value, (bool, int, float)):
            return node.value
        if isinstance(node.value, str):
            return {"str": node.value}
        raise _ByHand()
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) \
            and isinstance(node.operand.value, (int, float)):
        return -node.operand.value
    if isinstance(node, ast.Name):
        return {"name": node.id}
    if isinstance(node, ast.Attribute):
        return {"enum": _dotted(node)}
    if isinstance(node, ast.List):
        return {"list": [_intent_of(e) for e in node.elts]}
    if isinstance(node, ast.Tuple):
        return {"tuple": [_intent_of(e) for e in node.elts]}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return {"div": [_intent_of(node.left), _intent_of(node.right)]}
    if isinstance(node, ast.Call):
        name = _dotted(node.func)
        short = name.split(".")[-1] if not name.startswith("board.") else name
        if short not in INTENT_FORMS:
            raise _ByHand()
        if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
            raise _ByHand()
        args = [_intent_of(a) for a in node.args]
        kwargs = {k.arg: _intent_of(k.value) for k in node.keywords}
        if short in ("Part", "Cell") and len(args) == 1 and not kwargs and isinstance(args[0], dict) and "str" in args[0]:
            return {"item": args[0]["str"]}
        if short == "PadRef" and len(args) == 2 and not kwargs and isinstance(args[0], dict) and "item" in args[0]:
            return {"pad": [args[0]["item"], args[1]]}
        if short == "Centre":
            if any(isinstance(a, (int, float)) and not isinstance(a, bool) for a in args[:2]) or kwargs.get("coordinates") is True:
                raise _ByHand()
        return {"form": short if not name.startswith("board.") else name, "args": args, "kwargs": kwargs}
    raise _ByHand()


def read_intent(text: str, target, name: str = "at"):
    """The value of the target call's `name` argument (default `at`) as the intent expression that writes it: the inverse
    of `_render` over the builder's closed vocabulary (relations, edges, intent `Centre`, items, pads, enums, numbers,
    names). `{"absent": True}` where the call does not give it; None where it is not readable as an intent (a coordinate,
    arithmetic, a form outside the vocabulary): "by hand"."""
    mod, hit = _call_of(text, target)
    arg = _given(hit.call, target.kind, name)
    if arg is None:
        return {"absent": True}
    try:
        return _intent_of(_value_node(arg))
    except _ByHand:
        return None


def read_call(text: str, target) -> dict:
    """Every argument of the target call as `read_intent` reads one: `{"args": [...], "kwargs": {name: ...}, "line": n}`, each
    value an intent expression or None where that argument is not readable as one (a coordinate, arithmetic, a form outside the
    vocabulary). A call that spreads `*` or `**` arguments is `{"spread": True}`."""
    mod, hit = _call_of(text, target)
    call = hit.call
    if any(isinstance(a, ast.Starred) for a in call.args) or _has_star_kwargs(call):
        return {"spread": True, "line": hit.line, "args": [], "kwargs": {}}

    def read(node):
        try:
            return _intent_of(node)
        except _ByHand:
            return None
    return {"args": [read(a) for a in call.args], "kwargs": {k.arg: read(k.value) for k in call.keywords}, "line": hit.line,
            "end": hit.end}


def site_calls(text: str, line: int) -> list:
    """The `board.<method>` calls that start on `line` of the script (as `["place"]`): what a declared site is a call of."""
    mod = _parse(text)
    return [n.func.attr for n in ast.walk(mod.tree) if isinstance(n, ast.Call) and n.lineno == line and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "board"]


def skeleton(name: str, description: str, outline=None) -> str:
    """The text of a new layout script: its docstring (`name: description`, or `name layout.` with no description), the
    import, and the outline statement, `outline` an intent expression (`{"form": "board.rect", "args": [...]}`) or None.
    The only generator of whole-file text."""
    description = description.strip().replace('"', "'")
    doc = "%s: %s" % (name, description) if description else "%s layout." % name
    head = '"""%s"""\nfrom placemat import board\n' % doc
    if outline is None:
        return head
    mod = _parse(head)
    ctx = _Ctx(_names_of(mod), lambda key: (_ for _ in ()).throw(EditRefused("%s is not an item here" % key)),
               _bound_names(mod), {})
    return head + "\n" + _render(outline, ctx) + "\n"


def apply_all(edit, read=_read_default) -> dict:
    """{file: (before, after)} for every file the edit writes, the first being the script (or the settings file).
    `read(path)` gives a file's text. A target whose digest differs from the file's text is refused as stale."""
    if edit.op not in OPS:
        raise EditRefused("unknown edit operation %r" % (edit.op,))
    cache = {}

    def texts_of(path):
        if path not in cache:
            cache[path] = read(path)
        return cache[path]
    if edit.op == "toml_set":
        text = texts_of(edit.file)
        a = edit.args
        return {edit.file: (text, toml_set(text, a["table"], a["key"], edit.value, a.get("comment", "")))}
    if edit.op == "create_file":
        try:
            texts_of(edit.file)
        except OSError:
            return {edit.file: (None, edit.args["text"])}
        raise EditRefused("%s exists: a new file is not written over it" % edit.file)
    if edit.op in ("zen_stackup", "zen_netclasses"):
        from . import zen_edit
        text = texts_of(edit.file)
        a = edit.args
        if edit.op == "zen_stackup":
            new = zen_edit.stackup_edit(text, a["board"], a["layers"], a.get("copper_layers"))
        else:
            new = zen_edit.netclasses_edit(text, a["board"], a["classes"])
        return {edit.file: (text, new)}
    if edit.op == "json_set":
        from . import json_edit
        text = texts_of(edit.file)
        return {edit.file: (text, json_edit.set_values(text, [(s["path"], s["value"]) for s in edit.args["sets"]]))}
    if edit.op == "confirm_facts":
        from .facts import confirmed_text
        try:
            text = texts_of(edit.file)
        except OSError:
            text = None
        return {edit.file: (text, confirmed_text(text or "", edit.args["digest"], edit.args.get("key")))}
    if edit.op == "ensure_import":
        text = texts_of(edit.file)
        return {edit.file: (text, _ensure_import(text, edit.args["names"]))}
    if edit.op == "remove_constant":
        text = texts_of(edit.file)
        return {edit.file: (text, _remove_constant(text, edit.args["name"]))}
    if edit.op == "move_statement":
        t = edit.target
        text = texts_of(t.file)
        if t.digest and digest(text) != t.digest:
            raise StaleEdit([t.file])
        return {t.file: (text, _move_statement(text, edit))}
    if edit.op == "insert_statement" and edit.target is None:
        text = texts_of(edit.file)
        return {edit.file: (text, _insert_region(text, edit, texts_of))}
    if edit.op == "set_constant":
        a = edit.args
        text = texts_of(edit.file)
        if a.get("existing"):
            return {edit.file: (text, _change_constant(text, a["name"], edit.value, a.get("comment", ""), a.get("replace_comment", False)))}
        module = _parse(text)
        name = _unique(a["name"], _bound_names(module) | _local_module_names(texts_of, edit.file, module))
        return {edit.file: (text, _add_constant(text, name, edit.value, a.get("comment", "")))}
    t = edit.target
    if t is None or not t.file:
        raise EditRefused("the edit has no target")
    home = t.file
    text = texts_of(home)
    if t.digest and digest(text) != t.digest:
        raise StaleEdit([home])
    consts = []
    _find_consts(edit.value, consts)
    if len(consts) > 1:
        raise EditRefused("one constant to an edit")
    names, plan = {}, None
    if consts:
        c = consts[0]["const"]
        cfile = c.get("file") or home
        ctext = texts_of(cfile)
        if cfile != home and c.get("digest") and digest(ctext) != c["digest"]:
            raise StaleEdit([cfile])
        cmodule = _parse(ctext)
        taken = _bound_names(cmodule) | _local_module_names(texts_of, cfile, cmodule)
        if cfile != home:
            taken |= _bound_names(_parse(text))
        names[id(consts[0])] = _unique(c["name"], taken)
        plan = (cfile, ctext, c)
    new = _CALL_OPS[edit.op](text, edit, _context(texts_of, edit, names))
    out = {home: (text, new)}
    if plan is not None:
        cfile, ctext, c = plan
        name = names[id(consts[0])]
        if cfile == home:
            out[home] = (text, _add_constant(new, name, c["value"], c.get("comment", "")))
        else:
            out[cfile] = (ctext, _add_constant(ctext, name, c["value"], c.get("comment", "")))
            out[home] = (text, _import_name(new, Path(cfile).stem, name))
    return out


def _remap(before: str, after: str, line: int) -> int:
    """Where line `line` of `before` is in `after`: through the lines the two share; a line the edit changed goes to where
    its change starts."""
    import difflib
    a, b = before.splitlines(), after.splitlines()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if i1 < line <= i2 or (i1 == i2 == line - 1 and tag == "insert"):
            if tag == "equal":
                return j1 + (line - i1)
            return j1 + 1
    return line


def apply_edits(edits, read=_read_default) -> dict:
    """{file: (before, after)} for every file the edits write, made together or not at all; `before` is None for a file
    the edits create. Each edit's digest is checked against the file as it stood at the plan (one stale file refuses all);
    the edits are then made one after another on the evolving text, each target's line carried through what the edits
    before it changed, so their order does not matter and a constant one adds above does not move the next off its
    call."""
    edits = list(edits)
    if not edits:
        raise EditRefused("there is nothing to edit")
    originals: dict = {}
    current: dict = {}

    def original(path):
        if path not in originals:
            try:
                originals[path] = read(path)
            except OSError:
                originals[path] = None
            current[path] = originals[path]
        return originals[path]

    def now(path):
        original(path)
        if current[path] is None:
            raise FileNotFoundError(path)
        return current[path]
    stale = []
    for e in edits:
        t = e.target
        if t is not None and t.file and t.digest and digest(now(t.file)) != t.digest:
            stale.append(t.file)
    if stale:
        raise StaleEdit(sorted(set(stale)))
    todo = [replace(e, target=replace(e.target, digest="")) if e.target is not None else e for e in edits]
    for k, e in enumerate(todo):
        t = e.target
        if t is not None and t.file:
            original(t.file)
        changed = apply_all(e, now)
        for path, (before, after) in changed.items():
            original(path)
            current[path] = after
            for j in range(k + 1, len(todo)):
                n = todo[j]
                if before is None:
                    continue
                if n.target is not None and n.target.file == path and n.target.line:
                    n = replace(n, target=replace(n.target, line=_remap(before, after, n.target.line)))
                if n.refs:                  # the declarations an expression names move with the text too
                    n = replace(n, refs={k: replace(t, line=_remap(before, after, t.line)) if t.file == path and t.line else t
                                         for k, t in n.refs.items()})
                todo[j] = n
    return {path: (originals[path], text) for path, text in current.items() if text != originals[path]}


def _context(texts_of, edit, names):
    t = edit.target

    def ctx_for(module, hit):
        spell = _spell_for(texts_of, edit.refs, t.file, hit.scope)
        ctx = _Ctx(_names_of(module), spell, _bound_names(module), {})
        ctx.consts.update(names)
        return ctx
    return ctx_for


def apply(edit, text: str) -> str:
    """The edited text of the edit's own file, with `text` as that file (a constant it carries goes there too)."""
    files = apply_all(edit, lambda path: text)
    first = edit.file or (edit.target.file if edit.target else "")
    return files[first][1]


def keyword_constant(text: str, target, name: str):
    """The name of the module-level constant that the target call's keyword `name` reads (`gap=GAP`), or None where it
    is not given, is not a bare name, or the name is not assigned exactly once in the file."""
    mod, hit = _call_of(text, target)
    kw = next((k for k in hit.call.keywords if k.arg == name), None)
    if kw is None or not isinstance(kw.value, ast.Name):
        return None
    ident = kw.value.id
    return ident if sum(1 for s in mod.tree.body if _assigns(s, ident)) == 1 else None


def _local_imports(script: Path) -> dict:
    """{module stem: its file} for the modules the script imports that sit among its own files."""
    from .settings import _files
    tops = [script.parent]
    found = _files(script.parent)
    if found:
        d = script.parent
        while d != found[0].parent and d.parent != d:
            d = d.parent
            tops.append(d)
    out = {}
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return out
    for node in ast.walk(tree):
        names = [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else (
            [a.name for a in node.names] if isinstance(node, ast.Import) else [])
        for full in names:
            stem = full.split(".")[0]
            for d in tops:
                cand = d / (stem + ".py")
                if cand.is_file() and cand != script:
                    out.setdefault(stem, str(cand))
                    break
    return out


_SKIP_DIRS = {".git", ".placemat", "__pycache__", "node_modules", ".venv", "venv", "generated"}


def shared_module(script) -> str | None:
    """The module the board's layout scripts share: of the local modules the script imports, the one most layout
    scripts of the project import (at least one other besides this script), or None. A layout script is a file of
    the project that imports placemat."""
    script = Path(script).resolve()
    mine = _local_imports(script)
    if not mine:
        return None
    from .settings import _files
    found = _files(script.parent)
    root = found[0].parent if found else script.parent
    counts = {stem: 1 for stem in mine}
    scanned = 0
    for p in sorted(root.rglob("*.py")):
        if p == script or any(part in _SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts[:-1]):
            continue
        scanned += 1
        if scanned > 400:
            break
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "placemat" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
        for stem in counts:
            if stem in imported and Path(mine[stem]) != p:
                counts[stem] += 1
    best = max(counts, key=lambda s: counts[s])
    return mine[best] if counts[best] >= 2 else None
