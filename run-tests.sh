#!/bin/bash
set -e
cd "$(dirname "$0")"

# Use the repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PY=.venv/bin/python3
[ -x "$PY" ] || PY=python3

# dirdelta's modules import each other by bare module name, while the picker library uses
# package-style imports, so each test dir gets its own PYTHONPATH. Pass -v for per-test output.

echo "=== dirdelta (tests/) ==="
PYTHONPATH=dirdelta:lib/treepicker $PY -m unittest discover -s tests "$@"

echo "=== treepicker (lib/treepicker/tests/) ==="
PYTHONPATH=lib/treepicker $PY -m unittest discover -s lib/treepicker/tests "$@"
