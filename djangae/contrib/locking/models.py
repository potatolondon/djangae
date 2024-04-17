# STANDARD LIB
from datetime import timedelta
import hashlib
import random
import time

# THRID PARTY
from django.db import models
from django.utils import timezone

try:
    from gcloudc.db import transaction
    from gcloudc.db.backends.datastore.transaction import TransactionFailedError as DatabaseError
except ImportError:
    from django.db import transaction
    from django.db import DatabaseError

from gcloudc.db.models.fields.charfields import CharField


class LockQuerySet(models.query.QuerySet):

    def acquire(self, identifier, wait=True, steal_after_ms=None, max_wait_ms=None):
        """ Create or fetch the Lock with the given `identifier`.
        `wait`:
            If True, wait until the Lock is available, otherwise if the lcok is not available then
            return None.
        `steal_after_ms`:
            If the lock is not available (already exists), then steal it if it's older than this.
            E.g. if you know that the section of code you're locking should never take more than
            3 seconds, then set this to 3000.
        `max_wait_ms`:
            Wait, but only for this long. If no lock has been acquired then returns
            None.
        """
        identifier_hash = hashlib.md5(identifier.encode()).hexdigest()

        start_time = timezone.now()

        def trans():
            """ Wrapper for the atomic transaction that handles transaction errors """
            @transaction.atomic()
            def _trans():
                lock = self.filter(identifier_hash=identifier_hash).first()
                if lock:
                    # Lock already exists, so check if it's old enough to ignore/steal
                    if (
                        steal_after_ms and
                        timezone.now() - lock.timestamp > timedelta(microseconds=steal_after_ms * 1000)
                    ):
                        # We can steal it.  Update timestamp to now and return it
                        lock.timestamp = timezone.now()
                        lock.save()
                        return lock
                else:
                    return DatastoreLock.objects.create(
                        identifier_hash=identifier_hash,
                        identifier=identifier
                    )
            try:
                return _trans()
            except DatabaseError:
                return None

        lock = trans()
        while wait and lock is None:
            # If more than max_wait_ms has elapsed, then give up
            if (max_wait_ms is not None) and (timezone.now() - start_time > timedelta(microseconds=max_wait_ms * 1000)):
                break

            time.sleep(random.uniform(0, 1))  # Sleep for a random bit between retries
            lock = trans()
        return lock


class DatastoreLock(models.Model):
    """ A marker for locking a block of code. """

    objects = LockQuerySet.as_manager()

    # To ensure that different locks are distributed evenly across the Datastore key space, we use
    # a hash of the identifier as the primary key
    identifier_hash = CharField(primary_key=True)
    identifier = CharField()
    timestamp = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.identifier

    def release(self):
        self.delete()
