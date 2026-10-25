# Architecture

## Data flow, end to end

```
shell script (dirsync-*.sh / dirpick-*.sh)
  → main.py: parse_args() → dirsync_main.run(args)  OR  dirpick_main.run(args)
     (no curses: each picker is a dirpicker run, which has the terminal while
      it's open; messages in between are plain lines, via messages.print_line)
       dirpick_main: local dir → picker.pick_under_dir(dir)   (dirpicker scans it)
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
Argparse: `dir_a_path` (required), `dir_b_path` (optional), `-x/--execute`,
`-m/--max-depth` (default 20, passed down to `localdiskdirtree.factory` as
`find -maxdepth`). One positional path → `dirpick_main.run`; two →
`dirsync_main.run`. No curses setup: a `picker.PickerError` (dirpicker
missing or failing) exits with its message.

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
relative (`sub/x`; the root's is `''`), like dirpicker's paths.

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
   (`files().list`, paged, `fields=... files(id,name,parents,kind,size,
   mimeType,sha256Checksum)`) and writes one JSON line per file to the
   cache.
3. `drivecache.entries(inner_rootpath)` reads that cache with `_parsefile`,
   which `json.loads`es each `{...}` line into a dict (id→children map +
   id→metadata map), finds the root (the one id with children but no
   metadata), then DFS-walks id→children, yielding `(relpath, cloud_id,
   is_dir)` for what's under the requested `inner_rootpath`, each folder
   before its contents. `clouddirtree.factory(rootpath)` builds the tree like
   `localdiskdirtree.factory()` does: a `CloudDirTree(rootpath)`, then its
   `update_from_cache()`, which adds them as `DirTree` nodes, and handles
   Drive's "two files, same path" case by suffixing `___DUP__<id>` on
   collision.

OAuth token handling (`token.json`/`credentials.json`,
`SCOPES=[drive.metadata.readonly]`) lives in `clouddirtreefactory.py`'s
`_scan_drive_files_list`. A near-duplicate, unused implementation used to
sit alongside it as `scandrive.py`; it's now archived at
`unused/scandrive.py` (outside any package), not part of the app.

### `dirdiff.py`, `programs.py`
`dirdiff.files_not_in(src_dir, dst_dir, max_depth)` runs `dirdiff -0 SRC DST`,
returning src's files (relative paths) that dst lacks, and find's errors.
It scans both dirs in C++ (~1s for two 119k-file dirs, where building their
Python trees took ~6s). `programs.find(name, env_var)` finds dirpicker and
dirdiff: `$env_var`, next to the running python, `lib/cpptree/build/`, `PATH`.

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
(label, action) pairs, each action an `InteractiveDirSync(src, dst)`'s
`sync(COPY or REMOVE)` or `view_diff()`, until Quit): `Copy A→B`, `Copy B→A`, `Remove from A` (A's
files that B lacks), `Remove from B`, `Quit` when **both** replicas are
`LocalDiskDirTree`s; else (a cloud replica) only `View diff A-not-B`,
`View diff B-not-A`, `Quit`, since cloud replicas are view-only (and the
local menu's pickers already show those diffs).
`dirpick_main.run` returns the picked path: for a local dir it lets
dirpicker scan the dir itself (`picker.pick_under_dir`, much faster than
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
dirpicker run (`--label`, `--label-color`: at the start of its bottom line)
and `interactive_dir_sync.py` to the progress screen (its top line).

### `picker.py`
Runs `dirpicker` (from github.com/levioctl/cpptree; `$DIRDELTA_PICKER`, or
`dirpicker` on `PATH`) as a subprocess for each pick, fzf-style: dirpicker
draws on `/dev/tty`, reads its input on stdin and prints what was picked on
stdout, all `\0`-separated (`-0`). Exit code 1 means the user quit (→
`None`); others raise `PickerError`. See `docs/dirpicker-integration.md`.
- `pick_from_tree(tree, header)`: picks one node of a `DirTree` (cloud
  picker mode, the cloud diff view). Sends its node ids (relative paths,
  like dirpicker's; the root, `''`, is dirpicker's `.`), each after its type
  (`--typed`: `f sub/x`, `d sub`), each dir before its contents, siblings
  sorted by tag; maps the picked path back to the node's entry (`.` is the
  root).
- `pick_files(rootpath, relpaths, header, picked)`: picks several of a
  list of files (`-m`), sent as `f sub/x` lines only: dirpicker adds their
  dirs. Returns the picked files' relpaths (dirpicker also prints the dirs
  whose files are all picked; those are dropped). `picked` start picked
  (`--picked FILE`).
- `pick_under_dir(dirpath, max_depth)`: `dirpicker [--max-depth N] DIR`.
- `pick_option(options, header)`: `dirpicker --list`, for menus.
Names are passed as bytes with `surrogateescape`, so non-UTF-8 file names
round-trip. Tests (`tests/test_picker.py`) run a fake dirpicker script.

## `lib/cpptree/` — dirpicker and dirdiff (git submodule)

The C++ tree picker dirdelta runs, and `dirdiff` (github.com/levioctl/cpptree;
its README and `--help` describe them). `make build` builds them in
`lib/cpptree/build/`; `make install`/`make deploy` copy them next to the
environment's python, where `programs.find()` looks first. The Python picker
library that was the UI before (`lib/treepicker`, with `cursesswitch`) was
removed on 2026-10-24.
