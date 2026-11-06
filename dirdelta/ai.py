"""What Claude (MODEL) says of files: a short description of each (which reads them), and where in
a sorted tree it belongs (by their names, sizes and descriptions: it reads nothing), and of a dir of
them as a whole, where it goes (recommend_dir()), for sorting an inbox (see inbox.py). Through the Claude Agent SDK, which runs Claude Code, and so the
laptop's logged-in Claude (or ANTHROPIC_API_KEY, if set).

Claude reads the files itself, with its Read tool (text, images, PDFs), and with no other tool: it
gets only the paths it's given, in a dir of its own (cwd). What it says is cached (CACHE_FILE), by
the file's contents' hash once it's known (so what's said of a file goes with it when it moves, and
its copies share it), else by its path and size, so it's asked once per file. It sends the files' contents to Anthropic,
so it's only asked when the user chooses to."""
import asyncio
import collections
import gc
import json
import logging
import os
import threading


# The model, for descriptions and recommendations both: the fastest and cheapest
MODEL = 'claude-haiku-5-5'
# For a plan of what to do with files (see aiplan.py), where following what the user said matters most
PLAN_MODEL = 'claude-opus-5-5'
CACHE_FILE = os.path.expanduser('~/.cache/dirdelta/ai.json')
# Around reading the cache, changing it and writing it, from the worker's thread and the main one, so
# neither overwrites what the other added
_cache_lock = threading.Lock()
# How many files one request is about
BATCH_SIZE = 10
# Bigger files aren't read (Claude says what it can from their names)
MAX_READ_SIZE = 20 * 1024 * 1024
# The biggest message from Claude Code the SDK takes (a file read is in one), and how many of Claude
# Code's last stderr lines are kept, for an error
MAX_MESSAGE_SIZE = 64 * 1024 * 1024
STDERR_LINES_KEPT = 20
# The most words of a description, and of the sorted tree's dirs a recommendation is given
MAX_DESCRIPTION_WORDS = 10
MAX_DIRS_GIVEN = 3000

SYSTEM_PROMPT = (
    "You help sort a person's files. You get a numbered list of files. Read each one marked "
    "'read it' with the Read tool (it shows text, images and PDFs); for the others, go by the name, "
    "type and size. Don't read any other file. Then answer about every file in the list, by its "
    "number.")
RECOMMEND_SYSTEM_PROMPT = (
    "You help sort a person's files into their sorted tree of dirs. You get a numbered list of files, "
    "each with its name, size and what it is, and the tree's dirs. Answer about every file in the "
    "list, by its number.")


DIR_SYSTEM_PROMPT = (
    "You help sort a person's files into their sorted tree of dirs. You get a dir of their inbox: "
    "what's in it (its size, its types of files, some of their names, dates and what a few of them are), "
    "and the tree's dirs. Say what to do with the dir as a whole.")
# How many of a dir's files' names Claude is given (the first, the last, and some between)
DIR_NAMES_GIVEN = 12


class AIError(Exception):
    pass


# A file to ask about: its relpath (in the inbox), its path on the local disk to read (None: not
# read), and its size (or None)
File = collections.namedtuple('File', ['relpath', 'local_path', 'size'])


def _schema(fields, enums=None):
    """The answers' schema: a list of {number, the fields (strings; those in enums, {field: values},
    one of their values)}"""
    enums = enums or {}
    item = {"type": "object",
            "properties": dict({"number": {"type": "integer"}},
                               **{field: dict({"type": "string"}, **({"enum": enums[field]} if field in enums else {}))
                                  for field in fields}),
            "required": ["number"] + list(fields)}
    return {"type": "object", "properties": {"files": {"type": "array", "items": item}}, "required": ["files"]}


# A dir of the inbox to ask about as a whole (see recommend_dir()): its relpath (in the inbox), how
# many files it has (under it, at any depth) and their total size, how many of each type
# ({extension: count}), some of their relpaths (in the dir), the dates they were taken or modified
# (the first and the last, 'YYYY-MM-DD', or None), {relpath in the dir: description} of a few, and how many
# of them are in the sorted tree already (copies)
Dir = collections.namedtuple('Dir', ['relpath', 'file_count', 'total_size', 'types', 'names', 'dates',
                                     'descriptions', 'copies'])


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


def _keys(cache_key, file):
    """cache_key(file) as a list: what it's kept under first, then what it may be cached under since
    before (e.g. by its path, before it was hashed)"""
    keys = cache_key(file)
    return [keys] if isinstance(keys, str) else list(keys)


def _entry_of(cache, keys):
    """What cache has of the file with keys, by the first of them that's in it"""
    return next((cache[key] for key in keys if key in cache), {})


def describe(files, cache_key, progress=None, anew=()):
    """{relpath: description} of files (File), a sentence of at most MAX_DESCRIPTION_WORDS words
    each, from the cache or Claude (which reads them), in batches of BATCH_SIZE,
    calling progress(done, count) after each. cache_key(file) is the file's key in the cache, or its
    keys (see _keys()); the files at anew (relpaths) are asked about again, whatever it has. Raises AIError if Claude can't
    be asked."""
    def is_cached(entry):
        return entry.get('description') and {'description': entry['description']}

    def keep(entry, answer):
        entry['description'] = answer['description']
    found = _ask(files, cache_key, is_cached, keep, _ask_for_descriptions, progress, anew)
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
        recommendation = _cached_recommendation(entry, root_name)
        # One made before the file was found to be a copy isn't of what's known now
        if recommendation and recommendation.get('copies', []) != sorted(copies.get(entry.get('_relpath'), [])):
            return None
        return recommendation

    def keep(entry, answer):
        entry.setdefault('recommendations', {})[root_name] = answer
    return _ask(files, cache_key, is_cached, keep,
                lambda batch: _ask_for_recommendations(batch, dirs, root_name, descriptions, copies), progress, anew)


def cached(files, cache_key, root_name):
    """What the cache has of files (File), without asking Claude: ({relpath: description},
    {relpath: recommendation in the sorted tree root_name, as recommend() gives it})"""
    cache = _load_cache()
    descriptions, recommendations = {}, {}
    for file in files:
        entry = _entry_of(cache, _keys(cache_key, file))
        if entry.get('description'):
            descriptions[file.relpath] = entry['description']
        recommendation = _cached_recommendation(entry, root_name)
        if recommendation:
            recommendations[file.relpath] = recommendation
    return descriptions, recommendations


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


def cached_dir(key, root_name):
    """What the cache has of the dir of key (dir_key()'s) in the sorted tree root_name, as
    recommend_dir() gives it, or None"""
    return cached_dirs({key: key}, root_name).get(key)


def cached_dirs(keys, root_name):
    """{name: what the cache has of the dir} of the dirs of keys ({name: dir_key()'s}) it has
    anything of, in the sorted tree root_name, as recommend_dir() gives it (one read of the cache)"""
    cache = _load_cache()
    found = {}
    for name, key in keys.items():
        recommendation = cache.get(key, {}).get('recommendations', {}).get(root_name)
        if recommendation and recommendation.get('action') in ('move', 'split', 'remove'):
            found[name] = recommendation
    return found


def _ask(files, cache_key, is_cached, keep, ask, progress, anew=()):
    """{relpath: answer} of files: is_cached(entry) of each one's cache entry (but the ones at anew,
    relpaths), or else ask(batch) of the others (BATCH_SIZE at a time) for {relpath: answer}, each
    kept by keep(entry, answer)"""
    cache = _load_cache()
    found = {}
    needed = []
    for file in files:
        answer = (None if file.relpath in anew else
                  is_cached(dict(_entry_of(cache, _keys(cache_key, file)), _relpath=file.relpath)))
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
        with _cache_lock:
            cache = _load_cache()
            for file in batch:
                answer = answers.get(file.relpath)
                if answer is not None:
                    found[file.relpath] = answer
                    keys = _keys(cache_key, file)
                    # Under its first key, with what's known of it by the others
                    entry = cache.setdefault(keys[0], dict(_entry_of(cache, keys)))
                    keep(entry, answer)
            _save_cache(cache)
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


def _size_text(file):
    return "size %d bytes" % (file.size,) if file.size is not None else "size unknown"


def _ask_for_descriptions(files):
    """{relpath: {'description'}} of what Claude says of files, reading the ones it may"""
    lines = []
    for number, file in enumerate(files, 1):
        is_read = file.local_path is not None and (file.size or 0) <= MAX_READ_SIZE
        lines.append("%d. %s (%s%s)%s" % (
            number, file.relpath, _size_text(file), "" if is_read else ", don't read it",
            (": read it at %s" % (file.local_path,)) if is_read else ""))
    prompt = ("For each file, a description: one short sentence, at most %d words, saying what it is "
              "(e.g. 'a cat asleep on a red sofa', 'a 2023 tax form for Eliran').\n\nThe files:\n%s" %
              (MAX_DESCRIPTION_WORDS, '\n'.join(lines)))
    readable = [os.path.dirname(file.local_path) for file in files if file.local_path is not None]
    result = _run_query(prompt, sorted(set(readable)), _schema(['description']),
                        max_turns=2 * len(files) + 5, model=MODEL)
    return {files[number - 1].relpath: {'description': _short(item.get('description', ''))}
            for number, item in _numbered(result, files)}


def _ask_for_recommendations(files, dirs, root_name, descriptions, copies):
    """{relpath: {'action', 'path', 'reason', 'copies'}} of what Claude says to do with files, by
    what's known of them"""
    lines = ["%d. %s (%s)%s%s" % (number, file.relpath, _size_text(file),
                                  ": " + descriptions[file.relpath] if file.relpath in descriptions else "",
                                  "; already in the sorted tree, with the same contents, at %s" %
                                  (', '.join(copies[file.relpath]),) if copies.get(file.relpath) else "")
             for number, file in enumerate(files, 1)]
    listed = _listed_dirs(dirs)
    prompt = ("Where each of these files belongs in the sorted tree %s, whose dirs are listed below "
              "(relative to its root, with a few of the names of the files in each): its new path, "
              "relative to the root, a dir and a file name. The dir: an existing one from the list "
              "where one fits, else a new one to make, in the tree's style. The name: the file's own, "
              "unless it says little of what the file is (e.g. IMG_2041.jpg, scan001.pdf, "
              "document(3).pdf) or doesn't fit how the files in that dir are named: then a name like "
              "theirs, with the file's extension. And the reason, in a few words. Files that go "
              "together (e.g. one trip's photos) should go to one dir. A file said to be in the "
              "sorted tree already is a copy: its action should be 'remove' (with an empty path), "
              "unless the copy in the tree is in the wrong place, and this one should go elsewhere. "
              "A file that's clearly junk by its name, size and what it is (a temporary or system "
              "file, an empty one, an unfinished download, a leftover installer) is 'remove' too, its "
              "reason saying why it's junk; only when that's clear: when in doubt, it's 'move'. Every "
              "other file's action is 'move'.\n\n"
              "The files (name, size, and what each is):\n%s\n\nThe sorted tree's dirs:\n%s" %
              (root_name, '\n'.join(lines), '\n'.join(listed) or "(none yet)"))
    result = _run_query(prompt, [], _schema(['action', 'path', 'reason'], {'action': ['move', 'remove']}),
                        max_turns=5, model=MODEL, system_prompt=RECOMMEND_SYSTEM_PROMPT)
    answers = {}
    for number, item in _numbered(result, files):
        relpath = files[number - 1].relpath
        reason = item.get('reason', '').strip()
        known = sorted(copies.get(relpath, []))
        if item.get('action') == 'remove':
            # A copy (known by its contents), or else junk (what Claude says)
            answers[relpath] = {'action': 'remove', 'path': '', 'reason': reason, 'copies': known}
            continue
        path = clean_path(item.get('path', ''), os.path.basename(relpath))
        if path is not None:
            answers[relpath] = {'action': 'move', 'path': path, 'reason': reason, 'copies': known}
    return answers


def _listed_dirs(dirs):
    """The lines that list the sorted tree's dirs ({relpath: a few of its files' names}) for Claude,
    the shallowest first"""
    return ["%s%s" % (dirpath or '. (the root)', " (e.g. %s)" % (', '.join(dirs[dirpath]),) if dirs[dirpath] else "")
            for dirpath in sorted(dirs, key=lambda relpath: (relpath.count('/'), relpath))[:MAX_DIRS_GIVEN]]


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
    result = _run_query(prompt, [], schema, max_turns=5, model=MODEL, system_prompt=DIR_SYSTEM_PROMPT)
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


def _cached_recommendation(entry, root_name):
    """A cache entry's recommendation in the sorted tree root_name, if it has one that says what to
    do (one that doesn't, from an older dirdelta, is asked for again)"""
    recommendation = entry.get('recommendations', {}).get(root_name)
    if recommendation and (recommendation.get('action') == 'remove' or recommendation.get('path')):
        return recommendation
    return None


def _numbered(result, files):
    """(number, item) of each of result's answers whose number is one of files'"""
    for item in result.get('files', []):
        number = item.get('number')
        if isinstance(number, int) and 1 <= number <= len(files):
            yield number, item


def _short(description):
    """description, as one line of at most MAX_DESCRIPTION_WORDS words"""
    words = description.split()
    return ' '.join(words[:MAX_DESCRIPTION_WORDS]).rstrip('.')


def clean_path(path, name):
    """A recommended path (of a file named name) as a relpath in the sorted tree (a leading '/' is
    its root too), with name's extension if it has none, or None if it isn't one: empty, or going up
    out of the tree"""
    parts = [part for part in path.strip().split('/') if part not in ('', '.')]
    if not parts or '..' in parts:
        return None
    extension = os.path.splitext(name)[1]
    if extension and not os.path.splitext(parts[-1])[1]:
        parts[-1] += extension
    return '/'.join(parts)


def ask(prompt, schema, system_prompt, readable_paths=()):
    """What Claude answers to prompt, by schema (a dict), going by what it's told, and what it reads of
    the local files at readable_paths (none: it reads nothing). Raises AIError if it can't be asked."""
    return _run_query(prompt, sorted({os.path.dirname(path) for path in readable_paths}), schema,
                      max_turns=2 * len(readable_paths) + 5, model=PLAN_MODEL, system_prompt=system_prompt)


def _run_query(prompt, readable_dirs, schema, max_turns, model, system_prompt=SYSTEM_PROMPT):
    """Ask Claude (model) prompt, letting it read only (with the Read tool) what's in
    readable_dirs (with none, it gets no tools), and return its answer by schema (a dict). Raises
    AIError if it can't."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query
    except ImportError:
        raise AIError("The Claude Agent SDK isn't installed (pip install claude-agent-sdk)")
    stderr_lines = collections.deque(maxlen=STDERR_LINES_KEPT)
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        # Only reading (if anything), and nothing asks the user: what isn't allowed is denied
        tools=['Read'] if readable_dirs else [], allowed_tools=['Read'] if readable_dirs else [],
        permission_mode='dontAsk',
        # Not the user's own Claude Code settings or CLAUDE.md
        setting_sources=[],
        cwd=readable_dirs[0] if readable_dirs else None, add_dirs=readable_dirs[1:],
        max_turns=max_turns,
        output_format={"type": "json_schema", "schema": schema},
        # A file Claude reads (an image, a PDF) comes back in a message bigger than the SDK's
        # default limit (1 MB), which fails the request
        max_buffer_size=MAX_MESSAGE_SIZE,
        # Claude Code's own messages: kept for the error, never on the screen (a picker may have it)
        stderr=stderr_lines.append)

    async def ask():
        result = None
        messages_ = query(prompt=prompt, options=options)
        try:
            async for message in messages_:
                if isinstance(message, ResultMessage):
                    result = message
        finally:
            # Claude Code's process closed while the event loop is still there (else its
            # transport's finalizer, later, finds it closed and says so on stderr)
            await messages_.aclose()
            gc.collect()
        return result

    _quiet_sdk_logging()
    try:
        result = asyncio.run(ask())
    except ClaudeSDKError as error:
        raise AIError("Couldn't ask Claude: %s" % (_why(error, stderr_lines),))
    except Exception as error:
        # The SDK raises after an error result too
        raise AIError("Claude failed: %s" % (_why(error, stderr_lines),))
    if result is None or result.subtype != 'success' or not result.structured_output:
        raise AIError("Claude gave no answer (%s)" % (getattr(result, 'subtype', 'no result'),))
    return result.structured_output


class _LastError(logging.Handler):
    """Keeps the SDK's last logged error (rather than letting Python print it on stderr)"""
    def __init__(self):
        super(_LastError, self).__init__(logging.ERROR)
        self.message = None

    def emit(self, record):
        self.message = record.getMessage()


_sdk_errors = _LastError()


def _quiet_sdk_logging():
    """The SDK's log, kept off the screen: it would be printed over a picker"""
    logger = logging.getLogger('claude_agent_sdk')
    if _sdk_errors not in logger.handlers:
        logger.addHandler(_sdk_errors)
        logger.propagate = False


def _why(error, stderr_lines):
    """What to say of error: it, and the SDK's last logged error, or Claude Code's last line"""
    said = str(error)
    extra = _sdk_errors.message or (stderr_lines[-1] if stderr_lines else None)
    _sdk_errors.message = None
    if extra and extra not in said:
        said += " (%s)" % (extra.strip()[:300],)
    return said


def carry(keys):
    """What the cache has of files by their paths, under their new ones too ({old key: new key}, see
    path_key()), after they were moved or copied, so it goes with them (by their hashes, it does)"""
    if not keys:
        return
    with _cache_lock:
        cache = _load_cache()
        for old_key, new_key in keys.items():
            if old_key in cache and new_key not in cache:
                cache[new_key] = dict(cache[old_key])
        _save_cache(cache)


def _load_cache():
    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        return cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        temp_path = CACHE_FILE + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(cache, f, indent=1)
        os.replace(temp_path, CACHE_FILE)
    except OSError:
        # Only a cache (and nothing's printed: a picker may have the screen): it's asked again
        pass
