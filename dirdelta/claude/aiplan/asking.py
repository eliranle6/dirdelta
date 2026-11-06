"""Asking the AI about a Task (make())"""
from dirdelta.claude import ai
from dirdelta.claude.aiplan.answer import _plan_of
from dirdelta.claude.aiplan.kinds import MAX_FILES, SYSTEM_PROMPT
from dirdelta.claude.aiplan.prompt import _of_focus, _prompt, _schema


def too_many(task):
    """Whether the task has more files than the AI is told of"""
    return len(task.files) > MAX_FILES


def make(task, instruction):
    """The Plan of the task, as the AI answers instruction (what the user said). Raises ai.AIError if
    it can't be asked, and OSError if a file of its focus can't be fetched."""
    extras, readable = _of_focus(task)
    return _plan_of(task, ai.ask(_prompt(task, instruction, extras), _schema(task), SYSTEM_PROMPT, readable))
