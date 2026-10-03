"""Edits to a layout script and to placemat.toml, as pure functions of the file's text.

An `Edit` (suggestions.Edit) names a declaration (its target call) and an operation; `apply_all` gives the
edited text of every file it writes. The text is edited as a LibCST tree, so every comment and the layout of
everything outside the target prints as it was; what is written inside the target follows the layout of what
was there (see `_Seq`). Two checks stand between an edit and the caller: the edited text must parse, and the
`ast` of everything outside the target must equal the original's. Either failing refuses the edit.

A value an edit writes is an intent expression (a dict), never source: forms and enums are written as the
script imports them, an item as the script spelled it where it declared it, and a measured number as a named
constant with a comment (`set_constant`)."""
from __future__ import annotations

import ast
import difflib
import functools
import hashlib
import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

OPS = ("set_kwarg", "remove_kwarg", "set_arg", "edit_list", "insert_statement", "remove_statement", "set_constant",
       "toml_set")


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


# ------------------------------------------------------------------ whitespace
def _is_par(ws) -> bool:
    return isinstance(ws, cst.ParenthesizedWhitespace)


def _comment_of(ws):
    return ws.first_line.comment if _is_par(ws) else None


def _merge(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return cst.Comment(a.value + "  " + b.value)


def _par(like, comment=None, empty_lines=(), last_line=None, gap="  "):
    """A newline in a parenthesis laid out as `like` (a ParenthesizedWhitespace): its indent, its last line."""
    return cst.ParenthesizedWhitespace(
        first_line=cst.TrailingWhitespace(whitespace=cst.SimpleWhitespace(gap if comment is not None else ""),
                                          comment=comment, newline=cst.Newline()),
        empty_lines=list(empty_lines), indent=like.indent,
        last_line=like.last_line if last_line is None else last_line)


def _with_comment(ws, comment):
    """`ws` (a newline) with this comment at the end of the line before it."""
    gap = ws.first_line.whitespace if ws.first_line.whitespace.value else cst.SimpleWhitespace("  ")
    return ws.with_changes(first_line=ws.first_line.with_changes(
        comment=comment, whitespace=gap if comment is not None else cst.SimpleWhitespace("")))


def _comment_line(like, comment):
    """A line of its own holding only `comment`, at the indent of `like`'s next line."""
    return cst.EmptyLine(indent=like.indent, whitespace=like.last_line, comment=comment, newline=cst.Newline())


# ------------------------------------------------------------------ a sequence: call arguments, list elements
@dataclass
class _Slot:
    item: object            # an Arg or an Element, its comma left to `ws` and `comma`
    ws: object              # what follows it: the whitespace after its comma, or after it where it has none
    comma: bool             # written with a comma (a non-last item always is)
    comma_node: object = None
    after_arg: object = None


class _Seq:
    """The arguments of a call, or the elements of a list or a tuple, as slots: each item with the whitespace
    after it, so one can be added or removed without disturbing the others' layout.

    Whitespace after the last item sits in different places: after its comma in a call's arguments, in the
    closing bracket's `whitespace_before` in a list or a tuple."""

    def __init__(self, node):
        self.node = node
        self.call = isinstance(node, cst.Call)
        if self.call:
            self.items = list(node.args)
        elif isinstance(node, cst.List):
            self.items = list(node.elements)
        elif isinstance(node, cst.Tuple) and node.lpar and node.rpar:
            self.items = list(node.elements)
        else:
            raise EditRefused("not a list or a tuple written with brackets")
        self.slots = [self._slot(i, it) for i, it in enumerate(self.items)]
        self.lead = (node.whitespace_before_args if self.call else
                     node.lbracket.whitespace_after if isinstance(node, cst.List) else node.lpar[0].whitespace_after)

    def _closing(self):
        n = self.node
        return n.rbracket.whitespace_before if isinstance(n, cst.List) else n.rpar[0].whitespace_before

    def _slot(self, i, item):
        last = i == len(self.items) - 1
        comma = isinstance(item.comma, cst.Comma)
        if not last:
            return _Slot(item, item.comma.whitespace_after, True, item.comma, getattr(item, "whitespace_after_arg", None))
        if self.call:
            return _Slot(item, item.comma.whitespace_after if comma else item.whitespace_after_arg, comma,
                         item.comma if comma else None, item.whitespace_after_arg if comma else None)
        return _Slot(item, self._closing(), comma, item.comma if comma else None)

    def build(self, slots, lead):
        items = []
        closing = None
        for i, s in enumerate(slots):
            last = i == len(slots) - 1
            item = s.item
            if not last or s.comma:
                comma_ws = s.ws if (not last or self.call) else cst.SimpleWhitespace("")
                comma = (s.comma_node.with_changes(whitespace_after=comma_ws) if s.comma_node is not None
                         else cst.Comma(whitespace_before=cst.SimpleWhitespace(""), whitespace_after=comma_ws))
                changes = {"comma": comma}
                if self.call:
                    changes["whitespace_after_arg"] = s.after_arg if s.after_arg is not None else cst.SimpleWhitespace("")
                item = item.with_changes(**changes)
            else:
                changes = {"comma": cst.MaybeSentinel.DEFAULT}
                if self.call:
                    changes["whitespace_after_arg"] = s.ws
                item = item.with_changes(**changes)
            if last and not self.call:
                closing = s.ws
            items.append(item)
        n = self.node
        if self.call:
            return n.with_changes(args=items, whitespace_before_args=lead)
        if closing is None:
            closing = cst.SimpleWhitespace("")
        if isinstance(n, cst.List):
            return n.with_changes(elements=items, lbracket=n.lbracket.with_changes(whitespace_after=lead),
                                  rbracket=n.rbracket.with_changes(whitespace_before=closing))
        return n.with_changes(elements=items, lpar=[n.lpar[0].with_changes(whitespace_after=lead)],
                              rpar=[n.rpar[0].with_changes(whitespace_before=closing)])


def _indent_of(seq: _Seq, slots, lead):
    """The newline layout in front of the items: the last one that precedes an item, or None on one line."""
    found = None
    if _is_par(lead):
        found = lead
    for s in slots[:-1]:
        if _is_par(s.ws):
            found = s.ws
    return found


def _insert(seq: _Seq, slots, lead, k, item, comment=None):
    """`item` (an Arg or an Element, with no comma set) at index k."""
    n = len(slots)
    new = _Slot(item, cst.SimpleWhitespace(""), False)
    if n == 0:
        return [new], lead
    if k >= n:
        last = slots[-1]
        old = last.ws
        like = _indent_of(seq, slots, lead)
        if _is_par(old):
            ind = like.last_line if like is not None else old.last_line
            keep = _par(old, comment=_comment_of(old), last_line=ind, gap=old.first_line.whitespace.value or "  ")
            tail = _par(old, comment=comment, empty_lines=old.empty_lines)
            if like is None:
                keep = keep.with_changes(last_line=cst.SimpleWhitespace(old.last_line.value + "    "))
            slots = slots[:-1] + [_Slot(last.item, keep, True, last.comma_node, last.after_arg),
                                  _Slot(item, tail, last.comma)]
        elif like is not None:
            slots = slots[:-1] + [_Slot(last.item, _par(like, last_line=like.last_line), True, last.comma_node, last.after_arg),
                                  _Slot(item, old, last.comma)]
        else:
            slots = slots[:-1] + [_Slot(last.item, cst.SimpleWhitespace(" "), True, last.comma_node, last.after_arg),
                                  _Slot(item, old, last.comma)]
        return slots, lead
    before = lead if k == 0 else slots[k - 1].ws
    if _is_par(before):
        sep = _par(before, comment=comment)
    else:
        sep = cst.SimpleWhitespace(before.value if k > 0 and before.value else " ")
    return slots[:k] + [_Slot(item, sep, True)] + slots[k:], lead


def _remove(slots, lead, i, carry=False):
    """The slots and lead without item i, and the comment that was on its line: left where the item stood (on
    the previous item's line, or a line of its own), never lost; with `carry`, only returned, for the caller to
    put on the item where it goes."""
    n = len(slots)
    gone = slots[i]
    c = _comment_of(gone.ws)
    if carry and c is not None:
        gone = _Slot(gone.item, _with_comment(gone.ws, None), gone.comma, gone.comma_node, gone.after_arg)
        slots = slots[:i] + [gone] + slots[i + 1:]
        got = c
        c = None
    else:
        got = c
    if n == 1:
        if c is not None:
            return [], _par(gone.ws, comment=lead.first_line.comment if _is_par(lead) else None,
                            empty_lines=[_comment_line(gone.ws, c)], last_line=gone.ws.last_line), got
        return [], cst.SimpleWhitespace(""), got
    if i < n - 1:
        rest = slots[:i] + slots[i + 1:]
        if c is None:
            return rest, lead, got
        if i > 0:
            prev = rest[i - 1]
            if _is_par(prev.ws):
                rest[i - 1] = _Slot(prev.item, _with_comment(prev.ws, _merge(_comment_of(prev.ws), c)), prev.comma,
                                    prev.comma_node, prev.after_arg)
            return rest, lead, got
        if _is_par(lead):
            return rest, lead.with_changes(empty_lines=list(lead.empty_lines) + [_comment_line(lead, c)]), got
        return rest, _par(gone.ws, comment=c, gap="  "), got
    prev = slots[i - 1]
    ws = gone.ws
    if _is_par(ws):
        if _is_par(prev.ws):
            merged = _par(ws, comment=_merge(_comment_of(prev.ws), c),
                          empty_lines=list(prev.ws.empty_lines) + list(ws.empty_lines), last_line=ws.last_line,
                          gap=prev.ws.first_line.whitespace.value or ws.first_line.whitespace.value or "  ")
        else:
            merged = ws
    elif _is_par(prev.ws) and _comment_of(prev.ws) is not None:
        merged = prev.ws
    else:
        merged = ws
    return slots[:i - 1] + [_Slot(prev.item, merged, gone.comma, prev.comma_node if gone.comma else None,
                                  prev.after_arg)], lead, got


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


class _ImportScan(cst.CSTVisitor):
    def __init__(self):
        self.names, self.star, self.modules, self.stems = set(), False, set(), {}

    def visit_ImportFrom(self, node):
        mod = node.module
        text = _dotted(mod) if mod is not None else ""
        self.stems.setdefault(text, []).append(node)
        if isinstance(node.names, cst.ImportStar):
            if text.split(".")[0] == "placemat":
                self.star = True
            return
        for a in node.names:
            nm = a.asname.name.value if a.asname else _dotted(a.name)
            self.names.add(nm)

    def visit_Import(self, node):
        for a in node.names:
            full = _dotted(a.name)
            nm = a.asname.name.value if a.asname else full.split(".")[0]
            self.names.add(nm)
            if full.split(".")[0] == "placemat":
                self.modules.add(nm)
            self.stems.setdefault(full, []).append(node)


def _dotted(node) -> str:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return _dotted(node.value) + "." + node.attr.value
    return ""


def _names_of(module) -> _Names:
    scan = _ImportScan()
    module.visit(scan)
    return _Names(scan.names, scan.star, scan.modules)


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
    call: object
    line: int
    end: int
    scope: tuple
    in_loop: bool
    stmt: object            # the SimpleStatementLine holding it, when it stands alone as a statement


class _Finder(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, method):
        self.method = method
        self.found = []
        self.scope = []
        self.loops = 0
        self.stmts = []
        self.dirty = 0

    def visit_FunctionDef(self, node):
        self.scope.append(node.name.value)

    def leave_FunctionDef(self, node):
        self.scope.pop()

    def visit_ClassDef(self, node):
        self.scope.append(node.name.value)

    def leave_ClassDef(self, node):
        self.scope.pop()

    def visit_For(self, node):
        self.loops += 1

    def leave_For(self, node):
        self.loops -= 1

    def visit_While(self, node):
        self.loops += 1

    def leave_While(self, node):
        self.loops -= 1

    def visit_CompFor(self, node):
        self.loops += 1

    def leave_CompFor(self, node):
        self.loops -= 1

    def visit_SimpleStatementLine(self, node):
        self.stmts.append(node)

    def leave_SimpleStatementLine(self, node):
        self.stmts.pop()

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, cst.Attribute) and f.attr.value == self.method:
            pos = self.get_metadata(PositionProvider, node)
            stmt = self.stmts[-1] if self.stmts else None
            alone = stmt is not None and len(stmt.body) == 1 and isinstance(stmt.body[0], cst.Expr) and stmt.body[0].value is node
            self.found.append(_Found(node, pos.start.line, pos.end.line, tuple(self.scope), self.loops > 0,
                                     stmt if alone else None))


def _name_literal(call, index, keyword):
    """The string a call gives as its `index`th positional argument or `keyword=`, or None when it is not a literal."""
    pos = [a for a in call.args if a.keyword is None and not a.star]
    node = None
    for a in call.args:
        if a.keyword is not None and a.keyword.value == keyword:
            node = a.value
    if node is None and len(pos) > index:
        node = pos[index].value
    if isinstance(node, cst.SimpleString):
        try:
            return ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return None
    return None


_FINDERS: dict = {}


def _finder_for(module, method):
    """The module's calls of `board.<method>` with their positions, worked out once per module."""
    key = (id(module), method)
    hit = _FINDERS.get(key)
    if hit is not None and hit[0] is module:
        return hit[1], hit[2]
    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    finder = _Finder(method)
    wrapper.visit(finder)
    if len(_FINDERS) > 96:
        _FINDERS.clear()
    _FINDERS[key] = (module, wrapper, finder)
    return wrapper, finder


def _locate(module, target, want_stmt=False):
    """The one call of this target in `module`: its method, its declared line, and (for a keepout, whose key is
    its name) the name it gives. Refused when there is none, or more than one, or it runs for several items."""
    if not target.line:
        raise EditRefused("the declaration of %s has no line: the script did not say where it was declared" % target.key)
    wrapper, finder = _finder_for(module, target.kind)
    hits = [f for f in finder.found if f.line == target.line]
    if not hits:
        hits = [f for f in finder.found if f.line <= target.line <= f.end]
    if target.kind == "keepout":
        keyed = [f for f in hits if _name_literal(f.call, 1, "name") in (None, target.key)]
        hits = keyed
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
    return wrapper, hit


# ------------------------------------------------------------------ transformations
class _Replace(cst.CSTTransformer):
    """The module with one node (found by identity) replaced, and nothing else touched."""

    def __init__(self, old, new):
        self.old, self.new, self.done = old, new, False

    def on_leave(self, original, updated):
        if original is self.old:
            self.done = True
            return self.new
        return updated


class _AfterStatement(cst.CSTTransformer):
    def __init__(self, anchor, new_lines):
        self.anchor, self.new_lines, self.done = anchor, new_lines, False

    def leave_SimpleStatementLine(self, original, updated):
        if original is self.anchor:
            self.done = True
            return cst.FlattenSentinel([updated] + self.new_lines)
        return updated


def _replace(wrapper, old, new):
    t = _Replace(old, new)
    out = wrapper.module.visit(t)
    if not t.done:
        raise EditRefused("the target was not found in the tree")
    return out


@functools.lru_cache(maxsize=32)
def _parse_cached(text):
    return cst.parse_module(text)


def _parse(text):
    """The text as a LibCST module. Modules are immutable, so a text parsed once (every suggestion of a plan reads
    the same script) is not parsed again."""
    try:
        return _parse_cached(text)
    except cst.ParserSyntaxError as e:
        raise EditRefused("the file does not parse: %s" % e)


def _expr(src: str):
    try:
        return cst.parse_expression(src)
    except cst.ParserSyntaxError as e:
        raise EditRefused("%r does not parse: %s" % (src, e))


def _arg(name, src):
    return _expr("f(%s=%s)" % (name, src)).args[0] if name else _expr("f(%s)" % src).args[0]


def _bound_names(module) -> set:
    out = set()

    class V(cst.CSTVisitor):
        def visit_Name(self, node):
            out.add(node.value)
    module.visit(V())
    return out


def _spell_for(texts_of, refs, home_file, home_scope):
    """A function: the source the script uses for an item, from the call that declared it."""
    def spell(key):
        ref = refs.get(key)
        if ref is None:
            raise EditRefused("%s is not an item this edit has a declaration for" % key)
        text = texts_of(ref.file)
        module = _parse(text)
        wrapper, hit = _locate(module, ref)
        if ref.file != home_file or hit.scope != home_scope:
            raise EditRefused("%s is declared in another file or scope than the call being edited" % key)
        positional = [a for a in hit.call.args if a.keyword is None and not a.star]
        first = positional[0].value if positional else next((a.value for a in hit.call.args if a.keyword and a.keyword.value in ("item", "name")), None)
        if first is None:
            raise EditRefused("the declaration of %s has no first argument to spell it from" % key)
        return module.code_for_node(first)
    return spell


def spelling(text: str, target) -> str:
    """How the script at `text` writes the item a call declares: its first argument, as written."""
    module = _parse(text)
    _, hit = _locate(module, target)
    positional = [a for a in hit.call.args if a.keyword is None and not a.star]
    if not positional:
        raise EditRefused("%s has no first argument" % target.key)
    return module.code_for_node(positional[0].value)


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


def _masked_call_dump(text, line, func_dump):
    tree = ast.parse(text)
    hits = _calls_at(tree, line, func_dump)
    if not hits:
        raise EditRefused("the target call is not where the edit left it")
    return ast.dump(_Mask(hits[0]).visit(tree))


def _check_call_edit(before, after, hit_line, func_dump):
    """The edited text parses and everything outside the target call is the tree it was."""
    try:
        ast.parse(after)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    if _masked_call_dump(before, hit_line, func_dump) != _masked_call_dump(after, hit_line, func_dump):
        raise EditRefused("the edit would change more than the target call")


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
def _call_of(text, target):
    module = _parse(text)
    wrapper, hit = _locate(module, target)
    return module, wrapper, hit


def _keywords(call):
    return {a.keyword.value: a for a in call.args if a.keyword is not None}


@functools.lru_cache(maxsize=None)
def _positional_index(kind, name):
    """Where the board method `kind` takes its parameter `name` by position (0 for the first after self), or None
    where it is by keyword alone."""
    import inspect
    from .layout import Board
    fn = getattr(Board, kind, None)
    if fn is None:
        return None
    index = 0
    for p in list(inspect.signature(fn).parameters.values())[1:]:
        if p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            return None
        if p.name == name:
            return index
        index += 1
    return None


def _given(call, kind, name):
    """The argument that gives parameter `name` of the call: `name=...`, or the argument in its position."""
    kw = _keywords(call).get(name)
    if kw is not None:
        return kw
    index = _positional_index(kind, name)
    if index is None:
        return None
    if any(a.star == "*" for a in call.args):
        raise EditRefused("the call spreads *args, so %s may be given there" % name)
    positional = [a for a in call.args if a.keyword is None and not a.star]
    return positional[index] if index < len(positional) else None


def _has_star_kwargs(call):
    return any(a.star == "**" for a in call.args)


def _finish_call(text, wrapper, hit, new_call):
    func_dump = ast.dump(ast.parse("(%s)" % wrapper.module.code_for_node(hit.call.func), mode="eval").body)
    out = _replace(wrapper, hit.call, new_call).code
    _check_call_edit(text, out, hit.line, func_dump)
    return out


def _set_kwarg(text, edit, ctx_for):
    module, wrapper, hit = _call_of(text, edit.target)
    name = edit.args["name"]
    ctx = ctx_for(module, hit)
    src = _render(edit.value, ctx)
    call = hit.call
    arg = _given(call, edit.target.kind, name)
    if arg is not None:
        if _same(src, module.code_for_node(arg.value)):
            raise EditRefused("%s= is already %s" % (name, src))
        new_args = [a.with_changes(value=_expr(src)) if a is arg else a for a in call.args]
        return _finish_call(text, wrapper, hit, call.with_changes(args=new_args))
    if _has_star_kwargs(call):
        raise EditRefused("the call takes **kwargs: %s= may already be given there" % name)
    seq = _Seq(call)
    new = _arg(name, src)
    slots, lead = _insert(seq, seq.slots, seq.lead, len(seq.slots), new)
    return _finish_call(text, wrapper, hit, seq.build(slots, lead))


def _remove_kwarg(text, edit, ctx_for):
    module, wrapper, hit = _call_of(text, edit.target)
    name = edit.args["name"]
    seq = _Seq(hit.call)
    arg = _given(hit.call, edit.target.kind, name)
    if arg is None:
        raise EditRefused("the call has no %s=" % name)
    k = next(i for i, a in enumerate(seq.items) if a is arg)
    if arg.keyword is None and any(a.keyword is None and not a.star for a in seq.items[k + 1:]):
        raise EditRefused("%s is given by position, and the arguments after it would move up" % name)
    slots, lead, _ = _remove(seq.slots, seq.lead, k)
    return _finish_call(text, wrapper, hit, seq.build(slots, lead))


def _set_arg(text, edit, ctx_for):
    module, wrapper, hit = _call_of(text, edit.target)
    index = edit.args["index"]
    src = _render(edit.value, ctx_for(module, hit))
    positional = [a for a in hit.call.args if a.keyword is None and not a.star]
    if index >= len(positional):
        raise EditRefused("the call has no positional argument %d" % index)
    arg = positional[index]
    new_args = [a.with_changes(value=_expr(src)) if a is arg else a for a in hit.call.args]
    return _finish_call(text, wrapper, hit, hit.call.with_changes(args=new_args))


def _list_arg(call, which, kind):
    if isinstance(which, int):
        pos = [a for a in call.args if a.keyword is None and not a.star]
        return pos[which] if which < len(pos) else None
    return _given(call, kind, which)


def _same(src_a, src_b):
    try:
        return ast.dump(ast.parse(src_a, mode="eval")) == ast.dump(ast.parse(src_b, mode="eval"))
    except SyntaxError:
        return False


def _edit_list(text, edit, ctx_for):
    module, wrapper, hit = _call_of(text, edit.target)
    ctx = ctx_for(module, hit)
    arg = _list_arg(hit.call, edit.args["arg"], edit.target.kind)
    if arg is None:
        if edit.args.get("create") and edit.args.get("action") == "add" and isinstance(edit.args["arg"], str):
            return _set_kwarg(text, replace(edit, op="set_kwarg", args={"name": edit.args["arg"]},
                                            value={"list": [edit.value]}), ctx_for)
        raise EditRefused("the call has no %s" % (edit.args["arg"],))
    seq = _Seq(arg.value)
    sources = [module.code_for_node(it.value) for it in seq.items]
    src = _render(edit.value, ctx)
    action = edit.args["action"]

    def index_of(spec):
        s = _render(spec, ctx)
        for i, have in enumerate(sources):
            if _same(have, s):
                return i
        raise EditRefused("%s is not in the list" % s)

    def element(s):
        return _expr("[%s]" % s).elements[0]
    if action == "add":
        if any(_same(src, have) for have in sources):
            raise EditRefused("%s is already in the list" % src)
        k = len(sources)
        if edit.args.get("before") is not None:
            k = index_of(edit.args["before"])
        elif edit.args.get("after") is not None:
            k = index_of(edit.args["after"]) + 1
        slots, lead = _insert(seq, seq.slots, seq.lead, k, element(src))
    elif action == "remove":
        k = index_of(edit.value)
        slots, lead, _ = _remove(seq.slots, seq.lead, k)
    elif action == "move":
        k = index_of(edit.value)
        item = seq.slots[k].item
        slots, lead, c = _remove(seq.slots, seq.lead, k, carry=True)
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
        slots, lead = _insert(seq, slots, lead, dest, item.with_changes(comma=cst.MaybeSentinel.DEFAULT), c)
    else:
        raise EditRefused("unknown list action %r" % (action,))
    new_list = seq.build(slots, lead)
    new_call = hit.call.with_changes(args=[a.with_changes(value=new_list) if a is arg else a for a in hit.call.args])
    return _finish_call(text, wrapper, hit, new_call)


def _insert_statement(text, edit, ctx_for):
    module, wrapper, hit = _locate_stmt(text, edit.target)
    if not isinstance(edit.value, dict) or "form" not in edit.value:
        raise EditRefused("an inserted statement is a call")
    src = _render(edit.value, ctx_for(module, hit))
    new = cst.SimpleStatementLine(body=[cst.Expr(value=_expr(src))])
    t = _AfterStatement(hit.stmt, [new])
    out = wrapper.module.visit(t).code
    if not t.done:
        raise EditRefused("the target statement was not found")
    try:
        ast.parse(out)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    end = wrapper.resolve(PositionProvider)[hit.stmt].end.line
    if _dump_without(out, end + 1) != ast.dump(ast.parse(text)):
        raise EditRefused("the edit would change more than the inserted statement")
    return out


def _locate_stmt(text, target):
    module = _parse(text)
    wrapper, hit = _locate(module, target, want_stmt=True)
    return module, wrapper, hit


class _Drop(cst.CSTTransformer):
    """The statement `stmt` removed from the block that holds it. Its leading comments and blank lines (a section
    heading above it) go to the statement after it, or to the block's footer where it was the last."""

    def __init__(self, stmt):
        self.stmt, self.done = stmt, False

    def _drop(self, original, updated):
        at = next((k for k, s in enumerate(original.body) if s is self.stmt), None)
        if at is None:
            return updated
        self.done = True
        body = list(updated.body)
        gone = body.pop(at)
        keep = list(gone.leading_lines)
        if at < len(body):
            body[at] = body[at].with_changes(leading_lines=keep + list(body[at].leading_lines))
            return updated.with_changes(body=body)
        return updated.with_changes(body=body, footer=keep + list(updated.footer))

    def leave_Module(self, original, updated):
        return self._drop(original, updated)

    def leave_IndentedBlock(self, original, updated):
        return self._drop(original, updated)


def _remove_statement(text, edit, ctx_for):
    module, wrapper, hit = _locate_stmt(text, edit.target)
    d = _Drop(hit.stmt)
    out = wrapper.module.visit(d).code
    if not d.done:
        raise EditRefused("the target statement was not found")
    try:
        ast.parse(out)
    except SyntaxError as e:
        raise EditRefused("the edited file would not parse: %s" % e)
    if _dump_without(text, wrapper.resolve(PositionProvider)[hit.stmt].start.line) != ast.dump(ast.parse(out)):
        raise EditRefused("the edit would change more than the removed statement")
    return out


_CALL_OPS = {"set_kwarg": _set_kwarg, "remove_kwarg": _remove_kwarg, "set_arg": _set_arg, "edit_list": _edit_list,
             "insert_statement": _insert_statement, "remove_statement": _remove_statement}


# ------------------------------------------------------------------ constants
_UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _is_constant_line(stmt) -> bool:
    """A module-level assignment to upper-case names alone: a line of a constants block."""
    if not isinstance(stmt, cst.SimpleStatementLine) or len(stmt.body) != 1 or not isinstance(stmt.body[0], cst.Assign):
        return False
    a = stmt.body[0]
    if len(a.targets) != 1:
        return False
    t = a.targets[0].target
    names = [t] if isinstance(t, cst.Name) else (list(e.value for e in t.elements) if isinstance(t, cst.Tuple) else [None])
    return all(isinstance(n, cst.Name) and (_UPPER.match(n.value) or n.value == "_") for n in names)


def _is_import(stmt) -> bool:
    return isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) >= 1 and all(
        isinstance(s, (cst.Import, cst.ImportFrom)) for s in stmt.body)


def _is_docstring(stmt) -> bool:
    return (isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1 and isinstance(stmt.body[0], cst.Expr)
            and isinstance(stmt.body[0].value, (cst.SimpleString, cst.ConcatenatedString)))


def _block_end(module):
    """(the index to add a constant at, whether the module has a constants block). The header is the docstring and
    the imports; the block is the run of plain assignments after it, and a constant goes after the last upper-case
    one of them (after the header where there is none)."""
    body = list(module.body)
    i = 1 if body and _is_docstring(body[0]) else 0
    end = i
    while i < len(body) and (_is_import(body[i]) or (isinstance(body[i], (cst.If, cst.Try)) and _only_imports(body[i]))):
        i += 1
        end = i
    has = False
    while i < len(body):
        s = body[i]
        if _is_constant_line(s):
            end, has = i + 1, True
        elif not (isinstance(s, cst.SimpleStatementLine) and len(s.body) == 1 and isinstance(s.body[0], cst.Assign)):
            break
        i += 1
    return end, has


def _only_imports(node) -> bool:
    inner = []

    class V(cst.CSTVisitor):
        def visit_SimpleStatementLine(self, n):
            inner.append(n)
    node.visit(V())
    return bool(inner) and all(_is_import(s) for s in inner)


def _local_module_names(texts_of, home_file, module):
    """Names bound at the top level of the modules this file imports that sit beside it."""
    out = set()
    scan = _ImportScan()
    module.visit(scan)
    base = Path(home_file).parent
    for stem in scan.stems:
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


def _comment_lines(comment):
    return [cst.EmptyLine(indent=True, whitespace=cst.SimpleWhitespace(""), comment=cst.Comment("# " + line),
                          newline=cst.Newline()) for line in comment.splitlines()]


def _constant_text(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EditRefused("a constant holds a number or a string, not %r" % (value,))
    return repr(value)


def _add_constant(text, name, value, comment):
    """`text` with `name = value` added at the end of its constants block (made, after the imports, where there
    is none), the comment on the lines above it."""
    module = _parse(text)
    body = list(module.body)
    end, has = _block_end(module)
    stmt = cst.SimpleStatementLine(body=[cst.Assign(targets=[cst.AssignTarget(target=cst.Name(name))],
                                                    value=_expr(_constant_text(value)))],
                                   leading_lines=([] if has else [cst.EmptyLine(indent=True)]) + _comment_lines(comment))
    new_body = body[:end] + [stmt] + body[end:]
    out = module.with_changes(body=new_body).code
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


def _change_constant(text, name, value, comment):
    """The assignment of `name` given `value`, with the comment above it."""
    module = _parse(text)
    hits = [s for s in module.body if _assigns(s, name)]
    if len(hits) != 1:
        raise EditRefused("%s is assigned %d times in the file, not once" % (name, len(hits)))
    s = hits[0]
    assign = s.body[0].with_changes(value=_expr(_constant_text(value)))
    new = s.with_changes(body=[assign], leading_lines=list(s.leading_lines) + _comment_lines(comment))
    t = _Replace(s, new)
    out = module.visit(t).code
    _check_constant(text, out, name, added=False)
    return out


def _assigns(stmt, name):
    return (isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1 and isinstance(stmt.body[0], cst.Assign)
            and len(stmt.body[0].targets) == 1 and isinstance(stmt.body[0].targets[0].target, cst.Name)
            and stmt.body[0].targets[0].target.value == name)


def _import_name(text, stem, name):
    """`text` importing `name` from the module `stem`: added to its one-line `from stem import ...`, or a line of
    its own after its imports. A script that has `from stem import *` already has it."""
    module = _parse(text)
    anchor = None
    for s in module.body:
        if not _is_import(s):
            continue
        anchor = s
        for item in s.body:
            if isinstance(item, cst.ImportFrom) and item.module is not None and _dotted(item.module) == stem \
                    and not item.relative:
                if isinstance(item.names, cst.ImportStar) or any(a.name.value == name for a in item.names):
                    return text
                if item.lpar is None and len(s.body) == 1:
                    names = list(item.names)
                    names[-1] = names[-1].with_changes(comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" ")))
                    names.append(cst.ImportAlias(name=cst.Name(name)))
                    out = module.visit(_Replace(item, item.with_changes(names=names))).code
                    _check_import(out)
                    return out
    line = cst.parse_statement("from %s import %s\n" % (stem, name))
    end = max((i for i, s in enumerate(module.body) if _is_import(s)), default=-1) + 1
    out = module.with_changes(body=list(module.body[:end]) + [line] + list(module.body[end:])).code
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
    tail = ("  # " + comment) if comment and any(l.lstrip().startswith("#") for l in lines) else ""
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


def _const_of(value):
    return value.get("const") if isinstance(value, dict) and isinstance(value.get("const"), dict) else None


def _find_consts(value, out):
    if isinstance(value, dict):
        if isinstance(value.get("const"), dict):
            out.append(value)
        for v in value.values():
            _find_consts(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _find_consts(v, out)


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
    if edit.op == "set_constant":
        a = edit.args
        text = texts_of(edit.file)
        if a.get("existing"):
            return {edit.file: (text, _change_constant(text, a["name"], edit.value, a.get("comment", "")))}
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


def diff(before: str, after: str, name: str = "") -> str:
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                        "a/" + name, "b/" + name))


def keyword_constant(text: str, target, name: str):
    """The name of the module-level constant that the target call's keyword `name` reads (`gap=GAP`), or None where it
    is not given, is not a bare name, or the name is not assigned exactly once in the file."""
    module, wrapper, hit = _call_of(text, target)
    kw = _keywords(hit.call).get(name)
    if kw is None or not isinstance(kw.value, cst.Name):
        return None
    ident = kw.value.value
    return ident if sum(1 for s in module.body if _assigns(s, ident)) == 1 else None


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
