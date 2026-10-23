# Installs into whichever environment's pip is first on PATH (activate a venv first)
install:
	pip install -U ./lib/treepicker .

check_convention:
	pep8 dirdelta

clean:
	rm -rf AUTHORS build ChangeLog dirdelta.egg-info
