# Improvement ideas

Not implemented: proposed changes, a backlog to pick from. The ones done so far (the 2026-10-23
and 2026-10-24 reviews' #1-25, and naming a cloud replica as given, 2026-10-27) are in git
history. treepicker's own are in
`lib/treepicker/docs/improvement-ideas.md`.

1. **Remove a whole Drive folder in one call.** A Remove from Drive trashes each picked file on
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

2. **Refresh only the cloud replica's folder, from the main menu, with a key.** The cache is
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

3. **Show where a file is in the other replica, beside the file picker.** The diff is by path
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

4. **Upload many small files faster.** A Copy into Drive uploads file by file
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

5. **Grey out a main menu option with nothing to do.** Once a way's files are found, an option
   whose count is 0 reads "Copy files from cloud/eliran to /mnt/win/Users/Johabab
   Glizerin/eliran (the 0 files it lacks)": an option offered for nothing, and choosing it only
   shows the "Nothing to copy" screen. It would be shown dimmed, can't be chosen (`j`/`k` skip
   it, or Enter on it does nothing), and say why in its label, e.g.:
   - "Copy files from cloud/eliran to /mnt/win/.../eliran: nothing to copy, it has them all"
   - "Remove files from /mnt/win/.../eliran: nothing to remove, cloud/eliran has them all"
   ("nothing to copy" says it at once, and "it has them all" why.) While loading, it stays as
   it is ("(loading...)"), and if counting failed ("couldn't count the files"), choosable, so
   choosing it shows the error. After a live action, the counts are found again
   (`_Way.find_missing()`), so an option may become disabled, or enabled again (e.g. a Remove
   that leaves the other way something to copy).
   - The label: `_Action.shown_as()`, which already says the count, says this for 0 instead.
   - Disabled needs treepicker: `--list` options are all pickable. Something like a
     `--updates` line that marks an option disabled (`OPTION<tab>TEXT<tab>disabled`), drawn
     dimmed, skipped by the selection, and never printed. A treepicker change, made in its
     repo. Without it, dirdelta could keep the option choosable and only reword it, since
     choosing it already just says so.

6. **Sort an inbox folder: file each one away, or remove it.** A mode for a folder of files
   not yet sorted (e.g. `cloud/unsorted`), rather than a diff of two replicas: for each file
   (or dir), decide to move it into the sorted tree (`cloud/eliran/...`, at a path picked in its
   tree, and into the other replicas too, if any, e.g. a copy into
   `/mnt/win/Users/.../eliran/...`), or remove it (Drive's trash), or leave it for later.
   - The flow: pick files in the inbox (`pick_files`), choose an action, and for "move", pick the
     destination dir with the dir picker (`pick_from_tree(dirs_only=True)` for Drive). Moving
     within Drive is one `files().update` with `addParents`/`removeParents` (no upload, keeps
     the id), like idea 3's Rename; the other replicas get a download (`fetch_file()`) or a
     local copy. A batch of decisions is confirmed together, like Copy/Remove now.
   - A recommendation from Claude: for each file, an agent (the Claude API, with the file's name,
     path, size, type, and its contents for text/PDF/images within limits) suggests where in
     the sorted tree it belongs (given that tree's dirs, maybe a summary of each) or that it's
     junk, with a reason. Shown beside the file, as the default answer, which the user accepts
     or changes: never acted on without the user. It sends the files' contents to an outside
     service, so off unless turned on (and maybe only for some folders), with an API key kept
     like `secrets/`. Costly for many files: suggest per dir where a dir holds one thing, cache
     the suggestions.
   - Entry: e.g. `dirdelta --sort cloud/unsorted`, or an option in the menu of a run without
     paths.

7. **A GUI, with the image beside the tree.** The same flows and keys as the TUI (the menus,
   the file pickers, `j`/`k`/Space/Enter, search), in a window, with a pane on the right that
   shows the selected file: an image (or a video's frame, a PDF's first page, a text's start),
   since a name like `IMG_2041.jpg` says little when deciding what to copy or remove. For a
   Drive file, its thumbnail (`thumbnailLink`, small, no full download) or the file itself,
   downloaded on demand and cached.
   - Where to build it: dirdelta's flows are Python calling `picker.py`, so the GUI could be
     another implementation of `picker.py`'s functions (`pick_files`, `pick_option`, ...), a
     window instead of a treepicker run, with the rest unchanged. A Python toolkit (Qt via
     PySide6 has tree views and image viewing built in; or a local web page served by dirdelta,
     opened in a browser, which also suits idea 8).
   - A cheaper first step, in the terminal: treepicker's side column (idea 3's) showing the image
     with a terminal graphics protocol (kitty's, sixel, or iTerm2's, via e.g. `chafa`), in
     terminals that support one. Windows Terminal supports sixel (WSL included).

8. **A dirdelta server, used from a phone.** A daemon on an always-on machine that holds the
   replicas' state (the Drive cache, scans of local dirs it can reach) and runs the actions
   (Copy, Remove, idea 6's sorting), with an API that a phone app (or the browser) connects to:
   the same choices, made remotely, e.g. sorting `cloud/unsorted` from the phone.
   - The core first: the flows (diff, pick, confirm, act) separated from the terminal, so they
     can be driven by an API rather than by treepicker runs and `messages` screens (the same
     separation idea 7 needs, and treepicker's own improvement-ideas mention driving it from
     somewhere other than the keyboard).
   - The server: an HTTP API (e.g. FastAPI): list replicas and pairs (`replicas.json`), a pair's
     diff, a tree's page of entries, an action on picked files, and an action's progress
     (polled or streamed, since actions take minutes), with the dry run as the default there
     too. Long actions run in the background and survive the phone disconnecting.
   - The phone app: a web app (a page served by the daemon, added to the home screen) is the
     cheapest, over a native one; it shows trees, thumbnails (idea 7) and the confirmations.
   - Access: it can delete files in Drive and on disk, so it must not be open: reached over a
     VPN (e.g. Tailscale) rather than the internet, with authentication on top, and the Drive
     token stays on the server. Which local dirs it can reach is the server's, not the
     laptop's (`/mnt/win` is the laptop's Windows drive), so the replicas it serves may
     differ.

9. **Say COPY or REMOVE in a colored label in the file picker.** The file picker's bottom line
   has one label, the mode's (DRY RUN in green, LIVE in red, `--label`/`--label-color`), and
   what the picks are for is only in the header's text ("Pick the ones to remove from ...").
   Picking files to remove looks like picking files to copy. A second label, e.g. COPY in
   blue and REMOVE in red (or magenta, to keep red for LIVE), before the header's text or next
   to the mode's label, would say it at a glance; the confirmation's header could start with
   it too. treepicker takes one `--label` today: it would take several (repeated `--label` and
   `--label-color`, drawn side by side), or a label for the header line. A treepicker change,
   small; then `interactive_dir_sync._chooseFiles()` passes it.

10. **One combined diff tree of both replicas, decided per file or dir.** Today's flow is per
    action: the main menu offers four (copy each way, remove from each), each picker shows one
    way's files, and a decision about a file is spread over passes (copy A's new files to B,
    then remove B's old ones from B, ...). The other way to work, like a sync tool's
    (Unison, Beyond Compare): one tree of everything that differs, both sides together, each
    entry marked by where it is (only in A: `A>`, only in B: `<B`), and an action per file or
    dir, chosen there: copy it to the side that lacks it, remove it from the side that has it,
    or skip. Then one confirmation of the whole plan ("copy 12 to B, remove 30 from B, copy 3
    to A"), and it's done in one go.
    - Better for: deciding about a dir as a whole whichever side it's on, seeing a moved file's
      two halves together (idea 3: `A> old/x.jpg` and `<B new/x.jpg` side by side, and
      Rename as an action that fits), and one plan to review. It's how one thinks of it ("make
      these two the same, except ..."), rather than four passes.
    - A default action per entry, so most need no decision: e.g. copy what's only in one
      side (for a backup-like pair), or per pair (a favorite could keep its default: "B is
      the backup of A": copy A>, remove <B). Space cycles the actions (copy, remove, skip), a
      key sets one for a whole dir, and the stats line counts each.
    - treepicker: each node has one picked state today; this needs a few states per node
      (shown as a mark and a color, like `X`/`-` now), set by keys, and printed with the node
      (`copy\tpath`, `remove\tpath`). Both sides' diffs are two dirdiff runs, merged in Python
      into one `--typed` list with a side for each. A bigger treepicker change than the others,
      made in its repo.
    - What stays: the actions themselves (`copy_inner_entries_from_dirtree`, `remove_files`),
      the progress screen, the dry run. The main menu becomes one "Sync" (plus maybe the
      current per-action ones, for the simple cases, e.g. a read-only replica, where only one
      way makes sense).
    - Could replace ideas 5 (options with nothing to do: there are no options) and 9 (the mode
      label: each entry says its action).

11. **Know each replica and when it was last updated.** The user keeps a `last_update.txt` at
    a replica's root, a log of changes, newest last, e.g. (`/mnt/win/.../eliran`'s, as of
    2026-10-27, also in `cloud/eliran`):
    ```
    15.12.2025 - copied DCIM pictures from old pixel 8 (not whatsapp pictures)
    17.05.2026 - removed old money.ods
                 remove Resume.* files
    ```
    (a `DD.MM.YYYY - text` line per entry, its continuation lines indented, an early entry a
    bare date). dirdelta could read it, and remember its replicas:
    - A replica's identity: for a local one, the filesystem it's on (its UUID, `findmnt -no
      UUID` / `blkid`, or on WSL's `/mnt/c` drives the Windows volume serial, e.g. via
      `cmd.exe /c vol`) plus the path in it, so an external disk is the same replica whatever
      it's mounted as; for Drive, the account (My Drive's root id, already in the cache) plus
      the path. Also a marker file it could write at the root (`.dirdelta-replica` with an id),
      which survives the disk being replaced or copied; but it's a file in the replica, which
      the user may not want.
    - What's kept, in `~/.config/dirdelta/` next to `replicas.json` (or in it): each replica's
      id, the paths it was seen at, the last entry of its `last_update.txt` (date and text), when
      dirdelta last saw it, and when dirdelta last changed it (a live Copy/Remove into it).
    - Shown: in the menu of a run without paths ("cloud/eliran: updated 17.05.2026, removed old
      money.ods"), and a replica list ("which disk did I last update, and when?"), including
      disks not plugged in now, from what was kept.
    - Written by dirdelta too: after a live Copy/Remove, offer to add an entry ("27.10.2026 -
      copied 12 files from cloud/eliran") to the replica's `last_update.txt`, so the log stays
      up to date without writing it by hand (and the other replica's copy of the file, which
      is itself a file that differs between them).
    - The format: parse the fixed one above (the date at a line's start); lines it can't parse
      are kept as text. Asking a model to read free text is possible but not needed while the
      user writes it this way: a fixed format is cheaper, offline, and predictable. A model
      could still summarize a long log, if ever wanted.

12. **Compare sizes or contents, not only paths.** The diff is by path only, so a file at the
    same path on both sides counts as the same, even if one was edited or is a half-copied
    file. Two more modes, for the files at the same path:
    - By size (a "medium" diff): a local file's size is a `stat` (find's `-printf '%s'`, in the
      same scan, so nearly free), and a Drive file's is in the cache (`size`: all 20,806 cached
      files have one, as of 2026-10-27). Catches truncated or different files, cheaply.
    - By contents (a "hard" diff): Drive does have hashes, returned as metadata, with no
      download: `md5Checksum`, `sha1Checksum`, `sha256Checksum` (all but Google's own types,
      whose content isn't a file). The scan already asks for `sha256Checksum`, and 20,804 of the
      20,806 cached files have one. So the Drive side is free; the cost is the local side,
      which must read every file to hash it (slow for a big replica, on `/mnt/win` more so).
      A local hash cache, keyed by path, size and mtime, makes the next run hash only what
      changed; and hashing only the files whose sizes match (a different size is already a
      different file). Between two local dirs, both sides are hashed, the same way.
    - The result: a third kind of entry besides "only in A" and "only in B": "in both, but
      different" (by size, or by contents), with its own actions: copy A's over B's, or B's
      over A's, comparing their mtimes (Drive's `modifiedTime`, which the scan could ask for)
      to suggest which is newer. This fits idea 10's combined tree.
    - Hashes also find moved files for idea 3 better than names: the same sha256 at another
      path is surely the same file, whatever it's named.

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
