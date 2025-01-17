from django.http import HttpResponse
from django.test import (
    Client,
    RequestFactory,
    override_settings,
)
from django.urls import (
    path,
    reverse,
)

from djangae.contrib import sleuth
from djangae.tasks.decorators import (
    csrf_exempt_if_task,
    task_only,
    task_or_superuser_only,
)
from djangae.tasks.deferred import defer
from djangae.tasks.environment import (
    is_in_cron,
    is_in_task,
    task_name,
    task_queue_name,
    task_execution_count,
    task_retry_count,
    tasks_location,
)
from djangae.tasks import environment
from djangae.tasks.middleware import _TASK_NAME_HEADER, task_environment_middleware
from djangae.test import TestCase


class TaskOnlyTestCase(TestCase):
    """ Tests for the @task_only decorator. """

    def setUp(self):
        self.factory = RequestFactory()
        super().setUp()

    def test_403_if_not_task(self):
        # If we are neither in a task or logged in as an admin, we expect a 403 response

        @task_only
        def view(request):
            return HttpResponse("Hello")

        request = self.factory.get("/")
        response = view(request)
        self.assertEqual(response.status_code, 403)

    def test_allowed_if_in_task(self):
        """ If we're in an App Engine task then it should allow the request through. """

        @task_only
        def view(request):
            return HttpResponse("Hello")

        request = self.factory.get("/")
        with sleuth.fake("djangae.tasks.decorators.is_in_task", True):
            response = view(request)

        self.assertEqual(response.status_code, 200)

    def test_allowed_if_in_cron(self):
        """ If the view is being called by the GAE cron, then it should allow the request through. """

        @task_only
        def view(request):
            return HttpResponse("Hello")

        request = self.factory.get("/")

        with sleuth.fake("djangae.tasks.decorators.is_in_cron", True):
            response = view(request)
        self.assertEqual(response.status_code, 200)


class TaskOrSuperuserOnlyTestCase(TestCase):
    """ Tests for the @task_only decorator. """

    def setUp(self):
        self.factory = RequestFactory()
        super().setUp()

    def test_403_if_not_task_or_superuser(self):
        # If we are neither in a task or logged in as an admin, we expect a 403 response

        @task_or_superuser_only
        def view(request):
            return HttpResponse("Hello")

        request = self.factory.get("/")
        response = view(request)
        self.assertEqual(response.status_code, 403)

    def test_allowed_if_in_task(self):
        """ If we're in an App Engine task then it should allow the request through. """

        @task_or_superuser_only
        def view(request):
            return HttpResponse("Hello")

        request = self.factory.get("/")
        request.META[_TASK_NAME_HEADER] = "test"

        with sleuth.fake("djangae.tasks.decorators.is_in_task", True):
            response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_allowed_if_superuser(self):
        """ If we're in an App Engine task then it should allow the request through. """

        @task_or_superuser_only
        def view(request):
            return HttpResponse("Hello")

        class User(object):
            is_superuser = True
            is_authenticated = True

        request = self.factory.get("/")
        request.user = None
        response = view(request)
        self.assertEqual(response.status_code, 403)

        request.user = User()
        response = view(request)
        self.assertEqual(response.status_code, 200)


@csrf_exempt_if_task
def view(request):
    return HttpResponse("Hello")


urlpatterns = [
    path("view", view, name="test_view")
]


@override_settings(ROOT_URLCONF='djangae.tasks.tests.test_environment')
class CsrfExemptIfTaskTest(TestCase):
    def test_csrf_required_if_normal_view(self):
        """ If we're in an App Engine task then it should allow the request through. """

        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("test_view"))
        self.assertEqual(response.status_code, 403)

        response = client.post(reverse("test_view"), HTTP_X_APPENGINE_TASKNAME="test")
        self.assertEqual(response.status_code, 200)


def deferred_func():
    assert (task_name())
    assert (task_queue_name())
    assert (task_execution_count())
    assert (not is_in_cron())


class EnvironmentTests(TestCase):
    def test_task_headers_are_available_in_tests(self):
        defer(deferred_func)
        self.process_task_queues()

        # Check nothing lingers
        self.assertFalse(task_name())
        self.assertFalse(task_queue_name())
        self.assertFalse(task_execution_count())

    def test_middleware_resets_thread_locals_flags(self):
        # Set all the task environment flags that should be reset
        for attr, set_value in (
            ("task_name", "footask"),
            ("queue_name", "fooqueue"),
            ("task_execution_count", 1),
            ("task_retry_count", 1),
            ("is_cron", True),
        ):
            setattr(environment._TASK_ENV, attr, set_value)

        # All helpers should return their active value
        self.assertTrue(is_in_task())
        self.assertTrue(is_in_cron())
        self.assertEqual(task_name(), "footask")
        self.assertEqual(task_queue_name(), "fooqueue")
        self.assertEqual(task_retry_count(), 1)
        self.assertEqual(task_execution_count(), 1)

        # Running the middleware should unset flags
        def get_response(request):
            return HttpResponse()
        request = RequestFactory().get("/")
        task_environment_middleware(get_response)(request)

        # All helpers should be reset to their default
        self.assertFalse(is_in_task())
        self.assertFalse(is_in_cron())
        self.assertIsNone(task_name())
        self.assertIsNone(task_queue_name())
        self.assertIsNone(task_retry_count())
        self.assertIsNone(task_execution_count())

    def test_tasks_location(self):
        self.assertEqual(tasks_location("e~example-app"), "europe-west1")
        self.assertEqual(tasks_location("zwn~example-app"), "us-west4")
        self.assertIsNone(tasks_location("xxx~example-app"))
