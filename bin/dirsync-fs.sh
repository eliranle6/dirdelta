ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Work on a copy, since Remove deletes real files
WORKDIR="$(mktemp -d)"
cp -r "$ROOT/tests/fixtures/alpha" "$ROOT/tests/fixtures/bravo" "$WORKDIR"
echo "Syncing copies of the fixtures in $WORKDIR"
# Use the repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PY="$ROOT/.venv/bin/python3"
[ -x "$PY" ] || PY=python3

PYTHONPATH="$ROOT" \
           "$PY" -m dirdelta \
           "$WORKDIR/alpha/" \
           "$WORKDIR/bravo/"
