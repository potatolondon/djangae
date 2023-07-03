
"""
Google provides the defer() call as a wrapper around the taskqueue API. Unfortunately
it suffers from serious bugs, and "ticking timebomb" API decisions. Specifically:

- defer(_transactional=True) won't work transactionally if your task > 100kb
- A working defer() might suddenly start blowing up inside transactions if the task grows > 100kb
  if you haven't specified xg=True, or you hit the entity group limit

This defer is an adapted version of that one, with the following changes:

- defer() will *always* use an entity group (even if the task is < 100kb) unless you pass
  _small_task=True
- defer(_transactional=True) works
- Adds a _wipe_related_caches option (defaults to True) which wipes out ForeignKey caches
  if you defer Django model instances (which can result in stale data when the deferred task
  runs)
"""

import copy
import functools
import logging
import pickle
import threading
import types
from datetime import (
    datetime,
    timedelta,
)
from urllib.parse import unquote

from django.conf import settings
from django.db import (
    connections,
    models,
    router,
    transaction as django_transaction,
)
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_str
from gcloudc.db import transaction as datastore_transaction
from google.api_core import exceptions
from google.protobuf.timestamp_pb2 import Timestamp

from djangae.environment import gae_version
from djangae.models import DeferIterationMarker
from djangae.processing import datastore_key_ranges
from djangae.utils import retry

from . import (
    CLOUD_TASKS_LOCATION_SETTING,
    cloud_tasks_project,
    get_cloud_tasks_client,
)
from .environment import task_queue_name
from .models import DeferredTask

logger = logging.getLogger(__name__)


_DEFAULT_QUEUE = "default"
_DEFAULT_URL = reverse_lazy("tasks_deferred_handler", urlconf=settings.ROOT_URLCONF)
_TASKQUEUE_HEADERS = {
    "Content-Type": "application/octet-stream"
}

# Task queue tasks have a 10 minute limit. We need to have
# some kind of guarantee for users of defer_iteration that
# they have up to X seconds for a callback to do its thing.
# We allow 30 seconds for this, and so redefer the shard
# when we get to 9.5 minutes.

_CALLBACK_TIME_LIMIT_IN_SECONDS = 30
_DEFERRED_SHARD_TIME_LIMIT_IN_SECONDS = (60 * 10) - _CALLBACK_TIME_LIMIT_IN_SECONDS


_local = threading.local()


def get_atomic(model):
    connection = router.db_for_write(model)
    engine = settings.DATABASES[connection]["ENGINE"]
    if engine == "gcloudc.db.backends.datastore":
        return datastore_transaction.atomic(xg=True)
    return django_transaction.atomic()


def get_deferred_shard_index():
    return getattr(_local, "shard_index", None)


def _set_deferred_shard_index(index):
    _local.shard_index = index


class Error(Exception):
    """Base class for exceptions in this module."""


class PermanentTaskFailure(Error):
    """Indicates that a task failed, and will never succeed."""


class SingularTaskFailure(Error):
    """Indicates that a task failed once."""


def _run_from_datastore(deferred_task_id):
    """
        Retrieves a task from the database and executes it.
    """

    def run(data):
        """
            Unpickles and executes a task.
        """
        try:
            func, args, kwds = pickle.loads(data)
        except Exception as e:
            raise PermanentTaskFailure(e)
        else:
            return func(*args, **kwds)

    entity = DeferredTask.objects.filter(pk=deferred_task_id).first()
    if not entity:
        raise PermanentTaskFailure()

    try:
        run(entity.data)
        entity.delete()
    except PermanentTaskFailure:
        entity.delete()
        raise


def invoke_member(obj, membername, *args, **kwargs):
    return getattr(obj, membername)(*args, **kwargs)


def _curry_callable(obj, *args, **kwargs):
    """
        Takes a callable and arguments and returns a task queue tuple.

        The returned tuple consists of (callable, args, kwargs), and can be pickled
        and unpickled safely.
    """

    if isinstance(obj, types.MethodType):
        return (invoke_member, (obj.__self__, obj.__func__.__name__) + args, kwargs)

    elif isinstance(obj, types.BuiltinMethodType):
        if not obj.__self__:
            return (obj, args, kwargs)
        else:
            return (invoke_member, (obj.__self__, obj.__name__) + args, kwargs)
    elif isinstance(obj, (
        types.FunctionType, types.BuiltinFunctionType, type
    )):
        return (obj, args, kwargs)
    elif hasattr(obj, "__call__"):
        return (obj, args, kwargs)
    else:
        raise ValueError("obj must be callable")


def _wipe_caches(args, kwargs):
    # Django related fields (E.g. foreign key) store a "cache" of the related
    # object when it's first accessed. These caches can drastically bloat up
    # an instance. If we then defer that instance we're pickling and unpickling a
    # load of data we likely need to reload in the task anyway. This code
    # wipes the caches of related fields if any of the args or kwargs are
    # instances.
    def _wipe_instance(instance):
        for field in (f for f in instance._meta.fields if f.remote_field):
            if field.is_cached(instance):
                field.delete_cached_value(instance)

    # We have to copy the instances before wiping the caches
    # otherwise the calling code will suddenly lose their cached things
    for i, arg in enumerate(args):
        if isinstance(arg, models.Model):
            args[i] = copy.deepcopy(arg)
            _wipe_instance(args[i])

    for k, v in list(kwargs.items()):
        if isinstance(v, models.Model):
            kwargs[k] = copy.deepcopy(v)
            _wipe_instance(kwargs[k])


def _serialize(obj, *args, **kwargs):
    curried = _curry_callable(obj, *args, **kwargs)
    return pickle.dumps(curried, protocol=pickle.HIGHEST_PROTOCOL)


def _schedule_task(
    project_id, location, queue, pickled_data,
    task_args, small_task, deferred_handler_url, task_headers
):

    client = get_cloud_tasks_client()
    deferred_task = None

    # Always use an entity group unless this has been
    # explicitly marked as a small task
    if not small_task:
        deferred_task = DeferredTask.objects.create(data=pickled_data)

    queue = queue or _DEFAULT_QUEUE
    path = client.queue_path(project_id, location, queue)

    schedule_time = task_args['eta']
    if task_args['countdown']:
        schedule_time = timezone.now() + timedelta(seconds=task_args['countdown'])

    if schedule_time:
        # If a schedule time has bee requested, we need to convert
        # to a Timestamp
        ts = Timestamp()
        ts.FromDatetime(schedule_time)
        schedule_time = ts

    task = {
        'name': (path + '/tasks/' + task_args['name']) if task_args['name'] else None,
        'schedule_time': schedule_time,
        'app_engine_http_request': {  # Specify the type of request.
            'http_method': 'POST',
            'relative_uri': deferred_handler_url,
            'body': pickled_data,
            'headers': task_headers,
            'app_engine_routing': task_args["routing"],
        }
    }

    try:
        # Defer the task
        task = client.create_task(path, task)  # FIXME: Handle transactional

        # Delete the key as it wasn't needed
        if deferred_task:
            deferred_task.delete()
    except exceptions.InvalidArgument as e:
        if "Task size too large" not in str(e):
            raise

        if small_task:
            raise

        # Replace the task body with one containing a function to run the
        # original task body which is stored in the datastore entity.
        task["body"] = _serialize(_run_from_datastore, deferred_task.pk)

        client.create_task(path, task)  # FIXME: Handle transactional
    except:  # noqa
        # Any other exception? Delete the key
        if deferred_task:
            deferred_task.delete()
        raise


def defer(obj, *args, **kwargs):
    """
        This is a reimplementation of the defer() function that shipped with Google App Engine
        before the Python 3 runtime.

        It fixes a number of bugs in that implementation, but has some subtle differences. In
        particular, the _transactional flag is not entirely atomic - deferred tasks will
        run on successful commit, but they're not *guaranteed* to run if there is an error
        submitting them.

        It also *always* uses an entity group, unless you pass _small_task=True in which
        case it *never* uses an entity group (but you are limited by 100K)

        :param _service: the GAE service to route the task to
        :type _service: str, optional
        :param _version: the GAE app version to route the task to;
            defaults to using the current GAE version
        :type _version: str, optional
        :param _instance: the GAE instance to route the task to
        :type _instance: str, optional
    """

    KWARGS = {
        "countdown", "eta", "name", "retry_options", "transactional",
        "service", "version", "instance", "using"
    }

    task_args = {x: kwargs.pop(("_%s" % x), None) for x in KWARGS}

    if task_args['retry_options']:
        raise NotImplementedError("FIXME. Implement these options")

    if "_target" in kwargs:
        raise UserWarning("'_target' parameter is no longer supported, use '_version' instead.")

    deferred_handler_url = kwargs.pop("_url", None) or unquote(force_str(_DEFAULT_URL))

    using = task_args["using"] or "default"
    connection = connections[using]

    transactional = (
        task_args["transactional"]
        if task_args["transactional"] is not None
        else connection.in_atomic_block
    )

    small_task = kwargs.pop("_small_task", False)
    wipe_related_caches = kwargs.pop("_wipe_related_caches", True)

    task_headers = dict(_TASKQUEUE_HEADERS)
    task_headers.update(kwargs.pop("_headers", {}))

    queue = kwargs.pop("_queue", _DEFAULT_QUEUE) or _DEFAULT_QUEUE

    # build the routing payload
    # default to using the current GAE version
    routing = {
        "version": task_args["version"] or gae_version(),
    }
    for key in ("service", "instance"):
        if task_args.get(key):
            routing[key] = task_args[key]

    # So we can pass through to the schedule function
    task_args["routing"] = routing

    if wipe_related_caches:
        args = list(args)
        _wipe_caches(args, kwargs)
        args = tuple(args)

    pickled = _serialize(obj, *args, **kwargs)

    project_id = cloud_tasks_project()
    assert(project_id)  # Should be checked in apps.py ready()

    location = getattr(settings, CLOUD_TASKS_LOCATION_SETTING, None)
    assert(location)  # Should be checked in apps.py

    args = (project_id, location, queue, pickled, task_args, small_task, deferred_handler_url, task_headers)

    if transactional:
        # Django connections have an on_commit message that run things on
        # post-commit.
        connection.on_commit(functools.partial(_schedule_task, *args))
    else:
        _schedule_task(*args)


class TimeoutException(Exception):
    "Exception thrown to indicate that a new shard should begin and the current one should end"
    pass


def _process_shard(marker_id, shard_number, model, query, callback, finalize, args, kwargs):
    args = args or tuple()

    # Set an index of the shard in the environment, which is useful for callbacks
    # to have access too so they can identify a task
    _set_deferred_shard_index(shard_number)

    start_time = datetime.now()

    try:
        marker = DeferIterationMarker.objects.get(pk=marker_id)
    except DeferIterationMarker.DoesNotExist:
        logger.warning("DeferIterationMarker with ID: %s has vanished, cancelling task", marker_id)
        return

    queue = task_queue_name()
    if queue:
        queue = queue.rsplit("/", 1)[-1]

    # Redefer if the task isn't ready to begin
    if not marker.is_ready:
        defer(
            _process_shard, marker_id, shard_number, model, query, callback, finalize,
            args=args,
            kwargs=kwargs,
            _queue=queue,
            _countdown=1
        )
        return

    first_iteration = True

    try:
        qs = model.objects.all()
        qs.query = query

        last_pk = None
        for instance in qs.order_by("pk"):
            last_pk = instance.pk

            shard_time = (datetime.now() - start_time).total_seconds()
            if shard_time > _DEFERRED_SHARD_TIME_LIMIT_IN_SECONDS:
                raise TimeoutException()

            callback_start = datetime.now()
            callback(instance, *args, **kwargs)
            callback_end = datetime.now()

            callback_time = (callback_end - callback_start).total_seconds()

            first_iteration = False

            if callback_time > _CALLBACK_TIME_LIMIT_IN_SECONDS:
                logging.warning(
                    "Detected slow callback function (>%ss) during iteration, this could result in failed tasks",
                    callback_time
                )
        else:
            @get_atomic(model)
            def mark_shard_complete():
                try:
                    marker.refresh_from_db()
                except DeferIterationMarker.DoesNotExist:
                    logger.warning(
                        "TaskMarker with ID: %s has vanished, cancelling task",
                        marker_id
                    )
                    return

                marker.shards_complete += 1
                marker.save()

                if marker.shards_complete == marker.shard_count:
                    # Delete the marker if we were asked to
                    if marker.delete_on_completion:
                        marker.delete()

                    defer(
                        finalize,
                        *args,
                        _transactional=True,
                        _queue=queue,
                        **kwargs
                    )
            retry(mark_shard_complete, _attempts=6)

    except (Exception, TimeoutException) as e:
        # If we get any kind of exception, we want to redefer from where we got to, and we'll keep doing
        # that until the developer deploys a fix.
        if isinstance(e, TimeoutException):
            logger.debug(
                "Ran out of time processing shard. Deferring new shard to continue from: %s",
                last_pk
            )
        else:
            logger.exception("Error processing shard. Retrying.")

            if first_iteration:
                # If this is the first iteration, we just re-raise to show that this
                # is an error-case. We can't do that if it's not the first iteration
                # because that would mean retrying the previous instances again
                raise

        if last_pk:
            qs = qs.filter(pk__gte=last_pk)

        defer(
            _process_shard, marker_id, shard_number, qs.model, qs.query, callback, finalize,
            args=args,
            kwargs=kwargs,
            _queue=queue,
            _countdown=1
        )
    finally:
        _set_deferred_shard_index(None)


def _generate_shards(
    model, query, callback, finalize, args, kwargs, shards, delete_marker, key_ranges_getter
):

    queryset = model.objects.all()
    queryset.query = query

    key_ranges = key_ranges_getter(queryset, shards)

    marker = DeferIterationMarker.objects.create(
        delete_on_completion=delete_marker,
        callback_name=callback.__name__,
        finalize_name=finalize.__name__
    )

    queue = task_queue_name()
    if queue:
        queue = queue.rsplit("/", 1)[-1]

    for i, (start, end) in enumerate(key_ranges):
        is_last = i == (len(key_ranges) - 1)
        shard_number = i

        qs = model.objects.all()
        qs.query = query

        filter_kwargs = {}
        if start:
            filter_kwargs["pk__gte"] = start

        if end:
            filter_kwargs["pk__lt"] = end

        qs = qs.filter(**filter_kwargs)

        @get_atomic(model)
        def make_shard():
            marker.refresh_from_db()
            marker.shard_count += 1
            if is_last:
                marker.is_ready = True
            marker.save()

            defer(
                _process_shard,
                marker.pk,
                shard_number,
                qs.model, qs.query, callback, finalize,
                args=args,
                kwargs=kwargs,
                _queue=queue,
                _transactional=True
            )

        try:
            retry(make_shard, _attempts=5)
        except:  # noqa
            marker.delete()  # This will cause outstanding tasks to abort
            raise


def defer_iteration_with_finalize(
        queryset, callback, finalize, key_ranges_getter=datastore_key_ranges, _queue='default', _shards=5,
        _delete_marker=True, _transactional=False, *args, **kwargs):

    defer(
        _generate_shards,
        queryset.model,
        queryset.query,
        callback,
        finalize,
        args=args,
        kwargs=kwargs,
        delete_marker=_delete_marker,
        key_ranges_getter=key_ranges_getter,
        shards=_shards,
        _queue=_queue,
        _transactional=_transactional
    )
