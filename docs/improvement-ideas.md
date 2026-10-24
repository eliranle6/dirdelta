# Improvement ideas

Not implemented: proposed changes, a backlog to pick from. The ones done so far (the 2026-10-23
and 2026-10-24 reviews' #1-25) are in git history. cpptree's own (dirpicker's) are in
`lib/cpptree/docs/improvement-ideas.md`.

1. **Don't build a Python tree of the missing files.** In a sync of two local dirs, the file
   picker waits for `InteractiveDirSync._missing()`: dirdiff lists the missing files (0.7s for
   /usr/share's 111k against an empty dir), then Python adds each to a DirTree (2.1s), and
   `picker.pick_from_tree()` lists the tree back out as typed paths for dirpicker, which builds
   the same tree again. The Python tree is used only for that listing, for "Nothing to copy"
   (an empty diff), and for looking the picked paths up as entries.

   Instead, dirdiff's output could go to dirpicker as it is: something like
   `picker.pick_from_paths(rootpath, relpaths)`, writing `f <relpath>` lines (dirpicker's
   stream adds the missing parent dirs, so only files are needed; dirdiff's output is sorted
   already), and making FileEntries only for the picked files, from the paths dirpicker prints.
   "Nothing to copy" is then `not relpaths`, and No in the confirmation passes the picked
   relpaths back as `--picked`. Copy keeps `DirTree.from_file_entries()`, of the picked files
   only. That would bring the wait from ~3s to under 1s for a big diff. Cloud syncs keep the
   tree, since their diff is made from it. To check: that a stream with only files marks the
   added parents as dirs (with `--typed`), and the `picked` round trip.
