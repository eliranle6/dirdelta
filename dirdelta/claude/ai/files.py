"""Asking Claude about files in batches: their descriptions, and where they go"""
from dirdelta.claude.ai.cache import cached_recommendation, entry_of, cache_keys, load_cache, save_cache
from dirdelta.claude.ai.config import AIError, BATCH_SIZE, cache_lock
from dirdelta.claude.ai.prompts import ask_for_descriptions, ask_for_recommendations


def describe(files, cache_key, progress=None, anew=()):
    """{relpath: description} of files (File), a sentence of at most MAX_DESCRIPTION_WORDS words
    each, from the cache or Claude (which reads them), in batches of BATCH_SIZE,
    calling progress(done, count) after each. cache_key(file) is the file's key in the cache, or its
    keys (see cache_keys()); the files at anew (relpaths) are asked about again, whatever it has. Raises AIError if Claude can't
    be asked."""
    def is_cached(entry):
        return entry.get('description') and {'description': entry['description']}

    def keep(entry, answer):
        entry['description'] = answer['description']
    found = _ask(files, cache_key, is_cached, keep, ask_for_descriptions, progress, anew)
    return {relpath: answer['description'] for relpath, answer in found.items()}


def recommend(files, cache_key, dirs, root_name, descriptions, copies=None, progress=None, anew=()):
    """{relpath: {'action', 'path', 'reason'}} of files (File): what to do with each, 'move' it to
    where in the sorted tree (root_name, whose dirs are dirs: {relpath: a few of its files' names})
    it belongs, its path relative to its root: a dir (an existing one, or a new one where none
    fits) and a name (its own, or a better one if it says little, or doesn't fit the names in that
    dir); or 'remove' it (its path then ''): a copy of a file already there (copies: {relpath: the
    paths in the sorted tree of files with the same contents}, its 'copies'), or junk (no copies:
    what Claude says, its reason why), from the cache or Claude.
    It goes by the files' names, sizes and descriptions ({relpath: description},
    e.g. describe()'s), so it reads nothing. The files at anew are asked about again, as describe()'s."""
    copies = copies or {}
    def is_cached(entry):
        recommendation = cached_recommendation(entry, root_name)
        # One made before the file was found to be a copy isn't of what's known now
        if recommendation and recommendation.get('copies', []) != sorted(copies.get(entry.get('_relpath'), [])):
            return None
        return recommendation

    def keep(entry, answer):
        entry.setdefault('recommendations', {})[root_name] = answer
    return _ask(files, cache_key, is_cached, keep,
                lambda batch: ask_for_recommendations(batch, dirs, root_name, descriptions, copies), progress, anew)


def _ask(files, cache_key, is_cached, keep, ask, progress, anew=()):
    """{relpath: answer} of files: is_cached(entry) of each one's cache entry (but the ones at anew,
    relpaths), or else ask(batch) of the others (BATCH_SIZE at a time) for {relpath: answer}, each
    kept by keep(entry, answer)"""
    cache = load_cache()
    found = {}
    needed = []
    for file in files:
        answer = (None if file.relpath in anew else
                  is_cached(dict(entry_of(cache, cache_keys(cache_key, file)), _relpath=file.relpath)))
        if answer:
            found[file.relpath] = answer
        else:
            needed.append(file)
    for start in range(0, len(needed), BATCH_SIZE):
        if progress is not None:
            progress(start, len(needed))
        batch = needed[start:start + BATCH_SIZE]
        answers = _ask_each_if_failed(ask, batch)
        # Kept at once, so what was asked isn't asked again if it's stopped
        with cache_lock:
            cache = load_cache()
            for file in batch:
                answer = answers.get(file.relpath)
                if answer is not None:
                    found[file.relpath] = answer
                    keys = cache_keys(cache_key, file)
                    # Under its first key, with what's known of it by the others
                    entry = cache.setdefault(keys[0], dict(entry_of(cache, keys)))
                    keep(entry, answer)
            save_cache(cache)
    if progress is not None and needed:
        progress(len(needed), len(needed))
    return found


def _ask_each_if_failed(ask, batch):
    """ask(batch), or if it fails, ask() of each file on its own, so one that Claude can't take
    doesn't fail the others; raises AIError only if all fail"""
    try:
        return ask(batch)
    except AIError:
        if len(batch) == 1:
            raise
    answers, last_error = {}, None
    for file in batch:
        try:
            answers.update(ask([file]))
        except AIError as error:
            last_error = error
    if not answers and last_error is not None:
        raise last_error
    return answers
