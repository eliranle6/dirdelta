"""What Claude (MODEL) says of files: a short description of each (which reads them), and where in
a sorted tree it belongs (by their names, sizes and descriptions: it reads nothing), and of a dir of
them as a whole, where it goes (recommend_dir()), for sorting an inbox (see inbox.py). Through the Claude Agent SDK, which runs Claude Code, and so the
laptop's logged-in Claude (or ANTHROPIC_API_KEY, if set).

Claude reads the files itself, with its Read tool (text, images, PDFs), and with no other tool: it
gets only the paths it's given, in a dir of its own (cwd). What it says is cached (CACHE_FILE), by
the file's contents' hash once it's known (so what's said of a file goes with it when it moves, and
its copies share it), else by its path and size, so it's asked once per file. It sends the files' contents to Anthropic,

Its parts are in the modules here; the names the rest of dirdelta uses are here too (but
run_query() and CACHE_FILE: patch or set them in query and config)."""
from dirdelta.claude.ai.cache import cached, cached_dir, cached_dirs, carry, dir_key, hash_key, path_key  # noqa: F401
from dirdelta.claude.ai.config import (BATCH_SIZE, DIR_NAMES_GIVEN, DIR_SYSTEM_PROMPT, MAX_DESCRIPTION_WORDS,  # noqa: F401
                                       MAX_DIRS_GIVEN, MAX_MESSAGE_SIZE, MAX_READ_SIZE, MODEL, PLAN_MODEL,
                                       SYSTEM_PROMPT, AIError, Dir, File)
from dirdelta.claude.ai.dirs import recommend_dir, recommended_path  # noqa: F401
from dirdelta.claude.ai.prompts import clean_path  # noqa: F401
from dirdelta.claude.ai.files import describe, recommend  # noqa: F401
from dirdelta.claude.ai.query import ask  # noqa: F401
