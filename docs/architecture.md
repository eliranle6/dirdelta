# Architecture

## Data flow, end to end

```
dirdelta command (or python -m dirdelta)
  → main.py: parse_args() → dirsync_main.run(args)  OR  dirpick_main.run(args)
     (no paths: choose_replicas.run(replicas.load()) first, then dirsync_main.run)
     (no curses: each picker is a treepicker run, which has the terminal while
      it's open; messages in between are plain lines, via messages.print_line)
       dirpick_main: local dir → picker.pick_under_dir(dir)   (treepicker scans it)
                     cloud    → utils.create_dirtree_from_arg() → picker.pick_from_tree()
       dirsync_main: utils.create_dirtree_from_arg(path)   for each replica path
            → clouddirtreefactory.factory_interactive()   if path starts with "cloud"
            → localdiskdirtree.factory()                   otherwise
       → picker.pick_option([...])                         (the top-level menu, in _sync)
       → interactive_dir_sync.InteractiveDirSync(src, dst).browse()   (a loop, until q)
              → dirdiff.files_not_in() for two local dirs, else
                DirTree.get_unknown_entries_in_given_dirtree()   (the diff: relpaths)
              → picker.pick_files(src, missing_relpaths)         (selection UI, with
                elsewhere.find_previews() beside it, on a thread)
              → picker.pick_option([Nothing, Copy, Remove, Rename x2])   (the action menu)
              → copy_inner_entries_from_dirtree() / .remove_files() / .move_files()
```

## `dirdelta/` — the application

### `main.py`
Argparse: `dir_a_path`, `dir_b_path` (both optional), `-x/--execute`,
`-m/--max-depth` (default 20, passed down to `localdiskdirtree.factory` as
`find -maxdepth`). No positional path → `choose_replicas.run`, then
`dirsync_main.run` on what it chose; one → `dirpick_main.run`; two →
`dirsync_main.run`. No curses setup: a `picker.PickerError` (treepicker
missing or failing), `DriveCacheError` or `replicas.ReplicasError` exits
with its message.

### `replicas.py` / `choose_replicas.py`
`replicas.py` keeps the pairs of replicas synced (`history`, the latest
first, at most `MAX_HISTORY`) and the favorite pairs, in
`~/.config/dirdelta/replicas.json` (`REPLICAS_FILE`; JSON, hand-editable,
written whole with `os.replace`). A pair is the same either way around, and
a pair used again moves to the top rather than being added twice. Paths are
normalized (`normalized()`: local ones absolute, cloud ones cleaned). A file
that can't be read raises `ReplicasError` rather than being overwritten.
`dirsync_main.run` records each sync's pair as it starts.
`choose_replicas.run(replicas)` is the menu for a run without paths: two
slots (Replica A, B), then the favorites, then the recent pairs (the
history without the favorites), then Quit. A pair is chosen at once, unless
one of its local dirs is gone (a screen says so, back to the menu; a cloud
one is checked when the sync reads Drive's file list); a slot
asks Local disk / Google Drive, then picks a dir: under `/` with
`picker.pick_under_dir(dirs_only=True, lazy=True)` (treepicker reads a dir
only when it's shown), or in the whole Drive tree (`cloud`) with
`pick_from_tree(dirs_only=True)`. Once both slots are chosen (and differ),
it returns them.

### `utils.py`
`create_dirtree_from_arg(rootpath)` is the single dispatch point deciding
cloud vs local, with `paths.is_cloud_path()`: a path is "cloud" iff its
first path component is literally the string `"cloud"` (`paths.py`, which
also has `path_in_cloud()`, used by `CloudDirTree`). `validate_dir` checks
the path is an existing directory for the local case, exiting with a
message (via `messages.print_line`) otherwise.

### `entries.py`, `dirtree.py` — the core data structure
`DirTree` models a filesystem tree, holding a `treelib.Tree` (it offers
`get_node`, `children`, `root`, `remove_node`, `all_nodes`, `in` and
`len()` of it). Its nodes' data are entries
(`entries.py`), each with `name`, `relpath` and `fullpath`:
- `DirEntry` — directory node
- `FileEntry` — file node, no size/hash/mtime stored

Since it doesn't subclass treelib, it has no `create_node`: all callers go
through `add_file_by_relpath` / `add_file_by_fullpath` /
`create_dir_node_from_relpath_if_not_exists` so relpath/fullpath bookkeeping
stays consistent. Node `identifier` in `treelib` is the file's `relpath`,
relative (`sub/x`; the root's is `''`), like treepicker's paths.

**The diff algorithm** — `get_unknown_entries_in_given_dirtree(self, other)`:
for every file in `other`, if its `relpath` is not a node id in `self`,
it's "missing" — collected into a fresh `DirTree` rooted at `other`'s root.
This is called as `dst.get_unknown_entries_in_given_dirtree(src)`, i.e. it
answers "what's in src that dst doesn't have" — pure path-string membership
test, no content comparison at all, matching the stated scope.

`DirTree.from_file_entries(files, root)` (a classmethod) builds a `DirTree`
holding a flat list of `FileEntry` objects at their relpaths: the "chosen
files" sub-tree, just before a copy.
`add_file_by_relpath` returns the existing entry for a file already in the
tree, which is what lets `update_from_filesystem` rescan a tree in place.

### `localdiskdirtree.py`
`LocalDiskDirTree(DirTree)`. `factory(filesystem_dirpath, max_depth=None,
silent=False)` builds the tree then calls `update_from_filesystem`, which
runs one `find ROOT -mindepth 1 [-maxdepth N] -printf '%y %p\0'` (rather
than walking Python-side) and adds its files and dirs (other types, like
symlinks, are skipped; names are decoded with `os.fsdecode`, so names that
aren't UTF-8 work). find's error messages (paths it couldn't read, e.g.
`Permission denied`) are kept in `scan_errors`. Building the tree, not
find, is most of the time (~2.8s for /usr/share's 119k entries).

`copy_inner_entries_from_dirtree(dirtree)` — for each file in the given
sub-tree, calls `add_file_by_relpath` to add the node to `self`'s tree, then
ensures the destination directory exists (`os.makedirs`, tolerant of
already-exists, path derived from `full_filesystem_path()`), then calls
`_copy_local_file_to_tree_with_path`. **Writing is gated behind
`dryrun.DRYRUN`** (`dryrun.py`; known-issues.md #5): dry-run is the default,
in which nothing changes, neither on disk (no directory is created, no
bytes are copied) nor in the tree; only `DRYRUN=0` copies, adding each
copied file to the tree. `remove_files()` is gated the same way: with
`DRYRUN=0` it deletes and drops the nodes from the tree, else neither, and
then removes the dirs that left empty (`_remove_emptied_dirs()`: `os.rmdir`,
deepest first, up to but not including the root; rmdir fails on a dir with
anything in it, which is then kept). Both print a progress line per file, and a
summary. A copy from a tree that says a file can't be copied out
(`cant_fetch()`, a cloud tree's Google files) skips it, saying why. (Previously called a nonexistent
`self._add_file_by_path(...)` and referenced a `filesystem_dirpath`
attribute that doesn't exist on the current `FileEntry`/`DirEntry` — both
fixed, see known-issues.md #2 — and is now covered by
`tests/test_localdiskdirtree.py`.)

### `clouddirtree.py` / `drivecache.py` / `clouddirtreefactory.py`
Cloud state is never queried live per-scan. Instead:
1. `utils.create_dirtree_from_arg` calls `factory_interactive(rootpath)`
   for any path whose first component is `cloud`. It ensures a cache file exists at
   `drivecache.FILE_LIST_CACHE` (`~/.cache/dirman/files.txt`), prompting
   the user (`picker.pick_option`) to refresh the replica's folder in it if it
   already exists ("Refresh cloud/X from Google Drive"; the prompt says if the
   cache may be out of date there, see the stale marker below).
2. `clouddirtree.refresh_cache(folder_path)` (a path in Drive, `/` for all
   of My Drive) reads the folder anew, one request at a time (never in
   parallel, so Drive sees nothing unusual): My Drive's root folder's id
   (`files().get('root')`), then the folders on the way, by name, a request
   a level (`name = 'X' and 'PARENT' in parents and mimeType = folder`; none
   or two is a `DriveCacheError`), then what's in the folder, a level of
   folders at a time, 30 folders a query (`files().list` with "'A' in parents
   or ..." and `trashed = false`, paged, with `drivecache.FILE_FIELDS`). It
   prints "Reading cloud/X from Google Drive...", and then how far it got on
   a line that changes in place (`messages.print_progress()`): "Read N of
   about M files and folders (P%)", where M is how many the cache had there
   (`drivecache.count_under()`), since the Drive API can't count them;
   without one, just N. What it read replaces what the cache had under the
   folder (`drivecache.replace_under()`: the cache rewritten through a `.tmp`
   file, the folder's own line and `trashedId` lines kept, the new lines
   after them, so a file restored from the trash is back), with the folders
   on the way; with no cache, it makes one the same way: the root line
   (`{"myDriveRootId": ...}`) and what it read, into the `.tmp` file that
   then takes the cache's place, so a refresh cut off at any point leaves
   the old cache, or none. The rest of the cache
   isn't read again, so a file moved from the folder to elsewhere in Drive is
   gone from the cache until that place is refreshed. This replaced a scan of
   all of Drive (`files().list` of everything, 2026-10-29): a folder walk
   reads only the folder, and timed on all of My Drive it was about as fast
   (both ~40s for ~17k files: Drive returns at most 460 per page either way).
3. `drivecache.entries(inner_rootpath)` reads that cache with `_parsefile`,
   which `json.loads`es each `{...}` line into a dict (id→children map +
   id→metadata map), and takes the
   root from the root line (a cache from before it guesses: the one id with
   children but no metadata). Files outside My Drive (no parents, or a parent
   that isn't listed) are never reached. It then DFS-walks id→children from
   the root, only into folders on the way to `inner_rootpath` and under it,
   yielding `(relpath, cloud_id, is_dir, is_google_file)` for what's under
   it, each folder before its contents. Google's own files (Docs, Sheets,
   shortcuts...: `application/vnd.google-apps.*` but folders) are in it, by
   their names and an extension, as Google Drive for desktop names them on
   disk (`path_name()`: `Budget.gsheet`, `Notes.gdoc`, `Link.glink`). It raises `DriveCacheError` (which `main.py` prints
   and exits with) if there's no such folder, or if names there can't be
   paths: a `/` in a name, or a folder's name shared with another folder or
   file in one folder (also on the way to it): the user renames them in Drive
   and refreshes the cache. `clouddirtree.factory(rootpath)` builds the tree like
   `localdiskdirtree.factory()` does: a `CloudDirTree(rootpath)`, then its
   `update_from_cache()`, which adds them as `DirTree` nodes, and handles
   Drive's "two files, same path" case by suffixing `___DUP__<id>` on
   collision (same-named folders are an error, above). A `CloudDirTree`'s
   `fullpath()` is its path in Drive (`/mein`), and its `displayname()` the
   cloud path (`cloud/mein`), which every screen names it by (the pickers'
   roots and headers, the confirmation, the progress and the report): a
   `DirTree`'s `displayname()` is its `fullpath()`.

Copying and removing: `CloudDirTree` keeps each file's and folder's Drive id
(`_cloud_ids`, by relpath; the root's from `entries()`' first, `''`, entry).
Copying into it (`_copy_files()`, from a local dir) first makes the folders the
files are in that Drive lacks (`_make_folders()`: ids from `generateIds`, then
a batch request per level of folders, up to 100 each; one that fails is made
later by `_folder_id()`, with its files), then uploads the files
(`MediaFileUpload`: in one request under 5 MB, else resumable),
`UPLOAD_THREADS` (4) at a time, each thread with its own `driveapi.service()`.
What Drive says of each upload goes into the tree and the cache on the main
thread, as it ends. Every request is retried by the client on rate limit and
server errors (`execute(num_retries=5)`, with exponential backoff). Ctrl-C
starts no more uploads and waits for the ones under way (Ctrl-C again
doesn't). Drive limits how fast a user makes files (about 2-3 a second), so
more threads wouldn't help. Copying out
of it, into a local dir, downloads (`fetch_file()`, which
`LocalDiskDirTree._copy_file()` calls on the source tree; a Google file is
skipped, since it's not a file to download); removing (`_remove_files()`)
moves files to Drive's trash, so they can be restored: each topmost folder all
of whose files are picked as one (`_whole_folders()`, from the whole tree, so a
folder whose picker showed it fully picked, but that has files the other replica
has too, isn't one), once Drive says it has nothing more in it, or in the
folders in it, than the tree (`_folders_holding_more()`: `files().list` of
what's in 30 folders a query, for a cache that's out of date), and the rest one
by one. A folder Drive has more in is kept, and the folders in it are tried
instead. Trashed as one, a folder is restored as one, and leaves no empty
folders behind. The confirmation says which folders go whole and which Google
files are removed (`removal_notes()`), or which Google files a copy skips
(`copy_notes()`). The
loops around these (progress lines, dry run, Ctrl-C, the report) are
`DirTree`'s `copy_inner_entries_from_dirtree()` and `remove_files()`, shared
with `LocalDiskDirTree`. A file that fails is said in red, and the rest go on.
The same refresh is the main menu's "Refresh cloud/X from Google Drive"
(all of the replica) and the file picker's `r` key (the selected folder, or
the folder of the selected file: `CloudDirTree.refresh_from_drive(relpath)`,
which goes up to the closest folder the tree has, e.g. for a dir only the
other replica has), which then rebuilds the tree from the cache.

Each change is added to the cache on disk as it's made (not in a dry run):
a JSON line per file or folder made (`drivecache.add()`, with the fields
Drive returns, `FILE_FIELDS`, as a scan lists them), and a
`{"trashedId": ID}` line per file or folder trashed (`drivecache.trash()`),
which `_parsefile()` drops it for (and with a folder, all that's in it, which
the walk from the root no longer reaches). So the cache stays up to date, and the
next run needn't refresh it. Around each change (an upload's: around all of
them) the replica's folder is marked stale
(`drivecache.mark_stale(path)`, a line with its path in Drive in a
`files.txt.stale` file next to the cache), and the mark is taken away once
the change is in the cache (`unmark_stale()`), unless it was there before: a
change cut off in the middle (e.g. Ctrl-C during an upload, when Drive may
or may not have the file) leaves it, so the next run's refresh prompt for a
replica at, above or under that folder says the cache may be out of date
there, and a refresh of that folder (or above it) clears the mark
(`mark_fresh(path)`). A marker from before the paths were written is all of
Drive (`/`).

Logging in to Drive (`token.json`/`credentials.json`, `SCOPES=[drive]`: all of
Drive, to change files too) is `driveapi.service()`, which also makes the
service once per thread (the client's HTTP connection isn't thread-safe), with
one login for all. A saved login without those scopes (e.g. from
when dirdelta only listed files) means logging in again, as does a rejected
refresh. A near-duplicate, unused implementation used to
sit alongside it as `scandrive.py`; it's now archived at
`unused/scandrive.py` (outside any package), not part of the app.

### `dirdiff.py`, `programs.py`
`dirdiff.files_not_in(src_dir, dst_dir, max_depth)` runs `dirdiff -0 SRC DST`,
returning src's files (relative paths) that dst lacks, and find's errors.
It scans both dirs in C++ (~1s for two 119k-file dirs, where building their
Python trees took ~6s). `programs.find(name, env_var)` finds treepicker and
dirdiff: `$env_var`, next to the running python, `lib/treepicker/build/`, `PATH`.

### `interactive_dir_sync.py`
`InteractiveDirSync(src, dst)`. Its diff (`_missing()`): for two local dirs,
`dirdiff`, run anew for each action (so the dirs' own trees are never
scanned: `dirsync_main` makes them empty, and there's no stale scan), with a
warning screen if find couldn't read everything; with a cloud replica, the
trees' `get_unknown_entries_in_given_dirtree()`. Either way it's a list of
relpaths: no Python tree is built of the missing files (for 111k of them that
took ~2.5s; the picker now opens 0.2s after the diff).
- `browse()`, a loop until the user quits the picker: diff →
  `picker.pick_files(src, missing)` (with `--print-selection`, so it returns a
  `picker.Picked`: the key, the selection and the picks) → Enter with picks:
  `_act()`, the action menu (`pick_option`, `NOTHING` first so it's
  selected): Copy to dst, Remove from src, Rename in dst (move dst's match to
  the picked file's path) or in src (the file to the match's path), each
  greyed out (a `picker.Disabled`, saying why) when it can't be done: Copy
  into a read-only dir or within Drive (`can_copy()`), Remove or Rename in a
  read-only one (`is_writable()`), Rename for picks with no sure match
  (`elsewhere.sure_matches()`; a Google file or a `___DUP__` one can't be
  moved, `cant_move()`) → its confirmation (`pick_option(['No', 'Yes'])`, No
  first; a removal a second time, "Are you sure?", `[No, CONFIRM_SURE]`) → act
  (on the progress screen) → back to the picker where it was (the selection,
  or the closest dir still shown, `_shown()`), the diff found again after a
  live change, the files done unpicked and the rest still picked. Nothing, No
  or quitting a menu goes back with the same picks. After an action the
  replicas' `elsewhere.Index`es are updated rather than rebuilt: a copied file
  added to dst's (`has_file()` says which were), a removed one dropped from
  src's, a moved one moved; the Drive cache is updated by the tree itself (a
  line per upload, trash and move). `has_changed` says whether anything did
  change (a live action, or a refresh), for the main menu. With a replica
  that's Drive's, the file picker's `r` (`REFRESH_KEY`, `pick_files(keys='r')`)
  reads the selected folder anew from Drive, in each of the two that's
  Drive's (`refresh_replica(replica, relpath)`), drops its `Index` (built
  again when next needed), diffs them again (the trees as they are, not the
  background future), and shows the picker again on the same node; with
  nothing missing any more, it says so and ends. Beside the picker, a column
  shows where dst has files of the selected file's name
  (`pick_files(previews=elsewhere.find_previews...)`, found each time the
  picker opens, on another thread while it's shown, from dst's `Index`),
  in case it was moved rather than being missing. `FileEntry`s are made for
  the picked files only (`_file_entry()`), and passed to
  `_copy(files)`/`_remove(files)`; Rename calls the replica's `move_files()`
  (`os.rename` locally, removing the dirs left empty; in Drive, one
  `files().update` with the new name and `addParents`/`removeParents`, which
  keeps the file's id).
- `_copy()` rebuilds a `DirTree` from just the selected `FileEntry`s via
  `dirtree.DirTree.from_file_entries` (previously
  miscalled as a `DirTree` classmethod — fixed, known-issues.md #3), then
  calls `dst.copy_inner_entries_from_dirtree(...)` — which is a dry run
  unless `DRYRUN=0` (see `localdiskdirtree.py` above).
- `_remove()` calls `src.remove_files(...)` (see `localdiskdirtree.py`
  above), which, unless it's a dry run, deletes the selected files and drops
  them from the in-memory `src` tree so the next diff doesn't list them
  again. (The `TypeError` from mixing `{}` placeholders with `%` that used
  to crash it is fixed, known-issues.md #16.)

### `dirsync_main.py` / `dirpick_main.py`
Thin wiring: for two local dirs, make their `LocalDiskDirTree`s without
scanning them (each action diffs them with dirdiff, see below); else build
both `DirTree`s, warn (`scan_errors_warning`, shown with
`messages.show()`) about each local one whose scan couldn't read everything,
since its diff may then be wrong,
present a top-level menu (`_sync`: a loop of `picker.pick_option()` over
`_Action`s, each way's "Files in A, not in B", an `InteractiveDirSync(src,
dst, missing, src_index, dst_index)`'s `browse()`, until Quit). Each
replica's `elsewhere.Index` (its files by name) is made here once and shared
by both ways' screens, so it's listed once and kept up to date as they act.
Before the menu, a "Read-only" screen (`messages.show()`) says which replicas
are read-only (`interactive_dir_sync.is_writable`: a cloud replica, or a
`LocalDiskDirTree` with write permission, so not one on a read-only mount)
and why. Each way's diff (`interactive_dir_sync.find_missing()`: dirdiff for
two local dirs, else the trees as they are, so a cloud tree is never scanned
again) is found once, on a daemon thread (`_Way.find_missing()`, a
`concurrent.futures.Future`), as the menu opens: while it's being found the
option is shown as "(loading...)", with the dots moving, then with how many
files it has (`pick_option(shown_as=...)`, which sends treepicker the changes
through `--updates`); with none, it can't be picked, and is shown greyed out
saying why ("none, B has them all", a `picker.Disabled`). Choosing an option
waits for both ways (an action may change what the other is diffing), and
after a screen that changed the files (`InteractiveDirSync.has_changed`: a
live action, or a refresh in its picker) both are found again. Each cloud
replica also gets "Refresh cloud/X from Google Drive", for when Drive changed
since the cache was made: `interactive_dir_sync.refresh_replica()`, which runs
`CloudDirTree.refresh_from_drive()` (see `clouddirtree.py` above), and says on
a screen if it fails (an `HttpError`, an `OSError` such as no network, a
`DriveCacheError`, or Ctrl-C), else it drops that replica's `Index` and both
ways are found again. Given a `Replicas` (as `run` does), the menu also has
"Add to favorites" (or "Remove from favorites") before Quit, which saves the
change.
`dirpick_main.run` returns the picked path: for a local dir it lets
treepicker scan the dir itself (`picker.pick_under_dir`, much faster than
building a `DirTree`, ~3s for 119k files); for a cloud path it builds the
`CloudDirTree` and uses `picker.pick_from_tree`. `main.py` then prints the
path, or `os.execvp`s the `-x` program on it.

### `messages.py`
`print_line(line, color=None)`: prints dirdelta's messages (scanning,
copying, removing...) as plain lines, optionally colored with `termcolor`,
encoding with `surrogateescape` so file names that aren't UTF-8 print as
they are. A picker covers what was printed before it, so what's to be read
goes on a screen that waits for Enter: `show(title, lines)` for messages
(the scan warnings, "Nothing to copy"), and `progress_screen(title)` for
actions. `progress_screen(title)` (a context manager) runs an action on the whole
screen, on a terminal: it clears it, keeps the title on the top line with
a scroll region (`ESC[2;Hr`) for the lines under it, catches Ctrl-C, and
at the end says Done/Stopped and waits for Enter. Actions that catch Ctrl-C to say
how far they got (copying, removing) call `note_stopped()`. Without a
terminal it only prints.

### `dryrun.py`
`DRYRUN` (true unless `DRYRUN=0` is set), read at each use, and `label()`:
("DRY RUN", "green") or ("LIVE", "red"), which `picker.py` passes to every
treepicker run (`--label`, `--label-color`: at the start of its bottom line)
and `interactive_dir_sync.py` to the progress screen (its top line).
Copy's and Remove's file picker and confirmation add their own label after
it (`InteractiveDirSync.LABELS`: COPY in blue, REMOVE in magenta).

### `elsewhere.py`, `exif.py`
`Index(replica)`: a replica's files by name (`{name: {relpath: size}}`, and
the names in each dir), built once from its `files_by_name(progress)` and
then kept up to date by `add()`, `remove()` and `move()` as files are copied,
removed and moved (or dropped with `invalidate()` after a refresh). dst's
files by name come from: a `DirTree`'s nodes and `file_size()` (None), a
`CloudDirTree`'s nodes with the cache's sizes (a same-named file's
`___DUP__` relpath under its real name), and a `LocalDiskDirTree`'s one
`find -type f -printf '%s %P'` of the dir (its tree may not be scanned: see
dirdiff), read as it goes; each calls `progress(count)` now and then.
`find_previews(relpaths, src, index, send)`, run by `picker.pick_files()` on
a thread of its own while the picker is shown, builds the index if it isn't,
then sends, for each missing file, the lines of the file picker's preview
column: the file's own size and date taken, and its matches (files of the
same name in the index), likeliest first (`_unlikeliness()`): the same size,
the same date taken, the most of the file's siblings in the match's dir (a
few of its dir's missing files, `SIBLINGS_TRIED`, looked up once per pair of
dirs), then the closest size; at most `MAX_MATCHES`, each with its dir,
size, date taken and siblings found, and "surely this file, moved" for the
`sure_match()` (the only one of the same size, and the same date taken where
both are known, or of several, the one with the most siblings). What's found
is sent every `SEND_INTERVAL` (0.1s), with how far it's got as the text of
the files not done yet ("Listed N of its files", then "Matched X of Y
files"). `send()` raises `picker.PickerClosed` once the picker is gone, which
stops it (and the `find`). `sure_matches()` is what Rename moves. Dates taken
are the replicas' `date_taken()`: Drive's `imageMediaMetadata.time` (in the
cache's lines from 2026-10-29 on: older ones have none until a refresh), or a
local JPEG's EXIF `DateTimeOriginal` (`exif.date_taken()`, which reads only up
to the EXIF segment, and only for files with matches); other formats (HEIC)
have none locally.

### `picker.py`
Runs `treepicker` (from github.com/eliranle6/treepicker; `$DIRDELTA_PICKER`, or
`treepicker` on `PATH`) as a subprocess for each pick, fzf-style: treepicker
draws on `/dev/tty`, reads its input on stdin and prints what was picked on
stdout, all `\0`-separated (`-0`). Exit code 1 means the user quit (→
`None`); others raise `PickerError`. See `docs/treepicker-integration.md`.
- `pick_from_tree(tree, header, dirs_only, root_name)`: picks one node of a `DirTree` (cloud
  picker mode, the cloud diff view). Sends its node ids (relative paths,
  like treepicker's; the root, `''`, is treepicker's `.`), each after its type
  (`--typed`: `f sub/x`, `d sub`), each dir before its contents, siblings
  sorted by tag; maps the picked path back to the node's entry (`.` is the
  root).
- `pick_files(rootpath, relpaths, header, picked, ...)`: picks several of a
  list of files (`-m`), sent as `f sub/x` lines only: treepicker adds their
  dirs. Returns a `Picked`: the key that ended it ('' for Enter), the
  selection (`--print-selection`) and the picked files' relpaths (treepicker
  also prints the dirs whose files are all picked; those are dropped). `picked` start picked
  (`--picked FILE`). `previews(send)`, called on a thread of its own while
  the picker is shown, sends what to show in a column beside the tree for the
  selected node (`--preview FD`, a pipe): `send(found, default)`. The input
  goes to treepicker from a temp file, not written by `communicate()`, so a
  busy thread holding the GIL doesn't slow treepicker's start; `_run()` waits
  for the threads before returning.
- `pick_under_dir(dirpath, max_depth, dirs_only, lazy, header)`:
  `treepicker [--max-depth N] [--dirs-only] [--lazy] DIR`.
- `pick_option(options, header)`: `treepicker --list`, for menus.
Names are passed as bytes with `surrogateescape`, so non-UTF-8 file names
round-trip. Tests (`tests/test_picker.py`) run a fake treepicker script.

## `lib/treepicker/` — treepicker and dirdiff (git submodule)

The C++ tree picker dirdelta runs, and `dirdiff` (github.com/eliranle6/treepicker;
its README and `--help` describe them). `make build` builds them in
`lib/treepicker/build/`; `make install`/`make deploy` copy them next to the
environment's python, where `programs.find()` looks first. The Python picker
library that was the UI before (with `cursesswitch`) was
removed on 2026-10-24.
