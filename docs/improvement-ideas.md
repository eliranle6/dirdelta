# Refactoring / readability ideas

Not implemented — a list of proposed simplifications, gathered by reading
the source (see `architecture.md`, `treepicker-internals.md`,
`known-issues.md`). Ordered roughly by impact. None of these are required;
treat as a backlog to pick from.

## Application layer (`dirdelta/`)

1. **Split `dirtree.py`** into `entries.py` (`DirEntry`/`FileEntry`, plain
   data holders) and `dirtree.py` (the `DirTree` class plus the orphaned
   module-level `factory_from_list_of_file_entries` function, which reads
   like a method but isn't one — make it `DirTree.from_file_entries()` so
   `interactive_dir_sync.py`'s existing call to it as a classmethod would
   even be correct; see `known-issues.md`).

2. **Replace the `create_node`-override trick** in `DirTree.__init__`
   (stash the real bound method, then monkey-patch `self.create_node` to
   always raise) with plain composition — hold a `treelib.Tree` as an
   attribute instead of subclassing it. Right now "you can't call
   `create_node` directly" is only discoverable via a runtime
   `NotImplementedError`; composition makes it structurally impossible
   instead of an emergent surprise.

3. **Make `CloudDirTree` and `LocalDiskDirTree` symmetric.** Local has a
   clean `factory()` doing the work outside `__init__`; Cloud does
   cache-parsing and a full tree-walk *inside* `__init__`. Give
   `CloudDirTree` the same `factory()` shape so both replica types are
   constructed the same way.

4. **Pull Drive-cache parsing out of `CloudDirTree`.**
   `_parsefile`/`_parseline`/`_dirdict_to_dirtree` turn a metadata cache
   file into id→children/id→metadata maps — a generic concern unrelated to
   being a `DirTree`. Move it to its own module (e.g. `drivecache.py`)
   that hands `CloudDirTree` an already-built index.

5. **Move cloud-path detection out of `CloudDirTree`.** `utils.py` reaches
   into `clouddirtree.CloudDirTree.path_components` just to check "does
   this path start with `cloud/`" — a generic path utility living inside a
   tree class. Give it its own home (e.g. `paths.py`) so `utils.py` doesn't
   need to import the cloud module just to route between cloud/local.

6. **Collapse `findcmdwrapper.find_files`/`find_dirs`.** They're ~90%
   identical (base command, `-maxdepth`, hidden-file exclusion), differing
   only in `-type f` vs `-type d` and the regex clause. One parameterized
   `_find(rootpath, type_flag, ...)` removes the duplication. (Also
   noticed while testing: `find_files`'s `max_depth` defaults to `None`,
   but `find_dirs`'s `max_depth` is a required positional arg with no
   default — worth aligning the two signatures while touching this.)

7. ~~Consolidate the near-duplicate Drive-scanning implementations~~ —
   resolved by relocation rather than a merge: the only live implementation
   is now the embedded one in `clouddirtreefactory.py`'s
   `_scan_drive_files_list`. The two dead duplicates (`dirdelta/scandrive.py`
   and `src/drivesync/scandrive.py`) were both unimported; moved to
   `unused/scandrive.py` (and `src/drivesync/` deleted) rather than kept
   alongside the real package.

8. **Extract a small "labeled-action menu" helper.** Both
   `dirsync_main._sync` and
   `InteractiveDirSync._chooseWhatToDoWithFiles`/`sync` hand-roll "build
   option strings → pick one → if/elif string-compare to dispatch"
   independently. A tiny `run_menu([(label, handler), ...])` helper would
   remove both duplicated dispatch chains.

9. **Break up `InteractiveDirSync.sync()`.** It mixes diff recomputation,
   UI invocation, menu dispatch, and control flow in one loop, with
   `self._selected` as implicit shared mutable state read by
   `_copy`/`_remove` several calls later. Extracting a `_pick_round()`
   step, and passing the selected files explicitly into
   `_copy(selected)`/`_remove(selected)` instead of through
   `self._selected`, would make the data flow traceable without jumping
   between methods.

## Picker library (`lib/treepicker/`)

10. **Turn `TreePicker.pick()`'s mode if/elif chain into a dispatch
    table** (`{mode: handler}` returning the next state), so each mode's
    logic lives in its own small method instead of one long loop body
    juggling `print_tree_once`/state-hash diffing inline.

11. **Give the `matching`/`original_matching` node attributes an explicit
    home.** They're bolted onto plain `treelib.Node` objects ad hoc in
    `treesearch.py` and read via defensive `hasattr()` checks scattered
    across `treeprinter.py`, `treenavigator.py`, and `treepickermodel.py`.
    Setting a default at node-creation time (or a tiny wrapper) would
    remove the repeated `hasattr` guards.

## Cleanup (low-risk, high readability payoff)

12. **Delete dead code** rather than refactor it:
    - `OptionPickerByNumbers` (Python 2 syntax, broken `super()` call,
      unused — `OptionPickerByMenuTraverse` is what's actually used)
    - the stray `print('toggling')`/`print('end toggle')` debug lines in
      `treepickermodel.toggle()` (these bypass the curses printer and
      would garble the screen if ever hit while curses is active)
    - `dirtree.py`'s broken `__main__` block (references undefined `t`)
    - the unused `config.py` / `MUSIC_FILE_EXTENTIONS` scaffolding for the
      never-built "auto-detect replica" feature
    - `treesearch.py`'s and `exampletree.py`'s broken `__main__`/demo code
      (see `known-issues.md`)
