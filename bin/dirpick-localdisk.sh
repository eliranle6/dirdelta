ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Prefer the venv next to the repo, which has the dependencies
PY="$ROOT/../dirstuff-venv/bin/python3"
[ -x "$PY" ] || PY=python3

PYTHONPATH="$ROOT/lib/treepicker" \
           "$PY" "$ROOT/dirdelta/main.py" .
