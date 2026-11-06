"""What Claude said, kept by the files' hashes, or their paths and sizes"""
import json
import os

from dirdelta.claude.ai import config
from dirdelta.claude.ai.config import cache_lock


def path_key(path, size):
    """A cache's key of a file by where it is, for what isn't hashed yet"""
    return '%s\t%s' % (path, size)


def dir_key(path, file_count, total_size):
    """A cache's key of a dir by where it is, how many files it has and their total size: a dir that
    changed is asked about again"""
    return 'dir:%s\t%d\t%d' % (path, file_count, total_size)


def hash_key(sha1):
    """A cache's key of a file by its contents"""
    return 'sha1:%s' % (sha1,)


def cache_keys(cache_key, file):
    """cache_key(file) as a list: what it's kept under first, then what it may be cached under since
    before (e.g. by its path, before it was hashed)"""
    keys = cache_key(file)
    return [keys] if isinstance(keys, str) else list(keys)


def entry_of(cache, keys):
    """What cache has of the file with keys, by the first of them that's in it"""
    return next((cache[key] for key in keys if key in cache), {})


def cached(files, cache_key, root_name):
    """What the cache has of files (File), without asking Claude: ({relpath: description},
    {relpath: recommendation in the sorted tree root_name, as recommend() gives it})"""
    cache = load_cache()
    descriptions, recommendations = {}, {}
    for file in files:
        entry = entry_of(cache, cache_keys(cache_key, file))
        if entry.get('description'):
            descriptions[file.relpath] = entry['description']
        recommendation = cached_recommendation(entry, root_name)
        if recommendation:
            recommendations[file.relpath] = recommendation
    return descriptions, recommendations


def cached_dir(key, root_name):
    """What the cache has of the dir of key (dir_key()'s) in the sorted tree root_name, as
    recommend_dir() gives it, or None"""
    return cached_dirs({key: key}, root_name).get(key)


def cached_dirs(keys, root_name):
    """{name: what the cache has of the dir} of the dirs of keys ({name: dir_key()'s}) it has
    anything of, in the sorted tree root_name, as recommend_dir() gives it (one read of the cache)"""
    cache = load_cache()
    found = {}
    for name, key in keys.items():
        recommendation = cache.get(key, {}).get('recommendations', {}).get(root_name)
        if recommendation and recommendation.get('action') in ('move', 'split', 'remove'):
            found[name] = recommendation
    return found


def cached_recommendation(entry, root_name):
    """A cache entry's recommendation in the sorted tree root_name, if it has one that says what to
    do (one that doesn't, from an older dirdelta, is asked for again)"""
    recommendation = entry.get('recommendations', {}).get(root_name)
    if recommendation and (recommendation.get('action') == 'remove' or recommendation.get('path')):
        return recommendation
    return None


def carry(keys):
    """What the cache has of files by their paths, under their new ones too ({old key: new key}, see
    path_key()), after they were moved or copied, so it goes with them (by their hashes, it does)"""
    if not keys:
        return
    with cache_lock:
        cache = load_cache()
        for old_key, new_key in keys.items():
            if old_key in cache and new_key not in cache:
                cache[new_key] = dict(cache[old_key])
        save_cache(cache)


def load_cache():
    try:
        with open(config.CACHE_FILE) as f:
            cache = json.load(f)
        return cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    try:
        os.makedirs(os.path.dirname(config.CACHE_FILE), exist_ok=True)
        temp_path = config.CACHE_FILE + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(cache, f, indent=1)
        os.replace(temp_path, config.CACHE_FILE)
    except OSError:
        # Only a cache (and nothing's printed: a picker may have the screen): it's asked again
        pass
