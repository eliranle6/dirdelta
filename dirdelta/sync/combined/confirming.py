"""Confirming a plan of what to do to the two replicas (confirm()): the combined tree's, and acting on both sides' files at
once (bothsides.py)"""
from dirdelta.sync import replica_ops
from dirdelta.sync.combined import plan as plans
from dirdelta.ui import picker
from dirdelta.util import dryrun
from dirdelta.util import text

# The most files of each thing the confirmation lists
MAX_FILES_LISTED = 5

CONFIRM_NO, CONFIRM_YES, CONFIRM_SURE = "Back to the tree", "Apply", "Yes, remove them"


def confirm(plan, replica_a, replica_b, name_a, name_b):
    """Whether the user says yes to the plan (a plan.Plan) for replica_a and replica_b (named name_a, name_b): what it does,
    listed; removing files, asked again"""
    nr_changes = sum(len(items) for items in plan)
    lines = ["Apply %s?" % ("these %d changes" % (nr_changes,) if nr_changes > 1 else "this change",)]
    for line, items in plans.summary(plan, name_a, name_b):
        lines.append("  " + line + ":")
        lines += text.listed(["      %s" % (item,) for item in items], MAX_FILES_LISTED)
    for replica, name, relpaths in ((replica_b, name_b, plan.replace_b),
                                    (replica_a, name_a, plan.replace_a)):
        if relpaths:
            lines.append("%s's versions replaced go %s." % (name, replica_ops.discarded_to(replica)
                                                            if replica_ops.is_local(replica) else "to Drive's older versions"))
    if dryrun.DRYRUN:
        lines.append(dryrun.note())
    label = ('SYNC', 'blue')
    # (Live, Apply is red: it changes files)
    apply = picker.Option(CONFIRM_YES, CONFIRM_YES, None if dryrun.DRYRUN else picker.Colored(CONFIRM_YES, 'red'))
    if picker.pick_option([CONFIRM_NO, apply], header='\n'.join(lines), title="Apply?", label=label) != CONFIRM_YES:
        return False
    nr_removed = plans.removals(plan)
    if not nr_removed:
        return True
    removed_from = [(replica, name) for replica, name, relpaths in (
        (replica_a, name_a, plan.remove_from_a), (replica_b, name_b, plan.remove_from_b)) if relpaths]
    where = [replica_ops.discarded_to(replica) for replica, _ in removed_from]
    # (Said once where both go the same way)
    where = ("both " + where[0] if len(where) == 2 and where[0] == where[1] else
             "; ".join("%s's %s" % (name, to) for (_, name), to in zip(removed_from, where)))
    sure = "Are you sure? %s will be removed (%s)." % (text.files(nr_removed), where)
    # (The answer's text for one file, its value the same)
    sure_text = CONFIRM_SURE if nr_removed > 1 else "Yes, remove it"
    sure_option = picker.Option(CONFIRM_SURE, sure_text, None if dryrun.DRYRUN else picker.Colored(sure_text, 'red'))
    return picker.pick_option([CONFIRM_NO, sure_option], header=sure, title="Sure?", label=label) == CONFIRM_SURE
