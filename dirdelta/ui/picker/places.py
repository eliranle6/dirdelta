"""Where the user is, the screens' breadcrumbs (place(), trail())"""
import contextlib


# Where the user is, the screens' breadcrumbs: the places entered (see place()), after the program's
# name. A menu's tree's root shows them (treepicker shows the path to the selection after it).
PROGRAM = 'dirdelta'
places_entered = []
# What the trail's places are shown apart by, as treepicker shows a path
TRAIL_SEPARATOR = ' > '


@contextlib.contextmanager
def place(name):
    """Inside, the menus' breadcrumbs end with name (e.g. 'Sync eliran \u21c4 cloud/eliran')"""
    places_entered.append(name)
    try:
        yield
    finally:
        places_entered.pop()


def trail(title=None):
    """The breadcrumbs, as a menu's root shows them: the program, the places, and title, if given"""
    return TRAIL_SEPARATOR.join([PROGRAM] + places_entered + ([title] if title else []))


# A preview's line starting with it, a label color's name and it again is shown highlighted (see
