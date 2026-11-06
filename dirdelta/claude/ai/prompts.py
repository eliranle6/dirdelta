"""The prompts about files, and reading Claude's answers to them"""
import os

from dirdelta.claude.ai import query
from dirdelta.claude.ai.config import (MAX_DESCRIPTION_WORDS, MAX_DIRS_GIVEN, MAX_READ_SIZE, MODEL,
                                       RECOMMEND_SYSTEM_PROMPT, answer_schema)


def _size_text(file):
    return "size %d bytes" % (file.size,) if file.size is not None else "size unknown"


def ask_for_descriptions(files):
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
    result = query.run_query(prompt, sorted(set(readable)), answer_schema(['description']),
                        max_turns=2 * len(files) + 5, model=MODEL)
    return {files[number - 1].relpath: {'description': shortened(item.get('description', ''))}
            for number, item in _numbered(result, files)}


def ask_for_recommendations(files, dirs, root_name, descriptions, copies):
    """{relpath: {'action', 'path', 'reason', 'copies'}} of what Claude says to do with files, by
    what's known of them"""
    lines = ["%d. %s (%s)%s%s" % (number, file.relpath, _size_text(file),
                                  ": " + descriptions[file.relpath] if file.relpath in descriptions else "",
                                  "; already in the sorted tree, with the same contents, at %s" %
                                  (', '.join(copies[file.relpath]),) if copies.get(file.relpath) else "")
             for number, file in enumerate(files, 1)]
    listed = listed_dirs(dirs)
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
    result = query.run_query(prompt, [], answer_schema(['action', 'path', 'reason'], {'action': ['move', 'remove']}),
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


def listed_dirs(dirs):
    """The lines that list the sorted tree's dirs ({relpath: a few of its files' names}) for Claude,
    the shallowest first"""
    return ["%s%s" % (dirpath or '. (the root)', " (e.g. %s)" % (', '.join(dirs[dirpath]),) if dirs[dirpath] else "")
            for dirpath in sorted(dirs, key=lambda relpath: (relpath.count('/'), relpath))[:MAX_DIRS_GIVEN]]


def _numbered(result, files):
    """(number, item) of each of result's answers whose number is one of files'"""
    for item in result.get('files', []):
        number = item.get('number')
        if isinstance(number, int) and 1 <= number <= len(files):
            yield number, item


def shortened(description):
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
