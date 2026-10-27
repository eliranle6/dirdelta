# Known issues / dead code

Issues 1-15 were found by reading the code on 2026-07-13 and numbered
2026-07-19; 16-24 were found later, mostly by running it. As of 2026-10-23
everything except 23-24 is fixed. Fixed entries are kept, struck through,
because their notes explain why the code looks the way it does. File paths
are relative to `dirdelta/` unless noted ("old picker" files were in the
old Python picker library, removed on 2026-10-24, so its entries here are
history).

## Confirmed by grep (referenced symbol genuinely doesn't exist)

1. ~~**`full_filesystem_path()` is called but never defined anywhere in the
  codebase.**~~ **FIXED** (2026-07-19, `dirtree.py`): `DirEntry`/`FileEntry`
  now implement `full_filesystem_path()`. While implementing it, also found
  and fixed the reason it had never been restored after an earlier
  rewrite: the root `DirEntry`'s `.fullpath` was collapsing to `'/'` because
  `os.path.join(parent_fullpath, name)` discards `parent_fullpath` whenever
  `name` is itself absolute, and the root's `name` is the literal string
  `'/'` — so every descendant's `.fullpath` inherited the same collapse.
  Covered by `tests/test_dirtree.py::test_fullpath_reflects_real_filesystem_path`.
  Callers (`interactive_dir_sync.py:87`, `dirpick_main.py:16,20`,
  `localdiskdirtree.py:57-58`) now resolve correctly — but see issues 2-3
  below, which still block the Copy/Remove flows independently.

2. ~~**`LocalDiskDirTree.copy_inner_entries_from_dirtree` calls
  `self._add_file_by_path(...)`**~~ **FIXED** (2026-07-19,
  `localdiskdirtree.py`): like issue 1, this was never lost — the
  pre-2018 `_add_file_by_path` (a `DirTree`-level method) was reimplemented
  under a new name, `add_file_by_relpath`, during the rewrite; this one
  caller just never got updated to call it. Two more stale references in
  the same method, both hidden behind this one (would have surfaced next
  once it was fixed), were fixed alongside it: `new_file_entry.filesystem_dirpath`
  (an attribute that doesn't exist on the current `FileEntry`/`DirEntry` —
  replaced with `os.path.dirname(new_file_entry.full_filesystem_path())`),
  and `self.remove_node(new_file_entry.fullpath())` (called `.fullpath` as
  a method, and used the wrong field — node identifiers are relpaths, not
  fullpaths — replaced with `self.remove_node(new_file_entry.relpath)`).
  Covered by `tests/test_localdiskdirtree.py`. The actual `shutil.copy` is
  still a stub (issue 5) — this fix makes the tree/directory bookkeeping
  correct, not byte copying.

3. ~~**`interactive_dir_sync.py:78` calls
  `dirtree.DirTree.factory_from_list_of_file_entries(...)` as if it were a
  classmethod/staticmethod on `DirTree`**~~ **FIXED** (2026-07-22): the
  call site now calls `dirtree.factory_from_list_of_file_entries(...)`
  directly on the module, matching its actual definition (`dirtree.py:6`)
  and the codebase's existing convention of module-level `factory*`
  functions (`localdiskdirtree.factory`, `clouddirtreefactory.factory_interactive`)
  rather than classmethods.

  **Net effect:** "Copy" no longer crashes on this bug, but still crashes
  inside `factory_from_list_of_file_entries` itself before copying anything
  (issue 17). "Remove" no longer hits issues 1-2; its next bug, issue 16, is
  fixed too.

4. ~~**`utils.py`'s `__validate_replica` calls `cursesswitch.print_string(...)`
  (`utils.py:33`) but the file never imports `cursesswitch`**~~ **FIXED**
  (2026-07-22): added `import cursesswitch`, matching how every other
  module that calls it does so (`main.py`, `dirpick_main.py`,
  `localdiskdirtree.py`, `interactive_dir_sync.py`).

16. ~~**`interactive_dir_sync.py:85-86`** (found 2026-07-19 while checking
  whether fixing issues 1-2 made "Remove" actually work) —
  `cursesswitch.print_string("Removing {} ({} out of {})" % (file_entry,
  index + 1, len(file_entries)))` uses `{}`-style placeholders with the
  `%` operator, which only understands `%s`/`%d`-style ones.~~ **FIXED**
  (2026-07-22): switched to `.format(...)`, matching the `{}` placeholders
  already in the string. "Remove" now gets past this line to
  `os.unlink(file_entry.full_filesystem_path())`.

## High-confidence from reading (not grep-verified against a live run)

5. ~~**`localdiskdirtree.py:63-65`** — `_copy_local_file_to_tree_with_path`'s
  real `shutil.copy(src, dst)` is commented out and replaced with `pass`.~~
  **FIXED** (2026-07-22): gated behind a module-level `DRYRUN` flag
  (`os.environ.get("DRYRUN") != "0"`, so dry-run is the default and only
  `DRYRUN=0` in the environment enables real copying). In dry-run mode it's
  a silent no-op — no extra print was added here since the caller
  (`copy_inner_entries_from_dirtree`, `localdiskdirtree.py:45`) already
  prints "Copying ... (n out of total)" for every file before this is
  called.

6. ~~**old picker's `treepicker.py:21`** constructs
  `TreePickerModel(tree, header, max_nr_lines, min_nr_options=..., 
  max_nr_options=...)` positionally, but
  `TreePickerModel.__init__(self, tree, including_root=True, header="",
  min_nr_options=1, max_nr_options=None)` has `including_root` — not
  `header` — as the second positional parameter.~~ **FIXED** (2026-07-22,
  submodule commit): switched to keyword args
  (`including_root=including_root, header=header`), so `TreePicker`'s own
  `including_root` parameter now actually reaches `TreeNavigator` via
  `TreePickerModel` instead of being silently dropped. Verified by
  constructing a `TreePicker` with `including_root=False` and checking
  `_picker._tree_navigator._including_root` reflects it.

7. ~~**`clouddirtreefactory.py:29`** — `factory_interactive` returns
  `CloudDirTree(path_in_cloud)`, but `path_in_cloud` is never assigned.~~
  **FIXED** (2026-10-23): returns `clouddirtree.CloudDirTree(rootpath)`.

8. ~~**`clouddirtree.py:120-124`** — `CloudDirTree._path_in_cloud` is a
  `@staticmethod` whose body references `self`.~~ **FIXED** (2026-10-23).
  It wasn't dead: `CloudDirTree.__init__` called it, as a bare
  `_path_in_cloud(...)` (`NameError`), and also read a nonexistent
  `self.FILE_LIST_CACHE` (the constant is module-level). All three fixed, so
  `CloudDirTree('cloud/mein')` now builds from the cache
  (`tests/test_clouddirtree.py`).

9. ~~**`clouddirtreefactory.py:86`** — `outfile.write(item)` writes a Drive API
  result `dict` object directly to a file opened in text mode, not a
  string.~~ **FIXED** (2026-10-23): the cache is now JSON lines, written
  with `json.dumps(item) + '\n'` and read back by `_parseline` with
  `json.loads` instead of `eval()`.

10. ~~**`optionpicker.py:26-28`** — `OptionPickerByNumbers.__init__` calls
  `super(OptionPicker, self).__init__(options)` and uses Python 2's
  `raw_input()`.~~ **FIXED** (2026-10-23) by deleting the class; nothing
  constructed it.

11. ~~**`dirtree.py:170-173`** — the `if __name__ == '__main__':` block
  references an undefined variable `t`.~~ **FIXED** (2026-10-23): removed.

12. ~~**`main.py`'s `-m/--max-depth` argument** is parsed but never passed
  through to `localdiskdirtree.factory`.~~ **FIXED** (2026-10-23):
  `create_dirtree_from_arg(rootpath, max_depth)` now receives it from both
  modes, and it's parsed as an `int`. Note this means the default of 20 now
  actually applies.

13. ~~**old picker's `treesearch.py:48-56`** (`__main__` block) calls
  `dirtree.DirTree.factory_from_filesystem(...)`, which does not
  exist.~~ **FIXED** (2026-10-23): removed.

14. ~~**old picker's `exampletree.py:6`** — `range(6) + range(10, 15)` is
  Python 2 only.~~ **FIXED** (2026-10-23): uses `list(range(...))`.

15. ~~`config.py`'s constants and `dirtree.py`'s `MUSIC_FILE_EXTENTIONS` were
  never referenced.~~ **FIXED** (2026-10-23): both deleted.

## Confirmed by running, all FIXED 2026-10-23

17-21 have regression tests that fail on the old code.

17. **Copy crashed before touching any file.**
  `dirtree.factory_from_list_of_file_entries` split `file_entry.fullpath`
  assuming the root's basename was its first component (`ValueError`), then
  called a nonexistent `get_dir_node` and the deliberately-raising
  `create_node`. It now just adds each entry's relpath to a fresh
  `DirTree`. The rescan right after the copy then crashed too
  (`DuplicatedNodeIdError`, since `update_from_filesystem` re-adds every
  file), so `add_file_by_relpath` now returns the existing entry for a file
  already in the tree.

18. **Next/prev leaf (`Ctrl-j`/`Ctrl-k`) raised `AttributeError`**:
  `move_selection_relative_leaf` used a nonexistent `self._selected_node`
  instead of `_selected_node_id`, and the prev direction called a
  nonexistent `self.last_node()` (now `move_selection_absolute(index=-1)`).

19. **Searching with no matches while `including_root=False` crashed the
  navigator** (`_calculate_initial_selected_node` and `go_to_root` indexed
  into an empty child list). Both now fall back to selecting the root.
  3000 random picker sessions (navigation, leaf jumps, picks, searches) now
  run without a single crash, and the ones that never crashed before render
  exactly as they used to.

20. **Remove left the removed files in the diff**: they were unlinked but
  stayed in the in-memory source tree, so the next round listed them again
  and removing them again raised `FileNotFoundError`. `_remove` now also
  drops each node from the source tree.

21. **Picker mode's result never reached the user.** The picked path was
  printed inside curses, so it vanished when curses restored the terminal,
  and `-x` called `.full_filesystem_path()` on the list `pick_one()`
  returns (`AttributeError`), then `os.execve`'d with an empty environment
  and no `PATH` lookup. `dirpick_main.run` now returns the path,
  `cursesswitch.wrapper` passes it back, and `main.py` prints it or
  `os.execvp`s the program once curses has exited.

22. **Smaller crashes**: `DirTree('/x/y/')` set its root path to `''` (a
  trailing slash made it take `basename`); `utils` raised `IndexError` on
  the path `/`; `_refresh_cache` wrote text into a binary `TemporaryFile`
  and then copied from its `.name` (an fd number) after closing it (it now
  writes `files.txt.tmp` and renames it over the cache, so a failed scan
  keeps the old cache); `_CursesWindowPrinter.print_line` called itself
  forever; the `bin/` scripts ran system `python3`, which lacks `treelib`
  (they now prefer the venv's), and `bin/example-sync-local.sh` synced the repo's
  own fixtures, where a Remove would delete them (it now syncs a temp copy).

## Still open

23. ~~**Menus are shown in alphabetical order**, not the order the code lists
  options in, because the picker sorts every sibling group by
  `str(node.data)`.~~ **FIXED** (2026-10-23): menus are `treepicker --list`
  now, which keeps the order given.

24. ~~**Cloud scanning is untested against real Drive data.**
  `drivecache._parsefile` asserts exactly one id has children but no
  metadata (the Drive root); files whose parent folder isn't in the listing
  (e.g. shared folders) would break that assumption. And a `___DUP__`-renamed
  folder's children still attach to the first folder of that name.~~
  **FIXED** (2026-10-25): the scan writes down My Drive's root id, so files
  outside My Drive are left out rather than breaking the assert, and
  same-named folders (or a `/` in a name) are an error telling the user to
  rename them. Also from reading the code then: the scan skips the trash,
  Google Docs/Sheets/shortcuts are left out (they're not files to sync), and
  a cloud folder that isn't there is an error rather than an empty tree.
