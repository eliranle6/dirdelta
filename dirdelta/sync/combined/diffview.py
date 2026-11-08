"""What the combined tree's right column shows of a differing text file's two versions, in one of its
views (Ctrl-T cycles them): side by side, as diff -u does, or either version, its changed lines colored"""
import difflib
import shutil

from dirdelta.sync.combined import diffing
from dirdelta.ui import picker

KEY, KEY_NAME = '\x14', 'Ctrl-T'
SIDE_BY_SIDE, UNIFIED, VERSION_A, VERSION_B = range(4)
NR_VIEWS = 4
# The biggest file read for it (the whole diff: d, in less), and the most lines shown
MAX_SIZE = 1024 * 1024
MAX_LINES = 3000
TAB_WIDTH = 4
# The colors: lines only in A (or changed, A's), only in B (or changed, B's), a hunk's line
A_STYLE, B_STYLE, HUNK_STYLE = 'red', 'green', 'cyan'
# A side by side line's mark between the two: changed, only on the left, only on the right
CHANGED, ONLY_LEFT, ONLY_RIGHT = '≠', '<', '>'


def view_name(view, name_a, name_b):
    return {SIDE_BY_SIDE: "side by side", UNIFIED: "as diff -u", VERSION_A: "%s's version" % (name_a,),
            VERSION_B: "%s's version" % (name_b,)}[view]


def column_width():
    """How wide treepicker's preview column is (2/5 of the terminal, after its line and a space, up to
    its last column)"""
    columns = shutil.get_terminal_size().columns
    return max(20, columns - 1 - (columns - columns * 2 // 5 + 2))


def read_lines(path):
    """The text file's lines (tabs expanded, no line ends), or None if it isn't text or is too big"""
    try:
        with open(path, 'rb') as f:
            data = f.read(MAX_SIZE + 1)
    except OSError:
        return None
    if len(data) > MAX_SIZE or not diffing.is_text(path):
        return None
    return [line.expandtabs(TAB_WIDTH) for line in data.decode('utf-8', 'replace').splitlines()]


def lines_of(view, lines_a, lines_b, name_a, name_b, width):
    """The column's lines of the two versions (lists of lines) in view, width columns wide"""
    opcodes = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False).get_opcodes()
    if view == SIDE_BY_SIDE:
        shown = _side_by_side(opcodes, lines_a, lines_b, name_a, name_b, width)
    elif view == UNIFIED:
        shown = _unified(lines_a, lines_b, name_a, name_b)
    else:
        shown = _version(opcodes, lines_a if view == VERSION_A else lines_b, view == VERSION_A)
    if len(shown) > MAX_LINES:
        shown = shown[:MAX_LINES] + ["(and %d more lines: Ctrl-O shows all of it)" % (len(shown) - MAX_LINES,)]
    return shown


def _cut(text, width):
    """text cut or padded to width (one column a character: the files' wide characters may misalign)"""
    return text[:width].ljust(width)


def _side_by_side(opcodes, lines_a, lines_b, name_a, name_b, width):
    half = max(4, (width - 3) // 2)
    shown = [picker.styled([(_cut(name_a, half), 'bold'), (" │ ", None), (name_b, 'bold')])]
    for tag, a1, a2, b1, b2 in opcodes:
        for i in range(max(a2 - a1, b2 - b1)):
            left = lines_a[a1 + i] if a1 + i < a2 else None
            right = lines_b[b1 + i] if b1 + i < b2 else None
            mark = ' ' if tag == 'equal' else CHANGED if left is not None and right is not None else (
                ONLY_LEFT if right is None else ONLY_RIGHT)
            changed = tag != 'equal'
            shown.append(picker.styled([(_cut(left or '', half), A_STYLE if changed and left is not None else None),
                                        (" %s " % (mark,), 'bold' if changed else 'grey'),
                                        (right or '', B_STYLE if changed and right is not None else None)]))
    return shown


def _unified(lines_a, lines_b, name_a, name_b):
    shown = []
    for line in difflib.unified_diff(lines_a, lines_b, name_a, name_b, lineterm=''):
        style = (HUNK_STYLE if line.startswith('@@') else 'bold' if line.startswith(('---', '+++')) else
                 A_STYLE if line.startswith('-') else B_STYLE if line.startswith('+') else None)
        shown.append(picker.styled([(line, style)]) if style else line)
    return shown


def _version(opcodes, lines, is_a):
    """The version's lines, the ones the other lacks or has otherwise colored"""
    style = A_STYLE if is_a else B_STYLE
    shown = []
    for tag, a1, a2, b1, b2 in opcodes:
        start, end = (a1, a2) if is_a else (b1, b2)
        for line in lines[start:end]:
            shown.append(line if tag == 'equal' else picker.styled([(line or ' ', style)]))
    return shown
