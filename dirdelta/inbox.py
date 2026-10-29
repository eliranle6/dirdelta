"""Sorting an inbox: a dir of files not yet sorted (e.g. cloud/unsorted), whose files the user moves
into a sorted tree (e.g. cloud/eliran), copies there, or removes, with Claude's help if they ask
for it (ai.py): a short description of each file, shown after its name, and where in the sorted
tree it belongs, shown beside it, to move it there.

When the inbox and the sorted tree are both local dirs, or both in Drive, the files are moved within
one tree that has both (their common dir, or Drive's), so a move is a rename (in Drive, one request
that keeps the file's id). When one is local and the other in Drive, a move is a copy (an upload or
a download, as a sync's), then the file's removal from the inbox, once it's there."""
import collections
import functools
import os
import posixpath
import subprocess
import tempfile
import textwrap
import threading
import time

from dirdelta import ai
from dirdelta import clouddirtree
from dirdelta import dirtree
from dirdelta import drivecache
from dirdelta import dryrun
from dirdelta import elsewhere
from dirdelta import entries
from dirdelta import interactive_dir_sync
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicas

# The label of the inbox's screens, so they're told from a sync's
LABEL = ('SORT', 'cyan')
# How wide the preview column's wrapped lines are, at most
PREVIEW_WIDTH = 40
# How often the picker's previews are looked at for changes (Claude's descriptions coming in), and
# how often Ask where they go looks whether the descriptions it waits for came, in seconds
PREVIEWS_INTERVAL = 0.3
DESCRIBED_WAIT_INTERVAL = 0.2
# The key that describes the picked files (or the selected one) with Claude, in the background
DESCRIBE_KEY = '\t'
# How many of a dir's file names Claude is given, so it sees how they're named
NAMES_PER_DIR = 3
# What says a file of the inbox is in the sorted tree already, in its preview: highlighted
SURELY_A_COPY = picker.highlighted("\u2192 a copy: it may be removed")
# What a file being described is shown as, after its name
LOOKING = "(Claude is looking at it...)"


class InboxError(Exception):
    pass


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


def _join(*relpaths):
    return posixpath.join(*[relpath for relpath in relpaths if relpath]) if any(relpaths) else ''


class InboxSort(object):
    """The inbox at inbox_path and the sorted tree at root_path (local dirs, or cloud paths)"""
    NOTHING = "Nothing: back to the files"
    DESCRIBE = 'describe'
    RECOMMEND = 'recommend'
    MOVE_RECOMMENDED = 'move to the recommendations'
    MOVE_TO = 'move to'
    COPY_TO = 'copy to'
    REMOVE = 'remove'
    REMOVE_COPIES = 'remove the copies'
    CONFIRM_NO = 'No'
    CONFIRM_YES = 'Yes'
    CONFIRM_SURE = 'Yes, remove them'
    REFRESH_KEY = 'r'

    def __init__(self, inbox_path, root_path):
        self.inbox_is_cloud = paths.is_cloud_path(inbox_path)
        self.root_is_cloud = paths.is_cloud_path(root_path)
        self.inbox_path = _normalized(inbox_path)
        self.root_path = _normalized(root_path)
        for path in (self.inbox_path, self.root_path):
            if not paths.is_cloud_path(path) and not os.path.isdir(path):
                raise InboxError("%s is not a directory" % (path,))
        if any(paths.is_cloud_path(path) for path in (self.inbox_path, self.root_path)) and \
                not os.path.exists(drivecache.FILE_LIST_CACHE):
            for path in (self.inbox_path, self.root_path):
                if paths.is_cloud_path(path):
                    clouddirtree.refresh_cache(paths.path_in_cloud(path))
        # Both of a kind: one tree with both, so a move is a rename. Else a tree each: a move is a
        # copy (an upload or a download), then a removal from the inbox.
        self.is_one_tree = self.inbox_is_cloud == self.root_is_cloud
        if self.is_one_tree:
            if self.inbox_is_cloud:
                inbox, root = paths.components(self.inbox_path)[1:], paths.components(self.root_path)[1:]
                common = os.path.commonprefix([inbox, root])
                tree = clouddirtree.factory(paths.join_cloud('/'.join(common)))
                self._inbox_rel, self._root_rel = '/'.join(inbox[len(common):]), '/'.join(root[len(common):])
            else:
                common = os.path.commonpath([self.inbox_path, self.root_path])
                tree = localdiskdirtree.LocalDiskDirTree(common, silent=True)
                self._inbox_rel, self._root_rel = _relpath(self.inbox_path, common), _relpath(self.root_path, common)
            if _is_at_or_under(self._root_rel, self._inbox_rel):
                raise InboxError("The sorted tree %s can't be in the inbox %s" % (self.root_path, self.inbox_path))
            self._inbox_tree = self._root_tree = tree
        else:
            self._inbox_tree, self._root_tree = _tree(self.inbox_path), _tree(self.root_path)
            self._inbox_rel = self._root_rel = ''
        for tree, relpath, path in ((self._inbox_tree, self._inbox_rel, self.inbox_path),
                                    (self._root_tree, self._root_rel, self.root_path)):
            if paths.is_cloud_path(path):
                node = tree.get_node(relpath)
                if node is None or not isinstance(node.data, entries.DirEntry):
                    raise InboxError("Google Drive has no folder %s (as of the cloud files list cache)" % (path,))
        # Neither is removed when it's left empty, nor moved whole
        self._inbox_tree.keep_dirs([self._inbox_rel])
        self._root_tree.keep_dirs([self._root_rel])
        # What Claude said of the inbox's files, by relpath (in the inbox)
        self._descriptions = {}
        self._recommendations = {}
        # The files being described (in the background), the queue of them, and the worker; and why
        # the ones that couldn't be weren't
        self._describing = set()
        self._queue = collections.deque()
        self._worker = None
        self._state_lock = threading.Lock()
        self._failed = {}
        # Drive is asked one request at a time: the describer's downloads and the screen's changes
        self._drive_lock = threading.Lock()
        # As a sync looks for a file where the other replica has it (elsewhere.py), the inbox's files
        # are looked for in the sorted tree, by name, size and contents: each as a replica of its own
        # (its relpaths the inbox's, the sorted tree's), with its index; the sorted tree's without
        # the inbox's files, if it's in it. checked: the files compared, as a sync's.
        self._inbox_view = self._inbox_tree if not self.is_one_tree else _tree(self.inbox_path)
        root_view = self._root_tree if not self.is_one_tree else _tree(self.root_path)
        inbox_in_root = (_relpath_in(self._inbox_rel, self._root_rel)
                         if self.is_one_tree and _is_at_or_under(self._inbox_rel, self._root_rel) else None)
        self._inbox_index = elsewhere.Index(self._inbox_view)
        self._root_index = elsewhere.Index(root_view, excluded=inbox_in_root)
        self._checked = {}
        self._indexing = None

    # The inbox's files

    def _inbox_files(self):
        """The inbox's files' relpaths (in it), each dir's together, sorted"""
        if self.inbox_is_cloud:
            full = self._inbox_tree._files_under(self._inbox_rel)
            relpaths = [_relpath_in(relpath, self._inbox_rel) for relpath in full]
        else:
            found = localdiskdirtree.LocalDiskDirTree(self.inbox_path, silent=True).files_by_name()
            relpaths = [relpath for files in found.values() for relpath, _ in files]
        return sorted(relpaths, key=lambda relpath: relpath.split('/'))

    def _full(self, relpath):
        """An inbox file's relpath in the inbox's tree"""
        return _join(self._inbox_rel, relpath)

    def _size(self, relpath):
        return self._inbox_tree.file_size(self._full(relpath))

    def _cache_key(self, file):
        return '%s\t%s' % (posixpath.join(self.inbox_path, file.relpath), file.size)

    def _load_cached(self, relpaths):
        files = [ai.File(relpath, None, self._size(relpath)) for relpath in relpaths]
        descriptions, recommendations = ai.cached(files, self._cache_key, self.root_path)
        self._descriptions.update(descriptions)
        self._recommendations.update(recommendations)

    # The screens

    def run(self):
        """Let the user pick some of the inbox's files, then choose what to do with them (_act()),
        and back to the picker, where they were, until they quit, or the inbox is empty"""
        header = ("Files in %s, to sort into %s. Pick some, then choose what to do with them:\n"
                  "(To pick a file, press Space. When finished, press Enter. Ctrl-I: Claude describes "
                  "the picked files, or the selected one, while you go on.%s After a '|': what Claude "
                  "says it is.)" %
                  (self.inbox_path, self.root_path,
                   " %s: read the selected folder anew from Google Drive." % (self.REFRESH_KEY,)
                   if self.inbox_is_cloud else ""))
        picked, selected = [], None
        while True:
            files = self._inbox_files()
            if not files:
                messages.show("The inbox is empty", ["%s has no files to sort." % (self.inbox_path,)],
                              dryrun.label())
                return
            self._load_cached(files)
            self._start_indexing()
            chosen = picker.pick_files(
                self.inbox_path, files, header=header, picked=picked, label=LABEL,
                keys=self.REFRESH_KEY if self.inbox_is_cloud else '', selected=selected,
                previews=lambda send, files=files: self._send_previews(files, send),
                shown_as=lambda files=files: self._shown_as(files),
                notify_keys=DESCRIBE_KEY,
                on_notify=lambda key, selected, picked, files=files: self.describe_in_background(
                    picked or [relpath for relpath in files if _is_at_or_under(relpath, selected)]),
                on_selection=functools.partial(elsewhere.check_contents, files, self._inbox_view,
                                               self._inbox_index, self._root_index, self._checked,
                                               sends_previews=False))
            if chosen is None:
                self._finish_describing()
                return
            selected = chosen.selected
            if chosen.key == self.REFRESH_KEY:
                with self._drive_lock:
                    interactive_dir_sync.refresh_replica(self._inbox_tree, self._full(selected))
                picked = chosen.files
                continue
            done = self._act(chosen.files)
            if done is None:
                picked = chosen.files
                continue
            done = set(done)
            picked = [relpath for relpath in chosen.files if relpath not in done]
            left = [relpath for relpath in self._inbox_files()]
            selected = _shown(selected, left)

    def _shown_as(self, relpaths):
        """{relpath: what the picker shows it as}: its name, and Claude's description, if any (or
        that Claude's looking at it); and '': the status, what Claude is doing"""
        shown = {}
        for relpath in relpaths:
            if relpath in self._descriptions:
                shown[relpath] = "%s  | %s" % (os.path.basename(relpath), self._descriptions[relpath])
            elif relpath in self._describing:
                shown[relpath] = "%s  | %s" % (os.path.basename(relpath), LOOKING)
        describing = len(self._describing)
        failed = len([relpath for relpath in relpaths if relpath in self._failed])
        shown[''] = ("Claude: describing %s" % (_files(describing),) if describing else
                     "Claude: couldn't describe %s" % (_files(failed),) if failed else '')
        return shown

    def _send_previews(self, relpaths, send):
        """Send the picker the files' previews, and again as they change (Claude's descriptions
        coming in), until it's gone"""
        sent = {}
        while True:
            changed = {relpath: lines for relpath, lines in self._previews(relpaths).items()
                       if sent.get(relpath) != lines}
            # Sent even with nothing to send: it raises PickerClosed once the picker is gone
            send(changed, default=[] if not sent else None)
            sent.update(changed)
            time.sleep(PREVIEWS_INTERVAL)

    def _previews(self, relpaths):
        """{relpath: lines} beside the picker: the file's size, and what Claude said of it"""
        previews = {}
        for relpath in relpaths:
            size = self._size(relpath)
            lines = ["This one: %s" % (elsewhere.format_size(size),)] if size is not None else []
            if relpath in self._descriptions:
                lines += ["", "Claude says it's:"] + _wrapped(self._descriptions[relpath], "  ")
            elif relpath in self._describing:
                lines += ["", "Claude is looking at it..."]
            elif relpath in self._failed:
                lines += ["", "Claude couldn't describe it:"] + _wrapped(self._failed[relpath], "  ")
            lines += self._copies_lines(relpath)
            recommendation = self._recommendations.get(relpath)
            if recommendation and recommendation.get('action') == 'remove':
                lines += ["", "Claude recommends removing it:"] + _wrapped(recommendation.get('reason', ''), "  ")
            elif recommendation:
                # Relative to the sorted tree, so a long root doesn't hide where in it
                target = self._target(relpath)
                lines += ["", "Claude recommends it go to:", "  %s/" % (os.path.dirname(target) or '.',)]
                if os.path.basename(target) != os.path.basename(relpath):
                    lines += ["  renamed:"] + _wrapped(os.path.basename(target), "    ")
                lines += ["  (in %s)" % (self.root_path,)]
                lines += _wrapped(recommendation.get('reason', ''), "  ")
            else:
                lines += ["", "Where it goes: pick it, press", "Enter, and ask Claude."]
            previews[relpath] = lines
        return previews

    def _act(self, relpaths):
        """Let the user choose what to do with the picked files at relpaths, and do it once they
        confirm. Returns the ones done (moved, copied, removed; in a dry run, the ones it would have
        done), or None if none were (or Claude was asked: nothing moved)."""
        count = _files(len(relpaths))
        undescribed = [relpath for relpath in relpaths
                       if relpath not in self._descriptions and relpath not in self._describing]
        unrecommended = [relpath for relpath in relpaths if relpath not in self._recommendations]
        recommended = [relpath for relpath in relpaths
                       if relpath in self._recommendations and self._target(relpath) is not None]
        removable = [relpath for relpath in relpaths
                     if relpath in self._recommendations and self._target(relpath) is None]
        destinations = sorted({os.path.dirname(self._target(relpath)) for relpath in recommended})
        renamed = [relpath for relpath in recommended
                   if os.path.basename(self._target(relpath)) != os.path.basename(relpath)]
        renamed_text = ", %d renamed" % (len(renamed),) if renamed else ""
        if len(destinations) == 1:
            to = "Claude's recommendation: %s/%s" % (_join(self.root_path, destinations[0]),
                                                    " (%s)" % (renamed_text[2:],) if renamed else "")
        else:
            to = "Claude's recommendations (%d dirs%s)" % (len(destinations), renamed_text)
        options = {
            self.DESCRIBE: ("Describe %s with Claude, while you go on (sends it their contents; or Ctrl-I)" %
                            (_files(len(undescribed)),),
                            None if undescribed else "they all have a description, or are being described"),
            self.RECOMMEND: ("Ask Claude where %s go in %s (describing them first)" %
                             (_files(len(unrecommended)), self.root_path),
                             None if unrecommended else "they all have a recommendation"),
            self.MOVE_RECOMMENDED: ("Move %s to %s" % ("the " + count if len(recommended) == len(relpaths) else
                                                       "the %d of them with one" % (len(recommended),), to),
                                    None if recommended else "none of them has a recommendation to move it yet"),
            self.REMOVE_COPIES: ("Remove the %s Claude says are copies of files in %s" %
                                 (_files(len(removable)), self.root_path),
                                 None if removable else "Claude says none of them is a copy (or wasn't asked)"),
            self.MOVE_TO: ("Move the %s to... (pick a dir in %s)" % (count, self.root_path), None),
            self.COPY_TO: ("Copy the %s to... (pick a dir in %s)" % (count, self.root_path), None),
            self.REMOVE: ("Remove the %s from %s" % (count, self.inbox_path), None),
        }
        disabled = {label: picker.Disabled("%s: %s" % (label, reason))
                    for label, reason in options.values() if reason is not None}
        answer = picker.pick_option([self.NOTHING] + [label for label, _ in options.values()],
                                    header="%s picked in %s. What to do with them?" % (count, self.inbox_path),
                                    shown_as=lambda: disabled, label=LABEL)
        action = next((action for action, (label, _) in options.items() if label == answer), None)
        if action == self.DESCRIBE:
            self.describe_in_background(undescribed)
            return None
        if action == self.RECOMMEND:
            self._recommend(unrecommended)
            return None
        if action == self.MOVE_RECOMMENDED:
            return self._approve(self.MOVE_TO, [(relpath, self._target(relpath)) for relpath in recommended])
        if action in (self.MOVE_TO, self.COPY_TO):
            destination = self._pick_dir("Pick the dir in %s to %s the %s to (Enter picks the selected dir)" %
                                         (self.root_path, 'move' if action == self.MOVE_TO else 'copy', count))
            if destination is None:
                return None
            return self._approve(action, [(relpath, _join(destination, os.path.basename(relpath)))
                                          for relpath in relpaths])
        if action == self.REMOVE:
            return self._remove(relpaths)
        if action == self.REMOVE_COPIES:
            return self._remove(removable, ["  %s: a copy of %s" % (relpath, ', '.join(
                _join(self.root_path, copy) for copy in self._copies(relpath)[:2]))
                for relpath in removable])
        return None

    def _copies(self, relpath):
        """The sorted tree's files (relpaths in it) with the same contents as the inbox's at relpath,
        of the ones compared"""
        return sorted(match for match, is_same in self._checked.get(relpath, {}).items() if is_same)

    def _copies_lines(self, relpath):
        """A preview's lines of what the sorted tree has of the inbox's file at relpath: its copies,
        or that it has none, or its candidates (to compare when it's selected)"""
        copies = self._copies(relpath)
        if copies:
            return (["", "In %s already, the same contents:" % (self.root_path,)] +
                    ["  " + copy for copy in copies[:3]] + [SURELY_A_COPY])
        if relpath in self._checked:
            return ["", "Not in %s (its contents compared)" % (self.root_path,)]
        if not self._root_index.is_built():
            return ["", "Looking through %s's files..." % (self.root_path,)]
        candidates = elsewhere._same_sized(relpath, self._size(relpath), self._root_index)
        if candidates:
            return ["", "%s of its size in %s: compared" % (_files(len(candidates)), self.root_path),
                    "when it's selected"]
        return []

    def _start_indexing(self):
        """List the sorted tree's files (its index), in the background, once"""
        if self._indexing is None:
            self._indexing = threading.Thread(target=self._build_index, daemon=True)
            self._indexing.start()

    def _build_index(self):
        try:
            self._root_index.build()
        except Exception:
            # Only for finding copies: without it, there are none to say
            pass

    def _compare_with_the_sorted_tree(self, relpaths):
        """Compare the contents of the inbox's files at relpaths with their candidates in the sorted
        tree, the ones not compared yet (on a progress screen's lines)"""
        self._start_indexing()
        self._indexing.join()
        elsewhere.check_all(relpaths, self._inbox_view, self._inbox_index, self._root_index, self._checked,
                            lambda number, count, relpath: messages.print_progress(
                                "Comparing with %s's files: %d of %d" % (self.root_path, number, count)))

    # Claude

    def describe_in_background(self, relpaths):
        """Have Claude describe the files at relpaths that have no description (and aren't being
        described), on a thread of its own, a batch at a time, while the user goes on: each picker
        shows them as they come"""
        with self._state_lock:
            new = [relpath for relpath in relpaths
                   if relpath not in self._descriptions and relpath not in self._describing]
            for relpath in new:
                self._failed.pop(relpath, None)
            self._describing.update(new)
            self._queue.extend(new)
            if new and self._worker is None:
                self._worker = threading.Thread(target=self._describe_queued, daemon=True)
                self._worker.start()

    def _describe_queued(self):
        """Describe the queued files, a batch at a time, until there are none (on the describer's
        thread: nothing is printed, as a picker may have the screen)"""
        while True:
            with self._state_lock:
                if not self._queue:
                    self._worker = None
                    return
                batch = [self._queue.popleft() for _ in range(min(ai.BATCH_SIZE, len(self._queue)))]
            try:
                with tempfile.TemporaryDirectory(prefix='dirdelta-ai-') as temp_dir:
                    with self._drive_lock:
                        files = self._ai_files(batch, temp_dir, is_quiet=True)
                    found = ai.describe(files, self._cache_key)
                self._descriptions.update(found)
                for relpath in batch:
                    if relpath not in found:
                        self._failed[relpath] = "Claude gave no description of it."
            except Exception as error:
                for relpath in batch:
                    self._failed[relpath] = str(error)
            finally:
                with self._state_lock:
                    self._describing.difference_update(batch)

    def _finish_describing(self):
        """Wait for the files being described, if any, on a progress screen (Ctrl-C stops waiting:
        what Claude said so far is kept)"""
        if not self._describing:
            return
        title = ("Waiting for Claude to finish describing %s (what it said so far is kept)" %
                 (_files(len(self._describing)),))
        with messages.progress_screen(title, dryrun.label(), wait=False):
            failed_before = len(self._failed)
            try:
                while self._describing:
                    messages.print_progress("%s left, %d described, %d couldn't be" % (
                        _files(len(self._describing)), len(self._descriptions), len(self._failed) - failed_before))
                    time.sleep(DESCRIBED_WAIT_INTERVAL)
            except KeyboardInterrupt:
                messages.note_stopped()
        if len(self._failed) > failed_before:
            messages.show("Claude couldn't describe %s" % (_files(len(self._failed) - failed_before),),
                          [list(self._failed.values())[-1]], dryrun.label(), 'red')

    def _recommend(self, relpaths):
        """Ask Claude where the files at relpaths go, on a progress screen (Ctrl-C stops it: what it
        said so far is kept): their descriptions first (the ones being described in the background
        waited for, the others described too), then where they go, by them. The screen goes once
        it's done, unless something went wrong, which is shown."""
        error = None
        with messages.progress_screen("Asking Claude where %s go in %s" % (_files(len(relpaths)), self.root_path),
                                      dryrun.label(), wait=False):
            try:
                # Which are copies of files in the sorted tree already, for Claude to know
                self._compare_with_the_sorted_tree(relpaths)
                messages.print_line("")
                self.describe_in_background(relpaths)
                while True:
                    waiting = [relpath for relpath in relpaths if relpath in self._describing]
                    if not waiting:
                        break
                    messages.print_progress("Claude is describing them first: %d of %d done" %
                                            (len(relpaths) - len(waiting), len(relpaths)))
                    time.sleep(DESCRIBED_WAIT_INTERVAL)
                messages.print_line("")
                files = [ai.File(relpath, None, self._size(relpath)) for relpath in relpaths]
                self._recommendations.update(ai.recommend(
                    files, self._cache_key, self._root_dirs(), self.root_path, self._descriptions,
                    {relpath: self._copies(relpath) for relpath in relpaths},
                    lambda done, total: messages.print_progress("Claude has placed %d of %d files" % (done, total))))
            except ai.AIError as error_:
                error = str(error_)
            except KeyboardInterrupt:
                messages.note_stopped()
        if error is not None:
            messages.show("Claude couldn't say where they go", [error], dryrun.label(), 'red')

    def _ai_files(self, relpaths, temp_dir, is_quiet=False):
        """ai.File of each of the inbox's files at relpaths: a Drive one downloaded into temp_dir
        first (one at a time), unless it's too big to be read, or a Google file. With is_quiet, it
        prints nothing (a picker may have the screen)."""
        files = []
        for number, relpath in enumerate(relpaths, 1):
            size = self._size(relpath)
            local_path = None
            if not self.inbox_is_cloud:
                local_path = os.path.join(self.inbox_path, relpath)
            elif (size or 0) <= ai.MAX_READ_SIZE and self._inbox_tree.cant_fetch(self._full(relpath)) is None:
                local_path = os.path.join(temp_dir, relpath)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                if not is_quiet:
                    messages.print_progress("Downloading %d of %d files for Claude: %s" %
                                            (number, len(relpaths), relpath))
                try:
                    self._inbox_tree.fetch_file(self._full(relpath), local_path)
                except OSError as error:
                    if not is_quiet:
                        messages.print_line("Couldn't download %s (%s): Claude goes by its name" %
                                            (relpath, error), "yellow")
                    local_path = None
            files.append(ai.File(relpath, local_path, size))
        return files

    def _root_dirs(self):
        """{dir relpath: the names of a few of its files (NAMES_PER_DIR)} of the sorted tree's dirs
        ('' its root), so Claude sees how they're named; not the inbox's (if it's in it)"""
        dirs = {'': []}
        if self.root_is_cloud:
            node = self._root_tree.get_node(self._root_rel)
            found = [(_relpath_in(child.identifier, self._root_rel), isinstance(child.data, entries.DirEntry))
                     for child in self._root_tree._tree.subtree(node.identifier).all_nodes_itr()
                     if child.identifier != self._root_rel]
        else:
            result = subprocess.run(['find', self.root_path, '-mindepth', '1', '(', '-type', 'd', '-o', '-type', 'f',
                                     ')', '-printf', '%y %P\\0'],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            found = [(os.fsdecode(entry[2:]), entry[:1] == b'd') for entry in result.stdout.split(b'\0') if entry]
        inbox_in_root = _relpath_in(self._inbox_rel, self._root_rel) if self.is_one_tree and _is_at_or_under(
            self._inbox_rel, self._root_rel) else None
        found = [(relpath, is_dir) for relpath, is_dir in found
                 if inbox_in_root is None or not _is_at_or_under(relpath, inbox_in_root)]
        for relpath, is_dir in sorted(found):
            if is_dir:
                dirs.setdefault(relpath, [])
        for relpath, is_dir in sorted(found):
            names = dirs.get(os.path.dirname(relpath))
            if not is_dir and names is not None and len(names) < NAMES_PER_DIR:
                names.append(os.path.basename(relpath))
        return dirs

    # Moving, copying, removing

    def _pick_dir(self, header):
        """Let the user pick a dir in the sorted tree. Returns its relpath ('' the root), or None."""
        if self.root_is_cloud:
            root = clouddirtree.factory(self.root_path)
            picked = picker.pick_from_tree(root, header=header, dirs_only=True, root_name=self.root_path)
            relpath = picked[0].relpath if picked else None
        else:
            path = picker.pick_under_dir(self.root_path, dirs_only=True, lazy=True, header=header)
            relpath = None if path is None else _relpath(path, self.root_path)
        if relpath is not None and self.is_one_tree and _is_at_or_under(_join(self._root_rel, relpath),
                                                                        self._inbox_rel):
            messages.show("That's the inbox", ["Pick a dir of %s that isn't in the inbox." % (self.root_path,)],
                          dryrun.label())
            return None
        return relpath

    def _approve(self, action, plan):
        """Show where each file of plan (relpath, its path in the sorted tree: a dir and a name, maybe
        another) goes, as the tree it makes, then, once the user confirms, move (MOVE_TO) or copy them
        there. Returns the picked files done (or that would have been, in a dry run), or None if the
        user didn't confirm."""
        verb = "Move" if action == self.MOVE_TO else "Copy"
        targets = {}
        for relpath, target in plan:
            targets.setdefault(target, []).append(relpath)
        clashes = {target: sources for target, sources in targets.items() if len(sources) > 1}
        if clashes:
            target = sorted(clashes)[0]
            messages.show("Files of the same name",
                          ["%d files would go to %s: %s. Pick them apart." %
                           (len(clashes[target]), _join(self.root_path, target), ', '.join(clashes[target]))],
                          dryrun.label(), 'red')
            return None
        destinations = sorted({os.path.dirname(target) for _, target in plan})
        new_dirs = [destination for destination in destinations
                    if not self._root_tree._exists(_join(self._root_rel, destination))]
        previews = {}
        for target, (relpath,) in targets.items():
            lines = ["From: %s" % (posixpath.join(self.inbox_path, relpath),)]
            if self._root_tree._exists(_join(self._root_rel, target)):
                lines += ["", "There's a file there already:", "it's skipped."]
            if os.path.dirname(target) in new_dirs:
                lines += ["", "In a new dir."]
            if os.path.basename(target) != os.path.basename(relpath):
                lines += ["", "Renamed, from:"] + _wrapped(os.path.basename(relpath), "  ")
            recommendation = self._recommendations.get(relpath)
            if recommendation and self._target(relpath) == target:
                lines += ["", "Why (Claude):"] + _wrapped(recommendation.get('reason', ''), "  ")
            previews[target] = lines
        summary = ("%s %s from %s into %d dirs of %s%s" %
                   (verb, _files(len(plan)), self.inbox_path, len(destinations), self.root_path,
                    " (%d of them new)" % (len(new_dirs),) if new_dirs else ""))
        header = ("%s, where shown (beside each: where it's from). Look them through, then:\n"
                  "Enter: go on to say yes or no. q: back to the inbox." % (summary,))
        if not picker.view_files(self.root_path, sorted(targets, key=lambda target: target.split('/')),
                                 header=header, previews=previews, label=LABEL):
            return None
        lines = [summary + "?"]
        if not self.is_one_tree:
            lines.append("(%s %s, then %s from the inbox%s, once each is there.)" % (
                "Uploaded to Google Drive" if self.root_is_cloud else "Downloaded from Google Drive",
                "and removed" if action == self.MOVE_TO else "", "" if action == self.MOVE_TO else "kept in",
                " (to Drive's trash)" if self.inbox_is_cloud and action == self.MOVE_TO else ""))
        if dryrun.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        if picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                              label=LABEL) != self.CONFIRM_YES:
            return None
        moves = [(self._full(relpath), _join(self._root_rel, target)) for relpath, target in plan]
        # The cache's keys of each file, here and where it goes (the same size), while it's here
        sizes = {relpath: self._size(relpath) for relpath, _ in plan}
        keys = {relpath: (self._cache_key(ai.File(relpath, None, sizes[relpath])),
                          self._target_cache_key(target, sizes[relpath]))
                for relpath, target in plan}
        with messages.progress_screen(summary + (" (a dry run)" if dryrun.DRYRUN else ""), dryrun.label()), \
                self._drive_lock:
            if self.is_one_tree:
                done = (self._inbox_tree.move_files(moves) if action == self.MOVE_TO else
                        self._inbox_tree.copy_files_within(moves))
            else:
                done = self._transfer(moves, action == self.MOVE_TO)
        if dryrun.DRYRUN:
            return [relpath for relpath, _ in plan]
        done_sources = {relpath for relpath, _ in done}
        done = [relpath for relpath, _ in plan if self._full(relpath) in done_sources]
        # What Claude said of each goes with it, to its new path
        ai.carry(dict(keys[relpath] for relpath in done))
        # The sorted tree has them now: a later file of the inbox may be a copy of one
        targets = dict(plan)
        for relpath in done:
            self._root_index.add(targets[relpath], sizes[relpath])
        return done

    def _target_cache_key(self, target, size):
        """The cache's key of a file at target in the sorted tree"""
        return '%s\t%s' % (posixpath.join(self.root_path, target), size)

    def _target(self, relpath):
        """Where Claude recommends the inbox's file at relpath go, in the sorted tree"""
        return ai.recommended_path(relpath, self._recommendations[relpath])

    def _transfer(self, moves, is_move):
        """Copy the inbox's files to the sorted tree, of another kind, each of moves (relpath in the
        inbox's tree, relpath in the sorted tree's): an upload to Drive, or a download from it, as a
        sync's copy does; then if is_move, remove from the inbox the ones copied. Returns the moves
        done (none in a dry run)."""
        source_of = {new_relpath: relpath for relpath, new_relpath in moves}
        files = [entries.FileEntry(os.path.basename(new_relpath), new_relpath,
                                   os.path.join(self.inbox_path, relpath))
                 for relpath, new_relpath in moves]
        source = None if self.root_is_cloud else _Renamed(self._inbox_tree, source_of)
        self._root_tree.copy_inner_entries_from_dirtree(
            dirtree.DirTree.from_file_entries(files, self.inbox_path), source)
        if dryrun.DRYRUN:
            if is_move:
                self._inbox_tree.remove_files(self._entries(relpath for relpath, _ in moves))
            return []
        done = [(relpath, new_relpath) for relpath, new_relpath in moves if self._root_tree.has_file(new_relpath)]
        if is_move and done:
            self._inbox_tree.remove_files(self._entries(relpath for relpath, _ in done))
            done = [(relpath, new_relpath) for relpath, new_relpath in done
                    if not self._inbox_tree.has_file(relpath)]
        return done

    def _entries(self, relpaths):
        """The entries of the inbox's files at relpaths (in its tree), to remove them"""
        found = []
        for relpath in relpaths:
            node = self._inbox_tree.get_node(relpath)
            found.append(node.data if node is not None else entries.FileEntry(
                os.path.basename(relpath), relpath, os.path.join(self._inbox_tree.fullpath(), relpath)))
        return found

    def _remove(self, relpaths, listed=None):
        """Remove the inbox's files at relpaths, once the user confirms twice; listed: the lines that
        list them (else their relpaths)"""
        lines = ["Remove %s from %s?" % (_files(len(relpaths)), self.inbox_path)]
        listed = listed or ["  %s" % (relpath,) for relpath in relpaths]
        lines += listed[:interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED]
        if len(relpaths) > interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED:
            lines.append("  (and %d more)" % (len(relpaths) - interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED,))
        if dryrun.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        if picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                              label=LABEL) != self.CONFIRM_YES:
            return None
        sure = "Are you sure? %s will be removed from %s%s." % (
            _files(len(relpaths)), self.inbox_path, " (to Drive's trash)" if self.inbox_is_cloud else ", for good")
        if picker.pick_option([self.CONFIRM_NO, self.CONFIRM_SURE], header=sure, label=LABEL) != self.CONFIRM_SURE:
            return None
        file_entries = self._entries(self._full(relpath) for relpath in relpaths)
        with messages.progress_screen("Removing %s from %s%s" % (_files(len(relpaths)), self.inbox_path,
                                                                " (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock:
            self._inbox_tree.remove_files(file_entries)
        if dryrun.DRYRUN:
            return relpaths
        left = set(self._inbox_files())
        return [relpath for relpath in relpaths if relpath not in left]


class _Renamed(object):
    """A tree to copy from (a copy_inner_entries_from_dirtree() source) whose files are asked for by
    where they go (relpaths in the tree copied into), each where source_of says it is in tree"""
    def __init__(self, tree, source_of):
        self._tree = tree
        self._source_of = source_of

    def cant_fetch(self, relpath):
        return self._tree.cant_fetch(self._source_of[relpath])

    def fetch_file(self, relpath, local_path):
        self._tree.fetch_file(self._source_of[relpath], local_path)


def _tree(path):
    """The tree of a replica path on its own: a Drive folder's (from the cache), or a local dir's
    (not scanned)"""
    if paths.is_cloud_path(path):
        return clouddirtree.factory(path)
    return localdiskdirtree.LocalDiskDirTree(path, silent=True)


def _normalized(path):
    """A replica path as it's shown and kept: a cloud one cleaned, a local one absolute and real"""
    if paths.is_cloud_path(path):
        return paths.join_cloud('/'.join(paths.components(path)[1:]))
    return os.path.realpath(path)


def run(inbox_path, root_path, known_replicas=None):
    """Sort the inbox at inbox_path into root_path (see InboxSort), with known_replicas (a
    replicas.Replicas, saved) remembering them as a recent sort"""
    sort = InboxSort(inbox_path, root_path)
    if known_replicas is not None:
        known_replicas.record_sort(sort.inbox_path, sort.root_path)
        replicas.save(known_replicas)
    sort.run()


def _wrapped(text, indent):
    return [indent + line for line in textwrap.wrap(text, PREVIEW_WIDTH - len(indent))] if text else []


def _relpath(path, root):
    relpath = os.path.relpath(path, root)
    return '' if relpath == '.' else relpath


def _relpath_in(relpath, dirpath):
    """relpath (under dirpath, both relpaths in one tree) relative to dirpath"""
    return relpath[len(dirpath) + 1:] if dirpath else relpath


def _is_at_or_under(relpath, dirpath):
    return not dirpath or relpath == dirpath or relpath.startswith(dirpath + '/')


def _shown(relpath, files):
    """relpath, or the closest dir above it that the picker of files still shows ('' the root)"""
    return interactive_dir_sync._shown(relpath or '', files)
