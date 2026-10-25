.PHONY: build help test clean install deploy undeploy check_convention

# The repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PYTHON ?= $(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3)

# dirdelta's C++ programs, built in their submodule: treepick (the pickers) and dirdiff (diffing
# two local dirs)
PROGRAMS = lib/cpptree/build/treepick lib/cpptree/build/dirdiff

build:
	$(MAKE) -C lib/cpptree $(patsubst lib/cpptree/%,%,$(PROGRAMS))

help:
	@echo "make build      build dirdelta's C++ programs (treepick, dirdiff) in lib/cpptree/build"
	@echo "make test       run the unit tests (ARGS=-v for per-test output)"
	@echo "make clean      remove caches and build output (keeps .venv, secrets/)"
	@echo "make install    pip install dirdelta (and its C++ programs) into \$$PYTHON's environment"
	@echo "make deploy     install a dirdelta command into ~/.local/bin via pipx; rerun to update"
	@echo "make undeploy   remove the deployed command"

# The repo root makes the dirdelta package importable. treepick runs its own tests.
# Some tests run dirdiff, so the programs are built first
test: build
	PYTHONPATH=. $(PYTHON) -m unittest discover -s tests $(ARGS)
	$(MAKE) -C lib/cpptree test

clean:
	find . \( -path ./.venv -o -path ./lib \) -prune -o \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
	rm -rf build AUTHORS ChangeLog *.egg-info .eggs
	$(MAKE) -C lib/cpptree clean

# The C++ programs go next to the environment's python (where its scripts go), which is where
# programs.find() looks first
install: build
	$(PYTHON) -m pip install -U .
	install -m 755 $(PROGRAMS) "$$($(PYTHON) -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"

deploy: build
	pipx install --force .
	install -m 755 $(PROGRAMS) "$$(pipx environment --value PIPX_LOCAL_VENVS)/dirdelta/bin"

undeploy:
	pipx uninstall dirdelta

check_convention:
	pep8 dirdelta
