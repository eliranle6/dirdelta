ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Picker mode: pick a file or dir under the path given (default: the current dir), and print it.
# Other arguments go to dirdelta too, e.g. bin/pick.sh -x less some/dir, or bin/pick.sh cloud/eliran
# Use the repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PY="$ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY=python3

[ $# -gt 0 ] || set -- .
PYTHONPATH="$ROOT" \
           "$PY" -m dirdelta "$@"
