.PHONY: build help test clean install deploy undeploy check_convention

# The repo's .venv if there is one, else whichever python3 is on PATH (e.g. an active venv)
PYTHON ?= $(if $(wildcard .venv/bin/python3),.venv/bin/python3,python3)

# dirpicker, the C++ picker dirdelta runs, built in its submodule
DIRPICKER = lib/cpptree/build/dirpicker

build:
	$(MAKE) -C lib/cpptree build/dirpicker

help:
	@echo "make build      build dirpicker (lib/cpptree/build/dirpicker), the picker dirdelta runs"
	@echo "make test       run the unit tests (ARGS=-v for per-test output)"
	@echo "make clean      remove caches and build output (keeps .venv, secrets/)"
	@echo "make install    pip install dirdelta (and dirpicker) into \$$PYTHON's environment"
	@echo "make deploy     install a dirdelta command into ~/.local/bin via pipx; rerun to update"
	@echo "make undeploy   remove the deployed command"

# The repo root makes the dirdelta package importable. dirpicker runs its own tests.
test:
	PYTHONPATH=. $(PYTHON) -m unittest discover -s tests $(ARGS)
	$(MAKE) -C lib/cpptree test

clean:
	find . \( -path ./.venv -o -path ./lib \) -prune -o \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
	rm -rf build AUTHORS ChangeLog *.egg-info .eggs
	$(MAKE) -C lib/cpptree clean

# dirpicker goes next to the environment's python (where its scripts go), which is where picker.py
# looks for it first
install: build
	$(PYTHON) -m pip install -U .
	install -m 755 $(DIRPICKER) "$$($(PYTHON) -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"

deploy: build
	pipx install --force .
	install -m 755 $(DIRPICKER) "$$(pipx environment --value PIPX_LOCAL_VENVS)/dirdelta/bin"

undeploy:
	pipx uninstall dirdelta

check_convention:
	pep8 dirdelta
