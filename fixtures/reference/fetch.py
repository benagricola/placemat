"""Fetch the reference set: pinned files of open, human-routed KiCad boards.

    .venv/bin/python fixtures/reference/fetch.py [name ...] [--offline]

Each board of manifest.json is pinned to a commit, and each of its files to a
sha256. A file already in the cache with the right sha256 is used as is; any
other is downloaded from the raw URL of the commit and checked. The cache is
~/.cache/placemat-reference/ (or $PLACEMAT_REFERENCE_CACHE).
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
CACHE_ENV = "PLACEMAT_REFERENCE_CACHE"
DOWNLOAD_TIMEOUT_S = 60

RAW_URLS = {
    "github": "https://raw.githubusercontent.com/{project}/{commit}/{path}",
    "gitlab": "https://gitlab.com/{project}/-/raw/{commit}/{path}",
}


@dataclasses.dataclass(frozen=True)
class Board:
    name: str
    repo: str  # "github:owner/repo" or "gitlab:kicad/code/kicad"
    commit: str
    files: dict[str, str]  # path in the repo -> sha256
    board: str  # the .kicad_pcb path
    licence: str  # SPDX
    tests: tuple[str, ...]  # "a" and/or "b"
    islands: tuple[str, ...]  # nets for --islands
    fixed: tuple[str, ...]  # references held in test b
    human_track_mm: float | None
    kicad5: bool
    notes: str = ""


class FetchError(Exception):
    def __init__(self, board: Board, path: str, reason: str):
        self.board = board
        self.path = path
        self.reason = reason
        super().__init__(f"{board.name}: {path}: {reason}")


def load_manifest(path: pathlib.Path = MANIFEST) -> list[Board]:
    boards = []
    for entry in json.loads(pathlib.Path(path).read_text()):
        for key in ("tests", "islands", "fixed"):
            entry[key] = tuple(entry.get(key, ()))
        boards.append(Board(**entry))
    return boards


def cache_dir() -> pathlib.Path:
    override = os.environ.get(CACHE_ENV)
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".cache" / "placemat-reference"


def url(board: Board, path: str) -> str:
    host, project = board.repo.split(":", 1)
    return RAW_URLS[host].format(project=project, commit=board.commit, path=path)


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as response:
        return response.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_status(board: Board, cache: pathlib.Path | None = None, *, offline: bool = False) -> tuple[pathlib.Path, int]:
    """The folder holding the board's files and how many files were downloaded."""
    folder = (cache if cache is not None else cache_dir()) / board.name
    downloaded = 0
    for path, want in board.files.items():
        target = folder / path
        if target.is_file():
            have = _sha256(target.read_bytes())
            if have == want:
                continue
            if offline:
                raise FetchError(board, path, f"cached sha256 {have} does not match the manifest's {want}")
        if offline:
            raise FetchError(board, path, f"not in the cache and offline; would fetch {url(board, path)}")
        source = url(board, path)
        try:
            data = _download(source)
        except (urllib.error.URLError, OSError) as error:
            raise FetchError(board, path, f"cannot fetch {source}: {error}") from error
        have = _sha256(data)
        if have != want:
            raise FetchError(board, path, f"sha256 of {source} is {have}, the manifest has {want}")
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(data)
        partial.replace(target)
        downloaded += 1
    return folder, downloaded


def fetch(board: Board, cache: pathlib.Path | None = None, *, offline: bool = False) -> pathlib.Path:
    """The folder holding the board's files, downloading and checking what is missing."""
    return fetch_status(board, cache, offline=offline)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("names", nargs="*", help="boards to fetch (default: all)")
    parser.add_argument("--offline", action="store_true", help="use the cache only")
    args = parser.parse_args(argv)
    boards = load_manifest()
    known = {board.name for board in boards}
    unknown = [name for name in args.names if name not in known]
    if unknown:
        parser.error(f"not in the manifest: {', '.join(unknown)}")
    failed = False
    for board in boards:
        if args.names and board.name not in args.names:
            continue
        try:
            folder, downloaded = fetch_status(board, offline=args.offline)
        except FetchError as error:
            failed = True
            print(f"{board.name}: ERROR {error.path}: {error.reason}")
            continue
        print(f"{board.name}: {'fetched ' + str(downloaded) + ' files' if downloaded else 'cached'} {folder}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
