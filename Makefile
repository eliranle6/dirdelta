.PHONY: build venv sources help test clean install deploy undeploy serve service unservice check_convention

# Nothing generated goes in the repo, so it can be copied as it is: this copy's programs, bytecode and
# install's leftovers go in OUT, by its path, and the one venv of all the copies next to it
OUT := $(shell bin/builddir)
VENV := $(dir $(OUT))venv
# make venv's if there is one, else whichever python3 is on PATH (e.g. an active venv)
PYTHON ?= $(if $(wildcard $(VENV)/bin/python3),$(VENV)/bin/python3,python3)
export PYTHONPYCACHEPREFIX := $(OUT)/pycache
export DIRDELTA_PROGRAMS_DIR := $(OUT)/treepicker

# dirdelta's C++ programs, built from their submodule: treepicker (the pickers) and dirdiff (diffing
# two local dirs). (BUILD is the submodule's own Makefile's.)
PROGRAMS = $(OUT)/treepicker/treepicker $(OUT)/treepicker/dirdiff
TREEPICKER = $(MAKE) -C lib/treepicker BUILD=$(OUT)/treepicker
# What's installed: a copy of the sources, so pip and pbr leave their files there, not here. No git
# there for pbr's version: it's setup.cfg's.
SOURCES = $(OUT)/src
export PBR_VERSION := $(shell sed -n 's/^version = //p' setup.cfg)

build:
	$(TREEPICKER) $(PROGRAMS)

venv:
	test -x $(VENV)/bin/python3 || python3 -m venv $(VENV)
	$(VENV)/bin/python3 -m pip install -r requirements.txt

help:
	@echo "make venv       make the venv of dirdelta's dependencies (in $(VENV))"
	@echo "make build      build dirdelta's C++ programs (treepicker, dirdiff, in $(OUT))"
	@echo "make test       run the unit tests, in parallel (ARGS=-v for per-test output, ARGS=test_x for one module)"
	@echo "make clean      remove caches and build output (keeps the venv, secrets/)"
	@echo "make install    pip install dirdelta (and its C++ programs) into \$$PYTHON's environment"
	@echo "make deploy     install a dirdelta command into ~/.local/bin via pipx; rerun to update"
	@echo "make undeploy   remove the deployed command"
	@echo "make serve      run the daemon from here: the web version, and the watch for phones and replicas"
	@echo "make service    deploy, then run the deployed daemon as a systemd user service (started with the session)"
	@echo "make unservice  stop that service and remove it"

# The repo root makes the dirdelta package importable. treepicker runs its own tests.
# Some tests run dirdiff, so the programs are built first. The modules run in parallel (tests/run.py),
# their temp files in memory if there's /dev/shm (SQLite's syncs to a disk were half the time)
TEST_TMPDIR := $(if $(wildcard /dev/shm),/dev/shm,$(TMPDIR))
test: build
	TMPDIR=$(TEST_TMPDIR) PYTHONPATH=. $(PYTHON) tests/run.py $(ARGS)
	$(TREEPICKER) test

# (Also what older versions left in the repo)
clean:
	find . \( -path ./.venv -o -path ./lib \) -prune -o \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
	rm -rf build AUTHORS ChangeLog *.egg-info .eggs lib/treepicker/build $(OUT)

sources:
	rm -rf $(SOURCES)
	mkdir -p $(SOURCES)
	cp -r dirdelta setup.py setup.cfg requirements.txt $(SOURCES)

# The C++ programs go next to the environment's python (where its scripts go), which is where
# programs.find() looks
install: build sources
	cd $(SOURCES) && $(abspath $(PYTHON)) -m pip install -U .
	install -m 755 $(PROGRAMS) "$$($(PYTHON) -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"

deploy: build sources
	pipx install --force $(SOURCES)
	install -m 755 $(PROGRAMS) "$$(pipx environment --value PIPX_LOCAL_VENVS)/dirdelta/bin"

undeploy:
	pipx uninstall dirdelta

# The daemon (dirdelta --serve): its link is printed, and kept in ~/.config/dirdelta/web.json
serve:
	bin/python -m dirdelta --serve $(ARGS)

# The deployed daemon as a systemd user service, with this copy's secrets/ (an installed copy has none of
# its own); DRYRUN=0 in its unit (systemctl --user edit dirdelta) makes it change files
SERVICE := $(HOME)/.config/systemd/user/dirdelta.service
service: deploy
	mkdir -p $(dir $(SERVICE))
	printf '[Unit]\nDescription=dirdelta: the web version, and the watch for phones and replicas\nAfter=network-online.target\n\n[Service]\nExecStart=%s --serve\nEnvironment=DIRDELTA_SECRETS_DIR=%s\nRestart=on-failure\n\n[Install]\nWantedBy=default.target\n' \
		"$(HOME)/.local/bin/dirdelta" "$(abspath secrets)" > $(SERVICE)
	systemctl --user daemon-reload
	systemctl --user enable --now dirdelta.service

unservice:
	-systemctl --user disable --now dirdelta.service
	rm -f $(SERVICE)
	systemctl --user daemon-reload

check_convention:
	pep8 dirdelta
