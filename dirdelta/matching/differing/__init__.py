"""The files that two replicas both have at the same path, but not alike: of other sizes, or of the
same size with other contents by hashes known without reading the files (the hash cache's for a
local one, Drive's for Drive's; see docs/plans.md, plan A). The same size with a hash unknown on
either side isn't counted, so there are no false alarms, but those are said (Changes' uncompared),
to be compared on request (sync/comparing.py), as found then. Modification times say only which one
is newer, never whether they differ (copies made before 2026-10-29 have their copy's time).

They're shown in the same pickers as the files only one has (interactive_dir_sync), with a tag: in
each way's, as either side can win, and Copy replaces the other side's version (to the trash).

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.matching.differing.finding import (ALGORITHM, BY_CONTENTS, BY_SIZE, SAME_TIME, Change,  # noqa: F401
                                                 Changes, find, flipped, newer)
from dirdelta.matching.differing.showing import (MARK, NEWER_MARK, NEWER_STYLE, OLDER_MARK, OLDER_STYLE,  # noqa: F401
                                                 STYLE, format_time, mark, preview_lines, style, styled_tag, tag)
