# dirdelta

A terminal TUI for diffing and syncing two "replicas" of a file tree — a local
filesystem path or a Google Drive ("cloud") tree — by **filename only** (no
content/hash comparison). For each file present in one replica but not the
other, the user can choose to copy it across or delete it.

This is the main repo. Its pickers and menus are `dirpicker`, a C++ program
from cpptree (github.com/levioctl/cpptree), vendored as a git submodule at
`lib/cpptree` (its own history/remote, pinned to a specific commit here) and
built with `make`; `dirdelta/picker.py` runs it as a subprocess (see
`docs/dirpicker-integration.md`). The Python `treepicker` library that was
the UI before is gone (removed 2026-10-24; it was the `lib/treepicker`
submodule, github.com/levioctl/treepicker). On the original dev machine this directory sits
inside a local `dirstuff/` folder alongside a Python venv and an `unused/`
scratch dir, but neither is part of this repo, and nothing in the repo may
assume that layout (see Structure below). Dependencies go in a `.venv`
inside the repo (gitignored; see README.md), which the Makefile targets and
`bin/` scripts pick up automatically, falling back to `python3` on `PATH`.

Deep dives live in `docs/`:
- `docs/architecture.md` — module-by-module breakdown and data flow (scan → diff → pick → copy/remove)
- `docs/known-issues.md` — real bugs and dead code found while reading the source, with file:line
- `docs/glossary.md` — project-specific terms (replica, dirtree, cloud path convention, etc.)
- `docs/improvement-ideas.md` — proposed refactors/simplifications, not implemented; a backlog to pick from
- `docs/dirpicker-integration.md` — how dirdelta runs cpptree's C++ `dirpicker` for its pickers and menus (it replaced the Python picker), and what's left

Read the relevant doc before making changes in that area rather than
re-deriving it from scratch.

## Running it

See README.md for running from source (`make` to build dirpicker, then
`python -m dirdelta` from the repo root), `make install` (into a venv) and
`make deploy` (a pipx-managed `dirdelta` in `~/.local/bin`); both also
install dirpicker next to the environment's python. Entry points are shell
scripts in `bin/`, each putting the repo root on `PYTHONPATH` and running
`python -m dirdelta` with the repo's `.venv` Python (falling back to
`python3`):

- `./bin/dirsync-fs.sh` — sync temp copies of `tests/fixtures/alpha` and `.../bravo`
- `./bin/dirsync-cloud.sh` — sync a local WSL path against `cloud/mein` (Drive)
- `./bin/dirpick-localdisk.sh` — browse/pick a file under wherever it's run from
- `./bin/dirpick-cloud.sh` — browse/pick a file under `cloud/mein`

`main.py` picks mode by arg count: one path → picker mode (`dirpick_main.py`,
which prints the picked path, or `execvp`s the `-x` program on it), two
paths → sync mode (`dirsync_main.py`). dirdelta doesn't use curses itself:
each pick is a `dirpicker` run, which has the terminal while it's open, and
messages in between are plain lines. A "cloud" path is any path whose
first component is literally `cloud` (see `utils.py`).

Env vars that change execution mode:
- `DIRDELTA_PICKER` — the dirpicker program to run (default: the first of
  `dirpicker` next to the running python, `lib/cpptree/build/dirpicker`,
  `dirpicker` on `PATH`)
- `DRYRUN=0` — actually copy bytes in "Copy" (`localdiskdirtree.py`); any
  other value or unset means dry-run, where the tree/dirs are updated but
  `shutil.copy` is skipped. "Remove" is not gated by this — it always deletes.

Developer tasks all live in the Makefile (`make` lists them): `test`,
`clean`, `install`, `deploy`, `undeploy`. Keep new ones there too rather
than adding shell scripts; `bin/` is only for app launchers. `make clean`
removes `__pycache__`/`*.pyc`/`*.egg-info`/`build/`/pbr's `AUTHORS` and
`ChangeLog` in this repo and the submodule, skipping `.venv`. It does not
touch `~/.cache/dirman/files.txt` (the real Drive-scan cache) or `secrets/`.

## Structure

```
dirstuff/                    the original dev machine's local folder, not a git repo
├── dirstuff-venv/            that machine's older venv (activate it, or make .venv)
├── unused/                   dead/unimported scripts kept for reference only
│   ├── scandrive.py           (near-dup of clouddirtreefactory.py's scan logic)
│   └── parse-drive-files.py
└── dirdelta/                 THIS repo
    ├── bin/                   entry-point scripts
    ├── Makefile               dev tasks: build, test, clean, install, deploy, undeploy
    ├── dirdelta/              the application (see docs/architecture.md)
    ├── secrets/               Google OAuth secrets — never print/edit
    ├── tests/                 unittest suite + tests/fixtures/{alpha,bravo}
    └── lib/
        └── cpptree/           git submodule — the C++ tree library and dirpicker
                               (make build → lib/cpptree/build/dirpicker)
```

(`cpptree` is a C++ learning project of the same author. Its own working copy
is at `/home/eliran/code/cpptree`; `lib/cpptree` is a separate clone of it,
so changes made there need committing in `lib/cpptree` (and pushing) before
the submodule pin here is updated.)

## Secrets

`credentials.json` and `token.json` live in `secrets/` (gitignored), loaded
via a path computed in `clouddirtreefactory.py` from `__file__` rather than
the process's CWD. These are Google Drive OAuth client secret / access-token
files. Never read their contents into a response, log them, or
commit-adjacent-copy them anywhere.

## Tests

```bash
make test             # or make test ARGS=-v, or any other unittest flags via ARGS
```

It runs `unittest discover` on `tests/` with `PYTHONPATH=.` (imports look
like `from dirdelta import dirtree`), then dirpicker's own C++ tests with
`make -C lib/cpptree test` (which needs Google Test, `libgtest-dev`).
`make clean` cleans the submodule too.

Patch targets must use the same module names the code imports
(`'dirdelta.localdiskdirtree.DRYRUN'`): a bare `import localdiskdirtree`
would load a second copy of the module that the app never sees. To run one
module:

```bash
PYTHONPATH=.:tests .venv/bin/python3 -m unittest test_interactive_dir_sync -v
```

Every module has a test file (60 tests, all passing as of 2026-10-24) except
the thin wiring in `main.py`/`dirsync_main.py`, covered only by running the
app. Shared fakes:
- `tests/helpers.py`: `scripted_option_picker` / `scripted_tree_picker` /
  `scripted_dir_picker` patch `dirdelta.picker`'s functions to return
  scripted answers, so no test runs dirpicker, plus `make_files` for
  temp dir fixtures. `tests/test_picker.py` tests `picker.py` itself against
  a fake dirpicker script. App tests build their own `tempfile.mkdtemp()` trees
  rather than using `tests/fixtures/`, so they never depend on (or modify)
  the repo.
- Drive is never contacted: `test_clouddirtree` writes a JSON-lines cache to
  a temp file, and `test_clouddirtreefactory` mocks `Credentials`/`build`.

`tests/fixtures/{alpha,bravo}` are sample trees for manual runs (see
README.md); `bin/dirsync-fs.sh` syncs a temp copy of them. As of 2026-10-23
picker mode, `-x`, and a sync with a real Copy (`DRYRUN=0`) have been run
end to end in a real terminal with dirpicker. The cloud flow has not, since it needs
Drive credentials.

Notes for whoever changes things next:
- To check something in a real terminal without a person at the keyboard,
  run `python -m dirdelta` in a detached tmux session (`tmux new-session -d
  -x 90 -y 20 ...`), send keys with `tmux send-keys`, and read the screen
  with `tmux capture-pane -p`. dirpicker draws on `/dev/tty`, so the
  terminal must be a real (pseudo-)terminal.
- Running the app caught most of known-issues.md #17-22, and dirpicker's
  randomized tests caught several of its bugs: good reasons to test before
  trusting a path through the code.

## Conventions observed in the code

- Python, plus dirpicker (C++, built by `make`). Modules inside `dirdelta/` import each other
  as `from dirdelta import x` (never bare `import x`, which only worked in
  Python 2 or when `dirdelta/` itself happened to be on `sys.path`), so the
  same code runs from source via `python -m dirdelta` and installed via
  `make install` (`pip install .`, a pbr-based `setup.py`).
  pbr derives versions from git tags, so `setup.cfg`'s `version` must stay
  ahead of the latest tag (dirdelta 1.4.0 vs. v1.3.2). The root
  `requirements.txt` lists the third-party dependencies.
- Diffing is filename/path-only (see `DirTree.get_unknown_entries_in_given_dirtree`
  in `dirdelta/dirtree.py`) — no hashing, no size/mtime comparison.
- The local-disk scanner shells out to the real `find` binary
  (`dirdelta/findcmdwrapper.py`) rather than using `os.walk`.
- Cloud state is cached to disk (`~/.cache/dirman/files.txt`) rather than
  queried live on every scan; refreshing it re-hits the Drive API.
