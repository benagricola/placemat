"""Notes: a short remark an agent (or the user) leaves where the studio is looking - "trying c_cpu further west" - at a point,
an item or a pad of the board.

A note is a record, not text to parse: `{"v", "id", "at", "from", "script", "description", "target"}` where `target` is None or one of
`{"kind": "point", "x", "y"}`, `{"kind": "item", "name"}`, `{"kind": "pad", "ref", "pad"}`. A point is a place to look at, never a
placement. Records are appended to `<board>/.placemat/views/studio/notes.jsonl`, one JSON object a line, the file bounded to the last
`[studio] notes_keep`; the studio watches the file, so a note reaches the open pages as it is written, and a studio started later
(or a page opened later) is given the ones that have not expired (`[studio] note_age_s`). The page, not this module, turns a record into
a pin and a line."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time

try:
    import fcntl
except ImportError:                                 # no file locks: appends are single writes all the same
    fcntl = None

NAME = "notes.jsonl"
MAX_TEXT = 1000                                     # characters of a note's description


def path_for(board_dir) -> Path:
    return Path(board_dir) / ".placemat" / "views" / "studio" / NAME


def target_of(at=None, item=None, pad=None):
    """The record's target from what the command line gave: `at` "X,Y" (mm on the board), `item` a name, `pad` "REF.N"; at most one."""
    given = [x for x in (at, item, pad) if x not in (None, "")]
    if len(given) > 1:
        raise ValueError("a note points at one thing: --at, --item or --pad")
    if at not in (None, ""):
        try:
            x, y = (float(v) for v in str(at).split(","))
        except ValueError:
            raise ValueError("--at wants X,Y in mm, for example --at 12.5,-4")
        return {"kind": "point", "x": x, "y": y}
    if item not in (None, ""):
        return {"kind": "item", "name": str(item)}
    if pad not in (None, ""):
        ref, dot, number = str(pad).rpartition(".")
        if not dot or not ref or not number:
            raise ValueError("--pad wants REF.N, for example --pad U1.3")
        return {"kind": "pad", "ref": ref, "pad": number}
    return None


def add(board_dir, script: str, description: str, target=None, author: str = "", keep: int = 100, now: float | None = None) -> dict:
    """Append a note for `script` (its file name) and return the record. The file is trimmed to the last `keep` records."""
    description = " ".join(str(description).split())[:MAX_TEXT]
    if not description:
        raise ValueError("a note needs some text")
    now = time.time() if now is None else now
    record = {"v": 1, "id": "n%d-%d-%s" % (int(now * 1000), os.getpid(), os.urandom(2).hex()), "at": round(now, 3), "from": author, "script": script,
              "description": description, "target": target}
    path = path_for(board_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, separators=(",", ":")) + "\n").encode()
    with open(path, "ab") as f:
        if fcntl is not None:
            fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        _trim(path, keep)
    return record


def _trim(path: Path, keep: int) -> None:
    """Keep the last `keep` records (read, then replaced whole: the writer holds the lock)."""
    try:
        lines = path.read_bytes().splitlines(keepends=True)
    except OSError:
        return
    if len(lines) <= max(1, keep):
        return
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".notes-")
    try:
        with os.fdopen(fd, "wb") as out:
            out.writelines(lines[-keep:])
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def read(board_dir, script: str | None = None) -> list:
    """The notes in the file, oldest first (those for `script` when it is given); a line that is not a note is skipped."""
    out = []
    try:
        text = path_for(board_dir).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            n = json.loads(line)
        except ValueError:
            continue
        if isinstance(n, dict) and n.get("id") and n.get("description") is not None and (script is None or n.get("script") == script):
            out.append(n)
    return out


def live(notes, age_s: float, now: float | None = None) -> list:
    """The notes that have not expired: `age_s` 0 keeps them all."""
    now = time.time() if now is None else now
    return [n for n in notes if not age_s or now - float(n.get("at", 0)) <= age_s]


def author(given: str = "") -> str:
    """Who is leaving the note: `--from`, else $PLACEMAT_FROM, else the login name."""
    if given:
        return given
    if os.environ.get("PLACEMAT_FROM"):
        return os.environ["PLACEMAT_FROM"]
    try:
        import getpass
        return getpass.getuser()
    except (ImportError, KeyError, OSError):
        return "agent"
