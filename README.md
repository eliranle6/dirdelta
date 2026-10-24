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
.venv/bin/python3 -m dirdelta /tmp/dd/alpha /tmp/dd/bravo             # Copy is a dry run
DRYRUN=0 .venv/bin/python3 -m dirdelta /tmp/dd/alpha /tmp/dd/bravo    # Copy really copies
```

Choose "Remove/Copy files from ... to ..." in the menu, select files with `Space` (on a directory it
selects everything under it), press `Enter`, then choose Copy or Remove. Copy copies the selected files from the entry's source ("from") directory into its
destination ("to"); Remove deletes them from the source. Copy's dry run writes nothing (not even
the dirs files would go into) and says what it would have copied; Remove is not affected by
`DRYRUN`.

For bravo vs. alpha, `alpha` is missing `third/anotherinthird/7.mp3` and `bravo` is missing
`first/infirst/ininfirst/huh/99.mp3`. `./bin/dirsync-fs.sh` runs this sync on a fresh temp copy of
the fixtures.

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
