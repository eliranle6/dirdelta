"""The action menu's options that move or copy the picked files"""
from dirdelta.inbox.constants import COPY, MOVE
from dirdelta.inbox.formatting import Action, join_path, path_of


class MenuMoves(object):
    """The moving and copying options (InboxSort's action menu's)"""

    def _move_options(self, f):
        """The options that move the files somewhere, or copy them: [(key, _Action)]"""
        return [
            (self.MOVE_DIR, Action("Move %s to Claude's recommendation%s: %s" %
                                    (f.the_dir, ", into the dir there" if f.dir_action == 'move' and
                                     self._root_tree.exists(f.dir_recommendation['path']) else "",
                                     path_of(f.root, f.claudes_dir_path)) if f.dir_action == 'move' else "",
                                    None if f.dir_action == 'move' else "no recommendation to move it", MOVE,
                                    [f.root, f.claudes_dir_path],
                                    lambda: self._approve(self.MOVE_TO, [(relpath, join_path(f.dir_recommendation['path'],
                                                                                         relpath[len(f.whole_dir) + 1:]))
                                                                         for relpath in f.relpaths]))),
            (self.MOVE_DIR_TO, Action("Move %s into a dir you pick: %s" %
                                       (f.the_dir, path_of(f.root, f.your_dir, f.own_dir_name)) if f.whole_dir else "",
                                       None if f.whole_dir else "not a dir", MOVE, [f.root, f.your_dir, f.own_dir_name],
                                       lambda: self._dir_to_a_dir(f.whole_dir, f.relpaths))),
            (self.MOVE_RECOMMENDED, Action("Move %s to Claude's recommendation: %s" %
                                            (f.it, path_of(f.root, f.claudes_dir, f.claudes_name))
                                            if f.is_one or len(f.destinations) == 1 else
                                            "Move %s to Claude's recommendations (%d dirs%s)" %
                                            (f.it, len(f.destinations), ", %d renamed" % (len(f.renamed),) if f.renamed else ""),
                                            None if f.recommended else "no recommendation", MOVE,
                                            [f.root, f.claudes_dir, f.claudes_name],
                                            lambda: self._approve(self.MOVE_TO, [(relpath, self._target(relpath))
                                                                                 for relpath in f.recommended]))),
            (self.MOVE_TO_CLAUDES_DIR, Action("Move %s to Claude's dir, keeping %s name: %s" %
                                               (f.it, "its" if f.is_one else "their", path_of(f.root, f.claudes_dir, f.own_name)),
                                               None if f.renamed else "the same as Claude's recommendation", MOVE,
                                               [f.root, f.claudes_dir, f.own_name],
                                               lambda: self._to_claudes_dir(f.recommended))),
            (self.MOVE_TO_CLAUDES_DIR_TYPED, Action("Move it to Claude's dir, under a name you type: %s" %
                                                     (path_of(f.root, f.claudes_dir, f.typed),),
                                                     None if f.is_one and f.recommended else "not one file with a recommendation",
                                                     MOVE, [f.root, f.claudes_dir, f.typed],
                                                     lambda: self._to_claudes_dir(f.recommended, is_typed=True))),
            (self.MOVE_TO, Action("Move %s to a dir you pick: %s" % (f.they, path_of(f.root, f.your_dir, f.own_name)),
                                   None, MOVE, [f.root, f.your_dir, f.own_name], f.to_a_dir(self.MOVE_TO))),
            (self.MOVE_TO_CLAUDES_NAMES, Action("Move %s to a dir you pick, under Claude's %s: %s" %
                                                 (f.they, "name" if f.is_one else "names",
                                                  path_of(f.root, f.your_dir, f.claudes_name)),
                                                 None if f.renamed else "no other name from Claude", MOVE,
                                                 [f.root, f.your_dir, f.claudes_name], f.to_a_dir(self.MOVE_TO_CLAUDES_NAMES))),
            (self.MOVE_TO_TYPED, Action("Move it to a dir you pick, under a name you type: %s" %
                                         (path_of(f.root, f.your_dir, f.typed),),
                                         None if f.is_one else "not one file", MOVE, [f.root, f.your_dir, f.typed],
                                         f.to_a_dir(self.MOVE_TO_TYPED))),
            (self.MOVE_IN_INBOX, Action("Move %s to another dir in the inbox, a dir you pick: %s" %
                                         (f.they, path_of(f.inbox_root, f.your_dir, f.own_name)),
                                         None, MOVE, [f.inbox_root, f.your_dir, f.own_name],
                                         lambda: self._to_a_dir_in_inbox(f.relpaths, f.count))),
            (self.COPY_TO, Action("Copy %s to a dir you pick (keeping %s in the inbox): %s" %
                                   (f.they, "it" if f.is_one else "them", path_of(f.root, f.your_dir, f.own_name)),
                                   None, COPY, [f.root, f.your_dir, f.own_name], f.to_a_dir(self.COPY_TO))),
        ]
