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
       → menu.run_menu([...]) → picker.pick_option()       (the top-level menu)
       → interactive_dir_sync.InteractiveDirSync(src, dst)
            .sync() / .view_diff()
              → DirTree.get_unknown_entries_in_given_dirtree()   (the diff)
              → picker.pick_from_tree(missing_tree, multi=True)  (selection UI)
              → menu.run_menu([...])                             (Copy/Remove/Nothing/Reselect menu)
              → LocalDiskDirTree.copy_inner_entries_from_dirtree() / os.unlink()
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
cloud vs local: a path is "cloud" iff its first path component
(`CloudDirTree.path_components`) is literally the string `"cloud"`.
`validate_dir` checks the path is an existing directory for the local
case, exiting with a message (via `messages.print_line`) otherwise.
`is_cloud_path` is public too, for `dirpick_main`.

### `dirtree.py` — the core data structure
`DirTree(treelib.Tree)` models a filesystem tree. Two entry types:
- `DirEntry(name, parent_relpath, parent_fullpath)` — directory node
- `FileEntry(name, parent_dir_entry)` — file node, no size/hash/mtime stored

Construction is deliberately locked down: `DirTree.__init__` overrides
`self.create_node` after root creation to always raise
`NotImplementedError`, forcing all callers through
`add_file_by_relpath` / `add_file_by_fullpath` /
`create_dir_node_from_relpath_if_not_exists` so relpath/fullpath bookkeeping
stays consistent. Node `identifier` in `treelib` is the file's `relpath`
(root's is `'/'`).

**The diff algorithm** — `get_unknown_entries_in_given_dirtree(self, other)`:
for every file in `other`, if its `relpath` is not a node id in `self`,
it's "missing" — collected into a fresh `DirTree` rooted at `other`'s root.
This is called as `dst.get_unknown_entries_in_given_dirtree(src)`, i.e. it
answers "what's in src that dst doesn't have" — pure path-string membership
test, no content comparison at all, matching the stated scope.

`factory_from_list_of_file_entries` (module-level function, despite living
next to the class) builds a `DirTree` holding a flat list of `FileEntry`
objects at their relpaths: the "chosen files" sub-tree, just before a copy.
`add_file_by_relpath` returns the existing entry for a file already in the
tree, which is what lets `update_from_filesystem` rescan a tree in place.

### `localdiskdirtree.py`
`LocalDiskDirTree(DirTree)`. `factory(filesystem_dirpath, max_depth=None,
file_extentions=None, dirs_only=False, include_hidden=True, silent=False)`
builds the tree then calls `update_from_filesystem`, which shells out via
`findcmdwrapper.find_files` / `find_dirs` (literally invokes the `find`
binary with `-maxdepth`/`-regex`/`-type`/hidden-file exclusion flags) rather
than walking Python-side. Directories are added after files, with the root
itself excluded (`dirnames_fullpath.remove(self.fullpath())`).

`copy_inner_entries_from_dirtree(dirtree)` — for each file in the given
sub-tree, calls `add_file_by_relpath` to add the node to `self`'s tree, then
ensures the destination directory exists (`os.makedirs`, tolerant of
already-exists, path derived from `full_filesystem_path()`), then calls
`_copy_local_file_to_tree_with_path`. **Writing is gated behind the
module-level `DRYRUN` flag** (known-issues.md #5): dry-run is the default,
so nodes get added to the tree, but no directory is created and no bytes
are copied unless `DRYRUN=0` is set in the environment. `remove_files()`
is gated the same way: it deletes only with `DRYRUN=0`, and drops the
nodes from the tree either way. Both print a progress line per file, and a
summary. (Previously called a nonexistent
`self._add_file_by_path(...)` and referenced a `filesystem_dirpath`
attribute that doesn't exist on the current `FileEntry`/`DirEntry` — both
fixed, see known-issues.md #2 — and is now covered by
`tests/test_localdiskdirtree.py`.)

### `clouddirtree.py` / `clouddirtreefactory.py`
Cloud state is never queried live per-scan. Instead:
1. `utils.create_dirtree_from_arg` calls `factory_interactive(rootpath)`
   for any path whose first component is `cloud`. It ensures a cache file exists at
   `CloudDirTree.FILE_LIST_CACHE` (`~/.cache/dirman/files.txt`), prompting
   the user via `OptionPickerByMenuTraverse` to refresh it if it already
   exists.
2. `_refresh_cache()` → `_scan_drive_files_list()` calls the Drive v3 API
   (`files().list`, paged, `fields=... files(id,name,parents,kind,size,
   mimeType,sha256Checksum)`) and writes one JSON line per file to the
   cache.
3. `CloudDirTree.__init__` reads that cache with `_parsefile`, which
   `json.loads`es each `{...}` line into a dict (id→children map + id→metadata
   map), finds the root (the one id with children but no metadata), then
   `_dirdict_to_dirtree` DFS-walks id→children building `DirTree` nodes,
   only for entries under the requested `inner_rootpath`. Handles Drive's
   "two files, same path" case by suffixing `___DUP__<id>` on collision.

OAuth token handling (`token.json`/`credentials.json`,
`SCOPES=[drive.metadata.readonly]`) lives in `clouddirtreefactory.py`'s
`_scan_drive_files_list`. A near-duplicate, unused implementation used to
sit alongside it as `scandrive.py`; it's now archived at
`unused/scandrive.py` (outside any package), not part of the app.

### `interactive_dir_sync.py`
`InteractiveDirSync(src, dst)`:
- `sync()` loop: diff → `picker.pick_from_tree(missing, multi=True)` to select
  files → `menu.run_menu` (`Do nothing` / `Reselect files` / `Copy` /
  `Remove`) → act → recompute diff → repeat until nothing is selected, the
  user picks "Do nothing", or quits either picker.
- `_copy()` rebuilds a `DirTree` from just the selected `FileEntry`s via
  the module-level `dirtree.factory_from_list_of_file_entries` (previously
  miscalled as a `DirTree` classmethod — fixed, known-issues.md #3), then
  calls `dst.copy_inner_entries_from_dirtree(...)` — which is a dry run
  unless `DRYRUN=0` (see `localdiskdirtree.py` above) — and rescans `dst`.
- `_remove()` calls `src.remove_files(...)` (see `localdiskdirtree.py`
  above), which deletes the selected files unless it's a dry run, and drops
  them from the in-memory `src` tree so the next diff doesn't list them
  again. (The `TypeError` from mixing `{}` placeholders with `%` that used
  to crash it is fixed, known-issues.md #16.)

### `menu.py`
`run_menu([(label, handler), ...])` shows the labels with
`picker.pick_option` (in the order given), calls the chosen label's handler (if not
`None`), and returns the label, or `None` if the user quit the menu. Both
the top-level sync menu and `InteractiveDirSync`'s Copy/Remove menu use it.

### `dirsync_main.py` / `dirpick_main.py`
Thin wiring: build both `DirTree`s, present a top-level menu (`View diff
A-not-B`, `View diff B-not-A`, `Remove/Copy A→B`, `Remove/Copy B→A`, `Quit`).
Copy/Remove options are only offered when **both** replicas are
`LocalDiskDirTree` — cloud replicas are diff/view-only from this menu.
`dirpick_main.run` returns the picked path: for a local dir it lets
dirpicker scan the dir itself (`picker.pick_under_dir`, much faster than
building a `DirTree`, ~3s for 119k files); for a cloud path it builds the
`CloudDirTree` and uses `picker.pick_from_tree`. `main.py` then prints the
path, or `os.execvp`s the `-x` program on it.

### `messages.py`
`print_line(line, color=None)`: prints dirdelta's messages (scanning,
copying, removing...) as plain lines, optionally colored with `termcolor`,
encoding with `surrogateescape` so file names that aren't UTF-8 print as
they are. The lines printed since the last picker are kept too (the last 8),
and `picker.py` shows them at the top of the next picker's header
(`take_recent()`), since the picker's screen would hide them: e.g. a copy's
progress and summary appear above the menu that follows it.

### `picker.py`
Runs `dirpicker` (from github.com/levioctl/cpptree; `$DIRDELTA_PICKER`, or
`dirpicker` on `PATH`) as a subprocess for each pick, fzf-style: dirpicker
draws on `/dev/tty`, reads its input on stdin and prints what was picked on
stdout, all `\0`-separated (`-0`). Exit code 1 means the user quit (→
`None`); others raise `PickerError`. See `docs/dirpicker-integration.md`.
- `pick_from_tree(tree, header, multi)`: sends a `DirTree`'s node ids
  without their leading `/` (`/sub/x` → `sub/x`), each dir before its
  contents, siblings sorted by tag; maps the picked paths back to the nodes'
  entries (`.` is the root).
- `pick_under_dir(dirpath, max_depth)`: `dirpicker [--max-depth N] DIR`.
- `pick_option(options, header)`: `dirpicker --list`, for menus.
Names are passed as bytes with `surrogateescape`, so non-UTF-8 file names
round-trip. Tests (`tests/test_picker.py`) run a fake dirpicker script.

## `lib/cpptree/` — dirpicker (git submodule)

The C++ tree picker dirdelta runs (github.com/levioctl/cpptree; its README and
`dirpicker --help` describe it). `make build` builds
`lib/cpptree/build/dirpicker`; `make install`/`make deploy` copy it next to
the environment's python, where `picker.py` looks first. The Python picker
library that was the UI before (`lib/treepicker`, with `cursesswitch`) was
removed on 2026-10-24.
