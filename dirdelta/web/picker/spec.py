"""What a treepicker command asks for (Spec), read from its arguments as dirdelta's picker makes them
(ui/picker/command.py; the options are treepicker's, see docs/treepicker-integration.md), for the web
picker to do the same in the browser"""

# Options without a value, with one, two and four
_FLAGS = {'-0', '-m', '--typed', '--list', '--print-selection', '--dirs-only', '--lazy',
          '--enter-picks-selection', '--preview-below'}
_ONE = {'--root', '--header', '--footer', '--select', '--expect', '--expect-twice', '--picked', '--states',
        '--max-depth', '--exclude', '--notify', '--side', '--side-root', '--side-key', '--side-expect',
        '--side-start', '--label', '--label-color', '--help-line', '--updates', '--preview', '--selection',
        '--notify-fd', '--side-select'}
_TWO = {'--key', '--key-if-none-picked', '--side-hint', '--tab'}
_FOUR = {'--state', '--state-mark'}


class SpecError(Exception):
    """Arguments the web picker doesn't know"""


class Spec(object):
    """A picker's arguments: what it shows, how it's picked, and its pipes' fds"""

    def __init__(self):
        self.flags = set()
        self.root = '.'
        self.header = self.footer = ''
        self.select = None
        self.expect = self.expect_twice = self.notify = ''
        self.picked_file = self.states_file = self.side_file = None
        self.max_depth = None
        self.excluded = []
        self.labels = []
        self.key_hints, self.none_picked_key_hints, self.help_lines = [], [], []
        # [(name, mark, color, key)], the first "nothing"; {(name, group): (mark, color)}; [(title, groups)]
        self.states, self.state_marks, self.tabs = [], {}, []
        self.side_root, self.side_key, self.side_expect, self.side_start = '', '', '', None
        self.side_hints = []
        # {option: fd}: --updates, --preview, --selection, --notify-fd, --side-select
        self.fds = {}
        # '-' (items on stdin), or the dir to scan
        self.source = None

    @property
    def is_list(self):
        return '--list' in self.flags

    @property
    def is_multi(self):
        return '-m' in self.flags

    @property
    def prints_key(self):
        """Whether what's printed starts with the key that ended it ('' for Enter)"""
        return bool(self.expect or self.expect_twice or self.side_key)


def parse(args):
    """The Spec of treepicker's args (without the program's name). Raises SpecError for one it doesn't
    know."""
    spec, i = Spec(), 0
    while i < len(args):
        option = args[i]
        if option in _FLAGS:
            spec.flags.add(option)
            i += 1
        elif option in _ONE:
            _one(spec, option, _values(args, i, 1)[0])
            i += 2
        elif option in _TWO:
            _two(spec, option, *_values(args, i, 2))
            i += 3
        elif option in _FOUR:
            first, second, third, fourth = _values(args, i, 4)
            if option == '--state':
                spec.states.append((first, second, third, fourth))
            else:
                spec.state_marks[(first, second)] = (third, fourth)
            i += 5
        elif not option.startswith('-') or option == '-':
            spec.source = option
            i += 1
        else:
            raise SpecError("Unknown option %s" % (option,))
    return spec


def _values(args, i, count):
    if i + count >= len(args):
        raise SpecError("%s takes %d values" % (args[i], count))
    return args[i + 1:i + 1 + count]


def _one(spec, option, value):
    if option in ('--updates', '--preview', '--selection', '--notify-fd', '--side-select'):
        spec.fds[option] = int(value)
    elif option == '--label':
        spec.labels.append([value, ''])
    elif option == '--label-color':
        if spec.labels:
            spec.labels[-1][1] = value
    elif option == '--help-line':
        spec.help_lines.append(value)
    elif option == '--exclude':
        spec.excluded.append(value)
    elif option == '--max-depth':
        spec.max_depth = int(value)
    else:
        setattr(spec, {'--picked': 'picked_file', '--states': 'states_file', '--side': 'side_file',
                       '--expect-twice': 'expect_twice'}.get(option, option[2:].replace('-', '_')), value)


def _two(spec, option, first, second):
    if option == '--key':
        spec.key_hints.append((first, second))
    elif option == '--key-if-none-picked':
        spec.none_picked_key_hints.append((first, second))
    elif option == '--side-hint':
        spec.side_hints.append((first, second))
    else:
        spec.tabs.append((first, [group for group in second.split(',') if group]))
