"""The sync menu's Sync (SyncMenu's, sync_view()): its differences in one screen, seen as chosen there (view.py: which
files, and planned with ⇒ ⇐ or acted on at once), the screen shown again after a change while anything still differs,
or in another view when its switch asks for one, until the user goes back to the menu"""
from dirdelta.known import replicanames
from dirdelta.sync import bothsides
from dirdelta.sync import combined
from dirdelta.sync import view
from dirdelta.ui import messages
from dirdelta.ui import picker
from dirdelta.util import dryrun


class Viewing(object):
    """SyncMenu's Sync, in its views"""

    def sync_view(self, scope=view.ALL, mode=view.PLAN):
        """Show the differences in the view (scope, mode), and the next one asked for, until the user goes back"""
        while True:
            # (The moved files found only for the views that show them: a side's tree doesn't, and finding them
            # builds both replicas' indexes)
            found = self._found(with_moved=mode == view.PLAN or scope in (view.ALL, view.MOVED))
            if found is None:
                return
            view.show(scope, mode, self._scopes(found, mode))
            # (The plan's tree and both sides' end once they've done something, to be shown again on what's left; a
            # side's tree ends only when it's left, saying whether anything changed meanwhile)
            one_side = mode == view.ACT and scope in (view.ONLY_A, view.ONLY_B, view.DIFFER)
            if mode == view.PLAN:
                changed, switch = self._plan(found, scope)
            elif one_side:
                changed, switch = self._act_one_side(scope)
            else:
                changed, switch = self._act_both(found, scope)
            if changed:
                self._find_all()
                for job in self.jobs:
                    job.scan_in_background()
            if switch is None and (one_side or not changed or not self._still_differ()):
                return
            scope, mode = switch or (scope, mode)

    def _found(self, with_moved=True):
        """(only in A, only in B, the ones that differ, the moved ones: {} without with_moved, unless they were found
        already) as each way found them, or None (said)"""
        try:
            missing = [way.missing.result() for way in self.ways]
            changes = self.ways[0].differs.result()
        except Exception as error:
            messages.show("Couldn't compare them", [str(error)], dryrun.label(), 'red')
            return None
        # (Both ways may say the same)
        warnings = list(dict.fromkeys(line for found in missing for line in (found.warning or [])))
        if warnings and getattr(self, '_warned', None) != warnings:
            self._warned = warnings
            messages.show("Warning: couldn't read everything", warnings, dryrun.label(), 'red')
        key = tuple(id(way.missing) for way in self.ways)
        if getattr(self, '_moved_for', None) != key and not with_moved:
            return missing[0].relpaths, missing[1].relpaths, changes, {}
        if getattr(self, '_moved_for', None) != key:
            # The moved files, by the hashes known (or what was compared before): nothing's read
            messages.print_line("Finding the moved files...")
            self._moved = combined.find_moved(missing[0].relpaths, missing[1].relpaths, self.replica_a,
                                              self.indexes[self.replica_a], self.indexes[self.replica_b], self.ways[0].checked)
            self._moved_for = key
        return missing[0].relpaths, missing[1].relpaths, changes, self._moved

    def _scopes(self, found, mode=view.PLAN):
        """[(scope, its title, how many files)] of the ones with any (All always). The moved files are Moved's in Plan;
        in Act a side's tree shows them too (with where the other may have them), so its Only in counts them"""
        only_a, only_b, changes, moved = found
        names = replicanames.short_names([self.replica_a_path, self.replica_b_path])
        in_b = set(moved.values())
        apart = mode == view.PLAN
        counts = {view.ALL: len(only_a) + len(only_b) - len(moved) + len(changes),
                  view.ONLY_A: len(only_a) - (len(moved) if apart else 0),
                  view.ONLY_B: len([relpath for relpath in only_b if not apart or relpath not in in_b]),
                  view.DIFFER: len(changes), view.MOVED: len(moved)}
        titles = {view.ALL: "All", view.ONLY_A: "Only in %s" % (names[self.replica_a_path],),
                  view.ONLY_B: "Only in %s" % (names[self.replica_b_path],), view.DIFFER: "Differ", view.MOVED: "Moved"}
        return [(scope, titles[scope], counts[scope]) for scope in view.SCOPES if scope == view.ALL or counts[scope]]

    def _plan(self, found, scope):
        """The combined tree (see sync/combined/), on scope: (whether the replicas' files changed, the view asked for)"""
        only_a, only_b, changes, moved = found
        sync = combined.CombinedSync(self.replica_a, self.replica_b, self.replica_a_path, self.replica_b_path,
                                     only_a, only_b, changes, self.changes, moved, chosen=self.combined_chosen)
        with picker.place("Sync"):
            changed = sync.run()
        self.combined_chosen = {} if changed else sync.chosen
        return changed, sync.switch

    def _act_one_side(self, scope):
        """One side's files tree (an Action's), checked and acted on: (whether the files changed, the view asked for)"""
        action = self.actions[self.action_labels[scope]]
        # (Only in: the files missing alone; the ones that differ are Differ's)
        action.with_differing = scope == view.DIFFER
        changed = action.run()
        if changed and action.was_read_anew:
            for way in self.ways:
                way.checked.clear()
            self.compared.clear()
        return changed, action.switch

    def _act_both(self, found, scope):
        """Both sides' files at once (bothsides.py), checked and acted on: (whether the files changed, the view asked for)"""
        only_a, only_b, changes, moved = found
        act = bothsides.BothSides(self.replica_a, self.replica_b, self.replica_a_path, self.replica_b_path,
                                  only_a, only_b, changes, moved, self.changes, only_moved=scope == view.MOVED)
        with picker.place("Sync"):
            changed = act.run()
        return changed, act.switch
