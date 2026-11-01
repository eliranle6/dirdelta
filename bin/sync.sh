#!/bin/sh
# Sync mode: choose the two replicas from the menu (or a favorite or recent pair). A dry run unless
# DRYRUN=0 is set
exec "$(dirname "$0")/python" -m dirdelta
