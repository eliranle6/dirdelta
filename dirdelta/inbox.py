"""Sorting an inbox: a dir of files not yet sorted (e.g. cloud/unsorted), whose files the user moves
into a sorted tree (e.g. cloud/eliran), copies there, or removes, with Claude's help if they ask
for it (ai.py): a short description of each file, shown after its name, and where in the sorted
tree it belongs, shown beside it, to move it there.

When the inbox and the sorted tree are both local dirs, or both in Drive, the files are moved within
one tree that has both (their common dir, or Drive's), so a move is a rename (in Drive, one request
that keeps the file's id). When one is local and the other in Drive, a move is a copy (an upload or
a download, as a sync's), then the file's removal from the inbox, once it's there."""
import collections
import contextlib
import functools
import os
import posixpath
import subprocess
import textwrap
import threading
import time

from dirdelta import ai
from dirdelta import clouddirtree
from dirdelta import dirtree
from dirdelta import drivecache
from dirdelta import downloads
from dirdelta import dryrun
from dirdelta import elsewhere
from dirdelta import entries
from dirdelta import interactive_dir_sync
from dirdelta import junk
from dirdelta import localdiskdirtree
from dirdelta import messages
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicalog
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
# The key that opens the selected file (Ctrl-X) with its program (xdg-open), a Drive one downloaded
# first (or found downloaded, see downloads.py), in the background
OPEN_KEY = '\x18'
# How long the bottom line says a file was opened, in seconds
OPENED_SHOWN_FOR = 5
# How many of a dir's file names Claude is given, so it sees how they're named
NAMES_PER_DIR = 3
# What says a file of the inbox is in the sorted tree already, in its preview: highlighted
SURELY_A_COPY = picker.highlighted("\u2192 a copy: it may be removed")
# What says a file looks like junk, in its preview: in yellow, since it's a guess, not a copy's sure
# green
MAYBE_JUNK = picker.highlighted("\u2192 junk? it may be removed", 'yellow')
# What a file that looks like junk is shown as, after its name (and its description): a search
# (/) for 'junk?' finds them all
JUNK_BY_NAME = "[junk? %s]"
JUNK_BY_CLAUDE = "[claude: junk? %s]"
# What a file being described is shown as, after its name
LOOKING = "(Claude is looking at it...)"
# What a file Claude described is shown as, after its name: a search (/) for 'claude:' finds them,
# and one for a word finds the files Claude said it of
DESCRIBED = "[claude: %s]"


class InboxError(Exception):
    pass


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


def _of(count, total):
    """How many of the picked files (total) count is: 'the 3 files' when it's all of them, else '3 of
    the 5 files'"""
    if count == total:
        return "the " + _files(count)
    return "%d of the %s" % (count, _files(total))


def _join(*relpaths):
    return posixpath.join(*[relpath for relpath in relpaths if relpath]) if any(relpaths) else ''


class InboxSort(object):
    """The inbox at inbox_path and the sorted tree at root_path (local dirs, or cloud paths)"""
    NOTHING = "Nothing: back to the files"
    DESCRIBE = 'describe'
    RECOMMEND = 'recommend'
    # Moving: to Claude's dir, or to a dir the user picks; under the file's name, Claude's, or one
    # the user types
    MOVE_RECOMMENDED = 'move to the recommendations'
    MOVE_TO_CLAUDES_DIR = "move to Claude's dirs"
    MOVE_TO_CLAUDES_DIR_TYPED = "move to Claude's dir, typing its name"
    MOVE_TO = 'move to'
    MOVE_TO_CLAUDES_NAMES = "move to, under Claude's names"
    MOVE_TO_TYPED = 'move to, typing its name'
    COPY_TO = 'copy to'
    REMOVE = 'remove'
    REMOVE_COPIES = 'remove the copies'
    REMOVE_JUNK = 'remove the junk'
    CONFIRM_NO = 'No'
    CONFIRM_YES = 'Yes'
    CONFIRM_SURE = 'Yes, remove them'
    REFRESH_KEY = 'r'
    # The dir picker's key that makes a new dir in the selected one (its name typed next)
    NEW_DIR_KEY = 'n'
    # Where files go: a dir picked in the sorted tree, or one of the recent ones (by its relpath in
    # it: the header names the sorted tree)
    PICK_DIR = "Pick a dir (or make a new one: n in the picker)"
    RECENT_DIR = "Recent: %s/"

    def __init__(self, inbox_path, root_path, known_replicas=None):
        self.inbox_is_cloud = paths.is_cloud_path(inbox_path)
        self.root_is_cloud = paths.is_cloud_path(root_path)
        self.inbox_path = _normalized(inbox_path)
        self.root_path = _normalized(root_path)
        # Where the sorted tree's recent dirs are kept (a replicas.Replicas, saved), if anywhere
        self._known_replicas = known_replicas
        # What's changed live in the inbox and the sorted tree, by their paths, for their logs'
        # entries (see replicalog.py)
        self.changes = replicalog.Changes()
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
        # The files to say where they go of; and all the queued ones (for either)
        self._placing = set()
        self._queued = set()
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
        # The inbox's files that look like junk by their names and sizes (junk.py): {relpath: why}
        self._junk_by_name = {}
        # What the bottom line says of opening a file (Ctrl-X), and until when (None: while it's
        # being downloaded)
        self._open_note = None

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
                  "(To pick a file, press Space. When finished, press Enter (with none picked: the "
                  "selected one). Ctrl-I: Claude describes the picked files (or the selected one), and "
                  "says where they go, while you go on. Ctrl-X: open the selected file.%s "
                  "[claude: ...]: what Claude says it is; [junk? ...]: it may be removed; / searches "
                  "them too.)" %
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
            self._junk_by_name = junk.find(files, {relpath: self._size(relpath) for relpath in files})
            self._start_indexing()
            chosen = picker.pick_files(
                self.inbox_path, files, header=header, picked=picked, label=LABEL,
                keys=self.REFRESH_KEY if self.inbox_is_cloud else '', selected=selected,
                previews=lambda send, files=files: self._send_previews(files, send),
                shown_as=lambda files=files: self._shown_as(files),
                notify_keys=DESCRIBE_KEY + OPEN_KEY, enter_picks_selection=True,
                on_notify=lambda key, selected, picked, files=files: self._on_key(key, selected, picked, files),
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
        that Claude's looking at it), and why it looks like junk, if it does; and '': the status,
        what Claude is doing"""
        shown = {}
        for relpath in relpaths:
            tags = []
            if relpath in self._descriptions:
                tags.append(DESCRIBED % (self._descriptions[relpath],))
            elif relpath in self._describing:
                tags.append(LOOKING)
            junk_reason = self._junk(relpath)
            if junk_reason is not None:
                tags.append((JUNK_BY_NAME if relpath in self._junk_by_name else JUNK_BY_CLAUDE) % (junk_reason,))
            if tags:
                shown[relpath] = "%s  %s" % (os.path.basename(relpath), '  '.join(tags))
        describing, placing = len(self._describing), len(self._placing)
        failed = len([relpath for relpath in relpaths if relpath in self._failed])
        busy = ["%s %s" % (what, _files(count))
                for what, count in (("describing", describing), ("placing", placing)) if count]
        status = ("Claude: " + ', '.join(busy) if busy else
                  "Claude: couldn't do %s" % (_files(failed),) if failed else '')
        note = self._open_note
        if note is not None and (note[1] is None or time.monotonic() < note[1]):
            status = note[0] + ("; " + status if status else "")
        shown[''] = status
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
            elif relpath in self._failed and relpath not in self._descriptions:
                lines += ["", "Claude couldn't describe it:"] + _wrapped(self._failed[relpath], "  ")
            lines += self._copies_lines(relpath)
            recommendation = self._recommendations.get(relpath)
            if relpath in self._junk_by_name:
                lines += ["", MAYBE_JUNK, "By its name or size, it's:"] + _wrapped(self._junk_by_name[relpath], "  ")
            if recommendation and recommendation.get('action') == 'remove':
                if self._junk(relpath) is not None and relpath not in self._junk_by_name:
                    lines += ["", MAYBE_JUNK]
                lines += ["", "Claude recommends removing it:"] + _wrapped(recommendation.get('reason', ''), "  ")
            elif recommendation:
                # Relative to the sorted tree, so a long root doesn't hide where in it
                target = self._target(relpath)
                lines += ["", "Claude recommends it go to:", "  %s/" % (os.path.dirname(target) or '.',)]
                if os.path.basename(target) != os.path.basename(relpath):
                    lines += ["  renamed:"] + _wrapped(os.path.basename(target), "    ")
                lines += ["  (in %s)" % (self.root_path,)]
                lines += _wrapped(recommendation.get('reason', ''), "  ")
            elif relpath in self._placing:
                lines += ["", "Claude is working out where", "it goes..."]
            elif relpath in self._failed and relpath in self._descriptions:
                lines += ["", "Claude couldn't say where it goes:"] + _wrapped(self._failed[relpath], "  ")
            else:
                lines += ["", "Where it goes: Ctrl-I (or pick", "it, press Enter, and ask Claude)."]
            previews[relpath] = lines
        return previews

    def _act(self, relpaths):
        """Let the user choose what to do with the picked files at relpaths, and do it once they
        confirm. Returns the ones done (moved, copied, removed; in a dry run, the ones it would have
        done), or None if none were (or Claude was asked: nothing moved)."""
        count = _files(len(relpaths))
        undescribed = [relpath for relpath in relpaths
                       if relpath not in self._descriptions and relpath not in self._describing]
        unrecommended = [relpath for relpath in relpaths
                         if relpath not in self._recommendations and relpath not in self._placing]
        recommended = [relpath for relpath in relpaths
                       if relpath in self._recommendations and self._target(relpath) is not None]
        # Copies of the sorted tree's files, by their contents (whatever Claude says of them), and the
        # files with candidates there not compared yet
        removable = [relpath for relpath in relpaths if self._copies(relpath)]
        junky = [relpath for relpath in relpaths if self._junk(relpath) is not None]
        uncompared = [relpath for relpath in relpaths if relpath not in self._checked and self._root_index.is_built()
                      and elsewhere._same_sized(relpath, self._size(relpath), self._root_index)]
        not_yet = " (%d not compared yet: Ctrl-I compares them)" % (len(uncompared),) if uncompared else ""
        destinations = sorted({os.path.dirname(self._target(relpath)) for relpath in recommended})
        renamed = [relpath for relpath in recommended
                   if os.path.basename(self._target(relpath)) != os.path.basename(relpath)]
        renamed_text = ", %d renamed" % (len(renamed),) if renamed else ""
        if len(destinations) == 1:
            to = "Claude's recommendation: %s/%s" % (_join(self.root_path, destinations[0]),
                                                    " (%s)" % (renamed_text[2:],) if renamed else "")
            claudes_dirs = "Claude's dir, %s/" % (_join(self.root_path, destinations[0]),)
        else:
            to = "Claude's recommendations (%d dirs%s)" % (len(destinations), renamed_text)
            claudes_dirs = "Claude's dirs (%d)" % (len(destinations),)
        # A name to type is for one file
        one = "can't: a name is typed for one file" if len(relpaths) > 1 else None
        options = {
            self.DESCRIBE: ("Describe %s with Claude, while you go on (sends it their contents; or Ctrl-I)" %
                            (_of(len(undescribed), len(relpaths)),),
                            None if undescribed else "they all have a description, or are being described"),
            self.RECOMMEND: ("Ask Claude where %s go in %s, while you go on (or Ctrl-I)" %
                             (_of(len(unrecommended), len(relpaths)), self.root_path),
                             None if unrecommended else "they all have a recommendation, or are being placed"),
            self.MOVE_RECOMMENDED: ("Move %s to %s" % (_of(len(recommended), len(relpaths)), to),
                                    None if recommended else "none of them has a recommendation to move it yet"),
            self.MOVE_TO_CLAUDES_DIR: ("Move %s, keeping their names, to %s" %
                                       (_of(len(recommended), len(relpaths)), claudes_dirs),
                                       None if recommended else "none of them has a recommendation yet"),
            self.MOVE_TO_CLAUDES_DIR_TYPED: ("Move the file, under a name you type, to %s" % (claudes_dirs,),
                                             one or (None if recommended else "it has no recommendation yet")),
            self.REMOVE_COPIES: ("Remove %s that are copies of files in %s%s" %
                                 (_of(len(removable), len(relpaths)), self.root_path, not_yet),
                                 None if removable else "none of them is a copy of a file there (by its contents)"),
            self.REMOVE_JUNK: ("Remove %s that look like junk (to %s)" %
                               (_of(len(junky), len(relpaths)), "Drive's trash" if self.inbox_is_cloud else "the trash"),
                               None if junky else "none of them looks like junk (by its name, or as Claude says)"),
            self.MOVE_TO: ("Move the %s to... (pick a dir in %s)" % (count, self.root_path), None),
            self.MOVE_TO_CLAUDES_NAMES: ("Move the %s, under Claude's names (%d renamed), to... (pick a dir in %s)" %
                                         (count, len(renamed), self.root_path),
                                         None if renamed else "none of them has a name from Claude"),
            self.MOVE_TO_TYPED: ("Move the file, under a name you type, to... (pick a dir in %s)" % (self.root_path,),
                                 one),
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
            self.ask_in_background(unrecommended)
            return None
        if action == self.MOVE_RECOMMENDED:
            return self._approve(self.MOVE_TO, [(relpath, self._target(relpath)) for relpath in recommended])
        if action in (self.MOVE_TO_CLAUDES_DIR, self.MOVE_TO_CLAUDES_DIR_TYPED):
            plan = [(relpath, _join(os.path.dirname(self._target(relpath)), os.path.basename(relpath)))
                    for relpath in recommended]
        elif action in (self.MOVE_TO, self.COPY_TO, self.MOVE_TO_CLAUDES_NAMES, self.MOVE_TO_TYPED):
            destination = self._choose_dir('copy' if action == self.COPY_TO else 'move', count)
            if destination is None:
                return None
            # Claude's name, for the files it renamed
            names = {relpath: os.path.basename(self._target(relpath) if relpath in renamed else relpath)
                     for relpath in relpaths}
            plan = [(relpath, _join(destination, names[relpath] if action == self.MOVE_TO_CLAUDES_NAMES
                                    else os.path.basename(relpath)))
                    for relpath in relpaths]
        if action in (self.MOVE_TO_CLAUDES_DIR_TYPED, self.MOVE_TO_TYPED):
            plan = self._typed_name(plan)
            if plan is None:
                return None
        if action in (self.MOVE_TO_CLAUDES_DIR, self.MOVE_TO_CLAUDES_DIR_TYPED):
            return self._approve(self.MOVE_TO, plan)
        if action in (self.MOVE_TO, self.COPY_TO, self.MOVE_TO_CLAUDES_NAMES, self.MOVE_TO_TYPED):
            done = self._approve(self.COPY_TO if action == self.COPY_TO else self.MOVE_TO, plan)
            if done and self._known_replicas is not None:
                # Offered first next time
                self._known_replicas.record_dir(self.root_path, destination)
                replicas.save(self._known_replicas)
            return done
        if action == self.REMOVE:
            return self._remove(relpaths)
        if action == self.REMOVE_JUNK:
            return self._remove(junky, ["  %s: %s" % (relpath, self._junk(relpath)) for relpath in junky],
                                to_trash=True)
        if action == self.REMOVE_COPIES:
            return self._remove(removable, ["  %s: a copy of %s" % (relpath, ', '.join(
                _join(self.root_path, copy) for copy in self._copies(relpath)[:2]))
                for relpath in removable])
        return None

    def _typed_name(self, plan):
        """plan (one file: [(relpath, its path in the sorted tree)]) with the name the user types for
        it there, starting as Claude's (or its own); None if they typed none, or one that can't be"""
        (relpath, target), = plan
        recommendation = self._recommendations.get(relpath)
        default = os.path.basename(self._target(relpath) if recommendation and self._target(relpath)
                                   else relpath)
        lines = ["Moving %s" % (posixpath.join(self.inbox_path, relpath),),
                 "to %s/" % (_join(self.root_path, os.path.dirname(target)),)]
        if relpath in self._descriptions:
            lines.append(DESCRIBED % (self._descriptions[relpath],))
        lines += ["", "Its name there (Enter to keep it as it is; an empty one, or Ctrl-C, to go back):"]
        name = messages.ask("The file's name in %s" % (self.root_path,), lines, "> ", default, dryrun.label())
        if name is None:
            return None
        if '/' in name or name in ('.', '..'):
            messages.show("Not a name", ["%r can't be a file's name: it's a name, without '/'." % (name,)],
                          dryrun.label(), 'red')
            return None
        return [(relpath, _join(os.path.dirname(target), name))]

    def _junk(self, relpath):
        """Why the inbox's file at relpath looks like junk: by its name and size (junk.py), or as
        Claude says (a recommendation to remove it that isn't for a copy); None if it doesn't"""
        if relpath in self._junk_by_name:
            return self._junk_by_name[relpath]
        recommendation = self._recommendations.get(relpath)
        if recommendation and recommendation.get('action') == 'remove' and not recommendation.get('copies'):
            return recommendation.get('reason') or "Claude says so"
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

    # Claude

    def describe_in_background(self, relpaths):
        """Have Claude describe the files at relpaths (see ask_in_background())"""
        self.ask_in_background(relpaths, False)

    def ask_in_background(self, relpaths, place=True):
        """Have Claude describe the files at relpaths that have no description, and with place, say
        where they go (what Enter's "Ask Claude where" did, and Ctrl-I does): their contents are
        compared with the sorted tree's files first, so Claude knows which are copies. On a thread
        of its own, a batch at a time, while the user goes on: each picker shows them as they come."""
        with self._state_lock:
            for relpath in relpaths:
                needs_description = relpath not in self._descriptions
                needs_place = place and relpath not in self._recommendations
                if not (needs_description or needs_place):
                    continue
                self._failed.pop(relpath, None)
                if needs_place:
                    self._placing.add(relpath)
                if relpath in self._queued:
                    continue
                self._queued.add(relpath)
                self._queue.append(relpath)
                if needs_description:
                    self._describing.add(relpath)
            if self._queue and self._worker is None:
                self._worker = threading.Thread(target=self._ask_queued, daemon=True)
                self._worker.start()

    def _ask_queued(self):
        """Ask Claude about the queued files, a batch at a time, until there are none (on the
        worker's thread: nothing is printed, as a picker may have the screen)"""
        while True:
            with self._state_lock:
                if not self._queue:
                    self._worker = None
                    return
                batch = [self._queue.popleft() for _ in range(min(ai.BATCH_SIZE, len(self._queue)))]
            try:
                self._describe(batch)
                self._place([relpath for relpath in batch if relpath in self._placing])
            finally:
                with self._state_lock:
                    self._describing.difference_update(batch)
                    self._placing.difference_update(batch)
                    self._queued.difference_update(batch)

    def _describe(self, batch):
        """Have Claude describe the files of batch that have no description (on the worker's thread)"""
        relpaths = [relpath for relpath in batch if relpath not in self._descriptions]
        try:
            if relpaths:
                with self._drive_lock:
                    files = self._ai_files(relpaths, is_quiet=True)
                found = ai.describe(files, self._cache_key)
                self._descriptions.update(found)
                for relpath in relpaths:
                    if relpath not in found:
                        self._failed[relpath] = "Claude gave no description of it."
        except Exception as error:
            for relpath in relpaths:
                self._failed[relpath] = str(error)
        finally:
            with self._state_lock:
                self._describing.difference_update(batch)

    def _place(self, relpaths):
        """Have Claude say where the files at relpaths go, by their descriptions and which are copies
        of the sorted tree's files (their contents compared first), on the worker's thread"""
        relpaths = [relpath for relpath in relpaths if relpath not in self._recommendations]
        if not relpaths:
            return
        try:
            self._compare(relpaths)
            files = [ai.File(relpath, None, self._size(relpath)) for relpath in relpaths]
            found = ai.recommend(files, self._cache_key, self._root_dirs(), self.root_path, self._descriptions,
                                 {relpath: self._copies(relpath) for relpath in relpaths})
            self._recommendations.update(found)
            for relpath in relpaths:
                if relpath not in found:
                    self._failed[relpath] = "Claude didn't say where it goes."
        except Exception as error:
            for relpath in relpaths:
                self._failed[relpath] = str(error)

    def _compare(self, relpaths):
        """Compare the contents of the inbox's files at relpaths with their candidates in the sorted
        tree, the ones not compared yet (once the sorted tree is listed)"""
        self._start_indexing()
        self._indexing.join()
        elsewhere.check_all(relpaths, self._inbox_view, self._inbox_index, self._root_index, self._checked)

    def wait_for_claude(self):
        """Wait for what Claude is asked of files, without a screen (e.g. for a test)"""
        while True:
            worker = self._worker
            if worker is None:
                return
            worker.join()

    def _finish_describing(self):
        """Wait for what Claude is asked of files, if anything, on a progress screen (Ctrl-C stops
        waiting: what it said so far is kept)"""
        if not self._queued:
            return
        title = ("Waiting for Claude to finish with %s (what it said so far is kept)" %
                 (_files(len(self._queued)),))
        failed_before = len(self._failed)
        with messages.progress_screen(title, dryrun.label(), wait=False):
            try:
                while self._queued:
                    messages.print_progress("%s left (%d being described, %d placed), %d failed" % (
                        _files(len(self._queued)), len(self._describing),
                        len(self._queued) - len(self._describing), len(self._failed) - failed_before))
                    time.sleep(DESCRIBED_WAIT_INTERVAL)
            except KeyboardInterrupt:
                messages.note_stopped()
        if len(self._failed) > failed_before:
            messages.show("Claude couldn't finish with %s" % (_files(len(self._failed) - failed_before),),
                          [list(self._failed.values())[-1]], dryrun.label(), 'red')

    def _ai_files(self, relpaths, is_quiet=False):
        """ai.File of each of the inbox's files at relpaths: a Drive one downloaded first (one at a
        time; or found downloaded, see downloads.py), unless it's too big to be read, or a Google
        file. With is_quiet, it prints nothing (a picker may have the screen)."""
        files = []
        for number, relpath in enumerate(relpaths, 1):
            size = self._size(relpath)
            local_path = None
            if not self.inbox_is_cloud:
                local_path = os.path.join(self.inbox_path, relpath)
            elif (size or 0) <= ai.MAX_READ_SIZE and self._inbox_tree.cant_fetch(self._full(relpath)) is None:
                if not is_quiet:
                    messages.print_progress("Downloading %d of %d files for Claude: %s" %
                                            (number, len(relpaths), relpath))
                try:
                    local_path = self._downloaded(relpath)
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

    # Opening a file

    def _on_key(self, key, selected, picked, files):
        """A notify key pressed in the picker of files (on another thread): Ctrl-X opens the
        selected file, Ctrl-I asks Claude about the picked ones (or the selected one, or a dir's)"""
        if key == OPEN_KEY:
            self.open_in_background(selected, files)
        else:
            self.ask_in_background(picked or [relpath for relpath in files if _is_at_or_under(relpath, selected)])

    def open_in_background(self, relpath, files):
        """Open the inbox's file at relpath (of files) with its program (xdg-open), as if
        double-clicked, on a thread of its own: a Drive one is downloaded first (or found
        downloaded). The bottom line says how it went."""
        threading.Thread(target=self._open, args=(relpath, files), daemon=True).start()

    def _open(self, relpath, files):
        name = os.path.basename(relpath) or self.inbox_path
        try:
            if not self.inbox_is_cloud:
                path = os.path.join(self.inbox_path, relpath)
            elif relpath not in files:
                raise OSError("a Google Drive folder can't be opened here")
            else:
                reason = self._inbox_tree.cant_fetch(self._full(relpath))
                if reason is not None:
                    raise OSError(reason)
                self._open_note = ("Downloading %s to open it..." % (name,), None)
                with self._drive_lock:
                    path = self._downloaded(relpath)
            # Its own session, so it outlives the picker (and dirdelta), and says nothing on its
            # screen
            subprocess.Popen(['xdg-open', path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            self._open_note = ("Opened %s" % (name,), time.monotonic() + OPENED_SHOWN_FOR)
        except OSError as error:
            self._open_note = ("Couldn't open %s: %s" % (name, error), time.monotonic() + OPENED_SHOWN_FOR)

    def _downloaded(self, relpath):
        """The local path of the inbox's Drive file at relpath, downloaded unless it was (see
        downloads.py). Raises OSError if it can't be."""
        return downloads.get(posixpath.join(self.inbox_path, relpath), self._size(relpath),
                             lambda local_path: self._inbox_tree.fetch_file(self._full(relpath), local_path))

    # Moving, copying, removing

    def _choose_dir(self, verb, count):
        """Let the user choose the dir in the sorted tree to move or copy (verb) the files (count, e.g.
        '2 files') to: one of its recent ones, if it has any, or one picked (_pick_dir()). Returns its
        relpath ('' the root), or None."""
        recent = self._known_replicas.dirs_of(self.root_path) if self._known_replicas is not None else []
        if not recent:
            return self._pick_dir(verb, count)
        options = {self.RECENT_DIR % (relpath or '.',): relpath for relpath in recent}
        pick = self.PICK_DIR
        answer = picker.pick_option(list(options) + [pick], header="Where in %s to %s the %s?" %
                                    (self.root_path, verb, count), label=LABEL)
        if answer == pick:
            return self._pick_dir(verb, count)
        if answer not in options:
            return None
        return self._not_the_inbox(options[answer])

    def _pick_dir(self, verb, count):
        """Let the user pick a dir in the sorted tree to move or copy (verb) the files (count) to, or
        make a new one in it (NEW_DIR_KEY, then its name). Returns its relpath ('' the root), or
        None."""
        header = ("Pick the dir in %s to %s the %s to (Enter picks the selected dir; %s: a new dir in it)" %
                  (self.root_path, verb, count, self.NEW_DIR_KEY))
        if self.root_is_cloud:
            root = clouddirtree.factory(self.root_path)
            picked = picker.pick_from_tree(root, header=header, dirs_only=True, root_name=self.root_path,
                                           keys=self.NEW_DIR_KEY)
            key, relpath = (picked[0], picked[1][0].relpath) if picked else ('', None)
        else:
            picked = picker.pick_under_dir(self.root_path, dirs_only=True, lazy=True, header=header,
                                           keys=self.NEW_DIR_KEY)
            key, relpath = (picked[0], _relpath(picked[1], self.root_path)) if picked else ('', None)
        if relpath is not None and key == self.NEW_DIR_KEY:
            relpath = self._new_dir(relpath, verb, count)
        return self._not_the_inbox(relpath)

    def _new_dir(self, parent, verb, count):
        """The relpath of a new dir in the sorted tree's dir at parent, its name typed (a/b: one in a
        new one), to move or copy (verb) the files (count) to; it's made when they go there. None if
        no name, or one that can't be, was typed."""
        name = messages.ask("A new dir in %s/" % (_join(self.root_path, parent),),
                            ["The new dir to %s the %s to, in %s/" % (verb, count, _join(self.root_path, parent)),
                             "(a/b makes b in a new a). An empty name, or Ctrl-C, goes back."],
                            "> ", label=dryrun.label())
        if name is None:
            return None
        parts = name.strip('/').split('/')
        if any(part in ('', '.', '..') for part in parts):
            messages.show("Not a dir's name", ["%r can't be a new dir's name." % (name,)], dryrun.label(), 'red')
            return None
        return _join(parent, *parts)

    def _not_the_inbox(self, relpath):
        """relpath (a dir in the sorted tree), unless it's the inbox or in it (then it says so, and
        it's None)"""
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
        # Once it's done (or stopped), Enter goes back to the picker, so what was done can be read
        with messages.progress_screen(summary + (" (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock:
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
        if action == self.MOVE_TO:
            self.changes.note(self.root_path, 'added', len(done), self.inbox_path)
            self.changes.note(self.inbox_path, 'moved', len(done), self.root_path, 'to')
        else:
            self.changes.note(self.root_path, 'copied', len(done), self.inbox_path)
        not_done = [relpath for relpath, _ in plan if relpath not in set(done)]
        if not_done:
            self._say_not_done("moved" if action == self.MOVE_TO else "copied", not_done, len(plan))
        return done

    def _say_not_done(self, what, relpaths, count):
        """Show that the inbox's files at relpaths (of count) weren't moved, copied or removed (what)"""
        messages.show("Not all were %s" % (what,),
                      ["%d of the %s couldn't be %s (they're still in %s):" % (
                          len(relpaths), _files(count), what, self.inbox_path)] +
                      ["  " + relpath for relpath in relpaths[:interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED]] +
                      (["  (and %d more)" % (len(relpaths) - interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED,)]
                       if len(relpaths) > interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED else []),
                      dryrun.label(), 'red')

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

    def log_trees(self):
        """[(tree, path)] of the inbox and the sorted tree, each a tree of its own (as it is now: a
        Drive one from the cache), to read and write their logs (see replicalog.py)"""
        return [(_tree(path), path) for path in (self.inbox_path, self.root_path)]

    def _entries(self, relpaths):
        """The entries of the inbox's files at relpaths (in its tree), to remove them"""
        found = []
        for relpath in relpaths:
            node = self._inbox_tree.get_node(relpath)
            found.append(node.data if node is not None else entries.FileEntry(
                os.path.basename(relpath), relpath, os.path.join(self._inbox_tree.fullpath(), relpath)))
        return found

    def _remove(self, relpaths, listed=None, to_trash=False):
        """Remove the inbox's files at relpaths, once the user confirms twice; listed: the lines that
        list them (else their relpaths). With to_trash, a local inbox's go to the desktop's trash
        (Drive's go to its trash anyway), rather than for good."""
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
            _files(len(relpaths)), self.inbox_path, " (to Drive's trash)" if self.inbox_is_cloud else
            " (to the trash)" if to_trash else ", for good")
        if picker.pick_option([self.CONFIRM_NO, self.CONFIRM_SURE], header=sure, label=LABEL) != self.CONFIRM_SURE:
            return None
        file_entries = self._entries(self._full(relpath) for relpath in relpaths)
        # Once it's done (or stopped), Enter goes back to the picker, so what was removed can be read
        with messages.progress_screen("Removing %s from %s%s" % (_files(len(relpaths)), self.inbox_path,
                                                                " (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()), self._drive_lock, \
                (self._inbox_tree.trashing() if to_trash and not self.inbox_is_cloud else contextlib.nullcontext()):
            self._inbox_tree.remove_files(file_entries)
        if dryrun.DRYRUN:
            return relpaths
        left = set(self._inbox_files())
        kept = [relpath for relpath in relpaths if relpath in left]
        if kept:
            self._say_not_done("removed", kept, len(relpaths))
        removed = [relpath for relpath in relpaths if relpath not in left]
        self.changes.note(self.inbox_path, 'removed', len(removed))
        return removed


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
    replicas.Replicas, saved) remembering them as a recent sort, and what's known of each (its log,
    see replicalog.py); once it's done, offer entries for the logs of the ones it changed"""
    sort = InboxSort(inbox_path, root_path, known_replicas)
    if known_replicas is not None:
        known_replicas.record_sort(sort.inbox_path, sort.root_path)
        replicalog.note_seen(sort.log_trees(), known_replicas)
        replicas.save(known_replicas)
    sort.run()
    if known_replicas is not None:
        replicalog.offer_entries(sort.changes, sort.log_trees(), known_replicas)


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
