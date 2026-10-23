#!/bin/bash
set -e
cd "$(dirname "$0")"

VENV_PY=../dirstuff-venv/bin/python3

echo "=== dirtree ==="
PYTHONPATH=dirdelta:tests $VENV_PY -m unittest test_dirtree -v

echo "=== findcmdwrapper ==="
PYTHONPATH=dirdelta:tests $VENV_PY -m unittest test_findcmdwrapper -v

echo "=== localdiskdirtree ==="
PYTHONPATH=dirdelta:tests:lib/treepicker $VENV_PY -m unittest test_localdiskdirtree -v

echo "=== menu ==="
PYTHONPATH=dirdelta:tests:lib/treepicker $VENV_PY -m unittest test_menu -v

echo "=== treepicker.pagination ==="
PYTHONPATH=lib/treepicker:lib/treepicker/tests $VENV_PY -m unittest test_pagination -v

echo "=== treepicker.treeprinter ==="
PYTHONPATH=lib/treepicker:lib/treepicker/tests $VENV_PY -m unittest test_treeprinter -v

echo "=== treepicker.treepickermodel ==="
PYTHONPATH=lib/treepicker:lib/treepicker/tests $VENV_PY -m unittest test_treepickermodel -v

echo "=== treepicker.treesearch ==="
PYTHONPATH=lib/treepicker:lib/treepicker/tests $VENV_PY -m unittest test_treesearch -v

echo "=== treepicker.treenavigator ==="
PYTHONPATH=lib/treepicker:lib/treepicker/tests $VENV_PY -m unittest test_treenavigator -v

echo "=== treepicker.treeops ==="
PYTHONPATH=lib/treepicker:lib/treepicker/tests $VENV_PY -m unittest test_treeops -v
