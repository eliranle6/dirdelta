"""What Claude said of an inbox's files and dirs, and what it's being asked now (ClaudeKnowledge): the
sort's one place for them, asked by the rest of it through its methods, and changed by the Claude
worker (claude.py, claude_dirs.py, claude_files.py), from any thread, under its lock"""
import threading


class ClaudeKnowledge(object):
    """What Claude said, and what it's asked now, of the inbox's files (by relpath) and dirs"""
    def __init__(self):
        self.lock = threading.Lock()
        # What Claude said of the files: a description, and a recommendation (see ai.recommend())
        self.descriptions = {}
        self.recommendations = {}
        # The files being described, and being placed (asked where they go); why the ones that
        # couldn't be weren't; and the ones to ask about anew (whatever Claude's cache has)
        self.describing = set()
        self.placing = set()
        self.failed = {}
        self.anew = set()
        # Of the dirs as wholes: {dirpath: (its ai.dir_key() then, the recommendation)}; the ones
        # being asked about, and why the ones that couldn't be weren't; how many of each one's files
        # were copies of the sorted tree's then
        self.dir_recommendations = {}
        self.dir_asking = set()
        self.dir_failed = {}
        self.dir_copies = {}

    # Of a file

    def description(self, relpath):
        return self.descriptions.get(relpath)

    def recommendation(self, relpath):
        return self.recommendations.get(relpath)

    def failure(self, relpath):
        """Why Claude couldn't say what was asked of the file, or None"""
        return self.failed.get(relpath)

    def is_describing(self, relpath):
        return relpath in self.describing

    def is_placing(self, relpath):
        return relpath in self.placing

    def busy(self):
        """(How many files are being described, being placed, the dirs being asked about)"""
        return len(self.describing), len(self.placing), len(self.dir_asking)

    # Of a dir

    def dir_recommendation(self, dirpath):
        """What Claude said of the dir as a whole (see ai.recommend_dir()), or None"""
        found = self.dir_recommendations.get(dirpath)
        return found[1] if found is not None else None

    def is_asking_dir(self, dirpath):
        return dirpath in self.dir_asking

    def dir_failure(self, dirpath):
        return self.dir_failed.get(dirpath)

    def dir_copies_of(self, dirpath):
        return self.dir_copies.get(dirpath)

    def known_dirs(self):
        """The dirs Claude said something of, or is asked about now"""
        with self.lock:
            return set(self.dir_recommendations) | set(self.dir_asking)

    # What's kept

    def load(self, descriptions, recommendations, dir_keys, cached_dirs):
        """Take in what Claude's cache had: descriptions and recommendations ({relpath: ...}), and of
        the dirs ({dirpath: recommendation}, cached_dirs) by their keys now (dir_keys): the ones that
        changed since are dropped (asked about again, they're asked anew)"""
        self.descriptions.update(descriptions)
        self.recommendations.update(recommendations)
        with self.lock:
            for dirpath in list(self.dir_recommendations):
                if dir_keys.get(dirpath) != self.dir_recommendations[dirpath][0]:
                    del self.dir_recommendations[dirpath]
            for dirpath, recommendation in cached_dirs.items():
                self.dir_recommendations.setdefault(dirpath, (dir_keys[dirpath], recommendation))

    def kept_of(self):
        """The dicts of what's known by relpath, to rename a moved file's in (see Keys._carry())"""
        return self.descriptions, self.recommendations, self.failed
