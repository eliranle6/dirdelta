# Refactoring / readability ideas

Not implemented — a list of proposed simplifications, gathered by reading
the source (see `architecture.md`,
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

8. ~~Extract a small "labeled-action menu" helper~~ — done (2026-10-23):
   `dirdelta/menu.py`'s `run_menu([(label, handler), ...])` now drives both
   `dirsync_main._sync` and `InteractiveDirSync.sync`.

9. **Break up `InteractiveDirSync.sync()`.** It mixes diff recomputation,
   UI invocation, menu dispatch, and control flow in one loop, with
   `self._selected` as implicit shared mutable state read by
   `_copy`/`_remove` several calls later. Extracting a `_pick_round()`
   step, and passing the selected files explicitly into
   `_copy(selected)`/`_remove(selected)` instead of through
   `self._selected`, would make the data flow traceable without jumping
   between methods.
   (Since 2026-10-24 there's no action menu in the loop anymore, but
   `self._selected` is still the hand-off.)

## Picker library (`lib/treepicker/`)

The library was removed on 2026-10-24 (#15); kept for the record.

10. **Turn `TreePicker.pick()`'s mode if/elif chain into a dispatch
    table** (`{mode: handler}` returning the next state), so each mode's
    logic lives in its own small method instead of one long loop body
    juggling `print_tree_once`/state-hash diffing inline.

11. **Give the `matching`/`original_matching` node attributes an explicit
    home.** Partly done (2026-10-23): every reader now goes through
    `treesearch.is_visible(node)` / `treesearch.is_self_match(node)` instead
    of its own `hasattr()` check. The attributes are still set ad hoc on
    plain `treelib.Node` objects, though; a cleaner next step would be for
    `TreeSearch` to return sets of visible/self-matching ids (keeping the
    narrowing optimization by remembering the previous set), which would
    also let `TreePickerModel` stop copying the tree for the navigator.

## Cleanup (low-risk, high readability payoff)

12. ~~Delete dead code~~ — done 2026-10-23: `OptionPickerByNumbers`,
    broken `__main__` blocks, `config.py`, `MUSIC_FILE_EXTENTIONS`, unused
    `treeprinter` constants, and the stray debug `print` in
    `TreePickerModel.update_search_pattern()`.

13. ~~Simplify `cursesswitch._CursesWindowPrinter`'s redraw tracking~~ —
    done 2026-10-23: it now draws at a running cursor and refreshes once
    per picker frame (see architecture.md).

14. ~~List menu options in the order given~~ — done 2026-10-23, by moving
    menus to `dirpicker --list` (known-issues.md #23).

15. ~~Drop lib/treepicker~~ — done 2026-10-24: its last use,
    `cursesswitch.print_line`, is `dirdelta/messages.py` now.

16. **Move the diff into C++.** Sync mode builds both trees in Python (~3s
    each for 119k files) before showing anything; dirpicker builds a tree of
    the same size in ~0.4s. Scanning both replicas and diffing them in a C++
    helper would cut most of sync's startup time.

## Simplifications found in the 2026-10-24 review

Concepts and UI first, then code. cpptree's own (dirpicker's) are in
`lib/cpptree/docs/improvement-ideas.md`.

17. **A dry run shouldn't pretend in the trees.** Copy's and Remove's dry
    runs update the in-memory trees as if they had acted, so right after a
    dry run sync says "Nothing to synchronize" although nothing changed on
    disk. If a dry run left the trees alone, it would offer the same files
    again (the honest result), and the "as if" code paths in
    `localdiskdirtree.py` (adding nodes in a dry copy, dropping them in a dry
    remove, then rescanning) would go.

18. **One `find` per scan.** `LocalDiskDirTree.update_from_filesystem()`
    runs find twice, once for files and once for dirs
    (`findcmdwrapper.find_files`/`find_dirs`), which doubles the scan time
    and makes both report the same unreadable paths (hence the de-duplicating
    of `scan_errors`). One `find ROOT -printf '%y %p\0'`, as dirpicker
    does, gives both, `\0`-separated so odd file names are safe too.

19. **Drop the unused scan options.** `localdiskdirtree.factory()` and
    `findcmdwrapper` take `file_extentions`, `dirs_only` and
    `include_hidden`, but the only caller (`utils.create_dirtree_from_arg`)
    passes just `max_depth`. Without them `findcmdwrapper` is a few lines,
    small enough to fold into `localdiskdirtree.py`.

20. **Remove the "View files in A, not B" menu items?** Since the menu has
    "Copy files from A to B" and "Remove files from A", whose pickers show
    exactly that diff (and can be left with `q` without doing anything),
    the two View items repeat them. Dropping them makes the main menu 5
    items: the 4 actions and Quit. (Kept for now: View can't change
    anything, which may be worth something on its own.)

21. **One way to show messages.** Messages reach the user two ways: in the
    next picker's header (`messages.take_recent()`), and on the progress
    screen. If scanning (and the find warnings) also ran on the progress
    screen, the header mechanism, with its line cap and "(N earlier lines)",
    could go. The cost: an extra Enter after scanning.

22. **Back to the main menu after an action?** After a copy or remove, the
    files left are offered again (`sync()` loops). Going back to the main
    menu instead would make the loop a single pass (pick, confirm, act), at
    the cost of re-choosing the action to continue.

23. **Thin wrappers.** `dirsync_main._view_diff()` and
    `_sync_from_src_to_dst()` only construct an `InteractiveDirSync` and call
    one method; `InteractiveDirSync.view_diff(src, dst)` takes src and dst
    although the object holds them. And `menu.run_menu()` has one caller.

24. **DirTree ids without the leading `/`.** DirTree's ids are `/sub/x`
    (the root's is `/`), dirpicker's are `sub/x` (the root's is `.`), so
    `picker.py` converts both ways (`_id_to_path`, `_path_to_id`). With
    relative ids the conversion would go, but every `relpath` user would
    change, so it's only worth it alongside other DirTree work (#1, #16).

25. **Count files, not nodes, in the picker's status line.** "picked: 7" for
    5 tracks counts the album and the artist dirs too, while the
    confirmation says "Copy 5 files". dirpicker would need to know which
    nodes are files (e.g. `d `/`f ` prefixes on stdin, like find's `%y`).

