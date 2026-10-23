import unittest
from unittest import mock

from dirdelta import menu


def _picker_choosing(label):
    picker_class = mock.Mock()
    picker_class.return_value.pick_one.return_value = label
    return mock.patch('treepicker.optionpicker.OptionPickerByMenuTraverse', picker_class)


class RunMenuTest(unittest.TestCase):
    def test_calls_only_the_chosen_handler_and_returns_its_label(self):
        first, second = mock.Mock(), mock.Mock()
        with _picker_choosing('second') as picker_class:
            label = menu.run_menu([('first', first), ('second', second)])

        picker_class.assert_called_once_with(['first', 'second'])
        self.assertEqual(label, 'second')
        second.assert_called_once_with()
        first.assert_not_called()

    def test_label_without_handler_is_returned_without_calling_anything(self):
        handler = mock.Mock()
        with _picker_choosing('quit'):
            label = menu.run_menu([('quit', None), ('other', handler)])

        self.assertEqual(label, 'quit')
        handler.assert_not_called()

    def test_quitting_the_menu_returns_none(self):
        handler = mock.Mock()
        with _picker_choosing(None):
            label = menu.run_menu([('only', handler)])

        self.assertIsNone(label)
        handler.assert_not_called()


if __name__ == '__main__':
    unittest.main()
