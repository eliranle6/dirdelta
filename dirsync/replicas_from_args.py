import os
import sys

import cursesswitch


def get():
    replica_a = replica_b = None
    nr_args = len(sys.argv)
    if nr_args == 2:
        replica_a = sys.argv[1]
    elif nr_args == 3:
        replica_a = sys.argv[1]
        replica_b = sys.argv[2]
    elif nr_args > 3:
        cursesswitch.print_string("Invalid number of arguments.")
        sys.exit(1)
    if replica_a is not None:
        validate_replica(replica_a)
        replica_a = os.path.realpath(replica_a)
    if replica_b is not None:
        validate_replica(replica_b)
        replica_b = os.path.realpath(replica_b)
    return replica_a, replica_b


def validate_replica(replica_path):
    if replica_path is not None and not os.path.isdir(replica_path):
        cursesswitch.print_string("{} is not a directory".format(replica_path))
        sys.exit(1)
