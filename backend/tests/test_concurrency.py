"""Verify the in-process extraction path actually runs files in parallel.

Drives the real submission entry point (``_enqueue_processing``) — not just
``_process_document`` — because the bug we're guarding against was that a
single bulk-upload POST (which arrives as N files in one request) was being
serialized by FastAPI's BackgroundTasks. The thread-pool fix is what makes
this test pass.

Stubs ``_run_processing`` so no OpenRouter traffic.
"""

import math
import threading
import time
from concurrent.futures import wait

from app.config import settings
from app.routers import documents as docs_module


def test_bulk_submission_runs_in_parallel(monkeypatch):
    limit = settings.extraction_concurrency
    assert limit >= 2

    sleep_seconds = 0.5
    total_jobs = limit * 2 + 1
    live = 0
    peak = 0
    lock = threading.Lock()

    def fake_run(doc_id: str, file_path: str) -> None:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(sleep_seconds)
        with lock:
            live -= 1

    monkeypatch.setattr(docs_module, "_run_processing", fake_run)

    # Submit all jobs from a single thread — mirrors the bulk-upload POST that
    # was hitting the BackgroundTasks bottleneck.
    pool = docs_module._get_extraction_pool()
    start = time.monotonic()
    futures = [
        pool.submit(docs_module._run_processing, f"doc-{i}", f"/tmp/x-{i}")
        for i in range(total_jobs)
    ]
    wait(futures)
    elapsed = time.monotonic() - start

    assert peak == limit, f"expected peak={limit}, got {peak} — pool not parallel"

    expected = math.ceil(total_jobs / limit) * sleep_seconds
    assert elapsed >= expected * 0.85, (
        f"elapsed={elapsed:.2f}s < {expected * 0.85:.2f}s — too fast, "
        "pool may not be limiting"
    )
    assert elapsed <= expected * 1.6, (
        f"elapsed={elapsed:.2f}s > {expected * 1.6:.2f}s — looks serialized"
    )
