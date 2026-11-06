"""Asking Claude about a dir as a whole"""
from dirdelta.claude.ai import query
from dirdelta.claude.ai.cache import _load_cache, _save_cache, cached_dir
from dirdelta.claude.ai.config import AIError, DIR_SYSTEM_PROMPT, MAX_DESCRIPTION_WORDS, MODEL, _cache_lock
from dirdelta.claude.ai.prompts import _listed_dirs, _short


def recommend_dir(dir_, key, dirs, root_name, anew=False):
    """What to do with the inbox's dir (a Dir) as a whole, in the sorted tree root_name (whose dirs
    are dirs, as recommend()'s): {'action', 'path', 'summary', 'reason'}: 'move' it to path (its
    relpath in the sorted tree: its name kept or a better one, in the dir it belongs in; or an
    existing dir to merge it into), 'split' it (its files don't go together: to ask about each), or
    'remove' it (e.g. all its files are copies of the sorted tree's; path ''); summary: what it is, in
    a few words. From the cache (by key, dir_key()'s), unless anew, or Claude (which reads nothing).
    Raises AIError if Claude can't be asked, or says nothing to go by."""
    if not anew:
        recommendation = cached_dir(key, root_name)
        if recommendation:
            return recommendation
    recommendation = _ask_for_dir_recommendation(dir_, dirs, root_name)
    with _cache_lock:
        cache = _load_cache()
        cache.setdefault(key, {}).setdefault('recommendations', {})[root_name] = recommendation
        _save_cache(cache)
    return recommendation


def _ask_for_dir_recommendation(dir_, dirs, root_name):
    """{'action', 'path', 'summary', 'reason'} of what Claude says to do with the inbox's dir (a Dir)"""
    types = ', '.join("%d %s" % (count, extension or "without an extension")
                      for extension, count in sorted(dir_.types.items(), key=lambda item: (-item[1], item[0])))
    lines = ["Its name: %s" % (dir_.relpath,),
             "%d files, %d bytes in all: %s" % (dir_.file_count, dir_.total_size, types)]
    lines.append("Some of their names: %s" % (', '.join(dir_.names),))
    if dir_.dates:
        lines.append("Taken or modified from %s to %s" % dir_.dates)
    for relpath, description in sorted(dir_.descriptions.items()):
        lines.append("What %s is: %s" % (relpath, description))
    if dir_.copies:
        lines.append("%d of its files are in the sorted tree already, with the same contents" % (dir_.copies,))
    prompt = ("What to do with this dir of the inbox, as a whole, in the sorted tree %s, whose dirs are "
              "listed below (relative to its root, with a few of the names of the files in each).\n"
              "- 'move': its files go together (e.g. one trip's photos, one year's tax papers): the path "
              "relative to the root it should have there, a dir in the tree's style. Its own name, "
              "unless that says little (e.g. 'New folder', 'DCIM', 'export'): then a name like the tree's "
              "(e.g. with the year, or what it's of). Under the existing dir where it belongs (a new one "
              "where none fits). Or an existing dir itself, if the files are more of what's in it, to "
              "merge them into it.\n"
              "- 'split': its files don't go together (e.g. a Downloads dir of this and that), so each "
              "should be asked about on its own (an empty path).\n"
              "- 'remove': it's all copies of the sorted tree's files, or clearly junk (an empty path).\n"
              "And the summary: what it is, in at most %d words (e.g. 'Rome trip photos, Oct 2024'), and "
              "the reason, in a few words.\n\n"
              "The dir:\n%s\n\nThe sorted tree's dirs:\n%s" %
              (root_name, MAX_DESCRIPTION_WORDS, '\n'.join(lines), '\n'.join(_listed_dirs(dirs)) or "(none yet)"))
    schema = {"type": "object",
              "properties": {"action": {"type": "string", "enum": ["move", "split", "remove"]},
                             "path": {"type": "string"}, "summary": {"type": "string"},
                             "reason": {"type": "string"}},
              "required": ["action", "path", "summary", "reason"]}
    result = query._run_query(prompt, [], schema, max_turns=5, model=MODEL, system_prompt=DIR_SYSTEM_PROMPT)
    action = result.get('action')
    answer = {'action': action, 'path': '', 'summary': _short(result.get('summary', '')),
              'reason': result.get('reason', '').strip()}
    if action == 'move':
        parts = [part for part in result.get('path', '').strip().split('/') if part not in ('', '.')]
        if not parts or '..' in parts:
            raise AIError("Claude said to move it, but not where to (%r)" % (result.get('path', ''),))
        answer['path'] = '/'.join(parts)
    elif action not in ('split', 'remove'):
        raise AIError("Claude didn't say what to do with it (%r)" % (action,))
    return answer


def recommended_path(recommendation):
    """The path in the sorted tree that a recommendation says its file goes to; None if it says to
    remove the file"""
    return None if recommendation.get('action') == 'remove' else recommendation['path']
