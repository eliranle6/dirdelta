"""The mounts kept, in MOUNTS_FILE"""
import json
import os

from dirdelta.known.mounts import names
from dirdelta.known.mounts.names import Mount, MountsError


def load():
    """The mounts in names.MOUNTS_FILE, by mount point (none if there's no file yet)"""
    try:
        with open(names.MOUNTS_FILE) as mounts_file:
            content = json.load(mounts_file)
        return {target: Mount(target=target, **fields) for target, fields in content.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, AttributeError, TypeError) as error:
        raise MountsError("Cannot read %s (fix or remove it): %s" % (names.MOUNTS_FILE, error))


def save(mounts):
    """Write mounts (by mount point) to names.MOUNTS_FILE, replacing it at once (so it's never half-written)"""
    content = {target: {field: value for field, value in mount._asdict().items() if field != 'target'}
               for target, mount in sorted(mounts.items())}
    try:
        os.makedirs(os.path.dirname(names.MOUNTS_FILE), exist_ok=True)
        temp_path = names.MOUNTS_FILE + '.tmp'
        with open(temp_path, 'w') as mounts_file:
            json.dump(content, mounts_file, indent=2)
            mounts_file.write('\n')
        os.replace(temp_path, names.MOUNTS_FILE)
    except OSError as error:
        raise MountsError("Cannot write %s: %s" % (names.MOUNTS_FILE, error))
