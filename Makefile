.PHONY: help test clean install deploy undeploy check_convention

# The repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PYTHON ?= $(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3)

help:
	@echo "make test       run the unit tests (ARGS=-v for per-test output)"
	@echo "make clean      remove caches and build output (keeps .venv, secrets/)"
	@echo "make install    pip install the picker library and dirdelta into \$$PYTHON's environment"
	@echo "make deploy     install a dirdelta command into ~/.local/bin via pipx; rerun to update"
	@echo "make undeploy   remove the deployed command"

# The repo root makes the dirdelta package importable, lib/treepicker the picker library. Each test
# dir is discovered separately so their helper modules don't collide.
test:
	PYTHONPATH=.:lib/treepicker $(PYTHON) -m unittest discover -s tests $(ARGS)
	PYTHONPATH=lib/treepicker $(PYTHON) -m unittest discover -s lib/treepicker/tests $(ARGS)

clean:
	find . -path ./.venv -prune -o \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
	rm -rf build AUTHORS ChangeLog *.egg-info
	rm -rf lib/treepicker/build lib/treepicker/AUTHORS lib/treepicker/ChangeLog lib/treepicker/*.egg-info

install:
	$(PYTHON) -m pip install -U ./lib/treepicker .

# treepicker isn't on PyPI, so it's injected into dirdelta's pipx venv from the submodule
deploy:
	pipx install --force .
	pipx inject --force dirdelta ./lib/treepicker

undeploy:
	pipx uninstall dirdelta

check_convention:
	pep8 dirdelta
