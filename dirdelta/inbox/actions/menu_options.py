"""The action menu's options but the moves: asking Claude or the AI, removing, opening"""
from dirdelta.inbox.constants import ASK, OPEN, READ, REMOVE
from dirdelta.inbox.formatting import Action, join_path, of_picked
from dirdelta.ui import filescreen
from dirdelta.ui import opening
from dirdelta.util import archives


class MenuOptions(object):
    """The other options (InboxSort's action menu's)"""

    def _ask_options(self, f):
        """The options that ask Claude or the AI: [(key, _Action)]"""
        return [
            (self.ASK_AI, Action("Ask AI what to do with %s, and review its plan" % (f.they,), None, ASK, [],
                                  lambda: self._ask_ai(f.relpaths, f.relpaths))),
            (self.DESCRIBE, Action("Describe %s with Claude, while you go on (sends it their contents)" %
                                    ("it" if f.is_one else of_picked(len(f.undescribed), len(f.relpaths)),),
                                    None if f.undescribed else "described", ASK, [],
                                    lambda: self.describe_in_background(f.undescribed))),
            # As Ctrl-I: the ones Claude placed already are asked about anew (they may have changed)
            (self.RECOMMEND, Action("Ask Claude where %s go%s in %s, while you go on%s" %
                                     ("it" if f.is_one else of_picked(len(f.askable), len(f.relpaths)), "es" if f.is_one else "",
                                      self.root_path, (" (anew: %s before)" % ("asked" if f.is_one else
                                                                               "%d asked" % (len(f.asked_before),)))
                                      if f.asked_before else ""),
                                     None if f.askable else "being asked", ASK, [],
                                     lambda: self.ask_in_background(f.askable, anew=True))),
            (self.ASK_DIR, Action("Ask Claude about %s as a whole: what it is, and where it goes, while you go on%s" %
                                   (f.the_dir, " (anew)" if f.dir_recommendation else ""),
                                   None if f.whole_dir and not self._claude.is_asking_dir(f.whole_dir) else
                                   "being asked" if f.whole_dir else "not a dir", ASK, [],
                                   lambda: self.ask_dir_in_background(f.whole_dir, f.relpaths),
                                   said=(ASK, " Claude, about %s, while you go on" % (f.the_dir,)))),
        ]

    def _removal_options(self, f):
        """The options that remove files: [(key, _Action)]"""
        return [
            (self.REMOVE_COPIES, Action("Remove %s: %s in %s%s" %
                                         ("it" if f.is_one else of_picked(len(f.removable), len(f.relpaths)),
                                          "a copy of a file" if f.is_one else "copies of files", self.root_path, f.not_yet),
                                         None if f.removable else "not a copy", REMOVE, [],
                                         lambda: self._remove(f.removable, ["  %s: a copy of %s" % (relpath, ', '.join(
                                             join_path(self.root_path, copy) for copy in self._copies(relpath)[:2]))
                                             for relpath in f.removable]), acted_on=f.removable)),
            (self.REMOVE_DIR, Action("Remove %s, as Claude says%s" %
                                      (f.the_dir, ": " + f.dir_recommendation['reason'] if f.dir_recommendation and
                                       f.dir_recommendation.get('reason') else "") if f.dir_action == 'remove' else "",
                                      None if f.dir_action == 'remove' else "no recommendation to remove it", REMOVE, [],
                                      lambda: self._remove(f.relpaths, ["  %s/: %s" % (f.whole_dir, f.dir_recommendation.get('reason') or
                                                                                      "Claude says so")] +
                                                           ["  " + relpath for relpath in f.relpaths], to_trash=True))),
            (self.REMOVE_JUNK, Action("Remove %s: %s like junk (to %s)" %
                                       ("it" if f.is_one else of_picked(len(f.junky), len(f.relpaths)),
                                        "it looks" if f.is_one or len(f.junky) == 1 else "they look",
                                        "Drive's trash" if self.inbox_is_cloud else "the trash"),
                                       None if f.junky else "not junk", REMOVE, [],
                                       lambda: self._remove(f.junky, ["  %s: %s" % (relpath, self._junk(relpath))
                                                                    for relpath in f.junky], to_trash=True),
                                       acted_on=f.junky)),
            # Not when it does what removing the copies does (all of them are), or the junk does
            # (all of them are, in Drive, where both go to its trash)
            (self.REMOVE, Action("Remove %s from %s" % (f.they, self.inbox_path),
                                  "the same as removing the copies" if len(f.removable) == len(f.relpaths) else
                                  "the same as removing the junk" if self.inbox_is_cloud and len(f.junky) == len(f.relpaths) else
                                  None, REMOVE, [], lambda: self._remove(f.relpaths))),
        ]

    def _other_options(self, f):
        """The options that explore, open or read anew: [(key, _Action)]"""
        return [
            (self.EXPLORE, Action("Explore it: what's in the zip", None if f.is_one and archives.is_archive(f.relpaths[0]) else
                                   "not a zip", OPEN, [], lambda: self._explore(f.relpaths[0], set(f.relpaths)),
                                   said=(OPEN, " look in it, unpacking nothing"))),
            (self.OPEN, Action("Open %s with %s program%s" %
                                (f.they, "its" if f.is_one else "their", "" if f.is_one else "s"),
                                None if len(f.relpaths) <= opening.names.MAX_OPENED else "too many", OPEN, [],
                                lambda: self._open(f.relpaths))),
            (self.READ_ANEW, Action("Read %s/ anew from Google Drive" % (join_path(self.inbox_path, f.folder),),
                                     None if self.inbox_is_cloud else "not Drive's", READ, [],
                                     lambda: filescreen.READ_ANEW, acted_on=[(f.folder or '.') + '/'])),
        ]
