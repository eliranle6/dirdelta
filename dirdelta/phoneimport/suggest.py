"""Where an imported photo may go, by its date only (Suggester): where the replica's photos of that day
are, else of the nearest day before it (within MAX_DAYS_BEFORE). Measured on 2026-11-17 on 1,309 phone
photos already sorted (docs/improvement-ideas.md, 5.10): right first for 65% of them with their own day
not in the replica, and for 93% with it there."""
import collections
import datetime
import posixpath
import re

# A date in a name: 20260224 (PXL_20260224_..., IMG-20260224-WA..., 20260224_093727.jpg)
_DATE = re.compile(r'(?:^|[^0-9])(20[0-9]{2})([01][0-9])([0-3][0-9])(?:[^0-9]|$)')
MAX_DAYS_BEFORE = 30
MAX_SUGGESTED = 3


def date_of(name, mtime=None):
    """The date a file was taken, by its name, else by its modification time (seconds), or None"""
    match = _DATE.search(posixpath.basename(name))
    if match:
        try:
            return datetime.date(*map(int, match.groups()))
        except ValueError:
            pass
    return datetime.date.fromtimestamp(mtime) if mtime else None


class Suggester(object):
    """Suggestions from the dirs of relpaths (a replica's files) by their names' dates"""

    def __init__(self, relpaths):
        self._by_day = collections.defaultdict(collections.Counter)
        for relpath in relpaths:
            day = date_of(relpath)
            if day is not None:
                self._by_day[day][posixpath.dirname(relpath)] += 1

    def suggest(self, day):
        """[dir], the likeliest first, for a photo of day (a date), or [] for none"""
        if day is None:
            return []
        for back in range(MAX_DAYS_BEFORE + 1):
            found = self._by_day.get(day - datetime.timedelta(days=back))
            if found:
                return [dirpath for dirpath, _ in found.most_common(MAX_SUGGESTED)]
        return []
