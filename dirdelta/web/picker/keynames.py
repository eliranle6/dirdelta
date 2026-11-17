"""A picker's keys as the web page's buttons: the ones that end it (--expect, --expect-twice) or that
it notifies (--notify), each named as the keys row names it (--key KEY TEXT: 'Ctrl-R', 'refresh')"""

_NAMED = {'\t': 'Tab', ' ': 'Space', '\x1b': 'Esc', '\r': 'Enter'}
# Other names of a key, as a keys row or a help line may call it (Tab is Ctrl-I)
_ALIASES = {'\t': ('Ctrl-I',), '\r': ('Ctrl-M',), '\x1b': ('Ctrl-[',)}


def name(key):
    """The key's name as the keys row writes it: 'Ctrl-R' for '\\x12', 'Tab', or the key itself"""
    if key in _NAMED:
        return _NAMED[key]
    if len(key) == 1 and ord(key) < 32:
        return 'Ctrl-' + chr(ord(key) + 64)
    return key


def buttons(spec):
    """[{key, name, text, ends, twice}] of the picker's keys, in the order given, each once, its text
    what the keys row (or else the ? help's lines) says of it, or ''"""
    hints = {}
    for key_name, text in list(spec.key_hints) + list(spec.none_picked_key_hints) + _help_hints(spec.help_lines):
        hints.setdefault(key_name, text)
    found = []
    for keys, ends, twice in ((spec.expect, True, False), (spec.expect_twice, True, True), (spec.notify, False, False)):
        for key in keys:
            if all(button['key'] != key for button in found):
                key_name = name(key)
                names = [key_name + key_name] if twice else []
                names += [key_name] + list(_ALIASES.get(key, ()))
                found.append({'key': key, 'name': names[0], 'text': next((hints[one] for one in names if one in hints), ''),
                              'ends': ends, 'twice': twice})
    return found


def _help_hints(help_lines):
    """[(key, text)] of the help's lines of keys ('  KEY   what it does', as picker.key_help_lines() makes them)"""
    found = []
    for line in help_lines:
        if line.startswith('  ') and not line.startswith('   '):
            key_name, _, text = line.strip().partition(' ')
            if text.strip():
                found.append((key_name, text.strip()))
    return found


def side_buttons(spec):
    """The side tree's keys that end the picker there (--side-expect), as buttons()"""
    hints = dict(spec.side_hints)
    return [{'key': key, 'name': name(key), 'text': hints.get(name(key), ''), 'ends': True, 'twice': False}
            for key in spec.side_expect]
