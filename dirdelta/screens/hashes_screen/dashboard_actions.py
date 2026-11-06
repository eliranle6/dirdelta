"""What the dashboard's options do, and the dashboard shown as it changes"""
import os

from dirdelta.hashes import hashcache
from dirdelta.hashes import hashing
from dirdelta.known import mounts
from dirdelta.known import replicainfo
from dirdelta.known import replicanames
from dirdelta.matching import syncstate
from dirdelta.screens import label_screen
from dirdelta.screens.hashes_screen.dashboard_lines import jobs_by_name, jobs_shown
from dirdelta.screens.hashes_screen.files import view_files
from dirdelta.screens.hashes_screen.names import BACK, TITLE, FILES, HASH, LABEL, RESCAN, TOGGLE
from dirdelta.trees import localscan
from dirdelta.trees import paths
from dirdelta.ui import picker


def is_there(name):
    """Whether the local replica named name can be reached: its volume's mounted and it's a dir"""
    return mounts.unmounted(name) is None and os.path.isdir(name)


def _start_hashing(name):
    """Hash the local replica named name in the background, its files listed first (as a sync's are,
    but without keeping the dashboard waiting), its hashes kept in it (see hashcache.use_replica())"""
    hashcache.use_replica(name)
    # As deep as a sync of it goes, by default, so that sync's listings can be shared with it
    job = hashing.job(name, localscan.DEFAULT_MAX_DEPTH)
    job.scan_in_background()
    job.start()


def label_option(name, known):
    """How the option that labels the replica named name is shown. Not of one that isn't there: what
    its path is on now isn't its disk, so it wouldn't be its identity, which its label is kept by"""
    if not paths.is_cloud_path(name) and not is_there(name):
        return picker.Disabled("  Label the replica: its disk isn't mounted")
    current = known.labels.get(replicanames.label_key(name))
    return "  Label the replica%s" % (": now '%s'" % (current,) if current else "",)


def finish_dashboard(items, options, shown, names, jobs, known, selected=None):
    """Show the dashboard of options, as _show_dashboard() says"""
    options.append(BACK)
    header = ("Replicas: when synced, and their files' hashes\n\n"
              "A local one's hashes are worked out here (SHA-1, as Drive's), each file read once, at the lowest "
              "priority, and kept in it, in %s (until it has one, in a dry run or if it's read-only: in %s)." % (
                  os.path.join(paths.META_DIR, hashcache.META_NAME), hashcache.database.CACHE_FILE))

    def shown_now():
        now = {**shown, **jobs_shown(items, names)}
        now[''] = picker.segments(hashing.status_parts(jobs))
        return now
    first = shown_now()
    # The first that can be picked
    selected = selected or next((option for option in options if isinstance(option, tuple) and
                                 option[0] in (TOGGLE, FILES, HASH, LABEL) and
                                 not isinstance(first.get(option), picker.Disabled)), BACK)
    # Those that are their ids; what they show, shown_as says
    choices = [picker.Option(option, '') if isinstance(option, tuple) else option for option in options]
    while True:
        option = picker.pick_option(choices, header=header, title=TITLE, shown_as=shown_now, selected=selected,
                                    key_hints=[('Enter', 'do it'), ('q', 'back')],
                                    help_lines=["The pairs' marks:"] + ["  " + line for line in syncstate.help_lines()] +
                                    replicainfo.path_marks_help())
        if option in (None, BACK):
            return None
        selected = option
        if option[0] == LABEL:
            label_screen.run(known, [option[1]])
            return option
        if option[0] == HASH:
            _start_hashing(option[1])
            # Shown anew, as its job's: it can be paused now
            return (TOGGLE, option[1])
        for name, job in jobs_by_name(items).items():
            if option == (TOGGLE, name):
                if job.is_started():
                    job.pause()
                else:
                    job.start()
            elif option == (FILES, name):
                view_files(job)
            elif option == (RESCAN, name):
                job.scan_in_background()
