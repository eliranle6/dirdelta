# treepicker internals — rendering, search, pagination, input

Deeper than `architecture.md`'s summary. Read this before changing how the
tree is drawn, how search filtering behaves, or how scrolling/pagination
works — the pieces are more coupled than they look from the outside.

## Rendering — `treeprinter.TreePrinter`

`calculate_lines_to_print(selected_node_id, picked_nodes, search_pattern)`
then `print_tree()` is the two-step protocol `TreePicker._print_tree` drives
every redraw.

### Auto-scoping the root (`_prepare_tree_for_printing`)
Before drawing, it picks *which node to treat as the display root* — not
always the tree's real root. If the selected node survives the current
search filter, it starts from the **selected node's parent** as a candidate
root, then repeatedly walks candidate roots up toward the real root via
`treeops.get_max_possible_depth`, accepting each successive ancestor as the
new root as long as the subtree from that ancestor still fits within
`max_nr_lines` (`node_counter <= max_nr_lines`). Net effect: the view shows
as much ancestor context as fits, scoped tightly around the current
selection, rather than always rendering from the absolute root — this is
what makes deep trees usable without the selected node scrolling off in a
sea of unrelated siblings.

`treeops.get_max_possible_depth(tree, root, max_nr_lines, min_depth)` does a
BFS from `root` counting only nodes with `matching` truthy (or no
`matching` attribute at all — i.e. unfiltered), stopping depth growth once
the running count would exceed `max_nr_lines`, but always allowing descent
down to `min_depth` (the selected node's depth) regardless of count.

### Drawing (`_get_tree_lines`)
Iterative DFS (explicit stack, not recursion) over `_children()` — which
itself filters to nodes with `matching` truthy or no `matching` attribute,
i.e. search-filtered-out nodes are simply skipped during traversal.
Children are sorted by `str(node.data)` (`_node_key`) at each level, not by
insertion order.

Box-drawing characters (UTF-8, hardcoded as escaped byte literals):
`VERTICAL │`, `LAST_CHILD └`, `MID_CHILD ├`, `HORIZONTAL ─`. Each line's
prefix is built as: `[selection marker][pick marker][search marker]` +
per-depth continuation marks (`│   ` if an ancestor at that depth still has
more siblings to print, else 4 spaces) + this node's own branch glyph
(`└── ` or `├── `).

Per-line color:
- selected node: `blue` if also picked, else `green`
- picked (not selected): `red`
- search match that isn't the selected/picked node: `yellow`, with a `~`
  appended to the marker column
- otherwise: no color

Multi-line tags (`node.tag` containing `\n`, or already a pre-built list of
`(text, color, bold)` segments) are supported — continuation lines get a
blank-prefix-of-equal-width so wrapped text still lines up under the tree
guides.

### Pagination integration
Within one sibling group, if there are more siblings than fit
(`pagination.paginate`), lines before/after the visible window collapse
into a single `"... (N more)"` line rather than being omitted silently.
Depth-limited subtrees (a node has children but is at `_max_allowed_depth`)
get a trailing `(...)` marker instead of being expanded, so the user knows
there's more below without it being drawn.

## Pagination math — `pagination.paginate(nr_items, selected_item_index, max_nr_items)`

Pure function, no state. Given a sibling count, the selected index within
that group, and a max visible count, returns
`(nr_items_removed_at_the_beginning, nr_items_removed_at_the_end)` — i.e.
how many leading/trailing siblings to collapse into "... N more" markers so
the selected item stays visible inside the window. Deliberately biases
toward keeping siblings *after* the selection first
(`nr_items_removed_at_the_end` computed first from
`nr_items - selected_item_index - 1`), then trims from the front only if
still over budget. Has an off-by-one guard: a removed-count of exactly `1`
is normalized to `0` (no point collapsing a single line into a "1 more"
marker).

## Search filtering — `treesearch.TreeSearch`

`get_filtered_tree(pattern)` mutates the tree's nodes **in place** (does
not build a new tree — despite the name, no tree object is returned; the
caller, `TreePickerModel._validate_navigator_tree`, does the actual
copy-into-new-tree step using the `matching`/`original_matching` flags this
sets). For every node (iterative DFS), sets:
- `node.original_matching` — whether *this node's own* tag/data text
  (case-insensitive) contains the pattern
- `node.matching` — `original_matching` OR any descendant matches (matching
  propagates *up* to ancestors via the `path_from_root` list maintained
  during the DFS, so a deeply matching leaf keeps its whole ancestor chain
  visible)

Has a "performance optimization" path: if the new pattern is a superset of
the previous pattern (`self._tree.pattern in pattern`), it only re-examines
children of already-matching nodes — narrowing search reuses prior results
instead of rescanning everything. This is why `treeprinter._DATA_THAT_WILL_APPEAR_FIRST`
constants and the `~` search-match marker exist — `original_matching`
(this node itself matched) is what's rendered with `~`, distinct from
`matching` (this node or a descendant matched, used for traversal/visibility).

Its `__main__` block (`treesearch.py:48-56`) calls
`dirtree.DirTree.factory_from_filesystem(...)`, which does not exist
anywhere in the codebase (nearest equivalents:
`localdiskdirtree.factory()`, or the module-level
`dirtree.factory_from_list_of_file_entries`). Dead/stale profiling script,
not part of any real call path.

## Raw input — `getcher.GetchUnix`

Reads exactly one raw character from stdin using `tty`/`termios`
(`tty.setraw` + restore via `termios.tcsetattr(..., TCSADRAIN, ...)` in a
`finally`). Unix-only (module names `tty`/`termios` don't exist on
Windows) — matches the WSL-oriented paths seen in `dirsync-cloud.sh`
(`/mnt/c/Users/...`). `keybind.KeyBind` and `linescanner.LineScanner` both
hold their own `GetchUnix()` instance rather than sharing one — harmless
since it's stateless per call, just a minor duplication.

## Line editing — `linescanner.LineScanner`

Backs both interactive and non-interactive search input. `scan_char()`
reads one char via `GetchUnix` and returns
`STATE_EDIT_IN_PROGRESS`/`STATE_EDIT_ENDED`:
- `Enter` (`chr(13)`) → ends edit, keeps current line
- `Backspace` (`chr(127)`) → pops last char; if line already empty, treated
  as "cancel" (ends edit)
- `Ctrl-H` / `Ctrl-U` / `Ctrl-W` (`ord in (8, 21, 23)`) → clear whole line,
  keep editing
- `Ctrl-C` / `Esc` (`chr(3)`, `chr(27)`) → clear line AND end edit (cancel)
- anything else → appended to the line

Note this overlaps/collides by design with `TreePicker`'s own navigation
keybinds (e.g. `Ctrl-U`/`Ctrl-D` are "page up/down" in navigation mode) —
they don't conflict at runtime only because `TreePicker._mode` gates which
handler (`KeyBind.do_one_action` vs. `LineScanner.scan_char`) receives the
keystroke.

## `exampletree.py`

Demo tree used by `treepicker.py`'s, `treeprinter.py`'s, and (indirectly)
`optionpicker.py`'s `__main__` blocks. **Broken under Python 3**: line 6
does `for i in range(6) + range(10, 15)`, and `range` objects don't support
`+` in Python 3 (only in Python 2, where `range()` returned a list). Would
raise `TypeError: unsupported operand type(s) for +: 'range' and 'range'`
the moment any of those demo scripts are run directly.
