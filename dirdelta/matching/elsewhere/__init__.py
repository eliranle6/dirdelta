"""Where the other replica has a file that a replica lacks, moved or renamed, shown beside the file
picker (picker.pick_files()'s previews), and offered for Rename: the diff is by path only, so a file
moved (or a dir renamed) in one replica is missing from the other, and the user can tell such a file
from one that's really missing before acting on it.

The candidates are the other replica's files of the same name, and, for a big file, those of its
size with another name (renamed); and when the other replica is Drive's, which knows its files'
hashes, the files of the same contents whatever their name and size (looked up by the file's hash,
when its contents are compared). A candidate is likelier the more of these it has: the same
contents (compared for the selected file, with the same-sized candidates only: check_contents(), or
for all the picked ones before a Rename: check_all()), the same name, the same size, the same date
taken (photos), the file's siblings (the other missing files of its dir, a few of them tried) in its
dir too, as when a dir was moved or renamed, the same modification time; and then the closer its
size is. One with the same contents is surely it, and the others are dropped; one with other
contents never is, and one with another name is dropped then.

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.matching.elsewhere.candidates import known_same, matches_of_size  # noqa: F401
from dirdelta.matching.elsewhere.constants import (MAX_MATCHES, RENAMED_MIN_SIZE, SAME_TIME,  # noqa: F401
                                                   SURELY_MOVED, SURELY_RENAMED, Match)
from dirdelta.matching.elsewhere.contents import check_all, check_contents, same_contents, to_check  # noqa: F401
from dirdelta.matching.elsewhere.index import Index  # noqa: F401
from dirdelta.matching.elsewhere.previews import find_previews  # noqa: F401
from dirdelta.matching.elsewhere.sure import may_be_elsewhere, sure_match, sure_matches  # noqa: F401
