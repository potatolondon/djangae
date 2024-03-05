#!/usr/bin/env python
import os
import sys
import signal

from djangae.sandbox import start_emulators, stop_emulators

PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))


def signal_handler(sig, frame):
    print("Stopping all emulators")
    sys.exit(0)


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "test_settings")  # replace this with the actual test config module
    start_emulators(
        persist_data=False,
    )

    signal.signal(signal.SIGINT, signal_handler)
    print("Emulators started.")
    print("Press Ctrl+C to exit")
    signal.pause()
    stop_emulators()
