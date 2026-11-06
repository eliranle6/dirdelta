"""Menus of options (pick_option()), and what an option may be"""
from dirdelta.ui.picker.kinds import Option, Skipped
from dirdelta.ui.picker.places import trail
from dirdelta.ui.picker.running import header_args, help_args, run_treepicker
from dirdelta.ui.picker.styles import unstyled


def pick_option(options, header='', shown_as=None, label=None, selected=None, title=None, key_hints=(),
                help_lines=(), previews_below=None):
    """Let the user pick one of the options: each a string, an Option, or a Skipped (a line that isn't
    an option: a heading, or BLANK). Returns the one picked (a string), or its id (an Option), or None
    if the user quit. Below, an option is what it's returned as.

    shown_as, if given, is called again and again while the menu is shown (every
    SHOWN_AS_INTERVAL seconds, on another thread), and returns {option: what to show it as} for
    the options to show otherwise than as they are, e.g. with a count that's coming in: a
    string, or a Disabled for one that can't be picked (until shown_as says otherwise). What's
    returned is still the option itself. label: as pick_files()'s. selected: the option to start
    with selected (else the first). title: what the menu is, after the breadcrumbs (see place()).
    key_hints, help_lines: as pick_files()'s. previews_below: {option: lines} shown below the
    menu, above its status bar, while the option is selected (e.g. what it would do), each line
    plain, or in colored parts (see segments()). shown_as's options may be Colored too."""
    lines, line_of, shown_first = _menu_lines(options)
    args = ['--list', '--root', trail(title)] + header_args(header) + help_args(key_hints, help_lines)
    if selected in line_of:
        args += ['--select', line_of[selected]]
    previews = None
    if previews_below:
        args.append('--preview-below')
        lines_previews = {line_of[option]: previews_below[option] for option in previews_below if option in line_of}
        previews = lambda send: send(lines_previews, default=[])

    def lines_shown():
        now = dict(shown_first)
        for option, shown in (shown_as() if shown_as is not None else {}).items():
            # (Its '' is the status, not an option)
            if option == '' or option in line_of:
                now[line_of.get(option, option)] = shown
        return now
    picked = run_treepicker(args, lines, lines_shown if shown_as is not None or shown_first else None, label, previews=previews)
    if picked is None:
        return None
    return {line: option for option, line in line_of.items()}.get(picked[0], picked[0])


def _menu_lines(options):
    """What treepicker gets of pick_option()'s options: (a line for each, {option (see pick_option()):
    its line}, {line: what to show it as at first}). A line is the option's text, each its own (a
    blank one, or a repeated one, with spaces after it), since treepicker tells them by it."""
    lines, line_of, shown_first = [], {}, {}
    for item in options:
        line = unstyled(option_label(item))
        while not line or line in shown_first or line in lines:
            line += ' '
        lines.append(line)
        if isinstance(item, Skipped):
            shown_first[line] = item
        else:
            line_of[option_id(item)] = line
            if isinstance(item, Option) and item.shown is not None:
                shown_first[line] = item.shown
    return lines, line_of, shown_first


def option_id(item):
    """What pick_option() returns for one of its options (not a Skipped)"""
    return item.id if isinstance(item, Option) else item


def option_label(item):
    """The plain text of one of pick_option()'s options"""
    if isinstance(item, Option):
        return item.label
    return item.text if isinstance(item, Skipped) else item
