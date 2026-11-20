"""Asking Claude to merge two versions of a text file (suggest_merge()): both sent in the prompt (no files
read), its answer the merged text and what it chose, which the user reviews in the merge window before
anything is saved"""
from dirdelta.claude.ai.config import AIError
from dirdelta.claude.ai.query import ask

# The most text sent (both versions), in characters: past it, it isn't asked
MAX_CHARS = 100 * 1000
SYSTEM_PROMPT = (
    "You merge two versions of one text file, kept in two copies of the user's files that drifted apart (each "
    "may have changes the other lacks). Keep every change that either version adds that the other doesn't "
    "contradict; where they contradict, keep the one that looks newer or more complete, and say so. Don't "
    "rewrite, reformat or reorder what both have alike. Answer with the whole merged file, and in a few short "
    "lines what you chose where they differed.")
SCHEMA = {"type": "object", "properties": {"merged": {"type": "string"}, "notes": {"type": "string"}},
          "required": ["merged", "notes"]}


def suggest_merge(name_a, lines_a, name_b, lines_b):
    """(the merged lines, what Claude says of them) of the two versions (named name_a and name_b). Raises
    AIError if it can't be asked, or the versions are too big to send"""
    text_a, text_b = '\n'.join(lines_a), '\n'.join(lines_b)
    if len(text_a) + len(text_b) > MAX_CHARS:
        raise AIError("They're too big to ask about (over %d characters together)" % (MAX_CHARS,))
    prompt = ("Merge these two versions of a file.\n\n"
              "=== The version in %s ===\n%s\n=== End of it ===\n\n"
              "=== The version in %s ===\n%s\n=== End of it ===\n" % (name_a, text_a, name_b, text_b))
    answer = ask(prompt, SCHEMA, SYSTEM_PROMPT)
    merged = answer.get('merged')
    if not isinstance(merged, str):
        raise AIError("Its answer had no merge")
    lines = merged.split('\n')
    # (A line end at its end isn't an empty last line: the file gets its own)
    if len(lines) > 1 and lines[-1] == '':
        lines.pop()
    return lines, str(answer.get('notes') or '')
