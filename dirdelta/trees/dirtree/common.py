"""What a tree's parts share: the error of a stopped hash, a batch's verb, a path's place"""
from dirdelta.trees import paths
from dirdelta.util import dryrun


class HashStopped(Exception):
    """Raised by content_hash() (and elsewhere's comparing) when its should_stop() says to"""


def batch_verb(verb):
    """A batch's verb before each file, e.g. 'Copying', or in a dry run 'Dry run, not copying'"""
    return "Dry run, not %s" % (verb,) if dryrun.DRYRUN else verb.capitalize()


# One answer for all (see paths.is_at_or_under()): the root has all
is_at_or_under = paths.is_at_or_under
