"""The sorted tree's other replicas (e.g. cloud/eliran's /mnt/win/.../eliran): the ones the user picks
as a sort starts (choice.py; none unless picked) get copies of the files it moves or copies into the
sorted tree, where they lack them (copying.py). Only what's added is copied: removals and renames in
the sorted tree aren't, and a file a replica has already is never overwritten."""
from dirdelta.inbox.followers.choice import cant_follow, choose  # noqa: F401
from dirdelta.inbox.followers.copying import Followers  # noqa: F401
