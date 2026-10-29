# Improvement ideas

Not implemented: proposed changes, a backlog to pick from. The ones done so far (the 2026-10-23
and 2026-10-24 reviews' #1-25; naming a cloud replica as given, the COPY/REMOVE label, greying
out an option with nothing to do, faster uploads, and trashing whole Drive folders, 2026-10-27;
refreshing a cloud folder at a time: at the start, from the main menu, or with `r` in the file
picker, 2026-10-29) are in git history. treepicker's own are in `lib/treepicker/docs/improvement-ideas.md`.

1. **Show where a file is in the other replica, beside the file picker.** The diff is by path
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

2. **Sort an inbox folder: file each one away, or remove it.** A mode for a folder of files
   not yet sorted (e.g. `cloud/unsorted`), rather than a diff of two replicas: for each file
   (or dir), decide to move it into the sorted tree (`cloud/eliran/...`, at a path picked in its
   tree, and into the other replicas too, if any, e.g. a copy into
   `/mnt/win/Users/.../eliran/...`), or remove it (Drive's trash), or leave it for later.
   - The flow: pick files in the inbox (`pick_files`), choose an action, and for "move", pick the
     destination dir with the dir picker (`pick_from_tree(dirs_only=True)` for Drive). Moving
     within Drive is one `files().update` with `addParents`/`removeParents` (no upload, keeps
     the id), like idea 1's Rename; the other replicas get a download (`fetch_file()`) or a
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

3. **A GUI, with the image beside the tree.** The same flows and keys as the TUI (the menus,
   the file pickers, `j`/`k`/Space/Enter, search), in a window, with a pane on the right that
   shows the selected file: an image (or a video's frame, a PDF's first page, a text's start),
   since a name like `IMG_2041.jpg` says little when deciding what to copy or remove. For a
   Drive file, its thumbnail (`thumbnailLink`, small, no full download) or the file itself,
   downloaded on demand and cached.
   - Where to build it: dirdelta's flows are Python calling `picker.py`, so the GUI could be
     another implementation of `picker.py`'s functions (`pick_files`, `pick_option`, ...), a
     window instead of a treepicker run, with the rest unchanged. A Python toolkit (Qt via
     PySide6 has tree views and image viewing built in; or a local web page served by dirdelta,
     opened in a browser, which also suits idea 4).
   - A cheaper first step, in the terminal: treepicker's side column (idea 1's) showing the image
     with a terminal graphics protocol (kitty's, sixel, or iTerm2's, via e.g. `chafa`), in
     terminals that support one. Windows Terminal supports sixel (WSL included).

4. **A dirdelta server, used from a phone.** A daemon on an always-on machine that holds the
   replicas' state (the Drive cache, scans of local dirs it can reach) and runs the actions
   (Copy, Remove, idea 2's sorting), with an API that a phone app (or the browser) connects to:
   the same choices, made remotely, e.g. sorting `cloud/unsorted` from the phone.
   - The core first: the flows (diff, pick, confirm, act) separated from the terminal, so they
     can be driven by an API rather than by treepicker runs and `messages` screens (the same
     separation idea 3 needs, and treepicker's own improvement-ideas mention driving it from
     somewhere other than the keyboard).
   - The server: an HTTP API (e.g. FastAPI): list replicas and pairs (`replicas.json`), a pair's
     diff, a tree's page of entries, an action on picked files, and an action's progress
     (polled or streamed, since actions take minutes), with the dry run as the default there
     too. Long actions run in the background and survive the phone disconnecting.
   - The phone app: a web app (a page served by the daemon, added to the home screen) is the
     cheapest, over a native one; it shows trees, thumbnails (idea 3) and the confirmations.
   - Access: it can delete files in Drive and on disk, so it must not be open: reached over a
     VPN (e.g. Tailscale) rather than the internet, with authentication on top, and the Drive
     token stays on the server. Which local dirs it can reach is the server's, not the
     laptop's (`/mnt/win` is the laptop's Windows drive), so the replicas it serves may
     differ.

5. **One combined diff tree of both replicas, decided per file or dir.** Today's flow is per
   action: the main menu offers four (copy each way, remove from each), each picker shows one
   way's files, and a decision about a file is spread over passes (copy A's new files to B,
   then remove B's old ones from B, ...). The other way to work, like a sync tool's
   (Unison, Beyond Compare): one tree of everything that differs, both sides together, each
   entry marked by where it is (only in A: `A>`, only in B: `<B`), and an action per file or
   dir, chosen there: copy it to the side that lacks it, remove it from the side that has it,
   or skip. Then one confirmation of the whole plan ("copy 12 to B, remove 30 from B, copy 3
   to A"), and it's done in one go.
   - Better for: deciding about a dir as a whole whichever side it's on, seeing a moved file's
     two halves together (idea 1: `A> old/x.jpg` and `<B new/x.jpg` side by side, and
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
   - Would replace the greyed-out options with nothing to do (there are no options) and the
     COPY/REMOVE label (each entry says its action).

6. **Know each replica and when it was last updated.** The user keeps a `last_update.txt` at
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

7. **Compare sizes or contents, not only paths.** The diff is by path only, so a file at the
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
     to suggest which is newer. This fits idea 5's combined tree.
   - Hashes also find moved files for idea 1 better than names: the same sha256 at another
     path is surely the same file, whatever it's named.

8. **Bring the phone's new photos in, periodically.** The user connects the phone to the laptop
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
     already copied is found by name and size anywhere in the destination (or by hash, idea 7),
     like idea 1's moved files, not by path.
   - Only what's new: remember, per phone (its serial, `adb get-serialno`, or the MTP device's),
     the newest photo time imported last time, and list only what's newer (by the file's
     mtime, or the date in its name: `IMG_20261027_...`, `PXL_20261027_...`). Then the flow is:
     plug in, choose "Import from phone" (or a favorite pair, phone → destination), see the new
     photos (idea 3's thumbnails help), Enter, done.
   - Where they go: into an inbox folder (e.g. `photos/unsorted`), to sort later with idea 2,
     or straight into a folder by date (`photos/2026/10`, from EXIF's DateTimeOriginal, or the
     name), set once per destination.
   - One way only: never remove from the phone by default. Optionally, once the photos are
     copied and checked (sizes match, or hashes), offer to remove them from the phone to free
     its space.
   - Then to Drive: the laptop's replica goes to `cloud/...` as today, by a sync, or the
     import could copy to both at once.

   Straight from the phone into Drive, with no laptop and no dirdelta server (idea 4):
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

9. **Remember how a replica's volume was mounted, and offer to mount it.** A local replica is
   often on a volume that isn't always mounted: `/mnt/win` is the laptop's Windows partition
   (as of 2026-10-29 `/dev/sda3`, NTFS via ntfs-3g, label `OS`, UUID `9618289F1828807B`, not in
   `/etc/fstab`, so mounted by hand), and an external disk comes and goes. Choosing a recent pair
   or a favorite with such a path while it's unmounted fails at `validate_dir()`, or worse: an
   unmounted mount point is still there, an empty dir on the root filesystem, so the diff says
   every file is missing, and a live Copy would fill the root filesystem rather than the volume.
   - What's kept: when a replica is used, the mount it's under (`findmnt -no
     TARGET,SOURCE,FSTYPE,OPTIONS,UUID,LABEL --target PATH`): mount point, device, filesystem
     type, options, UUID, label. In `~/.config/dirdelta/` with the pair (`replicas.json`), or
     with idea 6's replica records, which identify a local replica by the same UUID. Only for a
     mount other than `/` (a path on the root filesystem has nothing to remember).
   - Finding it unmounted: before scanning, the recorded mount point isn't a mount
     (`os.path.ismount()` is false, or `findmnt --target PATH` now says `/`), whether or not the
     path exists.
   - The question, rather than an error: "/mnt/win isn't mounted (last time: /dev/sda3, NTFS,
     'OS'). Mount it?", with Yes, No (back to the menu) and, if the disk isn't there
     (`/dev/disk/by-uuid/UUID` missing, so it's unplugged), "Connect it, then try again".
   - Mounting it, by the UUID (the device name may differ next time), at the same mount point,
     so the replica's path still holds: `mount TARGET` if fstab has a line for it (`noauto,user`
     needs no root), else `sudo mount -t TYPE -o OPTIONS UUID=... TARGET` with the recorded
     options (sudo asks for the password in the terminal, which dirdelta doesn't hold between
     pickers). `udisksctl mount -b /dev/disk/by-uuid/UUID` needs no sudo (polkit), but mounts
     at `/media/$USER/LABEL`, another path: the replica's path would then be mapped to it, for
     this run. Each run is shown before it's run, and its error if it fails.
   - NTFS: if Windows hibernated, or shut down with Fast Startup on, ntfs-3g won't mount it
     read-write ("The disk contains an unclean file system"): mounted read-only instead
     (`-o ro`, said so), the "Read-only" screen already says nothing will be copied into or
     removed from it.
   - Where: `choose_replicas` (a recent pair or a favorite) and a run with paths, before the
     trees are made; picker mode too. Mounting changes the system, not files, so it's asked
     even in a dry run, and never done without asking.

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
