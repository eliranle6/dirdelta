# Architecture

## Data flow, end to end

```
shell script (dirsync-*.sh / dirpick-*.sh)
  → main.py: parse_args() → cursesswitch.wrapper(main)   [curses init, unless MODE=static/direct]
    → dirsync_main.run(args)  OR  dirpick_main.run(args)
       → utils.create_dirtree_from_arg(path)   for each replica path
            → clouddirtreefactory.factory_interactive()   if path starts with "cloud"
            → localdiskdirtree.factory()                   otherwise
       → interactive_dir_sync.InteractiveDirSync(src, dst)
            .sync() / .view_diff()
              → DirTree.get_unknown_entries_in_given_dirtree()   (the diff)
              → treepicker.TreePicker(missing_tree).pick()        (curses selection UI)
              → optionpicker.OptionPickerByMenuTraverse([...]).pick_one()  (Copy/Remove/Nothing/Reselect menu)
              → LocalDiskDirTree.copy_inner_entries_from_dirtree() / os.unlink()
```

## `dirdelta/` — the application

### `main.py`
Argparse: `dir_a_path` (required), `dir_b_path` (optional), `-x/--execute`,
`-m/--max-depth` (default 20, currently unused downstream — not threaded
into `localdiskdirtree.factory()`'s `max_depth` param anywhere in the call
chain from `main.py`). One positional path → `dirpick_main.run`; two →
`dirsync_main.run`. Wrapped in `cursesswitch.wrapper(main)` unless
`MODE=static`.

### `utils.py`
`create_dirtree_from_arg(rootpath)` is the single dispatch point deciding
cloud vs local: a path is "cloud" iff its first path component
(`CloudDirTree.path_components`) is literally the string `"cloud"`.
`__validate_replica` checks the path is an existing directory for the local
case, reporting failures via `cursesswitch.print_string` (the missing
`import cursesswitch` here was fixed — known-issues.md #4).

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
next to the class) is meant to rebuild a `DirTree` from a flat list of
`FileEntry` objects, to build the "chosen files" sub-tree just before a
copy. As written it crashes before doing so (known-issues.md #17).

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
`_copy_local_file_to_tree_with_path`. **That method's `shutil.copy` is gated
behind the module-level `DRYRUN` flag** (known-issues.md #5): dry-run is
the default, so nodes get added to the tree and the containing directory
gets created, but bytes are only copied when `DRYRUN=0` is set in the
environment. (Previously called a nonexistent
`self._add_file_by_path(...)` and referenced a `filesystem_dirpath`
attribute that doesn't exist on the current `FileEntry`/`DirEntry` — both
fixed, see known-issues.md #2 — and is now covered by
`tests/test_localdiskdirtree.py`.)

### `clouddirtree.py` / `clouddirtreefactory.py`
Cloud state is never queried live per-scan. Instead:
1. `factory_interactive(rootpath)` ensures a cache file exists at
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
- `sync()` loop: diff → `treepicker.TreePicker(missing).pick()` to select
  files → `menu.run_menu` (`Do nothing` / `Reselect files` / `Copy` /
  `Remove`) → act → recompute diff → repeat until nothing is selected, the
  user picks "Do nothing", or quits either picker.
- `_copy()` rebuilds a `DirTree` from just the selected `FileEntry`s via
  the module-level `dirtree.factory_from_list_of_file_entries` (previously
  miscalled as a `DirTree` classmethod — fixed, known-issues.md #3), then
  calls `dst.copy_inner_entries_from_dirtree(...)` — which is a dry run
  unless `DRYRUN=0` (see `localdiskdirtree.py` above) — and rescans `dst`.
  Currently crashes in `factory_from_list_of_file_entries` before any of
  that (known-issues.md #17).
- `_remove()` prints a progress line, then calls
  `os.unlink(file_entry.full_filesystem_path())` for each selected file.
  The `TypeError` from mixing `{}` placeholders with `%` that used to crash
  it first is fixed (known-issues.md #16). Note `_remove()` is **not**
  gated by `DRYRUN` — it really deletes files.

### `menu.py`
`run_menu([(label, handler), ...])` shows the labels with
`OptionPickerByMenuTraverse`, calls the chosen label's handler (if not
`None`), and returns the label, or `None` if the user quit the menu. Both
the top-level sync menu and `InteractiveDirSync`'s Copy/Remove menu use it.

### `dirsync_main.py` / `dirpick_main.py`
Thin wiring: build both `DirTree`s, present a top-level menu (`View diff
A-not-B`, `View diff B-not-A`, `Remove/Copy A→B`, `Remove/Copy B→A`, `Quit`).
Copy/Remove options are only offered when **both** replicas are
`LocalDiskDirTree` — cloud replicas are diff/view-only from this menu.
`dirpick_main.FilesystemPicker` just wraps a single-select `TreePicker`.

### `config.py`
Only constants, currently unused elsewhere in the read code path:
`POSSIBLE_PARENT_DIRS`, `FILE_EXTENTION_FOR_REPLICA_CANDIDATE = "mp3"`,
`MIN_NR_FILES_WITH_EXTENTION_FOR_REPLICA_CANDIDATE = 30` — looks like
scaffolding for an unfinished "auto-detect replica candidates" feature
(matches the `MUSIC_FILE_EXTENTIONS` list sitting unused in `dirtree.py` too).

## `lib/treepicker/` — curses tree-picker library (own git repo, nested as a submodule)

- `TreePicker` (`treepicker.py`) — the main class. State machine over modes:
  navigation / non-interactive search / interactive search / return / quit.
  Keybindings registered via `keybind.KeyBind` (vim-ish: `hjkl` navigate,
  `space` toggle, `/` interactive search, `Ctrl-/` non-interactive search,
  `g`/`G` first/last, `Ctrl-d`/`Ctrl-u` or `d`/`u` page down/up, `Enter`
  return selection, `q`/`Ctrl-c` quit).
- `treepickermodel.TreePickerModel` — selection/pick-set state, search
  filtering (rebuilds a filtered `treelib.Tree` copy tagging nodes with
  `.matching`), delegates cursor movement to `treenavigator.TreeNavigator`.
- `treenavigator.TreeNavigator` — cursor movement over siblings/children
  with a sorted-children cache (sort key = `str(node.data)`); leaf-to-leaf
  jumps via `move_selection_relative_leaf`.
- `treeprinter.py` / `linescanner.py` / `pagination.py` / `treesearch.py` /
  `getcher.py` — rendering, raw single-char input reading (Unix `getch`),
  pagination, and substring search respectively (not fully read; skim these
  before making UI changes).
- `optionpicker.py` — flat "pick one of N strings" menu, implemented by
  wrapping the strings as a 1-level `treelib.Tree` and reusing `TreePicker`.
  `OptionPickerByMenuTraverse` is its only implementation.

## `lib/treepicker/cursesswitch.py` — curses init/teardown + colored print

A flat module (no longer its own repo/package — bundled into `treepicker`
as a single file, since it was really just one module,`printer.py`, behind
a re-exporting `__init__.py`). `wrapper(main)` calls
`curses.wrapper(...)` and installs a module-global `_CursesWindowPrinter`
bound to the curses window, unless `MODE=direct`, in which case a
`_ConsolePrinter` (plain colored stdout via `termcolor`) is used instead —
this is what lets the same `cursesswitch.print_string` calls work whether
or not curses is active. `_CursesWindowPrinter` buffers printed lines and
only redraws newly-added/overflowed lines (`_draw`/`_print_missing_lines`)
rather than a full repaint every call.

