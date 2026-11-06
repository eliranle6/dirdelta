"""Opening from a menu (confirmed on a screen of its own), and a picker's tags with opening's"""
from dirdelta.ui import picker
from dirdelta.ui.opening import names
from dirdelta.ui.opening.names import CONFIRM_NO, CONFIRM_YES, files_text, tag_style
from dirdelta.util import text


def confirm(opener, relpaths, files, label=None):
    """Whether to open relpaths (of files) with opener, as the action menu's Open: asked on a
    screen of its own (No first) if there's more than one file to download (else yes at once)"""
    question = opener.question(relpaths, files)
    if question is None:
        return True
    found = opener.to_download(relpaths, files)
    lines = ["Open %s? First, %s:" % (files_text(len(relpaths)), question.replace(", and open them", ""))]
    lines += ["  %s (%s)" % (relpath, text.format_size(size or 0)) for relpath, size in found[:names.MAX_OPENED]]
    answer = picker.pick_option([CONFIRM_NO, CONFIRM_YES], header='\n'.join(lines), label=label, title="Sure?")
    return answer == CONFIRM_YES


def with_tags(shown, opener, name_of):
    """A picker's shown_as result (shown, {relpath: text}) with opener's tags after the files'
    texts: name_of(relpath) is what a file is shown as without one, for the ones shown has none of"""
    for relpath, tag in opener.tags().items():
        text = shown.get(relpath) or name_of(relpath)
        shown[relpath] = text + picker.styled([("  ", None), (tag, tag_style(tag))]) if tag else text
    return shown
