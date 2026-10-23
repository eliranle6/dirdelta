# Glossary

**Replica** — one of the two file trees being compared/synced (a local
filesystem directory, or a Google Drive subtree). The user picks two
replicas per run; the app's job is to reconcile them.

**Cloud path** — any path string whose first `/`-separated component is
literally `"cloud"` (e.g. `cloud/mein`). Detected in `utils.py`'s
`__is_cloud_path` / `clouddirtree.CloudDirTree.path_components`. Everything
after the leading `cloud/` segment is the path *inside* the Drive tree, not
a real filesystem path.

**DirTree** — the shared in-memory representation (`dirtree.py`, built on
`treelib.Tree`) of a scanned replica: one node per file or directory,
node identifier = relpath from the tree's root. `LocalDiskDirTree` and
`CloudDirTree` both subclass it and differ only in how they populate
themselves (real `find` scan vs. cached Drive metadata).

**Missing tree / diff tree** — the result of
`DirTree.get_unknown_entries_in_given_dirtree(other)`: a fresh `DirTree`
containing only the files that exist in `other` but not in `self`. This is
literally what gets shown to the user as "the tree of differences."

**DirEntry / FileEntry** — the two node payload types stored in a
`DirTree`'s nodes (`node.data`). `DirEntry` = directory, `FileEntry` = file.
Both carry `name`, `relpath` (from the tree root), and `fullpath`
(absolute-ish path including the tree's root prefix). Neither carries size,
mtime, or a hash — the diff is filename/path-string equality only, by
design.

**Cloud files list cache** — `~/.cache/dirman/files.txt`
(`CloudDirTree.FILE_LIST_CACHE`). One JSON line per Drive API
file object (`id`, `name`, `parents`, `mimeType`, etc.), refreshed on
demand rather than queried live per scan. `CloudDirTree` parses this
file line-by-line to rebuild id→children / id→metadata maps before walking
them into a `DirTree`.

**Picker vs. sync mode** — determined purely by argument count to `main.py`:
one path → "picker" (`dirpick_main.py`, browse/select a single file, e.g.
for the `-x/--execute` launch-with-a-program flow); two paths → "sync"
(`dirsync_main.py`, the diff/copy/remove flow this whole project exists
for).

**`cursesswitch`** — a tiny module (`lib/treepicker/cursesswitch.py`,
bundled into the `treepicker` submodule, not its own repo). dirdelta uses only
its `print_line`, which prints a (optionally colored) line to stdout; its
curses mode (`wrapper()`) is no longer used.

**`dirpicker`** — the C++ tree picker program (from cpptree,
github.com/levioctl/cpptree) that dirdelta runs for every pick and menu, via
`dirdelta/picker.py`. See `docs/dirpicker-integration.md`.

**`treepicker`** — a tiny Python library (own git repo, nested as a submodule
at `lib/treepicker/`) implementing a curses tree-navigation-and-multi-select
widget (`TreePicker`) plus a flat single-select menu (`OptionPickerByMenuTraverse`).
It used to be dirdelta's UI; dirpicker replaced it, since it was too slow for
big trees.
