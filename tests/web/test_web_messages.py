"""dirdelta's messages in the browser (web/messages.py, web/session.py)"""
import time
import unittest

from dirdelta.ui import messages
from dirdelta.web import api
from web_support import WebTest


class MessagesTest(WebTest):
    def test_a_message_waits_for_continue(self):
        screen = self.start(lambda: messages.show('Copied', ['3 files copied']))
        self.wait_until(lambda: screen.waiting)
        self.assertEqual([('3 files copied', None)], screen.lines)
        screen.answer()
        self.result()

    def test_an_actions_progress_shows_as_it_goes_and_a_progress_line_is_replaced(self):
        def action():
            with messages.progress_screen('Copying'):
                messages.print_line('Copying a')
                messages.print_progress('1 of 2')
                messages.print_progress('2 of 2')
                messages.print_line('Done', 'green')
        screen = self.start(action)
        self.wait_until(lambda: screen.waiting)
        self.assertEqual([('Copying a', None), ('2 of 2', None), ('Done', 'green')], screen.lines)
        self.assertEqual('Done', screen.status)
        screen.answer()
        self.result()

    def test_stop_stops_the_action_as_ctrl_c_does(self):
        def action():
            with messages.progress_screen('Copying'):
                while True:
                    time.sleep(0.01)
            return messages.is_stopped()
        self.session.start(lambda: None)
        screen = self.start(action)
        # (The flow's thread is the one stopped: here, the call's)
        self.session._flow = self._thread
        self.session.stop()
        self.wait_until(lambda: screen.waiting)
        self.assertEqual('Stopped', screen.status)
        screen.answer()
        self.assertTrue(self.result())

    def test_a_question_returns_the_answer(self):
        screen = self.start(lambda: messages.ask('Rename', ['x.jpg'], 'New name: ', 'x.jpg'))
        self.wait_until(lambda: screen.asking)
        self.assertEqual({'prompt': 'New name: ', 'default': 'x.jpg'}, screen.asking)
        screen.answer(' y.jpg ')
        self.assertEqual('y.jpg', self.result())

    def test_a_pages_first_ask_is_answered_at_once_and_later_ones_wait_for_a_change(self):
        state = api.routes(self.session, lambda: None)[('GET', '/api/state')]
        started = time.monotonic()
        found = state({'since': '0'}, {})
        self.assertLess(time.monotonic() - started, 1)
        self.assertIsNone(found['screen'])
        screen = self.start(lambda: messages.show('Done', ['x']))
        self.assertEqual(screen.id, state({'since': str(found['version'])}, {})['screen']['id'])
        screen.answer()
        self.result()

    def test_lines_printed_between_screens_are_kept_for_the_page(self):
        messages.print_line('Scanning...')
        self.assertEqual([('Scanning...', None)], self.session.log)


if __name__ == '__main__':
    unittest.main()
