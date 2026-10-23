# Usage

## Synchronizing two directories
```
dirdelta directory_a_path directory_b_path
```

## Exploring a directory
```
dirdelta directory_path
```

# Running from source

Run `dirdelta/main.py` with the picker library on `PYTHONPATH`, from the repo root. The dependencies
(`treelib`, `termcolor`, the Google API client) come from the venv one level up:

```bash
git submodule update --init          # once, to fetch lib/treepicker
PY=../dirstuff-venv/bin/python3
export PYTHONPATH=lib/treepicker
```

Work on copies of the sample trees in `tests/fixtures`, since Remove deletes real files:

```bash
rm -rf /tmp/dd && cp -r tests/fixtures /tmp/dd
```

## Picker mode (one path)

```bash
$PY dirdelta/main.py /tmp/dd/alpha                 # prints the picked path after exiting
$PY dirdelta/main.py -x ls /tmp/dd/alpha           # runs `ls <picked path>` instead
$PY dirdelta/main.py -m 1 /tmp/dd/alpha            # scan only one level deep (default 20)
```

Move with `h`/`j`/`k`/`l`, `g`/`G` for first/last, `/` to search, `Enter` to pick the selected
entry, `q` to quit without picking.

## Sync mode (two paths)

```bash
$PY dirdelta/main.py /tmp/dd/alpha /tmp/dd/bravo             # Copy is a dry run
DRYRUN=0 $PY dirdelta/main.py /tmp/dd/alpha /tmp/dd/bravo    # Copy really copies
```

Choose "Remove/Copy files from ... to ..." in the menu, select files with `Space` (on a directory it
selects everything under it), press `Enter`, then choose Copy or Remove. Menu entries are listed
alphabetically. Copy copies the selected files from the entry's source ("from") directory into its
destination ("to"); Remove deletes them from the source. Remove is not affected by `DRYRUN`.

For bravo vs. alpha, `alpha` is missing `third/anotherinthird/7.mp3` and `bravo` is missing
`first/infirst/ininfirst/huh/99.mp3`.

## Other modes

`MODE=direct` prints to plain stdout instead of using curses (handy with a debugger), and
`MODE=static` skips the curses setup in `main.py` entirely.

## Tests

```bash
./run-tests.sh        # or ./run-tests.sh -v
```
