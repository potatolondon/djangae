import logging
import os
import psutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional, Sequence
from urllib.error import (
    HTTPError,
    URLError,
)
from urllib.request import urlopen

from djangae.utils import get_next_available_port, port_is_open
from djangae.environment import get_application_root

# This is copied from Django so that we don't import Django, and therefore
# settings.py before we've got the Datastore etc. up and running
DJANGO_AUTORELOAD_ENV = 'RUN_MAIN'

_ACTIVE_EMULATORS = {}
_ALL_EMULATORS = ("datastore", "tasks", "storage")

_DJANGO_DEFAULT_PORT = 8000

SERVICE_HOST = "127.0.0.1"
SERVICE_PROTOCOL_HOST = f"http://{SERVICE_HOST}"

DEFAULT_DATASTORE_PORT = 10901
DEFAULT_TASKS_PORT = 10908
DEFAULT_STORAGE_PORT = 10911

DEFAULT_PROJECT_ID = "example"
DEFAULT_GAE_APPLICATION = "e~{}".format(DEFAULT_PROJECT_ID)
DEFAULT_BUCKET = "%s.appspot.com" % DEFAULT_PROJECT_ID

logger = logging.getLogger(__name__)


def _launch_process(command_line):
    env = os.environ.copy()
    return subprocess.Popen(command_line.split(" "), env=env)


def _wait_for_tasks(port):
    time.sleep(2)  # FIXME: Need to somehow check it's running


def _wait_for_datastore(port):
    _wait(port, "Cloud Datastore Emulator")


def _wait_for_storage(port):
    _wait(port, "Cloud Storage Emulator")


def _wait(port, service):
    logger.info("Waiting for %s..." % service)

    TIMEOUT = 60.0
    start = datetime.now()

    time.sleep(1)

    failures = 0
    while True:
        try:
            response = urlopen(f"{SERVICE_PROTOCOL_HOST}:{port}/")
        except (HTTPError, URLError):
            failures += 1
            time.sleep(1)
            if failures > 5:
                # Only start logging if this becomes persistent
                logger.exception("Error connecting to the %s. Retrying..." % service)
            continue

        if response.status == 200:
            # Give things a second to really boot
            time.sleep(1)
            break

        if (datetime.now() - start).total_seconds() > TIMEOUT:
            raise RuntimeError("Unable to start %s. Please check the logs." % service)

        time.sleep(1)


def _kill_proc_tree(pid, sig=signal.SIGTERM, timeout=None, on_terminate=None):
    """Kill a process tree (including grandchildren) with signal
    "sig" and return a (gone, still_alive) tuple.
    "on_terminate", if specified, is a callabck function which is
    called as soon as a child terminates.
    """
    assert pid != os.getpid(), "won't kill myself"
    parent = psutil.Process(pid)
    children = parent.children(recursive=True)
    children.append(parent)

    for p in children:
        try:
            p.send_signal(sig)
        except psutil.NoSuchProcess:
            pass
    gone, alive = psutil.wait_procs(children, timeout=timeout, callback=on_terminate)
    return (gone, alive)


def start_emulators(
    persist_data: bool,
    project_id: str = DEFAULT_PROJECT_ID,
    emulators: Sequence[str] = _ALL_EMULATORS,
    datastore_port: int = DEFAULT_DATASTORE_PORT,
    datastore_dir: Optional[str] = None,
    tasks_port: int = DEFAULT_TASKS_PORT,
    task_target_port: Optional[int] = None,
    task_queue_yaml: Optional[str] = None,
    autodetect_task_port: bool = True,
    storage_port: int = DEFAULT_STORAGE_PORT,
    storage_dir: Optional[str] = None,
):
    # This prevents restarting of the emulators when Django code reload kicks in
    if os.environ.get(DJANGO_AUTORELOAD_ENV) == 'true':
        return

    # If storage_dir and datastore_dir are specified, we just
    # use them verbatim, otherwise we do some guesswork
    if not (storage_dir and datastore_dir):
        # sys.path[0] is nearly always the parent path of the
        # executed script (e.g. manage.py)
        base_path = sys.path[0]

        # Fall-back to the application root with a warning
        if not base_path:
            logging.warn(
                "Unable to determine script path, using "
                "application root for storage directories"
            )
            base_path = get_application_root()

        storage_dir = storage_dir or os.path.join(base_path, ".clouddata", "storage")
        datastore_dir = datastore_dir or os.path.join(base_path, ".clouddata", "datastore")

    os.makedirs(storage_dir, exist_ok=True)
    os.makedirs(datastore_dir, exist_ok=True)

    enable_test_environment_variables(project_id=project_id)

    if "datastore" in emulators:
        if not port_is_open(SERVICE_HOST, datastore_port):
            # If start_emulators is call explicitly passing the Datastore Emulator port
            # and the port is not available raise and Runtime exception.
            if datastore_port != DEFAULT_DATASTORE_PORT:
                raise RuntimeError(f"Unable to start Cloud Datastore Emulator at port {datastore_port}.")
            else:
                datastore_port = get_next_available_port(SERVICE_HOST, datastore_port)

        os.environ["DATASTORE_EMULATOR_HOST"] = f"{SERVICE_HOST}:{datastore_port}"
        os.environ["DATASTORE_PROJECT_ID"] = project_id

        # Start the cloud datastore emulator
        command = f"gcloud beta emulators datastore start --user-output-enabled=false --use-firestore-in-datastore-mode --quiet --project={project_id}"  # noqa
        command += f" --host-port={SERVICE_HOST}:{datastore_port}"

        if datastore_dir:
            command += " --data-dir=%s" % datastore_dir
        if not persist_data:
            command += " --no-store-on-disk"

        _ACTIVE_EMULATORS["datastore"] = _launch_process(command)
        _wait_for_datastore(datastore_port)

    if "tasks" in emulators:
        # If start_emulators is call explicitly passing the Cloud Task emulator port
        # and the port is not available raise and Runtime exception.
        if not port_is_open(SERVICE_HOST, tasks_port):
            if tasks_port != DEFAULT_TASKS_PORT:
                raise RuntimeError(f"Unable to start Cloud Tasks Emulator at port {tasks_port}.")
            else:
                tasks_port = get_next_available_port(SERVICE_HOST, tasks_port)

        from djangae.tasks import cloud_tasks_location, cloud_tasks_parent_path, cloud_tasks_project
        default_queue = "%s/queues/default" % cloud_tasks_parent_path()

        if task_target_port is None:
            if sys.argv[1] == "runserver" and autodetect_task_port:
                from django.core.management.commands.runserver import Command as RunserverCommand
                parser = RunserverCommand().create_parser('django', 'runserver')
                args = parser.parse_args(sys.argv[2:])
                if args.addrport:
                    task_target_port = args.addrport.split(":")[-1]
                else:
                    task_target_port = _DJANGO_DEFAULT_PORT
            else:
                task_target_port = _DJANGO_DEFAULT_PORT

        command = "gcloud-tasks-emulator start -q --port=%s --target-port=%s --default-queue=%s" % (
            tasks_port, task_target_port, default_queue
        )

        # If the project contains a queue.yaml, pass it to the Tasks Emulator so that those queues
        # can be created (needs version >= 0.4.0)
        if task_queue_yaml and os.path.exists(task_queue_yaml):
            command += " --queue-yaml=%s --queue-yaml-project=%s --queue-yaml-location=%s" % (
                task_queue_yaml, cloud_tasks_project(), cloud_tasks_location()
            )
        elif task_queue_yaml:
            logger.warn("task_queue_yaml was passed, but the file does not exist. Ignoring.")

        os.environ["TASKS_EMULATOR_HOST"] = f"{SERVICE_HOST}:{tasks_port}"
        _ACTIVE_EMULATORS["tasks"] = _launch_process(command)
        _wait_for_tasks(tasks_port)

    if "storage" in emulators:
        # If start_emulators is call explicitly passing the Cloud Storage emulator port
        # and the port is not available raise and Runtime exception.
        if not port_is_open(SERVICE_HOST, storage_port):
            if storage_port != DEFAULT_STORAGE_PORT:
                raise RuntimeError(f"Unable to start Cloud Storage Emulator at port {storage_port}.")
            else:
                storage_port = get_next_available_port(SERVICE_HOST, storage_port)

        os.environ["STORAGE_EMULATOR_HOST"] = f"http://{SERVICE_HOST}:{storage_port}"
        command = "gcloud-storage-emulator start -q --port=%s --default-bucket=%s" % (
            storage_port, DEFAULT_BUCKET)

        if storage_dir:
            command += " --data-dir=%s" % storage_dir

        if not persist_data:
            command += " --no-store-on-disk"

        _ACTIVE_EMULATORS["storage"] = _launch_process(command)
        _wait_for_storage(storage_port)


def stop_emulators(emulators=None):
    # This prevents restarting of the emulators when Django code reload kicks in
    if os.environ.get(DJANGO_AUTORELOAD_ENV) == 'true':
        return

    emulators = emulators or _ALL_EMULATORS
    for name, process in _ACTIVE_EMULATORS.items():

        if name in emulators:
            logger.info('Stopping %s emulator with PID %s', name, process.pid)
            _kill_proc_tree(process.pid)


def enable_test_environment_variables(project_id=DEFAULT_PROJECT_ID):
    """
        Sets up sample environment variables that are available on production
    """

    gae_application_id = "e~{}".format(project_id)

    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
    os.environ.setdefault("GAE_APPLICATION", gae_application_id)
    os.environ.setdefault("GAE_ENV", "development")


def wipe_cloud_storage():
    storage_emulator_host = os.environ['STORAGE_EMULATOR_HOST']
    if not storage_emulator_host:
        logger.warning(
            "Cloud storage emulator wipe operation failed."
            "Cloud storage emulator has not been started.")
        return

    urlopen(f"{storage_emulator_host}/wipe?keep-buckets=true")
