"""What a local replica's tests share: two temp dirs, src's and dst's"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers
from dirdelta.trees import entries
from dirdelta.trees import localdiskdirtree


class LocalDiskDirTreeTest(unittest.TestCase):
    def setUp(self):
        self.src_root = tempfile.mkdtemp(prefix='dirstuff-localdiskdirtree-src-')
        self.dst_root = tempfile.mkdtemp(prefix='dirstuff-localdiskdirtree-dst-')

    def tearDown(self):
        shutil.rmtree(self.src_root, ignore_errors=True)
        shutil.rmtree(self.dst_root, ignore_errors=True)

    def _copy_subdir_file(self):
        src = localdiskdirtree.LocalDiskDirTree(self.src_root, silent=True)
        src.add_file_by_relpath('subdir/file.txt')
        os.makedirs(os.path.join(self.src_root, 'subdir'))
        with open(os.path.join(self.src_root, 'subdir', 'file.txt'), 'w') as f:
            f.write('content')

        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)
        with mock.patch('dirdelta.ui.messages.print_line'):
            dst.copy_inner_entries_from_dirtree(src)
        return dst

    def _remove(self, relpaths, existing):
        """Remove relpaths from a src_root holding existing (relpaths: a trailing '/' an empty dir)"""
        for relpath in existing:
            path = os.path.join(self.src_root, relpath)
            if relpath.endswith('/'):
                os.makedirs(path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as f:
                    f.write(relpath)
        tree = localdiskdirtree.factory(self.src_root, silent=True)
        with mock.patch('dirdelta.ui.messages.print_line') as print_line:
            tree.remove_files([tree.get_node(relpath).data for relpath in relpaths])
        self.lines = [call.args[0] for call in print_line.call_args_list]
        return tree

    def _left(self):
        found = []
        for dirpath, dirnames, filenames in os.walk(self.src_root):
            for name in dirnames + filenames:
                found.append(os.path.relpath(os.path.join(dirpath, name), self.src_root))
        return sorted(found)

    def replace(self, content='new version', copy=None):
        """Copy src's a.txt (of content) over dst's (of 'old'), inside replacing(); copy, if given,
        is shutil.copy2's fake. Returns the tree, the trash and what listened."""
        helpers.make_files(self.src_root, ['a.txt'])
        helpers.make_files(self.dst_root, ['a.txt'])
        with open(os.path.join(self.src_root, 'a.txt'), 'w') as f:
            f.write(content)
        with open(os.path.join(self.dst_root, 'a.txt'), 'w') as f:
            f.write('old')
        trash = helpers.fake_trash(self)
        dst = localdiskdirtree.LocalDiskDirTree(self.dst_root, silent=True)
        dst.update_from_filesystem()
        listener = mock.Mock()
        dst.add_listener(listener)
        with mock.patch('dirdelta.util.dryrun.DRYRUN', False), mock.patch('dirdelta.ui.messages.print_line'), \
                mock.patch('dirdelta.trees.localdiskdirtree.copying.shutil.copy2', side_effect=copy or shutil.copy2), \
                dst.replacing():
            dst.copy_in([entries.FileEntry('a.txt', 'a.txt', os.path.join(self.src_root, 'a.txt'))])
        return dst, trash, listener

    def _scan(self, relpaths, **kwargs):
        for relpath in relpaths:
            path = os.path.join(self.src_root, relpath)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'w').close()
        return localdiskdirtree.factory(self.src_root, silent=True, **kwargs)


if __name__ == '__main__':
    unittest.main()
