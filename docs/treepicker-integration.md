# dirdelta's picker: treepicker

The old Python picker library (a submodule, removed since) was too slow for big trees: in a
119k file tree (/usr/share) one search keystroke took over 70s, and building
dirdelta's own Python tree takes ~3s. `treepicker`, from the C++ project at
/home/eliran/code/treepicker (github.com/eliranle6/treepicker), shows the same
kind of tree picker: a search keystroke takes milliseconds, and it opens
/usr/share in ~0.5s. So dirdelta runs `treepicker` as a subprocess for every
pick and every menu (`dirdelta/picker.py`), and no longer uses curses itself.

Done as of 2026-10-23 (see the plan below); what's left is at the end.

## How dirdelta talks to treepicker

Like fzf: dirdelta starts `treepicker`, which draws on the terminal itself
(/dev/tty) and prints what was picked on stdout.

- Picking from a tree dirdelta already has (a cloud tree):
  `treepicker -0 --typed [--header TEXT] [--root NAME] -`, with the tree's
  paths on stdin, each ending with `\0`, relative to the root (`sub/x`, the
  same as dirdelta's ids), after their type (`f `, `d `). Each folder before
  what's in it, in the order to show.
- Picking files of a diff (sync mode): the same with `-m`, but only the
  files are sent (`f sub/x`), as dirdiff lists them: treepicker adds their
  dirs, so dirdelta builds no tree of them. `-m` picks several (Space picks
  a node and everything under it, Enter finishes).
- Picking under a local dir (picker mode): `treepicker -0 --max-depth N DIR`.
  treepicker scans it with `find` itself, so dirdelta builds no Python tree;
  if find couldn't read everything, treepicker warns in its header.
- Picking a replica dir (the menu of a run without paths):
  `treepicker -0 --dirs-only --lazy /` for a local one: only dirs, each read
  when it's shown (so `/` opens at once; a search finds only what was read).
  A Drive one is the cloud tree's picker with `--dirs-only`.
- Showing a picker again with the user's picks: `--picked FILE`, FILE
  holding the paths treepicker printed, and `--select PATH` to start on the
  node it was on.
- A key that ends the file picker for dirdelta to act on the selected node
  (`r`: read the selected folder anew from Drive): `--expect r`. Then the
  output starts with the key pressed (or an empty item for Enter) and, after
  a key, the selected node's path, then the picks so far, so dirdelta runs it
  again with `--picked` and `--select`.
- Text beside the file picker for the selected node (where the other replica
  has files of its name): `--preview FILE`, FILE holding `PATH<tab>LINE<tab>LINE...\0`
  per file (a tab or newline in a line is sent as '?'). treepicker shows it in
  a column on the right (2/5 of the width, on a screen 60 columns wide or more),
  which `p` hides or shows.
- Menus: `treepicker -0 --list [--header TEXT] -`, with the labels on stdin
  (`--list` keeps them flat, since labels contain '/'). With `shown_as`,
  `pick_option` adds `--updates FD`, a pipe that a thread writes `LABEL<tab>TEXT\0`
  to whenever an option's text changes (e.g. the main menu's file counts coming
  in); treepicker still prints the label when it's picked. `LABEL<tab>TEXT<tab>disabled\0`
  (a `picker.Disabled` in `shown_as`) greys the option out, and Enter does
  nothing on it, until an update without it: the main menu's options with
  nothing to do.
- Labels: every run gets the dry run's (`--label DRY RUN --label-color green`,
  or LIVE in red), and Copy's and Remove's file picker and confirmation a
  second one after it (COPY in blue, REMOVE in magenta), each `--label` with
  its `--label-color` after it.
- Output: the picked paths (or labels), each ending with `\0`, the root as
  `.`. Exit code 0: something was picked; 1: the user quit; anything else:
  an error (its message is on stderr).

treepicker is the `lib/treepicker` submodule, built by `make` (make build) into
`lib/treepicker/build/treepicker`; `make install` and `make deploy` put a copy
next to the environment's python. dirdelta runs `$DIRDELTA_PICKER` if set,
else the first of: treepicker next to the running python, that build,
treepicker on `PATH`.

## Plan and status

treepicker, each a commit:
1. [done] Read the tree from stdin (`-`, `-0`)
2. [done] Pick with Enter, print the result, exit codes
3. [done] Multi-select (`-m`)
4. [done] Esc / Ctrl-[ clears the search filter, also after Enter kept it
5. [done] `--header TEXT`: lines shown above the tree
6. [done] `--root NAME`: the root's name (stdin trees' root is otherwise ".")
7. [done] `--list`: stdin lines are a flat list of options, the first one selected
8. [done] `--max-depth N` for scanning a dir

dirdelta, each a commit:
9. [done] `dirdelta/picker.py`: runs treepicker (tree → stdin, stdout → picked
   entries), with tests using a fake treepicker script
10. [done] Use it for the sync picker (`interactive_dir_sync.py`), menus
   (`menu.py`, since folded into `dirsync_main.py`; `clouddirtreefactory.py`) and picker mode (`dirpick_main.py`)
11. [done] Stop using curses: `main.py` no longer wraps the app in
   `cursesswitch.wrapper()`, so messages are plain prints
12. [done] Update README.md, CLAUDE.md and the other docs

## Differences from the Python picker

- Keys: h/j/k/l or arrows, / to search (Enter keeps the filter, Esc drops
  it), Space picks (with -m), Enter picks/finishes, q or Ctrl-C quits.
  g/G go to the first/last sibling, Ctrl-/ searches only when Enter is
  pressed, and f switches between the matches-only tree and the whole tree
  with matches highlighted. ? shows the keys (the stats line says so).
  Not there: the leaf jumps (Ctrl-J/K) and u/d (use Ctrl-U/Ctrl-D or
  PageUp/PageDown); not needed.
- Search is smartcase (case-insensitive unless the keyword has uppercase)
  and matches names, like the Python picker's.
- With -m, Enter with nothing picked does nothing, like the Python picker.

## What's left

- The cloud flow hasn't been run end to end with treepicker (it needs Drive
  credentials); its pieces are covered by the unit tests.
