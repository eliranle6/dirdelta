
# Peer review: a newcomer's read of the code

Read cold, top-down from `main.py` and bottom-up from the trees, picker and C++ core, without the
docs. Each idea: what I saw, why it bothers me, what I'd do. Sorted by ROI (value ÷ effort,
risk included), best first. "Effort" is a guess: S (< 1h), M (a few hours), L (a day or more).

(No .md file was opened for this. Two CLAUDE.md files, the repo's and lib/treepicker's, were loaded
into the reviewer's context automatically; the findings come from the code.)

## 1. Menus are keyed by their display text (S→M, high value)
`picker.pick_option()` takes and returns label strings, so every caller maps the answer back by
string equality, and several work around it:
- `choose_replicas.blank_line()` makes separators unique by padding them with N spaces; headings
  are disabled options.
- `hashes_screen.dashboard()` builds fake option ids (`"  bar %s"`, `"  known 0 name"`), shows them
  as something else via `shown_as`, then matches `option == _TOGGLE % (name,)` and
  `option.startswith(("  toggle", "  See"))`.
- `inbox._act()` / `InteractiveDirSync._act()`: `next(action for action, (label, ...) in
  options.items() if label == answer)`.
- `clouddirtreefactory`: compares the answer with `OPTION_REFRESH % (rootpath,)` re-formatted.

Let `pick_option` accept `(id, label)` items (strings still allowed) plus a `Separator`/`Heading`
item type, and return the id. treepicker already separates node id from tag (`--updates`
id→text), so it's mostly Python. Removes a class of "rename a label, break a branch" bugs.

## 2. Five `_is_at_or_under` variants, with different semantics (S, high value) — fixed 2026-11-01 (`paths.is_at_or_under()`; the inline copies are left)
`dirtree._is_at_or_under`, `drivecache._is_at_or_under`, `inbox._is_at_or_under`,
`clouddirtree._is_under`, `clouddirtreefactory._overlap` (+ inline copies in `mounts.unmounted`,
`elsewhere.Index._is_excluded`, `interactive_dir_sync._shown`). They differ: inbox's returns True
for an empty `dirpath` (root contains everything), dirtree's doesn't; drivecache's strips a
trailing '/'. Same name, different answers is a trap. One `paths.is_at_or_under(path, dir)`
with the root case explicit.

## 3. Drive's "stale" marker stays set after a failed request (S, bug + simplification) — the bug fixed 2026-11-01 (the context manager not done)
`mark_stale()` / `if is_newly_stale: unmark_stale()` is hand-written in 6 places in
`clouddirtree.py`. In `_move_file`, `_move_dir`, `_copy_within` and `_trash`, an `HttpError`
returns before the unmark, so a request that changed nothing leaves the folder marked stale, and
the user is told to refresh. A `with drivecache.changing(path):` context manager (unmark on
success or on a clean failure, keep only if interrupted mid-way) fixes it and removes the
repetition.

## 4. Copy-pasted small helpers (S, moderate value) — done in part 2026-11-01: `dryrun.NOTE`, `text.files()`; the listings and joins not yet
- `_files(count)` defined 6 times (dirsync_main, elsewhere, hashes_screen (with `{:,}`),
  interactive_dir_sync, inbox, opening), plus inline in `replicalog.Changes.summary`.
- `is_local(replica)` twice (interactive_dir_sync, hashes_screen).
- "first N lines, then `(and K more)`" in 6 places: `clouddirtree._listed`,
  `localdiskdirtree.scan_warning`, `drivecache.entries` problems, `InteractiveDirSync._confirm`
  and `_rename`, `inbox._remove` and `_say_not_done` (C++ `scan_errors_warning` too).
- `"(A dry run: nothing on disk will change. DRYRUN=0 changes files.)"` 4 times; `title += " (a
  dry run)"` several more. Belongs in `dryrun.py`.
- Path joins: `inbox._join`, `opening.Opener._full`, `replicalog.posix_join`.
A small `text.py` (counts, listings) and `paths.join` cover them.

## 5. CloudDirTree keeps file metadata in six parallel dicts (M, high value) — the drift on removal fixed 2026-11-01 (`_forget()`); the entries not done
`_cloud_ids`, `_google_files`, `_sizes`, `_dates_taken`, `_hashes`, `_modified`, all keyed by
relpath, must be moved/copied/dropped by hand on every change (`_move_file`, `_move_dir`,
`_copy_within`, `_trash_folder`, `_remove_file`, `_uploaded`, `write_file`), and they already
drift: `_remove_file` and `_trash_folder` drop ids but leave sizes/hashes/times behind;
`refresh_from_drive()` re-runs `super().__init__` and re-creates all six (a copy of `__init__`).
`_uploaded`, `write_file` and `update_from_cache` each translate Drive metadata into the dicts.
Put it in the node: a `CloudFileEntry(FileEntry)` with `cloud_id, size, hashes, modified,
date_taken, is_google`, filled by one `_entry_from_md(md)`. Moving a node moves its data;
`_move_subtree` stops needing callbacks.

## 6. Drive parallelism contradicts itself (S to decide, clarity) — no rule (2026-11-01): the parallel uploads stay; the lock's comments say it's for thread safety
`inbox.py` has `_drive_lock`, "Drive is asked one request at a time", and `opening.Opener` takes
it too; but `clouddirtree.UPLOAD_THREADS = 4` uploads in parallel, and `_make_folders_batch`
sends up to 100 creates per batch request. Either the rule is "one at a time" (then the uploads
break it) or it's "only interactive work serialises" (then the comment is wrong). Decide and
write the rule in one place (`driveapi.py`).

## 7. One local directory listing, not five (M, moderate value, some speed)
Local dirs are walked by: `LocalDiskDirTree.update_from_filesystem` (find `%y %s %T@ %p`),
`LocalDiskDirTree.files_by_name` (find `%s %P`), `hashing._list_files` (find `%s %T@ %P`),
`inbox._root_dirs` (find `%y %P`), plus C++ `dirdiff` and `treepicker`. `inbox._inbox_files()`
even builds a throwaway `LocalDiskDirTree` and flattens `files_by_name()` back into a list.
One `localscan.scan(root, max_depth, types) -> {relpath: (kind, size, mtime_ns)}` (streaming for
progress) would serve all Python callers; `LocalDiskDirTree.file_size()`/`modified_time()` could
read `file_stamps` instead of an `lstat` per call.

## 8. The four batch operations in DirTree repeat one skeleton (S→M, moderate value)
`copy_inner_entries_from_dirtree`, `remove_files`, `move_files`, `copy_files_within` each build
a verb, count, catch `KeyboardInterrupt`, call `note_stopped()`, and print a dry-run or live
summary. Dry-run handling also sits in different layers (copy: top level; remove: inside
`_remove_files`; move: per item). One `_run_batch(what, items, do_one)` helper makes them
consistent.
Related: `copy_inner_entries_from_dirtree(dirtree, source)` takes a *DirTree* only to call
`iter_files()` on it, so `InteractiveDirSync._copy` and `inbox._transfer` build one with
`DirTree.from_file_entries()` just to pass it. Take a list of relpaths (and the source).

## 9. Sync's and inbox's file screens are the same loop written twice (M, high value)
`InteractiveDirSync.browse()` and `InboxSort.run()`: pick files → `#` opens the dashboard → `r`
refreshes from Drive → `_act()` → rescan → re-pick, reselect with `_shown()`. Both `_act()`s
return `list | None | REFRESH_KEY` (a sentinel string mixed into a list return), and both have
the same Yes/No → "Are you sure?" removal confirmation, built separately (`_confirm` vs
`_remove`). The inbox reaches into the other's privates (`interactive_dir_sync._shown`,
`InteractiveDirSync.MAX_FILES_LISTED`). A shared `FilesScreen` base (loop, keys, confirmations,
an `ActResult` type) would shrink both and keep their behaviour from drifting.

## 10. `inbox._act()` is a 160-line table plus a 13-branch dispatch (M, moderate value)
An `OrderedDict` of 13 `(label, why_not, verb, path_parts)` tuples, filtered, then matched back
by label, then a second chain of `if action == ...` that re-derives the same per-action data.
Small `Option` objects (label, enabled/why, verb, parts, `run()`) would keep each action's text
and behaviour together. Goes well with #1.

## 11. The inbox's AI cache is keyed by path+size, while everything is hashed (M, moderate)
`ai.py` keys by `"<cloud or local path>\t<size>"`, so a move needs `ai.carry()`, two key
functions (`_cache_key`, `_target_cache_key`) and bookkeeping in `_approve()`. Files now have
SHA-1s (Drive's, or the background hasher's): keyed by hash (falling back to path+size until
hashed), a moved or copied file keeps its description for free, and duplicates share it.
Also: the cache is a whole-JSON read-modify-write, done from the Claude worker thread
(`_ask`) and the main thread (`carry`) with no lock, so one can overwrite the other's entries.

## 12. `LocalDiskDirTree` is sometimes a tree and sometimes an empty shell (L, high value)
For local↔local syncs and for the inbox, the tree is never scanned (dirdiff does the diff), so
`has_file`, `_files_under`, `_exists`, `files_by_name`, `_move_file`, `_remove_file`,
`_copy_within` all check the disk or say "the tree may not have it, if it wasn't scanned".
Every new method has to remember both modes. I'd split it: a disk-backed `LocalReplica` (no
in-memory tree, asks the filesystem) and the in-memory tree only where a tree is really needed
(the cloud, and the local side of a cloud sync, or not even there: dirdiff could diff a dir
against a list of Drive paths on stdin).

## 13. `elsewhere.Index` is a second copy of each replica, synced by hand (M, moderate)
After every action, callers must remember `dst_index.add(...)`, `src_index.remove(...)`,
`index.move(...)` (interactive_dir_sync, inbox); forgetting one silently gives wrong
"surely moved" previews. Have trees notify listeners of add/remove/move, or rebuild the
name/size maps lazily (they're dict builds, cheap next to the hashing).

## 14. The inbox's "one tree at the common ancestor" (L, moderate)
To make moves renames, `InboxSort` builds a tree at the common ancestor of inbox and sorted tree,
then two more "view" trees, and juggles `_inbox_rel`, `_root_rel`, `_full()`, `_relpath_in()`,
`excluded=` on the index. For `cloud/a` and `cloud/b` the common tree is all of My Drive (the
whole cache is parsed into a tree). A `move_to(other_tree, relpath, new_relpath)` on trees of the
same backend (a local rename, or a Drive parents change) would let it keep just two trees.

## 15. The Drive cache is re-parsed whole on every call (M, value grows with Drive size)
`drivecache.entries()` parses the full JSON-lines file; `count_under()` is `entries()` again;
`refresh_cache()` calls `count_under()` then `replace_under()` (which parses, then re-reads and
`json.loads` every line again); `refresh_from_drive()` and `factory()` parse again. Memoize the
parse by the file's (mtime, size), or move it to SQLite like `hashcache` (with an index on
parent), which also stops the file from growing with `trashedId` lines forever.

## 16. Paths are normalized three ways (S, small bug risk) — fixed 2026-11-01 (`paths.normalized()`, real paths)
`replicas.normalized()` uses `abspath`, `inbox._normalized()` and `LocalDiskDirTree` use
`realpath`, `hashing` uses `realpath`, `replicalog.identity` uses `realpath`. The same dir
reached through a symlink is one replica to the hasher and two pairs to the history. Pick one
(`realpath`, probably) in `paths.py`.

## 17. Compatibility shims for old cache formats (S, cleanup)
`drivecache._guess_root` (caches without a root line), stale markers without paths,
`ai.recommended_path`'s `destination` key, the dashboard's "no SHA-1 (from before 29.10.2026)"
note, and `drivecache.is_stale()` is unused. For a single-user tool, one forced refresh/migration
would let these go.

## 18. Layering: UI in the worker, screens importing screens (S, low-moderate)
`hashing.py` (the thread pool) also holds the tags, bar, colors, `status_text`,
`format_duration`; `hashing.tag()` reads `job._failed` without the lock. `hashes_screen` imports
`choose_replicas` for `known_lines()`, and `choose_replicas` imports `hashes_screen` inside a
function to dodge the cycle. `known_lines()` belongs with `replicas.py`; the formatting with
`hashes_screen`. Also `elsewhere.format_size` is used app-wide from a matching module.
More private reach-ins from `inbox.py`: `_root_tree._exists`, `_inbox_tree._files_under`,
`_root_tree._tree.subtree`, `elsewhere._same_sized`. Make the ones it needs public.

## 19. Small wiring oddities in main/sync (S, low)
`main._run` mutates the argparse `Namespace` in a loop to pass paths into `dirsync_main.run(args)`;
pass paths. `utils.validate_dir()` calls `sys.exit` from a helper, deep in the sync. Mount checks
run twice for a recent pair (`choose_replicas._mounted`, then `main._ready`). `choose_replicas.run`
has the same "missing dir" block twice (sorts and pairs). `utils.py` is a two-function grab bag
(`create_dirtree_from_arg` belongs in a replica factory).

## 20. The picker's in-band markup is defined six times (S→M, low-moderate)
`\x01color\x01text` is produced by three Python functions (`picker.highlighted`, `status`,
`segments`) and parsed by three C++ ones (`parse_status`, `parse_preview_line`,
`parse_preview_segments`), with slightly different rules (default colors, line vs. segment).
One "segments" format, one producer and one parser. (A JSON-lines protocol over one socket
instead of `--updates`/`--preview`/`--selection`/`--notify-fd` + two temp files would be
cleaner still, but it's an L change on both sides for little user-visible gain.)

## 21. C++: two scanners in PathTree (M, low-moderate) — find waited for by its pid, from PATH (2026-11-01); one scanner not done
`update_from_filesystem` fork/execs a hard-coded `/usr/bin/find`, sends stderr to a tmpfile,
then `wait(nullptr)`, which reaps *any* child rather than find's pid; `load_children` (lazy)
uses `std::filesystem::directory_iterator`. One `std::filesystem` scan would drop the subprocess
utility and the tmpfile (measure first: speed matters here). At least wait on find's pid and
look `find` up on PATH, as the Python side does.

## 22. C++: small duplication in cli/readers (S, low) — the key checks one (2026-11-01); the rest not done
`pick_and_print` copies `CliOptions` into `PickerOptions` field by field (embed one in the
other); `expect_key_error` and `notify_key_error` loop over the same key table;
`UpdatesReader::feed` and `PreviewsReader::feed` share the same delimiter-buffering loop;
`needs_cleaning` and `clean_path` walk components twice.

## 23. C++: the demo `picker` program is built and installed (S, low) — fixed 2026-11-01
`make install` installs `build/picker` (a hard-coded "people" tree) next to treepicker and
dirdiff. Keep it out of `install`.

## Considered, not recommended
- `exif.py`, a hand-written EXIF reader: a library would be shorter, but it avoids a dependency
  for one field, and it's contained. Leave it.
- `hashcache` on SQLite, the shared hashing pool (idle I/O priority, one worker on spinning
  disks), `find` instead of `os.walk`, dirdiff in C++: each looked over-built at first, and each
  has a measured reason in its comments. Keep.
- C++ `Node` holds UI state (search/picked/disabled/color): mixing model and view, but moving it
  out would cost lookups on a hot path for 100k-node trees. Not worth it.
- `elsewhere.py`'s scoring (siblings, date taken, mtime, size closeness) predates whole-replica
  hashing and could shrink to "hash first, names as a fallback", but it still matters for Drive's
  Google files and for files not hashed yet. Revisit once hashing is the norm.

