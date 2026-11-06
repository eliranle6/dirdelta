"""The action menu of the picked files"""
import collections
import os
import posixpath
import types

from dirdelta.inbox.constants import (ASK, CLAUDES_DIR, CLAUDES_NAME, COPY, LABEL, MOVE, OPEN, OWN_NAME,
                                      READ, REMOVE, SORTED_TREE, THE_INBOX, VERB_COLORS, YOUR_DIR, YOUR_NAME)
from dirdelta.inbox.actions.menu_moves import MenuMoves
from dirdelta.inbox.actions.menu_options import MenuOptions
from dirdelta.inbox.formatting import files_text, of_picked, option_text
from dirdelta.matching import elsewhere
from dirdelta.trees import entries
from dirdelta.ui import picker


class Menu(MenuOptions, MenuMoves):
    """The action menu (InboxSort's): its options are in MenuOptions and MenuMoves"""

    def _act(self, relpaths, selected=None):
        """Let the user choose what to do with the picked files at relpaths, and do it once they
        confirm. Returns the ones done (moved, copied, removed; in a dry run, the ones it would have
        done), or None if none were (or Claude was asked, or they were opened: nothing moved); or
        filescreen.READ_ANEW to read the folder of selected (the picker's selection: a file, or a dir; by
        default the first file's) anew from Drive, as the key does."""
        if selected is None:
            selected = relpaths[0]
        f = self._menu_facts(relpaths, selected)
        actions = collections.OrderedDict(self._ask_options(f) + self._move_options(f) +
                                          self._removal_options(f) + self._other_options(f))
        # The ones that can't be done aren't offered, nor one that does the same as another (Claude's
        # dir under the file's own name, when Claude keeps the name)
        # (Nor what a read-only inbox or sorted tree can't have done)
        cant = self._cant_be_done()
        offered = collections.OrderedDict((key, action) for key, action in actions.items() if action.why_not is None
                                          and key not in cant)
        # Similar actions together, a blank line between each kind (opening and reading anew, the
        # picker's keys, together)
        kinds = [(ASK,), (MOVE,), (COPY,), (REMOVE,), (OPEN, READ)]
        # Each in its verb's color, the parts saying where the files go in their sources' (as the
        # brackets below the menu), after its key, if a picker's key does it too
        prefixes = picker.shortcut_prefixes([self.NOTHING] + [action.label for action in offered.values()],
                                            {action.label: self.SHORTCUTS[key] for key, action in offered.items()
                                             if key in self.SHORTCUTS})
        choices = picker.grouped([[picker.Option(self.NOTHING, self.NOTHING, prefixes[self.NOTHING] + self.NOTHING)]] + [
            [picker.Option(key, action.label, prefixes[action.label] + option_text(action.label, VERB_COLORS[action.verb], action.parts))
             for key, action in offered.items() if action.verb in kind] for kind in kinds])
        lines = {key: (self._said_lines(*action.said) if action.said else
                       self._destination_lines(action.verb, action.parts, f.relpaths, action.acted_on or f.relpaths))
                 for key, action in offered.items()}
        lines[self.ASK_AI] = self._said_lines(ASK, " tell it what to do; it answers with a plan to review")
        header = ("%s, in %s: what to do with it?" % (f.name, posixpath.dirname(posixpath.join(self.inbox_path, f.relpaths[0])))
                  if f.is_one else "%s picked in %s. What to do with them?" % (f.count, self.inbox_path))
        chosen = offered.get(picker.pick_option(choices, header=header, title="What to do", label=LABEL, previews_below=lines))
        return chosen.run() if chosen is not None else None

    def _menu_facts(self, relpaths, selected):
        """What the action menu of the picked files at relpaths (selected: the picker's selection)
        says and offers, worked out once for its options (see _ask_options() and the like)"""
        node = self._inbox_tree.get_node(selected)
        folder = selected if node is None or isinstance(node.data, entries.DirEntry) else posixpath.dirname(selected)
        count = files_text(len(relpaths))
        undescribed = [relpath for relpath in relpaths
                       if relpath not in self._descriptions and relpath not in self._describing]
        # The ones Claude may be asked where they go: all but the ones it's being asked of now (the
        # ones it placed, or couldn't, asked anew)
        askable = [relpath for relpath in relpaths if relpath not in self._placing]
        asked_before = [relpath for relpath in askable if relpath in self._recommendations or relpath in self._failed]
        recommended = [relpath for relpath in relpaths
                       if relpath in self._recommendations and self._target(relpath) is not None]
        # Copies of the sorted tree's files, by their contents (whatever Claude says of them), and the
        # files with candidates there not compared yet
        removable = [relpath for relpath in relpaths if self._copies(relpath)]
        junky = [relpath for relpath in relpaths if self._junk(relpath) is not None]
        uncompared = [relpath for relpath in relpaths if relpath not in self._checked and self._root_index.is_built()
                      and elsewhere.matches_of_size(relpath, self._size(relpath), self._root_index)]
        not_yet = " (%d not compared yet: Ctrl-I compares them)" % (len(uncompared),) if uncompared else ""
        destinations = sorted({os.path.dirname(self._target(relpath)) for relpath in recommended})
        renamed = [relpath for relpath in recommended
                   if os.path.basename(self._target(relpath)) != os.path.basename(relpath)]
        is_one = len(relpaths) == 1
        name = os.path.basename(relpaths[0]) if is_one else None
        # All the files of the selected dir: what Claude said of it as a whole, and what's done with it whole
        whole_dir = self._whole_dir(relpaths, selected)
        dir_recommendation = self._dir_recommendation(whole_dir) if whole_dir else None
        dir_action = dir_recommendation['action'] if dir_recommendation else None
        the_dir = ("the dir %s/ (%s)" % (posixpath.basename(whole_dir), count)) if whole_dir else None
        claudes_dir_path = ((dir_recommendation['path'] + '/', CLAUDES_DIR) if dir_action == 'move' else None)
        own_dir_name = ((posixpath.basename(whole_dir) + '/', OWN_NAME) if whole_dir else None)
        # Where each option puts the files: the parts of the path, each with where it's from (see
        # _destination_lines())
        root = (self.root_path.rstrip('/') + '/', SORTED_TREE)
        claudes_dir = (((destinations[0] + '/') if destinations[0] else '', CLAUDES_DIR)
                       if len(destinations) == 1 else ("<Claude's %d dirs>/" % (len(destinations),), CLAUDES_DIR))
        claudes_name = ((os.path.basename(self._target(relpaths[0])), CLAUDES_NAME) if is_one and recommended else
                        ("<Claude's names, %d renamed>" % (len(renamed),), CLAUDES_NAME))
        own_name = (name, OWN_NAME) if is_one else ("<their own names>", OWN_NAME)
        your_dir = ("<a dir you pick>/", YOUR_DIR)
        inbox_root = (self.inbox_path.rstrip('/') + '/', THE_INBOX)
        typed = ("<a name you type>", YOUR_NAME)
        it = "it" if is_one else of_picked(len(recommended), len(relpaths))
        they = "it" if is_one else "the %s" % (count,)
        def to_a_dir(action):
            return lambda: self._to_a_dir(action, relpaths, renamed, count)
        return types.SimpleNamespace(**{name: value for name, value in locals().items() if name != 'self'})
