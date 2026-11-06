"""What's sent to treepicker's preview column"""
import os
import threading

from dirdelta.ui.picker.selection import PickerClosed
from dirdelta.ui.picker.updates import null_terminated


class PreviewSender(object):
    """Writes what's sent to treepicker's --preview pipe (see pick_files()), from any thread"""

    def __init__(self, fd, is_done):
        self._fd = fd
        self._is_done = is_done
        self._lock = threading.Lock()

    def send(self, found=None, default=None):
        if self._is_done.is_set():
            raise PickerClosed()
        items = [_preview(relpath or '.', lines) for relpath, lines in (found or {}).items()]
        if default is not None:
            # An empty path: the lines of the ones without any
            items.append(_preview('', default))
        self._write(null_terminated(items))

    def _write(self, data):
        if self._is_done.is_set():
            raise PickerClosed()
        # A preview's lines in one piece, whichever thread sends it
        with self._lock:
            try:
                while data:
                    data = data[os.write(self._fd, data):]
            except BrokenPipeError:
                raise PickerClosed()

    def send_image(self, relpath, image):
        """Show image (see pick_files()'s images) below relpath's lines"""
        self._write(null_terminated(['\x03' + (relpath or '.') + '\t' + _one_line(image)]))

    def run(self, previews):
        """Call previews(send), until it returns, or treepicker is gone"""
        try:
            previews(self.send)
        except PickerClosed:
            pass


def _preview(path, lines):
    """treepicker's --preview line showing lines for path"""
    return path + '\t' + '\t'.join(_one_line(line) for line in lines)


def _one_line(text):
    """text without what would end a --preview line, or the preview's line itself (e.g. a file
    name's tab), shown as '?' like treepicker shows control characters"""
    return text.replace('\t', '?').replace('\n', '?').replace('\0', '?')
