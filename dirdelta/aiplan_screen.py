"""The screens of asking AI what to do with files (see aiplan.py): what to do, typed; then what it
answers, to review, unpicking what shouldn't be done. The sync and the inbox's sort do what's left,
each with its own confirmations."""
import os

from dirdelta import ai
from dirdelta import aiplan
from dirdelta import dryrun
from dirdelta import messages
from dirdelta import picker
from dirdelta import text

# The file pickers' key: about the picked files, or with none picked, about all of them
KEY = 'a'
KEY_NAME = 'a'
KEY_HINT = (KEY, 'ask AI')
# How many of what can't be done are listed
MAX_LEFT_OUT = 15


def ask(task, default='', label=None):
    """Ask what to do with the task's files (default: how it starts, to edit), and the AI what that
    means, for the user to review. Returns (what they typed, the aiplan.Steps they approved), or
    (what they typed, None) if none are, and (default, None) if they typed nothing."""
    if aiplan.too_many(task):
        messages.show("Too many files for the AI", [
            "That's %s, and it can be told of %d at most: pick some of them, then ask again." %
            (text.files(len(task.files)), aiplan.MAX_FILES)], dryrun.label())
        return default, None
    instruction = messages.ask(
        "Ask AI about %s" % (text.files(len(task.files)),),
        [task.place, "",
         "What should be done with them? In your own words: it answers with a plan, for you to review.",
         "It's told their paths and sizes, not their contents. Nothing's done until you approve it.",
         "(Empty, or Ctrl-C, goes back.)"],
        "> ", default, dryrun.label())
    if instruction is None:
        return default, None
    plan, error = None, None
    with messages.progress_screen("Asking AI (%s)" % (instruction,), dryrun.label(), wait=False):
        try:
            plan = aiplan.make(task, instruction)
        except ai.AIError as failure:
            error = failure
    if error is not None:
        messages.show("Couldn't ask the AI", [str(error)], dryrun.label(), 'red')
    if plan is None:
        return instruction, None
    if plan.left_out:
        messages.show("Some of what the AI said can't be done", [
            "Left out of the plan (%d):" % (len(plan.left_out),)] +
            text.listed(["  %s: %s" % left_out for left_out in plan.left_out], MAX_LEFT_OUT), dryrun.label())
    if not plan.steps:
        messages.show("The AI has no plan", [plan.summary or "It said nothing to do."], dryrun.label())
        return instruction, None
    return instruction, _review(task, plan, label)


def _review(task, plan, label):
    """The steps of plan the user leaves picked and approves, or None"""
    labels = {action.name: action.label for action in task.actions}
    steps = {'%s/%s' % (labels[step.action], step.relpath): step for step in plan.steps}
    previews = {item: _preview(step, labels) for item, step in steps.items()}
    shown = {item: picker.styled([(os.path.basename(step.relpath), None), ("  → " + step.target, 'cyan')])
             for item, step in steps.items() if step.target is not None}
    header = "%s\n%s\nThe AI's plan: %s. Space unpicks what shouldn't be done; each kind is confirmed next." % (
        task.place, plan.summary, text.files(len(steps)))
    chosen = picker.pick_files(
        "The AI's plan", list(steps), header=header, picked=list(steps), label=label,
        previews=lambda send: send(previews, default=[]), shown_as=lambda: shown,
        key_hints=[('Enter', 'go on with the picked ones'), ('Space', 'pick or unpick'), ('q', 'back, doing nothing')])
    if chosen is None or not chosen.files:
        return None
    return [steps[item] for item in chosen.files]


def _preview(step, labels):
    lines = [labels[step.action] + ":", "  " + step.relpath]
    if step.target is not None:
        lines += ["To:", "  " + step.target]
    if step.reason:
        lines += ["", "Why (AI):", "  " + step.reason]
    return lines


def of_action(steps, name):
    """The steps of the action named name"""
    return [step for step in steps if step.action == name]
