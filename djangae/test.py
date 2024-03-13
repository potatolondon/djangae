import tempfile
from django.test.runner import DiscoverRunner
from djangae.tasks.test import (
    TaskFailedBehaviour,
    TaskFailedError,
    TestCaseMixin,
)
from django import test
from django.core.cache import cache
from djangae.sandbox import start_emulators, stop_emulators, wipe_cloud_storage

TaskFailedError = TaskFailedError
TaskFailedBehaviour = TaskFailedBehaviour


class TestEnvironmentMixin(object):
    def setUp(self):
        cache.clear()
        super().setUp()


class CloudStorageTestCaseMixin(object):
    def setUp(self):
        wipe_cloud_storage()
        super().setUp()


class TestCase(TestEnvironmentMixin, TestCaseMixin, test.TransactionTestCase):
    pass


class TransactionTestCase(TestEnvironmentMixin, TestCaseMixin, test.TransactionTestCase):
    pass


class AppEngineDiscoverRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        datastore_dir = tempfile.mkdtemp()
        storage_dir = tempfile.mkdtemp()

        start_emulators(
            persist_data=False,
            datastore_dir=datastore_dir,
            storage_dir=storage_dir
        )

        super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        super().teardown_test_environment(**kwargs)
        stop_emulators()
