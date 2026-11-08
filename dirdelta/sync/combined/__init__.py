"""The combined tree of a sync (docs/plans.md, plan C): one tree of everything that differs between
the two replicas, each file put in a state (skip, ⇒ make B like A, ⇐ make A like B; treepicker's
--state), with tabs for each group (only in A, only in B, differ, moved), then one plan to confirm, done in
one go. Moved pairs (moved.py) are one entry, and `a` asks AI to set the states (ask_ai.py).

Its parts are in the modules here; the names the rest of dirdelta uses are here too."""
from dirdelta.sync.combined.moved import find as find_moved  # noqa: F401
from dirdelta.sync.combined.screen import CombinedSync  # noqa: F401
