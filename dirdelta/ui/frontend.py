"""Where dirdelta's screens are shown: the terminal (current is None: treepicker runs there, and messages
print there), or the web version's session (web/session.py), set by the daemon (web/daemon.py), which
does treepicker's commands and the messages in the browser"""

# The web version's Session, or None for the terminal
current = None
