"""A treepicker command being made, and run: its arguments, the pipes to and from it, and the
threads that serve them while it runs"""
import functools
import os
import subprocess
import tempfile
import threading

from dirdelta.ui.picker.kinds import SIDE_KEY
from dirdelta.ui.picker.pictures import IMAGES_KEY, _Images
from dirdelta.ui.picker.places import _trail
from dirdelta.ui.picker.previews import _PreviewSender
from dirdelta.ui.picker.selection import Selection, _follow, _read_notifications, _read_selection
from dirdelta.ui.picker.updates import _logging_errors, _null_terminated
from dirdelta.util import dryrun
from dirdelta.util import programs

PROGRAM_NAME = 'treepicker'


class PickerError(programs.ProgramError):
    pass


class _Command(object):
    """treepicker's command with args (its own, after the dry run's label, then label, if given),
    the pipes to treepicker (which reads --updates and --preview) and from it (it writes
    --selection): treepicker's ends, and ours; and the jobs serving them, each run on a thread of
    its own while treepicker runs"""
    def __init__(self, args, label):
        self.args = [_find_program(), '-0']
        for text, color in [dryrun.label()] + ([label] if label else []):
            self.args += ['--label', text, '--label-color', color]
        if not any(args[i:i + 2] == ['--key', 'q'] for i in range(len(args))):
            # q quits the start menu; anywhere else, it goes back to where the user was
            self.args += ['--key', 'q', 'back' if _trail else 'quit']
        self.args += args
        self.is_done = threading.Event()
        self.child_fds, self.our_fds = [], []
        self.jobs = []
        # The ones on the selection's moves, each its own (see Selection), all moved by one reader
        self.selections = []
        self.side_file = None

    def pipe(self, option, is_read_by_child):
        """A pipe to or from treepicker, passed to it as option; returns our end"""
        read_fd, write_fd = os.pipe()
        child_fd, our_fd = (read_fd, write_fd) if is_read_by_child else (write_fd, read_fd)
        self.child_fds.append(child_fd)
        self.our_fds.append(our_fd)
        self.args.extend([option, str(child_fd)])
        return our_fd

    def add_side(self, side):
        """The tree beside the picker (a Side)"""
        self.side_file = tempfile.NamedTemporaryFile('wb', prefix='dirdelta-side-')
        self.side_file.write(_null_terminated(side.items))
        self.side_file.flush()
        self.args.extend(['--side', self.side_file.name, '--side-root', side.root_name])
        if side.is_enter_picking:
            self.args.extend(['--side-key', SIDE_KEY])
        if side.keys:
            self.args.extend(['--side-expect', side.keys])
        if side.start is not None:
            self.args.extend(['--side-start', side.start or '.'])
        for key, text in side.key_hints:
            self.args.extend(['--side-hint', key, text])
        if side.follow is not None:
            self.selections.append(Selection())
            self.jobs.append(functools.partial(_follow, self.selections[-1], side.follow,
                                               self.pipe('--side-select', True)))

    def add_previews(self, previews, on_selection, images, notify):
        """What's shown in the preview column: previews, on_selection's, and the pictures (see
        pick_files()); returns notify, with the pictures' key added, if they're shown"""
        if previews is None and on_selection is None:
            return notify
        preview_sender = _PreviewSender(self.pipe('--preview', True), self.is_done)
        if previews is not None:
            self.jobs.append(functools.partial(preview_sender.run, previews))
        if on_selection is not None:
            selection = Selection()
            self.selections.append(selection)
            self.jobs.append(functools.partial(preview_sender.run, lambda send: on_selection(selection, send)))
        if images is not None:
            self.selections.append(Selection())
            pictures = _Images(self.selections[-1], images, preview_sender)
            self.jobs.append(pictures.run)
            # Its key, besides the caller's
            keys, on_notify = notify if notify is not None else ('', None)

            def notified(key, selected, picked, on_notify=on_notify):
                if key == IMAGES_KEY:
                    pictures.toggle(selected)
                elif on_notify is not None:
                    on_notify(key, selected, picked)
            notify = (keys + IMAGES_KEY, notified)
        return notify

    def add_readers(self, notify):
        """The jobs reading what treepicker says: where the selection is, and the keys of notify
        ((keys, a function of what they say), or None)"""
        if self.selections:
            self.jobs.append(functools.partial(_read_selection, self.pipe('--selection', False), self.selections))
        if notify is not None:
            keys, on_notify = notify
            self.args.extend(['--notify', keys])
            self.jobs.append(functools.partial(_read_notifications, self.pipe('--notify-fd', False), on_notify))

    def run(self, input_items):
        """Run treepicker with input_items (or None) on its stdin, the jobs on their threads meanwhile;
        returns (the process, what it printed)"""
        threads = [threading.Thread(target=_logging_errors, args=(job,), daemon=True) for job in self.jobs]
        try:
            # From a file, rather than written to a pipe by communicate(): with a sender busy on its
            # thread (holding the GIL), writing a big input would be slow to get the GIL back each time
            with tempfile.TemporaryFile() as input_file:
                if input_items is not None:
                    input_file.write(_null_terminated(input_items))
                    input_file.seek(0)
                try:
                    process = subprocess.Popen(
                        self.args, stdout=subprocess.PIPE,
                        stdin=input_file if input_items is not None else subprocess.DEVNULL,
                        pass_fds=self.child_fds)
                except OSError as error:
                    raise PickerError('Cannot run %s: %s' % (self.args[0], error))
                finally:
                    # treepicker has its own copies
                    for child_fd in self.child_fds:
                        os.close(child_fd)
            for thread in threads:
                thread.start()
            stdout, _ = process.communicate()
        finally:
            self.is_done.set()
            # So nothing a thread started (e.g. a find) outlives the picker. They end once treepicker
            # has: what they send raises PickerClosed, and the selection's pipe ends.
            for thread in threads:
                if thread.is_alive():
                    thread.join()
            for our_fd in self.our_fds:
                os.close(our_fd)
            if self.side_file is not None:
                self.side_file.close()
        return process, stdout


def _find_program():
    return programs.find(PROGRAM_NAME)
