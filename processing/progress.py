"""Consistent, live terminal progress for every on-demand AI pipeline.

Writes to stderr and flushes before provider calls. stdout remains reserved
for structured command results. No prompts, secrets or full model outputs are
ever printed. Existing saved batches count toward resumed progress.
"""
from __future__ import annotations

import math
import sys
import time


class AIProgress:
    def __init__(self, stage: str, *, total: int, completed: int = 0,
                 batch_size: int, max_batches: int | None = None):
        if total < 0 or completed < 0 or completed > total or batch_size < 1:
            raise ValueError("Invalid AI progress totals")
        self.stage = stage
        self.total = total
        self.completed = completed
        self.batch_size = batch_size
        self.max_batches = max_batches
        self.started = time.monotonic()
        self.new_batches = 0
        self.total_batches = math.ceil(total / batch_size) if total else 0

    def line(self, message: str) -> None:
        print(f"[AI {self.stage}] {message}", file=sys.stderr, flush=True)

    def begin(self) -> None:
        resumed = f" (resuming {self.completed} completed)" if self.completed else ""
        limit = f"; max {self.max_batches} new batches this run" if self.max_batches else ""
        self.line(f"start: {self.completed}/{self.total} items completed{resumed}; "
                  f"{self.total - self.completed} remaining; "
                  f"batch size {self.batch_size}{limit}")

    def batch_start(self, *, number: int, first_id: int, last_id: int,
                    count: int) -> None:
        self.line(f"batch {number}/{self.total_batches} started: "
                  f"IDs {first_id}-{last_id}, {count} items; "
                  f"{self.completed}/{self.total} completed")

    def retry(self, *, first_id: int, last_id: int,
              attempt: int, error: str, phase: str = "validation") -> None:
        self.line(f"IDs {first_id}-{last_id}: {phase} validation failed "
                  f"({attempt}/2 repairs); {error[:160]}. Retrying")

    def saved(self, count: int, *, extra: str = "") -> None:
        if count < 0 or self.completed + count > self.total:
            raise ValueError("AI batch progress exceeds total input count")
        self.completed += count
        self.new_batches += 1
        elapsed = round(time.monotonic() - self.started, 1)
        suffix = f"; {extra}" if extra else ""
        self.line(f"saved: {self.completed}/{self.total} items "
                  f"({self.total - self.completed} remaining); "
                  f"{self.new_batches} new batch(es); {elapsed:.1f}s elapsed{suffix}")

    def finish(self) -> None:
        elapsed = round(time.monotonic() - self.started, 1)
        state = "complete" if self.completed == self.total else "paused"
        self.line(f"{state}: {self.completed}/{self.total} items; "
                  f"{self.total - self.completed} remaining; "
                  f"{self.new_batches} new batch(es); {elapsed:.1f}s elapsed")

    def failure(self, reason: Exception | str) -> None:
        self.line(f"failed after {self.completed}/{self.total} items; "
                  f"saved batches remain available for resumption; {str(reason)[:180]}")
