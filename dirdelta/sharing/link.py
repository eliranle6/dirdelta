"""Handing the user a page's address, to open on their phone: on a screen as a QR code to scan, and
in an email to them (share())"""
from googleapiclient.errors import HttpError
from google.auth.exceptions import GoogleAuthError

from dirdelta.drive import driveapi
from dirdelta.known import settings
from dirdelta.known import users
from dirdelta.sharing import gmail
from dirdelta.sharing import qr
from dirdelta.ui import messages

BODY = ("%s:\n\n%s\n\nOpen it on a phone on the same Wi-Fi as the computer. The address has a key in it: "
        "whoever has it can see the page while it runs.\n")


def share(url, what, label=None):
    """Email url to the user (the address of Drive's login), saying it's for what (e.g. "Sort the
    imported photos"), then show it as a QR code on a screen under what (with label, see
    messages.progress_screen()), saying whether it was emailed, or why not, until Enter is pressed"""
    status = email(url, what)
    messages.show(what, ["Scan it with the phone's camera, or open it from your email:", ""] + qr.lines(url) +
                  ["", url, "", status], label)


def email(url, what):
    """Email url to the user (the address it was sent to before, else, for the owner, Drive's login's,
    kept for next time: Drive's account is the owner's, see users.py), saying it's for what. Returns
    what to say of it: where it went, or why it wasn't sent."""
    to = settings.email_address()
    if to is None and users.current() != users.OWNER:
        return "Not emailed: no address for %s (set it on the web page's user menu)" % (users.current(),)
    messages.print_line("Emailing the address to you...")
    try:
        to = to or driveapi.user_email()
        gmail.send(to, "dirdelta: %s" % (what,), BODY % (what, url))
        settings.set_email_address(to)
    except gmail.MailError as error:
        return "Not emailed: %s" % (error,)
    except (HttpError, GoogleAuthError, OSError) as error:
        return "Not emailed: no address (Drive's login: %s)" % (error,)
    return "Emailed to %s too." % (to,)
