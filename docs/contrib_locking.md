# djangae.contrib.locking

This app provides functionality for locking functions or blocks of code to prevent multiple
simultaneous threads from executing them at the same time.  On App Engine where simultaneous
threads can be running on different instances, Python's normal threading locks cannot provide
this functionality.

## Setup

If you're using the `STRONG` lock kind (which is the default), then you will want to add the
app to `INSTALLED_APPS`, and add the `cleanup-locks` URL to your URL config and call it
periodically on a cron.

```
# settings.py
INSTALLED_APPS = (
    ...
    'djangae.contrib.locking',
)

# Your ROOT_URLCONF file
from djangae.contrib.locking.urls import urlpatterns as locking_urls
urlpatterns += locking_urls

# Your cron.yaml file
cron:
- description: Cleanup locks
  url: /djangae-cleanup-locks/
  schedule: every 1 days
```


## Usage

The main utility is the `lock` object, which can be used as a function decorator or context manager.

### `lock(identifier, wait=True, steal_after_ms=None, kind=LOCK_KINDS.STRONG)`

* `identifier` - a string which uniquely identifies the block of code that you want to lock.
* `wait` - whether to wait if another thread has already got a lock with the same identifier, or to bail.
    - In the function decorator case, bailing means that the function will not be run.
    - In the context manager case, bailing means that `LockAcquisitionError` will be raised when
    entering `with`.
* `steal_after_ms` - if passed, then any existing lock which is older than this value will be ignored.
* `wait_for_ms` - if passed, this is the max time to wait before giving up getting the lock
* `kind` - which kind of lock implementation to use.
    - LOCK_KINDS.WEAK is not guaranteed to be robust, but can be used for situations where avoiding
      simultaneous code execution is preferable but not critical (uses memcache).
    - LOCK_KINDS.STRONG is for where prevention of simultaneous code execution is *required* (uses the datastore).


### Usage Examples

Locking a function

```
from djangae.contrib.locking import lock, LOCK_KINDS, LockAcquisitionError


@lock('my_lock')
def refresh_user_oauth_token(user):
    """ This function refreshes a user's oauth token (thereby invalidating old one) and then
        saves the new token onto the user object.  If multiple threads run this at the same
        time then we unecessarily hammer the external API and one thread potentially invalidates
        the token which was just fetched by another thread.  @lock to the rescue!
    """
    user.refresh_from_db()
    if token_is_expired(user):
	    new_token = get_new_token_from_external_api(user)
	    update_user(user, new_token)
```

Locking a block of code using the context manager

```
with lock('my_other_lock'):
    do_something_which_should_not_be_run_many_times_at_once()
```

Bailing if another thread is already holding the lock (decorator)

```
@lock('my_lock', wait=False):
def my_function():
    # This will not be called if another thread is already holding the lock
```

Bailing if another thread is already holding the lock (context manager)

```
try:
    with lock('my_lock', wait=False):
        # This will not be run if another thread is already holding the lock
except LockAcquisitionError:
    pass
```

## Lower Level Interface

If you want to be able to acquire and release the locks manually, then you can use the lower-level
`Lock` class directly.

* `Lock.acquire(identifier, wait=True, steal_after_ms=None, kind=LOCK_KINDS.STRONG)`
    - Class method which returns a `Lock` object or if `wait=False` and another thread has the
      lock, returns `None`.
    - Keyword arguments are the same as for `lock`.
* `Lock().release()`
    - Instance method which releases the lock.


### Usage example

```
from djangae.contrib.locking import Lock

lock = Lock.acquire('my_lock')
do_something_which_should_not_be_run_many_times_at_once()
lock.release()
```
