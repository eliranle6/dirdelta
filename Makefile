install:
	sudo pip install -U -r requirements.txt
	sudo pip install . -U

check_convention:
	pep8 dirsync

clean:
	rm -rf AUTHORS build ChangeLog dirsync.egg-info
