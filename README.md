# file_age_retention

Deletes regular files in a directory older than a given age threshold, with an optional dry run and a structured report. Standard library only.

```python
import tempfile
from file_age_retention import FileAgeRetention, RetentionReport, RetentionResult

with tempfile.TemporaryDirectory() as d:
    fr = FileAgeRetention(max_age_seconds=60 * 60 * 24)  # one day
    report: RetentionReport = fr.run(d, dry_run=True)

    print("would delete", report.would_delete_count)
    print("retained  ", report.retained_count)
    for r in report.results:
        print(r.path, r.reason, round(r.age_seconds, 1))

    # Commit the deletion:
    fr.run(d, dry_run=False)
```

## Why this exists

Log and cache directories accumulate files until something breaks. Cron-driven `find ... -mtime +N -delete` works but is opaque: it prints nothing useful by default, swallows per-file errors, and gives you no structured handle on what happened. This library gives you a single callable that returns a report you can log, serialize, or branch on.

The trade-off is scope. This library deletes regular files in one directory, non-recursively. It does not walk subtrees, it does not follow or delete symlinks, and it does not match glob patterns. If you need those, wrap it — but the narrow surface is the point: a deletion tool that tries to do everything is a deletion tool that deletes the wrong thing eventually.

## The awkward edge

"Older than the threshold" means strictly greater than. A file whose age is exactly equal to `max_age_seconds` is **retained**, not deleted. This is deliberate: boundary-inclusive deletion races with scheduler jitter, where the same file is deleted on one run and kept on the next depending on which side of the second boundary the clock falls. If you need inclusive behaviour, pass `max_age_seconds - 1` and accept the imprecision, or adjust your threshold.

The clock is injectable (`FileAgeRetention(max_age_seconds, clock=...)`) for exactly this reason — tests pass a fake clock so the boundary is hit precisely and deterministically.

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

