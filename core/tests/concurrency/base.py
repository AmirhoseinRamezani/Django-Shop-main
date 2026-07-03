# tests/concurrency/base.py
import threading


class ConcurrentRunner:

    def __init__(self):
        self.errors = []

    def run(self, *targets):

        threads = []

        for target in targets:

            t = threading.Thread(
                target=self._safe,
                args=(target,),
            )

            threads.append(t)
            t.start()

        for t in threads:
            t.join()

    def _safe(self, target):

        try:
            target()

        except Exception as exc:
            self.errors.append(exc)
