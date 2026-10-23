# Known issues / dead code

Found by reading (not running) the code on 2026-07-13. Grouped by how
confident the read is; nothing here has been executed or fixed. File paths
are relative to `dirdelta/` unless noted.

Numbered 2026-07-19 for discussion purposes, re-verified against the
current source at that time — all still present as described (the
`treepicker` submodule's real on-disk path is `lib/treepicker/treepicker/*.py`,
a package with `__init__.py`, not the flat `lib/treepicker/*.py` some
mentions below imply; that's a path nit in this doc, not a code bug).

## Confirmed by grep (referenced symbol genuinely doesn't exist)

1. ~~**`full_filesystem_path()` is called but never defined anywhere in the
  codebase.**~~ **FIXED** (2026-07-19, `dirtree.py`): `DirEntry`/`FileEntry`
  now implement `full_filesystem_path()`. While implementing it, also found
  and fixed the reason it had never been restored after the dirsync→dirdelta
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

6. ~~**`treepicker/treepicker.py:21`** constructs
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

7. **`clouddirtreefactory.py:29`** — `factory_interactive` returns
  `CloudDirTree(path_in_cloud)`, but `path_in_cloud` is never assigned
  anywhere in the function (only the parameter `rootpath` is). This would
  raise `NameError` — the interactive cloud-tree factory path looks
  unfinished/broken as written.

8. **`clouddirtree.py:120-124`** — `CloudDirTree._path_in_cloud` is declared
  `@staticmethod` but its body references `self.path_components(path)`.
  Calling it would raise `NameError: name 'self' is not defined`. (Note:
  nothing currently calls `_path_in_cloud` — it may be dead.)

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

12. **`main.py`'s `-m/--max-depth` argument** is parsed but, in the traced
  call chain (`main.py` → `dirsync_main.run`/`dirpick_main.run` →
  `utils.create_dirtree_from_arg` → `localdiskdirtree.factory`), `args.max_depth`
  is never actually passed through — `create_dirtree_from_arg` calls
  `localdiskdirtree.factory(rootpath)` with no `max_depth` kwarg, so the
  factory's `max_depth=None` default always applies regardless of what the
  user passes on the CLI.

13. ~~**`treepicker/treesearch.py:48-56`** (`__main__` block) calls
  `dirtree.DirTree.factory_from_filesystem(...)`, which does not
  exist.~~ **FIXED** (2026-10-23): removed.

14. **`treepicker/exampletree.py:6`** — `for i in range(6) + range(10, 15)`
  is Python 2 syntax (`range()` returned a list there); in Python 3
  `range` objects don't support `+`. This demo tree is used by
  `treepicker.py`'s `__main__` block, which therefore can't run as a
  standalone script under Python 3. (`treeprinter.py`'s `__main__`, which
  also used it, was removed 2026-10-23.) Doesn't affect the real app, which
  never imports `exampletree`.

## Confirmed by running (2026-10-23)

17. **`dirtree.factory_from_list_of_file_entries`** (`dirtree.py:5-20`), which
  "Copy" uses to build the tree of chosen files, cannot work as written: it
  splits `file_entry.fullpath` assuming the root's basename is the first
  path component (a scripted Copy on copies of the fixture dirs raised
  `ValueError: File's first path component must match ...`), and past that
  it calls `dirtree.get_dir_node(...)`, which doesn't exist, and
  `dirtree.create_node(...)`, which `DirTree` overrides to always raise.
  **Copy crashes here before any file is touched**, DRYRUN or not.

18. **`treenavigator.move_selection_relative_leaf`** (`Ctrl-j`/`Ctrl-k`,
  next/prev leaf) assigns and reads `self._selected_node` (`treenavigator.py:81,87`),
  an attribute that doesn't exist (the real one is `_selected_node_id`),
  and the prev direction calls `explore_deepest_child(DIRECTION_PREV)`,
  which calls a nonexistent `self.last_node()`. Both raise
  `AttributeError` in random picker scenarios.

19. **Searching with no matches while `including_root=False`** raises
  `AttributeError: 'NoneType' object has no attribute 'identifier'`: the
  filtered tree is just the root, so
  `TreeNavigator._calculate_initial_selected_node` finds no child to select
  and dereferences `None`. The app's own pickers use `including_root=True`,
  so this only affects library users.

## Stale references (not bugs in code that runs, just dangling)

15. `config.py`'s constants (`POSSIBLE_PARENT_DIRS`,
  `FILE_EXTENTION_FOR_REPLICA_CANDIDATE`,
  `MIN_NR_FILES_WITH_EXTENTION_FOR_REPLICA_CANDIDATE`) and
  `dirtree.py`'s `MUSIC_FILE_EXTENTIONS` are defined but never referenced
  by any other module in `dirdelta/` — scaffolding for an
  unfinished "auto-detect likely replica directories by music-file count"
  feature.
