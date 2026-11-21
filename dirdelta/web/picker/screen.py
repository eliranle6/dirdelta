"""A picker shown in the browser (PickerScreen): treepicker's command, done by the web page. The
browser selects, picks, sets states, presses the picker's keys and ends it; this says so on the pipes
as treepicker would, and works out what treepicker would print (see docs/treepicker-integration.md)."""
import collections
import os
import threading

from dirdelta.ui import images
from dirdelta.ui.picker import places
from dirdelta.web.picker import keynames
from dirdelta.web.picker import pipes
from dirdelta.web.picker.items import Items

# treepicker's exit codes: picked, quit
PICKED, QUIT = 0, 1
# What a Picked's key is when Enter in the side tree ended it (picker.SIDE_KEY)
SIDE_KEY = '\x1d'
# A grid's pictures: how many a screen keeps (see picture()), and how many are made at once (each a file
# read and decoded: a grid asks for many at once)
MAX_JPEGS_KEPT = 300
_MAKING = threading.BoundedSemaphore(3)


class PickerScreen(object):
    kind = 'picker'

    def __init__(self, screen_id, spec, records, bump, pictures=None):
        self.id = screen_id
        # Its files' pictures' function (pick_files()'s images), for the grid of a folder's photos (picture())
        self.pictures = pictures
        self._jpegs = collections.OrderedDict()
        self._jpegs_lock = threading.Lock()
        self.spec = spec
        self._bump = bump
        self.items = Items(spec, records, bump)
        self.previews, self.images, self.default_preview = {}, {}, []
        # {path: the version its preview (or picture) last changed at}
        self.preview_versions = {}
        self.picked = set(pipes.read_file(spec.picked_file))
        self.side_items = [record.split(' ', 1) for record in pipes.read_file(spec.side_file)]
        self.side_selected = spec.side_start
        self.selected = spec.select if spec.select is not None else self._first()
        # (Where the flow is, the menus' breadcrumbs: a tree's page shows them too, as the menus' do)
        self.crumbs = places.trail()
        self.version = bump()
        self._writers = {option: pipes.Writer(spec.fds[option]) for option in ('--selection', '--notify-fd')
                         if option in spec.fds}
        self._readers = []
        self._result = None
        self._done = threading.Event()

    def _has(self, path):
        if path in self.items.info:
            return True
        if self.spec.is_list:
            return False
        if path in ('', '.'):
            return True
        if self.spec.source not in (None, '-'):
            # A dir's picker: what's in the dir (its items are listed as they're opened)
            return '..' not in path.split('/') and os.path.lexists(os.path.join(self.spec.source, path))
        return False

    def _first(self):
        if self.spec.is_list:
            return next((path for path in self.items.order if not self.items.info[path].get('s')), '')
        return '.'

    def run(self):
        """Serve the pipes until the browser ends the picker: returns (exit code, what's printed)"""
        handlers = {'--updates': self.items.update, '--preview': self._preview,
                    '--side-select': self._side_select}
        self._readers = [pipes.read_records(self.spec.fds[option], handler)
                         for option, handler in handlers.items() if option in self.spec.fds]
        self._write_selection()
        self._done.wait()
        for writer in self._writers.values():
            writer.close()
        return self._result

    def cancel(self):
        """End it as if the user quit (e.g. the daemon is stopping)"""
        self._finish(QUIT, [])

    # What the browser does

    def select(self, path):
        """Select the node at path ('' or '.' the root): only one the picker has, as in treepicker"""
        if not self._has(path):
            return
        self.selected = path
        self._write_selection()
        self.version = self._bump()

    def pick(self, paths, is_picked):
        """Pick the files at paths (a dir: its files), or unpick them"""
        files = self.items.files_at(paths)
        if is_picked:
            self.picked.update(files)
        else:
            self.picked.difference_update(files)
        self.version = self._bump()

    def press(self, key):
        """A key of the picker's: one that ends it (--expect, --expect-twice), or one it notifies
        (--notify)"""
        if key in self.spec.notify:
            if '--notify-fd' in self._writers:
                self._writers['--notify-fd'].write(key, self.selected or '.', *self._picked_in_order(), '')
            return
        if key in self.spec.expect or key in self.spec.expect_twice:
            self._finish(PICKED, [key] + self._after_key())

    def enter(self, side=False, side_key=''):
        """Enter: pick (a menu's option, a tree's node, or with -m what's picked), or in the side tree,
        end it there"""
        if side:
            printed = [SIDE_KEY, self.selected or '.', self.side_selected or '.']
            self._finish(PICKED, printed + ([side_key] if self.spec.side_expect else []) + self._picks())
            return
        if self.items.info.get(self.selected, {}).get('d'):
            # Greyed out (or not an option): Enter does nothing there
            return
        if self.spec.is_multi and not self.spec.states and not self.picked:
            if '--enter-picks-selection' not in self.spec.flags:
                return
            self.picked.update(self.items.files_at([self.selected]))
        self._finish(PICKED, ([''] if self.spec.prints_key else []) + self._after_key())

    def quit(self):
        self._finish(QUIT, [])

    def _after_key(self):
        """What's printed after the key: the selected node (--print-selection), then the picks"""
        if '--print-selection' in self.spec.flags:
            return [self.selected or '.'] + self._picks()
        return self._picks() if self.spec.is_multi else [self.selected or '.']

    def _picks(self):
        if self.spec.states:
            first = self.spec.states[0][0]
            return ['%s\t%s' % (info['st'], path) for path, info in
                    ((path, self.items.info[path]) for path in self.items.order) if info.get('st', first) != first]
        return self._picked_in_order() if self.spec.is_multi else []

    def _picked_in_order(self):
        return [path for path in self.items.order if path in self.picked] or sorted(self.picked)

    def _finish(self, code, printed):
        if self._done.is_set():
            return
        self._result = (code, b''.join(item.encode('utf-8', 'surrogateescape') + b'\0' for item in printed))
        self._done.set()
        self.version = self._bump()

    def _write_selection(self):
        if '--selection' in self._writers:
            self._writers['--selection'].write(self.selected or '.')

    # What's sent to it

    def _preview(self, record):
        if record.startswith('\x03'):
            path, _, image = record[1:].partition('\t')
            self.images[path] = image
        else:
            path, *lines = record.split('\t')
            if path == '':
                self.default_preview = lines
            else:
                self.previews[path] = lines
        self.preview_versions[path] = self._bump()

    def _side_select(self, path):
        self.side_selected = '' if path == '.' else path
        self.version = self._bump()

    # What the browser is told

    def meta(self):
        spec = self.spec
        is_dir = spec.source not in (None, '-')
        return {'kind': self.kind, 'id': self.id, 'root': spec.source if is_dir and spec.root == '.' else spec.root,
                'crumbs': self.crumbs, 'header': spec.header, 'footer': spec.footer,
                'labels': spec.labels, 'mode': 'list' if spec.is_list else 'dir' if is_dir else 'tree',
                'multi': spec.is_multi, 'dirsOnly': '--dirs-only' in spec.flags,
                'keys': keynames.buttons(spec), 'hints': spec.key_hints, 'nonePickedHints': spec.none_picked_key_hints,
                'help': spec.help_lines, 'enterPicksSelection': '--enter-picks-selection' in spec.flags,
                'states': [{'name': name, 'mark': mark, 'color': color, 'key': key} for name, mark, color, key in spec.states],
                'stateMarks': [[name, group, mark, color] for (name, group), (mark, color) in spec.state_marks.items()],
                'tabs': [{'title': title, 'groups': groups} for title, groups in spec.tabs],
                'side': self._side_meta(), 'previewBelow': '--preview-below' in spec.flags,
                'hasPreviews': '--preview' in spec.fds, 'hasPictures': self.pictures is not None}

    def _side_meta(self):
        if self.spec.side_file is None:
            return None
        return {'root': self.spec.side_root, 'items': [{'t': kind, 'p': path} for kind, path in self.side_items],
                'enterPicks': bool(self.spec.side_key), 'keys': keynames.side_buttons(self.spec)}

    def state(self, since):
        """What changed since the version since: the items, the status, the selection, the picks"""
        return {'changes': self.items.changed_since(since), 'status': self.items.status,
                'selected': self.selected, 'sideSelected': self.side_selected,
                'picked': self._picked_in_order() if self.spec.is_multi else [],
                'previewVersion': self.preview_versions.get(self.selected or '.', 0),
                'done': self._done.is_set()}

    def picture(self, path, size):
        """The JPEG of the file at path, at most size pixels a side, or None if it has none; the last ones
        made kept (MAX_JPEGS_KEPT), as a grid asks for them again as it's scrolled"""
        key = (path, size)
        with self._jpegs_lock:
            if key in self._jpegs:
                self._jpegs.move_to_end(key)
                return self._jpegs[key]
        if self.pictures is None:
            return None
        with _MAKING:
            data = images.to_jpeg(self.pictures(path, size, size))
        with self._jpegs_lock:
            self._jpegs[key] = data
            while len(self._jpegs) > MAX_JPEGS_KEPT:
                self._jpegs.popitem(last=False)
        return data

    def preview(self, path):
        path = path or '.'
        return {'path': path, 'lines': self.previews.get(path, self.default_preview),
                'image': self.images.get(path) or None}
