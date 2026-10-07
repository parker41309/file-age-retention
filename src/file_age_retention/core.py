from __future__ import annotations

import os
import time
import dataclasses
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple


__all__ = ["RetentionReport", "RetentionResult", "FileAgeRetention"]


@dataclass(frozen=True)
class RetentionResult:
    path: str
    age_seconds: float
    deleted: bool
    would_delete: bool
    reason: str
    error: Optional[str] = None


@dataclass
class RetentionReport:
    dry_run: bool
    target_dir: str
    max_age_seconds: float
    results: List[RetentionResult] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    would_delete: List[str] = field(default_factory=list)
    retained: List[str] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)

    @property
    def would_delete_count(self) -> int:
        return len(self.would_delete)

    @property
    def retained_count(self) -> int:
        return len(self.retained)

    @property
    def error_count(self) -> int:
        return len(self.errors)


class FileAgeRetention:
    def __init__(
        self,
        max_age_seconds: float,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_age_seconds < 0:
            raise ValueError(
                f"max_age_seconds must be non-negative, got {max_age_seconds!r}"
            )
        self._max_age_seconds = float(max_age_seconds)
        self._clock = clock

    def run(self, directory: str, *, dry_run: bool = False) -> RetentionReport:
        if not os.path.exists(directory):
            raise FileNotFoundError(f"target directory does not exist: {directory!r}")
        if not os.path.isdir(directory):
            raise NotADirectoryError(f"target is not a directory: {directory!r}")

        now = self._clock()
        report = RetentionReport(
            dry_run=dry_run,
            target_dir=directory,
            max_age_seconds=self._max_age_seconds,
        )

        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            report.errors.append((directory, f"scandir_failed: {exc}"))
            return report

        for entry in entries:
            path = entry.path

            is_regular = False
            try:
                if entry.is_dir(follow_symlinks=False):
                    is_regular = False
                elif entry.is_file(follow_symlinks=False):
                    is_regular = True
                else:
                    is_regular = False
            except OSError:
                try:
                    st = os.lstat(path)
                    is_regular = os.path.S_ISREG(st.st_mode)
                except OSError as exc:
                    report.errors.append((path, f"stat_failed: {exc}"))
                    report.results.append(
                        RetentionResult(
                            path=path,
                            age_seconds=0.0,
                            deleted=False,
                            would_delete=False,
                            reason="error",
                            error=f"stat_failed: {exc}",
                        )
                    )
                    continue

            if not is_regular:
                report.retained.append(path)
                report.results.append(
                    RetentionResult(
                        path=path,
                        age_seconds=0.0,
                        deleted=False,
                        would_delete=False,
                        reason="retained_not_regular",
                    )
                )
                continue

            try:
                st = os.stat(path)
            except OSError as exc:
                report.errors.append((path, f"stat_failed: {exc}"))
                report.results.append(
                    RetentionResult(
                        path=path,
                        age_seconds=0.0,
                        deleted=False,
                        would_delete=False,
                        reason="error",
                        error=f"stat_failed: {exc}",
                    )
                )
                continue

            age = now - st.st_mtime

            if age > self._max_age_seconds:
                if dry_run:
                    report.would_delete.append(path)
                    report.results.append(
                        RetentionResult(
                            path=path,
                            age_seconds=age,
                            deleted=False,
                            would_delete=True,
                            reason="would_delete",
                        )
                    )
                else:
                    try:
                        os.remove(path)
                        report.deleted.append(path)
                        report.results.append(
                            RetentionResult(
                                path=path,
                                age_seconds=age,
                                deleted=True,
                                would_delete=True,
                                reason="deleted",
                            )
                        )
                    except OSError as exc:
                        report.errors.append((path, f"remove_failed: {exc}"))
                        report.results.append(
                            RetentionResult(
                                path=path,
                                age_seconds=age,
                                deleted=False,
                                would_delete=True,
                                reason="error",
                                error=f"remove_failed: {exc}",
                            )
                        )
            else:
                report.retained.append(path)
                report.results.append(
                    RetentionResult(
                        path=path,
                        age_seconds=age,
                        deleted=False,
                        would_delete=False,
                        reason="retained_young",
                    )
                )

        return report
