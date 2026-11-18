"""Each user's choices that last from one run to the next (SETTINGS_FILE): whether the file pickers
show the selected file's picture (images.py; `i` in a picker switches it), and the address links are
emailed to (sharing/link.py)."""
import json
import os
import threading

from dirdelta.known import users

# The owner's (another user's: in a folder of theirs beside it, see users.py)
SETTINGS_FILE = os.path.expanduser('~/.config/dirdelta/settings.json')
_lock = threading.Lock()


def are_images_shown():
    """Whether the file pickers show pictures (the default: yes)"""
    return _load().get('images', True) is not False


def set_images_shown(is_shown):
    with _lock:
        settings = _load()
        settings['images'] = bool(is_shown)
        _save(settings)


def email_address():
    """The address links are emailed to, or None if none's known yet"""
    address = _load().get('email')
    return address if isinstance(address, str) and address else None


def set_email_address(address):
    with _lock:
        settings = _load()
        settings['email'] = address
        _save(settings)


def _load():
    try:
        with open(users.own(SETTINGS_FILE)) as f:
            settings = json.load(f)
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(settings):
    path = users.own(SETTINGS_FILE)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = path + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(settings, f, indent=1)
        os.replace(temp_path, path)
    except OSError:
        # Then it's only for this run (nothing's printed: a picker may have the screen)
        pass
