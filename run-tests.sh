#!/bin/bash
set -e
cd "$(dirname "$0")"

# Use the repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PY=.venv/bin/python3
[ -x "$PY" ] || PY=python3

# The repo root makes the dirdelta package importable, lib/treepicker the picker library. Each test
# dir is discovered separately so their helper modules don't collide. Pass -v for per-test output.

echo "=== dirdelta (tests/) ==="
PYTHONPATH=.:lib/treepicker $PY -m unittest discover -s tests "$@"

echo "=== treepicker (lib/treepicker/tests/) ==="
PYTHONPATH=lib/treepicker $PY -m unittest discover -s lib/treepicker/tests "$@"
