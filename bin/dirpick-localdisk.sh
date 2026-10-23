ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Use the repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PY="$ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY=python3

PYTHONPATH="$ROOT:$ROOT/lib/treepicker" \
           "$PY" -m dirdelta .
