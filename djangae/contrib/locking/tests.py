# STANDARD LIB
import hashlib
import threading
import time

# THIRD PARTY
from django.utils import timezone

# DJANGAE
from djangae.contrib import sleuth
from djangae.test import TestCase

try:
    from gcloudc.db.backends.datastore.transaction import TransactionFailedError as DatabaseError
except ImportError:
    from django.db import DatabaseError


from .kinds import LOCK_KINDS
from .lock import (
    Lock,
    LockAcquisitionError,
    lock,
)
from .memcache import MemcacheLock
from .models import DatastoreLock
from .views import cleanup_locks


class DatastoreLocksTestCase(TestCase):
    """ Tests for the implementation of the STRONG kind of lock (DatastoreLock). """

    def _make_lock(self, identifier, **kwargs):
        """ Shorcut for when we need to manually create DatastoreLock objects for tests. """
        identifier_hash = hashlib.md5(identifier.encode()).hexdigest()
        return DatastoreLock.objects.create(identifier_hash=identifier_hash, **kwargs)

    def test_acquire_and_release(self):
        # If we try to acquire the same lock twice then the second one should fail
        lock = Lock.acquire("my_lock")
        self.assertTrue(isinstance(lock, Lock))
        # Now if we try to acquire the same one again before releasing it, we should get None
        lock_again = Lock.acquire("my_lock", wait=False)
        self.assertIsNone(lock_again)
        # Now if we release it we should then be able to acquire it again
        lock.release()
        lock_again = Lock.acquire("my_lock", wait=False)
        self.assertTrue(isinstance(lock_again, Lock))

    def test_context_manager_no_wait(self):
        """ If the lock is already acquired, then our context manager with wait=False should raise
            LockAcquisitionError.
        """
        def do_context():
            with lock('x', wait=False):
                return True

        # With the lock already in use, the context manager should blow up
        my_lock = Lock.acquire('x')
        self.assertRaises(LockAcquisitionError, do_context)
        # And with the lock released the context should be run
        my_lock.release()
        self.assertTrue(do_context())

    def test_context_manager_steal(self):
        """ If the lock is already acquired, but is older than our limit then the context manager
            should steal it.
        """
        def do_context():
            with lock('x', wait=True, steal_after_ms=10):
                return True

        self._make_lock('x', timestamp=timezone.now() - timezone.timedelta(microseconds=2000))
        self.assertTrue(do_context())

    def test_decorator_no_wait(self):
        """ If the lock is already acquired, then our decorator with wait=False should not run the
            function.
        """
        @lock('x', wait=False)
        def do_something():
            return True

        # With the lock already in use, the function should not be run
        my_lock = Lock.acquire('x')
        self.assertIsNone(do_something())
        # And with the lock released the function should run
        my_lock.release()
        self.assertTrue(do_something())

    def test_decorator_steal(self):
        """ If the lock is already acquired, but is older than our limit then the decorator should
            steal it.
        """
        @lock('x', wait=True, steal_after_ms=10)
        def do_something():
            return True

        self._make_lock('x', timestamp=timezone.now() - timezone.timedelta(microseconds=2000))
        self.assertTrue(do_something())

    def test_cleanup_view(self):
        ages_ago = timezone.now() - timezone.timedelta(minutes=15)
        self._make_lock("old_lock", timestamp=ages_ago)
        recent_lock = self._make_lock("recent_lock")
        cleanup_locks(None)
        self.process_task_queues()
        # The old lock should have been deleted but the new one should not
        self.assertCountEqual(DatastoreLock.objects.all(), [recent_lock])

    def test_transaction_errors_are_handled(self):
        with sleuth.detonate(
            'djangae.contrib.locking.models.LockQuerySet.filter', DatabaseError
        ):
            lock = Lock.acquire("my_lock", wait=False)
            self.assertIsNone(lock)

    def test_max_wait_ms(self):
        lock1 = Lock.acquire("my_lock")   # Get the lock
        self.assertTrue(lock1)

        lock2 = Lock.acquire("my_lock", max_wait_ms=100, wait=True, steal_after_ms=10000)  # Wait 100 ms

        # If we stole it, this wouldn't be None
        self.assertIsNone(lock2)


class MemcacheLocksTestCase(TestCase):
    """ Tests for the implementation of the WEAK kind of lock (MemcacheLock). """

    def test_acquire_and_release(self):
        # If we try to acquire the same lock twice then the second one should fail
        lock = Lock.acquire("my_lock", kind=LOCK_KINDS.WEAK)
        self.assertTrue(isinstance(lock, Lock))
        # Now if we try to acquire the same one again before releasing it, we should get None
        lock_again = Lock.acquire("my_lock", kind=LOCK_KINDS.WEAK, wait=False)
        self.assertIsNone(lock_again)
        # Now if we release it we should then be able to acquire it again
        lock.release()
        lock_again = Lock.acquire("my_lock", kind=LOCK_KINDS.WEAK, wait=False)
        self.assertTrue(isinstance(lock_again, Lock))

    def test_context_manager_steal(self):
        """ If the lock is already acquired, but is older than our limit then the context manager
            should steal it.
        """
        def do_context():
            with lock('x', wait=True, steal_after_ms=10, kind=LOCK_KINDS.WEAK):
                return True

        MemcacheLock.acquire('x')  # Acquire the lock

        # If we don't wait, then the lock can't be acquired
        self.assertFalse(MemcacheLock.acquire('x', wait=False))

        self.assertTrue(do_context())  # Should succeed eventually

    def test_context_manager_no_steal(self):
        did_raise_error = False

        def acquire_lock():
            nonlocal did_raise_error

            try:
                lock = MemcacheLock.acquire('x')
                lock.release()
            except Exception:
                did_raise_error = True

        # acquire lock x
        lock = MemcacheLock.acquire('x')
        # try to acquire the same lock x in a thread
        t = threading.Thread(target=acquire_lock)
        t.start()
        # release lock
        lock.release()
        # wait for the thread to finish
        t.join()

        # assert that the thread did not raise an error when acquiring the lock
        self.assertFalse(did_raise_error)

    def test_context_manager_no_wait(self):
        """ If the lock is already acquired, then our context manager with wait=False should raise
            LockAcquisitionError.
        """
        def do_context():
            with lock('x', wait=False, kind=LOCK_KINDS.WEAK):
                return True

        # With the lock already in use, the context manager should blow up
        my_lock = Lock.acquire('x', kind=LOCK_KINDS.WEAK)
        self.assertRaises(LockAcquisitionError, do_context)
        # And with the lock released the context should be run
        my_lock.release()
        self.assertTrue(do_context())

    def test_decorator_no_wait(self):
        """ If the lock is already acquired, then our decorator with wait=False should not run the
            function.
        """
        @lock('x', wait=False, kind=LOCK_KINDS.WEAK)
        def do_something():
            return True

        # With the lock already in use, the function should not be run
        my_lock = Lock.acquire('x', kind=LOCK_KINDS.WEAK)
        self.assertIsNone(do_something())
        # And with the lock released the function should run
        my_lock.release()
        self.assertTrue(do_something())

    def test_steal_without_waiting(self):
        identifier = 'test_steal_without_waiting'

        MemcacheLock.acquire(identifier)

        time.sleep(0.1)

        lock = MemcacheLock.acquire(identifier, wait=False, steal_after_ms=10)
        self.assertIsNotNone(lock)

    def test_steal_without_waiting_too_early(self):
        identifier = 'test_steal_without_waiting_too_early'

        MemcacheLock.acquire(identifier)

        lock = MemcacheLock.acquire(identifier, wait=False, steal_after_ms=10)
        self.assertIsNone(lock)
