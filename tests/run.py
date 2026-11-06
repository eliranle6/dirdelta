"""Runs the test modules in parallel, each in a process of its own (as their fakes of the caches are
per process: see helpers.py), the slowest first, and sums them up as unittest would.

    python tests/run.py [unittest's options, e.g. -v, -k PATTERN, -f] [test_x ...]

With no modules named, all the test_*.py under tests/ (in folders mirroring dirdelta's packages; a
module is named by its file's name, which is unique). A module imports helpers.py (tests/) and the
support modules of its folder and the ones above it by name. Each module's output is shown if it failed, or
with -v."""
import concurrent.futures
import json
import os
import subprocess
import sys
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
# What run_one() prints last, before its counts
MARK = '\x00counts '


def test_modules():
    """{module name: its file} of the test modules under TESTS"""
    found = {}
    for dirpath, dirnames, filenames in os.walk(TESTS):
        dirnames[:] = sorted(name for name in dirnames if name not in ('fixtures', '__pycache__'))
        for name in filenames:
            if name.startswith('test_') and name.endswith('.py'):
                if name[:-3] in found:
                    sys.exit('Two test modules named %s: in %s and %s' % (name, found[name[:-3]], dirpath))
                found[name[:-3]] = os.path.join(dirpath, name)
    return found


def run_one(module, args):
    """Runs module's tests, its output on stderr, and prints how many ran, failed and so on"""
    # Its folder's support modules, and those of the folders above it, up to helpers.py's
    folders, folder = [], os.path.dirname(test_modules()[module])
    while folder != TESTS:
        folders.append(folder)
        folder = os.path.dirname(folder)
    sys.path[:0] = folders + [TESTS]
    program = unittest.main(module=None, argv=['run.py'] + args + [module], exit=False)
    result = program.result
    print(MARK + json.dumps([result.testsRun, len(result.failures), len(result.errors), len(result.skipped),
                             len(result.expectedFailures), len(result.unexpectedSuccesses)]))


def run(module, args):
    """(module, its output, its counts, or None if it didn't say them)"""
    done = subprocess.run([sys.executable, __file__, '--one', module] + args, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, universal_newlines=True)
    output, _, counts = done.stdout.rpartition(MARK)
    if not _:
        return module, done.stdout, None
    return module, output, json.loads(counts)


def main(argv):
    # unittest's options (-k's pattern with it), and the modules named
    options, named = [], []
    args = iter(argv)
    for arg in args:
        if arg.startswith('-'):
            options += [arg, next(args)] if arg == '-k' else [arg]
        else:
            named.append(arg)
    files = test_modules()
    modules = [os.path.basename(name)[:-3] if name.endswith('.py') else name for name in named] or sorted(files)
    unknown = [module for module in modules if module not in files]
    if unknown:
        sys.stderr.write('No such test module: %s\n' % (', '.join(unknown),))
        return 2
    # The biggest first, as they take the longest
    modules.sort(key=lambda module: -os.path.getsize(files[module]))
    verbose = '-v' in options
    started = time.time()
    totals = [0] * 6
    broken = []
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 2) as pool:
        for module, output, counts in pool.map(lambda module: run(module, options), modules):
            failed = counts is None or counts[1] or counts[2] or counts[5]
            if failed:
                broken.append(module)
            if verbose or failed:
                sys.stderr.write('=== %s\n%s' % (module, output))
            for i, count in enumerate(counts or []):
                totals[i] += count
    ran, failures, errors, skipped, expected, unexpected = totals
    sys.stderr.write('-' * 70 + '\nRan %d tests in %d modules in %.1fs\n\n' % (ran, len(modules), time.time() - started))
    details = [(name, count) for name, count in (('failures', failures), ('errors', errors), ('skipped', skipped),
                                                 ('expected failures', expected),
                                                 ('unexpected successes', unexpected)) if count]
    about = ' (%s)' % ', '.join('%s=%d' % pair for pair in details) if details else ''
    if broken:
        sys.stderr.write('FAILED%s: %s\n' % (about, ' '.join(broken)))
        return 1
    sys.stderr.write('OK%s\n' % (about,))
    return 0


if __name__ == '__main__':
    if sys.argv[1:2] == ['--one']:
        run_one(sys.argv[2], sys.argv[3:])
    else:
        sys.exit(main(sys.argv[1:]))
