.PHONY: build help test clean install deploy undeploy check_convention

# The repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PYTHON ?= $(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3)
# The same interpreter for the submodule's own targets, which run from inside lib/treepicker
SUBMAKE = $(MAKE) -C lib/treepicker PYTHON=$(if $(findstring /,$(PYTHON)),$(abspath $(PYTHON)),$(PYTHON))

# dirpicker, the C++ picker dirdelta runs, built in its submodule
DIRPICKER = lib/cpptree/build/dirpicker

build:
	$(MAKE) -C lib/cpptree build/dirpicker

help:
	@echo "make build      build dirpicker (lib/cpptree/build/dirpicker), the picker dirdelta runs"
	@echo "make test       run the unit tests (ARGS=-v for per-test output)"
	@echo "make clean      remove caches and build output (keeps .venv, secrets/)"
	@echo "make install    pip install the picker library and dirdelta into \$$PYTHON's environment"
	@echo "make deploy     install a dirdelta command into ~/.local/bin via pipx; rerun to update"
	@echo "make undeploy   remove the deployed command"

# The repo root makes the dirdelta package importable, lib/treepicker the picker library. The picker
# library runs its own tests.
test:
	PYTHONPATH=.:lib/treepicker $(PYTHON) -m unittest discover -s tests $(ARGS)
	$(SUBMAKE) test ARGS="$(ARGS)"
	$(MAKE) -C lib/cpptree test

clean:
	find . \( -path ./.venv -o -path ./lib/treepicker \) -prune -o \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
	rm -rf build AUTHORS ChangeLog *.egg-info
	$(SUBMAKE) clean
	$(MAKE) -C lib/cpptree clean

install:
	$(SUBMAKE) install
	$(PYTHON) -m pip install -U .

# treepicker isn't on PyPI, so it's injected into dirdelta's pipx venv from the submodule
deploy:
	pipx install --force .
	pipx inject --force dirdelta ./lib/treepicker

undeploy:
	pipx uninstall dirdelta

check_convention:
	pep8 dirdelta
