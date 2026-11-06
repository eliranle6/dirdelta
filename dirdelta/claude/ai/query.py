"""Running a query with the Claude Agent SDK: Read only, answering by a schema"""
import asyncio
import collections
import gc
import logging
import os

from dirdelta.claude.ai.config import AIError, MAX_MESSAGE_SIZE, PLAN_MODEL, STDERR_LINES_KEPT, SYSTEM_PROMPT


def ask(prompt, schema, system_prompt, readable_paths=()):
    """What Claude answers to prompt, by schema (a dict), going by what it's told, and what it reads of
    the local files at readable_paths (none: it reads nothing). Raises AIError if it can't be asked."""
    return run_query(prompt, sorted({os.path.dirname(path) for path in readable_paths}), schema,
                      max_turns=2 * len(readable_paths) + 5, model=PLAN_MODEL, system_prompt=system_prompt)


def run_query(prompt, readable_dirs, schema, max_turns, model, system_prompt=SYSTEM_PROMPT):
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
