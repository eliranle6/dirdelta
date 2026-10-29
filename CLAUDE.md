# dirdelta

A terminal TUI for diffing and syncing two "replicas" of a file tree — a local
filesystem path or a Google Drive ("cloud") tree — by **filename only** (no
content/hash comparison). For each file present in one replica but not the
other, the user can choose to copy it across or delete it.

This is the main repo (github.com/eliranle6/dirdelta). Its pickers and menus are `treepicker`, a C++ program
from its own repo (github.com/eliranle6/treepicker), vendored as a git submodule at
`lib/treepicker` (its own history/remote, pinned to a specific commit here) and
built with `make`; `dirdelta/picker.py` runs it as a subprocess (see
`docs/treepicker-integration.md`). The old Python picker library that was
the UI before is gone (removed 2026-10-24). On the original dev machine this directory sits
inside a local `dirstuff/` folder alongside a Python venv and an `unused/`
scratch dir, but neither is part of this repo, and nothing in the repo may
assume that layout (see Structure below). Dependencies go in a `.venv`
inside the repo (gitignored; see README.md), which the Makefile targets
pick up automatically, falling back to `python3` on `PATH`.

Deep dives live in `docs/`:
- `docs/architecture.md` — module-by-module breakdown and data flow (scan → diff → pick → copy/remove)
- `docs/known-issues.md` — real bugs and dead code found while reading the source, with file:line
- `docs/glossary.md` — project-specific terms (replica, dirtree, cloud path convention, etc.)
- `docs/improvement-ideas.md` — what's left to do, not implemented: a backlog to pick from
- `lib/treepicker/CLAUDE.md` and `lib/treepicker/docs/improvement-ideas.md` — treepicker's own (read before changing picker behavior; picker changes are made in treepicker, not here)
- `docs/treepicker-integration.md` — how dirdelta runs the C++ `treepicker` for its pickers and menus (it replaced the Python picker), and what's left

Read the relevant doc before making changes in that area rather than
re-deriving it from scratch.

## Running it

See README.md for running from source (`make` to build treepicker, then
`python -m dirdelta` from the repo root), `make install` (into a venv) and
`make deploy` (a pipx-managed `dirdelta` in `~/.local/bin`); both also
install treepicker next to the environment's python. To sync, run it
without paths and choose the replicas from the menu, which remembers the
recent pairs and the favorites (so the `bin/example-*.sh` launchers with
paths in them were removed, 2026-10-27). From the repo, with its `.venv`
Python (falling back to `python3`): `bin/sync.sh` runs it that way, and
`bin/pick.sh [PATH]` runs picker mode on PATH (default: the current dir;
other arguments, e.g. `-x PROGRAM`, go to dirdelta too).

`main.py` picks mode by arg count: no path → a menu that chooses the two
replicas (`choose_replicas.py`: each slot browsed from `/` or Drive, or a
favorite or recent pair from `~/.config/dirdelta/replicas.json`, kept by
`replicas.py`), then sync mode; one path → picker mode (`dirpick_main.py`,
which prints the picked path, or `execvp`s the `-x` program on it), two
paths → sync mode (`dirsync_main.py`), which records the pair in that file;
`--sort INBOX ROOT` (or "Sort an inbox" in the no-path menu) → sorting an
inbox into a sorted tree (`inbox.py`, with Claude's descriptions and
recommendations from `ai.py`, through the Claude Agent SDK), kept in that
file's `sorts`.
dirdelta doesn't use curses itself: each pick is a `treepicker` run, which
has the terminal while it's open, and
what's to be read in between (warnings, "Nothing to copy", an action's
report) is on a full screen that waits for Enter (`messages.show()`,
`messages.progress_screen()`); plain progress lines ("Scanning...") just
print. Copy, Remove and Rename (chosen after picking files in a
direction's picker, which then comes back) run on the progress screen,
stoppable with Ctrl-C, and ask for confirmation first (Remove twice). A "cloud" path is any path whose
first component is literally `cloud` (see `paths.py`).

Env vars that change execution mode:
- `DIRDELTA_PICKER`, `DIRDELTA_DIRDIFF` — the treepicker and dirdiff programs
  to run (default, `programs.find()`: the first of the program next to the
  running python, in `lib/treepicker/build/`, on `PATH`)
- `DIRDELTA_AI_DESCRIBE_MODEL`, `DIRDELTA_AI_RECOMMEND_MODEL` — the models `ai.py`
  asks for descriptions (default `claude-haiku-5-5`) and recommendations
  (default `claude-sonnet-5-5`); `DIRDELTA_AI_MODEL` sets both
- `DRYRUN=0` — actually change files: Copy, Remove and Rename (`dryrun.py`, used by
  `localdiskdirtree.py`). Every screen shows the mode: "DRY RUN" in green, or
  "LIVE" in red.
  Any other value, or unset, means a dry run: nothing on disk changes (no
  copies, no new dirs, no deletes) and neither do the in-memory trees, and
  the progress lines say so.

Developer tasks all live in the Makefile (`make` lists them): `test`,
`clean`, `install`, `deploy`, `undeploy`. Keep new ones there too rather
than adding shell scripts. `make clean`
removes `__pycache__`/`*.pyc`/`*.egg-info`/`build/`/pbr's `AUTHORS` and
`ChangeLog` in this repo and the submodule, skipping `.venv`. It does not
touch `~/.cache/dirman/files.txt` (the real Drive cache, refreshed a folder at a
time: a replica's, at the start or from the main menu, or one in it, with the file
picker's `r`; with a `files.txt.stale` next to it, listing the folders where a
change dirdelta made to Drive was cut off before it was added to the cache),
`~/.config/dirdelta/replicas.json` (the history, favorites and sorts),
`~/.cache/dirdelta/ai.json` (what Claude said of files),
`~/.cache/dirdelta/hashes.json` (local files' hashes) or `secrets/`.

## Structure

```
dirstuff/                    the original dev machine's local folder, not a git repo
├── dirstuff-venv/            that machine's older venv (activate it, or make .venv)
├── unused/                   dead/unimported scripts kept for reference only
│   ├── scandrive.py           (an old scan of all of Drive, like the one dirdelta had until 2026-10-29)
│   └── parse-drive-files.py
└── dirdelta/                 THIS repo
    ├── bin/                   sync.sh, pick.sh: sync and picker mode from source
    ├── Makefile               dev tasks: build, test, clean, install, deploy, undeploy
    ├── dirdelta/              the application (see docs/architecture.md)
    ├── secrets/               Google OAuth secrets — never print/edit
    ├── tests/                 unittest suite + tests/fixtures/{alpha,bravo}
    └── lib/
        └── treepicker/        git submodule — the C++ tree library, treepicker and
                               dirdiff (make build → lib/treepicker/build/)
```

(`treepicker` is a C++ learning project of the same author. Its own working copy
is at `/home/eliran/code/treepicker`, where changes are committed; `lib/treepicker`
is a separate clone of it, updated by fetching from that copy and
fast-forwarding, then committing the new pin here. Don't push either repo.)

## Secrets

`credentials.json` and `token.json` live in `secrets/` (gitignored), loaded
via a path computed in `driveapi.py` from `__file__` rather than
the process's CWD. These are Google Drive OAuth client secret / access-token
files. Never read their contents into a response, log them, or
commit-adjacent-copy them anywhere.

## Tests

```bash
make test             # or make test ARGS=-v, or any other unittest flags via ARGS
```

It runs `unittest discover` on `tests/` with `PYTHONPATH=.` (imports look
like `from dirdelta import dirtree`), then treepicker's own C++ tests with
`make -C lib/treepicker test` (which needs Google Test, `libgtest-dev`).
`make clean` cleans the submodule too.

Patch targets must use the same module names the code imports
(`'dirdelta.dryrun.DRYRUN'`): a bare `import dryrun` would load a second
copy of the module that the app never sees. To run one
module:

```bash
PYTHONPATH=.:tests .venv/bin/python3 -m unittest test_interactive_dir_sync -v
```

Every module has a test file (403 tests, all passing as of 2026-10-29) except
the thin wiring in `main.py`/`dirsync_main.py`, covered only by running the
app. Shared fakes:
- `tests/helpers.py`: `scripted_option_picker` / `scripted_tree_picker` /
  `scripted_files_picker` / `scripted_dir_picker` patch `dirdelta.picker`'s functions to return
  scripted answers, so no test runs treepicker, plus `make_files` for
  temp dir fixtures. `tests/test_picker.py` tests `picker.py` itself against
  a fake treepicker script. App tests build their own `tempfile.mkdtemp()` trees
  rather than using `tests/fixtures/`, so they never depend on (or modify)
  the repo.
- The real hash cache isn't written: `tests/helpers.py` points
  `hashcache.CACHE_FILE` at a temp file when it's imported, and every test
  module that hashes files imports it.
- Claude is never asked in the tests: `test_ai` patches `ai._run_query` or the
  SDK's `query`, and `test_inbox` patches `ai._run_query`; `ai.CACHE_FILE` goes
  to a temp file. A manual run with a scratch `HOME` can't reach Claude Code's
  login (it's under the real `HOME`); `CLAUDE_CONFIG_DIR=~/.claude` gets it,
  but then Claude Code writes a `.claude.json` into `~/.claude` (2026-10-29).
- The real `~/.config/dirdelta/replicas.json` is never written: tests patch
  `dirdelta.replicas.REPLICAS_FILE` to a temp file (`test_replicas`), or
  `replicas.load`/`replicas.save`. A manual run that shouldn't touch it can set
  `HOME` to a scratch dir (but that hides the real Drive cache too).
- Drive is never contacted: `test_clouddirtree` writes a JSON-lines cache to
  a temp file, `test_driveapi` mocks `Credentials`/`build`, and the rest patch
  `driveapi.service()` with a fake (e.g. `test_clouddirtree`'s uploads, downloads
  and trashing).

`tests/fixtures/{alpha,bravo}` are sample trees for manual runs (see
README.md), which says how to sync a temp copy of them. As of 2026-10-23
picker mode, `-x`, and a sync with a real Copy (`DRYRUN=0`) have been run
end to end in a real terminal with treepicker. The cloud flow has not, since it needs
Drive credentials.

Notes for whoever changes things next:
- To check something in a real terminal without a person at the keyboard,
  run `python -m dirdelta` in a detached tmux session (`tmux new-session -d
  -x 90 -y 20 ...`), send keys with `tmux send-keys`, and read the screen
  with `tmux capture-pane -p`. treepicker draws on `/dev/tty`, so the
  terminal must be a real (pseudo-)terminal.
- Running the app caught most of known-issues.md #17-22, and treepicker's
  randomized tests caught several of its bugs: good reasons to test before
  trusting a path through the code.

## Conventions observed in the code

- Python, plus treepicker (C++, built by `make`). Modules inside `dirdelta/` import each other
  as `from dirdelta import x` (never bare `import x`, which only worked in
  Python 2 or when `dirdelta/` itself happened to be on `sys.path`), so the
  same code runs from source via `python -m dirdelta` and installed via
  `make install` (`pip install .`, a pbr-based `setup.py`).
  pbr derives versions from git tags, so `setup.cfg`'s `version` must stay
  ahead of the latest tag (dirdelta 1.4.0 vs. v1.3.2). The root
  `requirements.txt` lists the third-party dependencies.
- Diffing is filename/path-only (see `DirTree.get_unknown_entries_in_given_dirtree`
  in `dirdelta/dirtree.py`) — no hashing, no size/mtime comparison.
- The local-disk scanner shells out to the real `find` binary (one run per
  scan, in `localdiskdirtree.py`) rather than using `os.walk`.
- Cloud state is cached to disk (`~/.cache/dirman/files.txt`) rather than
  queried live on every scan; refreshing a folder re-reads it from the Drive
  API, one request at a time: never in parallel (the user doesn't want
  Google to see unusual use of the account).
