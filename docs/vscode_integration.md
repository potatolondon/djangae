# Visual Studio Code integration


## Running tests

Tests for you Djangae app can be run within Visual Studio Code with a little bit of extra setup

### Requirements
* An active virtual env (e.g. `.venv/bin/activate`)
* The (official python extension)[https://marketplace.visualstudio.com/items?itemName=ms-python.python] for vscode

### Setup
Install some extra deps: `pip install pytest pytest-django pytest-env`

Create a `pytest.ini` (or add to `tox.ini`if you have one) with the following

```ini
[pytest]
DJANGO_SETTINGS_MODULE = your.test.setting.module # (e.g. core.conf.tests)
python_files = test_*.py
env =
    DATASTORE_EMULATOR_HOST=0.0.0.0:10901
    DATASTORE_EMULATOR_HOST_PATH=0.0.0.0:10901/datastore
    DATASTORE_HOST=http://0.0.0.0:10901
    DATASTORE_PROJECT_ID=test
    TASKS_EMULATOR_HOST=127.0.0.1:10908
    STORAGE_EMULATOR_HOST=http://127.0.0.1:10911
```

Note: this assuming Djangae's default ports/settings - if you changed them, change here accordingly

### Start the emulators

When running tests with `python ./manage.py test` your `manage.py` file will at some point call `start_emulators(...)`. This is not done by pytest, so we need to run these in a separate shell/terminal (but we can keep that running in the background and run tests wheenever we want!)

To do that, create a `start_emulators.py` file with a content like this one:

```python
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
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "your.test.setting.module") # replace this with the actual test config module
    start_emulators(
        persist_data=False,
        # add params as per your manage.py file
    )

    signal.signal(signal.SIGINT, signal_handler)
    print("Emulators started.")
    print("Press Ctrl+C to exit")
    signal.pause()
    stop_emulators()
```

Open a terminal and execute that script `python ./start_emulators.py`

### Visual Studio Code setup
* Run the "Python > Configure Tests" command and select pytest
* Make sure you're using the right python interpreter (e.g. the one in your virtualenv)
* Open the test panel (the one with the "lab flask" icon)
* Your tests should appear there and you should be able to run or debug them
