# dirdelta

A terminal TUI for diffing and syncing two "replicas" of a file tree — a local
filesystem path or a Google Drive ("cloud") tree — by **filename only** (no
content/hash comparison). For each file present in one replica but not the
other, the user can choose to copy it across or delete it.

This is the main repo. `treepicker` (the curses tree-picker TUI library this
app is built on, reusable on its own outside this project) is vendored inside
it as a git submodule at `lib/treepicker` — its own history/remote, pinned to
a specific commit here. This directory happens to sit inside a local
`dirstuff/` folder alongside a Python venv and an `unused/` scratch dir, but
neither of those is part of this repo (see Structure below).

Deep dives live in `docs/`:
- `docs/architecture.md` — module-by-module breakdown and data flow (scan → diff → pick → copy/remove)
- `docs/treepicker-internals.md` — the curses tree UI's rendering/pagination/search/input internals (read before touching picker UI behavior)
- `docs/known-issues.md` — real bugs and dead code found while reading the source, with file:line
- `docs/glossary.md` — project-specific terms (replica, dirtree, cloud path convention, etc.)
- `docs/improvement-ideas.md` — proposed refactors/simplifications, not implemented; a backlog to pick from

Read the relevant doc before making changes in that area rather than
re-deriving it from scratch.

## Running it

Entry points are shell scripts in `bin/`, each setting `PYTHONPATH` and
invoking `dirdelta/main.py`:

- `./bin/dirsync-fs.sh` — sync two local dirs (`tests/fixtures/alpha` vs `.../bravo`, sample/test dirs)
- `./bin/dirsync-cloud.sh` — sync a local WSL path against `cloud/mein` (Drive)
- `./bin/dirpick-localdisk.sh` — browse/pick a file under wherever it's run from
- `./bin/dirpick-cloud.sh` — browse/pick a file under `cloud/mein`

`main.py` picks mode by arg count: one path → picker mode (`dirpick_main.py`),
two paths → sync mode (`dirsync_main.py`). A "cloud" path is any path whose
first component is literally `cloud` (see `utils.py`).

Env vars that change execution mode:
- `MODE=static` — skip the `cursesswitch.wrapper()` curses init in `main.py`
- `MODE=direct` — skip curses in `cursesswitch.py`'s `wrapper()` (falls back to plain stdout `_ConsolePrinter`)
- `DRYRUN=0` — actually copy bytes in "Copy" (`localdiskdirtree.py`); any
  other value or unset means dry-run, where the tree/dirs are updated but
  `shutil.copy` is skipped. "Remove" is not gated by this — it always deletes.

`./clean.sh` removes `__pycache__`/`*.pyc`/`*.egg-info`/`build/` cruft from
this repo and the `lib/treepicker` submodule. It does not touch
`~/.cache/dirman/files.txt` (the real Drive-scan cache) or `secrets/`/any
gitignored files.

## Structure

```
dirstuff/                    a local folder, not itself a git repo
├── dirstuff-venv/            Python venv, not part of this repo
├── unused/                   dead/unimported scripts kept for reference only
│   ├── scandrive.py           (near-dup of clouddirtreefactory.py's scan logic)
│   └── parse-drive-files.py
└── dirdelta/                 THIS repo
    ├── bin/                   entry-point scripts
    ├── clean.sh, run-tests.sh dev-tooling scripts
    ├── dirdelta/              the application (see docs/architecture.md)
    ├── secrets/               Google OAuth secrets — never print/edit
    ├── tests/                 unittest suite + tests/fixtures/{alpha,bravo}
    └── lib/
        └── treepicker/        git submodule — curses tree-picker TUI library
            ├── cursesswitch.py  curses on/off + colored-print shim, bundled
            │                    in as a flat module (no longer its own repo)
            └── tests/           unittest suite
```

(`cpptree`, a personal, unrelated C++/autotools learning project, used to
live alongside this tree but has since moved to `/home/eliran/code/cpptree`
— no longer part of it at all.)

## Secrets

`credentials.json` and `token.json` live in `secrets/` (gitignored), loaded
via a path computed in `clouddirtreefactory.py` from `__file__` rather than
the process's CWD. These are Google Drive OAuth client secret / access-token
files. Never read their contents into a response, log them, or
commit-adjacent-copy them anywhere.

## Tests

Started conservatively with `unittest`, on small self-contained modules
picked because they need no curses/network mocking (`dirtree.py`,
`findcmdwrapper.py`), or are pure tree logic in the picker library that
never touches curses directly: `pagination.py` (window math),
`treeprinter.py` (`calculate_lines_to_print()` builds the line list in
memory; only `print_tree()` writes to the screen), `treepickermodel.py`
(pick/unpick, subtree toggle), `treesearch.py` (match propagation, the
narrowing-reuse optimization), `treenavigator.py` (cursor movement), and
`treeops.py` (the BFS depth-capping helper `treeprinter` relies on).
Test files live in a `tests/` dir sibling to the package (`tests/`,
`lib/treepicker/tests/`), separate from the production code — this is a
change from the original bare-colocation layout; `dirdelta`'s tests still
bare-import their target module (`import dirtree`) rather than using
`treepicker`'s package-style imports.

`tests/fixtures/{alpha,bravo}` are small sample directory trees used by
`bin/dirsync-fs.sh` for manual/exploratory testing — not consumed by any
unittest. **Unverified**: `bin/dirsync-fs.sh` and the other entry-point
scripts have not been run end-to-end since the dirsync→dirdelta rewrite;
don't assume they work. Only the unittest-covered modules (`dirtree.py`,
`findcmdwrapper.py`, `localdiskdirtree.py`, `menu.py`, and treepicker's
`pagination.py`, `treeprinter.py`, `treepickermodel.py`, `treesearch.py`,
`treenavigator.py`, `treeops.py`) are known-good.

Run everything at once:

```bash
./run-tests.sh
```

(Just chains the commands below with `set -e`, since the modules'
mismatched import conventions — `dirdelta`'s bare sibling imports vs.
`treepicker`'s package-style imports — mean plain `python -m unittest
discover` can't satisfy both at once with one `PYTHONPATH`.)

Or run one module's tests at a time with the venv's Python:

```bash
# dirtree.py — core diff algorithm (DirTree, DirEntry/FileEntry)
PYTHONPATH=dirdelta:tests ../dirstuff-venv/bin/python3 -m unittest test_dirtree -v

# findcmdwrapper.py — the `find`-shelling-out layer (uses real temp dirs, no mocking needed)
PYTHONPATH=dirdelta:tests ../dirstuff-venv/bin/python3 -m unittest test_findcmdwrapper -v

# localdiskdirtree.py — copy_inner_entries_from_dirtree's tree/directory
# bookkeeping (uses real tempfile.mkdtemp() dirs; needs cursesswitch on the
# path too, since the module imports it for progress printing)
PYTHONPATH=dirdelta:tests:lib/treepicker ../dirstuff-venv/bin/python3 -m unittest test_localdiskdirtree -v

# menu.py — run_menu's (label, handler) dispatch, with the option picker mocked
PYTHONPATH=dirdelta:tests:lib/treepicker ../dirstuff-venv/bin/python3 -m unittest test_menu -v

# treepicker/pagination.py — pure pagination-window math
PYTHONPATH=lib/treepicker:lib/treepicker/tests ../dirstuff-venv/bin/python3 -m unittest test_pagination -v

# treepicker/treeprinter.py — rendering logic (markers, colors, pagination
# collapse), via calculate_lines_to_print() rather than print_tree()
PYTHONPATH=lib/treepicker:lib/treepicker/tests ../dirstuff-venv/bin/python3 -m unittest test_treeprinter -v

# treepicker/treepickermodel.py — pick/unpick a node's whole subtree,
# get_picked_nodes()'s min/max-bound gating and single-option mode
PYTHONPATH=lib/treepicker:lib/treepicker/tests ../dirstuff-venv/bin/python3 -m unittest test_treepickermodel -v

# treepicker/treesearch.py — matching propagates up to ancestors,
# original_matching stays node-specific, narrowing reuse doesn't go stale
PYTHONPATH=lib/treepicker:lib/treepicker/tests ../dirstuff-venv/bin/python3 -m unittest test_treesearch -v

# treepicker/treenavigator.py — explore/go_up, sibling-bound clamping,
# explore_deepest_child()
PYTHONPATH=lib/treepicker:lib/treepicker/tests ../dirstuff-venv/bin/python3 -m unittest test_treenavigator -v

# treepicker/treeops.py — BFS depth-capping used by treeprinter's
# auto-scoping (get_max_possible_depth)
PYTHONPATH=lib/treepicker:lib/treepicker/tests ../dirstuff-venv/bin/python3 -m unittest test_treeops -v
```

(`cursesswitch` is bundled inside the treepicker submodule as a flat
`lib/treepicker/cursesswitch.py`, so `PYTHONPATH=lib/treepicker` resolves
both `import treepicker` and `import cursesswitch` — even though none of
the tested treepicker code paths touch curses. Test files live outside
the `treepicker` package proper, so they're imported by their bare module
names (`test_pagination`, `test_treeprinter`, etc.), not a dotted
`treepicker.test_*`.)

All 30 tests pass as of 2026-10-23.

Notes for whoever adds the next batch:
- Writing `test_treenavigator.py` caught a real bug in
  `explore_deepest_child()`: it compared a local variable to itself every
  loop iteration (never refreshed after `self.explore()`), so the
  "did we move?" check was always true and it stopped after one level
  regardless of tree depth. Fixed — worth remembering as a cautionary
  example of why these modules were worth testing in the first place.
- New filesystem-dependent tests (`test_findcmdwrapper.py`) build their
  own `tempfile.mkdtemp()` fixture rather than depending on
  `tests/fixtures/` — hermetic, no dependency on repo working-tree state.
- Nothing touching Google Drive has tests yet. `clouddirtree.py` /
  `clouddirtreefactory.py` have known bugs (see `known-issues.md`) that
  would surface immediately; mock the `googleapiclient`/`google.oauth2`
  calls with `unittest.mock` rather than hitting the real API, and
  consider fixing the `NameError`/`TypeError` bugs first so there's
  something correct to test.
- `localdiskdirtree.py`'s `full_filesystem_path()`/`_add_file_by_path`
  crashes (known-issues.md #1-#2) are now fixed and covered by
  `test_localdiskdirtree.py`. `interactive_dir_sync.py` is a natural next
  candidate: its `AttributeError` (known-issues.md #3) and `TypeError`
  (#16) crashes are fixed, so `_remove` should now be testable against
  `tempfile.mkdtemp()` dirs (mind that it really unlinks). `_copy` still
  crashes in `dirtree.factory_from_list_of_file_entries` (#17).
- The unit tests only cover small pieces of the picker. Before refactoring
  `treeprinter`/`treesearch`/`treepickermodel`, it's worth snapshotting the
  old package and diffing rendered frames (`TreePrinter._tree_lines` plus
  the selected id) over many seeded random navigate/pick/search sequences,
  old vs. new. That's how the 2026-10-23 simplifications were checked.
  Leave `next_leaf`/`prev_leaf` out of such sequences until known-issues.md
  #18 is fixed, or most runs crash early.

## Conventions observed in the code

- Pure Python, no build step, no `requirements.txt` lockfile management beyond
  the plain `requirements.txt` files per package (google API libs mainly).
  There's a `dirstuff-venv/` one level up from the repo root — activate that
  rather than assuming system Python has the deps.
- Diffing is filename/path-only (see `DirTree.get_unknown_entries_in_given_dirtree`
  in `dirdelta/dirtree.py`) — no hashing, no size/mtime comparison.
- The local-disk scanner shells out to the real `find` binary
  (`dirdelta/findcmdwrapper.py`) rather than using `os.walk`.
- Cloud state is cached to disk (`~/.cache/dirman/files.txt`) rather than
  queried live on every scan; refreshing it re-hits the Drive API.
