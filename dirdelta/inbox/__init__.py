"""Sorting an inbox: a dir of files not yet sorted (e.g. cloud/unsorted), whose files the user moves
into a sorted tree (e.g. cloud/eliran), copies there, or removes, with Claude's help if they ask
for it (ai.py): a short description of each file, shown after its name, and where in the sorted
tree it belongs, shown beside it, to move it there.

When the inbox and the sorted tree are both local dirs, or both in Drive, the files are moved within
one tree that has both (their common dir, or Drive's), so a move is a rename (in Drive, one request
that keeps the file's id). When one is local and the other in Drive, a move is a copy (an upload or
a download, as a sync's), then the file's removal from the inbox, once it's there.

Its parts are in the modules here, InboxSort (sort.py) bringing them together."""
from dirdelta.inbox.sort import InboxError, InboxSort, run  # noqa: F401
