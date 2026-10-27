ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Sync mode: choose the two replicas from the menu (or a favorite or recent pair). A dry run unless
# DRYRUN=0 is set
# Use the repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PY="$ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY=python3

PYTHONPATH="$ROOT" \
           "$PY" -m dirdelta
