#!/usr/bin/env python3
"""The project a layout is being laid out for.

Where the fab profile is, which directories hold the cells and the parts, which
boards exist, where the root is. The runner resolves it once and calls `use()`,
and everything needing one of those answers asks here. Nothing climbs the
filesystem for them, so a call means the same thing wherever it is made from.

`Project.discover()` is for a script run by hand, and it WARNS at each step it
had to guess. A project with no fab profile says so on every request for a
number rather than answering with somebody else's: a board laid out to via
sizes and clearances nobody chose is worth the noise.

    from placemat.project import Project, use
    use(Project.discover())                 # a tool, resolving a repo once
    use(Project(root=..., fab={...}))       # a test, or another project
"""
import glob
import json
import os
import re
import sys

# What a fab profile has to answer. Used only when a project supplies no
# profile at all, and saying so out loud is the point - these are somebody's
# defaults, not this fab's numbers.
# WHERE THINGS ARE, unless a project says otherwise. Globs relative to the
# root, matched against directories. A board is then a directory among these
# that holds a `.zen` declaring `Board(...)`, and a cell one that holds
# `<Name>.zen` - the globs say where to LOOK, the file says what it IS.
DEFAULT_BOARDS = ("*",)
DEFAULT_CELLS = ("modules/*", "*/modules/*")
DEFAULT_PARTS = ("parts/*", "*/parts/*")

FALLBACK_FAB = {
    "via": {"default_drill_mm": 0.3, "default_size_mm": 0.6},
    "via_in_pad": {"min_pad_dim_mm": 0.45},
}


def repo_root(start=None):
    """The directory holding `pcb.toml`, climbing from `start`; None if there is
    none. The one implementation of this question."""
    d = os.path.abspath(start or os.path.dirname(os.path.abspath(__file__)))
    if os.path.isfile(d):
        d = os.path.dirname(d)
    while d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, "pcb.toml")):
            return d
        d = os.path.dirname(d)
    return None


class Project:
    """Where this project's parts, cells, boards and fab rules are.

    Every field is given. Nothing is discovered once the object exists, so two
    projects can be open at once and neither depends on the working directory.
    """

    def __init__(self, root, fab=None, modules_dir=None, parts_dir=None,
                 board_dirs=None, name=None, boards=None, cells=None, parts=None):
        self.root = os.path.abspath(root) if root else None
        self.name = name or (os.path.basename(self.root) if self.root else "<none>")
        self._fab = fab
        self.modules_dir = modules_dir or (os.path.join(self.root, "modules") if self.root else None)
        self.boards = tuple(boards) if boards else DEFAULT_BOARDS
        self.cells = tuple(cells) if cells else DEFAULT_CELLS
        self.parts = tuple(parts) if parts else DEFAULT_PARTS
        self.parts_dir = parts_dir            # the container, when one is named
        self._board_dirs = board_dirs
        self._module_dirs = None
        self._part_dirs = None

    @property
    def fab(self):
        """The fab profile. A project without one says so on every request."""
        if self._fab is None:
            warn("%s has no fab profile: falling back to %s. Via sizes, via-in-pad "
                 "minimums and courtyard excess are NOT this fab's numbers."
                 % (self.name, FALLBACK_FAB))
            return FALLBACK_FAB
        return self._fab

    @property
    def board_dirs(self):
        """Directories holding a schematic that declares a board.

        A BOARD is what `Board(...)` in a `.zen` makes, so that is the test.
        Holding a `*_layout.py` is not: a directory of shared code matches that
        by accident, and a board that has been captured but never laid out -
        the one most worth finding - does not match it at all.
        """
        if self._board_dirs is None:
            self._board_dirs = []
            for p in self._look(self.boards):
                for f in sorted(os.listdir(p)):
                    if not f.endswith(".zen"):
                        continue
                    try:
                        if re.search(r'(?m)^\s*Board\s*\(', open(os.path.join(p, f)).read()):
                            self._board_dirs.append(p)
                            break
                    except OSError:
                        pass
            self._told("boards", self.boards, DEFAULT_BOARDS, self._board_dirs)
        return self._board_dirs

    def _look(self, globs):
        """The directories a set of globs matches, in order, without repeats."""
        if not self.root:
            return []
        seen, out = set(), []
        for g in globs:
            for p in sorted(glob.glob(os.path.join(self.root, g))):
                if os.path.isdir(p) and p not in seen:
                    seen.add(p)
                    out.append(p)
        return out

    @property
    def module_dirs(self):
        """{module name: its folder}, root-level and board-local alike.

        A cell is a folder holding `<Name>.zen`. A board keeps its own under
        `<board>/modules/`, and those are found too."""
        if self._module_dirs is None:
            self._module_dirs = {}
            for d in self._look(self.cells):
                name = os.path.basename(d)
                if os.path.exists(os.path.join(d, name + ".zen")):
                    self._module_dirs.setdefault(name, d)
            self._told("cells", self.cells, DEFAULT_CELLS, self._module_dirs)
        return self._module_dirs

    @property
    def part_dirs(self):
        """{part name: its folder}. A PART is a folder holding `<Name>.kicad_mod`
        or a wrapper `<Name>.zen` beside its assets - the footprint, the symbol,
        the 3D model and the datasheet that the datasheet gate insists on."""
        if self._part_dirs is None:
            self._part_dirs = {}
            for d in self._look(self.parts):
                name = os.path.basename(d)
                if (glob.glob(os.path.join(d, "*.kicad_mod"))
                        or os.path.exists(os.path.join(d, name + ".zen"))):
                    self._part_dirs.setdefault(name, d)
            self._told("parts", self.parts, DEFAULT_PARTS, self._part_dirs)
        return self._part_dirs

    def _told(self, what, globs, default, found):
        """Say when a project's OWN setting finds nothing.

        These are globs of the things themselves, not of the folder holding
        them: `parts = ["footprints/*"]`, not `"footprints"`. Getting that
        wrong yields an empty list, and an empty list that nobody mentions
        reads as "this project has none"."""
        if not found and tuple(globs) != tuple(default):
            warn("pcb.toml [placemat] %s = %s matched no %s. These are globs of "
                 "the %s themselves - \"dir/*\", not \"dir\"."
                 % (what, list(globs), what, what))

    def generated_boards(self):
        """(board .zen sources, generated layout) for every generated board.

        `board_dirs` filtered, so there is one definition of a board and this is
        a narrowing of it."""
        out = []
        for d in self.board_dirs:
            zens = sorted(f for f in glob.glob(os.path.join(d, "*.zen")))
            pcbs = sorted(glob.glob(os.path.join(d, "layout", "*", "layout.kicad_pcb")))
            if zens and pcbs:
                out.append((zens, pcbs[0]))
        return out

    def board_pcb(self, which):
        """The generated layout of a board, named however a person would name it.

        A board is `middleweight`, or its directory, or its `.zen` - all of
        which are the board to everyone except the filesystem. Returns None if
        it is not a board here; `board_names()` says what is."""
        which = which.rstrip("/")
        want = os.path.basename(which)
        if want.endswith(".zen"):
            want = want[:-4]
        for d in self.board_dirs:
            if os.path.basename(d).lower() not in (want.lower(), os.path.basename(which).lower()):
                continue
            pcbs = sorted(glob.glob(os.path.join(d, "layout", "*", "layout.kicad_pcb")))
            return pcbs[0] if pcbs else False        # a board, but never generated
        return None

    def board_names(self):
        return [os.path.basename(d) for d in self.board_dirs]

    def board_dir_of(self, path):
        """Which board directory a path belongs to, by containment.

        A project states its own shape; the library does not infer one by
        counting path components off a board file."""
        path = os.path.abspath(path)
        for d in self.board_dirs:
            if path == d or path.startswith(d + os.sep):
                return d
        return None

    @classmethod
    def discover(cls, start=None, quiet=False):
        """Climb for a `pcb.toml` and read the profile beside it.

        For a script run by hand. It reports what it found and what it could
        not: an unreported guess is how a board gets laid out to rules nobody
        chose."""
        root = repo_root(start)
        if root is None:
            warn("no pcb.toml above %s: this project has no root and no fab profile"
                 % (start or os.getcwd()))
            return cls(root=None)
        cfg = cls.read_config(root)
        f = os.path.join(root, "fab-profile.json")
        fab = None
        if os.path.exists(f):
            try:
                fab = json.load(open(f))
            except Exception as e:
                warn("%s is unreadable (%s): its numbers will NOT be used" % (f, e))
        else:
            warn("no fab-profile.json at %s" % root)
        if not quiet:
            print("project: %s (fab profile %s)" % (root, "loaded" if fab else "MISSING"))
        return cls(root=root, fab=fab, **cfg)

    @staticmethod
    def read_config(root):
        """The `[placemat]` table of a project's `pcb.toml`, if it has one.

            [placemat]
            boards = ["boards/*"]          # where to look for boards
            cells  = ["cells/*"]           # ...and for cells
            parts  = ["footprints/*"]

        The defaults suit a project whose boards are top-level directories and
        whose cells live under `modules/`. A project that is laid out
        differently says so here rather than being told it is wrong.
        """
        f = os.path.join(root, "pcb.toml")
        if not os.path.exists(f):
            return {}
        try:
            import tomllib
            with open(f, "rb") as fh:
                table = tomllib.load(fh).get("placemat", {})
        except Exception as e:
            warn("%s could not be read (%s): its placemat settings are ignored" % (f, e))
            return {}
        out = {}
        for key, arg in (("boards", "boards"), ("cells", "cells")):
            if key in table:
                v = table[key]
                out[arg] = [v] if isinstance(v, str) else list(v)
        if "parts" in table:
            v = table["parts"]
            out["parts"] = [v] if isinstance(v, str) else list(v)
        return out


_active = None
_warned = set()


def warn(msg):
    """Say it once per distinct message, on stderr, and never swallow it."""
    if msg not in _warned:
        _warned.add(msg)
        print("project: WARNING: %s" % msg, file=sys.stderr)


def use(project):
    """Make this the project the library reads. The runner calls it; a test calls
    it with whatever it wants to pretend the world looks like."""
    global _active
    _active = project
    return project


def active():
    """The project in use. Discovers one - loudly - if nobody set it, so a
    script run by hand still works and still says what it assumed."""
    global _active
    if _active is None:
        warn("no project was set; discovering one from the filesystem. A tool "
             "should call project.use() so this does not depend on where files sit.")
        _active = Project.discover(quiet=True)
    return _active


def clear():
    """Forget the active project (tests)."""
    global _active
    _active = None
    _warned.clear()


def fab():
    """The active project's fab profile."""
    return active().fab
