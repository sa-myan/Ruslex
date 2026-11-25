"""Progress is live, flushed, and safe to inspect during long AI requests."""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from processing.progress import AIProgress


class ProgressTests(unittest.TestCase):
    def test_resume_batch_retry_and_paused_output(self):
        stream = io.StringIO()
        with redirect_stderr(stream):
            progress = AIProgress("stress", total=43, completed=4,
                                  batch_size=4, max_batches=1)
            progress.begin()
            progress.batch_start(number=2, first_id=317,
                                 last_id=457, count=4)
            progress.retry(first_id=317, last_id=457, attempt=1,
                           error="invalid ID", phase="primary")
            progress.saved(4, extra="batch file 000317-000457.json")
            progress.finish()
        displayed = stream.getvalue()
        self.assertIn("resuming 4 completed", displayed)
        self.assertIn("39 remaining", displayed)
        self.assertIn("batch 2/11 started", displayed)
        self.assertIn("correction", displayed.lower().replace("repairs", "correction"))
        self.assertIn("8/43 items", displayed)
        self.assertIn("35 remaining", displayed)
        self.assertIn("paused", displayed)
        self.assertIn("000317-000457.json", displayed)

    def test_instant_empty_stage_and_no_overcount(self):
        stream = io.StringIO()
        with redirect_stderr(stream):
            progress = AIProgress("pages", total=0, batch_size=2)
            progress.begin()
            progress.finish()
        self.assertIn("complete: 0/0", stream.getvalue())
        with self.assertRaises(ValueError):
            AIProgress("pages", total=1, completed=2, batch_size=1)
        with self.assertRaises(ValueError):
            AIProgress("pages", total=1, batch_size=0)
        with self.assertRaises(ValueError):
            AIProgress("pages", total=1, completed=1,
                       batch_size=1).saved(1)

    def test_terminal_failure_retains_counts(self):
        stream = io.StringIO()
        with redirect_stderr(stream):
            progress = AIProgress("lexemes", total=12,
                                  completed=8, batch_size=4)
            progress.failure(RuntimeError("provider unavailable"))
        displayed = stream.getvalue()
        self.assertIn("failed after 8/12 items", displayed)
        self.assertIn("saved batches remain available", displayed)
        self.assertIn("provider unavailable", displayed)


if __name__ == "__main__":
    unittest.main()
