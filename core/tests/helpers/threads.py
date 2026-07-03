# tests/helpers/threads.py
import threading


def run_parallel(*targets):

    threads = [
        threading.Thread(target=target)
        for target in targets
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()