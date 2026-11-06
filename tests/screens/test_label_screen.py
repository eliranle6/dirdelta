import unittest
from unittest import mock

import helpers
from dirdelta.screens import label_screen
from dirdelta.known import mounts
from dirdelta.known import replicanames
from dirdelta.known import replicas

MOUNT = mounts.Mount('/mnt/disk', '/dev/sdb1', 'ext4', 'rw', '', 'AAAA-1234', None)


class RunTest(unittest.TestCase):
    def setUp(self):
        for name, patcher in (('mount', mock.patch('dirdelta.known.mounts.current_mount', return_value=MOUNT)),
                              ('save', mock.patch('dirdelta.known.replicas.save'))):
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        replicanames.forget()
        self.addCleanup(replicanames.forget)
        self.known = replicas.Replicas()

    def run_with(self, chosen, typed='laptop', paths=('/mnt/disk/a',)):
        """run(), each menu choosing the option starting with the next of chosen, and then going back"""
        chosen = list(chosen)
        self.menus = []
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=lambda options, **_: self._answer(options, chosen)), \
                mock.patch('dirdelta.ui.messages.ask', return_value=typed) as self.ask:
            label_screen.run(self.known, list(paths))

    def _answer(self, options, chosen):
        self.menus.append(options)
        if not chosen:
            return None
        start = chosen.pop(0)
        return helpers.answer_of(options, start)

    def test_a_label_is_kept(self):
        self.run_with(['Label'])
        self.assertEqual(self.known.labels, {'uuid:AAAA-1234:/a': 'laptop'})
        self.save.assert_called_once_with(self.known)

    def test_it_starts_from_the_current_one_and_can_be_removed(self):
        self.known.set_label('uuid:AAAA-1234:/a', 'old')
        self.run_with(['Label'])
        self.assertEqual(self.ask.call_args.args[3], 'old')
        self.run_with(['Remove'])
        self.assertEqual(self.known.labels, {})

    def test_typing_nothing_keeps_it(self):
        self.known.set_label('uuid:AAAA-1234:/a', 'old')
        self.run_with(['Label'], typed=None)
        self.assertEqual(self.known.labels, {'uuid:AAAA-1234:/a': 'old'})
        self.save.assert_not_called()

    def test_two_replicas_on_one_disk_are_labeled_each_on_its_own(self):
        self.run_with(['Label /mnt/disk/b'], paths=('/mnt/disk/a', '/mnt/disk/b'))
        self.assertEqual(len([label for label in helpers.labels_of(self.menus[0]) if label.startswith('Label')]), 2)
        self.assertEqual(self.known.labels, {'uuid:AAAA-1234:/b': 'laptop'})


if __name__ == '__main__':
    unittest.main()
