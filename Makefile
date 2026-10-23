.PHONY: install deploy undeploy check_convention clean

# Installs into whichever environment's pip is first on PATH (activate a venv first)
install:
	pip install -U ./lib/treepicker .

# Deploys a `dirdelta` command into ~/.local/bin with its own venv, via pipx. Rerun to update.
# treepicker isn't on PyPI, so it's injected into dirdelta's venv from the submodule.
deploy:
	pipx install --force .
	pipx inject --force dirdelta ./lib/treepicker

undeploy:
	pipx uninstall dirdelta

check_convention:
	pep8 dirdelta

clean:
	rm -rf AUTHORS build ChangeLog dirdelta.egg-info
