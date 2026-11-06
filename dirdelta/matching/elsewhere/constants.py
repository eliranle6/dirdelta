"""How many candidates are shown and tried, how often, and what says one is surely it"""
import collections

from dirdelta.ui import picker


# How many of a name's files in the other replica a preview lists (a common name, like README.md,
# may have many): the likeliest to be the file
MAX_MATCHES = 10
# How often what's found so far is sent to the picker, with how far it's got, in seconds
SEND_INTERVAL = 0.1
# How many of a file's siblings are looked for in a match's dir: a few say enough
SIBLINGS_TRIED = 10
# The smallest file whose files of its size (with other names) are candidates too: smaller sizes
# are too common to say much
RENAMED_MIN_SIZE = 64 * 1024
# Modification times this close are the same (FAT keeps them to 2 seconds), in seconds
SAME_TIME = 2
# What says a candidate is surely the file, in its preview: highlighted, so it's seen when it comes
SURELY_MOVED = picker.highlighted("→ surely this file, moved")
SURELY_RENAMED = picker.highlighted("→ surely this file, renamed")

# The hashes that Drive gives (drivecache.HASH_FIELDS), the fastest to work out first
_HASH_PREFERENCE = ('sha1', 'sha256')

# A candidate in the other replica: its relpath, size, date taken and modification time (or None),
# how many of the file's siblings (of how many tried) are in its dir too, whether its contents are
# the same (None: not compared), and whether it has another name than the file's
Match = collections.namedtuple('Match', ['relpath', 'size', 'date_taken', 'modified', 'siblings_found',
                                         'siblings_tried', 'same_contents', 'is_other_name'])
