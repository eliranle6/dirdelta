"""A web picker's items: what it was given (a menu's options, a tree's paths, or a dir to list), and
how each is shown now, as --updates says (see docs/treepicker-integration.md), each change numbered
(a version) so a browser can ask for what changed since it last asked"""
import os
import threading

from dirdelta.web.picker import pipes


class Items(object):
    """The items of a picker of spec (a Spec), from stdin's records (or None, for a dir's); bump() is
    called with each change"""

    def __init__(self, spec, records, bump):
        self._spec = spec
        self._bump = bump
        self.lock = threading.RLock()
        # Paths in the order shown, each dir before what's in it; {path: its info}
        self.order, self.info = [], {}
        # {path: the version it last changed at}
        self.versions = {}
        self.status = ''
        self.status_version = 0
        if spec.is_list:
            for line in records or []:
                self._add(line, 'o')
        elif records is not None:
            for record in records:
                kind, _, path = record.partition(' ')
                self._add_with_dirs(path, kind)
        self._add_states()

    def _add(self, path, kind):
        if path not in self.info:
            self.order.append(path)
            self.info[path] = {'p': path, 't': kind}

    def _add_with_dirs(self, path, kind):
        """path, after its dirs not there yet (a picker of files is given only those)"""
        parts = path.split('/')
        for i in range(1, len(parts)):
            self._add('/'.join(parts[:i]), 'd')
        self._add(path, kind)

    def _add_states(self):
        """Each file's allowed states, first state and group (--states's lines: ALLOWED, STATE, GROUP, PATH)"""
        for line in pipes.read_file(self._spec.states_file):
            allowed, state, group, path = line.split('\t', 3)
            if path in self.info:
                self.info[path].update(a=[name for name in allowed.split(',') if name], g=group,
                                       st=state or self._spec.states[0][0])

    def update(self, record):
        """Show an item as --updates' record says: ITEM, TEXT, and maybe disabled, skipped, color=NAME or
        state=NAME (an empty ITEM: the status)"""
        fields = record.split('\t')
        path, text, extras = fields[0], fields[1] if len(fields) > 1 else '', fields[2:]
        with self.lock:
            if path == '':
                self.status = text
                self.status_version = self._bump()
                return
            info = self.info.get(path)
            if info is None:
                return
            info.update(x=text, d='disabled' in extras or 'skipped' in extras, s='skipped' in extras, c=None)
            for extra in extras:
                if extra.startswith('color='):
                    info['c'] = extra[len('color='):]
                elif extra.startswith('state=') and self._spec.states:
                    info['st'] = extra[len('state='):]
            self.versions[path] = self._bump()

    def set_state(self, paths, name):
        """Put the files at paths (a dir: its files) in the state name, where they allow it"""
        with self.lock:
            for path in self.files_at(paths):
                info = self.info[path]
                if not info.get('a') or name in info['a']:
                    info['st'] = name
                    self.versions[path] = self._bump()

    def files_at(self, paths):
        """The files at paths, a dir's being the files under it, in the order shown"""
        wanted = set(paths)
        prefixes = tuple(path + '/' for path in paths if path not in ('', '.'))
        everything = '' in wanted or '.' in wanted
        return [path for path in self.order if self.info[path]['t'] == 'f' and
                (everything or path in wanted or path.startswith(prefixes))]

    def changed_since(self, version):
        with self.lock:
            return [self.info[path] for path, at in self.versions.items() if at > version]

    def listed(self):
        with self.lock:
            return [dict(self.info[path]) for path in self.order]

    def children(self, relpath):
        """The items in the dir at relpath ('' the root) of a picker that lists a dir: its dirs, then its
        files (with --dirs-only, none), by name, but the ones left out (--exclude)"""
        spec = self._spec
        dirpath = os.path.join(spec.source, relpath)
        depth = 0 if relpath in ('', '.') else relpath.count('/') + 1
        if spec.max_depth is not None and depth >= spec.max_depth:
            return []
        found = []
        try:
            with os.scandir(dirpath) as listing:
                for entry in listing:
                    child = entry.name if relpath in ('', '.') else relpath + '/' + entry.name
                    is_dir = entry.is_dir(follow_symlinks=False)
                    if child in spec.excluded or (not is_dir and '--dirs-only' in spec.flags):
                        continue
                    found.append({'p': child, 't': 'd' if is_dir else 'f'})
        except OSError:
            return []
        return sorted(found, key=lambda item: (item['t'] != 'd', item['p'].lower()))
