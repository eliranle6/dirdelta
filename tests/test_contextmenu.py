import unittest
from unittest import mock

from dirdelta.ui import contextmenu
from dirdelta.ui import picker
import helpers

ENTRIES = [contextmenu.Entry('a', 'Ask', 'asked'), contextmenu.Entry(None, 'Do', 'done')]


class ChooseTest(unittest.TestCase):
    def choose(self, answer, **kwargs):
        def pick_option(options, **picked):
            self.options, self.shown = helpers.labels_of(options), helpers.shown_of(options)
            return None if answer is None else helpers.answer_of(options, answer)
        with mock.patch('dirdelta.ui.picker.pick_option', side_effect=pick_option):
            return contextmenu.choose(ENTRIES, 'What?', **kwargs)

    def test_the_results(self):
        self.assertEqual(self.choose('Ask'), 'asked')
        self.assertEqual(self.choose('Do'), 'done')
        self.assertIsNone(self.choose(contextmenu.NOTHING))
        self.assertIsNone(self.choose(None))

    def test_each_is_shown_after_its_key(self):
        self.choose(None)
        self.assertTrue(picker.unstyled(self.shown['Ask']).startswith('[a]'))
        self.assertEqual(picker.unstyled(self.shown['Do']).strip(), 'Do')

    def test_the_pickers_keys_cant_be_chosen(self):
        self.choose(None, side='there')
        skipped = [shown.text for shown in self.shown.values() if isinstance(shown, picker.Skipped)]
        self.assertTrue(any('search' in line for line in skipped))
        self.assertTrue(any('there' in line for line in skipped))

    def test_without_a_side_tree_its_key_isnt_shown(self):
        self.choose(None)
        self.assertFalse(any(contextmenu.SIDE_KEY_NAME in option for option in self.options))


class UnderTest(unittest.TestCase):
    def test_under(self):
        files = ['a.txt', 'd/b.txt', 'd/e/c.txt', 'dd.txt']
        self.assertEqual(contextmenu.under(files, ''), files)
        self.assertEqual(contextmenu.under(files, 'd'), ['d/b.txt', 'd/e/c.txt'])
        self.assertEqual(contextmenu.under(files, 'a.txt'), ['a.txt'])


if __name__ == '__main__':
    unittest.main()
