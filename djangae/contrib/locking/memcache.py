import logging
import random
import time
from datetime import datetime

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
from django.core.cache.backends.db import BaseDatabaseCache
from django.core.cache.backends.memcached import BaseMemcachedCache

try:
    from redis_cache.backends.base import BaseRedisCache
except ImportError:
    class BaseRedisCache:
        pass


logger = logging.getLogger(__name__)


class MemcacheLock(object):
    def __init__(self, identifier, unique_value):
        self.identifier = identifier
        self.unique_value = unique_value

    @classmethod
    def acquire(cls, identifier, wait=True, steal_after_ms=None):
        cache = _get_cache()
        unique_value = f'{random.randint(1, 100000)}|{datetime.utcnow().isoformat()}'

        while True:
            # Note that django-redis-cache's get_or_set implementation does not exactly follow the Django spec:
            # https://github.com/sebleier/django-redis-cache/issues/127
            # So we'll always use Django's base cache implemenation which will make the underlying `get` and `add`
            # calls to the actual cache backend.
            # If caller does't specify steal_after_ms, then the lock value will be cached indefinitely until released.
            timeout = steal_after_ms / 1000 if steal_after_ms else None
            cached_value = BaseCache.get_or_set(cache, identifier, unique_value, timeout=timeout)
            acquired = cached_value == unique_value
            if acquired:
                return cls(identifier, unique_value)
            else:
                locked_at = datetime.fromisoformat(cached_value.split('|')[1])
                if steal_after_ms and (datetime.utcnow() - locked_at).total_seconds() * 1000 > steal_after_ms:
                    # Steal anyway
                    cache.set(identifier, unique_value)
                    return cls(identifier, unique_value)

                if not wait:
                    return None

                # We are waiting for the lock
                time.sleep(0)

    def release(self):
        cache = _get_cache()
        # Delete the key if it was ours. There is a race condition here
        # if something steals the lock between the if and the delete...
        if cache.get(self.identifier) == self.unique_value:
            cache.delete(self.identifier)


def _get_cache():
    cache_name = getattr(settings, "DJANGAE_LOCKING_CACHE_NAME", "default")
    cache = caches[cache_name]
    if not getattr(_get_cache, "_checked", False):  # Avoid endless spam on every access
        # This check is inherently uncertain, but it's about as good as we can get
        if not isinstance(cache, (BaseDatabaseCache, BaseMemcachedCache, BaseRedisCache)):
            logger.warning(
                "You are using a djangae.contrib.locking weak lock with a non-global cache "
                "backend. This means it cannot prevent simultaneous code execution across App "
                "Engine instances. Change your default cache or set DJANGAE_LOCKING_CACHE_NAME to "
                "a global cache to fix this."
            )
        _get_cache._checked = True
    return cache
