ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# The Windows drive is mounted read-only, so only a dry run (the default) makes sense here
# Use the repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PY="$ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY=python3

PYTHONPATH="$ROOT" \
           "$PY" -m dirdelta \
           /mnt/win/Users/Johabab\ Glizerin/eliran/ \
           cloud/eliran
