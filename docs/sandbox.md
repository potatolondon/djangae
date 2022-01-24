# Local/remote management commands

If you set your manage.py up as described [in Installation](installation.md), Djangae will allow you to run management commands locally or remotely.

## Running Commands Locally

Django management commands run as normal, e.g.


    ./manage.py shell


## Local Server Port Configuration

When you call `runserver` the following ports are used by default:

 - The default module (the main webserver) runs on port 8000
 - Datastore emulator runs on port 10901
 - Cloud Tasks emulator runs on port 10908
 - Cloud Storage emulator runs on port 10911

Ports for the Google Cloud service emulators (Datastore, Cloud Tasks, Cloud Storage) will be
automatically incremented if the default ports (listed above) aren't available.
The ports can be overridden by passing `datastore_port`, `tasks_port` and `storage_port` (respectively)
to the `start_emulators` function in `manage.py`.


## Running Commands Remotely

!!! important "This feature has not yet been implemented in the Python 3 version of Djangae"
    The removal of the built-in `remote_api` feature on the Python 3 runtime means that this feature needs to be rearchitected.

Djangae also lets you run management commands which connect remotely to the Datastore of your deployed App Engine application.  To do this you need to:

Add the `remote_api` built-in to app.yaml, and deploy that change.

    builtins:
      - remote_api: on

You also need to ensure that the `application` in app.yaml is set to the application which you wish to connect to.

Then run your management command specifying the `remote` sandbox.

    ./manage.py --sandbox=remote shell

This will use your **local** Python code, but all database operations will be performed on the remote Datastore.

Additionally, you can specify the application to run commands against by providing an `--app_id`. Eg

    ./manage.py --sandbox=remote --app_id=myapp shell  # Starts a remote shell with the "myapp" instance


### Deferring Tasks Remotely

!!! important "This feature has not yet been implemented in the Python 3 version of Djangae"
    The removal of the built-in `remote_api` feature on the Python 3 runtime means that this feature needs to be rearchitected.

App Engine tasks are stored in the Datastore, so when you are in the remote shell any tasks that you defer will run on the live application, not locally.  For example:

    ./manage.py --sandbox=remote shell
    >>> from my_code import my_function
    >>> from djangae.tasks.deferred import defer
    >>> defer(my_function, arg1, arg2, _queue="queue_name")


# Testing

Along with the local/remote sandboxes, Djangae ships with a test sandbox. This should be called explicitly
from your manage.py when tests are being run. This sandbox sets up the bare minimum to use the Datastore
connector (the memcache and Datastore stubs only). This prevents accesses to the Datastore from throwing an error
when you do so outside a test case (e.g. from `settings.py`).

Your tests should setup and teardown a full testbed instance (see `DjangaeDiscoverRunner` and the nose plugin).
