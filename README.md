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
git submodule update --init       # fetches lib/cpptree (dirpicker)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
make                              # builds dirpicker: needs g++ and libncurses-dev
```

dirdelta's pickers and menus are `dirpicker`, a C++ program from
[cpptree](https://github.com/levioctl/cpptree) (see `docs/dirpicker-integration.md`), a submodule at
`lib/cpptree`; `make` builds it into `lib/cpptree/build/dirpicker`, where dirdelta finds it when run
from the source tree. `$DIRDELTA_PICKER` overrides which program it runs.

Development tasks are Makefile targets (`make help` lists them). They and the launcher scripts in
`bin/` use `.venv` automatically when it exists, and otherwise whichever `python3` is on your `PATH`,
so an already activated venv works too. `make PYTHON=/path/to/python3 ...` overrides that.

## Running from source

Run the `dirdelta` package as a module from the repo root (after `make`, which builds dirpicker):

```bash
.venv/bin/python3 -m dirdelta --help
```

Work on copies of the sample trees in `tests/fixtures`, since Remove deletes real files:

```bash
rm -rf /tmp/dd && cp -r tests/fixtures /tmp/dd
```

### Picker mode (one path)

```bash
.venv/bin/python3 -m dirdelta /tmp/dd/alpha            # prints the picked path after exiting
.venv/bin/python3 -m dirdelta -x ls /tmp/dd/alpha      # runs `ls <picked path>` instead
.venv/bin/python3 -m dirdelta -m 1 /tmp/dd/alpha       # scan only one level deep (default 20)
```

Move with `h`/`j`/`k`/`l` or the arrows, `Ctrl-D`/`Ctrl-U` to page, `/` to search (`Enter` keeps
the filter, `Esc` drops it), `Enter` to pick the selected entry, `q` to quit without picking. A local
dir is scanned by `dirpicker` itself, so even big trees open fast.

### Sync mode (two paths)

```bash
.venv/bin/python3 -m dirdelta /tmp/dd/alpha /tmp/dd/bravo             # a dry run: changes nothing
DRYRUN=0 .venv/bin/python3 -m dirdelta /tmp/dd/alpha /tmp/dd/bravo    # Copy and Remove really do
```

The menu offers, for each direction, "Copy files from A to B" (the files in A that aren't in B, copied
into B) and "Remove files from A" (the files in A that aren't in B, deleted from A). Choose one, pick
files with `Space` (on a directory it picks everything under it), and press `Enter`. A confirmation
follows, with No selected: No takes you back to the picker, with the same files picked; Yes goes
ahead. Its progress fills the screen under a top line saying what's being done; `Ctrl-C` stops it
(a file cut off in the middle of its copy is deleted), and when it's done or stopped, `Enter` goes
on. Then the files that are left are offered again, until you quit the picker (`q`). Unless `DRYRUN=0` is set, both are dry
runs: they change nothing on disk (not even the dirs copied files would go into), and say what they
would have done.

The fixtures are a small music library. Both have 44 files in common; only `alpha` has 42 (e.g.
`podcasts/`, `music/Nina Simone/` and `first/infirst/ininfirst/huh/99.mp3`), and only `bravo` has 31
(e.g. `audiobooks/Dune/`, `music/The Beatles/` and `third/anotherinthird/7.mp3`), so copying or
removing them fills the progress screen. `./bin/example-sync-local.sh` runs this sync on a fresh temp
copy of the fixtures, so `DRYRUN=0 ./bin/example-sync-local.sh` is safe too.

## Tests

```bash
make test             # or make test ARGS=-v
```

It also runs dirpicker's own tests (in `lib/cpptree`), which need Google Test (`libgtest-dev`).

## Cleaning

```bash
make clean
```

Removes `__pycache__`, `*.pyc`, `build/`, `*.egg-info`, `.eggs` and pbr's generated
`AUTHORS`/`ChangeLog`, and dirpicker's build (`lib/cpptree/build`). It leaves `.venv`, `secrets/` and the Drive cache
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

`make deploy` builds dirpicker too, and puts it in dirdelta's pipx venv (next to its python, where
dirdelta looks first), so it needs g++ and libncurses-dev, and `make undeploy` removes it with the
venv.

## Installing into a venv

```bash
make install          # pip install . (and dirpicker next to that python)
```

Installs dirdelta into the same environment the other targets use (`.venv` if it exists, else the
`python3` on your `PATH`), and dirpicker next to that environment's python. Useful for trying the packaged `dirdelta` command without deploying it.
