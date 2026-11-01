"""What's known of a replica, as the screens say it: when it was last synced and changed, its
log's last entry, the marks of how fresh what's known is (see freshness()), and the cache's time of
a Drive one's file list. For the start menu (choose_replicas.py), the sync's menu and the replicas
dashboard (hashes_screen.py), so neither imports the other for it."""
import datetime
import os

from dirdelta import drivecache
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicalog


def _date(iso_date):
    """'YYYY-MM-DD' as the logs write dates, DD.MM.YYYY"""
    return datetime.date.fromisoformat(iso_date).strftime(replicalog.DATE_FORMAT)


def _time(iso_time):
    """'YYYY-MM-DD HH:MM' as 'DD.MM.YYYY HH:MM'"""
    date, _, hours = iso_time.partition(' ')
    return ('%s %s' % (_date(date), hours)).strip()


# The colors of how fresh what's known is (when a replica was last synced, Drive's file list last
# read): today, this week, before
FRESH, RECENT, OLD = 'green', 'yellow', 'red'
# What's before a pair's path in the menu: when it was last synced, in its freshness's color, and
# for a Drive one, when Drive's file list was last read
SYNCED_MARK = '\u25cf'
CACHE_MARK = '\u2601'


def freshness(when):
    """The color of how long ago when (a datetime, or 'YYYY-MM-DD HH:MM' as replicas.json keeps
    times) was: FRESH today, RECENT this week, OLD before; None if it's not known"""
    if not when:
        return None
    if isinstance(when, str):
        try:
            when = datetime.datetime.strptime(when[:16], '%Y-%m-%d %H:%M')
        except ValueError:
            return None
    today = datetime.date.today()
    if when.date() >= today:
        return FRESH
    return RECENT if when.date() > today - datetime.timedelta(days=7) else OLD


def cache_time(path=None):
    """When Drive's file list was last read (its cache last written), or None; with path (a cloud
    path), when the cache's list of that folder was last updated, if that's known
    (drivecache.updated(): read from Drive, changed by dirdelta, or its copy in it used)"""
    if path is not None:
        updated = drivecache.updated(paths.path_in_cloud(path))
        if updated is not None:
            return datetime.datetime.fromtimestamp(updated)
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(drivecache.FILE_LIST_CACHE))
    except OSError:
        return None


def path_marks_help():
    """The ? help's lines of the marks before a replica's path"""
    return (["Marks before a path:",
             "  %s when the replica was last synced: green today, yellow this week, red before, grey never" % (SYNCED_MARK,),
             "  %s (a Google Drive one) when Drive's file list was last read into the cache: the same colors" % (CACHE_MARK,),
             "(updated DD.MM.YYYY) after a path: the last entry of its %s" % (replicalog.LOG_NAME,)])


def known_lines(info, styled=False):
    """The lines of what's known of a replica (its info, see replicas.Replicas.known): its log's
    last entry, and when it was last synced and changed (with styled, when it was synced in its
    freshness's color, see freshness())"""
    lines = []
    entry = info.get('last_entry')
    if entry:
        text = (entry.get('text') or '').splitlines() or ['']
        lines.append('  Last update: %s%s%s' % (_date(entry['date']) if entry.get('date') else '(no date)',
                                                ' - ' + text[0] if text[0] else '',
                                                ' (+%d more line%s)' % (len(text) - 1, 's' if len(text) > 2 else '')
                                                if len(text) > 1 else ''))
    else:
        lines.append('  Last update: (no %s)' % (replicalog.LOG_NAME,))
    synced = ['synced %s' % (_time(info['seen']),)] if info.get('seen') else []
    synced += ['changed by dirdelta %s' % (_time(info['changed']),)] if info.get('changed') else []
    if synced:
        line = '  ' + '; '.join(synced).capitalize()
        if styled and info.get('seen'):
            first = '  Synced %s' % (_time(info['seen']),)
            line = picker.styled([('  ', None), (SYNCED_MARK + ' ', freshness(info['seen'])),
                                  (first[2:], freshness(info['seen'])),
                                  (line[len(first):], None)])
        lines.append(line)
    return lines
