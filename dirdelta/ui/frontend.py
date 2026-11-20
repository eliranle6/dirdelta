"""Where dirdelta's screens are shown: the terminal (current is None: treepicker runs there, and messages
print there), or the web version's session (web/session.py), set by the daemon (web/daemon.py), which
does treepicker's commands and the messages in the browser"""

# The web version's Session, or None for the terminal
current = None


def show_replicas(pair):
    """Say which two replicas the screens about to be shown are about: [(path, name), (path, name)], A's
    first (the web version's pages show them with their icons and colors; the terminal's show the names)"""
    if current is not None:
        current.replicas = pair
