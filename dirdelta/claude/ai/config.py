"""The models, the cache's file, the limits and the system prompts; and what's asked about"""
import collections
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
