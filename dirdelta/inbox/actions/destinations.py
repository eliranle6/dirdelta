"""Where the action menu's options put the files, and the lines saying so"""
import os
import posixpath
import shutil

from dirdelta.inbox.constants import ASK, LABEL, OPEN, READ, REMOVE, VERB_COLORS
from dirdelta.inbox.formatting import bracket, files_text, fitting, join_path
from dirdelta.known import replicas
from dirdelta.ui import opening
from dirdelta.ui import picker


class Destinations(object):
    """The action menu's destinations (InboxSort's)"""

    def _said_lines(self, verb, text):
        """The lines below the menu for an option that says what it does in its own words"""
        return [picker.segments([(" %s " % (verb.upper(),), VERB_COLORS[verb]), (text, None)])]

    def _open(self, relpaths):
        if opening.confirm(self._opener, relpaths, relpaths, LABEL):
            self.open_in_background(relpaths, relpaths)

    def _to_a_dir_in_inbox(self, relpaths, count):
        destination = self._pick_dir('move', count, in_inbox=True)
        return None if destination is None else self._move_in_inbox(relpaths, destination)

    def _to_claudes_dir(self, recommended, is_typed=False):
        """Move the recommended files to the dirs Claude says, each under its own name, or (is_typed:
        one file) one the user types"""
        plan = [(relpath, join_path(os.path.dirname(self._target(relpath)), os.path.basename(relpath)))
                for relpath in recommended]
        if is_typed:
            plan = self._typed_name(plan)
        return None if plan is None else self._approve(self.MOVE_TO, plan)

    def _dir_to_a_dir(self, dirpath, relpaths, is_typed=False):
        """Move the inbox's dir at dirpath (its files: relpaths) into a dir the user chooses, under its
        own name (is_typed: one they type), as a whole; offered first next time, if it went"""
        destination = self._choose_dir('move', "%s of %s/" % (files_text(len(relpaths)), dirpath))
        if destination is None:
            return None
        name = posixpath.basename(dirpath)
        if is_typed:
            name = self._typed_dir_name(dirpath, destination)
            if name is None:
                return None
        done = self._approve(self.MOVE_TO, [(relpath, join_path(destination, name, relpath[len(dirpath) + 1:]))
                                            for relpath in relpaths])
        if done and self._known_replicas is not None:
            self._known_replicas.record_dir(self.root_path, destination)
            replicas.save(self._known_replicas)
        return done

    def _to_a_dir(self, action, relpaths, renamed, count):
        """Move or copy (action) the files to a dir the user chooses, under their own names, Claude's
        (for the ones it renamed: MOVE_TO_CLAUDES_NAMES) or one typed (MOVE_TO_TYPED); offered first
        next time, if they went"""
        destination = self._choose_dir('copy' if action == self.COPY_TO else 'move', count)
        if destination is None:
            return None
        names = {relpath: os.path.basename(self._target(relpath) if relpath in renamed and action == self.MOVE_TO_CLAUDES_NAMES
                                           else relpath) for relpath in relpaths}
        plan = [(relpath, join_path(destination, names[relpath])) for relpath in relpaths]
        if action == self.MOVE_TO_TYPED:
            plan = self._typed_name(plan)
            if plan is None:
                return None
        done = self._approve(self.COPY_TO if action == self.COPY_TO else self.MOVE_TO, plan)
        if done and self._known_replicas is not None:
            self._known_replicas.record_dir(self.root_path, destination)
            replicas.save(self._known_replicas)
        return done

    def _destination_lines(self, verb, parts, relpaths, acted_on):
        """The lines below the menu for an option: what it does to the files (verb, see VERB_COLORS),
        as a label in its color, and where it puts them (parts: the path's, each (text, where it's
        from)), and under the path, a bracket under each part saying where it's from, in that one's
        color (see SORTED_TREE)"""
        verb_label = " %s " % (verb.upper(),)
        if not parts:
            what = (os.path.basename(acted_on[0]) if len(acted_on) == 1 else files_text(len(acted_on)))
            text = {ASK: " Claude, about %s, while you go on" % (what,),
                    REMOVE: " %s, from %s%s" % (what, self.inbox_path,
                                                " (to the trash)" if verb == REMOVE and not self.inbox_is_cloud else ""),
                    OPEN: " %s, with %s program%s" % (what, "its" if len(acted_on) == 1 else "their",
                                                      "" if len(acted_on) == 1 else "s"),
                    READ: " %s, in %s, anew from Google Drive" % (acted_on[0], self.inbox_path)}
            return [picker.segments([(verb_label, VERB_COLORS[verb]), (text.get(verb, ''), None)])]
        parts = fitting(parts, shutil.get_terminal_size().columns - 1 - picker.display_width(verb_label) - 1)
        path_line = picker.segments([(verb_label, VERB_COLORS[verb]), (" ", None)] +
                                    [(text, None) for text, _ in parts])
        brackets = [(" " * (picker.display_width(verb_label) + 1), None)]
        for text, (color, names) in parts:
            brackets.append((bracket(names, picker.display_width(text)), color))
        return [path_line, picker.segments(brackets)]
