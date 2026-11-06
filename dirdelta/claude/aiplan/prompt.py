"""The prompt of a Task (with the files of its focus, which the AI may read), and the schema of its answer"""
from dirdelta.claude import ai
from dirdelta.claude.aiplan.kinds import MAX_FOCUS, MAX_MEMBERS, MAX_OTHERS
from dirdelta.util import archives


def focus_of(task):
    """The files of its focus it's told of"""
    return list(task.focus)[:MAX_FOCUS]


def of_focus(task):
    """({relpath: what's more to say of a file of its focus}, the local paths the AI may read): what's
    in a zip is said (it can't read one); another is to be read, if it's not too big"""
    extras, readable = {}, []
    sizes = {file.relpath: file.size for file in task.files}
    for relpath in focus_of(task) if task.fetch is not None else []:
        path = task.fetch(relpath)
        if path is None:
            continue
        if archives.is_archive(relpath):
            try:
                extras[relpath] = archives.said(archives.members(path), MAX_MEMBERS)
            except archives.ArchiveError as error:
                extras[relpath] = str(error)
        elif (sizes.get(relpath) or 0) <= ai.MAX_READ_SIZE:
            extras[relpath] = "read it at %s" % (path,)
            readable.append(path)
    return extras, readable


def answer_schema(task):
    return {"type": "object",
            "properties": {
                "answer": {"type": "string"},
                "summary": {"type": "string"},
                "steps": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"action": {"type": "string", "enum": [action.name for action in task.actions]},
                                   "number": {"type": "integer"},
                                   "path": {"type": "string"},
                                   "reason": {"type": "string"}},
                    "required": ["action", "number", "reason"]}}},
            "required": ["answer", "summary", "steps"]}


def others_of(task):
    return list(task.others)[:MAX_OTHERS]


def prompt_of(task, instruction, extras=None):
    extras = extras or {}
    lines = ["What the person wants: %s" % (instruction,), ""]
    if task.focus:
        lines += ["They're on %s, which is what 'this' means." % (', '.join(focus_of(task)),), ""]
    lines += [task.place, "", "What you can do, each step on one file, by its number:"]
    for action in task.actions:
        lines.append("- %s: %s%s" % (action.name, action.help,
                                     " Its 'path' is the file's new path, with its name." if action.has_target else ""))
    lines += ["", "Each step's reason: a few words. The files:"]
    for number, file in enumerate(task.files, 1):
        notes = [note for note in (file.note, extras.get(file.relpath)) if note]
        lines.append("%d. %s (%s)%s" % (number, file.relpath,
                                        "size unknown" if file.size is None else "%d bytes" % (file.size,),
                                        ": " + '; '.join(notes) if notes else ""))
    others = others_of(task)
    if others:
        lines += ["", "The other files, for the actions said to be on them%s:" %
                  (" (only %d of the %d)" % (len(others), len(task.others)) if len(others) < len(task.others) else "",)]
        lines += ["%d. %s" % (number, relpath) for number, relpath in enumerate(others, len(task.files) + 1)]
    if task.context:
        lines += [""] + list(task.context)
    return '\n'.join(lines)
