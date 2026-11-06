"""The user's choices that last from one run to the next (SETTINGS_FILE): whether the file pickers
show the selected file's picture (images.py; `i` in a picker switches it)."""
import json
import os
import threading

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


def _load():
    try:
        with open(SETTINGS_FILE) as f:
            settings = json.load(f)
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(settings):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        temp_path = SETTINGS_FILE + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(settings, f, indent=1)
        os.replace(temp_path, SETTINGS_FILE)
    except OSError:
        # Then it's only for this run (nothing's printed: a picker may have the screen)
        pass
