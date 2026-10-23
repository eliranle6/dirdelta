# Replacing the Python picker with cpptree's dirpicker

The Python `treepicker` (lib/treepicker) is too slow for big trees: in a
119k file tree (/usr/share) one search keystroke took over 70s, and building
dirdelta's own Python tree takes ~3s. `dirpicker`, from the C++ project at
/home/eliran/code/cpptree (github.com/levioctl/cpptree), shows the same
kind of tree picker: a search keystroke takes milliseconds, and it opens
/usr/share in ~0.5s. So dirdelta runs `dirpicker` as a subprocess for every
pick and every menu, and no longer uses curses itself.

This doc is the plan and its status, kept current so work can resume if
interrupted.

## How dirdelta talks to dirpicker

Like fzf: dirdelta starts `dirpicker`, which draws on the terminal itself
(/dev/tty) and prints what was picked on stdout.

- Picking from a tree dirdelta already has (sync mode's diff tree, a cloud
  tree): `dirpicker -0 [-m] [--header TEXT] [--root NAME] -`, with the tree's
  paths on stdin, each ending with `\0`, relative to the root (`sub/x`, not
  dirdelta's `/sub/x` ids). Each folder before what's in it, in the order to
  show. `-m` picks several (Space picks a node and everything under it,
  Enter finishes).
- Picking under a local dir (picker mode): `dirpicker -0 --max-depth N DIR`.
  dirpicker scans it with `find` itself, so dirdelta builds no Python tree.
- Menus: `dirpicker -0 --list [--header TEXT] -`, with the labels on stdin
  (`--list` keeps them flat, since labels contain '/').
- Output: the picked paths (or labels), each ending with `\0`, the root as
  `.`. Exit code 0: something was picked; 1: the user quit; anything else:
  an error (its message is on stderr).

dirdelta finds the program as `$DIRDELTA_PICKER` if set, or else
`dirpicker` on `PATH` (`make install PREFIX=~/.local` in cpptree puts it in
~/.local/bin).

## Plan and status

cpptree (dirpicker), each a commit:
1. [done] Read the tree from stdin (`-`, `-0`)
2. [done] Pick with Enter, print the result, exit codes
3. [done] Multi-select (`-m`)
4. [done] Esc / Ctrl-[ clears the search filter, also after Enter kept it
5. [ ] `--header TEXT`: lines shown above the tree
6. [ ] `--root NAME`: the root's name (stdin trees' root is otherwise ".")
7. [ ] `--list`: stdin lines are a flat list of options, the first one selected
8. [ ] `--max-depth N` for scanning a dir

dirdelta, each a commit:
9. [ ] `dirdelta/picker.py`: runs dirpicker (tree → stdin, stdout → picked
   entries), with tests using a fake dirpicker script
10. [ ] Use it for the sync picker (`interactive_dir_sync.py`), menus
   (`menu.py`, `clouddirtreefactory.py`) and picker mode (`dirpick_main.py`)
11. [ ] Stop using curses: `main.py` no longer wraps the app in
   `cursesswitch.wrapper()`, so messages are plain prints
12. [ ] Update README.md, CLAUDE.md and the other docs; decide what to do
   with lib/treepicker (still used for `cursesswitch`'s plain printing)

## Differences from the Python picker

- Keys: h/j/k/l or arrows, / to search (Enter keeps the filter, Esc drops
  it), Space picks (with -m), Enter picks/finishes, q or Ctrl-C quits.
  Missing so far: g/G, the leaf jumps (Ctrl-J/K), Ctrl-H, Ctrl-L, u/d (use
  Ctrl-U/Ctrl-D or PageUp/PageDown), non-interactive search (Ctrl-/).
- Search is smartcase (case-insensitive unless the keyword has uppercase)
  and matches names, like the Python picker's.
- With -m, Enter with nothing picked does nothing, like the Python picker.
