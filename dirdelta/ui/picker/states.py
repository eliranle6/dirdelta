"""Putting files in states (pick_states()), rather than picking them: e.g. what a sync does with each"""
import collections
import tempfile

from dirdelta.ui.picker.running import header_args, help_args, run_treepicker
from dirdelta.ui.picker.updates import null_terminated

# A state a file can be in: its name, its mark (one column, before the file) and color, the key that
# sets it ('' for none), and other marks for some groups' files: {group: (mark, color)}
State = collections.namedtuple('State', ['name', 'mark', 'color', 'key', 'group_marks'], defaults=('', {}))

# A file to put in a state: its relpath, its group ('' for none), the states it allows (their names;
# empty: all) and the one it's in at first ('' for the first)
StateEntry = collections.namedtuple('StateEntry', ['relpath', 'group', 'allowed', 'state'], defaults=('', (), ''))

# A tab above the tree: its title, and the groups of files it shows (empty: all)
Tab = collections.namedtuple('Tab', ['title', 'groups'], defaults=((),))

# What pick_states() returns: where the selection was ('' the root), each file's state but the
# first's ({relpath: name}), and the key that ended it ('' for Enter)
StatesPicked = collections.namedtuple('StatesPicked', ['selected', 'states', 'key'], defaults=('',))


def pick_states(rootpath, entries, states, tabs=(), header='', label=None, selected=None, shown_as=None,
                previews=None, key_hints=(), help_lines=(), footer='', keys='', on_selection=None, notify_keys='',
                on_notify=None):
    """Let the user put each of the files of entries (StateEntry, relative to rootpath, as pick_files() takes
    relpaths) in one of states (State, the first, e.g. skip, being "nothing"): Space puts the selected
    file (a dir's files) in the next state it allows, and a state's key in that one. tabs: Tab, each
    showing some groups of the files. Returns a StatesPicked once the user is done (Enter, with a file
    in a state other than the first, or one of keys, which end it too, with the states so far), or None
    if they quit. selected, shown_as, previews, label, key_hints, help_lines, footer, on_selection,
    notify_keys and on_notify (called with the key and the selected relpath): as pick_files()'s."""
    args = (['--typed', '--root', rootpath, '-m', '--print-selection'] + header_args(header) +
            help_args(key_hints, help_lines))
    for state in states:
        args += ['--state', state.name, state.mark, state.color, state.key]
    for state in states:
        for group, (mark, color) in state.group_marks.items():
            args += ['--state-mark', state.name, group, mark, color]
    for tab in tabs:
        args += ['--tab', tab.title, ','.join(tab.groups)]
    if footer:
        args += ['--footer', footer]
    if selected is not None:
        args += ['--select', selected or '.']
    if keys:
        args += ['--expect', keys]
    with tempfile.NamedTemporaryFile('wb', prefix='dirdelta-states-') as states_file:
        states_file.write(null_terminated('%s\t%s\t%s\t%s' % (','.join(entry.allowed), entry.state, entry.group,
                                                              entry.relpath) for entry in entries))
        states_file.flush()
        args += ['--states', states_file.name]
        notify = None
        if notify_keys and on_notify is not None:
            notify = (notify_keys, lambda key, selected, picked: on_notify(key, selected))
        printed = run_treepicker(args + ['-'], ('f ' + entry.relpath for entry in entries), shown_as=shown_as,
                                 label=label, previews=previews, on_selection=on_selection, notify=notify)
    if printed is None:
        return None
    key = ''
    if keys:
        key, printed = printed[0], printed[1:]
    selected, printed = printed[0], printed[1:]
    chosen = {}
    for line in printed:
        name, _, relpath = line.partition('\t')
        chosen[relpath] = name
    return StatesPicked('' if selected == '.' else selected, chosen, key)
