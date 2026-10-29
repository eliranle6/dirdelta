"""What Claude says of files: a short description of each, and where in a sorted tree it belongs (for
sorting an inbox, see inbox.py). Through the Claude Agent SDK, which runs Claude Code, and so the
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

# The model, unless DIRDELTA_AI_MODEL says otherwise
MODEL = 'claude-opus-5-5'
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


class AIError(Exception):
    pass


# A file to ask about: its relpath (in the inbox), its path on the local disk to read (None: not
# read), and its size (or None)
File = collections.namedtuple('File', ['relpath', 'local_path', 'size'])


def _description_schema(with_destination):
    item = {
        "type": "object",
        "properties": {
            "number": {"type": "integer"},
            "description": {"type": "string"},
        },
        "required": ["number", "description"],
    }
    if with_destination:
        item["properties"]["destination"] = {"type": "string"}
        item["properties"]["reason"] = {"type": "string"}
        item["required"] += ["destination", "reason"]
    return {"type": "object", "properties": {"files": {"type": "array", "items": item}},
            "required": ["files"]}


def describe(files, cache_key, progress=None):
    """{relpath: description} of files (File), a sentence of at most MAX_DESCRIPTION_WORDS words
    each, from the cache or Claude, in batches of BATCH_SIZE, calling progress(done, count) after
    each. cache_key(file) is the file's key in the cache. Raises AIError if Claude can't be asked."""
    return {relpath: answer['description']
            for relpath, answer in _ask(files, cache_key, None, progress).items()}


def recommend(files, cache_key, dirs, root_name, progress=None):
    """{relpath: {'description', 'destination', 'reason'}} of files (File): where in the sorted
    tree (root_name, whose dirs are dirs: relpaths) each belongs, as a dir relative to its root
    (an existing one, or a new one where none fits), from the cache or Claude, as describe() does"""
    return _ask(files, cache_key, (tuple(dirs), root_name), progress)


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


def _ask(files, cache_key, sorted_tree, progress):
    cache = _load_cache()
    found = {}
    needed = []
    for file in files:
        cached = cache.get(cache_key(file), {})
        answer = (cached.get('recommendations', {}).get(sorted_tree[1]) if sorted_tree else
                  cached.get('description') and {'description': cached['description']})
        if answer:
            found[file.relpath] = answer
        else:
            needed.append(file)
    for start in range(0, len(needed), BATCH_SIZE):
        if progress is not None:
            progress(start, len(needed))
        batch = needed[start:start + BATCH_SIZE]
        answers = _ask_claude(batch, sorted_tree)
        # Kept at once, so what was asked isn't asked again if it's stopped
        cache = _load_cache()
        for file in batch:
            answer = answers.get(file.relpath)
            if answer is None:
                continue
            found[file.relpath] = answer
            entry = cache.setdefault(cache_key(file), {})
            entry['description'] = answer['description']
            if sorted_tree:
                entry.setdefault('recommendations', {})[sorted_tree[1]] = answer
        _save_cache(cache)
    if progress is not None and needed:
        progress(len(needed), len(needed))
    return found


def _ask_claude(files, sorted_tree):
    """{relpath: answer} of what Claude says of files (see _ask())"""
    lines = []
    for number, file in enumerate(files, 1):
        is_read = file.local_path is not None and (file.size or 0) <= MAX_READ_SIZE
        lines.append("%d. %s (%s%s)%s" % (
            number, file.relpath, "size %d bytes" % (file.size,) if file.size is not None else "size unknown",
            "" if is_read else ", don't read it", (": read it at %s" % (file.local_path,)) if is_read else ""))
    task = ("For each file, a description: one short sentence, at most %d words, saying what it is "
            "(e.g. 'a cat asleep on a red sofa', 'a 2023 tax form for Eliran')." % (MAX_DESCRIPTION_WORDS,))
    if sorted_tree:
        dirs, root_name = sorted_tree
        listed = sorted(dirs, key=lambda relpath: (relpath.count('/'), relpath))[:MAX_DIRS_GIVEN]
        task += ("\n\nAnd where each belongs in the sorted tree %s, whose dirs are listed below (relative "
                 "to its root): its destination, an existing dir from the list where one fits, else a "
                 "new dir to make (a path relative to the root, in the tree's style), and the reason, "
                 "in a few words. Files that go together (e.g. one trip's photos) should go to one "
                 "dir.\n\nThe sorted tree's dirs:\n%s" % (root_name, '\n'.join(listed) or "(none yet)"))
    prompt = "%s\n\nThe files:\n%s" % (task, '\n'.join(lines))
    readable = [os.path.dirname(file.local_path) for file in files if file.local_path is not None]
    result = _run_query(prompt, sorted(set(readable)), _description_schema(sorted_tree is not None),
                        max_turns=2 * len(files) + 5)
    answers = {}
    for item in result.get('files', []):
        number = item.get('number')
        if isinstance(number, int) and 1 <= number <= len(files):
            answer = {'description': _short(item.get('description', ''))}
            if sorted_tree:
                destination = _clean_destination(item.get('destination', ''))
                if destination is None:
                    continue
                answer['destination'] = destination
                answer['reason'] = item.get('reason', '').strip()
            answers[files[number - 1].relpath] = answer
    return answers


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


def _run_query(prompt, readable_dirs, schema, max_turns):
    """Ask Claude prompt (see SYSTEM_PROMPT), letting it read only (with the Read tool) what's in
    readable_dirs, and return its answer by schema (a dict). Raises AIError if it can't."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query
    except ImportError:
        raise AIError("The Claude Agent SDK isn't installed (pip install claude-agent-sdk)")
    options = ClaudeAgentOptions(
        model=os.environ.get(MODEL_ENV_VAR) or MODEL,
        system_prompt=SYSTEM_PROMPT,
        # Only reading, and nothing asks the user: what isn't allowed is denied
        tools=['Read'], allowed_tools=['Read'], permission_mode='dontAsk',
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
