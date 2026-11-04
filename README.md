# Usage

## Synchronizing two directories
```
dirdelta directory_a_path directory_b_path
```

## Exploring a directory
```
dirdelta directory_path
```

## Sorting an inbox
```
dirdelta --sort inbox_path sorted_tree_path
```
(or "Sort an inbox" in the menu of a run without paths; it remembers the recent ones)

# Development

## Setup

dirdelta is Python 3, plus its picker, which is C++ and built with `make`: you can run it straight
from the source tree, or install it (see below). From the repo root:

```bash
git clone --recursive https://github.com/eliranle6/dirdelta && cd dirdelta
git submodule update --init       # fetches lib/treepicker (treepicker), if cloned without --recursive
make venv                         # dirdelta's dependencies
make                              # builds treepicker: needs g++ and libncurses-dev
```

dirdelta's pickers and menus are `treepicker`, and it diffs two local dirs with `dirdiff`: C++
programs from [treepicker](https://github.com/eliranle6/treepicker) (see `docs/treepicker-integration.md`), a
submodule at `lib/treepicker`.

Nothing generated goes in the repo, so it can be copied to another dir as it is: `bin/builddir` says
where it goes, `~/.cache/dirdelta-build/<this copy's path>/` (the programs, the bytecode, what's made
while installing; `DIRDELTA_BUILD_DIR` overrides it), with one `venv` beside those, shared by all the
copies. A copy somewhere else needs only a `make` of its own. `bin/python` runs Python with all of it
found, and is how dirdelta runs from the source tree.

Development tasks are Makefile targets (`make help` lists them). They use `make venv`'s automatically
when it exists, and otherwise whichever `python3` is on your `PATH`, so an already activated venv
works too. `make PYTHON=/path/to/python3 ...` overrides that.

## Running from source

Run the `dirdelta` package as a module from the repo root (after `make`, which builds treepicker):

```bash
bin/python -m dirdelta --help
```

Work on copies of the sample trees in `tests/fixtures`, since Remove deletes real files:

```bash
rm -rf /tmp/dd && cp -r tests/fixtures /tmp/dd
```

### Choosing what to sync (no paths)

```bash
bin/python -m dirdelta      # or bin/sync.sh
```

A menu: "Replica A" and "Replica B", each `<none: press Enter to choose one>` until chosen (a local
dir, browsed from `/`, or a Google Drive folder), then your favorite pairs and the recent ones.
Choosing a pair, or both replicas, goes on to the sync menu below, which also has "Add to favorites"
(or "Remove from favorites"). Every sync's pair is kept in `~/.config/dirdelta/replicas.json` (the
latest first, each pair once, either way around), which you can also edit by hand.

A local replica on a volume of its own (a partition mounted by hand, like `/mnt/win`, or an external
disk) has its mount remembered in `~/.config/dirdelta/mounts.json`. When it's used again and the
volume isn't mounted (its mount point would be an empty dir, where every file looks missing),
dirdelta asks to mount it where it was, by its UUID, showing the command (`sudo mount ...`, or
`mount TARGET` if `/etc/fstab` has it), or to connect its disk first; Back goes back to the menu. It's mounted
read-write. A Windows partition that Windows left hibernated (or with Fast Startup) can't be: the
error says to start Windows and shut it down fully.

Its sections, each under a grey heading: "Sync two replicas" (the two slots and the favorites),
"Recent syncs", "Sort an inbox into a sorted tree" (a new sort: choose the inbox, then the sorted
tree), and "Recent inbox sorts", with a blank line between them (and before Quit).

### Sorting an inbox

```bash
bin/python -m dirdelta --sort cloud/unsorted cloud/eliran
```

An inbox is a dir of files not sorted yet; the sorted tree is where they go (local dirs or Google
Drive folders; choosing it, the replicas you sync are offered too). The inbox's picker works like a sync's: pick files with `Space`, press
`Enter` (with none picked, it picks the selected file, or a dir's files), and choose what to do with
them, with "Nothing" selected first:

- `Ctrl-I` in the picker, on the picked files (or else the selected file or dir): all of what's
  below, describing them and saying where they go, in the background. Files Claude was asked
  about before are asked about anew (and compared with the sorted tree again), since they may have
  changed; so does the menu's "Ask Claude where" (marked `[Ctrl-I]`).
- `Ctrl-X` in the picker opens the selected file (or dir) with its program (`xdg-open`), as a
  double-click would; "Open" in the menu opens the picked files (up to 10), and has no key (a
  sync's picker has both too). A Drive file is downloaded first, into
  `~/.cache/dirdelta/downloads` (also where the files Claude reads are downloaded to), so it's
  downloaded once (the least recently used go beyond 2 GB). More than one to download is asked
  about first, on a screen of its own. Then they're downloaded in the background, one after another: the status bar says how far it got in all ("Downloading to open:
  2 of 3 files, 55% (16.0 MB of 29.0 MB)"), and each file in a tag after its name: `[↓ waiting]`,
  `[↓ 35%]`, `[↓ opened]` (or `[↓ failed]`).
- `cc` in the picker renames the selected file or dir (a dir with all in it), as vim's `cc`: its
  new name is typed, starting as its own (what Claude said of it goes with it). The same in a
  sync's pickers, and in the dir picker of where files go (the sorted tree's dirs, but the inbox's).
  In that dir picker, `n` makes a new dir in the selected one, and `o`/`O` (as vim's) one beside
  it; the files go there.
- "Move N files to another dir in the inbox": a dir of the inbox picked (with `n`, `o`/`O` and `cc`
  too), and what's known of them goes with them.
- In every picker of several files, `V` picks a range (as vim's visual line mode), and Esc
  (`Ctrl-[`) unpicks: the range being picked, or else, without a search to drop, all.
- "Describe N files with Claude": a short description of each (at most 10 words, by Claude Haiku, which reads
  the files), shown after its name in the picker (`a.txt  [claude: a shopping list]`), and searchable (`/claude:`
  shows the described ones). It's
  done in the background: you go on picking, the files say "(Claude is looking at it...)" until
  their descriptions come, and the bottom line says what Claude is doing.
- "Ask Claude where N files go" (as `Ctrl-I` does, in the background too): their descriptions
  first (the missing ones), and which are copies (below), then Claude is
  given them and the sorted tree's dirs (with a few of the names of the files in each), and
  recommends a path for each file: a dir (an existing one, or a new one) and a name, the file's own
  unless it says little (`IMG_2041.jpg`, `scan001.pdf`) or doesn't fit how that dir's files are
  named; with a reason, shown beside the file. It reads nothing itself.
- Copies: each file is looked for in the sorted tree, as a sync looks for a moved file (by name, by
  size, and in Drive by hash), and the selected one's contents are compared with what's found (in
  the background; the picked ones' before Claude is asked where they go). A file with the same
  contents as one in the sorted tree says so, highlighted ("a copy: it may be removed"), Claude is
  told, and may recommend removing it: "Remove 3 of the 5 files that are copies of files in X" (by their contents, whatever
  Claude says; asked twice).
  Local files' hashes are kept in each local replica, in `meta/hashes.sqlite` at its root (made in
  the first live run, `DRYRUN=0`, unless it's read-only; `meta/` is never synced), else in
  `~/.cache/dirdelta/hashes.sqlite`, so a file is read once.
- Moving: to Claude's dir (its recommendation) or to a dir you pick in the sorted tree, under the
  file's own name, Claude's, or one you type (for one file: it starts as Claude's, or its own, to
  edit): "Move the N files to Claude's recommendation" (its dir and name; naming the dir, when they
  all go to one), "Move the N files, keeping their names, to Claude's dirs", "Move the file, under a
  name you type, to Claude's dir", "Move the N files to..." (pick a dir), "Move the N files, under
  Claude's names, to...", and "Move the file, under a name you type, to...". Then "Copy the N files
  to...", and "Remove the N files" (asked twice).
- Junk: files that look like junk are shown as such, `[junk? a Windows thumbnails cache]` after the
  name (so `/junk?` finds them all), with a yellow "junk? it may be removed" beside them. By their
  names and sizes, with no Claude: `Thumbs.db`, `desktop.ini`, `.DS_Store`, `~$` lock files, temporary
  and partly downloaded files, empty files, installers, and archives whose contents are beside them
  (`junk.py`). And as Claude says, when it's asked where files go: a clearly junk file it recommends
  removing, `[claude: junk? ...]`. Nothing is read for it (no images analysed). "Remove N of the M
  files that look like junk" lists each with why, asks twice, and sends a local file to the
  desktop's trash (`gio trash`, so it can be restored; not on a tmpfs like `/tmp`, where it's
  kept and said), a Drive one to Drive's trash.
- Where "to..." goes: the sorted tree's recent dirs first (the last 10 that files were moved or copied
  to, kept in `replicas.json`), or "Pick a dir", where `n` makes a new dir in the selected one (its
  name typed next; `a/b` makes both), made when the files go there.

A move or a copy first shows the tree it makes (each file where it goes, and where it's from beside
it), to look through (`Enter` goes on, `q` back); then No/Yes. When both are local, or both in
Drive, moving is a rename (in Drive, one request that keeps the file's id); when one is local and
the other in Drive, it's an upload (or a download), then the file's removal from the inbox, once
it's there. The inbox is kept, even when it's left empty.

Claude is asked through the Claude Agent SDK (`pip install claude-agent-sdk`, in `requirements.txt`),
which runs Claude Code: the laptop's logged-in Claude, or `ANTHROPIC_API_KEY` if it's set. Claude reads
the picked files itself (text, images, PDFs; a Drive file is downloaded first, and kept, see `Ctrl-X`), with no tool but
`Read`, so their contents are sent to Anthropic: only when you choose to. What it says is kept in
`~/.cache/dirdelta/ai.json`, by the file's path and size, so a file is asked about once, and it goes
with the file when it's moved or copied. Descriptions and
recommendations are both asked of `claude-haiku-5-5`.

### What replicas are called, and labels

Screens say which disk or Drive account a replica is on, e.g. `LocalDisk(ABC):/mnt/eliran` (the end of the
filesystem's UUID) or `Cloud(me):/eliran` (the account's user name, once dirdelta has asked Drive). "Label the
replicas" in the sync menu names them: a local replica's label is its disk's, so all the replicas on that
disk have it (`blue WD ext. disk:/mnt/eliran`), and a Drive one's is its own, by the account and the path.

### Rescanning a replica

"Rescan X" in the sync menu sees what's on a local replica's disk now, if you changed something while dirdelta was
running, and the menu's counts and state follow. (For a Drive replica, that's "Refresh X file list from Google Drive".)

### Removing from the other replica

In a sync's file picker the other replica's tree is at the top right. `Ctrl-W l` moves into it, as in vim (`Ctrl-W h`
back; `Ctrl-L` and `Ctrl-H` do too). `d` there removes the selected file or dir, after confirming twice, and Enter or `:`
offers it, so you needn't go to the other direction's picker. Removing
one version of a repository this way makes the other replica's version show up as missing, ready to copy.

### The menu of the keys (`:`)

In a sync's and a sort's file pickers, `:` with nothing picked opens a menu of what can be done there with
the selected file or dir, each with its key: what to do with it, picking it, asking AI, opening, renaming,
reading anew from Drive, the dashboard (and in a sort, Claude's description), and below them, to read,
the keys that only work in the list itself (search, a range, the side tree...). With files picked, `:` opens
the same menu as Enter, of what to do with them.

### Exploring a zip

`e` on a selected `.zip` in a sync's or sort's file picker (or "Explore" in the `:` and Enter menus) shows
what's in it as a tree, with each file's size and date beside it. Nothing's unpacked; a zip in Drive is
downloaded first.

### Asking AI

In a sync's and a sort's file pickers, `a` asks the AI (Claude, for now) about the picked files, or with
none picked, about all of them; the menu that Enter opens has "Ask AI" too, for what it's about. A
question ("what's in this zip file?") it just answers, "this" being what you're on: the picked files, or
else the selected one. Asked to do something, in your own words, e.g. "copy the 2019 photos, and remove
the unfinished downloads", it picks the files, and answers with a plan: in a sync, copying, removing from the source (to the trash),
and renaming in either replica; in a sort, moving or copying into the sorted tree, moving or renaming
in the inbox, and removing (to the trash).

Nothing's done until you approve it. The plan is shown as a tree, by kind, with where each file goes and
why beside it: Space unpicks a file or a whole kind, Enter goes on, `q` goes back. Each kind is then
confirmed as it is from the menu (a removal twice), and a dry run changes nothing. It's told the files'
paths and sizes, and what's known of them (e.g. Claude's descriptions, or that the other replica has a
copy). Of the files you're on (at most 10, and 20 MB each if they're in Drive), it's told the list of files in a zip
(it can't read what's inside them), and may read the others, which sends their contents to it; the screen says which. What can't be done (a file it wasn't told of, a path that's taken) is left
out of the plan, and said. At most 5000 files at once.

### Picker mode (one path)

`bin/pick.sh [PATH]` runs it from the repo on PATH (default: the current dir), or:

```bash
bin/python -m dirdelta /tmp/dd/alpha            # prints the picked path after exiting
bin/python -m dirdelta -x ls /tmp/dd/alpha      # runs `ls <picked path>` instead
bin/python -m dirdelta -m 1 /tmp/dd/alpha       # scan only one level deep (default 20)
```

Move with `h`/`j`/`k`/`l` or the arrows, `Ctrl-D`/`Ctrl-U` to page, `/` to search (`Enter` keeps
the filter, `Esc` drops it), `Enter` to pick the selected entry, `q` to quit without picking. A local
dir is scanned by `treepicker` itself, so even big trees open fast.

### Sync mode (two paths)

```bash
bin/python -m dirdelta /tmp/dd/alpha /tmp/dd/bravo             # a dry run: changes nothing
DRYRUN=0 bin/python -m dirdelta /tmp/dd/alpha /tmp/dd/bravo    # Copy, Remove and Rename really do
```

The menu offers, for each direction, "Files in A, not in B" (with how many there are). Choose one,
pick files with `Space` (on a directory it picks everything under it, or while a search filters
the tree, the matches under it), and press `Enter`. A
directory is marked picked (`X`, red) when everything under it is, and partly picked (`-`, magenta)
when only some of it is. Beside the tree, a column shows, for the selected file, where B has files
of the same name, and for a big file, of its size with another name (found while you look, with
how far it's got), the likeliest first: the same size, the same date taken (photos), the file's
neighbours there too, the same modification time; for the selected file, the same-sized ones'
contents are compared too (in the background), and one with the same contents is then the only one
shown. One that's surely the file, moved or renamed, says so, highlighted in green (`p` hides the
column). A Rename compares the contents of all the picked files first, so it moves only what's
surely the file. `Enter` then asks what to do with the picked files, with
"Nothing" selected first: copy them to B, remove them from A, or, for the ones whose match in B is
surely them, rename: move B's match to the file's path, or the file to the match's (greyed out
when it can't be done); and what the picker's keys do, so they're all in the menu too: open them
with their programs (`Ctrl-X` opens the selected one, see "Sorting an inbox"), and, with a cloud
replica, read the selected folder anew from Drive (`Ctrl-R`). A confirmation follows, with No selected (a removal asks a second time,
"Are you sure?", also with No selected): No takes you back to the picker, with the same files
picked; Yes goes ahead. Its progress fills the screen under a top line saying what's being done
(and over a status bar saying whether it's working, done or stopped, and a row of the keys);
`Ctrl-C` stops it (a file cut off in the middle of its copy is deleted), and when it's done or
stopped, `Enter` goes back to the picker, where you were, without the files done; `q` goes back
to the main menu. With a cloud replica, the menu also has "Refresh cloud/X from Google
Drive", which reads that folder anew from Drive (as the refresh offered at the start does), for when
it changed outside dirdelta, and in the file picker `Ctrl-R` reads just the selected folder anew.
A Drive replica's file list is kept in it too, in `meta/files.jsonl`: uploaded while a sync (or a
sort into it) goes on, a minute at most after it changed, and once more at the end (not in a dry
run). At the start, if the copy there is newer than this machine's cache (another machine's), it's
used instead of reading the folder again. Unless
`DRYRUN=0` is set, both are dry
runs: they change nothing on disk (not even the dirs copied files would go into), and say what they
would have done. Every screen says which it is, at the start of its status bar (its bottom line but
one): "DRY RUN" in green, or "LIVE" in red. Every screen is laid out the same way: what it is on
top (a menu's first line is its breadcrumbs, e.g. `dirdelta > Sync eliran ⇄ cloud/eliran > What
to do`), the status bar, then the keys of that screen on the last line (`?` lists them all; `q`
goes back, and quits only on the start menu).

Each replica's log, `last_update.txt` at its root, which you keep (newest last; an entry a line
starting with its date, `DD.MM.YYYY - what changed`, its other lines after it): when a sync starts,
dirdelta reads each replica's (a Drive one is downloaded, once until it changes) and keeps its last
entry in `replicas.json`, by the replica's identity: a local one by its filesystem's UUID and the path
in it (so a disk is the same replica wherever it's mounted), a Drive one by the account and its path.
The menu of a run without paths says when each was last updated (`/mnt/win/eliran (updated
17.05.2026) <-> cloud/eliran`), with marks (`?` explains them): before a pair, whether it was in
sync when last synced (≡ green), one ahead of the other (» or « yellow), branched (≠ red: each has
files the other lacks) or never compared (?), in grey if one was changed since; before each path,
when it was last synced (● green today, yellow this week, red before), and for a Drive one when
Drive's file list was read (☁). A sync's menu starts with the same state, as found now, and its "Replicas dashboard" lists them all, with their last
entry, when they were last synced and changed by dirdelta, which disks aren't connected now, and
their files' hashes, with an option to label each (in a sync or a sort, the same dashboard is in its menu and behind `#`). When you quit a sync that changed files (live: copied, removed or moved), it offers
an entry for each changed replica, e.g. `30.10.2026 - copied 12 files from cloud/eliran` for the one
copied into: added to its log (only its: the other's log is of the other's changes), edited first,
or not (a log is made if there's none).
An inbox's sort does the same for the sorted tree, when you quit it: e.g. `30.10.2026 - added 12
files from cloud/unsorted`. An inbox has no log (no `last_update.txt` is made or read in it): it's
where files wait to be sorted, not a replica to keep track of.

The fixtures are a small music library. Both have 106 files in common; only `alpha` has 364 (e.g.
`podcasts/`, `music/Nina Simone/` and `first/infirst/ininfirst/huh/99.mp3`), and only `bravo` has 31
(e.g. `audiobooks/Dune/`, `music/The Beatles/` and `third/anotherinthird/7.mp3`), so copying or
removing them fills the progress screen. Some dirs are taller than a screen, to show the picker's
pagination (`... N more` lines): `alpha/music/` has 36 artists, `alpha/podcasts/` 150 episodes, and
`alpha/music/Bach/The Well-Tempered Clavier/` 48 tracks. Sync copies of them (see above), since a
live Remove deletes real files.

## Tests

```bash
make test             # or make test ARGS=-v
```

It also runs treepicker's own tests (in `lib/treepicker`), which need Google Test (`libgtest-dev`).

## Cleaning

```bash
make clean
```

Removes this copy's build output (see `bin/builddir`), and what older versions left in the repo
(`__pycache__`, `*.pyc`, `build/`, `*.egg-info`, `.eggs`, pbr's `AUTHORS`/`ChangeLog`, `lib/treepicker/build`).
It leaves the venv, `secrets/` and the Drive cache (`~/.cache/dirman/files.sqlite`) alone; to start over,
delete the venv too (`~/.cache/dirdelta-build/venv`).

## Deploying to your system

To get a `dirdelta` command for everyday use, without activating any venv:

```bash
make deploy           # needs pipx (on Debian/Ubuntu: sudo apt install pipx)
```

This uses [pipx](https://pipx.pypa.io/) to install dirdelta and the picker library into a private venv
and link the command into `~/.local/bin`, which must be on your `PATH` (`pipx ensurepath` adds it).
Rerun `make deploy` after pulling changes, since it installs a copy rather than linking to the
source tree. `make undeploy` removes it.

For cloud paths, the deployed copy can't find the repo's `secrets/` folder, so point
`DIRDELTA_SECRETS_DIR` at the folder holding `credentials.json`/`token.json`.

`make deploy` builds treepicker too, and puts it in dirdelta's pipx venv (next to its python, where
dirdelta looks first), so it needs g++ and libncurses-dev, and `make undeploy` removes it with the
venv.

## Installing into a venv

```bash
make install          # pip install . (and treepicker next to that python)
```

Installs dirdelta into the same environment the other targets use (`make venv`'s if it exists, else the
`python3` on your `PATH`), and treepicker next to that environment's python. Useful for trying the packaged `dirdelta` command without deploying it.
