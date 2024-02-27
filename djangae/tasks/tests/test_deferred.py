import os

from django.db import models
from gcloudc.db import transaction

from djangae.contrib import sleuth
from djangae.tasks.deferred import defer, PermanentTaskFailure
from djangae.test import (
    TaskFailedError,
    TestCase,
)

ANOTHER_DB_ALIAS = 'another_db'


def test_task(*args, **kwargs):
    pass


def assert_cache_wiped(instance):
    field = DeferModelA._meta.get_field("b")
    assert(field.get_cached_value(instance, None) is None)


class DeferModelA(models.Model):
    b = models.ForeignKey("DeferModelB", on_delete=models.CASCADE)

    class Meta:
        app_label = "djangae"


class DeferModelB(models.Model):
    class Meta:
        app_label = "djangae"


class DeferModelC(models.Model):
    text = models.TextField()

    class Meta:
        app_label = "djangae"


def create_defer_model_b(key_value):
    DeferModelB.objects.create(pk=key_value)


def create_defer_model_b_on_another_db(key_value):
    DeferModelB.objects.using(ANOTHER_DB_ALIAS).create(pk=key_value)


def process_argument(arg):
    DeferModelC.objects.create(text=arg)


def permanent_task_failure():
    raise PermanentTaskFailure


class DeferTests(TestCase):
    databases = '__all__'

    def test_large_task(self):
        random_file = os.path.join(os.path.dirname(__file__), "random_data")
        with open(random_file, "r") as f:
            big_string = f.read()

        try:
            defer(process_argument, big_string)
        except Exception:  # noqa
            self.fail("A large task couldn't be deferred")

        self.process_task_queues()

        self.assertTrue(DeferModelC.objects.exists())

        instance = DeferModelC.objects.get()
        self.assertEqual(instance.text, big_string)

    def test_wipe_related_caches(self):
        b = DeferModelB.objects.create()
        a = DeferModelA.objects.create(b=b)
        a.b  # Make sure we access it

        cache_name = DeferModelA._meta.get_field("b").get_cache_name()
        self.assertTrue(getattr(a, cache_name))

        defer(assert_cache_wiped, a)

        # Should raise an assertion error if the cache existed
        try:
            self.process_task_queues()
        except TaskFailedError as e:
            raise e.original_exception

        # Should not have wiped the cache for us!
        self.assertIsNotNone(getattr(a, cache_name, None))

    def test_queues_task(self):
        initial_count = self.get_task_count()
        defer(test_task)
        self.assertEqual(self.get_task_count(), initial_count + 1)

    def test_task_default_routing(self):
        gae_version = 'demo'
        os.environ['GAE_VERSION'] = gae_version

        with sleuth.watch('google.cloud.tasks_v2.CloudTasksClient.create_task') as _create_task:
            defer(test_task)

            self.assertTrue(_create_task.called)
            routing = _create_task.calls[0].args[2]['app_engine_http_request']['app_engine_routing']
            self.assertFalse('service' in routing)
            self.assertFalse('instance' in routing)
            self.assertEqual(routing['version'], gae_version)

        del os.environ['GAE_VERSION']

    def test_task_routing(self):
        service = 'service123'
        version = 'version456'
        instance = 'instance789'
        os.environ['GAE_VERSION'] = 'demo'

        with sleuth.watch('google.cloud.tasks_v2.CloudTasksClient.create_task') as _create_task:
            defer(test_task, _service=service, _version=version, _instance=instance)

            self.assertTrue(_create_task.called)
            routing = _create_task.calls[0].args[2]['app_engine_http_request']['app_engine_routing']
            self.assertEqual(routing['service'], service)
            self.assertEqual(routing['version'], version)
            self.assertEqual(routing['instance'], instance)

        del os.environ['GAE_VERSION']

    def test_deprecated_target_parameter(self):
        self.assertRaises(UserWarning, defer, test_task, _target='test')

    def test_transactional_defer(self):
        try:
            with transaction.atomic():
                defer(create_defer_model_b, 1, _transactional=True)
                raise ValueError()  # Rollback the transaction
        except ValueError:
            pass

        self.process_task_queues()

        # Shouldn't have created anything
        self.assertEqual(0, DeferModelB.objects.count())

        with transaction.atomic():
            defer(create_defer_model_b, 1, _transactional=True)
            self.process_task_queues()
            self.assertEqual(0, DeferModelB.objects.count())  # Still nothing

        # Now we should be good!
        self.process_task_queues()
        self.assertEqual(1, DeferModelB.objects.count())

    def test_permanent_task_failure(self):

        defer(permanent_task_failure)

        # Complete task without exception raised externally.
        self.process_task_queues()
        self.assertEqual(self.get_task_count(), 0)

    def test_uses_right_database_connection(self):
        pk = 1
        defer(create_defer_model_b_on_another_db, pk, _using=ANOTHER_DB_ALIAS)
        self.process_task_queues()
        try:
            DeferModelB.objects.using(ANOTHER_DB_ALIAS).get(pk=pk)
        except DeferModelB.DoesNotExist:
            self.fail("The task didn't use the right database connection")
