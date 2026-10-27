# Improvement ideas

Not implemented: proposed changes, a backlog to pick from. The ones done so far (the 2026-10-23
and 2026-10-24 reviews' #1-25) are in git history. treepicker's own are in
`lib/treepicker/docs/improvement-ideas.md`.

1. **Say which replica a cloud path is.** A `CloudDirTree`'s `fullpath()` is its path inside
   Drive (`/eliran`), and that's what the Copy/Remove confirmation ("Remove 1400 files from
   /eliran?"), the progress lines and the report ("removed 1400 of 1400 files from /eliran (to
   Drive's trash)") show. It reads like a local dir. The main menu shows the replica as given
   (`cloud/eliran`), so the screens after it should too, e.g. through a display name on each
   tree (`cloud/eliran`, or "Google Drive: /eliran") rather than `fullpath()`. (Found
   2026-10-27, removing 1400 files from Drive.)

2. **Remove a whole Drive folder in one call.** A Remove from Drive trashes each picked file on
   its own (`CloudDirTree._remove_file()`, one API call each), even when a whole folder is
   picked, and leaves the folders behind, now empty (a known gap: after removing
   `docs/archive`'s 1400 files on 2026-10-27, its 209 folders were still there, so Drive looked
   unchanged, while the files were in its trash). Trashing a folder trashes all that's in it in
   one call, and keeps it together in the trash for restoring. It's not a small change:
   - `picker.pick_files()` returns files only (it drops the dirs treepicker prints), so the
     folders all of whose files are picked would be found again from the picked relpaths, the
     topmost ones only.
   - The cache leaves out Google's own types (Docs, Sheets, shortcuts) and what dirdelta can't
     see, so a folder can look fully picked while holding more: trashing it would trash those
     too. Each such folder would be checked with Drive first (a `files().list` of what's in it,
     recursively), or the user told and asked.
   - The progress lines and the report count files: a folder would count as its files.
   - The cache: a `trashedId` line for the folder already hides what's under it (`entries()`
     walks down from the root), so that part works as it is.
   Smaller, and maybe enough: after the files, trash the folders the Remove left empty (by the
   cache, checked with Drive as above), so the folder tree doesn't stay behind.

3. **Refresh only the cloud replica's folder, from the main menu, with a key.** The cache is
   refreshed only all at once (`clouddirtreefactory._refresh_cache()`, a scan of all of Drive),
   and only at the start, by the "Refresh cloud files list cache" prompt. When the replica is one
   folder (`cloud/eliran/docs`), or Drive changed outside dirdelta while the main menu is open,
   a refresh of just that folder would be much faster, and wouldn't mean starting over. In the
   main menu (Copy/Remove), a key (e.g. `r`) would:
   - Read the folder anew from Drive: a `files().list(q="'ID' in parents and trashed = false")`
     per folder, walking down from the replica's root (its id is `CloudDirTree._cloud_ids['']`),
     with `drivecache.FILE_FIELDS`. One call per folder (hundreds for a big tree) rather than the
     full scan's one call per 1000 files, so it pays off for a part of Drive, not for most of it.
   - Put it in the cache: drop the old lines of what's under the folder and add the new ones.
     That means rewriting the cache (~10 MB, once), unlike the appended lines of
     `drivecache.add()`/`trash()`. It leaves the stale marker as it is, since the rest of the
     cache wasn't refreshed (unless it was marked for a change under this folder only, which
     isn't recorded).
   - Rebuild the `CloudDirTree` from the cache, and find each way's files again
     (`_Way.find_missing()`), so the menu's counts come back as "(loading...)" and then anew.
   The key needs treepicker: today `--list` only prints the picked option. Something like fzf's
   `--expect KEYS` (print the key that ended the pick, then the selection) would be a treepicker
   change, made in its repo (see `lib/treepicker/docs/improvement-ideas.md`). Without it, a
   "Refresh cloud/eliran from Drive" option in the menu does the same, with no treepicker change.

4. **Show where a file is in the other replica, beside the file picker.** The diff is by path
   only, so a file moved (or renamed dir) in one replica shows up as missing from the other:
   Copy would make a second copy of it, and Remove would remove the one that moved. While
   picking files (Copy/Remove's picker, `picker.pick_files()`), a right-hand column would show,
   for the selected file, a small tree of where the other replica has a file of the same name
   (its paths there, as a tree from the replica's root), or that it has none. Then the user can
   tell a moved file from a missing one before copying or removing it.
   - Matching: by name, the cheapest, with all of a common name's matches listed (e.g.
     `README.md`). Size, or a hash, would tell same-named files apart: the Drive cache has
     `size` and `sha256Checksum`, a local dir would need a `stat` (size) or reading the file
     (hash). Name and size may be enough to start with.
   - The other replica's files by name: a `{name: [relpaths]}` map, built once per picker. For a
     local dir that's one more `find` of it (dirdiff lists only the diff); a cloud tree has
     them all.
   - treepicker: it has no side column. Something like fzf's `--preview`, but rather than
     running a command per selection (slow for Drive, and dirdelta has the map in memory), a
     protocol like `--updates`: treepicker writes the selected node's path to an fd as the
     selection moves, and dirdelta answers with the lines to show (a tree, drawn by treepicker
     or sent drawn). The column would take part of the width, or be toggled with a key. A
     treepicker change, made in its repo.
   - Then suggest renaming rather than copying: for a file whose match is found, a "Rename"
     action that moves the match in the other replica to this file's path (or this file to the
     match's), so both have it at one path, rather than a Copy and a Remove. Cheap on both
     sides: `os.rename` (a move within one disk) locally, and in Drive one `files().update`
     with the new `name` and `addParents`/`removeParents` (making the folders on the way, like
     `_folder_id()`), which keeps the file's id, history and sharing, unlike a new upload. The
     cache gets the change as a line too (the file again, with its new name and parents). The
     Copy/Remove pickers could say which of their files have a match ("moved?"), and the
     confirmation offer Rename for those.

5. **Upload many small files faster.** A Copy into Drive uploads file by file
   (`CloudDirTree._copy_file()`), each a resumable upload (`MediaFileUpload(resumable=True)`:
   two requests, one to start it and one with the data) and each folder on the way its own
   `files().create`, one after the other. For a folder of many small files, the round trips
   are most of the time. The Drive API has no "upload a folder" call (and doesn't unpack an
   uploaded zip), so a picked dir is still its files, but:
   - A simple (multipart) upload for small files (`resumable=False`, say under 5 MB): one
     request each rather than two. Resumable only for big ones, where a cut-off upload can go on.
   - Uploads in parallel, a few at a time (e.g. 4-8 threads). The client's `httplib2` isn't
     thread-safe, so each thread needs its own `driveapi.service()` (its own `Http`). Drive
     limits requests per user (on the order of 10 per second sustained), so a few threads,
     with retries on 403/429 rate-limit errors (exponential backoff), not dozens. The progress
     lines, Ctrl-C (stop starting new ones, let the running ones finish or cancel), and the
     cache lines (`drivecache.add()`, from one thread) would need care.
   - The folders first, in batches: `files().generateIds()` gives ids up front, so the folders
     of a whole picked tree can be made in a `BatchHttpRequest` (up to 100 creates in one
     request; batches can't carry file data, only metadata), and then the files uploaded
     into them, in parallel.
   Measure first (one big folder of small files), since how much each step saves depends on
   the round-trip time.

## Parked: performance

Decided 2026-10-25: speed is good enough, so no more work on it until decided otherwise. A sync
of a 111k-file diff shows its file picker ~0.75s after Copy is chosen (dirdiff 0.56s, then
treepicker's load 0.15s). Ideas measured then, if it's ever reopened:
- dirdiff builds two full sorted trees, where a hash set of the other dir's paths and the first
  dir's sorted find output would do (find alone takes 0.17s of its 0.56s): ~0.3s.
- dirdiff printing the missing files as find lists them, piped into treepicker, so its tree is
  built during the scan: ~0.15s. ("Nothing to copy" and the find warning need the whole diff.)
- treepicker showing the tree while it loads (like fzf): the first screen at once, but a tree that
  changes under the user. Streaming dirdiff's list from Python would save only ~0.02s.
