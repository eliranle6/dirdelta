"""What's shown beside the files: previews, as the selection moves, and pictures"""
import os
import threading
import time
import unittest
from unittest import mock

from dirdelta.ui import picker
from picker_support import PickerTest


class PreviewsTest(PickerTest):
    """Previews and pictures"""

    def test_pick_files_sends_previews_as_they_come(self):
        os.environ['FAKE_PICKER_PREVIEW_WAIT_FOR'] = 'done'
        self.answer('a/1.txt')

        def previews(send):
            send({'a/1.txt': ['In b:', '  x\ty']})
            send({'': ['root']}, default=['done'])
        picker.pick_files('/r', ['a/1.txt'], previews=previews)

        # Each line after a tab, the root as '.', the default's path empty, and a tab in a line
        # shown as '?'
        self.assertEqual(self.log_entry('preview').split('\0'),
                         ['a/1.txt\tIn b:\t  x?y', '.\troot', '\tdone', ''])

    def test_previews_stop_once_the_picker_is_gone(self):
        self.answer('a/1.txt')
        stopped = []

        def previews(send):
            try:
                while True:
                    send(default=['still going'])
            except picker.PickerClosed:
                stopped.append(True)
                raise
        picker.pick_files('/r', ['a/1.txt'], previews=previews)
        # pick_files() waited for it
        self.assertEqual(stopped, [True])

    def test_on_selection_follows_the_selection_and_sends_previews(self):
        os.environ['FAKE_PICKER_SELECTIONS'] = 'a/1.txt|.|a'
        os.environ['FAKE_PICKER_PREVIEW_WAIT_FOR'] = 'done'
        self.answer('a/1.txt')
        seen = []

        def on_selection(selection, send):
            while len(seen) < 3:
                relpath = selection.wait_next()
                # Moves between waits may come as one
                seen.append(relpath)
                if relpath == 'a':
                    break
            self.assertTrue(selection.is_at('a'))
            send({'a': ['done']})
            selection.wait_next()
        picker.pick_files('/r', ['a/1.txt'], on_selection=on_selection)
        self.assertEqual(seen[-1], 'a')
        self.assertEqual(self.log_entry('preview'), 'a\tdone\0')

    def test_images_of_where_the_selection_stays_are_sent_once(self):
        # The selection moves through a/1.txt to a/2.jpg, and stays there
        os.environ['FAKE_PICKER_SELECTIONS'] = 'a/1.txt|a/2.jpg'
        os.environ['FAKE_PICKER_PREVIEW_WAIT_FOR'] = '0000ff'
        self.answer('a/2.jpg')
        asked = []

        def images(relpath, max_width, max_height):
            asked.append(relpath)
            self.assertGreater(max_width, 0)
            self.assertGreater(max_height, 0)
            return '1 1 0000ff' if relpath.endswith('.jpg') else None
        picker.pick_files('/r', ['a/1.txt', 'a/2.jpg'], previews=lambda send: None, images=images)
        self.assertEqual(asked, ['a/2.jpg'])
        self.assertEqual(self.log_entry('preview'), '\x03a/2.jpg\t1 1 0000ff\0')

    def test_an_image_that_fails_is_none_and_the_next_are_made(self):
        selection = picker.Selection()
        sent = []
        sender = mock.Mock(send_image=lambda relpath, image: sent.append((relpath, image)))

        def images(relpath, max_width, max_height):
            if relpath == 'bad.jpg':
                raise ValueError('bad')
            selection._close()
            return '1 1 000000'
        selection._move('bad.jpg')
        thread = threading.Thread(target=picker.pictures._send_images, args=(selection, images, sender))
        with mock.patch.object(picker.pictures, 'log_error') as log_error, \
                mock.patch.object(picker.pictures, 'IMAGE_DELAY', 0.01):
            thread.start()
            time.sleep(0.1)
            selection._move('good.jpg')
            thread.join(5)
        self.assertFalse(thread.is_alive())
        log_error.assert_called_once_with()
        self.assertEqual(sent, [('good.jpg', '1 1 000000')])

    def test_the_images_key_switches_them_off_and_on_for_the_next_pickers_too(self):
        selection = picker.Selection()
        sent = []
        sender = mock.Mock(send_image=lambda relpath, image: sent.append((relpath, image)))
        made = []

        def images(relpath, max_width, max_height):
            made.append(relpath)
            return '1 1 000000'
        pictures = picker.pictures.Images(selection, images, sender)
        thread = threading.Thread(target=pictures.run)
        with mock.patch.object(picker.pictures, 'IMAGE_DELAY', 0.01):
            thread.start()
            selection._move('a.jpg')
            self.wait_for(lambda: sent)
            # Off: the one sent is dropped, and none is made
            pictures.toggle('a.jpg')
            self.assertFalse(picker.pictures.settings.are_images_shown())
            self.assertEqual(sent[-1], ('a.jpg', ''))
            selection._move('b.jpg')
            time.sleep(0.1)
            self.assertEqual(made, ['a.jpg'])
            # On: the selected one's is made at once
            pictures.toggle('b.jpg')
            self.wait_for(lambda: made == ['a.jpg', 'b.jpg'])
            selection._close()
            thread.join(5)
        self.assertTrue(picker.pictures.settings.are_images_shown())
        self.assertEqual(sent[-1], ('b.jpg', '1 1 000000'))

    def test_the_images_key_is_one_of_the_pickers_notify_keys(self):
        os.environ['FAKE_PICKER_NOTIFY'] = 'i|a.jpg|;\t|a.jpg|'
        self.answer('a.jpg')
        notified = []
        with mock.patch.object(picker.pictures.Images, 'toggle') as toggle:
            picker.pick_files('/r', ['a.jpg'], previews=lambda send: None, images=lambda *_: None,
                              notify_keys='\t', on_notify=lambda *args: notified.append(args))
        args, _ = self.call()
        self.assertEqual(args[args.index('--notify') + 1], '\ti')
        toggle.assert_called_once_with('a.jpg')
        self.assertEqual(notified, [('\t', 'a.jpg', [])])

    def test_a_selection_says_the_picker_is_gone(self):
        selection = picker.Selection()
        self.assertIsNone(selection.wait_next(timeout=0.01))
        selection._move('x')
        self.assertEqual(selection.wait_next(), 'x')
        self.assertIsNone(selection.wait_next(timeout=0.01))
        selection._close()
        with self.assertRaises(picker.PickerClosed):
            selection.wait_next()
        with self.assertRaises(picker.PickerClosed):
            selection.is_at('x')


if __name__ == '__main__':
    unittest.main()
