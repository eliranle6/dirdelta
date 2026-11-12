"""A job's media files (images, audio, video, see media.py): hashed after its others, or left out"""
from dirdelta.hashes.hashing.pool import pool
from dirdelta.hashes.hashing.states import Left


class JobMedia(object):
    """Its media files (Job's)"""

    def set_media(self, with_media):
        """Hash its media files too (after the others), or leave out the ones not hashed yet: its
        progress then counts only the others, and it's done without them (the ones being hashed
        now are finished)"""
        with self._lock:
            self.with_media = with_media
        if with_media and self._is_started:
            pool().wake()

    def is_left_out(self, relpath):
        """Whether the file at relpath is a media file it leaves out, not hashed"""
        with self._lock:
            return not self.with_media and relpath in self._media_files and self._is_unhashed(relpath)

    def left(self):
        """(Left of its other files, Left of its media files): the ones not hashed yet (nor failed)"""
        with self._lock:
            others = [relpath for relpath in self._files
                      if relpath not in self._media_files and self._is_unhashed(relpath)]
            media_files = [relpath for relpath in self._media_files if self._is_unhashed(relpath)]
            return tuple(Left(len(relpaths), sum(self._files[relpath][0] for relpath in relpaths))
                         for relpaths in (others, media_files))

    def _is_unhashed(self, relpath):
        """Whether the file isn't hashed, failed or being hashed (with the lock held)"""
        return relpath not in self._hashes and relpath not in self._failed and relpath not in self._current

    def _left_out(self):
        """The media files it'd leave out: not hashed, failed or being hashed (with the lock held)"""
        return [relpath for relpath in self._media_files if self._is_unhashed(relpath)]
