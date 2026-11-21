"""The combined tree's AI, as the sort's: Ctrl-I asks it about the selection's files in the background,
each file's suggestion shown after its name and in the right column as it comes, Ctrl-A sets the arrows
it suggests in the tree that's shown"""
import threading
from unittest import mock

from dirdelta.claude import aiplan
from dirdelta.matching import differing
from dirdelta.sync.combined import ai_showing
from dirdelta.sync.combined import ask_ai
from dirdelta.sync.combined import plan as plans
from dirdelta.sync.combined import screen
from dirdelta.sync.combined import suggestions
from dirdelta.ui import picker
from dirdelta.ui.picker import updates
from combined_support import ReplicasTest

CHANGE = differing.Change(1, 2, None, None, differing.BY_SIZE)


class AITest(ReplicasTest):
    def setUp(self):
        super().setUp()
        self.sync = screen.CombinedSync(self.replica_a, self.replica_b, self.path_a, self.path_b,
                                        ['gone.txt', 'new/a.txt'], ['b.txt', 'old/b2.txt'],
                                        differing.Changes({'both.txt': CHANGE}))
        self.asked = []
        # The AI: ⇒ for new/a.txt, nothing for the rest (its summary says why)
        self.released = threading.Event()
        self.released.set()

        def make(task, instruction):
            self.released.wait()
            self.asked.append(([file.relpath for file in task.files], list(task.focus), instruction))
            steps = [aiplan.Step(plans.TO_B, file.relpath, None, "it's new") for file in task.files
                     if file.relpath == 'new/a.txt']
            return aiplan.Plan("The rest are unclear", steps, [])
        patcher = mock.patch('dirdelta.claude.aiplan.make', side_effect=make)
        patcher.start()
        self.addCleanup(patcher.stop)

    def shown(self, relpath):
        shown = self.sync._shown_as()[relpath]
        return picker.unstyled(shown.text if isinstance(shown, picker.Stated) else shown)

    def test_ctrl_i_asks_about_the_selections_files_which_it_may_read(self):
        self.sync._on_key(ask_ai.SUGGEST_KEY, 'new')
        self.sync.suggestions.wait()
        self.assertEqual(self.asked, [(['new/a.txt'], ['new/a.txt'], suggestions.SUGGESTION)])
        self.assertEqual(self.sync.suggestions.suggestion('new/a.txt'), suggestions.Suggestion(plans.TO_B, "it's new"))

    def test_while_its_asked_the_file_and_the_status_say_so_then_its_suggestion_shows(self):
        self.released.clear()
        self.sync._on_key(ask_ai.SUGGEST_KEY, '')
        self.assertIn(ai_showing.LOOKING, self.shown('new/a.txt'))
        self.assertIn("AI: asking about 5 files", picker.unstyled(self.sync._shown_as()['']))
        self.released.set()
        self.sync.suggestions.wait()
        self.assertEqual(self.shown('new/a.txt'), "a.txt  only in LocalDisk:A  [ai: ⇒ LocalDisk:B]")
        # What it left out is to be left, as its summary says
        self.assertEqual(self.shown('b.txt'), "b.txt  only in LocalDisk:B  [ai: leave it]")
        self.assertEqual(self.sync.suggestions.suggestion('b.txt').reason, "The rest are unclear")
        # Done: said no more
        self.assertEqual(picker.unstyled(self.sync._shown_as()['']), '')

    def test_the_files_are_asked_about_a_batch_at_a_time(self):
        files = ['f%02d.txt' % (i,) for i in range(suggestions.BATCH_SIZE + 3)]
        sync = screen.CombinedSync(self.replica_a, self.replica_b, self.path_a, self.path_b, files, [], differing.Changes())
        sync._on_key(ask_ai.SUGGEST_KEY, '')
        sync.suggestions.wait()
        self.assertEqual([len(asked[0]) for asked in self.asked], [suggestions.BATCH_SIZE, 3])

    def test_a_failure_is_shown_and_said(self):
        with mock.patch('dirdelta.claude.aiplan.make', side_effect=OSError("Not logged in")):
            self.sync._on_key(ask_ai.SUGGEST_KEY, 'new/a.txt')
            self.sync.suggestions.wait()
        self.assertIn("[ai: couldn't say]", self.shown('new/a.txt'))
        lines = [picker.unstyled(line) for line in self.sync._file_preview('new/a.txt')]
        self.assertIn("Recommendation (ai): failed", lines)
        self.assertIn("  Not logged in", lines)

    def test_the_right_column_says_what_it_suggests_and_why_or_how_to_ask(self):
        self.assertIn("  Ctrl-I asks AI", [picker.unstyled(line) for line in self.sync._file_preview('new/a.txt')])
        self.sync._on_key(ask_ai.SUGGEST_KEY, 'new')
        self.sync.suggestions.wait()
        lines = [picker.unstyled(line) for line in self.sync._file_preview('new/a.txt')]
        self.assertEqual(lines[lines.index("Recommendation (ai):"):],
                         ["Recommendation (ai):", "  ⇒ make LocalDisk:B like LocalDisk:A", "", "  it's new", "  Ctrl-A sets its arrow so"])
        # A dir's: what it suggests for its files, in all
        dir_lines = [picker.unstyled(line) for line in self.sync._dir_previews()['']]
        # (Wrapped, as the names are long)
        self.assertIn("⇒ make LocalDisk:B like LocalDisk:A: 1 file", " ".join(line.strip() for line in dir_lines))

    def test_ctrl_a_puts_the_selections_files_in_the_states_it_suggests_once(self):
        self.sync._on_key(ask_ai.SUGGEST_KEY, '')
        self.sync.suggestions.wait()
        self.sync._on_key(ask_ai.APPLY_KEY, 'new')
        shown = self.sync._shown_as()
        self.assertEqual((shown['new/a.txt'].state, shown['new/a.txt'].generation), (plans.TO_B, 1))
        # Only the selection's
        self.assertNotIsInstance(shown['b.txt'], picker.Stated)
        # Sent to treepicker with the state once: its text changing after doesn't put it back in it
        line = updates._update('new/a.txt', shown['new/a.txt'])
        self.assertTrue(line.endswith('\tstate=' + plans.TO_B))
        changed = picker.Stated('a.txt  changed', plans.TO_B, 1)
        self.assertNotIn('state=', updates._update('new/a.txt', changed, shown['new/a.txt']))
        # Ctrl-A again: again
        self.sync._on_key(ask_ai.APPLY_KEY, 'new')
        again = self.sync._shown_as()['new/a.txt']
        self.assertIn('state=', updates._update('new/a.txt', again, shown['new/a.txt']))

    def test_the_previews_are_sent_again_as_they_change(self):
        sends = []

        def send(found=None, default=None):
            sends.append(dict(found or {}))
            if len(sends) == 1:
                self.sync._on_key(ask_ai.SUGGEST_KEY, 'new/a.txt')
                self.sync.suggestions.wait()
            if len(sends) == 3:
                raise picker.PickerClosed()
        with self.assertRaises(picker.PickerClosed):
            self.sync._send_previews(send)
        self.assertIn('new/a.txt', sends[0])
        # Then only what changed: the file, and its dirs
        self.assertEqual(sorted(sends[1]), ['', 'new', 'new/a.txt'])
