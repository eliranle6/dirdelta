import unittest

from dirdelta import archive_screen
from dirdelta import contextmenu
from dirdelta import filescreen
from dirdelta import hashes_screen
from dirdelta import picker
import helpers


class _Screen(filescreen.FilesScreen):
    def __init__(self, answer=None):
        self.answer = answer
        self.explored = []
        self.dashboards = 0
        self.keys = []

    def _context_menu(self, selected, files):
        return self.answer

    def _menu_key(self, answer, selected, files):
        self.keys.append(answer)
        return answer == 'own'

    def _explore(self, relpath, files):
        self.explored.append(relpath)

    def _dashboard(self):
        self.dashboards += 1


def _chosen(key, selected='d', files=()):
    return picker.Picked(key, selected, list(files))


class SharedKeyTest(unittest.TestCase):
    FILES = ['d/a', 'd/b', 'e']

    def test_exploring_and_the_dashboard_keep_the_picks(self):
        screen = _Screen()
        self.assertEqual(screen._shared_key(_chosen(archive_screen.KEY, 'z', ['e']), self.FILES), (None, ['e']))
        self.assertEqual(screen.explored, ['z'])
        self.assertEqual(screen._shared_key(_chosen(hashes_screen.KEY, 'z', ['e']), self.FILES), (None, ['e']))
        self.assertEqual(screen.dashboards, 1)

    def test_the_context_menu(self):
        self.assertEqual(_Screen(None)._shared_key(_chosen(contextmenu.KEY), self.FILES), (None, []))
        self.assertEqual(_Screen(contextmenu.PICK)._shared_key(_chosen(contextmenu.KEY), self.FILES), (None, ['d/a', 'd/b']))
        self.assertEqual(_Screen('own')._shared_key(_chosen(contextmenu.KEY), self.FILES), (None, []))
        chosen, _ = _Screen(contextmenu.WHAT_TO_DO)._shared_key(_chosen(contextmenu.KEY), self.FILES)
        self.assertEqual((chosen.key, chosen.files), ('', ['d/a', 'd/b']))
        chosen, _ = _Screen('k')._shared_key(_chosen(contextmenu.KEY), self.FILES)
        self.assertEqual(chosen.key, 'k')
        # Its key may be a shared one
        screen = _Screen(hashes_screen.KEY)
        self.assertEqual(screen._shared_key(_chosen(contextmenu.KEY), self.FILES), (None, []))
        self.assertEqual(screen.dashboards, 1)

    def test_with_files_picked_its_enters_menu(self):
        screen = _Screen('not asked')
        chosen, _ = screen._shared_key(_chosen(contextmenu.KEY, files=['e']), self.FILES)
        self.assertEqual((chosen.key, chosen.files), ('', ['e']))


class ConfirmTest(unittest.TestCase):
    def test_yes(self):
        with helpers.answering_option_picker([filescreen.CONFIRM_YES, filescreen.CONFIRM_NO]) as pick:
            self.assertTrue(_Screen()._said_yes(['Sure?'], None))
            self.assertFalse(_Screen()._said_yes(['Sure?'], None))
        self.assertEqual(pick.call_args.args[0][0], filescreen.CONFIRM_NO)

    def test_sure_says_where_they_go(self):
        for is_drive, to_trash, said in ((True, False, "(to Drive's trash)"), (False, True, "(to the trash)"),
                                         (False, False, ", for good")):
            with helpers.answering_option_picker([filescreen.CONFIRM_SURE]) as pick:
                self.assertTrue(_Screen()._is_sure(2, '/x', is_drive, to_trash, None))
            self.assertIn(said, pick.call_args.kwargs['header'])
            self.assertIn('2 files', pick.call_args.kwargs['header'])


class ShownTest(unittest.TestCase):
    def test_the_selection_or_the_closest_dir_still_shown(self):
        missing = ['a/b/1', 'a/c/2']
        self.assertEqual(filescreen.shown_near('a/b/1', missing), 'a/b/1')
        self.assertEqual(filescreen.shown_near('a/b', missing), 'a/b')
        self.assertEqual(filescreen.shown_near('a/d/3', missing), 'a')
        self.assertEqual(filescreen.shown_near('z', missing), '')

    def test_a_gone_one_is_followed_by_the_closest_file_left(self):
        before = ['a/1', 'a/2', 'a/3', 'b/4', 'c/5']
        shown = filescreen.shown_near
        # The next one
        self.assertEqual(shown('a/2', ['a/1', 'a/3', 'b/4'], before), 'a/3')
        # The one before, in its dir, rather than the next, in another
        self.assertEqual(shown('a/3', ['a/1', 'b/4'], before), 'a/1')
        # The last: the one before
        self.assertEqual(shown('c/5', ['a/1', 'b/4'], before), 'b/4')
        # A dir that's gone: from its first file's place
        self.assertEqual(shown('b', ['a/1', 'c/5'], before), 'c/5')
        # None left near: the closest dir
        self.assertEqual(shown('a/2', [], before), '')


if __name__ == '__main__':
    unittest.main()
