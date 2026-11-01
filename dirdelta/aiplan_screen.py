"""The screens of asking AI about files (see aiplan.py): what's wanted, typed; waiting for it; then its
answer, or its plan, to review, unpicking what shouldn't be done. The sync and the inbox's sort do
what's left, each with its own confirmations."""
import os
import shutil
import textwrap
import threading
import time

from dirdelta import ai
from dirdelta import aiplan
from dirdelta import archives
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
# How often the time waited is said, in seconds
WAITING_INTERVAL = 1
# The lines of a screen that aren't its text (the title's, the bars', and Press Enter's)
SCREEN_MARGIN = 6


def ask(task, default='', label=None):
    """Ask what's wanted of the task's files (default: how it starts, to edit), and the AI, showing what
    it answers: its answer to a question, or its plan to review. Returns (what they typed, the
    aiplan.Steps they approved), or (what they typed, None) if none are, and (default, None) if they
    typed nothing."""
    if aiplan.too_many(task):
        messages.show("Too many files for the AI", [
            "That's %s, and it can be told of %d at most: pick some of them, then ask again." %
            (text.files(len(task.files)), aiplan.MAX_FILES)], dryrun.label())
        return default, None
    instruction = messages.ask(
        "Ask AI about %s" % (text.files(len(task.files)),),
        [task.place, "",
         "What do you want? Ask it something, or say what should be done: that it answers with a plan,",
         "for you to review. Nothing's done until you approve it.", _what_its_told(task),
         "(Empty, or Ctrl-C, goes back.)"],
        "> ", default, dryrun.label())
    if instruction is None:
        return default, None
    plan, error = None, None
    with messages.progress_screen("Asking AI: %s" % (instruction,), dryrun.label(), wait=False):
        plan, error = _waiting_for(lambda: aiplan.make(task, instruction))
    if error is not None:
        messages.show("Couldn't ask the AI", [str(error)], dryrun.label(), 'red')
    if plan is None:
        return instruction, None
    if plan.answer:
        _show_answer(plan.answer)
    if plan.left_out:
        messages.show("Some of what the AI said can't be done", [
            "Left out of the plan (%d):" % (len(plan.left_out),)] +
            text.listed(["  %s: %s" % left_out for left_out in plan.left_out], MAX_LEFT_OUT), dryrun.label())
    if not plan.steps:
        if not plan.answer:
            messages.show("The AI has no plan", [plan.summary or "It said nothing to do."], dryrun.label())
        return instruction, None
    return instruction, _review(task, plan, label)


def _what_its_told(task):
    """What the AI gets, in a line"""
    focus = aiplan.focus_of(task) if task.fetch is not None else []
    zips = [relpath for relpath in focus if archives.is_archive(relpath)]
    read = [relpath for relpath in focus if relpath not in zips]
    said = "It's told their paths and sizes"
    if zips:
        said += ", and the list of files in %s" % (_those(zips),)
    if not read:
        return said + (", not their contents." if not zips else ".")
    return "%s. It may read %s, which sends the contents to it." % (said, _those(read))


def _those(relpaths):
    return relpaths[0] if len(relpaths) == 1 else "the %s you're on" % (text.files(len(relpaths)),)


def _waiting_for(work):
    """(what work() returns, None), or (None, why it failed), saying how long it's been; on a thread of
    its own, so that it's said, and Ctrl-C stops waiting ((None, None): the progress screen says so)"""
    results = []

    def run():
        try:
            results.append((work(), None))
        except Exception as error:
            results.append((None, error))
    thread = threading.Thread(target=run, daemon=True)
    started = time.monotonic()
    thread.start()
    messages.print_line("Waiting for the AI (Ctrl-C stops waiting)...")
    while thread.is_alive():
        messages.print_progress("Waited %s" % (text.format_duration(time.monotonic() - started),))
        thread.join(WAITING_INTERVAL)
    return results[0]


def _show_answer(answer):
    """The AI's answer, wrapped, on as many screens as it takes"""
    width, height = shutil.get_terminal_size()
    lines = [wrapped for line in answer.splitlines() for wrapped in textwrap.wrap(line, width - 1) or ['']]
    per_screen = max(1, height - SCREEN_MARGIN)
    pages = [lines[start:start + per_screen] for start in range(0, len(lines), per_screen)]
    for number, page in enumerate(pages, 1):
        messages.show("The AI says" + (" (%d of %d)" % (number, len(pages)) if len(pages) > 1 else ""), page,
                      dryrun.label())


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
