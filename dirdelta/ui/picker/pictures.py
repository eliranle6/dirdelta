"""The pictures of the files a picker's selection stays on"""
import collections
import os
import threading

from dirdelta.known import settings
from dirdelta.ui.picker.selection import PickerClosed
from dirdelta.ui.picker.updates import _log_error


# How long the selection stays on a node before its picture is made (so moving through files doesn't
# read each), in seconds; and how many pictures treepicker keeps (fewer than its own most, 64, so
# those sent are still there)
IMAGE_DELAY = 0.15
# The key that switches the pictures off and on (see pick_files()'s images)
IMAGES_KEY = 'i'
MAX_IMAGES_SENT = 48


def _send_images(selection, images, sender):
    """Send treepicker the picture of each node the selection stays on (see pick_files()'s images),
    once, until it's gone"""
    _Images(selection, images, sender).run()


class _Images(object):
    """What sends treepicker the pictures of a pick_files() picker (see _send_images()), unless
    they're switched off (settings.are_images_shown(); IMAGES_KEY switches them)"""

    def __init__(self, selection, images, sender):
        self._selection = selection
        self._images = images
        self._sender = sender
        self._lock = threading.Lock()
        # The relpaths whose pictures were made (and sent, if they have one), oldest first
        self._sent = collections.OrderedDict()

    def run(self):
        max_width, max_height = _image_box()
        try:
            while True:
                relpath = self._selection.wait_next()
                while True:
                    later = self._selection.wait_next(IMAGE_DELAY)
                    if later is None:
                        break
                    relpath = later
                if relpath in self._sent or not settings.are_images_shown():
                    continue
                try:
                    image = self._images(relpath, max_width, max_height)
                except Exception:
                    _log_error()
                    image = None
                with self._lock:
                    # Switched off meanwhile: not shown
                    if not settings.are_images_shown():
                        continue
                    self._sent[relpath] = True
                    if len(self._sent) > MAX_IMAGES_SENT:
                        self._sent.popitem(last=False)
                    if image is not None:
                        self._sender.send_image(relpath, image)
        except PickerClosed:
            pass

    def toggle(self, selected):
        """Switch the pictures off (the ones sent are dropped) or on (the selected node's, at
        selected, is made), for this picker and the next ones"""
        with self._lock:
            is_shown = not settings.are_images_shown()
            settings.set_images_shown(is_shown)
            if not is_shown:
                for relpath in self._sent:
                    self._sender.send_image(relpath, '')
                self._sent.clear()
        if is_shown:
            # As if the selection moved there, so its picture is made
            self._selection._move(selected)


def _image_box():
    """The most pixels (width, height) a picture may take in the preview column: its width and twice
    its rows (treepicker's: 2/5 of the terminal), as the terminal is now"""
    try:
        with open('/dev/tty') as tty:
            columns, rows = os.get_terminal_size(tty.fileno())
    except OSError:
        columns, rows = 100, 30
    return max(1, columns * 2 // 5 - 2), max(2, rows * 2)
