"""The action menu of the picked files"""
import collections
import os
import posixpath

from dirdelta.inbox.constants import (ASK,
    CLAUDES_DIR,
    CLAUDES_NAME,
    COPY,
    LABEL,
    MOVE,
    OPEN,
    OWN_NAME,
    READ,
    REMOVE,
    SORTED_TREE,
    THE_INBOX,
    VERB_COLORS,
    YOUR_DIR,
    YOUR_NAME)
from dirdelta.inbox.formatting import _Action, _files, _join, _of, _option_text
from dirdelta.matching import elsewhere
from dirdelta.trees import entries
from dirdelta.ui import filescreen
from dirdelta.ui import opening
from dirdelta.ui import picker
from dirdelta.util import archives


class Menu(object):
    """The action menu (InboxSort's)"""

    def _act(self, relpaths, selected=None):
        """Let the user choose what to do with the picked files at relpaths, and do it once they
        confirm. Returns the ones done (moved, copied, removed; in a dry run, the ones it would have
        done), or None if none were (or Claude was asked, or they were opened: nothing moved); or
        filescreen.READ_ANEW to read the folder of selected (the picker's selection: a file, or a dir; by
        default the first file's) anew from Drive, as the key does."""
        if selected is None:
            selected = relpaths[0]
        node = self._inbox_tree.get_node(selected)
        folder = selected if node is None or isinstance(node.data, entries.DirEntry) else posixpath.dirname(selected)
        count = _files(len(relpaths))
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
        it = "it" if is_one else _of(len(recommended), len(relpaths))
        they = "it" if is_one else "the %s" % (count,)
        def path_of(*parts):
            return ''.join(text for text, _ in parts)

        def to_a_dir(action):
            return lambda: self._to_a_dir(action, relpaths, renamed, count)
        actions = collections.OrderedDict([
            (self.ASK_AI, _Action("Ask AI what to do with %s, and review its plan" % (they,), None, ASK, [],
                                  lambda: self._ask_ai(relpaths, relpaths))),
            (self.DESCRIBE, _Action("Describe %s with Claude, while you go on (sends it their contents)" %
                                    ("it" if is_one else _of(len(undescribed), len(relpaths)),),
                                    None if undescribed else "described", ASK, [],
                                    lambda: self.describe_in_background(undescribed))),
            # As Ctrl-I: the ones Claude placed already are asked about anew (they may have changed)
            (self.RECOMMEND, _Action("Ask Claude where %s go%s in %s, while you go on%s" %
                                     ("it" if is_one else _of(len(askable), len(relpaths)), "es" if is_one else "",
                                      self.root_path, (" (anew: %s before)" % ("asked" if is_one else
                                                                               "%d asked" % (len(asked_before),)))
                                      if asked_before else ""),
                                     None if askable else "being asked", ASK, [],
                                     lambda: self.ask_in_background(askable, anew=True))),
            (self.ASK_DIR, _Action("Ask Claude about %s as a whole: what it is, and where it goes, while you go on%s" %
                                   (the_dir, " (anew)" if dir_recommendation else ""),
                                   None if whole_dir and whole_dir not in self._dir_asking else
                                   "being asked" if whole_dir else "not a dir", ASK, [],
                                   lambda: self.ask_dir_in_background(whole_dir, relpaths),
                                   said=(ASK, " Claude, about %s, while you go on" % (the_dir,)))),
            (self.MOVE_DIR, _Action("Move %s to Claude's recommendation%s: %s" %
                                    (the_dir, ", into the dir there" if dir_action == 'move' and
                                     self._root_tree.exists(dir_recommendation['path']) else "",
                                     path_of(root, claudes_dir_path)) if dir_action == 'move' else "",
                                    None if dir_action == 'move' else "no recommendation to move it", MOVE,
                                    [root, claudes_dir_path],
                                    lambda: self._approve(self.MOVE_TO, [(relpath, _join(dir_recommendation['path'],
                                                                                         relpath[len(whole_dir) + 1:]))
                                                                         for relpath in relpaths]))),
            (self.MOVE_DIR_TO, _Action("Move %s into a dir you pick: %s" %
                                       (the_dir, path_of(root, your_dir, own_dir_name)) if whole_dir else "",
                                       None if whole_dir else "not a dir", MOVE, [root, your_dir, own_dir_name],
                                       lambda: self._dir_to_a_dir(whole_dir, relpaths))),
            (self.MOVE_RECOMMENDED, _Action("Move %s to Claude's recommendation: %s" %
                                            (it, path_of(root, claudes_dir, claudes_name))
                                            if is_one or len(destinations) == 1 else
                                            "Move %s to Claude's recommendations (%d dirs%s)" %
                                            (it, len(destinations), ", %d renamed" % (len(renamed),) if renamed else ""),
                                            None if recommended else "no recommendation", MOVE,
                                            [root, claudes_dir, claudes_name],
                                            lambda: self._approve(self.MOVE_TO, [(relpath, self._target(relpath))
                                                                                 for relpath in recommended]))),
            (self.MOVE_TO_CLAUDES_DIR, _Action("Move %s to Claude's dir, keeping %s name: %s" %
                                               (it, "its" if is_one else "their", path_of(root, claudes_dir, own_name)),
                                               None if renamed else "the same as Claude's recommendation", MOVE,
                                               [root, claudes_dir, own_name],
                                               lambda: self._to_claudes_dir(recommended))),
            (self.MOVE_TO_CLAUDES_DIR_TYPED, _Action("Move it to Claude's dir, under a name you type: %s" %
                                                     (path_of(root, claudes_dir, typed),),
                                                     None if is_one and recommended else "not one file with a recommendation",
                                                     MOVE, [root, claudes_dir, typed],
                                                     lambda: self._to_claudes_dir(recommended, is_typed=True))),
            (self.MOVE_TO, _Action("Move %s to a dir you pick: %s" % (they, path_of(root, your_dir, own_name)),
                                   None, MOVE, [root, your_dir, own_name], to_a_dir(self.MOVE_TO))),
            (self.MOVE_TO_CLAUDES_NAMES, _Action("Move %s to a dir you pick, under Claude's %s: %s" %
                                                 (they, "name" if is_one else "names",
                                                  path_of(root, your_dir, claudes_name)),
                                                 None if renamed else "no other name from Claude", MOVE,
                                                 [root, your_dir, claudes_name], to_a_dir(self.MOVE_TO_CLAUDES_NAMES))),
            (self.MOVE_TO_TYPED, _Action("Move it to a dir you pick, under a name you type: %s" %
                                         (path_of(root, your_dir, typed),),
                                         None if is_one else "not one file", MOVE, [root, your_dir, typed],
                                         to_a_dir(self.MOVE_TO_TYPED))),
            (self.MOVE_IN_INBOX, _Action("Move %s to another dir in the inbox, a dir you pick: %s" %
                                         (they, path_of(inbox_root, your_dir, own_name)),
                                         None, MOVE, [inbox_root, your_dir, own_name],
                                         lambda: self._to_a_dir_in_inbox(relpaths, count))),
            (self.COPY_TO, _Action("Copy %s to a dir you pick (keeping %s in the inbox): %s" %
                                   (they, "it" if is_one else "them", path_of(root, your_dir, own_name)),
                                   None, COPY, [root, your_dir, own_name], to_a_dir(self.COPY_TO))),
            (self.REMOVE_COPIES, _Action("Remove %s: %s in %s%s" %
                                         ("it" if is_one else _of(len(removable), len(relpaths)),
                                          "a copy of a file" if is_one else "copies of files", self.root_path, not_yet),
                                         None if removable else "not a copy", REMOVE, [],
                                         lambda: self._remove(removable, ["  %s: a copy of %s" % (relpath, ', '.join(
                                             _join(self.root_path, copy) for copy in self._copies(relpath)[:2]))
                                             for relpath in removable]), acted_on=removable)),
            (self.REMOVE_DIR, _Action("Remove %s, as Claude says%s" %
                                      (the_dir, ": " + dir_recommendation['reason'] if dir_recommendation and
                                       dir_recommendation.get('reason') else "") if dir_action == 'remove' else "",
                                      None if dir_action == 'remove' else "no recommendation to remove it", REMOVE, [],
                                      lambda: self._remove(relpaths, ["  %s/: %s" % (whole_dir, dir_recommendation.get('reason') or
                                                                                      "Claude says so")] +
                                                           ["  " + relpath for relpath in relpaths], to_trash=True))),
            (self.REMOVE_JUNK, _Action("Remove %s: %s like junk (to %s)" %
                                       ("it" if is_one else _of(len(junky), len(relpaths)),
                                        "it looks" if is_one or len(junky) == 1 else "they look",
                                        "Drive's trash" if self.inbox_is_cloud else "the trash"),
                                       None if junky else "not junk", REMOVE, [],
                                       lambda: self._remove(junky, ["  %s: %s" % (relpath, self._junk(relpath))
                                                                    for relpath in junky], to_trash=True),
                                       acted_on=junky)),
            # Not when it does what removing the copies does (all of them are), or the junk does
            # (all of them are, in Drive, where both go to its trash)
            (self.REMOVE, _Action("Remove %s from %s" % (they, self.inbox_path),
                                  "the same as removing the copies" if len(removable) == len(relpaths) else
                                  "the same as removing the junk" if self.inbox_is_cloud and len(junky) == len(relpaths) else
                                  None, REMOVE, [], lambda: self._remove(relpaths))),
            (self.EXPLORE, _Action("Explore it: what's in the zip", None if is_one and archives.is_archive(relpaths[0]) else
                                   "not a zip", OPEN, [], lambda: self._explore(relpaths[0], set(relpaths)),
                                   said=(OPEN, " look in it, unpacking nothing"))),
            (self.OPEN, _Action("Open %s with %s program%s" %
                                (they, "its" if is_one else "their", "" if is_one else "s"),
                                None if len(relpaths) <= opening.names.MAX_OPENED else "too many", OPEN, [],
                                lambda: self._open(relpaths))),
            (self.READ_ANEW, _Action("Read %s/ anew from Google Drive" % (_join(self.inbox_path, folder),),
                                     None if self.inbox_is_cloud else "not Drive's", READ, [],
                                     lambda: filescreen.READ_ANEW, acted_on=[(folder or '.') + '/'])),
        ])
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
            [picker.Option(key, action.label, prefixes[action.label] + _option_text(action.label, VERB_COLORS[action.verb], action.parts))
             for key, action in offered.items() if action.verb in kind] for kind in kinds])
        lines = {key: (self._said_lines(*action.said) if action.said else
                       self._destination_lines(action.verb, action.parts, relpaths, action.acted_on or relpaths))
                 for key, action in offered.items()}
        lines[self.ASK_AI] = self._said_lines(ASK, " tell it what to do; it answers with a plan to review")
        header = ("%s, in %s: what to do with it?" % (name, posixpath.dirname(posixpath.join(self.inbox_path, relpaths[0])))
                  if is_one else "%s picked in %s. What to do with them?" % (count, self.inbox_path))
        chosen = offered.get(picker.pick_option(choices, header=header, title="What to do", label=LABEL, previews_below=lines))
        return chosen.run() if chosen is not None else None
