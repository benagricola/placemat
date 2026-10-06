# Handover: building 0.100 (phases, one score, refine, the loop)

For the session that builds this work. Read it first, then the documents it lists, in order.

## The lanes

Decided with the user. Two sessions work on placemat at once:
- **The consolidation session** (the one that wrote this) fixes the board sessions' bug reports and releases 0.99.x,
  until 0.100.0 ships. After that its fixes land on main, and you release them.
- **You** build 0.100 in git worktrees under `.claude/worktrees/`. You merge a step into main only when that step is
  complete: its plan done, its gates met, the full suite green, and its removal-ledger rows gone. You own the 0.100.x
  releases and their notices.

Both sessions merge into main. Before you merge, pull main and resolve against it. `skills/placemat/references/migration.md`
is where merges collide: `tools/release/merge_unreleased.py` resolves two sides' "## Unreleased" entries, and
`tools/release/fix_migration.py vX.Y.Z ...` restores released sections to their tag text. After any merge, diff every
released section since your branch was cut against its tag. Check that "## Unreleased" sits above the newest released
section; the merge tool has put it below once.

## Read, in order

1. The user's instructions are loaded for you: ~/.claude/CLAUDE.md, this repo's CLAUDE.md and CHARTER.md, and the
   memory index. Follow them exactly: plain ASCII, no Claude or Anthropic in commits, structured data inside and text at
   the edge, defer to upstream, keep CPU light, kill only your own PIDs, and when disk space runs short, stop and ask.
2. `docs/superpowers/specs/2026-10-06-roadmap-0.100.md`: the order, gates, attribution, the reference set, and the
   removal ledger.
3. The four specs, in build order:
   - `2026-10-06-routing-phases-design.md`
   - `2026-10-06-one-score-design.md`
   - `2026-10-06-refine-pass-design.md`
   - `2026-10-06-place-route-loop-design.md`
4. `docs/superpowers/plans/2026-10-06-reference-set.md`: the plan for step 0.
5. `docs/superpowers/research/2026-10-06/`: the evidence the specs cite.

## What to do first

Execute step 0's plan with superpowers:subagent-driven-development, the method the user chose, in a new worktree.
Step 0 records the baseline every later step is held to, so nothing else starts before it is merged.

Then, for each step in order, write its plan with superpowers:writing-plans. Write it after the previous step has landed
and its gate numbers are in, so the plan argues from measured facts. Ask the user to review each plan, briefly; they
prefer a short rundown and multiple-choice questions to reading the full text.

## Things that are open, to settle with the user when you reach them

- **Zener fork, stage 2:** an interface instance named only by its assignment (`DISP = Spi(...)`) records no root name.
  Trace where the name is inferred before you size the work (research/zener-net-export.md).
- **KRT fork:** the design of `--connections`, routing only given pad pairs of a net at a width per layer.
- **Refine:** how a module's declarations travel with a stamped cell as data. This is the largest unknown in refine.
- **Gates:** each gate's numbers. A failed gate goes back to the user with the numbers; it is never worked round.

## Shared machine

- **Real-board runs and benches** take
  `flock /tmp/claude-1000/-home-ben-work-placemat/5d67ca9e-2758-4c31-8023-db2f60969045/scratchpad/realboard.lock`.
  Use that exact path, because other sessions and agents use it too. Run one at a time, with no more than `--jobs 2`.
- **A worktree needs:**
  - `src/placemat/_version.py` copied in from the main checkout;
  - for native work, its own `.venv`;
  - otherwise the main checkout's `.venv` with `PYTHONPATH=<worktree>/src`, or imports resolve to main.
- **Forks:**
  - KRT is https://github.com/benagricola/KiCadRoutingTools: remote `fork` in ~/work/KRT-upstream, branch
    `placemat/upstream-2026-10`. Push router work there. Never push upstream, and never open issues or PRs there.
  - Zener is https://github.com/benagricola/pcb at ~/work/pcb.
- **Skills:** the placemat skill lives in this repo. The circuit-capture skill is ~/work/circuit-capture, its own repo
  with its own charter.
- **Board sessions:** fairing-instrument-pcb (the board lead) and fairing-instrument-electronics. The electronics
  session owns electronics/.venv. Send them release notices only when you release, and tell them to reload the skill.

## Release line

0.100.0 is the first release containing any of the four steps, and later releases are 0.100.y. Each release:
1. runs the full suite: `pytest --full -n 2 -p no:cacheprovider`;
2. runs the bench;
3. runs both reference runners, with the tally in the release commit;
4. adds a migration section;
5. then is released and the board sessions notified.

The user cuts 1.0 after step 4 and the last ledger row are merged. Do not cut it yourself.
