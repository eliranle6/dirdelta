"""The AI's answer, checked into a Plan: only what can be done"""
import posixpath

from dirdelta.claude import ai
from dirdelta.claude.aiplan.kinds import Plan, Step
from dirdelta.claude.aiplan.prompt import others_of
from dirdelta.trees import paths


def plan_of(task, answer):
    """The Plan of the AI's answer: what can't be done is left out, saying why"""
    actions = {action.name: action for action in task.actions}
    others = others_of(task)
    steps, left_out = [], []
    # Per action's replica: of_others' are in another place than the files'
    done_files, targets = set(), set()
    for item in answer.get('steps', []):
        action = actions.get(item.get('action'))
        number = item.get('number')
        said = "%s of file %s" % (item.get('action'), number)
        if action is None or not isinstance(number, int) or isinstance(number, bool):
            left_out.append((said, "not a step it can do"))
            continue
        index = number - 1 - (len(task.files) if action.of_others else 0)
        relpaths = others if action.of_others else [file.relpath for file in task.files]
        if not 0 <= index < len(relpaths):
            left_out.append((said, "no such file"))
            continue
        relpath = relpaths[index]
        said = "%s %s" % (action.name, relpath)
        target = None
        if action.has_target:
            target = ai.clean_path(item.get('path', ''), posixpath.basename(relpath))
            if target is None:
                left_out.append((said, "no path it can go to: %r" % (item.get('path', ''),)))
                continue
            said += " to %s" % (target,)
        why_not = ("another step has this file" if (action.of_others, relpath) in done_files else
                   _why_not(action, relpath, target, targets))
        if why_not:
            left_out.append((said, why_not))
            continue
        done_files.add((action.of_others, relpath))
        if target is not None:
            targets.add((action.name, target))
        steps.append(Step(action.name, relpath, target, str(item.get('reason', '')).strip()))
    # In the order of the actions, as a screen does them
    order = {action.name: place for place, action in enumerate(task.actions)}
    return Plan(str(answer.get('summary', '')).strip(), sorted(steps, key=lambda step: order[step.action]), left_out,
                str(answer.get('answer', '')).strip())


def _why_not(action, relpath, target, targets):
    """Why the step can't be done, or None"""
    if target is not None:
        if target == relpath:
            return "it's there already"
        if paths.is_meta(target):
            return "that's dirdelta's own dir"
        if (action.name, target) in targets:
            return "another file goes there"
    return action.check(relpath, target) if action.check is not None else None
