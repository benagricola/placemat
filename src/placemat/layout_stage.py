#!/usr/bin/env python3
"""The stage framework: a layout script declares, the library schedules.

A board script is a CONSTRAINT LIST - the frame, the face law, which edge a
connector presents, what a millimetre costs on each link - and nothing else.
It is not the schedule. Every order-sensitive operation is either DERIVED from
constraints or scheduled here at a point defined by its dependencies, so
anything imperative at a script's top level is a scheduling decision the file
is making by accident.

WHAT A SCRIPT LOOKS LIKE. It declares config and contributes bodies. A body
runs when its stage runs, not where it is written, so code that measures what
placement actually did still works.

    from placemat import stage

    BOARD_W, BOARD_H = 56.4, 56.4          # source: the case
    PLANE_NETS = {"GND", "3V3"}

    layout, board = context()

    @stage("frame")
    def _outline():
        board.outline_chamfered(2.0)

    @stage("copper")
    def _rails():
        layout.route45("5V_CAN", [_v_tp, _v_dec], w=0.30, layer="In2.Cu")

`layout`, `board`, `b` and `G` are injected into the script's own globals before the
first body runs, so a body reads them as plain names.

WHAT THE RUNNER OWNS. Resolving the board and the project, preparing the
interpreter, building the context from the script's config, running the stages
in dependency order, and saving. None of that is a layout decision.

WITHIN a stage, bodies run in registration order, and that order must not
matter: the shuffle gate permutes registration and requires a byte-identical
board. A stage whose bodies do not commute wants another stage, not a
convention about where to write things.
"""
import os
import sys


# The stages, in dependency order. Each reads what the one before it left, and
# that dependency is the whole reason the list is fixed here rather than chosen
# per board: a script that could reorder them would be scheduling again.
STAGES = (
    "frame",     # outline, mounting, mechanical keepouts, reserved bands
    "anchors",   # positions decided outside the layout, then the edge-bound
    "cells",     # stamped fragments; the order within is derived, not written
    "loose",     # individual parts, likewise
    "copper",    # planes, pours, rails, spines, traces
    "drops",     # plane drops and stitching: needs all the copper above
    "repair",    # re-check what an earlier stage could not see, and REPORT it
    "silk",      # labels and refs: needs the final geometry
    "report",    # stamp and link reports, the pass's own evidence
)

_REGISTRY = []          # (stage, order registered, function)


class _Context:
    """What a layout script works on. The runner fills it in before any body."""
    layout = None
    board = None


_CTX = _Context()


class _Handle:
    """A name for an object the runner builds later.

    A layout script is imported before its board exists: the runner reads the
    script's config to know the frame and the plane nets, and only then can it
    open the board and build the layout objects. So `context()` at the top of a
    script names them, and every attribute goes through to the real object once
    there is one. Asking too early says so rather than failing as None.
    """
    __slots__ = ("_which",)

    def __init__(self, which):
        object.__setattr__(self, "_which", which)

    def _obj(self):
        o = getattr(_CTX, object.__getattribute__(self, "_which"))
        if o is None:
            raise RuntimeError(
                "placemat: %s is not built yet. context() names the objects the "
                "runner creates, and they exist once it has read this script's "
                "config - so use them inside a stage body, not at import."
                % object.__getattribute__(self, "_which"))
        return o

    def __getattr__(self, k):
        return getattr(self._obj(), k)

    def __setattr__(self, k, v):
        setattr(self._obj(), k, v)

    def __getitem__(self, k):
        return self._obj()[k]

    def __repr__(self):
        o = getattr(_CTX, object.__getattribute__(self, "_which"))
        return repr(o) if o is not None else "<placemat %s, not built yet>" % (
            object.__getattribute__(self, "_which"))


def context():
    """The two objects a layout script works with, named at the top of it.

        from placemat import stage, context

        layout, board = context()

    `layout` is the artwork and the file: polygons, tracks, vias, labels, the
    nets and links, and the save.
    `board` is the board being laid out - its outline, where parts and cells
    go, the planes and pours, the reports. The raw pcbnew board is `board.pcb`
    and the stamped cells are `board.cells`.
    """
    return _Handle("layout"), _Handle("board")


def stage(name):
    """Register a body to run in `name`. Raises on a stage that does not exist -
    a typo would otherwise mean a body that silently never runs, which is the
    worst possible failure for a scheduler."""
    if name not in STAGES:
        raise ValueError("no such stage %r; the stages are %s" % (name, ", ".join(STAGES)))

    def take(fn):
        _REGISTRY.append((name, len(_REGISTRY), fn))
        return fn
    return take


def registered():
    """Every registered body, as (stage, registration index, function)."""
    return list(_REGISTRY)


def reset():
    """Forget every registration. For tests, and for a runner loading twice."""
    _REGISTRY.clear()


def plan(registry=None, order=None):
    """The bodies in the order they will run: by stage, then as registered.

    Pure, so a test can ask what a script WOULD do without building anything.
    `order` overrides the registration index per body, which is what the
    shuffle gate uses to prove the answer does not depend on it.
    """
    regs = registered() if registry is None else list(registry)
    if order is not None:
        regs = [(s, order[i], f) for i, (s, _, f) in enumerate(regs)]
    return sorted(regs, key=lambda r: (STAGES.index(r[0]), r[1]))


def run(board_path, width, height, plane_nets=(), registry=None,
        verbose=True, project=None, **board_kw):
    """Build the context and run every body in dependency order.

    Returns (layout, board). The caller saves: keeping the save out of here lets a test
    run the stages and inspect the board without writing anything.
    """
    from placemat import project as _project
    from placemat.layout_helpers import ModuleLayout, patch_stackup_colors
    from placemat.board_layout import BoardLayout

    # THE PROJECT IS RESOLVED ONCE, HERE. Everything downstream asks it for the
    # fab profile, the module directories and the root.
    if project is not None:
        _project.use(project)
    elif _project._active is None:
        _project.use(_project.Project.discover(start=board_path))

    patch_stackup_colors(board_path)             # before the load, per the house convention
    layout = ModuleLayout(board_path)
    board = BoardLayout(layout, width=width, height=height, plane_nets=plane_nets, **board_kw)

    _CTX.layout, _CTX.board = layout, board   # what context()'s handles point at

    bodies = plan(registry)
    if not bodies:
        raise SystemExit(
            "placemat: this script registered no stages, so nothing would be placed.\n"
            "  A script contributes bodies with @stage(...) from placemat. If it imports\n"
            "  `layout_stage` (or any other copy of this library) directly, its bodies\n"
            "  register somewhere else and this runner sees none of them.\n"
            "  Saving now would write an unplaced board over a placed one.")
    for name, _i, fn in bodies:
        if verbose:
            print("stage %-8s %s" % (name, getattr(fn, "__name__", "?")))
        fn()
    return layout, board
