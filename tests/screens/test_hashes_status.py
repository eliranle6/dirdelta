import unittest
from unittest import mock

import helpers  # noqa: F401  (the caches' fakes)
from dirdelta.hashes import hashing
from dirdelta.screens.hashes_screen import status as hash_status
from dirdelta.util import text


def _progress(**fields):
    defaults = dict(state=hashing.HASHING, nr_files=10, nr_done=0, size=1000, size_done=0, current=[],
                    rate=None, nr_failed=0, is_paused=False, is_started=True)
    defaults.update(fields)
    return hashing.Progress(**defaults)


class StatusTest(unittest.TestCase):
    def test_percent_is_of_bytes_and_100_only_when_done(self):
        self.assertEqual(hash_status.percent(_progress(size_done=630)), 63)
        self.assertEqual(hash_status.percent(_progress(size_done=1000)), 99)
        self.assertEqual(hash_status.percent(_progress(state=hashing.DONE, size_done=1000)), 100)
        # Empty files: of the files
        self.assertEqual(hash_status.percent(_progress(size=0, nr_done=5)), 50)

    def test_the_colors_go_from_red_to_green(self):
        self.assertEqual([hash_status.color(_progress(size_done=done)) for done in (0, 400, 700)],
                         ['red', 'orange', 'yellow'])
        self.assertEqual(hash_status.color(_progress(state=hashing.DONE, size_done=1000)), 'green')

    def test_active_jobs_are_the_ones_hashing_or_paused_with_files_left(self):
        states = {'/hashing': _progress(), '/paused': _progress(is_started=False, is_paused=True),
                  '/idle': _progress(is_started=False), '/done': _progress(state=hashing.DONE)}
        made = []
        for root, progress in states.items():
            job = hashing.Job(root)
            job.progress = lambda progress=progress: progress
            made.append(job)
        with mock.patch('dirdelta.screens.hashes_screen.status.jobs', return_value=made):
            self.assertEqual([job.root for job in hash_status.active_jobs()], ['/hashing', '/paused'])

    def test_its_text_by_its_state(self):
        job = hashing.Job('/photos')
        self.assertEqual(hash_status.status_text(job, _progress(state=hashing.SCANNING)), "photos: listing its files...")
        self.assertEqual(hash_status.status_text(job, _progress(size_done=630)), "photos: 63% hashed (0/10)")
        self.assertEqual(hash_status.status_text(job, _progress(size_done=630, is_started=False, is_paused=True)),
                         "photos: 63% hashed (0/10, paused)")
        self.assertEqual(hash_status.status_text(job, _progress(is_started=False)), "photos: 0% hashed (0/10, not hashing)")
        self.assertEqual(hash_status.status_text(job, _progress(state=hashing.DONE, nr_done=10)), "photos: 100% hashed ✓ (10/10)")

    def test_time_left_by_its_speed(self):
        self.assertEqual(hash_status.time_left(_progress(size_done=400, rate=100)), 6)
        self.assertIsNone(hash_status.time_left(_progress()))
        self.assertEqual([text.format_duration(seconds) for seconds in (45, 720, 12000)],
                         ["45 s", "12 min", "3 h 20 min"])

    def test_the_tags(self):
        job = hashing.Job('/photos')
        job._hashes['a'] = 'H'
        job._current.add('b')
        job._failed.add('d')
        self.assertEqual([hash_status.tag(job, relpath) for relpath in ('a', 'b', 'c', 'd')],
                         ["[\u25cf hashed]", "[\u25d0 hashing now]", "[\u25cb not hashed yet]",
                          "[\u2715 couldn't be hashed]"])
