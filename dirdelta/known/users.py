"""Who dirdelta is used by (its users, e.g. two people on one laptop, each with replicas of their own):
each user's own files apart (own()): their replicas, pairs and sorts (replicas.json), settings and
imports. The first user (OWNER, the computer's login) has them where they always were; any other has
them in a 'users/NAME' folder beside them (~/.config/dirdelta/users/hagit/replicas.json). What isn't
anyone's own is shared: the hashes and Drive's cache (one Drive account), the mounts, the phones'
copies.

Who the user is now (current()): the one this thread acts as (acting_as(): a web request's, a web
flow's), else the run's (set_default(): --user or DIRDELTA_USER, else OWNER)."""
import contextlib
import getpass
import os
import re
import threading

ENV = 'DIRDELTA_USER'
USERS_FOLDER = 'users'
NAME = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')


class UserError(Exception):
    pass


def _owner():
    try:
        name = getpass.getuser().lower()
    except Exception:
        name = 'me'
    return name if NAME.match(name) else 'me'


OWNER = _owner()
_default = os.environ.get(ENV, '').strip().lower() or OWNER
_local = threading.local()


def current():
    """The user acting now"""
    return getattr(_local, 'name', None) or _default


def set_default(name):
    """Act as name from now on, wherever no other user is acted as (the run's user)"""
    global _default
    _default = checked(name)


@contextlib.contextmanager
def acting_as(name):
    """This thread acts as the user name while in it"""
    before = getattr(_local, 'name', None)
    _local.name = checked(name)
    try:
        yield
    finally:
        _local.name = before


def checked(name):
    """name, if it can be a user's (lowercase letters, digits, - and _)"""
    if not isinstance(name, str) or not NAME.match(name):
        raise UserError("A user's name is lowercase letters, digits, - and _ (up to 32): %r" % (name,))
    return name


def own(path, name=None):
    """Where the user name's (default: the current one's) own copy of the file or dir at path (the
    owner's) is"""
    name = name or current()
    if name == OWNER:
        return path
    return os.path.join(os.path.dirname(path), USERS_FOLDER, name, os.path.basename(path))


def _users_dir():
    from dirdelta.known import replicas
    return os.path.join(os.path.dirname(replicas.REPLICAS_FILE), USERS_FOLDER)


def all_users():
    """Every user: the owner first, then the others by name"""
    try:
        others = sorted(name for name in os.listdir(_users_dir())
                        if NAME.match(name) and name != OWNER and os.path.isdir(os.path.join(_users_dir(), name)))
    except OSError:
        others = []
    return [OWNER] + others


def exists(name):
    return name in all_users()


def add(name):
    """Make name a user (with nothing of their own yet; the owner always is one)"""
    if checked(name) == OWNER:
        return
    os.makedirs(os.path.join(_users_dir(), checked(name)), exist_ok=True)
