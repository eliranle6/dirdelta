# Architecture

## Data flow, end to end

```
dirdelta command (or python -m dirdelta)
  → main.py: parse_args() → dirsync_main.run(args)  OR  dirpick_main.run(args)
     (no paths: choose_replicas.run(replicas.load()) first, then dirsync_main.run)
     (no curses: each picker is a treepicker run, which has the terminal while
      it's open; messages in between are plain lines, via messages.print_line)
       dirpick_main: local dir → picker.pick_under_dir(dir)   (treepicker scans it)
                     cloud    → utils.create_dirtree_from_arg() → picker.pick_from_tree()
       dirsync_main: utils.create_dirtree_from_arg(path)   for each replica path
            → clouddirtreefactory.factory_interactive()   if path starts with "cloud"
            → localdiskdirtree.factory()                   otherwise
       → picker.pick_option([...])                         (the top-level menu, in _sync)
       → interactive_dir_sync.InteractiveDirSync(src, dst)
            .sync(COPY or REMOVE) / .view_diff()
              → dirdiff.files_not_in() for two local dirs, else
                DirTree.get_unknown_entries_in_given_dirtree()   (the diff: relpaths)
              → picker.pick_files(src, missing_relpaths)         (selection UI)
              → LocalDiskDirTree.copy_inner_entries_from_dirtree() / .remove_files()
```

## `dirdelta/` — the application

### `main.py`
Argparse: `dir_a_path`, `dir_b_path` (both optional), `-x/--execute`,
`-m/--max-depth` (default 20, passed down to `localdiskdirtree.factory` as
`find -maxdepth`). No positional path → `choose_replicas.run`, then
`dirsync_main.run` on what it chose; one → `dirpick_main.run`; two →
`dirsync_main.run`. No curses setup: a `picker.PickerError` (treepicker
missing or failing), `DriveCacheError` or `replicas.ReplicasError` exits
with its message.

### `replicas.py` / `choose_replicas.py`
`replicas.py` keeps the pairs of replicas synced (`history`, the latest
first, at most `MAX_HISTORY`) and the favorite pairs, in
`~/.config/dirdelta/replicas.json` (`REPLICAS_FILE`; JSON, hand-editable,
written whole with `os.replace`). A pair is the same either way around, and
a pair used again moves to the top rather than being added twice. Paths are
normalized (`normalized()`: local ones absolute, cloud ones cleaned). A file
that can't be read raises `ReplicasError` rather than being overwritten.
`dirsync_main.run` records each sync's pair as it starts.
`choose_replicas.run(replicas)` is the menu for a run without paths: two
slots (Replica A, B), then the favorites, then the recent pairs (the
history without the favorites), then Quit. A pair is chosen at once, unless
one of its local dirs is gone (a screen says so, back to the menu; a cloud
one is checked when the sync reads Drive's file list); a slot
asks Local disk / Google Drive, then picks a dir: under `/` with
`picker.pick_under_dir(dirs_only=True, lazy=True)` (treepicker reads a dir
only when it's shown), or in the whole Drive tree (`cloud`) with
`pick_from_tree(dirs_only=True)`. Once both slots are chosen (and differ),
it returns them.

### `utils.py`
`create_dirtree_from_arg(rootpath)` is the single dispatch point deciding
cloud vs local, with `paths.is_cloud_path()`: a path is "cloud" iff its
first path component is literally the string `"cloud"` (`paths.py`, which
also has `path_in_cloud()`, used by `CloudDirTree`). `validate_dir` checks
the path is an existing directory for the local case, exiting with a
message (via `messages.print_line`) otherwise.

### `entries.py`, `dirtree.py` — the core data structure
`DirTree` models a filesystem tree, holding a `treelib.Tree` (it offers
`get_node`, `children`, `root`, `remove_node`, `all_nodes`, `in` and
`len()` of it). Its nodes' data are entries
(`entries.py`), each with `name`, `relpath` and `fullpath`:
- `DirEntry` — directory node
- `FileEntry` — file node, no size/hash/mtime stored

Since it doesn't subclass treelib, it has no `create_node`: all callers go
through `add_file_by_relpath` / `add_file_by_fullpath` /
`create_dir_node_from_relpath_if_not_exists` so relpath/fullpath bookkeeping
stays consistent. Node `identifier` in `treelib` is the file's `relpath`,
relative (`sub/x`; the root's is `''`), like treepicker's paths.

**The diff algorithm** — `get_unknown_entries_in_given_dirtree(self, other)`:
for every file in `other`, if its `relpath` is not a node id in `self`,
it's "missing" — collected into a fresh `DirTree` rooted at `other`'s root.
This is called as `dst.get_unknown_entries_in_given_dirtree(src)`, i.e. it
answers "what's in src that dst doesn't have" — pure path-string membership
test, no content comparison at all, matching the stated scope.

`DirTree.from_file_entries(files, root)` (a classmethod) builds a `DirTree`
holding a flat list of `FileEntry` objects at their relpaths: the "chosen
files" sub-tree, just before a copy.
`add_file_by_relpath` returns the existing entry for a file already in the
tree, which is what lets `update_from_filesystem` rescan a tree in place.

### `localdiskdirtree.py`
`LocalDiskDirTree(DirTree)`. `factory(filesystem_dirpath, max_depth=None,
silent=False)` builds the tree then calls `update_from_filesystem`, which
runs one `find ROOT -mindepth 1 [-maxdepth N] -printf '%y %p\0'` (rather
than walking Python-side) and adds its files and dirs (other types, like
symlinks, are skipped; names are decoded with `os.fsdecode`, so names that
aren't UTF-8 work). find's error messages (paths it couldn't read, e.g.
`Permission denied`) are kept in `scan_errors`. Building the tree, not
find, is most of the time (~2.8s for /usr/share's 119k entries).

`copy_inner_entries_from_dirtree(dirtree)` — for each file in the given
sub-tree, calls `add_file_by_relpath` to add the node to `self`'s tree, then
ensures the destination directory exists (`os.makedirs`, tolerant of
already-exists, path derived from `full_filesystem_path()`), then calls
`_copy_local_file_to_tree_with_path`. **Writing is gated behind
`dryrun.DRYRUN`** (`dryrun.py`; known-issues.md #5): dry-run is the default,
in which nothing changes, neither on disk (no directory is created, no
bytes are copied) nor in the tree; only `DRYRUN=0` copies, adding each
copied file to the tree. `remove_files()` is gated the same way: with
`DRYRUN=0` it deletes and drops the nodes from the tree, else neither. Both print a progress line per file, and a
summary. (Previously called a nonexistent
`self._add_file_by_path(...)` and referenced a `filesystem_dirpath`
attribute that doesn't exist on the current `FileEntry`/`DirEntry` — both
fixed, see known-issues.md #2 — and is now covered by
`tests/test_localdiskdirtree.py`.)

### `clouddirtree.py` / `drivecache.py` / `clouddirtreefactory.py`
Cloud state is never queried live per-scan. Instead:
1. `utils.create_dirtree_from_arg` calls `factory_interactive(rootpath)`
   for any path whose first component is `cloud`. It ensures a cache file exists at
   `drivecache.FILE_LIST_CACHE` (`~/.cache/dirman/files.txt`), prompting
   the user (`picker.pick_option`) to refresh it if it already exists.
2. `_refresh_cache()` → `_scan_drive_files_list()` calls the Drive v3 API
   and writes My Drive's root folder's id (`files().get('root')`) as the
   cache's first JSON line (`{"myDriveRootId": ...}`), then one JSON line per
   file not in the trash (`files().list`, paged, `q='trashed = false'`,
   `fields=... files(id,name,parents,kind,size,mimeType,sha256Checksum)`).
   It prints "Scanning Google Drive...", like a local scan, and then how far
   it got on a line that changes in place (`messages.print_progress()`):
   "Read N of about M files and folders (P%)", where M is how many the last
   scan's cache lists (`drivecache.count_entries()`), since the Drive API
   can't count them; without a cache, just N.
3. `drivecache.entries(inner_rootpath)` reads that cache with `_parsefile`,
   which `json.loads`es each `{...}` line into a dict (id→children map +
   id→metadata map), leaving out Google's own types (Docs, Sheets,
   shortcuts...: `application/vnd.google-apps.*` but folders), and takes the
   root from the root line (a cache from before it guesses: the one id with
   children but no metadata). Files outside My Drive (no parents, or a parent
   that isn't listed) are never reached. It then DFS-walks id→children from
   the root, only into folders on the way to `inner_rootpath` and under it,
   yielding `(relpath, cloud_id, is_dir)` for what's under it, each folder
   before its contents. It raises `DriveCacheError` (which `main.py` prints
   and exits with) if there's no such folder, or if names there can't be
   paths: a `/` in a name, or a folder's name shared with another folder or
   file in one folder (also on the way to it): the user renames them in Drive
   and refreshes the cache. `clouddirtree.factory(rootpath)` builds the tree like
   `localdiskdirtree.factory()` does: a `CloudDirTree(rootpath)`, then its
   `update_from_cache()`, which adds them as `DirTree` nodes, and handles
   Drive's "two files, same path" case by suffixing `___DUP__<id>` on
   collision (same-named folders are an error, above).

Copying and removing: `CloudDirTree` keeps each file's and folder's Drive id
(`_cloud_ids`, by relpath; the root's from `entries()`' first, `''`, entry).
Copying into it (`_copy_file()`, from a local dir) uploads each file
(`MediaFileUpload`), making the folders on its way (`_folder_id()`); copying out
of it, into a local dir, downloads (`fetch_file()`, which
`LocalDiskDirTree._copy_file()` calls on the source tree); removing
(`_remove_file()`) moves files to Drive's trash, so they can be restored. The
loops around these (progress lines, dry run, Ctrl-C, the report) are
`DirTree`'s `copy_inner_entries_from_dirtree()` and `remove_files()`, shared
with `LocalDiskDirTree`. A file that fails is said in red, and the rest go on.
Each change is added to the cache on disk as it's made (not in a dry run):
a JSON line per file or folder made (`drivecache.add()`, with the fields
Drive returns, `FILE_FIELDS`, as a scan lists them), and a
`{"trashedId": ID}` line per file trashed (`drivecache.trash()`), which
`_parsefile()` drops the file for. So the cache stays up to date, and the
next run needn't refresh it. Around each change the cache is marked stale
(`drivecache.mark_stale()`, a `files.txt.stale` file next to it), and the
mark is taken away once the change is in the cache, unless it was there
before: a change cut off in the middle (e.g. Ctrl-C during an upload, when
Drive may or may not have the file) leaves it, so the next run's refresh
prompt says the cache may be out of date, and a refresh clears the mark.

Logging in to Drive (`token.json`/`credentials.json`, `SCOPES=[drive]`: all of
Drive, to change files too) is `driveapi.service()`, which also makes the
service once for all callers. A saved login without those scopes (e.g. from
when dirdelta only listed files) means logging in again, as does a rejected
refresh. A near-duplicate, unused implementation used to
sit alongside it as `scandrive.py`; it's now archived at
`unused/scandrive.py` (outside any package), not part of the app.

### `dirdiff.py`, `programs.py`
`dirdiff.files_not_in(src_dir, dst_dir, max_depth)` runs `dirdiff -0 SRC DST`,
returning src's files (relative paths) that dst lacks, and find's errors.
It scans both dirs in C++ (~1s for two 119k-file dirs, where building their
Python trees took ~6s). `programs.find(name, env_var)` finds treepicker and
dirdiff: `$env_var`, next to the running python, `lib/treepicker/build/`, `PATH`.

### `interactive_dir_sync.py`
`InteractiveDirSync(src, dst)`. Its diff (`_missing()`): for two local dirs,
`dirdiff`, run anew for each action (so the dirs' own trees are never
scanned: `dirsync_main` makes them empty, and there's no stale scan), with a
warning screen if find couldn't read everything; with a cloud replica, the
trees' `get_unknown_entries_in_given_dirtree()`. Either way it's a list of
relpaths: no Python tree is built of the missing files (for 111k of them that
took ~2.5s; the picker now opens 0.2s after the diff).
- `sync(action)`, one pass, for `COPY` (src's missing files into dst) or
  `REMOVE` (them from src): diff → `picker.pick_files(src, missing)` to
  select files → confirm (`picker.pick_option(['No', 'Yes'])`, No first so
  it's selected; No, or quitting it, picks again, starting from the same
  picks via `pick_files(picked=...)`) → act (on the progress screen) → back
  to the main menu. `FileEntry`s are made for the picked files only
  (`_file_entry()`), and passed to `_copy(files)`/`_remove(files)`.
- `_copy()` rebuilds a `DirTree` from just the selected `FileEntry`s via
  `dirtree.DirTree.from_file_entries` (previously
  miscalled as a `DirTree` classmethod — fixed, known-issues.md #3), then
  calls `dst.copy_inner_entries_from_dirtree(...)` — which is a dry run
  unless `DRYRUN=0` (see `localdiskdirtree.py` above).
- `_remove()` calls `src.remove_files(...)` (see `localdiskdirtree.py`
  above), which, unless it's a dry run, deletes the selected files and drops
  them from the in-memory `src` tree so the next diff doesn't list them
  again. (The `TypeError` from mixing `{}` placeholders with `%` that used
  to crash it is fixed, known-issues.md #16.)

### `dirsync_main.py` / `dirpick_main.py`
Thin wiring: for two local dirs, make their `LocalDiskDirTree`s without
scanning them (each action diffs them with dirdiff, see below); else build
both `DirTree`s, warn (`scan_errors_warning`, shown with
`messages.show()`) about each local one whose scan couldn't read everything,
since its diff may then be wrong,
present a top-level menu (`_sync`: a loop of `picker.pick_option()` over
`_Action`s, each an `InteractiveDirSync(src, dst, missing)`'s
`sync(COPY or REMOVE)` or `view_diff()`, until Quit), by what's writable
(`_is_writable`: a cloud replica, or a `LocalDiskDirTree` with write
permission, so not one on a read-only mount): each way, `Copy A→B` if B is
writable and A or B is local (not within Drive), `Remove from A` (A's files
that B lacks) if A is writable, and if neither, `View diff A-not-B` (the
others' pickers already show that diff); then `Quit`. Before the menu, a
"Read-only" screen (`messages.show()`) says which replicas are read-only and
why. Each way's diff (`interactive_dir_sync.find_missing()`: dirdiff for two
local dirs, else the trees as they are, so a cloud tree is never scanned
again) is found once, on a daemon thread (`_Way.find_missing()`, a
`concurrent.futures.Future`), as the menu opens, and shared by that way's
options: while it's being found they're shown as "(loading...)", with the
dots moving, then with how many files it has (`pick_option(shown_as=...)`,
which sends treepicker the changes through `--updates`). Choosing an option
waits for both ways (an action may change what the other is diffing), and
after a live (not dry run) action both are found again. Given a `Replicas`
(as `run` does), the menu also has "Add to favorites" (or "Remove from
favorites") before Quit, which saves the change.
`dirpick_main.run` returns the picked path: for a local dir it lets
treepicker scan the dir itself (`picker.pick_under_dir`, much faster than
building a `DirTree`, ~3s for 119k files); for a cloud path it builds the
`CloudDirTree` and uses `picker.pick_from_tree`. `main.py` then prints the
path, or `os.execvp`s the `-x` program on it.

### `messages.py`
`print_line(line, color=None)`: prints dirdelta's messages (scanning,
copying, removing...) as plain lines, optionally colored with `termcolor`,
encoding with `surrogateescape` so file names that aren't UTF-8 print as
they are. A picker covers what was printed before it, so what's to be read
goes on a screen that waits for Enter: `show(title, lines)` for messages
(the scan warnings, "Nothing to copy"), and `progress_screen(title)` for
actions. `progress_screen(title)` (a context manager) runs an action on the whole
screen, on a terminal: it clears it, keeps the title on the top line with
a scroll region (`ESC[2;Hr`) for the lines under it, catches Ctrl-C, and
at the end says Done/Stopped and waits for Enter. Actions that catch Ctrl-C to say
how far they got (copying, removing) call `note_stopped()`. Without a
terminal it only prints.

### `dryrun.py`
`DRYRUN` (true unless `DRYRUN=0` is set), read at each use, and `label()`:
("DRY RUN", "green") or ("LIVE", "red"), which `picker.py` passes to every
treepicker run (`--label`, `--label-color`: at the start of its bottom line)
and `interactive_dir_sync.py` to the progress screen (its top line).

### `picker.py`
Runs `treepicker` (from github.com/eliranle6/treepicker; `$DIRDELTA_PICKER`, or
`treepicker` on `PATH`) as a subprocess for each pick, fzf-style: treepicker
draws on `/dev/tty`, reads its input on stdin and prints what was picked on
stdout, all `\0`-separated (`-0`). Exit code 1 means the user quit (→
`None`); others raise `PickerError`. See `docs/treepicker-integration.md`.
- `pick_from_tree(tree, header, dirs_only)`: picks one node of a `DirTree` (cloud
  picker mode, the cloud diff view). Sends its node ids (relative paths,
  like treepicker's; the root, `''`, is treepicker's `.`), each after its type
  (`--typed`: `f sub/x`, `d sub`), each dir before its contents, siblings
  sorted by tag; maps the picked path back to the node's entry (`.` is the
  root).
- `pick_files(rootpath, relpaths, header, picked)`: picks several of a
  list of files (`-m`), sent as `f sub/x` lines only: treepicker adds their
  dirs. Returns the picked files' relpaths (treepicker also prints the dirs
  whose files are all picked; those are dropped). `picked` start picked
  (`--picked FILE`).
- `pick_under_dir(dirpath, max_depth, dirs_only, lazy, header)`:
  `treepicker [--max-depth N] [--dirs-only] [--lazy] DIR`.
- `pick_option(options, header)`: `treepicker --list`, for menus.
Names are passed as bytes with `surrogateescape`, so non-UTF-8 file names
round-trip. Tests (`tests/test_picker.py`) run a fake treepicker script.

## `lib/treepicker/` — treepicker and dirdiff (git submodule)

The C++ tree picker dirdelta runs, and `dirdiff` (github.com/eliranle6/treepicker;
its README and `--help` describe them). `make build` builds them in
`lib/treepicker/build/`; `make install`/`make deploy` copy them next to the
environment's python, where `programs.find()` looks first. The Python picker
library that was the UI before (with `cursesswitch`) was
removed on 2026-10-24.
