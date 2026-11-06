"""The inbox's files that are copies of the sorted tree's, or junk"""
import threading

from dirdelta.inbox.constants import CLAUDE_STYLE, IN_SORTED_TREE_TITLE, SURELY_A_COPY
from dirdelta.inbox.formatting import files_text, grey_line, join_path, wrapped_path
from dirdelta.matching import elsewhere
from dirdelta.ui import picker


class Copies(object):
    """Copies and junk (InboxSort's)"""

    def _junk(self, relpath):
        """Why the inbox's file at relpath looks like junk: by its name and size (junk.py), or as
        Claude says (a recommendation to remove it that isn't for a copy); None if it doesn't"""
        if relpath in self._junk_by_name:
            return self._junk_by_name[relpath]
        recommendation = self._claude.recommendation(relpath)
        if recommendation and recommendation.get('action') == 'remove' and not recommendation.get('copies'):
            return recommendation.get('reason') or "Claude says so"
        return None

    def _copies(self, relpath):
        """The sorted tree's files (relpaths in it) with the same contents as the inbox's at relpath,
        of the ones compared, and the ones of its hash, if it's known (see elsewhere.known_same())"""
        copies = {match for match, is_same in self._checked.get(relpath, {}).items() if is_same}
        copies |= {match for match, is_same in elsewhere.known_same(relpath, self._inbox_index,
                                                                    self._root_index).items() if is_same}
        return sorted(copies)

    def _copies_lines(self, relpath):
        """A preview's lines of what the sorted tree has of the inbox's file at relpath: its copies,
        or that it has none, or its candidates (to compare when it's selected)"""
        copies = self._copies(relpath)
        title = (IN_SORTED_TREE_TITLE + " ", 'bold,' + CLAUDE_STYLE)
        if copies:
            return (["", picker.styled([title, ("Yes", 'bold,green')])] +
                    [line for copy in copies[:3] for line in wrapped_path(join_path(self.root_path, copy), "    ")] +
                    [SURELY_A_COPY])
        if relpath in self._checked:
            return ["", picker.styled([title, ("No", 'bold,red'), (" (contents compared)", 'grey')])]
        if not self._root_index.is_built():
            return ["", picker.styled([title]), grey_line("  Looking through the sorted tree...")]
        candidates = elsewhere.matches_of_size(relpath, self._size(relpath), self._root_index)
        if candidates:
            return ["", picker.styled([title]), grey_line("  %s of its size there:" % (files_text(len(candidates)),)),
                    grey_line("  compared when it's selected")]
        # None of its size (nor of its hash) there
        return ["", picker.styled([title, ("No", 'bold,red')])]

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
