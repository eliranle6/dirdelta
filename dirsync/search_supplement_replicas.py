import os
import sys
import json
import logging
import subprocess

import config
import cursesswitch
from treepicker import optionpicker


def search(replica_a_path, replica_b_path):
    if replica_a_path is None and replica_b_path is None:
        replica_a_path, replica_b_path = _search_replicas(nr_replicas=2)
    elif replica_b_path is None:
        replica_b_path = _search_replicas(nr_replicas=1, filter_out=replica_a_path)[0]
    else:
        assert replica_a_path is not None
        assert replica_b_path is not None
    replica_a_path = os.path.realpath(replica_a_path)
    replica_b_path = os.path.realpath(replica_b_path)
    return replica_a_path, replica_b_path


def _find_dirs_with_matching_name(parentdir):
    cmd = ["find", parentdir, "-type", "d", "-regex", ".*\/Music\|.*\/music"]
    logging.debug("Searching for a replica under %s...", parentdir)
    output = subprocess.check_output(cmd)
    dirs = output.strip().splitlines()
    return dirs


invocation_counter = 0


def _search_replicas(nr_replicas, filter_out=None):
    global invocation_counter
    invocation_counter += 1
    if invocation_counter > 1:
        cursesswitch.print_string("Don't invoke this function more than once")
        sys.exit(1)
    if filter_out is None:
        filter_out = list()

    if nr_replicas == 1:
        cursesswitch.print_string("Missing 1 replicas from arguments. Searching for it in the filesystem...")
    elif nr_replicas == 2:
        cursesswitch.print_string("Missing 2 replicas from arguments. Searching for them in the filesystem...")
    candidates = list()
    for parentdir in config.POSSIBLE_PARENT_DIRS:
        cursesswitch.print_string("\tSearching under '%s'..." % (parentdir,))
        candidates_paths = _find_dirs_with_matching_name(parentdir)
        candidates.extend(candidates_paths)
    candidates = [candidate for candidate in candidates if candidate not in filter_out]
    _validate_enough_replicas(candidates, nr_replicas)
    picker = optionpicker.OptionPickerByMenuTraverse(candidates)
    return picker.pick_several(nr_options_to_pick=nr_replicas)


def _validate_enough_replicas(candidates, nr_replicas):
    if len(candidates) < nr_replicas:
        if len(candidates) == 0:
            cursesswitch.print_string("Did not find any replica in the filesystem to supplement existing.")
        elif len(candidates) == 1:
            cursesswitch.print_string("Did not find enough replicas in the filesystem to to pick from.")
            cursesswitch.print_string("Only the following was found: %s" % (candidates[0],))
        else:
            assert False
        sys.exit(1)


def _get_device_storing_dir(_dir):
    filesystem = subprocess.check_output(["df", ".", "--output=source"]).splitlines()[1]
    device = filesystem.strip('0123456789')
    return device


def _get_dir_size(_dir):
    return subprocess.check_output(["du", "-h", "-s", _dir]).split()[0].strip()


def _get_device_info(device, devices_info):
    if devices_info.get('logicalname') == device:
        return devices_info['description'], devices_info['product']
    if 'children' in devices_info:
        for child in devices_info['children']:
            childinfo = _get_device_info(device, child)
            if childinfo is not None:
                return childinfo
    return None


def print_dirs(dirs):
    cursesswitch.print_string("\tReading device list...")
    devices_info = json.loads(subprocess.check_output(["lshw", "-json"]))
    for dir_idx, _dir in enumerate(dirs):
        device_storing_dir = _get_device_storing_dir(_dir)
        device_info = _get_device_info(device_storing_dir, devices_info)
        device_info_output = "" if device_info is None else " ".join(device_info)
        device_size = _get_dir_size(_dir)
        cursesswitch.print_string("%d: \t%s\t%s\t%s" % (dir_idx, _dir, device_size, device_info_output))
