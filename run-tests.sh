#!/bin/bash
set -e
cd "$(dirname "$0")"

VENV_PY=../dirstuff-venv/bin/python3

# dirdelta's modules import each other by bare module name, while the picker library uses
# package-style imports, so each test dir gets its own PYTHONPATH. Pass -v for per-test output.

echo "=== dirdelta (tests/) ==="
PYTHONPATH=dirdelta:lib/treepicker $VENV_PY -m unittest discover -s tests "$@"

echo "=== treepicker (lib/treepicker/tests/) ==="
PYTHONPATH=lib/treepicker $VENV_PY -m unittest discover -s lib/treepicker/tests "$@"
