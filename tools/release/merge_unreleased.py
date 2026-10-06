"""Resolve migration.md conflicts where both sides add Unreleased entries: keep both sides, then merge every
'## Unreleased' section into one, entries grouped under New / Changed / Removed / Fixed, duplicates dropped."""
import re
p = "skills/placemat/references/migration.md"
s = open(p).read()
s = re.sub(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", lambda m: m.group(1) + "\n" + m.group(2), s, flags=re.S)
order = ["### New", "### Changed", "### Removed", "### Fixed"]
blocks = {h: [] for h in order}
first = None
out = []
parts = re.split(r"(?m)^(## [^\n]*\n)", s)
i = 0
head = parts[0]; rest = []
for j in range(1, len(parts), 2):
    rest.append((parts[j], parts[j + 1]))
kept = []
for h, body in rest:
    if h.strip() == "## Unreleased":
        sub = None
        for chunk in re.split(r"(?m)^(### [^\n]*\n)", body):
            if chunk.startswith("### "):
                sub = chunk.strip(); continue
            for e in re.split(r"\n(?=- \*\*)", chunk):
                e = e.strip()
                if e.startswith("- **") and sub in blocks and e not in blocks[sub]:
                    blocks[sub].append(e)
        if first is None:
            first = len(kept); kept.append(None)
    else:
        kept.append((h, body))
un = "## Unreleased\n"
for h in order:
    if blocks[h]:
        un += "\n" + h + "\n\n" + "\n\n".join(blocks[h]) + "\n"
un += "\n"
res = head + "".join(un if k is None else k[0] + k[1] for k in kept)
open(p, "w").write(res)
print({h: len(v) for h, v in blocks.items()})
