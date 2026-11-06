"""What the picker's tests share: a fake treepicker (a script that logs what it's given and answers as told)"""
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from dirdelta.trees import dirtree


# Stands in for treepicker: records its arguments and stdin into $FAKE_PICKER_LOG, and with
# --updates (--preview), what it read from that fd until it read $FAKE_PICKER_WAIT_FOR
# ($FAKE_PICKER_PREVIEW_WAIT_FOR), after writing $FAKE_PICKER_SELECTIONS ('|'-separated) to
# --selection's fd; then prints
# $FAKE_PICKER_OUTPUT (items separated by '|', each printed '\0'-terminated, empty ones too) and exits with
# $FAKE_PICKER_EXIT_CODE
FAKE_PICKER = '''#!%s
import json, os, sys
stdin = sys.stdin.buffer.read().decode('utf-8', 'surrogateescape')
updates = b''
def read_until(option, wait_for):
    read = b''
    if option in sys.argv:
        fd = int(sys.argv[sys.argv.index(option) + 1])
        while wait_for.encode() not in read:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            read += chunk
    return read.decode()
if '--selection' in sys.argv:
    fd = int(sys.argv[sys.argv.index('--selection') + 1])
    for path in os.environ.get('FAKE_PICKER_SELECTIONS', '').split('|'):
        os.write(fd, path.encode() + b'\\0')
if '--notify-fd' in sys.argv:
    fd = int(sys.argv[sys.argv.index('--notify-fd') + 1])
    # Records ('|'-separated items, ';'-separated records), each ended by an empty item
    for record in os.environ.get('FAKE_PICKER_NOTIFY', '').split(';'):
        os.write(fd, b''.join(item.encode() + b'\\0' for item in record.split('|')) + b'\\0')
updates = read_until('--updates', os.environ.get('FAKE_PICKER_WAIT_FOR', ''))
preview = read_until('--preview', os.environ.get('FAKE_PICKER_PREVIEW_WAIT_FOR', ''))
with open(os.environ['FAKE_PICKER_LOG'], 'w') as log:
    json.dump({'args': sys.argv[1:], 'stdin': stdin, 'updates': updates, 'preview': preview}, log)
output = os.environ.get('FAKE_PICKER_OUTPUT', '')
sys.stdout.buffer.write(b''.join(item.encode('utf-8', 'surrogateescape') + b'\\0'
                                 for item in (output.split('|') if output else [])))
sys.exit(int(os.environ.get('FAKE_PICKER_EXIT_CODE', '0')))
''' % (sys.executable,)


class PickerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.program = os.path.join(self.tmpdir, 'treepicker')
        with open(self.program, 'w') as f:
            f.write(FAKE_PICKER)
        os.chmod(self.program, os.stat(self.program).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.tmpdir, 'log.json')
        self.env = mock.patch.dict(os.environ, {'FAKE_PICKER_LOG': self.log})
        self.env.start()
        self.find = mock.patch('dirdelta.util.programs.find', return_value=self.program)
        self.find.start()
        settings_file = mock.patch('dirdelta.known.settings.SETTINGS_FILE', os.path.join(self.tmpdir, 'settings.json'))
        settings_file.start()
        self.addCleanup(settings_file.stop)

    def tearDown(self):
        self.find.stop()
        self.env.stop()
        shutil.rmtree(self.tmpdir)

    def answer(self, output='', exit_code=0):
        os.environ['FAKE_PICKER_OUTPUT'] = output
        os.environ['FAKE_PICKER_EXIT_CODE'] = str(exit_code)

    def log_entry(self, key):
        """What the fake treepicker logged as key (e.g. 'preview': what it read from that fd)"""
        with open(self.log) as f:
            return json.load(f)[key]

    def call(self, with_label=False):
        """The arguments and the stdin items the fake treepicker got (the arguments without the
        dry run label every call has, unless with_label)"""
        with open(self.log) as f:
            log = json.load(f)
        args = log['args']
        if not with_label:
            index = args.index('--label')
            args = args[:index] + args[index + 4:]
            # Nor what q does, which every call says too (see test_q_quits_or_goes_back)
            index = args.index('--key')
            if args[index + 1] == 'q':
                args = args[:index] + args[index + 3:]
        return args, [item for item in log['stdin'].split('\0') if item]

    def make_tree(self):
        tree = dirtree.DirTree('/some/root')
        for relpath in ['b/2.txt', 'a/1.txt', 'b/sub/3.txt', 'c.txt']:
            tree.add_file_by_relpath(relpath)
        return tree

    def wait_for(self, condition):
        for _ in range(500):
            if condition():
                return
            time.sleep(0.01)
        self.fail("it didn't happen")


if __name__ == '__main__':
    unittest.main()
