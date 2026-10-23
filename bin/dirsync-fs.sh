ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Work on a copy, since Remove deletes real files
WORKDIR="$(mktemp -d)"
cp -r "$ROOT/tests/fixtures/alpha" "$ROOT/tests/fixtures/bravo" "$WORKDIR"
echo "Syncing copies of the fixtures in $WORKDIR"
# Prefer the venv next to the repo, which has the dependencies
PY="$ROOT/../dirstuff-venv/bin/python3"
[ -x "$PY" ] || PY=python3

PYTHONPATH="$ROOT/lib/treepicker" \
           "$PY" "$ROOT/dirdelta/main.py" \
           "$WORKDIR/alpha/" \
           "$WORKDIR/bravo/"
