from __future__ import annotations

import threading
from collections.abc import Callable


class ConcurrentRunner:
    """Run targets concurrently and fail the test if any worker fails."""

    def __init__(self) -> None:
        self.errors: list[BaseException] = []
        self._errors_lock = threading.Lock()

    def run(self, *targets: Callable[[], object]) -> None:
        if not targets:
            return

        barrier = threading.Barrier(len(targets))
        threads = [
            threading.Thread(
                target=self._safe,
                args=(target, barrier),
            )
            for target in targets
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        if self.errors:
            details = "\n".join(
                f"{type(error).__name__}: {error}"
                for error in self.errors
            )
            raise AssertionError(
                f"{len(self.errors)} concurrent worker(s) failed:\n{details}"
            )

    def _safe(
        self,
        target: Callable[[], object],
        barrier: threading.Barrier,
    ) -> None:
        from django.db import close_old_connections

        try:
            close_old_connections()
            barrier.wait()
            target()
        except BaseException as exc:
            with self._errors_lock:
                self.errors.append(exc)
        finally:
            close_old_connections()
