"""Asking the AI what to do with the inbox's files (see aiplan.py)"""
from dirdelta.claude import ai
from dirdelta.claude import aiplan
from dirdelta.inbox.constants import LABEL
from dirdelta.screens import aiplan_screen
from dirdelta.ui import messages
from dirdelta.util import dryrun


class AskAI(object):
    """The AI's plans (InboxSort's)"""

    def _ai_task(self, relpaths, focus):
        """What to ask the AI about the inbox's files at relpaths, the user being on those of focus (see
        aiplan.py): what's known of each, and the sorted tree's dirs"""
        def in_sorted_tree(relpath, target):
            if self._is_in_inbox(target):
                return "that's in the inbox"
            return "there's a file or dir there already" if self._root_tree.exists(target) else None

        def in_inbox(relpath, target):
            return "there's a file or dir there already" if self._inbox_tree.exists(target) else None
        where = "its path relative to the root of the sorted tree"
        actions = [aiplan.Action(self.MOVE_TO, "Move to the sorted tree", "move the file into the sorted tree: %s." % (where,),
                                 True, False, in_sorted_tree),
                   aiplan.Action(self.COPY_TO, "Copy to the sorted tree",
                                 "copy the file to the sorted tree, keeping it in the inbox: %s." % (where,),
                                 True, False, in_sorted_tree),
                   aiplan.Action(self.MOVE_IN_INBOX, "Move in the inbox",
                                 "move or rename the file in the inbox: its path relative to the inbox.",
                                 True, False, in_inbox),
                   aiplan.Action(self.REMOVE, "Remove from the inbox", "remove the file from the inbox.")]
        cant = self._cant_be_done()
        actions = [action for action in actions if action.name not in cant]
        files = []
        for relpath in relpaths:
            notes = ([self._claude.descriptions[relpath]] if relpath in self._claude.descriptions else [])
            copies = self._copies(relpath)
            if copies:
                notes.append("the sorted tree has the same contents at %s" % (', '.join(copies[:3]),))
            if self._junk(relpath) is not None:
                notes.append("looks like junk: %s" % (self._junk(relpath),))
            files.append(aiplan.File(relpath, self._size(relpath), '; '.join(notes)))
        dirs = self._root_dirs()
        listed = ["%s%s" % (dirpath or '. (the root)', " (e.g. %s)" % (', '.join(dirs[dirpath]),) if dirs[dirpath] else "")
                  for dirpath in sorted(dirs)[:ai.MAX_DIRS_GIVEN]]
        return aiplan.Task("These are files in the inbox %s, of files waiting to be sorted into the sorted tree %s." %
                           (self.inbox_path, self.root_path), files, actions,
                           context=["The sorted tree's dirs, with a few of the names of the files in each:"] + listed,
                           focus=focus, fetch=lambda relpath: self._opener.local_path(relpath, ai.MAX_READ_SIZE))

    def _ask_ai(self, relpaths, focus=()):
        """Ask the AI about the inbox's files at relpaths, the user being on those of focus, and do what
        the user approves of its plan, if it answers with one (each kind once they confirm it, as if
        they chose it). Returns the ones done (in a
        dry run, the ones it would have done), or None if none were."""
        task = self._ai_task(relpaths, focus)
        if not task.actions:
            messages.show("Read-only", ["Both %s and %s are read-only: nothing can be done with these files." %
                                        (self.inbox_path, self.root_path)], dryrun.label(), 'yellow')
            return None
        self._last_instruction, steps = aiplan_screen.ask(task, self._last_instruction, LABEL)
        if not steps:
            return None
        done = []
        for action in (self.MOVE_TO, self.COPY_TO):
            plan = [(step.relpath, step.target) for step in aiplan_screen.of_action(steps, action)]
            if plan:
                done += self._approve(action, plan, is_reviewed=True) or []
        moves = [(step.relpath, step.target) for step in aiplan_screen.of_action(steps, self.MOVE_IN_INBOX)]
        if moves:
            done += self._move_plan_in_inbox(moves, self.inbox_path) or []
        removed = aiplan_screen.of_action(steps, self.REMOVE)
        if removed:
            done += self._remove([step.relpath for step in removed],
                                 ["  %s: %s" % (step.relpath, step.reason) for step in removed], to_trash=True) or []
        return done or None
