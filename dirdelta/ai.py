"""What Claude says of files: a short description of each (DESCRIBE_MODEL, which reads them), and
where in a sorted tree it belongs (RECOMMEND_MODEL, by their names, sizes and descriptions: it reads
nothing), for sorting an inbox (see inbox.py). Through the Claude Agent SDK, which runs Claude Code, and so the
laptop's logged-in Claude (or ANTHROPIC_API_KEY, if set).

Claude reads the files itself, with its Read tool (text, images, PDFs), and with no other tool: it
gets only the paths it's given, in a dir of its own (cwd). What it says is cached (CACHE_FILE), by
the file's path and size, so it's asked once per file. It sends the files' contents to Anthropic,
so it's only asked when the user chooses to."""
import asyncio
import collections
import json
import os

from dirdelta import messages

# The models: a description is a short sentence, so the fastest and cheapest does; a recommendation
# is a choice among the sorted tree's dirs, which takes more judgment. Each is set by its env var, or
# both by MODEL_ENV_VAR.
DESCRIBE_MODEL = 'claude-haiku-5-5'
RECOMMEND_MODEL = 'claude-sonnet-5-5'
DESCRIBE_MODEL_ENV_VAR = 'DIRDELTA_AI_DESCRIBE_MODEL'
RECOMMEND_MODEL_ENV_VAR = 'DIRDELTA_AI_RECOMMEND_MODEL'
MODEL_ENV_VAR = 'DIRDELTA_AI_MODEL'
CACHE_FILE = os.path.expanduser('~/.cache/dirdelta/ai.json')
# How many files one request is about
BATCH_SIZE = 10
# Bigger files aren't read (Claude says what it can from their names)
MAX_READ_SIZE = 20 * 1024 * 1024
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


class AIError(Exception):
    pass


# A file to ask about: its relpath (in the inbox), its path on the local disk to read (None: not
# read), and its size (or None)
File = collections.namedtuple('File', ['relpath', 'local_path', 'size'])


def _schema(fields):
    """The answers' schema: a list of {number, the fields (strings)}"""
    item = {"type": "object",
            "properties": dict({"number": {"type": "integer"}}, **{field: {"type": "string"} for field in fields}),
            "required": ["number"] + list(fields)}
    return {"type": "object", "properties": {"files": {"type": "array", "items": item}}, "required": ["files"]}


def describe(files, cache_key, progress=None):
    """{relpath: description} of files (File), a sentence of at most MAX_DESCRIPTION_WORDS words
    each, from the cache or Claude (DESCRIBE_MODEL, which reads them), in batches of BATCH_SIZE,
    calling progress(done, count) after each. cache_key(file) is the file's key in the cache.
    Raises AIError if Claude can't be asked."""
    def is_cached(entry):
        return entry.get('description') and {'description': entry['description']}

    def keep(entry, answer):
        entry['description'] = answer['description']
    found = _ask(files, cache_key, is_cached, keep, _ask_for_descriptions, progress)
    return {relpath: answer['description'] for relpath, answer in found.items()}


def recommend(files, cache_key, dirs, root_name, descriptions, progress=None):
    """{relpath: {'destination', 'reason'}} of files (File): where in the sorted tree (root_name,
    whose dirs are dirs: relpaths) each belongs, as a dir relative to its root (an existing one, or
    a new one where none fits), from the cache or Claude (RECOMMEND_MODEL). It goes by the files'
    names, sizes and descriptions ({relpath: description}, e.g. describe()'s), so it reads nothing."""
    def is_cached(entry):
        return entry.get('recommendations', {}).get(root_name)

    def keep(entry, answer):
        entry.setdefault('recommendations', {})[root_name] = answer
    return _ask(files, cache_key, is_cached, keep,
                lambda batch: _ask_for_recommendations(batch, dirs, root_name, descriptions), progress)


def cached(files, cache_key, root_name):
    """What the cache has of files (File), without asking Claude: ({relpath: description},
    {relpath: recommendation in the sorted tree root_name, as recommend() gives it})"""
    cache = _load_cache()
    descriptions, recommendations = {}, {}
    for file in files:
        entry = cache.get(cache_key(file), {})
        if entry.get('description'):
            descriptions[file.relpath] = entry['description']
        recommendation = entry.get('recommendations', {}).get(root_name)
        if recommendation:
            recommendations[file.relpath] = recommendation
    return descriptions, recommendations


def _ask(files, cache_key, is_cached, keep, ask, progress):
    """{relpath: answer} of files: is_cached(entry) of each one's cache entry, or else ask(batch)
    of the others (BATCH_SIZE at a time) for {relpath: answer}, each kept by keep(entry, answer)"""
    cache = _load_cache()
    found = {}
    needed = []
    for file in files:
        answer = is_cached(cache.get(cache_key(file), {}))
        if answer:
            found[file.relpath] = answer
        else:
            needed.append(file)
    for start in range(0, len(needed), BATCH_SIZE):
        if progress is not None:
            progress(start, len(needed))
        batch = needed[start:start + BATCH_SIZE]
        answers = ask(batch)
        # Kept at once, so what was asked isn't asked again if it's stopped
        cache = _load_cache()
        for file in batch:
            answer = answers.get(file.relpath)
            if answer is not None:
                found[file.relpath] = answer
                keep(cache.setdefault(cache_key(file), {}), answer)
        _save_cache(cache)
    if progress is not None and needed:
        progress(len(needed), len(needed))
    return found


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
                        max_turns=2 * len(files) + 5, model=_model(False))
    return {files[number - 1].relpath: {'description': _short(item.get('description', ''))}
            for number, item in _numbered(result, files)}


def _ask_for_recommendations(files, dirs, root_name, descriptions):
    """{relpath: {'destination', 'reason'}} of where Claude says files go, by what's known of them"""
    lines = ["%d. %s (%s)%s" % (number, file.relpath, _size_text(file),
                                ": " + descriptions[file.relpath] if file.relpath in descriptions else "")
             for number, file in enumerate(files, 1)]
    listed = sorted(dirs, key=lambda relpath: (relpath.count('/'), relpath))[:MAX_DIRS_GIVEN]
    prompt = ("Where each of these files belongs in the sorted tree %s, whose dirs are listed below "
              "(relative to its root): its destination, an existing dir from the list where one fits, "
              "else a new dir to make (a path relative to the root, in the tree's style), and the "
              "reason, in a few words. Files that go together (e.g. one trip's photos) should go to "
              "one dir.\n\nThe files (name, size, and what each is):\n%s\n\nThe sorted tree's dirs:\n%s" %
              (root_name, '\n'.join(lines), '\n'.join(listed) or "(none yet)"))
    result = _run_query(prompt, [], _schema(['destination', 'reason']), max_turns=5, model=_model(True),
                        system_prompt=RECOMMEND_SYSTEM_PROMPT)
    answers = {}
    for number, item in _numbered(result, files):
        destination = _clean_destination(item.get('destination', ''))
        if destination is not None:
            answers[files[number - 1].relpath] = {'destination': destination,
                                                  'reason': item.get('reason', '').strip()}
    return answers


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


def _clean_destination(destination):
    """A recommended dir as a relpath in the sorted tree ('' its root; a leading '/' is its root
    too), or None if it goes up out of it"""
    parts = [part for part in destination.strip().split('/') if part not in ('', '.')]
    if '..' in parts:
        return None
    return '/'.join(parts)


def _model(is_recommending):
    """The model to ask for a recommendation, or else for a description"""
    if is_recommending:
        return os.environ.get(RECOMMEND_MODEL_ENV_VAR) or os.environ.get(MODEL_ENV_VAR) or RECOMMEND_MODEL
    return os.environ.get(DESCRIBE_MODEL_ENV_VAR) or os.environ.get(MODEL_ENV_VAR) or DESCRIBE_MODEL


def _run_query(prompt, readable_dirs, schema, max_turns, model, system_prompt=SYSTEM_PROMPT):
    """Ask Claude (model) prompt, letting it read only (with the Read tool) what's in
    readable_dirs (with none, it gets no tools), and return its answer by schema (a dict). Raises
    AIError if it can't."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query
    except ImportError:
        raise AIError("The Claude Agent SDK isn't installed (pip install claude-agent-sdk)")
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
        output_format={"type": "json_schema", "schema": schema})

    async def ask():
        result = None
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result = message
        return result

    try:
        result = asyncio.run(ask())
    except ClaudeSDKError as error:
        raise AIError("Couldn't ask Claude: %s" % (error,))
    except Exception as error:
        # The SDK raises after an error result too
        raise AIError("Claude failed: %s" % (error,))
    if result is None or result.subtype != 'success' or not result.structured_output:
        raise AIError("Claude gave no answer (%s)" % (getattr(result, 'subtype', 'no result'),))
    return result.structured_output


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
    except OSError as error:
        messages.print_line("Couldn't keep what Claude said in %s: %s" % (CACHE_FILE, error), "yellow")
