"""Asking the AI what to do with the picked files (see aiplan.py)"""
from dirdelta.claude import ai
from dirdelta.claude import aiplan
from dirdelta.matching import elsewhere
from dirdelta.screens import aiplan_screen
from dirdelta.sync import replica_ops
from dirdelta.trees import paths
from dirdelta.ui import messages
from dirdelta.util import dryrun


class AskAI(object):
    """The AI's plans (InteractiveDirSync's)"""

    def _ai_task(self, relpaths, focus):
        """What to ask the AI about src's files at relpaths, the user being on those of focus (see
        aiplan.py): dst's files are told too, to rename them, and each's copies there, as far as it's
        known"""
        src_name, dst_name = self._src.displayname(), self._dst.displayname()

        def can_rename(replica):
            def check(relpath, target):
                return replica.cant_move(relpath) or ("there's a file there already" if replica_ops.exists(replica, target) else None)
            return check
        actions = []
        if replica_ops.can_copy(self._src, self._dst):
            actions.append(aiplan.Action(self.COPY, "Copy to destination",
                                         "copy the file to %s, to the same path." % (dst_name,)))
        if replica_ops.is_writable(self._src):
            actions.append(aiplan.Action(self.RENAME_IN_SRC, "Rename in source",
                                         "move or rename the file in %s." % (src_name,), True, False,
                                         can_rename(self._src)))
        if replica_ops.is_writable(self._dst):
            actions.append(aiplan.Action(self.RENAME_IN_DST, "Rename in destination",
                                         "move or rename one of %s's other files, in it (e.g. to the path of the "
                                         "same file in %s, so they match)." % (dst_name, src_name), True, True,
                                         can_rename(self._dst)))
        if replica_ops.is_writable(self._src):
            actions.append(aiplan.Action(self.REMOVE, "Remove from source",
                                         "remove the file from %s, which is then in neither." % (src_name,)))
        files = []
        for relpath in relpaths:
            same = [match for match, is_same in elsewhere.known_same(relpath, self.src_index, self.dst_index).items()
                    if is_same]
            files.append(aiplan.File(relpath, self._src.file_size(relpath),
                                     "the same contents as %s in %s" % (', '.join(sorted(same)[:3]), dst_name)
                                     if same else ''))
        others = sorted(relpath for relpath in self.dst_index.relpaths() if not paths.is_meta(relpath))
        return aiplan.Task("These are files in the source, %s, which the destination, %s, lacks at the same paths." %
                           (src_name, dst_name),
                           files, actions, others, focus=focus,
                           fetch=lambda relpath: self._opener.local_path(relpath, ai.MAX_READ_SIZE))

    def _ask_ai(self, relpaths, focus=()):
        """Ask the AI about src's files at relpaths, the user being on those of focus, and do what the
        user approves of its plan, if it answers with one (each kind once they confirm it, as if they
        chose it). Returns the files done (in a dry run,
        the ones it would have done), or None if none were."""
        relpaths = [relpath for relpath in relpaths if relpath not in self.differs]
        if not relpaths:
            messages.show("Nothing to ask about", ["AI is asked about the files %s lacks, not those it has other versions of." %
                                                   (self._dst.displayname(),)], dryrun.label())
            return None
        focus = [relpath for relpath in focus if relpath not in self.differs]
        messages.print_line("Looking through %s and %s..." % (self._src.displayname(), self._dst.displayname()))
        self.src_index.build()
        self.dst_index.build()
        self._last_instruction, steps = aiplan_screen.ask(self._ai_task(relpaths, focus), self._last_instruction)
        if not steps:
            return None
        done = []
        for action in (self.COPY, self.RENAME_IN_SRC, self.RENAME_IN_DST):
            moves = [(step.relpath, step.target) for step in aiplan_screen.of_action(steps, action) if step.target]
            if action == self.COPY:
                copied = [step.relpath for step in aiplan_screen.of_action(steps, action)]
                done += (self._copy_or_remove(action, copied) or []) if copied else []
            elif moves:
                done += self._rename(action, moves) or []
        removed = [step.relpath for step in aiplan_screen.of_action(steps, self.REMOVE)]
        if removed:
            # Which only src has: what the AI said to remove can be restored
            done += self._copy_or_remove(self.REMOVE, removed, to_trash=True) or []
        # Of several kinds: the replicas are diffed anew
        self._last_action = None
        return done or None

    def _note(self, replica, verb, count, source=None):
        """Note a live change of the replica's files (see log_entries.Changes.note())"""
        if self.changes is not None:
            self.changes.note(replica.displayname(), verb, count, source)
