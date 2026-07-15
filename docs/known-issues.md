# Known issues / dead code

Found by reading (not running) the code on 2026-07-13. Grouped by how
confident the read is; nothing here has been executed or fixed. File paths
are relative to `dirdelta/` unless noted.

## Confirmed by grep (referenced symbol genuinely doesn't exist)

- **`full_filesystem_path()` is called but never defined anywhere in the
  codebase.** Callers: `interactive_dir_sync.py:87` (the Remove flow —
  `os.unlink(file_entry.full_filesystem_path())`), `dirpick_main.py:16,20`,
  `localdiskdirtree.py:57-58` (the Copy flow). The docstring in
  `dirtree.py:73` documents it as if it existed on `node.data`, but neither
  `FileEntry` nor `DirEntry` in `dirtree.py` define it — closest existing
  attribute is `.fullpath`. **Both the Remove and Copy flows in
  `interactive_dir_sync.py` would raise `AttributeError` if exercised**,
  which is presumably why `_copy_local_file_to_tree_with_path`'s real
  `shutil.copy` is commented out (line below never runs anyway once the
  `full_filesystem_path()` call above it raises).

- **`LocalDiskDirTree.copy_inner_entries_from_dirtree` calls
  `self._add_file_by_path(...)`** (`localdiskdirtree.py:46`), which is not
  defined on `LocalDiskDirTree`, `DirTree`, or anywhere else in the repo.
  Nearest equivalents are `add_file_by_fullpath` / `add_file_by_relpath`.
  This would raise `AttributeError` before the `full_filesystem_path` issue
  above is even reached.

- **`interactive_dir_sync.py:78` calls
  `dirtree.DirTree.factory_from_list_of_file_entries(...)` as if it were a
  classmethod/staticmethod on `DirTree`**, but in `dirtree.py:6` it's a
  plain module-level function (`def factory_from_list_of_file_entries(files,
  filesystem_dirpath):`), not a method on the class. This call would raise
  `AttributeError: type object 'DirTree' has no attribute
  'factory_from_list_of_file_entries'`.

  **Net effect:** as read, both "Copy" and "Remove" — the two actions the
  sync flow exists to perform — look like they'd crash immediately when
  invoked, before doing any real work. Worth an end-to-end run to confirm
  before relying on this flow, or treat it as needing repair.

- **`utils.py`'s `__validate_replica` calls `cursesswitch.print_string(...)`
  (`utils.py:33`) but the file never imports `cursesswitch`** (only
  imports `os`, `sys`, `clouddirtree`, `clouddirtreefactory`,
  `localdiskdirtree`). Would raise `NameError` the first time an invalid
  local replica path is given.

## High-confidence from reading (not grep-verified against a live run)

- **`localdiskdirtree.py:63-65`** — `_copy_local_file_to_tree_with_path`'s
  real `shutil.copy(src, dst)` is commented out and replaced with `pass`.
  Even if the `AttributeError`s above were fixed, no bytes would be copied
  yet — this looks like an intentional stub/WIP rather than an accidental
  regression (there's a commented-out line right there, not a deletion).

- **`treepicker/treepicker.py:21`** constructs
  `TreePickerModel(tree, header, max_nr_lines, min_nr_options=..., 
  max_nr_options=...)` positionally, but
  `TreePickerModel.__init__(self, tree, including_root=True, header="",
  min_nr_options=1, max_nr_options=None)` has `including_root` — not
  `header` — as the second positional parameter. So the `header` string
  gets bound to `including_root`, and `max_nr_lines` (an int/None) gets
  bound to `header`. Since `including_root` is only used truthily
  elsewhere, a non-empty header string would evaluate as truthy (no crash,
  wrong-ish behavior); an empty header (`""`, the default in most call
  sites) is falsy, which may coincidentally work. Worth fixing to use
  keyword args regardless.

- **`clouddirtreefactory.py:29`** — `factory_interactive` returns
  `CloudDirTree(path_in_cloud)`, but `path_in_cloud` is never assigned
  anywhere in the function (only the parameter `rootpath` is). This would
  raise `NameError` — the interactive cloud-tree factory path looks
  unfinished/broken as written.

- **`clouddirtree.py:120-124`** — `CloudDirTree._path_in_cloud` is declared
  `@staticmethod` but its body references `self.path_components(path)`.
  Calling it would raise `NameError: name 'self' is not defined`. (Note:
  nothing currently calls `_path_in_cloud` — it may be dead.)

- **`clouddirtreefactory.py:86`** — `outfile.write(item)` writes a Drive API
  result `dict` object directly to a file opened in text mode, not a
  string. This would raise `TypeError: write() argument must be str, not
  dict` — needs `json.dump`/`str(item)`/`repr(item)`. (`clouddirtree.py`'s
  cache reader, `_parseline`, does `eval(line)` on each line, implying the
  intended format is Python-repr text — so `outfile.write(repr(item))` or
  similar is probably the fix, matching what the reader expects.)

- **`optionpicker.py:26-28`** — `OptionPickerByNumbers.__init__` calls
  `super(OptionPicker, self).__init__(options)` (should be
  `super(OptionPickerByNumbers, self).__init__(options)`), and the class
  also uses Python 2's `raw_input()` (removed in Python 3). This class
  looks unused/dead: the app only ever constructs
  `OptionPickerByMenuTraverse` (`interactive_dir_sync.py`,
  `dirsync_main.py`, `clouddirtreefactory.py`).

- **`dirtree.py:170-173`** — the `if __name__ == '__main__':` block
  references an undefined variable `t` and calls `t.show()`. Dead/leftover
  debug code; only matters if someone runs `python dirtree.py` directly.

- **`main.py`'s `-m/--max-depth` argument** is parsed but, in the traced
  call chain (`main.py` → `dirsync_main.run`/`dirpick_main.run` →
  `utils.create_dirtree_from_arg` → `localdiskdirtree.factory`), `args.max_depth`
  is never actually passed through — `create_dirtree_from_arg` calls
  `localdiskdirtree.factory(rootpath)` with no `max_depth` kwarg, so the
  factory's `max_depth=None` default always applies regardless of what the
  user passes on the CLI.

- **`treepicker/treesearch.py:48-56`** (`__main__` block) calls
  `dirtree.DirTree.factory_from_filesystem(...)`, which does not exist
  anywhere in the codebase. Dead/stale profiling script, not on any real
  call path.

- **`treepicker/exampletree.py:6`** — `for i in range(6) + range(10, 15)`
  is Python 2 syntax (`range()` returned a list there); in Python 3
  `range` objects don't support `+`. This demo tree is used by the
  `__main__` blocks of `treepicker.py`, `treeprinter.py`, and (indirectly)
  `optionpicker.py` — none of them would run as standalone scripts under
  Python 3 as a result. Doesn't affect the real app, which never imports
  `exampletree`.

## Stale references (not bugs in code that runs, just dangling)

- `config.py`'s constants (`POSSIBLE_PARENT_DIRS`,
  `FILE_EXTENTION_FOR_REPLICA_CANDIDATE`,
  `MIN_NR_FILES_WITH_EXTENTION_FOR_REPLICA_CANDIDATE`) and
  `dirtree.py`'s `MUSIC_FILE_EXTENTIONS` are defined but never referenced
  by any other module in `dirdelta/` — scaffolding for an
  unfinished "auto-detect likely replica directories by music-file count"
  feature.
