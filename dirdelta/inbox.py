"""Sorting an inbox: a dir of files not yet sorted (e.g. cloud/unsorted), whose files the user moves
into a sorted tree (e.g. cloud/eliran), copies there, or removes, with Claude's help if they ask
for it (ai.py): a short description of each file, shown after its name, and where in the sorted
tree it belongs, shown beside it, to move it there.

The inbox and the sorted tree are both local dirs, or both in Drive: the files are moved within one
tree that has both (their common dir, or Drive's), so a move is a rename (in Drive, one request that
keeps the file's id), never a copy."""
import os
import posixpath
import subprocess
import tempfile
import textwrap

from dirdelta import ai
from dirdelta import clouddirtree
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


class InboxError(Exception):
    pass


def _files(count):
    return "1 file" if count == 1 else "%d files" % (count,)


def _join(*relpaths):
    return posixpath.join(*[relpath for relpath in relpaths if relpath]) if any(relpaths) else ''


class InboxSort(object):
    """The inbox at inbox_path and the sorted tree at root_path (both local dirs, or both cloud
    paths)"""
    NOTHING = "Nothing: back to the files"
    DESCRIBE = 'describe'
    RECOMMEND = 'recommend'
    MOVE_RECOMMENDED = 'move to the recommendations'
    MOVE_TO = 'move to'
    COPY_TO = 'copy to'
    REMOVE = 'remove'
    CONFIRM_NO = 'No'
    CONFIRM_YES = 'Yes'
    CONFIRM_SURE = 'Yes, remove them'
    REFRESH_KEY = 'r'

    def __init__(self, inbox_path, root_path):
        if paths.is_cloud_path(inbox_path) != paths.is_cloud_path(root_path):
            raise InboxError("The inbox and the sorted tree must both be local dirs, or both in Google "
                             "Drive (%s, %s)" % (inbox_path, root_path))
        self.is_cloud = paths.is_cloud_path(inbox_path)
        if self.is_cloud:
            self.inbox_path = paths.join_cloud('/'.join(paths.components(inbox_path)[1:]))
            self.root_path = paths.join_cloud('/'.join(paths.components(root_path)[1:]))
            inbox, root = paths.components(inbox_path)[1:], paths.components(root_path)[1:]
            common = os.path.commonprefix([inbox, root])
            tree_path = paths.join_cloud('/'.join(common))
            if not os.path.exists(drivecache.FILE_LIST_CACHE):
                for path in (self.inbox_path, self.root_path):
                    clouddirtree.refresh_cache(paths.path_in_cloud(path))
            self._tree = clouddirtree.factory(tree_path)
            self._inbox_rel = '/'.join(inbox[len(common):])
            self._root_rel = '/'.join(root[len(common):])
        else:
            self.inbox_path, self.root_path = os.path.realpath(inbox_path), os.path.realpath(root_path)
            for path in (self.inbox_path, self.root_path):
                if not os.path.isdir(path):
                    raise InboxError("%s is not a directory" % (path,))
            common = os.path.commonpath([self.inbox_path, self.root_path])
            self._tree = localdiskdirtree.LocalDiskDirTree(common, silent=True)
            self._inbox_rel = _relpath(self.inbox_path, common)
            self._root_rel = _relpath(self.root_path, common)
        if _is_at_or_under(self._root_rel, self._inbox_rel):
            raise InboxError("The sorted tree %s can't be in the inbox %s" % (self.root_path, self.inbox_path))
        if self.is_cloud:
            for relpath, path in ((self._inbox_rel, self.inbox_path), (self._root_rel, self.root_path)):
                node = self._tree.get_node(relpath)
                if node is None or not isinstance(node.data, entries.DirEntry):
                    raise InboxError("Google Drive has no folder %s (as of the cloud files list cache)" % (path,))
        # Neither is removed when it's left empty, nor moved whole
        self._tree.keep_dirs([self._inbox_rel, self._root_rel])
        # What Claude said of the inbox's files, by relpath (in the inbox)
        self._descriptions = {}
        self._recommendations = {}

    # The inbox's files

    def _inbox_files(self):
        """The inbox's files' relpaths (in it), each dir's together, sorted"""
        if self.is_cloud:
            full = self._tree._files_under(self._inbox_rel)
            relpaths = [_relpath_in(relpath, self._inbox_rel) for relpath in full]
        else:
            found = localdiskdirtree.LocalDiskDirTree(self.inbox_path, silent=True).files_by_name()
            relpaths = [relpath for files in found.values() for relpath, _ in files]
        return sorted(relpaths, key=lambda relpath: relpath.split('/'))

    def _full(self, relpath):
        """An inbox file's relpath in the tree"""
        return _join(self._inbox_rel, relpath)

    def _size(self, relpath):
        return self._tree.file_size(self._full(relpath))

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
                  "(To pick a file, press Space. When finished, press Enter.%s After a '|': what "
                  "Claude says it is.)" %
                  (self.inbox_path, self.root_path,
                   " %s: read the selected folder anew from Google Drive." % (self.REFRESH_KEY,)
                   if self.is_cloud else ""))
        picked, selected = [], None
        while True:
            files = self._inbox_files()
            if not files:
                messages.show("The inbox is empty", ["%s has no files to sort." % (self.inbox_path,)],
                              dryrun.label())
                return
            self._load_cached(files)
            labels = self._labels(files)
            previews = self._previews(files)
            chosen = picker.pick_files(
                self.inbox_path, files, header=header, picked=picked, label=LABEL,
                keys=self.REFRESH_KEY if self.is_cloud else '', selected=selected,
                previews=lambda send, previews=previews: send(previews, default=[]),
                shown_as=lambda labels=labels: labels)
            if chosen is None:
                return
            selected = chosen.selected
            if chosen.key == self.REFRESH_KEY:
                interactive_dir_sync.refresh_replica(self._tree, self._full(selected))
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

    def _labels(self, relpaths):
        """{relpath: what the picker shows it as}: its name, and Claude's description, if any"""
        return {relpath: "%s  | %s" % (os.path.basename(relpath), self._descriptions[relpath])
                for relpath in relpaths if relpath in self._descriptions}

    def _previews(self, relpaths):
        """{relpath: lines} beside the picker: the file's size, and what Claude said of it"""
        previews = {}
        for relpath in relpaths:
            size = self._size(relpath)
            lines = ["This one: %s" % (elsewhere.format_size(size),)] if size is not None else []
            if relpath in self._descriptions:
                lines += ["", "Claude says it's:"] + _wrapped(self._descriptions[relpath], "  ")
            recommendation = self._recommendations.get(relpath)
            if recommendation:
                # Relative to the sorted tree, so a long root doesn't hide where in it
                lines += ["", "Claude recommends it go to:",
                          "  %s/" % (recommendation['destination'] or '.',),
                          "  (in %s)" % (self.root_path,)]
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
        undescribed = [relpath for relpath in relpaths if relpath not in self._descriptions]
        unrecommended = [relpath for relpath in relpaths if relpath not in self._recommendations]
        recommended = [relpath for relpath in relpaths if relpath in self._recommendations]
        destinations = sorted({self._recommendations[relpath]['destination'] for relpath in recommended})
        if len(destinations) == 1:
            to = "Claude's recommendation: %s/" % (_join(self.root_path, destinations[0]),)
        else:
            to = "Claude's recommendations (%d dirs)" % (len(destinations),)
        options = {
            self.DESCRIBE: ("Describe %s with Claude (sends it their contents)" % (_files(len(undescribed)),),
                            None if undescribed else "they all have a description"),
            self.RECOMMEND: ("Ask Claude where %s go in %s (sends it their contents)" %
                             (_files(len(unrecommended)), self.root_path),
                             None if unrecommended else "they all have a recommendation"),
            self.MOVE_RECOMMENDED: ("Move %s to %s" % ("the " + count if len(recommended) == len(relpaths) else
                                                       "the %d of them with one" % (len(recommended),), to),
                                    None if recommended else "none of them has a recommendation yet"),
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
        if action in (self.DESCRIBE, self.RECOMMEND):
            self._ask_claude(action, undescribed if action == self.DESCRIBE else unrecommended)
            return None
        if action == self.MOVE_RECOMMENDED:
            return self._approve(self.MOVE_TO, [(relpath, self._recommendations[relpath]['destination'])
                                                for relpath in recommended])
        if action in (self.MOVE_TO, self.COPY_TO):
            destination = self._pick_dir("Pick the dir in %s to %s the %s to (Enter picks the selected dir)" %
                                         (self.root_path, 'move' if action == self.MOVE_TO else 'copy', count))
            if destination is None:
                return None
            return self._approve(action, [(relpath, destination) for relpath in relpaths])
        if action == self.REMOVE:
            return self._remove(relpaths)
        return None

    # Claude

    def _ask_claude(self, action, relpaths):
        """Ask Claude to describe the files at relpaths (DESCRIBE), or where they go (RECOMMEND), on
        a progress screen (Ctrl-C stops it: what it said so far is kept)"""
        what = "Describing" if action == self.DESCRIBE else "Asking where they go:"
        with messages.progress_screen("%s %s with Claude" % (what, _files(len(relpaths))), dryrun.label()):
            with tempfile.TemporaryDirectory(prefix='dirdelta-ai-') as temp_dir:
                try:
                    files = self._ai_files(relpaths, temp_dir)
                    progress = lambda done, total: messages.print_progress(
                        "Claude has looked at %d of %d files" % (done, total))
                    if action == self.DESCRIBE:
                        self._descriptions.update(ai.describe(files, self._cache_key, progress))
                    else:
                        recommendations = ai.recommend(files, self._cache_key, self._root_dirs(),
                                                       self.root_path, progress)
                        self._recommendations.update(recommendations)
                        self._descriptions.update({relpath: recommendation['description']
                                                   for relpath, recommendation in recommendations.items()})
                    messages.print_line("")
                    messages.print_line("Done: what Claude said is shown in the picker.")
                except ai.AIError as error:
                    messages.print_line("")
                    messages.print_line(str(error), "red")
                except KeyboardInterrupt:
                    messages.note_stopped()

    def _ai_files(self, relpaths, temp_dir):
        """ai.File of each of the inbox's files at relpaths: a Drive one downloaded into temp_dir
        first (one at a time), unless it's too big to be read, or a Google file"""
        files = []
        for number, relpath in enumerate(relpaths, 1):
            size = self._size(relpath)
            local_path = None
            if not self.is_cloud:
                local_path = os.path.join(self.inbox_path, relpath)
            elif (size or 0) <= ai.MAX_READ_SIZE and self._tree.cant_fetch(self._full(relpath)) is None:
                local_path = os.path.join(temp_dir, relpath)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                messages.print_progress("Downloading %d of %d files for Claude: %s" % (number, len(relpaths), relpath))
                try:
                    self._tree.fetch_file(self._full(relpath), local_path)
                except OSError as error:
                    messages.print_line("Couldn't download %s (%s): Claude goes by its name" % (relpath, error),
                                        "yellow")
                    local_path = None
            files.append(ai.File(relpath, local_path, size))
        return files

    def _root_dirs(self):
        """The sorted tree's dirs' relpaths (in it), not the inbox's (if it's in it)"""
        if self.is_cloud:
            node = self._tree.get_node(self._root_rel)
            dirs = [_relpath_in(dir_node.identifier, self._root_rel)
                    for dir_node in self._tree._tree.subtree(node.identifier).all_nodes_itr()
                    if isinstance(dir_node.data, entries.DirEntry) and dir_node.identifier != self._root_rel]
        else:
            result = subprocess.run(['find', self.root_path, '-mindepth', '1', '-type', 'd', '-printf', '%P\\0'],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            dirs = [os.fsdecode(path) for path in result.stdout.split(b'\0') if path]
        inbox_in_root = _relpath_in(self._inbox_rel, self._root_rel) if _is_at_or_under(
            self._inbox_rel, self._root_rel) else None
        return [dirpath for dirpath in dirs
                if inbox_in_root is None or not _is_at_or_under(dirpath, inbox_in_root)]

    # Moving, copying, removing

    def _pick_dir(self, header):
        """Let the user pick a dir in the sorted tree. Returns its relpath ('' the root), or None."""
        if self.is_cloud:
            root = clouddirtree.factory(self.root_path)
            picked = picker.pick_from_tree(root, header=header, dirs_only=True, root_name=self.root_path)
            relpath = picked[0].relpath if picked else None
        else:
            path = picker.pick_under_dir(self.root_path, dirs_only=True, lazy=True, header=header)
            relpath = None if path is None else _relpath(path, self.root_path)
        if relpath is not None and _is_at_or_under(_join(self._root_rel, relpath), self._inbox_rel):
            messages.show("That's the inbox", ["Pick a dir of %s that isn't in the inbox." % (self.root_path,)],
                          dryrun.label())
            return None
        return relpath

    def _approve(self, action, plan):
        """Show where each file of plan (relpath, destination dir in the sorted tree) goes, as the tree
        it makes, then, once the user confirms, move (MOVE_TO) or copy them there. Returns the picked
        files done (or that would have been, in a dry run), or None if the user didn't confirm."""
        verb = "Move" if action == self.MOVE_TO else "Copy"
        targets = {}
        for relpath, destination in plan:
            target = _join(destination, os.path.basename(relpath))
            targets.setdefault(target, []).append(relpath)
        clashes = {target: sources for target, sources in targets.items() if len(sources) > 1}
        if clashes:
            target = sorted(clashes)[0]
            messages.show("Files of the same name",
                          ["%d files would go to %s: %s. Pick them apart." %
                           (len(clashes[target]), _join(self.root_path, target), ', '.join(clashes[target]))],
                          dryrun.label(), 'red')
            return None
        destinations = sorted({destination for _, destination in plan})
        new_dirs = [destination for destination in destinations
                    if not self._tree._exists(_join(self._root_rel, destination))]
        previews = {}
        for target, (relpath,) in targets.items():
            lines = ["From: %s" % (posixpath.join(self.inbox_path, relpath),)]
            if self._tree._exists(_join(self._root_rel, target)):
                lines += ["", "There's a file there already:", "it's skipped."]
            if os.path.dirname(target) in new_dirs:
                lines += ["", "In a new dir."]
            recommendation = self._recommendations.get(relpath)
            if recommendation and recommendation['destination'] == os.path.dirname(target):
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
        if dryrun.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        if picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                              label=LABEL) != self.CONFIRM_YES:
            return None
        moves = [(self._full(relpath), _join(self._root_rel, destination, os.path.basename(relpath)))
                 for relpath, destination in plan]
        with messages.progress_screen(summary + (" (a dry run)" if dryrun.DRYRUN else ""), dryrun.label()):
            done = (self._tree.move_files(moves) if action == self.MOVE_TO else
                    self._tree.copy_files_within(moves))
        if dryrun.DRYRUN:
            return [relpath for relpath, _ in plan]
        done_sources = {relpath for relpath, _ in done}
        return [relpath for relpath, _ in plan if self._full(relpath) in done_sources]

    def _remove(self, relpaths):
        """Remove the inbox's files at relpaths, once the user confirms twice"""
        lines = ["Remove %s from %s?" % (_files(len(relpaths)), self.inbox_path)]
        lines += ["  %s" % (relpath,) for relpath in relpaths[:interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED]]
        if len(relpaths) > interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED:
            lines.append("  (and %d more)" % (len(relpaths) - interactive_dir_sync.InteractiveDirSync.MAX_FILES_LISTED,))
        if dryrun.DRYRUN:
            lines.append("(A dry run: nothing on disk will change. DRYRUN=0 changes files.)")
        if picker.pick_option([self.CONFIRM_NO, self.CONFIRM_YES], header='\n'.join(lines),
                              label=LABEL) != self.CONFIRM_YES:
            return None
        sure = "Are you sure? %s will be removed from %s%s." % (
            _files(len(relpaths)), self.inbox_path, " (to Drive's trash)" if self.is_cloud else ", for good")
        if picker.pick_option([self.CONFIRM_NO, self.CONFIRM_SURE], header=sure, label=LABEL) != self.CONFIRM_SURE:
            return None
        file_entries = []
        for relpath in relpaths:
            node = self._tree.get_node(self._full(relpath))
            file_entries.append(node.data if node is not None else entries.FileEntry(
                os.path.basename(relpath), self._full(relpath), os.path.join(self._tree.fullpath(), self._full(relpath))))
        with messages.progress_screen("Removing %s from %s%s" % (_files(len(relpaths)), self.inbox_path,
                                                                " (a dry run)" if dryrun.DRYRUN else ""),
                                      dryrun.label()):
            self._tree.remove_files(file_entries)
        if dryrun.DRYRUN:
            return relpaths
        left = set(self._inbox_files())
        return [relpath for relpath in relpaths if relpath not in left]


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
