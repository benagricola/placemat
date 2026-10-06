"""Rebuild migration.md so every released section reads exactly as its tag has it, and every entry a merge put into a
released section is moved under "## Unreleased" at the top. Usage: python fix_migration.py v0.97.6 v0.97.5 ... (newest first,
every release since the merged branches were cut); run in the repo root, after resolving any conflict markers."""
import re, subprocess, sys
p = "skills/placemat/references/migration.md"
cur = open(p).read()
assert "<<<<<<<" not in cur and ">>>>>>>" not in cur, "resolve the conflict markers first"
def show(tag):
    return subprocess.run(["git", "show", tag + ":" + p], capture_output=True, text=True, check=True).stdout
def section(s, head):
    i = s.index(head); j = s.find("\n## ", i + len(head)); return i, (len(s) if j < 0 else j + 1)
def blocks(sec):
    out, sub = [], None
    for blk in re.split(r"\n(?=### |- \*\*)", sec):
        if blk.startswith("### "):
            sub = blk.split("\n")[0]; rest = blk[len(sub):].strip()
        else:
            rest = blk.strip()
        if rest.startswith("- **"):
            out.append((sub, rest))
    return out
moved = []
if "## Unreleased" in cur:
    a, b = section(cur, "## Unreleased"); moved += blocks(cur[a:b]); cur = cur[:a] + cur[b:]
for tag in sys.argv[1:]:
    head = "## To " + tag.lstrip("v")
    rel = show(tag); ri, rj = section(rel, head); released = rel[ri:rj]
    have = {b for _, b in blocks(released)}
    ci, cj = section(cur, head)
    moved += [(s, b) for s, b in blocks(cur[ci:cj]) if b not in have]
    cur = cur[:ci] + released + cur[cj:]
seen, uniq = set(), []
for s, b in moved:
    if b not in seen:
        seen.add(b); uniq.append((s, b))
if uniq:
    un = "## Unreleased\n"
    for h in ("### New", "### Changed", "### Fixed", "### Removed"):
        bs = [b for s, b in uniq if s == h]
        if bs:
            un += "\n" + h + "\n\n" + "\n".join(bs) + "\n"
    top = cur.index("\n## ") + 1
    cur = cur[:top] + un + "\n" + cur[top:]
open(p, "w").write(cur)
print("moved:", [b[:60] for _, b in uniq])
