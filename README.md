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

dirdelta is plain Python 3 with no build step: you can run it straight from the source tree, or
install it (see below). From the repo root:

```bash
git submodule update --init                 # fetches the picker library into lib/treepicker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The scripts in `bin/` and `run-tests.sh` use `.venv` automatically when it exists, and otherwise
whichever `python3` is on your `PATH`, so an already activated venv works too.

## Running from source

Run the `dirdelta` package as a module from the repo root, with the picker library on `PYTHONPATH`:

```bash
export PYTHONPATH=lib/treepicker
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

Move with `h`/`j`/`k`/`l`, `g`/`G` for first/last, `/` to search, `Enter` to pick the selected
entry, `q` to quit without picking.

### Sync mode (two paths)

```bash
.venv/bin/python3 -m dirdelta /tmp/dd/alpha /tmp/dd/bravo             # Copy is a dry run
DRYRUN=0 .venv/bin/python3 -m dirdelta /tmp/dd/alpha /tmp/dd/bravo    # Copy really copies
```

Choose "Remove/Copy files from ... to ..." in the menu, select files with `Space` (on a directory it
selects everything under it), press `Enter`, then choose Copy or Remove. Menu entries are listed
alphabetically. Copy copies the selected files from the entry's source ("from") directory into its
destination ("to"); Remove deletes them from the source. Remove is not affected by `DRYRUN`.

For bravo vs. alpha, `alpha` is missing `third/anotherinthird/7.mp3` and `bravo` is missing
`first/infirst/ininfirst/huh/99.mp3`. `./bin/dirsync-fs.sh` runs this sync on a fresh temp copy of
the fixtures.

### Other modes

`MODE=direct` prints to plain stdout instead of using curses (handy with a debugger), and
`MODE=static` skips the curses setup in `main.py` entirely.

## Tests

```bash
./run-tests.sh        # or ./run-tests.sh -v
```

## Cleaning

```bash
./clean.sh
```

Removes `__pycache__`, `*.pyc`, `build/`, `*.egg-info` and pbr's generated `AUTHORS`/`ChangeLog`, both
here and in `lib/treepicker`. It leaves `.venv`, `secrets/` and the Drive cache
(`~/.cache/dirman/files.txt`) alone; delete `.venv` yourself to start over.

## Installing

```bash
make install          # pip install ./lib/treepicker .
```

This installs the picker library and dirdelta, with their dependencies, into whichever environment's
`pip` comes first on your `PATH`, so activate a venv first. That gives you the `dirdelta` command used
under Usage above. An installed copy can't find the repo's `secrets/` folder, so for cloud paths point
`DIRDELTA_SECRETS_DIR` at the folder holding `credentials.json`/`token.json`.
