"""The mounts kept, in MOUNTS_FILE"""
import json
import os

from dirdelta.known.mounts import names
from dirdelta.known.mounts.names import Mount, MountsError, UUID_KEY


def load():
    """The mounts in names.MOUNTS_FILE, by mount point, and by 'uuid:' and its disk's UUID (each disk's last mount:
    two disks of one model are mounted at one mount point, which keeps the last one's); none if there's no file yet"""
    try:
        with open(names.MOUNTS_FILE) as mounts_file:
            content = json.load(mounts_file)
        return {key: Mount(**dict({'target': key}, **fields)) for key, fields in content.items()}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, AttributeError, TypeError) as error:
        raise MountsError("Cannot read %s (fix or remove it): %s" % (names.MOUNTS_FILE, error))


def save(mounts):
    """Write mounts (by mount point) to names.MOUNTS_FILE, replacing it at once (so it's never half-written)"""
    # (A disk's own entry, by its UUID, says its mount point; a mount point's is its key)
    content = {key: {field: value for field, value in mount._asdict().items() if field != 'target' or key.startswith(UUID_KEY)}
               for key, mount in sorted(mounts.items())}
    try:
        os.makedirs(os.path.dirname(names.MOUNTS_FILE), exist_ok=True)
        temp_path = names.MOUNTS_FILE + '.tmp'
        with open(temp_path, 'w') as mounts_file:
            json.dump(content, mounts_file, indent=2)
            mounts_file.write('\n')
        os.replace(temp_path, names.MOUNTS_FILE)
    except OSError as error:
        raise MountsError("Cannot write %s: %s" % (names.MOUNTS_FILE, error))
