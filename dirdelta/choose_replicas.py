"""The menu that chooses what to sync, when dirdelta is run without paths: a replica for each of its
two slots (a local dir under /, or a Drive one), or a favorite or recent pair at once; or an inbox
to sort into a sorted tree (inbox.py), a new one or a recent one. Each kind is a section of its own,
under a heading."""
import collections
import datetime
import os

from dirdelta import drivecache
from dirdelta import dryrun
from dirdelta import messages
from dirdelta import mounts
from dirdelta import paths
from dirdelta import picker
from dirdelta import replicalog
from dirdelta import syncstate
from dirdelta import utils

NOT_CHOSEN = '<none: press Enter to choose one>'
LOCAL = 'Local disk'
CLOUD = 'Google Drive'
QUIT = 'Quit'
KNOWN_LIST = '  Replicas dashboard: every known replica (last updates, files, hashes)'
SORT = '  New sort: choose an inbox, and the sorted tree its files go to (with Claude\'s help)'
# The menu's sections' headings (shown in grey, and skipped when moving: they can't be picked)
SYNC_SECTION = '\u2500\u2500 Sync two replicas \u2500\u2500'
RECENT_SYNCS_SECTION = '\u2500\u2500 Recent syncs \u2500\u2500'
SORT_SECTION = '\u2500\u2500 Sort an inbox into a sorted tree \u2500\u2500'
RECENT_SORTS_SECTION = '\u2500\u2500 Recent inbox sorts \u2500\u2500'
REPLICAS_SECTION = '\u2500\u2500 Replicas \u2500\u2500'
# What a replica the user knows is offered as, when choosing a sorted tree
KNOWN = 'Known replica: '

# What run() returns for an inbox to sort (rather than a pair to sync)
Sort = collections.namedtuple('Sort', ['inbox', 'root'])

# Where a local replica is browsed from, and a cloud one (all of Drive)
LOCAL_ROOT = '/'
CLOUD_ROOT = 'cloud'


def blank_line(number):
    """A blank line of the menu, between its sections (skipped, as the headings are: see picker.Skipped):
    spaces, number of them and one, so each is an option of its own"""
    return ' ' * (number + 1)


def run(replicas):
    """Let the user choose two replicas, from replicas' (a Replicas) favorites and history or each
    on its own. Returns their paths (a, b); or a Sort, if they chose an inbox to sort (a new one, or
    one of replicas' sorts); or None if the user quit."""
    chosen = [None, None]
    while True:
        slots = {slot_label(name, path): index for index, (name, path) in enumerate(zip('AB', chosen))}
        favorites = {favorite_label(*pair, known=replicas): pair for pair in replicas.favorites}
        recent = {recent_label(*pair, known=replicas): pair for pair in replicas.recent()}
        # How fresh each is, in colors (see styled_pair())
        pair_texts = {label: styled_pair(label, pair[0], pair[1], replicas)
                      for label, pair in list(favorites.items()) + list(recent.items())}
        pairs = dict(favorites, **recent)
        sorts = {sort_label(*sort): Sort(*sort) for sort in replicas.sorts}
        sections = [(SYNC_SECTION, list(slots) + list(favorites)), (RECENT_SYNCS_SECTION, list(recent)),
                    (SORT_SECTION, [SORT]), (RECENT_SORTS_SECTION, list(sorts)),
                    (REPLICAS_SECTION, [KNOWN_LIST] if replicas.known else [])]
        options = []
        for heading, section in sections:
            if section:
                options += ([blank_line(len(options))] if options else []) + [heading] + section
        # Quit apart from the last section too
        options.append(blank_line(len(options)))
        headings = {option: picker.Skipped(option)
                    for option in [heading for heading, _ in sections] + [option for option in options if not option.strip()]}
        headings.update(pair_texts)
        option = picker.pick_option(options + [QUIT],
                                    header='Choose the two replicas to sync, or an inbox to sort',
                                    shown_as=lambda: headings, selected=options[1], help_lines=help_lines())
        if option in (None, QUIT):
            return None
        if option == KNOWN_LIST:
            # Imported here: hashes_screen uses this module's known_lines()
            from dirdelta import hashes_screen
            hashes_screen.dashboard(known=replicas, other_paths=known_paths(replicas))
            continue
        if option == SORT:
            sort = _choose_sort(replicas)
            if sort is not None:
                return sort
            continue
        if option in sorts:
            if _are_there(sorts[option]):
                return sorts[option]
            continue
        if option in pairs:
            if _are_there(pairs[option]):
                return pairs[option]
            continue
        index = slots[option]
        path = _choose_replica('Replica %s' % ('AB'[index],))
        if path is None:
            continue
        chosen[index] = path
        if None not in chosen:
            if chosen[0] == chosen[1]:
                messages.show("Same replica",
                              ["Both replicas are %s: choose another one." % (path,)], dryrun.label())
                chosen[index] = None
                continue
            return tuple(chosen)


def _choose_sort(replicas):
    """Let the user choose an inbox and the sorted tree to sort it into: one of the replicas they
    know (replicas', a Replicas), or any dir. Returns a Sort, or None."""
    inbox = _choose_replica('the inbox (the dir of files to sort)')
    if inbox is None:
        return None
    root = _choose_replica('the sorted tree (where its files go)',
                           [path for path in known_replicas(replicas) if path != inbox])
    if root is None:
        return None
    return Sort(inbox, root)


def _are_there(replica_paths):
    """Whether the replicas at replica_paths (a sort's or a pair's) can be used: their volumes are
    mounted (see _mounted()), and their local dirs there, which may be gone since (a cloud one is
    checked when its Drive file list is read); if not, it's said why"""
    if not _mounted(replica_paths):
        return False
    missing = [path for path in replica_paths if not paths.is_cloud_path(path) and not os.path.isdir(path)]
    if missing:
        messages.show("No such directory", ["%s is not a directory (anymore?)." % (path,) for path in missing],
                      dryrun.label(), 'red')
        return False
    return True


def _mounted(replica_paths):
    """Whether the replicas' volumes are mounted (the user is asked to mount one that isn't, see
    mounts.py); if not, the user goes back to the menu"""
    return all(mounts.ensure_mounted(path) for path in replica_paths)


def known_replicas(replicas):
    """The replicas' paths the user knows, once each: the favorites', the recent pairs', then the
    sorted trees of the recent sorts"""
    found = [path for pair in replicas.favorites + replicas.history for path in pair]
    found += [root for _, root in replicas.sorts]
    return list(dict.fromkeys(found))



def slot_label(name, path):
    return '  Replica %s: %s' % (name, path or NOT_CHOSEN)


def favorite_label(path_a, path_b, known=None):
    return '  Favorite: %s' % (pair_label(path_a, path_b, known),)


def recent_label(path_a, path_b, known=None):
    return '  %s' % (pair_label(path_a, path_b, known),)


def sort_label(inbox, root):
    return '  %s -> %s' % (inbox, root)


def pair_label(path_a, path_b, known=None):
    """The pair's label: each path, with when it was last updated (its log's last entry, as known
    (a Replicas), if it is)"""
    return '%s%s <-> %s%s' % (path_a, _updated(known, path_a), path_b, _updated(known, path_b))


def _updated(known, path):
    """' (updated DD.MM.YYYY)' of the replica at path, by its log's last entry, as known has it;
    '' if it doesn't"""
    info = known.info_at(path) if known is not None else None
    date = ((info or {}).get('last_entry') or {}).get('date')
    return ' (updated %s)' % (_date(date),) if date else ''


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


def help_lines():
    """The start menu's ? help: what the marks before a pair and its paths are"""
    return (["Marks before a pair: whether it's in sync, as far as dirdelta knows"] +
            ["  " + line for line in syncstate.help_lines()] + path_marks_help())


def path_marks_help():
    """The ? help's lines of the marks before a replica's path"""
    return (["Marks before a path:",
             "  %s when the replica was last synced: green today, yellow this week, red before, grey never" % (SYNCED_MARK,),
             "  %s (a Google Drive one) when Drive's file list was last read into the cache: the same colors" % (CACHE_MARK,),
             "(updated DD.MM.YYYY) after a path: the last entry of its %s" % (replicalog.LOG_NAME,)])


def styled_pair(label, path_a, path_b, known):
    """A pair's menu label (label, ending with pair_label()'s) as it's shown: after a mark of whether
    it's in sync (see syncstate.py), each path after a mark in the color of when it was last synced
    (grey: never, as far as known), and a Drive one's after one in the color of when Drive's file
    list was read"""
    def marks(path):
        info = known.info_at(path) if known is not None else None
        parts = [(SYNCED_MARK + " ", freshness((info or {}).get('seen')) or 'grey')]
        if paths.is_cloud_path(path):
            parts.append((CACHE_MARK + " ", freshness(cache_time(path)) or 'grey'))
        return parts
    pair = pair_label(path_a, path_b, known)
    head = label[:len(label) - len(pair)] if label.endswith(pair) else label
    a_text = '%s%s' % (path_a, _updated(known, path_a))
    sync_mark, sync_color = syncstate.mark(syncstate.of(known, path_a, path_b))
    return picker.styled([(head, None), (sync_mark + " ", sync_color)] + marks(path_a) + [(a_text + " <-> ", None)] + marks(path_b) +
                         [(pair[len(a_text) + 5:], None)])


def known_paths(replicas):
    """The paths of the replicas known (replicas', a Replicas), each at the path it was last seen at,
    the latest updated first"""
    def last_date(info):
        return ((info.get('last_entry') or {}).get('date') or '', info.get('seen') or '')
    return [(info.get('paths') or [identity])[-1]
            for identity, info in sorted(replicas.known.items(), key=lambda item: last_date(item[1]), reverse=True)]


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


def _choose_replica(name, known=()):
    """Let the user choose a local dir or a Drive one, or one of known (paths) at once. Returns its
    path, or None if they quit."""
    options = {KNOWN + path: path for path in known}
    where = picker.pick_option(list(options) + [LOCAL, CLOUD], header='Where is %s?' % (name,),
                               title='Choose %s' % (name,))
    if where in options:
        return options[where]
    header = 'Choose %s' % (name,)
    key_hints = [('Enter', 'choose the selected dir')]
    if where == LOCAL:
        return picker.pick_under_dir(LOCAL_ROOT, dirs_only=True, lazy=True, header=header, key_hints=key_hints)
    if where == CLOUD:
        try:
            tree = utils.create_dirtree_from_arg(CLOUD_ROOT)
        except drivecache.DriveCacheError as error:
            messages.show("Cannot read Google Drive's file list", str(error).splitlines(),
                          dryrun.label(), 'red')
            return None
        if tree is None:
            return None
        picked = picker.pick_from_tree(tree, header=header, dirs_only=True, key_hints=key_hints)
        # A cloud tree's paths are Drive's (/mein/music), not cloud paths (cloud/mein/music)
        return paths.join_cloud(picked[0].relpath) if picked else None
    return None
