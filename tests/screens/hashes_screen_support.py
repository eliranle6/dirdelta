"""What the hashing screens' tests share: a job whose progress is as given"""
import unittest

from dirdelta.hashes import hashing


class FakeJob(hashing.Job):
    """A job whose progress is as given, and that's started and paused by hand"""
    def __init__(self, root, progress):
        super(FakeJob, self).__init__(root)
        self.progress_of = progress
        self.started = self.paused = 0

    def progress(self):
        return self.progress_of

    def start(self):
        self.started += 1
        self._is_started = True

    def pause(self):
        self.paused += 1
        self._is_started = False


def progress_of(**fields):
    defaults = dict(state=hashing.SCANNED, nr_files=10, nr_done=4, size=2048, size_done=1024, current=[],
                    rate=None, nr_failed=0, is_paused=False, is_started=False)
    defaults.update(fields)
    return hashing.Progress(**defaults)


if __name__ == '__main__':
    unittest.main()
