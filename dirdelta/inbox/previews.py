"""What the inbox's picker shows of each file: its tags, and its preview"""
import os
import posixpath
import time

from dirdelta.hashes import hashing
from dirdelta.inbox.constants import (CLAUDE_STYLE, DESCRIBED, DESCRIPTION_TITLE, DESTINATION_TITLE,
                                      DIR_TITLE, JUNK_BY_CLAUDE, JUNK_BY_NAME, LOOKING, LOOKING_AT_DIR,
                                      MAYBE_JUNK, PREVIEWS_INTERVAL)
from dirdelta.inbox.formatting import _dirs, _files, _grey, _title, _wrapped, _wrapped_path
from dirdelta.screens import hashes_screen
from dirdelta.ui import opening
from dirdelta.ui import picker
from dirdelta.util import text


class Previews(object):
    """The picker's tags and previews (InboxSort's)"""

    def _shown_as(self, relpaths):
        """{relpath: what the picker shows it as}: its name, and Claude's description, if any (or that Claude's looking at it),
        and why it looks like junk, if it does, and whether it's hashed (if the inbox is local); and
        '': the status, how far hashing got and what
        Claude is doing"""
        shown = {}
        job = hashing.job_for(self.inbox_path) if not self.inbox_is_cloud else None
        for relpath in relpaths:
            # Each (text, style): Claude's in its color, junk in a guess's yellow
            tags = []
            if relpath in self._descriptions:
                tags.append((DESCRIBED % (self._descriptions[relpath],), CLAUDE_STYLE))
            elif relpath in self._describing:
                tags.append((LOOKING, 'grey'))
            junk_reason = self._junk(relpath)
            if junk_reason is not None:
                tags.append(((JUNK_BY_NAME if relpath in self._junk_by_name else JUNK_BY_CLAUDE) % (junk_reason,),
                             'yellow'))
            if job is not None:
                tag = hashing.tag(job, relpath)
                tags.append((tag, hashing.TAG_STYLES[tag]))
            if tags:
                shown[relpath] = picker.styled([(os.path.basename(relpath), None)] +
                                               [part for tag in tags for part in (("  ", None), tag)])
        # The dirs Claude said what they are of, as wholes (treepicker skips the ones that aren't there)
        with self._state_lock:
            dirpaths = set(self._dir_recommendations) | set(self._dir_asking)
        for dirpath in dirpaths:
            recommendation = self._dir_recommendation(dirpath)
            tag = ((DESCRIBED % (recommendation['summary'],), CLAUDE_STYLE) if recommendation and recommendation.get('summary') else
                   (LOOKING_AT_DIR, 'grey') if dirpath in self._dir_asking else None)
            if tag is not None:
                # treepicker puts the dir's '/' after its name
                shown[dirpath] = picker.styled([(posixpath.basename(dirpath), None), ("  ", None), tag])
        describing, placing = len(self._describing), len(self._placing)
        failed = len([relpath for relpath in relpaths if relpath in self._failed])
        busy = ["%s %s" % (what, _files(count))
                for what, count in (("describing", describing), ("placing", placing)) if count]
        if self._dir_asking:
            busy.append("asking about %s" % (_dirs(len(self._dir_asking)),))
        status = ("Claude: " + ', '.join(busy) if busy else
                  "Claude: couldn't do %s" % (_files(failed),) if failed else '')
        # Downloading files to open them: how far it got (on the status bar, first), and each
        # file's tag
        opening.with_tags(shown, self._opener, os.path.basename)
        parts = self._opener.status_parts() + ([(status, 'yellow')] if status else [])
        shown[''] = (hashes_screen.picker_status(self._trees(), parts) if self._jobs() else
                     picker.segments(parts) if self._opener.status_parts() else status)
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
        """{relpath: lines} beside the picker: the file's size, what Claude said of it, where the
        sorted tree has it already, and where it goes; each under a title in its color (Claude's
        in its own, see CLAUDE_STYLE)"""
        previews = {}
        for relpath in relpaths:
            size = self._size(relpath)
            lines = [picker.styled([("Size: ", 'bold'), (text.format_size(size), None)])] if size is not None else []
            if relpath in self._descriptions:
                lines += ["", _title(DESCRIPTION_TITLE, CLAUDE_STYLE)] + _wrapped(self._descriptions[relpath], "  ")
            elif relpath in self._describing:
                lines += ["", _title(DESCRIPTION_TITLE, CLAUDE_STYLE), _grey("  Claude is looking at it...")]
            elif relpath in self._failed and relpath not in self._descriptions:
                lines += ["", _title(DESCRIPTION_TITLE + " failed", 'red')] + _wrapped(self._failed[relpath], "  ")
            lines += self._copies_lines(relpath)
            recommendation = self._recommendations.get(relpath)
            if relpath in self._junk_by_name:
                lines += ["", MAYBE_JUNK, _title("Junk? By its name or size:", 'yellow')] + \
                    _wrapped(self._junk_by_name[relpath], "  ")
            if recommendation and recommendation.get('action') == 'remove':
                if self._junk(relpath) is not None and relpath not in self._junk_by_name:
                    lines += ["", MAYBE_JUNK]
                lines += ["", _title("Recommendation (ai): remove it", CLAUDE_STYLE)] + \
                    _wrapped(recommendation.get('reason', ''), "  ")
            elif recommendation:
                # Relative to the sorted tree, so a long root doesn't hide where in it
                target = self._target(relpath)
                is_renamed = os.path.basename(target) != os.path.basename(relpath)
                lines += ["", _title(DESTINATION_TITLE, CLAUDE_STYLE)]
                lines += _wrapped(target if is_renamed else "%s/" % (os.path.dirname(target) or '.',), "  ")
                if is_renamed:
                    lines.append(_grey("  (renamed)"))
                # Why, apart from where
                lines += [""] + _wrapped(recommendation.get('reason', ''), "  ")
            elif relpath in self._placing:
                lines += ["", _title(DESTINATION_TITLE, CLAUDE_STYLE), _grey("  Claude is working it out...")]
            elif relpath in self._failed and relpath in self._descriptions:
                lines += ["", _title(DESTINATION_TITLE + " failed", 'red')] + _wrapped(self._failed[relpath], "  ")
            else:
                lines += ["", picker.styled([("Dest. path:", 'bold')]), _grey("  Ctrl-I asks Claude")]
            previews[relpath] = lines
        for dirpath, (count, size) in self._dir_stats(relpaths).items():
            previews[dirpath] = self._dir_preview(dirpath, count, size)
        return previews

    def _dir_preview(self, dirpath, count, size):
        """The lines beside the picker of the inbox's dir at dirpath (of count files, of size): what
        Claude said of it as a whole, if it was asked (Ctrl-I)"""
        lines = [picker.styled([("Dir: ", 'bold'), ("%s, %s" % (_files(count), text.format_size(size)), None)])]
        recommendation = self._dir_recommendation(dirpath)
        if dirpath in self._dir_asking:
            return lines + ["", _title(DIR_TITLE, CLAUDE_STYLE), _grey("  Claude is looking at it...")]
        if recommendation is None and dirpath in self._dir_failed:
            return lines + ["", _title(DIR_TITLE + " failed", 'red')] + _wrapped(self._dir_failed[dirpath], "  ")
        if recommendation is None:
            return lines + ["", picker.styled([("Dir recommendation:", 'bold')]),
                            _grey("  Ctrl-I asks Claude about the dir"), _grey("  as a whole")]
        lines += ["", _title(DIR_TITLE, CLAUDE_STYLE)] + _wrapped(recommendation.get('summary', ''), "  ") + [""]
        if recommendation['action'] == 'move':
            is_merged = self._root_tree.exists(recommendation['path'])
            lines += [picker.styled([("Move it %s:" % ("into the dir there" if is_merged else "to"), 'bold')])]
            lines += _wrapped_path(recommendation['path'] + '/', "  ")
        elif recommendation['action'] == 'remove':
            lines += [picker.styled([("Remove it", 'bold')])]
        else:
            lines += [picker.styled([("Its files don't go together:", 'bold')]),
                      _grey("  pick them (Space), then Ctrl-I"), _grey("  asks about each")]
        if recommendation.get('reason'):
            lines += [""] + _wrapped(recommendation['reason'], "  ")
        copies = self._dir_copies.get(dirpath)
        if copies:
            lines += ["", "%s of it in the sorted tree already" % (_files(copies),)]
        if recommendation['action'] != 'split':
            lines += ["", _grey("  Enter: the menu, to do it")]
        return lines
