# Improvement ideas

Not implemented: proposed changes, a backlog to pick from. The ones done so far (the 2026-10-23
and 2026-10-24 reviews' #1-25; naming a cloud replica as given, the COPY/REMOVE label, greying
out an option with nothing to do, faster uploads, and trashing whole Drive folders, 2026-10-27;
refreshing a cloud folder at a time: at the start, from the main menu, or with `r` in the file
picker, 2026-10-29; showing where the other replica has a file of the same name, beside the file
picker, one picker per direction with Copy, Remove and Rename in it, sorting an inbox with
Claude's help, 2026-10-29; remembering how a replica's volume was mounted and offering to mount
it, and a new dir and the recent ones for an inbox's "Move to...", 2026-10-30) are in git history. treepicker's own are in `lib/treepicker/docs/improvement-ideas.md`.

Ordered by how easy they are, easiest first (2026-10-30).

1. **Find moved files better.** What's there (2026-10-29, `elsewhere.py`): each direction's
   picker shows, beside the selected file, where the other replica may have it: its files of the
   same name, for a big file, of its size with another name, and in Drive, of its contents whatever
   their name and size (by Drive's hashes); likeliest first (the same contents, size, date taken,
   siblings there too, modification time). The selected file's contents are compared with all its
   same-sized candidates in the background (two local files read side by side; with Drive, its
   SHA-1 or SHA-256), and a Rename compares all the picked files' first, so it moves only what's
   surely the file, and a whole dir as one where it can. Copies keep their modification times.

   Current limits:
   - In a local replica, a renamed file is found only if it's 64 KB or more (`RENAMED_MIN_SIZE`:
     smaller sizes are too common); in Drive, any size, by hash, but only for the files whose
     contents are compared (the selected one, or the picked ones before a Rename).
   - Drive's SHA-1, modification times and photo dates are in the cache only for what was read
     from Drive since 2026-10-29: older lines have only SHA-256 (slower to work out locally), and
     no times or dates, until their folder is refreshed.
   - Files copied before 2026-10-29 have the time of their copy as their modification time, so
     theirs say little.
   - Some photos have no date taken: CR3 and RAF raws (not TIFF files). HEIF's and the TIFF raws'
     reading was tested only on files built by the tests, not on a camera's or phone's.

   Idea: local files' hashes are kept now (`hashcache.py`, 2026-10-29), but only of the files
   compared so far; hashing a whole local replica once (in the background, then kept) would let it
   be looked up by hash as Drive is, finding renamed files (and an inbox's copies) of any size.

2. **Sort an inbox: what's left.** Sorting an inbox into a sorted tree, with Claude's descriptions
   and recommendations, is there (2026-10-29: `inbox.py`, `ai.py`). What's left:
   - The other replicas: a file moved into the sorted tree (`cloud/eliran/...`) could be copied into
     its other replicas too (e.g. `/mnt/win/Users/.../eliran/...`), in the same plan.
   - Junk: files to remove rather than sort, offered as such, never removed without the user. What's
     there: when Claude says where files go, it may answer `remove`, but `ai.recommend()` keeps that
     only for the files the contents check found to be copies of the sorted tree's; any other
     `remove` is dropped (and with no path, the file has no recommendation: "Claude didn't say where
     it goes"). The kinds of junk:
     - By its name, with no Claude: `Thumbs.db`, `.DS_Store`, `desktop.ini`, `~$report.docx`,
       `*.part`, `*.crdownload`, `*.tmp`, empty files; leftovers, like installers (`setup.exe`,
       `.dmg`, `.msi`) or a `.zip` whose contents are beside it. A short list of rules: offline,
       free, predictable, and for files Claude wasn't asked about too.
     - By what Claude says, from what it's given already: accept a `remove` in `ai.recommend()` for
       junk too, not only copies, with its reason, by the names, sizes and descriptions it has now
       (no more reading).
     - Shown: the label `name  [claude: junk? reason]` (`/junk?` finds them all), and the preview
       in yellow, so it isn't taken for a copy's green: "Claude thinks it's junk: ..." or "Junk by
       its name: a Windows thumbnails cache". The menu: "Remove 12 of the 40 files that look like
       junk", apart from "Remove copies" (copies are sure, by their contents; junk is a judgment),
       confirmed twice with each file's reason listed. `Ctrl-X` opens one to look first. Locally,
       to the desktop's trash (`gio trash`) rather than for good, so a wrong guess is undone
       easily; in Drive, to its trash, as now.
     - Kept in `ai.json` with the description, so it's judged once.

     Keep as an idea, but don't implement (2026-10-30): image analysis for junk, as it may take a
     lot of tokens. That is: Haiku judging, while it reads a photo to describe it, whether it's a
     bad one (a pocket shot, a black frame, blurry, a screenshot of nothing), as a `junk` field of
     the description; and near-duplicates (a burst of shots of one scene, a resized or WhatsApp copy
     of a photo, `report-v1`...`v3`): grouping files that look like one (dates taken seconds apart,
     names in a sequence, similar sizes) and asking Claude which to keep.
   - Recommendations per dir. Claude is asked about each file, but an inbox often has dirs whose
     files go together (`rome-2024/`, 300 photos; `scans/tax-2025/`, 40 PDFs). Per file, that's 30
     batches of 10 images read, files of one trip sent to different places (`photos/2024/rome/`,
     `photos/italy/`) as each batch decides on its own, and 300 recommendations to look through
     for what's one decision ("this trip goes to `photos/2024/`"). So: ask about the dir, and move
     it as one.
     - What Claude is given: the dir's name and file count, its size and types (a count per
       extension), a few names (the first, the last, a sample), its date range (photos' dates
       taken, `exif.py`, else modification times), descriptions of 3-5 of its files (read, as
       now), and the sorted tree's dirs.
     - What it answers: move it (where: kept or renamed, or merged into an existing dir), split
       (mixed, e.g. `Downloads/`: back to asking per file), or remove (e.g. all its files are
       copies of the sorted tree's).
     - The picker: `Ctrl-I` on a selected dir (with nothing picked) asks about the dir rather than
       each of its files; the dir's label gets `[claude: Rome trip photos, Oct 2024]` (so `/`
       finds it), and its preview where it goes, why, and how many of its files are in the sorted
       tree already.
     - The menu: "Move the dir rome-2024 (300 files) to Claude's recommendation:
       photos/2024/rome-trip/", and the other ways a file moves (Claude's dir or a picked one,
       its name or a typed one) for a dir too.
     - Moving: locally, one rename; in Drive, one request that changes the folder's parent (it
       keeps its id; a sync's Rename moves whole dirs this way already); local to Drive or back,
       its files copied, then the dir removed from the inbox. Into an existing dir, a merge: the
       approval's tree shows the clashes first.
     - Kept in `ai.json` by the dir's path, file count and total size, so a dir that changed is
       asked about again.
     - Open: which dirs (only those asked about with `Ctrl-I`, to start with, or ones guessed to
       be one thing, by their names or a tight date range); nested dirs (ask about the top one,
       Claude answering split when its subdirs differ); a dir with some files already in the
       sorted tree (move the rest and remove the copies, or leave those to "Remove copies").
     - Effort: medium. `ai.recommend_dir()` with its own prompt, dir nodes in the inbox's picker
       (labels, previews, `Ctrl-I`), whole-dir plans in `_approve()`, tests. Drive's folder move
       and the approval's tree are there.

3. **Know each replica and when it was last updated.** The user keeps a `last_update.txt` at
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
     it's mounted as (the UUID is in `mounts.json` already, by mount point:
     `mounts.py`); for Drive, the account (My Drive's root id, already in the cache) plus
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

4. **Compare sizes or contents of the files at the same path.** The diff is by path only, so a
   file at the same path on both sides counts as the same, even if one was edited or is a
   half-copied file, and it's in neither direction's list. (Idea 1 is the other case: a file at
   different paths, moved or renamed. Its machinery is there now, and this would reuse it: comparing
   contents, `elsewhere._same_contents()`, two local files side by side or by Drive's hash; Drive's
   SHA-1, SHA-256 and `modifiedTime` in the cache; copies that keep their modification times.) Two
   more modes, for the files at the same path:
   - By size (a "medium" diff): a local file's size is a `stat` (find's `-printf '%s'`, in the
     same scan, so nearly free), and a Drive file's is in the cache (`size`: all 20,806 cached
     files have one, as of 2026-10-27). Catches truncated or different files, cheaply.
   - By contents (a "hard" diff): Drive does have hashes, returned as metadata, with no
     download: `md5Checksum`, `sha1Checksum`, `sha256Checksum` (all but Google's own types,
     whose content isn't a file). The cache has `sha256Checksum` (20,804 of the 20,806 cached
     files, as of 2026-10-27) and, since 2026-10-29, `sha1Checksum`. So the Drive side is free;
     the cost is the local side,
     which must read every file to hash it (slow for a big replica, on `/mnt/win` more so).
     The local hash cache (`hashcache.py`: by path, size and mtime) makes the next run hash
     only what changed; and hashing only the files whose sizes match (a different size is already a
     different file). Between two local dirs, both sides are hashed, the same way.
   - The result: a third kind of entry besides "only in A" and "only in B": "in both, but
     different" (by size, or by contents), with its own actions: copy A's over B's, or B's
     over A's, comparing their modification times (Drive's `modifiedTime`, in the cache since
     2026-10-29) to suggest which is newer. This fits idea 7's combined tree.

5. **A GUI, with the image beside the tree.** The same flows and keys as the TUI (the menus,
   the file pickers, `j`/`k`/Space/Enter, search), in a window, with a pane on the right that
   shows the selected file: an image (or a video's frame, a PDF's first page, a text's start),
   since a name like `IMG_2041.jpg` says little when deciding what to copy or remove. For a
   Drive file, its thumbnail (`thumbnailLink`, small, no full download) or the file itself,
   downloaded on demand and cached.
   - Where to build it: dirdelta's flows are Python calling `picker.py`, so the GUI could be
     another implementation of `picker.py`'s functions (`pick_files`, `pick_option`, ...), a
     window instead of a treepicker run, with the rest unchanged. A Python toolkit (Qt via
     PySide6 has tree views and image viewing built in; or a local web page served by dirdelta,
     opened in a browser, which also suits idea 9).
   - A cheaper first step, in the terminal: treepicker's preview column (`--preview`) showing
     the image with a terminal graphics protocol (kitty's, sixel, or iTerm2's, via e.g.
     `chafa`), in terminals that support one. Windows Terminal supports sixel (WSL included).

6. **Bring the phone's new photos in, periodically.** The user connects the phone to the laptop
   now and then, to copy its new pictures into the laptop's replica (photos are kept in Drive,
   not Google Photos). Today that's a plain sync of two dirs, which doesn't fit well:
   - Reaching the phone: plugged in by USB, an Android phone is MTP, not a disk. GNOME's gvfs
     mounts it under `/run/user/UID/gvfs/mtp:host=.../Internal shared storage/DCIM/Camera`, a
     path `find` can walk, but slowly and sometimes not at all (gvfs's MTP drops out on big
     folders). `adb` (USB debugging on) is faster and steadier: `adb shell find` to list,
     `adb pull` to copy. A phone replica type (like `CloudDirTree`, a `PhoneDirTree` listing
     and fetching through `adb`) would hide which is used.
   - Matching by path doesn't work: the phone keeps one flat `DCIM/Camera`, while the laptop's
     replica is sorted into folders (by year, by event), so every photo looks missing. What's
     already copied is found by name and size anywhere in the destination (or by hash, idea 4),
     like idea 1's moved files, not by path.
   - Only what's new: remember, per phone (its serial, `adb get-serialno`, or the MTP device's),
     the newest photo time imported last time, and list only what's newer (by the file's
     mtime, or the date in its name: `IMG_20261027_...`, `PXL_20261027_...`). Then the flow is:
     plug in, choose "Import from phone" (or a favorite pair, phone → destination), see the new
     photos (idea 5's thumbnails help), Enter, done.
   - Where they go: into an inbox folder (e.g. `photos/unsorted`), to sort later with idea 2,
     or straight into a folder by date (`photos/2026/10`, from EXIF's DateTimeOriginal, or the
     name), set once per destination.
   - One way only: never remove from the phone by default. Optionally, once the photos are
     copied and checked (sizes match, or hashes), offer to remove them from the phone to free
     its space.
   - Then to Drive: the laptop's replica goes to `cloud/...` as today, by a sync, or the
     import could copy to both at once.

   Straight from the phone into Drive, with no laptop and no dirdelta server (idea 9):
   - Before writing an app: apps that already do this exist, e.g. Autosync for Google Drive
     (MetaCtrl) or FolderSync, which keep a phone folder synced (one way, upload only, on
     Wi-Fi) into a Drive folder. The Drive app itself uploads by hand only.
   - A dirdelta phone app doing it would be a Drive API client of its own: Android sign-in
     with the user's account, then the same uploads as `CloudDirTree._copy_files()`. The
     `drive.file` scope (only the files the app made) is enough to upload but not to see
     what's already there; checking for duplicates in Drive's folders needs the full `drive`
     scope, a "restricted" one, fine for the user's own app left in Testing (which Google
     doesn't review), but its sign-ins then expire every 7 days.
   - Either way the laptop's Drive cache doesn't know of these uploads: a refresh of the
     folder they went into (at the start, from the menu, or `r` in the file picker) picks them up, and the laptop's replica gets them by a sync
     from `cloud/...`.

7. **One combined diff tree of both replicas, decided per file or dir.** Today's flow is per
   direction: the main menu offers each way's files ("Files in A, not in B"), and its picker
   acts on picks (copy, remove, rename), so a decision about a file is spread over the two
   ways' screens (copy A's new files to B, then remove B's old ones from B, ...). The other way to work, like a sync tool's
   (Unison, Beyond Compare): one tree of everything that differs, both sides together, each
   entry marked by where it is (only in A: `A>`, only in B: `<B`), and an action per file or
   dir, chosen there: copy it to the side that lacks it, remove it from the side that has it,
   or skip. Then one confirmation of the whole plan ("copy 12 to B, remove 30 from B, copy 3
   to A"), and it's done in one go.
   - Better for: deciding about a dir as a whole whichever side it's on, seeing a moved file's
     two halves together (idea 1: `A> old/x.jpg` and `<B new/x.jpg` side by side, and
     Rename, done now from one side, with its two halves in one screen), and one plan to
     review. It's how one thinks of it ("make these two the same, except ..."), rather than a
     pass per direction.
   - A default action per entry, so most need no decision: e.g. copy what's only in one
     side (for a backup-like pair), or per pair (a favorite could keep its default: "B is
     the backup of A": copy A>, remove <B). Space cycles the actions (copy, remove, skip), a
     key sets one for a whole dir, and the stats line counts each.
   - treepicker: each node has one picked state today; this needs a few states per node
     (shown as a mark and a color, like `X`/`-` now), set by keys, and printed with the node
     (`copy\tpath`, `remove\tpath`). Both sides' diffs are two dirdiff runs, merged in Python
     into one `--typed` list with a side for each. A bigger treepicker change than the others,
     made in its repo.
   - What stays: the actions themselves (`copy_inner_entries_from_dirtree`, `remove_files`,
     `move_files`), the progress screen, the dry run, the match indexes. The main menu becomes
     one "Sync" (plus maybe the current per-direction ones, for the simple cases, e.g. a
     read-only replica, where only one way makes sense).

8. **A desktop (or web) app on dirdelta's own libraries.** dirdelta's Python already decides what
   every screen holds: the main menu's options (with their counts, and which are greyed out),
   a picker's files and dirs, the preview column's lines, the confirmations, the progress and
   report lines. Only the drawing is treepicker's and `messages`'. A desktop app (or a web app)
   could reuse all of that, and draw it with its own widgets: a menu as a list or buttons, a
   file picker as a tree view with checkboxes, the preview column as a side pane (idea 5's
   image there too), a confirmation as a dialog with No as the default button, progress as a
   progress bar.
   - The split: the screens' contents as plain data (a menu: a title, header lines, its options
     and which are disabled; a picker: its root, paths, picks, the selection, the previews as
     they come; a confirmation; a progress screen's lines), handed to a frontend, which shows
     them and returns the user's answer (the option, the picks, the key). `picker.py` and
     `messages.py` are already close to that interface: their functions take the contents and
     return the answer, so the terminal frontend is today's treepicker runs and screens, and a
     desktop one is another implementation of the same functions, chosen at startup (e.g.
     `dirdelta --gui`). The flows (`dirsync_main`, `interactive_dir_sync`, `choose_replicas`)
     stay as they are.
   - What needs care: the parts that run while a screen is shown, the menu's counts coming in
     (`shown_as`) and the previews (`send()`), become calls the frontend gets on a thread
     other than its UI thread, so it must hand them to it (Qt's signals, a web socket's
     messages); and an action's progress, which now prints, must go to the frontend's
     progress screen instead.
   - Which toolkit: Qt (PySide6) for a desktop app, with tree views, dialogs and image views
     built in; or a local web app (dirdelta serving a page, opened in the browser), which is
     also the way to idea 9's phone app. Both reuse the same frontend interface.

9. **A dirdelta server, used from a phone.** A daemon on an always-on machine that holds the
   replicas' state (the Drive cache, scans of local dirs it can reach) and runs the actions
   (Copy, Remove, idea 2's sorting), with an API that a phone app (or the browser) connects to:
   the same choices, made remotely, e.g. sorting `cloud/unsorted` from the phone.
   - The core first: the flows (diff, pick, confirm, act) separated from the terminal, so they
     can be driven by an API rather than by treepicker runs and `messages` screens (the same
     separation idea 5 needs, and treepicker's own improvement-ideas mention driving it from
     somewhere other than the keyboard).
   - The server: an HTTP API (e.g. FastAPI): list replicas and pairs (`replicas.json`), a pair's
     diff, a tree's page of entries, an action on picked files, and an action's progress
     (polled or streamed, since actions take minutes), with the dry run as the default there
     too. Long actions run in the background and survive the phone disconnecting.
   - The phone app: a web app (a page served by the daemon, added to the home screen) is the
     cheapest, over a native one; it shows trees, thumbnails (idea 5) and the confirmations.
   - Access: it can delete files in Drive and on disk, so it must not be open: reached over a
     VPN (e.g. Tailscale) rather than the internet, with authentication on top, and the Drive
     token stays on the server. Which local dirs it can reach is the server's, not the
     laptop's (`/mnt/win` is the laptop's Windows drive), so the replicas it serves may
     differ.

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

