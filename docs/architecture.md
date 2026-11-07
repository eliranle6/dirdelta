# Architecture

## Data flow, end to end

```
dirdelta command (or python -m dirdelta)
  → main.py: parse_args() → dirsync_main.run(args)  OR  dirpick_main.run(args)
     (no paths: choose_replicas.run(replicas.load()) first, then dirsync_main.run)
     (no curses: each picker is a treepicker run, which has the terminal while
      it's open; messages in between are plain lines, via messages.print_line)
       dirpick_main: local dir → picker.pick_under_dir(dir)   (treepicker scans it)
                     cloud    → replicafactory.create_dirtree_from_arg() → picker.pick_from_tree()
       dirsync_main: replicafactory.create_dirtree_from_arg(path)   for each replica path
            → clouddirtreefactory.factory_interactive()   if path starts with "cloud"
            → localdiskdirtree.factory()                   otherwise
       → picker.pick_option([...])                         (the top-level menu, in _sync)
       → interactive_dir_sync.InteractiveDirSync(src, dst).browse()   (a loop, until q)
              → dirdiff.files_not_in() for two local dirs, else
                DirTree.get_unknown_entries_in_given_dirtree()   (the diff: relpaths)
              → picker.pick_files(src, missing_relpaths)         (selection UI, with
                elsewhere.find_previews() beside it, on a thread)
              → picker.pick_option([Nothing, Copy, Remove, Rename x2])   (the action menu)
              → copy_in() / .remove_files() / .move_files()
```

## `dirdelta/` — the application

### Its layout

The modules are grouped in packages by what they're about; no file is much longer than ~200
lines. A module that grew big became a package of its own (e.g. `inbox/`, `ui/picker/`,
`drive/clouddirtree/`): its `__init__.py` re-exports the names the rest of dirdelta uses, so
callers still write `picker.pick_option()` or `clouddirtree.factory()`. A big class (InboxSort,
InteractiveDirSync, DirTree, LocalReplica, CloudDirTree, Index, Job, Opener) is one object whose
methods are in mixins, each in a module of its own (named by what it does): they're one object's
operations on its state, often overriding its base's hooks. State with an owner of its own is a
collaborator instead: InboxSort's Claude knowledge (`inbox/ai/knowledge.py`, `self._claude`: what
Claude said and is asked, under its lock), which the rest of the sort asks through its methods
(`description()`, `recommendation()`, `is_describing()`...), and only the Claude worker changes; a long function is
steps of their own (InboxSort's menu: _menu_facts() and its options by kind; the sync's picker:
_browse() and its steps; the sync menu: sync_menu.SyncMenu; treepicker's run: picker.command._Command). The sections below
still name the modules by their own names (`inbox.py` is now `inbox/`, and so on).

A name used by another module is public (no leading underscore), even inside a package.

Tests patch a name where it's looked up: in the module that uses it (e.g.
`dirdelta.claude.ai.query.run_query`, `dirdelta.drive.drivecache.names.LINES_FILE`,
`dirdelta.trees.localdiskdirtree.fs.trash`), not in the package that re-exports it. A module
global that tests change (those three, `ai.config.CACHE_FILE`, `hashcache.database.CACHE_FILE`,
`mounts.names.MOUNTS_FILE`, `opening.names.MAX_OPENED`) is
read through its module (`names.LINES_FILE`) by the others, so one patch reaches all of them.

The map (each module's docstring's first line; generated from the code):

- `dirpick_main.py`: Picker mode: pick a file or dir under a path, then print it, or run a program (-x) on it
- `main.py`: dirdelta's entry point: the arguments, then the start menu (no path), picker mode (one path), sync mode (two) ...
- `claude/`: What Claude says of files, and the AI's plans of what to do with them
  - `ai/`: What Claude (MODEL) says of files: a short description of each (which reads them), and where in a sorted tree ...
    - `cache.py`: What Claude said, kept by the files' hashes, or their paths and sizes
    - `config.py`: The models, the cache's file, the limits and the system prompts; and what's asked about
    - `dirs.py`: Asking Claude about a dir as a whole
    - `files.py`: Asking Claude about files in batches: their descriptions, and where they go
    - `prompts.py`: The prompts about files, and reading Claude's answers to them
    - `query.py`: Running a query with the Claude Agent SDK: Read only, answering by a schema
  - `aiplan/`: Asking AI about files: the user says what they want in their own words, and the AI answers it (if it's a quest...
    - `answer.py`: The AI's answer, checked into a Plan: only what can be done
    - `asking.py`: Asking the AI about a Task (make())
    - `kinds.py`: What the AI is told and answers: its limits, its system prompt, and Action, File, Task, Step, Plan
    - `prompt.py`: The prompt of a Task (with the files of its focus, which the AI may read), and the schema of its answer
- `drive/`: Google Drive: its API, the cache of its file list, and a Drive folder as a replica
  - `clouddirtreefactory.py`: A Drive replica's tree, after asking whether to refresh its file list from Drive first
  - `driveapi.py`: dirdelta's connection to the Google Drive API (service()), logged in with the OAuth secrets in SECRETS_DIR: cr...
  - `clouddirtree/`: A Google Drive folder as a replica (CloudDirTree): its files read from the Drive cache (drivecache.py), copied...
    - `constants.py`: How a Drive tree's changes are made: how many at once, in what requests, retried how often
    - `fetching.py`: Copying a Drive tree's files out of it: downloading them
    - `folders.py`: Making the folders that files go into, a level of them in a batch
    - `info.py`: What's known of a Drive file, from its metadata
    - `moves.py`: Moving and copying files within Drive: one request each, keeping the file's id
    - `refresh.py`: Reading a Drive folder anew into the cache
    - `removals.py`: Removing files from a Drive tree, to Drive's trash
    - `tree.py`: A tree of a Drive folder (CloudDirTree), read from the Drive cache; its changes are mixins, each in a module o...
    - `uploads.py`: Copying files into a Drive tree: uploading them, a few at once
    - `whole_folders.py`: The folders all of whose files are removed, trashed as one
  - `drivecache/`: The cache of Google Drive's file list, an SQLite file (see database_path(), next to LINES_FILE): a row per fil...
    - `changes.py`: What dirdelta changes in Drive, put in the cache
    - `database.py`: The cache's SQLite database: one connection, from any thread; and importing the old file
    - `metadata.py`: What a file's metadata (as Drive gives it) says of it
    - `names.py`: Where the cache is, and the names and fields of what it keeps
    - `reading.py`: Reading the cache into the paths of what's under a folder
    - `stale.py`: The folders whose part of the cache may be out of date: a change to them was cut off
    - `times.py`: When each folder's list was last read from Drive, and uploaded to it; and whose Drive it is
  - `drivemeta/`: A Drive replica's file list, kept in it too: FILE_NAME in its paths.META_DIR (cloud/X/meta/ files.jsonl), so a...
    - `checking.py`: Using a newer copy from Drive, at a sync's start (check())
    - `lookup.py`: Finding a folder's copy in Drive
    - `names.py`: The copy's name and header, and how often it's uploaded
    - `uploader.py`: Uploading it again as it changes, while a sync goes on (Uploader, kept())
    - `uploading.py`: Uploading the cache's list of a folder to its copy (upload())
- `hashes/`: Hashing local replicas' files in the background, and the cache of their hashes
  - `hashcache/`: Local files' contents' hashes, kept in SQLite databases, so a file is read to hash it once: by its path, with ...
    - `access.py`: Getting a file's hashes, putting them, and the ones known under a dir
    - `database.py`: The databases kept (CACHE_FILE's, and each replica's own), opened once, from any thread, and committed at most...
    - `moving.py`: A moved file's or dir's hashes, moved with it
    - `replica_dbs.py`: A local replica's own database (META_DIR/META_NAME in it), and which database has a file
  - `hashing/`: Hashing local replicas' files in the background, all of them, so a file can be looked up by its contents (else...
    - `job.py`: A local replica's hashing job (Job): its files hashed in the background, by the pool's threads
    - `job_files.py`: What a job knows of its files, and who it tells as they're hashed
    - `job_scanning.py`: A job's scan: listing its replica's files, and telling which are hashed already
    - `pool.py`: The threads that hash the jobs' files, and how many there are
    - `reading.py`: Reading a file to hash it: at the lowest priority, without filling the page cache
    - `registry.py`: The jobs, one by replica
    - `states.py`: The hash a job makes, how it reads, and the states it goes through (Progress)
- `inbox/`: Sorting an inbox: a dir of files not yet sorted (e.g. cloud/unsorted), whose files the user moves into a sorte...
  - `constants.py`: The inbox sort's keys, timings, labels and colors
  - `copies.py`: The inbox's files that are copies of the sorted tree's, or junk
  - `formatting.py`: Small helpers for the sort's texts: counts, the action menu's options and the preview column's lines
  - `keys.py`: What the inbox picker's own keys do: its menus, exploring, renaming and opening
  - `listing.py`: The inbox's files and dirs, as last listed, and what's kept of them
  - `previews.py`: What the inbox's picker shows of each file: its tags, and its preview
  - `screen.py`: The inbox's picker: the loop that shows it and does what's chosen
  - `side.py`: The sorted tree beside the inbox's picker (see sidetree.py), and its hashing
  - `sort.py`: The sort of an inbox into a sorted tree (see dirdelta.inbox): InboxSort, one object whose parts are mixins, ea...
  - `actions/`: What the inbox sort's action menu does: where files go, and moving, copying and removing them
    - `approval.py`: The approval of a move or copy: the tree it makes, shown before it's done
    - `destinations.py`: Where the action menu's options put the files, and the lines saying so
    - `dirs.py`: Choosing a dir of the sorted tree (or the inbox) for files to go to
    - `menu.py`: The action menu of the picked files
    - `menu_moves.py`: The action menu's options that move or copy the picked files
    - `menu_options.py`: The action menu's options but the moves: asking Claude or the AI, removing, opening
    - `transfer.py`: Moving, copying and removing the inbox's files
    - `typed_names.py`: Names the user types for the files and dirs moved into the sorted tree
  - `ai/`: The inbox sort's Claude: describing and placing files and dirs, and the AI's plans
    - `ask_ai.py`: Asking the AI what to do with the inbox's files (see aiplan.py)
    - `claude.py`: Asking Claude about the inbox's files in the background: describing them, and where they go
    - `claude_dirs.py`: Asking Claude about an inbox's dir as a whole
    - `claude_files.py`: Waiting for Claude, and the files it's given (downloaded from Drive, if they must be)
    - `knowledge.py`: What Claude said of an inbox's files and dirs, and what it's being asked now (ClaudeKnowledge): the sort's one...
- `known/`: What's known of the replicas: recent pairs and favorites, their logs, names, labels and mounts
  - `log_entries.py`: What a sync or a sort changed in each replica, and the entries offered for their logs once it's done
  - `replica_history.py`: What's known of the replicas (Replicas): the pairs synced, the favorites, the sorts, each sorted tree's recent...
  - `replicainfo.py`: What's known of a replica, as the screens say it: when it was last synced and changed, its log's last entry, t...
  - `replicalog.py`: Each replica's log of changes, LOG_NAME at its root, which the user keeps, newest last:
  - `replicanames.py`: What to call a replica on the screens, telling which disk or Drive account it's on, as the user labeled it if ...
  - `replicas.py`: The pairs of replicas the user synced (history, the latest first) and the ones they made favorites, and the in...
  - `settings.py`: The user's choices that last from one run to the next (SETTINGS_FILE): whether the file pickers show the selec...
  - `mounts/`: The volumes that local replicas are on, kept in MOUNTS_FILE (JSON) so that one that isn't mounted now (a disk'...
    - `current.py`: What's mounted now, and remembering it
    - `file.py`: The mounts kept, in MOUNTS_FILE
    - `mounting.py`: Mounting a volume again where it was, once the user says so
    - `names.py`: Where the mounts are kept, what's looked for, the mount question's options, and a Mount
    - `read_only.py`: Why a volume is read-only, and what to do about it
    - `running.py`: Running the commands that say what's mounted, and mount
- `matching/`: Matching files across replicas: where a missing file may be, files that differ, junk, sync state
  - `differing/`: The files that two replicas both have at the same path, but not alike: of other sizes, or of the same size wit...
    - `finding.py`: Finding the files two replicas both have at the same path that differ, and which is newer
    - `showing.py`: What's shown of the files that differ: their tags, and their previews
  - `junk.py`: Junk an inbox's files may be, by their names and sizes alone (no Claude, nothing read): system files, temporar...
  - `syncstate.py`: Whether a pair of replicas is in sync, as far as dirdelta knows: what a sync of them last found (replicas.Repl...
  - `elsewhere/`: Where the other replica has a file that a replica lacks, moved or renamed, shown beside the file picker (picke...
    - `candidates.py`: The other replica's files that may be a file: of its name, of its size, of its contents
    - `constants.py`: How many candidates are shown and tried, how often, and what says one is surely it
    - `contents.py`: Comparing the files' contents with their candidates'
    - `index.py`: A replica's files by name, size and hash (Index), built once and kept up to date
    - `index_files.py`: An Index's files: looked up, and kept up to date as they're added, removed and moved
    - `index_hashes.py`: What an Index knows of its files' hashes, without reading them, and what it reads
    - `preview_lines.py`: The lines of a missing file's preview
    - `previews.py`: The previews of the missing files, sent to the picker as they're found
    - `sure.py`: The candidates that are surely the file
- `screens/`: Screens of their own: choosing replicas, the replicas dashboard, the AI's plan, zips and labels
  - `aiplan_screen.py`: The screens of asking AI about files (see aiplan.py): what's wanted, typed; waiting for it; then its answer, o...
  - `archive_screen.py`: Exploring an archive (see archives.py) in a picker, as a tree of what's in it, each file's size and date besid...
  - `choose_replicas.py`: The menu that chooses what to sync, when dirdelta is run without paths: a replica for each of its two slots (a...
  - `label_screen.py`: Labeling replicas (see replicanames.py), e.g. 'laptop' or 'blue WD ext. disk'.
  - `pair_labels.py`: How the start menu labels pairs, sorts and replicas: their names, when each was updated, and their marks
  - `replica_choices.py`: Choosing one replica for a slot: a local dir, a Drive one, or one already known
  - `start_names.py`: The start menu's options, sections and what it returns
  - `hashes_screen/`: The screens of hashing local replicas' files (hashing.py): whether to hash a replica's files when it's opened ...
    - `dashboard_actions.py`: What the dashboard's options do, and the dashboard shown as it changes
    - `dashboard_lines.py`: The dashboard's lines of each replica's hashing and Drive's hashes
    - `dashboard_rows.py`: The dashboard's rows of each pair and each replica
    - `dashboard_screen.py`: The replicas dashboard: each replica's files, last update and hashing
    - `files.py`: A job's files, each with its tag and hash
    - `marks.py`: What the file pickers show of hashing: their key, each file's tag, and the status line
    - `names.py`: The hashing screens' key, and the dashboard's options (what each is, by replica) and headings
    - `offering.py`: Whether to hash a replica's files when it's opened
    - `status.py`: What's shown of the hashing jobs (hashing.py): each file's tag, and how far each job got
    - `waiting.py`: Waiting for the hashing, and whether it's all right to quit meanwhile
- `sync/`: Sync mode: the menu of a pair of replicas, its two ways, and what it does to the replicas
  - `comparing.py`: Comparing, on request, the files two replicas both have at the same paths, of the same size, whose hashes aren't both known
  - `dirsync_main.py`: Sync mode: the menu of a pair of replicas, until it goes back to the start menu
  - `options.py`: The sync menu's lines: whether the two are in sync, and each way's option
  - `replica_ops.py`: What a sync does to its replicas outside its screens: what one lacks of the other, reading them anew, and whet...
  - `sync_menu.py`: The sync menu of a pair of replicas (SyncMenu): each way's files, the files that differ, reading the replicas ...
  - `ways.py`: A sync's two ways (src's files that dst lacks), and the files that differ, found in the background
  - `way/`: A way of a sync (InteractiveDirSync) and its parts, as mixins
    - `ask_ai.py`: Asking the AI what to do with the picked files (see aiplan.py)
    - `browsing.py`: The sync's file picker: the loop that shows it and does what's chosen
    - `copying.py`: Copying and removing the picked files, and copying back the other replica's versions
    - `interactive_dir_sync.py`: A way of a sync: the files in src that aren't in dst (and the ones both have that differ), picked and copied, ...
    - `keys.py`: What the sync picker's own keys do: its menus, the tree beside it, exploring and renaming
    - `lists.py`: What the sync's picker lists: the missing files, the ones that differ, and their previews
    - `menu.py`: The action menu of the picked files
    - `picking.py`: What the sync's file picker is shown with, and showing it once
    - `renames.py`: Renaming files to where the other replica has them (see elsewhere.py)
- `trees/`: Trees of a replica's files: the base DirTree, a local dir's, listing and diffing local dirs, and paths
  - `dirdiff.py`: Diffing two local dirs with the dirdiff program (from the lib/treepicker submodule): it scans them in C++, muc...
  - `entries.py`: The data of DirTree's nodes: a DirEntry for a dir, a FileEntry for a file.
  - `localscan.py`: One listing of a local dir, for all that lists one: by one find (faster than os.walk, see docs), its files and...
  - `paths.py`: Replica paths, as given on the command line: a cloud (Google Drive) one starts with the component 'cloud' (e.g...
  - `replicafactory.py`: The tree of a replica, made from its path: a local dir's or a Drive folder's
  - `dirtree/`: A tree of a dir's files and dirs (DirTree), the base of the replicas' trees: a local dir's (localdiskdirtree.p...
    - `changes.py`: Removing and moving a tree's files, in batches, and what each kind of tree does for one file
    - `common.py`: What a tree's parts share: the error of a stopped hash, a batch's verb, a path's place
    - `copying.py`: Copying files into a tree, and within it
    - `dir_moves.py`: Moving a whole dir as one, and what can't be changed
    - `files_info.py`: What a tree knows of its files: sizes, dates, hashes, and the files by name
    - `listeners.py`: Who a tree tells of its changes, and the dirs it keeps
    - `tree.py`: DirTree: a tree of a dir's files and dirs; what it does with them are mixins, each in a module here
  - `localdiskdirtree/`: A local dir as a replica: LocalReplica, whose files are asked of the disk as they are now, and LocalDiskDirTre...
    - `copying.py`: LocalCopying files into a local replica (replacing one, if it's asked to), and within it
    - `fs.py`: What a local replica does on the disk itself: the trash, and renames that never overwrite
    - `local_info.py`: What a local replica says of its files: sizes, dates, hashes
    - `moving.py`: LocalMoving a local replica's files and dirs
    - `removing.py`: LocalRemoving a local replica's files (and the dirs they leave empty)
    - `replica.py`: A local dir as a replica (LocalReplica), its files asked of the disk; what it does with them are mixins, each ...
    - `scanned.py`: A local replica with a tree of its files too (LocalDiskDirTree), scanned
- `ui/`: What dirdelta shows: its pickers (treepicker), messages, menus, previews and opening files
  - `contextmenu.py`: The file pickers' menu for when nothing's picked (:), of what can be done there with the selected file or dir,...
  - `filescreen.py`: What the two file screens have in common, the sync's (interactive_dir_sync.py) and the inbox's (inbox.py): a p...
  - `images.py`: The selected file's picture, in a file picker's preview column (picker.pick_files(images=...)): a photo or ano...
  - `messages.py`: dirdelta's messages: plain lines, printed between pickers (each picker has the terminal while it's open), and ...
  - `renaming.py`: Renaming a file or dir where it is, as vim's cc does: the file pickers' cc (of a sync, an inbox's sort, and th...
  - `sidetree.py`: The tree beside a file picker (picker.Side): another replica's dirs and files, to look through while picking, ...
  - `opening/`: Opening a picker's files with their programs (xdg-open), as if double-clicked: Ctrl-X in the inbox's and a syn...
    - `downloading.py`: An opener's queue of files, downloaded and opened one after another in the background
    - `names.py`: Opening's key, timings, colors and tags
    - `opener.py`: Opener: opens a tree's files, downloading Drive's first; its queue and status are mixins here
    - `screens.py`: Opening from a menu (confirmed on a screen of its own), and a picker's tags with opening's
    - `status.py`: What a picker shows of an opener's work: its status bar, and each file's tag
  - `picker/`: dirdelta's pickers: they run the treepicker program, from github.com/eliranle6/treepicker.
    - `command.py`: A treepicker command being made, and run: its arguments, the pipes to and from it, and the threads that serve ...
    - `files.py`: Picking files (pick_files()), and viewing them (view_files())
    - `kinds.py`: What pickers are given and give back: their options' kinds, and what a pick returns
    - `menus.py`: Menus of options (pick_option()), and what an option may be
    - `pictures.py`: The pictures of the files a picker's selection stays on
    - `places.py`: Where the user is, the screens' breadcrumbs (place(), trail())
    - `previews.py`: What's sent to treepicker's preview column
    - `running.py`: Running treepicker: its arguments, its input and output, and the threads beside it (see command.py)
    - `selection.py`: Where a picker's selection is, as treepicker says, and the keys it was told of
    - `styles.py`: Text in styles and colors, as treepicker shows it: styled(), segments(), highlighted()
    - `trees.py`: Picking a node of a tree (pick_from_tree()) or a path under a dir (pick_under_dir())
    - `updates.py`: What's sent to a running picker as it changes: how its items are shown, the status of what goes on behind it, ...
- `util/`: Small helpers: texts, programs, downloads, dry runs, EXIF dates and zips
  - `archives.py`: What's in an archive (a zip, for now), without unpacking it: for exploring one (archive_screen.py), and tellin...
  - `downloads.py`: Drive files downloaded to be read on this machine: by Claude, describing them, or by the user, opening one (in...
  - `dryrun.py`: Whether dirdelta changes files. Unless DRYRUN=0 is set it's a dry run: actions that change files (copying, rem...
  - `programs.py`: dirdelta's C++ programs (treepicker, dirdiff), from the lib/treepicker submodule: finding them.
  - `text.py`: Small texts said everywhere, said one way: counts of files, lists cut short, sizes and durations
  - `exif/`: When a photo was taken, from its EXIF data (DateTimeOriginal), read from a JPEG's header, a HEIF (HEIC) file's...
    - `dates.py`: When a photo was taken, by its format
    - `formats.py`: The files read, by extension, how much of each, and the EXIF tags and markers looked for
    - `isobmff.py`: A HEIF file's EXIF item, and a Canon CR3's CMT boxes: both ISO BMFF boxes
    - `jpeg.py`: A JPEG's EXIF segment, and a Fujifilm RAF's embedded JPEG's
    - `tiff.py`: The date in TIFF data's IFDs

### `main.py`
Argparse: `dir_a_path`, `dir_b_path` (both optional), `-x/--execute`,
`-m/--max-depth` (default 20, passed down to `localdiskdirtree.factory` as
`find -maxdepth`), `-s/--sort`. No positional path → `choose_replicas.run`, then
`dirsync_main.run` on what it chose (or `inbox.run`, for a `Sort`); one →
`dirpick_main.run`; two → `dirsync_main.run`, or with `--sort`, `inbox.run`
(the first path the inbox, the second the sorted tree). Before any of them,
`_ready()` checks that the local paths' volumes are mounted
(`mounts.ensure_mounted()`; if the user won't mount one, it quits, or goes back to
the start menu) and remembers how they are (`mounts.remember()`); what the start
menu chose is then checked to be there (`choose_replicas.are_there()`). No curses setup: a `picker.PickerError` (treepicker
missing or failing), `DriveCacheError`, `replicas.ReplicasError` or
`mounts.MountsError` exits with its message.

### `mounts.py`
The volumes local replicas are on, in `~/.config/dirdelta/mounts.json`
(`MOUNTS_FILE`, by mount point; JSON, written whole with `os.replace`), so one
that isn't mounted now (`/mnt/win`, mounted by hand; an external disk) is found
before it's scanned: an unmounted mount point is an empty dir on the root
filesystem, where the diff would say every file is missing and a live Copy
would fill the root filesystem. `remember(path)` keeps `findmnt --target`'s
mount (point, device, type, options, UUID, label), unless it's `/` or has no
UUID (a tmpfs, WSL's drives); a FUSE type (ntfs-3g's `fuseblk`) is kept as
the device's (`lsblk`: `ntfs`). `unmounted(path)` is the innermost kept mount
above the path that `os.path.ismount()` says isn't mounted. `ensure_mounted(path)`
asks, until it's mounted or the user goes back: if the disk isn't connected
(`/dev/disk/by-uuid/UUID` missing), Try again or Back; else Mount it (the option
shows the command) or Back. `mount_command()`: `mount TARGET` if fstab has a line
for it (with `sudo` unless the line has `user`/`users`), else `sudo mount -t TYPE
-o rw,OPTIONS UUID=... TARGET`: read-write (even if it was read-only), with the
filesystem's options (none of NTFS's, which are FUSE's own). sudo asks for the password
on the terminal; a failure is shown (`messages.show`) and asked about again. If
ntfs-3g refuses (Windows hibernated, or Fast Startup: "unclean file system"), the
error screen says to shut Windows down fully; and if it mounts read-only instead,
as 2022.10.3 does, exiting 0 (`_came_up_read_only()`, unless fstab's line says `ro`), a warning
says so, and the same. A read-only replica still works as a source: a sync and a sort warn, copying from it
goes on, and only what would change it is held back (`is_writable()`; `LocalReplica._is_stuck()` refuses a move out
before it starts, as between filesystems the copy would be made before the removal failed).
Only a replica's root is checked, at the start: a read-only dir in a writable replica fails file by file, and says so.
In a sort, a read-only side's actions aren't offered in its menu or to the AI (`_cant_be_done()`), and Enter in the
side tree copies from a read-only inbox. Why it's read-only is said for a volume mounted so before dirdelta started too
(`read_only_lines_of()`): Windows' only if its `hiberfil.sys` starts with `HIBR`. Asked even in a dry run (it
changes the system, not files), never done without asking.

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
a volume one of its local dirs is on isn't mounted and the user won't mount it
(`mounts.ensure_mounted()`, back to the menu), or one of its local dirs is gone (a screen says so, back to the menu; a cloud
one is checked when the sync reads Drive's file list); a slot
asks Local disk / Google Drive, then picks a dir: under `/` with
`picker.pick_under_dir(dirs_only=True, lazy=True)` (treepicker reads a dir
only when it's shown), or in the whole Drive tree (`cloud`) with
`pick_from_tree(dirs_only=True)`. Once both slots are chosen (and differ),
it returns them. After the pairs: "Sort an inbox" (the inbox, then the
sorted tree, each chosen as a slot is) and the recent sorts (`sorts`, at
most `MAX_SORTS`, by their way around: `record_sort()`), which return a
`choose_replicas.Sort(inbox, root)`. It also keeps each sorted tree's
recent dirs (`recent_dirs`, by its path: the relpaths files were moved or copied
to by "Move to...", at most `MAX_RECENT_DIRS`, `record_dir()`/`dirs_of()`),
for the inbox. Each kind is a section under a heading
(a `picker.Skipped` line, so it can't be picked; the menu starts on the
first slot, `pick_option(selected=...)`): Sync two replicas (the slots and the
favorites), Recent syncs, Sort an inbox, Recent inbox sorts; a section with
nothing in it has no heading. A blank line (`picker.BLANK`) comes between sections, and
before Quit. Choosing the sorted tree offers the
replicas the user knows first (`known_replicas()`: the favorites', the
recent pairs', the recent sorts' trees).

Marks (`styled_pair()`; `?` explains them, `help_lines()`): before a pair, its
sync state (`syncstate.py`); before each path, `SYNCED_MARK` (●) in the color of
when it was last synced (`freshness()`: green today, yellow this week, red
before), and before a Drive one `CACHE_MARK` (☁) in the color of when Drive's
file list was read. `syncstate.of(known, a, b)` is a `State` from what a sync
last found (`Replicas.note_compared()`/`comparison()`, `compared` in
`replicas.json`: how many of each one's files the other lacked, noted by the
sync menu each time both ways are found): in sync, one ahead (it has files the
other lacks, and lacks none of the other's), branched (each has files the other
lacks) or unknown, and the replicas changed since (by dirdelta, at the time of
the change, `Changes.when()`, or a later log entry), which grey its mark. It has
no screen code: `mark()`, `describe()` and `help_lines()` give marks and words
for any front end. The sync menu's first line is the state as found now
(`dirsync_main._state_line()`), and the dashboard lists the known pairs first,
under "Pairs: what's synced to what".

### `inbox/`, `claude/ai/` — sorting an inbox
`InboxSort(inbox_path, root_path)`: local dirs or cloud paths, a tree each
(`LocalReplica`, or `CloudDirTree`). Both of a kind (`is_same_kind`): a move is a
rename, by `move_files(moves, to)` (`InboxError` if the sorted
tree is in the inbox; one in the sorted tree is `_inbox_in_root`, left out of its index and side tree). One of each: a move is
`_transfer()`: the sorted tree's `copy_in(files)` (an
upload; or a download, from a `_Renamed` source that maps each file's new
relpath to the inbox's), then the inbox's `remove_files()` of the files
copied. Either way the inbox and the root are `keep_dirs()` (never removed
when left empty, never moved or trashed whole). `run()` is a loop like
`InteractiveDirSync.browse()`: `pick_files` of the inbox's files, with
Claude's descriptions as their tags (`shown_as`, through `--updates`: "name
[claude: description]" (`DESCRIBED`), searchable, or "(Claude is looking at it...)", and the status, Claude's
work, on the bottom line) and its recommendations in the preview column (sent
again as they change, `_send_previews()`), both kept in `ai.CACHE_FILE` and
loaded at each pick. Asking Claude is in the background
(`ask_in_background(relpaths, place)`: a queue and one worker thread, a batch
at a time: `_describe()` the ones without a description, then with place,
`_place()` them: their contents compared with the sorted tree's (`_compare()`),
then `ai.recommend()`; its Drive downloads and the screen's Drive changes one
at a time, `_drive_lock`), from `Ctrl-I` (`pick_files(notify_keys='\t\x18')`,
treepicker's `--notify`, `_on_key()`: the picked files, or else the selected file or dir's;
describing and placing) or the menu (Describe: describing only; Ask where:
both). `Ctrl-I` and Ask where ask anew about the files asked about before (`ask_in_background(anew=True)`,
`_forget()`: what Claude said, and the contents compared, are dropped, and `ai.describe()`/`recommend()`
skip their cache entries, `anew=`); quitting waits for it (`_finish_describing()`).
`Ctrl-I` on a dir with nothing picked (not the root) asks about the dir as a whole instead
(`ask_dir_in_background()`, a thread per dir: `_describe()` of `DIR_FILES_DESCRIBED` of its files
spread over them (`_spread()`), `_compare()` of all, `_dates()` of `DIR_FILES_DATED`, then
`ai.recommend_dir()` with an `ai.Dir`: move to a path, split, or remove, and a summary). It's kept in
`ai.json` by `ai.dir_key()` (the dir's path, file count and total size), loaded with the files'
(`_load_cached()`, `ai.cached_dirs()`), and dropped once the dir's key changes. `_shown_as()` tags the
dir (treepicker puts its `/` after the name, and draws the rest in its styles), `_dir_preview()` says
it beside it, and `_act()`, when the picked files are all of the selected dir's (`_whole_dir()`, as Enter
on it picks them), adds ASK_DIR, MOVE_DIR (to Claude's path: the files' plan keeps their paths under
it, so `move_files()` moves the dir with one rename where nothing's there, else file by file, merging),
MOVE_DIR_TO (`_dir_to_a_dir()`: into a picked dir, under its own name) and REMOVE_DIR. `Ctrl-X` (`OPEN_KEY`, `opening.KEY`)
opens the selected file (`Opener.press([selected])`; the picked ones only from the menu's Open,
which has no key; an `opening.Opener`: `xdg-open`
in a session of its own, a queue of them on a thread of its own, a Drive file downloaded first,
through `downloads.get()` and `fetch_file(progress=...)`, which asks Drive for
`PROGRESS_CHUNK_SIZE` at a time). `cc` (`renaming.KEY`, treepicker's `--expect-twice`,
`pick_files(twice_keys=)`) renames the selected file or dir (`renaming.rename()`, `_rename_selected()`:
what's known of its files goes with them, Claude's cache too, `ai.carry()`); so does a sync's
picker's (`InteractiveDirSync._rename_selected()`, which diffs anew), and the dir picker's of
where files go (`_rename_sorted_dir()`, through the sorted tree's own tree). That dir picker
(`_pick_dir()`, the sorted tree's or, `in_inbox`, the inbox's for "Move ... to another dir in the
inbox", `_move_in_inbox()`) makes a new dir in the selected one (`n`) or beside it (`o`/`O`,
`SIBLING_DIR_KEYS`); what's known of files moved in the inbox goes with them (`_carry()`). The
status bar says how far the downloads got (`Opener.status_parts()`), and each file in a tag after
its name (`Opener.tags()`, added by `opening.with_tags()` to `_shown_as()`'s, or a sync's
`hashes_screen.Marks`'s); a sync's picker has it too. The menu's Open asks on a screen of its
own (`opening.confirm()`). Every key that acts on the selection is in
the action menu too (at its end): Open (the picked files, at most `opening.MAX_OPENED`), and for a
Drive inbox "Read ... anew from Google Drive" (`Ctrl-R`'s; `_act()` returns `REFRESH_KEY` for it). Each
option a key does is shown after it, in a column (`[Ctrl-I] Ask Claude ...`: `SHORTCUTS`,
`picker.shortcut_prefixes()`), and in the inbox's menu the words saying where the files go, and the
destination's parts, are in their sources' colors, as the brackets below the menu (`_option_text()`). Enter (with none picked, the
selection: `pick_files(enter_picks_selection=True)`, treepicker's
`--enter-picks-selection`) → `_act()`, the action menu
(`NOTHING` first): describe, ask where they go, move (to Claude's dir, or a
picked one, `_choose_dir()`: the sorted tree's recent dirs first, if it has
any (`replicas.Replicas.dirs_of()`; the one moved or copied to is recorded,
`record_dir()`), else `_pick_dir()`: `pick_under_dir(dirs_only, lazy)`, or `pick_from_tree` of the sorted tree
from the cache, with `keys='n'` (`--expect`): a new dir in the selected one,
its name typed, `_new_dir()`; under the file's name, Claude's, or one typed for one file,
`_typed_name()`, `messages.ask()`, starting as Claude's or its own), copy to a
picked dir, remove (confirmed twice). A move or copy (`_approve()`)
first shows the tree it makes (`picker.view_files()`, with where each file
is from beside it; files of one name to one dir are refused), then No/Yes,
then `move_files()` / `copy_files_within()` (local `shutil.copy2`, Drive's
`files().copy`) on a progress screen. `Ctrl-R` refreshes the selected Drive
folder, as a sync's does. Copies: the inbox and the sorted tree are each a
replica of its own, with
their `elsewhere.Index`es, told of changes by their trees (`DirTree.add_listener()`), the sorted tree's built in the background and
without the inbox's files, if it's in it), and the picker runs
`elsewhere.check_contents()` on the selection, as a sync's does
(`sends_previews=False`: the inbox's own previews show `_checked`); before
Claude is asked where files go, `check_all()` compares the picked ones. A file
with the same contents as one of the sorted tree's is a copy (`_copies()`,
highlighted `SURELY_A_COPY`); Claude is told (`ai.recommend(copies=...)`) and
may answer `action: 'remove'` (for junk too, with no copies: what Claude says,
by the names, sizes and descriptions it's given), and the copies (by their contents, whatever Claude says) are offered as
"Remove N of the M files that are copies of files in X". After a move or copy, the sorted tree's index has the file.
Logs (see `dirsync_main.py` below): only the sorted tree has one (an inbox has no
`last_update.txt`, since 2026-10-31). `inbox.run()` notes it seen (`replicalog.note_seen()`,
`InboxSort.log_trees()`: a tree of it, apart from the one moves happen in), the sort notes what it
does to it live in `InboxSort.changes` ('added' from the inbox, 'copied', 'moved' by a dir's
rename), and once it's quit, `replicalog.offer_entries()`.
Junk (`_junk()`): by its name or size (`junk.find()` at each pick, `_junk_by_name`: system,
temporary, partly downloaded, empty files, installers, archives unpacked beside them), or a
`remove` of Claude's for a file with no copies. Shown as `[junk? why]` (`JUNK_BY_NAME`) or
`[claude: junk? why]` after the name, and `MAYBE_JUNK` (yellow) in the preview; "Remove N of the M
files that look like junk" (`REMOVE_JUNK`) is `_remove(to_trash=True)`: a local inbox's files go
to the desktop's trash (`LocalDiskDirTree.trashing()`: `_remove_file()` runs `gio trash`), Drive's
to its trash as always.

### The inbox's action menu (`InboxSort._act()`)
Only what can be done is offered (no greyed-out options), and not two that do
the same (Claude's dir under the file's own name, when Claude keeps the name;
Claude's names, when it renames none). For one file, the header names it and
each destination ends with its name. Options are colored by what they do
(`VERB_COLORS`: Claude's in magenta, moves blue, the copy cyan, removals red),
and below the menu (`_destination_lines()`) the selected one says it again: its
verb as a label in that color, the destination path, and under each part of
the path a bracket saying where it's from (`SORTED_TREE`, `CLAUDES_DIR`,
`CLAUDES_NAME` in magenta, `YOUR_DIR`/`YOUR_NAME` in yellow, `OWN_NAME` in
green; `_bracket()` takes the longest name that fits, `_fitting()` cuts a long
sorted tree's root to `.../its-name/`).

### `replicainfo.py`
What's known of a replica, as the screens say it (`known_lines()`: its log's
last entry, when it was synced and changed; `freshness()`, `SYNCED_MARK`,
`CACHE_MARK`, `cache_time()`, `path_marks_help()`), for the start menu, the
sync's menu and the dashboard (`choose_replicas` keeps their old names as
aliases), so `choose_replicas` and `hashes_screen` don't import each other for it.

### `hashcache.py`
Local files' contents' hashes. A local replica's are kept in it, in
`meta/hashes.sqlite` (`paths.META_DIR`, `META_NAME`; by their paths in the
replica, so they're found wherever its disk is mounted), from when
`use_replica(root)` is called (a sync's local replicas, a sort's local sorted
tree): it makes the database there unless it's a dry run or the replica is
read-only, and moves `CACHE_FILE`'s hashes of its files into it (once: they're
deleted there). `meta/` is left out of the diffs (`interactive_dir_sync.find_missing()`)
and of hashing (`Job.scan()`). Others' (an inbox not in its sorted tree, a
read-only replica) are in `~/.cache/dirdelta/hashes.sqlite`
(`CACHE_FILE`, by absolute paths; `_where()` picks the database). Each is SQLite in WAL mode: a table `files(path, size, mtime_ns,
hashes)`, the hashes as JSON), by path, with the size and mtime (ns) they were
of: a hash of a file changed since isn't given. `LocalDiskDirTree.content_hashes()` reads
it first and keeps what it works out; `elsewhere._same_contents()` compares
two local files by it when both are kept, else reads them side by side (and
keeps both hashes when they're the same). `known_under(dir)` gives a dir's in
one query (a job's scan checks them against find's sizes and times); `move()`
keeps them when dirdelta moves a file or dir, and a local copy gets its
source's. Committed at most every `SAVE_INTERVAL` (a timer), and at exit:
SQLite rather than JSON, so hashing a whole replica doesn't rewrite a big file
again and again.

### The screens' layout (every picker, menu and progress screen)
The top says what the screen is: a menu's tree root is its breadcrumbs
(`picker.trail()`: `dirdelta > Sync a ⇄ b > What to do`, from `picker.place()`
and `pick_option(title=...)`; replicas by `paths.short_names()`), with the
header (the question, or what the files are) above it; never keys. The bottom
is the status bar (the mode's label, the caller's labels, statuses such as
hashing's, counts, the selection) and, under it, the keys row: treepicker's
main keys, the caller's (`key_hints=[(key, what it does)]`: `--key`), `/`, `?`
(with `help_lines`, e.g. the tags' legend: `--help-line`) and `q`, which
`picker._run()` names "quit" on the start menu and "back" anywhere else (going
back from a sync or a sort, or "Nothing: go back" before one, returns to the
start menu: `main._run()`'s loop; only the start menu's Quit quits). What a picker's threads raise
goes to `picker.ERRORS_LOG`, not the screen, and a failing `shown_as` puts a red
label on the status bar.

### `hashes/hashing/`, `screens/hashes_screen/`
`hashing.Job(root)`: a local replica's hashing. `scan()` lists its files (one
`find -type f -printf '%s %T@ %P'`) and takes the ones the hash cache has with
the same size and mtime as hashed; `start()`/`pause()`; `first(relpaths)` puts
files ahead (a sync's picker puts the files it shows). One `_Pool` of
`nr_workers()` threads (physical cores − 1) serves all jobs in turn; a job on a
spinning disk (`is_rotational()`) uses one at a time. Each worker lowers its
own CPU (nice 19) and I/O (idle, `ioprio_set`) priority, reads a file in
`READ_SIZE` chunks (pausing between them), checks it didn't change while read,
drops it from the page cache, and puts its SHA-1 in the hash cache; then tells
the job's subscribers (`subscribe()`: `elsewhere.Index`, `hashes_screen.Marks`).
`progress()` (a `Progress`: files, bytes, current files, rate over
`RATE_WINDOW`, failures). What's shown of it is `hashes_screen/status.py`'s
(imported as `hash_status`): `percent()` (of bytes), `color()` (red < 34%,
orange < 67%, yellow, green when done), `status_text()`, `tag()` (`[● hashed]`, `[◐ hashing now]`, `[○ not hashed yet]`,
`[✕ couldn't be hashed]`, after a file's name in the pickers).
Jobs are kept by root (`job()`, `job_for()`), for the whole run.

`hashes_screen.prepare(replicas)` scans the local replicas' jobs; `offer(jobs)`
asks whether to hash what's left (now and wait, `wait()`, a progress screen
that Ctrl-C leaves while it goes on; in the background; or not now), and starts
the jobs all hashed already, so later files are hashed too. `dashboard(jobs,
known, other_paths)`, the "Replicas dashboard" (the sync's menu, `#` in the
file pickers, and the start menu's, of every known replica): a menu, live
through `shown_as`, of each replica's files (how many, their size), what
`replicas.json` knows of it, and its job's bar, state, current
file, failures, Pause/Resume, its files (`view_files()`: a tree of them with
their tags, the selected one's hash beside it) and a new scan; and each cloud
replica's Drive hashes (how many have SHA-1, SHA-256). `Marks`: a picker's
`shown_as` that puts each file's tag after its name (only the changed ones
after the first time) and the jobs' statuses on the bottom line
(`picker.status()`: treepicker's colored status labels).
`ai.describe()` asks Claude about `ai.File`s (relpath, a local path
to read, size), `BATCH_SIZE` a request, reading them; `ai.recommend()` asks
Claude where they go by their names, sizes and descriptions
(`_place()` gets the missing descriptions first), reading nothing (no tools); a batch that fails is asked again a file at a time. Both through the
Claude Agent
SDK, both of `MODEL` (Haiku)
(`run_query()`: `query()` with tools and allowed tools only `Read`,
`permission_mode='dontAsk'`, no settings sources, the files' dirs as `cwd` and
`add_dirs`, and `output_format` a JSON schema of the answers by file number).
A Drive file is downloaded first (one at a time), into `downloads.py`'s cache
(`~/.cache/dirdelta/downloads`, `DOWNLOADS_DIR`: a dir per file, by its cloud
path and size, under its own name, so Claude, let read the files' dirs, reads
only it; the least recently used go beyond `MAX_BYTES`, 2 GB), kept for
`Ctrl-X` and the next time; one over
`MAX_READ_SIZE`, or a Google file, isn't read (Claude goes by its name).
Recommendations are given the sorted tree's dirs (at most `MAX_DIRS_GIVEN`,
the shallowest; not the inbox's, if it's in it), each with a few of its
files' names (`NAMES_PER_DIR`), and recommend a path (a dir and a name, the
file's own or a better one in that dir's style), cleaned (`..` refused, the
file's extension kept): `ai.recommended_path()` (one cached without a
path, by an older dirdelta, is asked for again). Answers are cached by the file's contents' SHA-1, once it's known
(`known_hash()`, nothing read for it; so they go with a moved file, and copies share them), else by its path and size, which
after a move or copy are copied to their new paths' keys (`ai.carry()`); the cache's read-modify-writes are under one lock
(recommendations also by the sorted tree), `AIError` if Claude can't be
asked.

### `sidetree.py`
`Listing` keeps a replica's side tree between its picker's showings, listed anew when its tree tells it of a change (or `invalidate()`); changes made outside dirdelta show after `Ctrl-R` (in either tree of the picker, for local replicas too), or the next time the picker is entered. `Ctrl-R` reads anew what's on Drive, and only without a Drive replica the local ones, unless pressed in a local side tree, which reads that one. It also drops those replicas' indexes and comparisons, rescans their hashing jobs (the side tree's replica's with the listing's own scan if both go as deep, `hashes_screen.scan_with_listing()`: the side tree goes down to its replica's `max_depth`) and, in a sync, diffs them again, the other way's comparisons dropped too; in the side tree (`Side.keys`) it does so for that replica only (on Drive, the folder selected there). `Side.start` (treepicker's `--side-start`) keeps the user in the side tree after `Ctrl-R`, and after a sync's other keys there; not after a sort's Enter there, since the next files to pick are in the inbox's tree.

### `localscan.py`
`scan(root, max_depth, progress)` is the one listing of a local dir (one `find`, stderr to a
temp file): `Scan.entries`, `{relpath: (kind, size, mtime_ns)}`, and `Scan.errors`. The local
trees, hashing's job, the inbox's listing and dirs, and the side tree all use it.

### `replicafactory.py`
`create_dirtree_from_arg(rootpath)` is the single dispatch point deciding
cloud vs local, with `paths.is_cloud_path()`: a path is "cloud" iff its
first path component is literally the string `"cloud"` (`paths.py`, which
also has `path_in_cloud()`, used by `CloudDirTree`). `validate_dir` checks
the path is an existing directory for the local case, raising `NotADirError`
otherwise (`main` says it and exits).

### `trees/entries.py`, `trees/dirtree/` — the core data structure
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

### `trees/localdiskdirtree/`
`LocalReplica` asks the disk for what it has and keeps no tree of it (two local replicas, an inbox);
`LocalDiskDirTree`, one that also keeps a tree (the local side of a sync with Drive), is told of each change
by `_file_added()` and the like. `filescreen.py` has what the sync's and the inbox's file screens share.

`LocalDiskDirTree(DirTree)`. `factory(filesystem_dirpath, max_depth=None,
silent=False)` builds the tree then calls `update_from_filesystem`, which
runs one `find ROOT -mindepth 1 [-maxdepth N] -printf '%y %p\0'` (rather
than walking Python-side) and adds its files and dirs (other types, like
symlinks, are skipped; names are decoded with `os.fsdecode`, so names that
aren't UTF-8 work). find's error messages (paths it couldn't read, e.g.
`Permission denied`) are kept in `scan_errors`. Building the tree, not
find, is most of the time (~2.8s for /usr/share's 119k entries).

`copy_in(files)` (or `copy_inner_entries_from_dirtree(dirtree)`, of its files) — for each of the given
files, calls `add_file_by_relpath` to add the node to `self`'s tree, then
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

### `drive/clouddirtree/` / `drive/drivecache/` / `drive/clouddirtreefactory.py`
Cloud state is never queried live per-scan. Instead:
1. `replicafactory.create_dirtree_from_arg` calls `factory_interactive(rootpath)`
   for any path whose first component is `cloud`. It ensures a cache exists
   (`drivecache.exists()`: `~/.cache/dirdelta/files.sqlite`, in WAL mode, with one connection kept open so a write is ~0.2ms, into which an old `files.txt` is imported, then kept as `.bak`), prompting
   the user (`picker.pick_option`) to refresh the replica's folder in it if it
   already exists ("Refresh cloud/X from Google Drive"; the prompt says if the
   cache may be out of date there, see the stale marker below), or to continue
   with the cache, or to do nothing ("Nothing: go back", the first option,
   selected at first, and `q`): then it's None, and the caller goes back (a
   sync or picker mode ends, the no-path menu shows again).
2. `clouddirtree.refresh_cache(folder_path)` (a path in Drive, `/` for all
   of My Drive) reads the folder anew, a request at a time: My Drive's root folder's id
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
The same refresh is the main menu's "Refresh cloud/X file list from Google Drive"
(all of the replica) and the file picker's `Ctrl-R` key (the selected folder, or
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
(`with drivecache.changing(path):`, which unmarks it when the change ends, or
fails cleanly, e.g. an `HttpError`, but not on a Ctrl-C unless the work under
way was `settled` first; `mark_stale(path)`, a line with its path in Drive in a
`files.stale` file next to the cache), and the mark is taken away once
the change is in the cache (`unmark_stale()`), unless it was there before: a
change cut off in the middle (e.g. Ctrl-C during an upload, when Drive may
or may not have the file) leaves it, so the next run's refresh prompt for a
replica at, above or under that folder says the cache may be out of date
there, and a refresh of that folder (or above it) clears the mark
(`mark_fresh(path)`). A marker from before the paths were written is all of
Drive (`/`).

When each folder's list in the cache was last made as Drive has it is kept in
`files.times` (`drivecache.note_updated()`/`updated()`: a refresh of it,
or a change dirdelta made in it, `CloudDirTree._cache_add()`, but not in its
`meta/`), with the copy last uploaded to it (`note_uploaded()`/`uploaded()`:
its modifiedTime, and `updated()` as of then). `drivemeta.py` keeps a Drive
replica's list in it, `meta/files.jsonl` (a header line, `HEADER_KEY`, with the
folder's path and id and My Drive's root id, then the cache's lines under the
folder, `drivecache.under()`, without `meta/`): `drivemeta.kept([(path,
tree)])`, around a sync's menu and an inbox's sort (for its sorted tree),
first `check()`s it (two `files().list` requests: `meta/`, then the file in
it) and, if it's newer than `updated()` and not this cache's own upload,
downloads it into the cache (`replace_under()`) and rebuilds the tree
(`reload_from_cache()`); then an `Uploader` (a thread) uploads it every
`UPLOAD_INTERVAL` (60s) if `updated()` is later than the last upload's, and
`kept()` uploads it once more at the end (not in a dry run). Its errors go to
`picker.ERRORS_LOG`; the last one is said on a screen. The start menu's and the
dashboard's ☁ freshness is the folder's `updated()`, if known
(`choose_replicas.cache_time(path)`).

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
Python trees took ~6s). `programs.find(name)` finds treepicker and
dirdiff: this copy's build (`DIRDELTA_PROGRAMS_DIR`, set by `bin/python` and make), next to the running python, `PATH`.

### `differing/`
The files both replicas have at the same path that differ (`docs/plans.md`, plan A): `find(src, dst)`
lists both (`listed('sha1')`: size and known hash of each, a local one by one `find` and one query of
the hash cache) and returns `{relpath: Change(src_size, dst_size, src_mtime, dst_mtime, by)}`, `by`
being `BY_SIZE`, or `BY_CONTENTS` for the same size with both hashes known and different. One
unknown: not counted, but in the result's `uncompared` (a `Changes`, the dict with that list), unless
`find()`'s `compared` (`{relpath: (src_size, dst_size, is_same)}`, kept by the sync menu) settles it
while both sizes are still those. The sync menu's "Compare the files of the same size ..."
(`sync/comparing.py`'s `compare()`, on a progress screen) compares the uncompared ones by
`elsewhere.same_contents()` (two local files side by side, a Drive file by its hash) into `compared`,
then finds them again. And while the local replicas are hashed, `comparing.AsHashed` has the menu's
`shown_as` find them again (only them, `ways.find_differing()`) once more files were hashed and a job
is done, or `REFIND_INTERVAL` (30 s) went by, as long as some are uncompared; `compared` is
cleared when a replica is rescanned or read anew. `flipped()` is the other way's; `tag()`, `styled_tag()` and `preview_lines()` are what
the pickers show, their mark and color by `newer()` (modification times, within 2 s the same):
`>` blue newer here, `<` red older here, `≠` yellow when the times don't say (`mark()`, `style()`). `sync/ways.py`'s
`find_all()` finds them once per pair, on a thread, with both ways' diffs (`Way.differs`, a future, the second
way's flipped); `InteractiveDirSync` lists them with the missing files (`_listed()`, kept in
`differs`), adds their tags to `shown_as` (once, then with what's sent again) and their previews
before `elsewhere`'s (`_find_previews()`), and leaves them out of what's about the missing ones
(Rename, `elsewhere`'s previews and checks, Ask AI). Copy over one runs inside the destination's
`replacing()` (`DirTree`): `LocalReplica._replace_file()` copies to `.dirdelta-part.NAME` next to
it, moves the old one to the trash (`gio trash`), then renames the copy over it; Drive's
`_upload()` with the file's id does `files.update` with the new media (a new version). Either tells
its listeners remove then add. Copy back (`COPY_BACK`, "Replace it with its version in B") is the
same into src (`_copy_back()`); which were done is what an `_Added` listener heard.

### `sync/way/` (`interactive_dir_sync.py` and its mixins)
`InteractiveDirSync(src, dst)`. Its diff (`_missing()`): for two local dirs,
`dirdiff`, run anew for each action (so the dirs' own trees are never
scanned: `dirsync_main` makes them empty, and there's no stale scan), with a
warning screen if couldn't read everything; with a cloud replica, the
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
  moved, `cant_move()`); then what the picker's keys do on the selection, so
  each is in the menu too: Open (`opening.Opener`, the picked files, as
  `Ctrl-X`, a `--notify` key, does: see `inbox.py` above), and with a cloud replica Read
  anew from Drive (`Ctrl-R`'s: `_act()` returns `REFRESH_KEY`, and `browse()`
  does what the key does) → its confirmation (`pick_option(['No', 'Yes'])`, No
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
  that's Drive's, the file picker's `Ctrl-R` (`REFRESH_KEY`, `pick_files(keys='\x12')`)
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
  keeps the file's id, then the folders left empty trashed, `_moved()`, once
  Drive says they hold nothing more). A dir all of whose files move into
  one other dir at the same relative paths, where nothing is yet, moves as
  one (`dir_moves()`, `_move_dir()`: one `os.rename`, or one
  `files().update` of the folder), as the confirmation says.
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

### `sync/dirsync_main.py` (with `ways.py`, `options.py`) / `dirpick_main.py`
Before the menu, `run()` reads each replica's log (`replicalog.note_seen()`, `replicalog.read()`: its
`last_update.txt`, a Drive one downloaded through `downloads.get()`) and notes
it in `replicas.json` (`Replicas.note_seen()`, by `replicalog.identity()`: a local
replica's filesystem UUID, `mounts.current_mount()`, and its path in it; a Drive
one's My Drive root id, `drivecache.root_id()`, and its path). The ways note
what they change live in a `replicalog.Changes` (`InteractiveDirSync(changes=...)`:
copied, removed, moved, added up per replica), and after going back,
`replicalog.offer_entries()` offers each changed replica an entry for its log
(`replicalog.entry_line()`: today's date and `Changes.summary()`): added to its
log, only its (`replicalog.write()`: a local file replaced at once, a
Drive one by `CloudDirTree.write_file()`, a new version of it, or a new file),
edited first (`messages.ask()`), or not; `note_changed()`/`note_entry()` keep
when and what. `replicalog.parse()`/`last_entry()` read the log's format
(`DD.MM.YYYY - text`, its continuation lines after it; what it can't parse is
kept as text). `choose_replicas` shows each pair's paths with when they were
last updated (`pair_label(known=...)`), and the "Replicas dashboard"
(`hashes_screen.dashboard(other_paths=known_paths())`): each one's last entry,
last sync and change (`known_lines()`), whether its disk is connected
(`replicalog.is_disk_connected()`), and its hashes.

Thin wiring: for two local dirs, make their `LocalDiskDirTree`s without
scanning them (each action diffs them with dirdiff, see below); else build
both `DirTree`s, warn (`scan_errors_warning`, shown with
`messages.show()`) about each local one whose scan couldn't read everything,
since its diff may then be wrong,
present a top-level menu (`_sync`: a loop of `picker.pick_option()` over
`_Action`s, each way's "Files in A, not in B", an `InteractiveDirSync(src,
dst, missing, src_index, dst_index)`'s `browse()`, until "Back to the start
menu" or `q`: a sync never quits dirdelta, and one given two paths shows the start
menu after it too). Each
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
replica also gets "Refresh cloud/X file list from Google Drive", for when Drive changed
since the cache was made: `interactive_dir_sync.refresh_replica()`, which runs
`CloudDirTree.refresh_from_drive()` (see `clouddirtree.py` above), and says on
a screen if it fails (an `HttpError`, an `OSError` such as no network, a
`DriveCacheError`, or Ctrl-C), else it drops that replica's `Index` and both
ways are found again. Given a `Replicas` (as `run` does), the menu also has
"Add to favorites" (or "Remove from favorites") before Back, which saves the
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
screen, on a terminal, laid out as the pickers are: the title alone on the top
line, a scroll region (`ESC[2;H-2r`) for the lines under it, and at the bottom
a status bar (the mode's label, then Working/Done/Stopped: `_bottom()`) and a
keys row (`Ctrl-C stop`, then `Enter continue`; `ask()`'s `Enter done`,
`Ctrl-C back`). It catches Ctrl-C, and at the end waits for Enter. Actions that catch Ctrl-C to say
how far they got (copying, removing) call `note_stopped()`. Without a
terminal it only prints.

### `dryrun.py`
`DRYRUN` (true unless `DRYRUN=0` is set), read at each use, and `label()`:
("DRY RUN", "green") or ("LIVE", "red"), which `picker.py` passes to every
treepicker run (`--label`, `--label-color`: at the start of its bottom line)
and `interactive_dir_sync.py` to the progress screen (its status bar).
Copy's and Remove's file picker and confirmation add their own label after
it (`InteractiveDirSync.LABELS`: COPY in blue, REMOVE in magenta).

### `matching/elsewhere/`, `util/exif/`
`Index(replica)`: a replica's files by name (`{name: {relpath: size}}`, the
names in each dir, the big ones by size, `RENAMED_MIN_SIZE`, and those whose
hashes are known without reading them, by hash: Drive's, once built, and a
local replica's hashing job's, which come as they're hashed: `_take_hashes()`
subscribes to the job once there's one, `take_new()` says which came,
`hash_coverage()` how much of it has them), built once
from its `files_by_name(progress)` and then kept up to date by `add()`,
`remove()` and `move()` as files are copied, removed and moved (or dropped
with `invalidate()` after a refresh); it also keeps the dates taken and the
contents' hashes worked out. The files by name come from: a `DirTree`'s
nodes, a `CloudDirTree`'s nodes with the cache's sizes (a same-named file's
`___DUP__` relpath under its real name), and a `LocalDiskDirTree`'s one
`find -type f -printf '%s %P'` of the dir (its tree may not be scanned: see
dirdiff), read as it goes; each calls `progress(count)` now and then.

A missing file's candidates (`_Matcher.matches()`) are the index's files of
its name, for a big file, all of its size with other names, and once its
contents are compared, or its hash is known without reading it (`known_same()`,
with the src's `Index`: its job's hashes or Drive's), the ones the index has by
its hash (any name and size); ranked (`_unlikeliness()`) by: the same contents, the same name, the
same size, the same date taken, the most of its siblings in the candidate's
dir (a few of its dir's missing files, `SIBLINGS_TRIED`, looked up once per
pair of dirs), the same modification time (within `SAME_TIME`), then the
closest size. Once compared, one with the same contents drops the others, and
one of another name with other contents is dropped. `sure_match()`: of the
ones with the same contents, the only one (or the one with the most
siblings); else the only one of the same name and size whose contents weren't
found to be other (and the same date taken). Its preview line is
highlighted (`SURELY_MOVED`, `SURELY_RENAMED`: `picker.highlighted()`).

`find_previews(relpaths, src, index, send, checked)`, run by
`picker.pick_files()` on a thread of its own while the picker is shown, builds
the index if it isn't, then sends each missing file's preview (`_preview()`:
its size, date taken and modification time, then its candidates of its name,
then "Of its size, another name", each with its dir, size, date, time ("the
same", "newer", "older"), siblings found and contents), every `SEND_INTERVAL`
(0.1s), with how far it's got as the text of the files not done yet ("Listed N
of its files", then "Matched X of Y files"). `send()` raises
`picker.PickerClosed` once the picker is gone, which stops it (and the `find`).
`check_contents()` runs too, on another thread (`pick_files(on_selection=...)`,
fed by treepicker's `--selection`): for the selected file, once the index is
built, it sends its preview at once, then compares its contents with its
same-sized candidates' and looks its hash up in the index if it has hashes
(`_check()`, `_same_contents()`: two local files read
side by side up to where they differ, no hash; with a Drive file, the fastest
hash Drive has for it, SHA-1 else SHA-256, worked out for the local one),
stopped when the selection moves on, notes the results in the way's `checked`
(`{relpath: {candidate: whether the same}}`, kept by `dirsync_main._Way`,
cleared by a refresh) and sends the preview again. Each file is compared once.
Rename uses `may_be_elsewhere()` (sure, or with candidates to compare) for its
menu count, then `check_all()` (on a progress screen, Ctrl-C stops it) for
the picked files not compared yet, then `sure_matches()`.

Dates taken are the replicas' `date_taken()`: Drive's
`imageMediaMetadata.time`, or a local photo's EXIF `DateTimeOriginal`
(`exif.date_taken()`: a JPEG's header up to its EXIF segment, a HEIF
file's EXIF item, found through its `meta` box's `iinf` and `iloc`, a
TIFF-based raw's start, a Canon CR3's `CMT2` (then `CMT1`) box in its `moov`
box's Canon `uuid` box, or a Fujifilm RAF's embedded JPEG), read
only for files with candidates. Modification times are `modified_time()`:
`lstat` locally, Drive's `modifiedTime`; copies keep them (`shutil.copy2`,
`os.utime` after a download, `modifiedTime` in an upload's body).

### `ui/picker/`
Runs `treepicker` (from github.com/eliranle6/treepicker; found by
`programs.find()`) as a subprocess for each pick, fzf-style: treepicker
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
  for the threads before returning. `images(relpath, max_width, max_height)`, on a thread of its own,
  makes the picture of the node the selection stays on (`IMAGE_DELAY`), once (`MAX_IMAGES_SENT`), sent
  through the same pipe (`\x03PATH\tW H RRGGBB...`): treepicker scales it to the rows the column's
  text leaves, and draws it with half blocks in 256 colors (see `images.py`).
- `pick_under_dir(dirpath, max_depth, dirs_only, lazy, header)`:
  `treepicker [--max-depth N] [--dirs-only] [--lazy] DIR`.
- `pick_option(options, header)`: `treepicker --list`, for menus.
Names are passed as bytes with `surrogateescape`, so non-UTF-8 file names
round-trip. Tests (`tests/test_picker.py`) run a fake treepicker script.

### `images.py`
The selected file's picture, below the preview column's text in the sync's and the inbox's file
pickers (`images.of_replica()`, their `pick_files(images=...)`): a local image by Pillow (decoded at a
fraction of its size with `draft()`, turned by its EXIF orientation, transparency on black), a PDF's
first page by `pdftoppm`, a Drive file's thumbnail (`CloudDirTree.thumbnail()`: its `thumbnailLink`,
asked for at the size wanted, got with the login by `driveapi.get_url()`). As big as the whole
screen can show (`picker._image_box()`: the terminal's width and twice its rows, for treepicker's `z`,
which shows it on the whole screen; it's made smaller for the column there), sent as hex RGB.
Half blocks rather than a terminal graphics protocol (sixel, kitty's): they're characters curses
draws like the rest, so the picture never covers the tree, the side tree or the bottom lines, and
goes with them on a redraw or resize; and every 256-color terminal shows them. No Pillow: no pictures.
A portrait one goes beside the text, on the column's right half; a landscape one below it. `i`
switches them off and on (`picker._Images.toggle()`), kept in `~/.config/dirdelta/settings.json`
(`settings.py`).

## What replicas are called: `replicanames.py`, `label_screen.py`

`replicanames.full()` says which disk or account a replica is on (`LocalDisk(ABC):/path`, `Cloud(user):/path`), or
its label; `short_names()` and `labeled()` are for where there's less room, or the paths are what's listed. Labels are
in `Replicas.labels`, by `label_key()`: each replica's identity (a local one's disk's UUID and path there, a Drive one's account and path). It reads
them from the file when it changed, so nothing need be passed around; `drivemeta.check()` notes the account's user
name in `files.times`, so naming a replica asks nothing of Drive. `identity()` moved here from `replicalog.py`.
The sync menu labels its two replicas, and the dashboard has an option for each replica it lists (not one that isn't
mounted or there: what its path is on now isn't its disk); both run `label_screen.run()`.

## The file pickers' `:` menu: `contextmenu.py`

With nothing picked, `:` shows a menu of `Entry`s (a key's name, what it does, what's returned), which
`InteractiveDirSync._context_menu()` and `InboxSort._context_menu()` make for the selected relpath, leaving
out what doesn't apply (opening a dir, renaming the root, reading anew what isn't Drive's). What's chosen
comes back as its key, and the picker's loop goes on as if it was pressed. What only treepicker does (search,
a range...) can't be done from a menu, so it's shown as lines that can't be chosen. With files picked, it's
Enter's menu.

## Exploring a zip: `archives.py`, `archive_screen.py`

`archives.members()` lists a zip's files (`Member`s) without unpacking it, and shows nothing;
`archive_screen.explore()` shows them with `picker.view_files()`. The sync and the sort offer it on a selected
`.zip`: their `e` key, and their `:` and Enter menus. A Drive zip is downloaded first (`Opener.local_path()`).

## Asking AI: `aiplan.py`, `aiplan_screen.py`

The user says what to do with files in their own words, and the AI answers with a plan to review.
`aiplan.py` has no UI, so another GUI can use it as it is: a `Task` (the `File`s to choose from, what's
known of each, the `Action`s the caller offers, others it may act on) and what the user said make a
`Plan` (its `answer` to a question, `Step`s, and what was `left_out` and why). `Task.focus` is what the user is
on: of those, `aiplan` tells it what's in a zip (`archives.py`) and lets it read the others, with the Read tool. The AI answers by the files' numbers, and all it says is
checked: only actions offered, only files it was told of, one step per file, no target that's taken, in
`meta/`, outside the tree, or the target of another step, and each `Action.check` the caller gives.
It goes through `ai.ask()`, so another provider is a change there. It reads nothing.
`aiplan_screen.py` asks what to do, and shows the plan as a `pick_files()` tree, by kind, all picked.
`InteractiveDirSync._ask_ai()` and `InboxSort._ask_ai()` build the `Task` and do the approved steps through
the same functions and confirmations as their menus.

## `lib/treepicker/` — treepicker and dirdiff (git submodule)

The C++ tree picker dirdelta runs, and `dirdiff` (github.com/eliranle6/treepicker;
its README and `--help` describe them). `make build` builds them in
the build dir (see `bin/builddir`); `make install`/`make deploy` copy them next to the
environment's python, where `programs.find()` looks first. The Python picker
library that was the UI before (with `cursesswitch`) was
removed on 2026-10-24.
