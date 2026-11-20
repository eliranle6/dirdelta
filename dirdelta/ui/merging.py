"""Merging two versions of a text file into one (merge()): in the browser, the web version's merge window
(each differing block's version chosen, or both, the result edited, the AI asked for its merge); in the
terminal, the user's editor on the file with each differing block marked as git marks a conflict. The
versions' lines are compared by difflib, in blocks: alike, or differing."""
import difflib
import os
import shutil
import subprocess
import tempfile

from dirdelta.ui import frontend
from dirdelta.ui import messages
from dirdelta.ui import picker

# The terminal's conflict marks, as git writes them
START, MIDDLE, END = '<<<<<<<', '=======', '>>>>>>>'
# What the terminal's editor is, if the user has none set
DEFAULT_EDITOR = 'vi'
SAVE, EDIT_AGAIN, NOTHING = "Save it", "Edit it again", "Nothing: go back"


def blocks(lines_a, lines_b):
    """The versions' lines in blocks: [('same', lines)] where they're alike, [('differ', a's lines, b's
    lines)] where they aren't (either may be empty: lines only one has)"""
    found = []
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False).get_opcodes():
        if tag == 'equal':
            found.append(('same', lines_a[a1:a2]))
        else:
            found.append(('differ', lines_a[a1:a2], lines_b[b1:b2]))
    return found


def merge(title, names, lines_a, lines_b, label=None, suggest=None):
    """The merged lines of two versions (names: theirs, as the user knows them), as the user makes them,
    or None if they went back. suggest, if given: a function asking the AI for its merge (given what the user
    says of it, if anything), returning (its lines, what it says of them), or raising an Exception saying why it
    can't (the browser's Ask AI)"""
    if frontend.current is not None:
        return frontend.current.merge(title, names, lines_a, lines_b, label, suggest)
    return _in_editor(title, names, lines_a, lines_b, label)


def marked(names, lines_a, lines_b):
    """The two versions in one, each differing block's two sides between conflict marks"""
    lines = []
    for block in blocks(lines_a, lines_b):
        if block[0] == 'same':
            lines += block[1]
        else:
            lines += ['%s %s' % (START, names[0])] + block[1] + [MIDDLE] + block[2] + ['%s %s' % (END, names[1])]
    return lines


def has_marks(lines):
    """Whether some of a merge's lines are still conflict marks"""
    return any(line.startswith((START + ' ', END + ' ')) or line == MIDDLE for line in lines)


def _in_editor(title, names, lines_a, lines_b, label):
    """The terminal's merge: the versions with their differing blocks marked, in the user's editor, until
    they save it without marks (or go back)"""
    editor = os.environ.get('VISUAL') or os.environ.get('EDITOR') or DEFAULT_EDITOR
    if not shutil.which(editor.split()[0]):
        messages.show(title, ["No editor to merge in: %s isn't installed (set EDITOR)." % (editor,)], label, 'red')
        return None
    with tempfile.TemporaryDirectory(prefix='dirdelta-merge-') as tmp:
        path = os.path.join(tmp, 'merged')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(marked(names, lines_a, lines_b)) + '\n')
        while True:
            try:
                subprocess.run(editor.split() + [path])
            except OSError as error:
                messages.show(title, ["Couldn't run %s: %s" % (editor, error)], label, 'red')
                return None
            with open(path, encoding='utf-8', errors='replace') as f:
                lines = f.read().splitlines()
            header = ("Its merge, as you saved it (%d lines)%s. Save it in both?" %
                      (len(lines), ", with conflict marks still in it" if has_marks(lines) else ""))
            answer = picker.pick_option([NOTHING, EDIT_AGAIN, SAVE], header=header, title="Merge", label=label)
            if answer == SAVE:
                return lines
            if answer != EDIT_AGAIN:
                return None
