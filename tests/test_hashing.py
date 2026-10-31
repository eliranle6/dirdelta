import hashlib
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import helpers
from dirdelta import hashcache
from dirdelta import hashing

# How long a test waits for the workers, at most, in seconds
TIMEOUT = 10


def _sha1(contents):
    return hashlib.sha1(contents.encode()).hexdigest()


class JobTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix='dirdelta-hashing-'))
        self.addCleanup(shutil.rmtree, self.root)
        helpers.make_files(self.root, ['a/x', 'a/y', 'z'])
        self.job = hashing.Job(self.root)
        self.addCleanup(self.job.pause)

    def wait_done(self):
        deadline = time.monotonic() + TIMEOUT
        while self.job.progress().state != hashing.DONE:
            self.assertLess(time.monotonic(), deadline, "not done in time")
            time.sleep(0.01)

    def test_scanning_lists_its_files_none_hashed_yet(self):
        self.assertEqual(self.job.progress().state, hashing.NOT_SCANNED)
        self.job.scan()
        progress = self.job.progress()
        self.assertEqual((progress.state, progress.nr_files, progress.nr_done, progress.size),
                         (hashing.SCANNED, 3, 0, len('a/x') + len('a/y') + len('z')))
        self.assertEqual(self.job.files(), ['a/x', 'a/y', 'z'])
        self.assertFalse(progress.is_started)

    def test_it_hashes_them_all_into_the_hash_cache_and_tells_its_subscribers(self):
        self.job.scan()
        told = {}
        self.job.subscribe(lambda relpath, hashes: told.update({relpath: hashes}))
        self.job.start()
        self.wait_done()
        self.assertEqual(told['a/x'], {'sha1': _sha1('a/x')})
        self.assertEqual(sorted(told), ['a/x', 'a/y', 'z'])
        self.assertEqual(self.job.hash_of('z'), _sha1('z'))
        self.assertEqual(hashcache.get(os.path.join(self.root, 'a', 'y'), 'sha1'), _sha1('a/y'))
        self.assertEqual(hashing.percent(self.job.progress()), 100)

    def test_the_hash_cache_says_which_are_hashed_already(self):
        hashcache.put(os.path.join(self.root, 'z'), {'sha1': 'kept'})
        hashcache.put(os.path.join(self.root, 'a', 'x'), {'sha256': 'not ours'})
        self.job.scan()
        self.assertEqual(self.job.progress().nr_done, 1)
        self.assertEqual(self.job.hash_of('z'), 'kept')
        self.assertIsNone(self.job.hash_of('a/x'))
        # Its subscribers get the ones hashed before when they subscribe
        self.assertEqual(self.job.subscribe(lambda relpath, hashes: None), {'z': {'sha1': 'kept'}})

    def test_a_file_changed_since_its_hash_was_kept_is_hashed_again(self):
        hashcache.put(os.path.join(self.root, 'z'), {'sha1': 'old'})
        with open(os.path.join(self.root, 'z'), 'w') as f:
            f.write('changed, and longer')
        self.job.scan()
        self.assertIsNone(self.job.hash_of('z'))

    def test_scanning_again_keeps_the_hashed_ones_and_finds_new_ones(self):
        self.job.scan()
        self.job.start()
        self.wait_done()
        helpers.make_files(self.root, ['new'])
        self.job.scan()
        self.assertEqual(self.job.progress().nr_done, 3)
        self.wait_done()
        self.assertEqual(self.job.hash_of('new'), _sha1('new'))

    def test_paused_it_hashes_nothing_until_resumed(self):
        self.job.scan()
        self.job.start()
        self.job.pause()
        # What was being hashed when it was paused may finish; then nothing more
        time.sleep(0.2)
        nr_done = self.job.progress().nr_done
        time.sleep(0.2)
        self.assertEqual(self.job.progress().nr_done, nr_done)
        if nr_done < 3:
            self.assertTrue(self.job.progress().is_paused)
            self.assertIn("(paused)", hashing.status_text(self.job))
        self.job.start()
        self.wait_done()

    def test_the_files_asked_first_are_taken_first(self):
        self.job.scan()
        # Taken by hand, rather than by the pool's workers
        self.job._is_started = True
        self.job.first(['z', 'nope'])
        self.assertEqual(self.job._next(), 'z')
        # Then the others, as find lists them
        self.assertIn(self.job._next(), ('a/x', 'a/y'))

    def test_a_job_of_a_spinning_disk_is_hashed_by_one_worker_at_a_time(self):
        self.job.scan()
        self.job._is_started = True
        self.job.max_workers = 1
        self.assertIsNotNone(self.job._next())
        self.assertIsNone(self.job._next())

    def test_a_file_that_cant_be_read_is_counted_and_its_done_without_it(self):
        self.job.scan()
        unreadable = os.path.join(self.root, 'z')
        os.chmod(unreadable, 0)
        self.addCleanup(os.chmod, unreadable, 0o644)
        if os.access(unreadable, os.R_OK):
            self.skipTest("running as root: it can be read")
        self.job.start()
        self.wait_done()
        progress = self.job.progress()
        self.assertEqual((progress.nr_done, progress.nr_failed), (3, 1))
        self.assertEqual(self.job.failed(), {'z'})


class HashFileTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='dirdelta-hashing-')
        self.addCleanup(shutil.rmtree, self.root)
        helpers.make_files(self.root, ['x'])
        self.path = os.path.join(self.root, 'x')

    def test_its_hash_and_its_stamp_when_read(self):
        stat = os.stat(self.path)
        self.assertEqual(hashing._hash_file(self.path, lambda: False),
                         (_sha1('x'), [stat.st_size, stat.st_mtime_ns]))

    def test_paused_it_stops(self):
        with self.assertRaises(hashing._Paused):
            hashing._hash_file(self.path, lambda: True)

    def test_a_gone_file_has_none(self):
        self.assertEqual(hashing._hash_file(os.path.join(self.root, 'nope'), lambda: False), (None, None))

    def test_one_changed_while_read_has_none(self):
        real_stat = os.stat
        with mock.patch('os.stat', side_effect=lambda path, *args, **kwargs: os.stat_result(
                (0,) * 6 + (99, 0, 0, 0)) if path == self.path else real_stat(path, *args, **kwargs)):
            self.assertEqual(hashing._hash_file(self.path, lambda: False), (None, None))


class ListFilesTest(unittest.TestCase):
    def test_its_files_with_their_sizes_and_times_in_ns(self):
        root = tempfile.mkdtemp(prefix='dirdelta-hashing-')
        self.addCleanup(shutil.rmtree, root)
        helpers.make_files(root, ['a/b c', 'd'])
        os.symlink('d', os.path.join(root, 'link'))
        found = hashing._list_files(root)
        stat = os.stat(os.path.join(root, 'a', 'b c'))
        self.assertEqual(sorted(found), ['a/b c', 'd'])
        self.assertEqual(found['a/b c'], (stat.st_size, stat.st_mtime_ns))

    def test_finds_seconds_in_nanoseconds(self):
        self.assertEqual(hashing.nanoseconds('1698765432.1234567890'), 1698765432123456789)
        self.assertEqual(hashing.nanoseconds('1698765432.5'), 1698765432500000000)
        self.assertEqual(hashing.nanoseconds('1698765432'), 1698765432000000000)
        self.assertEqual(hashing.nanoseconds('-1.5'), -1500000000)


def _progress(**fields):
    defaults = dict(state=hashing.HASHING, nr_files=10, nr_done=0, size=1000, size_done=0, current=[],
                    rate=None, nr_failed=0, is_paused=False, is_started=True)
    defaults.update(fields)
    return hashing.Progress(**defaults)


class StatusTest(unittest.TestCase):
    def test_percent_is_of_bytes_and_100_only_when_done(self):
        self.assertEqual(hashing.percent(_progress(size_done=630)), 63)
        self.assertEqual(hashing.percent(_progress(size_done=1000)), 99)
        self.assertEqual(hashing.percent(_progress(state=hashing.DONE, size_done=1000)), 100)
        # Empty files: of the files
        self.assertEqual(hashing.percent(_progress(size=0, nr_done=5)), 50)

    def test_the_colors_go_from_red_to_green(self):
        self.assertEqual([hashing.color(_progress(size_done=done)) for done in (0, 400, 700)],
                         ['red', 'orange', 'yellow'])
        self.assertEqual(hashing.color(_progress(state=hashing.DONE, size_done=1000)), 'green')

    def test_its_text_by_its_state(self):
        job = hashing.Job('/photos')
        self.assertEqual(hashing.status_text(job, _progress(state=hashing.SCANNING)), "photos: listing its files...")
        self.assertEqual(hashing.status_text(job, _progress(size_done=630)), "photos: 63% hashed")
        self.assertEqual(hashing.status_text(job, _progress(size_done=630, is_started=False, is_paused=True)),
                         "photos: 63% hashed (paused)")
        self.assertEqual(hashing.status_text(job, _progress(is_started=False)), "photos: 0% hashed (not hashing)")
        self.assertEqual(hashing.status_text(job, _progress(state=hashing.DONE)), "photos: hashed ✓")

    def test_a_bar(self):
        self.assertEqual(hashing.bar(_progress(size_done=500), width=4), '[██░░]')

    def test_time_left_by_its_speed(self):
        self.assertEqual(hashing.time_left(_progress(size_done=400, rate=100)), 6)
        self.assertIsNone(hashing.time_left(_progress()))
        self.assertEqual([hashing.format_duration(seconds) for seconds in (45, 720, 12000)],
                         ["45 s", "12 min", "3 h 20 min"])

    def test_the_tags(self):
        job = hashing.Job('/photos')
        job._hashes['a'] = 'H'
        job._current.add('b')
        job._failed.add('d')
        self.assertEqual([hashing.tag(job, relpath) for relpath in ('a', 'b', 'c', 'd')],
                         ["[\u25cf hashed]", "[\u25d0 hashing now]", "[\u25cb not hashed yet]",
                          "[\u2715 couldn't be hashed]"])


class MachineTest(unittest.TestCase):
    def test_one_worker_fewer_than_physical_cores(self):
        with mock.patch('dirdelta.hashing.physical_cores', return_value=4):
            self.assertEqual(hashing.nr_workers(), 3)
        with mock.patch('dirdelta.hashing.physical_cores', return_value=1):
            self.assertEqual(hashing.nr_workers(), 1)

    def test_physical_cores_by_their_ids_or_half_the_logical_ones(self):
        self.assertGreaterEqual(hashing.physical_cores(), 1)
        with mock.patch('glob.glob', return_value=[]), mock.patch('os.cpu_count', return_value=8):
            self.assertEqual(hashing.physical_cores(), 4)

    def test_a_path_whose_disk_isnt_known_isnt_rotational(self):
        self.assertFalse(hashing.is_rotational('/nonexistent/path'))

    def test_jobs_are_kept_by_their_roots(self):
        root = tempfile.mkdtemp(prefix='dirdelta-hashing-')
        self.addCleanup(shutil.rmtree, root)
        self.assertIsNone(hashing.job_for(root))
        job = hashing.job(root + '/')
        self.addCleanup(hashing._jobs.pop, os.path.realpath(root))
        self.assertIs(hashing.job(root), job)
        self.assertIs(hashing.job_for(root), job)
        self.assertIn(job, hashing.jobs())


if __name__ == '__main__':
    unittest.main()
