# Usage

## Synchronizing two directories
```
dirdelta directory_a_path directory_b_path
```

## Exploring a directory
```
dirdelta directory_path
```

# Development

## Setup

dirdelta is Python 3, plus its picker, which is C++ and built with `make`: you can run it straight
from the source tree, or install it (see below). From the repo root:

```bash
git clone --recursive https://github.com/eliranle6/dirdelta && cd dirdelta
git submodule update --init       # fetches lib/treepicker (treepicker), if cloned without --recursive
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
make                              # builds treepicker: needs g++ and libncurses-dev
```

dirdelta's pickers and menus are `treepicker`, and it diffs two local dirs with `dirdiff`: C++
programs from [treepicker](https://github.com/eliranle6/treepicker) (see `docs/treepicker-integration.md`), a
submodule at `lib/treepicker`. `make` builds them into `lib/treepicker/build/`, where dirdelta finds them
when run from the source tree. `$DIRDELTA_PICKER` and `$DIRDELTA_DIRDIFF` override which programs it
runs.

Development tasks are Makefile targets (`make help` lists them). They use `.venv` automatically
when it exists, and otherwise whichever `python3` is on your `PATH`, so an already activated venv
works too. `make PYTHON=/path/to/python3 ...` overrides that.

## Running from source

Run the `dirdelta` package as a module from the repo root (after `make`, which builds treepicker):

```bash
.venv/bin/python3 -m dirdelta --help
```

Work on copies of the sample trees in `tests/fixtures`, since Remove deletes real files:

```bash
rm -rf /tmp/dd && cp -r tests/fixtures /tmp/dd
```

### Choosing what to sync (no paths)

```bash
.venv/bin/python3 -m dirdelta      # or bin/sync.sh
```

A menu: "Replica A" and "Replica B", each `<none: press Enter to choose one>` until chosen (a local
dir, browsed from `/`, or a Google Drive folder), then your favorite pairs and the recent ones.
Choosing a pair, or both replicas, goes on to the sync menu below, which also has "Add to favorites"
(or "Remove from favorites"). Every sync's pair is kept in `~/.config/dirdelta/replicas.json` (the
latest first, each pair once, either way around), which you can also edit by hand.

### Picker mode (one path)

`bin/pick.sh [PATH]` runs it from the repo on PATH (default: the current dir), or:

```bash
.venv/bin/python3 -m dirdelta /tmp/dd/alpha            # prints the picked path after exiting
.venv/bin/python3 -m dirdelta -x ls /tmp/dd/alpha      # runs `ls <picked path>` instead
.venv/bin/python3 -m dirdelta -m 1 /tmp/dd/alpha       # scan only one level deep (default 20)
```

Move with `h`/`j`/`k`/`l` or the arrows, `Ctrl-D`/`Ctrl-U` to page, `/` to search (`Enter` keeps
the filter, `Esc` drops it), `Enter` to pick the selected entry, `q` to quit without picking. A local
dir is scanned by `treepicker` itself, so even big trees open fast.

### Sync mode (two paths)

```bash
.venv/bin/python3 -m dirdelta /tmp/dd/alpha /tmp/dd/bravo             # a dry run: changes nothing
DRYRUN=0 .venv/bin/python3 -m dirdelta /tmp/dd/alpha /tmp/dd/bravo    # Copy, Remove and Rename really do
```

The menu offers, for each direction, "Files in A, not in B" (with how many there are). Choose one,
pick files with `Space` (on a directory it picks everything under it), and press `Enter`. A
directory is marked picked (`X`, red) when everything under it is, and partly picked (`-`, magenta)
when only some of it is. Beside the tree, a column shows, for the selected file, where B has files
of the same name (found while you look, with how far it's got), the likeliest first: the same
size, the same date taken (photos), the file's neighbours there too; one that's surely the file,
moved, says so (`p` hides the column). `Enter` then asks what to do with the picked files, with
"Nothing" selected first: copy them to B, remove them from A, or, for the ones whose match in B is
surely them, rename: move B's match to the file's path, or the file to the match's (greyed out
when it can't be done). A confirmation follows, with No selected (a removal asks a second time,
"Are you sure?", also with No selected): No takes you back to the picker, with the same files
picked; Yes goes ahead. Its progress fills the screen under a top line saying what's being done;
`Ctrl-C` stops it (a file cut off in the middle of its copy is deleted), and when it's done or
stopped, `Enter` goes back to the picker, where you were, without the files done; `q` goes back
to the main menu. With a cloud replica, the menu also has "Refresh cloud/X from Google
Drive", which reads that folder anew from Drive (as the refresh offered at the start does), for when
it changed outside dirdelta, and in the file picker `r` reads just the selected folder anew. Unless
`DRYRUN=0` is set, both are dry
runs: they change nothing on disk (not even the dirs copied files would go into), and say what they
would have done. Every screen says which it is, at the start of its bottom line (the progress
screen: its top line): "DRY RUN" in green, or "LIVE" in red.

The fixtures are a small music library. Both have 106 files in common; only `alpha` has 364 (e.g.
`podcasts/`, `music/Nina Simone/` and `first/infirst/ininfirst/huh/99.mp3`), and only `bravo` has 31
(e.g. `audiobooks/Dune/`, `music/The Beatles/` and `third/anotherinthird/7.mp3`), so copying or
removing them fills the progress screen. Some dirs are taller than a screen, to show the picker's
pagination (`... N more` lines): `alpha/music/` has 36 artists, `alpha/podcasts/` 150 episodes, and
`alpha/music/Bach/The Well-Tempered Clavier/` 48 tracks. Sync copies of them (see above), since a
live Remove deletes real files.

## Tests

```bash
make test             # or make test ARGS=-v
```

It also runs treepicker's own tests (in `lib/treepicker`), which need Google Test (`libgtest-dev`).

## Cleaning

```bash
make clean
```

Removes `__pycache__`, `*.pyc`, `build/`, `*.egg-info`, `.eggs` and pbr's generated
`AUTHORS`/`ChangeLog`, and treepicker's build (`lib/treepicker/build`). It leaves `.venv`, `secrets/` and the Drive cache
(`~/.cache/dirman/files.txt`) alone; delete `.venv` yourself to start over.

## Deploying to your system

To get a `dirdelta` command for everyday use, without activating any venv:

```bash
make deploy           # needs pipx (on Debian/Ubuntu: sudo apt install pipx)
```

This uses [pipx](https://pipx.pypa.io/) to install dirdelta and the picker library into a private venv
and link the command into `~/.local/bin`, which must be on your `PATH` (`pipx ensurepath` adds it).
Rerun `make deploy` after pulling changes, since it installs a copy rather than linking to the
source tree. `make undeploy` removes it.

For cloud paths, the deployed copy can't find the repo's `secrets/` folder, so point
`DIRDELTA_SECRETS_DIR` at the folder holding `credentials.json`/`token.json`.

`make deploy` builds treepicker too, and puts it in dirdelta's pipx venv (next to its python, where
dirdelta looks first), so it needs g++ and libncurses-dev, and `make undeploy` removes it with the
venv.

## Installing into a venv

```bash
make install          # pip install . (and treepicker next to that python)
```

Installs dirdelta into the same environment the other targets use (`.venv` if it exists, else the
`python3` on your `PATH`), and treepicker next to that environment's python. Useful for trying the packaged `dirdelta` command without deploying it.
