"""Diffing two local dirs with the dirdiff program (from the lib/treepicker submodule): it scans them in
C++, much faster than building their DirTrees in Python (~1s rather than ~6s for two 119k file
dirs)."""
import os
import subprocess

from dirdelta import programs

PROGRAM_ENV_VAR = 'DIRDELTA_DIRDIFF'
PROGRAM_NAME = 'dirdiff'


def files_not_in(src_dir, dst_dir, max_depth=None):
    """The paths (relative to src_dir) of src_dir's files that dst_dir lacks, by path only, and find's
    error messages (paths it couldn't read in either dir)."""
    command = [programs.find(PROGRAM_NAME, PROGRAM_ENV_VAR), '-0']
    if max_depth is not None:
        command += ['--max-depth', str(max_depth)]
    command += [src_dir, dst_dir]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as error:
        raise programs.ProgramError('Cannot run %s: %s' % (command[0], error))
    errors = result.stderr.decode('utf-8', 'surrogateescape').splitlines()
    if result.returncode != 0:
        raise programs.ProgramError('%s failed: %s' % (command[0], ' '.join(errors)))
    # Names needn't be valid UTF-8: decoded like Python decodes paths
    return [os.fsdecode(path) for path in result.stdout.split(b'\0') if path], errors
