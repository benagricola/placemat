"""Harvest open-licensed, human-routed KiCad boards from GitHub, for tools/reference_training.py.

    python tools/harvest_boards.py ROOT search [--max-candidates N]
    python tools/harvest_boards.py ROOT fetch [--target N]
    python tools/harvest_boards.py ROOT facts BOARDS_DIR      (writes ROOT/facts.json for reference_training --facts)
    python tools/harvest_boards.py ROOT all [--max-candidates N] [--target N]

Needs the `gh` CLI, authenticated. Everything lives under ROOT and every step resumes where it stopped:

    candidates.jsonl   code-search hits: repo, path, fork
    searched.jsonl     the size ranges the search has settled
    repos.jsonl        what GitHub says about each repo looked at (licence, default branch, fork)
    decisions.jsonl    one line per repo that is done, kept or rejected
    rejected.jsonl     one line per repo or board left out, with its reason
    harvest.jsonl      the manifest: one line per kept board - repo, commit, path, licence, sha256, bytes
    boards/<slug>/     the kept boards (and the sibling .kicad_pro), pinned to the commit in the manifest

Code search returns 1000 results per query at most, so the search splits a size range in two until each part fits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

OPEN_LICENCES = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "MPL-2.0", "CC-BY-4.0", "CC-BY-SA-4.0",
                 "CC0-1.0", "Unlicense", "CERN-OHL-P-2.0", "CERN-OHL-W-2.0", "CERN-OHL-S-2.0"}
OPEN_LICENCE_PREFIXES = ("LGPL-", "GPL-", "AGPL-", "CERN-OHL")

MAX_BYTES = 20 * 1024 * 1024
MIN_SEGMENTS = 20
MIN_FOOTPRINTS = 4
MAX_PER_REPO = 3
ATTEMPTS_PER_REPO = 8
DOWNLOADS = 4
SEARCH_PAGE = 100
SEARCH_CAP = 1000
SEARCH_PAUSE = 6.5  # code search allows 10 requests a minute
MIN_WIDTH = 500  # a size range this narrow is not split further

# Path parts that mark a template, an example, a test or a library. A part is a run of letters and digits.
PATH_WORDS = ("template", "example", "test", "demo", "sample", "backup", "autosave")
PATH_WHOLE = {"lib", "libs", "library", "libraries", "bak", "old"}
KICAD_REPOS = re.compile(r"^kicad/|(^|/)kicad[-_](symbols|footprints|packages3d|library|libraries|templates?|demos?|"
                         r"source-mirror|docs)", re.I)

SEGMENT = re.compile(r"\(segment[\s)]")
FOOTPRINT = re.compile(r"\((?:footprint|module)\s+[\"A-Za-z0-9_]")


# ---- pure rules

def is_open_licence(spdx) -> bool:
    """Whether a GitHub licence id is on the open list; NOASSERTION, none and anything else are not."""
    if not spdx or spdx in ("NOASSERTION", "NONE", "other"):
        return False
    return spdx in OPEN_LICENCES or spdx.startswith(OPEN_LICENCE_PREFIXES)


def path_ok(path: str) -> bool:
    """Whether a board path does not look like a template, example, test, library or backup."""
    if not path.lower().endswith(".kicad_pcb"):
        return False
    for part in re.findall(r"[a-z0-9]+", path.lower()):
        if part in PATH_WHOLE or part.startswith(PATH_WORDS):
            return False
    return True


def repo_ok(full_name: str, fork: bool) -> str | None:
    """None if a repo may be harvested, else the reason it may not."""
    if fork:
        return "fork"
    if KICAD_REPOS.search(full_name):
        return "KiCad's own library or demo repo"
    return None


def pick_paths(paths) -> list:
    """The board paths of one repo worth trying, best first: one per directory, shallowest first."""
    seen, out = set(), []
    for p in sorted({p for p in paths if path_ok(p)}, key=lambda p: (p.count("/"), p)):
        folder = p.rpartition("/")[0]
        if folder in seen:
            continue
        seen.add(folder)
        out.append(p)
    return out


def routed_counts(text: str) -> dict:
    """{"segments", "footprints"} counted in the text of a .kicad_pcb."""
    return {"segments": len(SEGMENT.findall(text)), "footprints": len(FOOTPRINT.findall(text))}


def routed_reason(counts: dict) -> str | None:
    """None if the counts are those of a routed board, else why not."""
    if counts["footprints"] < MIN_FOOTPRINTS:
        return "fewer than %d footprints (%d)" % (MIN_FOOTPRINTS, counts["footprints"])
    if counts["segments"] < MIN_SEGMENTS:
        return "fewer than %d segments (%d)" % (MIN_SEGMENTS, counts["segments"])
    return None


def slug(repo: str, sha: str) -> str:
    return "%s__%s" % (repo.replace("/", "__"), sha[:8])


def split_range(lo: int, hi: int):
    """The two halves of a size range, or None when it is too narrow to split."""
    if hi - lo < MIN_WIDTH:
        return None
    mid = (lo + hi) // 2
    return (lo, mid), (mid + 1, hi)


def start_ranges(lo: int, hi: int) -> list:
    """Size ranges covering lo..hi, about a factor 1.5 wide each, smallest first."""
    out, a = [], lo
    while a <= hi:
        b = min(hi, int(a * 1.5))
        out.append((a, b))
        a = b + 1
    return out


# ---- files

class Log:
    """An append-only JSON-lines file, safe to write from several threads."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def rows(self) -> list:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass  # a line cut short by a stopped run
        return out

    def add(self, row: dict) -> None:
        with self.lock, self.path.open("a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
            f.flush()


class Manifest(Log):
    """harvest.jsonl: the kept boards. Knows what it holds, so a resumed run skips it."""

    def __init__(self, path: Path):
        super().__init__(path)
        self.refresh()

    def refresh(self) -> None:
        rows = self.rows()
        self.keys = {(r["repo"], r["path"]) for r in rows}
        self.hashes = {r["sha256"]: r["repo"] for r in rows}
        self.count = len(rows)

    def has(self, repo: str, path: str) -> bool:
        return (repo, path) in self.keys

    def duplicate_of(self, sha256: str) -> str | None:
        return self.hashes.get(sha256)

    def add(self, row: dict) -> None:
        with self.lock:
            self.keys.add((row["repo"], row["path"]))
            self.hashes[row["sha256"]] = row["repo"]
            self.count += 1
        super().add(row)


# ---- GitHub

class Gate:
    """One shared pause, so that every thread waits when GitHub asks for a wait."""

    def __init__(self):
        self.until = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        while True:
            delay = self.until - time.time()
            if delay <= 0:
                return
            time.sleep(min(delay, 30))

    def hold(self, seconds: float, why: str) -> None:
        with self.lock:
            until = time.time() + seconds
            if until > self.until:
                self.until = until
                print("waiting %.0f s: %s" % (seconds, why), file=sys.stderr, flush=True)


GATE = Gate()


def parse_response(text: str) -> tuple:
    """(status, headers, body) of `gh api -i` output."""
    head, _, body = text.partition("\r\n\r\n") if "\r\n\r\n" in text else text.partition("\n\n")
    lines = head.splitlines()
    status = int(lines[0].split()[1]) if lines and lines[0].startswith("HTTP") else 0
    headers = {}
    for line in lines[1:]:
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    return status, headers, body


def wait_for(status: int, headers: dict, attempt: int) -> float:
    """Seconds to wait before trying again after a limit response, 0 if the response is not a limit."""
    remaining = headers.get("x-ratelimit-remaining")
    if "retry-after" in headers:
        return float(headers["retry-after"]) + 1
    if status in (403, 429):
        if remaining == "0" and "x-ratelimit-reset" in headers:
            return max(1.0, float(headers["x-ratelimit-reset"]) - time.time() + 2)
        return min(600.0, 30.0 * 2 ** attempt)
    return 0.0


def gh_api(path: str, params: dict | None = None, accept: str | None = None, tries: int = 6) -> tuple:
    """(status, headers, body) of a GET through `gh api`, sleeping on rate limits."""
    cmd = ["gh", "api", "-i", path]
    for k, v in (params or {}).items():
        cmd += ["-f", "%s=%s" % (k, v)]
    if accept:
        cmd += ["-H", "Accept: " + accept]
    cmd += ["-X", "GET"]
    for attempt in range(tries):
        GATE.wait()
        run = subprocess.run(cmd, capture_output=True, text=True)
        status, headers, body = parse_response(run.stdout)
        if status == 0:
            GATE.hold(10.0 * (attempt + 1), "gh api failed: %s" % run.stderr.strip()[:120])
            continue
        delay = wait_for(status, headers, attempt)
        if delay:
            GATE.hold(delay, "%s on %s" % (status, path))
            continue
        if status >= 500:
            GATE.hold(5.0 * (attempt + 1), "%s on %s" % (status, path))
            continue
        remaining = headers.get("x-ratelimit-remaining")
        if remaining is not None and int(remaining) <= 2 and "x-ratelimit-reset" in headers:
            GATE.hold(max(1.0, float(headers["x-ratelimit-reset"]) - time.time() + 2), "%s limit used up" % path)
        return status, headers, body
    return 0, {}, ""


def download(url: str, limit: int = MAX_BYTES, tries: int = 5):
    """The bytes at `url`; None if it is not there, "big" if it is over `limit`."""
    for attempt in range(tries):
        GATE.wait()
        req = urllib.request.Request(url, headers={"User-Agent": "placemat-harvest"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                size = r.headers.get("Content-Length")
                if size and int(size) > limit:
                    return "big"
                data = r.read(limit + 1)
                return "big" if len(data) > limit else data
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 451):
                return None
            if e.code in (403, 429) or e.code >= 500:
                GATE.hold(float(e.headers.get("Retry-After") or 15 * 2 ** attempt), "%s on %s" % (e.code, url))
                continue
            return None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(3 * (attempt + 1))
    return None


# ---- search

def search_page(lo: int, hi: int, page: int) -> tuple:
    """(total_count, items) of one page of code search for .kicad_pcb files of lo..hi bytes."""
    time.sleep(SEARCH_PAUSE)
    status, _, body = gh_api("search/code", {"q": "extension:kicad_pcb size:%d..%d" % (lo, hi), "per_page": SEARCH_PAGE,
                                              "page": page})
    if status != 200:
        raise RuntimeError("code search %d..%d page %d: HTTP %s %s" % (lo, hi, page, status, body[:200]))
    data = json.loads(body)
    return data["total_count"], data["items"]


def candidate_row(item: dict) -> dict:
    repo = item["repository"]
    return {"repo": repo["full_name"], "path": item["path"], "fork": bool(repo.get("fork")),
            "private": bool(repo.get("private"))}


def search(root: Path, lo: int, hi: int, max_candidates: int) -> int:
    """Fill ROOT/candidates.jsonl by code search over size ranges; the number of candidate boards held."""
    cands, done = Log(root / "candidates.jsonl"), Log(root / "searched.jsonl")
    held = {(r["repo"], r["path"]) for r in cands.rows()}
    settled = {(r["lo"], r["hi"]): r for r in done.rows()}
    queue = start_ranges(lo, hi)
    while queue and len(held) < max_candidates:
        a, b = queue.pop(0)
        known = settled.get((a, b))
        if known and known["split"]:
            queue += list(split_range(a, b))
            continue
        if known:
            continue
        total, items = search_page(a, b, 1)
        halves = split_range(a, b) if total > SEARCH_CAP else None
        if halves:
            done.add({"lo": a, "hi": b, "total": total, "split": True})
            queue += list(halves)
            print("%d..%d: %d hits, split" % (a, b, total), flush=True)
            continue
        pages = min(SEARCH_CAP, total) // SEARCH_PAGE + (1 if min(SEARCH_CAP, total) % SEARCH_PAGE else 0)
        for page in range(1, pages + 1):
            if page > 1:
                _, items = search_page(a, b, page)
            for item in items:
                row = candidate_row(item)
                if (row["repo"], row["path"]) not in held:
                    held.add((row["repo"], row["path"]))
                    cands.add(row)
        done.add({"lo": a, "hi": b, "total": total, "split": False})
        print("%d..%d: %d hits, %d candidates held" % (a, b, total, len(held)), flush=True)
    return len(held)


# ---- fetch

def repo_info(repos: Log, cache: dict, name: str) -> dict:
    """What GitHub says about a repo: {"spdx", "fork", "branch", "archived"}, or {"error": reason}."""
    if name in cache:
        return cache[name]
    status, _, body = gh_api("repos/" + name)
    if status == 200:
        d = json.loads(body)
        info = {"repo": name, "spdx": (d.get("license") or {}).get("spdx_id"), "fork": bool(d.get("fork")),
                "branch": d.get("default_branch"), "archived": bool(d.get("archived")), "size_kb": d.get("size")}
    elif status in (404, 451):
        info = {"repo": name, "error": "repo gone (HTTP %d)" % status}
    else:
        return {"repo": name, "error": "transient", "transient": True}
    repos.add(info)
    cache[name] = info
    return info


def head_commit(name: str, branch: str) -> str | None:
    status, _, body = gh_api("repos/%s/git/ref/heads/%s" % (name, urllib.parse.quote(branch, safe="/")))
    if status != 200:
        return None
    return json.loads(body)["object"]["sha"]


def raw_url(repo: str, commit: str, path: str) -> str:
    return "https://raw.githubusercontent.com/%s/%s/%s" % (repo, commit, urllib.parse.quote(path))


class Fetcher:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.manifest = Manifest(root / "harvest.jsonl")
        self.repos = Log(root / "repos.jsonl")
        self.decisions = Log(root / "decisions.jsonl")
        self.rejected = Log(root / "rejected.jsonl")
        self.cache = {r["repo"]: r for r in self.repos.rows()}

    def reject(self, repo: str, reason: str, path: str | None = None) -> None:
        self.rejected.add({"repo": repo, "path": path, "reason": reason})

    def finish(self, repo: str, status: str, reason: str = "", kept: int = 0) -> None:
        self.decisions.add({"repo": repo, "status": status, "reason": reason, "kept": kept})

    def one_repo(self, repo: str, paths: list, stop) -> None:
        """Licence, pin and fetch the boards of one repo; every outcome is logged."""
        why = repo_ok(repo, False)
        if why:
            self.reject(repo, why)
            return self.finish(repo, "rejected", why)
        info = repo_info(self.repos, self.cache, repo)
        if info.get("transient"):
            return  # no decision: a later run tries again
        if "error" in info:
            self.reject(repo, info["error"])
            return self.finish(repo, "rejected", info["error"])
        if info["fork"]:
            self.reject(repo, "fork")
            return self.finish(repo, "rejected", "fork")
        if not is_open_licence(info["spdx"]):
            reason = "licence %s" % (info["spdx"] or "none")
            self.reject(repo, reason)
            return self.finish(repo, "rejected", reason)
        picks = pick_paths(paths)
        if not picks:
            self.reject(repo, "every path looks like a template, example, test or library")
            return self.finish(repo, "rejected", "paths")
        commit = head_commit(repo, info["branch"])
        if commit is None:
            self.reject(repo, "default branch head not found")
            return self.finish(repo, "rejected", "no head")
        kept = 0
        for path in picks[:ATTEMPTS_PER_REPO]:
            if kept >= MAX_PER_REPO or stop():
                break
            if self.manifest.has(repo, path):
                kept += 1
                continue
            kept += self.one_board(repo, commit, path, info["spdx"])
        self.finish(repo, "kept" if kept else "rejected", "" if kept else "no board passed", kept)

    def one_board(self, repo: str, commit: str, path: str, spdx: str) -> int:
        data = download(raw_url(repo, commit, path))
        if data is None:
            self.reject(repo, "not found at the head commit", path)
            return 0
        if data == "big":
            self.reject(repo, "over %d MB" % (MAX_BYTES // 2 ** 20), path)
            return 0
        sha = hashlib.sha256(data).hexdigest()
        other = self.manifest.duplicate_of(sha)
        if other:
            self.reject(repo, "same file as one kept from %s" % other, path)
            return 0
        counts = routed_counts(data.decode("utf-8", "replace"))
        why = routed_reason(counts)
        if why:
            self.reject(repo, why, path)
            return 0
        folder = self.root / "boards" / slug(repo, sha)
        folder.mkdir(parents=True, exist_ok=True)
        name = path.rpartition("/")[2]
        (folder / name).write_bytes(data)
        pro_path = path[:-len("kicad_pcb")] + "kicad_pro"
        pro = download(raw_url(repo, commit, pro_path), limit=2 * 2 ** 20)
        has_pro = isinstance(pro, bytes)
        if has_pro:
            (folder / (name[:-len("kicad_pcb")] + "kicad_pro")).write_bytes(pro)
        self.manifest.add({"repo": repo, "commit": commit, "path": path, "licence": spdx, "sha256": sha,
                           "bytes": len(data), "file": "boards/%s/%s" % (folder.name, name), "pro": has_pro,
                           "segments": counts["segments"], "footprints": counts["footprints"]})
        return 1


def fetch(root: Path, target: int) -> int:
    """Licence-check, pin and download boards from ROOT/candidates.jsonl until the manifest holds `target`."""
    f = Fetcher(root)
    done = {r["repo"] for r in f.decisions.rows()}
    by_repo = {}
    for r in Log(root / "candidates.jsonl").rows():
        if not r.get("fork") and not r.get("private"):
            by_repo.setdefault(r["repo"], []).append(r["path"])
    todo = sorted((r for r in by_repo if r not in done), key=lambda r: hashlib.sha1(r.encode()).hexdigest())
    print("%d kept already, %d repos to look at" % (f.manifest.count, len(todo)), flush=True)

    def stop():
        return f.manifest.count >= target

    started = time.monotonic()
    with ThreadPoolExecutor(DOWNLOADS) as pool:
        pending, queue = set(), iter(todo)
        while True:
            while len(pending) < DOWNLOADS and not stop():
                repo = next(queue, None)
                if repo is None:
                    break
                pending.add(pool.submit(f.one_repo, repo, by_repo[repo], stop))
            if not pending:
                break
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                fut.result()
            print("%d kept, %d repos done, %.0f s" % (f.manifest.count, len(f.decisions.rows()),
                                                       time.monotonic() - started), flush=True)
    return f.manifest.count


def facts_for(root: Path, boards_dir: Path) -> dict:
    """{board path under boards_dir: facts} for reference_training --facts, from the manifest."""
    out = {}
    for r in Manifest(root / "harvest.jsonl").rows():
        key = str(boards_dir / Path(r["file"]).relative_to("boards"))
        out[key] = {"name": Path(r["file"]).parent.name, "repo": r["repo"], "commit": r["commit"], "path": r["path"],
                    "licence": r["licence"], "board_sha256": r["sha256"]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("step", choices=["search", "fetch", "facts", "all"])
    ap.add_argument("boards_dir", nargs="?", type=Path, help="facts: where the boards will be when processed")
    ap.add_argument("--max-candidates", type=int, default=8000)
    ap.add_argument("--target", type=int, default=500)
    ap.add_argument("--min-size", type=int, default=20000, help="smallest board file searched, bytes")
    ap.add_argument("--max-size", type=int, default=MAX_BYTES, help="largest board file searched, bytes")
    args = ap.parse_args(argv)
    args.root.mkdir(parents=True, exist_ok=True)
    if args.step == "facts":
        if args.boards_dir is None:
            ap.error("facts needs BOARDS_DIR")
        facts = facts_for(args.root, args.boards_dir)
        (args.root / "facts.json").write_text(json.dumps(facts, indent=1, sort_keys=True))
        print("%d board(s) in %s" % (len(facts), args.root / "facts.json"))
        return 0
    if args.step in ("search", "all"):
        print("%d candidate boards" % search(args.root, args.min_size, args.max_size, args.max_candidates))
    if args.step in ("fetch", "all"):
        print("%d boards kept" % fetch(args.root, args.target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
