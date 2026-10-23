# dirdelta

A terminal TUI for diffing and syncing two "replicas" of a file tree — a local
filesystem path or a Google Drive ("cloud") tree — by **filename only** (no
content/hash comparison). For each file present in one replica but not the
other, the user can choose to copy it across or delete it.

This is the main repo. `treepicker` (the curses tree-picker TUI library this
app is built on, reusable on its own outside this project) is vendored inside
it as a git submodule at `lib/treepicker` — its own history/remote, pinned to
a specific commit here. On the original dev machine this directory sits
inside a local `dirstuff/` folder alongside a Python venv and an `unused/`
scratch dir, but neither is part of this repo, and nothing in the repo may
assume that layout (see Structure below). Dependencies go in a `.venv`
inside the repo (gitignored; see README.md), which `bin/` and
`run-tests.sh` pick up automatically, falling back to `python3` on `PATH`.

Deep dives live in `docs/`:
- `docs/architecture.md` — module-by-module breakdown and data flow (scan → diff → pick → copy/remove)
- `docs/treepicker-internals.md` — the curses tree UI's rendering/pagination/search/input internals (read before touching picker UI behavior)
- `docs/known-issues.md` — real bugs and dead code found while reading the source, with file:line
- `docs/glossary.md` — project-specific terms (replica, dirtree, cloud path convention, etc.)
- `docs/improvement-ideas.md` — proposed refactors/simplifications, not implemented; a backlog to pick from

Read the relevant doc before making changes in that area rather than
re-deriving it from scratch.

## Running it

See README.md for running from source (`python -m dirdelta`, from the
repo root with `PYTHONPATH=lib/treepicker`), `make install` (into a venv) and
`make deploy` (a pipx-managed `dirdelta` in `~/.local/bin`). Entry
points are shell scripts in `bin/`, each putting the repo root and
`lib/treepicker` on `PYTHONPATH` and running `python -m dirdelta` with the
repo's `.venv` Python (falling back to `python3`):

- `./bin/dirsync-fs.sh` — sync temp copies of `tests/fixtures/alpha` and `.../bravo`
- `./bin/dirsync-cloud.sh` — sync a local WSL path against `cloud/mein` (Drive)
- `./bin/dirpick-localdisk.sh` — browse/pick a file under wherever it's run from
- `./bin/dirpick-cloud.sh` — browse/pick a file under `cloud/mein`

`main.py` picks mode by arg count: one path → picker mode (`dirpick_main.py`,
which prints the picked path, or `execvp`s the `-x` program on it, after
curses has exited), two paths → sync mode (`dirsync_main.py`). A "cloud" path is any path whose
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
dirstuff/                    the original dev machine's local folder, not a git repo
├── dirstuff-venv/            that machine's older venv (activate it, or make .venv)
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

```bash
./run-tests.sh        # or ./run-tests.sh -v, or with any other unittest flags
```

It runs `unittest discover` once per test dir, so the two dirs' helper
modules (`helpers.py`, `scripted_keys.py`) don't collide. `tests/` runs with
`PYTHONPATH=.:lib/treepicker` and imports its targets as
`from dirdelta import dirtree`, and `lib/treepicker/tests/` runs with
`PYTHONPATH=lib/treepicker` (`from treepicker import treeprinter`).
`cursesswitch` is a flat top-level module in `lib/treepicker/`. Patch targets
must use the same module names the code imports (`'dirdelta.localdiskdirtree.DRYRUN'`):
a bare `import localdiskdirtree` would load a second copy of the module that
the app never sees. To run one module:

```bash
PYTHONPATH=.:lib/treepicker:tests .venv/bin/python3 -m unittest test_interactive_dir_sync -v
PYTHONPATH=lib/treepicker:lib/treepicker/tests .venv/bin/python3 -m unittest test_treepicker -v
```

Every module has a test file (78 tests, all passing as of 2026-10-23)
except the thin wiring in `main.py`/`dirsync_main.py`, covered only by
running the app, and the tiny `keybind.py`/`getcher.py`, exercised through
`test_treepicker`. Shared fakes:
- `tests/helpers.py`: `scripted_option_picker` / `scripted_tree_picker`
  patch the curses pickers to return scripted answers, plus `make_files` for
  temp dir fixtures. App tests build their own `tempfile.mkdtemp()` trees
  rather than using `tests/fixtures/`, so they never depend on (or modify)
  the repo.
- `lib/treepicker/tests/scripted_keys.py`: `scripted_keys` feeds
  `TreePicker`/`LineScanner` a key sequence by patching
  `getcher.GetchUnix`, and `silent_screen` swaps the `cursesswitch` printer
  for a mock.
- Drive is never contacted: `test_clouddirtree` writes a JSON-lines cache to
  a temp file, and `test_clouddirtreefactory` mocks `Credentials`/`build`.

`tests/fixtures/{alpha,bravo}` are sample trees for manual runs (see
README.md); `bin/dirsync-fs.sh` syncs a temp copy of them. As of 2026-10-23
picker mode, `-x`, `-m`, and a sync with a real Copy (`DRYRUN=0`) have been
run end to end in a real terminal. The cloud flow has not, since it needs
Drive credentials.

Notes for whoever changes things next:
- The unit tests cover only small pieces of the picker. Before refactoring
  `treeprinter`/`treesearch`/`treepickermodel`/`treenavigator`, snapshot the
  old package and diff rendered frames (`TreePrinter._tree_lines` plus the
  selected id) over many seeded random navigate/pick/search sequences, old
  vs. new. That's how the 2026-10-23 simplifications and fixes were checked.
- To check something in a real terminal without a person at the keyboard,
  run `python -m dirdelta` (or an installed `dirdelta`) under `pty.fork()` (set a window size with
  `TIOCSWINSZ`), write keys to the pty, and read what's printed after
  curses exits.
- Writing `test_treenavigator.py` caught a real bug in
  `explore_deepest_child()` (it compared a variable to itself, so it always
  stopped after one level), and running the app caught most of
  known-issues.md #17-22. Both are good reasons to test before trusting a
  path through the code.

## Conventions observed in the code

- Pure Python, no build step. Modules inside `dirdelta/` import each other
  as `from dirdelta import x` (never bare `import x`, which only worked in
  Python 2 or when `dirdelta/` itself happened to be on `sys.path`), so the
  same code runs from source via `python -m dirdelta` and installed via
  `make install` (`pip install ./lib/treepicker .`, pbr-based `setup.py`s).
  pbr derives versions from git tags, so `setup.cfg`'s `version` must stay
  ahead of the latest tag (dirdelta 1.4.0 vs. v1.3.2, treepicker 1.1.0 vs.
  v1.0.1). The root `requirements.txt` lists the third-party dependencies;
  the picker library comes from the submodule, not PyPI.
- Diffing is filename/path-only (see `DirTree.get_unknown_entries_in_given_dirtree`
  in `dirdelta/dirtree.py`) — no hashing, no size/mtime comparison.
- The local-disk scanner shells out to the real `find` binary
  (`dirdelta/findcmdwrapper.py`) rather than using `os.walk`.
- Cloud state is cached to disk (`~/.cache/dirman/files.txt`) rather than
  queried live on every scan; refreshing it re-hits the Drive API.
