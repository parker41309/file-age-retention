import os
import shutil
import tempfile
import unittest

from file_age_retention import FileAgeRetention, RetentionReport, RetentionResult


class _FakeClock:
    """Deterministic clock. Returns whatever value is set on ``.now``."""

    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


class _TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="far_")
        self.addCleanup(shutil.rmtree, self._tmp)

    def _touch(self, name: str, mtime: float) -> str:
        p = os.path.join(self._tmp, name)
        with open(p, "w") as f:
            f.write("")
        os.utime(p, (mtime, mtime))
        return p

    def _mkdir(self, name: str) -> str:
        p = os.path.join(self._tmp, name)
        os.mkdir(p)
        return p


class TestConstruction(unittest.TestCase):
    def test_negative_threshold_raises(self) -> None:
        with self.assertRaises(ValueError):
            FileAgeRetention(-1)

    def test_zero_threshold_is_allowed(self) -> None:
        # Zero is a legal boundary: every file older than "now" (strictly)
        # is deleted. A file whose mtime equals now is retained.
        fr = FileAgeRetention(0)
        self.assertEqual(fr._max_age_seconds, 0.0)


class TestBoundary(_TempDirTestCase):
    def test_file_at_exactly_threshold_is_retained(self) -> None:
        # now = 1000, threshold = 100, file mtime = 900 => age == 100
        # Strict greater-than means this file is RETAINED.
        self._touch("boundary.txt", 900.0)
        clock = _FakeClock(1000.0)
        fr = FileAgeRetention(100.0, clock=clock)
        report = fr.run(self._tmp)
        self.assertEqual(report.deleted_count, 0)
        self.assertEqual(report.retained_count, 1)
        self.assertEqual(report.results[0].reason, "retained_young")

    def test_file_just_past_threshold_is_deleted(self) -> None:
        # age = 100.5 > 100 => deleted
        self._touch("old.txt", 899.5)
        clock = _FakeClock(1000.0)
        fr = FileAgeRetention(100.0, clock=clock)
        report = fr.run(self._tmp)
        self.assertEqual(report.deleted_count, 1)
        self.assertTrue(os.path.exists(self._tmp))  # dir still there
        self.assertFalse(os.path.exists(os.path.join(self._tmp, "old.txt")))


class TestDryRun(_TempDirTestCase):
    def test_dry_run_does_not_delete(self) -> None:
        p = self._touch("old.txt", 800.0)
        clock = _FakeClock(1000.0)
        fr = FileAgeRetention(100.0, clock=clock)
        report = fr.run(self._tmp, dry_run=True)
        self.assertEqual(report.would_delete_count, 1)
        self.assertEqual(report.deleted_count, 0)
        self.assertTrue(os.path.exists(p))
        self.assertEqual(report.results[0].reason, "would_delete")
        self.assertEqual(report.results[0].deleted, False)
        self.assertEqual(report.results[0].would_delete, True)


class TestNonRegularFiles(_TempDirTestCase):
    def test_subdirectory_is_retained_not_deleted(self) -> None:
        d = self._mkdir("subdir")
        clock = _FakeClock(100000.0)
        fr = FileAgeRetention(1.0, clock=clock)
        report = fr.run(self._tmp)
        self.assertEqual(report.deleted_count, 0)
        self.assertTrue(os.path.isdir(d))
        self.assertEqual(report.results[0].reason, "retained_not_regular")

    def test_symlink_is_not_followed_or_deleted(self) -> None:
        # A symlink to a regular file should be ignored entirely, never removed.
        # The target is young so it survives on its own; the symlink must not
        # be deleted either.
        target = self._touch("target.txt", 99999.0)
        link = os.path.join(self._tmp, "link.txt")
        os.symlink(target, link)
        clock = _FakeClock(100000.0)
        fr = FileAgeRetention(1.0, clock=clock)
        report = fr.run(self._tmp)
        self.assertEqual(report.deleted_count, 0)
        self.assertTrue(os.path.exists(target))
        self.assertTrue(os.path.islink(link))
        reasons = [r.reason for r in report.results]
        self.assertIn("retained_not_regular", reasons)


class TestMissingDirectory(_TempDirTestCase):
    def test_nonexistent_directory_raises(self) -> None:
        fr = FileAgeRetention(100.0, clock=_FakeClock(1000.0))
        missing = os.path.join(self._tmp, "does_not_exist")
        with self.assertRaises(FileNotFoundError):
            fr.run(missing)

    def test_file_as_directory_raises(self) -> None:
        f = self._touch("not_a_dir.txt", 900.0)
        fr = FileAgeRetention(100.0, clock=_FakeClock(1000.0))
        with self.assertRaises(NotADirectoryError):
            fr.run(f)


class TestReportShape(_TempDirTestCase):
    def test_report_has_expected_fields_and_types(self) -> None:
        self._touch("a.txt", 800.0)
        clock = _FakeClock(1000.0)
        fr = FileAgeRetention(100.0, clock=clock)
        report = fr.run(self._tmp, dry_run=True)
        self.assertIsInstance(report, RetentionReport)
        self.assertEqual(report.target_dir, self._tmp)
        self.assertEqual(report.max_age_seconds, 100.0)
        self.assertTrue(report.dry_run)
        self.assertIsInstance(report.results, list)
        self.assertIsInstance(report.results[0], RetentionResult)
        self.assertIsInstance(report.results[0].age_seconds, float)

    def test_mixed_directory_contents(self) -> None:
        young = self._touch("young.txt", 999.0)
        old = self._touch("old.txt", 800.0)
        self._mkdir("subdir")
        clock = _FakeClock(1000.0)
        fr = FileAgeRetention(100.0, clock=clock)
        report = fr.run(self._tmp)
        self.assertEqual(report.deleted_count, 1)
        self.assertEqual(report.retained_count, 2)
        self.assertEqual(report.error_count, 0)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(young))


class TestEmptyDirectory(_TempDirTestCase):
    def test_empty_directory_yields_empty_report(self) -> None:
        fr = FileAgeRetention(100.0, clock=_FakeClock(1000.0))
        report = fr.run(self._tmp)
        self.assertEqual(report.deleted_count, 0)
        self.assertEqual(report.retained_count, 0)
        self.assertEqual(report.error_count, 0)
        self.assertEqual(report.results, [])


class TestZeroThreshold(_TempDirTestCase):
    def test_zero_threshold_deletes_old_keeps_now(self) -> None:
        # mtime == now => age == 0, not > 0, retained.
        # mtime < now => age > 0, deleted.
        kept = self._touch("now.txt", 1000.0)
        gone = self._touch("past.txt", 999.0)
        clock = _FakeClock(1000.0)
        fr = FileAgeRetention(0.0, clock=clock)
        report = fr.run(self._tmp)
        self.assertEqual(report.deleted_count, 1)
        self.assertTrue(os.path.exists(kept))
        self.assertFalse(os.path.exists(gone))


if __name__ == "__main__":
    unittest.main()
