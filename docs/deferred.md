# djangae.tasks

The djangae.tasks app provides functionality for working with Google Cloud Tasks from your Django application.

The main functionality it provides is the ability to "defer" a function to be run later by Cloud Tasks. It
also provides a number of helper methods that leverage that ability.

## Google Cloud Tasks Emulator

When developing locally, it is recommended you make use of the [GCloud Tasks Emulator](https://gitlab.com/potato-oss/google-cloud/gcloud-tasks-emulator)
project that simulates the Cloud Task API locally.

Djangae's sandbox.py provides functionality to start/stop the emulator for you, and djangae.tasks integrates with the emulator when it's running.

## Queue Initialisation

In the Python 2 App Engine runtime - a file named queue.yaml was used to define new task queues. When App Engine tasks were migrated to Cloud Tasks, queue.yaml
was effectively deprecated (or at least introduces conflicts with the wider Cloud Tasks configuration).

It is however useful to be able to create or update queues from a configuration setting in your project. `djangae.tasks` provides the `CLOUD_TASKS_QUEUES` setting to do this.

`CLOUD_TASKS_QUEUES` is a list of dictionaries to create or update task queues. On app initialisation the queues are checked to see if they exist or need updating
and the configuration changes are applied.

Here is an example configuration:

```
[
   {
      "name": "default",
      "rate_per_second": "1",  # The tasks per second
      "rate_max_concurrent": 10,  # The maximium number of concurrent tasks to run
      "retry_max_attempts": 3,  # -1 indicates retry forever (recommended)
   }
]
```

> Note! There are many more options for queue configuration that can be configured via API, but only these are supported via the `CLOUD_TASKS_QUEUES` setting.


## djangae.tasks.deferred.defer

This allows you to take any function along with the arguments to be passed to it, and defer the function call to be run in the background by Google Cloud Tasks.

A similar function exists in the old Python 2.x version of the App Engine SDK.
Djangae's version brings this functionality to the Python 3 App Engine environment, and also fixes a number of issues with the original App Engine implementation.


```defer(function, *args, **kwargs)```

You can optionally pass any of the following kwargs, which are used to control the behaviour, and are not passed to the function call:

* `_queue` - Name of the Cloud Tasks queue on which to run the task.
* `_eta` - A `datetime` object specifying when you want the task to run.
* `_countdown` - Number of seconds by which to delay execution of the task. Overrides `_eta`.
* `_name` - A name for the Cloud Tasks task. Can be used to avoid repeated execution of the same task.
* `_service` - Name of the App Engine service on which to run the task.
* `_version` - Name of the version of the App Engine service on which to run the task.
* `_instance` - Name of the App Engine instance on which to run the task.
* `_transactional` - Boolean, which if True delays the deferring of the task until after the current database transaction has successfully committed. Defaults to False, unless called from within an atomic block, in which case it's forced to True.
* `_using` - Name of the Django database connection to which `_transactional` relates. Defaults to "default".
* `_small_task` - If you know that the task payload will be less than 100KB, then you can set this to True and a Datastore entity will not be used to store the task payload.
* `_wipe_related_caches` - By default, if a Django instance is passed as an argument to the called function, then the foreign key caches are wiped before
   deferring to avoid bloating and stale data when the task runs. Set this to False to disable this functionality.
* `_retry_options` - Not yet implemented.

Usage notes:

 - It is good practice to not pass Django model instances as arguments for the function, as if you do, when the function runs it will get the model instance as it was when the function was deferred, which may be different to how that instance is in the database when the function _runs_, especially if the task gets retried due to an error, or if the `_countdown` or `_eta` was specified. It's better to pass the PK of the instance and reload it inside the function.
 - Transactional tasks do not *guarantee* that the task will run. It's possible (but unlikely) for the transaction to complete
   successfully, but the queuing of the task to fail. It is not possible for the transaction to fail and the task to queue however.

## djange.tasks.deferred.defer_iteration_with_finalize

`defer_iteration_with_finalize(queryset, callback, finalize, _queue='default', _shards=5, _delete_marker=True, _transactional=False, *args, **kwargs)`

This function provides similar functionality to a Mapreduce pipeline, but it's entirely self-contained and leverages
defer to process the tasks.

The function iterates the passed Queryset in shards, calling `callback` on each instance. Once all shards complete then
the `finalize` callback is called. If a shard runs for 9.5 minutes, or it hits an unhandled exception it re-defers another shard to continue processing. This
avoids hitting the 10 minute deadline for background tasks.

This means that callbacks should complete **within a maximum of 30 seconds**. Callbacks that take longer than this could cause the iteration to fail,
or, more likely, repeatedly retry running the callback on the same instances.

If additional `*args` and/or `**kwargs` are specified, these are passed to both `callback` (after the instance) and `finalize`.

`_shards` is the number of shards to use for processing. If `_delete_marker` is `True` then the Datastore entity that
tracks complete shards is deleted. If you want to keep these (as a log of sorts) then set this to `False`.

`_transactional` and `_queue` work in the same way as `defer()`

### Identifying a task shard

From a shard callback, you can identify the current shard by using the `get_deferred_shard_index()` function:

```
from djangae.deferred import get_deferred_shard_index
shard_index = get_deferred_shard_index()
```

This can be useful when doing things like updating sharded counters.
