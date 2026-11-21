"""Merging a text file that differs (the action menu's Merge them...): its two versions read (a Drive one
downloaded), merged by the user (ui/merging.py: the browser's merge window, with the AI's merge to start
from, or the terminal's editor), and the merge written to both replicas, replacing their versions as Copy
does (a local one's to the trash, a Drive one's kept as an older version), once the user confirms"""
import os
import tempfile

from dirdelta.claude import ai
from dirdelta.claude.ai import merging as ai_merging
from dirdelta.known import replicanames
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import diffing
from dirdelta.trees import entries
from dirdelta.ui import merging
from dirdelta.ui import messages
from dirdelta.ui import opening
from dirdelta.util import dryrun

# The biggest version merged
MAX_SIZE = 1024 * 1024


class Merging(object):
    """Merges (InteractiveDirSync's)"""

    def _cant_merge(self, relpaths):
        """Why the files at relpaths can't be merged (one that differs, in replicas both written), or None"""
        if len(relpaths) != 1 or relpaths[0] not in self.differs:
            return "can't: for one file that differs"
        if not (replica_ops.is_writable(self._src) and replica_ops.is_writable(self._dst)):
            return "can't: one of them is read-only"
        return None

    def _merge_selected(self, selected):
        """g: merge the selected file, if it's one that can be merged (else say why). Returns as _merge()"""
        reason = self._cant_merge([selected] if selected else [])
        if reason is not None:
            messages.show("Merge", ["Select a text file that differs to merge its two versions (%s)." %
                                    (reason.replace("can't: ", ''),)], dryrun.label())
            return None
        return self._merge(selected)

    def _merge(self, relpath):
        """Merge the file's two versions and write the merge to both. Returns [relpath] once it's written (in a
        dry run, would have been), or None"""
        title = "Merge %s" % (os.path.basename(relpath),)
        # (Named as the diff names them)
        names = replicanames.short_names([self._path_of(self._src), self._path_of(self._dst)])
        src_name, dst_name = names[self._path_of(self._src)], names[self._path_of(self._dst)]
        versions = []
        for replica, name in ((self._src, src_name), (self._dst, dst_name)):
            messages.print_line("Getting %s's version..." % (name,))
            try:
                read = _read_text(opening.Opener(replica).local_path(relpath, MAX_SIZE))
            except OSError as error:
                messages.show(title, ["Couldn't get %s's version: %s" % (name, error)], dryrun.label(), 'red')
                return None
            if read is None:
                messages.show(title, ["%s's version isn't text, or it's over %d KB: it can't be merged here." %
                                      (name, MAX_SIZE // 1024)], dryrun.label())
                return None
            versions.append(read)
        (lines_a, ends_a), (lines_b, _) = versions

        def suggest(context=''):
            try:
                return ai_merging.suggest_merge(src_name, lines_a, dst_name, lines_b, context)
            except ai.AIError as error:
                raise Exception(str(error))
        merged = merging.merge(title, (src_name, dst_name), lines_a, lines_b, dryrun.label(), suggest)
        if merged is None:
            return None
        lines = ["Write this merge of %s (%d lines) to both %s and %s?" % (relpath, len(merged), src_name, dst_name),
                 self._replaced_note(self._src, 1), self._replaced_note(self._dst, 1)]
        if merging.has_marks(merged):
            lines.append("Careful: it still has conflict marks (<<<<<<<, =======, >>>>>>>) in it.")
        if dryrun.DRYRUN:
            lines.append(dryrun.note())
        if not self._said_yes(lines, self.LABELS[self.MERGE]):
            return None
        self._write_merge(relpath, merged, ends_a)
        return [relpath]

    def _write_merge(self, relpath, merged, ends):
        """Write the merged lines (ends: the line end, and whether the last line had one) to both replicas"""
        newline, has_last = ends
        title = "Writing the merge of %s" % (relpath,) + (" (a dry run)" if dryrun.DRYRUN else "")
        with tempfile.TemporaryDirectory(prefix='dirdelta-merge-') as tmp:
            path = os.path.join(tmp, os.path.basename(relpath))
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(newline.join(merged) + (newline if has_last else ''))
            entry = entries.FileEntry(os.path.basename(relpath), relpath, path)
            with messages.progress_screen(title, dryrun.label()):
                for replica in (self._src, self._dst):
                    with replica.replacing():
                        replica.copy_in([entry])
        if not dryrun.DRYRUN:
            # (As Copy's: what's done is noted, and the file no longer differs)
            self._last_action = self.COPY
            for replica in (self._src, self._dst):
                self._note(replica, 'merged', 1)


def _read_text(path):
    """(its lines, (its line end, whether its last line has one)) of the text file at path, or None if it
    isn't one (or it's None: too big), or isn't UTF-8"""
    if path is None or not diffing.is_text(path):
        return None
    with open(path, 'rb') as f:
        data = f.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        return None
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return None
    newline = '\r\n' if '\r\n' in text else '\n'
    return text.splitlines(), (newline, text.endswith(('\n', '\r')))
