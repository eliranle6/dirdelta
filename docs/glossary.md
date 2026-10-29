# Glossary

**Replica** — one of the two file trees being compared/synced (a local
filesystem directory, or a Google Drive subtree). The user picks two
replicas per run; the app's job is to reconcile them.

**Cloud path** — any path string whose first `/`-separated component is
literally `"cloud"` (e.g. `cloud/eliran`). Detected by
`paths.is_cloud_path()`. Everything
after the leading `cloud/` segment is the path *inside* the Drive tree, not
a real filesystem path.

**DirTree** — the shared in-memory representation (`dirtree.py`, holding a
`treelib.Tree`) of a scanned replica: one node per file or directory,
node identifier = relpath from the tree's root (`sub/x`; the root's is `''`). `LocalDiskDirTree` and
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
(`drivecache.FILE_LIST_CACHE`). One JSON line per Drive API
file object (`id`, `name`, `parents`, `mimeType`, etc.), refreshed on
demand a folder at a time (a replica's, or a folder in it) rather than
queried live per scan. `CloudDirTree` parses this
file line-by-line to rebuild id→children / id→metadata maps before walking
them into a `DirTree`.

**Picker vs. sync mode** — determined purely by argument count to `main.py`:
one path → "picker" (`dirpick_main.py`, browse/select a single file, e.g.
for the `-x/--execute` launch-with-a-program flow); two paths → "sync"
(`dirsync_main.py`, the diff/copy/remove flow this whole project exists
for).

**Old Python picker** — the Python curses tree-picker library that was dirdelta's UI, as a
submodule (with `cursesswitch`, its curses/plain printing shim), until treepicker replaced it;
removed 2026-10-24.
