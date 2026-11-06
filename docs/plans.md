# Plans: changed files, sorting into several replicas, one combined tree

Plans for three of `improvement-ideas.md`'s ideas, not implemented yet (2026-11-06): its 3 (files at
the same path that differ), 2.1 (an inbox's sort reaching the sorted tree's other replicas), and 6
(one tree of both replicas' differences). Plan A comes first: plan C uses what it adds.

## A. Files at the same path that differ (idea 3)

### What there is to show

For a pair of replicas, each path is one of:

1. In both, the same: hidden, as today (nothing to do).
2. Only in one: shown in that direction's picker, as today.
3. In both, different: a new kind. Today these are hidden as if they were the same.

### Same picker or another view? The same picker, marked

Recommended: the changed files go in the same direction pickers as the missing ones, marked
differently, and not in a view of their own.

- A direction's picker already means "what A has that B doesn't have like this". A's newer version
  of a file is one of those, and its action is the same one: Copy (which then replaces B's).
- Another view would add a third screen to go through per sync. The point of the picker is one
  pass of decisions per direction.
- A changed file shows in both directions' pickers, since either side can win: A's picker offers
  A's version to replace B's, B's picker the other way. Each says which version is newer, so the
  side that wins is clear. Once it's copied either way, it's the same, and gone from both.
- The cost is mixing two kinds of entries in one list. The marks deal with that (below), and so
  does one way to see only the changed ones: their tag is searchable (`/≠`), and the main menu also
  has its own entry, "Changed files (N)", which opens the same picker with only those. A separate
  view would only be better when there are many changed files and few missing ones (e.g. after
  editing a whole library's metadata), and that entry covers that case.

How a changed file is marked in the picker:

- A tag after its name, in orange: `[≠ newer here, 2.1 MB vs 1.9 MB]` or
  `[≠ older here, same size, other contents]`.
- Its preview column shows both sides: size, modification time, hash if known, which is newer, and
  what Copy does ("replaces B's; B's version goes to the trash").
- The main menu's counts: "A has 12 files B lacks, and 3 that differ" (`A ⇄ B: 12 + 3 ≠`).
- Copy's confirmation lists them apart: "Copy 12 files to B, and replace 3 of B's (B's versions to
  the trash)".

### What counts as different

- By size, always: it's in the scan already (`find`'s `%s`, `localscan`; Drive's cache `size`),
  so it's nearly free.
- By contents, when both hashes are known without reading: the hash cache for local files, Drive's
  SHA-1 for Drive files. Same size with different hashes means different.
- Same size with a hash missing on either side: "same size, not compared". Not shown as different
  (no false alarms). The picker's `Ctrl-I`-style key, or the dashboard's hashing, can compare them on
  request, as `elsewhere.py` compares a moved file's candidates.
- Modification times only say which version is newer. They never decide "different" (copies made
  before 2026-10-29 have their copy's time).

### Steps

1. dirdiff: `--differing`, which prints the files in both dirs whose sizes differ (`SIZE_A SIZE_B
   PATH`), and with `--same-size`, also the files in both of the same size (for the hash check). It
   needs an `lstat` per file in both dirs: time it on the 119k-file dirs (it should be ~0.1-0.3s).
2. Python (`dirdiff.py`, `interactive_dir_sync.py`): the changed list per pair, `{relpath:
   Change(size_a, size_b, mtime_a, mtime_b, by='size'|'hash')}`. Hashes come from
   `known_hash()` on both trees (one query for a local one, as `listed()` does). With a Drive
   replica there's no dirdiff: intersect `listed()` with the cache.
3. The pickers: changed relpaths after the missing ones in `pick_files()`, with the tag
   (`shown_as`) and the preview lines (`previews`). treepicker needs no change: tags, colors and
   search exist already.
4. Copy on a changed file replaces the other side's. Locally, the old version goes to the trash
   first (`trashing()`, as junk does), then the copy keeps the source's mtime. In Drive,
   `files.update` with the new media on the same file id, so Drive keeps the old version as a
   revision (and the cache line is updated). Remove on a changed file removes this side's version
   only; it then becomes "only in the other". Rename doesn't apply to changed files.
5. The main menu's counts and the "Changed files (N)" entry; the dry run as everywhere.
6. Tests: dirdiff's `--differing` (gtest), the changed list (local, Drive, by size and by hash),
   replacing (local with the trash, Drive's update with a fake service), the counts and tags.

Effort: medium. Most of the machinery is there: hashes, comparing, trashing, the pickers' tags.

## B. Sorting an inbox into all of the sorted tree's replicas (idea 2.1)

### The problem

The sorted tree (`cloud/eliran`) has other replicas (`/mnt/win/Users/.../eliran`, a backup disk).
A file moved into it from the inbox should end up in all of them. Seen per file and per replica,
that's a matrix: each target may be missing in one replica, already there in another, and there in
a different version in a third. Showing that matrix, and asking for decisions in it, is what makes
it complex.

### How other tools do it

- **Unison, FreeFileSync, Beyond Compare**: pairs only. More replicas means more pairs (a star
  around a hub, or a chain), each synced on its own. FreeFileSync puts several folder pairs in one
  job, but each is still compared as a pair.
- **Syncthing**: one folder shared by N devices, with no per-file, per-device decisions. Changes
  spread on their own. Each device shows its "out of sync items", and conflicts become
  `.sync-conflict` files to resolve later.
- **Git with several remotes**: one source of truth; pushing to each remote is a separate step that
  either fast-forwards or refuses (never silently overwrites).
- **Backup tools (restic, Time Machine)**: one source, N destinations; per destination only "up to
  date" or "N behind".

What they share: nobody decides per file per replica. There's one place where decisions are made
(the hub, the source), and the replicas follow it. Each replica's state comes down to a count
("12 to bring, 1 conflict"), with the details one level down.

### The plan: the sorted tree is the hub, its replicas follow

- **Decisions stay as they are now**, against one sorted tree: the side tree on the right stays a
  single tree, with no tabs per replica. Tabs would make each move a question about N trees, which
  is the complexity we want to avoid.
- **Afterwards, one summary screen.** Once a move into the sorted tree is done (live), dirdelta
  knows exactly which paths were added: the plan's targets. So it needs no diff of whole replicas,
  only a look at those paths in each follower (a `stat`, or a cache lookup in Drive):

  ```
  Also put the 12 files moved into cloud/eliran in its other replicas?

   /mnt/win/Users/eli/eliran     12 to copy
   /media/backup/eliran          not mounted: kept for later (12)
   cloud/old-eliran              11 to copy, 1 there already, 1 different: skipped

  > Copy to all that can be reached
    Choose which replicas
    Not now (kept for later)
  ```

  One row per replica; "show the files" on a row opens the usual picker of that replica's files.
- **Never overwrite.** A target already there and the same: nothing to do. There but different: a
  conflict, skipped, and listed. The replica's next sync with the sorted tree shows it as a changed
  file (plan A), where the user decides.
- **Unreachable replicas catch up later.** For a replica that isn't mounted (or is read-only), the
  paths are queued in `replicas.json` (`pending: {replica: [{"from": root, "relpaths": [...]}]}`).
  The start menu says "2 replicas behind: 40 files", and the next time the replica is reached (a
  sync, a sort, the dashboard) dirdelta offers to bring it up to date the same way. This is
  Syncthing's "out of sync, syncs when connected", without a daemon.
- **Which replicas follow which tree** is set once per sorted tree ("Other replicas of this tree" on
  the dashboard), suggested from the pairs history (paths that were synced with it, e.g. `/mnt/win/...
  ⇄ cloud/eliran`). It's kept in `replicas.json` (`followers: {root: [paths]}`), by the replicas'
  identities (`replicanames.label_key()`), so a disk mounted elsewhere is still found.

What that leaves out on purpose: removals and renames in the sorted tree aren't sent to the
followers (only additions are, which can't lose anything). A later step could send renames as
moves, for a follower whose file at the old path is the same, using the rename machinery a sync
has.

### Steps

1. `replicas.py`: `followers` and `pending`, saved and loaded, with tests.
2. `propagate.py`: `check(root, relpaths, follower)` → (to copy, there already, different,
   unreachable), and `bring(root, relpaths, follower)`, using the trees' copy methods
   (`copy_in`, `copy_inner_entries_from_dirtree`) on the progress screen, with the dry run.
3. `inbox.py`: after `_approve()` moves or copies into the sorted tree (live), the summary screen,
   then copying or queueing.
4. The start menu's "behind" line, and the offer when a pending replica is reached.
5. The dashboard's "Other replicas of this tree".
6. Tests: check/bring with local followers (temp dirs) and a fake Drive, queueing for an unmounted
   one, conflicts never overwritten.

Effort: medium. The copy and progress machinery is there; what's new is the follower config, the
summary screen and the queue.

## C. One combined tree of both replicas' differences (idea 6)

### What it is

One picker of everything that differs between A and B, instead of a pass per direction, each entry
marked by where it is and given an action:

| Entry | Mark | Actions (Space cycles them) |
|---|---|---|
| Only in A | `A>` | copy to B · remove from A · skip |
| Only in B | `<B` | copy to A · remove from B · skip |
| In both, different (plan A) | `≠` | A's wins · B's wins · skip |
| Moved (same contents at different paths, `elsewhere.py`'s sure matches) | `↔` | rename B's to A's path · rename A's to B's · skip |

Then one review of the whole plan ("copy 120 to B, 1.2 GB; copy 4 to A; remove 30 from B; replace
2"), one confirmation (twice if it removes), and it's done in one go.

### Defaults, so most entries need no decision

A pair has a policy, chosen in the menu and kept with a favorite pair in `replicas.json`:

- **Backup A→B**: `A>` copy, `<B` skip, `≠` A wins.
- **Mirror A→B**: `A>` copy, `<B` remove, `≠` A wins.
- **Two-way**: `A>` copy, `<B` copy, `≠` the newer wins (skipped if unclear), `↔` skipped.
- **Manual**: everything skipped.

Each entry starts at its policy's action; the user changes only the exceptions.

### treepicker: a few states per node

Today a node is picked or not. This needs states from a list given by the caller:

- `--states "copy-b:→:blue,copy-a:←:cyan,remove-a:✗A:red,remove-b:✗B:red,replace-b:≠→:orange,replace-a:←≠:orange,skip:·:grey"`:
  each state's name, mark and color.
- Input, with `--typed`: `f STATES INITIAL PATH`, the states allowed for the node (e.g.
  `copy-b,remove-a,skip`) and its first one.
- Keys: Space cycles the selected node's allowed states. On a dir it cycles the states its nodes all
  allow, setting all of them. A key per state sets it directly (`--state-key c copy-b`, ...). V
  (range) sets a range.
- Drawing: the mark before the name, in its color. A dir shows its nodes' state if they're all the
  same, else `*`. The stats line counts each state ("→ 120 · ← 4 · ✗B 30 · · 2").
- Output: `STATE\tPATH` for each file node. `--updates` can set states too (e.g. an AI plan).
- In treepicker's model, a node gets a state index and an allowed-states mask, next to
  `is_picked`. `TreeSelector` sets them as it does picking; the printer draws the mark. Tests: a
  randomized one, like the selector's, checking that a dir's shown state always agrees with its
  nodes.

### dirdelta

- `combined.py`: the entries, from dirdiff both ways, plan A's changed list and `elsewhere`'s sure
  matches for moved pairs (by hash only, so only certain ones are `↔`). Each with its allowed
  actions and its policy default.
- `picker.pick_actions()`: runs treepicker with the states, and returns `{relpath: state}`.
- The review: `view_files` of the plan grouped by action, then the confirmation(s).
- Doing it, each phase on the progress screen, in an order where a failure loses nothing: renames,
  then copies, then replacements (old versions to the trash), then removals. The existing
  `move_files`, `copy_inner_entries_from_dirtree`, `remove_files` do the work.
- The main menu: "Sync (all differences in one tree)" first, with the per-direction entries kept
  below it for simple cases (e.g. a read-only replica, where only one way makes sense).

### Phases, each usable on its own

1. treepicker's states (and its tests), with the demo program.
2. The combined tree of only-in-A and only-in-B, with the Manual and Backup policies.
3. Mirror and Two-way, kept per favorite pair.
4. `≠` entries (after plan A).
5. `↔` moved pairs.
6. "Ask AI" (`a`) sets states from its plan, so the plan is reviewed in this same tree.

Effort: large. Phase 1 is the biggest single change in treepicker so far. Phases 2-3 are a medium
change in dirdelta.

## Order

A, then C, since C's `≠` entries are A's. B is independent of both, and can come before or after.
