#!/bin/sh
# Picker mode: pick a file or dir under the path given (default: the current dir), and print it.
# Other arguments go to dirdelta too, e.g. bin/pick.sh -x less some/dir, or bin/pick.sh cloud/eliran
[ $# -gt 0 ] || set -- .
exec "$(dirname "$0")/python" -m dirdelta "$@"
