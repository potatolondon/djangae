
from datetime import datetime
import time
from django.test import LiveServerTestCase

from djangae.tasks import (
    cloud_tasks_parent_path,
    cloud_tasks_queue_path,
    ensure_required_queues_exist,
    get_cloud_tasks_client,
)
from google.api_core.exceptions import GoogleAPIError, NotFound


class TaskFailedBehaviour:
    DO_NOTHING = 0
    RETRY_TASK = 1
    RAISE_ERROR = 2


class TaskFailedError(Exception):
    def __init__(self, task_name, status_code, original_exception=None):
        self.task_name = task_name
        self.status_code = status_code
        self.original_exception = original_exception

        super(TaskFailedError, self).__init__(
            "Task {} failed with status code: {}. \n\nMessage was: {}".format(
                task_name, status_code, original_exception
            )
        )


class TestCaseMixin(LiveServerTestCase):
    """
        A TestCase base class that manages task queues
        during testing. Ensures that required queues
        are created and paused, and manually runs the
        queued tasks in them to check their responses
    """
    def __init__(self, *args, **kwargs):
        self.max_task_retry_count = 100
        super().__init__(*args, **kwargs)

    def setUp(self):
        # Create all the queues required by this application

        super().setUp()

        # Find the port we were allocated
        self._server_port = self.live_server_url.rsplit(":")[-1]

        ensure_required_queues_exist()

        self.task_client = get_cloud_tasks_client()

        parent = cloud_tasks_parent_path()

        for queue in self.task_client.list_queues(parent=parent):
            # Make sure the queue is paused
            self.task_client.pause_queue(queue.name)

            # Make sure it's empty
            self.task_client.purge_queue(queue.name)

    def _get_queues(self, queue_name=None):
        if queue_name:
            path = cloud_tasks_queue_path(queue_name)
            queue = self.task_client.get_queue(path)
            queues = [queue]
        else:
            parent = cloud_tasks_parent_path()
            queues = self.task_client.list_queues(parent)

        return queues

    def flush_task_queues(self, queue_name=None):
        for queue in self._get_queues(queue_name=queue_name):
            self.task_client.purge_queue(queue.name)

    def get_task_count(self, queue_name=None):
        count = 0
        for queue in self._get_queues(queue_name=queue_name):
            path = queue.name
            count += len(list(self.task_client.list_tasks(path)))

        return count

    def assertNumTasksEquals(self, num, queue_name=None):
        self.assertEqual(num, self.get_task_count(queue_name=queue_name))

    def _get_all_tasks_for_queues(self, queue_names):
        tasks = []
        for path in queue_names:
            tasks += [x for x in self.task_client.list_tasks(path)]
        return tasks

    def _wait_on_task(self, task_name, timeout=20):
        """
        It waits for a task to be completed.
        """
        task = None
        start = datetime.now()
        while True:
            try:
                task = self.task_client.get_task(task_name)
                if 300 <= task.last_attempt.response_status.code < 600:

                    raise TaskFailedError(task.name, task.last_attempt.response_status.code,
                                          original_exception=Exception("Immediate task execution failed"))
            except NotFound:
                # If the task in not the queue is completed
                break
            delta = datetime.now() - start
            if delta.total_seconds() > timeout:
                raise TaskFailedError(task.name, None, original_exception=Exception("Immediate task execution timeout"))

            time.sleep(.1)
        return task

    def process_task_queues(self, queue_name=None, failure_behaviour=TaskFailedBehaviour.RAISE_ERROR):
        queue_names = [q.name for q in self._get_queues(queue_name)]

        tasks = self._get_all_tasks_for_queues(queue_names)
        task_failure_counts = {}
        while tasks:
            task = tasks.pop(0)

            try:
                # Appending the port number to the task name
                # is a special-case that does not exist
                # on the live server and it exists so that
                # local development servers can direct a task
                # to run on a particular port.
                self.task_client.run_task(task.name + "?port=%s" % self._server_port)

                # If the returned status wasn't a success then
                # drop into the except block below to handle the
                # failure
                self._wait_on_task(task.name)

            except (GoogleAPIError, TaskFailedError) as e:
                if failure_behaviour == TaskFailedBehaviour.RETRY_TASK:
                    if task.name not in task_failure_counts:
                        task_failure_counts[task.name] = 1
                    else:
                        task_failure_counts[task.name] += 1

                    if task_failure_counts[task.name] >= self.max_task_retry_count:
                        # Make sure we don't get an infinite loop while retrying
                        raise

                    tasks.append(task)  # Add back to the end of the queue
                    continue
                elif failure_behaviour == TaskFailedBehaviour.RAISE_ERROR:
                    raise TaskFailedError(task.name, str(e), original_exception=e)
                else:
                    # Do nothing, ignore the failure
                    pass

            if not tasks:
                tasks = self._get_all_tasks_for_queues(queue_names)
