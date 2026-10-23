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

dirdelta is plain Python 3 with no build step: you run it straight from the source tree. From the repo
root:

```bash
git submodule update --init                 # fetches the picker library into lib/treepicker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The scripts in `bin/` and `run-tests.sh` use `.venv` automatically when it exists, and otherwise
whichever `python3` is on your `PATH`, so an already activated venv works too.

## Running from source

Run `dirdelta/main.py` with the picker library on `PYTHONPATH`:

```bash
export PYTHONPATH=lib/treepicker
```

Work on copies of the sample trees in `tests/fixtures`, since Remove deletes real files:

```bash
rm -rf /tmp/dd && cp -r tests/fixtures /tmp/dd
```

### Picker mode (one path)

```bash
.venv/bin/python3 dirdelta/main.py /tmp/dd/alpha            # prints the picked path after exiting
.venv/bin/python3 dirdelta/main.py -x ls /tmp/dd/alpha      # runs `ls <picked path>` instead
.venv/bin/python3 dirdelta/main.py -m 1 /tmp/dd/alpha       # scan only one level deep (default 20)
```

Move with `h`/`j`/`k`/`l`, `g`/`G` for first/last, `/` to search, `Enter` to pick the selected
entry, `q` to quit without picking.

### Sync mode (two paths)

```bash
.venv/bin/python3 dirdelta/main.py /tmp/dd/alpha /tmp/dd/bravo             # Copy is a dry run
DRYRUN=0 .venv/bin/python3 dirdelta/main.py /tmp/dd/alpha /tmp/dd/bravo    # Copy really copies
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

## Installing as a package

Not working yet. `setup.py` (pbr) and `make install` would install a `dirdelta` command, but the
modules import each other by bare name (`import dirsync_main`, `import cursesswitch`), which only
resolves when running from source as above, so the installed command fails at startup.
