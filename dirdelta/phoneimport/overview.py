"""An import's overview (of()): how many files its source has, how many are hashed (each is as it's
copied), and for each replica checked how many it has already: by their contents, or only by name and
size (the phone's file not hashed yet, or the replica's), and how many no replica has; then what's been
chosen (and of those, copied: ready to move), moved and skipped"""
from dirdelta.phoneimport import known
from dirdelta.phoneimport import store

# What a file's match in a replica is: the same contents; the same name and size, with the phone's file
# not hashed yet, or with its hash known but not the replica's file's
CONTENTS, NAME_PHONE_UNHASHED, NAME_REPLICA_UNHASHED = 'contents', 'namePhoneUnhashed', 'nameReplicaUnhashed'


def match(info, how):
    """How sure the match (a Known.found() how) of the file of info is"""
    if how == known.SAME_CONTENTS:
        return CONTENTS
    return NAME_REPLICA_UNHASHED if info.get('sha1') else NAME_PHONE_UNHASHED


def of(files, haves, replica_paths):
    """The overview of files ({relpath: info}, an import's), haves ({relpath: [(replica, relpath there,
    how)]}, or None while the replicas are being checked) and the replicas checked"""
    counts = {store.PENDING: 0, store.COPIED: 0, store.MOVED: 0, store.SKIPPED: 0}
    replicas = {path: {'path': path, 'have': 0, CONTENTS: 0, NAME_PHONE_UNHASHED: 0, NAME_REPLICA_UNHASHED: 0}
                for path in replica_paths}
    hashed = chosen = ready = in_none = in_all = 0
    # The files not hashed: all, and the ones a replica has by name and size only (what hashing confirms)
    unhashed, name_only = [0, 0], [0, 0]
    for relpath, info in files.items():
        counts[info['state']] += 1
        hashed += bool(info.get('sha1'))
        if not info.get('sha1') and info['state'] != store.MOVED:
            unhashed[0] += 1
            unhashed[1] += info['size']
            if haves is not None and haves.get(relpath):
                name_only[0] += 1
                name_only[1] += info['size']
        chosen += bool(info.get('target')) and info['state'] in (store.PENDING, store.COPIED)
        ready += bool(info.get('target')) and info['state'] == store.COPIED
        if haves is None:
            continue
        roots = set()
        for replica, _, how in haves.get(relpath, []):
            if replica in replicas and replica not in roots:
                roots.add(replica)
                replicas[replica]['have'] += 1
                replicas[replica][match(info, how)] += 1
        in_none += not roots
        in_all += len(roots) == len(replicas)
    for found in replicas.values():
        found['missing'] = len(files) - found['have']
    return {'total': len(files), 'hashed': hashed, 'counts': counts, 'chosen': chosen, 'ready': ready,
            'unhashed': {'files': unhashed[0], 'size': unhashed[1]},
            'nameOnly': {'files': name_only[0], 'size': name_only[1]},
            'checked': haves is not None, 'replicas': [replicas[path] for path in replica_paths],
            'inNone': in_none if haves is not None else None, 'inAll': in_all if haves is not None else None}
